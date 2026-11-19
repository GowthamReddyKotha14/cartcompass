"""An offline stand-in for the Kroger API, shaped like its real responses."""
from __future__ import annotations

import urllib.parse


def product(pid, desc, size, regular, promo=0, brand="Kroger", stock="HIGH", category="Dairy"):
    return {"productId": pid, "upc": pid, "brand": brand, "description": desc, "categories": [category],
            "items": [{"itemId": pid, "size": size, "soldBy": "UNIT",
                       "price": {"regular": regular, "promo": promo},
                       "inventory": {"stockLevel": stock}}]}


STORES = [
    {"locationId": "01600878", "chain": "KROGER", "name": "Kroger - Bowling Green",
     "address": {"addressLine1": "1094 N Main St", "city": "Bowling Green", "zipCode": "43402"},
     "geolocation": {"latitude": 41.3925, "longitude": -83.6513}},
    {"locationId": "01600531", "chain": "KROGER", "name": "Kroger - Waterville",
     "address": {"addressLine1": "8730 Waterville Swanton Rd", "city": "Waterville", "zipCode": "43566"},
     "geolocation": {"latitude": 41.5000, "longitude": -83.7180}},
]

CATALOG = {
    "01600878": [
        product("1", "Kroger® 2% Reduced Fat Milk Gallon", "1 gal", 2.69),
        product("2", "Kroger® 2% Reduced Fat Milk Half Gallon", "1/2 gal", 1.89),
        product("3", "Simple Truth Organic® 2% Reduced Fat Milk Half Gallon", "1/2 gal", 4.49, promo=3.99, brand="Simple Truth Organic"),
        product("4", "Kroger® Vitamin D Whole Milk Gallon", "1 gal", 2.69),
    ],
    "01600531": [
        product("1", "Kroger® 2% Reduced Fat Milk Gallon", "1 gal", 2.49),
        product("4", "Kroger® Vitamin D Whole Milk Gallon", "1 gal", 2.79, stock="TEMPORARILY_OUT_OF_STOCK"),
    ],
}


class FakeKroger:
    """Callable transport. Set `fail` to a list of statuses to return first."""

    def __init__(self, fail=None, catalog=None):
        self.fail = list(fail or [])
        self.catalog = catalog if catalog is not None else CATALOG
        self.requests = []

    def __call__(self, method, url, headers, body):
        self.requests.append((method, url))
        if url.endswith("/connect/oauth2/token"):
            return 200, {"access_token": "tok", "expires_in": 1800}
        if self.fail:
            return self.fail.pop(0), {"error": "boom"}
        path, _, query = url.partition("?")
        q = dict(urllib.parse.parse_qsl(query))
        if path.endswith("/locations"):
            return 200, {"data": STORES[: int(q.get("filter.limit", 10))]}
        if path.endswith("/products"):
            items = [p for p in self.catalog.get(q["filter.locationId"], [])
                     if all(w in p["description"].lower() for w in q["filter.term"].lower().split())]
            start, limit = int(q.get("filter.start", 1)), int(q.get("filter.limit", 50))
            return 200, {"data": items[start - 1:start - 1 + limit]}
        return 404, {}
