"""Find the cheapest real substitute for an item across nearby stores."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .kroger import KrogerClient, Store
from .matching import Variant, apply_unit, matches, variant
from .offers import Offer, from_product


@dataclass
class Choice:
    """One kind of product (e.g. store-brand 2% milk) and its offers, cheapest first."""
    variant: Variant
    offers: list[Offer]

    @property
    def best(self) -> Offer | None:
        return next((o for o in self.offers if o.available and o.unit_price is not None), None)

    def best_per_store(self) -> list[Offer]:
        seen, out = set(), []
        for o in self.offers:
            if o.store_id not in seen and o.available and o.unit_price is not None:
                seen.add(o.store_id)
                out.append(o)
        return out


@dataclass
class Comparison:
    query: str
    stores: dict[str, Store]
    choices: list[Choice]
    skipped: int = 0            # products returned by the search that were not the item
    unpriced: int = 0           # matching products without a readable unit price
    searched: list[str] = field(default_factory=list)


def rank(offers: list[Offer], query: str) -> tuple[list[Choice], int, int]:
    kept = [apply_unit(o, query) for o in offers if matches(o, query)]
    skipped = len(offers) - len(kept)
    unpriced = sum(o.unit_price is None for o in kept)
    groups: dict[Variant, list[Offer]] = defaultdict(list)
    for o in kept:
        groups[variant(o, query)].append(o)
    key = lambda o: (not o.available, o.unit_price is None, o.unit_price or 0, o.price)
    choices = [Choice(v, sorted(os, key=key)) for v, os in groups.items()]
    # Ordinary kinds first (a plain gallon before shelf-stable boxes), then the most
    # widely sold, then the cheapest.
    choices.sort(key=lambda c: (c.variant.plainness, -len({o.store_id for o in c.offers}),
                                c.best.unit_price if c.best else float("inf")))
    return choices, skipped, unpriced


def compare(client: KrogerClient, query: str, zip_code: str, radius_miles: int = 10,
            max_stores: int = 5, per_store: int = 50) -> Comparison:
    stores = client.stores(zip_code, radius_miles=radius_miles, limit=max_stores)
    offers: list[Offer] = []
    for s in stores:
        for p in client.products(query, s.location_id, limit=per_store):
            offers.extend(from_product(s.location_id, p))
    choices, skipped, unpriced = rank(offers, query)
    return Comparison(query, {s.location_id: s for s in stores}, choices, skipped, unpriced,
                      [s.location_id for s in stores])
