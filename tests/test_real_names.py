"""Regression tests from real Kroger listings near Bowling Green, OH (November 2026).

Each case is a product name and size exactly as the store's API returned it, with
the kind it should be compared as (or None: not the item searched for).
"""
import pytest

from cartcompass.compare import rank
from cartcompass.matching import apply_unit, matches, variant
from cartcompass.offers import from_product
from fake_kroger import product


def offer(desc, size, brand="", price=3.0):
    return from_product("S", product("x", desc, size, price, brand=brand))[0]


def kind(query, desc, size, brand=""):
    o = offer(desc, size, brand)
    return variant(o, query).label() if matches(o, query) else None


@pytest.mark.parametrize("desc,size,brand,expected", [
    ("Horizon Organic Vitamin D Nonfat Milk - Vitamin D Milk", "1/2 gal", "Horizon Organic", "skim organic milk (name brand)"),
    ("Horizon Organic DHA Omega-3 Milk - DHA 2 Percent Milk", "1/2 gal", "Horizon Organic", "2% organic milk (name brand)"),
    ("Kroger® Vitamin D Whole Milk 16 fl. oz. Bottle", "1 pt", "Kroger", "whole single-serve milk (store brand)"),
    ("Kroger® Vitamin D Whole Milk Gallon", "1 gal", "Kroger", "whole milk (store brand)"),
    ("Simple Truth Organic® 1% Lowfat Milk Bottles", "12 bottles / 8 fl oz", "Simple Truth Organic", "1% multipack organic milk (store brand)"),
    ("Simple Truth Organic® Low Fat Chocolate Milk", "12 ct / 8 fl oz", "Simple Truth Organic", "1% chocolate multipack organic milk (store brand)"),
    ("fairlife® Whole Ultra-Filtered Milk Bottle", "52 fl oz", "fairlife", "whole lactose-free milk (name brand)"),
])
def test_real_milk(desc, size, brand, expected):
    assert kind("milk", desc, size, brand) == expected


@pytest.mark.parametrize("desc,size,brand,expected", [
    ("Kroger® Grade A Large White Eggs", "18 ct", "Kroger", "large eggs (store brand)"),
    # The store lists these non-organic eggs under its organic brand.
    ("Simple Truth® Cage Free Grade A Large Brown Eggs", "18 ct", "Simple Truth Organic", "large cage-free brown eggs (store brand)"),
    # ...and these organic eggs under a different store brand.
    ("Simple Truth Organic® Pasture Raised Large Brown Eggs", "12 ct", "Private Selection", "large pasture-raised brown organic eggs (store brand)"),
    ("Simple Truth™ Natural Cage Free Grade A Large Brown Eggs", "18 ct / 36 oz", "Simple Truth", "large cage-free brown eggs (store brand)"),
    ("Kroger® Deli Kitchen Peeled Hard-Cooked Eggs", "6 ct", "Kroger", None),
    ("Eggland's Best Hard Cooked Eggs, Medium White", "6 count", "Eggland's Best", None),
    ("Just Egg Folded, Plant-Based Egg, 4 Ct", "8 oz", "Just Egg", None),
    ("Just Crack An Egg Classic Breakfast Scramble Breakfast Bowl Kit", "3 oz", "Just Crack An Egg", None),
])
def test_real_eggs(desc, size, brand, expected):
    assert kind("eggs", desc, size, brand) == expected


def test_eggs_are_priced_per_dozen_even_when_weight_is_listed():
    o = apply_unit(offer("Simple Truth™ Natural Cage Free Grade A Large Brown Eggs", "18 ct / 36 oz", price=5.10), "eggs")
    assert (o.unit, o.unit_price) == ("doz", 3.4)


@pytest.mark.parametrize("desc,size,brand,expected", [
    ("Kroger® White Bread", "20 oz", "Kroger", "white bread (store brand)"),
    ("Kroger® Honey Wheat Bread", "20 oz", "Kroger", "bread (store brand)"),
    ("Nature's Own 100% Whole Wheat Bread", "20 oz", "Nature's Own", "whole wheat bread (name brand)"),
    ("Simple Truth Organic® White Bread", "26 oz", "Simple Truth Organic", "white organic bread (store brand)"),
    ("Food for Life® Ezekiel 4:9® Sprouted Grain Frozen Bread", "24 oz", "Food for Life", "multigrain frozen bread (name brand)"),
    ("Base Culture Keto Frozen Bread", "16 oz", "Base Culture", "frozen bread (name brand)"),
    ("Brazi Bites® Cheddar & Parmesan Brazilian Frozen Bread", "11.5 oz", "Brazi Bites", None),
    ("Julian's® Recipe Butter Garlic Baguette Frozen Bread", "2 ct / 12.35 oz", "Julian's", None),
    ("Dave's Killer Bread Rockin' Grains English Muffins Organic Whole Grain", "6 ct", "Dave's Killer Bread", None),
])
def test_real_bread(desc, size, brand, expected):
    assert kind("bread", desc, size, brand) == expected


def test_white_bread_and_other_bread_get_different_labels():
    offers = [offer("Kroger® White Bread", "20 oz", "Kroger"), offer("Kroger® Honey Wheat Bread", "20 oz", "Kroger")]
    labels = [c.variant.label() for c in rank(offers, "bread")[0]]
    assert len(labels) == len(set(labels)) == 2


@pytest.mark.parametrize("query,desc,size,brand,expected", [
    # Real listings that a 150-deep search returned for these words (November 2026).
    ("butter", "Bakery Fresh Peanut Butter Cookies", "12 count", "Bakery Fresh", None),
    ("butter", "Kroger® Salted Butter Sticks", "16 oz", "Kroger", "salted butter (store brand)"),
    ("butter", "Land O Lakes® Unsalted Butter Sticks", "16 oz", "Land O Lakes", "unsalted butter (name brand)"),
    ("butter", "I Can't Believe It's Not Butter! Original Spread", "15 oz", "ICBINB", "spread butter (name brand)"),
    ("chicken breast", "Tyson Frozen Stuffed Chicken Breasts Cordon Bleu", "2 count", "Tyson", None),
    ("chicken breast", "Kroger® Boneless Skinless Chicken Breasts", "3 lb", "Kroger", "chicken breast (store brand)"),
    ("chicken breast", "Kroger® Frozen Boneless Skinless Chicken Breasts", "3 lb", "Kroger", "frozen chicken breast (store brand)"),
    ("bananas", "Kroger® Frozen Sliced Bananas", "16 oz", "Kroger", None),
    ("bananas", "Fresh Banana - Each", "1 each", "", "bananas (name brand)"),
    ("bread", "Smart Way™ Enriched White Bread", "16 oz", "Smart Way", "white bread (store brand)"),
])
def test_real_everyday_items(query, desc, size, brand, expected):
    assert kind(query, desc, size, brand) == expected
