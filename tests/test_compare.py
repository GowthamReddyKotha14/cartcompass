import json

from cartcompass.__main__ import main
from cartcompass.compare import compare
from cartcompass.kroger import KrogerClient
from fake_kroger import FakeKroger


def client():
    return KrogerClient("id", "secret", transport=FakeKroger(), sleep=lambda s: None)


def test_cheapest_store_brand_2pct_is_waterville():
    c = compare(client(), "milk", "43402")
    two = next(ch for ch in c.choices if ch.variant.label() == "2% milk (store brand)")
    assert two.best.store_id == "01600531" and two.best.unit_price == 2.49
    assert [o.store_id for o in two.best_per_store()] == ["01600531", "01600878"]


def test_out_of_stock_never_wins():
    c = compare(client(), "milk", "43402")
    whole = next(ch for ch in c.choices if ch.variant.label() == "whole milk (store brand)")
    assert whole.best.store_id == "01600878"  # Waterville is cheaper on paper but out of stock


def test_organic_is_its_own_choice():
    labels = [ch.variant.label() for ch in compare(client(), "milk", "43402").choices]
    assert "2% organic milk (store brand)" in labels


def test_cli_flags_the_half_gallon_trap(capsys):
    assert main(["search", "milk", "--zip", "43402"], client=client()) == 0
    out = capsys.readouterr().out
    assert "2% milk (store brand)" in out and "$2.49/gal" in out
    assert "careful: the 1/2 gal at $1.89" not in out  # different store from the winner
    assert main(["search", "milk", "--stores", "1"], client=client()) == 0
    out = capsys.readouterr().out
    assert "careful: the 1/2 gal at $1.89 looks cheaper but is $3.78/gal (41% more)" in out


def test_cli_json(capsys):
    assert main(["search", "milk", "--json"], client=client()) == 0
    d = json.loads(capsys.readouterr().out)
    assert d["query"] == "milk" and d["choices"][0]["offers"]


def test_cli_reports_bad_keys(capsys):
    bad = KrogerClient("id", "secret", transport=lambda *a: (401, {"error": "invalid_client"}))
    assert main(["search", "milk"], client=bad) == 2
    assert "invalid_client" in capsys.readouterr().err


def test_plain_kinds_come_before_niche_ones():
    from cartcompass.compare import rank
    from cartcompass.offers import from_product
    from fake_kroger import product
    offers = []
    for store in ("A", "B", "C"):  # boxed milk sold everywhere
        offers += from_product(store, product("b", "Horizon Organic Shelf Stable 1% Lowfat Milk", "12 ct / 8 fl oz", 14.99, brand="Horizon Organic"))
    offers += from_product("A", product("g", "Kroger® Vitamin D Whole Milk Gallon", "1 gal", 2.29))
    choices, _, _ = rank(offers, "milk")
    assert choices[0].variant.label() == "whole milk (store brand)"


def test_search_saves_history_and_track_records_a_basket(tmp_path, capsys):
    db = tmp_path / "p.sqlite"
    assert main(["search", "milk", "--db", str(db)], client=client()) == 0
    import sqlite3
    assert sqlite3.connect(db).execute("SELECT count(*) FROM prices").fetchone()[0] == 6
    assert main(["search", "milk", "--no-save", "--db", str(tmp_path / "none.sqlite")], client=client()) == 0
    assert not (tmp_path / "none.sqlite").exists()
    capsys.readouterr()
    assert main(["track", "milk", "eggs", "--db", str(db)], client=client()) == 0
    out = capsys.readouterr().out
    assert "milk" in out and "history now covers 1 day" in out


def test_search_shows_real_deals(tmp_path, capsys):
    from datetime import date, timedelta
    from cartcompass import history
    from cartcompass.offers import from_product
    from fake_kroger import product
    db = history.connect(tmp_path / "p.sqlite")
    for i in range(1, 8):  # the organic half gallon usually costs $4.49 in Bowling Green
        history.record(db, from_product("01600878", product("3", "Simple Truth Organic® 2% Reduced Fat Milk Half Gallon",
                                                            "1/2 gal", 4.49, brand="Simple Truth Organic")),
                       date.today() - timedelta(days=i))
    assert main(["search", "milk", "--db", str(tmp_path / "p.sqlite")], client=client()) == 0
    assert "✓ real deal: $3.99 is 11% below its usual $4.49 over 7 days" in capsys.readouterr().out
