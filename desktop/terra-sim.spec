# -*- mode: python ; coding: utf-8 -*-
# PyInstaller: baut TERRA-Sim als Windows-Programm in dist/TERRA-Sim/.
#
#   python desktop/make_icon.py
#   pyinstaller desktop/terra-sim.spec --noconfirm
#
# Die Seiten (views/) und Module (modules/) kommen als kompilierter Code ins Programm;
# app.py, assets/, das Farbschema und der 3D-Viewer liegen als Dateien daneben, weil
# Streamlit sie zur Laufzeit von der Festplatte liest.

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).parent
# Ohne diese Zeile findet collect_submodules die eigenen Pakete views/ und modules/ nur, wenn
# PyInstaller zufällig aus dem Projektordner heraus gestartet wird (python -m PyInstaller).
sys.path.insert(0, str(ROOT))

datas, binaries, hiddenimports = [], [], []
# Pakete mit Dateien neben dem Code (Weboberfläche, Vorlagen, Kartenanbieter, Schriften …)
for package in ("streamlit", "streamlit_folium", "folium", "branca", "xyzservices", "pydeck", "meteostat",
                "osmnx", "trimesh", "ezdxf"):
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h
# Versionsangaben, die Pakete zur Laufzeit über importlib.metadata abfragen
for dist in ("streamlit", "streamlit-folium", "folium", "pydeck", "plotly", "meteostat", "osmnx", "geopandas",
             "pyproj", "shapely", "numpy", "pandas", "requests", "packaging", "altair", "pyarrow", "protobuf",
             "tornado", "click", "trimesh", "ezdxf", "scipy", "pillow", "networkx"):
    try:
        datas += copy_metadata(dist)
    except Exception:
        pass
# Nicht ins Programm: Streamlits Vorlagen für KI-Assistenten (.agents/) – zur Laufzeit unnötig und mit
# bis zu 127 Zeichen so tief verschachtelt, dass der Installer in längeren Zielordnern an der
# Windows-Pfadgrenze (260 Zeichen) scheitert.
SKIP_PARTS = {".agents"}
datas = [(src, dest) for src, dest in datas if not SKIP_PARTS & set(Path(dest).parts)]

own = collect_submodules("views") + collect_submodules("modules")
if not {"views.navigation", "modules.methods"} <= set(own):
    raise SystemExit(f"views/ und modules/ nicht gefunden – nur {own}")
hiddenimports += own

datas += [
    (str(ROOT / "app.py"), "."),
    (str(ROOT / "assets"), "assets"),
    (str(ROOT / ".streamlit" / "config.toml"), ".streamlit"),
    (str(ROOT / "modules" / "viewer_webgpu" / "frontend"), "modules/viewer_webgpu/frontend"),
    (str(ROOT / "desktop" / "icon.ico"), "."),
]

a = Analysis(
    [str(ROOT / "desktop" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tests", "pytest", "IPython", "jupyter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TERRA-Sim",
    icon=str(ROOT / "desktop" / "icon.ico"),
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="TERRA-Sim", upx=False)

# Pfadlängen begrenzen: Mit höchstens 110 Zeichen unter dem Programmordner bleibt für den
# Installationsort (z. B. C:\Users\<Name>\AppData\Local\Programs\TERRA-Sim) genug Luft bis 260.
MAX_RELATIVE_PATH = 110
longest = max((len("_internal/" + name) for name, *_ in [*a.datas, *a.binaries]), default=0)
if longest > MAX_RELATIVE_PATH:
    worst = max((name for name, *_ in [*a.datas, *a.binaries]), key=len)
    raise SystemExit(f"Pfad zu lang ({longest} Zeichen): _internal/{worst}")
print(f"Längster Pfad im Programm: {longest} Zeichen (Grenze {MAX_RELATIVE_PATH})")
