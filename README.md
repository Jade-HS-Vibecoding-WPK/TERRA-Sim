# 🌍 TERRA-Sim – 3D Terrain, Environment & Resilience Simulator

> **Dozenten-Referenzprojekt & Open-Source Boilerplate**  
> Ein interaktives Web-Tool zur automatischen Generierung von 3D-Stadtmodellen (LOD 1–2) und zur heuristischen Simulation von Katastrophen (Hochwasser, Starkregen, Starkwind, Erdbeben, Tornado – und als Planspiele ein Kaiju-Angriff und eine Alien-Invasion).

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
* **3D-Ansicht mit WebGPU** (three.js): Das Gebiet steht wie ein Arbeitsmodell auf einem Geländesockel, mit Sonnenschatten, Umgebungsverdeckung (SSAO) und feinen Gebäudekanten. Gebäude zeigen beim Überfahren ihre Daten; die Kamera bleibt beim Wechsel zwischen den Seiten stehen. Browser ohne WebGPU nutzen automatisch WebGL 2.

### 2. 🌊 Modul A: Hochwasser-Simulation („Bathtub-Model“)
* Abruf eines digitalen Geländemodells zur Bestimmung der realen Topografie: in Niedersachsen, NRW, Bayern, Berlin/Brandenburg, Hessen, Mecklenburg-Vorpommern und Rheinland-Pfalz das **amtliche DGM1** der Landesvermessung (1-m-Raster aus Laserscanning, ohne Gebäude und Bäume), sonst ein weltweites Höhenmodell.
* Stufenloser Schieberegler für den Wasserpegel (`+0.0 m` bis `+10.0 m`).
* **Live-Auswertung:** Visuelle Schnittebene im 3D-Modell; betroffene Gebäude färben sich rot; automatische Berechnung der überfluteten Bruttogrundfläche (BGF) im Erdgeschoss.

### 3. 🌧️ Modul B: Starkregen & Oberflächenabfluss
* Auswahl definierter Starkregen-Szenarien (z. B. Jahrhundertregen: `100 l/m²`).
* Kombination aus topografischen Senken und dem lokalen Versiegelungsgrad (Verhältnis von Straßen/Dächern zu Grünflächen/Parks).
* **Kanalisation und Fallrohre:** Die Kanäle nehmen eine einstellbare Regenmenge auf (Standard 20 l/m²); was darüber hinausgeht, läuft vom Dach über die Fallrohre an die tiefste Stelle neben dem Gebäude.
* **Live-Auswertung:** Heatmap am Boden zur Identifikation von Wasseransammlungen und Rückstau-Risiken.

### 4. 💨 Modul C: Starkwind & Urbane Kamineffekte
* Einstellung von Windrichtung (360°-Kompass) und Windstärke (Beaufort-Skala).
* Geometrische Expositions- und Sichtlinienanalyse (Raycasting light) statt rechenintensiver CFD-Strömungsmechanik.
* **Live-Auswertung:** Markierung ungeschützter, hochbelasteter Fassadenflächen sowie enger Straßenschluchten mit Düseneffekt (Venturi-Effekt).

### 5. 🫨 Modul D: Erdbeben
* Magnitude, Entfernung zum Epizentrum und Untergrund wählen; Vorlagen von „spürbar“ bis „extrem“ (u. a. wie Roermond 1992).
* **Makroseismische Methode** (Lagomarsino & Giovinazzi): Intensität nach EMS-98 am Standort × Verletzbarkeit je Gebäude (Klasse aus Gebäudetyp und Geschosszahl, Zuschläge für Grundrissform und Lage im Block).
* Ergebnis: Schadensgrad 0–5 je Gebäude, schwer beschädigte Gebäude sacken in der 3D-Ansicht zusammen.

### 6. 🌪️ Modul E: Tornado
* Stärke nach Enhanced-Fujita-Skala (EF0–EF5), Zugrichtung und Lage der Bahn.
* Wirbel nach Rankine plus Zuggeschwindigkeit (rechts der Bahn stärker); Schaden je Gebäude aus der Windgeschwindigkeit, leichte Bauten früher, Stahlbeton später.

### 7. 👾 Modul F: Kaiju-Angriff (Planspiel)
* Ein Riesenmonster (eigene Figur, 20–150 m) läuft quer durch das Gebiet: Schneise, Reichweite von Schwanz und Armen, Erschütterung der Schritte.
* **Kampf:** Das Monster feuert Laserstrahlen aus den Augen, Hubschrauber greifen mit Raketen an. Abgeschossene Hubschrauber stürzen in die Stadt, Fehlschüsse treffen Gebäude – alles mit festem Zufall, damit Bild und Schadensbilanz zusammenpassen.
* Zeigt spielerisch, wie man eine Gefahr mit Weg, Reichweite und Schadensstufen modelliert – und welche Gebäude Deckung bieten.

### 8. 🛸 Modul G: Alien-Invasion (Planspiel)
* 1–5 UFOs kreuzen über dem Gebiet, bleiben stehen und holen Menschen mit dem Traktorstrahl hoch; die 3D-Ansicht zählt die Entführungen live mit. Gebäude bleiben heil.

### Animation: Menschen im Gebiet
* Bis zu 1.000 kleine Figuren (Anzahl in der Seitenleiste, 0 = aus) laufen auf Straßen und Wegen und reagieren auf die gewählte Gefahr: Beim Orkan werden sie weggeweht, der Tornado saugt sie hoch, vor dem Monster fliehen sie, Explosionen schleudern sie weg, UFOs holen sie ab, beim Erdbeben stürzen sie, im Hochwasser schwimmen sie.
* Die Figur mit dem Afro und dem Namensschild ist **Nik**. Der Knopf **Nik folgen** in der 3D-Ansicht zoomt auf ihn und hängt die Kamera an ihn – auch wenn er durch die Luft fliegt.
* Tornado, Monster, Hubschrauber und UFOs bewegen sich; beim Erdbeben wackelt das ganze Modell wie auf einem Rütteltisch. Mit dem Knopf **Menschen** lässt sich die Animation anhalten.

---

## 🛠️ Tech-Stack & Architektur

| Bereich | Eingesetzte Bibliotheken / APIs | Funktion in TERRA-Sim |
| :--- | :--- | :--- |
| **Frontend / UI** | `streamlit`, `streamlit-folium` | Benutzeroberfläche, Slider, KPI-Dashboard & 2D-Kartenintegration |
| **Geodaten & GIS** | `osmnx`, `geopandas`, `shapely` | Abruf und geometrische Aufbereitung von OpenStreetMap-Daten |
| **Topografie & Wetter**| DGM1 der Länder (WCS, STAC, Kacheln), `open-elevation API`, `meteostat` | Geländehöhen und historische Klimadaten |
| **3D-Visualisierung** | `three.js` (WebGPU), `pydeck`, `plotly` | 3D-Ansicht mit Schatten und Umgebungsverdeckung im Browser; Diagramme |
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
│   ├── terrain_loader.py      # Lädt Geländehöhen (DEM), mit Rückfall auf weltweite Dienste
│   ├── dgm1_loader.py         # Amtliches DGM1 (1 m) der Bundesländer
│   ├── climate_loader.py      # Lädt Klimadaten (Meteostat): Steckbrief, Windrose
│   ├── mesh_builder.py        # Baut das 3D-Modell & exportiert DXF/OBJ/STL
│   ├── simulator.py           # Berechnet Hochwasser-, Regen- und Wind-Effekte
│   ├── hazards.py             # Erdbeben, Tornado, Kaiju (Schadensgrad 0–5 je Gebäude)
│   ├── viewer_webgpu/         # 3D-Ansicht der App: three.js mit WebGPU (Streamlit-Komponente)
│   │   ├── scene.py           #   baut die Szene (Gelände, Gebäude, Analyse-Ebenen) – nur numpy
│   │   └── frontend/          #   viewer.js rendert, people.js = Menschen, effects.js = Laser, Hubschrauber, UFOs
│   └── viewer_3d.py           # Einfache 3D-Szene mit pydeck (deck.gl) und Farbskalen
│
├── views/                     # 🖥️ SEITEN DER OBERFLÄCHE (Streamlit)
│   ├── navigation.py          # Seitenstruktur, Sperre bis ein Projekt geladen ist
│   ├── common.py              # Gemeinsames: Projektdaten, Kennzahlen, Legenden
│   ├── setup.py               # Projekt anlegen (Standort wählen, Daten laden)
│   ├── overview.py            # Übersicht mit Kennzahlen, Analyse-Kacheln, Exporten
│   ├── climate.py             # Klima am Standort
│   ├── model3d.py             # 3D-Modell & Export
│   ├── flood.py · rain.py · wind.py   # Wetter & Wasser
│   └── earthquake.py · tornado.py · kaiju.py · alien.py   # weitere Katastrophen
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

* **Geländehöhen:** Das amtliche DGM1 ist in sieben Datenquellen eingebunden
  (acht Länder, siehe `modules/dgm1_loader.py`). Die übrigen Länder bieten ihr
  DGM1 nur als große Pakete zum Download an; dort, an Landesgrenzen und im
  Ausland nutzt TERRA-Sim freie globale Höhenmodelle (30–250 m Auflösung,
  teils mit Gebäuden und Bäumen), die in flachen Gebieten um mehrere Meter
  danebenliegen können. Welche Quelle genutzt wurde, steht in der Seitenleiste.
* **Klimadaten** stammen von der nächstgelegenen Station mit ausreichend
  vollständigen Daten, die bis zu 60 km entfernt sein kann. Der stärkste
  Tagesregen ist kein Kurzzeit-Starkregen (z. B. 1 Stunde).
* **Gebäudehöhen** sind in OpenStreetMap oft nicht erfasst und werden dann
  aus der Geschosszahl oder dem Gebäudetyp geschätzt.
* **Hochwasser:** Badewannen-Modell ohne Deiche, Fließwege und Zeitverlauf.
* **Starkregen:** Kanalisation als feste Aufnahmemenge (ohne Rückstau und
  Leitungsnetz), keine zeitliche Dynamik. Ein Gebäude zählt als betroffen,
  wenn daneben mindestens 10 cm Wasser auf mindestens 25 m² stehen.
  Geschlossene Innenhöfe sammeln weiterhin viel Dachwasser.
* **Erdbeben:** Die Bauweise wird aus dem OSM-Gebäudetyp geschätzt, Baujahr
  und Zustand sind unbekannt. Die Intensität ist im ganzen Gebiet gleich.
* **Tornado und Kaiju:** einfache geometrische Modelle (Abstand zur Bahn),
  keine Trümmerflug- oder Strömungsrechnung. Kaiju und Alien-Invasion sind
  Planspiele; die animierten Menschen sind Darstellung, keine Personenstrom-Simulation.
* **Starkwind:** geometrische Sichtlinien-Analyse, keine Strömungssimulation.
* **3D-Ansicht:** Die Bibliothek three.js wird beim Öffnen aus dem Internet geladen
  (jsDelivr). Ohne Internet bleibt die 3D-Ansicht leer – die App braucht für
  OpenStreetMap ohnehin eine Verbindung.
