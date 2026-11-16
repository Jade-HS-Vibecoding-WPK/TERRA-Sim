"""Baut das 3D-Modell (LOD 1 / LOD 2) und exportiert es als OBJ, STL oder DXF.

Alle Funktionen arbeiten in einem **metrischen** Koordinatensystem
(z. B. UTM, siehe ``osm_fetcher.metric_crs``): x/y in Metern, z = Höhe.

* **LOD 1** – Klötzchenmodell: Grundriss wird bis zur Gesamthöhe extrudiert.
* **LOD 2** – Wände bis zur Traufe, darüber eine einfache Dachform
  (Satteldach, Walmdach, Zeltdach), sofern OSM eine Dachform kennt.

Ein Dreiecksnetz ist hier schlicht ein ``numpy``-Array der Form ``(n, 3, 3)``:
n Dreiecke x 3 Eckpunkte x (x, y, z).

Beispiel::

    from modules.mesh_builder import building_triangles, export_obj

    teile = building_triangles(polygon, base_z=0, eave_height=6,
                               roof_shape="gabled", roof_height=3)
    obj_text = export_obj({"Gebaeude": teile.all()})
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import numpy as np
import shapely
from shapely import affinity
from shapely.geometry import LineString, Polygon
from shapely.geometry.polygon import orient
from shapely.ops import polygonize

EMPTY = np.zeros((0, 3, 3))
_GRID = 1e-6  # Rechengenauigkeit beim Zerschneiden der Grundrisse (Meter)


@dataclass
class BuildingMesh:
    """Dreiecke eines Gebäudes, getrennt nach Bauteil."""

    walls: np.ndarray   # (n, 3, 3)
    roof: np.ndarray    # (n, 3, 3)
    bottom: np.ndarray  # (n, 3, 3)

    def all(self) -> np.ndarray:
        return np.concatenate([self.walls, self.roof, self.bottom])


# --------------------------------------------------------------------------
# Dachformen
# --------------------------------------------------------------------------

def _roof_profile(poly: Polygon, shape: str, roof_height: float):
    """Beschreibt die Dachform als Höhenfunktion plus Knicklinien.

    Das Dach wird am kleinsten umschließenden Rechteck des Grundrisses
    ausgerichtet: ``s`` läuft entlang der langen Seite (First), ``d`` quer dazu.
    Rückgabe: ``(knicklinien, hoehenfunktion)`` oder ``([], None)`` für Flachdach.
    Entlang der Knicklinien wird der Grundriss später zerschnitten, damit jede
    Teilfläche eine ebene Dachfläche ist.
    """
    if shape not in ("gabled", "hipped", "pyramidal") or roof_height <= 0:
        return [], None

    rect = poly.minimum_rotated_rectangle
    if rect.geom_type != "Polygon":
        return [], None
    corners = np.asarray(rect.exterior.coords)[:4]
    edge_a = corners[1] - corners[0]
    edge_b = corners[2] - corners[1]
    len_a, len_b = np.linalg.norm(edge_a), np.linalg.norm(edge_b)
    if min(len_a, len_b) < 0.5:
        return [], None

    center = corners.mean(axis=0)
    if len_a >= len_b:
        axis_s, half_len, half_width = edge_a / len_a, len_a / 2, len_b / 2
    else:
        axis_s, half_len, half_width = edge_b / len_b, len_b / 2, len_a / 2
    axis_d = np.array([-axis_s[1], axis_s[0]])
    reach = 4 * (half_len + half_width)  # "unendlich" lange Schnittlinien

    def line(s0, d0, ds, dd):
        """Linie durch den Punkt (s0, d0) mit Richtung (ds, dd) im Dach-System."""
        point = center + s0 * axis_s + d0 * axis_d
        direction = ds * axis_s + dd * axis_d
        direction = direction / np.linalg.norm(direction)
        return LineString([point - reach * direction, point + reach * direction])

    def local(xy):
        rel = np.asarray(xy) - center
        return rel @ axis_s, rel @ axis_d

    ridge = line(0, 0, 1, 0)

    if shape == "gabled":
        def height(xy):
            _, d = local(xy)
            return roof_height * np.clip(1 - np.abs(d) / half_width, 0, 1)
        return [ridge], height

    if shape == "hipped" and half_len - half_width > 0.25:
        offset = half_len - half_width  # halbe Firstlänge

        def height(xy):
            s, d = local(xy)
            slope_side = 1 - np.abs(d) / half_width
            slope_end = (half_len - np.abs(s)) / half_width
            return roof_height * np.clip(np.minimum(slope_side, slope_end), 0, 1)
        hips = [line(offset, 0, 1, 1), line(offset, 0, 1, -1),
                line(-offset, 0, 1, 1), line(-offset, 0, 1, -1)]
        return [ridge] + hips, height

    # Zeltdach (auch: Walmdach auf fast quadratischem Grundriss)
    def height(xy):
        s, d = local(xy)
        return roof_height * np.clip(
            np.minimum(1 - np.abs(d) / half_width, 1 - np.abs(s) / half_len), 0, 1)
    cross = line(0, 0, 0, 1)
    diagonals = [line(0, 0, half_len, half_width), line(0, 0, half_len, -half_width)]
    return [ridge, cross] + diagonals, height


def _split(poly: Polygon, lines: list) -> list:
    """Zerschneidet ein Polygon entlang von Linien in Teilflächen."""
    # ``grid_size`` rastet alle Schnittpunkte auf ein 1-µm-Gitter ein. Ohne das
    # entstehen durch Rundungsfehler winzige Splitterflächen, wenn eine
    # Knicklinie (fast) genau durch einen Eckpunkt des Grundrisses läuft.
    merged = shapely.unary_union([poly.boundary, *lines], grid_size=_GRID)
    pieces = [p for p in polygonize(merged)
              if p.area > 1e-4 and poly.covers(p.representative_point())]
    return pieces or [poly]


# --------------------------------------------------------------------------
# Ein Gebäude
# --------------------------------------------------------------------------

def building_triangles(poly: Polygon, base_z: float, eave_height: float,
                       roof_shape: str = "flat", roof_height: float = 0.0) -> BuildingMesh:
    """Dreiecksnetz eines Gebäudes (geschlossener Körper).

    ``poly``         Grundriss in metrischen Koordinaten (Innenhöfe erlaubt)
    ``base_z``       Geländehöhe am Gebäude
    ``eave_height``  Wandhöhe (Traufe) über ``base_z``
    ``roof_shape``   "flat", "gabled", "hipped" oder "pyramidal"
    ``roof_height``  Höhe des Dachs über der Traufe
    """
    if poly.is_empty or poly.area <= 0:
        return BuildingMesh(EMPTY, EMPTY, EMPTY)

    # Lokal rechnen (Ursprung am Schwerpunkt), sonst leidet die Genauigkeit.
    origin = np.array(poly.centroid.coords[0])
    poly = orient(affinity.translate(poly, -origin[0], -origin[1]), 1.0)

    creases, height_fn = _roof_profile(poly, roof_shape, roof_height)
    pieces = _split(poly, creases) if creases else [poly]
    outline = poly.boundary

    walls, roof, bottom = [], [], []
    for piece in pieces:
        piece = orient(piece, 1.0)
        rings = [np.asarray(piece.exterior.coords)[:-1, :2]]
        rings += [np.asarray(r.coords)[:-1, :2] for r in piece.interiors]
        verts = np.vstack(rings)

        def lift(xy, z):
            return np.column_stack([xy + origin, np.broadcast_to(z, len(xy))])

        def roof_z(xy):
            return base_z + eave_height + (height_fn(xy) if height_fn else 0.0)

        top = lift(verts, roof_z(verts))
        base = lift(verts, base_z)

        # Dach- und Bodenfläche: Die "constrained Delaunay"-Triangulierung behält
        # alle Randpunkte – wichtig, damit Dach und Wände lückenlos zusammenpassen.
        triangles = shapely.get_parts(shapely.constrained_delaunay_triangles(piece))
        if len(triangles):
            corners = shapely.get_coordinates(triangles).reshape(-1, 4, 2)[:, :3].reshape(-1, 2)
            roof.append(_face_up(lift(corners, roof_z(corners)).reshape(-1, 3, 3)))
            bottom.append(_face_up(lift(corners, base_z).reshape(-1, 3, 3))[:, ::-1])  # Normale nach unten

        # Wände: nur Kanten, die auf dem echten Gebäudeumriss liegen.
        start = 0
        for ring in rings:
            idx_a = np.arange(start, start + len(ring))
            idx_b = np.roll(idx_a, -1)
            start += len(ring)
            if creases:
                mids = (verts[idx_a] + verts[idx_b]) / 2
                on_outline = shapely.distance(shapely.points(mids), outline) < 100 * _GRID
                idx_a, idx_b = idx_a[on_outline], idx_b[on_outline]
            if len(idx_a) == 0:
                continue
            a_base, b_base, a_top, b_top = base[idx_a], base[idx_b], top[idx_a], top[idx_b]
            walls.append(np.stack([a_base, b_base, b_top], axis=1))
            walls.append(np.stack([a_base, b_top, a_top], axis=1))

    def join(parts):
        return np.concatenate(parts) if parts else EMPTY

    return BuildingMesh(*(_drop_degenerate(join(part)) for part in (walls, roof, bottom)))


def _face_up(tris: np.ndarray) -> np.ndarray:
    """Dreht Dreiecke so, dass ihre Normale nach oben zeigt."""
    normal_z = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])[:, 2]
    tris = tris.copy()
    flip = normal_z < 0
    tris[flip] = tris[flip][:, ::-1]
    return tris


def _drop_degenerate(tris: np.ndarray) -> np.ndarray:
    """Entfernt Dreiecke ohne Fläche (z. B. Wandstücke mit Höhe 0)."""
    if len(tris) == 0:
        return tris
    area = np.linalg.norm(np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0]), axis=1)
    return tris[area > 1e-9]


# --------------------------------------------------------------------------
# Viele Gebäude + Gelände
# --------------------------------------------------------------------------

def buildings_meshes(buildings, lod: int = 1, ground_column: str = "ground_m") -> list:
    """Erzeugt für jede Zeile des (metrischen) Gebäude-GeoDataFrame ein ``BuildingMesh``.

    Erwartete Spalten: ``height_m``, ``eave_height_m``, ``roof_shape``,
    ``roof_height_m`` und optional ``ground_m`` (Geländehöhe, sonst 0).
    """
    ground = buildings[ground_column].to_numpy() if ground_column in buildings else np.zeros(len(buildings))
    meshes = []
    for geom, base, height, eave, shape, roof_h in zip(
            buildings.geometry.values, ground, buildings["height_m"].to_numpy(),
            buildings["eave_height_m"].to_numpy(), buildings["roof_shape"].to_numpy(),
            buildings["roof_height_m"].to_numpy()):
        if lod >= 2 and shape != "flat" and roof_h > 0:
            meshes.append(building_triangles(geom, base, eave, shape, roof_h))
        else:
            meshes.append(building_triangles(geom, base, height))
    return meshes


def terrain_triangles(x: np.ndarray, y: np.ndarray, z: np.ndarray, step: int = 1) -> np.ndarray:
    """Geländeoberfläche aus einem Punktraster.

    ``x`` (nx,), ``y`` (ny,) sind die Koordinaten der Rasterpunkte,
    ``z`` (ny, nx) ihre Höhen. ``step`` > 1 dünnt das Raster aus.
    """
    rows = _thin(len(y), step)
    cols = _thin(len(x), step)
    gx, gy = np.meshgrid(x[cols], y[rows])
    pts = np.dstack([gx, gy, z[np.ix_(rows, cols)]])
    p00, p10 = pts[:-1, :-1], pts[:-1, 1:]
    p01, p11 = pts[1:, :-1], pts[1:, 1:]
    tri_a = np.stack([p00, p10, p11], axis=2).reshape(-1, 3, 3)
    tri_b = np.stack([p00, p11, p01], axis=2).reshape(-1, 3, 3)
    return np.concatenate([tri_a, tri_b])


def _thin(n: int, step: int) -> np.ndarray:
    idx = np.arange(0, n, max(1, step))
    return idx if idx[-1] == n - 1 else np.append(idx, n - 1)


def recenter(tris: np.ndarray, origin) -> np.ndarray:
    """Verschiebt ein Netz, sodass ``origin`` (x, y, z) zum Nullpunkt wird."""
    return tris - np.asarray(origin, dtype=float)


# --------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------

def _indexed(tris: np.ndarray):
    """Dreiecksliste -> (Eckpunkte, Flächenindizes) mit zusammengefassten Punkten."""
    verts, inverse = np.unique(np.round(tris.reshape(-1, 3), 4), axis=0, return_inverse=True)
    return verts, inverse.reshape(-1, 3)


def export_obj(parts: dict, comment: str = "") -> str:
    """Wavefront-OBJ als Text. ``parts`` = {Objektname: Dreiecke (n, 3, 3)}.

    OBJ ist y-up; TERRA-Sim rechnet z-up. Die meisten Programme (Blender,
    Rhino) fragen beim Import nach der Hochachse – hier bleibt z oben.
    """
    out = io.StringIO()
    out.write("# TERRA-Sim 3D-Export (Einheit: Meter, Z = oben)\n")
    for line in comment.splitlines():
        out.write(f"# {line}\n")
    offset = 1
    for name, tris in parts.items():
        if len(tris) == 0:
            continue
        verts, faces = _indexed(tris)
        out.write(f"o {name}\n")
        out.writelines(f"v {x:.3f} {y:.3f} {z:.3f}\n" for x, y, z in verts)
        out.writelines(f"f {a} {b} {c}\n" for a, b, c in faces + offset)
        offset += len(verts)
    return out.getvalue()


def export_stl(parts: dict) -> bytes:
    """Binäres STL (alle Teile in einem Netz), z. B. für den 3D-Druck."""
    import trimesh

    tris = np.concatenate([t for t in parts.values() if len(t)] or [EMPTY])
    verts, faces = _indexed(tris)
    mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
    return mesh.export(file_type="stl")


def export_dxf(building_meshes: list, terrain: np.ndarray | None = None,
               footprints: list | None = None, streets: list | None = None) -> str:
    """DXF für CAD (AutoCAD, Rhino, Vectorworks, ArchiCAD …).

    Layer:
      ``GEBAEUDE_3D``  je Gebäude ein Block aus 3DFACE-Flächen (einzeln anwählbar;
                       zum Bearbeiten im CAD "auflösen" / "explode")
      ``GELAENDE_3D``  Gelände als 3DFACE-Flächen
      ``GRUNDRISSE``   2D-Umrisse der Gebäude (z. B. für den Lasercutter)
      ``STRASSEN``     2D-Straßenachsen
    ``building_meshes`` ist eine Liste von Dreiecks-Arrays ``(n, 3, 3)``.
    """
    import ezdxf
    from ezdxf import units

    doc = ezdxf.new("R2010", setup=False)
    doc.units = units.M
    for name, color in [("GEBAEUDE_3D", 7), ("GELAENDE_3D", 3), ("GRUNDRISSE", 1), ("STRASSEN", 8)]:
        doc.layers.add(name, color=color)
    msp = doc.modelspace()

    for number, tris in enumerate(building_meshes, start=1):
        if len(tris) == 0:
            continue
        block = doc.blocks.new(name=f"GEBAEUDE_{number:04d}")
        for tri in tris.tolist():
            block.add_3dface([*tri, tri[2]], dxfattribs={"layer": "GEBAEUDE_3D"})
        msp.add_blockref(block.name, (0, 0, 0), dxfattribs={"layer": "GEBAEUDE_3D"})

    if terrain is not None:
        for tri in terrain.tolist():
            msp.add_3dface([*tri, tri[2]], dxfattribs={"layer": "GELAENDE_3D"})

    for poly in footprints or []:
        for ring in [poly.exterior, *poly.interiors]:
            msp.add_lwpolyline([(x, y) for x, y, *_ in ring.coords], close=True,
                               dxfattribs={"layer": "GRUNDRISSE"})

    for line in streets or []:
        msp.add_lwpolyline([(x, y) for x, y, *_ in line.coords],
                           dxfattribs={"layer": "STRASSEN"})

    out = io.StringIO()
    doc.write(out)
    return out.getvalue()
