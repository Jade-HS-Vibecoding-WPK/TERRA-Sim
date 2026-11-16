"""Lädt Gebäude, Höhen, Straßen, Grün- und Wasserflächen aus OpenStreetMap.

Eingabe ist eine Bounding-Box ``(west, south, east, north)`` in WGS84-Grad,
Ausgabe ein ``OsmData``-Objekt mit vier ``GeoDataFrame`` (alle in WGS84).

Gebäudehöhen stehen in OSM nur teilweise. Die Höhe wird deshalb in dieser
Reihenfolge bestimmt (Spalte ``height_source`` sagt, was gegriffen hat):

1. ``height``-Tag (gemessene Gesamthöhe)            -> "OSM-Höhe"
2. ``building:levels`` x Geschosshöhe               -> "OSM-Geschosse"
3. typische Geschosszahl für den Gebäudetyp         -> "Schätzung"

Beispiel::

    from modules.osm_fetcher import fetch_osm, metric_crs

    bbox = (8.2120, 53.1375, 8.2175, 53.1405)
    osm = fetch_osm(bbox)
    gebaeude_in_metern = osm.buildings.to_crs(metric_crs(bbox))
"""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely.geometry import box

BBox = tuple[float, float, float, float]  # (west, south, east, north)

# Öffentliche Overpass-Server (OSM-Datenbankabfrage), in dieser Reihenfolge
# probiert. Der Hauptserver ist zeitweise überlastet (Fehler 502 "at capacity")
# und bittet dann ausdrücklich um Wiederholung mit wachsender Wartezeit.
OVERPASS_URLS = (
    "https://overpass-api.de/api",
    "https://overpass.private.coffee/api",
)
RETRY_WAITS_S = (3, 6, 12)     # Pausen vor dem 2., 3. und 4. Versuch je Server

STOREY_HEIGHT_M = 3.0          # angenommene Geschosshöhe
DEFAULT_ROOF_HEIGHT_M = 3.0    # Dachhöhe, wenn OSM nur die Dachform kennt
MIN_BUILDING_AREA_M2 = 5.0     # kleinere Flächen (Gartenhäuschen, Fehler) ignorieren

# Typische Geschosszahl je Gebäudetyp, falls OSM gar keine Höhenangabe hat.
DEFAULT_LEVELS = {
    "house": 2, "detached": 2, "semidetached_house": 2, "terrace": 2,
    "bungalow": 1, "residential": 3, "apartments": 4, "dormitory": 4,
    "garage": 1, "garages": 1, "carport": 1, "shed": 1, "hut": 1, "roof": 1,
    "greenhouse": 1, "kiosk": 1, "service": 1,
    "commercial": 3, "office": 4, "retail": 2, "supermarket": 2, "hotel": 5,
    "industrial": 3, "warehouse": 3, "hangar": 4,
    "school": 3, "university": 4, "college": 4, "hospital": 5, "public": 3,
    "civic": 3, "government": 4, "kindergarten": 2,
    "church": 5, "cathedral": 8, "chapel": 3, "mosque": 4, "synagogue": 4,
    "train_station": 3, "parking": 4, "stadium": 5,
}
FALLBACK_LEVELS = 2

# OSM kennt viele Dachformen – TERRA-Sim vereinfacht sie auf vier (LOD 2).
ROOF_SHAPES = {
    "flat": "flat", "skillion": "flat", "round": "flat",
    "gabled": "gabled", "gambrel": "gabled", "saltbox": "gabled",
    "hipped": "hipped", "half-hipped": "hipped", "mansard": "hipped",
    "pyramidal": "pyramidal", "dome": "pyramidal", "onion": "pyramidal",
}

# Angenommene Straßenbreite (m) je Straßentyp, falls kein ``width``-Tag da ist.
STREET_WIDTH_M = {
    "motorway": 14, "trunk": 12, "primary": 10, "secondary": 8, "tertiary": 7,
    "motorway_link": 7, "trunk_link": 7, "primary_link": 6, "secondary_link": 6,
    "residential": 6, "unclassified": 6, "living_street": 5, "pedestrian": 6,
    "service": 4, "track": 3, "cycleway": 2.5, "footway": 2, "path": 1.5,
    "steps": 2, "bridleway": 2,
}
FALLBACK_STREET_WIDTH_M = 5

GREEN_TAGS = {
    "leisure": ["park", "garden", "playground", "pitch", "nature_reserve",
                "golf_course", "dog_park"],
    "landuse": ["grass", "forest", "meadow", "village_green", "recreation_ground",
                "allotments", "cemetery", "farmland", "orchard", "vineyard",
                "greenfield", "flowerbed"],
    "natural": ["wood", "scrub", "grassland", "heath", "wetland"],
}
WATER_TAGS = {
    "natural": ["water"],
    "landuse": ["basin", "reservoir"],
    "waterway": ["river", "stream", "canal", "ditch", "drain", "riverbank", "dock"],
}
WATERWAY_WIDTH_M = {"river": 20, "canal": 12, "stream": 3, "ditch": 1.5, "drain": 1.5}


@dataclass
class OsmData:
    """Alle OSM-Ebenen eines Untersuchungsgebiets (Koordinaten in WGS84)."""

    bbox: BBox
    buildings: gpd.GeoDataFrame  # Polygone + Höhenangaben
    streets: gpd.GeoDataFrame    # Linien + Spalte ``width_m``
    green: gpd.GeoDataFrame      # Polygone (unversiegelt)
    water: gpd.GeoDataFrame      # Polygone


# --------------------------------------------------------------------------
# Hilfsfunktionen
# --------------------------------------------------------------------------

def metric_crs(bbox: BBox) -> str:
    """Passendes metrisches Koordinatensystem (UTM-Zone) für die Bounding-Box."""
    west, south, east, north = bbox
    lon = (west + east) / 2
    lat = (south + north) / 2
    zone = int((lon + 180) // 6) % 60 + 1
    return f"EPSG:{(32600 if lat >= 0 else 32700) + zone}"


_NUMBER = re.compile(r"[-+]?\d+(?:[.,]\d+)?")


def parse_length_m(value) -> float:
    """Liest Längenangaben wie ``"12"``, ``"12,5 m"`` oder ``"40 ft"`` (-> Meter)."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return float("nan")
    text = str(value).strip().lower()
    match = _NUMBER.search(text)
    if not match:
        return float("nan")
    number = float(match.group().replace(",", "."))
    if "ft" in text or "'" in text:
        number *= 0.3048
    return number if number > 0 else float("nan")


def _column(gdf: gpd.GeoDataFrame, name: str) -> pd.Series:
    """Spalte holen – oder eine leere Spalte, wenn OSM das Tag hier nicht kennt."""
    if name in gdf.columns:
        return gdf[name]
    return pd.Series([None] * len(gdf), index=gdf.index, dtype=object)


def _has_tag(gdf: gpd.GeoDataFrame, tags: dict) -> pd.Series:
    mask = pd.Series(False, index=gdf.index)
    for key, values in tags.items():
        mask |= _column(gdf, key).isin(values)
    return mask


def _empty(columns: list[str]) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame({c: [] for c in columns}, geometry=[], crs="EPSG:4326")


def _polygons_only(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Repariert Geometrien und zerlegt Multi-Polygone in einzelne Polygone."""
    if gdf.empty:
        return gdf
    gdf = gdf.copy()
    gdf["geometry"] = shapely.make_valid(gdf.geometry.values)
    gdf = gdf.explode(index_parts=False)
    gdf = gdf[gdf.geom_type == "Polygon"]
    return gdf[~gdf.geometry.is_empty].reset_index(drop=True)


def _clip(gdf: gpd.GeoDataFrame, bbox: BBox) -> gpd.GeoDataFrame:
    if gdf.empty:
        return gdf
    clipped = gdf.clip(box(*bbox))
    return clipped[~clipped.geometry.is_empty].reset_index(drop=True)


# --------------------------------------------------------------------------
# Aufbereitung der einzelnen Ebenen
# --------------------------------------------------------------------------

BUILDING_COLUMNS = ["osm_id", "name", "building", "levels", "height_m",
                    "eave_height_m", "roof_shape", "roof_height_m",
                    "height_source", "area_m2"]


def _prepare_buildings(raw: gpd.GeoDataFrame, crs_metric: str) -> gpd.GeoDataFrame:
    is_building = _column(raw, "building").notna() & (_column(raw, "building") != "no")
    is_area = raw.geom_type.isin(["Polygon", "MultiPolygon"])
    src = raw[is_building & is_area]
    if src.empty:
        return _empty(BUILDING_COLUMNS)

    rows = []
    for (element, osm_id), row in src.iterrows():
        kind = str(row.get("building"))
        tagged_height = parse_length_m(row.get("height"))
        tagged_levels = parse_length_m(row.get("building:levels"))

        shape_tag = row.get("roof:shape")
        roof_shape = ROOF_SHAPES.get(str(shape_tag).strip().lower(), "flat")
        roof_height = 0.0
        if roof_shape != "flat":
            roof_height = parse_length_m(row.get("roof:height"))
            if math.isnan(roof_height):
                roof_levels = parse_length_m(row.get("roof:levels"))
                roof_height = (roof_levels * STOREY_HEIGHT_M
                               if not math.isnan(roof_levels) else DEFAULT_ROOF_HEIGHT_M)

        if not math.isnan(tagged_height):
            # ``height`` meint in OSM die Gesamthöhe inklusive Dach.
            height = tagged_height
            roof_height = min(roof_height, 0.6 * height)
            eave = height - roof_height
            levels = tagged_levels if not math.isnan(tagged_levels) else max(1, round(eave / STOREY_HEIGHT_M))
            source = "OSM-Höhe"
        else:
            if not math.isnan(tagged_levels):
                levels, source = tagged_levels, "OSM-Geschosse"
            else:
                levels, source = DEFAULT_LEVELS.get(kind, FALLBACK_LEVELS), "Schätzung"
            # ``building:levels`` zählt nur Vollgeschosse, das Dach kommt obendrauf.
            eave = levels * STOREY_HEIGHT_M
            height = eave + roof_height

        name = row.get("name")
        rows.append({
            "osm_id": f"{element}/{osm_id}",
            "name": name if isinstance(name, str) else "",
            "building": kind,
            "levels": float(levels),
            "height_m": round(float(height), 2),
            "eave_height_m": round(float(eave), 2),
            "roof_shape": roof_shape,
            "roof_height_m": round(float(roof_height), 2),
            "height_source": source,
            "geometry": row.geometry,
        })

    buildings = _polygons_only(gpd.GeoDataFrame(rows, geometry="geometry", crs=raw.crs))
    buildings["area_m2"] = buildings.to_crs(crs_metric).area.round(1).values
    buildings = buildings[buildings["area_m2"] >= MIN_BUILDING_AREA_M2]
    return buildings[BUILDING_COLUMNS + ["geometry"]].reset_index(drop=True)


def _prepare_streets(raw: gpd.GeoDataFrame, bbox: BBox) -> gpd.GeoDataFrame:
    highway = _column(raw, "highway")
    src = raw[highway.notna() & raw.geom_type.isin(["LineString", "MultiLineString"])]
    if src.empty:
        return _empty(["highway", "name", "width_m"])

    width = _column(src, "width").map(parse_length_m)
    default = _column(src, "highway").map(STREET_WIDTH_M).fillna(FALLBACK_STREET_WIDTH_M)
    streets = gpd.GeoDataFrame({
        "highway": _column(src, "highway").astype(str).values,
        "name": _column(src, "name").fillna("").astype(str).values,
        "width_m": width.fillna(default).clip(1, 40).astype(float).values,
    }, geometry=src.geometry.values, crs=raw.crs)
    streets = _clip(streets, bbox).explode(index_parts=False)
    return streets[streets.geom_type == "LineString"].reset_index(drop=True)


def _prepare_areas(raw: gpd.GeoDataFrame, tags: dict, bbox: BBox, crs_metric: str,
                   line_widths: dict | None = None) -> gpd.GeoDataFrame:
    """Flächen mit bestimmten Tags; Linien (z. B. Bäche) werden zu Flächen gepuffert."""
    src = raw[_has_tag(raw, tags)]
    if src.empty:
        return _empty([])
    parts = [src[src.geom_type.isin(["Polygon", "MultiPolygon"])].geometry]

    if line_widths:
        lines = src[src.geom_type.isin(["LineString", "MultiLineString"])]
        if not lines.empty:
            width = _column(lines, "waterway").map(line_widths).fillna(2.0).astype(float)
            buffered = lines.geometry.to_crs(crs_metric).buffer(width.values / 2, cap_style="flat")
            parts.append(buffered.to_crs(raw.crs))

    areas = gpd.GeoDataFrame(geometry=pd.concat(parts).values, crs=raw.crs)
    return _clip(_polygons_only(areas), bbox)


# --------------------------------------------------------------------------
# Öffentliche Funktion
# --------------------------------------------------------------------------

def _query_overpass(bbox: BBox, tags: dict) -> gpd.GeoDataFrame:
    """Fragt die Overpass-Server der Reihe nach ab, mit Wiederholungen bei Überlast."""
    import osmnx as ox

    last_error = None
    for url in OVERPASS_URLS:
        ox.settings.overpass_url = url
        for wait in (0, *RETRY_WAITS_S):
            time.sleep(wait)
            try:
                return ox.features_from_bbox(bbox, tags)
            except ox._errors.InsufficientResponseError:
                # Kein einziges Objekt im Gebiet (z. B. offenes Meer).
                return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
            except ox._errors.ResponseStatusCodeError as error:
                last_error = error      # Server überlastet -> gleich noch einmal
            except Exception as error:  # Zeitüberschreitung, keine Verbindung …
                last_error = error
                break                   # -> nächster Server
    reason = str(last_error).splitlines()[0] if last_error else "unbekannt"
    raise ConnectionError(f"Kein Overpass-Server hat geantwortet ({reason})")


def fetch_osm(bbox: BBox, cache_folder: str = ".cache/osmnx") -> OsmData:
    """Lädt alle benötigten OSM-Ebenen für die Bounding-Box in einer Abfrage.

    Gebäude, die die Box nur anschneiden, bleiben vollständig erhalten;
    Straßen, Grün- und Wasserflächen werden auf die Box zugeschnitten.
    """
    import osmnx as ox

    ox.settings.use_cache = True
    ox.settings.cache_folder = cache_folder
    ox.settings.requests_timeout = 60
    # Die vorgeschaltete Status-Abfrage des Overpass-Servers dauert oft länger
    # als die eigentliche Abfrage; bei Überlast wiederholt osmnx ohnehin.
    ox.settings.overpass_rate_limit = False

    # Bewusst ganze Schlüssel statt einzelner Werte: Jeder einzelne Wert würde
    # die Overpass-Abfrage um drei Teilabfragen verlängern (deutlich langsamer).
    # Welche Werte als Grün bzw. Wasser zählen, wird unten lokal gefiltert.
    tags = {key: True for key in
            ("building", "highway", "leisure", "landuse", "natural", "waterway")}
    raw = _query_overpass(tuple(bbox), tags)

    crs_metric = metric_crs(bbox)
    if raw.empty:
        return OsmData(bbox, _empty(BUILDING_COLUMNS), _empty(["highway", "name", "width_m"]),
                       _empty([]), _empty([]))
    return OsmData(
        bbox=bbox,
        buildings=_prepare_buildings(raw, crs_metric),
        streets=_prepare_streets(raw, bbox),
        green=_prepare_areas(raw, GREEN_TAGS, bbox, crs_metric),
        water=_prepare_areas(raw, WATER_TAGS, bbox, crs_metric, WATERWAY_WIDTH_M),
    )


def height_source_summary(buildings: gpd.GeoDataFrame) -> pd.DataFrame:
    """Kleine Statistik: Woher stammen die Gebäudehöhen?"""
    if buildings.empty:
        return pd.DataFrame(columns=["Quelle der Höhe", "Gebäude", "Anteil"])
    counts = buildings["height_source"].value_counts()
    return pd.DataFrame({
        "Quelle der Höhe": counts.index,
        "Gebäude": counts.values,
        "Anteil": [f"{v / len(buildings):.0%}" for v in counts.values],
    })
