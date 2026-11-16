"""2D-Karte & Koordinaten-Auswahl.

Dieses Modul beantwortet die Frage "Welches Gebiet soll untersucht werden?".
Das Ergebnis ist immer eine Bounding-Box als Tupel
``(west, south, east, north)`` in WGS84-Grad.

Die reinen Rechenfunktionen (``bbox_from_center`` usw.) brauchen weder
Streamlit noch Folium und können überall verwendet werden. Nur
``render_map_selector`` zeichnet die interaktive Karte in eine Streamlit-App.

Beispiel::

    from modules.map_selector import geocode_address, bbox_from_center

    ort = geocode_address("Marktplatz, Oldenburg")
    bbox = bbox_from_center(ort["lat"], ort["lon"], width_m=500)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import requests

BBox = tuple[float, float, float, float]  # (west, south, east, north)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# Nominatim verlangt einen aussagekräftigen User-Agent (Nutzungsbedingungen).
USER_AGENT = "TERRA-Sim/0.1 (Hochschul-Lehrprojekt)"

_M_PER_DEG_LAT = 111_320.0
_EARTH_CIRCUMFERENCE_M = 40_075_016.0


# --------------------------------------------------------------------------
# Rechnen mit Bounding-Boxen
# --------------------------------------------------------------------------

def bbox_from_center(lat: float, lon: float, width_m: float,
                     height_m: Optional[float] = None) -> BBox:
    """Bounding-Box mit gegebener Breite/Höhe (in Metern) um einen Mittelpunkt."""
    height_m = width_m if height_m is None else height_m
    dlat = height_m / 2 / _M_PER_DEG_LAT
    dlon = width_m / 2 / (_M_PER_DEG_LAT * math.cos(math.radians(lat)))
    return (lon - dlon, lat - dlat, lon + dlon, lat + dlat)


def bbox_center(bbox: BBox) -> tuple[float, float]:
    """Mittelpunkt der Bounding-Box als ``(lat, lon)``."""
    west, south, east, north = bbox
    return ((south + north) / 2, (west + east) / 2)


def bbox_size_m(bbox: BBox) -> tuple[float, float]:
    """Breite und Höhe der Bounding-Box in Metern."""
    west, south, east, north = bbox
    lat, _ = bbox_center(bbox)
    width = (east - west) * _M_PER_DEG_LAT * math.cos(math.radians(lat))
    height = (north - south) * _M_PER_DEG_LAT
    return (width, height)


def clamp_bbox(bbox: BBox, max_side_m: float) -> BBox:
    """Begrenzt eine zu große Bounding-Box auf ``max_side_m`` Kantenlänge."""
    width, height = bbox_size_m(bbox)
    if width <= max_side_m and height <= max_side_m:
        return bbox
    lat, lon = bbox_center(bbox)
    return bbox_from_center(lat, lon, min(width, max_side_m), min(height, max_side_m))


def zoom_for_bbox(bbox: BBox, target_px: int = 380) -> int:
    """Web-Karten-Zoomstufe, bei der die Box etwa ``target_px`` Pixel breit ist."""
    lat, _ = bbox_center(bbox)
    width, height = bbox_size_m(bbox)
    side = max(width, height, 1.0)
    world_px = target_px * _EARTH_CIRCUMFERENCE_M * math.cos(math.radians(lat)) / side
    return int(min(18, max(3, math.floor(math.log2(world_px / 256)))))


# --------------------------------------------------------------------------
# Adresssuche
# --------------------------------------------------------------------------

def geocode_address(query: str, timeout: float = 15.0) -> Optional[dict]:
    """Sucht eine Adresse über Nominatim (OpenStreetMap).

    Rückgabe: ``{"lat": ..., "lon": ..., "name": ...}`` oder ``None``,
    wenn nichts gefunden wurde. Netzwerkfehler werden als
    ``requests.RequestException`` weitergereicht.
    """
    query = (query or "").strip()
    if not query:
        return None
    response = requests.get(
        NOMINATIM_URL,
        params={"q": query, "format": "jsonv2", "limit": 1},
        headers={"User-Agent": USER_AGENT, "Accept-Language": "de"},
        timeout=timeout,
    )
    response.raise_for_status()
    hits = response.json()
    if not hits:
        return None
    hit = hits[0]
    return {
        "lat": float(hit["lat"]),
        "lon": float(hit["lon"]),
        "name": hit.get("display_name", query),
    }


# --------------------------------------------------------------------------
# Interaktive Karte (Streamlit + Folium)
# --------------------------------------------------------------------------

@dataclass
class MapSelection:
    """Was die Nutzerin / der Nutzer zuletzt auf der Karte getan hat."""

    drawn_bbox: Optional[BBox] = None             # gezeichnetes Rechteck
    clicked: Optional[tuple[float, float]] = None  # (lat, lon) des letzten Klicks


def bbox_from_drawing(drawing: Optional[dict]) -> Optional[BBox]:
    """Wandelt ein gezeichnetes GeoJSON-Rechteck in eine Bounding-Box um."""
    try:
        ring = drawing["geometry"]["coordinates"][0]
        lons = [float(p[0]) for p in ring]
        lats = [float(p[1]) for p in ring]
    except (TypeError, KeyError, IndexError, ValueError):
        return None
    if not lons or max(lons) == min(lons) or max(lats) == min(lats):
        return None
    return (min(lons), min(lats), max(lons), max(lats))


def render_map_selector(bbox: BBox, draw_mode: bool = False,
                        key: str = "terra_map", height: int = 520) -> MapSelection:
    """Zeichnet die Auswahlkarte und gibt die letzte Interaktion zurück.

    ``draw_mode=False``: ein Klick auf die Karte wird gemeldet (neuer Mittelpunkt).
    ``draw_mode=True``:  es erscheint ein Rechteck-Werkzeug zum Aufziehen der Box.
    """
    import folium
    from folium.plugins import Draw
    from streamlit_folium import st_folium

    west, south, east, north = bbox
    lat, lon = bbox_center(bbox)

    fmap = folium.Map(location=[lat, lon], zoom_start=zoom_for_bbox(bbox),
                      control_scale=True, tiles="OpenStreetMap")
    folium.Rectangle(
        bounds=[[south, west], [north, east]],
        color="#e4572e", weight=2, fill=True, fill_opacity=0.08,
        tooltip="Aktuelles Untersuchungsgebiet",
    ).add_to(fmap)

    if draw_mode:
        Draw(
            draw_options={
                "polyline": False, "polygon": False, "circle": False,
                "marker": False, "circlemarker": False,
                "rectangle": {"shapeOptions": {"color": "#1d70b8"}},
            },
            edit_options={"edit": False, "remove": False},
        ).add_to(fmap)

    wanted = ["last_active_drawing"] if draw_mode else ["last_clicked"]
    result = st_folium(fmap, key=f"{key}_{'draw' if draw_mode else 'click'}",
                       height=height, use_container_width=True,
                       returned_objects=wanted) or {}

    selection = MapSelection()
    if draw_mode:
        selection.drawn_bbox = bbox_from_drawing(result.get("last_active_drawing"))
    else:
        click = result.get("last_clicked")
        if click and "lat" in click and "lng" in click:
            selection.clicked = (float(click["lat"]), float(click["lng"]))
    return selection
