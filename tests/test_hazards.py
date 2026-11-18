"""Erdbeben, Tornado, Kaiju, Aliens (modules/hazards.py) – Formeln wie in modules/methods.py."""

import math

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import box

from modules import hazards as hz


@pytest.fixture(scope="module")
def model():
    from tests.fixtures import demo_model
    return demo_model()


def _single_houses(n=3, kind="house", levels=2.0):
    """Frei stehende, quadratische Häuser (keine Nachbarn, kompakter Grundriss)."""
    geoms = [box(i * 50, 0, i * 50 + 10, 10) for i in range(n)]
    return gpd.GeoDataFrame({"building": [kind] * n, "levels": [levels] * n, "height_m": [levels * 3] * n,
                             "area_m2": [100.0] * n}, geometry=geoms, crs="EPSG:25832")


# --------------------------------------------------------------------------- Erdbeben

def test_epicentral_and_site_intensity():
    assert hz.epicentral_intensity(5.5) == pytest.approx(7.75)
    assert hz.epicentral_intensity(9.5) == 12.0                         # Skala endet bei XII
    assert hz.site_intensity(5.5, 0) == pytest.approx(hz.epicentral_intensity(5.5))   # r = h
    near, far = hz.site_intensity(5.5, 10), hz.site_intensity(5.5, 80)
    assert far < near < hz.epicentral_intensity(5.5)


def test_pga_follows_wald_1999():
    for intensity in (5, 6.5, 8):
        assert hz.pga_g(intensity) * 981 == pytest.approx(10 ** ((intensity + 1.66) / 3.66))


@pytest.mark.parametrize("kind, levels, cls", [("church", 1, "A"), ("house", 2, "B"), ("apartments", 4, "B"),
                                               ("apartments", 7, "C"), ("office", 3, "C"), ("warehouse", 1, "C")])
def test_vulnerability_class(kind, levels, cls):
    assert hz.vulnerability_class(kind, levels) == cls


def test_earthquake_damage_matches_lagomarsino_giovinazzi():
    """μD = 2,5·[1 + tanh((I + 6,25·V − 13,1) / Q)] mit V = 0,72 (Mauerwerk) − 0,02 (≤ 2 Geschosse)."""
    houses = _single_houses()
    result = hz.simulate_earthquake(houses, magnitude=6.0, distance_km=10, soil="Mittel")
    intensity = result.kpis["intensity"]
    expected = 2.5 * (1 + math.tanh((intensity + 6.25 * (0.72 - 0.02) - 13.1) / 2.3))
    assert np.allclose(result.damage, expected)
    assert 0 <= result.damage.min() and result.damage.max() <= 5


def test_soft_soil_and_stronger_quake_cause_more_damage():
    houses = _single_houses()
    base = hz.simulate_earthquake(houses, 5.5, 15, "Mittel").damage.mean()
    assert hz.simulate_earthquake(houses, 5.5, 15, "Weich").damage.mean() > base
    assert hz.simulate_earthquake(houses, 5.5, 15, "Fels").damage.mean() < base
    assert hz.simulate_earthquake(houses, 6.5, 15, "Mittel").damage.mean() > base


# --------------------------------------------------------------------------- Tornado

def test_rankine_vortex_profile():
    ef = 3
    d = np.arange(0.0, 2000.0, 1.0)
    right = hz.tornado_speed(d, np.ones_like(d), ef)
    left = hz.tornado_speed(d, -np.ones_like(d), ef)
    assert np.all(right >= left)                                       # rechts addiert sich die Zuggeschwindigkeit
    assert right.max() == pytest.approx(hz.EF_GUST_MS[ef], rel=0.01)   # Spitzenböe der Stufe am Kernrand
    core = int(np.argmax(right))
    assert np.all(np.diff(right[:core + 1]) >= 0)                      # innen linear ansteigend
    assert np.all(np.diff(right[core:]) <= 0)                          # außen mit 1/r abfallend
    assert right[hz.EF_PATH_WIDTH_M[ef] // 2] >= 28                    # am Schneisenrand noch schadensrelevant


def test_tornado_damage_grows_with_strength(model):
    weak = hz.simulate_tornado(model.buildings, model.raster, 0, 60)
    strong = hz.simulate_tornado(model.buildings, model.raster, 5, 60)
    assert strong.damage.sum() > weak.damage.sum()
    assert strong.kpis["heavy"] >= weak.kpis["heavy"]


# --------------------------------------------------------------------------- Planspiele

def test_kaiju_and_aliens_run(model):
    kaiju = hz.simulate_kaiju(model.buildings, model.raster, 80, 90)
    assert kaiju.kpis["buildings_total"] == len(model.buildings)
    assert kaiju.damage.shape == (len(model.buildings),)
    alien = hz.simulate_alien(model.buildings, model.raster, 2, 30, 60)
    assert alien.kpis["buildings_total"] == len(model.buildings)
