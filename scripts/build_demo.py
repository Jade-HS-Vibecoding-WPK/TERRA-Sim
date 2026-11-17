"""Baut die Daten für die Live-Demo auf GitHub Pages (Ordner ``demo/``).

GitHub Pages kann nur statische Dateien ausliefern, TERRA-Sim braucht aber
Python. Dieses Skript rechnet deshalb ein Beispielgebiet mit dem echten Code
durch – jede Analyseseite läuft einmal mit ihren Standard-Einstellungen – und
speichert, was die Seiten anzeigen würden:

* die Szene für den 3D-Viewer (``modules/viewer_webgpu``),
* die Kennzahl-Kacheln, Legenden und die Karte „So entsteht die Zahl“,
* die Wahrscheinlichkeiten aller Gefahren.

Aufruf (im Projektordner, mit der virtuellen Umgebung)::

    python scripts/build_demo.py
    python scripts/build_demo.py --name "Oldenburg Innenstadt" --lat 53.1405 --lon 8.2146 --side 600

Die Seite selbst liegt in ``demo/`` (index.html, demo.js, demo.css); der
Workflow ``.github/workflows/pages.yml`` veröffentlicht sie zusammen mit dem
Viewer aus ``modules/viewer_webgpu/frontend``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "demo" / "data"

# Reihenfolge der Reiter in der Demo: Schlüssel -> (Modul in views/, Titel)
PAGES = {
    "modell": ("model3d", "3D-Modell"),
    "hochwasser": ("flood", "Hochwasser"),
    "starkregen": ("rain", "Starkregen"),
    "starkwind": ("wind", "Starkwind"),
    "erdbeben": ("earthquake", "Erdbeben"),
    "tornado": ("tornado", "Tornado"),
    "kaiju": ("kaiju", "Kaiju-Angriff"),
    "aliens": ("alien", "Alien-Invasion"),
}


def _render_page():
    """Läuft als Streamlit-Skript (AppTest): Projekt laden, eine Seite rendern, alles mitschreiben."""
    import html
    import json
    import os
    import re
    import sys

    root = os.environ["TERRA_DEMO_ROOT"]
    sys.path.insert(0, root)
    os.chdir(root)

    import streamlit as st
    from streamlit.delta_generator import DeltaGenerator

    import modules.viewer_webgpu as viewer_webgpu
    import views.common as vc
    from modules.map_selector import bbox_center, bbox_from_center, bbox_size_m

    page_key, module_name = os.environ["TERRA_DEMO_PAGE"], os.environ["TERRA_DEMO_MODULE"]
    out = {"metrics": [], "legends": [], "side": [], "scene": None, "odds_key": None, "explain": ""}
    mode = {"side": False}

    def md_html(text: str) -> str:
        text = html.escape(str(text))
        return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)

    # --- mitschreiben, was die Seite anzeigt ------------------------------------------
    # Originale nur beim ersten Lauf merken – sonst stapeln sich die Hüllen über die Läufe
    if not hasattr(st, "_terra_demo_orig"):
        st._terra_demo_orig = {"metric": DeltaGenerator.metric,
                               **{n: getattr(st, n) for n in ("markdown", "caption", "html")}}
    originals = st._terra_demo_orig
    orig_metric = originals["metric"]

    def metric(self, label, value, *args, **kwargs):
        out["metrics"].append({"label": str(label), "value": str(value), "help": kwargs.get("help")})
        return orig_metric(self, label, value, *args, **kwargs)

    DeltaGenerator.metric = metric

    for name in ("markdown", "caption", "html"):
        original = originals[name]

        def wrapper(body, *args, _name=name, _orig=original, **kwargs):
            if _name == "html" and "terra-legend" in str(body) and not mode["side"]:
                out["legends"].append(str(body))
            if mode["side"]:
                if _name == "html":
                    out["side"].append(str(body))
                elif _name == "markdown":
                    out["side"].append(f'<p class="side-title">{md_html(body)}</p>')
                else:
                    out["side"].append(f'<p class="side-note">{md_html(body)}</p>')
            return _orig(body, *args, **kwargs)

        setattr(st, name, wrapper)

    def show_scene(data, key, height=600):
        out["scene"] = data

    viewer_webgpu.show_scene = show_scene

    def odds_row(model, key, explain="", side=None):
        out["odds_key"], out["explain"] = key, explain
        if side is not None:
            mode["side"] = True
            try:
                side()
            finally:
                mode["side"] = False

    vc.odds_row = odds_row          # vor dem Import der Seiten, die es per Name importieren

    # --- Projekt anlegen wie views/setup.create_project --------------------------------
    ss = st.session_state
    for key, default in vc.SETTINGS_DEFAULTS.items():
        ss[key] = ss.get(key, default)
    lat, lon, side_m = (float(os.environ[k]) for k in ("TERRA_DEMO_LAT", "TERRA_DEMO_LON", "TERRA_DEMO_SIDE"))
    bbox = bbox_from_center(lat, lon, side_m)
    osm = vc.cached_osm(bbox)
    dem = vc.cached_dem(bbox)
    climate, climate_error = None, ""
    try:
        climate = vc.cached_climate(*(round(v, 3) for v in bbox_center(bbox)))
    except Exception as error:            # Klimadaten sind optional
        climate_error = str(error)
    model = vc.build_model(os.environ["TERRA_DEMO_NAME"], bbox, osm, dem, climate, climate_error)
    vc.warm_official_data(model)
    ss.model = model
    if model.climate_ok:
        info = vc.climate_info(model)
        if info.get("wind_dir_strong") is not None:
            ss.wind_dir = int(round(info["wind_dir_strong"] / 5) * 5) % 360

    from views import navigation
    navigation.register()
    page = __import__(f"views.{module_name}", fromlist=["render"])
    if hasattr(page, "odds_row"):     # Seiten sind evtl. schon aus einem früheren Lauf importiert
        page.odds_row = odds_row
    vc.reset_layout()
    page.render()

    # --- Wahrscheinlichkeiten und Projektangaben -------------------------------------------
    from modules.likelihood import LIFETIME_YEARS, one_in, percent
    odds = {}
    for key, (o, source) in vc.scenario_odds(model).items():
        odds[key] = {"text": o.get("text"), "level": o.get("level"), "T": o.get("T"),
                     "p_life": o.get("p_life"), "p_year": o.get("p_year"),
                     "life": percent(o.get("p_life")), "year": percent(o.get("p_year")),
                     "one_in": one_in(o.get("p_life")) if o.get("p_life") else "", "source": source}
    width, height = bbox_size_m(model.bbox)
    out["project"] = {
        "name": model.name, "lat": round(model.center[0], 5), "lon": round(model.center[1], 5),
        "width_m": round(width), "height_m": round(height), "buildings": int(len(model.buildings)),
        "terrain": model.dem.attribution or model.dem.source,
        "climate": model.climate.attribution if model.climate_ok else "",
        "lifetime_years": LIFETIME_YEARS,
    }
    out["odds"] = odds
    num, where = vc.num, vc.wind_direction_label
    out["scenario"] = {
        "modell": f"{ss.model_lod}, {len(model.buildings)} Gebäude aus OpenStreetMap",
        "hochwasser": f"Pegel +{num(ss.flood_gauge, 1)} m über dem Bezugsniveau „{ss.flood_ref}“",
        "starkregen": f"{ss.rain_scenario} in {ss.rain_duration}, die Kanalisation nimmt {ss.rain_sewer} l/m² auf",
        "starkwind": f"Beaufort {ss.wind_bft} aus {where(ss.wind_dir)} – der häufigsten Richtung bei Starkwind",
        "erdbeben": f"Magnitude {num(ss.quake_mw, 1)} in {ss.quake_dist_km} km Entfernung, Untergrund {ss.quake_soil}",
        "tornado": f"EF{ss.tornado_ef}, zieht nach {where(ss.tornado_heading)}",
        "kaiju": f"{ss.kaiju_height} m groß, läuft nach {where(ss.kaiju_heading)}, {ss.kaiju_lasers} Laserstrahlen, "
                 f"{ss.kaiju_helis} Hubschrauber",
        "aliens": f"{ss.alien_ufos} UFOs mit {ss.alien_size} m Durchmesser in {ss.alien_height} m Höhe",
    }[page_key]
    with open(os.environ["TERRA_DEMO_OUT"], "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, default=str)


def build(name: str, lat: float, lon: float, side: float, only: list[str] | None = None):
    from streamlit.testing.v1 import AppTest

    OUT.mkdir(parents=True, exist_ok=True)
    raw_dir = ROOT / ".cache" / "demo"
    raw_dir.mkdir(parents=True, exist_ok=True)
    os.environ.update({"TERRA_DEMO_ROOT": str(ROOT), "TERRA_DEMO_NAME": name, "TERRA_DEMO_LAT": str(lat),
                       "TERRA_DEMO_LON": str(lon), "TERRA_DEMO_SIDE": str(side)})
    results = {}
    for key, (module, title) in PAGES.items():
        raw = raw_dir / f"{key}.json"
        if only and key not in only and raw.exists():
            results[key] = json.loads(raw.read_text(encoding="utf-8"))
            continue
        started = time.time()
        os.environ.update({"TERRA_DEMO_PAGE": key, "TERRA_DEMO_MODULE": module, "TERRA_DEMO_OUT": str(raw)})
        app = AppTest.from_function(_render_page, default_timeout=900)
        app.run()
        if app.exception:
            raise RuntimeError(f"{title}: " + "\n".join(str(e.value) for e in app.exception))
        results[key] = json.loads(raw.read_text(encoding="utf-8"))
        print(f"{title}: {time.time() - started:.0f} s, {len(results[key]['metrics'])} Kennzahlen")

    # Gemeinsame Teile der Szenen (Gelände, Karte, Gebäude, Wege) nur einmal speichern
    scenes = {k: r["scene"] or {} for k, r in results.items()}
    first = next(iter(scenes.values()))
    shared = {k: v for k, v in first.items()
              if all(json.dumps(s.get(k), sort_keys=True) == json.dumps(v, sort_keys=True) for s in scenes.values())}
    _write(OUT / "base.json", shared)

    last = results[list(PAGES)[-1]]
    pages = []
    for key, (module, title) in PAGES.items():
        r = results[key]
        delta = {k: v for k, v in (r["scene"] or {}).items() if k not in shared}
        _write(OUT / f"{key}.json", {
            "scene": delta, "metrics": r["metrics"], "legends": r["legends"], "side": r["side"],
            "odds_key": r["odds_key"], "explain": r["explain"], "scenario": r["scenario"],
        })
        pages.append({"key": key, "title": title, "odds_key": r["odds_key"]})
    _write(OUT / "project.json", {"project": last["project"], "odds": last["odds"], "pages": pages,
                                  "built": time.strftime("%Y-%m-%d")})
    total = sum(p.stat().st_size for p in OUT.glob("*.json"))
    print(f"Fertig: {OUT} ({total / 1e6:.1f} MB)")


def _write(path: Path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--name", default="Jade Hochschule Wilhelmshaven")
    parser.add_argument("--lat", type=float, default=53.5476)
    parser.add_argument("--lon", type=float, default=8.0884)
    parser.add_argument("--side", type=float, default=600, help="Kantenlänge des Gebiets in Metern")
    parser.add_argument("--only", nargs="*", help="nur diese Seiten neu rechnen (Rest aus .cache/demo)")
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    build(args.name, args.lat, args.lon, args.side, args.only)
