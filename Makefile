PY ?= python3

install:
	$(PY) -m pip install -e ".[dev]"

test:
	$(PY) -m pytest -q

# Record today's prices for the standard basket (schedule this daily)
track:
	$(PY) -m cartcompass track
