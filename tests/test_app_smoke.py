"""Rauchtest: Jede Seite der App läuft mit dem Offline-Testgebiet ohne Fehler durch.

Streamlits ``AppTest`` führt die Seite wie im Browser aus (Widgets, Zwischenspeicher,
Sitzungszustand) – nur ohne Browser. Die amtlichen Dienste sind durch feste Testwerte
ersetzt (tests/fixtures.py), es braucht also kein Netz.
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent

ANALYSES = ["model3d", "flood", "rain", "wind", "earthquake", "tornado", "kaiju", "alien"]
PAGES = ["setup", "overview", "climate", *ANALYSES, "literature"]


def _page_script():
    """Wie app.py, aber mit Testgebiet und genau einer Seite (läuft als eigenes Streamlit-Skript)."""
    import os
    import sys

    sys.path.insert(0, os.environ["TERRA_TEST_ROOT"])
    import streamlit as st

    from tests.fixtures import demo_model, install_offline

    install_offline()
    import views.common as vc
    from views import navigation

    vc.load_style()
    vc.reset_layout()
    for key, default in vc.SETTINGS_DEFAULTS.items():
        st.session_state[key] = st.session_state.get(key, default)
    page_name = os.environ["TERRA_TEST_PAGE"]
    if page_name not in ("setup", "literature") and "model" not in st.session_state:
        st.session_state.model = demo_model()
    pages = navigation.register()
    st.navigation(list(pages.values()), position="hidden")
    navigation.sidebar()
    __import__(f"views.{page_name}", fromlist=["render"]).render()


def _run(page: str, monkeypatch) -> AppTest:
    monkeypatch.setenv("TERRA_TEST_ROOT", str(ROOT))
    monkeypatch.setenv("TERRA_TEST_PAGE", page)
    app = AppTest.from_function(_page_script, default_timeout=300)
    app.run()
    return app


@pytest.mark.parametrize("page", PAGES)
def test_page_renders_without_errors(page, monkeypatch):
    app = _run(page, monkeypatch)
    assert not app.exception, "\n".join(str(e.value) for e in app.exception)


@pytest.mark.parametrize("page", ANALYSES)
def test_analysis_pages_show_method_and_sources(page, monkeypatch):
    app = _run(page, monkeypatch)
    labels = [e.label for e in app.expander]
    assert any("Methode & Quellen" in label for label in labels), labels


def test_official_data_appear_in_the_app(monkeypatch):
    """Mit den Testwerten: Hochwasserkarte trifft Gebäude, Wahrscheinlichkeiten sind berechnet."""
    app = _run("flood", monkeypatch)
    html = " ".join(str(getattr(e, "proto", "")) for e in app.get("html"))
    assert "HQ100" in html and "Gebäude" in html
    app = _run("wind", monkeypatch)
    html = " ".join(str(getattr(e, "proto", "")) for e in app.get("html"))
    assert "Wie oft?" in html and "Chance in 30 Jahren" in html
