"""Seitenstruktur und Seitenleiste.

Ablauf wie bei Planungswerkzeugen (z. B. Autodesk Forma): Zuerst wird ein
Projektgebiet festgelegt und geladen. Erst danach werden Übersicht, Klima,
3D-Modell und die Analysen freigeschaltet – vorher sind sie in der
Seitenleiste ausgegraut.
"""

from __future__ import annotations

import html

import streamlit as st

from modules.map_selector import bbox_size_m
from views.common import get_model, num, project_file

PAGES: dict = {}

SECTIONS = [
    ("Standort", ["overview", "climate", "model"]),
    ("Analysen", ["flood", "rain", "wind"]),
]


def register() -> dict:
    """Legt alle Seiten an (bei jedem Durchlauf neu, das ist bei Streamlit üblich)."""
    from views import climate, flood, model3d, overview, rain, setup, wind

    PAGES.clear()
    PAGES.update({
        "setup": st.Page(setup.render, title="Projekt anlegen", icon=":material/add_location_alt:",
                         url_path="projekt", default=True),
        "overview": st.Page(overview.render, title="Übersicht", icon=":material/dashboard:",
                            url_path="uebersicht"),
        "climate": st.Page(climate.render, title="Klima am Standort", icon=":material/partly_cloudy_day:",
                           url_path="klima"),
        "model": st.Page(model3d.render, title="3D-Modell & Export", icon=":material/view_in_ar:",
                         url_path="modell"),
        "flood": st.Page(flood.render, title="Hochwasser", icon=":material/flood:",
                         url_path="hochwasser"),
        "rain": st.Page(rain.render, title="Starkregen", icon=":material/rainy:",
                        url_path="starkregen"),
        "wind": st.Page(wind.render, title="Starkwind", icon=":material/air:",
                        url_path="starkwind"),
    })
    return PAGES


def require_project():
    """Am Anfang jeder Projektseite: ohne Projekt zurück zur Projekt-Seite."""
    model = get_model()
    if model is None:
        st.switch_page(PAGES["setup"])
    return model


def close_project():
    for key in ("model", "export"):
        st.session_state.pop(key, None)


def sidebar():
    model = get_model()
    with st.sidebar:
        if model is not None:
            lat, lon = model.center
            width, height = bbox_size_m(model.bbox)
            climate = "Klimadaten: " + ("Meteostat" if model.climate_ok else "nicht verfügbar")
            st.html(
                f'<div class="terra-project"><div class="name">{html.escape(model.name)}</div>'
                f'<div class="meta">{lat:.4f}° N, {lon:.4f}° E<br>'
                f'{num(width)} × {num(height)} m · {len(model.buildings)} Gebäude<br>'
                f'Gelände: {html.escape(model.dem.source)} · {climate}</div></div>')
            left, right = st.columns(2)
            left.download_button("Speichern", project_file(model), file_name=_file_name(model.name),
                                 mime="application/json", icon=":material/save:",
                                 help="Projektdatei (.json) mit Gebiet und Einstellungen herunterladen",
                                 width="stretch")
            if right.button("Schließen", icon=":material/close:", width="stretch",
                            help="Projekt schließen und ein neues Gebiet wählen"):
                close_project()
                st.switch_page(PAGES["setup"])
        else:
            st.page_link(PAGES["setup"], label="Projekt anlegen", icon=":material/add_location_alt:")

        locked = model is None
        for title, keys in SECTIONS:
            st.html(f'<div class="terra-nav-title">{title}</div>')
            for key in keys:
                page = PAGES[key]
                label = f"{page.title}" + ("  🔒" if locked else "")
                st.page_link(page, label=label, icon=page.icon, disabled=locked)
        if locked:
            st.html('<div class="terra-locked-hint">Wird freigeschaltet, sobald ein Projektgebiet '
                    'angelegt und geladen ist.</div>')

        st.divider()
        st.caption("Daten: © OpenStreetMap-Mitwirkende · Open-Elevation / Open-Meteo · "
                   "Meteostat. Heuristische Ersteinschätzung, kein Gutachten.")


def _file_name(name: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name.strip()) or "projekt"
    return f"{safe.lower()}.terrasim.json"
