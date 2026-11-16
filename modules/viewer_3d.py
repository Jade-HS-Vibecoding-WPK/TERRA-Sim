"""3D-Darstellung im Browser mit pydeck (deck.gl).

Dieses Modul übersetzt die Daten der anderen Module in deck.gl-Ebenen:
Gelände, Straßen, Gebäude (LOD 1 / LOD 2), Wasserspiegel, Fassaden-Belastung
und Windpfeile. Die Simulation selbst passiert in ``simulator.py`` – hier
wird nur gezeichnet.

Höhen werden relativ zu ``zmin`` (tiefster Punkt der Szene) dargestellt,
damit das Modell auf der Kartenebene steht.

Beispiel::

    ebenen = [terrain_layer(raster, zmin), *building_layers(geb_wgs, geb_m, zmin, farben, tips)]
    st.pydeck_chart(make_deck(ebenen, bbox))
"""

from __future__ import annotations

import math

import numpy as np
import pydeck as pdk
import shapely
from pyproj import Transformer

from .mesh_builder import building_triangles

# Farbe je Flächennutzung (Reihenfolge = LC_*-Codes aus simulator.py)
LANDCOVER_COLORS = np.array([
    [226, 220, 205],   # Sonstige Fläche
    [170, 207, 143],   # Grünfläche
    [158, 158, 163],   # Straße / Weg
    [205, 200, 194],   # Gebäude
    [126, 176, 222],   # Wasser
], dtype=float)

COLOR_RAMPS = {
    "heat": [(255, 237, 160), (254, 178, 76), (240, 59, 32), (128, 0, 38)],
    "water": [(198, 219, 239), (107, 174, 214), (33, 113, 181), (8, 48, 107)],
    "wind": [(116, 196, 118), (255, 217, 79), (244, 109, 67), (165, 0, 38)],
    "height": [(237, 248, 251), (158, 188, 218), (136, 86, 167), (77, 0, 75)],
}

_LIGHT = np.array([-0.35, -0.55, 0.76])
_LIGHT = _LIGHT / np.linalg.norm(_LIGHT)


def color_ramp(values, name: str = "heat") -> np.ndarray:
    """Werte 0..1 -> RGB-Farben (n, 3) entlang einer Farbskala."""
    stops = np.array(COLOR_RAMPS[name], dtype=float)
    values = np.clip(np.asarray(values, dtype=float), 0, 1)
    position = values * (len(stops) - 1)
    low = np.minimum(position.astype(int), len(stops) - 2)
    t = (position - low)[..., None]
    return stops[low] * (1 - t) + stops[low + 1] * t


def _edges(n: int, step: int) -> np.ndarray:
    idx = np.arange(0, n, step)
    return np.append(idx, n)


# --------------------------------------------------------------------------
# Gelände
# --------------------------------------------------------------------------

def terrain_layer(raster, zmin: float, overlay: np.ndarray | None = None,
                  ramp: str = "heat", max_cells: int = 70) -> pdk.Layer:
    """Gelände als Kachel-Fläche, eingefärbt nach Flächennutzung.

    ``overlay`` ist optional ein Raster mit Werten 0..1 (z. B. Risiko-Index),
    das als Heatmap über das Gelände gelegt wird (0 = keine Einfärbung).
    """
    step = max(1, math.ceil(max(raster.nx, raster.ny) / max_cells))
    rows, cols = _edges(raster.ny, step), _edges(raster.nx, step)
    grid = np.ix_(rows, cols)
    lon = np.round(raster.corner_lon[grid], 6).tolist()
    lat = np.round(raster.corner_lat[grid], 6).tolist()
    z = np.round(raster.corner_z[grid] - zmin, 2).tolist()

    # Grundfarbe: Flächennutzung in der Kachelmitte, leicht nach Höhe schattiert
    mid_r = (rows[:-1] + rows[1:]) // 2
    mid_c = (cols[:-1] + cols[1:]) // 2
    color = LANDCOVER_COLORS[raster.landcover[np.ix_(mid_r, mid_c)]]
    elevation = raster.elevation[np.ix_(mid_r, mid_c)]
    span = max(1e-6, float(elevation.max() - elevation.min()))
    color = color * (0.9 + 0.14 * (elevation - elevation.min()) / span)[..., None]

    if overlay is not None:
        # je Kachel der höchste Wert der darin liegenden Rasterzellen
        value = np.maximum.reduceat(np.maximum.reduceat(overlay, rows[:-1], axis=0), cols[:-1], axis=1)
        alpha = np.where(value > 0.02, 0.45 + 0.55 * value, 0.0)[..., None]
        color = color * (1 - alpha) + color_ramp(value, ramp) * alpha

    color = np.clip(color, 0, 255).astype(int).tolist()
    data = []
    for r in range(len(rows) - 1):
        for c in range(len(cols) - 1):
            data.append({
                "polygon": [[lon[r][c], lat[r][c], z[r][c]],
                            [lon[r][c + 1], lat[r][c + 1], z[r][c + 1]],
                            [lon[r + 1][c + 1], lat[r + 1][c + 1], z[r + 1][c + 1]],
                            [lon[r + 1][c], lat[r + 1][c], z[r + 1][c]]],
                "color": color[r][c],
            })
    return pdk.Layer("SolidPolygonLayer", data, id="gelaende", get_polygon="polygon",
                     get_fill_color="color", extruded=False, pickable=False, material=False)


def street_layer(streets_wgs, sample_elevation, zmin: float, lift_m: float = 0.35) -> pdk.Layer:
    """Straßen als Bänder, die dem Gelände folgen."""
    data = []
    if len(streets_wgs):
        lines = shapely.segmentize(np.asarray(streets_wgs.geometry.values), 0.00012)  # ~10 m
        for line, width in zip(lines, streets_wgs["width_m"].to_numpy()):
            xy = shapely.get_coordinates(line)
            z = sample_elevation(xy[:, 0], xy[:, 1]) - zmin + lift_m
            path = np.column_stack([np.round(xy, 6), np.round(z, 2)]).tolist()
            data.append({"path": path, "width": float(width)})
    return pdk.Layer("PathLayer", data, id="strassen", get_path="path", get_width="width",
                     get_color=[122, 122, 130], width_min_pixels=1, cap_rounded=True,
                     joint_rounded=True, pickable=False)


# --------------------------------------------------------------------------
# Gebäude
# --------------------------------------------------------------------------

def building_layers(buildings_wgs, buildings_m, zmin: float, colors, tooltips,
                    lod: int = 1) -> list:
    """Gebäude als extrudierte Körper; bei LOD 2 zusätzlich die Dachformen.

    ``buildings_wgs`` / ``buildings_m``  dieselben Gebäude in WGS84 bzw. metrisch
    ``colors``    RGB je Gebäude, Form (n, 3)
    ``tooltips``  HTML-Text je Gebäude (erscheint beim Überfahren mit der Maus)
    """
    colors = np.asarray(colors, dtype=float).reshape(-1, 3)
    ground = buildings_m["ground_m"].to_numpy(float)
    height = buildings_m["height_m"].to_numpy(float)
    eave = buildings_m["eave_height_m"].to_numpy(float)
    roof_h = buildings_m["roof_height_m"].to_numpy(float)
    shape = buildings_m["roof_shape"].to_numpy()
    has_roof = (lod >= 2) & (shape != "flat") & (roof_h > 0)

    bodies = []
    for i, geom in enumerate(buildings_wgs.geometry.values):
        base = round(float(ground[i] - zmin), 2)
        rings = [[[round(x, 6), round(y, 6), base] for x, y, *_ in ring.coords]
                 for ring in (geom.exterior, *geom.interiors)]
        bodies.append({
            "polygon": rings,
            "height": float(eave[i] if has_roof[i] else height[i]),
            "color": colors[i].astype(int).tolist(),
            "tooltip": tooltips[i],
        })
    layers = [pdk.Layer("PolygonLayer", bodies, id="gebaeude", get_polygon="polygon",
                        get_elevation="height", get_fill_color="color", extruded=True,
                        stroked=False, wireframe=True, get_line_color=[70, 70, 70],
                        pickable=True, auto_highlight=True)]

    if has_roof.any():
        tris, owner = [], []
        for i in np.flatnonzero(has_roof):
            # Nur der Teil oberhalb der Traufe: Dachflächen + Giebeldreiecke
            mesh = building_triangles(buildings_m.geometry.values[i], ground[i] + eave[i],
                                      0.0, shape[i], roof_h[i])
            part = np.concatenate([mesh.roof, mesh.walls])
            tris.append(part)
            owner.append(np.full(len(part), i))
        tris, owner = np.concatenate(tris), np.concatenate(owner)

        # Schattierung selbst berechnen (deck.gl beleuchtet freie Dreiecke nicht)
        normal = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
        normal /= np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-12)
        shade = 0.62 + 0.38 * np.clip(normal @ _LIGHT, 0, 1)
        tri_color = np.clip(colors[owner] * 0.93 * shade[:, None], 0, 255).astype(int).tolist()

        to_wgs = Transformer.from_crs(buildings_m.crs, "EPSG:4326", always_xy=True)
        lon, lat = to_wgs.transform(tris[..., 0], tris[..., 1])
        points = np.stack([np.round(lon, 6), np.round(lat, 6), np.round(tris[..., 2] - zmin, 2)],
                          axis=-1).tolist()
        roofs = [{"polygon": p, "color": c, "tooltip": tooltips[o]}
                 for p, c, o in zip(points, tri_color, owner)]
        layers.append(pdk.Layer("SolidPolygonLayer", roofs, id="daecher", get_polygon="polygon",
                                get_fill_color="color", extruded=False, _full3d=True,
                                material=False, pickable=True))
    return layers


# --------------------------------------------------------------------------
# Simulations-Ebenen
# --------------------------------------------------------------------------

def water_layer(bbox, level_rel: float, margin: float = 0.0) -> pdk.Layer:
    """Halbtransparente Wasserfläche in Höhe ``level_rel`` (relativ zu zmin)."""
    west, south, east, north = bbox
    dx, dy = (east - west) * margin, (north - south) * margin
    z = round(float(level_rel), 2)
    ring = [[west - dx, south - dy, z], [east + dx, south - dy, z],
            [east + dx, north + dy, z], [west - dx, north + dy, z]]
    return pdk.Layer("SolidPolygonLayer", [{"polygon": ring}], id="wasser", get_polygon="polygon",
                     get_fill_color=[38, 120, 220, 150], extruded=False, pickable=False,
                     material=False)


def facade_layer(facades, ground, zmin: float, crs: str, min_exposure: float = 0.05,
                 thickness_m: float = 0.6) -> pdk.Layer:
    """Wind-belastete Fassaden als farbige Scheiben vor der Wand."""
    shown = facades[facades["exposure"] >= min_exposure]
    data = []
    if len(shown):
        a = shown[["ax", "ay"]].to_numpy()
        b = shown[["bx", "by"]].to_numpy()
        out = shown[["nx", "ny"]].to_numpy() * thickness_m
        quad = np.stack([a, b, b + out, a + out], axis=1)  # (n, 4, 2)
        to_wgs = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
        lon, lat = to_wgs.transform(quad[..., 0], quad[..., 1])
        base = np.round(ground[shown["building"].to_numpy()] - zmin, 2)
        colors = color_ramp(shown["exposure"].to_numpy(), "wind").astype(int).tolist()
        for i, row in enumerate(shown.itertuples()):
            ring = [[round(float(lon[i, k]), 6), round(float(lat[i, k]), 6), float(base[i])]
                    for k in range(4)]
            data.append({
                "polygon": ring,
                "height": float(row.height_m) + 0.2,
                "color": colors[i],
                "tooltip": (f"<b>Fassade</b> {row.length_m:.0f} m × {row.height_m:.0f} m<br>"
                            f"Exposition: {row.exposure:.0%} (Windschatten {row.shelter:.0%})<br>"
                            f"Winddruck: {row.pressure_kn_m2:.2f} kN/m²"),
            })
    return pdk.Layer("PolygonLayer", data, id="fassaden", get_polygon="polygon",
                     get_elevation="height", get_fill_color="color", extruded=True,
                     stroked=False, pickable=True, auto_highlight=True)


def venturi_layer(venturi, ground, zmin: float, crs: str) -> pdk.Layer:
    """Engstellen mit Düseneffekt als leuchtende Balken quer durch die Lücke."""
    data = []
    if len(venturi):
        to_wgs = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
        for line, row in zip(venturi.geometry.values, venturi.itertuples()):
            xy = shapely.get_coordinates(line)
            lon, lat = to_wgs.transform(xy[:, 0], xy[:, 1])
            z = round(float(ground[row.building] - zmin + 2.0), 2)
            data.append({
                "path": [[round(float(x), 6), round(float(y), 6), z] for x, y in zip(lon, lat)],
                "tooltip": (f"<b>Düseneffekt</b><br>Lücke: {row.width_m:.1f} m breit, "
                            f"H/B = {row.hw_ratio:.1f}<br>Beschleunigung: ×{row.factor:.2f} "
                            f"→ ca. {row.speed_ms * 3.6:.0f} km/h"),
            })
    return pdk.Layer("PathLayer", data, id="duesen", get_path="path", get_width=3.0,
                     get_color=[214, 39, 180], width_min_pixels=4, cap_rounded=True,
                     pickable=True, auto_highlight=True)


def wind_arrow_layer(bbox, direction_deg: float, z_rel: float) -> pdk.Layer:
    """Großer Pfeil über der Szene, der die Strömungsrichtung zeigt."""
    west, south, east, north = bbox
    lat0, lon0 = (south + north) / 2, (west + east) / 2
    m_lat = 111_320.0
    m_lon = m_lat * math.cos(math.radians(lat0))
    half = max((east - west) * m_lon, (north - south) * m_lat) / 2

    theta = math.radians(direction_deg)
    upwind = np.array([math.sin(theta), math.cos(theta)])
    side = np.array([upwind[1], -upwind[0]])
    tail = upwind * half * 1.15
    tip = upwind * half * 0.6
    head = half * 0.14

    def point(p):
        return [lon0 + p[0] / m_lon, lat0 + p[1] / m_lat, round(float(z_rel), 1)]

    paths = [
        {"path": [point(tail), point(tip)]},
        {"path": [point(tip + upwind * head + side * head * 0.6), point(tip),
                  point(tip + upwind * head - side * head * 0.6)]},
    ]
    return pdk.Layer("PathLayer", paths, id="windpfeil", get_path="path",
                     get_width=max(2.0, half * 0.03), get_color=[30, 100, 200],
                     width_min_pixels=3, cap_rounded=True, joint_rounded=True, pickable=False)


# --------------------------------------------------------------------------
# Szene
# --------------------------------------------------------------------------

def make_deck(layers: list, bbox, pitch: float = 52, bearing: float = -18) -> pdk.Deck:
    """Fasst die Ebenen zu einer 3D-Szene mit passender Kamera zusammen."""
    west, south, east, north = bbox
    lat, lon = (south + north) / 2, (west + east) / 2
    side = max((east - west) * 111_320.0 * math.cos(math.radians(lat)),
               (north - south) * 111_320.0)
    zoom = math.log2(620 * 40_075_016.0 * math.cos(math.radians(lat)) / (side * 512))
    view = pdk.ViewState(latitude=lat, longitude=lon, zoom=round(zoom, 2),
                         pitch=pitch, bearing=bearing)
    return pdk.Deck(
        layers=layers,
        initial_view_state=view,
        map_style=None,
        tooltip={"html": "{tooltip}",
                 "style": {"backgroundColor": "#1f2933", "color": "white",
                           "fontSize": "12px", "borderRadius": "4px"}},
    )
