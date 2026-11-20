import pytest

from cartcompass.receipt_ocr import decode_name, parse_text, read_receipt_free, rows_from_boxes
from cartcompass.receipts import ReceiptError

# What OCR returns for a typical Walmart receipt (shortened), line by line.
WALMART_TEXT = """\
Walmart
Save money. Live better.
( 419 ) 555 - 0100
131 W GYPSY LANE RD
BOWLING GREEN OH 43402
ST# 01234 OP# 00009 TE# 09 TR# 01234
GV 2% MLK GAL 007874235187 F 2.98 N
GV LG WHT EGG 18CT 060538818718 F 3.47 N
BANANAS 000000004011 F 1.16 N
2.31 lb @ 0.50 /lb
GV WHT BRD 20OZ 007874206301 2 @ 1.42 2.84 N
MRKT SD BKRY ITM 002139400000 F 4.98 N
SUBTOTAL 15.43
TAX 1 7.250 % 0.00
TOTAL 15.43
VISA TEND 15.43
CHANGE DUE 0.00
11/18/26 19:42:07
""".splitlines()


def test_walmart_receipt():
    r = parse_text(WALMART_TEXT)
    assert (r.store, r.zip, r.date, r.address) == ("Walmart", "43402", "2026-11-18", "131 W GYPSY LANE RD")
    assert [i.price for i in r.items] == [2.98, 3.47, 1.16, 2.84, 4.98]
    milk, eggs, bananas, bread, bakery = r.items
    assert (milk.name, milk.brand, milk.size) == ("Great Value 2% milk", "Great Value", "1 gal")
    assert (eggs.name, eggs.size) == ("Great Value large white eggs", "18 ct")
    assert bananas.sold_by_weight and bananas.quantity == 2.31 and bananas.each == 0.5
    assert (bread.quantity, bread.each, bread.size) == (2, 1.42, "20 oz")
    assert r.adds_up is True
    assert not bakery.confident and "partly decoded" in r.checks[0]


def test_totals_tax_and_payment_are_not_items():
    names = " ".join(i.raw for i in parse_text(WALMART_TEXT).items)
    for word in ("SUBTOTAL", "TOTAL", "TAX", "VISA", "CHANGE"):
        assert word not in names


def test_misread_price_is_caught_by_the_subtotal():
    text = [l.replace("3.47", "8.47") for l in WALMART_TEXT]
    r = parse_text(text)
    assert r.adds_up is False and "some lines may be misread" in r.checks[0]


@pytest.mark.parametrize("body,name,size", [
    ("GV 2% MLK GAL", "Great Value 2% milk", "1 gal"),
    ("KRO WHL MLK 1/2 GAL", "Kroger whole milk", "1/2 gal"),
    ("FF 2% MILK HGAL", "Friendly Farms 2% milk", "1/2 gal"),
    ("CHKN BRST BNLS SKNLS", "chicken breast boneless skinless", ""),
    ("BTR UNSLT 16OZ", "butter unsalted", "16 oz"),
    ("ORG LG BRN EGG 12CT", "organic large brown eggs", "12 ct"),
])
def test_decode(body, name, size):
    got_name, _, got_size, sure = decode_name(body)
    assert (got_name, got_size, sure) == (name, size, True)


def test_rows_from_boxes_joins_name_and_price():
    boxes = [("2.98 N", 0.80, 0.700, 0.02), ("GV 2% MLK GAL", 0.05, 0.701, 0.02),
             ("3.47 N", 0.80, 0.670, 0.02), ("GV LG WHT EGG 18CT", 0.05, 0.672, 0.02)]
    assert rows_from_boxes(boxes) == ["GV 2% MLK GAL 2.98 N", "GV LG WHT EGG 18CT 3.47 N"]


def test_aldi_style_lines():
    r = parse_text(["ALDI", "1001 N MAIN ST", "BOWLING GREEN, OH 43402",
                    "123456 FF 2% MILK GAL 2.89 FS", "234567 GOLDHEN LG EGGS 12CT 1.94 FS",
                    "SUBTOTAL 4.83", "11/19/2026"])
    assert r.store == "ALDI" and r.date == "2026-11-19" and r.adds_up
    assert r.items[0].name == "Friendly Farms 2% milk"


def test_no_engine_gives_a_clear_fix(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    img = tmp_path / "r.jpg"
    img.write_bytes(b"x")
    with pytest.raises(ReceiptError, match="pyobjc-framework-Vision"):
        read_receipt_free(img)


# Real Tesseract output for a rendered Walmart receipt image, misreads included.
TESSERACT_OUTPUT = """\
Walmart
131 W GYPSY LANE RD
BOWLING GREEN OH 43402
GV 2% MLK GAL 007874235187 F 2.98 N
GV LG WHT EGG 18CT 060538818718 F 3.47 N
BANANAS 800000004011 F 1.16 N

2.31 lb @ 0.50 /1b
GV WHT BRD 200Z 007874206301 2 @ 1.42 2.84 N
SUBTOTAL 10.45
11/18/26 19:42:07
""".splitlines()


def test_common_ocr_misreads_are_repaired():
    r = parse_text(TESSERACT_OUTPUT)
    bananas, bread = r.items[2], r.items[3]
    assert bananas.sold_by_weight and bananas.each == 0.5          # "/1b" read as "/lb"
    assert (bread.name, bread.size, bread.confident) == ("Great Value white bread", "20 oz", True)  # "200Z"
    assert r.adds_up is True


def test_clean_ocr_leaves_real_numbers_alone():
    from cartcompass.receipt_ocr import clean_ocr
    assert clean_ocr("TAX 1 7.250 % 0.00") == "TAX 1 7.250 % 0.00"
    assert clean_ocr("GV 2% MLK GAL 2,98 N") == "GV 2% MLK GAL 2.98 N"


def test_auto_engine_is_free_without_a_key(monkeypatch, tmp_path):
    from cartcompass import receipts
    from cartcompass.__main__ import pick_reader
    from cartcompass.receipt_ocr import read_receipt_free
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(receipts, "ENV_FILE", tmp_path / "none.env")
    monkeypatch.setattr(receipts.api_key, "__defaults__", (tmp_path / "none.env",))
    assert pick_reader("auto") is read_receipt_free
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert pick_reader("auto") is receipts.read_receipt
    assert pick_reader("free") is read_receipt_free


@pytest.mark.skipif(__import__("shutil").which("tesseract") is None, reason="needs tesseract")
def test_free_receipt_end_to_end_on_an_image(tmp_path, capsys):
    """Render a receipt, OCR it for real, and save it, all without an account."""
    pil = pytest.importorskip("PIL", reason="needs Pillow to draw the test image")
    from PIL import Image, ImageDraw, ImageFont
    from cartcompass.__main__ import main
    lines = ["Walmart", "BOWLING GREEN OH 43402", "GV 2% MLK GAL 007874235187 F 2.98 N",
             "GV LG WHT EGG 18CT 060538818718 F 3.47 N", "SUBTOTAL 6.45", "11/18/26"]
    try:
        font = ImageFont.truetype("DejaVuSansMono.ttf", 26)
    except OSError:
        pytest.skip("no monospace font")
    img = Image.new("L", (760, 40 * (len(lines) + 2)), 250)
    d = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        d.text((24, 40 * (i + 1)), line, font=font, fill=15)
    path = tmp_path / "receipt.png"
    img.save(path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "zcta_centroids.tsv").write_text("GEOID\tINTPTLAT\tINTPTLONG\n43402\t41.389\t-83.656\n")
    assert main(["receipt", str(path), "--engine", "free"]) == 0
    out = capsys.readouterr().out
    assert "Great Value 2% milk" in out and "✓ items add up to the subtotal ($6.45)" in out
    assert "saved 2 prices from Walmart" in out
