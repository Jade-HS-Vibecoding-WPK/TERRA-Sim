"""Modul F: Kaiju-Angriff (Planspiel mit einem Riesenmonster)."""

from __future__ import annotations

import streamlit as st

from modules.hazards import collapse_scale
from modules.viewer_webgpu import scene as vscene
from views.common import (damage_colors, damage_legend, damage_tooltips, legend_ramp, no_buildings, num,
                          page_header, scene_for, scene_origin, show_scene, wind_direction_label)
from views.common import current_kaiju

PRESETS = {"Jungtier · 30 m": 30, "Ausgewachsen · 80 m": 80, "Titan · 150 m": 150}


def _apply(height: int):
    st.session_state.kaiju_height = height


def render():
    from views.navigation import require_project

    model = require_project()
    page_header("Kaiju-Angriff", "Planspiel: Ein Riesenmonster läuft quer durch das Gebiet. Welche "
                                 "Gebäude liegen in der Schneise, und wo bieten hohe Häuser Deckung?")

    left, right = st.columns([1, 2.6], gap="large")
    with left:
        with st.container(border=True):
            st.markdown("**Monster**")
            for label, height in PRESETS.items():
                st.button(label, key=f"kaiju_{label}", width="stretch", on_click=_apply, args=(height,))
        with st.container(border=True):
            st.slider("Größe", 20, 150, step=5, format="%d m", key="kaiju_height")
            st.slider("Laufrichtung (wohin es läuft)", 0, 355, step=5, format="%d°", key="kaiju_heading")
            st.slider("Seitlicher Versatz des Wegs", -400, 400, step=10, format="%d m", key="kaiju_offset")
        result = current_kaiju(model)
        k = result.kpis
        h = k["height_m"]
        st.caption(f"Läuft nach **{wind_direction_label(st.session_state.kaiju_heading)}**. Schneise "
                   f"(Füße und Körper) {num(k['swath_m'])} m breit, Schwanz und Arme reichen "
                   f"{num(0.45 * h)} m weit, die Schritte erschüttern bis {num(0.8 * h)} m.")
        st.caption("Ein Spaß-Szenario für die Lehre – es zeigt, wie man eine Gefahr mit Weg, Reichweite "
                   "und Schadensstufen modelliert. Das Monster ist eine eigene Figur.")

    with right:
        c = st.columns(4)
        c[0].metric(f"Zerstört (von {k['buildings_total']})", num(k["destroyed"]))
        c[1].metric("Schwer beschädigt", num(k["heavy"] - k["destroyed"]), help="Schadensgrad 3–4")
        c[2].metric("BGF nicht nutzbar", f"{num(k['gfa_unusable_m2'])} m²",
                    help="Bruttogeschossfläche der Gebäude mit Schadensgrad 4–5 (geschätzt)")
        c[3].metric("Höher als das Monster", num(k["taller_buildings"]),
                    help="Gebäude, hinter denen man sich verstecken könnte")
        origin = scene_origin(model)
        extent = max(model.raster.nx, model.raster.ny) * model.raster.cell
        scene = scene_for(model, colors=damage_colors(result.damage), tips=damage_tooltips(model, result.damage),
                          overlay=result.overlay, ramp="heat", hazard=vscene.hazard("kaiju"),
                          monster=vscene.monster(result.extra["center"], origin, h,
                                                 st.session_state.kaiju_heading, travel_m=1.3 * extent),
                          building_scale=vscene.building_scale(collapse_scale(result.damage)))
        show_scene(scene, key="scene_kaiju", height=640)
        st.html(legend_ramp("heat", "Erschütterung", "Fußabdruck", "Weg des Monsters"))
        st.html(damage_legend())
    no_buildings(model)
