"""Übersicht als Bento-Grid: Projekt, Klima, Gefahren mit Wahrscheinlichkeit, Exporte."""

from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from views.common import (area_metrics, climate_info, current_alien, current_flood, current_kaiju, current_quake,
                          current_rain, current_tornado, current_wind, num, page_header, pill,
                          project_file, risk_level, wind_direction_label)
from views.common import card, kpi_row, odds_bar, odds_line, scenario_odds, tone_of
from modules.climate_loader import BEAUFORT_KMH
from modules.simulator import BEAUFORT_NAMES

REFERENCE_SHORT = {
    "Tiefster Geländepunkt im Gebiet": "dem tiefsten Geländepunkt",
    "Wasserspiegel der Gewässer im Gebiet": "dem Gewässerspiegel",
    "Meeresspiegel (0 m ü. NHN)": "Meeresspiegel",
}


def _tile(title: str, scenario: str, value: str, sub: str, level: str, status: str, page_key: str,
          probability: str = ""):
    """Bento-Kachel einer Analyse; Orange/Rot getönt, wenn es kritisch wird."""
    from views.navigation import PAGES

    with card(tone_of(level)):
        st.html(f'<div class="terra-tile-head"><span class="terra-tile-title">{html.escape(title)}</span>'
                f'{pill(status, level)}</div>'
                f'<div class="terra-tile-scenario">{html.escape(scenario)}</div>'
                f'<div class="terra-tile-value">{html.escape(value)}</div>'
                f'<div class="terra-tile-sub">{html.escape(sub)}</div>'
                + (f'<div class="terra-tile-prob">{probability}</div>' if probability else ""))
        st.page_link(PAGES[page_key], label="Analyse öffnen", icon=":material/arrow_forward:")


def _damage_tile(title: str, scenario: str, k: dict, page_key: str, probability: str = ""):
    share = k["heavy"] / max(1, k["buildings_total"])
    level, status = risk_level(share, warn=0.02, risk=0.15) if k["damaged"] else ("ok", "keine Schäden")
    _tile(title, scenario, f"{k['heavy']} von {k['buildings_total']} Gebäuden",
          f"schwer beschädigt · {k['destroyed']} zerstört · {k['damaged']} mit Schäden", level, status, page_key,
          probability)


def _results_table(model, flood, rain, wind, quake=None, tornado=None, kaiju=None) -> pd.DataFrame:
    """Gebäude mit allen Analyse-Ergebnissen (für den GeoJSON-Export)."""
    b = model.buildings_wgs
    table = b[["osm_id", "name", "building", "levels", "height_m", "height_source",
               "area_m2", "ground_m", "geometry"]].copy()
    table["hochwasser_tiefe_m"] = flood.building_depth.round(2)
    table["hochwasser_betroffen"] = flood.affected
    table["starkregen_tiefe_m"] = rain.building_depth.round(2)
    table["starkregen_betroffen"] = rain.affected
    table["wind_exposition"] = wind.building_exposure.round(2)
    for name, result in (("erdbeben", quake), ("tornado", tornado), ("kaiju", kaiju)):
        if result is not None:
            table[f"{name}_schadensgrad"] = result.grade
    table["ground_m"] = table["ground_m"].round(2)
    return table


def render():
    from views.navigation import PAGES, require_project

    model = require_project()
    page_header("Übersicht", "Das Projektgebiet auf einen Blick – Kennzahlen, Klima und die Gefahren mit den "
                             "zuletzt gewählten Einstellungen.")
    for note in st.session_state.pop("load_notes", []):
        st.warning(note)
    ss = st.session_state
    m = area_metrics(model)
    info = climate_info(model)
    lat, lon = model.center

    # ---- Reihe 1: Projekt (groß, dunkel) + Klima -----------------------------
    hero, climate = st.columns([1.55, 1], gap="medium")
    with hero:
        with card("dark"):
            st.html(f'<div style="font-size:.8rem;opacity:.85">Projektgebiet</div>'
                    f'<div style="font-size:1.7rem;font-weight:800;line-height:1.15">{html.escape(model.name)}</div>'
                    f'<div style="font-size:.85rem;opacity:.85;margin:.15rem 0 .5rem">{lat:.4f}° N, {lon:.4f}° E · '
                    f'Gelände: {html.escape(model.dem.source)}</div>')
            c = st.columns(4)
            c[0].metric("Fläche", f"{num(m['site_area_m2'] / 10_000, 1)} ha")
            c[1].metric("Gebäude", num(m["buildings"]))
            c[2].metric("GRZ", num(m["grz"], 2), help="Grundflächenzahl: bebaute Fläche / Gebietsfläche "
                        f"({num(m['footprint_m2'])} m² bebaut)")
            c[3].metric("GFZ", num(m["gfz"], 2), help="Geschossflächenzahl (geschätzt): Summe aller "
                        f"Geschossflächen / Gebietsfläche (BGF ca. {num(m['gfa_m2'])} m²)")
    with climate:
        with card("mint"):
            st.markdown("**Klima am Standort**")
            if info is None:
                st.caption(f"Keine Klimadaten verfügbar. {model.climate_error}")
            else:
                c = st.columns(2)
                c[0].metric("Jahresmittel", f"{num(info['temp_mean'], 1)} °C" if info["temp_mean"] is not None else "–")
                c[1].metric("Niederschlag", f"{num(info['prcp_year'])} mm" if info["prcp_year"] else "–",
                            help="pro Jahr")
                c[0].metric("Hauptwind", wind_direction_label(info["wind_dir_prevailing"])
                            if info["wind_dir_prevailing"] is not None else "–")
                c[1].metric("Sturmtage", f"{num(info['storm_days'], 1)} / Jahr" if info["storm_days"] is not None else "–",
                            help=f"Tage mit Böen ab {BEAUFORT_KMH[8]} km/h (Bft 9)")
                st.page_link(PAGES["climate"], label=f"Klimadaten {info['years']}", icon=":material/arrow_forward:")

    # ---- Reihe 2: kleine Kennzahl-Kacheln -------------------------------------
    known = (model.buildings["height_source"] != "Schätzung").mean() if m["buildings"] else 0
    c = kpi_row(6)
    c[0].metric("Mittlere Höhe", f"{num(m['mean_height_m'], 1)} m", help=f"Höchstes Gebäude: {num(m['max_height_m'], 1)} m")
    c[1].metric("Versiegelt", f"{m['sealed_share']:.0%}", help="Straßen und Dächer an der Landfläche")
    c[2].metric("Grünflächen", f"{m['green_share']:.0%}")
    c[3].metric("Wasserflächen", f"{m['water_share']:.0%}")
    c[4].metric("Geländehöhe", f"{num(m['elevation_min'], 1)}–{num(m['elevation_max'], 1)} m",
                help=f"Quelle: {model.dem.source}")
    c[5].metric("Höhen aus OSM", f"{known:.0%}", help="Anteil der Gebäude mit Höhen- oder Geschossangabe in "
                "OpenStreetMap; der Rest ist geschätzt.")

    # ---- Reihe 3–5: Gefahren als Bento-Kacheln ------------------------------
    st.subheader("Gefahren")
    st.caption("Ergebnis mit den Einstellungen, die zuletzt in der jeweiligen Analyse gewählt wurden. "
               "Grün = unkritisch, Orange = erhöhtes Risiko, Rot = hohes Risiko.")
    flood, base = current_flood(model)
    rain, rain_label = current_rain(model)
    wind, direction, beaufort = current_wind(model)
    quake, tornado, kaiju = current_quake(model), current_tornado(model), current_kaiju(model)
    alien = current_alien(model)
    odds = _odds(model)
    n = max(1, len(model.buildings))

    cols = st.columns([1.3, 1, 1], gap="medium")
    with cols[0]:
        k = flood.kpis
        level, status = risk_level(k["buildings_affected"] / n)
        reference = REFERENCE_SHORT.get(ss.flood_ref, ss.flood_ref)
        _tile("🌊 Hochwasser", f"Pegel +{num(ss.flood_gauge, 1)} m über {reference}",
              f"{k['buildings_affected']} von {k['buildings_total']} Gebäuden",
              f"{num(k['flooded_gfa_m2'])} m² BGF im Erdgeschoss überflutet", level, status, "flood",
              odds.get("flood", ""))
    with cols[1]:
        k = rain.kpis
        level, status = risk_level(k["buildings_affected"] / n, warn=0.1, risk=0.3)
        _tile("🌧️ Starkregen", rain_label, f"{k['buildings_affected']} von {k['buildings_total']} Gebäuden",
              f"mit Wasser ≥ 10 cm am Gebäude · max. {num(k['max_ponding_m'], 2)} m tief", level, status, "rain",
              odds.get("rain", ""))
    with cols[2]:
        k = wind.kpis
        share = k["facade_area_high_m2"] / k["facade_area_total_m2"] if k["facade_area_total_m2"] else 0
        level, status = risk_level(share, warn=0.03, risk=0.1) if beaufort >= 8 else ("ok", "unkritisch")
        _tile("💨 Starkwind", f"{BEAUFORT_NAMES[beaufort]} (Bft {beaufort}) aus {wind_direction_label(direction)}",
              f"{num(k['facade_area_high_m2'])} m² Fassade",
              f"frei angeströmt, bis {num(k['max_pressure_kn_m2'], 2)} kN/m² · "
              f"{k['venturi_count']} Düsen-Engstellen", level, status, "wind", odds.get("wind", ""))

    cols = st.columns([1, 1, 1.3], gap="medium")
    with cols[0]:
        _damage_tile("🫨 Erdbeben", f"Mw {num(ss.quake_mw, 1)} in {ss.quake_dist_km} km · Intensität "
                     f"{num(quake.kpis['intensity'], 1)}", quake.kpis, "quake", odds.get("quake", ""))
    with cols[1]:
        _damage_tile("🌪️ Tornado", f"EF{ss.tornado_ef} nach {wind_direction_label(ss.tornado_heading)}",
                     tornado.kpis, "tornado", odds.get("tornado", ""))
    with cols[2]:
        _damage_tile("👾 Kaiju-Angriff", f"{ss.kaiju_height} m groß, läuft nach "
                     f"{wind_direction_label(ss.kaiju_heading)} · {ss.kaiju_lasers} Laser, "
                     f"{ss.kaiju_helis} Hubschrauber", kaiju.kpis, "kaiju", odds.get("kaiju", ""))

    cols = st.columns([1, 2.3], gap="medium")
    with cols[0]:
        plural = ss.alien_ufos > 1
        kind = ("Mutterschiffe" if plural else "Mutterschiff") if alien.kpis["mothership"] else \
            ("UFOs" if plural else "UFO")
        scenario = f"{ss.alien_ufos} {kind}, {ss.alien_size} m Durchmesser"
        if alien.kpis["mothership"]:
            level, status = risk_level(alien.kpis["lifted"] / max(1, alien.kpis["buildings_total"]), 0.02, 0.1)
            _tile("🛸 Alien-Invasion", scenario, f"{alien.kpis['lifted']} von {alien.kpis['buildings_total']} Gebäuden",
                  "werden eingesaugt · Entführungen zählt die 3D-Ansicht", level, status, "alien",
                  odds.get("alien", ""))
        else:
            _tile("🛸 Alien-Invasion", scenario, f"{ss.people_count} Menschen im Gebiet",
                  "Entführungen zählt die 3D-Ansicht live mit", "none", "Planspiel", "alien", odds.get("alien", ""))
    with cols[1]:
        _probability_card(model)

    # ---- Reihe 6: Exporte ------------------------------------------------------
    kpis = [("Gebiet", "Fläche", m["site_area_m2"], "m²"), ("Gebiet", "Gebäude", m["buildings"], ""),
            ("Gebiet", "GRZ", round(m["grz"], 3), ""), ("Gebiet", "GFZ (geschätzt)", round(m["gfz"], 3), ""),
            ("Gebiet", "Versiegelungsgrad", round(m["sealed_share"], 3), "Anteil"),
            ("Hochwasser", f"Pegel +{ss.flood_gauge:.1f} m: betroffene Gebäude", flood.kpis["buildings_affected"], ""),
            ("Hochwasser", "Überflutete BGF EG", round(flood.kpis["flooded_gfa_m2"]), "m²"),
            ("Starkregen", f"{rain_label}: betroffene Gebäude", rain.kpis["buildings_affected"], ""),
            ("Starkregen", "Oberflächenabfluss", round(rain.kpis["runoff_m3"]), "m³"),
            ("Starkwind", f"Bft {beaufort} aus {direction}°: frei angeströmte Fassaden",
             round(wind.kpis["facade_area_high_m2"]), "m²"),
            ("Starkwind", "Engstellen mit Düseneffekt", wind.kpis["venturi_count"], ""),
            ("Erdbeben", f"Mw {ss.quake_mw:.1f} in {ss.quake_dist_km} km: Intensität",
             round(quake.kpis["intensity"], 1), "EMS-98"),
            ("Erdbeben", "Schwer beschädigte Gebäude (Grad ≥ 3)", quake.kpis["heavy"], ""),
            ("Tornado", f"EF{ss.tornado_ef}: schwer beschädigte Gebäude (Grad ≥ 3)", tornado.kpis["heavy"], ""),
            ("Tornado", "Zerstörte Gebäude", tornado.kpis["destroyed"], ""),
            ("Kaiju", f"{ss.kaiju_height} m: zerstörte Gebäude", kaiju.kpis["destroyed"], "")]
    kpis += _odds_rows(model)
    kpi_csv = pd.DataFrame(kpis, columns=["Bereich", "Kennzahl", "Wert", "Einheit"]).to_csv(
        index=False, sep=";", decimal=",").encode("utf-8-sig")
    geojson = _results_table(model, flood, rain, wind, quake, tornado, kaiju).to_json(
        drop_id=True).encode("utf-8")

    with card("mint"):
        st.markdown("**Projekt & Ergebnisse exportieren**")
        cols = st.columns(3)
        cols[0].download_button("Projektdatei (.json)", project_file(model), file_name="projekt.terrasim.json",
                                mime="application/json", icon=":material/save:", width="stretch",
                                help="Gebiet und alle Einstellungen – später über „Projektdatei“ wieder öffnen")
        cols[1].download_button("Kennzahlen (.csv)", kpi_csv, file_name="terra-sim_kennzahlen.csv",
                                mime="text/csv", icon=":material/table:", width="stretch",
                                help="Für Excel: Semikolon-getrennt, Dezimalkomma")
        cols[2].download_button("Gebäude mit Ergebnissen (.geojson)", geojson,
                                file_name="terra-sim_gebaeude.geojson", mime="application/geo+json",
                                icon=":material/map:", width="stretch",
                                help="Für QGIS & Co.: jedes Gebäude mit Höhe und den Ergebnissen aller Analysen")


# ---------------------------------------------------------------------------
# Wahrscheinlichkeiten (amtliche Daten) – Berechnung in modules/likelihood.py
# ---------------------------------------------------------------------------

HAZARD_LABELS = {"flood": "🌊 Hochwasser", "rain": "🌧️ Starkregen", "wind": "💨 Sturm", "quake": "🫨 Erdbeben",
                 "tornado": "🌪️ Tornado", "kaiju": "👾 Kaiju", "alien": "🛸 Aliens"}


def _odds(model) -> dict:
    """Kurzer Text je Gefahr für die Kacheln: „Wie oft? etwa alle N Jahre …“."""
    return {key: odds_line(odds, source) for key, (odds, source) in scenario_odds(model).items()}


def _odds_rows(model) -> list:
    rows = []
    for key, (odds, source) in scenario_odds(model).items():
        if odds.get("T"):
            rows.append(("Wahrscheinlichkeit", f"{HAZARD_LABELS[key][2:].strip()}: Wiederkehrzeit (Szenario)",
                         round(odds["T"]), "Jahre"))
    return rows


def _probability_card(model):
    """Bento-Karte: alle Gefahren nach Wahrscheinlichkeit sortiert."""
    odds = scenario_odds(model)
    order = sorted(odds.items(), key=lambda kv: -(kv[1][0].get("p_life") or -1))
    with card():
        st.markdown("**Wie wahrscheinlich ist was?**")
        st.caption("Chance, dass das eingestellte Szenario am Standort in den nächsten 30 Jahren mindestens "
                   "einmal eintritt – aus amtlichen Daten und Messreihen, bei Kaiju und Aliens aus "
                   "Modellrechnungen mit Fachliteratur. Rot = häufig (bis alle 30 Jahre), "
                   "Orange = bis alle 300 Jahre, Grün = seltener.")
        st.html("".join(odds_bar(HAZARD_LABELS[key], o, src) for key, (o, src) in order))
