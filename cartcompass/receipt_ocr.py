"""Read receipts for free, on your own Mac: OCR plus a receipt-abbreviation decoder.

Text recognition uses Apple's Vision framework (the engine behind Live Text),
which ships with macOS and runs offline. Tesseract is used instead when it is
installed and Vision is not available. Neither sends the photo anywhere.

Receipts then go through rules instead of an AI model: each line is split into
name and price, sizes are read from tokens like GAL or 18CT, and a dictionary
expands common abbreviations (GV -> Great Value, MLK -> milk). Lines the
dictionary cannot fully decode are marked as guesses. The same checks as the AI
reader apply, so a misread price shows up as a subtotal mismatch.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from .receipts import Line, Receipt, ReceiptError

CHAINS = {"walmart": "Walmart", "wal-mart": "Walmart", "aldi": "ALDI", "meijer": "Meijer",
          "kroger": "Kroger", "target": "Target", "costco": "Costco", "giant eagle": "Giant Eagle"}

# Abbreviation -> words. Store brands first; then common grocery shorthand.
ABBREV = {
    "gv": "Great Value", "mkts": "Marketside", "mktsd": "Marketside", "sc": "Sam's Choice",
    "ff": "Friendly Farms", "lov": "L'oven Fresh", "kro": "Kroger", "krog": "Kroger", "st": "Simple Truth",
    "sto": "Simple Truth Organic", "pvt": "Private Selection", "mjr": "Meijer",
    "mlk": "milk", "milk": "milk", "whl": "whole", "whol": "whole", "skm": "skim", "rf": "reduced fat",
    "lf": "lowfat", "choc": "chocolate", "org": "organic", "orgnc": "organic",
    "egg": "eggs", "eggs": "eggs", "lg": "large", "lrg": "large", "xl": "extra large", "jmb": "jumbo",
    "med": "medium", "wht": "white", "brn": "brown", "cf": "cage free", "cgfr": "cage free",
    "brd": "bread", "bread": "bread", "ww": "whole wheat", "wht wht": "white wheat", "sdgh": "sourdough",
    "btr": "butter", "bttr": "butter", "slt": "salted", "uns": "unsalted", "unslt": "unsalted",
    "chkn": "chicken", "chk": "chicken", "brst": "breast", "bnls": "boneless", "sknls": "skinless",
    "thgh": "thighs", "grnd": "ground", "bf": "beef", "chs": "cheese", "chdr": "cheddar", "shrd": "shredded",
    "yog": "yogurt", "ygrt": "yogurt", "bnna": "bananas", "banana": "bananas", "bananas": "bananas",
    "appl": "apples", "pot": "potatoes", "tom": "tomatoes", "oj": "orange juice", "jce": "juice",
    "cer": "cereal", "pb": "peanut butter", "tp": "toilet paper", "pt": "paper towels",
}

SKIP = re.compile(r"\b(sub\s*total|subtotal|total|tax|change|cash|visa|mastercard|debit|credit|"
                  r"balance|tend|savings|you saved|coupon|approval|auth|account|ref\s*#|card|"
                  r"items sold|thank|survey|store\s*#|st#|op#|te#|tr#)\b", re.I)
SUBTOTAL = re.compile(r"sub\s*total\s*\$?\s*(\d+\.\d{2})", re.I)
PRICE_AT_END = re.compile(r"^(?P<body>.*?)\s+\$?(?P<price>-?\d{1,4}\.\d{2})\s*-?\s*[A-Z]{0,2}\s*$")
UPC = re.compile(r"\b\d{6,14}\b")
TAX_FLAG = re.compile(r"\s+[A-Z]$")                      # Walmart's "F"/"N"/"X" flags after the code
MULTI = re.compile(r"(\d+)\s*@\s*\$?(\d+\.\d{2})")       # "2 @ 1.42"
WEIGHT = re.compile(r"(\d+\.\d+)\s*lb\s*@\s*\$?(\d+\.\d{2})\s*/\s*lb", re.I)
DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b")
STATE_ZIP = re.compile(r"\b[A-Z]{2}\s+(\d{5})(?:-\d{4})?\b")
STREET = re.compile(r"^\s*\d{2,6}\s+[A-Za-z0-9 .]+\b(rd|road|st|street|ave|avenue|blvd|dr|drive|ln|lane|"
                    r"hwy|pike|way|pkwy|ct)\b\.?", re.I)
SIZE_TOKENS = [
    (re.compile(r"^(1/2|h|hf|hlf)\s*-?gal$|^hg$", re.I), lambda m: "1/2 gal"),
    (re.compile(r"^gal(lon)?$", re.I), lambda m: "1 gal"),
    (re.compile(r"^(\d+)\s*ct$", re.I), lambda m: f"{m.group(1)} ct"),
    (re.compile(r"^(\d+(?:\.\d+)?)\s*oz$", re.I), lambda m: f"{m.group(1)} oz"),
    (re.compile(r"^(\d+(?:\.\d+)?)\s*lb$", re.I), lambda m: f"{m.group(1)} lb"),
    (re.compile(r"^(\d+)\s*dz$", re.I), lambda m: f"{int(m.group(1)) * 12} ct"),
]


# --- OCR ---------------------------------------------------------------------

def rows_from_boxes(boxes: list[tuple[str, float, float, float]]) -> list[str]:
    """Join OCR fragments into printed lines. Each box is (text, x, y_mid, height),
    with y growing upward (Vision's coordinates). Receipts put the name and the
    price far apart on one line, so fragments at the same height are joined
    left to right."""
    rows: list[list[tuple[str, float, float, float]]] = []
    for b in sorted(boxes, key=lambda b: -b[2]):
        if rows and abs(rows[-1][0][2] - b[2]) < 0.5 * max(rows[-1][0][3], b[3]):
            rows[-1].append(b)
        else:
            rows.append([b])
    return [" ".join(t for t, *_ in sorted(r, key=lambda b: b[1])) for r in rows]


def vision_lines(image: Path) -> list[str]:
    """Apple Vision text recognition (macOS, needs `pip install pyobjc-framework-Vision`)."""
    import Vision
    from Foundation import NSURL
    handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(NSURL.fileURLWithPath_(str(image)), None)
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    req.setUsesLanguageCorrection_(False)   # receipts are abbreviations, not words
    ok, err = handler.performRequests_error_([req], None)
    if not ok:
        raise ReceiptError(f"text recognition failed: {err}")
    boxes = []
    for o in req.results() or []:
        cand = o.topCandidates_(1)
        if cand:
            bb = o.boundingBox()
            boxes.append((str(cand[0].string()), bb.origin.x, bb.origin.y + bb.size.height / 2, bb.size.height))
    return rows_from_boxes(boxes)


def tesseract_lines(image: Path) -> list[str]:
    out = subprocess.run(["tesseract", str(image), "stdout", "--psm", "4"], capture_output=True, text=True)
    if out.returncode != 0:
        raise ReceiptError(f"tesseract failed: {out.stderr.strip()[:200]}")
    return out.stdout.splitlines()


def ocr_lines(image: Path) -> tuple[list[str], str]:
    try:
        return vision_lines(image), "apple-vision"
    except ImportError:
        pass
    if shutil.which("tesseract"):
        return tesseract_lines(image), "tesseract"
    raise ReceiptError("No free OCR engine found. On a Mac: pip install pyobjc-framework-Vision "
                       "(or: brew install tesseract)")


# --- decoding ----------------------------------------------------------------

def decode_name(body: str) -> tuple[str, str, str, bool]:
    """'GV 2% MLK GAL' -> ('Great Value 2% milk', 'Great Value', '1 gal', True).

    The last value says whether every token was understood: an abbreviation in
    the dictionary, a size, a percentage, or a word printed in full.
    """
    body = re.sub(r"\b(1/2|half)\s*gal(lon)?\b", "HGAL", body, flags=re.I)
    words, size, brand, sure = [], "", "", True
    tokens = body.split()
    i = 0
    while i < len(tokens):
        low = tokens[i].lower().strip(".,")
        pair = f"{low} {tokens[i + 1].lower()}" if i + 1 < len(tokens) else ""
        if pair in ABBREV:
            words.append(ABBREV[pair])
            i += 2
            continue
        size_hit = next((fmt(m) for pattern, fmt in SIZE_TOKENS if (m := pattern.match(low))), None)
        if size_hit:
            size = size or size_hit
        elif low in ABBREV:
            word = ABBREV[low]
            if not words and word[0].isupper():
                brand = word
            words.append(word)
        elif re.fullmatch(r"\d+%", low) or (len(low) >= 4 and low.isalpha() and re.search(r"[aeiou]", low)):
            words.append(low)
        else:
            words.append(tokens[i])
            sure = False
        i += 1
    return " ".join(words).strip() or body.strip(), brand, size, sure


# Characters OCR commonly confuses on receipts, fixed only where the meaning is unambiguous.
OCR_FIXES = [
    (re.compile(r"(?<=[\d/@ ])1b\b"), "lb"),          # "0.50 /1b" -> "/lb"
    (re.compile(r"(\d)0Z\b"), r"\1OZ"),               # "200Z" -> "20OZ" (letter O read as zero)
    (re.compile(r"(\d)\s?0z\b"), r"\1oz"),
    (re.compile(r"(?<=\d)\s*,\s*(?=\d{2}\b)"), "."),  # "2,98" -> "2.98"
]


def clean_ocr(line: str) -> str:
    for pattern, repl in OCR_FIXES:
        line = pattern.sub(repl, line)
    return line


def parse_text(lines: list[str]) -> Receipt:
    lines = [clean_ocr(l) for l in lines]
    text = "\n".join(lines)
    low = text.lower()
    store = next((v for k, v in CHAINS.items() if k in low), "")
    zip_ = next((m.group(1) for m in map(STATE_ZIP.search, lines) if m), "")
    address = next((l.strip() for l in lines if STREET.match(l)), "")
    date = ""
    m = DATE.search(text)
    if m:
        mo, d, y = (int(g) for g in m.groups())
        y = y + 2000 if y < 100 else y
        if 1 <= mo <= 12 and 1 <= d <= 31:
            date = f"{y:04d}-{mo:02d}-{d:02d}"
    sub = SUBTOTAL.search(text)
    items: list[Line] = []
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        wm = WEIGHT.search(line)
        if wm and items and not re.search(r"[A-Za-z]{2}", line[:wm.start()]):
            # a weight line under its item ("2.31 lb @ 0.50 /lb"): the item was sold by weight
            last = items[-1]
            last.quantity, last.sold_by_weight = float(wm.group(1)), True
            continue
        if SKIP.search(line):
            continue
        pm = PRICE_AT_END.match(line)
        if not pm:
            continue
        body, price = pm.group("body"), float(pm.group("price"))
        if price <= 0:
            continue          # discounts and voids are not prices of goods
        qty, sold_by_weight = 1.0, False
        mm = MULTI.search(body)
        if wm:
            qty, sold_by_weight = float(wm.group(1)), True
            body = body[:wm.start()]
        elif mm:
            qty = float(mm.group(1))
            body = body[:mm.start()]
        body = TAX_FLAG.sub("", UPC.sub("", body)).strip()
        if not re.search(r"[A-Za-z]{2}", body):
            continue
        name, brand, size, sure = decode_name(body)
        items.append(Line(raw=line, name=name, price=round(price, 2), brand=brand, size=size,
                          quantity=qty, sold_by_weight=sold_by_weight, confident=sure))
    r = Receipt(store=store, items=items, address=address, zip=zip_, date=date,
                subtotal=float(sub.group(1)) if sub else None, model="free-ocr")
    if r.adds_up is False:
        r.checks.append(f"items add up to ${sum(i.price for i in items):.2f}, but the receipt's subtotal "
                        f"is ${r.subtotal:.2f}: some lines may be misread")
    unsure = [i.raw for i in items if not i.confident]
    if unsure:
        r.checks.append(f"{len(unsure)} line(s) only partly decoded: " + "; ".join(unsure[:5]))
    return r


def read_receipt_free(image: Path, model: str = "") -> Receipt:
    lines, engine = ocr_lines(Path(image))
    r = parse_text(lines)
    r.model = f"free-ocr ({engine})"
    if not r.items:
        raise ReceiptError("No priced lines found. Is the photo a receipt, flat and in focus?")
    return r
