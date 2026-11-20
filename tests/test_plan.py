import pytest

from cartcompass.compare import rank
from cartcompass.kroger import Store
from cartcompass.offers import from_product
from cartcompass.plan import Item, best_plans, price_item
from fake_kroger import product

HOME = (41.375, -83.650)
NEAR = Store("NEAR", "KROGER", "Kroger - Near", "", "Bowling Green", "", 41.385, -83.650)   # ~0.9 mi away
FAR = Store("FAR", "KROGER", "Kroger - Far", "", "Perrysburg", "", 41.540, -83.630)        # ~15 mi away
STORES = {s.location_id: s for s in (NEAR, FAR)}


def offers(store, *rows):
    out = []
    for desc, size, price in rows:
        out += from_product(store, product(desc, desc, size, price))
    return out


def priced(query, *offer_lists):
    choices, _, _ = rank([o for ol in offer_lists for o in ol], Item.parse(query).family)
    return price_item(Item.parse(query), choices)


def test_item_parsing():
    assert (Item.parse("2% milk").family, Item.parse("2% milk").wants) == ("milk", ["2%"])
    assert Item.parse("organic eggs").wants == ["organic"]
    assert Item.parse("egg").family == "eggs"
    assert Item.parse("bananas").family == "bananas"


def test_typical_package_and_per_store_cost():
    p = priced("milk",
               offers("NEAR", ("Kroger 2% Reduced Fat Milk Gallon", "1 gal", 2.69),
                      ("Kroger 2% Reduced Fat Milk Half Gallon", "1/2 gal", 1.89),
                      ("Kroger 2% Reduced Fat Milk 16 fl. oz. Bottle", "1 pt", 1.69)),
               offers("FAR", ("Kroger 2% Reduced Fat Milk Gallon", "1 gal", 2.29)))
    assert (p.amount, p.unit) == (1.0, "gal")
    assert p.cost("NEAR") == 2.69 and p.cost("FAR") == 2.29


def test_asked_for_kind_is_respected():
    p = priced("organic milk",
               offers("NEAR", ("Kroger 2% Reduced Fat Milk Gallon", "1 gal", 2.69),
                      ("Simple Truth Organic 2% Reduced Fat Milk Half Gallon", "1/2 gal", 3.99)))
    assert "organic" in p.choice.variant.label()


def test_small_savings_are_not_worth_the_drive():
    milk = priced("milk", offers("NEAR", ("Kroger 2% Milk Gallon", "1 gal", 2.69)),
                  offers("FAR", ("Kroger 2% Milk Gallon", "1 gal", 2.29)))
    best = best_plans([milk], STORES, HOME, max_stores=2, per_mile=0.20)[0]
    assert best.stores == ("NEAR",)  # 40 cents saved, ~$7 of driving


def test_big_savings_justify_a_longer_drive():
    rows = [("Kroger Grade A Large Eggs", "60 ct", 30.0)]
    eggs = priced("eggs", offers("NEAR", *rows), offers("FAR", ("Kroger Grade A Large Eggs", "60 ct", 9.0)))
    best = best_plans([eggs], STORES, HOME, max_stores=2, per_mile=0.20)[0]
    assert best.stores == ("FAR",)
    assert best.groceries == 9.0 and best.driving == pytest.approx(best.miles * 0.20, abs=0.02)


def test_two_store_split():
    milk = priced("milk", offers("NEAR", ("Kroger 2% Milk Gallon", "1 gal", 2.69)),
                  offers("FAR", ("Kroger 2% Milk Gallon", "1 gal", 9.99)))
    eggs = priced("eggs", offers("NEAR", ("Kroger Grade A Large Eggs", "12 ct", 9.99)),
                  offers("FAR", ("Kroger Grade A Large Eggs", "12 ct", 1.00)))
    plans = best_plans([milk, eggs], STORES, HOME, max_stores=2, per_mile=0.01)
    assert plans[0].stores == ("FAR", "NEAR") or set(plans[0].stores) == {"FAR", "NEAR"}
    assert plans[0].buy == {"milk": "NEAR", "eggs": "FAR"}


def test_plans_that_get_everything_come_first():
    milk = priced("milk", offers("FAR", ("Kroger 2% Milk Gallon", "1 gal", 2.69)))
    eggs = priced("eggs", offers("NEAR", ("Kroger Grade A Large Eggs", "12 ct", 2.0)),
                  offers("FAR", ("Kroger Grade A Large Eggs", "12 ct", 2.5)))
    best = best_plans([milk, eggs], STORES, HOME, max_stores=1)[0]
    assert best.stores == ("FAR",) and not best.missing


def test_a_second_stop_must_save_more_than_it_costs_in_time():
    milk = priced("milk", offers("NEAR", ("Kroger 2% Milk Gallon", "1 gal", 2.69)),
                  offers("FAR", ("Kroger 2% Milk Gallon", "1 gal", 2.99)))
    eggs = priced("eggs", offers("NEAR", ("Kroger Grade A Large Eggs", "12 ct", 2.49)),
                  offers("FAR", ("Kroger Grade A Large Eggs", "12 ct", 2.00)))
    # Splitting saves 30 cents over the cheaper single store, with driving free (per_mile=0).
    assert len(best_plans([milk, eggs], STORES, HOME, per_mile=0, per_stop=2.0)[0].stores) == 1
    assert len(best_plans([milk, eggs], STORES, HOME, per_mile=0, per_stop=0.1)[0].stores) == 2
