import base64
import json

import pytest

from cartcompass.receipts import ReceiptError, TOOL, api_key, load_image, parse_response, read_receipt

# A tiny valid PNG standing in for a receipt photo.
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")

WALMART = {
    "store": "Walmart", "address": "131 W Gypsy Lane Rd", "zip": "43402", "date": "2026-11-18",
    "items": [
        {"raw": "GV 2% MLK GAL 007874235187 F 2.98 N", "name": "Great Value 2% Reduced Fat Milk",
         "brand": "Great Value", "size": "1 gal", "quantity": 1, "price": 2.98},
        {"raw": "GV LG WHT EGG 18CT F 3.47 N", "name": "Great Value Large White Eggs",
         "brand": "Great Value", "size": "18 ct", "quantity": 1, "price": 3.47},
        {"raw": "BANANAS 2.31 lb @ 0.50 /lb 1.16 N", "name": "Bananas", "quantity": 2.31,
         "sold_by_weight": True, "price": 1.16},
        {"raw": "GV WHT BRD 2 @ 1.42 2.84", "name": "Great Value White Bread", "brand": "Great Value",
         "size": "20 oz", "quantity": 2, "price": 2.84},
    ],
    "subtotal": 10.45,
}


def reply(x):
    return {"content": [{"type": "tool_use", "name": "record_receipt", "input": x}]}


def test_parse_and_check():
    r = parse_response(reply(WALMART), "m")
    assert r.store == "Walmart" and r.zip == "43402" and len(r.items) == 4
    assert r.adds_up is True and r.checks == []
    bread = r.items[3]
    assert bread.each == 1.42                      # 2 loaves for $2.84
    assert r.items[2].each == 0.5                  # bananas, per pound


def test_misread_totals_are_flagged():
    bad = dict(WALMART, subtotal=12.45)
    r = parse_response(reply(bad))
    assert r.adds_up is False and "some lines may be misread" in r.checks[0]


def test_guesses_are_flagged():
    x = dict(WALMART, items=WALMART["items"] + [{"raw": "MRKT SD XX 1.00", "name": "unknown", "price": 1.0,
                                                  "confident": False}], subtotal=None)
    r = parse_response(reply(x))
    assert r.adds_up is None and "decoded as a guess: MRKT SD XX 1.00" in r.checks[0]


def test_not_a_receipt():
    with pytest.raises(ReceiptError, match="is the photo a receipt"):
        parse_response({"content": [{"type": "text", "text": "I can't see a receipt."}]})


def test_bad_lines_are_skipped_not_fatal():
    x = dict(WALMART, items=[{"raw": "?", "name": "?"}, WALMART["items"][0]], subtotal=None)
    assert len(parse_response(reply(x)).items) == 1


def test_request_shape(tmp_path):
    img = tmp_path / "r.png"
    img.write_bytes(PNG)
    seen = {}

    def transport(url, headers, body):
        seen.update(url=url, headers=headers, body=json.loads(body))
        return 200, reply(WALMART)

    r = read_receipt(img, key="sk-test", transport=transport)
    assert r.store == "Walmart"
    b = seen["body"]
    assert seen["headers"]["x-api-key"] == "sk-test"
    assert b["tool_choice"] == {"type": "tool", "name": TOOL["name"]}
    content = b["messages"][0]["content"]
    assert content[0]["source"]["media_type"] == "image/png"
    assert base64.b64decode(content[0]["source"]["data"]) == PNG


def test_api_errors_are_explained(tmp_path):
    img = tmp_path / "r.png"
    img.write_bytes(PNG)
    with pytest.raises(ReceiptError, match="HTTP 401.*invalid x-api-key"):
        read_receipt(img, key="k", transport=lambda *a: (401, {"error": {"message": "invalid x-api-key"}}))


def test_heic_needs_macos(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    f = tmp_path / "IMG_1234.HEIC"
    f.write_bytes(b"not really heic")
    with pytest.raises(ReceiptError, match="HEIC"):
        load_image(f)


def test_api_key_from_file(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    f = tmp_path / "k.env"
    f.write_text("KROGER_CLIENT_ID=x\nANTHROPIC_API_KEY=sk-ant-123\n")
    assert api_key(f) == "sk-ant-123"
    with pytest.raises(ReceiptError):
        api_key(tmp_path / "none.env")


def test_saved_receipts_join_nearby_comparisons():
    from datetime import date
    from cartcompass import history
    from cartcompass.compare import rank
    from cartcompass.receipts import nearby, save
    db = history.connect(":memory:")
    r = parse_response(reply(WALMART))
    n = save(db, r, where=(41.389, -83.656))
    assert n == 4
    stores, offers = nearby(db, home=(41.38, -83.65), radius_miles=10, today=date(2026, 11, 19))
    (sid,) = stores
    assert sid.startswith("receipt:walmart:43402") and stores[sid].label.startswith("Walmart")
    milk = next(o for o in offers if "Milk" in o.description)
    assert (milk.unit_price, milk.unit, milk.amount) == (2.98, "gal", 1.0)
    choices, _, _ = rank(offers, "milk")
    assert choices[0].variant.label() == "2% milk (store brand)"   # Great Value is a store brand
    bread = next(o for o in offers if "Bread" in o.description)
    assert bread.price == 1.42                                       # one loaf, not the two-loaf line


def test_far_or_old_receipts_are_left_out():
    from datetime import date
    from cartcompass import history
    from cartcompass.receipts import nearby, save
    db = history.connect(":memory:")
    save(db, parse_response(reply(WALMART)), where=(41.389, -83.656))
    assert nearby(db, (39.96, -82.99), 25)[0] == {}                               # Columbus is too far
    assert nearby(db, (41.38, -83.65), 10, today=date(2027, 3, 1))[1] == []       # prices too old

