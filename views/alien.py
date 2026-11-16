"""Modul G: Alien-Invasion (Planspiel) – UFOs holen Menschen aus dem Gebiet."""

from __future__ import annotations

import streamlit as st

from modules.viewer_webgpu import scene as vscene
from views.common import GREY, num, page_header, scene_for, show_scene

PRESETS = {"Erkundung · 1 kleines UFO": (1, 20, 50), "Invasion · 3 UFOs": (3, 30, 60),
           "Mutterschiff · 1 riesiges UFO": (1, 80, 120)}


def _apply(count: int, size: int, height: int):
    st.session_state.alien_ufos = count
    st.session_state.alien_size = size
    st.session_state.alien_height = height


def render():
    from views.navigation import require_project

    model = require_project()
    page_header("Alien-Invasion", "Planspiel: UFOs kreuzen über dem Gebiet, bleiben stehen und holen mit dem "
                                  "Traktorstrahl Menschen nach oben. Gebäude bleiben heil.")
    ss = st.session_state
    raster = model.raster
    extent = max(raster.nx, raster.ny) * raster.cell

    left, right = st.columns([1, 2.6], gap="large")
    with left:
        with st.container(border=True):
            st.markdown("**Szenario**")
            for label, values in PRESETS.items():
                st.button(label, key=f"alien_{label}", width="stretch", on_click=_apply, args=values)
        with st.container(border=True):
            st.slider("Anzahl UFOs", 1, 5, key="alien_ufos")
            st.slider("Durchmesser", 10, 80, step=5, format="%d m", key="alien_size")
            st.slider("Flughöhe", 25, 150, step=5, format="%d m", key="alien_height")
        beam = 0.9 * ss.alien_size
        st.caption(f"Jedes UFO fliegt 5 Sekunden, bleibt dann stehen und strahlt 4 Sekunden lang einen Kreis "
                   f"von {num(beam)} m Durchmesser ab. Wer in der Nähe ist, rennt weg – wer im Strahl steht, "
                   "schwebt nach oben. Der Zähler unten rechts in der 3D-Ansicht zählt mit.")
        st.caption("Tipp: Mit „Nik folgen“ in der 3D-Ansicht sieht man, ob Nik entkommt.")

    with right:
        c = st.columns(4)
        c[0].metric("UFOs", num(ss.alien_ufos))
        c[1].metric("Strahl-Durchmesser", f"{num(beam)} m")
        c[2].metric("Flughöhe", f"{num(ss.alien_height)} m")
        c[3].metric("Menschen im Gebiet", num(ss.people_count),
                    help="Einstellbar in der Seitenleiste unter „Darstellung“")
        scene = scene_for(model, colors=[GREY] * len(model.buildings),
                          ufos=vscene.ufos(ss.alien_ufos, ss.alien_size, ss.alien_height, extent),
                          hazard=vscene.hazard("alien"))
        show_scene(scene, key="scene_alien", height=640)
        if ss.people_count == 0:
            st.info("Es sind keine Menschen im Gebiet – die UFOs finden niemanden. "
                    "Die Anzahl lässt sich in der Seitenleiste einstellen.")
