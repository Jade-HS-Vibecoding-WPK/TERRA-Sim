"""Historische Klimadaten am Standort (Meteostat).

Lädt Messwerte der nächstgelegenen Wetterstationen und fasst sie zu einem
Klima-Steckbrief zusammen: Temperatur, Niederschlag, Starkregen, Windrose
und Sturm. Die Werte dienen in TERRA-Sim als Vorgabe für die Simulationen
(z. B. Hauptwindrichtung bei Sturm, stärkster gemessener Tagesregen).

Quelle: Meteostat (https://meteostat.net), Daten u. a. vom Deutschen
Wetterdienst. Lizenz meist CC BY 4.0 – die Quelle muss genannt werden
(steht in ``ClimateData.attribution``).

Für jeden Messwert wird die nächstgelegene Station verwendet, die im
Zeitraum ausreichend vollständige Daten hat. Temperatur und Wind können
deshalb von unterschiedlichen Stationen stammen.

Beispiel::

    from modules.climate_loader import load_climate, climate_summary

    klima = load_climate(53.14, 8.21)
    print(climate_summary(klima))
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

MIN_COVERAGE = 0.7          # Mindestanteil vorhandener Werte im Zeitraum
SEARCH_RADIUS_M = 60_000
MAX_STATIONS = 8

# Grenzen der Beaufort-Skala in km/h (Untergrenze von Bft 1 … 12)
BEAUFORT_KMH = np.array([1, 6, 12, 20, 29, 39, 50, 62, 75, 89, 103, 118])

COMPASS_16 = ["N", "NNO", "NO", "ONO", "O", "OSO", "SO", "SSO",
              "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
COMPASS_8_DE = ["Nord", "Nordost", "Ost", "Südost", "Süd", "Südwest", "West", "Nordwest"]

DAILY_PARAMETERS = ("temp", "tmin", "tmax", "prcp", "wspd", "wpgt")
HOURLY_PARAMETERS = ("wdir", "wspd")


@dataclass
class ClimateData:
    """Messreihen am Standort und woher sie stammen."""

    lat: float
    lon: float
    start: date
    end: date
    daily: pd.DataFrame                  # Tageswerte, Index = Datum
    hourly: pd.DataFrame                 # Stundenwerte für Wind (wdir, wspd)
    sources: dict = field(default_factory=dict)  # Messwert -> Station (Name, Entfernung)
    attribution: str = "Meteostat"

    @property
    def empty(self) -> bool:
        return self.daily.empty and self.hourly.empty


# --------------------------------------------------------------------------
# Umrechnungen
# --------------------------------------------------------------------------

def kmh_to_beaufort(kmh) -> np.ndarray:
    """Windgeschwindigkeit (km/h) -> Beaufort-Stärke 0 … 12."""
    return np.searchsorted(BEAUFORT_KMH, np.asarray(kmh, dtype=float), side="right")


def compass_name(degrees: float) -> str:
    """Himmelsrichtung (8 Sektoren, deutsch) für eine Gradzahl."""
    return COMPASS_8_DE[int(round(degrees / 45)) % 8]


# --------------------------------------------------------------------------
# Laden
# --------------------------------------------------------------------------

def _configure(cache_folder: str):
    import meteostat as ms

    os.makedirs(cache_folder, exist_ok=True)
    ms.config.cache_directory = cache_folder
    # Standardmäßig landet die Stationsdatenbank im Benutzerordner (~/.meteostat),
    # der nicht immer existiert – deshalb mit in den Projekt-Cache legen.
    ms.config.stations_db_file = os.path.join(cache_folder, "stations.db")
    ms.config.network_timeout = 30
    return ms


def _coverage(frame: pd.DataFrame | None, column: str, expected: int) -> float:
    if frame is None or frame.empty or column not in frame:
        return 0.0
    return float(frame[column].notna().sum()) / max(1, expected)


def _station_label(stations: pd.DataFrame, station_id) -> dict:
    row = stations.loc[station_id]
    return {"id": str(station_id), "name": str(row["name"]),
            "distance_km": round(float(row["distance"]) / 1000, 1),
            "elevation_m": None if pd.isna(row["elevation"]) else float(row["elevation"])}


def load_climate(lat: float, lon: float, years: int = 10, wind_years: int = 3,
                 cache_folder: str = ".cache/meteostat") -> ClimateData:
    """Lädt Tageswerte (``years`` Jahre) und stündliche Winddaten (``wind_years``).

    Meteostat blockiert Stundenabfragen über mehr als 3 Jahre (Server-Schonung),
    deshalb ist ``wind_years`` auf 3 begrenzt.

    Rückgabe ist immer ein ``ClimateData``-Objekt; gibt es im Umkreis keine
    geeignete Station, sind die Tabellen leer (``ClimateData.empty``).
    Netzwerkfehler werden weitergereicht.
    """
    ms = _configure(cache_folder)
    wind_years = min(wind_years, 3)
    end = date(date.today().year - 1, 12, 31)          # letztes vollständiges Jahr
    start = date(end.year - years + 1, 1, 1)
    wind_start = date(end.year - wind_years + 1, 1, 1)
    n_days = (end - start).days + 1
    n_hours = ((end - wind_start).days + 1) * 24

    stations = ms.stations.nearby(ms.Point(lat, lon), radius=SEARCH_RADIUS_M, limit=MAX_STATIONS)
    daily = pd.DataFrame(index=pd.DatetimeIndex([], name="time"))
    hourly = pd.DataFrame(index=pd.DatetimeIndex([], name="time"))
    sources: dict = {}
    licenses: set = set()

    # Tageswerte: je Messwert die nächste Station mit ausreichend Daten
    missing = list(DAILY_PARAMETERS)
    for station_id in stations.index:
        if not missing:
            break
        series = ms.daily(station_id, start, end)
        frame = series.fetch()
        found = [p for p in missing if _coverage(frame, p, n_days) >= MIN_COVERAGE]
        if not found:
            continue
        daily = daily.join(frame[found], how="outer") if not daily.empty else frame[found].copy()
        for p in found:
            sources[p] = _station_label(stations, station_id)
            missing.remove(p)
        licenses.update(lic.attribution for lic in series.licenses)

    # Stundenwerte für die Windrose (Richtung und Geschwindigkeit von derselben Station)
    for station_id in stations.index:
        series = ms.hourly(station_id, wind_start, end)
        frame = series.fetch()
        if all(_coverage(frame, p, n_hours) >= MIN_COVERAGE for p in HOURLY_PARAMETERS):
            hourly = frame[list(HOURLY_PARAMETERS)].dropna().astype(float)
            sources["wind_hourly"] = _station_label(stations, station_id)
            licenses.update(lic.attribution for lic in series.licenses)
            break

    daily = daily.apply(pd.to_numeric, errors="coerce").astype(float) if not daily.empty else daily
    attribution = "Meteostat" + "".join(f", {name}" for name in sorted(n for n in licenses if n))
    return ClimateData(lat, lon, start, end, daily, hourly, sources, attribution)


# --------------------------------------------------------------------------
# Auswertung
# --------------------------------------------------------------------------

def climate_summary(data: ClimateData) -> dict:
    """Klima-Steckbrief als Dictionary (fehlende Werte = None)."""
    d, h = data.daily, data.hourly
    n_years = max(1.0, (data.end - data.start).days / 365.25)
    out: dict = {"years": f"{data.start.year}–{data.end.year}"}

    def col(name):
        return d[name].dropna() if name in d else pd.Series(dtype=float)

    temp, tmax, tmin, prcp, gust = col("temp"), col("tmax"), col("tmin"), col("prcp"), col("wpgt")
    out["temp_mean"] = float(temp.mean()) if len(temp) else None
    out["hot_days"] = float((tmax >= 30).sum() / n_years) if len(tmax) else None
    out["summer_days"] = float((tmax >= 25).sum() / n_years) if len(tmax) else None
    out["frost_days"] = float((tmin < 0).sum() / n_years) if len(tmin) else None
    out["tmax_record"] = float(tmax.max()) if len(tmax) else None

    if len(prcp):
        out["prcp_year"] = float(prcp.sum() / (len(prcp) / 365.25))
        out["prcp_max_day"] = float(prcp.max())
        out["prcp_max_date"] = prcp.idxmax().date()
        out["heavy_rain_days"] = float((prcp >= 20).sum() / (len(prcp) / 365.25))
        out["prcp_p99"] = float(prcp[prcp > 0].quantile(0.99)) if (prcp > 0).any() else 0.0
    else:
        out.update(prcp_year=None, prcp_max_day=None, prcp_max_date=None,
                   heavy_rain_days=None, prcp_p99=None)

    if len(gust):
        out["gust_max"] = float(gust.max())
        out["gust_max_date"] = gust.idxmax().date()
        out["storm_days"] = float((gust >= BEAUFORT_KMH[8]).sum() / (len(gust) / 365.25))  # ab Bft 9
    else:
        out.update(gust_max=None, gust_max_date=None, storm_days=None)

    if len(h):
        speed = h["wspd"]
        out["wind_mean"] = float(speed.mean())
        out["wind_p98"] = float(speed.quantile(0.98))
        out["wind_max_hour"] = float(speed.max())
        out["wind_dir_prevailing"] = _prevailing_direction(h)
        strong = h[speed >= BEAUFORT_KMH[5]]  # ab Bft 6 ("starker Wind")
        out["wind_dir_strong"] = _prevailing_direction(strong) if len(strong) >= 24 else out["wind_dir_prevailing"]
    else:
        out.update(wind_mean=None, wind_p98=None, wind_max_hour=None,
                   wind_dir_prevailing=None, wind_dir_strong=None)
    return out


def _prevailing_direction(hourly: pd.DataFrame) -> float:
    """Häufigste Windrichtung (Mitte des stärksten 22,5°-Sektors)."""
    sector = ((hourly["wdir"].to_numpy() + 11.25) // 22.5).astype(int) % 16
    counts = np.bincount(sector, minlength=16)
    return float(np.argmax(counts) * 22.5)


def wind_rose(hourly: pd.DataFrame) -> pd.DataFrame:
    """Häufigkeit (%) je Richtungssektor (16) und Windstärke-Klasse.

    Windstille (< 1 km/h) wird nicht mitgezählt. Spalten: ``Richtung``,
    ``Winkel``, ``Klasse``, ``Anteil``.
    """
    classes = [("Bft 1–3 (bis 19 km/h)", 1, 20), ("Bft 4–5 (20–38 km/h)", 20, 39),
               ("Bft 6–7 (39–61 km/h)", 39, 62), ("ab Bft 8 (ab 62 km/h)", 62, np.inf)]
    h = hourly[hourly["wspd"] >= 1]
    if h.empty:
        return pd.DataFrame(columns=["Richtung", "Winkel", "Klasse", "Anteil"])
    sector = ((h["wdir"].to_numpy() + 11.25) // 22.5).astype(int) % 16
    rows = []
    for label, low, high in classes:
        in_class = (h["wspd"].to_numpy() >= low) & (h["wspd"].to_numpy() < high)
        counts = np.bincount(sector[in_class], minlength=16)
        for i in range(16):
            rows.append({"Richtung": COMPASS_16[i], "Winkel": i * 22.5, "Klasse": label,
                         "Anteil": 100.0 * counts[i] / len(h)})
    return pd.DataFrame(rows)


def monthly_climate(daily: pd.DataFrame) -> pd.DataFrame:
    """Mittlere Monatswerte: Temperatur (°C) und Niederschlagssumme (mm)."""
    months = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]
    out = pd.DataFrame({"Monat": months})
    if "temp" in daily:
        out["Temperatur (°C)"] = daily["temp"].groupby(daily.index.month).mean().reindex(range(1, 13)).to_numpy()
    if "prcp" in daily:
        monthly_sum = daily["prcp"].resample("MS").sum(min_count=20)
        out["Niederschlag (mm)"] = monthly_sum.groupby(monthly_sum.index.month).mean().reindex(range(1, 13)).to_numpy()
    return out


def annual_extremes(daily: pd.DataFrame) -> pd.DataFrame:
    """Je Jahr: stärkster Tagesregen, stärkste Böe, heißester Tag."""
    columns = {"prcp": "Max. Tagesregen (mm)", "wpgt": "Max. Böe (km/h)", "tmax": "Höchsttemperatur (°C)"}
    present = [c for c in columns if c in daily]
    if not present:
        return pd.DataFrame()
    table = daily[present].groupby(daily.index.year).max().rename(columns=columns)
    table.index.name = "Jahr"
    return table.reset_index()


def direction_stats(hourly: pd.DataFrame, direction_deg: float, beaufort: int) -> dict:
    """Wie oft kommt der Wind aus dieser Richtung – und wie oft so stark?

    ``direction_deg``  Richtung, aus der der Wind kommt (Sektor ± 11,25°)
    ``beaufort``       Mindeststärke (Stundenmittel in 10 m Höhe)
    Rückgabe: Anteile in % und Stunden pro Jahr (Mittel über den Messzeitraum).
    """
    h = hourly.dropna(subset=["wdir", "wspd"]) if not hourly.empty else hourly
    if h.empty:
        return {}
    years = max(1e-6, (h.index[-1] - h.index[0]).days / 365.25)
    sector = ((h["wdir"].to_numpy() + 11.25) // 22.5).astype(int) % 16
    chosen = int(round(direction_deg / 22.5)) % 16
    moving = h["wspd"].to_numpy() >= 1
    from_dir = (sector == chosen) & moving
    threshold = BEAUFORT_KMH[max(0, int(beaufort) - 1)] if beaufort > 0 else 0
    strong = h["wspd"].to_numpy() >= threshold
    return {
        "years": years,
        "sector": COMPASS_16[chosen],
        "share_from_dir": 100.0 * from_dir.sum() / max(1, moving.sum()),
        "strong_hours_per_year": float(strong.sum() / years),
        "strong_from_dir_hours_per_year": float((strong & from_dir).sum() / years),
        "share_strong_from_dir": 100.0 * (strong & from_dir).sum() / max(1, strong.sum()),
        "max_kmh": float(h["wspd"].max()),
    }
