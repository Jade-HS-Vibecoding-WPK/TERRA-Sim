# assets/

Gestaltungsdateien für die TERRA-Sim-Oberfläche.

| Datei | Verwendung |
| :--- | :--- |
| `logo.svg` | Wortbildmarke oben in der Seitenleiste (`st.logo`) |
| `icon.svg` | Bildmarke allein: eingeklappte Seitenleiste und Browser-Tab |
| `style.css` | Zusätzliches Styling: Schrittanzeige, Projektkarte, Analyse-Kacheln, Ampeln, Legenden |

Die Grundfarben (Primärfarbe, Hintergrund, Schrift) stehen in
`.streamlit/config.toml`. Wer die Farbe ändern will, passt sie dort **und**
in `style.css` (Variable `--terra-primary`) an.

Eigene Projekte können die Dateien frei übernehmen und austauschen.
