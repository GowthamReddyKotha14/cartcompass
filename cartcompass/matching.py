"""Decide which products are the thing you asked for, and which are alike.

"milk" should not match milk chocolate, and 2% milk should not be compared with
organic whole milk. Matching is rule-based and transparent: a small taxonomy for
common staples, and a generic fallback (organic, store vs. name brand) for
everything else. Each rule is a plain list so it can be audited and extended.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .units import parse_count, parse_size

STORE_BRANDS = {
    # Kroger
    "kroger", "simple truth", "simple truth organic", "private selection", "heritage farm", "big k", "smart way",
    "home sense", "comforts", "psst",
    # Walmart
    "great value", "marketside", "sam's choice", "freshness guaranteed",
    # ALDI
    "friendly farms", "goldhen", "l'oven fresh", "simply nature", "never any!", "kirkwood",
    "specially selected", "happy farms", "millville", "clancy's", "southern grove",
    # Meijer
    "meijer", "true goodness", "frederik's",
}

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
            # Most specific first: "Vitamin D Nonfat Milk" is skim, not whole.
            "fat": [("skim", r"\bskim\b|fat[- ]free|non[- ]?fat"),
                    ("2%", r"\b2\s?(%|percent)|reduced[- ]fat"),
                    ("1%", r"\b1\s?(%|percent)|low[- ]?fat"),
                    ("whole", r"\bwhole\b|vitamin d milk")],
        },
        "default": {"type": "regular", "format": "fresh"},
        "single_serve_fl_oz": 16,   # a 1 pt bottle is not a substitute for a gallon jug
    },
    "eggs": {
        "reject": [r"\begg ?nog\b", r"\begg noodles?\b", r"\begg rolls?\b", r"\begg whites?\b",
                   r"\beggs? substitute", r"\bplastic\b", r"\bdye\b", r"\bsalad\b", r"\bbites\b",
                   r"hard[- ](cooked|boiled)", r"\bpeeled\b", r"\bscramble", r"\bkit\b", r"\bjust egg\b",
                   r"plant[- ]based", r"\bdeviled\b", r"\bsandwich", r"\bpatt(y|ies)\b", r"\bomelet"],
        "unit": "dozen",            # "12 ct / 24 oz" eggs compare by count, not weight
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
        "reject": [r"\bcrumbs\b", r"\bpudding\b", r"\bmix\b", r"\bsticks\b", r"\bbowl\b",
                   r"\bmuffins?\b", r"\bbagels?\b", r"\bbuns?\b", r"\brolls?\b", r"\bcroutons?\b",
                   r"\bstuffing\b", r"\bbites\b", r"cheese bread", r"\bgarlic\b", r"\bbaguette",
                   r"\bpita\b", r"\bnaan\b", r"\btortilla"],
        "attrs": {"grain": [("whole wheat", r"whole wheat|100% wheat"), ("sourdough", r"sourdough"),
                            ("multigrain", r"multi[- ]?grain|whole grain|sprouted|grains"),
                            ("white", r"\bwhite\b")],
                  "format": [("frozen", r"\bfrozen\b"), ("keto", r"\bketo\b|low[- ]carb")]},
        "default": {"format": "fresh"},
    },
    "butter": {
        "reject": [r"peanut butter", r"\b(apple|almond|cashew|nut|seed|cookie|body|cocoa|shea|sunflower|pumpkin)\s+butter",
                   r"\bcookies?\b", r"\bpopcorn\b", r"\bcrackers?\b", r"\bcake\b", r"\bbiscuits?\b",
                   r"\bcroissants?\b", r"\bbuttermilk\b", r"\bbutterscotch\b", r"butter beans?", r"\bcandy\b",
                   r"\bcups?\b", r"\bsauce\b", r"\bbread\b", r"\brolls?\b", r"\bcroutons?\b", r"\bflavou?red\b",
                   r"\bpecan\b", r"\btoffee\b", r"\bspray\b", r"\bpasta\b", r"\brice\b", r"\bpotatoes\b",
                   r"\bbutterfinger\b", r"\bbutterball\b"],
        "attrs": {"salt": [("unsalted", r"unsalted|sweet cream unsalted"), ("salted", r"\bsalted\b")],
                  "format": [("spread", r"\bspread|spreadable|\btub\b|whipped|i can'?t believe"),
                             ("plant-based", r"plant[- ]based|vegan|\boat\b|olive oil")]},
        "default": {"format": "sticks"},
    },
    "chicken breast": {
        "reject": [r"\bstuffed\b", r"\bbreaded\b", r"\bnuggets?\b", r"\bstrips?\b", r"\bpatt(y|ies)\b",
                   r"cordon bleu", r"\bkiev\b", r"fully cooked", r"\bgrilled\b", r"\brotisserie\b",
                   r"\bsandwich", r"\bsoup\b", r"\bbroth\b", r"\b(dog|cat|pet)\b", r"\bdeli\b",
                   r"\blunch\s*meat\b", r"\bcanned\b", r"\bchunk\b", r"\bcan\b", r"\bbites\b", r"\bwings?\b",
                   r"\bmeal\b", r"\bbowl\b", r"\bsalad\b", r"\bslices?\b", r"\bjerky\b", r"\bseasoning\b",
                   r"\bbuffalo\b", r"\bteriyaki\b", r"\bmarinated\b", r"\bfrozen\b.*\bfritters?\b"],
        "attrs": {"cut": [("tenderloins", r"tenderloin|tenders"), ("thin-sliced", r"thin[- ](sliced|cut)")],
                  "format": [("frozen", r"\bfrozen\b|individually (frozen|wrapped)|\biqf\b")],
                  "raising": [("air-chilled", r"air[- ]chilled"), ("free-range", r"free[- ]range|pasture")]},
        "default": {"format": "fresh"},
    },
    "bananas": {
        "reject": [r"\bchips?\b", r"\bbread\b", r"\bpudding\b", r"\bpeppers?\b", r"\bcream\b",
                   r"\bdried\b", r"\bbaby\b", r"\bflavou?red\b", r"\bsmoothie\b", r"\bsplit\b", r"\bmuffins?\b",
                   r"\bcereal\b", r"\bpopsicles?\b", r"\bbars?\b", r"\btaffy\b", r"\bcandy\b", r"\bnut\b",
                   r"\bfrozen\b", r"\bsliced\b", r"\bpuree\b", r"\bpouch(es)?\b", r"\bpancake",
                   # mixes and snacks that merely contain banana
                   r"\bmix\b", r"\btrail\b", r"\bsnacks?\b", r"\bgranola\b", r"\byogh?urt\b", r"\boatmeal\b",
                   r"\bjuice\b", r"\bberr(y|ies)\b", r"\band\s+banana|banana\s+and\b", r"\bcrisps?\b"],
        "attrs": {"kind": [("plantains", r"plantain"), ("baby", r"\bbaby\b|\bmanzano\b|\bred bananas?\b")]},
        "default": {},
    },
}

# Attribute values that describe the ordinary version of an item; not shown in labels.
PLAIN = {("type", "regular"), ("format", "fresh"), ("format", "sticks"), ("housing", "caged"),
         ("color", "white"), ("organic", "conventional"), ("pack", "single")}

# Reading order for labels: "1% shelf-stable multipack organic milk".
LABEL_ORDER = ["size", "fat", "salt", "cut", "grain", "type", "kind", "housing", "color", "raising", "format",
               "pack", "organic"]

ALIASES = {"egg": "eggs", "dozen eggs": "eggs", "2% milk": "milk", "whole milk": "milk",
           "loaf of bread": "bread"}


# "12 ct / 8 fl oz", "6 pk / 12 oz", "2 x 16 oz": several packages sold together
_MULTIPACK = re.compile(r"\d+\s*(ct|pk|packs?|count|bottles?|cans?|boxes|pouches)\s*/|\d+\s*x\s*\d")


@dataclass(frozen=True)
class Variant:
    family: str
    attrs: tuple[tuple[str, str], ...]

    @property
    def plainness(self) -> int:
        """How many ways this differs from the ordinary item (0 = plain 2% milk jug)."""
        return sum((k, v) not in PLAIN for k, v in self.attrs
                   if k not in ("tier", "fat", "size", "grain", "salt", "cut"))

    def label(self) -> str:
        attrs = dict(self.attrs)
        parts = [attrs[k] for k in LABEL_ORDER if k in attrs and (k, attrs[k]) not in PLAIN]
        tier = dict(self.attrs).get("tier")
        name = " ".join(parts + [self.family]) if parts else self.family
        return f"{name} ({tier})" if tier else name


def family_of(query: str) -> str:
    q = query.strip().lower()
    return ALIASES.get(q, q)


def _text(o) -> str:
    return f"{o.brand} {o.description}".lower()


def is_store_brand(brand: str) -> bool:
    b = (brand or "").lower().replace("®", "").replace("™", "").strip()
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
    desc = (o.description or "").lower().replace("®", "").replace("™", "")
    if rules.get("unit") != "dozen":  # eggs: "12 ct / 24 oz" is one carton, not a multipack
        q = parse_size(o.size)
        if _MULTIPACK.search((o.size or "").lower()):
            found["pack"] = "multipack"
        elif q and q.dim == "volume" and q.amount <= rules.get("single_serve_fl_oz", 0):
            found["pack"] = "single-serve"
        else:
            found["pack"] = "single"
    # The store's brand field is sometimes wrong (non-organic eggs listed under an
    # organic brand), so organic and store-brand are read from the product name too.
    found["organic"] = "organic" if "organic" in desc else "conventional"
    store = is_store_brand(o.brand) or any(desc.startswith(b) for b in STORE_BRANDS)
    found["tier"] = "store brand" if store else "name brand"
    return Variant(fam, tuple(sorted(found.items())))


def apply_unit(o, query: str):
    """Re-price an offer in the unit people compare this item by (eggs: per dozen)."""
    if TAXONOMY.get(family_of(query), {}).get("unit") == "dozen":
        n = parse_count(o.size)
        if n:
            o.amount, o.unit, o.unit_price = n / 12, "doz", round(o.price / n * 12, 4)
    return o
