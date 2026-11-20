"""Where you start from, and how far each store is.

Home is either given as "lat,lon" or taken as the center of a ZIP code, from the
U.S. Census Bureau's ZIP Code Tabulation Area gazetteer (public domain), which
is downloaded once into data/.

Driving distance is estimated as straight-line distance times a road factor.
That is an approximation, stated wherever it is used; it avoids sending your
location to a routing service.
"""
from __future__ import annotations

import io
import math
import urllib.request
import zipfile
from pathlib import Path

GAZETTEER_URL = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_zcta_national.zip"
GAZETTEER = Path("data/zcta_centroids.tsv")
ROAD_FACTOR = 1.3   # typical ratio of road distance to straight-line distance in towns


def haversine_miles(a: tuple[float, float], b: tuple[float, float]) -> float:
    (lat1, lon1), (lat2, lon2) = a, b
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 3958.8 * math.asin(math.sqrt(h))


def drive_miles(a: tuple[float, float], b: tuple[float, float]) -> float:
    return haversine_miles(a, b) * ROAD_FACTOR


def route_miles(home: tuple[float, float], stops: list[tuple[float, float]]) -> float:
    """Shortest round trip from home through every stop (stops are few, so try all orders)."""
    from itertools import permutations
    if not stops:
        return 0.0
    best = math.inf
    for order in permutations(stops):
        pts = [home, *order, home]
        best = min(best, sum(drive_miles(pts[i], pts[i + 1]) for i in range(len(pts) - 1)))
    return best


def parse_gazetteer(text: str) -> dict[str, tuple[float, float]]:
    """ZIP -> (lat, lon). Handles the Census file's tab- or pipe-delimited formats."""
    lines = text.splitlines()
    sep = "|" if "|" in lines[0] else "\t"
    head = [h.strip().upper() for h in lines[0].split(sep)]
    iz, ilat, ilon = head.index("GEOID"), head.index("INTPTLAT"), head.index("INTPTLONG")
    out = {}
    for line in lines[1:]:
        f = line.split(sep)
        if len(f) > max(iz, ilat, ilon):
            out[f[iz].strip()] = (float(f[ilat]), float(f[ilon]))
    return out


def download_gazetteer(path: Path = GAZETTEER, url: str = GAZETTEER_URL) -> Path:
    with urllib.request.urlopen(url, timeout=60) as r:
        z = zipfile.ZipFile(io.BytesIO(r.read()))
    text = z.read(next(n for n in z.namelist() if n.endswith(".txt"))).decode("utf-8", "replace")
    rows = parse_gazetteer(text)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("GEOID\tINTPTLAT\tINTPTLONG\n" + "".join(f"{z}\t{a}\t{b}\n" for z, (a, b) in rows.items()))
    return path


def zip_center(zip_code: str, path: Path = GAZETTEER) -> tuple[float, float]:
    if not path.exists():
        download_gazetteer(path)
    rows = parse_gazetteer(path.read_text())
    if zip_code not in rows:
        raise KeyError(f"ZIP {zip_code} not found in the Census ZIP list; pass --home lat,lon instead")
    return rows[zip_code]


def parse_home(text: str) -> tuple[float, float]:
    lat, lon = (float(x) for x in text.split(","))
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("home must be 'latitude,longitude'")
    return lat, lon
