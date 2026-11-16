"""Lädt das amtliche Digitale Geländemodell DGM1 der Bundesländer (Open Data).

DGM1 = Geländehöhe im 1-m-Raster aus Laserscanning, **ohne** Gebäude und
Bäume – genau das, was Hochwasser- und Starkregen-Analysen brauchen. Die
freien weltweiten Höhenmodelle (30–90 m, teils mit Gebäuden) sind dagegen
nur grob.

Eingebunden sind die Länder, deren Daten sich ohne Riesen-Downloads für
ein Gebiet abrufen lassen:

=========================  ===========================================
Niedersachsen              STAC-Katalog + 1-km-Kacheln (Cloud-GeoTIFF)
Nordrhein-Westfalen        WCS (Ausschnitt direkt vom Server)
Bayern                     1-km-Kacheln (GeoTIFF)
Brandenburg und Berlin     WCS
Hessen                     WCS
Mecklenburg-Vorpommern     WCS
Rheinland-Pfalz            1-km-Kacheln (GeoTIFF)
=========================  ===========================================

Die übrigen Länder bieten DGM1 ebenfalls als Open Data an, aber nur in
großen ZIP-Paketen (z. B. Hamburg 1,5 GB) – das passt nicht zu einer
Abfrage auf Knopfdruck.

Beispiel::

    from modules.dgm1_loader import load_dgm1

    dem = load_dgm1((8.2120, 53.1375, 8.2175, 53.1405))   # Oldenburg
    print(dem.source, dem.attribution, dem.min, dem.max)
"""

from __future__ import annotations

import io
import math
import struct
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable

import numpy as np
import requests
from PIL import Image
from pyproj import Transformer

from .terrain_loader import DemGrid, grid_from_metric

BBox = tuple[float, float, float, float]  # (west, south, east, north) in WGS84
USER_AGENT = "TERRA-Sim/0.1 (Hochschul-Lehrprojekt)"
NODATA_BELOW = -9000.0     # Kein-Wert-Markierung der Länder: -9999
MAX_MISSING = 0.01         # mehr als 1 % Lücken -> Gebiet gilt als nicht abgedeckt
TILE_CACHE = Path(".cache") / "dgm1"


@dataclass(frozen=True)
class Service:
    name: str              # wird als Quelle angezeigt
    area: BBox             # grober Umriss des Landes (WGS84) – nur zur Vorauswahl
    crs: str
    attribution: str
    fetch: Callable        # (e0, n0, e1, n1, timeout) -> (z, x_links, y_oben, zellgröße)
    excluded: tuple = ()   # Bereiche im Umriss, die nicht dazugehören (z. B. Stadtstaaten)


# --------------------------------------------------------------------------
# GeoTIFF lesen (Pillow kann die LZW-komprimierten Fließkomma-Kacheln)
# --------------------------------------------------------------------------

def read_geotiff(data: bytes) -> tuple[np.ndarray, float, float, float]:
    """GeoTIFF -> (Höhen, x linker Rand, y oberer Rand, Zellgröße). Zeile 0 = Norden."""
    image = Image.open(io.BytesIO(data))
    z = np.array(image, dtype=np.float32)
    tags = image.tag_v2
    scale = tags.get(33550)          # ModelPixelScale (sx, sy, sz)
    tie = tags.get(33922)            # ModelTiepoint (i, j, k, x, y, z)
    if not scale or not tie:
        raise ValueError("GeoTIFF ohne Georeferenz")
    sx, sy = float(scale[0]), float(scale[1])
    x_left = float(tie[3]) - float(tie[0]) * sx
    y_top = float(tie[4]) + float(tie[1]) * sy
    if _pixel_is_point(tags.get(34735)):   # Koordinate = Zellmitte statt Zellecke
        x_left -= sx / 2
        y_top += sy / 2
    z[z <= NODATA_BELOW] = np.nan
    return z, x_left, y_top, sx


def _pixel_is_point(geokeys) -> bool:
    if not geokeys:
        return False
    keys = list(geokeys)
    for k in range(4, len(keys) - 3, 4):
        if keys[k] == 1025:          # GTRasterTypeGeoKey: 1 = Fläche, 2 = Punkt
            return keys[k + 3] == 2
    return False


def _get(url: str, timeout: float, **kwargs) -> requests.Response:
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout, **kwargs)
    response.raise_for_status()
    return response


def _cached_tile(url: str, timeout: float) -> bytes | None:
    """Lädt eine Kachel (oder nimmt sie aus ``.cache/dgm1``). ``None`` = gibt es nicht."""
    path = TILE_CACHE / url.rsplit("/", 1)[-1]
    if path.exists():
        return path.read_bytes()
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)
    return response.content


# --------------------------------------------------------------------------
# Abrufwege
# --------------------------------------------------------------------------

def _wcs(url: str, coverage: str, axes: tuple[str, str]):
    """WCS 2.0.1: Der Server schneidet genau den gewünschten Ausschnitt aus."""
    def fetch(e0, n0, e1, n1, timeout):
        params = [("SERVICE", "WCS"), ("VERSION", "2.0.1"), ("REQUEST", "GetCoverage"),
                  ("COVERAGEID", coverage), ("FORMAT", "image/tiff"),
                  ("SUBSET", f"{axes[0]}({e0},{e1})"), ("SUBSET", f"{axes[1]}({n0},{n1})")]
        return read_geotiff(_get(url, timeout, params=params).content)
    return fetch


def _mosaic(tiles: list, e0: int, n0: int, e1: int, n1: int):
    """Setzt Kacheln (z, x_links, y_oben, res) zu einem Raster für den Ausschnitt zusammen."""
    res = tiles[0][3]
    width, height = int(round((e1 - e0) / res)), int(round((n1 - n0) / res))
    out = np.full((height, width), np.nan, dtype=np.float32)
    for z, x_left, y_top, _ in tiles:
        col, row = int(round((x_left - e0) / res)), int(round((n1 - y_top) / res))
        r0, c0 = max(0, row), max(0, col)
        r1, c1 = min(height, row + z.shape[0]), min(width, col + z.shape[1])
        if r1 > r0 and c1 > c0:
            out[r0:r1, c0:c1] = z[r0 - row:r1 - row, c0 - col:c1 - col]
    return out, float(e0), float(n1), res


def _km_tiles(e0, n0, e1, n1):
    return [(e, n) for e in range(e0 // 1000, (e1 - 1) // 1000 + 1)
            for n in range(n0 // 1000, (n1 - 1) // 1000 + 1)]


def _tile_fetch(urls_for: Callable):
    """1-km-Kacheln: ``urls_for(e_km, n_km, timeout)`` liefert die Adresse(n) einer Kachel."""
    def fetch(e0, n0, e1, n1, timeout):
        def one(tile):
            for url in urls_for(*tile, timeout):
                data = _cached_tile(url, timeout)
                if data is not None:
                    return read_geotiff(data)
            return None
        with ThreadPoolExecutor(max_workers=4) as pool:
            tiles = [t for t in pool.map(one, _km_tiles(e0, n0, e1, n1)) if t is not None]
        if not tiles:
            raise ValueError("Keine DGM1-Kachel für dieses Gebiet")
        return _mosaic(tiles, e0, n0, e1, n1)
    return fetch


def _niedersachsen_urls(e_km, n_km, timeout):
    """LGLN: Kachel-Adresse enthält Lieferlos und Jahr -> über den STAC-Katalog suchen."""
    to_wgs = Transformer.from_crs("EPSG:25832", "EPSG:4326", always_xy=True)
    lon, lat = to_wgs.transform(e_km * 1000 + 500, n_km * 1000 + 500)
    items = _get("https://dgm.stac.lgln.niedersachsen.de/search", timeout,
                 params={"collections": "dgm1", "bbox": f"{lon:.5f},{lat:.5f},{lon:.5f},{lat:.5f}",
                         "limit": 20}).json().get("features", [])
    wanted = f"dgm1_32_{e_km}_{n_km}_1_ni"
    items = [f for f in items if f["id"].startswith(wanted)]
    items.sort(key=lambda f: f["properties"].get("datetime") or "", reverse=True)  # neuester Stand zuerst
    return [f["assets"]["dgm1-tif"]["href"] for f in items[:1]]


def _bayern_urls(e_km, n_km, timeout):
    return [f"https://download1.bayernwolke.de/a/dgm/dgm1/{e_km}_{n_km}.tif"]


def _rlp_urls(e_km, n_km, timeout):
    """LVermGeo RLP: Jahreszahl im Namen ist je Kachel verschieden -> von heute rückwärts suchen."""
    base = "https://geobasis-rlp.de/data/dgm1/current/tif/dgm1_32_{e}_{n}_1_rp_{y}.tif"
    cached = sorted(TILE_CACHE.glob(f"dgm1_32_{e_km}_{n_km}_1_rp_*.tif"), reverse=True)
    if cached:
        return [base.format(e=e_km, n=n_km, y=cached[0].stem.rsplit("_", 1)[-1])]
    for year in range(date.today().year, 2017, -1):
        url = base.format(e=e_km, n=n_km, y=year)
        if requests.head(url, headers={"User-Agent": USER_AGENT}, timeout=timeout).status_code == 200:
            return [url]
    return []


SERVICES = [
    Service("DGM1 Niedersachsen (LGLN)", (6.6, 51.29, 11.6, 53.9), "EPSG:25832",
            "© GeoBasis-DE/LGLN, CC BY 4.0", _tile_fetch(_niedersachsen_urls),
            excluded=((9.73, 53.40, 10.33, 53.74),     # Hamburg
                      (8.70, 53.03, 8.99, 53.20),      # Bremen (ohne Bremen-Nord, Delmenhorst bleibt drin)
                      (8.48, 53.46, 8.65, 53.61))),    # Bremerhaven
    Service("DGM1 Nordrhein-Westfalen", (5.86, 50.32, 9.46, 52.53), "EPSG:25832",
            "Geobasis NRW, dl-de/zero-2-0",
            _wcs("https://www.wcs.nrw.de/geobasis/wcs_nw_dgm", "nw_dgm", ("x", "y"))),
    Service("DGM1 Bayern", (8.97, 47.27, 13.84, 50.57), "EPSG:25832",
            "Datenquelle: Bayerische Vermessungsverwaltung – www.geodaten.bayern.de, CC BY 4.0",
            _tile_fetch(_bayern_urls)),
    Service("DGM1 Brandenburg/Berlin", (11.26, 51.36, 14.77, 53.56), "EPSG:25833",
            "© GeoBasis-DE/LGB, dl-de/by-2-0; © Geoportal Berlin, dl-de/by-2-0",
            _wcs("https://isk.geobasis-bb.de/ows/dgm_wcs", "bb_dgm", ("x", "y"))),
    Service("DGM1 Hessen (HVBG)", (7.77, 49.39, 10.24, 51.66), "EPSG:25832",
            "HVBG Hessen, dl-de/zero-2-0",
            _wcs("https://inspire-hessen.de/raster/dgm1/ows", "he_dgm1", ("E", "N"))),
    Service("DGM1 Mecklenburg-Vorpommern", (10.59, 53.11, 14.41, 54.69), "EPSG:25833",
            "© GeoBasis-DE/M-V",
            _wcs("https://www.geodaten-mv.de/dienste/dgm_wcs", "mv_dgm", ("x", "y"))),
    Service("DGM1 Rheinland-Pfalz", (6.11, 48.97, 8.51, 50.94), "EPSG:25832",
            "© GeoBasis-DE / LVermGeoRP, dl-de/by-2-0, www.lvermgeo.rlp.de [Daten bearbeitet]",
            _tile_fetch(_rlp_urls)),
]


# --------------------------------------------------------------------------
# Öffentliche Funktionen
# --------------------------------------------------------------------------

def candidates(bbox: BBox) -> list[Service]:
    """Dienste, in deren Land die Gebietsmitte liegen könnte (grobe Vorauswahl)."""
    lon, lat = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2

    def inside(box):
        return box[0] <= lon <= box[2] and box[1] <= lat <= box[3]

    return [s for s in SERVICES if inside(s.area) and not any(inside(b) for b in s.excluded)]


def load_dgm1(bbox: BBox, spacing_m: float | None = None, margin_m: float = 15.0,
              timeout: float = 60.0) -> DemGrid | None:
    """Lädt das DGM1 für die Bounding-Box. ``None``, wenn kein Land das Gebiet ganz abdeckt.

    ``spacing_m``  Punktabstand des Ergebnisses (Standard: je nach Gebietsgröße 1–3 m)
    """
    errors = []
    for service in candidates(bbox):
        try:
            to_m = Transformer.from_crs("EPSG:4326", service.crs, always_xy=True)
            xs, ys = to_m.transform([bbox[0], bbox[2], bbox[2], bbox[0]], [bbox[1], bbox[1], bbox[3], bbox[3]])
            e0, n0 = int(math.floor(min(xs) - margin_m)), int(math.floor(min(ys) - margin_m))
            e1, n1 = int(math.ceil(max(xs) + margin_m)), int(math.ceil(max(ys) + margin_m))
            z, x_left, y_top, res = service.fetch(e0, n0, e1, n1, timeout)
            missing = float(np.isnan(z).mean()) if z.size else 1.0
            if missing > MAX_MISSING:
                errors.append(f"{service.name}: Gebiet nur teilweise abgedeckt")
                continue
            if missing:
                z = np.where(np.isnan(z), np.nanmedian(z), z)
            side = max(max(xs) - min(xs), max(ys) - min(ys))
            spacing = spacing_m or max(1.0, side / 500)
            return grid_from_metric(z, x_left, y_top, res, service.crs, bbox, spacing,
                                    service.name, service.attribution)
        except (requests.RequestException, ValueError, OSError, KeyError, struct.error) as error:
            errors.append(f"{service.name}: {error}")
    load_dgm1.last_errors = errors   # zur Fehlersuche
    return None


load_dgm1.last_errors = []
