"""Schritt 1: Projektgebiet festlegen und alle Daten laden."""

from __future__ import annotations

import requests
import streamlit as st

from modules.map_selector import (bbox_center, bbox_from_center, bbox_size_m, clamp_bbox,
                                  geocode_address, render_map_selector)
from views.common import (build_model, cached_climate, cached_dem, cached_osm, get_model,
                          num, read_project_file)
from modules.dgm1_loader import candidates as dgm1_candidates
from modules.terrain_loader import flat_dem

MAX_SIDE_M = 1500
DEFAULT_SIDE_M = 500

PRESETS = {
    "Wilhelmshaven – Jade Hochschule": (53.5476, 8.0884),
    "Oldenburg – Innenstadt": (53.1400, 8.2140),
    "Passau – Altstadt (Dreiflüsseeck)": (48.5745, 13.4700),
    "Hamburg – HafenCity": (53.5413, 9.9930),
    "Köln – Altstadt am Rhein": (50.9385, 6.9620),
}


# --------------------------------------------------------------------------
# Zustand der Gebietsauswahl
# --------------------------------------------------------------------------

def _init():
    ss = st.session_state
    ss.setdefault("side_m", DEFAULT_SIDE_M)
    if "draft_bbox" not in ss:
        model = get_model()
        name, center = next(iter(PRESETS.items()))
        ss.draft_bbox = model.bbox if model else bbox_from_center(*center, DEFAULT_SIDE_M)
        ss.place_label = model.name if model else name.split(" – ")[0]
    ss.setdefault("project_name", "")


def _set_center(lat: float, lon: float, label: str | None = None):
    st.session_state.draft_bbox = bbox_from_center(lat, lon, st.session_state.side_m)
    if label:
        st.session_state.place_label = label


def _on_preset():
    choice = st.session_state.get("preset_choice")
    if choice:
        _set_center(*PRESETS[choice], label=choice.split(" – ")[0])


def _on_size():
    _set_center(*bbox_center(st.session_state.draft_bbox))


def _steps(active: int) -> str:
    labels = ["Standort wählen", "Daten laden", "Analysieren"]
    parts = []
    for i, label in enumerate(labels, start=1):
        state = "done" if i < active else ("active" if i == active else "")
        mark = "✓" if i < active else str(i)
        parts.append(f'<div class="terra-step {state}"><span class="num">{mark}</span>{label}</div>')
    return f'<div class="terra-steps">{"".join(parts)}</div>'


# --------------------------------------------------------------------------
# Laden
# --------------------------------------------------------------------------

def create_project(name: str, bbox: tuple, settings: dict | None = None):
    """Lädt alle Daten, baut das Modell und wechselt zur Übersicht."""
    from views.navigation import PAGES

    notes = []
    with st.status("Projekt wird angelegt …", expanded=True) as status:
        st.write("🗺️ Gebäude, Straßen, Grün- und Wasserflächen aus OpenStreetMap … "
                 "(bei ausgelastetem Server bis zu einer Minute)")
        try:
            osm = cached_osm(bbox)
        except Exception as error:
            status.update(label="OpenStreetMap nicht erreichbar", state="error")
            st.error(f"Die OSM-Abfrage ist fehlgeschlagen: {error}\n\n"
                     "Bitte in einer Minute erneut versuchen.")
            return
        st.write("⛰️ Geländehöhen (amtliches DGM1, sonst weltweites Höhenmodell) …")
        try:
            dem = cached_dem(bbox)
        except Exception:
            dem = flat_dem(bbox)
            notes.append("Kein Höhendienst erreichbar – es wird mit ebenem Gelände gerechnet. "
                         "Hochwasser und Starkregen sind so nicht aussagekräftig.")
        if dgm1_candidates(bbox) and not dem.source.startswith("DGM1"):
            notes.append("Das amtliche DGM1 war für dieses Gebiet nicht abrufbar (Server nicht erreichbar "
                         "oder Gebiet an einer Landesgrenze). Es wird das gröbere weltweite Höhenmodell "
                         f"genutzt ({dem.source}).")
        st.write("🌦️ Klimadaten der nächsten Wetterstation (Meteostat) …")
        climate, climate_error = None, ""
        try:
            climate = cached_climate(*(round(v, 3) for v in bbox_center(bbox)))
            if climate.empty:
                climate_error = "Im Umkreis von 60 km gibt es keine Wetterstation mit ausreichend Daten."
        except Exception as error:
            climate_error = f"Meteostat nicht erreichbar ({error})."
        if climate_error:
            notes.append(f"Klimadaten fehlen: {climate_error} Die Analysen nutzen dann Standardwerte.")
        st.write("🧱 Raster und 3D-Modell …")
        model = build_model(name, bbox, osm, dem, climate, climate_error)
        status.update(label="Projekt angelegt", state="complete", expanded=False)

    ss = st.session_state
    ss.model = model
    ss.pop("export", None)
    ss.load_notes = notes
    if settings:
        ss.update(settings)
    elif model.climate_ok:
        # Neues Projekt: Windanalyse mit der Hauptwindrichtung bei Starkwind beginnen
        from views.common import climate_info
        info = climate_info(model)
        if info.get("wind_dir_strong") is not None:
            ss.wind_dir = int(round(info["wind_dir_strong"] / 5) * 5) % 360
    st.switch_page(PAGES["overview"])


# --------------------------------------------------------------------------
# Seite
# --------------------------------------------------------------------------

def render():
    from views.navigation import PAGES

    _init()
    ss = st.session_state
    model = get_model()

    st.title("Neues Projekt")
    st.html(_steps(1))
    if model is not None:
        st.info(f"Das Projekt **{model.name}** ist geöffnet. Ein neues Projekt ersetzt es.")
        st.page_link(PAGES["overview"], label="Zurück zum geöffneten Projekt", icon=":material/arrow_back:")

    left, right = st.columns([1, 2.1], gap="large")

    with left:
        with st.container(border=True):
            st.subheader("1 · Standort festlegen")
            tab_address, tab_coords, tab_preset, tab_file = st.tabs(
                ["Adresse", "Koordinaten", "Beispielort", "Projektdatei"])

            with tab_address:
                with st.form("address_form", border=False):
                    query = st.text_input("Adresse oder Ort", placeholder="z. B. Schlossplatz, Oldenburg")
                    if st.form_submit_button("Suchen", icon=":material/search:") and query.strip():
                        try:
                            hit = geocode_address(query)
                        except requests.RequestException as error:
                            st.error(f"Adresssuche nicht erreichbar: {error}")
                        else:
                            if hit is None:
                                st.warning("Keine Adresse gefunden.")
                            else:
                                _set_center(hit["lat"], hit["lon"], label=hit["name"].split(",")[0])
                                st.success(hit["name"])

            with tab_coords:
                lat0, lon0 = bbox_center(ss.draft_bbox)
                with st.form("coord_form", border=False):
                    c1, c2 = st.columns(2)
                    lat = c1.number_input("Breite (°N)", -85.0, 85.0, float(round(lat0, 5)), format="%.5f")
                    lon = c2.number_input("Länge (°E)", -180.0, 180.0, float(round(lon0, 5)), format="%.5f")
                    if st.form_submit_button("Übernehmen", icon=":material/my_location:"):
                        _set_center(lat, lon, label=f"{lat:.3f}° N, {lon:.3f}° E")

            with tab_preset:
                st.selectbox("Beispielort", list(PRESETS), index=None, key="preset_choice",
                             placeholder="Ort wählen …", on_change=_on_preset)
                st.caption("Vorbereitete Orte mit unterschiedlichen Risiken: Küste, Flussufer, Altstadt.")

            with tab_file:
                upload = st.file_uploader("TERRA-Sim-Projektdatei (.json)", type=["json"])
                if upload is not None and st.button("Projekt öffnen", icon=":material/folder_open:",
                                                    type="primary"):
                    try:
                        project = read_project_file(upload.getvalue())
                    except (ValueError, KeyError, UnicodeDecodeError) as error:
                        st.error(f"Datei kann nicht gelesen werden: {error}")
                    else:
                        ss.draft_bbox = project["bbox"]
                        create_project(project["name"], project["bbox"], project["settings"])

            st.slider("Kantenlänge des Gebiets (m)", 200, MAX_SIDE_M, step=50, key="side_m",
                      on_change=_on_size)
            width, height = bbox_size_m(ss.draft_bbox)
            lat_c, lon_c = bbox_center(ss.draft_bbox)
            st.caption(f"Gebiet: {num(width)} × {num(height)} m · Mitte {lat_c:.5f}° N, {lon_c:.5f}° E")

        with st.container(border=True):
            st.subheader("2 · Projekt anlegen")
            name = st.text_input("Projektname", key="project_name",
                                 placeholder=ss.get("place_label") or "Projekt")
            st.caption("Geladen werden: Gebäude, Straßen, Grün- und Wasserflächen (OpenStreetMap), "
                       "Gelände (amtliches DGM1 mit 1 m Raster, wo verfügbar – sonst Open-Elevation / "
                       "Open-Meteo) und Klimadaten der nächsten Wetterstation (Meteostat). Danach werden "
                       "3D-Modell und Analysen freigeschaltet.")
            dgm1 = dgm1_candidates(tuple(ss.draft_bbox))
            st.caption(f"Höhenmodell für dieses Gebiet: **{dgm1[0].name}** (1-m-Raster)" if dgm1 else
                       "Für dieses Gebiet ist kein amtliches DGM1 eingebunden – es werden die "
                       "weltweiten, gröberen Höhenmodelle genutzt.")
            if st.button("Projekt anlegen & Daten laden", type="primary", icon=":material/rocket_launch:",
                         width="stretch"):
                create_project(name.strip() or ss.get("place_label") or "Projekt", tuple(ss.draft_bbox))

    with right:
        mode = st.segmented_control("Auswahl auf der Karte", ["Klick setzt Mittelpunkt", "Rechteck aufziehen"],
                                    default="Klick setzt Mittelpunkt", label_visibility="collapsed")
        draw_mode = mode == "Rechteck aufziehen"
        selection = render_map_selector(ss.draft_bbox, draw_mode=draw_mode, height=600)
        st.caption("Rot: Projektgebiet. Gebäude, die den Rand berühren, werden vollständig geladen.")

    if selection.clicked and selection.clicked != ss.get("last_click"):
        ss.last_click = selection.clicked
        _set_center(*selection.clicked, label=f"{selection.clicked[0]:.3f}° N, {selection.clicked[1]:.3f}° E")
        st.rerun()
    if selection.drawn_bbox and selection.drawn_bbox != ss.get("last_drawn"):
        ss.last_drawn = selection.drawn_bbox
        ss.draft_bbox = clamp_bbox(selection.drawn_bbox, MAX_SIDE_M)
        st.rerun()
