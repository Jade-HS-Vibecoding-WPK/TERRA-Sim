"""Gemeinsame Bausteine aller Seiten: Projektdaten, Zwischenspeicher, Hilfen."""

from __future__ import annotations

import html
import json
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
import streamlit as st
from shapely.geometry import box

from modules import viewer_3d, viewer_webgpu
from modules.viewer_webgpu import scene as vscene
from modules.climate_loader import (ClimateData, climate_summary, compass_name,
                                    kmh_to_beaufort, load_climate)
from modules.map_selector import bbox_center, bbox_size_m
from modules.osm_fetcher import OsmData, fetch_osm, metric_crs
from modules.simulator import (LC_BUILDING, LC_GREEN, LC_STREET, LC_WATER, Raster,
                               build_raster, simulate_flood, simulate_rain, simulate_wind, wind_field)
from modules.hazards import simulate_alien, simulate_earthquake, simulate_kaiju, simulate_tornado
from modules.terrain_loader import DemGrid, flat_dem, load_dem

ASSETS = Path(__file__).resolve().parent.parent / "assets"
PROJECT_FILE_VERSION = 1

# Farben: Grün = Normalzustand, Orange = Warnung, Rot = Gefahr/Schaden (wie assets/style.css)
GREY = (222, 226, 218)          # unbeschädigte Gebäude (leicht grünliches Hellgrau)
RED = (211, 58, 58)             # Gebäude im Wasser, Gefahr
ORANGE = (240, 140, 40)         # Warnung, z. B. Rückstau-Risiko beim Starkregen
SOURCE_COLORS = {"OSM-Höhe": (47, 158, 95), "OSM-Geschosse": (159, 214, 179), "Schätzung": (240, 180, 90)}

STANDARD_RAIN = {
    "Starkregen (30 l/m²)": 30,
    "Heftiger Starkregen (50 l/m²)": 50,
    "Jahrhundertregen (100 l/m²)": 100,
    "Extremereignis (150 l/m²)": 150,
}

# Einstellungen, die beim Seitenwechsel erhalten bleiben und im Projekt gespeichert werden
SETTINGS_DEFAULTS = {
    "flood_gauge": 1.0,
    "flood_ref": "Tiefster Geländepunkt im Gebiet",
    "rain_scenario": "Jahrhundertregen (100 l/m²)",
    "rain_display": "Risiko-Index",
    "wind_dir": 270,
    "wind_bft": 9,
    "model_lod": "LOD 1 – Klötzchenmodell",
    "model_color": "Einheitlich",
    "rain_sewer": 20,
    "rain_duration": "24 Stunden",
    "flood_official": True,
    "quake_mw": 5.5,
    "quake_dist_km": 15,
    "quake_soil": "Mittel (Kies, fester Lehm)",
    "tornado_ef": 3,
    "tornado_heading": 60,
    "tornado_offset": 0,
    "kaiju_height": 80,
    "kaiju_heading": 90,
    "kaiju_offset": 0,
    "kaiju_lasers": 6,
    "kaiju_helis": 4,
    "people_count": 300,
    "wind_ground": "Wind in Fußgängerhöhe",
    "wind_flow": True,
    "wind_arrow": True,
    "wind_rose": True,
    "alien_ufos": 2,
    "alien_size": 30,
    "alien_height": 60,
}
# Wertebereiche der Zahlen-Einstellungen (für Projektdateien)
SETTINGS_LIMITS = {
    "flood_gauge": (0.0, 10.0), "wind_dir": (0, 355), "wind_bft": (0, 12), "rain_sewer": (0, 60),
    "quake_mw": (3.0, 8.0), "quake_dist_km": (1, 150), "tornado_ef": (0, 5), "tornado_heading": (0, 355),
    "tornado_offset": (-400, 400), "kaiju_height": (20, 150), "kaiju_heading": (0, 355),
    "kaiju_offset": (-400, 400), "kaiju_lasers": (0, 20), "kaiju_helis": (0, 10),
    "people_count": (0, 1000), "alien_ufos": (1, 5), "alien_size": (10, 80), "alien_height": (25, 150),
}
DIRECTION_SETTINGS = {"wind_dir", "tornado_heading", "kaiju_heading"}   # in 5°-Schritten
RADIO_OPTIONS = {
    "wind_ground": ["Wind in Fußgängerhöhe", "Windschatten", "keine"],
    "quake_soil": ["Fels", "Mittel (Kies, fester Lehm)", "Weich (Sand, Ton, Auen)"],
    "rain_display": ["Risiko-Index", "Wassertiefe in Senken", "Abflussbahnen"],
    "rain_duration": ["1 Stunde", "6 Stunden", "24 Stunden"],
    "model_lod": ["LOD 1 – Klötzchenmodell", "LOD 2 – mit Dachformen"],
    "model_color": ["Einheitlich", "Gebäudehöhe", "Datenquelle der Höhe"],
}


# ==========================================================================
# Datenmodell
# ==========================================================================

@dataclass
class Model:
    """Alles, was für ein Projektgebiet geladen und vorbereitet wurde."""

    name: str
    bbox: tuple
    key: str                         # eindeutiger Name (für Zwischenspeicher)
    crs: str                         # metrisches Koordinatensystem
    osm: OsmData                     # Rohdaten in WGS84
    dem: DemGrid
    buildings: gpd.GeoDataFrame      # metrisch, inkl. ``ground_m``
    buildings_wgs: gpd.GeoDataFrame  # dieselben Gebäude in WGS84
    streets: gpd.GeoDataFrame        # metrisch
    raster: Raster
    zmin: float                      # tiefster Punkt der Szene
    climate: ClimateData | None
    climate_error: str = ""

    @property
    def center(self) -> tuple[float, float]:
        return bbox_center(self.bbox)

    @property
    def climate_ok(self) -> bool:
        return self.climate is not None and not self.climate.empty


def get_model() -> Model | None:
    return st.session_state.get("model")


@st.cache_data(show_spinner=False, max_entries=16)
def cached_osm(bbox: tuple) -> OsmData:
    return fetch_osm(bbox)


@st.cache_data(show_spinner=False, max_entries=16)
def cached_dem(bbox: tuple) -> DemGrid:
    dem = load_dem(bbox)
    if dem.source == "flach":
        raise ConnectionError("Kein Höhendienst erreichbar")  # Fehlschlag nicht cachen
    return dem


@st.cache_data(show_spinner=False, max_entries=16, ttl=7 * 24 * 3600)
def cached_climate(lat: float, lon: float) -> ClimateData:
    return load_climate(lat, lon)


@st.cache_data(show_spinner=False, max_entries=16)
def cached_climate_summary(model_key: str, _climate: ClimateData) -> dict:
    return climate_summary(_climate)


def build_model(name: str, bbox: tuple, osm: OsmData, dem: DemGrid,
                climate: ClimateData | None, climate_error: str = "") -> Model:
    crs = metric_crs(bbox)
    buildings_wgs = osm.buildings.reset_index(drop=True).copy()

    # Geländehöhe je Gebäude = tiefster Punkt entlang des Grundrisses
    if len(buildings_wgs):
        coords, owner = shapely.get_coordinates(np.asarray(buildings_wgs.geometry.values),
                                                return_index=True)
        heights = dem.sample(coords[:, 0], coords[:, 1])
        ground = pd.Series(heights).groupby(owner).min().reindex(range(len(buildings_wgs))).to_numpy()
    else:
        ground = np.zeros(0)
    buildings_wgs["ground_m"] = ground
    buildings = buildings_wgs.to_crs(crs)
    streets = osm.streets.to_crs(crs)

    raster = build_raster(bbox, crs, dem.sample, buildings, streets,
                          osm.green.to_crs(crs), osm.water.to_crs(crs))
    zmin = float(min(raster.corner_z.min(), ground.min() if len(ground) else np.inf))
    # eindeutig je Gebiet und Höhenquelle (andere Höhen = andere Ergebnisse)
    key = "_".join(f"{v:.5f}" for v in bbox) + f"_{dem.source}"
    return Model(name, bbox, key, crs, osm, dem, buildings, buildings_wgs, streets, raster,
                 zmin, climate, climate_error)


# ==========================================================================
# Kennzahlen, die mehrere Seiten brauchen
# ==========================================================================

def climate_info(model: Model) -> dict | None:
    if not model.climate_ok:
        return None
    return cached_climate_summary(model.key, model.climate)


def area_metrics(model: Model) -> dict:
    """Städtebauliche Kennzahlen des Gebiets (vgl. "Area metrics" in Forma)."""
    width, height = bbox_size_m(model.bbox)
    site_area = width * height
    b = model.buildings
    shares = {code: float((model.raster.landcover == code).mean())
              for code in (LC_GREEN, LC_STREET, LC_BUILDING, LC_WATER)}
    if len(b):
        x0, y0 = model.raster.x0, model.raster.y0
        site = box(x0, y0, x0 + model.raster.nx * model.raster.cell, y0 + model.raster.ny * model.raster.cell)
        inside = shapely.area(shapely.intersection(np.asarray(b.geometry.values), site))
        footprint = float(inside.sum())
        gfa = float((inside * b["levels"].to_numpy(float)).sum())
    else:
        footprint = gfa = 0.0
    return {
        "site_area_m2": site_area,
        "buildings": int(len(b)),
        "footprint_m2": footprint,
        "grz": footprint / site_area if site_area else 0.0,
        "gfa_m2": gfa,
        "gfz": gfa / site_area if site_area else 0.0,
        "mean_height_m": float(b["height_m"].mean()) if len(b) else 0.0,
        "max_height_m": float(b["height_m"].max()) if len(b) else 0.0,
        "sealed_share": model.raster.sealed_share,
        "green_share": shares[LC_GREEN],
        "water_share": shares[LC_WATER],
        "elevation_min": model.dem.min,
        "elevation_max": model.dem.max,
    }


def flood_references(model: Model) -> dict:
    raster = model.raster
    refs = {"Tiefster Geländepunkt im Gebiet": float(raster.elevation.min())}
    water_cells = raster.landcover == LC_WATER
    if water_cells.any():
        refs["Wasserspiegel der Gewässer im Gebiet"] = float(np.median(raster.elevation[water_cells]))
    refs["Meeresspiegel (0 m ü. NHN)"] = 0.0
    return refs


def rain_scenarios(model: Model) -> dict:
    """Standard-Szenarien, der stärkste gemessene Tagesregen am Standort und die amtlichen
    100-jährlichen Regen aus KOSTRA-DWD-2020 (Stunden- und Tagesregen)."""
    scenarios = dict(STANDARD_RAIN)
    table = official_kostra(model)
    if table.get(1440, {}).get(100):
        scenarios = {f"Amtlicher 100-jährlicher Tagesregen (KOSTRA, {num(table[1440][100])} l/m²)":
                     round(table[1440][100], 1), **scenarios}
    if table.get(60, {}).get(100):
        scenarios = {f"Amtlicher 100-jährlicher Stundenregen (KOSTRA, {num(table[60][100])} l/m²)":
                     round(table[60][100], 1), **scenarios}
    info = climate_info(model)
    if info and info.get("prcp_max_day"):
        label = (f"Stärkster Tagesregen am Standort ({num(info['prcp_max_day'])} l/m², "
                 f"{info['prcp_max_date']:%d.%m.%Y})")
        scenarios = {label: round(info["prcp_max_day"], 1), **scenarios}
    return scenarios


def wind_presets(model: Model) -> dict:
    """Wind-Szenarien aus den Messdaten: Name -> (Richtung, Beaufort)."""
    info = climate_info(model)
    if not info or info.get("wind_dir_strong") is None:
        return {}
    direction = int(info["wind_dir_strong"]) % 360
    return {
        "Typisch": (direction, int(kmh_to_beaufort(info["wind_p98"]))),
        "Gemessenes Maximum": (direction, int(kmh_to_beaufort(info["wind_max_hour"]))),
        "Sturm": (direction, 9),
        "Orkan": (direction, 12),
    }


@st.cache_data(show_spinner="Starkregen wird berechnet …", max_entries=32)
def cached_rain(model_key: str, rain_mm: float, sewer_mm: float, _raster: Raster, n_buildings: int):
    return simulate_rain(_raster, n_buildings, rain_mm, sewer_mm)


@st.cache_data(show_spinner="Wind wird berechnet …", max_entries=64)
def cached_wind(model_key: str, direction: float, beaufort: int, _buildings: gpd.GeoDataFrame):
    return simulate_wind(_buildings, direction, beaufort)


def current_flood(model: Model):
    refs = flood_references(model)
    ref = st.session_state.get("flood_ref")
    base = refs.get(ref, next(iter(refs.values())))
    level = base + float(st.session_state.get("flood_gauge", SETTINGS_DEFAULTS["flood_gauge"]))
    return simulate_flood(model.raster, model.buildings, level), base


def current_rain(model: Model):
    scenarios = rain_scenarios(model)
    label = st.session_state.get("rain_scenario")
    if label not in scenarios:
        label = SETTINGS_DEFAULTS["rain_scenario"]
    sewer = float(st.session_state.get("rain_sewer", SETTINGS_DEFAULTS["rain_sewer"]))
    return cached_rain(model.key, scenarios[label], sewer, model.raster, len(model.buildings)), label


@st.cache_data(show_spinner="Erdbeben wird berechnet …", max_entries=32)
def cached_quake(model_key: str, magnitude: float, distance_km: float, soil: str, _buildings):
    return simulate_earthquake(_buildings, magnitude, distance_km, soil)


@st.cache_data(show_spinner="Tornado wird berechnet …", max_entries=32)
def cached_tornado(model_key: str, ef: int, heading: float, offset: float, _buildings, _raster):
    return simulate_tornado(_buildings, _raster, ef, heading, offset)


@st.cache_data(show_spinner="Das Monster läuft los …", max_entries=32)
def cached_kaiju(model_key: str, height: float, heading: float, offset: float, lasers: int, helis: int,
                 _buildings, _raster):
    return simulate_kaiju(_buildings, _raster, height, heading, offset, lasers, helis)


@st.cache_data(show_spinner="UFOs nähern sich …", max_entries=32)
def cached_alien(model_key: str, count: int, size: float, height: float, _buildings, _raster):
    return simulate_alien(_buildings, _raster, count, size, height)


def current_alien(model: Model):
    return cached_alien(model.key, int(_setting("alien_ufos")), float(_setting("alien_size")),
                        float(_setting("alien_height")), model.buildings, model.raster)


def _setting(key: str):
    return st.session_state.get(key, SETTINGS_DEFAULTS[key])


def current_quake(model: Model):
    return cached_quake(model.key, float(_setting("quake_mw")), float(_setting("quake_dist_km")),
                        str(_setting("quake_soil")), model.buildings)


def current_tornado(model: Model):
    return cached_tornado(model.key, int(_setting("tornado_ef")), float(_setting("tornado_heading")),
                          float(_setting("tornado_offset")), model.buildings, model.raster)


def current_kaiju(model: Model):
    return cached_kaiju(model.key, float(_setting("kaiju_height")), float(_setting("kaiju_heading")),
                        float(_setting("kaiju_offset")), int(_setting("kaiju_lasers")),
                        int(_setting("kaiju_helis")), model.buildings, model.raster)


# Schadensgrad 0..5 -> Farbe (0 = Grau wie unbeschädigte Gebäude)
DAMAGE_COLORS = [GREY, (250, 222, 100), (246, 162, 62), (226, 88, 46), (178, 30, 42), (84, 18, 32)]


def damage_colors(damage) -> np.ndarray:
    damage = np.clip(np.asarray(damage, dtype=float), 0, 5)
    stops = np.array(DAMAGE_COLORS, dtype=float)
    low = np.minimum(np.floor(damage).astype(int), 4)
    t = (damage - low)[:, None]
    return stops[low] * (1 - t) + stops[low + 1] * t


def damage_legend() -> str:
    from modules.hazards import DAMAGE_NAMES
    return legend_swatches([(f"{g} {DAMAGE_NAMES[g]}", DAMAGE_COLORS[g]) for g in range(1, 6)])


def damage_tooltips(model: Model, damage, prefix: str = "") -> list:
    from modules.hazards import DAMAGE_NAMES
    extra = []
    for d in np.asarray(damage, dtype=float):
        g = int(np.clip(round(d), 0, 5))
        color = "#ffcc80" if g < 3 else "#ff8a80"
        extra.append(f"<b style='color:{color}'>{prefix}Schadensgrad {g} – {DAMAGE_NAMES[g]}</b>"
                     if g > 0 else f"{prefix}kein Schaden")
    return building_tooltips(model, extra)


@st.cache_data(show_spinner="Strömung wird berechnet …", max_entries=32)
def cached_wind_field(model_key: str, direction: float, beaufort: int, _raster: Raster, _heights):
    return wind_field(_raster, _heights, direction, beaufort)


# ==========================================================================
# Amtliche Daten (modules/gov_data.py) – je Standort einmal laden
# ==========================================================================

GOV_TTL = 30 * 24 * 3600
RAIN_DURATION_MIN = {"1 Stunde": 60, "6 Stunden": 360, "24 Stunden": 1440}


@st.cache_data(show_spinner="Starkregen-Statistik (DWD KOSTRA) wird geladen …", ttl=GOV_TTL)
def _kostra(lat: float, lon: float) -> dict:
    from modules.gov_data import kostra
    return kostra(lat, lon)


@st.cache_data(show_spinner="Amtliche Hochwassergefahrenkarten werden geladen …", ttl=GOV_TTL, max_entries=16)
def _floods(bbox: tuple) -> dict:
    from modules.gov_data import official_floods
    return official_floods(bbox)


@st.cache_data(show_spinner="Böen-Messreihe (DWD) wird geladen …", ttl=GOV_TTL)
def _gusts(lat: float, lon: float) -> dict:
    from modules.gov_data import gust_maxima
    return gust_maxima(lat, lon)


@st.cache_data(show_spinner="Windmessungen (DWD) werden geladen …", ttl=GOV_TTL)
def _dwd_wind(lat: float, lon: float) -> dict:
    from modules.gov_data import hourly_wind
    return hourly_wind(lat, lon)


@st.cache_data(show_spinner="Erdbebenzone (GFZ) wird abgefragt …", ttl=GOV_TTL)
def _quake_zone(lat: float, lon: float) -> dict:
    from modules.gov_data import quake_zone
    return quake_zone(lat, lon)


def _site(model: Model) -> tuple[float, float]:
    lat, lon = model.center
    return round(lat, 4), round(lon, 4)


def _safe(loader, *args):
    """Amtliche Daten laden; bei Netzwerk- oder Formatfehlern ``None`` statt Absturz."""
    try:
        return loader(*args)
    except Exception as error:   # Dienste sind extern – die App soll trotzdem laufen
        st.session_state.setdefault("_gov_errors", {})[getattr(loader, "__name__", "amtliche Daten")] = str(error)[:200]
        return None


def official_kostra(model: Model) -> dict:
    return _safe(_kostra, *_site(model)) or {}


def official_gusts(model: Model) -> dict:
    return _safe(_gusts, *_site(model)) or {}


def official_quake_zone(model: Model):
    return _safe(_quake_zone, *_site(model))


def measured_wind(model: Model) -> tuple:
    """Stündlicher Wind am Standort: bevorzugt 10 Jahre DWD, sonst Meteostat. -> (Tabelle, Quelle)."""
    dwd = _safe(_dwd_wind, *_site(model))
    if dwd:
        return dwd["hourly"], f"DWD-Station {dwd['station']} ({num(dwd['km'])} km)"
    if model.climate_ok and not model.climate.hourly.empty:
        return model.climate.hourly, model.climate.attribution
    return None, ""



def warm_official_data(model: Model):
    """Alle amtlichen Daten für das Projekt vorab laden (Fehler werden still übergangen)."""
    official_kostra(model)
    official_gusts(model)
    official_quake_zone(model)
    measured_wind(model)
    official_flood_impact(model)

@st.cache_data(show_spinner=False, max_entries=8)
def _flood_impact(model_key: str, _model: Model, _floods: dict) -> dict:
    from pyproj import Transformer
    transformer = Transformer.from_crs("EPSG:25832", _model.crs, always_xy=True)

    def project(xy: np.ndarray) -> np.ndarray:
        return np.column_stack(transformer.transform(xy[:, 0], xy[:, 1]))

    geoms = np.asarray(_model.buildings.geometry.values)
    out = {}
    for key, scenario in _floods.items():
        area = shapely.transform(scenario["geometry"], project)
        hit = shapely.intersects(geoms, area) if len(geoms) else np.zeros(0, bool)
        out[key] = {**{k: v for k, v in scenario.items() if k != "geometry"}, "geometry_model": area,
                    "buildings": int(hit.sum()), "hit": hit}
    return out


def official_flood_impact(model: Model):
    """Amtliche Überflutungsflächen im Gebiet und betroffene Gebäude je Szenario (None bei Fehler)."""
    floods = _safe(_floods, tuple(round(v, 5) for v in model.bbox))
    if floods is None:
        return None
    return _flood_impact(model.key, model, floods)


@st.cache_data(show_spinner=False, max_entries=64)
def _direction_stats(model_key: str, direction: int, beaufort: int, _hourly):
    from modules.climate_loader import direction_stats
    return direction_stats(_hourly, direction, beaufort)


def measured_direction_stats(model: Model, direction: int, beaufort: int) -> dict:
    """Gemessene Häufigkeit von Windrichtung und -stärke am Standort (leer ohne Daten)."""
    hourly, source = measured_wind(model)
    if hourly is None:
        return {}
    return {**_direction_stats(f"{model.key}_{source}", int(direction), int(beaufort), hourly), "source": source}


def current_wind_field(model: Model):
    direction = int(st.session_state.get("wind_dir", SETTINGS_DEFAULTS["wind_dir"]))
    beaufort = int(st.session_state.get("wind_bft", SETTINGS_DEFAULTS["wind_bft"]))
    return cached_wind_field(model.key, direction, beaufort, model.raster,
                             model.buildings["height_m"].to_numpy(float))


def current_wind(model: Model):
    direction = int(st.session_state.get("wind_dir", SETTINGS_DEFAULTS["wind_dir"]))
    beaufort = int(st.session_state.get("wind_bft", SETTINGS_DEFAULTS["wind_bft"]))
    return cached_wind(model.key, direction, beaufort, model.buildings), direction, beaufort


# ==========================================================================
# Projektdatei
# ==========================================================================

def project_file(model: Model) -> bytes:
    data = {
        "terra_sim_project": PROJECT_FILE_VERSION,
        "name": model.name,
        "bbox": list(model.bbox),
        "settings": {k: st.session_state.get(k, v) for k, v in SETTINGS_DEFAULTS.items()},
    }
    return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")


def read_project_file(raw: bytes) -> dict:
    """Prüft eine Projektdatei und gibt ``{"name", "bbox", "settings"}`` zurück."""
    data = json.loads(raw.decode("utf-8"))
    if data.get("terra_sim_project") != PROJECT_FILE_VERSION:
        raise ValueError("Keine TERRA-Sim-Projektdatei (oder unbekannte Version).")
    bbox = tuple(float(v) for v in data["bbox"])
    west, south, east, north = bbox
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError("Die Projektdatei enthält ein ungültiges Gebiet.")
    return {"name": str(data.get("name") or "Projekt"), "bbox": bbox,
            "settings": _clean_settings(data.get("settings", {}))}


def _clean_settings(raw: dict) -> dict:
    """Übernimmt nur bekannte Einstellungen mit passendem Typ und gültigem Wertebereich."""
    limits = SETTINGS_LIMITS
    clean = {}
    for key, default in SETTINGS_DEFAULTS.items():
        value = raw.get(key) if isinstance(raw, dict) else None
        if isinstance(default, bool):
            if isinstance(value, bool):
                clean[key] = value
        elif isinstance(default, str) and isinstance(value, str):
            if key not in RADIO_OPTIONS or value in RADIO_OPTIONS[key]:
                clean[key] = value                  # Auswahllisten prüfen die Seiten selbst
        elif isinstance(default, (int, float)) and isinstance(value, (int, float)) and not isinstance(value, bool):
            low, high = limits[key]
            value = min(max(value, low), high)
            if key in DIRECTION_SETTINGS:
                clean[key] = int(round(value / 5) * 5) % 360
            elif isinstance(default, int):
                clean[key] = int(round(value))
            else:
                clean[key] = round(float(value), 1)
    return clean


# ==========================================================================
# Darstellung
# ==========================================================================

def load_style():
    # Achtung: st.html verwirft einen <style>-Block komplett, wenn darin "<" vorkommt
    # (Schutz vor eingeschleustem HTML) – deshalb hier sicherheitshalber entfernen.
    css = (ASSETS / "style.css").read_text(encoding="utf-8").replace("<", "")
    st.html(f"<style>{css}</style>")


def num(value: float, digits: int = 0) -> str:
    """Zahl in deutscher Schreibweise (1.234,5)."""
    text = f"{value:,.{digits}f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


KIND_ICONS = {"paper": "📚", "norm": "📏", "data": "🗂️"}


def render_method(key: str):
    """Rechenweg einer Analyse mit Formeln, Annahmen, Grenzen und nummerierten Quellen (modules/methods.py)."""
    from modules.methods import METHODS
    from modules.sources import SOURCES
    method = METHODS[key]
    keys = method.source_keys
    number = {k: i + 1 for i, k in enumerate(keys)}

    def refs(step_sources) -> str:
        return " ".join(f"[[{number[k]}]]({SOURCES[k].link})" if SOURCES[k].link else f"[{number[k]}]"
                        for k in step_sources)

    st.markdown(method.summary)
    st.markdown("**Rechenweg**")
    for i, step in enumerate(method.steps, start=1):
        st.markdown(f"{i}. {step.text} {refs(step.sources)}")
        if step.formula:
            st.latex(step.formula)
    if method.assumptions:
        st.markdown("**Annahmen** – von TERRA-Sim gesetzt, nicht aus der Literatur")
        st.markdown("\n".join(f"- ⚙️ {a}" for a in method.assumptions))
    if method.limits:
        st.markdown("**Grenzen**")
        st.markdown("\n".join(f"- {a}" for a in method.limits))
    st.markdown("**Quellen**")
    lines = []
    for k in keys:
        s = SOURCES[k]
        link = f" [{s.link.replace('https://', '')}]({s.link})" if s.link else ""
        lines.append(f"{number[k]}. {KIND_ICONS.get(s.kind, '')} {s.reference}{link}")
    st.markdown("\n".join(lines))


def method_card(key: str):
    """Aufklappbare Karte „Methode & Quellen“ unter dem Kopf jeder Analyseseite."""
    from modules.methods import METHODS
    with st.expander(f"🔬 Methode & Quellen – so rechnet TERRA-Sim ({len(METHODS[key].source_keys)} Quellen)"):
        render_method(key)
        st.caption("Alle Quellen, Normen und Datensätze gesammelt (auch als BibTeX) unter **Methoden & Quellen** "
                   "in der Seitenleiste.")


def page_header(title: str, subtitle: str = ""):
    """Grüner Kopfbereich jeder Seite (Projekt, Titel, kurze Erklärung)."""
    model = get_model()
    crumb = ""
    if model is not None:
        lat, lon = model.center
        width, height = bbox_size_m(model.bbox)
        crumb = (f'<div class="crumb">Projekt <b>{html.escape(model.name)}</b> · '
                 f'{lat:.4f}° N, {lon:.4f}° E · {num(width)} × {num(height)} m</div>')
    sub = f"<p>{html.escape(subtitle)}</p>" if subtitle else ""
    st.html(f'<div class="terra-hero">{crumb}<h1>{html.escape(title)}</h1>{sub}</div>')


# ---------------------------------------------------------------------------
# Bento-Karten: Streamlit hängt den Schlüssel als CSS-Klasse an (st-key-…)
# ---------------------------------------------------------------------------

CARD_TONES = ("plain", "mint", "dark", "warn", "risk")


def reset_layout():
    """Zu Beginn jedes Durchlaufs: Kartennummern neu zählen (stabile Schlüssel)."""
    st.session_state["_card_n"] = 0


def _next_key(prefix: str) -> str:
    n = st.session_state.get("_card_n", 0) + 1
    st.session_state["_card_n"] = n
    return f"{prefix}-{n}"


def card(tone: str = "plain", height=None):
    """Bento-Karte: ``plain`` (weiß), ``mint`` (hellgrün), ``dark`` (dunkelgrün),
    ``warn`` (orange) oder ``risk`` (rot). Gebrauch: ``with card(): …``"""
    tone = tone if tone in CARD_TONES else "plain"
    kwargs = {"height": height} if height else {}
    return st.container(key=_next_key(f"card-{tone}"), **kwargs)


def tone_of(level: str) -> str:
    """Ampel-Stufe (ok | warn | risk | none) -> Kartenfarbe."""
    return {"warn": "warn", "risk": "risk"}.get(level, "plain")


def kpi_row(spec):
    """Reihe kleiner Kennzahl-Kacheln; ``spec`` wie bei ``st.columns``."""
    with st.container(key=_next_key("kpis")):
        return st.columns(spec)


def pill(text: str, level: str) -> str:
    """Kleine Status-Plakette; ``level`` = ok | warn | risk | none."""
    return f'<span class="terra-pill {level}">{html.escape(text)}</span>'


def risk_level(share: float, warn: float = 0.05, risk: float = 0.2) -> tuple[str, str]:
    if share >= risk:
        return "risk", "hohes Risiko"
    if share >= warn:
        return "warn", "erhöhtes Risiko"
    return "ok", "geringes Risiko"


def _rgb(color) -> str:
    return "rgb({},{},{})".format(*[int(c) for c in color])


def legend_swatches(items: list[tuple[str, tuple]]) -> str:
    parts = [f'<span><span class="swatch" style="background:{_rgb(c)}"></span>{html.escape(t)}</span>'
             for t, c in items]
    return f'<div class="terra-legend">{"".join(parts)}</div>'


def legend_ramp(ramp: str, low: str, high: str, title: str = "") -> str:
    stops = ", ".join(_rgb(c) for c in viewer_3d.COLOR_RAMPS[ramp])
    head = f"<span>{html.escape(title)}</span>" if title else ""
    return (f'<div class="terra-legend">{head}<span>{html.escape(low)}'
            f'<span class="ramp" style="background:linear-gradient(90deg,{stops})"></span>'
            f'{html.escape(high)}</span></div>')


def building_tooltips(model: Model, extra: list | None = None) -> list:
    b = model.buildings
    tips = []
    for i, (name, kind, height, levels, source, area) in enumerate(zip(
            b["name"], b["building"], b["height_m"], b["levels"], b["height_source"], b["area_m2"])):
        title = name or ("Gebäude" if kind == "yes" else kind.replace("_", " ").capitalize())
        tip = (f"<b>{html.escape(title)}</b><br>Höhe: {height:.1f} m ({levels:.0f} Geschosse, {source})"
               f"<br>Grundfläche: {area:.0f} m²")
        if extra is not None and extra[i]:
            tip += f"<br>{extra[i]}"
        tips.append(tip)
    return tips


def scene_origin(model: Model) -> tuple[float, float, float]:
    return vscene.origin_of(model.raster, model.zmin)


@st.cache_resource(show_spinner="3D-Szene wird vorbereitet …", max_entries=8)
def _terrain_scene(model_key: str, _model: Model) -> dict:
    m = _model
    return {
        "terrain": vscene.terrain(m.raster, scene_origin(m)),
        "texture": vscene.map_texture(m.raster, m.buildings, m.streets,
                                      m.osm.green.to_crs(m.crs), m.osm.water.to_crs(m.crs)),
        "walkways": vscene.walkways(m.streets, scene_origin(m), m.raster),
    }


@st.cache_resource(show_spinner="Gebäude werden vorbereitet …", max_entries=16)
def _building_scene(model_key: str, lod: int, _model: Model) -> dict:
    return vscene.buildings(_model.buildings, scene_origin(_model), lod, clip_raster=_model.raster)


def scene_for(model: Model, *, lod: int = 1, colors=None, tips: list | None = None,
              overlay=None, ramp: str = "heat", **layers) -> dict:
    """Szene für den 3D-Viewer: Gelände + Gebäude, dazu Analyse-Ebenen.

    ``overlay``  Raster 0..1 als Heatmap auf dem Gelände (Farbskala ``ramp``)
    ``layers``   weitere Ebenen aus ``viewer_webgpu.scene`` (water, facades, paths, arrow)
    """
    data = {**_terrain_scene(model.key, model), "buildings": _building_scene(model.key, lod, model)}
    if colors is not None:
        data["building_colors"] = vscene.colors(colors)
    data["building_tips"] = tips if tips is not None else building_tooltips(model)
    if overlay is not None:
        data["overlay"] = vscene.overlay(overlay, viewer_3d.color_ramp(overlay, ramp), raster=model.raster)
    data.update({k: v for k, v in layers.items() if v is not None})
    data["people"] = {"count": int(st.session_state.get("people_count", SETTINGS_DEFAULTS["people_count"]))}
    return data


def show_scene(scene: dict, key: str, height: int = 600):
    viewer_webgpu.show_scene(scene, key=key, height=height)
    st.caption("Linke Maustaste: verschieben · rechte Taste: drehen und kippen · Rad: zoomen · "
               "Gebäude überfahren für Details")


def no_buildings(model: Model) -> bool:
    if len(model.buildings) == 0:
        st.warning("In diesem Gebiet kennt OpenStreetMap keine Gebäude – die Auswertung bleibt leer.")
        return True
    return False


def wind_direction_label(direction: float) -> str:
    return f"{compass_name(direction)} ({int(direction)}°)"


# ---------------------------------------------------------------------------
# Wahrscheinlichkeit eines Szenarios (siehe modules/likelihood.py)
# ---------------------------------------------------------------------------

ODDS_COLORS = {"risk": "#d33a3a", "warn": "#f08c28", "ok": "#2f9e5f", "none": "#9fb5a8"}


def odds_bar(label: str, odds: dict, note: str = "") -> str:
    """Zeile mit Balken: Wahrscheinlichkeit in 30 Jahren (logarithmisch 0,001 % … 100 %)."""
    from modules.likelihood import LIFETIME_YEARS, percent
    p = odds.get("p_life")
    width = 0 if not p else max(2.0, min(100.0, (np.log10(max(p, 1e-5)) + 5) / 5 * 100))
    color = ODDS_COLORS.get(odds.get("level", "none"), ODDS_COLORS["none"])
    value = f"{percent(p)} in {LIFETIME_YEARS} J." if p is not None else "keine Angabe"
    sub = f'<div class="value" style="grid-column:1/-1;font-size:.76rem">{html.escape(note)}</div>' if note else ""
    return (f'<div class="terra-prob"><span class="label">{html.escape(label)}</span>'
            f'<span class="value">{html.escape(odds.get("text", ""))} · {value}</span>'
            f'<div class="bar"><span style="width:{width:.0f}%;background:{color}"></span></div>{sub}</div>')


def odds_line(odds: dict, source: str = "") -> str:
    """Kurzer Satz für Kacheln: „Wie oft? etwa alle 120 Jahre (22 % in 30 Jahren)“."""
    from modules.likelihood import LIFETIME_YEARS, percent
    if not odds or odds.get("T") is None:
        return ""
    color = ODDS_COLORS.get(odds["level"], ODDS_COLORS["none"])
    src = f" · {html.escape(source)}" if source else ""
    return (f'Wie oft? <b style="color:{color}">{html.escape(odds["text"])}</b> '
            f'({percent(odds["p_life"])} in {LIFETIME_YEARS} Jahren){src}')


def scenario_odds(model: Model) -> dict:
    """Wahrscheinlichkeit der aktuell eingestellten Szenarien: {Gefahr: (odds, Quelle)}.

    Gefahren: flood, rain, wind, quake, tornado, kaiju, alien (Planspiele, Modellrechnung).
    """
    from modules.hazards import EF_PATH_WIDTH_M
    from modules.likelihood import describe, tornado_return_period
    ss = st.session_state
    out = {}
    width, height = bbox_size_m(model.bbox)
    T = tornado_return_period(int(_setting("tornado_ef")), max(width, height), EF_PATH_WIDTH_M)
    from modules.likelihood import TORNADO_SOURCE
    out["tornado"] = (describe(T), TORNADO_SOURCE)
    from modules.likelihood import ALIEN_SOURCE, KAIJU_SOURCE, alien_return_period, kaiju_return_period
    swath = 0.5 * float(_setting("kaiju_height"))
    out["kaiju"] = (describe(kaiju_return_period(max(width, height), swath), exact=True, bound=True), KAIJU_SOURCE)
    out["alien"] = (describe(alien_return_period(), exact=True), ALIEN_SOURCE)
    out.update(_official_odds(model))
    return out


def _official_odds(model: Model) -> dict:
    """Szenarien mit amtlichen Daten (Starkregen, Hochwasser, Sturm, Erdbeben) – siehe gov_data.py."""
    from modules.likelihood import (describe, gumbel_fit, gumbel_return_period, quake_return_period_from_zone,
                                    rain_return_period)
    from modules.simulator import beaufort_to_ms
    out = {}

    # Starkregen: KOSTRA-Tabelle der gewählten Dauerstufe
    table = official_kostra(model)
    scenarios = rain_scenarios(model)
    label = st.session_state.get("rain_scenario")
    label = label if label in scenarios else SETTINGS_DEFAULTS["rain_scenario"]
    minutes = rain_duration_min(label)
    if table.get(minutes):
        T = rain_return_period(table[minutes], scenarios[label])
        out["rain"] = (describe(T), f"DWD KOSTRA-DWD-2020, als {RAIN_DURATION_NAME[minutes]}")

    # Hochwasser: häufigstes amtliches Szenario, das Gebäude erreicht
    impact = official_flood_impact(model)
    if impact is not None:
        hits = sorted((v for v in impact.values() if v["buildings"]), key=lambda v: v["T"])
        if hits:
            first = hits[0]
            out["flood"] = (describe(first["T"]), f"amtliche Gefahrenkarte: {first['buildings']} Gebäude im "
                                                  f"{first['name']}-Gebiet")
        else:
            text = ("kein Gebäude in amtlichen Überflutungsflächen" if impact
                    else "außerhalb amtlicher Überflutungsflächen")
            out["flood"] = ({"T": None, "p_year": 0.0, "p_life": None, "text": text, "level": "ok"},
                            "Hochwassergefahrenkarten der Länder (BfG)")

    # Sturm: Jahreshöchstwerte der Böen (Gumbel) und Anteil der Richtung bei starkem Wind
    beaufort = int(_setting("wind_bft"))
    gusts = official_gusts(model)
    if beaufort > 0 and gusts:
        gust = beaufort_to_ms(beaufort) * 3.6 * 1.5
        T_any = gumbel_return_period(gumbel_fit(gusts["maxima"].values), gust)
        stats = measured_direction_stats(model, int(_setting("wind_dir")), 6)
        share = stats.get("share_strong_from_dir") if stats else None
        if T_any and share:
            out["wind"] = (describe(T_any / (share / 100)),
                           f"Böen ab {num(gust)} km/h aus {stats['sector']}; aus allen Richtungen "
                           f"{describe(T_any)['text']} (DWD {gusts['station']}, {gusts['years']})")
        elif T_any:
            out["wind"] = (describe(T_any), f"Böen ab {num(gust)} km/h (DWD {gusts['station']}, {gusts['years']})")

    # Erdbeben: Zone am Ort und Intensität des Szenarios
    zone = official_quake_zone(model)
    if zone:
        intensity = current_quake(model).kpis["intensity"]
        T = quake_return_period_from_zone(zone["zone"], intensity)
        where = f"Erdbebenzone {zone['zone']}" if zone["zone"] is not None else "keine Erdbebenzone"
        out["quake"] = (describe(T), f"{where} ({zone['place']}), GFZ / DIN 4149")
    return out


RAIN_DURATION_NAME = {60: "Stundenregen", 360: "6-Stunden-Regen", 1440: "Tagesregen"}


def rain_duration_min(label: str) -> int:
    """Dauerstufe (Minuten) zum Regen-Szenario: amtliche/gemessene Szenarien haben eine feste Dauer."""
    if "Stundenregen" in label:
        return 60
    if "Tagesregen" in label:
        return 1440
    return RAIN_DURATION_MIN.get(st.session_state.get("rain_duration"), 1440)


def facts_html(items) -> str:
    """Große Kennzahlen, die umbrechen statt abgeschnitten zu werden (anders als ``st.metric``).

    ``items`` = [(Bezeichnung, Wert, Erläuterung oder None), …]
    """
    parts = []
    for label, value, note in items:
        sub = f'<div class="note">{html.escape(note)}</div>' if note else ""
        parts.append(f'<div class="terra-fact"><div class="lbl">{html.escape(label)}</div>'
                     f'<div class="val">{html.escape(value)}</div>{sub}</div>')
    return f'<div class="terra-facts">{"".join(parts)}</div>'


def odds_row(model: Model, key: str, explain: str = "", side=None):
    """Reihe über die volle Breite unter dem Seitenkopf: links „Wie wahrscheinlich?“,
    rechts optional eine Karte mit den amtlichen Daten dazu (``side`` = Funktion ohne Argumente)."""
    with st.container(key=_next_key("band")):
        if side is None:
            odds_card(model, key, explain)
            return
        a, b = st.columns([1, 1.15], gap="medium")
        with a:
            odds_card(model, key, explain)
        with b:
            side()


def odds_card(model: Model, key: str, explain: str = ""):
    """Karte „Wie wahrscheinlich?“ für eine Analyseseite (Gefahr ``key``, siehe scenario_odds)."""
    from modules.likelihood import LIFETIME_YEARS, percent
    odds, source = scenario_odds(model).get(key, ({}, ""))
    tone = {"risk": "risk", "warn": "warn"}.get(odds.get("level"), "mint")
    with card(tone):
        st.markdown("**Wie wahrscheinlich ist dieses Szenario?**")
        if not odds or odds.get("T") is None:
            st.caption(odds.get("text", "Für dieses Szenario liegen keine Daten zur Häufigkeit vor.")
                       if odds else "Für dieses Szenario liegen keine Daten zur Häufigkeit vor.")
            return
        from modules.likelihood import one_in
        tiny = odds["p_life"] < 0.001
        st.html(facts_html([
            ("Wie oft?", odds["text"], "im Mittel – nicht „genau alle …“"),
            (f"Chance in {LIFETIME_YEARS} Jahren", percent(odds["p_life"]),
             (f"also {one_in(odds['p_life'])}" if tiny else "mindestens einmal")
             + f"; pro Jahr {percent(odds['p_year'])}"),
        ]))
        if explain or source:
            st.caption(" ".join(t for t in (explain, f"Quelle: {source}." if source else "") if t))
