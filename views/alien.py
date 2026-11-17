"""Modul G: Alien-Invasion (Planspiel) – UFOs holen Menschen aus dem Gebiet."""

from __future__ import annotations

import streamlit as st

from modules.hazards import MOTHERSHIP_SIZE_M
from modules.viewer_webgpu import scene as vscene
from views.common import GREY, current_alien, num, page_header, scene_for, scene_origin, show_scene
from views.common import card, facts_html, kpi_row, odds_row

PRESETS = {"Erkundung · 1 kleines UFO": (1, 20, 50), "Invasion · 3 UFOs": (3, 30, 60),
           "Mutterschiff · 1 riesiges UFO": (1, 80, 120)}


def _apply(count: int, size: int, height: int):
    st.session_state.alien_ufos = count
    st.session_state.alien_size = size
    st.session_state.alien_height = height


def _how_card():
    """So entsteht die Alien-Wahrscheinlichkeit (Hanson et al. 2021)."""
    from modules.likelihood import ALIEN_ARRIVAL_RANGE, ALIEN_ARRIVAL_YEARS, NATURAL_EXTINCTION_YEARS, big_number
    low, high = ALIEN_ARRIVAL_RANGE
    with card("mint"):
        st.markdown("**So entsteht die Zahl**")
        st.html(facts_html([
            ("Erstkontakt mit expandierenden Aliens", f"in ≈ {big_number(ALIEN_ARRIVAL_YEARS)} Jahren",
             f"Spanne {big_number(low)} – {big_number(high)} Jahre"),
            ("Betroffen", "die ganze Erde", "wer sich so ausbreitet, übernimmt alles, was er erreicht"),
            ("Zum Vergleich", f"1 zu {big_number(NATURAL_EXTINCTION_YEARS)} pro Jahr",
             "alle natürlichen Katastrophen zusammen, die die Menschheit auslöschen könnten (Obergrenze)"),
        ]))
        st.caption("Das Modell erklärt, warum die Menschheit so früh in der Geschichte des Universums auftaucht: "
                   "Laute, sich ausbreitende Zivilisationen füllen das All und lassen später keinen Platz mehr. "
                   "Quellen: Hanson, Martin, McCarter & Paulson (2021), Astrophysical Journal 922:182; "
                   "Snyder-Beattie, Ord & Bonsall (2019), Scientific Reports 9:11054.")


def render():
    from views.navigation import require_project

    model = require_project()
    page_header("Alien-Invasion", "Planspiel: UFOs kreuzen über dem Gebiet, bleiben stehen und holen mit dem "
                                  "Traktorstrahl Menschen nach oben. Ein Mutterschiff saugt auch Gebäude ein.")
    ss = st.session_state
    raster = model.raster
    extent = max(raster.nx, raster.ny) * raster.cell

    odds_row(model, "alien", "Chance, dass sich ausbreitende Aliens die Erde erreichen – nach einem "
                             "astrophysikalischen Modell, nicht nach UFO-Sichtungen.", side=_how_card)

    left, right = st.columns([1, 2.6], gap="large")
    with left:
        with card():
            st.markdown("**Szenario**")
            for label, values in PRESETS.items():
                st.button(label, key=f"alien_{label}", width="stretch", on_click=_apply, args=values)
        with card():
            st.slider("Anzahl UFOs", 1, 5, key="alien_ufos")
            st.slider("Durchmesser", 10, 80, step=5, format="%d m", key="alien_size")
            st.slider("Flughöhe", 25, 150, step=5, format="%d m", key="alien_height")
        result = current_alien(model)
        k = result.kpis
        beam = k["beam_m"]
        if k["mothership"]:
            st.caption(f"**Mutterschiff:** Es fliegt {len(result.extra['routes'][0])} Haltepunkte an und saugt "
                       f"dort jedes Gebäude ein, dessen Mitte im {num(beam)} m breiten Strahl liegt und das "
                       f"niedriger ist als {num(0.7 * ss.alien_height)} m. Nach jeder Runde stehen die Gebäude "
                       "wieder da.")
        else:
            st.caption(f"Jedes UFO fliegt 5 Sekunden, bleibt dann stehen und strahlt 4 Sekunden lang einen Kreis "
                       f"von {num(beam)} m Durchmesser ab. Ab {num(MOTHERSHIP_SIZE_M)} m Durchmesser wird es "
                       "zum Mutterschiff und saugt auch Gebäude ein.")
        st.caption("Wer in der Nähe ist, rennt weg – wer im Strahl steht, schwebt nach oben; der Zähler unten "
                   "rechts in der 3D-Ansicht zählt mit. Mit „Nik folgen“ sieht man, ob Nik entkommt.")

    with right:
        c = kpi_row(4)
        c[0].metric("UFOs", num(ss.alien_ufos))
        c[1].metric("Strahl-Durchmesser", f"{num(beam)} m")
        c[2].metric(f"Gebäude eingesaugt (von {k['buildings_total']})", num(k["lifted"]) if k["mothership"] else "–",
                    help=f"{num(k['lifted_gfa_m2'])} m² Geschossfläche (geschätzt)" if k["mothership"]
                    else f"Nur ein Mutterschiff (ab {num(MOTHERSHIP_SIZE_M)} m) saugt Gebäude ein")
        c[3].metric("Menschen im Gebiet", num(ss.people_count),
                    help="Einstellbar in der Seitenleiste unter „Darstellung“")
        scene = scene_for(model, colors=[GREY] * len(model.buildings),
                          overlay=result.overlay, ramp="water",
                          ufos=vscene.ufos(ss.alien_ufos, ss.alien_size, ss.alien_height, extent,
                                           routes=result.extra["routes"], origin=scene_origin(model)),
                          hazard=vscene.hazard("alien"))
        show_scene(scene, key="scene_alien", height=640)
        if ss.people_count == 0:
            st.info("Es sind keine Menschen im Gebiet – die UFOs finden niemanden. "
                    "Die Anzahl lässt sich in der Seitenleiste einstellen.")
