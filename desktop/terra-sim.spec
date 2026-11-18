# -*- mode: python ; coding: utf-8 -*-
# PyInstaller: baut TERRA-Sim als Windows-Programm in dist/TERRA-Sim/.
#
#   python desktop/make_icon.py
#   pyinstaller desktop/terra-sim.spec --noconfirm
#
# Die Seiten (views/) und Module (modules/) kommen als kompilierter Code ins Programm;
# app.py, assets/, das Farbschema und der 3D-Viewer liegen als Dateien daneben, weil
# Streamlit sie zur Laufzeit von der Festplatte liest.

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).parent

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
hiddenimports += collect_submodules("views") + collect_submodules("modules")

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
