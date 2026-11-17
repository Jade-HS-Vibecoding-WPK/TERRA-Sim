"""Modul B: Starkregen & Oberflächenabfluss."""

from __future__ import annotations

import numpy as np
import streamlit as st

from modules.simulator import LC_BUILDING, LC_WATER
from views.common import (GREY, ORANGE, RADIO_OPTIONS, building_tooltips, climate_info,
                          current_rain, legend_ramp, legend_swatches, num, page_header, rain_scenarios,
                          scene_for, show_scene)
from views.common import RAIN_DURATION_NAME, card, facts_html, kpi_row, odds_row, official_kostra
import pandas as pd

DISPLAYS = RADIO_OPTIONS["rain_display"]


def _kostra_card(model):
    """Amtliche Regenhöhen am Standort: 100-jährliche Werte groß, die ganze Tabelle aufklappbar."""
    table = official_kostra(model)
    with card("mint"):
        st.markdown("**Amtliche Starkregen-Statistik am Standort**")
        st.html(facts_html([(f"{RAIN_DURATION_NAME.get(d, f'{d} min')} · alle 100 Jahre", f"{num(t[100])} l/m²", None)
                            for d, t in table.items() if t.get(100)]))
        with st.expander("Alle Regenhöhen (KOSTRA-DWD-2020)"):
            rows = {RAIN_DURATION_NAME.get(d, f"{d} min"): {f"alle {T} J.": v for T, v in t.items()}
                    for d, t in table.items()}
            st.dataframe(pd.DataFrame(rows).T, width="stretch")
            st.caption("Regenhöhe in l/m², die im Mittel einmal in so vielen Jahren erreicht wird "
                       "(5-km-Raster). Quelle: Deutscher Wetterdienst, KOSTRA-DWD-2020, CC BY 4.0.")


def render():
    from views.navigation import require_project

    model = require_project()
    page_header("Starkregen", "Der Regen fließt je nach Versiegelung ab, folgt dem Gefälle und staut sich in Senken.")
    scenarios = rain_scenarios(model)
    if st.session_state.rain_scenario not in scenarios:
        st.session_state.rain_scenario = "Jahrhundertregen (100 l/m²)"
    raster, b = model.raster, model.buildings

    odds_row(model, "rain", "Chance, dass mindestens diese Regenmenge in der gewählten Dauer fällt.",
             side=(lambda: _kostra_card(model)) if official_kostra(model) else None)

    left, right = st.columns([1, 2.6], gap="large")
    with left:
        with card():
            st.markdown("**Szenario**")
            st.selectbox("Regenmenge", list(scenarios), key="rain_scenario")
            fixed = "Stundenregen" in st.session_state.rain_scenario or "Tagesregen" in st.session_state.rain_scenario
            st.radio("Regendauer", RADIO_OPTIONS["rain_duration"], key="rain_duration", horizontal=True,
                     disabled=fixed,
                     help="Wie lange es dauert, bis die Regenmenge gefallen ist. Entscheidet, wie selten der Regen "
                          "ist (DWD KOSTRA) – die Wasserverteilung rechnet TERRA-Sim für das ganze Ereignis auf "
                          "einmal. Amtliche und gemessene Szenarien haben eine feste Dauer.")
            st.slider("Kanalisation nimmt auf", 0, 60, step=5, format="%d l/m²", key="rain_sewer",
                      help="So viel Regen leiten Kanäle und Fallrohre von Dächern, Straßen und Plätzen ab. "
                           "Übliche Auslegung: Regen, wie er alle 2–5 Jahre vorkommt – etwa 15–25 l/m² "
                           "in einer Stunde. 0 = ohne Kanalisation.")
            st.radio("Heatmap zeigt", DISPLAYS, key="rain_display")
            info = climate_info(model)
            if info and info.get("prcp_max_day"):
                st.caption(f"Am Standort gemessen ({info['years']}): stärkster Tagesregen "
                           f"{num(info['prcp_max_day'])} l/m², im Mittel {num(info['heavy_rain_days'], 1)} "
                           "Tage pro Jahr mit mindestens 20 l/m².")
        result, _ = current_rain(model)
        k = result.kpis
        st.caption(f"Versiegelungsgrad des Gebiets: {k['sealed_share']:.0%}. Die Kanalisation nimmt "
                   f"{num(k['sewer_m3'])} m³ auf, {k['runoff_coeff']:.0%} des Regens fließen oberflächlich "
                   "ab. Dachwasser kommt über die Fallrohre neben dem Gebäude an.")
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
        c = kpi_row(4)
        c[0].metric(f"Gebäude (von {k['buildings_total']})", num(k["buildings_affected"]),
                    help="Gebäude mit Rückstau-Risiko: Neben dem Gebäude stehen mindestens 10 cm Wasser "
                         "auf mindestens 25 m².")
        c[1].metric("Oberflächenabfluss", f"{num(k['runoff_m3'])} m³",
                    help=f"Von {num(k['rain_m3'])} m³ Niederschlag auf der Landfläche")
        c[2].metric("Wasser ≥ 10 cm", f"{num(k['ponding_area_m2'])} m²", help="Fläche, auf der das Wasser "
                    "mindestens 10 cm hoch steht")
        c[3].metric("Max. Wassertiefe", f"{num(k['max_ponding_m'], 2)} m")
        colors = np.where(result.affected[:, None], np.array(ORANGE, float), np.array(GREY, float))
        extra = [f"<b style='color:#ffcc80'>Wasser am Gebäude: bis {d * 100:.0f} cm</b>" if hit else ""
                 for d, hit in zip(result.building_depth, result.affected)]
        show_scene(scene_for(model, colors=colors, tips=building_tooltips(model, extra),
                             overlay=overlay, ramp=ramp), key="scene_rain", height=640)
        st.html(legend)
        st.html(legend_swatches([("Gebäude mit Rückstau-Risiko", ORANGE), ("übrige Gebäude", GREY)]))
