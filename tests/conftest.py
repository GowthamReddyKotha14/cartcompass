import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))

import pytest


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    """Commands write data/prices.sqlite by default; keep that out of the repo."""
    monkeypatch.chdir(tmp_path)
