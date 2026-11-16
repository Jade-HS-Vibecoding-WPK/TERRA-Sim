"""Modul B: Starkregen & Oberflächenabfluss."""

from __future__ import annotations

import numpy as np
import streamlit as st

from modules import viewer_3d
from modules.simulator import LC_BUILDING, LC_WATER
from views.common import (GREY, ORANGE, RADIO_OPTIONS, base_layers, building_tooltips, climate_info,
                          current_rain, legend_ramp, legend_swatches, num, page_header, rain_scenarios,
                          show_scene)

DISPLAYS = RADIO_OPTIONS["rain_display"]


def render():
    from views.navigation import require_project

    model = require_project()
    page_header("Starkregen", "Der Regen fließt je nach Versiegelung ab, folgt dem Gefälle und staut sich in Senken.")
    scenarios = rain_scenarios(model)
    if st.session_state.rain_scenario not in scenarios:
        st.session_state.rain_scenario = "Jahrhundertregen (100 l/m²)"
    raster, b = model.raster, model.buildings

    left, right = st.columns([1, 2.6], gap="large")
    with left:
        with st.container(border=True):
            st.markdown("**Szenario**")
            st.selectbox("Regenmenge", list(scenarios), key="rain_scenario")
            st.radio("Heatmap zeigt", DISPLAYS, key="rain_display")
            info = climate_info(model)
            if info and info.get("prcp_max_day"):
                st.caption(f"Am Standort gemessen ({info['years']}): stärkster Tagesregen "
                           f"{num(info['prcp_max_day'])} l/m², im Mittel {num(info['heavy_rain_days'], 1)} "
                           "Tage pro Jahr mit mindestens 20 l/m².")
        result, _ = current_rain(model)
        k = result.kpis
        st.caption(f"Versiegelungsgrad des Gebiets: {k['sealed_share']:.0%} – "
                   f"{k['runoff_coeff']:.0%} des Regens fließen oberflächlich ab.")
        if model.dem.source == "flach":
            st.warning("Ohne Geländehöhen gibt es kein Gefälle – das Ergebnis ist nicht aussagekräftig.")

    display = st.session_state.rain_display
    if display == "Wassertiefe in Senken":
        overlay, ramp = np.clip(result.ponding_depth / 0.5, 0, 1), "water"
        legend = legend_ramp("water", "wenige cm", "≥ 50 cm", "Wassertiefe")
    elif display == "Abflussbahnen":
        flow = np.clip(np.log10(np.maximum(result.flow_m3, 1e-9) / 50) / 2, 0, 1)
        off_ground = np.isin(raster.landcover, (LC_BUILDING, LC_WATER))
        overlay, ramp = np.where(off_ground, 0, flow), "water"
        legend = legend_ramp("water", "50 m³", "≥ 5.000 m³", "Zusammenfließendes Wasser")
    else:
        overlay, ramp = result.risk, "heat"
        legend = legend_ramp("heat", "erhöhter Abfluss", "Wasseransammlung", "Risiko")

    with right:
        c = st.columns(4)
        c[0].metric(f"Gebäude (von {k['buildings_total']})", num(k["buildings_affected"]),
                    help="Gebäude mit Rückstau-Risiko: Am Gebäude sammeln sich mindestens 10 cm Wasser.")
        c[1].metric("Oberflächenabfluss", f"{num(k['runoff_m3'])} m³",
                    help=f"Von {num(k['rain_m3'])} m³ Niederschlag auf der Landfläche")
        c[2].metric("Wasser ≥ 10 cm", f"{num(k['ponding_area_m2'])} m²", help="Fläche, auf der das Wasser "
                    "mindestens 10 cm hoch steht")
        c[3].metric("Max. Wassertiefe", f"{num(k['max_ponding_m'], 2)} m")
        layers = base_layers(model, overlay, ramp)
        if len(b):
            colors = np.where(result.affected[:, None], np.array(ORANGE, float), np.array(GREY, float))
            extra = [f"<b style='color:#ffcc80'>Wasser am Gebäude: bis {d * 100:.0f} cm</b>" if hit else ""
                     for d, hit in zip(result.building_depth, result.affected)]
            layers += viewer_3d.building_layers(model.buildings_wgs, b, model.zmin, colors,
                                                building_tooltips(model, extra), lod=1)
        show_scene(layers, model, key="scene_rain", height=640)
        st.html(legend)
        st.html(legend_swatches([("Gebäude mit Rückstau-Risiko", ORANGE), ("übrige Gebäude", GREY)]))
