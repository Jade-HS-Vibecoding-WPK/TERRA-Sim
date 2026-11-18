"""Hochwasser, Starkregen, Starkwind (modules/simulator.py) am Offline-Testgebiet."""

import numpy as np
import pytest

from modules import simulator as sim


@pytest.fixture(scope="module")
def model():
    from tests.fixtures import demo_model
    return demo_model()


# --------------------------------------------------------------------------- Hochwasser

def test_flood_extremes(model):
    dry = sim.simulate_flood(model.raster, model.buildings, model.zmin - 1)
    assert dry.kpis["buildings_affected"] == 0
    assert dry.depth.max() == 0
    wet = sim.simulate_flood(model.raster, model.buildings, model.raster.elevation.max() + 1)
    assert wet.kpis["buildings_affected"] == len(model.buildings)


def test_flood_depth_is_level_minus_ground(model):
    level = model.zmin + 1.5
    result = sim.simulate_flood(model.raster, model.buildings, level)
    expected = np.clip(level - model.raster.elevation, 0, None)
    assert np.allclose(result.depth, expected)


def test_flood_grows_with_level(model):
    shares = [sim.simulate_flood(model.raster, model.buildings, model.zmin + h).kpis["flooded_share"]
              for h in (0.5, 1.5, 3.0, 5.0)]
    assert shares == sorted(shares)


# --------------------------------------------------------------------------- Starkregen

def test_rain_mass_balance(model):
    result = sim.simulate_rain(model.raster, len(model.buildings), rain_mm=100, sewer_mm=20)
    k = result.kpis
    assert k["ponding_volume_m3"] <= k["runoff_m3"] * 1.001 + 1e-6      # es staut sich nicht mehr, als abfließt
    assert k["runoff_m3"] < k["rain_m3"]
    assert result.ponding_depth.min() >= 0


def test_more_rain_more_water_and_sewer_helps(model):
    n = len(model.buildings)
    runs = [sim.simulate_rain(model.raster, n, rain, 20).kpis for rain in (21, 22, 30, 60, 120)]
    runoff = [k["runoff_m3"] for k in runs]
    ponding = [k["ponding_volume_m3"] for k in runs]
    assert runoff == sorted(runoff) and runoff[-1] > runoff[0]          # mehr Regen, mehr Abfluss
    assert ponding == sorted(ponding) and ponding[1] > ponding[0]       # Senken füllen sich …
    assert ponding[-1] == pytest.approx(ponding[-2])                    # … bis sie voll sind, der Rest fließt ab
    no_sewer = sim.simulate_rain(model.raster, n, 60, 0).kpis
    big_sewer = sim.simulate_rain(model.raster, n, 60, 40).kpis
    assert big_sewer["runoff_m3"] < no_sewer["runoff_m3"]


def test_water_collects_in_the_hollow(model):
    """Die Mulde im Südwesten des Testgeländes muss sich füllen."""
    result = sim.simulate_rain(model.raster, len(model.buildings), 120, 0)
    ny, nx = result.ponding_depth.shape
    hollow = result.ponding_depth[: ny // 2, : nx // 2]
    assert hollow.max() > 0.05


# --------------------------------------------------------------------------- Starkwind

def test_beaufort():
    assert sim.beaufort_to_ms(0) == 0
    assert sim.beaufort_to_ms(12) == pytest.approx(0.836 * 12 ** 1.5)
    assert sim.beaufort_to_ms(12) > 32.6                                # Orkan ab 32,7 m/s


def test_wind_pressure_and_exposure(model):
    calm = sim.simulate_wind(model.buildings, 270, 0)
    storm = sim.simulate_wind(model.buildings, 270, 10)
    assert storm.kpis["max_pressure_kn_m2"] > calm.kpis.get("max_pressure_kn_m2", 0)
    assert 0 <= storm.building_exposure.min() and storm.building_exposure.max() <= 1
    # Winddruck w = ½ ρ v² c_pe bei voller Exposition ist die Obergrenze
    v_top = sim.beaufort_to_ms(10) * (model.buildings["height_m"].max() / 10) ** sim.WIND_PROFILE_EXPONENT
    upper = 0.5 * sim.AIR_DENSITY * v_top ** 2 * sim.PRESSURE_COEFF / 1000
    assert storm.kpis["max_pressure_kn_m2"] <= upper * 1.01


def test_ground_wind_field(model):
    heights = model.buildings["height_m"].to_numpy(float)
    field = sim.wind_field(model.raster, heights, 270, 9, iterations=150)
    assert np.all(field.speed[field.solid] == 0)                        # in Gebäuden weht kein Wind
    assert field.kpis["free_ped_ms"] == pytest.approx(
        sim.beaufort_to_ms(9) * (sim.PEDESTRIAN_HEIGHT_M / 10) ** sim.WIND_PROFILE_EXPONENT)
    calm = sim.wind_field(model.raster, heights, 270, 0, iterations=50)
    assert calm.kpis["dangerous_share"] == 0
