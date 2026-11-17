"""Wie wahrscheinlich ist ein Szenario am Standort? (Wiederkehrzeiten)

Die Analysen in ``simulator.py`` und ``hazards.py`` rechnen aus, *was*
passiert. Dieses Modul schätzt, *wie oft* so etwas am Standort vorkommt –
als **Wiederkehrzeit** T (im Mittel einmal in T Jahren) und daraus

* Wahrscheinlichkeit pro Jahr:          p = 1 / T
* Wahrscheinlichkeit in n Jahren:       1 − (1 − p)^n   (z. B. Nutzungsdauer 30 Jahre)

Grundlage sind amtliche bzw. Messdaten (siehe ``gov_data.py``):

* Starkregen  – KOSTRA-DWD-2020 (Regenhöhe je Dauer und Wiederkehrzeit)
* Hochwasser  – Hochwassergefahrenkarten der Länder (HQ häufig, HQ100, HQ extrem)
* Sturm       – Jahreshöchstwerte der Böen (DWD-Stationen) mit Gumbel-Verteilung
* Erdbeben    – Erdbebengefährdung (Bodenbeschleunigung für 475 Jahre)
* Tornado     – Häufigkeit und Schneisenfläche in Deutschland (Literaturwerte)
* Aliens      – Ankunft expandierender Zivilisationen (Hanson et al. 2021, ApJ)
* Kaiju       – Obergrenze aus Fossilbericht und Knochenstatik („Rule of Three“)

Alles bleibt eine **Ersteinschätzung**: Wiederkehrzeiten über ~100 Jahre
sind aus 10–50 Jahren Messung nur grob abschätzbar.

Beispiel::

    from modules.likelihood import gust_return_period, describe
    T = gust_return_period(jahreshoechstwerte_kmh, 120)
    print(describe(T)["text"])   # "etwa alle 35 Jahre"
"""

from __future__ import annotations

import math

import numpy as np

EULER_GAMMA = 0.5772156649
GERMANY_KM2 = 357_600.0
LIFETIME_YEARS = 30          # Bezugszeitraum, z. B. Nutzungsdauer eines Gebäudes / Zinsbindung

# Tornados über Land in Deutschland pro Jahr je Stärke (F0 … F5), hochgerechnet aus den
# Meldungen 2000–2024: Beyer, Wapler & Kühne (2025), Meteorol. Z., DOI 10.1127/metz/1276
# (DWD/ESWD). F3: etwa alle zwei Jahre, F4: etwa alle 21 Jahre, F5: in Deutschland nicht
# beobachtet (hier sehr vorsichtig 1 in 200 Jahren angesetzt).
TORNADOES_PER_YEAR = [34.0, 12.2, 4.4, 0.5, 0.048, 0.005]
TORNADO_PATH_KM = [2.0, 4.0, 10.0, 18.0, 25.0, 40.0]      # typische Schneisenlänge (Annahme)
TORNADO_SOURCE = "DWD/ESWD-Tornadostatistik 2000–2024 (Beyer et al. 2025)"

# Alien-Invasion: Hanson, Martin, McCarter & Paulson (2021), „If Loud Aliens Explain Human
# Earliness, Quiet Aliens Are Also Rare“, Astrophysical Journal 922:182 (arXiv:2102.01522).
# Sich ausbreitende („grabby“) Zivilisationen erreichen uns in etwa 200 Mio. bis 2 Mrd. Jahren,
# im Mittel nach rund 1 Mrd. Jahren. Wer sich so ausbreitet, übernimmt den ganzen Planeten –
# das Projektgebiet ist dann sicher dabei.
ALIEN_ARRIVAL_YEARS = 1.0e9
ALIEN_ARRIVAL_RANGE = (2.0e8, 2.0e9)
ALIEN_SOURCE = "Hanson et al. (2021), Astrophysical Journal 922:182 („Grabby Aliens“)"
# Zum Vergleich: alle natürlichen Katastrophen, die die Menschheit auslöschen könnten, zusammen –
# wahrscheinlich seltener als 1 zu 87.000 pro Jahr (Snyder-Beattie, Ord & Bonsall 2019,
# Scientific Reports 9:11054).
NATURAL_EXTINCTION_YEARS = 87_000

# Kaiju: In rund 370 Mio. Jahren Landleben wurde kein Landtier schwerer als etwa 100 t
# (Sauropoden); Knochen versagen oberhalb von etwa 140 t (Hokkanen 1986, J. Theor. Biol.
# 118:491). Null Fälle in N Jahren heißt mit 95 % Sicherheit: Rate unter 3 / N
# („Rule of Three“, Hanley & Lippman-Hand 1983, JAMA 249:1743). Taucht ein Kaiju auf, verwüstet
# es eine Schneise (Länge: Annahme wie im Film) – wie oft liegt das Gebiet darin?
LAND_LIFE_YEARS = 370e6
EARTH_LAND_KM2 = 148.9e6
KAIJU_RAMPAGE_KM = 100.0
LARGEST_LAND_ANIMAL_T = 100.0
BONE_LIMIT_T = 140.0
KAIJU_SOURCE = ("Fossilbericht + Knochenstatik (Hokkanen 1986), „Rule of Three“ "
                "(Hanley & Lippman-Hand 1983)")

# Erdbebenzonen (DIN 4149 / DIN EN 1998-1/NA): Intensität, die im Mittel alle 475 Jahre
# erreicht wird (Zonenmitte); None = außerhalb aller Zonen (Intensität unter 6).
ZONE_INTENSITY_475 = {None: 5.5, 0: 6.25, 1: 6.75, 2: 7.25, 3: 7.75}


# --------------------------------------------------------------------------
# Darstellung
# --------------------------------------------------------------------------

def describe(T: float | None, years: int = LIFETIME_YEARS, exact: bool = False, bound: bool = False) -> dict:
    """Wiederkehrzeit -> Texte und Wahrscheinlichkeiten für die Oberfläche.

    Über 10.000 Jahre bleibt der Text bewusst vage („seltener als …“), weil Messreihen dafür
    nicht reichen – außer mit ``exact=True`` (Modellrechnungen wie Kaiju und Aliens).
    ``bound=True``: T ist eine Untergrenze („seltener als alle …“).
    """
    if T is None or not np.isfinite(T) or T <= 0:
        return {"T": None, "p_year": None, "p_life": None, "text": "keine Angabe", "level": "none"}
    p = min(1.0, 1.0 / T)
    life = -math.expm1(years * math.log1p(-p)) if p < 1 else 1.0   # 1 − (1 − p)^n, genau auch für winzige p
    if T < 1.5:
        text = "mehrmals pro Jahr" if T < 0.7 else "etwa jedes Jahr"
    elif exact:
        text = ("seltener als alle " if bound else "etwa alle ") + f"{big_number(T)} Jahre"
    elif T > 10_000:
        text = "seltener als alle 10.000 Jahre"
    else:
        rounded = _round_nicely(T)
        text = f"etwa alle {rounded:,} Jahre".replace(",", ".")
    # Ampel: häufig = rot (das passiert wirklich), selten = grün
    level = "risk" if T <= 30 else ("warn" if T <= 300 else "ok")
    return {"T": float(T), "p_year": p, "p_life": life, "text": text, "level": level}


def _round_nicely(T: float) -> int:
    if T < 10:
        return int(round(T))
    digits = 10 ** (len(str(int(T))) - 2)
    return int(round(T / digits) * digits)


def big_number(n: float) -> str:
    """Große Zahl auf Deutsch: 87.000, 33 Mio., 1,2 Mrd., 340 Bio."""
    for div, unit in ((1e12, "Bio."), (1e9, "Mrd."), (1e6, "Mio.")):
        if n >= div:
            v = n / div
            text = f"{v:,.0f}".replace(",", ".") if v >= 10 else f"{v:.1f}".replace(".", ",").replace(",0", "")
            return f"{text} {unit}"
    return f"{_round_nicely(n):,}".replace(",", ".")


def one_in(p: float | None) -> str:
    """Wahrscheinlichkeit als „1 zu …“."""
    return f"1 zu {big_number(1 / p)}" if p else "–"


def percent(p: float | None) -> str:
    if p is None:
        return "–"
    if p >= 0.995:
        return "fast sicher"
    if p >= 0.1:
        return f"{p * 100:.0f} %"
    if p >= 0.01:
        return f"{p * 100:.1f} %".replace(".", ",")
    if p >= 0.0001:
        return f"{p * 100:.2f} %".replace(".", ",")
    if p <= 0:
        return "0 %"
    digits = 1 - math.floor(math.log10(p * 100))          # zwei gültige Stellen: 0,0000033 %
    text = f"{p * 100:.{digits}f}".rstrip("0").rstrip(".")
    return text.replace(".", ",") + " %"


# --------------------------------------------------------------------------
# Extremwertstatistik
# --------------------------------------------------------------------------

def gumbel_fit(annual_maxima) -> tuple[float, float] | None:
    """Gumbel-Verteilung (Momentenmethode) an Jahreshöchstwerte: (Lage μ, Streuung β)."""
    x = np.asarray([v for v in annual_maxima if v is not None and np.isfinite(v)], dtype=float)
    if len(x) < 5:
        return None
    beta = x.std(ddof=1) * math.sqrt(6) / math.pi
    mu = x.mean() - EULER_GAMMA * beta
    return (mu, beta) if beta > 0 else None


def gumbel_return_period(fit, value: float) -> float | None:
    """Wiederkehrzeit, mit der ``value`` als Jahreshöchstwert erreicht oder überschritten wird."""
    if fit is None:
        return None
    mu, beta = fit
    p_not = math.exp(-math.exp(-(value - mu) / beta))     # P(Jahreshöchstwert < value)
    p = 1 - p_not
    return 1.0 / p if p > 0 else math.inf


def gumbel_level(fit, T: float) -> float | None:
    """Wert, der im Mittel einmal in T Jahren erreicht wird."""
    if fit is None:
        return None
    mu, beta = fit
    return mu - beta * math.log(-math.log(1 - 1 / T))


def gust_return_period(annual_max_gusts_kmh, gust_kmh: float) -> float | None:
    return gumbel_return_period(gumbel_fit(annual_max_gusts_kmh), gust_kmh)


# --------------------------------------------------------------------------
# Starkregen: KOSTRA-Tabelle (Regenhöhe je Wiederkehrzeit) umkehren
# --------------------------------------------------------------------------

def rain_return_period(table: dict, depth_mm: float) -> float | None:
    """``table`` = {Wiederkehrzeit T: Regenhöhe in mm} für eine Dauerstufe (KOSTRA).

    Zwischen den Stützstellen wird logarithmisch interpoliert; oberhalb von
    100 Jahren mit dem Anstieg der letzten beiden Stützstellen fortgeschrieben.
    """
    if not table:
        return None
    Ts = np.array(sorted(table), dtype=float)
    hs = np.array([table[t] for t in sorted(table)], dtype=float)
    logT = np.log(Ts)
    if depth_mm <= hs[0]:
        return float(Ts[0]) if depth_mm >= hs[0] * 0.999 else max(0.5, float(Ts[0]) * depth_mm / hs[0])
    if depth_mm <= hs[-1]:
        return float(np.exp(np.interp(depth_mm, hs, logT)))
    slope = (hs[-1] - hs[-2]) / (logT[-1] - logT[-2])             # mm je e-fache Wiederkehrzeit
    return float(np.exp(logT[-1] + (depth_mm - hs[-1]) / max(slope, 1e-6)))


# --------------------------------------------------------------------------
# Erdbeben: Gefährdungskurve aus dem 475-Jahres-Wert
# --------------------------------------------------------------------------

def quake_return_period(pga_475_g: float, pga_g: float, slope: float = 2.8) -> float | None:
    """Wiederkehrzeit einer Bodenbeschleunigung ``pga_g`` am Standort.

    Die amtliche Karte nennt die Beschleunigung, die im Mittel alle 475 Jahre
    erreicht wird (10 % in 50 Jahren). Für andere Werte wird eine Potenzkurve
    angenommen, wie sie für Mitteleuropa typisch ist: λ(a) = λ475 · (a / a475)^−k.
    """
    if not pga_475_g or pga_475_g <= 0:
        return None
    return 475.0 * (pga_g / pga_475_g) ** slope


def quake_return_period_from_zone(zone, intensity: float) -> float | None:
    """Wiederkehrzeit der Intensität ``intensity`` (EMS-98) in einer Erdbebenzone.

    Über die Bodenbeschleunigung (Wald et al. 1999) und die Potenzkurve oben.
    """
    def pga(i):
        return 10 ** ((i + 1.66) / 3.66)
    if zone not in ZONE_INTENSITY_475:
        return None
    return quake_return_period(pga(ZONE_INTENSITY_475[zone]), pga(intensity))


# --------------------------------------------------------------------------
# Planspiele: Alien-Invasion und Kaiju
# --------------------------------------------------------------------------

def alien_return_period() -> float:
    """Wiederkehrzeit „Aliens erreichen die Erde“ (und damit auch das Gebiet)."""
    return ALIEN_ARRIVAL_YEARS


def kaiju_rate_world() -> float:
    """Obergrenze (95 %) für Kaiju-Auftritte pro Jahr weltweit: 3 / 370 Mio. Jahre Landleben."""
    return 3.0 / LAND_LIFE_YEARS


def kaiju_return_period(side_m: float, swath_m: float, rampage_km: float = KAIJU_RAMPAGE_KM) -> float:
    """Untergrenze der Wiederkehrzeit „ein Kaiju läuft durch dieses Gebiet“.

    Wie beim Tornado: Eine Schneise (Länge L, Breite B) trifft ein Gebiet der Kantenlänge S,
    wenn ihre Mittellinie näher als (B + S) / 2 vorbeiläuft – überstrichene Fläche
    (L + S) · (B + S), verteilt auf die Landfläche der Erde.
    """
    s = side_m / 1000
    swept = (rampage_km + s) * (swath_m / 1000 + s)
    return 1.0 / (kaiju_rate_world() * swept / EARTH_LAND_KM2)


def kaiju_mass_t(height_m: float) -> float:
    """Grobe Masse eines aufrecht gehenden Kaijus: hochgerechnet von einem T. rex (≈ 8 t bei
    4 m Hüfthöhe, die Masse wächst mit der dritten Potenz der Größe)."""
    return 8.0 * (height_m / 4.0) ** 3


# --------------------------------------------------------------------------
# Tornado: Wie oft trifft eine Schneise dieses Gebiet?
# --------------------------------------------------------------------------

def tornado_return_period(ef: int, side_m: float, path_width_m: list,
                          per_year: list = TORNADOES_PER_YEAR, path_km: list = TORNADO_PATH_KM) -> float:
    """Wiederkehrzeit für „ein Tornado der Stärke ≥ ``ef`` streift das Gebiet“.

    Eine Schneise (Länge L, Breite B) trifft ein quadratisches Gebiet der
    Kantenlänge S, wenn ihre Mittellinie näher als (B + S) / 2 vorbeiläuft:
    überstrichene Fläche ≈ (L + S) · (B + S). Verteilt auf die Fläche Deutschlands.
    """
    rate = 0.0
    s_km = side_m / 1000
    for k in range(int(ef), 6):
        swept = (path_km[k] + s_km) * (path_width_m[k] / 1000 + s_km)
        rate += per_year[k] * swept / GERMANY_KM2
    return 1.0 / rate if rate > 0 else math.inf
