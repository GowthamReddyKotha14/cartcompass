"""Build the showcase site's data from the local price history.

The site shows findings, not a price list: for a few everyday items, the
cheapest per-unit price of the same kind at each store on the latest tracked
day, and how far apart the stores are. It also ships the cartcompass package
itself as a zip, so the page can run the real code in the browser (Pyodide).
"""
from __future__ import annotations

import json
import sqlite3
import zipfile
from datetime import date
from pathlib import Path

from .compare import rank
from .matching import family_of
from .offers import Offer

# Packaged staples with clear sizes. Loose produce (bananas) is left out: stores
# list it by weight or each, and "banana" appears in too many other products for
# a public claim about it to be safe.
ITEMS = ["milk", "eggs", "bread", "butter", "chicken breast"]
PACKAGE = Path(__file__).resolve().parent


def offers_on(db: sqlite3.Connection, day: str) -> list[Offer]:
    rows = db.execute(
        "SELECT store_id, product_id, size, upc, description, price, regular, on_sale, stock, unit_price, unit "
        "FROM prices WHERE day=? AND store_id NOT LIKE 'receipt:%'", (day,))
    out = []
    for sid, pid, size, upc, desc, price, regular, sale, stock, up, unit in rows:
        amount = round(price / up, 6) if up else None
        out.append(Offer(sid, pid, upc or "", "", desc or "", "", size, price, regular or price,
                         bool(sale), stock or "", up, unit, amount))
    return out


def same_product(per_store: list[Offer]) -> bool:
    return len({(o.description, o.size) for o in per_store}) == 1


def pick(choices) -> list:
    """Kinds worth reporting, best first. The everyday version comes first: plain
    (not almond, not pasture-raised, not frozen) and store brand, the budget
    staple most shoppers buy. Then the exact same product at every store beats a
    mix of similar products; then wider store coverage; then more listings."""
    ok = [c for c in choices if c.variant.plainness == 0 and len(c.best_per_store()) >= 2]
    tier = lambda c: dict(c.variant.attrs).get("tier") != "store brand"
    return sorted(ok, key=lambda c: (tier(c), not same_product(c.best_per_store()),
                                     -len(c.best_per_store()), -len(c.offers)))


def finding(offers: list[Offer], item: str, labels: dict[str, str]) -> dict | None:
    choices, _, _ = rank(offers, family_of(item))
    for c in pick(choices):
        per_store = c.best_per_store()
        lo, hi = per_store[0], per_store[-1]
        trap = None
        sizes = [o for o in c.offers if o.available and o.unit_price and o.store_id == lo.store_id]
        cheaper_looking = [o for o in sizes if o.price < lo.price and o.unit_price > lo.unit_price * 1.15]
        if cheaper_looking:
            t = min(cheaper_looking, key=lambda o: o.price)
            trap = {"small": {"size": t.size, "price": t.price, "unit_price": t.unit_price},
                    "big": {"size": lo.size, "price": lo.price, "unit_price": lo.unit_price},
                    "store": labels.get(lo.store_id, lo.store_id)}
        return {
            "item": item, "kind": c.variant.label(), "unit": lo.unit,
            "stores": [{"store": labels.get(o.store_id, o.store_id), "unit_price": o.unit_price,
                        "price": o.price, "size": o.size, "product": o.description} for o in per_store],
            "spread": round(hi.unit_price / lo.unit_price - 1, 4),
            "same_product": same_product(per_store),
            "trap": trap,
        }
    return None


def build(db_path: Path, out_dir: Path, items: list[str] = ITEMS) -> dict:
    db = sqlite3.connect(db_path)
    days = [d for (d,) in db.execute(
        "SELECT DISTINCT day FROM prices WHERE store_id NOT LIKE 'receipt:%' ORDER BY day")]
    if not days:
        raise SystemExit("No price history yet. Run 'cartcompass track' first.")
    latest = days[-1]
    labels = dict(db.execute("SELECT store_id, label FROM stores"))
    offers = offers_on(db, latest)
    findings = [f for f in (finding(offers, it, labels) for it in items) if f]
    data = {
        "generated": date.today().isoformat(), "day": latest, "days_tracked": len(days),
        "first_day": days[0], "stores": len({o.store_id for o in offers}),
        "prices_that_day": len(offers),
        "prices_total": db.execute("SELECT count(*) FROM prices WHERE store_id NOT LIKE 'receipt:%'").fetchone()[0],
        "findings": findings,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "findings.js").write_text("window.FINDINGS = " + json.dumps(data, indent=1) + ";\n")
    with zipfile.ZipFile(out_dir / "cartcompass.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(PACKAGE.glob("*.py")):
            z.write(f, f"cartcompass/{f.name}")
    return data
