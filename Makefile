PY ?= python3

install:
	$(PY) -m pip install -e ".[dev]"

test:
	$(PY) -m pytest -q
