from datetime import date, timedelta

from cartcompass.history import check, connect, record
from cartcompass.offers import from_product
from fake_kroger import product

TODAY = date(2026, 11, 19)


def offer(price, promo=0, store="S"):
    return from_product(store, product("1", "Kroger 2% Milk Gallon", "1 gal", price, promo=promo))[0]


def with_history(prices, store="S"):
    db = connect(":memory:")
    for i, p in enumerate(prices):
        record(db, [offer(p, store=store)], TODAY - timedelta(days=len(prices) - i))
    return db


def test_record_is_one_row_per_day_and_rerun_safe():
    db = connect(":memory:")
    assert record(db, [offer(2.69)], TODAY) == 1
    record(db, [offer(2.59)], TODAY)
    assert db.execute("SELECT count(*), max(price) FROM prices").fetchone() == (1, 2.59)


def test_needs_a_few_days_before_judging():
    db = with_history([2.69, 2.69])
    c = check(db, offer(2.69, promo=1.99), TODAY)
    assert c.verdict == "new" and c.days == 2


def test_real_deal_is_well_under_the_usual_price():
    db = with_history([2.69] * 10)
    c = check(db, offer(2.69, promo=1.99), TODAY)
    assert c.verdict == "real deal" and c.usual == 2.69
    assert c.describe(1.99) == "real deal: $1.99 is 26% below its usual $2.69 over 10 days"


def test_fake_sale_tag_at_the_usual_price():
    # Usually $2.49; the tag now says "regular $2.99, sale $2.49".
    db = with_history([2.49] * 8)
    c = check(db, offer(2.99, promo=2.49), TODAY)
    assert c.verdict == "not really a sale"


def test_normal_price():
    assert check(with_history([2.69] * 6), offer(2.69), TODAY).verdict == "normal price"


def test_history_is_per_store():
    db = with_history([1.99] * 8, store="OTHER")
    assert check(db, offer(2.69), TODAY).verdict == "new"


def test_old_history_falls_out_of_the_window():
    db = connect(":memory:")
    for i in range(8):
        record(db, [offer(4.00)], TODAY - timedelta(days=200 + i))
    assert check(db, offer(2.69), TODAY).verdict == "new"


def test_file_database_is_created(tmp_path):
    db = connect(tmp_path / "sub" / "prices.sqlite")
    record(db, [offer(2.69)], TODAY)
    assert (tmp_path / "sub" / "prices.sqlite").exists()
