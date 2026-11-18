"""Wiederkehrzeiten und Wahrscheinlichkeiten (modules/likelihood.py)."""

import math

import numpy as np
import pytest

from modules import likelihood as lk


# --------------------------------------------------------------------------- Darstellung

def test_describe_100_years():
    d = lk.describe(100)
    assert d["T"] == 100
    assert d["p_year"] == pytest.approx(0.01)
    assert d["p_life"] == pytest.approx(1 - 0.99 ** 30)           # 26 %
    assert d["text"] == "etwa alle 100 Jahre"
    assert d["level"] == "warn"


@pytest.mark.parametrize("T, level", [(5, "risk"), (30, "risk"), (31, "warn"), (300, "warn"), (301, "ok")])
def test_describe_levels(T, level):
    assert lk.describe(T)["level"] == level


def test_describe_vague_above_10000_unless_exact():
    assert lk.describe(20_000)["text"] == "seltener als alle 10.000 Jahre"
    assert lk.describe(1e9, exact=True)["text"] == "etwa alle 1 Mrd. Jahre"
    assert lk.describe(3.4e14, exact=True, bound=True)["text"] == "seltener als alle 340 Bio. Jahre"


@pytest.mark.parametrize("T", [None, 0, -5, math.inf, math.nan])
def test_describe_without_value(T):
    assert lk.describe(T)["level"] == "none"


def test_tiny_probabilities_stay_exact():
    """1 − (1 − p)^n darf für winzige p nicht auf 0 runden (Kaiju!)."""
    d = lk.describe(1e15, exact=True)
    assert d["p_life"] == pytest.approx(30e-15, rel=1e-6)


@pytest.mark.parametrize("p, text", [
    (None, "–"), (0, "0 %"), (1.0, "fast sicher"), (0.26, "26 %"), (0.042, "4,2 %"), (0.0048, "0,48 %"),
    (3e-8, "0,000003 %"), (8.9e-14, "0,0000000000089 %"),
])
def test_percent(p, text):
    assert lk.percent(p) == text


@pytest.mark.parametrize("n, text", [(87_000, "87.000"), (3.3e7, "33 Mio."), (1.2e9, "1,2 Mrd."),
                                     (2e9, "2 Mrd."), (3.4e14, "340 Bio.")])
def test_big_number(n, text):
    assert lk.big_number(n) == text


def test_one_in():
    assert lk.one_in(3e-8) == "1 zu 33 Mio."
    assert lk.one_in(None) == "–"


# --------------------------------------------------------------------------- Extremwertstatistik

def test_gumbel_fit_recovers_parameters():
    rng = np.random.default_rng(0)
    sample = rng.gumbel(loc=100.0, scale=10.0, size=20_000)
    mu, beta = lk.gumbel_fit(sample)
    assert mu == pytest.approx(100.0, rel=0.02)
    assert beta == pytest.approx(10.0, rel=0.03)


def test_gumbel_level_and_return_period_are_inverse():
    fit = (100.0, 10.0)
    for T in (2, 10, 50, 100, 1000):
        assert lk.gumbel_return_period(fit, lk.gumbel_level(fit, T)) == pytest.approx(T, rel=1e-9)


def test_gumbel_needs_enough_years():
    assert lk.gumbel_fit([100, 110, 120, 130]) is None
    assert lk.gumbel_return_period(None, 120) is None


def test_rain_return_period_log_interpolation_and_extrapolation():
    table = {1: 10.0, 10: 20.0, 100: 30.0}
    assert lk.rain_return_period(table, 20.0) == pytest.approx(10.0)
    assert lk.rain_return_period(table, 25.0) == pytest.approx(math.sqrt(10 * 100))   # logarithmisch mittig
    assert lk.rain_return_period(table, 40.0) == pytest.approx(1000.0)                # gleicher Anstieg weiter
    assert lk.rain_return_period(table, 5.0) < 1.0
    assert lk.rain_return_period({}, 20.0) is None


def test_rain_return_period_grows_with_depth():
    from tests.fixtures import kostra_table
    table = kostra_table(1440)
    periods = [lk.rain_return_period(table, d) for d in (40, 60, 80, 100, 150)]
    assert periods == sorted(periods)


# --------------------------------------------------------------------------- Erdbeben

def test_quake_zone_reference_intensity_is_475_years():
    for zone, intensity in lk.ZONE_INTENSITY_475.items():
        assert lk.quake_return_period_from_zone(zone, intensity) == pytest.approx(475.0)


def test_quake_stronger_shaking_is_rarer():
    assert lk.quake_return_period_from_zone(1, 7.5) > lk.quake_return_period_from_zone(1, 6.0)
    assert lk.quake_return_period_from_zone(3, 7.0) < lk.quake_return_period_from_zone(0, 7.0)
    assert lk.quake_return_period_from_zone("unbekannt", 7.0) is None


# --------------------------------------------------------------------------- Tornado, Kaiju, Aliens

def test_tornado_stronger_is_rarer_and_larger_area_is_hit_more_often():
    from modules.hazards import EF_PATH_WIDTH_M
    by_ef = [lk.tornado_return_period(ef, 500, EF_PATH_WIDTH_M) for ef in range(6)]
    assert by_ef == sorted(by_ef)
    assert lk.tornado_return_period(2, 1500, EF_PATH_WIDTH_M) < lk.tornado_return_period(2, 300, EF_PATH_WIDTH_M)


def test_kaiju_upper_bound():
    assert lk.kaiju_rate_world() == pytest.approx(3 / 370e6)            # Rule of Three
    T = lk.kaiju_return_period(500, 40)
    assert T > 1e12                                                     # länger als das Alter des Universums
    assert lk.kaiju_return_period(1500, 75) < T                         # größeres Gebiet, größeres Monster


def test_aliens_and_mass():
    assert lk.alien_return_period() == 1e9
    assert lk.kaiju_mass_t(4.0) == pytest.approx(8.0)
    assert lk.kaiju_mass_t(80) == pytest.approx(64_000)
