PY ?= python3

install:
	$(PY) -m pip install -e ".[dev]"

test:
	$(PY) -m pytest -q

# Record today's prices for the standard basket (schedule this daily)
track:
	$(PY) -m cartcompass track

# macOS: run `track` every day (launchd). `make unschedule` removes it.
schedule:
	sh scripts/schedule_mac.sh

unschedule:
	sh scripts/schedule_mac.sh remove

# Showcase site data (findings from your price history + the package for the browser demo)
site:
	$(PY) -m cartcompass site
