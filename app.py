"""TERRA-Sim – Terrain, Environment & Resilience Simulator.

Start:  streamlit run app.py

Diese Datei enthält nur die Oberfläche. Die eigentliche Arbeit steckt in den
wiederverwendbaren Modulen im Ordner ``modules/``.
"""

from __future__ import annotations

from dataclasses import dataclass

import geopandas as gpd
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import shapely
import streamlit as st
from shapely import affinity

from modules import mesh_builder, viewer_3d
from modules.map_selector import (bbox_center, bbox_from_center, bbox_size_m, clamp_bbox,
                                  geocode_address, render_map_selector)
from modules.osm_fetcher import OsmData, fetch_osm, height_source_summary, metric_crs
from modules.simulator import (BEAUFORT_NAMES, LC_BUILDING, LC_WATER, Raster, build_raster,
                               flood_curve, simulate_flood, simulate_rain, simulate_wind)
from modules.terrain_loader import DemGrid, flat_dem, load_dem

st.set_page_config(page_title="TERRA-Sim", page_icon="🌍", layout="wide")

MAX_SIDE_M = 1500
DEFAULT_SIDE_M = 500

PRESETS = {
    "Wilhelmshaven – Jade Hochschule": (53.5476, 8.0884),
    "Oldenburg – Innenstadt": (53.1400, 8.2140),
    "Passau – Altstadt (Dreiflüsseeck)": (48.5745, 13.4700),
    "Hamburg – HafenCity": (53.5413, 9.9930),
    "Köln – Altstadt am Rhein": (50.9385, 6.9620),
}

VIEWS = ["🗺️ Gebiet & Daten", "🏙️ 3D-Modell", "🌊 Hochwasser", "🌧️ Starkregen", "💨 Starkwind"]

RAIN_SCENARIOS = {
    "Starkregen (30 l/m²)": 30,
    "Heftiger Starkregen (50 l/m²)": 50,
    "Jahrhundertregen (100 l/m²)": 100,
    "Extremereignis (150 l/m²)": 150,
}

GREY = (214, 210, 204)
RED = (214, 48, 49)
ORANGE = (240, 140, 40)
SOURCE_COLORS = {"OSM-Höhe": (49, 163, 84), "OSM-Geschosse": (116, 169, 207), "Schätzung": (240, 180, 90)}


# ==========================================================================
# Datenmodell
# ==========================================================================

@dataclass
class Model:
    """Alles, was für ein Untersuchungsgebiet geladen und vorbereitet wurde."""

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


@st.cache_data(show_spinner=False, max_entries=16)
def cached_osm(bbox: tuple) -> OsmData:
    return fetch_osm(bbox)


@st.cache_data(show_spinner=False, max_entries=16)
def cached_dem(bbox: tuple) -> DemGrid:
    dem = load_dem(bbox)
    if dem.source == "flach":
        raise ConnectionError("Kein Höhendienst erreichbar")  # Fehlschlag nicht cachen
    return dem


def build_model(bbox: tuple, osm: OsmData, dem: DemGrid) -> Model:
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
    key = "_".join(f"{v:.5f}" for v in bbox)
    return Model(bbox, key, crs, osm, dem, buildings, buildings_wgs, streets, raster, zmin)


@st.cache_data(show_spinner="Starkregen wird berechnet …", max_entries=32)
def cached_rain(model_key: str, rain_mm: float, _raster: Raster, n_buildings: int):
    return simulate_rain(_raster, n_buildings, rain_mm)


@st.cache_data(show_spinner="Wind wird berechnet …", max_entries=64)
def cached_wind(model_key: str, direction: float, beaufort: int, _buildings: gpd.GeoDataFrame):
    return simulate_wind(_buildings, direction, beaufort)


# ==========================================================================
# Hilfen für die Oberfläche
# ==========================================================================

def num(value: float, digits: int = 0) -> str:
    """Zahl in deutscher Schreibweise (1.234,5)."""
    text = f"{value:,.{digits}f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def building_tooltips(model: Model, extra: list | None = None) -> list:
    b = model.buildings
    tips = []
    for i, (name, kind, height, levels, source, area) in enumerate(zip(
            b["name"], b["building"], b["height_m"], b["levels"], b["height_source"], b["area_m2"])):
        title = name or ("Gebäude" if kind == "yes" else kind.replace("_", " ").capitalize())
        tip = (f"<b>{title}</b><br>Höhe: {height:.1f} m ({levels:.0f} Geschosse, {source})"
               f"<br>Grundfläche: {area:.0f} m²")
        if extra is not None and extra[i]:
            tip += f"<br>{extra[i]}"
        tips.append(tip)
    return tips


def show_scene(layers: list, model: Model, key: str, height: int = 620):
    st.pydeck_chart(viewer_3d.make_deck(layers, model.bbox), height=height, key=key)


def base_layers(model: Model, overlay=None, ramp: str = "heat") -> list:
    return [
        viewer_3d.terrain_layer(model.raster, model.zmin, overlay, ramp),
        viewer_3d.street_layer(model.osm.streets, model.dem.sample, model.zmin),
    ]


def require_model() -> Model | None:
    model = st.session_state.get("model")
    if model is None:
        st.info("Noch kein Modell vorhanden. Wähle links ein Gebiet und klicke auf "
                "**Modell generieren**.")
    return model


def no_buildings_hint(model: Model) -> bool:
    if len(model.buildings) == 0:
        st.warning("In diesem Gebiet kennt OpenStreetMap keine Gebäude – "
                   "die Auswertung bleibt deshalb leer.")
        return True
    return False


# ==========================================================================
# Seitenleiste: Gebiet wählen & Modell erzeugen
# ==========================================================================

def set_area(lat: float, lon: float):
    st.session_state.bbox = bbox_from_center(lat, lon, st.session_state.side_m)


def on_preset_change():
    if st.session_state.preset:
        set_area(*PRESETS[st.session_state.preset])


def on_size_change():
    set_area(*bbox_center(st.session_state.bbox))


def generate_model():
    bbox = tuple(st.session_state.bbox)
    with st.status("Modell wird erzeugt …", expanded=True) as status:
        try:
            st.write("🗺️ Lade Gebäude, Straßen und Grünflächen aus OpenStreetMap … "
                     "(bei ausgelastetem Server bis zu einer Minute)")
            osm = cached_osm(bbox)
        except Exception as error:  # Netzwerk, Overpass-Limit …
            status.update(label="OpenStreetMap nicht erreichbar", state="error")
            st.error(f"Die OSM-Abfrage ist fehlgeschlagen: {error}")
            return
        st.write("⛰️ Lade Geländehöhen …")
        try:
            dem = cached_dem(bbox)
        except Exception:
            dem = flat_dem(bbox)
            st.warning("Kein Höhendienst erreichbar – es wird mit ebenem Gelände gerechnet.")
        st.write("🧱 Baue Raster und 3D-Modell …")
        st.session_state.model = build_model(bbox, osm, dem)
        st.session_state.pop("export", None)
        status.update(label="Modell fertig", state="complete", expanded=False)


def sidebar() -> str:
    ss = st.session_state
    ss.setdefault("side_m", DEFAULT_SIDE_M)
    ss.setdefault("bbox", bbox_from_center(*next(iter(PRESETS.values())), DEFAULT_SIDE_M))

    with st.sidebar:
        st.title("🌍 TERRA-Sim")
        st.caption("Terrain, Environment & Resilience Simulator")
        view = st.radio("Ansicht", VIEWS, key="view")

        st.divider()
        st.subheader("Untersuchungsgebiet")
        st.selectbox("Zu Beispielort springen", list(PRESETS), key="preset", index=None,
                     placeholder="Ort wählen …", on_change=on_preset_change)

        with st.form("address_form", border=False):
            query = st.text_input("Adresse suchen", placeholder="z. B. Marktplatz, Oldenburg")
            if st.form_submit_button("🔍 Suchen") and query.strip():
                try:
                    hit = geocode_address(query)
                except requests.RequestException as error:
                    hit = None
                    st.error(f"Adresssuche nicht erreichbar: {error}")
                else:
                    if hit is None:
                        st.warning("Keine Adresse gefunden.")
                if hit:
                    set_area(hit["lat"], hit["lon"])
                    st.success(hit["name"])

        st.slider("Kantenlänge des Gebiets (m)", 200, MAX_SIDE_M, step=50, key="side_m",
                  on_change=on_size_change)

        if st.button("🚀 Modell generieren", type="primary"):
            generate_model()

        model = ss.get("model")
        if model is not None:
            if tuple(model.bbox) != tuple(ss.bbox):
                st.warning("Das Gebiet wurde geändert – bitte Modell neu generieren.")
            else:
                st.success(f"Modell aktuell: {len(model.buildings)} Gebäude")
    return view


# ==========================================================================
# Ansicht: Gebiet & Daten
# ==========================================================================

def view_area():
    ss = st.session_state
    st.header("🗺️ Gebiet & Daten")
    width, height = bbox_size_m(ss.bbox)
    st.caption(f"Aktuelles Gebiet: {num(width)} m × {num(height)} m "
               f"(Mittelpunkt {bbox_center(ss.bbox)[0]:.5f}°, {bbox_center(ss.bbox)[1]:.5f}°)")

    mode = st.radio("Auswahl auf der Karte", ["Klick setzt den Mittelpunkt", "Rechteck aufziehen"],
                    horizontal=True, label_visibility="collapsed")
    draw_mode = mode == "Rechteck aufziehen"
    selection = render_map_selector(ss.bbox, draw_mode=draw_mode)

    if selection.clicked and selection.clicked != ss.get("last_click"):
        ss.last_click = selection.clicked
        set_area(*selection.clicked)
        st.rerun()
    if selection.drawn_bbox and selection.drawn_bbox != ss.get("last_drawn"):
        ss.last_drawn = selection.drawn_bbox
        ss.bbox = clamp_bbox(selection.drawn_bbox, MAX_SIDE_M)
        st.rerun()

    model = ss.get("model")
    if model is None:
        st.info("Gebiet festlegen und links auf **Modell generieren** klicken.")
        return

    st.subheader("Geladene Daten")
    raster, dem = model.raster, model.dem
    cols = st.columns(5)
    cols[0].metric("Gebäude", num(len(model.buildings)))
    cols[1].metric("Straßen & Wege", f"{num(model.streets.length.sum() / 1000, 1)} km")
    cols[2].metric("Versiegelungsgrad", f"{raster.sealed_share:.0%}")
    cols[3].metric("Geländehöhe", f"{num(dem.min, 1)} – {num(dem.max, 1)} m")
    cols[4].metric("Höhendaten", dem.source)
    if dem.source == "flach":
        st.warning("Es konnten keine Geländehöhen geladen werden. Hochwasser und Starkregen "
                   "sind auf ebenem Gelände nicht aussagekräftig.")

    left, right = st.columns(2)
    with left:
        st.markdown("**Woher stammen die Gebäudehöhen?**")
        st.dataframe(height_source_summary(model.buildings), hide_index=True)
        st.caption("Nur ein Teil der Gebäude hat in OpenStreetMap eine gemessene Höhe. "
                   "Fehlt sie, rechnet TERRA-Sim mit Geschosszahl × 3 m oder einem "
                   "typischen Wert für den Gebäudetyp.")
    with right:
        st.markdown("**Flächenbilanz**")
        shares = raster.landcover_shares()
        st.dataframe(pd.DataFrame({"Fläche": list(shares),
                                   "Anteil": [f"{v:.0%}" for v in shares.values()]}),
                     hide_index=True)
        st.caption(f"Analyse-Raster: {raster.nx} × {raster.ny} Zellen à {num(raster.cell, 1)} m.")


# ==========================================================================
# Ansicht: 3D-Modell & Export
# ==========================================================================

def building_colors(model: Model, mode: str) -> np.ndarray:
    b = model.buildings
    if mode == "Gebäudehöhe":
        top = max(1.0, float(b["height_m"].quantile(0.98)))
        return viewer_3d.color_ramp(b["height_m"].to_numpy() / top, "height")
    if mode == "Datenquelle der Höhe":
        return np.array([SOURCE_COLORS[s] for s in b["height_source"]], dtype=float)
    return np.tile(np.array(GREY, dtype=float), (len(b), 1))


def make_export(model: Model, fmt: str, lod: int, with_terrain: bool):
    raster = model.raster
    origin = np.array([raster.x0 + raster.nx * raster.cell / 2,
                       raster.y0 + raster.ny * raster.cell / 2, model.zmin])
    meshes = [mesh_builder.recenter(m.all(), origin)
              for m in mesh_builder.buildings_meshes(model.buildings, lod)]
    terrain = None
    if with_terrain:
        step = max(1, int(np.ceil(max(raster.nx, raster.ny) / 100)))
        terrain = mesh_builder.recenter(mesh_builder.terrain_triangles(
            raster.corner_x, raster.corner_y, raster.corner_z, step), origin)

    parts = {"Gebaeude": np.concatenate(meshes) if meshes else mesh_builder.EMPTY}
    if terrain is not None:
        parts["Gelaende"] = terrain

    name = f"terra-sim_lod{lod}"
    if fmt == "OBJ":
        lat, lon = bbox_center(model.bbox)
        note = (f"Mittelpunkt: {lat:.6f} N, {lon:.6f} E ({model.crs})\n"
                f"Nullpunkt Z = {model.zmin:.2f} m (tiefster Geländepunkt)")
        return mesh_builder.export_obj(parts, note).encode("utf-8"), f"{name}.obj", "text/plain"
    if fmt == "STL":
        return mesh_builder.export_stl(parts), f"{name}.stl", "model/stl"
    footprints = [affinity.translate(g, -origin[0], -origin[1]) for g in model.buildings.geometry]
    streets = [affinity.translate(g, -origin[0], -origin[1]) for g in model.streets.geometry]
    text = mesh_builder.export_dxf(meshes, terrain, footprints, streets)
    return text.encode("utf-8"), f"{name}.dxf", "application/dxf"


def view_model(model: Model):
    st.header("🏙️ 3D-Modell")
    c1, c2 = st.columns(2)
    lod_label = c1.radio("Detailgrad", ["LOD 1 – Klötzchenmodell", "LOD 2 – mit Dachformen"],
                         horizontal=True)
    color_mode = c2.radio("Einfärbung", ["Einheitlich", "Gebäudehöhe", "Datenquelle der Höhe"],
                          horizontal=True)
    lod = 2 if lod_label.startswith("LOD 2") else 1

    b = model.buildings
    layers = base_layers(model)
    if len(b):
        layers += viewer_3d.building_layers(model.buildings_wgs, b, model.zmin,
                                            building_colors(model, color_mode),
                                            building_tooltips(model), lod)
    show_scene(layers, model, key="scene_model")

    with_roof = int(((b["roof_shape"] != "flat") & (b["roof_height_m"] > 0)).sum()) if len(b) else 0
    cols = st.columns(4)
    cols[0].metric("Gebäude", num(len(b)))
    cols[1].metric("Mittlere Höhe", f"{num(b['height_m'].mean(), 1)} m" if len(b) else "–")
    cols[2].metric("Höchstes Gebäude", f"{num(b['height_m'].max(), 1)} m" if len(b) else "–")
    cols[3].metric("Mit Dachform in OSM", num(with_roof))
    if lod == 2 and with_roof == 0:
        st.info("In diesem Gebiet ist in OpenStreetMap keine Dachform hinterlegt – "
                "LOD 2 sieht deshalb aus wie LOD 1.")
    if color_mode == "Datenquelle der Höhe":
        st.caption("🟢 gemessene Höhe aus OSM · 🔵 aus Geschosszahl berechnet · 🟠 geschätzt")

    st.subheader("📦 Export für CAD & 3D-Druck")
    e1, e2, e3 = st.columns([1, 1, 2])
    fmt = e1.selectbox("Format", ["OBJ", "STL", "DXF"])
    with_terrain = e2.checkbox("Gelände mit exportieren", value=True)
    e3.caption("Einheit Meter, Z = oben. Nullpunkt ist die Gebietsmitte auf Höhe des tiefsten "
               "Geländepunkts. DXF enthält zusätzlich 2D-Grundrisse und Straßenachsen "
               "auf eigenen Layern.")
    signature = (model.key, fmt, lod, with_terrain)
    if st.button("Export erzeugen"):
        with st.spinner("Export wird erzeugt …"):
            st.session_state.export = (signature, *make_export(model, fmt, lod, with_terrain))
    export = st.session_state.get("export")
    if export and export[0] == signature:
        _, data, filename, mime = export
        st.download_button(f"⬇️ {filename} herunterladen ({num(len(data) / 1e6, 1)} MB)",
                           data, file_name=filename, mime=mime)


# ==========================================================================
# Ansicht: Modul A – Hochwasser
# ==========================================================================

def view_flood(model: Model):
    st.header("🌊 Modul A: Hochwasser")
    st.caption("„Badewannen-Modell“: Alles, was unter dem Wasserspiegel liegt, gilt als überflutet.")
    raster, b = model.raster, model.buildings

    references = {"Tiefster Geländepunkt im Gebiet": float(raster.elevation.min())}
    water_cells = raster.landcover == LC_WATER
    if water_cells.any():
        references["Wasserspiegel der Gewässer im Gebiet"] = float(np.median(raster.elevation[water_cells]))
    references["Meeresspiegel (0 m ü. NHN)"] = 0.0

    c1, c2 = st.columns([2, 1])
    gauge = c1.slider("Wasserpegel über Bezugsniveau", 0.0, 10.0, 1.0, 0.1, format="+%.1f m")
    reference = c2.selectbox("Bezugsniveau", list(references))
    base = references[reference]
    level = base + gauge
    result = simulate_flood(raster, b, level)
    k = result.kpis

    cols = st.columns(4)
    cols[0].metric("Betroffene Gebäude", f"{k['buildings_affected']} von {k['buildings_total']}")
    cols[1].metric("Überflutete BGF (EG)", f"{num(k['flooded_gfa_m2'])} m²")
    cols[2].metric("Überflutete Fläche", f"{k['flooded_share']:.0%}",
                   help=f"{num(k['flooded_area_m2'])} m² des Untersuchungsgebiets, "
                        f"davon {num(k['flooded_street_m2'])} m² Straßen und Wege")
    cols[3].metric("Größte Wassertiefe", f"{num(k['max_depth_m'], 1)} m")

    layers = base_layers(model)
    if len(b):
        colors = np.where(result.affected[:, None], np.array(RED, float), np.array(GREY, float))
        extra = [f"<b style='color:#ff8a80'>Wassertiefe am Gebäude: {d:.1f} m</b>" if hit else ""
                 for d, hit in zip(result.building_depth, result.affected)]
        layers += viewer_3d.building_layers(model.buildings_wgs, b, model.zmin, colors,
                                            building_tooltips(model, extra), lod=1)
    if level > model.zmin:
        layers.append(viewer_3d.water_layer(model.bbox, level - model.zmin))
    show_scene(layers, model, key="scene_flood")
    st.caption(f"Wasserspiegel bei {num(level, 1)} m ü. NHN (Bezugsniveau {num(base, 1)} m). "
               "Rote Gebäude stehen im Wasser.")

    if no_buildings_hint(model):
        return
    curve = flood_curve(b, base)
    fig = go.Figure()
    fig.add_scatter(x=curve["Pegel (m)"], y=curve["Überflutete BGF EG (m²)"], mode="lines",
                    fill="tozeroy", line=dict(color="#2678dc"), name="Überflutete BGF (EG)")
    fig.add_vline(x=gauge, line_dash="dash", line_color="#d63031",
                  annotation_text=f"aktuell +{gauge:.1f} m")
    fig.update_layout(height=300, margin=dict(l=10, r=10, t=30, b=10), showlegend=False,
                      xaxis_title="Wasserpegel über Bezugsniveau (m)",
                      yaxis_title="Überflutete BGF im EG (m²)")
    st.plotly_chart(fig, key="flood_curve")

    with st.expander(f"Liste der betroffenen Gebäude ({k['buildings_affected']})"):
        table = pd.DataFrame({
            "Name / Typ": [n or t for n, t in zip(b["name"], b["building"])],
            "Grundfläche (m²)": b["area_m2"].round(0),
            "Geländehöhe (m)": b["ground_m"].round(2),
            "Wassertiefe (m)": result.building_depth.round(2),
        })[result.affected].sort_values("Wassertiefe (m)", ascending=False)
        st.dataframe(table, hide_index=True)


# ==========================================================================
# Ansicht: Modul B – Starkregen
# ==========================================================================

def view_rain(model: Model):
    st.header("🌧️ Modul B: Starkregen & Oberflächenabfluss")
    st.caption("Der Regen fließt je nach Versiegelung ab, folgt dem Gefälle und staut sich in Senken.")
    raster, b = model.raster, model.buildings

    c1, c2 = st.columns([1, 1])
    scenario = c1.selectbox("Szenario", list(RAIN_SCENARIOS), index=2)
    display = c2.radio("Heatmap zeigt", ["Risiko-Index", "Wassertiefe in Senken", "Abflussbahnen"],
                       horizontal=True)
    rain_mm = RAIN_SCENARIOS[scenario]
    result = cached_rain(model.key, rain_mm, raster, len(b))
    k = result.kpis

    cols = st.columns(5)
    cols[0].metric("Versiegelungsgrad", f"{k['sealed_share']:.0%}")
    cols[1].metric("Oberflächenabfluss", f"{num(k['runoff_m3'])} m³",
                   help=f"{k['runoff_coeff']:.0%} des Niederschlags ({num(k['rain_m3'])} m³) "
                        "fließen oberflächlich ab.")
    cols[2].metric("Wasserfläche ≥ 10 cm", f"{num(k['ponding_area_m2'])} m²")
    cols[3].metric("Größte Wassertiefe", f"{num(k['max_ponding_m'], 2)} m")
    cols[4].metric("Gebäude mit Rückstau-Risiko", f"{k['buildings_affected']} von {k['buildings_total']}")

    if display == "Wassertiefe in Senken":
        overlay, ramp = np.clip(result.ponding_depth / 0.5, 0, 1), "water"
        legend = "Hellblau = wenige Zentimeter, Dunkelblau = 50 cm und mehr."
    elif display == "Abflussbahnen":
        flow = np.clip(np.log10(np.maximum(result.flow_m3, 1e-9) / 50) / 2, 0, 1)
        off_ground = np.isin(raster.landcover, (LC_BUILDING, LC_WATER))
        overlay, ramp = np.where(off_ground, 0, flow), "water"
        legend = "Je dunkler, desto mehr Wasser fließt hier zusammen (ab ca. 50 m³)."
    else:
        overlay, ramp = result.risk, "heat"
        legend = "Gelb = erhöhter Abfluss, Rot = Wasseransammlung in einer Senke."

    layers = base_layers(model, overlay, ramp)
    if len(b):
        colors = np.where(result.affected[:, None], np.array(ORANGE, float), np.array(GREY, float))
        extra = [f"<b style='color:#ffcc80'>Wasser am Gebäude: bis {d * 100:.0f} cm</b>" if hit else ""
                 for d, hit in zip(result.building_depth, result.affected)]
        layers += viewer_3d.building_layers(model.buildings_wgs, b, model.zmin, colors,
                                            building_tooltips(model, extra), lod=1)
    show_scene(layers, model, key="scene_rain")
    st.caption(f"{legend} Orange Gebäude grenzen an eine Wasseransammlung von mindestens 10 cm.")
    if model.dem.source == "flach":
        st.warning("Ohne Geländehöhen gibt es kein Gefälle – das Ergebnis ist nicht aussagekräftig.")


# ==========================================================================
# Ansicht: Modul C – Starkwind
# ==========================================================================

COMPASS = ["Nord", "Nordost", "Ost", "Südost", "Süd", "Südwest", "West", "Nordwest"]


def view_wind(model: Model):
    st.header("💨 Modul C: Starkwind & Düseneffekte")
    st.caption("Sichtlinien-Analyse: Welche Fassaden stehen frei im Wind, wo wird er in "
               "engen Gassen beschleunigt?")
    b = model.buildings

    c1, c2 = st.columns(2)
    direction = c1.slider("Windrichtung (woher der Wind kommt)", 0, 355, 270, 5, format="%d°")
    beaufort = c2.slider("Windstärke (Beaufort)", 0, 12, 9)
    result = cached_wind(model.key, direction, beaufort, b)
    k = result.kpis
    c1.caption(f"Wind aus **{COMPASS[round(direction / 45) % 8]}** ({direction}°)")
    c2.caption(f"**{BEAUFORT_NAMES[beaufort]}** – ca. {num(k['speed_kmh'])} km/h in 10 m Höhe")

    cols = st.columns(4)
    share = k["facade_area_high_m2"] / k["facade_area_total_m2"] if k["facade_area_total_m2"] else 0
    cols[0].metric("Stark belastete Fassaden", f"{num(k['facade_area_high_m2'])} m²",
                   help=f"{share:.0%} der gesamten Fassadenfläche stehen nahezu ungeschützt "
                        "und frontal im Wind (Exposition ≥ 60 %).")
    cols[1].metric("Größter Winddruck", f"{num(k['max_pressure_kn_m2'], 2)} kN/m²")
    cols[2].metric("Engstellen mit Düseneffekt", num(k["venturi_count"]))
    cols[3].metric("Spitze in Engstellen", f"{num(k['venturi_max_speed_ms'] * 3.6)} km/h"
                   if k["venturi_count"] else "–",
                   help="Geschätzte Windgeschwindigkeit in der am stärksten beschleunigten Gasse.")

    layers = base_layers(model)
    if len(b):
        ground = b["ground_m"].to_numpy(float)
        colors = np.tile(np.array(GREY, float), (len(b), 1))
        layers += viewer_3d.building_layers(model.buildings_wgs, b, model.zmin, colors,
                                            building_tooltips(model), lod=1)
        if beaufort > 0:
            layers.append(viewer_3d.facade_layer(result.facades, ground, model.zmin, model.crs))
            layers.append(viewer_3d.venturi_layer(result.venturi, ground, model.zmin, model.crs))
        top = float((ground + b["height_m"].to_numpy()).max() - model.zmin)
    else:
        top = float(model.raster.corner_z.max() - model.zmin)
    layers.append(viewer_3d.wind_arrow_layer(model.bbox, direction, top + 15))
    show_scene(layers, model, key="scene_wind")
    st.caption("Fassaden: 🟢 geschützt → 🟡 → 🔴 frei angeströmt. Pinke Balken markieren Gassen mit "
               "Düseneffekt, der blaue Pfeil zeigt die Strömungsrichtung.")
    no_buildings_hint(model)


# ==========================================================================
# Hauptprogramm
# ==========================================================================

def main():
    view = sidebar()
    if view == VIEWS[0]:
        view_area()
        return
    model = require_model()
    if model is None:
        return
    {VIEWS[1]: view_model, VIEWS[2]: view_flood, VIEWS[3]: view_rain, VIEWS[4]: view_wind}[view](model)


main()
