"""Modul C: Starkwind & Düseneffekte."""

from __future__ import annotations

import numpy as np
import streamlit as st

import shapely

from modules import viewer_3d
from modules.simulator import (BEAUFORT_NAMES, DANGEROUS_WIND_MS, WIND_PROFILE_EXPONENT,
                               beaufort_to_ms)
from modules.viewer_webgpu import scene as vscene
from views.common import (GREY, RADIO_OPTIONS, current_wind, current_wind_field, legend_ramp,
                          legend_swatches, no_buildings, num, page_header, scene_for, scene_origin,
                          show_scene, wind_direction_label, wind_presets)

VENTURI_COLOR = (214, 39, 180)


def _inside(raster, x, y) -> np.ndarray:
    """Liegt der Punkt im Raster (= auf dem Geländesockel der 3D-Ansicht)?"""
    return ((x >= raster.x0) & (x <= raster.x0 + raster.nx * raster.cell)
            & (y >= raster.y0) & (y <= raster.y0 + raster.ny * raster.cell))


def _facade_layer(facades, ground, origin, raster, min_exposure: float = 0.05):
    mid_x = (facades["ax"] + facades["bx"]) / 2
    mid_y = (facades["ay"] + facades["by"]) / 2
    shown = facades[(facades["exposure"] >= min_exposure) & _inside(raster, mid_x, mid_y)]
    tips = [f"<b>Fassade</b> {r.length_m:.0f} m × {r.height_m:.0f} m<br>"
            f"Exposition: {r.exposure:.0%} (Windschatten {r.shelter:.0%})<br>"
            f"Winddruck: {r.pressure_kn_m2:.2f} kN/m²" for r in shown.itertuples()]
    colors = viewer_3d.color_ramp(shown["exposure"].to_numpy(), "wind")
    return vscene.facades(shown, ground, origin, colors, tips)


def _venturi_layer(venturi, ground, origin, raster):
    ox, oy, oz = origin
    lines, tips = [], []
    for line, row in zip(venturi.geometry.values, venturi.itertuples()):
        mid = line.interpolate(0.5, normalized=True)
        if not _inside(raster, mid.x, mid.y):
            continue
        xy = shapely.get_coordinates(line) - (ox, oy)
        z = np.full(len(xy), ground[row.building] - oz + 2.0)
        lines.append(np.column_stack([xy, z]))
        tips.append(f"<b>Düseneffekt</b><br>Lücke: {row.width_m:.1f} m breit, H/B = {row.hw_ratio:.1f}<br>"
                    f"Beschleunigung: ×{row.factor:.2f} → ca. {row.speed_ms * 3.6:.0f} km/h")
    return vscene.paths(lines, VENTURI_COLOR, tips, radius_m=1.2)


def _apply_preset(direction: int, beaufort: int):
    st.session_state.wind_dir = int(round(direction / 5) * 5) % 360
    st.session_state.wind_bft = beaufort


def render():
    from views.navigation import require_project

    model = require_project()
    page_header("Starkwind", "Welche Fassaden stehen frei im Wind, wo wird er in engen Gassen "
                             "beschleunigt, und wie strömt die Luft am Boden durch die Stadt?")
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
            st.toggle("Windpfeil anzeigen", key="wind_arrow",
                      help="Der blaue Pfeil über der Szene zeigt, wohin der Wind weht.")
            result, direction, beaufort = current_wind(model)
            k = result.kpis
            st.caption(f"Wind aus **{wind_direction_label(direction)}** · **{BEAUFORT_NAMES[beaufort]}**, "
                       f"ca. {num(k['speed_kmh'])} km/h in 10 m Höhe")
        field = current_wind_field(model)
        fk = field.kpis
        with st.container(border=True):
            st.markdown("**Am Boden (2 m Höhe)**")
            st.radio("Heatmap", RADIO_OPTIONS["wind_ground"], key="wind_ground", horizontal=True)
            st.toggle("Luftströmung animieren", key="wind_flow",
                      help="Windteilchen fließen durch die Straßen (unten) und über die Dächer (oben). "
                           "Farbe = Geschwindigkeit.")
            g1, g2 = st.columns(2)
            g1.metric("Gefährlich windig", f"{fk['dangerous_share']:.0%}",
                      help=f"Anteil der Freiflächen mit mindestens {num(DANGEROUS_WIND_MS * 3.6)} km/h im Mittel "
                           f"– Gehen wird gefährlich ({num(fk['dangerous_m2'])} m²)")
            g2.metric("Im Windschatten", f"{fk['sheltered_share']:.0%}",
                      help="Anteil der Freiflächen mit weniger als halb so viel Wind wie im Freien")
            st.caption(f"Im Freien wären es in 2 m Höhe {num(fk['free_ped_ms'] * 3.6)} km/h; zwischen den "
                       f"Gebäuden im Mittel {num(fk['mean_ped_ms'] * 3.6)} km/h, an Ecken und in Lücken bis "
                       f"{num(fk['max_ped_ms'] * 3.6)} km/h. Die Menschen in der 3D-Ansicht spüren genau "
                       "diesen Wind.")
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
        origin = scene_origin(model)
        facades = venturi = None
        if len(b):
            ground = b["ground_m"].to_numpy(float)
            if beaufort > 0:
                facades = _facade_layer(result.facades, ground, origin, model.raster)
                venturi = _venturi_layer(result.venturi, ground, origin, model.raster)
            top = float((ground + b["height_m"].to_numpy()).max() - model.zmin)
        else:
            top = float(model.raster.corner_z.max() - model.zmin)
        ground_mode = st.session_state.wind_ground
        if ground_mode == "Wind in Fußgängerhöhe":
            overlay, ramp = np.clip(field.speed / 20.0, 0, 1), "wind"
        elif ground_mode == "Windschatten":
            overlay, ramp = np.where(field.solid, 0, field.shelter), "water"
        else:
            overlay, ramp = None, "wind"
        flow = None
        if st.session_state.wind_flow and beaufort > 0:
            upper = beaufort_to_ms(beaufort) * (max(10.0, top + 10) / 10.0) ** WIND_PROFILE_EXPONENT
            flow = vscene.flow(field, model.raster, origin, top, upper, direction, fk["free_ped_ms"])
        scene = scene_for(model, colors=np.tile(np.array(GREY, float), (len(b), 1)), facades=facades,
                          paths=venturi,
                          arrow=vscene.wind_arrow(direction, top + 15) if st.session_state.wind_arrow else None,
                          overlay=overlay, ramp=ramp, flow=flow,
                          hazard=vscene.hazard("wind", bft=beaufort, from_deg=direction))
        show_scene(scene, key="scene_wind", height=640)
        if ground_mode == "Wind in Fußgängerhöhe":
            st.html(legend_ramp("wind", "windstill", "≥ 72 km/h", "Wind am Boden"))
        elif ground_mode == "Windschatten":
            st.html(legend_ramp("water", "kein Schatten", "tiefer Windschatten", "Windschatten"))
        st.html(legend_ramp("wind", "geschützt", "frei angeströmt", "Fassaden"))
        st.html(legend_swatches([("Gasse mit Düseneffekt", VENTURI_COLOR)]
                                + ([("Windrichtung", (30, 100, 200))] if st.session_state.wind_arrow else [])
                                + ([("Windteilchen: Farbe = Geschwindigkeit", (244, 109, 67))] if flow else [])))
    no_buildings(model)
