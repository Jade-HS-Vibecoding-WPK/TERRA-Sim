"""Weitere Katastrophen: Erdbeben, Tornado und Kaiju-Angriff (heuristisch).

Wie ``simulator.py`` sind das **Ersteinschätzungen** für Entwurf und Lehre.
Alle drei Module liefern je Gebäude einen **Schadensgrad von 0 bis 5**
(angelehnt an die Europäische Makroseismische Skala EMS-98):

    0 kein Schaden · 1 leicht (Putz, Dachziegel) · 2 mäßig (Risse, Dach teilweise)
    3 schwer (Wände, Dachstuhl) · 4 sehr schwer (Teileinsturz) · 5 zerstört

* ``simulate_earthquake``  Modul D – makroseismische Methode: Intensität am
  Standort x Verletzbarkeit des Gebäudetyps.
* ``simulate_tornado``     Modul E – Wirbel nach Rankine, der über das Gebiet
  zieht; Schaden aus der Windgeschwindigkeit am Gebäude.
* ``simulate_kaiju``       Modul F – ein Riesenmonster läuft quer durch das
  Gebiet (Planspiel: Wie robust ist die Stadtstruktur?).

Die Gebäude kommen als metrischer GeoDataFrame mit den Spalten aus
``osm_fetcher`` (``building``, ``levels``, ``height_m``, ``area_m2``).

Beispiel::

    beben = simulate_earthquake(gebaeude, magnitude=5.5, distance_km=15)
    print(beben.kpis["heavy"], "Gebäude schwer beschädigt")
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import shapely

DAMAGE_NAMES = ["kein Schaden", "leicht", "mäßig", "schwer", "sehr schwer", "zerstört"]

# Gebäudetypen (OSM-Tag ``building``) für die Verletzbarkeit
HISTORIC = {"church", "cathedral", "chapel", "tower", "bell_tower", "castle", "ruins", "temple",
            "mosque", "synagogue", "monastery"}
REINFORCED = {"office", "hospital", "university", "college", "commercial", "parking", "train_station",
              "transportation", "civic", "government", "public", "hotel"}
HALLS = {"industrial", "warehouse", "hangar", "factory", "retail", "supermarket", "sports_hall",
         "stadium", "manufacture"}
LIGHT = {"shed", "garage", "garages", "hut", "carport", "roof", "greenhouse", "kiosk", "container",
         "cabin", "boathouse"}


@dataclass
class HazardResult:
    damage: np.ndarray                 # je Gebäude: Schadensgrad 0..5 (Kommazahl = Mittelwert)
    kpis: dict
    overlay: np.ndarray | None = None  # (ny, nx) 0..1 für die Heatmap auf dem Gelände
    extra: dict = field(default_factory=dict)

    @property
    def grade(self) -> np.ndarray:
        """Gerundeter Schadensgrad 0..5."""
        return np.clip(np.round(self.damage), 0, 5).astype(int)


def collapse_scale(damage: np.ndarray) -> np.ndarray:
    """Höhenfaktor für die 3D-Ansicht: ab Grad 3 sackt das Gebäude sichtbar zusammen."""
    return 1.0 - 0.7 * np.clip((np.asarray(damage, float) - 3.0) / 2.0, 0, 1)


def _damage_kpis(buildings, damage: np.ndarray) -> dict:
    grade = np.clip(np.round(damage), 0, 5)
    gfa = (buildings["area_m2"].to_numpy(float) * buildings["levels"].to_numpy(float)) if len(buildings) \
        else np.zeros(0)
    return {
        "buildings_total": int(len(buildings)),
        "damaged": int((grade >= 1).sum()),
        "heavy": int((grade >= 3).sum()),
        "destroyed": int((grade >= 5).sum()),
        "unusable": int((grade >= 4).sum()),          # nicht mehr bewohnbar
        "mean_damage": float(damage.mean()) if len(damage) else 0.0,
        "gfa_unusable_m2": float(gfa[grade >= 4].sum()),
        "per_grade": [int((grade == g).sum()) for g in range(6)],
    }


# ==========================================================================
# Modul D – Erdbeben (makroseismische Methode)
# ==========================================================================

# Verletzbarkeitsindex V je EMS-98-Klasse (Lagomarsino & Giovinazzi 2006)
VULNERABILITY_INDEX = {"A": 0.88, "B": 0.72, "C": 0.56, "D": 0.40, "E": 0.24}
CLASS_NAMES = {"A": "Bruchstein / historisch", "B": "Mauerwerk", "C": "Stahlbeton / Stahl",
               "D": "Stahlbeton, erdbebengerecht", "E": "sehr robust"}
SOIL_AMPLIFICATION = {"Fels": -0.5, "Mittel": 0.0, "Weich": 0.5}


def vulnerability_class(kind: str, levels: float) -> str:
    """EMS-98-Verletzbarkeitsklasse aus Gebäudetyp und Geschosszahl (grob geschätzt).

    OSM kennt meist weder Baujahr noch Bauweise – deshalb nur eine Faustregel:
    Kirchen & Co. = A, Wohnhäuser und Kleinbauten = B (Mauerwerk),
    Büro-/Großbauten und Hochhäuser = C (Stahlbeton), Hallen = C (Stahl).
    """
    if kind in HISTORIC:
        return "A"
    if kind in REINFORCED or kind in HALLS or levels >= 6:
        return "C"
    return "B"


def vulnerability_modifiers(buildings, classes: np.ndarray) -> np.ndarray:
    """Zuschläge zum Verletzbarkeitsindex (Giovinazzi & Lagomarsino):

    * Geschosszahl – hohe Mauerwerksbauten schwingen ungünstiger
    * unregelmäßiger Grundriss (wenig kompakt) +0,04
    * Lage im Block: Mittelhaus −0,04 (Nachbarn stützen), Endhaus/Ecke +0,04
    """
    if not len(buildings):
        return np.zeros(0)
    geoms = np.asarray(buildings.geometry.values)
    levels = buildings["levels"].to_numpy(float)
    masonry = np.isin(classes, ["A", "B"])
    floors = np.where(masonry, np.select([levels <= 2, levels <= 5], [-0.02, 0.02], 0.06),
                      np.select([levels <= 3, levels <= 7], [-0.02, 0.0], 0.08))
    compact = 4 * np.pi * shapely.area(geoms) / np.maximum(shapely.length(geoms) ** 2, 1e-9)
    irregular = np.where(compact < 0.5, 0.04, 0.0)
    tree = shapely.STRtree(geoms)
    pairs = tree.query(geoms, predicate="dwithin", distance=0.5)
    neighbours = np.bincount(pairs[0][pairs[0] != pairs[1]], minlength=len(geoms))
    position = np.select([neighbours >= 2, neighbours == 1], [-0.04, 0.04], 0.0)
    return floors + irregular + position


def epicentral_intensity(magnitude: float) -> float:
    """Intensität im Epizentrum (EMS-98) aus der Momenten-Magnitude, Herdtiefe ~10 km."""
    return min(12.0, 1.5 * magnitude - 0.5)


def site_intensity(magnitude: float, distance_km: float, depth_km: float = 10.0) -> float:
    """Intensität am Standort: nimmt mit dem Abstand zum Herd ab (Kövesligethy-Ansatz)."""
    r = math.hypot(distance_km, depth_km)
    return max(0.0, epicentral_intensity(magnitude) - 3.0 * math.log10(r / depth_km)
               - 0.002 * (r - depth_km))


def pga_g(intensity: float) -> float:
    """Ungefähre Spitzenbodenbeschleunigung in g (Wald et al. 1999)."""
    return 10 ** ((intensity + 1.66) / 3.66) / 981.0


def simulate_earthquake(buildings, magnitude: float, distance_km: float,
                        soil: str = "Mittel", ductility: float = 2.3) -> HazardResult:
    """Schadensgrad je Gebäude: μD = 2,5 · [1 + tanh((I + 6,25 V − 13,1) / Q)].

    ``soil`` = "Fels" | "Mittel" | "Weich" – weicher Untergrund schaukelt auf.
    """
    soil_key = next((k for k in SOIL_AMPLIFICATION if soil.startswith(k)), "Mittel")
    intensity = site_intensity(magnitude, distance_km) + SOIL_AMPLIFICATION[soil_key]
    kinds = buildings["building"].to_numpy() if len(buildings) else np.array([])
    levels = buildings["levels"].to_numpy(float) if len(buildings) else np.array([])
    classes = np.array([vulnerability_class(k, l) for k, l in zip(kinds, levels)], dtype=object)
    v = np.array([VULNERABILITY_INDEX[c] for c in classes], dtype=float)
    v = v + vulnerability_modifiers(buildings, classes)
    damage = 2.5 * (1 + np.tanh((intensity + 6.25 * v - 13.1) / ductility)) if len(v) else np.zeros(0)
    kpis = _damage_kpis(buildings, damage)
    kpis.update({"intensity": intensity, "pga_g": pga_g(intensity),
                 "epicentral_intensity": epicentral_intensity(magnitude),
                 "classes": {c: int((classes == c).sum()) for c in VULNERABILITY_INDEX}})
    return HazardResult(damage, kpis, extra={"classes": classes, "vulnerability": v})


# ==========================================================================
# Bahn quer durch das Gebiet (Tornado, Kaiju)
# ==========================================================================

def _track(raster, heading_deg: float, offset_m: float):
    """Gerade Bahn durch das Gebiet. ``heading_deg`` = wohin sie zieht (0 = Norden),
    ``offset_m`` = seitlicher Versatz von der Mitte (positiv = rechts in Zugrichtung)."""
    cx = raster.x0 + raster.nx * raster.cell / 2
    cy = raster.y0 + raster.ny * raster.cell / 2
    t = math.radians(heading_deg)
    forward = np.array([math.sin(t), math.cos(t)])
    right = np.array([forward[1], -forward[0]])
    center = np.array([cx, cy]) + right * offset_m
    reach = math.hypot(raster.nx, raster.ny) * raster.cell
    line = shapely.LineString([center - forward * reach, center + forward * reach])
    return line, center, forward, right


def _signed_distance(geoms, line, center, right) -> tuple[np.ndarray, np.ndarray]:
    """Abstand jedes Gebäudes zur Bahn (0 = berührt sie) und Seite (+1 rechts, −1 links)."""
    dist = shapely.distance(np.asarray(geoms), line)
    cent = shapely.centroid(np.asarray(geoms))
    side = np.sign((shapely.get_x(cent) - center[0]) * right[0] + (shapely.get_y(cent) - center[1]) * right[1])
    return np.asarray(dist, float), np.where(side == 0, 1.0, side)


def _cell_distance(raster, center, right) -> np.ndarray:
    """Vorzeichenbehafteter Abstand jeder Rasterzelle zur Bahn (positiv = rechts)."""
    xs = raster.x0 + (np.arange(raster.nx) + 0.5) * raster.cell
    ys = raster.y0 + (np.arange(raster.ny) + 0.5) * raster.cell
    gx, gy = np.meshgrid(xs, ys)
    return (gx - center[0]) * right[0] + (gy - center[1]) * right[1]


# ==========================================================================
# Modul E – Tornado
# ==========================================================================

# Enhanced-Fujita-Skala: typische Spitzenböe (m/s) und Breite der Schadensschneise (m)
EF_GUST_MS = [33, 43, 55, 67, 82, 95]
EF_PATH_WIDTH_M = [30, 60, 140, 260, 400, 550]
TRANSLATION_MS = 15.0     # Zuggeschwindigkeit, auf der rechten Seite addiert sie sich
# Windgeschwindigkeit (m/s), ab der ein Wohnhaus Schadensgrad 0..5 erreicht
WIND_DAMAGE_STEPS = [28, 33, 45, 58, 72, 85]
WIND_RESISTANCE_SHIFT = {"leicht": -10.0, "normal": 0.0, "robust": 12.0}


def wind_resistance(kind: str, levels: float) -> str:
    if kind in LIGHT:
        return "leicht"
    if kind in REINFORCED or levels >= 6:
        return "robust"
    return "normal"


def tornado_speed(d: np.ndarray, side: np.ndarray, ef: int) -> np.ndarray:
    """Windgeschwindigkeit (m/s) im Abstand ``d`` von der Bahnmitte (Rankine-Wirbel)."""
    v_rot = EF_GUST_MS[ef] - TRANSLATION_MS
    half = EF_PATH_WIDTH_M[ef] / 2
    core = max(10.0, 30.0 * half / v_rot)          # Kernradius: am Schneisenrand noch ~30 m/s
    d = np.abs(np.asarray(d, float))
    tangential = np.where(d < core, v_rot * d / core, v_rot * core / np.maximum(d, 1e-6))
    return np.maximum(0.0, tangential + TRANSLATION_MS * side)


def _wind_damage(speed: np.ndarray, shift: np.ndarray) -> np.ndarray:
    return np.interp(speed - shift, WIND_DAMAGE_STEPS, [0, 1, 2, 3, 4, 5])


def simulate_tornado(buildings, raster, ef: int, heading_deg: float, offset_m: float = 0.0) -> HazardResult:
    """Ein Tornado der Stärke ``ef`` (0–5) zieht in Richtung ``heading_deg`` über das Gebiet."""
    ef = int(np.clip(ef, 0, 5))
    line, center, forward, right = _track(raster, heading_deg, offset_m)
    if len(buildings):
        d, side = _signed_distance(buildings.geometry.values, line, center, right)
        kinds, levels = buildings["building"].to_numpy(), buildings["levels"].to_numpy(float)
        shift = np.array([WIND_RESISTANCE_SHIFT[wind_resistance(k, l)] for k, l in zip(kinds, levels)])
        speed = tornado_speed(d, side, ef)
        damage = _wind_damage(speed, shift)
    else:
        speed = damage = np.zeros(0)
    cell_d = _cell_distance(raster, center, right)
    cell_speed = tornado_speed(cell_d, np.sign(cell_d) + (cell_d == 0), ef)
    overlay = np.clip((cell_speed - 28) / (EF_GUST_MS[5] - 28), 0, 1)
    kpis = _damage_kpis(buildings, damage)
    kpis.update({"ef": ef, "gust_ms": EF_GUST_MS[ef], "path_width_m": EF_PATH_WIDTH_M[ef],
                 "max_speed_at_building_ms": float(speed.max()) if len(speed) else 0.0})
    core = max(10.0, 30.0 * EF_PATH_WIDTH_M[ef] / 2 / (EF_GUST_MS[ef] - TRANSLATION_MS))
    return HazardResult(damage, kpis, overlay, extra={
        "speed": speed, "center": center, "forward": forward, "track": line, "core_m": core})


# ==========================================================================
# Modul F – Kaiju-Angriff (Planspiel)
# ==========================================================================

def simulate_kaiju(buildings, raster, height_m: float, heading_deg: float,
                   offset_m: float = 0.0) -> HazardResult:
    """Ein Riesenmonster der Höhe ``height_m`` läuft quer durch das Gebiet.

    * Schneise (Füße, Körper): halbe Breite 0,25 · Höhe -> zerstört (Grad 5)
    * Schwanz und Arme: bis 0,45 · Höhe -> Grad 3–4
    * Erschütterung der Schritte: bis 0,8 · Höhe -> Grad 1–2
    Gebäude, die höher sind als das halbe Monster, halten etwas mehr aus.
    """
    line, center, forward, right = _track(raster, heading_deg, offset_m)
    h = float(height_m)
    if len(buildings):
        d, _ = _signed_distance(buildings.geometry.values, line, center, right)
        damage = np.interp(d, [0, 0.25 * h, 0.25 * h + 1e-6, 0.45 * h, 0.8 * h, 0.8 * h + 1e-6],
                           [5, 5, 4, 3, 1, 0])
        sturdy = buildings["height_m"].to_numpy(float) > 0.5 * h
        damage = np.where(sturdy & (damage < 5), np.maximum(0, damage - 1), damage)
    else:
        damage = np.zeros(0)

    # Fußabdrücke auf dem Gelände: abwechselnd links und rechts der Bahn
    cell_d = _cell_distance(raster, center, right)
    xs = raster.x0 + (np.arange(raster.nx) + 0.5) * raster.cell
    ys = raster.y0 + (np.arange(raster.ny) + 0.5) * raster.cell
    gx, gy = np.meshgrid(xs, ys)
    along = (gx - center[0]) * forward[0] + (gy - center[1]) * forward[1]
    step = 0.45 * h
    k = np.round(along / step)
    foot_side = np.where(k % 2 == 0, 1.0, -1.0) * 0.12 * h
    foot = np.hypot(along - k * step, cell_d - foot_side) < 0.09 * h
    swath = np.clip(1 - np.abs(cell_d) / (0.8 * h), 0, 1) * 0.55
    overlay = np.where(foot, 1.0, swath)

    kpis = _damage_kpis(buildings, damage)
    kpis.update({"height_m": h, "swath_m": 0.5 * h,
                 "taller_buildings": int((buildings["height_m"].to_numpy(float) > h).sum()) if len(buildings) else 0})
    return HazardResult(damage, kpis, overlay, extra={"center": center, "forward": forward, "track": line})
