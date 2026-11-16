"""Lädt Geländehöhen (DEM = Digital Elevation Model) für eine Bounding-Box.

Fällt eine Quelle aus, wird automatisch die nächste probiert:

1. DGM1 der Landesvermessung (1 m, ohne Gebäude) – in einigen
   Bundesländern, siehe ``dgm1_loader.py``
2. Open-Elevation  (https://open-elevation.com, SRTM-Daten)
3. Open-Meteo      (https://open-meteo.com, Copernicus-DEM, 90 m)
4. ebenes Gelände  (Notlösung, damit die App weiterläuft – ``source`` = "flach")

Wichtig für die Interpretation: Die globalen Höhenmodelle (2. und 3.)
haben nur 30–250 m Auflösung und enthalten teils Gebäude und Bäume;
Open-Meteo liefert zudem nur ganze Meter. Sie können sich deshalb um
mehrere Meter unterscheiden. Das DGM1 ist um Größenordnungen genauer.

Beispiel::

    from modules.terrain_loader import load_dem

    dem = load_dem((8.2120, 53.1375, 8.2175, 53.1405))
    hoehe = dem.sample(8.2150, 53.1390)   # Höhe an einem beliebigen Punkt
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

import numpy as np
import requests

BBox = tuple[float, float, float, float]  # (west, south, east, north)

OPEN_ELEVATION_URL = "https://api.open-elevation.com/api/v1/lookup"
OPEN_METEO_URL = "https://api.open-meteo.com/v1/elevation"
USER_AGENT = "TERRA-Sim/0.1 (Hochschul-Lehrprojekt)"

_M_PER_DEG_LAT = 111_320.0


@dataclass
class DemGrid:
    """Höhenraster: ``elevation[zeile, spalte]`` mit Zeile 0 = Süden, Spalte 0 = Westen."""

    lons: np.ndarray       # (nx,) aufsteigend, West -> Ost
    lats: np.ndarray       # (ny,) aufsteigend, Süd -> Nord
    elevation: np.ndarray  # (ny, nx) Höhe in Metern
    source: str            # welcher Dienst die Daten geliefert hat
    attribution: str = ""  # Quellenangabe, die mit angezeigt werden muss

    @property
    def min(self) -> float:
        return float(self.elevation.min())

    @property
    def max(self) -> float:
        return float(self.elevation.max())

    def sample(self, lon, lat) -> np.ndarray:
        """Höhe an beliebigen Punkten (bilinear interpoliert, am Rand geklemmt)."""
        lon = np.asarray(lon, dtype=float)
        lat = np.asarray(lat, dtype=float)
        ny, nx = self.elevation.shape

        fx = (lon - self.lons[0]) / (self.lons[-1] - self.lons[0]) * (nx - 1)
        fy = (lat - self.lats[0]) / (self.lats[-1] - self.lats[0]) * (ny - 1)
        fx = np.clip(fx, 0, nx - 1)
        fy = np.clip(fy, 0, ny - 1)

        x0 = np.minimum(np.floor(fx).astype(int), nx - 2)
        y0 = np.minimum(np.floor(fy).astype(int), ny - 2)
        tx = fx - x0
        ty = fy - y0

        z = self.elevation
        bottom = z[y0, x0] * (1 - tx) + z[y0, x0 + 1] * tx
        top = z[y0 + 1, x0] * (1 - tx) + z[y0 + 1, x0 + 1] * tx
        return bottom * (1 - ty) + top * ty


# --------------------------------------------------------------------------
# Abfrage der Höhendienste
# --------------------------------------------------------------------------

def _query_open_elevation(lats: np.ndarray, lons: np.ndarray, timeout: float) -> np.ndarray:
    heights = []
    for start in range(0, len(lats), 500):
        locations = [{"latitude": float(a), "longitude": float(o)}
                     for a, o in zip(lats[start:start + 500], lons[start:start + 500])]
        response = requests.post(OPEN_ELEVATION_URL, json={"locations": locations},
                                 headers={"User-Agent": USER_AGENT}, timeout=timeout)
        response.raise_for_status()
        heights.extend(float(r["elevation"]) for r in response.json()["results"])
    return np.array(heights)


def _query_open_meteo(lats: np.ndarray, lons: np.ndarray, timeout: float) -> np.ndarray:
    heights = []
    for start in range(0, len(lats), 100):  # API-Limit: 100 Punkte pro Abfrage
        params = {
            "latitude": ",".join(f"{a:.6f}" for a in lats[start:start + 100]),
            "longitude": ",".join(f"{o:.6f}" for o in lons[start:start + 100]),
        }
        response = requests.get(OPEN_METEO_URL, params=params,
                                headers={"User-Agent": USER_AGENT}, timeout=timeout)
        response.raise_for_status()
        heights.extend(float(h) for h in response.json()["elevation"])
    return np.array(heights)


PROVIDERS = {
    "Open-Elevation": _query_open_elevation,
    "Open-Meteo": _query_open_meteo,
}
ATTRIBUTION = {
    "Open-Elevation": "Open-Elevation (SRTM)",
    "Open-Meteo": "Open-Meteo (Copernicus DEM GLO-90)",
}


# --------------------------------------------------------------------------
# Öffentliche Funktionen
# --------------------------------------------------------------------------

def grid_shape(bbox: BBox, spacing_m: float = 25.0, max_points: int = 40) -> tuple[int, int]:
    # (max_points begrenzt die Abfragen bei den Punkt-Diensten; DGM1 nutzt mehr Punkte)
    """Anzahl Rasterpunkte ``(ny, nx)`` für etwa ``spacing_m`` Punktabstand."""
    west, south, east, north = bbox
    lat = (south + north) / 2
    width = (east - west) * _M_PER_DEG_LAT * math.cos(math.radians(lat))
    height = (north - south) * _M_PER_DEG_LAT
    nx = int(np.clip(math.ceil(width / spacing_m) + 1, 6, max_points))
    ny = int(np.clip(math.ceil(height / spacing_m) + 1, 6, max_points))
    return ny, nx


def flat_dem(bbox: BBox, elevation: float = 0.0) -> DemGrid:
    """Ebenes Ersatzgelände (z. B. für Tests oder wenn kein Dienst erreichbar ist)."""
    west, south, east, north = bbox
    return DemGrid(np.array([west, east]), np.array([south, north]),
                   np.full((2, 2), float(elevation)), "flach")


def load_dem(bbox: BBox, spacing_m: float = 25.0, smooth: bool = True,
             providers: tuple[str, ...] = ("DGM1", "Open-Elevation", "Open-Meteo"),
             timeout: float = 25.0) -> DemGrid:
    """Lädt das Höhenraster für die Bounding-Box.

    Zuerst wird das amtliche DGM1 versucht (nur in einigen Bundesländern,
    siehe ``dgm1_loader.py``), danach die weltweiten Dienste.
    ``smooth=True`` glättet deren Raster leicht – die globalen Höhenmodelle
    rauschen in Städten um einige Dezimeter bis Meter.
    """
    if "DGM1" in providers:
        from .dgm1_loader import load_dgm1
        dem = load_dgm1(bbox)
        if dem is not None:
            return dem
        providers = tuple(p for p in providers if p != "DGM1")

    west, south, east, north = bbox
    ny, nx = grid_shape(bbox, spacing_m)
    lons = np.linspace(west, east, nx)
    lats = np.linspace(south, north, ny)
    grid_lon, grid_lat = np.meshgrid(lons, lats)

    for name in providers:
        for attempt in range(2):  # die freien Dienste antworten gelegentlich mit Fehlern
            try:
                heights = PROVIDERS[name](grid_lat.ravel(), grid_lon.ravel(), timeout)
            except (requests.RequestException, KeyError, ValueError, TypeError):
                time.sleep(1.0)
                continue
            if len(heights) != nx * ny or not np.all(np.isfinite(heights)):
                break
            elevation = heights.reshape(ny, nx)
            if smooth:
                elevation = _smooth(elevation)
            return DemGrid(lons, lats, elevation, name, ATTRIBUTION[name])

    return flat_dem(bbox)


# --------------------------------------------------------------------------
# Hilfen für metrische Raster (DGM1)
# --------------------------------------------------------------------------

def _box_mean(z: np.ndarray, k: int) -> np.ndarray:
    """Gleitender Mittelwert über k x k Zellen (gleiche Größe wie ``z``)."""
    if k <= 1:
        return z
    pad = k // 2
    p = np.pad(z, ((pad, k - 1 - pad), (pad, k - 1 - pad)), mode="edge")
    c = np.cumsum(np.cumsum(p, axis=0), axis=1)
    c = np.pad(c, ((1, 0), (1, 0)))
    return (c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]) / (k * k)


def grid_from_metric(z: np.ndarray, x_left: float, y_top: float, res: float, crs: str,
                     bbox: BBox, spacing_m: float, source: str, attribution: str = "") -> DemGrid:
    """Rechnet ein metrisches Raster (Zeile 0 = Norden) auf das ``DemGrid`` in WGS84 um.

    ``x_left``/``y_top`` = linke obere Ecke der linken oberen Zelle, ``res`` = Zellgröße.
    Vorher wird auf etwa ``spacing_m`` gemittelt, damit nichts "flimmert".
    """
    from pyproj import Transformer

    z = np.asarray(z, dtype=float)
    z = _box_mean(z, int(round(spacing_m / res)))
    west, south, east, north = bbox
    ny, nx = grid_shape(bbox, spacing_m, max_points=1000)
    lons, lats = np.linspace(west, east, nx), np.linspace(south, north, ny)
    gx, gy = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform(*np.meshgrid(lons, lats))

    fc = np.clip((gx - x_left) / res - 0.5, 0, z.shape[1] - 1)
    fr = np.clip((y_top - gy) / res - 0.5, 0, z.shape[0] - 1)
    c0 = np.minimum(np.floor(fc).astype(int), z.shape[1] - 2)
    r0 = np.minimum(np.floor(fr).astype(int), z.shape[0] - 2)
    tc, tr = fc - c0, fr - r0
    top = z[r0, c0] * (1 - tc) + z[r0, c0 + 1] * tc
    bottom = z[r0 + 1, c0] * (1 - tc) + z[r0 + 1, c0 + 1] * tc
    return DemGrid(lons, lats, top * (1 - tr) + bottom * tr, source, attribution)


def _smooth(z: np.ndarray) -> np.ndarray:
    """3x3-Glättung (Gewichte 1-2-1) ohne zusätzliche Bibliothek."""
    padded = np.pad(z, 1, mode="edge")
    rows = padded[:-2] + 2 * padded[1:-1] + padded[2:]
    return (rows[:, :-2] + 2 * rows[:, 1:-1] + rows[:, 2:]) / 16.0
