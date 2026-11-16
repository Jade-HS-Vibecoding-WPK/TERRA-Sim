# 🌍 TERRA-Sim – 3D Terrain, Environment & Resilience Simulator

> **Dozenten-Referenzprojekt & Open-Source Boilerplate**  
> Ein interaktives Web-Tool zur automatischen Generierung von 3D-Stadtmodellen (LOD 1–2) und zur heuristischen Simulation von Umweltkatastrophen (Hochwasser, Starkregen, Starkwind).

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Framework](https://img.shields.io/badge/Streamlit-1.40%2B-FF4B4B)
![GIS](https://img.shields.io/badge/Data-OpenStreetMap%20%7C%20SRTM-green)
![AI-Assisted](https://img.shields.io/badge/Built%20with-Claude%20Pro%20%2F%20Code-purple)

---

## 🎯 Über das Projekt

**TERRA-Sim** (*Terrain, Environment & Resilience Simulator*) verfolgt im Rahmen des Seminars zwei zentrale Ziele:

1. **Inhaltlich (Climate Resilience Tool):** Städtebauliche Entwürfe müssen heute extremen Wetterereignissen standhalten. **TERRA-Sim** ermöglicht es, jeden beliebigen Ort auf der Welt auszuwählen, in Sekunden ein 3D-Umgebungsmodell inklusive Topografie zu generieren und erste Risiko-Analysen für Hochwasser, Starkregen und Sturm durchzuführen – direkt im Browser und ohne komplexe Simulationssoftware.
2. **Didaktisch (Kurs-Boilerplate):** Die Codebasis von **TERRA-Sim** ist streng modular aufgebaut. Alle Studierenden-Teams im Kurs können einzelne Module (z. B. den Karten-Selektor, den OSM-Datenabruf oder den 3D-Export) frei kopieren und als Fundament für ihre eigenen Werkzeuge (Laser-Cutter-Generatoren, Standortanalysen, Verschattungsrechner etc.) nutzen.

---

## ✨ Kernfunktionen

### Arbeitsablauf: erst das Gebiet, dann die Werkzeuge
Angelehnt an Planungswerkzeuge wie Autodesk Forma beginnt jede Sitzung mit einem **Projekt**:

1. **Standort wählen** – über Adresse, Koordinaten, Beispielort, Klick oder Rechteck auf der Karte, oder eine gespeicherte Projektdatei öffnen.
2. **Daten laden** – Gebäude, Straßen, Grün- und Wasserflächen (OpenStreetMap), Gelände (Höhenmodell) und Klimadaten der nächsten Wetterstation (Meteostat).
3. **Analysieren** – erst jetzt werden Übersicht, Klima, 3D-Modell und die drei Analysen in der Seitenleiste freigeschaltet.

Die **Übersicht** zeigt Gebietskennzahlen (GRZ, GFZ, Versiegelung, Grünanteil), den Klima-Steckbrief und je Analyse eine Kachel mit Ampel. Projekt, Kennzahlen (CSV) und alle Gebäude mit ihren Ergebnissen (GeoJSON, z. B. für QGIS) lassen sich exportieren.

### 0. 🌦️ Klima am Standort (Meteostat)
* Messdaten der nächstgelegenen Wetterstationen der letzten 10 Jahre (Wind: 3 Jahre stündlich).
* Klimadiagramm, Windrose, Extremwerte je Jahr, Kennzahlen wie heiße Tage, Frosttage, Starkregentage, Sturmtage.
* **Verknüpft mit den Analysen:** Hauptwindrichtung bei Starkwind und gemessene Windstärken als Wind-Szenarien, der stärkste gemessene Tagesregen als Starkregen-Szenario.

### 1. 🗺️ Geo-Selector & 3D-Modellgenerator (LOD 1–2)
* Auswahl eines beliebigen Untersuchungsgebiets über Adresssuche oder Bounding-Box auf einer interaktiven 2D-Karte.
* Automatischer Abruf von Gebäude-Grundrissen, Geschosszahlen, Straßen und Grünflächen über OpenStreetMap (`osmnx`).
* Extrusion zu einem 3D-Modell: **LOD 1** (Klötzchenmodell auf Basis realer Höhen oder Geschoss-Schätzungen) und **LOD 2** (Annäherung einfacher Dachformen, sofern in OSM hinterlegt).

### 2. 🌊 Modul A: Hochwasser-Simulation („Bathtub-Model“)
* Abruf eines digitalen Geländemodells (DEM) zur Bestimmung der realen Topografie.
* Stufenloser Schieberegler für den Wasserpegel (`+0.0 m` bis `+10.0 m`).
* **Live-Auswertung:** Visuelle Schnittebene im 3D-Modell; betroffene Gebäude färben sich rot; automatische Berechnung der überfluteten Bruttogrundfläche (BGF) im Erdgeschoss.

### 3. 🌧️ Modul B: Starkregen & Oberflächenabfluss
* Auswahl definierter Starkregen-Szenarien (z. B. Jahrhundertregen: `100 l/m²`).
* Kombination aus topografischen Senken und dem lokalen Versiegelungsgrad (Verhältnis von Straßen/Dächern zu Grünflächen/Parks).
* **Live-Auswertung:** Heatmap am Boden zur Identifikation von Wasseransammlungen und Rückstau-Risiken.

### 4. 💨 Modul C: Starkwind & Urbane Kamineffekte
* Einstellung von Windrichtung (360°-Kompass) und Windstärke (Beaufort-Skala).
* Geometrische Expositions- und Sichtlinienanalyse (Raycasting light) statt rechenintensiver CFD-Strömungsmechanik.
* **Live-Auswertung:** Markierung ungeschützter, hochbelasteter Fassadenflächen sowie enger Straßenschluchten mit Düseneffekt (Venturi-Effekt).

---

## 🛠️ Tech-Stack & Architektur

| Bereich | Eingesetzte Bibliotheken / APIs | Funktion in TERRA-Sim |
| :--- | :--- | :--- |
| **Frontend / UI** | `streamlit`, `streamlit-folium` | Benutzeroberfläche, Slider, KPI-Dashboard & 2D-Kartenintegration |
| **Geodaten & GIS** | `osmnx`, `geopandas`, `shapely` | Abruf und geometrische Aufbereitung von OpenStreetMap-Daten |
| **Topografie & Wetter**| `open-elevation API`, `meteostat` | Geländehöhen (DEM) und historische Klimadaten |
| **3D-Visualisierung** | `pydeck` (deck.gl), `plotly` | Hardwarebeschleunigtes 3D-Rendering im Webbrowser |
| **CAD / 3D-Export** | `trimesh`, `ezdxf` | Export der 3D-Geometrien als `.obj`, `.stl` oder `.dxf` |

---

## 📂 Ordnerstruktur (Modular für Studierende)

Damit andere Teams einzelne Funktionen leicht in ihre eigenen Projekte übernehmen können, ist der Code von **TERRA-Sim** strikt getrennt:

```text
terra-sim/
├── app.py                     # Hauptdatei (richtet Oberfläche und Navigation ein)
├── requirements.txt           # Liste aller benötigten Python-Pakete
├── README.md                  # Projektdokumentation & Konzeptplan
├── .streamlit/config.toml     # Farbschema der Oberfläche
│
├── modules/                   # 🔌 WIEDERVERWENDBARE MODULE FÜR STUDIERENDE
│   ├── map_selector.py        # 2D-Karte & Koordinaten-Auswahl
│   ├── osm_fetcher.py         # Lädt Gebäude, Höhen, Straßen & Grünflächen
│   ├── terrain_loader.py      # Lädt Geländehöhen (DEM)
│   ├── climate_loader.py      # Lädt Klimadaten (Meteostat): Steckbrief, Windrose
│   ├── mesh_builder.py        # Baut das 3D-Modell & exportiert DXF/OBJ/STL
│   ├── simulator.py           # Berechnet Hochwasser-, Regen- und Wind-Effekte
│   └── viewer_3d.py           # Zeichnet die 3D-Szene im Browser (pydeck)
│
├── views/                     # 🖥️ SEITEN DER OBERFLÄCHE (Streamlit)
│   ├── navigation.py          # Seitenstruktur, Sperre bis ein Projekt geladen ist
│   ├── common.py              # Gemeinsames: Projektdaten, Kennzahlen, Legenden
│   ├── setup.py               # Projekt anlegen (Standort wählen, Daten laden)
│   ├── overview.py            # Übersicht mit Kennzahlen, Analyse-Kacheln, Exporten
│   ├── climate.py             # Klima am Standort
│   ├── model3d.py             # 3D-Modell & Export
│   └── flood.py · rain.py · wind.py   # die drei Analysen
│
└── assets/                    # Logo, Icon und CSS-Styling
```

---

## 🚀 Schnellstart

Voraussetzung: Python 3.10 oder neuer.

```bash
# 1. Virtuelle Umgebung anlegen und aktivieren
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS / Linux

# 2. Pakete installieren
pip install -r requirements.txt

# 3. App starten (öffnet sich im Browser unter http://localhost:8501)
streamlit run app.py
```

In der App: Standort wählen (Adresse, Koordinaten, Beispielort oder Klick auf
die Karte), auf **Projekt anlegen & Daten laden** klicken und danach in der
Seitenleiste zwischen Übersicht, Klima, 3D-Modell und den Analysen wechseln.

> Die erste Abfrage eines Gebiets kann bis zu einer Minute dauern, wenn der
> öffentliche OpenStreetMap-Server (Overpass) ausgelastet ist. Danach liegt
> das Gebiet im lokalen Zwischenspeicher (`.cache/`) und lädt sofort.

> Ein Neuladen der Browserseite beendet die Sitzung. Mit **Speichern** in der
> Seitenleiste lässt sich das Projekt als Datei sichern und später über den
> Reiter **Projektdatei** wieder öffnen.

---

## 🔌 Module einzeln verwenden

Jedes Modul funktioniert ohne die App und ohne die anderen Module. Sie
tauschen nur einfache Datentypen aus: eine Bounding-Box als Tupel
`(west, south, east, north)`, Geodaten als `GeoDataFrame`, Raster als
`numpy`-Arrays.

```python
from modules.map_selector import geocode_address, bbox_from_center
from modules.osm_fetcher import fetch_osm, metric_crs
from modules.terrain_loader import load_dem
from modules.climate_loader import load_climate, climate_summary

ort = geocode_address("Schlossplatz, Oldenburg")
bbox = bbox_from_center(ort["lat"], ort["lon"], width_m=500)

osm = fetch_osm(bbox)                    # Gebäude, Straßen, Grün, Wasser
dem = load_dem(bbox)                     # Geländehöhen
gebaeude = osm.buildings.to_crs(metric_crs(bbox))   # in Metern rechnen
print(gebaeude[["building", "height_m", "height_source", "area_m2"]].head())

klima = load_climate(ort["lat"], ort["lon"])        # Meteostat-Messdaten
print(climate_summary(klima)["prcp_max_day"])       # stärkster Tagesregen (mm)
```

---

## ⚠️ Grenzen der Simulation

TERRA-Sim liefert **Ersteinschätzungen für den Entwurf**, keine Gutachten.

* **Geländehöhen** stammen aus freien globalen Höhenmodellen (30–250 m
  Auflösung, teils mit Gebäuden und Bäumen). In flachen Gebieten können sie
  um mehrere Meter danebenliegen. Das wirkt sich besonders auf den Starkregen
  aus: Scheinbare Senken im Höhenmodell erscheinen als Wasseransammlungen.
* **Klimadaten** stammen von der nächstgelegenen Station mit ausreichend
  vollständigen Daten, die bis zu 60 km entfernt sein kann. Der stärkste
  Tagesregen ist kein Kurzzeit-Starkregen (z. B. 1 Stunde).
* **Gebäudehöhen** sind in OpenStreetMap oft nicht erfasst und werden dann
  aus der Geschosszahl oder dem Gebäudetyp geschätzt.
* **Hochwasser:** Badewannen-Modell ohne Deiche, Fließwege und Zeitverlauf.
* **Starkregen:** ohne Kanalisation und ohne zeitliche Dynamik.
* **Starkwind:** geometrische Sichtlinien-Analyse, keine Strömungssimulation.
