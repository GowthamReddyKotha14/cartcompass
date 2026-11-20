"""Read grocery receipts with an AI vision model.

Store receipts abbreviate everything ("GV 2% MLK GAL 2.98"). A vision model
reads the photo and returns each line both as printed and decoded ("Great Value
2% milk", "1 gal", 2.98), through a tool schema so the output is always
structured. The result is then checked, not trusted: the item prices must add
up to the printed subtotal, and every line keeps its raw text for review.

Uses the Anthropic Messages API directly (no SDK). The key is read from
ANTHROPIC_API_KEY in the environment or ~/.cartcompass.env and never logged.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from .kroger import ENV_FILE

API = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-5-5"
MAX_BYTES = 4_500_000   # stay under the API's per-image size limit
MEDIA = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}

Transport = Callable[[str, dict, bytes], tuple[int, dict]]

TOOL = {
    "name": "record_receipt",
    "description": "Record every purchased line on a grocery receipt, decoded into plain product names.",
    "input_schema": {
        "type": "object",
        "properties": {
            "store": {"type": "string", "description": "Chain name as printed, e.g. Walmart, ALDI, Meijer"},
            "address": {"type": "string", "description": "Store street address if printed, else empty"},
            "zip": {"type": "string", "description": "Store 5-digit ZIP if printed, else empty"},
            "date": {"type": "string", "description": "Purchase date as YYYY-MM-DD, else empty"},
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "raw": {"type": "string", "description": "The line exactly as printed"},
                        "name": {"type": "string", "description": "Decoded product, e.g. 'Great Value 2% Reduced Fat Milk'"},
                        "brand": {"type": "string", "description": "Brand if known, e.g. Great Value; else empty"},
                        "size": {"type": "string", "description": "Package size if printed or certain, e.g. '1 gal', '12 ct', '20 oz'; else empty"},
                        "quantity": {"type": "number", "description": "How many were bought (default 1). For items sold by weight, the weight in lb."},
                        "sold_by_weight": {"type": "boolean"},
                        "price": {"type": "number", "description": "Line total actually charged, after any instant savings on that line"},
                        "confident": {"type": "boolean", "description": "False if the decoding is a guess"},
                    },
                    "required": ["raw", "name", "price"],
                },
            },
            "subtotal": {"type": "number", "description": "Printed subtotal before tax, if present"},
        },
        "required": ["store", "items"],
    },
}

PROMPT = """This is a photo of a grocery store receipt. Call record_receipt with every purchased line.
Decode store abbreviations into plain product names (e.g. "GV" is Great Value at Walmart).
Only fill in a size when it is printed or certain; never invent one. Skip tax, totals,
payment, coupons that are not tied to one line, and loyalty messages. If a line is
unreadable, still record its raw text with your best guess and confident=false."""


class ReceiptError(RuntimeError):
    pass


@dataclass
class Line:
    raw: str
    name: str
    price: float
    brand: str = ""
    size: str = ""
    quantity: float = 1.0
    sold_by_weight: bool = False
    confident: bool = True

    @property
    def each(self) -> float:
        """Price of one package (or of one pound, if sold by weight)."""
        return round(self.price / self.quantity, 2) if self.quantity else self.price


@dataclass
class Receipt:
    store: str
    items: list[Line]
    address: str = ""
    zip: str = ""
    date: str = ""
    subtotal: float | None = None
    model: str = ""
    checks: list[str] = field(default_factory=list)

    @property
    def adds_up(self) -> bool | None:
        if self.subtotal is None:
            return None
        return abs(sum(i.price for i in self.items) - self.subtotal) <= 0.02

    def to_dict(self) -> dict:
        return asdict(self) | {"adds_up": self.adds_up}


def api_key(path: Path = ENV_FILE) -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key and path.exists():
        for line in path.read_text().splitlines():
            k, _, v = line.partition("=")
            if k.strip() == "ANTHROPIC_API_KEY":
                key = v.strip()
    if not key:
        raise ReceiptError(f"Set ANTHROPIC_API_KEY (environment or {path}).")
    return key


def load_image(path: Path) -> tuple[str, bytes]:
    """Image bytes in a format the API accepts. iPhone HEIC photos and very large
    images are converted with macOS `sips` when it is available."""
    path = Path(path)
    suffix = path.suffix.lower()
    data = path.read_bytes()
    if suffix in MEDIA and len(data) <= MAX_BYTES:
        return MEDIA[suffix], data
    if not shutil.which("sips"):
        raise ReceiptError(f"{path.name}: use a JPEG or PNG under {MAX_BYTES // 1_000_000} MB "
                           "(HEIC and resizing need macOS)")
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "receipt.jpg"
        subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "80", "-Z", "2400",
                        str(path), "--out", str(out)], check=True, capture_output=True)
        return "image/jpeg", out.read_bytes()


def urllib_transport(url: str, headers: dict, body: bytes) -> tuple[int, dict]:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}


def parse_response(d: dict, model: str = "") -> Receipt:
    call = next((c for c in d.get("content", []) if c.get("type") == "tool_use"
                 and c.get("name") == TOOL["name"]), None)
    if call is None:
        raise ReceiptError("The model did not return a receipt (is the photo a receipt?)")
    x = call["input"]
    lines = []
    for it in x.get("items", []):
        try:
            lines.append(Line(raw=str(it.get("raw", "")), name=str(it.get("name", "")).strip(),
                              price=round(float(it["price"]), 2), brand=str(it.get("brand") or ""),
                              size=str(it.get("size") or ""), quantity=float(it.get("quantity") or 1),
                              sold_by_weight=bool(it.get("sold_by_weight", False)),
                              confident=bool(it.get("confident", True))))
        except (KeyError, TypeError, ValueError):
            continue
    sub = x.get("subtotal")
    r = Receipt(store=str(x.get("store", "")).strip(), items=lines, address=str(x.get("address") or ""),
                zip=str(x.get("zip") or "")[:5], date=str(x.get("date") or ""),
                subtotal=round(float(sub), 2) if isinstance(sub, (int, float)) else None, model=model)
    if r.adds_up is False:
        r.checks.append(f"items add up to ${sum(i.price for i in lines):.2f}, but the receipt's "
                        f"subtotal is ${r.subtotal:.2f}: some lines may be misread")
    unsure = [i.raw for i in lines if not i.confident]
    if unsure:
        r.checks.append(f"{len(unsure)} line(s) decoded as a guess: " + "; ".join(unsure[:5]))
    return r


def read_receipt(image: Path, key: str | None = None, model: str = MODEL,
                 transport: Transport = urllib_transport) -> Receipt:
    media, data = load_image(Path(image))
    body = json.dumps({
        "model": model, "max_tokens": 4096,
        "tools": [TOOL], "tool_choice": {"type": "tool", "name": TOOL["name"]},
        "messages": [{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": media,
                                         "data": base64.b64encode(data).decode()}},
            {"type": "text", "text": PROMPT}]}],
    }).encode()
    status, d = transport(API, {"x-api-key": key or api_key(), "anthropic-version": "2023-06-01",
                                "content-type": "application/json"}, body)
    if status != 200:
        msg = (d.get("error") or {}).get("message") if isinstance(d.get("error"), dict) else d
        raise ReceiptError(f"AI request failed (HTTP {status}): {msg}")
    return parse_response(d, model)


# --- saving receipts and using them next to live store prices -------------------

RECENT_DAYS = 30   # receipt prices older than this are not used for comparisons


def store_id(r: Receipt) -> str:
    chain = "-".join(r.store.lower().split()) or "store"
    where = "-".join((r.address or "").lower().split()) or "unknown"
    return f"receipt:{chain}:{r.zip or '00000'}:{where}"


def to_offers(r: Receipt):
    """Receipt lines as offers, so they are matched, unit-priced and ranked like any other."""
    from .offers import Offer
    from .units import DISPLAY, parse_size
    sid, out = store_id(r), []
    for i in r.items:
        if i.sold_by_weight:
            unit_price, unit, amount = i.each, "lb", 1.0   # priced per pound; plan one pound
        else:
            q = parse_size(i.size)
            unit_price = unit = amount = None
            if q:
                unit, amount = DISPLAY[q.dim][0], q.per()
                unit_price = round(i.each / amount, 4)
        out.append(Offer(store_id=sid, product_id=" ".join(i.raw.upper().split()[:4]) or i.name,
                         upc="", brand=i.brand, description=i.name, category="", size=i.size,
                         price=i.each, regular=i.each, on_sale=False, stock="",
                         unit_price=unit_price, unit=unit, amount=amount))
    return out


def save(db, r: Receipt, where: tuple[float, float] | None, day=None) -> int:
    """Record a receipt's prices in the history, dated by the receipt itself."""
    from datetime import date as _date
    from . import history
    if day is None:
        try:
            day = _date.fromisoformat(r.date)
        except ValueError:
            day = _date.today()
    lat, lon = where if where else (None, None)
    db.execute("INSERT OR REPLACE INTO other_stores VALUES (?,?,?,?,?,?)",
               (store_id(r), r.store, r.address, r.zip, lat, lon))
    return history.record(db, to_offers(r), day)


def nearby(db, home: tuple[float, float], radius_miles: float, days: int = RECENT_DAYS, today=None):
    """Receipt-based stores within the radius, and each product's latest price there."""
    from datetime import date as _date, timedelta
    from .geo import haversine_miles
    from .kroger import Store
    from .offers import Offer
    since = ((today or _date.today()) - timedelta(days=days)).isoformat()
    stores = {}
    for sid, chain, address, zip_, lat, lon in db.execute("SELECT * FROM other_stores"):
        if lat is not None and haversine_miles(home, (lat, lon)) <= radius_miles:
            stores[sid] = Store(sid, chain.upper(), f"{chain} - {address or zip_}", address or "", "", zip_ or "", lat, lon)
    offers = []
    for sid in stores:
        rows = db.execute(
            "SELECT p.store_id, p.product_id, p.size, p.upc, p.description, p.price, p.regular, p.unit_price, p.unit "
            "FROM prices p JOIN (SELECT product_id, size, max(day) d FROM prices WHERE store_id=? AND day>=? "
            "GROUP BY product_id, size) last ON p.product_id=last.product_id AND p.size=last.size AND p.day=last.d "
            "WHERE p.store_id=?", (sid, since, sid))
        for s_id, pid, size, upc, desc, price, regular, unit_price, unit in rows:
            amount = round(price / unit_price, 6) if unit_price else None
            offers.append(Offer(s_id, pid, upc or "", "", desc or "", "", size, price, regular or price, False,
                                "", unit_price, unit, amount))
    return stores, offers
