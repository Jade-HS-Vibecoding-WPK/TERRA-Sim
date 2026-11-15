# 🌍 TERRA-Sim – 3D Terrain, Environment & Resilience Simulator

> **Dozenten-Referenzprojekt & Open-Source Boilerplate**  
> Ein interaktives Web-Tool zur automatischen Generierung von 3D-Stadtmodellen (LOD 1–2) und zur heuristischen Simulation von Umweltkatastrophen (Hochwasser, Starkregen, Starkwind).

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Framework](https://img.shields.io/badge/Streamlit-1.32%2B-FF4B4B)
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
│   ├── mesh_builder.py        # Baut das 3D-Modell & exportiert DXF/OBJ
│   └── simulator.py           # Berechnet Hochwasser-, Regen- und Wind-Effekte
│
└── assets/                    # Beispielbilder, Icons, CSS-Styling
