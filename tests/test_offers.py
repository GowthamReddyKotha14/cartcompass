import pytest

from cartcompass.offers import effective_price, from_product
from fake_kroger import product


def test_promo_zero_means_no_sale():
    assert effective_price({"regular": 2.69, "promo": 0}) == (2.69, 2.69, False)


def test_sale_price_is_what_you_pay():
    assert effective_price({"regular": 4.49, "promo": 3.99}) == (3.99, 4.49, True)


def test_a_promo_above_regular_is_ignored():
    assert effective_price({"regular": 3.0, "promo": 3.5}) == (3.0, 3.0, False)


def test_offer_has_unit_price():
    (o,) = from_product("S", product("2", "Kroger 2% Milk Half Gallon", "1/2 gal", 1.89))
    assert (o.unit_price, o.unit, o.amount) == (3.78, "gal", 0.5)
    assert o.available and not o.on_sale


def test_out_of_stock_is_kept_but_marked():
    (o,) = from_product("S", product("4", "Whole Milk", "1 gal", 2.79, stock="TEMPORARILY_OUT_OF_STOCK"))
    assert not o.available


def test_sold_by_weight_is_already_per_pound():
    p = product("9", "Bananas", "1 lb", 0.59, category="Produce")
    p["items"][0]["soldBy"] = "WEIGHT"
    (o,) = from_product("S", p)
    assert (o.unit_price, o.unit) == (0.59, "lb")


def test_unpriced_items_are_dropped():
    p = product("5", "Milk", "1 gal", 0)
    p["items"][0]["price"] = None
    assert from_product("S", p) == []


def test_unreadable_size_keeps_the_offer_without_unit_price():
    (o,) = from_product("S", product("6", "Party tray", "serves 10", 24.99))
    assert o.unit_price is None and o.price == pytest.approx(24.99)
