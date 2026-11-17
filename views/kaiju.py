"""Modul F: Kaiju-Angriff (Planspiel mit einem Riesenmonster)."""

from __future__ import annotations

import streamlit as st

from views.common import method_card

from modules.hazards import collapse_scale
from modules.viewer_webgpu import scene as vscene
from views.common import (damage_colors, damage_legend, damage_tooltips, legend_ramp, no_buildings, num,
                          page_header, scene_for, scene_origin, show_scene, wind_direction_label)
from views.common import current_kaiju
from views.common import card, facts_html, kpi_row, odds_row

PRESETS = {"Jungtier · 30 m": 30, "Ausgewachsen · 80 m": 80, "Titan · 150 m": 150}


def _apply(height: int):
    st.session_state.kaiju_height = height


def _how_card():
    """So entsteht die Kaiju-Wahrscheinlichkeit: Fossilbericht, Knochenstatik, Schneise."""
    from modules.likelihood import (BONE_LIMIT_T, KAIJU_RAMPAGE_KM, LAND_LIFE_YEARS, LARGEST_LAND_ANIMAL_T,
                                    big_number, kaiju_mass_t, kaiju_rate_world)
    h = int(st.session_state.kaiju_height)
    mass = kaiju_mass_t(h)
    with card("mint"):
        st.markdown("**So entsteht die Zahl**")
        st.html(facts_html([
            ("Schwerstes Landtier aller Zeiten", f"≈ {num(LARGEST_LAND_ANIMAL_T)} t",
             f"Sauropoden; Knochen halten bis ≈ {num(BONE_LIMIT_T)} t (Hokkanen 1986)"),
            (f"Dieses Kaiju ({h} m)", f"≈ {big_number(mass)} t",
             f"rund {num(mass / BONE_LIMIT_T)}-mal zu schwer für Knochen"),
            ("Kaijus weltweit", f"höchstens 1 in {big_number(1 / kaiju_rate_world())} Jahren",
             f"0 Fälle in {big_number(LAND_LIFE_YEARS)} Jahren Landleben → „Rule of Three“"),
        ]))
        st.caption(f"Dann muss es noch genau dieses Gebiet treffen: Schneise {KAIJU_RAMPAGE_KM:.0f} km lang "
                   "(Annahme wie im Film), verteilt auf die Landfläche der Erde. Zum Vergleich: Das Universum ist "
                   "erst 13,8 Mrd. Jahre alt. Quellen: Hokkanen (1986), J. Theor. Biol. "
                   "118:491; Hanley & Lippman-Hand (1983), JAMA 249:1743.")


def render():
    from views.navigation import require_project

    model = require_project()
    page_header("Kaiju-Angriff", "Planspiel: Ein Riesenmonster läuft quer durch das Gebiet. Welche "
                                 "Gebäude liegen in der Schneise, und wo bieten hohe Häuser Deckung?")

    odds_row(model, "kaiju", "Obergrenze: Chance, dass ein Kaiju dieser Größe genau durch dieses Gebiet läuft.",
             side=_how_card)

    method_card("kaiju")

    left, right = st.columns([1, 2.6], gap="large")
    with left:
        with card():
            st.markdown("**Monster**")
            for label, height in PRESETS.items():
                st.button(label, key=f"kaiju_{label}", width="stretch", on_click=_apply, args=(height,))
        with card():
            st.slider("Größe", 20, 150, step=5, format="%d m", key="kaiju_height")
            st.slider("Laufrichtung (wohin es läuft)", 0, 355, step=5, format="%d°", key="kaiju_heading")
            st.slider("Seitlicher Versatz des Wegs", -400, 400, step=10, format="%d m", key="kaiju_offset")
        with card():
            st.markdown("**Kampf**")
            st.slider("Laserstrahlen aus den Augen", 0, 20, key="kaiju_lasers",
                      help="Treffen zufällige Ziele neben dem Weg – gleiche Einstellungen, gleicher Ablauf.")
            st.slider("Angreifende Hubschrauber", 0, 10, key="kaiju_helis",
                      help="Sie umkreisen das Monster und feuern Raketen. Etwa 60 % werden abgeschossen und "
                           "stürzen in die Stadt, Fehlschüsse treffen Gebäude.")
        result = current_kaiju(model)
        k = result.kpis
        h = k["height_m"]
        st.caption(f"Läuft nach **{wind_direction_label(st.session_state.kaiju_heading)}**. Schneise "
                   f"(Füße und Körper) {num(k['swath_m'])} m breit, Schwanz und Arme reichen "
                   f"{num(0.45 * h)} m weit, die Schritte erschüttern bis {num(0.8 * h)} m.")
        st.caption("Ein Spaß-Szenario für die Lehre – es zeigt, wie man eine Gefahr mit Weg, Reichweite "
                   "und Schadensstufen modelliert. Das Monster ist eine eigene Figur.")

    with right:
        c = kpi_row(4)
        c[0].metric(f"Zerstört (von {k['buildings_total']})", num(k["destroyed"]))
        c[1].metric("Schwer beschädigt", num(k["heavy"] - k["destroyed"]), help="Schadensgrad 3–4")
        c[2].metric("BGF nicht nutzbar", f"{num(k['gfa_unusable_m2'])} m²",
                    help="Bruttogeschossfläche der Gebäude mit Schadensgrad 4–5 (geschätzt)")
        c[3].metric("Hubschrauber abgeschossen", f"{k['helis_down']} von {k['helis']}" if k["helis"] else "–",
                    help=f"{k['laser_shots']} Laserschüsse; {k['taller_buildings']} Gebäude sind höher als "
                         "das Monster und bieten Deckung.")
        origin = scene_origin(model)
        extent = max(model.raster.nx, model.raster.ny) * model.raster.cell
        scene = scene_for(model, colors=damage_colors(result.damage), tips=damage_tooltips(model, result.damage),
                          overlay=result.overlay, ramp="heat", hazard=vscene.hazard("kaiju"),
                          monster=vscene.monster(result.extra["center"], origin, h,
                                                 st.session_state.kaiju_heading, travel_m=1.3 * extent,
                                                 events=result.extra["events"], helis=k["helis"]),
                          building_scale=vscene.building_scale(collapse_scale(result.damage)))
        show_scene(scene, key="scene_kaiju", height=640)
        st.html(legend_ramp("heat", "Erschütterung", "Fußabdruck", "Weg des Monsters"))
        st.html(damage_legend())
    no_buildings(model)
