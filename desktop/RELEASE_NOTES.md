## TERRA-Sim 1.0 – Terrain, Environment & Resilience Simulator

3D-Stadtmodell aus offenen Daten und Katastrophen-Analysen mit amtlichen Wahrscheinlichkeiten – jetzt auch als Programm für Windows.

### Herunterladen

| Datei | Für wen |
| :--- | :--- |
| **TERRA-Sim-1.0-Setup.exe** | Installer für Windows 10/11 (64 Bit), ohne Administratorrechte. Legt TERRA-Sim im Startmenü an, auf Wunsch auch auf dem Desktop. |
| **TERRA-Sim-1.0-Windows-portabel.zip** | Ohne Installation: entpacken und `TERRA-Sim.exe` starten, z. B. vom USB-Stick. |

**Beim ersten Start:**
- Das Programm ist nicht signiert, deshalb zeigt Windows SmartScreen eventuell eine Warnung. Starten über **Weitere Informationen → Trotzdem ausführen**.
- Der erste Start dauert etwas länger. TERRA-Sim öffnet sich dann in einem eigenen Fenster über Microsoft Edge oder Google Chrome. Ohne beide öffnet es sich im Standard-Browser.
- Für Gebäude, Gelände, Klima und amtliche Daten braucht TERRA-Sim eine Internetverbindung.
- Zwischenspeicher und Protokolle liegen unter `%LOCALAPPDATA%\TERRA-Sim`.

### Weiterhin im Browser

- **Live-Demo ohne Installation:** https://jade-hs-vibecoding-wpk.github.io/TERRA-Sim/ – ein fertig berechnetes Beispielgebiet mit 3D-Ansicht und allen Gefahren.
- **Aus dem Quellcode,** auf jedem Betriebssystem: `pip install -r requirements.txt`, dann `streamlit run app.py`.

### Was TERRA-Sim kann

- **Projektgebiet:**
  - Gebiet auf der Karte wählen.
  - Gebäude, Straßen und Flächen aus OpenStreetMap, Gelände aus dem amtlichen DGM1 (1 m), Klima der nächsten Wetterstation.
  - 3D-Modell mit Export für CAD und 3D-Druck.
- **Analysen:**
  - Hochwasser, Starkregen, Starkwind (mit Luftströmung und Windrose), Erdbeben, Tornado.
  - Als Planspiele ein Kaiju-Angriff und eine Alien-Invasion.
  - Animierte Menschen, einer davon ist Nik.
- **Wie wahrscheinlich ist das?** Wiederkehrzeit und Chance in 30 Jahren aus amtlichen Daten:
  - KOSTRA-DWD-2020,
  - Hochwassergefahrenkarten der Länder,
  - DWD-Böen und -Wind,
  - GFZ-Erdbebenzonen,
  - DWD-Tornadostatistik.
- **Methoden & Quellen:** jeder Rechenweg mit Formeln, Annahmen und Grenzen, 48 Quellen mit DOI-Links und BibTeX-Export.
- **Qualität:** 93 automatische Tests, die bei jeder Änderung laufen.

TERRA-Sim ist eine heuristische Ersteinschätzung für Entwurf und Lehre, kein Gutachten.

Daten: © OpenStreetMap-Mitwirkende (ODbL) · Geobasisdaten der Länder (DGM1) · Deutscher Wetterdienst (CC BY 4.0) · Meteostat · GFZ Potsdam · Hochwassergefahrenkarten der Länder (BfG-Geoportal).
