"""Client for the Kroger Public API (Products and Locations).

Uses the client-credentials flow: no shopper login, read-only. Credentials come
from the environment or ~/.cartcompass.env and are never logged.

The HTTP layer is a single injectable function so tests run offline.
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

API = "https://api.kroger.com/v1"
ENV_FILE = Path.home() / ".cartcompass.env"
PAGE = 50          # the Products API returns at most 50 per call
MAX_START = 250    # and pages no further than this offset

# transport(method, url, headers, body) -> (status, parsed_json)
Transport = Callable[[str, str, dict, bytes | None], tuple[int, dict]]


class KrogerError(RuntimeError):
    pass


def load_credentials(path: Path = ENV_FILE) -> tuple[str, str]:
    cid, secret = os.environ.get("KROGER_CLIENT_ID"), os.environ.get("KROGER_CLIENT_SECRET")
    if (not cid or not secret) and path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = (s.strip() for s in line.split("=", 1))
                cid = cid or (v if k == "KROGER_CLIENT_ID" else None)
                secret = secret or (v if k == "KROGER_CLIENT_SECRET" else None)
    if not cid or not secret:
        raise KrogerError(f"Set KROGER_CLIENT_ID and KROGER_CLIENT_SECRET (environment or {path}).")
    return cid, secret


def urllib_transport(method: str, url: str, headers: dict, body: bytes | None) -> tuple[int, dict]:
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read() or b"{}")
        except ValueError:
            payload = {}
        return e.code, payload


@dataclass
class Store:
    location_id: str
    chain: str
    name: str
    address: str
    city: str
    zip: str
    lat: float | None
    lon: float | None

    @property
    def short_name(self) -> str:
        """'Kroger - Kroger Maumee' -> 'Maumee'; 'Kroger Marketplace - Perrysburg Marketplace' -> 'Perrysburg'."""
        name = self.name.split(" - ", 1)[-1]
        for junk in ("Kroger Marketplace", "Kroger", "Marketplace"):
            name = name.replace(junk, "")
        name = " ".join(name.split())
        return name or self.city or self.location_id

    @property
    def label(self) -> str:
        kind = "Kroger Marketplace" if "marketplace" in self.name.lower() else self.chain.title() or "Store"
        return f"{kind} {self.short_name}"

    @classmethod
    def from_api(cls, d: dict) -> "Store":
        a, g = d.get("address") or {}, d.get("geolocation") or {}
        return cls(d["locationId"], d.get("chain", ""), d.get("name", ""), a.get("addressLine1", ""),
                   a.get("city", ""), a.get("zipCode", ""), g.get("latitude"), g.get("longitude"))


@dataclass
class KrogerClient:
    client_id: str
    client_secret: str = field(repr=False)
    transport: Transport = urllib_transport
    sleep: Callable[[float], None] = time.sleep
    retries: int = 3
    _token: str | None = field(default=None, repr=False)
    _expires: float = 0.0
    calls: int = 0

    @classmethod
    def from_env(cls, **kw) -> "KrogerClient":
        return cls(*load_credentials(), **kw)

    def token(self) -> str:
        if self._token and time.time() < self._expires - 60:
            return self._token
        basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        status, d = self.transport("POST", f"{API}/connect/oauth2/token",
                                   {"Authorization": f"Basic {basic}",
                                    "Content-Type": "application/x-www-form-urlencoded",
                                    "Accept": "application/json"},
                                   b"grant_type=client_credentials&scope=product.compact")
        if status != 200 or "access_token" not in d:
            raise KrogerError(f"Token request failed (HTTP {status}): {d.get('error_description') or d.get('error') or d}")
        self._token, self._expires = d["access_token"], time.time() + float(d.get("expires_in", 1800))
        return self._token

    def get(self, path: str, params: dict) -> dict:
        url = f"{API}{path}?{urllib.parse.urlencode(params)}"
        for attempt in range(self.retries + 1):
            self.calls += 1
            status, d = self.transport("GET", url, {"Authorization": f"Bearer {self.token()}",
                                                    "Accept": "application/json"}, None)
            if status == 200:
                return d
            if status == 401 and attempt == 0:  # token revoked or expired early: refresh once
                self._token = None
                continue
            if status in (429, 500, 502, 503, 504) and attempt < self.retries:
                self.sleep(2 ** attempt)
                continue
            raise KrogerError(f"GET {path} failed (HTTP {status}): {d}")
        raise KrogerError(f"GET {path} failed after {self.retries} retries")

    def stores(self, zip_code: str, radius_miles: int = 10, limit: int = 20, chain: str | None = None) -> list[Store]:
        params = {"filter.zipCode.near": zip_code, "filter.radiusInMiles": radius_miles, "filter.limit": limit}
        if chain:
            params["filter.chain"] = chain
        return [Store.from_api(d) for d in self.get("/locations", params).get("data", [])]

    def products(self, term: str, location_id: str, limit: int = PAGE) -> list[dict]:
        """Search one store's catalog; pages until `limit` results or the API's offset cap."""
        out: list[dict] = []
        start = 1
        while len(out) < limit and start <= MAX_START:
            n = min(PAGE, limit - len(out))
            d = self.get("/products", {"filter.term": term, "filter.locationId": location_id,
                                       "filter.limit": n, "filter.start": start})
            page = d.get("data", [])
            out.extend(page)
            if len(page) < n:
                break
            start += n
        return out
