"""Offline-Testgebiet: synthetische OSM-Daten, Gelände mit Mulde, feste amtliche Daten.

Die Tests sollen ohne Netz laufen (lokal wie in GitHub Actions). Deshalb:

* ``osm_data()``      baut OSM-Rohdaten wie von osmnx und schickt sie durch den echten
                      Parser in ``modules/osm_fetcher.py``
* ``dem_grid()``      Gelände mit einer Mulde in der Südwest-Ecke (für Hochwasser, Starkregen)
* ``demo_model()``    das fertige ``Model`` wie nach „Projekt anlegen“
* ``install_offline()`` ersetzt die Abfragen in ``modules/gov_data.py`` durch feste Werte
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Transformer
from shapely.geometry import LineString, Polygon, box

LAT, LON, SIDE_M = 53.5476, 8.0884, 300.0
KOSTRA = {   # Regenhöhe (mm) je Dauerstufe (min) und Wiederkehrzeit (Jahre), Größenordnung Norddeutschland
    60: {1: 14.0, 2: 17.5, 3: 19.5, 5: 22.0, 10: 25.5, 20: 29.0, 30: 31.0, 50: 34.0, 100: 41.0},
    360: {1: 24.0, 2: 29.0, 3: 32.0, 5: 36.0, 10: 41.0, 20: 46.0, 30: 50.0, 50: 54.0, 100: 65.0},
    1440: {1: 36.0, 2: 43.0, 3: 47.0, 5: 52.0, 10: 59.0, 20: 66.0, 30: 70.0, 50: 76.0, 100: 94.0},
}


def bbox() -> tuple:
    from modules.map_selector import bbox_from_center
    return bbox_from_center(LAT, LON, SIDE_M)


def _metric():
    from modules.osm_fetcher import metric_crs
    crs = metric_crs(bbox())
    to_m = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform
    to_wgs = Transformer.from_crs(crs, "EPSG:4326", always_xy=True).transform
    cx, cy = to_m(LON, LAT)
    return crs, to_wgs, cx, cy


def _raw_osm() -> gpd.GeoDataFrame:
    """OSM-Rohdaten im Format von ``osmnx.features_from_bbox`` (Index: Element-Typ, ID)."""
    crs, to_wgs, cx, cy = _metric()

    def poly(x, y, w, h):
        return Polygon([to_wgs(cx + x + dx, cy + y + dy) for dx, dy in ((0, 0), (w, 0), (w, h), (0, h))])

    rows, index = [], []
    kinds = ["house", "house", "apartments", "terrace", "church", "office", "garage", "retail", "house"]
    for k in range(18):
        i, j = k % 6, k // 6
        tags = {"building": kinds[k % len(kinds)]}
        if k % 3 == 0:
            tags["building:levels"] = str(2 + k % 5)
        if k % 4 == 1:
            tags["height"] = f"{8 + k} m"
        if k % 5 == 2:
            tags["roof:shape"] = "gabled"
        rows.append({**tags, "geometry": poly(-130 + i * 45, -110 + j * 70, 14 + k % 3 * 4, 10 + k % 2 * 6)})
        index.append(("way", 1000 + k))
    # zwei Häuser Wand an Wand und eine schmale Gasse (Düseneffekt beim Wind)
    rows += [{"building": "apartments", "building:levels": "5", "geometry": poly(60, 40, 20, 40)},
             {"building": "apartments", "building:levels": "5", "geometry": poly(86, 40, 20, 40)}]
    index += [("way", 2000), ("way", 2001)]
    # Straße quer durchs Gebiet, Park, Teich
    rows.append({"highway": "residential", "name": "Teststraße",
                 "geometry": LineString([to_wgs(cx - 160, cy - 15), to_wgs(cx + 160, cy - 15)])})
    rows.append({"leisure": "park", "geometry": poly(-140, 60, 80, 70)})
    rows.append({"natural": "water", "geometry": poly(100, -140, 30, 25)})
    index += [("way", 3000), ("way", 3001), ("way", 3002)]
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326",
                            index=pd.MultiIndex.from_tuples(index, names=["element", "id"]))


def osm_data():
    from modules.osm_fetcher import (GREEN_TAGS, WATER_TAGS, WATERWAY_WIDTH_M, OsmData, _prepare_areas,
                                     _prepare_buildings, _prepare_streets, metric_crs)
    raw, b = _raw_osm(), bbox()
    crs = metric_crs(b)
    return OsmData(b, _prepare_buildings(raw, crs), _prepare_streets(raw, b),
                   _prepare_areas(raw, GREEN_TAGS, b, crs), _prepare_areas(raw, WATER_TAGS, b, crs, WATERWAY_WIDTH_M))


def dem_grid():
    """Gelände 2–6 m ü. NHN mit einer Mulde in der Südwest-Ecke."""
    from modules.terrain_loader import DemGrid
    west, south, east, north = bbox()
    lons = np.linspace(west - 0.001, east + 0.001, 60)
    lats = np.linspace(south - 0.001, north + 0.001, 60)
    gx, gy = np.meshgrid(np.linspace(0, 1, 60), np.linspace(0, 1, 60))
    elevation = 2.0 + 4.0 * gx * gy + 1.5 * np.exp(-((gx - 0.7) ** 2 + (gy - 0.6) ** 2) / 0.02) \
        - 1.2 * np.exp(-((gx - 0.25) ** 2 + (gy - 0.25) ** 2) / 0.01)
    return DemGrid(lons, lats, elevation, "Testgelände", "synthetisch")


def demo_model():
    from views.common import build_model
    return build_model("Testgebiet", bbox(), osm_data(), dem_grid(), None, "keine Klimadaten im Test")


# --------------------------------------------------------------------------
# Amtliche Daten ohne Netz
# --------------------------------------------------------------------------

def _gusts(lat, lon, **_):
    years = np.arange(1995, 2025)
    rng = np.random.default_rng(1)
    maxima = 95 + 12 * -np.log(-np.log(rng.uniform(0.02, 0.98, len(years))))    # Gumbel-verteilt, km/h
    return {"maxima": pd.Series(maxima, index=years), "station": "Teststation", "km": 5.0,
            "years": f"{years[0]}–{years[-1]}"}


def _hourly(lat, lon, **_):
    index = pd.date_range("2020-01-01", periods=2 * 8760, freq="h", tz="UTC")
    rng = np.random.default_rng(2)
    wdir = (230 + 70 * rng.standard_normal(len(index))) % 360          # meist aus Südwest
    wspd = rng.weibull(2.0, len(index)) * 18                            # km/h
    return {"hourly": pd.DataFrame({"wdir": wdir, "wspd": wspd}, index=index), "station": "Teststation", "km": 5.0}


def _floods(b, **_):
    """Ein HQ100-Gebiet über der Mulde (Koordinaten in EPSG:25832 wie beim Kartendienst)."""
    west, south, east, north = b
    to_utm = Transformer.from_crs("EPSG:4326", "EPSG:25832", always_xy=True).transform
    x0, y0 = to_utm(west, south)
    x1, y1 = to_utm(west + (east - west) * 0.45, south + (north - south) * 0.45)
    return {"M": {"name": "HQ100", "T": 100, "geometry": box(x0, y0, x1, y1), "share": 0.2}}


def install_offline():
    """Ersetzt alle Netzabfragen für amtliche Daten durch feste Testwerte."""
    import modules.gov_data as gov
    gov.kostra = lambda lat, lon, *a, **k: {d: dict(t) for d, t in KOSTRA.items()}
    gov.official_floods = _floods
    gov.gust_maxima = _gusts
    gov.hourly_wind = _hourly
    gov.quake_zone = lambda lat, lon, *a, **k: {"zone": 1, "subsoil": "T", "place": "Teststadt", "postcode": "26000"}


def kostra_table(minutes: int) -> dict:
    return dict(KOSTRA[minutes])

