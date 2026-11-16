"""3D-Ansicht mit WebGPU (three.js) als Streamlit-Komponente.

Der Browser rendert die Szene mit ``WebGPURenderer`` von three.js:
Sonnenlicht mit weichen Schatten, Umgebungsverdeckung (SSAO), Kanten an
den Gebäuden, Geländesockel wie bei einem Arbeitsmodell. Kann der Browser
kein WebGPU, schaltet three.js automatisch auf WebGL 2 um.

* ``scene.py``      baut die Szene (nur numpy, ohne Streamlit)
* ``frontend/``     HTML + JavaScript, das im Browser läuft
* ``show_scene()``  zeigt die Szene in einer Streamlit-App

Die Kamera bleibt beim Ändern von Einstellungen stehen – nur Farben,
Wasserstand usw. werden im Browser ausgetauscht.

Beispiel::

    from modules.viewer_webgpu import scene, show_scene

    origin = scene.origin_of(raster, zmin)
    show_scene({"terrain": scene.terrain(raster, origin)}, key="gelaende")

Die Bibliothek three.js wird beim ersten Öffnen aus dem Internet geladen
(cdn.jsdelivr.net).
"""

from __future__ import annotations

from pathlib import Path

import streamlit.components.v1 as components

from . import scene

FRONTEND = Path(__file__).resolve().parent / "frontend"
_component = components.declare_component("terra_viewer", path=str(FRONTEND))


def show_scene(data: dict, key: str, height: int = 600):
    """Zeigt die Szene ``data`` (siehe ``scene.py``) in der App an."""
    return _component(scene=data, height=int(height), key=key, default=None)


__all__ = ["scene", "show_scene"]
