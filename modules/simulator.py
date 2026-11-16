"""Berechnet Hochwasser-, Starkregen- und Starkwind-Effekte (heuristisch).

Alle drei Simulationen sind bewusst einfache **Heuristiken** – schnelle
Ersteinschätzungen für den Entwurf, kein Ersatz für hydraulische Modelle
oder CFD-Strömungssimulation.

Gemeinsame Grundlage ist ein ``Raster``: das Untersuchungsgebiet als Gitter
aus quadratischen Zellen (metrisches Koordinatensystem), mit Geländehöhe und
Flächennutzung je Zelle.

* ``simulate_flood``  Modul A – "Badewannen-Modell": alles unter dem Pegel ist nass.
* ``simulate_rain``   Modul B – Abfluss folgt dem Gefälle und sammelt sich in Senken.
* ``simulate_wind``   Modul C – Sichtlinien-Analyse: Welche Fassade steht frei im Wind?

Beispiel::

    raster = build_raster(bbox, crs, dem.sample, gebaeude, strassen, gruen, wasser)
    flut = simulate_flood(raster, gebaeude, water_level=raster.elevation.min() + 2.0)
    print(flut.kpis["flooded_gfa_m2"])
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from PIL import Image, ImageDraw
from pyproj import Transformer
from scipy import ndimage

BBox = tuple[float, float, float, float]  # (west, south, east, north)

# Flächennutzung je Rasterzelle
LC_OTHER, LC_GREEN, LC_STREET, LC_BUILDING, LC_WATER = 0, 1, 2, 3, 4
LANDCOVER_NAMES = {LC_OTHER: "Sonstige Fläche", LC_GREEN: "Grünfläche", LC_STREET: "Straße / Weg",
                   LC_BUILDING: "Gebäude (Dach)", LC_WATER: "Wasser"}

# Abflussbeiwert: Welcher Anteil des Regens fließt oberflächlich ab?
RUNOFF_COEFF = {LC_OTHER: 0.5, LC_GREEN: 0.15, LC_STREET: 0.9, LC_BUILDING: 0.95, LC_WATER: 0.0}


# ==========================================================================
# Raster
# ==========================================================================

@dataclass
class Raster:
    """Gitter über dem Untersuchungsgebiet. Zeile 0 = Süden, Spalte 0 = Westen."""

    x0: float                 # linke untere Ecke (metrisch)
    y0: float
    cell: float               # Zellgröße in Metern
    nx: int
    ny: int
    crs: str
    elevation: np.ndarray     # (ny, nx) Geländehöhe in der Zellmitte
    landcover: np.ndarray     # (ny, nx) LC_*-Code
    building_idx: np.ndarray  # (ny, nx) Zeilennummer des Gebäudes, -1 = keins
    corner_lon: np.ndarray    # (ny+1, nx+1) Zell-Ecken in WGS84 (für die Darstellung)
    corner_lat: np.ndarray
    corner_z: np.ndarray      # (ny+1, nx+1) Geländehöhe an den Ecken

    @property
    def cell_area(self) -> float:
        return self.cell * self.cell

    @property
    def corner_x(self) -> np.ndarray:
        return self.x0 + np.arange(self.nx + 1) * self.cell

    @property
    def corner_y(self) -> np.ndarray:
        return self.y0 + np.arange(self.ny + 1) * self.cell

    @property
    def sealed_share(self) -> float:
        """Versiegelungsgrad: Anteil Straßen + Dächer an der Landfläche."""
        land = self.landcover != LC_WATER
        sealed = (self.landcover == LC_STREET) | (self.landcover == LC_BUILDING)
        return float(sealed.sum() / max(1, land.sum()))

    def landcover_shares(self) -> dict:
        return {LANDCOVER_NAMES[code]: float((self.landcover == code).mean())
                for code in LANDCOVER_NAMES}


def _rasterize(layers: list, x0: float, y0: float, cell: float, nx: int, ny: int) -> np.ndarray:
    """Brennt Polygone in ein Gitter. ``layers`` = [(Geometrien, Werte), ...].

    Spätere Ebenen überschreiben frühere. Innenhöfe (Löcher) werden auf 0 gesetzt.
    """
    image = Image.new("I", (nx, ny), 0)
    draw = ImageDraw.Draw(image)

    def to_pixels(ring):
        xy = np.asarray(ring.coords)[:, :2]
        return [((x - x0) / cell - 0.5, (y - y0) / cell - 0.5) for x, y in xy]

    for geoms, values in layers:
        for geom, value in zip(geoms, values):
            if geom is None or geom.is_empty:
                continue
            for poly in getattr(geom, "geoms", [geom]):
                if poly.geom_type != "Polygon":
                    continue
                draw.polygon(to_pixels(poly.exterior), fill=int(value))
                for hole in poly.interiors:
                    draw.polygon(to_pixels(hole), fill=0)
    return np.asarray(image)


def build_raster(bbox: BBox, crs: str, sample_elevation,
                 buildings: gpd.GeoDataFrame, streets: gpd.GeoDataFrame,
                 green: gpd.GeoDataFrame, water: gpd.GeoDataFrame,
                 max_cells: int = 150, min_cell_m: float = 2.0) -> Raster:
    """Legt das Analyse-Raster an.

    ``bbox``              Untersuchungsgebiet in WGS84
    ``crs``               metrisches Koordinatensystem der GeoDataFrames
    ``sample_elevation``  Funktion ``(lon, lat) -> Höhe`` (z. B. ``DemGrid.sample``)
    ``buildings`` …       GeoDataFrames **im metrischen CRS**; ``streets``
                          braucht die Spalte ``width_m``
    """
    to_metric = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    to_wgs = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)

    west, south, east, north = bbox
    xs, ys = to_metric.transform([west, east, east, west], [south, south, north, north])
    x0, y0 = min(xs), min(ys)
    width, height = max(xs) - x0, max(ys) - y0

    cell = max(min_cell_m, max(width, height) / max_cells)
    nx = max(2, math.ceil(width / cell))
    ny = max(2, math.ceil(height / cell))

    # Geländehöhe an Zellmitten und Zell-Ecken
    cx, cy = np.meshgrid(x0 + (np.arange(nx) + 0.5) * cell, y0 + (np.arange(ny) + 0.5) * cell)
    lon, lat = to_wgs.transform(cx, cy)
    elevation = np.asarray(sample_elevation(lon, lat), dtype=float)

    kx, ky = np.meshgrid(x0 + np.arange(nx + 1) * cell, y0 + np.arange(ny + 1) * cell)
    corner_lon, corner_lat = to_wgs.transform(kx, ky)
    corner_z = np.asarray(sample_elevation(corner_lon, corner_lat), dtype=float)

    # Flächennutzung: Grün < Wasser < Straße < Gebäude (spätere überschreiben)
    street_areas = streets.geometry.buffer(streets["width_m"].to_numpy() / 2, cap_style="flat") \
        if len(streets) else []
    landcover = _rasterize([
        (green.geometry.values, np.full(len(green), LC_GREEN)),
        (water.geometry.values, np.full(len(water), LC_WATER)),
        (street_areas, np.full(len(streets), LC_STREET)),
        (buildings.geometry.values, np.full(len(buildings), LC_BUILDING)),
    ], x0, y0, cell, nx, ny).astype(np.uint8)

    # Große Gebäude zuerst, damit kleine in Innenhöfen nicht überschrieben werden
    order = np.argsort(-buildings.geometry.area.to_numpy()) if len(buildings) else []
    building_idx = _rasterize(
        [(buildings.geometry.values[order], np.asarray(order) + 1)], x0, y0, cell, nx, ny
    ).astype(np.int32) - 1

    return Raster(x0, y0, cell, nx, ny, crs, elevation, landcover, building_idx,
                  np.asarray(corner_lon), np.asarray(corner_lat), corner_z)


# ==========================================================================
# Modul A – Hochwasser ("Badewannen-Modell")
# ==========================================================================

@dataclass
class FloodResult:
    water_level: float            # Wasserspiegel (absolute Höhe in m)
    depth: np.ndarray             # (ny, nx) Wassertiefe über Gelände, 0 = trocken
    building_depth: np.ndarray    # je Gebäude: Wassertiefe am Gebäude
    affected: np.ndarray          # je Gebäude: True = steht im Wasser
    kpis: dict


def simulate_flood(raster: Raster, buildings: gpd.GeoDataFrame, water_level: float) -> FloodResult:
    """Badewannen-Modell: Jede Fläche unterhalb des Wasserspiegels gilt als überflutet.

    Vereinfachung: Es wird nicht geprüft, ob das Wasser die Fläche tatsächlich
    erreichen kann (Deiche, abgeschlossene Senken) – das Ergebnis ist also
    eine Obergrenze der Betroffenheit.

    ``buildings`` braucht die Spalten ``ground_m`` (Geländehöhe am Gebäude)
    und ``area_m2`` (Grundfläche = BGF des Erdgeschosses).
    """
    depth = np.clip(water_level - raster.elevation, 0, None)
    wet = depth > 0

    building_depth = np.clip(water_level - buildings["ground_m"].to_numpy(float), 0, None)
    affected = building_depth > 0.01
    area = buildings["area_m2"].to_numpy(float)

    kpis = {
        "buildings_total": int(len(buildings)),
        "buildings_affected": int(affected.sum()),
        "flooded_gfa_m2": float(area[affected].sum()),       # überflutete BGF im EG
        "total_gfa_m2": float(area.sum()),
        "flooded_area_m2": float(wet.sum() * raster.cell_area),
        "flooded_share": float(wet.mean()),
        "flooded_street_m2": float((wet & (raster.landcover == LC_STREET)).sum() * raster.cell_area),
        "max_depth_m": float(depth.max()),
        "max_building_depth_m": float(building_depth.max()) if len(buildings) else 0.0,
    }
    return FloodResult(float(water_level), depth, building_depth, affected, kpis)


def flood_curve(buildings: gpd.GeoDataFrame, base_level: float,
                gauges=np.arange(0.0, 10.01, 0.25)) -> pd.DataFrame:
    """Betroffenheit für eine ganze Pegel-Reihe (für das Diagramm)."""
    ground = buildings["ground_m"].to_numpy(float)
    area = buildings["area_m2"].to_numpy(float)
    wet = (base_level + np.asarray(gauges)[:, None]) > ground[None, :] + 0.01
    return pd.DataFrame({
        "Pegel (m)": gauges,
        "Betroffene Gebäude": wet.sum(axis=1),
        "Überflutete BGF EG (m²)": (wet * area[None, :]).sum(axis=1),
    })


# ==========================================================================
# Modul B – Starkregen & Oberflächenabfluss
# ==========================================================================

@dataclass
class RainResult:
    rain_mm: float
    ponding_depth: np.ndarray        # (ny, nx) Wassertiefe in Senken (m)
    flow_m3: np.ndarray              # (ny, nx) Abfluss, der durch die Zelle läuft (m³)
    risk: np.ndarray                 # (ny, nx) kombinierter Risiko-Index 0..1
    building_depth: np.ndarray       # je Gebäude: größte Wassertiefe direkt am Gebäude
    affected: np.ndarray             # je Gebäude: Wasser >= 10 cm am Gebäude
    kpis: dict


_NEIGHBOURS = ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1))


def _priority_flood(z: np.ndarray):
    """Füllt Senken ("Priority-Flood") und bestimmt dabei die Fließwege.

    Das Gebiet wird vom Rand her nach innen "geflutet", immer an der aktuell
    tiefsten Stelle. Rückgabe:
      ``filled``  Gelände mit bis zum Überlauf aufgefüllten Senken
      ``order``   Reihenfolge der Zellen (vom Auslass zur Quelle)
      ``parent``  je Zelle die Nachbarzelle, in die sie entwässert (-1 = Gebietsrand)
    """
    ny, nx = z.shape
    flat = z.ravel().tolist()
    filled = flat[:]
    parent = [-1] * (ny * nx)
    closed = bytearray(ny * nx)
    heap, order, seq = [], [], 0

    for r in range(ny):
        for c in range(nx):
            if r in (0, ny - 1) or c in (0, nx - 1):
                i = r * nx + c
                closed[i] = 1
                heap.append((flat[i], seq, i))
                seq += 1
    heapq.heapify(heap)

    while heap:
        level, _, i = heapq.heappop(heap)
        order.append(i)
        r, c = divmod(i, nx)
        for dr, dc in _NEIGHBOURS:
            rr, cc = r + dr, c + dc
            if 0 <= rr < ny and 0 <= cc < nx:
                j = rr * nx + cc
                if not closed[j]:
                    closed[j] = 1
                    new_level = flat[j] if flat[j] > level else level
                    filled[j] = new_level
                    parent[j] = i
                    seq += 1
                    heapq.heappush(heap, (new_level, seq, j))

    return np.array(filled).reshape(ny, nx), order, parent


def _fill_depression(capacity_depth: np.ndarray, volume: float, cell_area: float) -> np.ndarray:
    """Verteilt ein Wasservolumen in einer Senke (Wasserspiegel per Bisektion)."""
    if volume >= capacity_depth.sum() * cell_area:
        return capacity_depth
    low, high = 0.0, float(capacity_depth.max())  # Freibord unter dem Überlauf
    for _ in range(30):
        mid = (low + high) / 2
        if np.clip(capacity_depth - mid, 0, None).sum() * cell_area > volume:
            low = mid
        else:
            high = mid
    return np.clip(capacity_depth - high, 0, None)


def _closed_gaps(blocked: np.ndarray, max_cells: int) -> np.ndarray:
    """Kleine, ringsum von Gebäuden eingeschlossene Lücken (z. B. Spalte zwischen
    zwei OSM-Grundrissen, die beim Rastern übrig bleiben)."""
    labels, count = ndimage.label(~blocked, structure=np.ones((3, 3)))
    if not count:
        return np.zeros_like(blocked)
    sizes = ndimage.sum(np.ones_like(labels), labels, np.arange(1, count + 1))
    edge = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
    small = np.flatnonzero(sizes <= max_cells) + 1
    return np.isin(labels, np.setdiff1d(small, edge))


def _downpipes(raster: Raster, roof_m3: np.ndarray, obstacle: np.ndarray) -> np.ndarray:
    """Fallrohre: Das Dachwasser jedes Gebäudes kommt an seiner tiefsten
    Nachbarzelle auf den Boden. Rückgabe: Abflussmenge je Zelle (m³)."""
    out = np.zeros_like(roof_m3)
    labels = raster.building_idx + 1
    for i, window in enumerate(ndimage.find_objects(labels)):
        if window is None:
            continue
        # Fenster um eine Zelle erweitern, damit die Nachbarzellen dabei sind
        rows = slice(max(0, window[0].start - 1), min(labels.shape[0], window[0].stop + 1))
        cols = slice(max(0, window[1].start - 1), min(labels.shape[1], window[1].stop + 1))
        mine = labels[rows, cols] == i + 1
        volume = float(roof_m3[rows, cols][mine].sum())
        ring = ndimage.binary_dilation(mine) & ~mine & ~obstacle[rows, cols]
        if not ring.any():                       # ringsum bebaut: Wasser bleibt auf dem Dach
            out[rows, cols][mine] += roof_m3[rows, cols][mine]
            continue
        z = np.where(ring, raster.elevation[rows, cols], np.inf)
        r, c = np.unravel_index(np.argmin(z), z.shape)
        out[rows.start + r, cols.start + c] += volume
    return out


def simulate_rain(raster: Raster, n_buildings: int, rain_mm: float, sewer_mm: float = 20.0,
                  building_block_m: float = 0.5, min_courtyard_m2: float = 40.0,
                  min_pond_m2: float = 25.0) -> RainResult:
    """Starkregen-Heuristik: Wo sammelt sich das Wasser?

    1. Die **Kanalisation** nimmt von Dächern, Straßen und befestigten Flächen
       die ersten ``sewer_mm`` Liter je m² auf (ausgelegt sind Kanäle meist auf
       Regen, wie er alle 2–5 Jahre vorkommt: etwa 15–25 l/m² in einer Stunde).
    2. Der Rest fließt oberflächlich ab (Regen x Abflussbeiwert). Dachwasser
       kommt über die **Fallrohre** an der tiefsten Stelle neben dem Gebäude an.
    3. Das Wasser folgt dem Gefälle; Gebäude wirken als Hindernis.
    4. In Geländesenken staut es sich, bis die Senke voll ist.

    ``building_block_m`` ist die Höhe, bis zu der ein Gebäude Wasser aufhält
    (Schwelle / Sockel). Steht das Wasser höher, läuft es "durch" das Gebäude
    weiter – ein geschlossener Innenhof staut also höchstens so tief ein.
    Eingeschlossene Lücken unter ``min_courtyard_m2`` gelten als bebaut.
    Ein Gebäude gilt als betroffen, wenn daneben mindestens 10 cm Wasser auf
    einer Fläche von mindestens ``min_pond_m2`` stehen.

    Vereinfachungen: Kanalisation als feste Menge (kein Rückstau, keine
    Leitungen), keine zeitliche Dynamik (das gesamte Ereignis wird auf einmal
    bilanziert).
    """
    lc = raster.landcover
    coeff = np.vectorize(RUNOFF_COEFF.get)(lc).astype(float)
    sewered = (lc == LC_STREET) | (lc == LC_BUILDING) | (lc == LC_OTHER)
    effective_mm = np.where(sewered, max(0.0, rain_mm - sewer_mm), rain_mm)
    runoff_m3 = effective_mm / 1000.0 * coeff * raster.cell_area
    sewer_m3 = float((np.minimum(rain_mm, sewer_mm) / 1000.0 * coeff * raster.cell_area)[sewered].sum())

    # Hindernisse: Gebäude plus winzige eingeschlossene Spalte dazwischen
    obstacle = (lc == LC_BUILDING) | _closed_gaps(lc == LC_BUILDING,
                                                 int(min_courtyard_m2 / raster.cell_area))
    # Dachwasser über Fallrohre neben das Gebäude leiten
    roof_m3 = np.where(raster.building_idx >= 0, runoff_m3, 0.0)
    runoff_m3 = np.where(raster.building_idx >= 0, 0.0, runoff_m3) + _downpipes(raster, roof_m3, obstacle)

    # Gebäude als Hindernis: Abfluss fließt außen herum.
    surface = raster.elevation + np.where(obstacle, building_block_m, 0.0)
    filled, order, parent = _priority_flood(surface)

    # Abfluss aufsummieren: von den Quellen (zuletzt geflutet) zum Auslass
    flow = runoff_m3.ravel().tolist()
    for i in reversed(order):
        p = parent[i]
        if p >= 0:
            flow[p] += flow[i]
    flow_m3 = np.array(flow).reshape(raster.ny, raster.nx)

    # Senken füllen
    capacity_depth = filled - surface
    labels, count = ndimage.label(capacity_depth > 0.03, structure=np.ones((3, 3)))
    ponding = np.zeros_like(surface)
    if count:
        index = np.arange(1, count + 1)
        inflow = ndimage.maximum(flow_m3, labels, index)
        for i, window in enumerate(ndimage.find_objects(labels)):
            mask = labels[window] == i + 1
            ponding[window][mask] = _fill_depression(
                capacity_depth[window][mask], float(inflow[i]), raster.cell_area)
    ponding[lc == LC_WATER] = 0.0

    # Risiko-Index: Wassertiefe in Senken (0.5 m = 1.0) oder starke Abflussbahn
    pond_index = np.clip(ponding / 0.5, 0, 1)
    flow_index = np.clip(np.log10(np.maximum(flow_m3, 1e-9) / 50.0) / np.log10(5000.0 / 50.0), 0, 1)
    flow_index[obstacle | (lc == LC_WATER)] = 0.0  # nur Gelände bewerten
    risk = np.maximum(pond_index, 0.7 * flow_index)

    # Gebäude: größte Wassertiefe in den Nachbarzellen. Pfützen unter ``min_pond_m2``
    # zählen nicht – sie liegen unter der Genauigkeit von Raster und Höhenmodell.
    building_depth = np.zeros(n_buildings)
    if n_buildings:
        wet, n_ponds = ndimage.label(ponding >= 0.10, structure=np.ones((3, 3)))
        if n_ponds:
            area = ndimage.sum(np.ones_like(wet), wet, np.arange(1, n_ponds + 1)) * raster.cell_area
            small = np.isin(wet, np.flatnonzero(area < min_pond_m2) + 1)
        else:
            small = np.zeros_like(wet, dtype=bool)
        nearby = ndimage.maximum_filter(np.where(small, np.minimum(ponding, 0.099), ponding), size=3)
        building_depth = np.nan_to_num(np.asarray(ndimage.maximum(
            nearby, raster.building_idx + 1, np.arange(1, n_buildings + 1)), dtype=float))
    affected = building_depth >= 0.10

    land = lc != LC_WATER
    rain_m3 = rain_mm / 1000.0 * land.sum() * raster.cell_area
    kpis = {
        "sealed_share": raster.sealed_share,
        "rain_m3": float(rain_m3),
        "sewer_mm": float(sewer_mm),
        "sewer_m3": sewer_m3,
        "runoff_m3": float(runoff_m3.sum()),
        "runoff_coeff": float(runoff_m3.sum() / rain_m3) if rain_m3 else 0.0,
        "ponding_area_m2": float((ponding >= 0.10).sum() * raster.cell_area),
        "ponding_volume_m3": float(ponding.sum() * raster.cell_area),
        "max_ponding_m": float(ponding.max()),
        "buildings_affected": int(affected.sum()),
        "buildings_total": int(n_buildings),
    }
    return RainResult(float(rain_mm), ponding, flow_m3, risk, building_depth, affected, kpis)


# ==========================================================================
# Modul C – Starkwind & Düseneffekte
# ==========================================================================

BEAUFORT_NAMES = ["Windstille", "leiser Zug", "leichte Brise", "schwache Brise",
                  "mäßige Brise", "frische Brise", "starker Wind", "steifer Wind",
                  "stürmischer Wind", "Sturm", "schwerer Sturm", "orkanartiger Sturm", "Orkan"]

AIR_DENSITY = 1.25         # kg/m³
PRESSURE_COEFF = 0.8       # Druckbeiwert einer frei angeströmten Luv-Fassade
WIND_PROFILE_EXPONENT = 0.25  # Zunahme der Windgeschwindigkeit mit der Höhe (Stadt)


def beaufort_to_ms(beaufort: float) -> float:
    """Windgeschwindigkeit in 10 m Höhe (m/s) aus der Beaufort-Stärke."""
    return 0.836 * beaufort ** 1.5


@dataclass
class WindResult:
    direction_deg: float
    speed_ms: float
    facades: pd.DataFrame          # je Luv-Fassade: Lage, Exposition, Winddruck
    building_exposure: np.ndarray  # je Gebäude: höchste Fassaden-Exposition 0..1
    venturi: gpd.GeoDataFrame      # Engstellen mit Düseneffekt (Linie quer durch die Lücke)
    kpis: dict


def simulate_wind(buildings: gpd.GeoDataFrame, direction_deg: float, beaufort: float,
                  shelter_reach: float = 8.0, max_gap_m: float = 20.0) -> WindResult:
    """Wind-Heuristik mit Sichtlinien statt Strömungssimulation.

    ``direction_deg``  Richtung, AUS der der Wind kommt (0 = Nord, 90 = Ost)
    ``shelter_reach``  Länge des Windschattens hinter einem Hindernis in
                       Vielfachen seiner Höhe

    Fassaden: Von jeder dem Wind zugewandten Fassade wird ein Strahl gegen
    den Wind geschickt. Trifft er ein anderes Gebäude, liegt die Fassade
    (teilweise) im Windschatten.

    Düseneffekt: Schmale, hohe Lücken zwischen zwei Gebäuden, die in
    Windrichtung verlaufen, beschleunigen die Strömung (Venturi-Effekt).

    ``buildings`` (metrisches CRS) braucht ``height_m`` und ``eave_height_m``.
    """
    theta = math.radians(direction_deg)
    upwind = np.array([math.sin(theta), math.cos(theta)])  # zeigt zur Windquelle
    speed = beaufort_to_ms(beaufort)
    n = len(buildings)

    empty_venturi = gpd.GeoDataFrame(
        {"width_m": [], "hw_ratio": [], "factor": [], "speed_ms": [], "building": []},
        geometry=[], crs=buildings.crs)
    if n == 0:
        return WindResult(direction_deg, speed, pd.DataFrame(), np.zeros(0), empty_venturi,
                          _wind_kpis(speed, pd.DataFrame(), 0.0, empty_venturi))

    geoms = np.asarray(buildings.geometry.values)
    heights = buildings["height_m"].to_numpy(float)
    eaves = buildings["eave_height_m"].to_numpy(float)
    tree = shapely.STRtree(geoms)

    # ---- Fassaden-Segmente aus den Außenringen -------------------------
    rings = shapely.get_exterior_ring(geoms)
    coords, owner = shapely.get_coordinates(rings, return_index=True)
    same_ring = owner[:-1] == owner[1:]
    a, b, seg_building = coords[:-1][same_ring], coords[1:][same_ring], owner[:-1][same_ring]

    delta = b - a
    length = np.linalg.norm(delta, axis=1)
    keep = length >= 1.0
    a, b, delta, length, seg_building = a[keep], b[keep], delta[keep], length[keep], seg_building[keep]

    # Außennormale: bei Umlauf gegen den Uhrzeigersinn liegt "außen" rechts der Kante
    sign = np.where(shapely.is_ccw(rings)[seg_building], 1.0, -1.0)
    normal = np.column_stack([delta[:, 1], -delta[:, 0]]) / length[:, None] * sign[:, None]
    total_facade_area = float((length * eaves[seg_building]).sum())

    facing = normal @ upwind            # 1 = frontal im Wind, <= 0 = Lee-Seite
    windward = facing > 0.05
    a, b, normal, length = a[windward], b[windward], normal[windward], length[windward]
    facing, seg_building = facing[windward], seg_building[windward]

    # ---- Sichtlinien gegen den Wind ------------------------------------
    mid = (a + b) / 2
    start = mid + 0.3 * normal
    reach = float(min(400.0, max(50.0, shelter_reach * heights.max())))
    rays = shapely.linestrings(np.stack([start, start + reach * upwind], axis=1))

    shelter = np.zeros(len(rays))
    ray_idx, hit_idx = tree.query(rays, predicate="intersects")
    if len(ray_idx):
        hit = shapely.intersection(rays[ray_idx], geoms[hit_idx])
        distance = shapely.distance(shapely.points(start[ray_idx]), hit)
        obstacle_h = heights[hit_idx]
        own_h = np.maximum(heights[seg_building[ray_idx]], 0.1)
        cover = np.clip(obstacle_h / own_h, 0, 1) * \
            np.clip(1 - distance / (shelter_reach * np.maximum(obstacle_h, 0.1)), 0, 1)
        np.maximum.at(shelter, ray_idx, np.nan_to_num(cover))

    exposure = facing * (1 - shelter)
    wall_h = np.maximum(eaves[seg_building], 0.1)
    speed_at_roof = speed * (np.maximum(heights[seg_building], 2.0) / 10.0) ** WIND_PROFILE_EXPONENT
    pressure = 0.5 * AIR_DENSITY * speed_at_roof ** 2 * PRESSURE_COEFF * exposure / 1000.0  # kN/m²
    area = length * wall_h

    facades = pd.DataFrame({
        "building": seg_building,
        "ax": a[:, 0], "ay": a[:, 1], "bx": b[:, 0], "by": b[:, 1],
        "nx": normal[:, 0], "ny": normal[:, 1],
        "length_m": length, "height_m": wall_h, "area_m2": area,
        "facing": facing, "shelter": shelter, "exposure": exposure,
        "pressure_kn_m2": pressure, "force_kn": pressure * area,
    })

    building_exposure = np.zeros(n)
    np.maximum.at(building_exposure, seg_building, exposure)

    venturi = _find_venturi(buildings, geoms, heights, tree, -upwind, speed, max_gap_m, empty_venturi)
    return WindResult(direction_deg, speed, facades, building_exposure, venturi,
                      _wind_kpis(speed, facades, total_facade_area, venturi))


def _find_venturi(buildings, geoms, heights, tree, flow_dir, speed, max_gap_m, empty,
                  min_length_m: float = 8.0):
    """Engstellen zwischen Gebäudepaaren, die in Windrichtung durchströmt werden.

    Kriterien: Lücke 2 m bis ``max_gap_m`` breit, Gebäude mindestens so hoch
    wie die Lücke breit (H/B >= 1), Gasse höchstens 30° zur Windrichtung gedreht.
    """
    i, j = tree.query(geoms, predicate="dwithin", distance=max_gap_m)
    pair = i < j
    i, j = i[pair], j[pair]
    if len(i) == 0:
        return empty

    gap = shapely.shortest_line(geoms[i], geoms[j])
    width = shapely.length(gap)
    ok = width >= 2.0                      # aneinandergebaute Häuser sind keine Lücke
    i, j, gap, width = i[ok], j[ok], gap[ok], width[ok]
    if len(i) == 0:
        return empty

    ends = shapely.get_coordinates(gap).reshape(-1, 2, 2)
    across = (ends[:, 1] - ends[:, 0]) / width[:, None]
    along = np.column_stack([-across[:, 1], across[:, 0]])   # Achse der Gasse
    alignment = np.abs(along @ flow_dir)                     # 1 = Wind bläst genau hindurch
    ratio = np.minimum(heights[i], heights[j]) / width       # Schluchtmaß H/B

    min_alignment = math.cos(math.radians(30))
    ok = (alignment >= min_alignment) & (ratio >= 1.0)

    # Eine Düse braucht Länge: Beide Gebäude müssen sich entlang der Gasse
    # mindestens ``min_length_m`` gegenüberstehen (sonst ist es nur eine Ecke).
    for k in np.flatnonzero(ok):
        side_a = shapely.get_coordinates(geoms[i[k]]) @ along[k]
        side_b = shapely.get_coordinates(geoms[j[k]]) @ along[k]
        ok[k] = min(side_a.max(), side_b.max()) - max(side_a.min(), side_b.min()) >= min_length_m
    if not ok.any():
        return empty

    factor = 1 + 0.6 * (alignment[ok] - min_alignment) / (1 - min_alignment) \
        * np.minimum(ratio[ok], 2.5) / 2.5
    return gpd.GeoDataFrame({
        "width_m": width[ok],
        "hw_ratio": ratio[ok],
        "factor": factor,
        "speed_ms": speed * factor,
        "building": i[ok],
    }, geometry=gap[ok], crs=buildings.crs).reset_index(drop=True)


def _wind_kpis(speed, facades, total_facade_area, venturi) -> dict:
    has = len(facades) > 0
    high = facades["exposure"] >= 0.6 if has else []
    medium = (facades["exposure"] >= 0.3) & ~high if has else []
    return {
        "speed_ms": float(speed),
        "speed_kmh": float(speed * 3.6),
        "facade_area_total_m2": float(total_facade_area),
        "facade_area_high_m2": float(facades.loc[high, "area_m2"].sum()) if has else 0.0,
        "facade_area_medium_m2": float(facades.loc[medium, "area_m2"].sum()) if has else 0.0,
        "max_pressure_kn_m2": float(facades["pressure_kn_m2"].max()) if has else 0.0,
        "total_force_kn": float(facades["force_kn"].sum()) if has else 0.0,
        "venturi_count": int(len(venturi)),
        "venturi_max_speed_ms": float(venturi["speed_ms"].max()) if len(venturi) else 0.0,
        "venturi_max_factor": float(venturi["factor"].max()) if len(venturi) else 1.0,
    }
