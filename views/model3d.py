"""3D-Modell (LOD 1 / LOD 2) und Export für CAD und 3D-Druck."""

from __future__ import annotations

import numpy as np
import streamlit as st
from shapely import affinity

from modules import mesh_builder, viewer_3d
from modules.map_selector import bbox_center
from views.common import (GREY, RADIO_OPTIONS, SOURCE_COLORS, legend_ramp, legend_swatches, num,
                          page_header, scene_for, show_scene)
from views.common import card, kpi_row


def building_colors(model, mode: str) -> np.ndarray:
    b = model.buildings
    if mode == "Gebäudehöhe":
        return viewer_3d.color_ramp(b["height_m"].to_numpy() / _top_height(model), "height")
    if mode == "Datenquelle der Höhe":
        return np.array([SOURCE_COLORS[s] for s in b["height_source"]], dtype=float).reshape(-1, 3)
    return np.tile(np.array(GREY, dtype=float), (len(b), 1))


def _top_height(model) -> float:
    return max(1.0, float(model.buildings["height_m"].quantile(0.98))) if len(model.buildings) else 1.0


def make_export(model, fmt: str, lod: int, with_terrain: bool):
    raster = model.raster
    origin = np.array([raster.x0 + raster.nx * raster.cell / 2,
                       raster.y0 + raster.ny * raster.cell / 2, model.zmin])
    meshes = [mesh_builder.recenter(m.all(), origin)
              for m in mesh_builder.buildings_meshes(model.buildings, lod)]
    terrain = None
    if with_terrain:
        step = max(1, int(np.ceil(max(raster.nx, raster.ny) / 100)))
        terrain = mesh_builder.recenter(mesh_builder.terrain_triangles(
            raster.corner_x, raster.corner_y, raster.corner_z, step), origin)

    parts = {"Gebaeude": np.concatenate(meshes) if meshes else mesh_builder.EMPTY}
    if terrain is not None:
        parts["Gelaende"] = terrain

    name = f"terra-sim_lod{lod}"
    if fmt == "OBJ":
        lat, lon = bbox_center(model.bbox)
        note = (f"Projekt: {model.name}\nMittelpunkt: {lat:.6f} N, {lon:.6f} E ({model.crs})\n"
                f"Nullpunkt Z = {model.zmin:.2f} m (tiefster Geländepunkt)")
        return mesh_builder.export_obj(parts, note).encode("utf-8"), f"{name}.obj", "text/plain"
    if fmt == "STL":
        return mesh_builder.export_stl(parts), f"{name}.stl", "model/stl"
    footprints = [affinity.translate(g, -origin[0], -origin[1]) for g in model.buildings.geometry]
    streets = [affinity.translate(g, -origin[0], -origin[1]) for g in model.streets.geometry]
    text = mesh_builder.export_dxf(meshes, terrain, footprints, streets)
    return text.encode("utf-8"), f"{name}.dxf", "application/dxf"


def render():
    from views.navigation import require_project

    model = require_project()
    page_header("3D-Modell & Export", "Gebäude aus OpenStreetMap auf dem Gelände – als Klötzchenmodell "
                                      "oder mit Dachformen, exportierbar für CAD und 3D-Druck.")
    b = model.buildings
    with_roof = int(((b["roof_shape"] != "flat") & (b["roof_height_m"] > 0)).sum()) if len(b) else 0

    left, right = st.columns([1, 2.6], gap="large")
    with left:
        with card():
            st.markdown("**Darstellung**")
            st.radio("Detailgrad", RADIO_OPTIONS["model_lod"], key="model_lod")
            st.radio("Einfärbung", RADIO_OPTIONS["model_color"], key="model_color")
        lod = 2 if st.session_state.model_lod.startswith("LOD 2") else 1
        color_mode = st.session_state.model_color

        with card():
            st.markdown("**Modell**")
            c1, c2 = st.columns(2)
            c1.metric("Gebäude", num(len(b)))
            c2.metric("Mit Dachform", num(with_roof))
            c1.metric("Mittlere Höhe", f"{num(b['height_m'].mean(), 1)} m" if len(b) else "–")
            c2.metric("Höchstes", f"{num(b['height_m'].max())} m" if len(b) else "–")
            if lod == 2 and with_roof == 0:
                st.caption("In OpenStreetMap ist hier keine Dachform hinterlegt – LOD 2 sieht aus wie LOD 1.")

        with card():
            st.markdown("**Export für CAD & 3D-Druck**")
            fmt = st.selectbox("Format", ["OBJ", "STL", "DXF"],
                               help="OBJ: Blender, Rhino, SketchUp · STL: 3D-Druck · "
                                    "DXF: AutoCAD, Vectorworks, ArchiCAD (mit Grundrissen und Straßen)")
            with_terrain = st.checkbox("Gelände mit exportieren", value=True)
            signature = (model.key, fmt, lod, with_terrain)
            if st.button("Export erzeugen", icon=":material/deployed_code:", width="stretch"):
                with st.spinner("Export wird erzeugt …"):
                    st.session_state.export = (signature, *make_export(model, fmt, lod, with_terrain))
            export = st.session_state.get("export")
            if export and export[0] == signature:
                _, data, filename, mime = export
                st.download_button(f"{filename} ({num(len(data) / 1e6, 1)} MB)", data, file_name=filename,
                                   mime=mime, icon=":material/download:", type="primary", width="stretch")
            st.caption(f"Einheit Meter, Z = oben. Nullpunkt: Gebietsmitte auf {num(model.zmin, 1)} m "
                       "(tiefster Geländepunkt).")

    with right:
        colors = building_colors(model, color_mode) if color_mode != "Einheitlich" else None
        show_scene(scene_for(model, lod=lod, colors=colors), key="scene_model", height=640)
        if color_mode == "Gebäudehöhe":
            st.html(legend_ramp("height", "0 m", f"{num(_top_height(model))} m", "Gebäudehöhe"))
        elif color_mode == "Datenquelle der Höhe":
            st.html(legend_swatches([("gemessene Höhe (OSM)", SOURCE_COLORS["OSM-Höhe"]),
                                     ("aus Geschosszahl", SOURCE_COLORS["OSM-Geschosse"]),
                                     ("geschätzt", SOURCE_COLORS["Schätzung"])]))
