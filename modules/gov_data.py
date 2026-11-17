"""Amtliche Daten zur Häufigkeit von Gefahren am Standort.

* **KOSTRA-DWD-2020** (Deutscher Wetterdienst): Regenhöhe je Dauerstufe und
  Wiederkehrzeit (1–100 Jahre) im 5-km-Raster – „wie selten ist dieser Regen?“
* **Hochwassergefahrenkarten** (Bundesanstalt für Gewässerkunde, Daten der
  Länder nach EU-Hochwasserrichtlinie): Überflutungsflächen für HQ häufig,
  HQ100 und HQ extrem
* **DWD-Klimastationen**: tägliche Spitzenböe (FX) über Jahrzehnte –
  Jahreshöchstwerte für die Sturm-Statistik – und stündlicher Wind (Richtung,
  Geschwindigkeit) der letzten zehn Jahre für die Windrose
* **Erdbebenzonen** nach DIN 4149 / DIN EN 1998-1/NA (Abfrage beim GFZ Potsdam
  über Ort und Postleitzahl)

Alle Downloads landen in ``.cache/gov`` und werden nur einmal geladen.

Beispiel::

    from modules.gov_data import kostra, official_floods, gust_maxima
    regen = kostra(53.14, 8.214)            # {60: {1: 21.4, …, 100: 49.0}, 1440: {...}}
    flut = official_floods(bbox)            # {"M": {"geometry": …, "T": 100, …}, …}
    boeen = gust_maxima(53.14, 8.214)       # Jahreshöchstwerte der Böen (km/h) + Station
"""

from __future__ import annotations

import io
import math
import re
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import shapely
from pyproj import Transformer
from shapely.geometry import box, shape

CACHE = Path(".cache") / "gov"
USER_AGENT = "TERRA-Sim/0.1 (Hochschul-Lehrprojekt)"
_session = requests.Session()
_session.headers["User-Agent"] = USER_AGENT


def _cached_get(url: str, name: str, timeout: float = 120) -> bytes:
    path = CACHE / name
    if path.exists():
        return path.read_bytes()
    response = _session.get(url, timeout=timeout)
    response.raise_for_status()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)
    return response.content


# ==========================================================================
# Starkregen: KOSTRA-DWD-2020
# ==========================================================================

KOSTRA_URL = ("https://opendata.dwd.de/climate_environment/CDC/grids_germany/return_periods/"
              "precipitation/KOSTRA/KOSTRA_DWD_2020/asc/StatRR_KOSTRA-DWD-2020_D{d:05d}_ASC.zip")
KOSTRA_T = (1, 2, 3, 5, 10, 20, 30, 50, 100)
KOSTRA_ATTRIBUTION = "Deutscher Wetterdienst, KOSTRA-DWD-2020"


def _read_asc(text: str) -> tuple[dict, np.ndarray]:
    lines = text.splitlines()
    header = {}
    for line in lines[:6]:
        key, value = line.split()
        header[key.lower()] = float(value)
    data = np.loadtxt(io.StringIO("\n".join(lines[6:])))
    return header, data


def kostra(lat: float, lon: float, durations=(60, 360, 1440)) -> dict:
    """Regenhöhe (mm) je Dauerstufe (Minuten) und Wiederkehrzeit (Jahre) an einem Punkt.

    Raster in EPSG:3035 (5 km). Rückgabe ``{dauer: {T: mm}}``; leer außerhalb Deutschlands.
    """
    x, y = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True).transform(lon, lat)
    out = {}
    for d in durations:
        archive = zipfile.ZipFile(io.BytesIO(_cached_get(KOSTRA_URL.format(d=d), f"kostra_D{d:05d}.zip")))
        table = {}
        for T in KOSTRA_T:
            name = next(n for n in archive.namelist() if n.startswith("Hn_") and f"_T{T:03d}" in n)
            h, data = _read_asc(archive.read(name).decode("ascii"))
            col = int((x - h["xllcorner"]) // h["cellsize"])
            row = int(h["nrows"]) - 1 - int((y - h["yllcorner"]) // h["cellsize"])
            if not (0 <= row < data.shape[0] and 0 <= col < data.shape[1]):
                break
            value = data[row, col]
            if value == h.get("nodata_value", -9999) or value < 0:
                break
            table[T] = float(value)
        if table:
            out[d] = table
    return out


# ==========================================================================
# Hochwasser: Gefahrenkarten nach EU-Hochwasserrichtlinie (BfG-Geoportal)
# ==========================================================================

FLOOD_URL = ("https://geoportal.bafg.de/arcgis3/rest/services/nHWGK_HWRK_live/"
             "Grenzen_der_%C3%9Cberflutungsgebiete_RW_{s}/MapServer/0/query")
# Szenario -> (Name, übliche Wiederkehrzeit, falls der Datensatz keine nennt)
FLOOD_SCENARIOS = {"H": ("HQ häufig", 20), "M": ("HQ100", 100), "L": ("HQ extrem", 1000)}
FLOOD_ATTRIBUTION = "Hochwassergefahrenkarten der Länder (EU-HWRM-RL), BfG-Geoportal"


def official_floods(bbox, timeout: float = 120) -> dict:
    """Amtliche Überflutungsflächen im Gebiet je Szenario (H, M, L).

    Rückgabe ``{"M": {"name": "HQ100", "T": 100, "geometry": Polygon (EPSG:25832)}, …}``
    – nur Szenarien, die das Gebiet berühren. Fehler (Server nicht erreichbar)
    werden als Ausnahme weitergereicht.
    """
    to_m = Transformer.from_crs("EPSG:4326", "EPSG:25832", always_xy=True)
    west, south, east, north = bbox
    xs, ys = to_m.transform([west, east, east, west], [south, south, north, north])
    area = box(min(xs), min(ys), max(xs), max(ys))
    out = {}
    for key, (name, default_T) in FLOOD_SCENARIOS.items():
        params = {"geometry": ",".join(f"{v:.1f}" for v in area.bounds), "geometryType": "esriGeometryEnvelope",
                  "inSR": 25832, "spatialRel": "esriSpatialRelIntersects", "outFields": "FL_RECUR,DESC_PROB",
                  "returnGeometry": "true", "outSR": 25832, "maxAllowableOffset": 2, "geometryPrecision": 0,
                  "f": "geojson"}
        response = _session.get(FLOOD_URL.format(s=key), params=params, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        if "error" in data:
            raise ValueError(data["error"].get("message", "Fehler im BfG-Dienst"))
        features = [f for f in data.get("features", []) if f.get("geometry")]
        if not features:
            continue
        geometry = shapely.union_all([shapely.make_valid(shape(f["geometry"])) for f in features]).intersection(area)
        if geometry.is_empty:
            continue
        out[key] = {"name": name, "T": _recurrence(features, default_T), "geometry": geometry,
                    "share": geometry.area / area.area}
    return out


def _recurrence(features: list, default: int) -> int:
    """Wiederkehrzeit aus dem Attribut FL_RECUR (z. B. „100“, „200--1000“), sonst Standardwert.

    Eigenheiten der Länder: Bayern trägt bei HQ extrem „999“ als Platzhalter ein
    (-> 1.000 Jahre), Rheinland-Pfalz teils „-9999“ (= keine Angabe).
    """
    values = []
    for f in features:
        text = str((f.get("properties") or {}).get("FL_RECUR") or "").strip()
        if text.startswith("-"):                    # z. B. „-9999“ = keine Angabe
            continue
        for n in (int(v) for v in re.findall(r"\d+", text)):
            if n == 999:
                n = 1000
            if 1 < n < 9999:
                values.append(n)
    return int(np.median(values)) if values else default


# ==========================================================================
# Sturm: tägliche Spitzenböen der DWD-Klimastationen
# ==========================================================================

CDC = "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/daily/kl"
GUST_ATTRIBUTION = "Deutscher Wetterdienst, Klimastationen (tägliche Spitzenböe FX)"


def _stations() -> pd.DataFrame:
    raw = _cached_get(f"{CDC}/recent/KL_Tageswerte_Beschreibung_Stationen.txt", "kl_stationen.txt", 60)
    rows = []
    for line in raw.decode("latin-1").splitlines()[2:]:
        p = line.split()
        if len(p) < 8:
            continue
        rows.append({"id": p[0], "von": p[1], "bis": p[2], "lat": float(p[4]), "lon": float(p[5]),
                     "name": " ".join(p[6:-2])})
    return pd.DataFrame(rows)


def _station_zips(part: str) -> list:
    raw = _cached_get(f"{CDC}/{part}/", f"kl_index_{part}.html", 60)
    return re.findall(r'href="([^"]+\.zip)"', raw.decode("latin-1"))


def _read_kl(content: bytes) -> pd.DataFrame:
    archive = zipfile.ZipFile(io.BytesIO(content))
    name = next(n for n in archive.namelist() if n.startswith("produkt_"))
    df = pd.read_csv(archive.open(name), sep=";", skipinitialspace=True, na_values=[-999, "-999"],
                     dtype={"MESS_DATUM": str})
    df.columns = [c.strip() for c in df.columns]
    return df


def _distance_km(lat, lon, lats, lons):
    p1, p2 = np.radians(lat), np.radians(lats)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lons - lon) / 2) ** 2
    return 2 * 6371 * np.arcsin(np.sqrt(a))


def gust_maxima(lat: float, lon: float, min_years: int = 20, max_km: float = 80, tries: int = 8) -> dict:
    """Jahreshöchstwerte der Spitzenböe (km/h) der nächsten DWD-Station mit langer, aktueller Messreihe.

    Die Böenmessung muss bis in die letzten fünf Jahre reichen (an manchen Stationen
    wurde sie eingestellt). Rückgabe ``{"maxima": pd.Series (Jahr -> km/h), "station",
    "km", "years"}`` oder ``{}``, wenn keine geeignete Station nahe genug ist.
    """
    stations = _stations()
    stations = stations[(stations["von"] <= "20000101") & (stations["bis"] >= "20240101")].copy()
    stations["km"] = _distance_km(lat, lon, stations["lat"].to_numpy(), stations["lon"].to_numpy())
    zips = {"historical": _station_zips("historical"), "recent": _station_zips("recent")}
    for _, st in stations[stations["km"] <= max_km].nsmallest(tries, "km").iterrows():
        frames = []
        for part, names in zips.items():
            for name in names:
                if f"_{st['id']}_" in name:
                    frames.append(_read_kl(_cached_get(f"{CDC}/{part}/{name}", f"kl_{name}")))
        if not frames:
            continue
        df = pd.concat(frames).drop_duplicates("MESS_DATUM", keep="last")
        if "FX" not in df:
            continue
        df = df.dropna(subset=["FX"])
        years = pd.to_datetime(df["MESS_DATUM"], format="%Y%m%d").dt.year
        per_year = df.groupby(years)["FX"].agg(["max", "size"])
        this_year = pd.Timestamp.today().year
        complete = per_year[(per_year["size"] >= 330) & (per_year.index < this_year)]
        if len(complete) >= min_years and complete.index.max() >= this_year - 5:
            return {"maxima": complete["max"] * 3.6, "station": st["name"], "km": float(st["km"]),
                    "years": f"{complete.index.min()}–{complete.index.max()}"}
    return {}


# ==========================================================================
# Wind: stündliche Messwerte der DWD-Stationen (Richtung, Geschwindigkeit)
# ==========================================================================

CDC_WIND = "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/wind"
WIND_ATTRIBUTION = "Deutscher Wetterdienst, stündliche Windmessungen"


def hourly_wind(lat: float, lon: float, years: int = 10, max_km: float = 60, tries: int = 4) -> dict:
    """Stundenwerte des Windes der nächsten aktiven DWD-Station (letzte ``years`` Jahre).

    Rückgabe ``{"hourly": DataFrame (wdir in °, wspd in km/h, Index = Zeit UTC),
    "station", "km"}`` oder ``{}``. Gleiche Spalten wie ``climate_loader``.
    """
    raw = _cached_get(f"{CDC_WIND}/recent/FF_Stundenwerte_Beschreibung_Stationen.txt", "ff_stationen.txt", 60)
    rows = []
    for line in raw.decode("latin-1").splitlines()[2:]:
        p = line.split()
        if len(p) >= 8:
            rows.append({"id": p[0], "von": p[1], "bis": p[2], "lat": float(p[4]), "lon": float(p[5]),
                         "name": " ".join(p[6:-2])})
    stations = pd.DataFrame(rows)
    start = pd.Timestamp.today() - pd.DateOffset(years=years)
    stations = stations[(stations["bis"] >= (pd.Timestamp.today() - pd.Timedelta(days=60)).strftime("%Y%m%d"))
                        & (stations["von"] <= start.strftime("%Y%m%d"))].copy()
    stations["km"] = _distance_km(lat, lon, stations["lat"].to_numpy(), stations["lon"].to_numpy())
    indexes = {part: re.findall(r'href="([^"]+\.zip)"',
                                _cached_get(f"{CDC_WIND}/{part}/", f"ff_index_{part}.html", 60).decode("latin-1"))
               for part in ("historical", "recent")}
    for _, st in stations[stations["km"] <= max_km].nsmallest(tries, "km").iterrows():
        frames = []
        for part, names in indexes.items():
            for name in names:
                if f"_{st['id']}_" in name:
                    content = _cached_get(f"{CDC_WIND}/{part}/{name}", f"ff_{name}")
                    archive = zipfile.ZipFile(io.BytesIO(content))
                    member = next(n for n in archive.namelist() if n.startswith("produkt_"))
                    df = pd.read_csv(archive.open(member), sep=";", skipinitialspace=True,
                                     na_values=[-999, "-999"], dtype={"MESS_DATUM": str})
                    df.columns = [c.strip() for c in df.columns]
                    frames.append(df)
        if not frames:
            continue
        df = pd.concat(frames).drop_duplicates("MESS_DATUM", keep="last")
        df.index = pd.to_datetime(df["MESS_DATUM"], format="%Y%m%d%H")
        df = df[df.index >= start].dropna(subset=["F", "D"]).sort_index()
        if len(df) < 24 * 365 * min(years, 3):
            continue
        hourly = pd.DataFrame({"wdir": df["D"].astype(float), "wspd": df["F"].astype(float) * 3.6}, index=df.index)
        return {"hourly": hourly, "station": st["name"], "km": float(st["km"])}
    return {}


# ==========================================================================
# Erdbeben: Erdbebenzonen nach DIN 4149 / DIN EN 1998-1/NA (GFZ Potsdam)
# ==========================================================================

GFZ_ZONE_URL = "https://ebz.gfz-potsdam.de/index_ug_cms.php"
NOMINATIM_REVERSE = "https://nominatim.openstreetmap.org/reverse"
QUAKE_ATTRIBUTION = "GFZ Potsdam, Erdbebenzonen DIN 4149 / DIN EN 1998-1/NA"


def reverse_place(lat: float, lon: float, timeout: float = 20) -> dict:
    """Gemeinde und Postleitzahl zu einem Punkt (OpenStreetMap Nominatim)."""
    response = _session.get(NOMINATIM_REVERSE, params={"lat": lat, "lon": lon, "format": "jsonv2",
                                                       "addressdetails": 1, "zoom": 18},
                            headers={"Accept-Language": "de"}, timeout=timeout)
    response.raise_for_status()
    address = response.json().get("address", {})
    name = next((address[k] for k in ("city", "town", "village", "municipality") if address.get(k)), "")
    return {"name": name, "postcode": address.get("postcode", ""), "country": address.get("country_code", "")}


def quake_zone(lat: float, lon: float, timeout: float = 30) -> dict:
    """Erdbebenzone (0–3) und geologische Untergrundklasse am Ort; ``zone`` = None: keine Zone.

    Das GFZ bestimmt die Zone für die Ortsmitte der Gemeinde. Außerhalb
    Deutschlands: ``{}``.
    """
    place = reverse_place(lat, lon)
    if place["country"] != "de" or not place["name"]:
        return {}
    def ask(name, postcode):
        response = _session.get(GFZ_ZONE_URL, params={"ortsname": name, "plz": postcode}, timeout=timeout)
        response.raise_for_status()
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", response.text))

    text = ask(place["name"], place["postcode"])
    sentence = re.search(r"gehört[^.]{0,200}\.", text)
    if not sentence and place["postcode"]:
        # Das GFZ kennt je Ort nur die Postleitzahl der Ortsmitte – ohne PLZ noch einmal fragen
        text = ask(place["name"], "")
        sentence = re.search(r"gehört[^.]{0,200}\.", text)
        postcode = re.search(r"\(PLZ: (\d{5})\) in", text)
        if sentence and postcode:
            place = {**place, "postcode": postcode.group(1)}
    if not sentence:
        # mehrere gleichnamige Orte: den mit der nächstgelegenen Ortsmitte nehmen
        rows = re.findall(r"([A-ZÄÖÜ][^°]*?) (?:Baden-Württemberg|Bayern|Berlin|Brandenburg|Bremen|Hamburg|Hessen|"
                          r"Mecklenburg-Vorpommern|Niedersachsen|Nordrhein-Westfalen|Rheinland-Pfalz|Saarland|"
                          r"Sachsen-Anhalt|Sachsen|Schleswig-Holstein|Thüringen) (\d{5}) ([\d.]+)°N, ([\d.]+)°E", text)
        if not rows:
            raise ValueError(f"Erdbebenzone für {place['name']} nicht gefunden")
        best = min(rows, key=lambda r: (float(r[2]) - lat) ** 2 + ((float(r[3]) - lon) * 0.65) ** 2)
        name = best[0].split("Ortsmitte")[-1].strip()
        text = ask(name, best[1])
        sentence = re.search(r"gehört[^.]{0,200}\.", text)
        if not sentence:
            raise ValueError(f"Erdbebenzone für {name} nicht gefunden")
        place = {**place, "name": name, "postcode": best[1]}
    zone = re.search(r"Erdbebenzone (\d)", sentence.group(0))
    subsoil = re.search(r"Untergrundklasse ([A-Z])", sentence.group(0))
    return {"zone": int(zone.group(1)) if zone else None, "subsoil": subsoil.group(1) if subsoil else None,
            "place": place["name"], "postcode": place["postcode"]}
