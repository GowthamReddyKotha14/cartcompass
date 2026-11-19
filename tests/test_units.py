import pytest

from cartcompass.units import parse_size, unit_price


@pytest.mark.parametrize("text,amount,dim", [
    ("1 gal", 128, "volume"),
    ("1/2 gal", 64, "volume"),
    ("64 fl oz", 64, "volume"),
    ("1 qt", 32, "volume"),
    ("1.75 L", 59.1745, "volume"),
    ("500 ml", 16.907, "volume"),
    ("16 oz", 16, "weight"),
    ("1 lb", 16, "weight"),
    ("2.5 lbs", 40, "weight"),
    ("454 g", 16.0144, "weight"),
    ("12 ct", 12, "count"),
    ("1 dozen", 12, "count"),
    ("6 pk / 12 fl oz", 72, "volume"),
    ("12 pk / 12 fl oz", 144, "volume"),
    ("2 x 16 oz", 32, "weight"),
    ("1 1/2 lb", 24, "weight"),
    ("18 Count", 18, "count"),
])
def test_parse_size(text, amount, dim):
    q = parse_size(text)
    assert q is not None and q.dim == dim
    assert q.amount == pytest.approx(amount, rel=1e-3)


def test_fl_oz_is_volume_but_oz_is_weight():
    assert parse_size("12 fl oz").dim == "volume"
    assert parse_size("12 oz").dim == "weight"


@pytest.mark.parametrize("text", [None, "", "each item varies", "16 oz / 1 pt"])
def test_unreadable_or_ambiguous_sizes_are_refused(text):
    assert parse_size(text) is None


def test_the_half_gallon_trap():
    # Real prices, Kroger, N Main St, Bowling Green OH, November 2026.
    gallon = unit_price(2.69, "1 gal")
    half = unit_price(1.89, "1/2 gal")
    assert gallon == (2.69, "gal")
    assert half == (3.78, "gal")
    assert half[0] / gallon[0] > 1.4


def test_unit_price_needs_price_and_size():
    assert unit_price(None, "1 gal") is None
    assert unit_price(2.0, "family size") is None


def test_eggs_per_dozen():
    q = parse_size("18 ct")
    assert q.per("dozen") == pytest.approx(1.5)
