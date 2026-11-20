"""Command line: cartcompass search milk --zip 43402"""
from __future__ import annotations

import argparse
import json
import sys

from pathlib import Path

from .compare import Comparison, compare, live_only
from . import geo, history, receipts
from .plan import DEFAULT_PER_MILE, DEFAULT_PER_STOP, plan_trip
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


def main(argv: list[str] | None = None, client: KrogerClient | None = None, reader=None) -> int:
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
    pl = sub.add_parser("plan", help="cheapest trip (1 or 2 stores) for a shopping list, driving included")
    pl.add_argument("items", nargs="+", help='e.g. milk eggs bread "chicken breast" "organic eggs"')
    pl.add_argument("--zip", default="43402")
    pl.add_argument("--home", help="your start point as lat,lon (default: the ZIP's center)")
    pl.add_argument("--radius", type=int, default=15)
    pl.add_argument("--stores", type=int, default=5)
    pl.add_argument("--max-stores", type=int, default=2, help="most stores to visit (default 2)")
    pl.add_argument("--per-mile", type=float, default=DEFAULT_PER_MILE,
                    help=f"cost of driving one mile, gas plus wear (default ${DEFAULT_PER_MILE:.2f})")
    pl.add_argument("--per-stop", type=float, default=DEFAULT_PER_STOP,
                    help=f"what each extra store is worth to you in time (default ${DEFAULT_PER_STOP:.2f})")
    pl.add_argument("--depth", type=int, default=150)
    pl.add_argument("--db", default=str(history.DEFAULT_DB))
    r = sub.add_parser("receipt", help="read a receipt photo (Walmart, ALDI, Meijer...) with AI and save its prices")
    r.add_argument("images", nargs="+", type=Path)
    r.add_argument("--zip", help="store ZIP if the receipt doesn't print one")
    r.add_argument("--engine", choices=["auto", "free", "ai"], default="auto",
                   help="free: OCR on this Mac, no account; ai: Claude vision (needs ANTHROPIC_API_KEY "
                        "and API credits). auto: ai if a key is set, else free")
    r.add_argument("--model", default=receipts.MODEL, help="AI model for --engine ai")
    r.add_argument("--no-save", action="store_true")
    r.add_argument("--db", default=str(history.DEFAULT_DB))
    t = sub.add_parser("track", help="record today's prices for a list of items (run daily)")
    t.add_argument("items", nargs="*", default=["milk", "eggs", "bread", "bananas", "butter", "chicken breast"])
    for p in (s, t):
        p.add_argument("--db", default=str(history.DEFAULT_DB), help="history file (default data/prices.sqlite)")
    t.add_argument("--zip", default="43402")
    t.add_argument("--radius", type=int, default=15)
    t.add_argument("--stores", type=int, default=5)
    t.add_argument("--depth", type=int, default=150)
    a = ap.parse_args(argv)
    if a.cmd == "receipt":
        return receipt_cmd(a, reader)
    try:
        client = client or KrogerClient.from_env()
        if a.cmd == "track":
            return track(client, a)
        if a.cmd == "plan":
            return plan_cmd(client, a)
        c = compare(client, " ".join(a.item), a.zip, a.radius, a.stores, a.depth, receipt_stores(a))
    except KrogerError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    db = None
    if not a.no_save:
        db = history.connect(a.db)
        history.record(db, live_only([o for ch in c.choices for o in ch.offers]))
        history.record_stores(db, c.stores.values())
    print(json.dumps(to_json(c), indent=2) if a.json else render(c, a.show, db))
    return 0


def receipt_stores(a, home=None):
    """Nearby stores known from saved receipts, or None if there are none (or no history yet)."""
    if not Path(a.db).exists():
        return None
    db = history.connect(a.db)
    if not db.execute("SELECT 1 FROM other_stores LIMIT 1").fetchone():
        return None
    try:
        home = home or geo.zip_center(a.zip)
    except (KeyError, OSError):
        return None
    stores, offers = receipts.nearby(db, home, a.radius)
    return (stores, offers) if stores else None


def pick_reader(engine: str):
    from .receipt_ocr import read_receipt_free
    if engine == "auto":
        try:
            receipts.api_key()
            engine = "ai"
        except receipts.ReceiptError:
            engine = "free"
    return receipts.read_receipt if engine == "ai" else read_receipt_free


def receipt_cmd(a, reader=None) -> int:
    reader = reader or pick_reader(a.engine)
    db = None if a.no_save else history.connect(a.db)
    status = 0
    for img in a.images:
        try:
            r = reader(img, model=a.model)
        except (receipts.ReceiptError, OSError) as e:
            print(f"{img.name}: error: {e}", file=sys.stderr)
            status = 2
            continue
        print(render_receipt(img.name, r))
        if db is not None:
            z = r.zip or a.zip
            try:
                where = geo.zip_center(z) if z else None
            except (KeyError, OSError):
                where = None
            n = receipts.save(db, r, where)
            note = "" if where else " (no store ZIP: pass --zip so it can be used in comparisons)"
            print(f"saved {n} prices from {r.store}{note}\n")
    return status


def render_receipt(name: str, r) -> str:
    from .units import unit_price
    head = f"{name}: {r.store or 'unknown store'}" + (f", {r.address}" if r.address else "") \
        + (f" {r.zip}" if r.zip else "") + (f" on {r.date}" if r.date else "") \
        + (f"  [read with {r.model}]" if r.model else "")
    lines = [head]
    for i in r.items:
        up = (i.each, "lb") if i.sold_by_weight else unit_price(i.each, i.size)
        per = f"{money(up[0])}/{up[1]}" if up else ""
        qty = f"{i.quantity:g} x " if i.quantity != 1 and not i.sold_by_weight else ""
        flag = "" if i.confident else "  ?"
        lines.append(f"  {i.raw[:28]:<28} → {i.name[:40]:<40} {i.size:<8} {qty}{money(i.each):>7} {per:>11}{flag}")
    if r.adds_up:
        lines.append(f"  ✓ items add up to the subtotal ({money(r.subtotal)})")
    for c in r.checks:
        lines.append(f"  ! {c}")
    return "\n".join(lines)


def plan_cmd(client: KrogerClient, a) -> int:
    try:
        home = geo.parse_home(a.home) if a.home else geo.zip_center(a.zip)
    except (KeyError, ValueError, OSError) as e:
        print(f"error: can't place home ({e}). Pass --home lat,lon.", file=sys.stderr)
        return 2
    priced, stores, plans, offers = plan_trip(client, a.items, a.zip, home, a.radius, a.max_stores,
                                              a.per_mile, a.stores, a.depth, receipt_stores(a, home),
                                              a.per_stop)
    db = history.connect(a.db)
    history.record(db, live_only(offers))
    history.record_stores(db, stores.values())
    name = lambda sid: stores[sid].label if sid in stores else sid
    print(render_plan(priced, plans, name, a.per_mile, a.per_stop))
    return 0


def render_plan(priced, plans, name, per_mile: float, per_stop: float = DEFAULT_PER_STOP) -> str:
    if not plans:
        return "No store near you had these items."
    best = plans[0]
    extra = f" + extra stop {money(per_stop)}" if len(best.stores) > 1 else ""
    out = [f"Best trip: {' + '.join(name(s) for s in best.stores)}",
           f"  groceries {money(best.groceries)} + driving {money(best.driving)} "
           f"({best.miles:.1f} mi round trip){extra} = {money(best.total)}", ""]
    for p in priced:
        sid = best.buy.get(p.item.text)
        if p.choice is None or sid is None:
            out.append(f"  {p.item.text:<16} not found at these stores")
            continue
        o = p.at[sid]
        size = f"{p.amount:g} {p.unit}"
        where = f"  at {name(sid)}" if len(best.stores) > 1 else ""
        out.append(f"  {p.item.text:<16} {money(p.cost(sid)):>7}  {p.choice.variant.label()}, {size}{where}"
                   f"  ({o.description})")
    others = [p for p in plans if p is not best and not p.missing]
    alt = [next((p for p in others if len(p.stores) == k), None) for k in (1, 2)]
    alt = [x for x in alt if x]
    if alt:
        out.append("")
        out.append("Compared with:")
        for x in alt:
            dg, dd = x.groceries - best.groceries, x.driving - best.driving
            why = (f"groceries {money(abs(dg))} {'cheaper' if dg < 0 else 'more'}, "
                   f"driving {money(abs(dd))} {'more' if dd > 0 else 'less'}")
            ds = len(x.stores) - len(best.stores)
            if ds:
                why += f", {'one more' if ds > 0 else 'one fewer'} stop"
            out.append(f"  {' + '.join(name(s) for s in x.stores):<48} {money(x.total):>8}  ({why})")
    out.append("")
    out.append(f"Driving is estimated at {money(per_mile)}/mile on straight-line distance x1.3, and each "
               f"extra store counts as {money(per_stop)} of your time. Each item is priced as one typical package.")
    return "\n".join(out)


def track(client: KrogerClient, a) -> int:
    db = history.connect(a.db)
    total = 0
    for item in a.items:
        c = compare(client, item, a.zip, a.radius, a.stores, a.depth)
        n = history.record(db, live_only([o for ch in c.choices for o in ch.offers]))
        history.record_stores(db, c.stores.values())
        total += n
        print(f"{item:<16} {n:>4} prices from {len(c.stores)} stores")
    days = db.execute("SELECT count(DISTINCT day) FROM prices").fetchone()[0]
    print(f"saved {total} prices; history now covers {days} day{'s' if days != 1 else ''} "
          f"({client.calls} API calls)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
