"""Klima am Standort: Messdaten der nächsten Wetterstationen (Meteostat)."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from modules.climate_loader import (BEAUFORT_KMH, annual_extremes, kmh_to_beaufort,
                                    monthly_climate, wind_rose)
from views.common import climate_info, num, page_header, rain_scenarios, wind_direction_label
from views.common import card, kpi_row

ROSE_COLORS = ["#c8eacf", "#4fae78", "#8e4cc4", "#d33a3a"]   # ruhig = grün, stark = lila, Sturm = rot

PARAMETER_NAMES = {"temp": "Temperatur", "tmin": "Tiefsttemperatur", "tmax": "Höchsttemperatur",
                   "prcp": "Niederschlag", "wspd": "Wind (Tagesmittel)", "wpgt": "Böen",
                   "wind_hourly": "Windrichtung (stündlich)"}


def _use_wind():
    info = climate_info(st.session_state.model)
    st.session_state.wind_dir = int(round(info["wind_dir_strong"] / 5) * 5) % 360
    st.session_state.wind_bft = int(kmh_to_beaufort(info["wind_max_hour"]))
    st.session_state.goto = "wind"


def _use_rain():
    st.session_state.rain_scenario = next(iter(rain_scenarios(st.session_state.model)))
    st.session_state.goto = "rain"


def render():
    from views.navigation import PAGES, require_project

    model = require_project()
    goto = st.session_state.pop("goto", None)
    if goto:
        st.switch_page(PAGES[goto])

    page_header("Klima am Standort", "Gemessene Werte der nächstgelegenen Wetterstationen – "
                                     "Grundlage für realistische Szenarien in den Analysen.")
    info = climate_info(model)
    if info is None:
        st.warning(f"Für dieses Gebiet liegen keine Klimadaten vor. {model.climate_error}")
        return
    climate = model.climate

    cols = kpi_row(6)
    cols[0].metric("Jahresmittel", f"{num(info['temp_mean'], 1)} °C" if info["temp_mean"] is not None else "–")
    cols[1].metric("Heiße Tage", f"{num(info['hot_days'], 1)} / Jahr" if info["hot_days"] is not None else "–",
                   help="Tage mit mindestens 30 °C")
    cols[2].metric("Frosttage", f"{num(info['frost_days'])} / Jahr" if info["frost_days"] is not None else "–",
                   help="Tage mit Tiefstwert unter 0 °C")
    cols[3].metric("Niederschlag", f"{num(info['prcp_year'])} mm/Jahr" if info["prcp_year"] else "–")
    cols[4].metric("Starkregentage", f"{num(info['heavy_rain_days'], 1)} / Jahr" if info["heavy_rain_days"] is not None else "–",
                   help="Tage mit mindestens 20 mm Niederschlag")
    cols[5].metric("Stärkste Böe", f"{num(info['gust_max'])} km/h" if info["gust_max"] else "–",
                   help=f"am {info['gust_max_date']:%d.%m.%Y}" if info["gust_max_date"] else None)

    left, right = st.columns(2, gap="large")
    with left:
        st.subheader("Klimadiagramm")
        monthly = monthly_climate(climate.daily)
        fig = go.Figure()
        if "Niederschlag (mm)" in monthly:
            fig.add_bar(x=monthly["Monat"], y=monthly["Niederschlag (mm)"], name="Niederschlag (mm)",
                        marker_color="#5fa8d3")
        if "Temperatur (°C)" in monthly:
            fig.add_scatter(x=monthly["Monat"], y=monthly["Temperatur (°C)"], name="Temperatur (°C)",
                            yaxis="y2", mode="lines+markers", line=dict(color="#d1495b", width=3))
        temps = monthly.get("Temperatur (°C)", [0.0])
        t_low, t_high = min(0.0, float(min(temps)) - 2), float(max(temps)) + 3
        fig.update_layout(height=360, margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h", y=-0.15),
                          yaxis=dict(title="Niederschlag (mm)", rangemode="tozero"),
                          yaxis2=dict(title="Temperatur (°C)", overlaying="y", side="right", showgrid=False,
                                      range=[t_low, t_high], tickmode="linear", tick0=0, dtick=5))
        st.plotly_chart(fig, key="climate_chart")
        st.caption(f"Monatsmittel {info['years']}.")
    with right:
        st.subheader("Windrose")
        if climate.hourly.empty:
            st.info("Keine stündlichen Winddaten verfügbar.")
        else:
            rose = wind_rose(climate.hourly)
            fig = go.Figure()
            for color, (label, part) in zip(ROSE_COLORS, rose.groupby("Klasse", sort=False)):
                fig.add_barpolar(r=part["Anteil"], theta=part["Richtung"], name=label, marker_color=color)
            fig.update_layout(height=360, margin=dict(l=30, r=30, t=20, b=10),
                              legend=dict(orientation="h", y=-0.12),
                              polar=dict(angularaxis=dict(direction="clockwise", rotation=90),
                                         radialaxis=dict(ticksuffix=" %", angle=45)))
            st.plotly_chart(fig, key="wind_rose")
            first, last = climate.hourly.index.min().year, climate.hourly.index.max().year
            st.caption(f"Häufigkeit der Windrichtungen nach Stärke, Stundenwerte {first}–{last}. "
                       f"Hauptwindrichtung: {wind_direction_label(info['wind_dir_prevailing'])}, "
                       f"bei starkem Wind: {wind_direction_label(info['wind_dir_strong'])}.")

    st.subheader("Szenarien für die Analysen")
    with card():
        c1, c2 = st.columns(2)
        with c1:
            if info.get("wind_max_hour"):
                bft = int(kmh_to_beaufort(info["wind_max_hour"]))
                st.markdown(f"**Starkwind:** stärkstes gemessenes Stundenmittel {num(info['wind_max_hour'])} km/h "
                            f"(Bft {bft}) aus {wind_direction_label(info['wind_dir_strong'])}.")
                st.button("In Starkwind-Analyse übernehmen", icon=":material/air:", on_click=_use_wind)
        with c2:
            if info.get("prcp_max_day"):
                share = 100 / info["prcp_max_day"]
                st.markdown(f"**Starkregen:** stärkster Tagesregen {num(info['prcp_max_day'])} l/m² am "
                            f"{info['prcp_max_date']:%d.%m.%Y}. Ein Jahrhundertregen (100 l/m²) wäre "
                            f"{num(share, 1)}-mal so viel.")
                st.button("In Starkregen-Analyse übernehmen", icon=":material/rainy:", on_click=_use_rain)

    left, right = st.columns(2, gap="large")
    with left:
        st.subheader("Extremwerte je Jahr")
        st.dataframe(annual_extremes(climate.daily).round(1), hide_index=True)
    with right:
        st.subheader("Verwendete Stationen")
        rows = [{"Messwert": PARAMETER_NAMES.get(k, k), "Station": v["name"],
                 "Entfernung": f"{num(v['distance_km'], 1)} km",
                 "Höhe": f"{num(v['elevation_m'])} m" if v["elevation_m"] is not None else "–"}
                for k, v in climate.sources.items()]
        st.dataframe(pd.DataFrame(rows), hide_index=True)
        st.caption("Je Messwert wird die nächste Station mit ausreichend vollständigen Daten verwendet. "
                   f"Sturm-Schwelle Bft 9 = ab {BEAUFORT_KMH[8]} km/h.")
    st.html(f'<div class="terra-source">Quelle: {climate.attribution} (über meteostat.net), '
            'Lizenz CC BY 4.0 bzw. Angaben der jeweiligen Wetterdienste.</div>')
