"""Rechenwege der Analysen – Schritt für Schritt, mit Formeln und Quellen.

Für jede Analyse beschreibt ein ``Method``-Objekt, *wie* TERRA-Sim rechnet:
die Schritte (mit Formel in LaTeX und Quellenschlüsseln aus ``sources.py``),
die Annahmen, die wir selbst gesetzt haben, und die Grenzen des Verfahrens.
Die App zeigt das auf jeder Analyseseite unter „Methode & Quellen“ und
gesammelt auf der Seite „Methoden & Quellen“.

Die Zahlen hier müssen zu den Konstanten in ``simulator.py``, ``hazards.py``
und ``likelihood.py`` passen – wer dort etwas ändert, ändert es hier mit.

Beispiel::

    from modules.methods import METHODS
    for step in METHODS["quake"].steps:
        print(step.text, step.sources)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from modules.sources import SOURCES


@dataclass(frozen=True)
class Step:
    text: str
    formula: str = ""                 # LaTeX (für st.latex / KaTeX), leer = keine Formel
    sources: tuple[str, ...] = ()


@dataclass(frozen=True)
class Method:
    title: str
    summary: str
    steps: tuple[Step, ...]
    assumptions: tuple[str, ...] = ()
    limits: tuple[str, ...] = ()
    extra_sources: tuple[str, ...] = field(default_factory=tuple)

    @property
    def source_keys(self) -> list[str]:
        """Alle zitierten Quellen in der Reihenfolge ihres ersten Auftretens."""
        keys = []
        for key in [k for s in self.steps for k in s.sources] + list(self.extra_sources):
            if key not in keys:
                keys.append(key)
        return keys


def _m(title, summary, steps, assumptions=(), limits=(), extra=()):
    return Method(title, summary, tuple(Step(*s) if isinstance(s, tuple) else s for s in steps),
                  tuple(assumptions), tuple(limits), tuple(extra))


RETURN_PERIOD = Step(
    "Aus der Wiederkehrzeit T wird die Chance, dass das Szenario in n = 30 Jahren (z. B. Nutzungsdauer) "
    "mindestens einmal eintritt.",
    r"P_n = 1 - \left(1 - \tfrac{1}{T}\right)^{n}", ("coles2001",))

METHODS: dict[str, Method] = {
    "model": _m(
        "3D-Modell", "Gebäudegrundrisse aus OpenStreetMap, auf das amtliche Geländemodell gestellt und in die Höhe "
                     "gezogen – als Klötzchen (LOD 1) oder mit Dachformen (LOD 2).",
        [
            ("Grundrisse, Nutzung und Höhenangaben der Gebäude kommen aus OpenStreetMap. Die Höhe stammt aus "
             "`height`, sonst aus der Geschosszahl × 3 m, sonst aus einer typischen Geschosszahl je Gebäudetyp – "
             "dasselbe Vorgehen, mit dem 3D-Stadtmodelle ohne Höhenmessung erzeugt werden.",
             r"h = n_{\text{Geschosse}} \cdot 3\,\text{m} + h_{\text{Dach}}", ("osm", "biljecki2017")),
            ("Detailstufe nach dem LOD-Konzept: LOD 1 = Prisma mit flachem Dach, LOD 2 = mit Dachform "
             "(Sattel-, Walm-, Pult-, Zeltdach aus `roof:shape`).", "", ("biljecki2016", "citygml")),
            ("Gelände: amtliches Digitales Geländemodell mit 1 m Raster (DGM1) der Länder, sonst weltweite "
             "Höhenmodelle (SRTM über Open-Elevation, Copernicus DEM über Open-Meteo).", "", ("dgm1", "farr2007")),
            ("Jedes Gebäude steht auf dem tiefsten Geländepunkt seines Grundrisses. Für die Analysen wird das Gebiet "
             "in ein Raster mit Flächennutzung je Zelle zerlegt (Gebäude, Straße, Grün, Wasser, Sonstiges).",
             "", ()),
        ],
        assumptions=["Geschosshöhe einheitlich 3 m, Dachhöhe 3 m, wenn OSM nur die Dachform kennt.",
                     "Fehlt jede Höhenangabe, gilt eine typische Geschosszahl je Gebäudetyp (Anteil im Steckbrief "
                     "unter „Höhen aus OSM“)."],
        limits=["OpenStreetMap ist je nach Ort unterschiedlich vollständig, besonders bei Höhen und Dächern.",
                "Weltweite Höhenmodelle (30–90 m) glätten das Gelände stark – für Hochwasser und Starkregen ist das "
                "DGM1 entscheidend."]),

    "flood": _m(
        "Hochwasser", "Planares „Badewannen“-Verfahren: Alles, was unter dem Wasserspiegel liegt, gilt als "
                      "überflutet. Dazu die amtlichen Hochwassergefahrenkarten der Länder.",
        [
            ("Wasserspiegel W = Bezugsniveau + eingestellter Pegel. Die Wassertiefe jeder Rasterzelle ist der "
             "Abstand zwischen Wasserspiegel und Gelände.", r"d(x) = \max\bigl(0,\; W - z(x)\bigr)", ("teng2017",)),
            ("Ein Gebäude ist betroffen, sobald das Wasser an seinem tiefsten Grundrisspunkt mehr als 1 cm hoch "
             "steht; gezählt wird die Bruttogrundfläche im Erdgeschoss.", "", ()),
            ("Amtliche Szenarien: Überflutungsflächen bei häufigem Hochwasser (HQ häufig), 100-jährlichem (HQ100) "
             "und extremem Hochwasser (HQ extrem) nach EU-Hochwasserrisikomanagement-Richtlinie; betroffene "
             "Gebäude per Verschneidung mit den Grundrissen.", "", ("eu_floods", "bfg_hwgk")),
            ("Wahrscheinlichkeit: das häufigste amtliche Szenario, das Gebäude im Gebiet erreicht, gibt die "
             "Wiederkehrzeit vor.", "", ("bfg_hwgk",)),
            RETURN_PERIOD,
        ],
        assumptions=["Der Pegel gilt im ganzen Gebiet gleich (horizontaler Wasserspiegel).",
                     "Wiederkehrzeiten der amtlichen Szenarien: HQ häufig ≈ 20 Jahre, HQ100 = 100 Jahre, "
                     "HQ extrem ≈ 1.000 Jahre, sofern der Kartendienst keine genaueren Werte liefert."],
        limits=["Keine Hydraulik: keine Fließgeschwindigkeit, keine Deiche, keine Dauer des Ereignisses. Auch "
                "Senken ohne Verbindung zum Gewässer laufen voll – das überschätzt die Fläche.",
                "Die amtlichen Karten zeigen Flusshochwasser, keine Sturzfluten durch Starkregen."]),

    "rain": _m(
        "Starkregen", "Der Regen fließt je nach Versiegelung ab, die Kanalisation nimmt einen Teil auf, der Rest "
                      "folgt dem Gefälle und staut sich in Senken.",
        [
            ("Abflusswirksamer Regen je Zelle: Die Kanalisation nimmt auf versiegelten Flächen die ersten K l/m² "
             "auf; vom Rest fließt der Anteil ψ (Abflussbeiwert) oberflächlich ab – Dach 0,95, Straße 0,9, "
             "Sonstiges 0,5, Grün 0,15.",
             r"h_{\text{eff}} = \psi \cdot \max(0,\; N - K)", ("din1986", "dwa_a118")),
            ("Kanalnetze werden in Deutschland für Regen bemessen, der etwa alle 2–5 Jahre vorkommt – Voreinstellung "
             "K = 20 l/m².", "", ("din752", "dwa_a118")),
            ("Dachwasser kommt über die Fallrohre an der tiefsten Ecke des Gebäudes auf dem Boden an.", "", ()),
            ("Senken füllen und Fließwege bestimmen: Das Gelände wird vom Rand her „geflutet“ (Priority-Flood); "
             "jede Zelle entwässert in eine Nachbarzelle, das Wasser sammelt sich entlang dieser Fließwege.",
             r"Q_i = A_i\,h_{\text{eff},i} + \sum_{j \to i} Q_j", ("barnes2014", "ocallaghan1984")),
            ("In jeder Senke wird das zufließende Volumen verteilt: Der Wasserspiegel wird so bestimmt, dass das "
             "Volumen genau hineinpasst (Bisektion).", r"\sum_{x \in S} \max\bigl(0,\, w - z(x)\bigr)\,A = V", ()),
            ("Ein Gebäude hat Rückstau-Risiko, wenn daneben mindestens 10 cm Wasser auf mindestens 25 m² stehen. "
             "Starkregengefahrenkarten stufen Überflutungstiefen ab etwa 5–10 cm ein.", "", ("lubw2016",)),
            ("Wahrscheinlichkeit: Regenhöhe je Dauerstufe und Wiederkehrzeit aus KOSTRA-DWD-2020 (5-km-Raster); "
             "dazwischen wird logarithmisch interpoliert, über 100 Jahre fortgeschrieben.",
             r"\ln T = \ln T_i + \frac{N - N_i}{N_{i+1} - N_i}\,\bigl(\ln T_{i+1} - \ln T_i\bigr)", ("kostra",)),
            RETURN_PERIOD,
        ],
        assumptions=["Das ganze Ereignis wird auf einmal verteilt – kein zeitlicher Verlauf, keine Versickerung "
                     "während des Regens über ψ hinaus.",
                     "Abflussbeiwerte sind gerundete mittlere Werte, angelehnt an DIN 1986-100.",
                     "Über 100 Jahre wird die KOSTRA-Kurve mit dem Anstieg der letzten Stützstellen verlängert."],
        limits=["Keine 2D-Hydrodynamik (Flachwassergleichungen): Fließgeschwindigkeiten und Überströmen von "
                "Bordsteinen fehlen.", "Die Kanalisation nimmt überall gleich viel auf; Engpässe im Netz fehlen."]),

    "wind": _m(
        "Starkwind", "Sichtlinien-Analyse der Fassaden, Winddruck nach Eurocode, Düseneffekt in Gassen und eine "
                     "Potentialströmung am Boden – eine schnelle Abschätzung statt einer CFD-Simulation.",
        [
            ("Windgeschwindigkeit in 10 m Höhe aus der Beaufort-Stärke.",
             r"v_{10} = 0{,}836 \cdot B^{1{,}5}\ \text{m/s}", ("wmo558",)),
            ("Zunahme mit der Höhe nach dem Potenzgesetz, Exponent α = 0,25 für bebaute Gebiete.",
             r"v(z) = v_{10}\left(\frac{z}{10\,\text{m}}\right)^{\alpha}", ("hellmann1915", "davenport1960")),
            ("Fassaden-Exposition: Anteil der Fassade, der zum Wind zeigt, mal (1 − Windschatten). Hindernisse "
             "werfen einen Windschatten bis zum 8-Fachen ihrer Höhe; die Strömungsregime in Straßenschluchten "
             "hängen vom Verhältnis Höhe zu Breite ab.", r"E = \cos\theta \cdot (1 - S)", ("oke1988",)),
            ("Winddruck auf frei angeströmte Fassaden mit Luftdichte ρ = 1,25 kg/m³ und Außendruckbeiwert "
             "c_pe = +0,8 für die Luv-Wand.", r"w = \tfrac{1}{2}\,\rho\,v(z)^2\,c_{pe} \cdot E", ("din1991_4",)),
            ("Düseneffekt: Lücken von 2–20 m zwischen Gebäuden, die mindestens so hoch wie die Lücke breit sind "
             "(H/B ≥ 1) und höchstens 30° zur Windrichtung stehen; Beschleunigung bis zum Faktor 1,6.",
             r"f = 1 + 0{,}6 \cdot a \cdot \frac{\min(H/B,\;2{,}5)}{2{,}5}", ("blocken2008", "oke1988")),
            ("Wind am Boden: Umströmung der Gebäude als Potentialströmung (Laplace-Gleichung, gelöst mit "
             "Rot-Schwarz-SOR), dazu Windschatten im Lee; auf 2 m Höhe umgerechnet.",
             r"\nabla^2 \varphi = 0, \qquad \vec{u} = \nabla \varphi", ("anderson2017",)),
            ("Gefährlich für Fußgänger: Stundenmittel ab 15 m/s in Kopfhöhe.", r"\bar{u}_{2\,\text{m}} \geq "
             r"15\ \text{m/s}", ("nen8100", "lawson1975")),
            ("Wahrscheinlichkeit: Jahreshöchstwerte der Spitzenböen an der nächsten DWD-Station, angepasst mit der "
             "Gumbel-Verteilung (Momentenmethode); dazu der gemessene Anteil der Windrichtung bei starkem Wind "
             "(10 Jahre Stundenwerte).",
             r"T(x) = \frac{1}{1 - \exp\!\left(-e^{-(x-\mu)/\beta}\right)}, \quad \beta = \frac{s\sqrt{6}}{\pi},"
             r"\quad \mu = \bar{x} - 0{,}5772\,\beta", ("gumbel1958", "coles2001", "dwd_cdc")),
            RETURN_PERIOD,
        ],
        assumptions=["Spitzenböe = 1,5 × Mittelwind der Beaufort-Stufe (für die Wahrscheinlichkeit).",
                     "Windschatten bis zum 8-Fachen der Hindernishöhe; Düsenfaktor höchstens 1,6.",
                     "Ein Exponent α für das ganze Gebiet."],
        limits=["Keine CFD: keine Wirbel, keine Ablösung an Kanten, keine Strömung über die Dächer. Für belastbare "
                "Aussagen zum Fußgängerwind braucht es CFD oder Windkanal.",
                "CFD-Studien zeigen, dass durch Gassen kaum mehr Luft strömt als im Freien – am Boden kann der Wind "
                "aber zunehmen. Der Düsenfaktor ist deshalb eine obere Abschätzung."],
        extra=("blocken2015", "meteostat")),

    "quake": _m(
        "Erdbeben", "Makroseismische Methode: Intensität am Standort nach EMS-98 trifft auf die Verletzbarkeit des "
                    "Gebäudetyps und ergibt einen mittleren Schadensgrad je Gebäude.",
        [
            ("Intensität im Epizentrum aus der Magnitude (Faustformel für Herde um 10 km Tiefe; Gutenberg & Richter "
             "geben M = 1 + ⅔·I₀ an).", r"I_0 \approx 1{,}5\,M_w - 0{,}5", ("gutenberg1956",)),
            ("Abnahme mit der Herdentfernung r (Kövesligethy-Ansatz), Herdtiefe h = 10 km, Absorption "
             "α ≈ 0,0015 km⁻¹.",
             r"I = I_0 - 3\log_{10}\frac{r}{h} - 3\,\alpha\,\log_{10}(e)\,(r - h)", ("sponheuer1960",)),
            ("Weicher Untergrund verstärkt die Erschütterung: +0,5 Stufen, Fels −0,5 Stufen.", "", ()),
            ("Verletzbarkeitsklasse nach EMS-98 aus dem OSM-Gebäudetyp und der Geschosszahl (A historisch, "
             "B Mauerwerk, C Stahlbeton/Stahl); Verletzbarkeitsindex V je Klasse plus Zuschläge für Geschosse, "
             "unregelmäßigen Grundriss und Lage im Block.", r"V = V_{\text{Klasse}} + \Delta V_{\text{Geschosse}} + "
             r"\Delta V_{\text{Grundriss}} + \Delta V_{\text{Lage}}", ("ems98", "lagomarsino2006")),
            ("Mittlerer Schadensgrad (0–5) mit dem Duktilitätsfaktor Q = 2,3.",
             r"\mu_D = 2{,}5\left[1 + \tanh\!\left(\frac{I + 6{,}25\,V - 13{,}1}{Q}\right)\right]",
             ("lagomarsino2006",)),
            ("Spitzenbodenbeschleunigung aus der Intensität (in cm/s²).",
             r"\log_{10}\text{PGA} = \frac{I + 1{,}66}{3{,}66}", ("wald1999",)),
            ("Wahrscheinlichkeit: Erdbebenzone und Untergrundklasse am Ort (DIN 4149) geben die Intensität vor, die "
             "im Mittel alle 475 Jahre erreicht wird; für andere Intensitäten eine Gefährdungskurve als "
             "Potenzfunktion der Bodenbeschleunigung.",
             r"\lambda(a) = \frac{1}{475}\left(\frac{a}{a_{475}}\right)^{-k}, \quad k = 2{,}8",
             ("din4149", "gfz_zones", "cornell1968")),
            RETURN_PERIOD,
        ],
        assumptions=["Bauweise nur aus dem OSM-Gebäudetyp geschätzt (Baujahr und Zustand unbekannt).",
                     "Untergrund ±0,5 Intensitätsstufen; Exponent der Gefährdungskurve k = 2,8.",
                     "Zonenmitte als 475-Jahres-Intensität: außerhalb der Zonen 5,5, Zone 0 6,25 … Zone 3 7,75."],
        limits=["Die Intensität ist im ganzen Gebiet gleich – lokale Bodeneffekte fehlen.",
                "Die Zone gilt für die Ortsmitte der Gemeinde; die neue Gefährdungskarte nach DIN EN 1998-1/NA "
                "ist kein offener Datensatz."]),

    "tornado": _m(
        "Tornado", "Ein Wirbel nach Rankine zieht auf gerader Bahn über das Gebiet; der Schaden folgt aus der "
                   "Windgeschwindigkeit am Gebäude.",
        [
            ("Stärke nach der (Enhanced/International) Fujita-Skala; Spitzenböe je Stufe aus der Klassenmitte: "
             "EF0 33, EF1 43, EF2 55, EF3 67, EF4 82, EF5 95 m/s.", "", ("ef_scale", "if_scale")),
            ("Windfeld als Rankine-Wirbel: Im Kern (Radius R) wächst die Drehgeschwindigkeit linear, außen fällt "
             "sie mit 1/r; auf der rechten Seite addiert sich die Zuggeschwindigkeit (15 m/s).",
             r"v_t(r) = \begin{cases} v_{\max}\,\dfrac{r}{R} & r < R \\[4pt] v_{\max}\,\dfrac{R}{r} & r \geq R "
             r"\end{cases} \qquad v = v_t \pm v_{\text{Zug}}", ("holton2013",)),
            ("Schneisenbreite je Stufe (30 bis 550 m): Schneisen werden mit der Stärke breiter und länger.", "",
             ("brooks2004",)),
            ("Schadensgrad aus der Windgeschwindigkeit am Gebäude, angelehnt an die Schadensindikatoren der "
             "EF-Skala für Wohnhäuser; leichte Bauten 10 m/s empfindlicher, robuste 12 m/s widerstandsfähiger.",
             "", ("ef_scale",)),
            ("Wahrscheinlichkeit: Tornados pro Jahr je Stärke in Deutschland (2000–2024) mal der Fläche, die eine "
             "Schneise der Länge L und Breite B beim Überqueren eines Gebiets der Kantenlänge S überstreicht.",
             r"\lambda = \sum_{k \geq \text{EF}} n_k \cdot \frac{(L_k + S)(B_k + S)}{A_{\text{Deutschland}}}",
             ("beyer2025",)),
            RETURN_PERIOD,
        ],
        assumptions=["Gerade Bahn, gleichbleibende Stärke, Zuggeschwindigkeit 15 m/s.",
                     "Schneisenbreiten und -längen je Stufe sind gerundete typische Werte."],
        limits=["Keine Trümmerflug- oder Strömungsrechnung; die Tornado-Häufigkeit ist ein Mittelwert für ganz "
                "Deutschland (regional bis etwa doppelt so hoch)."]),

    "kaiju": _m(
        "Kaiju-Angriff (Planspiel)", "Ein Riesenmonster läuft durch das Gebiet – ein Planspiel für Wege, Reichweiten "
                                     "und Schadensstufen. Die Wahrscheinlichkeit stützt sich trotzdem auf Physik und "
                                     "Statistik.",
        [
            ("Schneise: Füße und Körper 0,5·h breit, Schwanz und Arme reichen 0,45·h, die Schritte erschüttern bis "
             "0,8·h (h = Größe des Monsters).", "", ()),
            ("Quadrat-Würfel-Gesetz: Die Masse wächst mit der dritten Potenz der Größe, der Knochenquerschnitt nur "
             "mit der zweiten – die Spannung in den Knochen wächst also mit der Größe.",
             r"\sigma = \frac{m\,g}{A} \propto \frac{h^3}{h^2} = h", ("galileo1638",)),
            ("Knochen von Landtieren versagen oberhalb von etwa 140 t; das schwerste Landtier aller Zeiten wog etwa "
             "100 t. Masse des Kaijus hochgerechnet von einem T. rex (≈ 8 t bei 4 m Hüfthöhe).",
             r"m \approx 8\,\text{t} \cdot \left(\frac{h}{4\,\text{m}}\right)^3", ("hokkanen1986",)),
            ("„Rule of Three“: Null Fälle in N Jahren bedeuten mit 95 % Sicherheit eine Rate unter 3/N – bei 370 Mio. "
             "Jahren Landleben höchstens ein Kaiju in 123 Mio. Jahren.", r"\lambda_{95\%} < \frac{3}{N}",
             ("hanley1983",)),
            ("Trefferchance wie beim Tornado: Schneise der Länge L (Annahme 100 km) und Breite B, verteilt auf die "
             "Landfläche der Erde (149 Mio. km²).",
             r"\lambda_{\text{Gebiet}} = \lambda_{95\%} \cdot \frac{(L + S)(B + S)}{A_{\text{Land}}}", ()),
            RETURN_PERIOD,
        ],
        assumptions=["Schneisenlänge 100 km „wie im Film“; Masse grob von einem T. rex hochgerechnet."],
        limits=["Ein Planspiel – der Wert ist eine Obergrenze, keine Vorhersage."]),

    "alien": _m(
        "Alien-Invasion (Planspiel)", "UFOs holen Menschen aus dem Gebiet – ein Planspiel. Die Wahrscheinlichkeit "
                                      "kommt aus einem astrophysikalischen Modell, nicht aus UFO-Sichtungen.",
        [
            ("„Grabby Aliens“: Sich ausbreitende Zivilisationen erklären, warum die Menschheit so früh in der "
             "Geschichte des Universums auftaucht. Nach dem Modell erreichen sie uns in etwa 200 Mio. bis 2 Mrd. "
             "Jahren, im Mittel nach rund 1 Mrd. Jahren.", r"T \approx 10^{9}\ \text{Jahre}", ("hanson2021",)),
            ("Wer sich so ausbreitet, übernimmt den ganzen Planeten – das Projektgebiet ist dann sicher betroffen.",
             r"\lambda_{\text{Gebiet}} = \lambda_{\text{Erde}} = 1/T", ()),
            ("Zum Vergleich: Alle natürlichen Katastrophen zusammen, die die Menschheit auslöschen könnten, liegen "
             "wahrscheinlich unter 1 zu 87.000 pro Jahr – sonst hätten wir die letzten 200.000 Jahre kaum überlebt.",
             "", ("snyderbeattie2019",)),
            RETURN_PERIOD,
        ],
        limits=["Ein Planspiel – das Modell beruht auf Annahmen über die Häufigkeit von Leben im All."]),
}


def check() -> list[str]:
    """Zitierte, aber unbekannte Quellenschlüssel (für Tests)."""
    return [k for m in METHODS.values() for k in m.source_keys if k not in SOURCES]
