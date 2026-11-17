"""Methoden & Quellen: wie TERRA-Sim rechnet und worauf es sich stützt.

Die Seite ist auch ohne Projekt erreichbar. Inhalte kommen aus
``modules/methods.py`` (Rechenwege) und ``modules/sources.py`` (Quellen).
"""

from __future__ import annotations

import streamlit as st

from modules.methods import METHODS
from modules.sources import KIND_NAMES, SOURCES, bibtex
from views.common import KIND_ICONS, card, kpi_row, page_header, render_method

TABS = [("model", "🏙️ 3D-Modell"), ("flood", "🌊 Hochwasser"), ("rain", "🌧️ Starkregen"), ("wind", "💨 Starkwind"),
        ("quake", "🫨 Erdbeben"), ("tornado", "🌪️ Tornado"), ("kaiju", "👾 Kaiju"), ("alien", "🛸 Aliens")]


def _used_in() -> dict[str, list[str]]:
    labels = dict(TABS)
    used: dict[str, list[str]] = {}
    for key, method in METHODS.items():
        for source in method.source_keys:
            used.setdefault(source, []).append(labels[key].split(" ", 1)[1])
    return used


def render():
    page_header("Methoden & Quellen", "Wie TERRA-Sim rechnet – Schritt für Schritt mit Formeln – und auf welche "
                                      "Fachliteratur, Normen und Daten sich jede Analyse stützt.")
    counts = {kind: sum(s.kind == kind for s in SOURCES.values()) for kind in KIND_NAMES}
    c = kpi_row(4)
    c[0].metric("Quellen insgesamt", len(SOURCES))
    c[1].metric("Fachliteratur", counts["paper"])
    c[2].metric("Normen, Richtlinien, Skalen", counts["norm"])
    c[3].metric("Daten und Dienste", counts["data"])

    with card("mint"):
        st.markdown("**So ist TERRA-Sim aufgebaut**")
        st.markdown(
            "TERRA-Sim ist eine **heuristische Ersteinschätzung** für Entwurf und Lehre: einfache, nachvollziehbare "
            "Verfahren statt aufwendiger Hydraulik- oder CFD-Simulationen. Damit das ehrlich bleibt, legt jede "
            "Analyse ihren Rechenweg offen:\n\n"
            "- 📚 **Fachliteratur**, 📏 **Normen und Skalen** und 🗂️ **Daten** sind als Quelle angegeben – mit Link "
            "zur DOI oder zum Dienst.\n"
            "- ⚙️ **Annahmen**, die TERRA-Sim selbst setzt (z. B. Geschosshöhe 3 m), stehen getrennt davon.\n"
            "- **Grenzen** sagen, wofür das Verfahren nicht reicht.\n\n"
            "Dieselben Angaben stehen auf jeder Analyseseite unter „🔬 Methode & Quellen“. Im Code liegen sie in "
            "`modules/methods.py` und `modules/sources.py`.")
        st.download_button("Alle Quellen als BibTeX (.bib)", bibtex(), file_name="terra-sim-quellen.bib",
                           mime="application/x-bibtex", icon=":material/download:",
                           help="Für LaTeX, Zotero, Citavi oder Word-Literaturverwaltung")

    st.subheader("Rechenwege der Analysen")
    for tab, (key, _) in zip(st.tabs([label for _, label in TABS]), TABS):
        with tab, card():
            st.markdown(f"#### {METHODS[key].title}")
            render_method(key)

    st.subheader("Alle Quellen")
    with card():
        query = st.text_input("Suchen", placeholder="z. B. Erdbeben, DWD, Eurocode, 2006 …",
                              label_visibility="collapsed")
        kinds = st.pills("Art", list(KIND_NAMES), format_func=lambda k: f"{KIND_ICONS[k]} {KIND_NAMES[k]}",
                         selection_mode="multi", default=list(KIND_NAMES), label_visibility="collapsed")
        used = _used_in()
        for kind, name in KIND_NAMES.items():
            if kind not in (kinds or []):
                continue
            rows = [s for s in SOURCES.values() if s.kind == kind
                    and (not query or query.lower() in (s.reference + " " + " ".join(used.get(s.key, []))).lower())]
            if not rows:
                continue
            st.markdown(f"**{KIND_ICONS[kind]} {name}**")
            lines = []
            for s in sorted(rows, key=lambda s: s.reference.lower()):
                link = f" [{s.link.replace('https://', '')}]({s.link})" if s.link else ""
                where = f" — *genutzt in: {', '.join(used[s.key])}*" if s.key in used else ""
                lines.append(f"- {s.reference}{link}{where}")
            st.markdown("\n".join(lines))
