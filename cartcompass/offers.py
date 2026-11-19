"""Turn raw store products into comparable offers."""
from __future__ import annotations

from dataclasses import asdict, dataclass

from .units import DISPLAY, parse_size

OUT_OF_STOCK = {"TEMPORARILY_OUT_OF_STOCK", "OUT_OF_STOCK"}


@dataclass
class Offer:
    store_id: str
    product_id: str
    upc: str
    brand: str
    description: str
    category: str
    size: str
    price: float            # what you pay today (sale price if on sale)
    regular: float
    on_sale: bool
    stock: str              # HIGH | LOW | TEMPORARILY_OUT_OF_STOCK | "" (unknown)
    unit_price: float | None
    unit: str | None        # gal | lb | each
    amount: float | None    # package size in display units (e.g. 0.5 gal)

    @property
    def available(self) -> bool:
        return self.stock not in OUT_OF_STOCK

    def to_dict(self) -> dict:
        return asdict(self)


def effective_price(price: dict | None) -> tuple[float | None, float | None, bool]:
    """(pay, regular, on_sale). The API reports promo 0 when there is no sale."""
    price = price or {}
    regular, promo = price.get("regular") or None, price.get("promo") or None
    if regular and promo and promo < regular:
        return promo, regular, True
    pay = regular or promo
    return pay, pay, False


def from_product(store_id: str, p: dict) -> list[Offer]:
    """One offer per item (size) of a product that has a price."""
    out = []
    for it in p.get("items") or []:
        pay, regular, sale = effective_price(it.get("price"))
        if pay is None:
            continue  # not sold at this store
        size = it.get("size") or ""
        if (it.get("soldBy") or "").upper() == "WEIGHT":
            unit_price, unit, amount = pay, "lb", None  # priced per pound already
        else:
            q = parse_size(size)
            unit_price = unit = amount = None
            if q:
                unit = DISPLAY[q.dim][0]
                amount = q.per()
                unit_price = round(pay / amount, 4)
        out.append(Offer(store_id=store_id, product_id=p.get("productId", ""), upc=p.get("upc", ""),
                         brand=p.get("brand") or "", description=p.get("description") or "",
                         category=(p.get("categories") or [""])[0], size=size, price=pay,
                         regular=regular, on_sale=sale,
                         stock=((it.get("inventory") or {}).get("stockLevel") or ""),
                         unit_price=unit_price, unit=unit, amount=amount))
    return out
