"""Command line: cartcompass search milk --zip 43402"""
from __future__ import annotations

import argparse
import json
import sys

from .compare import Comparison, compare
from . import history
from .kroger import KrogerClient, KrogerError


def money(x: float) -> str:
    return f"${x:,.2f}"


def render(c: Comparison, show: int = 5, db=None) -> str:
    lines = [f"{c.query!r} near you: {len(c.stores)} stores searched, "
             f"{sum(len(ch.offers) for ch in c.choices)} matching products"
             + (f" ({c.skipped} look-alikes ignored)" if c.skipped else "")]
    if not c.choices:
        return lines[0] + "\nNothing matched. Try a simpler word, or a wider --radius."
    for ch in c.choices[:show]:
        best = ch.best
        lines.append("")
        lines.append(ch.variant.label())
        if best is None:
            lines.append("  no in-stock offer with a readable size")
            continue
        for o in ch.best_per_store():
            store = c.stores.get(o.store_id)
            where = store.label if store else o.store_id
            where = where if len(where) <= 28 else where[:27] + "…"
            sale = f", sale from {money(o.regular)}" if o.on_sale else ""
            mark = "→" if o is best else " "
            lines.append(f" {mark} {money(o.unit_price)}/{o.unit:<4} {where:<28} {o.description} "
                         f"({o.size}, {money(o.price)}{sale})")
            if db is not None and (o.on_sale or o is best):
                chk = history.check(db, o)
                if chk.verdict in ("real deal", "not really a sale"):
                    lines.append(f"   {'✓' if chk.verdict == 'real deal' else '!'} {chk.describe(o.price)}")
        trap = [o for o in ch.offers if o.available and o.unit_price and o.store_id == best.store_id
                and o.unit_price > best.unit_price * 1.15 and o.price < best.price]
        if trap:
            t = min(trap, key=lambda o: o.price)
            lines.append(f"   careful: the {t.size} at {money(t.price)} looks cheaper but is "
                         f"{money(t.unit_price)}/{t.unit} ({(t.unit_price / best.unit_price - 1):.0%} more)")
    if len(c.choices) > show:
        lines.append(f"\n+ {len(c.choices) - show} more kinds (use --show)")
    return "\n".join(lines)


def to_json(c: Comparison) -> dict:
    return {"query": c.query, "stores": {k: vars(v) for k, v in c.stores.items()},
            "skipped": c.skipped, "unpriced": c.unpriced,
            "choices": [{"label": ch.variant.label(), "attrs": dict(ch.variant.attrs),
                         "offers": [o.to_dict() for o in ch.offers]} for ch in c.choices]}


def main(argv: list[str] | None = None, client: KrogerClient | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cartcompass", description="Find the real cheapest grocery near you.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search", help="compare one item across nearby stores")
    s.add_argument("item", nargs="+")
    s.add_argument("--zip", default="43402")
    s.add_argument("--radius", type=int, default=15, help="miles (default 15)")
    s.add_argument("--stores", type=int, default=5, help="max stores to search")
    s.add_argument("--show", type=int, default=5, help="kinds of product to show")
    s.add_argument("--depth", type=int, default=150, help="products to read per store (default 150)")
    s.add_argument("--json", action="store_true")
    s.add_argument("--no-save", action="store_true", help="don't add today's prices to the history")
    t = sub.add_parser("track", help="record today's prices for a list of items (run daily)")
    t.add_argument("items", nargs="*", default=["milk", "eggs", "bread", "bananas", "butter", "chicken breast"])
    for p in (s, t):
        p.add_argument("--db", default=str(history.DEFAULT_DB), help="history file (default data/prices.sqlite)")
    t.add_argument("--zip", default="43402")
    t.add_argument("--radius", type=int, default=15)
    t.add_argument("--stores", type=int, default=5)
    t.add_argument("--depth", type=int, default=150)
    a = ap.parse_args(argv)
    try:
        client = client or KrogerClient.from_env()
        if a.cmd == "track":
            return track(client, a)
        c = compare(client, " ".join(a.item), a.zip, a.radius, a.stores, a.depth)
    except KrogerError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    db = None
    if not a.no_save:
        db = history.connect(a.db)
        history.record(db, [o for ch in c.choices for o in ch.offers])
    print(json.dumps(to_json(c), indent=2) if a.json else render(c, a.show, db))
    return 0


def track(client: KrogerClient, a) -> int:
    db = history.connect(a.db)
    total = 0
    for item in a.items:
        c = compare(client, item, a.zip, a.radius, a.stores, a.depth)
        n = history.record(db, [o for ch in c.choices for o in ch.offers])
        total += n
        print(f"{item:<16} {n:>4} prices from {len(c.stores)} stores")
    days = db.execute("SELECT count(DISTINCT day) FROM prices").fetchone()[0]
    print(f"saved {total} prices; history now covers {days} day{'s' if days != 1 else ''} "
          f"({client.calls} API calls)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
