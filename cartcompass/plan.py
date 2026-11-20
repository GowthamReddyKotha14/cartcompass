"""Plan the cheapest trip for a whole shopping list.

For each item, the planner picks one kind (the ordinary one, or what you asked
for: "2% milk", "organic eggs") and prices one typical package of it at every
store. Then it tries every set of up to N stores, buys each item where it is
cheapest within that set, and adds the cost of driving the round trip. Two
stores only win if the groceries saved are worth more than the extra miles.
"""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from itertools import combinations

from .compare import Choice, compare
from .geo import route_miles
from .kroger import KrogerClient, Store
from .matching import TAXONOMY, family_of
from .offers import Offer

DEFAULT_PER_MILE = 0.20   # rough gas-plus-wear cost of driving a mile; change with --per-mile
DEFAULT_PER_STOP = 2.00   # what an extra store's parking, lines and time is worth to you; --per-stop


@dataclass
class Item:
    text: str                 # as written: "2% milk"
    family: str               # what to search for: "milk"
    wants: list[str]          # words the kind's label must contain: ["2%"]

    @classmethod
    def parse(cls, text: str) -> "Item":
        t = " ".join(text.lower().split())
        for fam in TAXONOMY:
            m = re.search(rf"\b{fam.rstrip('s')}s?\b", t)
            if m:
                wants = (t[:m.start()] + " " + t[m.end():]).split()
                return cls(text, fam, wants)
        return cls(text, family_of(t), [])


@dataclass
class Priced:
    """One item's chosen kind, and what one typical package costs at each store."""
    item: Item
    choice: Choice | None
    amount: float | None                      # typical package, in display units
    unit: str | None
    at: dict[str, Offer] = field(default_factory=dict)   # store -> best offer near that size

    def cost(self, store_id: str) -> float | None:
        o = self.at.get(store_id)
        return round(o.unit_price * self.amount, 2) if o else None


def pick_choice(choices: list[Choice], wants: list[str]) -> Choice | None:
    for c in choices:  # already ordered: ordinary kinds first
        label = c.variant.label().lower()
        if c.best and all(w in label for w in wants):
            return c
    return None


def price_item(item: Item, choices: list[Choice]) -> Priced:
    c = pick_choice(choices, item.wants)
    if c is None:
        return Priced(item, None, None, None)
    offers = [o for o in c.offers if o.available and o.unit_price is not None and o.amount]
    amount = statistics.mode(round(o.amount, 3) for o in offers)
    at: dict[str, Offer] = {}
    for o in offers:  # a package between half and twice the typical size counts as "one"
        if 0.5 * amount <= o.amount <= 2 * amount:
            if o.store_id not in at or o.unit_price < at[o.store_id].unit_price:
                at[o.store_id] = o
    return Priced(item, c, amount, offers[0].unit, at)


@dataclass
class Plan:
    stores: tuple[str, ...]
    buy: dict[str, str]          # item text -> store id
    groceries: float
    miles: float
    driving: float
    missing: list[str]
    stop_cost: float = 0.0       # charged for each store after the first

    @property
    def total(self) -> float:
        return round(self.groceries + self.driving + self.stop_cost * (len(self.stores) - 1), 2)


def best_plans(priced: list[Priced], stores: dict[str, Store], home: tuple[float, float],
               max_stores: int = 2, per_mile: float = DEFAULT_PER_MILE,
               per_stop: float = DEFAULT_PER_STOP) -> list[Plan]:
    where = {s.location_id: (s.lat, s.lon) for s in stores.values() if s.lat is not None}
    plans = []
    for k in range(1, max_stores + 1):
        for combo in combinations(sorted(where), k):
            buy, groceries, missing = {}, 0.0, []
            for p in priced:
                costs = [(p.cost(s), s) for s in combo if p.cost(s) is not None]
                if not costs:
                    missing.append(p.item.text)
                    continue
                cost, s = min(costs)
                buy[p.item.text] = s
                groceries += cost
            used = tuple(s for s in combo if s in buy.values())
            if len(used) < len(combo):
                continue  # a store with nothing to buy is just a detour; the smaller set covers it
            miles = route_miles(home, [where[s] for s in used])
            plans.append(Plan(used, buy, round(groceries, 2), round(miles, 1),
                              round(miles * per_mile, 2), missing, per_stop))
    plans.sort(key=lambda p: (len(p.missing), p.total))
    return plans


def plan_trip(client: KrogerClient, items: list[str], zip_code: str, home: tuple[float, float],
              radius_miles: int = 15, max_stores: int = 2, per_mile: float = DEFAULT_PER_MILE,
              stores: int = 5, depth: int = 150, extra=None, per_stop: float = DEFAULT_PER_STOP):
    parsed = [Item.parse(t) for t in items]
    priced, all_stores, offers = [], {}, []
    for it in parsed:
        c = compare(client, it.family, zip_code, radius_miles, stores, depth, extra)
        all_stores.update(c.stores)
        offers += [o for ch in c.choices for o in ch.offers]
        priced.append(price_item(it, c.choices))
    return priced, all_stores, best_plans(priced, all_stores, home, max_stores, per_mile, per_stop), offers
