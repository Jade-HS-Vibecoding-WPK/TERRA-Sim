"""Übersicht: Kennzahlen des Gebiets, Klima-Steckbrief und Analyse-Kacheln."""

from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from views.common import (area_metrics, climate_info, current_flood, current_rain, current_wind,
                          num, page_header, pill, project_file, risk_level, wind_direction_label)
from modules.climate_loader import BEAUFORT_KMH
from modules.simulator import BEAUFORT_NAMES

REFERENCE_SHORT = {
    "Tiefster Geländepunkt im Gebiet": "dem tiefsten Geländepunkt",
    "Wasserspiegel der Gewässer im Gebiet": "dem Gewässerspiegel",
    "Meeresspiegel (0 m ü. NHN)": "Meeresspiegel",
}


def _tile(title: str, scenario: str, value: str, sub: str, level: str, status: str, page_key: str):
    from views.navigation import PAGES

    with st.container(border=True):
        st.html(f'<div class="terra-tile-head"><span class="terra-tile-title">{html.escape(title)}</span>'
                f'{pill(status, level)}</div>'
                f'<div class="terra-tile-scenario">{html.escape(scenario)}</div>'
                f'<div class="terra-tile-value">{html.escape(value)}</div>'
                f'<div class="terra-tile-sub">{html.escape(sub)}</div>')
        st.page_link(PAGES[page_key], label="Analyse öffnen", icon=":material/arrow_forward:")


def _results_table(model, flood, rain, wind) -> pd.DataFrame:
    """Gebäude mit allen Analyse-Ergebnissen (für den GeoJSON-Export)."""
    b = model.buildings_wgs
    table = b[["osm_id", "name", "building", "levels", "height_m", "height_source",
               "area_m2", "ground_m", "geometry"]].copy()
    table["hochwasser_tiefe_m"] = flood.building_depth.round(2)
    table["hochwasser_betroffen"] = flood.affected
    table["starkregen_tiefe_m"] = rain.building_depth.round(2)
    table["starkregen_betroffen"] = rain.affected
    table["wind_exposition"] = wind.building_exposure.round(2)
    table["ground_m"] = table["ground_m"].round(2)
    return table


def render():
    from views.navigation import PAGES, require_project

    model = require_project()
    page_header("Übersicht", "Das Projektgebiet auf einen Blick – Kennzahlen, Klima und die "
                             "Ergebnisse der Analysen mit den aktuellen Einstellungen.")
    for note in st.session_state.pop("load_notes", []):
        st.warning(note)

    # ---- Gebietskennzahlen ------------------------------------------------
    m = area_metrics(model)
    st.subheader("Gebietskennzahlen")
    with st.container(border=True):
        row1 = st.columns(5)
        row1[0].metric("Gebietsfläche", f"{num(m['site_area_m2'] / 10_000, 1)} ha")
        row1[1].metric("Gebäude", num(m["buildings"]))
        row1[2].metric("GRZ", num(m["grz"], 2), help="Grundflächenzahl: bebaute Fläche / Gebietsfläche "
                       f"({num(m['footprint_m2'])} m² bebaut)")
        row1[3].metric("GFZ (geschätzt)", num(m["gfz"], 2), help="Geschossflächenzahl: Summe aller "
                       f"Geschossflächen / Gebietsfläche (BGF ca. {num(m['gfa_m2'])} m², aus "
                       "Grundfläche × Geschosszahl)")
        row1[4].metric("Mittlere Gebäudehöhe", f"{num(m['mean_height_m'], 1)} m",
                       help=f"Höchstes Gebäude: {num(m['max_height_m'], 1)} m")
        row2 = st.columns(5)
        row2[0].metric("Versiegelungsgrad", f"{m['sealed_share']:.0%}", help="Straßen und Dächer an der Landfläche")
        row2[1].metric("Grünflächen", f"{m['green_share']:.0%}")
        row2[2].metric("Wasserflächen", f"{m['water_share']:.0%}")
        row2[3].metric("Geländehöhe", f"{num(m['elevation_min'], 1)} – {num(m['elevation_max'], 1)} m",
                       help=f"Quelle: {model.dem.source}")
        known = (model.buildings["height_source"] != "Schätzung").mean() if m["buildings"] else 0
        row2[4].metric("Höhen aus OSM", f"{known:.0%}", help="Anteil der Gebäude mit Höhen- oder "
                       "Geschossangabe in OpenStreetMap; der Rest ist geschätzt.")

    # ---- Analysen ---------------------------------------------------------
    st.subheader("Analysen")
    st.caption("Die Kacheln zeigen das Ergebnis mit den Einstellungen, die zuletzt in der jeweiligen "
               "Analyse gewählt wurden.")
    flood, base = current_flood(model)
    rain, rain_label = current_rain(model)
    wind, direction, beaufort = current_wind(model)
    n = max(1, len(model.buildings))
    cols = st.columns(3)
    with cols[0]:
        k = flood.kpis
        level, status = risk_level(k["buildings_affected"] / n)
        reference = REFERENCE_SHORT.get(st.session_state.flood_ref, st.session_state.flood_ref)
        _tile("🌊 Hochwasser", f"Pegel +{num(st.session_state.flood_gauge, 1)} m über {reference}",
              f"{k['buildings_affected']} von {k['buildings_total']} Gebäuden",
              f"{num(k['flooded_gfa_m2'])} m² BGF im Erdgeschoss überflutet", level, status, "flood")
    with cols[1]:
        k = rain.kpis
        level, status = risk_level(k["buildings_affected"] / n, warn=0.1, risk=0.3)
        _tile("🌧️ Starkregen", rain_label, f"{k['buildings_affected']} von {k['buildings_total']} Gebäuden",
              f"mit Wasser ≥ 10 cm am Gebäude · max. {num(k['max_ponding_m'], 2)} m tief", level, status, "rain")
    with cols[2]:
        k = wind.kpis
        share = k["facade_area_high_m2"] / k["facade_area_total_m2"] if k["facade_area_total_m2"] else 0
        level, status = risk_level(share, warn=0.03, risk=0.1) if beaufort >= 8 else ("ok", "unkritisch")
        _tile("💨 Starkwind", f"{BEAUFORT_NAMES[beaufort]} (Bft {beaufort}) aus {wind_direction_label(direction)}",
              f"{num(k['facade_area_high_m2'])} m² Fassade",
              f"frei angeströmt, bis {num(k['max_pressure_kn_m2'], 2)} kN/m² · "
              f"{k['venturi_count']} Düsen-Engstellen", level, status, "wind")

    # ---- Klima ------------------------------------------------------------
    st.subheader("Klima am Standort")
    info = climate_info(model)
    with st.container(border=True):
        if info is None:
            st.info(f"Keine Klimadaten verfügbar. {model.climate_error}")
        else:
            cols = st.columns(5)
            cols[0].metric("Jahresmittel", f"{num(info['temp_mean'], 1)} °C" if info["temp_mean"] is not None else "–")
            cols[1].metric("Niederschlag", f"{num(info['prcp_year'])} mm/Jahr" if info["prcp_year"] else "–")
            cols[2].metric("Stärkster Tagesregen", f"{num(info['prcp_max_day'])} mm" if info["prcp_max_day"] else "–",
                           help=f"am {info['prcp_max_date']:%d.%m.%Y}" if info["prcp_max_date"] else None)
            cols[3].metric("Hauptwindrichtung", wind_direction_label(info["wind_dir_prevailing"])
                           if info["wind_dir_prevailing"] is not None else "–")
            cols[4].metric("Sturmtage", f"{num(info['storm_days'], 1)} pro Jahr" if info["storm_days"] is not None else "–",
                           help=f"Tage mit Böen ab {BEAUFORT_KMH[8]} km/h (Bft 9)")
            st.page_link(PAGES["climate"], label=f"Klimadaten {info['years']} ansehen", icon=":material/arrow_forward:")

    # ---- Exporte ----------------------------------------------------------
    st.subheader("Projekt & Ergebnisse exportieren")
    kpis = [("Gebiet", "Fläche", m["site_area_m2"], "m²"), ("Gebiet", "Gebäude", m["buildings"], ""),
            ("Gebiet", "GRZ", round(m["grz"], 3), ""), ("Gebiet", "GFZ (geschätzt)", round(m["gfz"], 3), ""),
            ("Gebiet", "Versiegelungsgrad", round(m["sealed_share"], 3), "Anteil"),
            ("Hochwasser", f"Pegel +{st.session_state.flood_gauge:.1f} m: betroffene Gebäude",
             flood.kpis["buildings_affected"], ""),
            ("Hochwasser", "Überflutete BGF EG", round(flood.kpis["flooded_gfa_m2"]), "m²"),
            ("Starkregen", f"{rain_label}: betroffene Gebäude", rain.kpis["buildings_affected"], ""),
            ("Starkregen", "Oberflächenabfluss", round(rain.kpis["runoff_m3"]), "m³"),
            ("Starkwind", f"Bft {beaufort} aus {direction}°: frei angeströmte Fassaden",
             round(wind.kpis["facade_area_high_m2"]), "m²"),
            ("Starkwind", "Engstellen mit Düseneffekt", wind.kpis["venturi_count"], "")]
    kpi_csv = pd.DataFrame(kpis, columns=["Bereich", "Kennzahl", "Wert", "Einheit"]).to_csv(
        index=False, sep=";", decimal=",").encode("utf-8-sig")
    geojson = _results_table(model, flood, rain, wind).to_json(drop_id=True).encode("utf-8")

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
