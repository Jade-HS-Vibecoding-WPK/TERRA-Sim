"""Modul D: Erdbeben (makroseismische Methode nach EMS-98)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from views.common import method_card

from modules.hazards import CLASS_NAMES, collapse_scale
from modules.viewer_webgpu import scene as vscene
from views.common import (RADIO_OPTIONS, damage_colors, damage_legend, damage_tooltips, no_buildings,
                          num, page_header, scene_for, show_scene)
from views.common import current_quake
from views.common import card, facts_html, kpi_row, odds_row, official_quake_zone

PRESETS = {
    "Spürbar · Mw 4,5 in 20 km": (4.5, 20),
    "Wie Roermond 1992 · Mw 5,3 in 15 km": (5.3, 15),
    "Stark · Mw 6,0 in 10 km": (6.0, 10),
    "Extrem · Mw 7,0 in 10 km": (7.0, 10),
}
INTENSITY_NAMES = ["", "nicht fühlbar", "kaum bemerkbar", "schwach", "deutlich", "stark",
                   "leichte Gebäudeschäden", "Gebäudeschäden", "schwere Gebäudeschäden", "zerstörend",
                   "sehr zerstörend", "verwüstend", "vollständig verwüstend"]
ROMAN = ["0", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"]


def _apply(magnitude: float, distance: int):
    st.session_state.quake_mw = magnitude
    st.session_state.quake_dist_km = distance


def intensity_label(intensity: float) -> str:
    i = int(min(12, max(1, round(intensity))))
    return f"{ROMAN[i]} – {INTENSITY_NAMES[i]}"


SUBSOIL = {"R": "Fels oder felsartiger Untergrund",
           "T": "Übergangsbereich, flache Sedimentbecken",
           "S": "tiefe Beckenstruktur mit mächtigen Sedimenten"}


def _zone_card(zone):
    """Amtliche Erdbebenzone und Untergrundklasse am Ort (GFZ, DIN 4149)."""
    with card("mint"):
        st.markdown("**Erdbebenzone am Standort**")
        items = [("Erdbebenzone", str(zone["zone"]) if zone["zone"] is not None else "keine",
                  "Skala 0–3; außerhalb: sehr geringe Gefährdung")]
        if zone.get("subsoil"):
            items.append(("Untergrundklasse", zone["subsoil"], SUBSOIL.get(zone["subsoil"])))
        items.append(("Ort", zone["place"], zone.get("postcode") or None))
        st.html(facts_html(items))
        st.caption("Quelle: GFZ Potsdam, Erdbebenzonen nach DIN 4149 – bezogen auf die Ortsmitte.")


def render():
    from views.navigation import require_project

    model = require_project()
    page_header("Erdbeben", "Wie stark bebt es am Standort, und welche Gebäude werden beschädigt? "
                            "Makroseismische Methode nach der Europäischen Skala EMS-98.")
    b = model.buildings

    zone = official_quake_zone(model)
    odds_row(model, "quake", "Chance, dass am Standort mindestens die eingestellte Intensität erreicht wird.",
             side=(lambda: _zone_card(zone)) if zone else None)

    method_card("quake")

    left, right = st.columns([1, 2.6], gap="large")
    with left:
        with card():
            st.markdown("**Szenario**")
            for label, (mw, dist) in PRESETS.items():
                st.button(label, key=f"quake_{label}", width="stretch", on_click=_apply, args=(mw, dist))
            st.caption("In Deutschland sind Beben bis etwa Mw 6 möglich – am ehesten am Niederrhein, "
                       "in der Schwäbischen Alb, im Oberrheingraben und im Vogtland.")
        with card():
            st.slider("Magnitude (Mw)", 3.0, 8.0, step=0.1, format="%.1f", key="quake_mw")
            st.slider("Entfernung zum Epizentrum", 1, 150, format="%d km", key="quake_dist_km")
            st.radio("Untergrund", RADIO_OPTIONS["quake_soil"], key="quake_soil",
                     help="Weicher Untergrund (z. B. Flussauen, Marsch) verstärkt die Erschütterung.")
        result = current_quake(model)
        k = result.kpis
        st.caption(f"Intensität am Standort **{intensity_label(k['intensity'])}** "
                   f"(im Epizentrum {intensity_label(k['epicentral_intensity'])}), "
                   f"Bodenbeschleunigung ca. {num(k['pga_g'], 2)} g.")

    with right:
        c = kpi_row(4)
        c[0].metric(f"Beschädigt (von {k['buildings_total']})", num(k["damaged"]),
                    help="Schadensgrad 1 oder mehr")
        c[1].metric("Schwer beschädigt", num(k["heavy"]), help="Schadensgrad 3 oder mehr: Risse in tragenden Wänden")
        c[2].metric("Nicht bewohnbar", num(k["unusable"]), help="Schadensgrad 4–5: Teileinsturz oder Einsturz")
        c[3].metric("Intensität (EMS-98)", ROMAN[int(min(12, max(1, round(k['intensity']))))])
        scene = scene_for(model, colors=damage_colors(result.damage),
                          tips=damage_tooltips(model, result.damage),
                          hazard=vscene.hazard("quake", intensity=k["intensity"]),
                          building_scale=vscene.building_scale(collapse_scale(result.damage)))
        show_scene(scene, key="scene_quake", height=640)
        st.html(damage_legend())

    if no_buildings(model):
        return
    with st.expander("Wie verletzbar sind die Gebäude? (Verletzbarkeitsklassen)"):
        classes = result.extra["classes"]
        table = pd.DataFrame([
            {"Klasse": c, "Bauweise (geschätzt)": CLASS_NAMES[c], "Gebäude": int((classes == c).sum()),
             "Mittlerer Schadensgrad": round(float(result.damage[classes == c].mean()), 1)}
            for c in CLASS_NAMES if (classes == c).any()])
        st.dataframe(table, hide_index=True)
        st.caption("OpenStreetMap kennt meist weder Baujahr noch Bauweise. Die Klasse wird deshalb aus "
                   "Gebäudetyp und Geschosszahl geschätzt; Geschosszahl, Grundrissform und Lage im Block "
                   "(Mittel- oder Eckhaus) verändern die Verletzbarkeit zusätzlich.")
