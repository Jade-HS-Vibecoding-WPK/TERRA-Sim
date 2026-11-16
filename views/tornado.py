"""Modul E: Tornado."""

from __future__ import annotations

import streamlit as st

from modules.hazards import EF_GUST_MS, EF_PATH_WIDTH_M, collapse_scale
from modules.viewer_webgpu import scene as vscene
from views.common import (damage_colors, damage_legend, damage_tooltips, legend_ramp, no_buildings, num,
                          page_header, scene_for, scene_origin, show_scene, wind_direction_label)
from views.common import current_tornado

PRESETS = {
    "Häufig · EF1": 1,
    "Wie Bützow 2015 · EF3": 3,
    "Wie Pforzheim 1968 · EF4": 4,
    "Extremfall · EF5": 5,
}


def _apply(ef: int):
    st.session_state.tornado_ef = ef


def render():
    from views.navigation import require_project

    model = require_project()
    page_header("Tornado", "Ein Wirbelsturm zieht über das Gebiet: Wo trifft er auf Gebäude, und wie "
                           "schwer werden sie beschädigt?")
    raster = model.raster

    left, right = st.columns([1, 2.6], gap="large")
    with left:
        with st.container(border=True):
            st.markdown("**Szenario**")
            for label, ef in PRESETS.items():
                st.button(label, key=f"tornado_{label}", width="stretch", on_click=_apply, args=(ef,))
            st.caption("In Deutschland gibt es jedes Jahr etwa 20–60 Tornados, meist schwach (EF0–EF1). "
                       "Sie ziehen meist von Südwest nach Nordost.")
        with st.container(border=True):
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
        c = st.columns(4)
        c[0].metric(f"Beschädigt (von {k['buildings_total']})", num(k["damaged"]))
        c[1].metric("Schwer beschädigt", num(k["heavy"]), help="Schadensgrad 3 oder mehr: Dachstuhl weg, Wände beschädigt")
        c[2].metric("Zerstört", num(k["destroyed"]))
        c[3].metric("Max. Wind am Gebäude", f"{num(k['max_speed_at_building_ms'] * 3.6)} km/h")
        origin = scene_origin(model)
        extent = max(raster.nx, raster.ny) * raster.cell
        funnel = vscene.funnel(result.extra["center"], origin, result.extra["core_m"],
                               min(900.0, max(300.0, 1.1 * extent)), st.session_state.tornado_heading,
                               travel_m=1.4 * extent)
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
