"""Modul A: Hochwasser ("Badewannen-Modell")."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from modules import viewer_3d
from modules.simulator import flood_curve
from views.common import (GREY, RED, base_layers, building_tooltips, current_flood, flood_references,
                          legend_swatches, no_buildings, num, page_header, show_scene)

WATER = (38, 120, 220)


def render():
    from views.navigation import require_project

    model = require_project()
    page_header("Hochwasser", "„Badewannen-Modell“: Alles, was unter dem Wasserspiegel liegt, gilt als überflutet.")
    refs = flood_references(model)
    if st.session_state.flood_ref not in refs:
        st.session_state.flood_ref = next(iter(refs))
    b = model.buildings

    left, right = st.columns([1, 2.6], gap="large")
    with left:
        with st.container(border=True):
            st.markdown("**Szenario**")
            st.slider("Wasserpegel über Bezugsniveau", 0.0, 10.0, step=0.1, format="+%.1f m", key="flood_gauge")
            st.selectbox("Bezugsniveau", list(refs), key="flood_ref")
        result, base = current_flood(model)
        level = base + st.session_state.flood_gauge
        k = result.kpis
        st.caption(f"Wasserspiegel: {num(level, 1)} m ü. NHN (Bezugsniveau {num(base, 1)} m).")
        if model.dem.source == "flach":
            st.warning("Ohne Geländehöhen ist das Ergebnis nicht aussagekräftig.")

    with right:
        c = st.columns(4)
        c[0].metric(f"Gebäude (von {k['buildings_total']})", num(k["buildings_affected"]),
                    help="Gebäude, die im Wasser stehen")
        c[1].metric("BGF im EG", f"{num(k['flooded_gfa_m2'])} m²",
                    help="Bruttogrundfläche im Erdgeschoss der betroffenen Gebäude")
        c[2].metric("Überflutete Fläche", f"{k['flooded_share']:.0%}",
                    help=f"{num(k['flooded_area_m2'])} m², davon {num(k['flooded_street_m2'])} m² Straßen")
        c[3].metric("Max. Wassertiefe", f"{num(k['max_depth_m'], 1)} m")
        layers = base_layers(model)
        if len(b):
            colors = np.where(result.affected[:, None], np.array(RED, float), np.array(GREY, float))
            extra = [f"<b style='color:#ff8a80'>Wassertiefe am Gebäude: {d:.1f} m</b>" if hit else ""
                     for d, hit in zip(result.building_depth, result.affected)]
            layers += viewer_3d.building_layers(model.buildings_wgs, b, model.zmin, colors,
                                                building_tooltips(model, extra), lod=1)
        if level > model.zmin:
            layers.append(viewer_3d.water_layer(model.bbox, level - model.zmin))
        show_scene(layers, model, key="scene_flood", height=640)
        st.html(legend_swatches([("Gebäude steht im Wasser", RED), ("Gebäude trocken", GREY),
                                 ("Wasserspiegel", WATER)]))

    if no_buildings(model):
        return
    st.subheader("Betroffenheit nach Pegel")
    curve = flood_curve(b, base)
    fig = go.Figure()
    fig.add_scatter(x=curve["Pegel (m)"], y=curve["Überflutete BGF EG (m²)"], mode="lines",
                    fill="tozeroy", line=dict(color="#2678dc"), name="Überflutete BGF (EG)")
    fig.add_vline(x=st.session_state.flood_gauge, line_dash="dash", line_color="#d63031",
                  annotation_text=f"aktuell +{st.session_state.flood_gauge:.1f} m")
    fig.update_layout(height=280, margin=dict(l=10, r=10, t=30, b=10), showlegend=False,
                      xaxis_title="Wasserpegel über Bezugsniveau (m)", yaxis_title="Überflutete BGF im EG (m²)")
    st.plotly_chart(fig, key="flood_curve")

    with st.expander(f"Liste der betroffenen Gebäude ({k['buildings_affected']})"):
        table = pd.DataFrame({
            "Name / Typ": [n or t for n, t in zip(b["name"], b["building"])],
            "Grundfläche (m²)": b["area_m2"].round(0),
            "Geländehöhe (m)": b["ground_m"].round(2),
            "Wassertiefe (m)": result.building_depth.round(2),
        })[result.affected].sort_values("Wassertiefe (m)", ascending=False)
        st.dataframe(table, hide_index=True)
