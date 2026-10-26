"""Polite HTTP: retries with exponential backoff, per-host pacing, and a timestamped raw cache.

Every response that feeds the analysis is saved under data/raw/<source>/ inside an envelope
recording the URL, parameters and pull time, so any number can be traced back to a pull.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from plumbing.config import RAW, USER_AGENT

# Minimum seconds between requests to the same host. Public endpoints document limits loosely, so
# these stay well under them (e.g. Solana's public RPC allows about 100 requests per 10 s).
DEFAULT_PACING = {
    "api.mainnet-beta.solana.com": 0.35,
    "api.trongrid.io": 0.4,
    "s1.ripple.com": 0.25,
    "s2.ripple.com": 0.25,
    "xrplcluster.com": 0.25,
    "api.wise.com": 1.0,
    "www.bitstamp.net": 0.5,
    "api.coingecko.com": 6.0,
}
FALLBACK_PACING = 0.2


def utcnow() -> datetime:
    return datetime.now(UTC)


def stamp(ts: datetime | None = None) -> str:
    return (ts or utcnow()).strftime("%Y%m%dT%H%M%SZ")


def make_session(retries: int = 5, backoff: float = 1.0) -> requests.Session:
    retry = Retry(
        total=retries,
        backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
        respect_retry_after_header=True,
    )
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


@dataclass
class Client:
    """A requests session that waits between calls to the same host."""

    session: requests.Session = field(default_factory=make_session)
    pacing: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_PACING))
    timeout: float = 30.0
    _last: dict[str, float] = field(default_factory=dict)

    def _wait(self, url: str) -> None:
        host = urlparse(url).netloc
        gap = self.pacing.get(host, FALLBACK_PACING)
        elapsed = time.monotonic() - self._last.get(host, 0.0)
        if elapsed < gap:
            time.sleep(gap - elapsed)
        self._last[host] = time.monotonic()

    def get(self, url: str, params: dict[str, Any] | None = None) -> requests.Response:
        self._wait(url)
        resp = self.session.get(url, params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp

    def post_json(self, url: str, body: Any) -> Any:
        self._wait(url)
        resp = self.session.post(url, json=body, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        return self.get(url, params).json()


def envelope(source: str, url: str, payload: Any, params: Any = None, pulled_at: datetime | None = None) -> dict:
    return {
        "source": source,
        "url": url,
        "params": params,
        "pulled_at": (pulled_at or utcnow()).isoformat(),
        "payload": payload,
    }


def save_json(path: Path, obj: Any) -> Path:
    """Write gzipped JSON atomically (write to a temp file, then rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump(obj, fh, separators=(",", ":"))
    tmp.replace(path)
    return path


def load_json(path: Path) -> Any:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def append_jsonl(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(obj, separators=(",", ":")) + "\n")


def iter_jsonl(path: Path) -> Iterator[Any]:
    """Yield records, skipping a torn final line from an interrupted write."""
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_manifest(root: Path = RAW) -> Path:
    """Record every raw file's size and SHA-256 so a later refresh can be compared with this one."""
    rows = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.name not in {"MANIFEST.csv", "README.md"} and not p.name.endswith(".tmp"):
            rows.append({
                "path": p.relative_to(root).as_posix(),
                "bytes": p.stat().st_size,
                "modified_utc": datetime.fromtimestamp(p.stat().st_mtime, UTC).isoformat(timespec="seconds"),
                "sha256": sha256(p),
            })
    out = root / "MANIFEST.csv"
    with out.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["path", "bytes", "modified_utc", "sha256"])
        writer.writeheader()
        writer.writerows(rows)
    return out
