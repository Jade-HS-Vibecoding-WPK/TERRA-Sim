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

## 📂 Geplante Ordnerstruktur (Modular für Studierende)

Damit andere Teams einzelne Funktionen leicht in ihre eigenen Projekte übernehmen können, ist der Code von **TERRA-Sim** strikt getrennt:

```text
terra-sim/
├── app.py                     # Hauptdatei (startet die TERRA-Sim Oberfläche)
├── requirements.txt           # Liste aller benötigten Python-Pakete
├── README.md                  # Projektdokumentation & Konzeptplan
│
├── modules/                   # 🔌 WIEDERVERWENDBARE MODULE FÜR STUDIERENDE
│   ├── map_selector.py        # 2D-Karte & Koordinaten-Auswahl
│   ├── osm_fetcher.py         # Lädt Gebäude, Höhen, Straßen & Grünflächen
│   ├── terrain_loader.py      # Lädt Geländehöhen (DEM)
│   ├── mesh_builder.py        # Baut das 3D-Modell & exportiert DXF/OBJ/STL
│   ├── simulator.py           # Berechnet Hochwasser-, Regen- und Wind-Effekte
│   └── viewer_3d.py           # Zeichnet die 3D-Szene im Browser (pydeck)
│
└── assets/                    # Beispielbilder, Icons, CSS-Styling (geplant)
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

In der App: links einen Beispielort wählen oder eine Adresse suchen, auf
**Modell generieren** klicken und dann über **Ansicht** zwischen 3D-Modell,
Hochwasser, Starkregen und Starkwind wechseln.

> Die erste Abfrage eines Gebiets kann bis zu einer Minute dauern, wenn der
> öffentliche OpenStreetMap-Server (Overpass) ausgelastet ist. Danach liegt
> das Gebiet im lokalen Zwischenspeicher (`.cache/`) und lädt sofort.

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

ort = geocode_address("Schlossplatz, Oldenburg")
bbox = bbox_from_center(ort["lat"], ort["lon"], width_m=500)

osm = fetch_osm(bbox)                    # Gebäude, Straßen, Grün, Wasser
dem = load_dem(bbox)                     # Geländehöhen
gebaeude = osm.buildings.to_crs(metric_crs(bbox))   # in Metern rechnen
print(gebaeude[["building", "height_m", "height_source", "area_m2"]].head())
```

---

## ⚠️ Grenzen der Simulation

TERRA-Sim liefert **Ersteinschätzungen für den Entwurf**, keine Gutachten.

* **Geländehöhen** stammen aus freien globalen Höhenmodellen (30–250 m
  Auflösung, teils mit Gebäuden und Bäumen). In flachen Gebieten können sie
  um mehrere Meter danebenliegen.
* **Gebäudehöhen** sind in OpenStreetMap oft nicht erfasst und werden dann
  aus der Geschosszahl oder dem Gebäudetyp geschätzt.
* **Hochwasser:** Badewannen-Modell ohne Deiche, Fließwege und Zeitverlauf.
* **Starkregen:** ohne Kanalisation und ohne zeitliche Dynamik.
* **Starkwind:** geometrische Sichtlinien-Analyse, keine Strömungssimulation.
