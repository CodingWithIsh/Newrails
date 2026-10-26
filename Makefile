# Numbers Behind the Money, project 2. `make all` rebuilds every result from the committed cache, offline.
PY ?= .venv/bin/python
PIP ?= .venv/bin/pip

.PHONY: setup test lint all results notebook refresh collect live clean

setup:            ## create .venv and install pinned dependencies
	python3 -m venv .venv
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.lock
	$(PIP) install -e . --no-deps
	$(PY) -m ipykernel install --sys-prefix --name plumbing --display-name "plumbing (.venv)"

test:             ## offline tests with coverage
	$(PY) -m pytest --cov=plumbing --cov-report=term-missing --cov-fail-under=85

lint:
	$(PY) -m ruff check src tests
	$(PY) -m mypy src

results:          ## results/*.csv and results/figures/*.png from data/cache
	$(PY) -m plumbing run --all

notebook:         ## execute the analysis notebook in place
	cd notebooks && ../$(PY) -m nbconvert --to notebook --execute --inplace \
		--ExecutePreprocessor.kernel_name=plumbing --ExecutePreprocessor.timeout=900 analysis.ipynb

all: lint test results notebook

refresh:          ## re-pull every source (network, ~20 minutes), then rebuild
	$(PY) -m plumbing run --all --refresh

collect:          ## poll ramp order books and Wise quotes for 72 hours (network)
	$(PY) -m plumbing collect --hours 72

live:             ## record XRPL/Solana/Tron timing for 2 hours (network)
	$(PY) -m plumbing live --minutes 120

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov
