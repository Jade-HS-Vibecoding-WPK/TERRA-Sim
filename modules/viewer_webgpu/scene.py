"""Baut die Szene für den WebGPU-Viewer (three.js) aus den Daten der anderen Module.

Die Szene ist ein einfaches ``dict`` aus Zahlen, Listen und Base64-Text,
das als JSON an den Browser geht. Koordinaten sind **lokal und metrisch**:
x = Osten, y = Norden, z = Höhe – jeweils relativ zum ``origin``
(Mitte des Rasters, tiefster Punkt der Szene). Der Browser dreht das in
das three.js-System (y = oben) um.

Große Zahlenreihen (Gelände, Gebäude-Dreiecke) werden als Binärdaten in
Base64 verpackt, damit die Übertragung klein bleibt:

* ``f32`` – Float32, ``i16`` – Int16 (mal ``scale`` = Meter), ``u8`` – Byte

Beispiel::

    from modules.viewer_webgpu import scene

    origin = scene.origin_of(raster, zmin)
    s = {
        "terrain": scene.terrain(raster, origin),
        "texture": scene.map_texture(raster, gebaeude, strassen, gruen, wasser),
        "buildings": scene.buildings(gebaeude, origin, lod=2),
        "building_colors": scene.colors(farben),
    }
"""

from __future__ import annotations

import base64
import hashlib
import io

import numpy as np
import shapely
from PIL import Image, ImageDraw

from ..mesh_builder import building_triangles, buildings_meshes
from ..simulator import LC_WATER

POS_SCALE = 0.05  # Int16-Schritt in Metern: 5 cm Genauigkeit, ±1.600 m Reichweite

# Farben der Kartengrundlage auf dem Gelände (hell, ruhig – wie ein Arbeitsmodell)
MAP_COLORS = {
    "ground": (233, 229, 219),
    "green": (190, 214, 166),
    "water": (150, 192, 224),
    "street": (204, 202, 198),
    "path": (221, 216, 206),
    "footprint": (214, 208, 198),
}


# --------------------------------------------------------------------------
# Hilfen
# --------------------------------------------------------------------------

def b64(array: np.ndarray, dtype) -> str:
    """Zahlenreihe -> Base64-Text (Little Endian, wie im Browser)."""
    return base64.b64encode(np.ascontiguousarray(array, dtype=dtype).tobytes()).decode("ascii")


def _digest(*parts) -> str:
    h = hashlib.sha1()
    for p in parts:
        h.update(p if isinstance(p, bytes) else str(p).encode())
    return h.hexdigest()[:16]


def origin_of(raster, zmin: float) -> tuple[float, float, float]:
    """Nullpunkt der Szene: Mitte des Rasters auf Höhe des tiefsten Punkts."""
    return (raster.x0 + raster.nx * raster.cell / 2, raster.y0 + raster.ny * raster.cell / 2, float(zmin))


# --------------------------------------------------------------------------
# Gelände
# --------------------------------------------------------------------------

def terrain(raster, origin) -> dict:
    """Geländeoberfläche als Höhenraster an den Zell-Ecken."""
    ox, oy, oz = origin
    z = (raster.corner_z - oz).astype(np.float32)
    return {
        "id": _digest(z.tobytes(), raster.x0, raster.y0, raster.cell),
        "nx": int(raster.nx), "ny": int(raster.ny), "cell": float(raster.cell),
        "x0": float(raster.x0 - ox), "y0": float(raster.y0 - oy),
        "z": b64(z, "<f4"),
    }


def map_texture(raster, buildings, streets, green, water, max_px: int = 2048,
                supersample: int = 2) -> str:
    """Kartengrundlage (Grün, Wasser, Straßen, Grundrisse) als PNG-Bild.

    Alle GeoDataFrames im metrischen CRS des Rasters. Rückgabe als
    ``data:``-URL, die der Browser direkt als Textur lädt.
    """
    width_m, height_m = raster.nx * raster.cell, raster.ny * raster.cell
    px_per_m = min(2.0, max_px / max(width_m, height_m)) * supersample
    w, h = max(2, round(width_m * px_per_m)), max(2, round(height_m * px_per_m))
    image = Image.new("RGB", (w, h), MAP_COLORS["ground"])
    draw = ImageDraw.Draw(image)

    def ring_px(ring):
        xy = np.asarray(ring.coords)[:, :2]
        return [((x - raster.x0) * px_per_m, (raster.y0 + height_m - y) * px_per_m) for x, y in xy]

    def fill(geoms, color):
        for geom in geoms:
            if geom is None or geom.is_empty:
                continue
            for poly in getattr(geom, "geoms", [geom]):
                if poly.geom_type != "Polygon":
                    continue
                draw.polygon(ring_px(poly.exterior), fill=color)
                for hole in poly.interiors:
                    draw.polygon(ring_px(hole), fill=MAP_COLORS["ground"])

    fill(green.geometry.values, MAP_COLORS["green"])
    fill(water.geometry.values, MAP_COLORS["water"])
    if len(streets):
        widths = streets["width_m"].to_numpy(float)
        areas = shapely.buffer(np.asarray(streets.geometry.values), widths / 2, cap_style="round")
        is_path = widths < 3.5
        fill(areas[is_path], MAP_COLORS["path"])
        fill(areas[~is_path], MAP_COLORS["street"])
    fill(buildings.geometry.values, MAP_COLORS["footprint"])

    if supersample > 1:
        image = image.resize((max(2, w // supersample), max(2, h // supersample)), Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def overlay(values: np.ndarray, ramp_colors: np.ndarray, threshold: float = 0.02,
            raster=None) -> dict:
    """Heatmap über dem Gelände: ``values`` 0..1 je Rasterzelle, Zeile 0 = Süden.

    ``ramp_colors`` sind die fertigen RGB-Farben (ny, nx, 3), z. B. aus
    ``viewer_3d.color_ramp``. Zellen unter ``threshold`` bleiben durchsichtig.
    Auf Wasserflächen (``raster`` angegeben) wird nichts eingefärbt.
    """
    values = np.clip(np.asarray(values, dtype=float), 0, 1)
    alpha = np.where(values > threshold, 0.5 + 0.5 * values, 0.0)
    if raster is not None:
        alpha = np.where(raster.landcover == LC_WATER, 0.0, alpha)
    rgba = np.dstack([np.clip(ramp_colors, 0, 255), alpha * 255]).astype(np.uint8)
    ny, nx = values.shape
    return {"nx": int(nx), "ny": int(ny), "rgba": b64(rgba, np.uint8)}


# --------------------------------------------------------------------------
# Gebäude
# --------------------------------------------------------------------------

def buildings(buildings_m, origin, lod: int = 1, clip_raster=None) -> dict:
    """Dreiecke aller Gebäude (Wände + Dächer), nach Gebäude sortiert.

    ``start[i]`` ist das erste Dreieck von Gebäude ``i``; so findet der
    Browser beim Anklicken eines Dreiecks das zugehörige Gebäude.
    Mit ``clip_raster`` werden Gebäude am Gebietsrand abgeschnitten, damit
    nichts über den Geländesockel hinausragt.
    """
    if clip_raster is not None and len(buildings_m):
        r = clip_raster
        clipped = shapely.clip_by_rect(np.asarray(buildings_m.geometry.values), r.x0, r.y0,
                                       r.x0 + r.nx * r.cell, r.y0 + r.ny * r.cell)
        rows = []
        for i, geom in enumerate(clipped):                 # Teilstücke behalten ihre Gebäudenummer
            for part in getattr(geom, "geoms", [geom]):
                if part.geom_type == "Polygon" and part.area > 0.5:
                    rows.append((i, part))
        b = buildings_m
        ground, height = b["ground_m"].to_numpy(float), b["height_m"].to_numpy(float)
        eave, roof_h = b["eave_height_m"].to_numpy(float), b["roof_height_m"].to_numpy(float)
        shape = b["roof_shape"].to_numpy()
        parts = [np.zeros((0, 3, 3))] * len(b)
        for i, poly in rows:
            if lod >= 2 and shape[i] != "flat" and roof_h[i] > 0:
                m = building_triangles(poly, ground[i], eave[i], shape[i], roof_h[i])
            else:
                m = building_triangles(poly, ground[i], height[i])
            parts[i] = np.concatenate([parts[i], m.walls, m.roof])
    else:
        meshes = buildings_meshes(buildings_m, lod) if len(buildings_m) else []
        parts = [np.concatenate([m.walls, m.roof]) for m in meshes]
    counts = np.array([len(p) for p in parts], dtype=np.int64)
    tris = np.concatenate(parts) if parts else np.zeros((0, 3, 3))
    pos = np.round((tris - np.asarray(origin)) / POS_SCALE)
    if len(pos) and np.abs(pos).max() > 32767:
        raise ValueError("Gebiet zu groß für die 3D-Ansicht (max. ±1.600 m um die Mitte).")
    start = np.concatenate([[0], np.cumsum(counts)[:-1]]) if len(counts) else np.zeros(0)
    data = b64(pos.reshape(-1), "<i2")
    return {
        "id": _digest(data, lod),
        "scale": POS_SCALE,
        "pos": data,
        "start": b64(start, "<u4"),
        "n": int(len(parts)),
    }


def colors(rgb) -> str:
    """RGB-Farben je Objekt (n, 3), Werte 0..255."""
    return b64(np.clip(np.round(np.asarray(rgb, dtype=float).reshape(-1, 3)), 0, 255), np.uint8)


# --------------------------------------------------------------------------
# Simulations-Ebenen
# --------------------------------------------------------------------------

def facades(facade_table, ground: np.ndarray, origin, ramp_colors: np.ndarray, tips: list,
            offset_m: float = 0.35) -> dict | None:
    """Wind-belastete Fassaden als farbige Platten knapp vor der Wand.

    ``facade_table`` braucht die Spalten ``ax, ay, bx, by, nx, ny, building,
    height_m`` (siehe ``simulator.simulate_wind``).
    """
    if not len(facade_table):
        return None
    ox, oy, oz = origin
    out = facade_table[["nx", "ny"]].to_numpy() * offset_m
    a = facade_table[["ax", "ay"]].to_numpy() + out - (ox, oy)
    b = facade_table[["bx", "by"]].to_numpy() + out - (ox, oy)
    z0 = ground[facade_table["building"].to_numpy()] - oz + 0.05
    z1 = z0 + facade_table["height_m"].to_numpy(float) + 0.1
    p0 = np.column_stack([a, z0]); p1 = np.column_stack([b, z0])
    p2 = np.column_stack([b, z1]); p3 = np.column_stack([a, z1])
    tris = np.stack([np.stack([p0, p1, p2], 1), np.stack([p0, p2, p3], 1)], 1)  # (n, 2, 3, 3)
    return {"pos": b64(tris.reshape(-1), "<f4"), "colors": colors(ramp_colors), "tips": tips}


def paths(lines: list, color, tips: list | None = None, radius_m: float = 1.0) -> dict | None:
    """Linien als leuchtende Röhren, z. B. Engstellen mit Düseneffekt.

    ``lines`` = Liste von Arrays (k, 3) in Szenen-Koordinaten.
    """
    if not lines:
        return None
    return {"lines": [np.round(np.asarray(l, dtype=float), 2).tolist() for l in lines],
            "color": [int(c) for c in color], "radius": radius_m, "tips": tips or []}


def wind_arrow(direction_deg: float, z_rel: float) -> dict:
    """Großer Pfeil über der Szene; ``direction_deg`` = woher der Wind kommt."""
    return {"from_deg": float(direction_deg) % 360, "z": float(z_rel)}


def building_scale(scale) -> str:
    """Höhenfaktor je Gebäude (1 = unverändert, 0,3 = eingestürzt) für Schadensbilder."""
    return b64(np.clip(np.asarray(scale, dtype=float), 0.05, 1.0), "<f4")


def funnel(center_xy, origin, core_m: float, height_m: float, heading_deg: float,
           travel_m: float, speed_ms: float = 15.0, vrot_ms: float = 40.0) -> dict:
    """Tornado-Trichter, der durch ``center_xy`` (metrisch) in Richtung ``heading_deg`` zieht.

    Der Browser bewegt ihn in einer Schleife über ``travel_m`` Meter Bahn;
    ``vrot_ms`` ist die Drehgeschwindigkeit am Kernrand (für die Wirbelteilchen).
    """
    return {"x": float(center_xy[0] - origin[0]), "y": float(center_xy[1] - origin[1]),
            "core": float(core_m), "height": float(height_m), "heading": float(heading_deg),
            "travel": float(travel_m), "speed": float(speed_ms), "vrot": float(vrot_ms)}


def monster(center_xy, origin, height_m: float, heading_deg: float, travel_m: float,
            speed_ms: float | None = None, events: dict | None = None, helis: int = 0) -> dict:
    """Riesenmonster, das durch ``center_xy`` in Laufrichtung ``heading_deg`` läuft.

    ``events`` (aus ``hazards.simulate_kaiju``): Laserschüsse, Hubschrauber-Abstürze
    und Fehlschüsse – jeweils mit der Bahnstelle ``u``, an der sie passieren.
    """
    ox, oy = origin[0], origin[1]

    def local(p):
        return [round(float(p[0] - ox), 2), round(float(p[1] - oy), 2)]

    events = events or {"lasers": [], "crashes": [], "misses": []}
    return {"x": float(center_xy[0] - ox), "y": float(center_xy[1] - oy),
            "height": float(height_m), "heading": float(heading_deg), "travel": float(travel_m),
            "speed": float(speed_ms if speed_ms is not None else 0.15 * height_m), "helis": int(helis),
            "lasers": [{"u": e["u"], "target": local(e["target"])} for e in events["lasers"]],
            "crashes": [{"u": e["u"], "point": local(e["point"])} for e in events["crashes"]],
            "misses": [{"u": e["u"], "point": local(e["point"])} for e in events["misses"]]}


def ufos(count: int, size_m: float, height_m: float, extent_m: float, seed: int = 7,
         routes: list | None = None, origin=None) -> dict:
    """UFOs, die über dem Gebiet kreuzen und mit dem Traktorstrahl Menschen hochholen.

    Mit ``routes`` (aus ``hazards.simulate_alien``) fliegt jedes UFO feste
    Haltepunkte an und saugt dort die angegebenen Gebäude ein (Mutterschiff).
    """
    spec = {"count": int(count), "size": float(size_m), "height": float(height_m),
            "reach": 0.38 * float(extent_m), "speed": 1.0, "seed": int(seed)}
    if routes and any(routes) and origin is not None:
        spec["routes"] = [[{"x": round(float(s["point"][0] - origin[0]), 2),
                            "y": round(float(s["point"][1] - origin[1]), 2),
                            "lift": [int(i) for i in s["lift"]]} for s in route] for route in routes]
    return spec


def flow(field, raster, origin, roof_top_rel: float, upper_speed_ms: float, direction_deg: float,
         free_ped_ms: float, particles: int = 1600) -> dict:
    """Strömungsfeld für die animierten Windteilchen (aus ``simulator.wind_field``).

    Unten fließen die Teilchen in Fußgängerhöhe durch das Feld ``u``/``v``,
    eine zweite Schicht zieht ungestört über die Dächer (``upper_speed_ms``).
    """
    peak = float(max(np.abs(field.u).max(), np.abs(field.v).max(), 1e-6))
    scale = peak / 127.0
    theta = np.radians(direction_deg)
    return {
        "nx": int(raster.nx), "ny": int(raster.ny), "cell": float(raster.cell),
        "x0": float(raster.x0 - origin[0]), "y0": float(raster.y0 - origin[1]),
        "u": b64(np.round(field.u / scale), np.int8), "v": b64(np.round(field.v / scale), np.int8),
        "scale": scale, "solid": b64(field.solid, np.uint8),
        "top": float(roof_top_rel), "upper_speed": float(upper_speed_ms),
        "upper_dir": [float(-np.sin(theta)), float(-np.cos(theta))],
        "free_ped": float(free_ped_ms), "particles": int(particles),
    }


def walkways(streets_m, origin, raster) -> list:
    """Straßen und Wege als Linien für die animierten Menschen (auf das Gebiet zugeschnitten)."""
    if not len(streets_m):
        return []
    ox, oy = origin[0], origin[1]
    clipped = shapely.clip_by_rect(np.asarray(streets_m.geometry.values), raster.x0, raster.y0,
                                   raster.x0 + raster.nx * raster.cell, raster.y0 + raster.ny * raster.cell)
    lines = []
    for geom in clipped:
        for part in getattr(geom, "geoms", [geom]):
            if part.geom_type == "LineString" and part.length >= 5:
                xy = np.asarray(part.coords)[:, :2] - (ox, oy)
                lines.append(np.round(xy, 1).tolist())
    return lines


def hazard(kind: str, **values) -> dict:
    """Wie die Menschen reagieren: ``wind`` (bft, from_deg), ``quake`` (intensity),
    ``tornado`` und ``kaiju`` (Position kommt aus funnel / monster)."""
    return {"type": kind, **{k: float(v) for k, v in values.items()}}


def water(level_rel: float) -> dict:
    """Wasserspiegel (Hochwasser) in Höhe ``level_rel`` über dem Nullpunkt."""
    return {"level": float(level_rel)}
