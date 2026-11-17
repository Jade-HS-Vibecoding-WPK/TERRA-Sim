"""TERRA-Sim – Terrain, Environment & Resilience Simulator.

Start:  streamlit run app.py

Diese Datei richtet nur die Oberfläche ein. Die Seiten liegen in ``views/``,
die wiederverwendbare Rechenarbeit in ``modules/``.
"""

import streamlit as st

from views import navigation
from views.common import ASSETS, SETTINGS_DEFAULTS, load_style, reset_layout

st.set_page_config(page_title="TERRA-Sim", page_icon=str(ASSETS / "icon.svg"), layout="wide")
st.logo(str(ASSETS / "logo.svg"), icon_image=str(ASSETS / "icon.svg"), size="large")
load_style()
reset_layout()   # Bento-Karten je Durchlauf neu nummerieren

# Einstellungen der Analysen sollen beim Seitenwechsel erhalten bleiben.
# Streamlit löscht den Zustand von Bedienelementen, die gerade nicht angezeigt
# werden – das erneute Zuweisen hier verhindert das (offiziell empfohlener Weg).
for key, default in SETTINGS_DEFAULTS.items():
    st.session_state[key] = st.session_state.get(key, default)

pages = navigation.register()
current = st.navigation(list(pages.values()), position="hidden")
navigation.sidebar()
current.run()
