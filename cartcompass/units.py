"""Parse package sizes into comparable quantities and unit prices.

Store size strings are free text: "1 gal", "1/2 gal", "64 fl oz", "12 ct",
"6 pk / 12 fl oz", "2 x 16 oz", "1.75 l". Each parses to one of three
dimensions, in a fixed base unit:

    volume  US fluid ounces
    weight  ounces (avoirdupois)
    count   items

Plain "oz" is weight; liquids are sold in "fl oz". Prices are then compared per
display unit: per gallon, per pound, or per item (eggs per dozen).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction

# unit word -> (dimension, base units per one of this unit)
UNITS: dict[str, tuple[str, float]] = {}
for names, dim, factor in [
    (("fl oz", "fl. oz", "fl.oz", "floz", "fluid ounce", "fluid ounces"), "volume", 1.0),
    (("gal", "gallon", "gallons"), "volume", 128.0),
    (("qt", "quart", "quarts"), "volume", 32.0),
    (("pt", "pint", "pints"), "volume", 16.0),
    (("cup", "cups"), "volume", 8.0),
    (("l", "liter", "liters", "litre", "litres", "ltr"), "volume", 33.814),
    (("ml", "milliliter", "milliliters", "millilitre"), "volume", 0.033814),
    (("oz", "ounce", "ounces", "wt oz", "net wt oz"), "weight", 1.0),
    (("lb", "lbs", "pound", "pounds"), "weight", 16.0),
    (("g", "gram", "grams"), "weight", 0.035274),
    (("kg", "kilogram", "kilograms"), "weight", 35.274),
    (("ct", "count", "each", "ea", "pc", "pcs", "piece", "pieces", "pk", "pack", "eggs", "rolls", "bags"), "count", 1.0),
    (("dozen", "dz", "doz"), "count", 12.0),
]:
    for n in names:
        UNITS[n] = (dim, factor)

# Longest names first so "fl oz" wins over "oz" and "kg" over "g".
_UNIT_RE = "|".join(sorted((re.escape(u) for u in UNITS), key=len, reverse=True))
_NUM = r"(\d+\s+\d+/\d+|\d+/\d+|\d*\.\d+|\d+)"
_PART = re.compile(rf"{_NUM}\s*-?\s*({_UNIT_RE})\.?(?![a-z])", re.I)
_MULT = re.compile(rf"^\s*{_NUM}\s*(?:x|×)\s*(.+)$", re.I)

# How each dimension is shown to people.
DISPLAY = {"volume": ("gal", 128.0), "weight": ("lb", 16.0), "count": ("each", 1.0)}


@dataclass(frozen=True)
class Quantity:
    amount: float  # in base units (fl oz, oz, items)
    dim: str       # "volume" | "weight" | "count"

    def per(self, unit: str | None = None) -> float:
        """Amount expressed in a display unit (default for the dimension)."""
        name, factor = DISPLAY[self.dim] if unit is None else (unit, _factor(unit, self.dim))
        return self.amount / factor


def _factor(unit: str, dim: str) -> float:
    if unit == "dozen" and dim == "count":
        return 12.0
    d, f = UNITS[unit.lower()]
    if d != dim:
        raise ValueError(f"{unit} is not a {dim} unit")
    return f


def _num(s: str) -> float:
    s = s.strip()
    if " " in s:  # mixed number "1 1/2"
        whole, frac = s.split()
        return float(int(whole) + Fraction(frac))
    return float(Fraction(s)) if "/" in s else float(s)


def parse_size(text: str | None) -> Quantity | None:
    """Parse a package size, or None if it can't be read reliably.

    Multipacks multiply: "6 pk / 12 fl oz" and "2 x 16 oz" are 72 fl oz and 32 oz.
    When both a count and a measure appear, the measure wins, so a 12-pack of cans
    compares by volume with a 2-liter bottle.
    """
    if not text:
        return None
    t = text.lower().replace("–", "-").strip()
    mult = 1.0
    m = _MULT.match(t)
    if m:
        mult, t = _num(m.group(1)), m.group(2)
    parts = [(_num(n), UNITS[u.lower()]) for n, u in _PART.findall(t)]
    if not parts:
        return None
    measures = [(n, d, f) for n, (d, f) in parts if d != "count"]
    counts = [n * f for n, (d, f) in parts if d == "count"]
    if measures:
        dims = {d for _, d, _ in measures}
        if len(dims) > 1:  # e.g. "16 oz / 1 pt": ambiguous, refuse rather than guess
            return None
        n, d, f = measures[-1]  # the per-item measure comes last ("6 pk / 12 fl oz")
        packs = counts[0] if counts and len(parts) > 1 else 1.0
        amount = n * f * packs * mult
    else:
        d, amount = "count", counts[0] * mult
    return Quantity(round(amount, 6), d) if amount > 0 else None


def unit_price(price: float | None, size: str | None) -> tuple[float, str] | None:
    """Price per display unit, e.g. (2.69, "gal") for a $2.69 gallon."""
    q = parse_size(size)
    if price is None or q is None:
        return None
    name, _ = DISPLAY[q.dim]
    return round(price / q.per(), 4), name
