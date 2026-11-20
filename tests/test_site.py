import json
import zipfile
from datetime import date

from cartcompass import history
from cartcompass.kroger import Store
from cartcompass.offers import from_product
from cartcompass.site import build
from fake_kroger import product


def test_site_findings_and_package(tmp_path):
    db_path = tmp_path / "p.sqlite"
    db = history.connect(db_path)
    day = date(2026, 11, 19)
    rows = {"A": [("Kroger® Vitamin D Whole Milk Gallon", "1 gal", 2.29),
                  ("Kroger® Vitamin D Whole Milk Half Gallon", "1/2 gal", 1.69)],
            "B": [("Kroger® Vitamin D Whole Milk Gallon", "1 gal", 3.09)]}
    for store, items in rows.items():
        history.record(db, [o for d, sz, p in items for o in from_product(store, product(d, d, sz, p))], day)
    history.record_stores(db, [Store("A", "KROGER", "Kroger Marketplace - Perrysburg Marketplace", "", "Perrysburg", "", 41.5, -83.6),
                               Store("B", "KROGER", "Kroger - Waterville", "", "Waterville", "", 41.5, -83.7)])
    d = build(db_path, tmp_path / "docs", items=["milk", "eggs"])
    (f,) = d["findings"]                       # no eggs tracked: no finding, no crash
    assert f["kind"] == "whole milk (store brand)"
    assert [s["store"] for s in f["stores"]] == ["Kroger Marketplace Perrysburg", "Kroger Waterville"]
    assert f["spread"] == round(3.09 / 2.29 - 1, 4)
    assert f["trap"]["small"] == {"size": "1/2 gal", "price": 1.69, "unit_price": 3.38}
    js = (tmp_path / "docs" / "findings.js").read_text()
    assert json.loads(js[len("window.FINDINGS = "):].rstrip().rstrip(";"))["day"] == "2026-11-19"
    names = zipfile.ZipFile(tmp_path / "docs" / "cartcompass.zip").namelist()
    assert "cartcompass/units.py" in names and "cartcompass/receipt_ocr.py" in names
