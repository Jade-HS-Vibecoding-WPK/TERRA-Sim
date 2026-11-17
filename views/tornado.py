"""Modul E: Tornado."""

from __future__ import annotations

import streamlit as st

from views.common import method_card

from modules.hazards import EF_GUST_MS, EF_PATH_WIDTH_M, TRANSLATION_MS, collapse_scale
from modules.viewer_webgpu import scene as vscene
from views.common import (damage_colors, damage_legend, damage_tooltips, legend_ramp, no_buildings, num,
                          page_header, scene_for, scene_origin, show_scene, wind_direction_label)
from views.common import current_tornado
from views.common import card, facts_html, kpi_row, odds_row

PRESETS = {
    "Häufig · EF1": 1,
    "Wie Bützow 2015 · EF3": 3,
    "Wie Pforzheim 1968 · EF4": 4,
    "Extremfall · EF5": 5,
}


def _apply(ef: int):
    st.session_state.tornado_ef = ef


def _germany_card():
    """Wie häufig sind Tornados dieser Stärke in ganz Deutschland?"""
    from modules.hazards import EF_PATH_WIDTH_M
    from modules.likelihood import TORNADO_PATH_KM, TORNADO_SOURCE, TORNADOES_PER_YEAR, describe
    ef = int(st.session_state.tornado_ef)
    per_year = sum(TORNADOES_PER_YEAR[ef:])
    count = f"{num(per_year)} pro Jahr" if per_year >= 1.5 else describe(1 / per_year)["text"].replace("etwa ", "")
    with card("mint"):
        st.markdown("**Tornados in ganz Deutschland**")
        st.html(facts_html([
            (f"EF{ef} oder stärker", count, "über Land, hochgerechnet aus den Meldungen"),
            ("Typische Schneise", f"{num(EF_PATH_WIDTH_M[ef])} m × {num(TORNADO_PATH_KM[ef])} km",
             "Breite × Länge (Annahme)"),
        ]))
        st.caption(f"Quelle: {TORNADO_SOURCE}. Ob ein Tornado genau dieses Gebiet trifft, ist deshalb sehr "
                   "unwahrscheinlich – auch wenn es in Deutschland jedes Jahr Tornados gibt.")


def render():
    from views.navigation import require_project

    model = require_project()
    page_header("Tornado", "Ein Wirbelsturm zieht über das Gebiet: Wo trifft er auf Gebäude, und wie "
                           "schwer werden sie beschädigt?")
    raster = model.raster

    odds_row(model, "tornado", "Chance, dass ein Tornado dieser Stärke oder stärker das Gebiet streift.",
             side=_germany_card)

    method_card("tornado")

    left, right = st.columns([1, 2.6], gap="large")
    with left:
        with card():
            st.markdown("**Szenario**")
            for label, ef in PRESETS.items():
                st.button(label, key=f"tornado_{label}", width="stretch", on_click=_apply, args=(ef,))
            st.caption("In Deutschland gibt es jedes Jahr etwa 20–60 Tornados, meist schwach (EF0–EF1). "
                       "Sie ziehen meist von Südwest nach Nordost.")
        with card():
            st.slider("Stärke (Enhanced-Fujita-Skala)", 0, 5, format="EF%d", key="tornado_ef")
            st.slider("Zugrichtung (wohin er zieht)", 0, 355, step=5, format="%d°", key="tornado_heading")
            st.slider("Seitlicher Versatz der Bahn", -400, 400, step=10, format="%d m", key="tornado_offset")
        result = current_tornado(model)
        k = result.kpis
        st.caption(f"EF{k['ef']}: Spitzenböen um {num(k['gust_ms'] * 3.6)} km/h, Schneise etwa "
                   f"{num(k['path_width_m'])} m breit. Zieht nach "
                   f"**{wind_direction_label(st.session_state.tornado_heading)}**; rechts der Bahn ist "
                   "der Wind stärker, weil sich die Zuggeschwindigkeit addiert.")

    with right:
        c = kpi_row(4)
        c[0].metric(f"Beschädigt (von {k['buildings_total']})", num(k["damaged"]))
        c[1].metric("Schwer beschädigt", num(k["heavy"]), help="Schadensgrad 3 oder mehr: Dachstuhl weg, Wände beschädigt")
        c[2].metric("Zerstört", num(k["destroyed"]))
        c[3].metric("Max. Wind am Gebäude", f"{num(k['max_speed_at_building_ms'] * 3.6)} km/h")
        origin = scene_origin(model)
        extent = max(raster.nx, raster.ny) * raster.cell
        funnel = vscene.funnel(result.extra["center"], origin, result.extra["core_m"],
                               min(900.0, max(300.0, 1.1 * extent)), st.session_state.tornado_heading,
                               travel_m=1.4 * extent, speed_ms=TRANSLATION_MS,
                               vrot_ms=EF_GUST_MS[k["ef"]] - TRANSLATION_MS)
        scene = scene_for(model, colors=damage_colors(result.damage), tips=damage_tooltips(model, result.damage),
                          overlay=result.overlay, ramp="heat", funnel=funnel, hazard=vscene.hazard("tornado"),
                          building_scale=vscene.building_scale(collapse_scale(result.damage)))
        show_scene(scene, key="scene_tornado", height=640)
        st.html(legend_ramp("heat", f"{num(28 * 3.6)} km/h", f"{num(EF_GUST_MS[5] * 3.6)} km/h", "Wind"))
        st.html(damage_legend())
    no_buildings(model)
    with st.expander("Enhanced-Fujita-Skala"):
        st.dataframe({"Stufe": [f"EF{i}" for i in range(6)],
                      "Spitzenböe (km/h)": [round(v * 3.6) for v in EF_GUST_MS],
                      "Typische Schneisenbreite (m)": EF_PATH_WIDTH_M},
                     hide_index=True)
