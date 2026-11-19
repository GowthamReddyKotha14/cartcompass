import pytest

from cartcompass.matching import is_store_brand, matches, variant
from cartcompass.offers import from_product
from fake_kroger import product


def offer(desc, brand="Kroger", size="1 gal", price=3.0):
    return from_product("S", product("x", desc, size, price, brand=brand))[0]


@pytest.mark.parametrize("desc,brand,ok", [
    ("Kroger® 2% Reduced Fat Milk Gallon", "Kroger", True),
    ("Simple Truth Organic® Vitamin D Whole Milk Half Gallon", "Simple Truth Organic", True),
    ("Hershey's Milk Chocolate Bar", "Hershey's", False),
    ("Carnation Sweetened Condensed Milk", "Carnation", False),
    ("Milk-Bone Original Dog Treats", "Milk-Bone", False),
    ("Kroger Bread", "Kroger", False),
])
def test_what_counts_as_milk(desc, brand, ok):
    assert matches(offer(desc, brand), "milk") is ok


def test_like_compares_with_like():
    a = variant(offer("Kroger® 2% Reduced Fat Milk Gallon"), "milk")
    b = variant(offer("Kroger® 2% Reduced Fat Milk Half Gallon", size="1/2 gal"), "milk")
    c = variant(offer("Simple Truth Organic® 2% Reduced Fat Milk", "Simple Truth Organic"), "milk")
    d = variant(offer("Kroger® Vitamin D Whole Milk Gallon"), "milk")
    assert a == b          # same milk, different size: comparable
    assert a != c          # organic is a different choice
    assert a != d          # so is whole vs 2%


def test_variant_labels_read_naturally():
    assert variant(offer("Kroger® 2% Reduced Fat Milk Gallon"), "milk").label() == "2% milk (store brand)"
    v = variant(offer("Horizon Organic Whole Milk", "Horizon Organic"), "milk")
    assert v.label() == "whole organic milk (name brand)"


def test_eggs():
    v = dict(variant(offer("Kroger® Grade A Large Cage Free Brown Eggs", size="12 ct"), "eggs").attrs)
    assert (v["size"], v["housing"], v["color"]) == ("large", "cage-free", "brown")
    assert not matches(offer("Kroger Egg Noodles", size="12 oz"), "eggs")
    assert matches(offer("Kroger Grade A Large Eggs", size="12 ct"), "egg")


def test_unknown_items_still_split_organic_and_tier():
    v = dict(variant(offer("Simple Truth Organic Bananas", "Simple Truth Organic"), "bananas").attrs)
    assert v == {"organic": "organic", "tier": "store brand"}


def test_store_brands():
    assert is_store_brand("Kroger®") and is_store_brand("Private Selection")
    assert not is_store_brand("Horizon Organic")
