from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures() -> Path:
    return FIXTURES


class FakeClient:
    """Stands in for plumbing.net.Client: answers from a dict of url -> payload (or exception)."""

    def __init__(self, routes: dict, default=None):
        self.routes = routes
        self.default = default
        self.calls: list[tuple[str, object]] = []

    def _answer(self, key):
        ans = self.routes.get(key, self.default)
        if isinstance(ans, Exception):
            raise ans
        if callable(ans):
            return ans()
        return ans

    def get_json(self, url, params=None):
        self.calls.append((url, params))
        return self._answer(url)

    def post_json(self, url, body):
        self.calls.append((url, body))
        method = body.get("method") if isinstance(body, dict) else None
        return self._answer((url, method)) if (url, method) in self.routes else self._answer(url)
