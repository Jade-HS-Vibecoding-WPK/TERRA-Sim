"""Quellen und Rechenwege (modules/sources.py, modules/methods.py) – passen sie zum Code?"""

import re

import pytest

from modules import hazards, likelihood, osm_fetcher, simulator
from modules.methods import METHODS, check
from modules.sources import SOURCES, bibtex, cite


def test_every_cited_source_exists():
    assert check() == []


def test_sources_are_complete():
    for s in SOURCES.values():
        assert s.kind in {"paper", "norm", "data"}, s.key
        assert s.authors and s.title and s.venue and s.year, s.key
        if s.doi:
            assert s.doi.startswith("10."), s.key
        assert s.link.startswith("https://") or not s.link, s.key


def test_every_source_is_used():
    used = {k for m in METHODS.values() for k in m.source_keys}
    assert set(SOURCES) - used == set()


def test_bibtex_has_one_entry_per_source():
    text = bibtex()
    keys = re.findall(r"^@\w+\{([^,]+),", text, flags=re.M)
    assert sorted(keys) == sorted(SOURCES)
    assert text.count("{") == text.count("}")


def test_cite():
    assert cite("lagomarsino2006") == "Lagomarsino & Giovinazzi (2006)"
    assert cite("wald1999") == "Wald et al. (1999)"


def test_every_method_has_steps_and_sources():
    for key, m in METHODS.items():
        assert m.steps, key
        assert m.source_keys, key


def _text(key):
    m = METHODS[key]
    return " ".join([m.summary, *(s.text + " " + s.formula for s in m.steps), *m.assumptions, *m.limits])


def _de(value) -> str:
    return f"{value}".replace(".", ",")


@pytest.mark.parametrize("key, expected", [
    ("model", [f"× {osm_fetcher.STOREY_HEIGHT_M:.0f} m"]),
    ("rain", [f"Dach {_de(simulator.RUNOFF_COEFF[simulator.LC_BUILDING])}",
              f"Straße {_de(simulator.RUNOFF_COEFF[simulator.LC_STREET])}",
              f"Sonstiges {_de(simulator.RUNOFF_COEFF[simulator.LC_OTHER])}",
              f"Grün {_de(simulator.RUNOFF_COEFF[simulator.LC_GREEN])}"]),
    ("wind", [f"ρ = {_de(simulator.AIR_DENSITY)} kg/m³", f"+{_de(simulator.PRESSURE_COEFF)}",
              f"α = {_de(simulator.WIND_PROFILE_EXPONENT)}", f"{simulator.DANGEROUS_WIND_MS:.0f} m/s"]),
    ("quake", ["Q = 2,3", "k = 2,8", "6{,}25", "13{,}1"]),
    ("tornado", [", ".join(f"EF{i} {v}" for i, v in enumerate(hazards.EF_GUST_MS)) + " m/s",
                 f"({hazards.TRANSLATION_MS:.0f} m/s)"]),
    ("kaiju", [f"{likelihood.KAIJU_RAMPAGE_KM:.0f} km", f"{likelihood.BONE_LIMIT_T:.0f} t"]),
])
def test_method_texts_match_code_constants(key, expected):
    """Wer eine Konstante im Code ändert, muss den Rechenweg in methods.py mit ändern."""
    text = _text(key)
    for snippet in expected:
        assert snippet in text, f"{key}: „{snippet}“ fehlt in modules/methods.py"


def test_quake_formula_constants_match_code():
    import inspect
    source = inspect.getsource(hazards.simulate_earthquake)
    assert "6.25 * v - 13.1" in source and "ductility: float = 2.3" in source
    assert inspect.signature(likelihood.quake_return_period).parameters["slope"].default == 2.8
