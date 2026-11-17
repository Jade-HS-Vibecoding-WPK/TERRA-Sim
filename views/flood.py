"""Modul A: Hochwasser ("Badewannen-Modell")."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from modules.simulator import flood_curve
from modules.viewer_webgpu import scene as vscene
from views.common import (GREY, RED, building_tooltips, current_flood, flood_references,
                          legend_swatches, no_buildings, num, page_header, scene_for, show_scene)
from views.common import card, kpi_row, legend_ramp, odds_card, official_flood_impact

WATER = (38, 120, 220)
OFFICIAL_LEVEL = {"L": 0.35, "M": 0.65, "H": 1.0}   # Heatmap-Wert je amtlichem Szenario


def _official_card(model, impact):
    """Amtliche Hochwassergefahrenkarte: Szenarien, Wiederkehrzeit, betroffene Gebäude."""
    from modules.likelihood import LIFETIME_YEARS, describe, percent
    odds_card(model, "flood", "Chance, dass Gebäude im Gebiet bei einem Flusshochwasser nass werden – "
                              "nach den amtlichen Gefahrenkarten, unabhängig vom Pegel oben.")
    with card("mint"):
        st.markdown("**Amtliche Hochwassergefahrenkarte**")
        st.toggle("Überflutungsflächen im 3D-Modell zeigen", key="flood_official")
        if impact is None:
            st.caption("Der Kartendienst der Bundesanstalt für Gewässerkunde ist gerade nicht erreichbar.")
            return
        if not impact:
            st.caption("Das Gebiet liegt außerhalb aller amtlichen Überflutungsflächen von Flüssen "
                       "(Sturzfluten durch Starkregen sind darin nicht enthalten).")
            return
        lines = []
        for key in ("H", "M", "L"):
            if key in impact:
                v = impact[key]
                d = describe(v["T"])
                lines.append(f"- **{v['name']}** (etwa alle {v['T']} Jahre, {percent(d['p_life'])} in "
                             f"{LIFETIME_YEARS} J.): {num(v['share'] * 100)} % der Fläche, **{v['buildings']} Gebäude**")
        st.markdown("\n".join(lines))
        st.caption("Quelle: Hochwassergefahrenkarten der Länder nach EU-Hochwasserrisikomanagement-Richtlinie, "
                   "BfG-Geoportal. Die Flächen enthalten auch das Flussbett.")


def _official_overlay(model, impact):
    if not impact:
        return None
    from modules.simulator import _rasterize
    r = model.raster
    layers = [([impact[k]["geometry_model"]], [int(OFFICIAL_LEVEL[k] * 100)]) for k in ("L", "M", "H") if k in impact]
    return _rasterize(layers, r.x0, r.y0, r.cell, r.nx, r.ny) / 100.0


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
        with card():
            st.markdown("**Szenario**")
            st.slider("Wasserpegel über Bezugsniveau", 0.0, 10.0, step=0.1, format="+%.1f m", key="flood_gauge")
            st.selectbox("Bezugsniveau", list(refs), key="flood_ref")
        result, base = current_flood(model)
        level = base + st.session_state.flood_gauge
        k = result.kpis
        st.caption(f"Wasserspiegel: {num(level, 1)} m ü. NHN (Bezugsniveau {num(base, 1)} m).")
        if model.dem.source == "flach":
            st.warning("Ohne Geländehöhen ist das Ergebnis nicht aussagekräftig.")
        impact = official_flood_impact(model)
        _official_card(model, impact)

    with right:
        c = kpi_row(4)
        c[0].metric(f"Gebäude (von {k['buildings_total']})", num(k["buildings_affected"]),
                    help="Gebäude, die im Wasser stehen")
        c[1].metric("BGF im EG", f"{num(k['flooded_gfa_m2'])} m²",
                    help="Bruttogrundfläche im Erdgeschoss der betroffenen Gebäude")
        c[2].metric("Überflutete Fläche", f"{k['flooded_share']:.0%}",
                    help=f"{num(k['flooded_area_m2'])} m², davon {num(k['flooded_street_m2'])} m² Straßen")
        c[3].metric("Max. Wassertiefe", f"{num(k['max_depth_m'], 1)} m")
        colors = np.where(result.affected[:, None], np.array(RED, float), np.array(GREY, float))
        extra = [f"<b style='color:#ff8a80'>Wassertiefe am Gebäude: {d:.1f} m</b>" if hit else ""
                 for d, hit in zip(result.building_depth, result.affected)]
        water = vscene.water(level - model.zmin) if level > model.zmin else None
        overlay = _official_overlay(model, impact) if st.session_state.flood_official else None
        show_scene(scene_for(model, colors=colors, tips=building_tooltips(model, extra), water=water,
                             overlay=overlay, ramp="water"),
                   key="scene_flood", height=640)
        st.html(legend_swatches([("Gebäude steht im Wasser", RED), ("Gebäude trocken", GREY),
                                 ("Wasserspiegel", WATER)]))
        if overlay is not None:
            st.html(legend_ramp("water", "HQ extrem", "HQ häufig", "Amtliche Überflutungsflächen"))

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
