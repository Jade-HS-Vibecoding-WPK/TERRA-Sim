"""Modul C: Starkwind & Düseneffekte."""

from __future__ import annotations

import numpy as np
import streamlit as st

from modules import viewer_3d
from modules.simulator import BEAUFORT_NAMES
from views.common import (GREY, base_layers, building_tooltips, current_wind, legend_ramp,
                          legend_swatches, no_buildings, num, page_header, show_scene,
                          wind_direction_label, wind_presets)


def _apply_preset(direction: int, beaufort: int):
    st.session_state.wind_dir = int(round(direction / 5) * 5) % 360
    st.session_state.wind_bft = beaufort


def render():
    from views.navigation import require_project

    model = require_project()
    page_header("Starkwind", "Sichtlinien-Analyse: Welche Fassaden stehen frei im Wind, wo wird er "
                             "in engen Gassen beschleunigt?")
    b = model.buildings

    left, right = st.columns([1, 2.6], gap="large")
    with left:
        presets = wind_presets(model)
        if presets:
            with st.container(border=True):
                st.markdown("**Szenario aus Messdaten**")
                for label, (direction, beaufort) in presets.items():
                    st.button(f"{label} · Bft {beaufort}", key=f"preset_{label}", width="stretch",
                              on_click=_apply_preset, args=(direction, beaufort))
                st.caption("„Typisch“ = an 2 % der Stunden überschritten, „Gemessenes Maximum“ = stärkstes "
                           "Stundenmittel. Richtung: häufigste bei starkem Wind am Standort, "
                           f"{wind_direction_label(next(iter(presets.values()))[0])}.")
        with st.container(border=True):
            st.markdown("**Szenario**")
            st.slider("Windrichtung (woher der Wind kommt)", 0, 355, step=5, format="%d°", key="wind_dir")
            st.slider("Windstärke (Beaufort)", 0, 12, key="wind_bft")
            result, direction, beaufort = current_wind(model)
            k = result.kpis
            st.caption(f"Wind aus **{wind_direction_label(direction)}** · **{BEAUFORT_NAMES[beaufort]}**, "
                       f"ca. {num(k['speed_kmh'])} km/h in 10 m Höhe")
    with right:
        share = k["facade_area_high_m2"] / k["facade_area_total_m2"] if k["facade_area_total_m2"] else 0
        c = st.columns(4)
        c[0].metric("Fassade frei im Wind", f"{num(k['facade_area_high_m2'])} m²",
                    help=f"{share:.0%} der Fassadenfläche stehen nahezu ungeschützt und frontal im Wind "
                         "(Exposition ≥ 60 %). Wie stark sie belastet werden, zeigt der Winddruck.")
        c[1].metric("Max. Druck (kN/m²)", num(k["max_pressure_kn_m2"], 2),
                    help="Größter Winddruck auf eine Fassade")
        c[2].metric("Düsen-Engstellen", num(k["venturi_count"]))
        c[3].metric("Spitze in Gassen", f"{num(k['venturi_max_speed_ms'] * 3.6)} km/h" if k["venturi_count"] else "–",
                    help="Geschätzte Windgeschwindigkeit in der am stärksten beschleunigten Gasse")
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
        show_scene(layers, model, key="scene_wind", height=640)
        st.html(legend_ramp("wind", "geschützt", "frei angeströmt", "Fassaden"))
        st.html(legend_swatches([("Gasse mit Düseneffekt", (214, 39, 180)), ("Windrichtung", (30, 100, 200))]))
    no_buildings(model)
