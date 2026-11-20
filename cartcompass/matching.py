"""Decide which products are the thing you asked for, and which are alike.

"milk" should not match milk chocolate, and 2% milk should not be compared with
organic whole milk. Matching is rule-based and transparent: a small taxonomy for
common staples, and a generic fallback (organic, store vs. name brand) for
everything else. Each rule is a plain list so it can be audited and extended.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

STORE_BRANDS = {"kroger", "simple truth", "simple truth organic", "private selection",
                "heritage farm", "big k", "home sense", "comforts", "psst"}

# family -> how to spot it, what to reject, and which attributes make variants
TAXONOMY: dict[str, dict] = {
    "milk": {
        "reject": [r"milk chocolate", r"\bcondensed\b", r"\bevaporated\b", r"\bpowder", r"\bdry milk\b",
                   r"\bbuttermilk\b", r"\bcoconut milk\b", r"\bmilk[- ]?bone", r"\b(dog|cat|pet)\b", r"\bcreamer\b", r"\bshake\b",
                   r"\bcereal\b", r"\bbar\b", r"\bsoap\b", r"\blotion\b"],
        "attrs": {
            "type": [("almond", r"\balmond"), ("oat", r"\boat\b"), ("soy", r"\bsoy"),
                     ("lactose-free", r"lactose[- ]free|lactaid|fairlife"),
                     ("chocolate", r"\bchocolate\b"), ("strawberry", r"\bstrawberry\b")],
            "format": [("shelf-stable", r"shelf[- ]stable|\baseptic\b|\buht\b")],
            "fat": [("whole", r"\bwhole\b|vitamin d milk"), ("2%", r"\b2\s?%"), ("1%", r"\b1\s?%"),
                    ("skim", r"\bskim\b|fat[- ]free|nonfat")],
        },
        "default": {"type": "regular", "format": "fresh"},
    },
    "eggs": {
        "reject": [r"\begg ?nog\b", r"\begg noodles?\b", r"\begg rolls?\b", r"\begg whites?\b",
                   r"\beggs? substitute", r"\bplastic\b", r"\bdye\b", r"\bsalad\b", r"\bbites\b"],
        "attrs": {
            "size": [("jumbo", r"\bjumbo\b"), ("extra large", r"extra[- ]large|\bxl\b"),
                     ("large", r"\blarge\b"), ("medium", r"\bmedium\b")],
            "housing": [("pasture-raised", r"pasture"), ("free-range", r"free[- ]range"),
                        ("cage-free", r"cage[- ]free")],
            "color": [("brown", r"\bbrown\b")],
        },
        "default": {"housing": "caged", "color": "white"},
    },
    "bread": {
        "reject": [r"\bcrumbs\b", r"\bpudding\b", r"\bmix\b", r"\bsticks\b", r"\bbowl\b"],
        "attrs": {"grain": [("whole wheat", r"whole wheat|100% wheat"), ("white", r"\bwhite\b"),
                            ("multigrain", r"multi[- ]?grain|grain"), ("sourdough", r"sourdough")]},
        "default": {},
    },
}

# Attribute values that describe the ordinary version of an item; not shown in labels.
PLAIN = {"regular", "fresh", "caged", "white", "conventional", "single"}

# Reading order for labels: "1% shelf-stable multipack organic milk".
LABEL_ORDER = ["size", "fat", "grain", "type", "housing", "color", "format", "pack", "organic"]

ALIASES = {"egg": "eggs", "dozen eggs": "eggs", "2% milk": "milk", "whole milk": "milk",
           "loaf of bread": "bread"}


# "12 ct / 8 fl oz", "6 pk / 12 oz", "2 x 16 oz": several packages sold together
_MULTIPACK = re.compile(r"\d+\s*(ct|pk|pack|count)\s*/|\d+\s*x\s*\d")


@dataclass(frozen=True)
class Variant:
    family: str
    attrs: tuple[tuple[str, str], ...]

    @property
    def plainness(self) -> int:
        """How many ways this differs from the ordinary item (0 = plain 2% milk jug)."""
        return sum(v not in PLAIN for k, v in self.attrs if k not in ("tier", "fat", "size", "grain"))

    def label(self) -> str:
        attrs = dict(self.attrs)
        parts = [attrs[k] for k in LABEL_ORDER if k in attrs and attrs[k] not in PLAIN]
        tier = dict(self.attrs).get("tier")
        name = " ".join(parts + [self.family]) if parts else self.family
        return f"{name} ({tier})" if tier else name


def family_of(query: str) -> str:
    q = query.strip().lower()
    return ALIASES.get(q, q)


def _text(o) -> str:
    return f"{o.brand} {o.description}".lower()


def is_store_brand(brand: str) -> bool:
    b = (brand or "").lower().replace("®", "").strip()
    return b in STORE_BRANDS or b.startswith("kroger")


def matches(o, query: str) -> bool:
    """True if this offer is the product asked for, not something that mentions it."""
    fam = family_of(query)
    text = _text(o).replace("®", "")
    words = [w for w in re.split(r"\s+", fam) if w]
    stem = lambda w: w[:-1] if w.endswith("s") and len(w) > 3 else w
    if not all(re.search(rf"\b{re.escape(stem(w))}", text) for w in words):
        return False
    rules = TAXONOMY.get(fam)
    return not (rules and any(re.search(r, text) for r in rules["reject"]))


def variant(o, query: str) -> Variant:
    fam = family_of(query)
    text = _text(o).replace("®", "")
    rules = TAXONOMY.get(fam, {"attrs": {}, "default": {}})
    found = dict(rules.get("default", {}))
    for attr, options in rules["attrs"].items():
        for value, pattern in options:
            if re.search(pattern, text):
                found[attr] = value
                break
    found["pack"] = "multipack" if _MULTIPACK.search((o.size or "").lower()) else "single"
    found["organic"] = "organic" if "organic" in text else "conventional"
    found["tier"] = "store brand" if is_store_brand(o.brand) else "name brand"
    return Variant(fam, tuple(sorted(found.items())))
