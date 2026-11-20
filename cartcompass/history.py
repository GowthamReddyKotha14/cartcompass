"""Daily price history in a local SQLite file, and honest sale checks.

Every search records what each store charged that day. Once a product has a few
days of history, a "sale" can be judged against what the store usually charges,
not against the regular price printed on the tag.

The database stays on your machine (data/ is git-ignored).
"""
from __future__ import annotations

import sqlite3
import statistics
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .offers import Offer

DEFAULT_DB = Path("data/prices.sqlite")
MIN_DAYS = 5          # days of history needed before judging a sale
REAL_DEAL = 0.10      # at least 10% under the usual price

SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
    day TEXT NOT NULL,
    store_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    size TEXT NOT NULL,
    upc TEXT,
    description TEXT,
    price REAL NOT NULL,
    regular REAL,
    on_sale INTEGER NOT NULL,
    stock TEXT,
    unit_price REAL,
    unit TEXT,
    PRIMARY KEY (day, store_id, product_id, size)
);
CREATE INDEX IF NOT EXISTS prices_item ON prices (store_id, product_id, size, day);
"""


def connect(path: Path | str = DEFAULT_DB) -> sqlite3.Connection:
    path = Path(path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    return db


def record(db: sqlite3.Connection, offers: list[Offer], day: date | None = None) -> int:
    """Store today's price for each offer. Re-running the same day overwrites it."""
    d = (day or date.today()).isoformat()
    rows = [(d, o.store_id, o.product_id, o.size, o.upc, o.description, o.price, o.regular,
             int(o.on_sale), o.stock, o.unit_price, o.unit) for o in offers]
    db.executemany("INSERT OR REPLACE INTO prices VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    db.commit()
    return len(rows)


@dataclass
class SaleCheck:
    verdict: str            # "real deal" | "normal price" | "not really a sale" | "new" (too little history)
    usual: float | None     # median price paid over the history, excluding today
    days: int               # days of history used
    lowest: float | None

    def describe(self, today: float) -> str:
        if self.verdict == "new":
            return f"tracking since recently ({self.days} day{'s' if self.days != 1 else ''} of history)"
        diff = (today - self.usual) / self.usual
        rel = f"{abs(diff):.0%} {'below' if diff < 0 else 'above'} its usual ${self.usual:.2f}" if abs(diff) >= 0.005 else f"its usual ${self.usual:.2f}"
        return f"{self.verdict}: ${today:.2f} is {rel} over {self.days} days"


def check(db: sqlite3.Connection, o: Offer, today: date | None = None, window_days: int = 60) -> SaleCheck:
    d = (today or date.today()).isoformat()
    past = [r[0] for r in db.execute(
        "SELECT price FROM prices WHERE store_id=? AND product_id=? AND size=? AND day<? "
        "AND day>=date(?, ?) ORDER BY day", (o.store_id, o.product_id, o.size, d, d, f"-{window_days} days"))]
    if len(past) < MIN_DAYS:
        return SaleCheck("new", None, len(past), None)
    usual, lowest = statistics.median(past), min(past)
    if o.price <= usual * (1 - REAL_DEAL):
        verdict = "real deal"
    elif o.on_sale:
        verdict = "not really a sale"   # tagged as a sale, but about what it usually costs
    else:
        verdict = "normal price"
    return SaleCheck(verdict, round(usual, 2), len(past), lowest)
