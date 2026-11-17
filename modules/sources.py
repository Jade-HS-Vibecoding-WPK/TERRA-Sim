"""Quellen-Register: Literatur, Normen und Daten, auf die sich TERRA-Sim stützt.

Jede Quelle hat einen kurzen Schlüssel (z. B. ``"lagomarsino2006"``). Die
Rechenwege in ``methods.py`` verweisen über diese Schlüssel auf ihre
Grundlagen; die App zeigt daraus Literaturangaben mit Links und erzeugt eine
BibTeX-Datei für Hausarbeiten.

Arten (``kind``):

* ``paper``  begutachtete Fachliteratur und Fachbücher
* ``norm``   Normen, Richtlinien, Leitfäden, Skalen
* ``data``   Datensätze und Dienste

Beispiel::

    from modules.sources import SOURCES, cite, bibtex
    print(cite("lagomarsino2006"))        # Lagomarsino & Giovinazzi (2006)
    print(SOURCES["wald1999"].reference)  # vollständige Angabe
    open("terra-sim.bib", "w").write(bibtex())
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Source:
    key: str
    authors: tuple[str, ...]          # "Nachname, V." oder Institution
    year: str
    title: str
    venue: str                        # Zeitschrift mit Band/Seiten, Verlag, Herausgeber …
    kind: str = "paper"               # paper | norm | data
    doi: str = ""
    url: str = ""
    topics: tuple[str, ...] = field(default_factory=tuple)

    @property
    def link(self) -> str:
        return f"https://doi.org/{self.doi}" if self.doi else self.url

    @property
    def short(self) -> str:
        names = [a.split(",")[0] for a in self.authors]
        if len(names) == 1:
            who = names[0]
        elif len(names) == 2:
            who = f"{names[0]} & {names[1]}"
        else:
            who = f"{names[0]} et al."
        return f"{who} ({self.year})"

    @property
    def reference(self) -> str:
        """Vollständige Angabe (ohne Link)."""
        authors = "; ".join(self.authors)
        return f"{authors} ({self.year}): {self.title}. {self.venue}."


def _s(key, authors, year, title, venue, kind="paper", doi="", url="", topics=()):
    return Source(key, tuple(authors), str(year), title, venue, kind, doi, url, tuple(topics))


_ALL = [
    # ------------------------------------------------------------------ Daten
    _s("osm", ["OpenStreetMap-Mitwirkende"], "laufend", "OpenStreetMap – Gebäude, Straßen, Grün- und Wasserflächen",
       "Open Database License (ODbL) 1.0, abgefragt über die Overpass API", "data",
       url="https://www.openstreetmap.org/copyright", topics=("modell",)),
    _s("dgm1", ["Vermessungsverwaltungen der Länder (AdV)"], "laufend",
       "Digitales Geländemodell Gitterweite 1 m (DGM1)", "Amtliche Geobasisdaten, offene Lizenzen je Land "
       "(z. B. © GeoBasis-DE/LGLN, CC BY 4.0)", "data", url="https://www.adv-online.de/", topics=("modell",)),
    _s("farr2007", ["Farr, T. G.", "Rosen, P. A.", "Caro, E.", "et al."], 2007, "The Shuttle Radar Topography Mission",
       "Reviews of Geophysics 45, RG2004", doi="10.1029/2005RG000183", topics=("modell",)),
    _s("meteostat", ["Meteostat"], "laufend", "Stündliche und tägliche Wetterdaten der nächstgelegenen Stationen",
       "Datenbasis u. a. Deutscher Wetterdienst und MET Norway, CC BY-NC 4.0", "data",
       url="https://meteostat.net", topics=("klima",)),
    _s("dwd_cdc", ["Deutscher Wetterdienst"], "laufend", "Climate Data Center: stündliche Windmessungen und tägliche "
       "Spitzenböen der Stationen", "Open Data, CC BY 4.0", "data",
       url="https://opendata.dwd.de/climate_environment/CDC/", topics=("wind", "klima")),
    _s("kostra", ["Deutscher Wetterdienst"], 2023, "KOSTRA-DWD-2020: Starkniederschlagshöhen für Deutschland "
       "(Dauerstufen 5 min bis 7 Tage, Wiederkehrzeiten 1 bis 100 Jahre)", "Rasterdaten 5 km, Open Data, CC BY 4.0",
       "data", url="https://opendata.dwd.de/climate_environment/CDC/grids_germany/return_periods/precipitation/KOSTRA/",
       topics=("starkregen",)),
    _s("bfg_hwgk", ["Bundesanstalt für Gewässerkunde (BfG)"], "laufend", "Hochwassergefahren- und Hochwasserrisikokarten "
       "der Länder nach EU-Hochwasserrisikomanagement-Richtlinie", "Geoportal der BfG (Kartendienste)", "data",
       url="https://geoportal.bafg.de/", topics=("hochwasser",)),
    _s("gfz_zones", ["GFZ Helmholtz-Zentrum für Geoforschung"], "laufend", "Zuordnung von Orten zu Erdbebenzonen und "
       "geologischen Untergrundklassen nach DIN 4149", "Online-Abfrage", "data",
       url="https://ebz.gfz-potsdam.de/", topics=("erdbeben",)),

    # ------------------------------------------------------------------ Normen, Richtlinien, Skalen
    _s("citygml", ["Open Geospatial Consortium (OGC)"], 2021, "OGC City Geography Markup Language (CityGML) 3.0 "
       "Conceptual Model", "OGC Standard 20-010", "norm", url="https://docs.ogc.org/is/20-010/20-010.html",
       topics=("modell",)),
    _s("eu_floods", ["Europäisches Parlament und Rat"], 2007, "Richtlinie 2007/60/EG über die Bewertung und das "
       "Management von Hochwasserrisiken", "Amtsblatt der EU L 288, 27–34", "norm",
       url="https://eur-lex.europa.eu/eli/dir/2007/60/oj", topics=("hochwasser",)),
    _s("din1986", ["DIN"], 2016, "DIN 1986-100: Entwässerungsanlagen für Gebäude und Grundstücke – Bestimmungen in "
       "Verbindung mit DIN EN 752 und DIN EN 12056", "Beuth, Berlin (Tabelle 9: Abflussbeiwerte)", "norm",
       topics=("starkregen",)),
    _s("din752", ["DIN"], 2017, "DIN EN 752: Entwässerungssysteme außerhalb von Gebäuden – Kanalmanagement",
       "Beuth, Berlin", "norm", topics=("starkregen",)),
    _s("dwa_a118", ["DWA"], 2006, "Arbeitsblatt DWA-A 118: Hydraulische Bemessung und Nachweis von "
       "Entwässerungssystemen", "Deutsche Vereinigung für Wasserwirtschaft, Abwasser und Abfall, Hennef", "norm",
       topics=("starkregen",)),
    _s("lubw2016", ["LUBW Landesanstalt für Umwelt Baden-Württemberg"], 2016, "Leitfaden Kommunales "
       "Starkregenrisikomanagement in Baden-Württemberg", "LUBW, Karlsruhe", "norm",
       url="https://www.lubw.baden-wuerttemberg.de/wasser/starkregen", topics=("starkregen",)),
    _s("din1991_4", ["DIN"], 2010, "DIN EN 1991-1-4: Eurocode 1 – Einwirkungen auf Tragwerke – Teil 1-4: "
       "Allgemeine Einwirkungen, Windlasten (mit Nationalem Anhang)", "Beuth, Berlin", "norm", topics=("wind",)),
    _s("nen8100", ["NEN"], 2006, "NEN 8100: Windhinder en windgevaar in de gebouwde omgeving",
       "Nederlands Normalisatie-instituut, Delft", "norm", topics=("wind",)),
    _s("wmo558", ["World Meteorological Organization"], 2012, "Manual on Marine Meteorological Services, "
       "Annex: Beaufort-Skala", "WMO-No. 558, Genf", "norm", topics=("wind",)),
    _s("ems98", ["Grünthal, G. (Hrsg.)"], 1998, "European Macroseismic Scale 1998 (EMS-98)",
       "Cahiers du Centre Européen de Géodynamique et de Séismologie 15, Luxemburg", "norm",
       url="https://www.gfz-potsdam.de/en/section/seismic-hazard-and-risk-dynamics/data-products-services/"
           "ems-98-european-macroseismic-scale", topics=("erdbeben",)),
    _s("din4149", ["DIN"], 2005, "DIN 4149: Bauten in deutschen Erdbebengebieten – Lastannahmen, Bemessung und "
       "Ausführung üblicher Hochbauten", "Beuth, Berlin", "norm", topics=("erdbeben",)),
    _s("ef_scale", ["Wind Science and Engineering Center"], 2006, "A Recommendation for an Enhanced Fujita Scale "
       "(EF-Scale)", "Texas Tech University, Lubbock", "norm", url="https://www.depts.ttu.edu/nwi/Pubs/FScale/EFScale.pdf",
       topics=("tornado",)),
    _s("if_scale", ["European Severe Storms Laboratory (ESSL)"], 2023, "The International Fujita (IF) Scale – "
       "Tornado and Wind Damage Assessment Guide, Version 1.0", "ESSL, Weßling", "norm",
       url="https://www.essl.org/cms/wp-content/uploads/IF-scale_v1.0.pdf", topics=("tornado",)),

    # ------------------------------------------------------------------ Fachliteratur
    _s("biljecki2016", ["Biljecki, F.", "Ledoux, H.", "Stoter, J."], 2016, "An improved LOD specification for 3D "
       "building models", "Computers, Environment and Urban Systems 59, 25–37",
       doi="10.1016/j.compenvurbsys.2016.04.005", topics=("modell",)),
    _s("biljecki2017", ["Biljecki, F.", "Ledoux, H.", "Stoter, J."], 2017, "Generating 3D city models without "
       "elevation data", "Computers, Environment and Urban Systems 64, 1–18",
       doi="10.1016/j.compenvurbsys.2017.01.001", topics=("modell",)),
    _s("teng2017", ["Teng, J.", "Jakeman, A. J.", "Vaze, J.", "et al."], 2017, "Flood inundation modelling: A review "
       "of methods, recent advances and uncertainty analysis", "Environmental Modelling & Software 90, 201–216",
       doi="10.1016/j.envsoft.2017.01.006", topics=("hochwasser",)),
    _s("barnes2014", ["Barnes, R.", "Lehman, C.", "Mulla, D."], 2014, "Priority-Flood: An optimal depression-filling "
       "and watershed-labeling algorithm for digital elevation models", "Computers & Geosciences 62, 117–127",
       doi="10.1016/j.cageo.2013.04.024", topics=("starkregen",)),
    _s("ocallaghan1984", ["O'Callaghan, J. F.", "Mark, D. M."], 1984, "The extraction of drainage networks from "
       "digital elevation data", "Computer Vision, Graphics, and Image Processing 28(3), 323–344",
       doi="10.1016/S0734-189X(84)80011-0", topics=("starkregen",)),
    _s("hellmann1915", ["Hellmann, G."], 1915, "Über die Bewegung der Luft in den untersten Schichten der Atmosphäre",
       "Meteorologische Zeitschrift 32, 1–16", topics=("wind",)),
    _s("davenport1960", ["Davenport, A. G."], 1960, "Rationale for determining design wind velocities",
       "Journal of the Structural Division (ASCE) 86(5), 39–68", doi="10.1061/JSDEAG.0000521", topics=("wind",)),
    _s("oke1988", ["Oke, T. R."], 1988, "Street design and urban canopy layer climate", "Energy and Buildings 11, "
       "103–113", doi="10.1016/0378-7788(88)90026-6", topics=("wind",)),
    _s("blocken2008", ["Blocken, B.", "Moonen, P.", "Stathopoulos, T.", "Carmeliet, J."], 2008, "Numerical study on "
       "the existence of the Venturi effect in passages between perpendicular buildings",
       "Journal of Engineering Mechanics 134(12), 1021–1028", doi="10.1061/(ASCE)0733-9399(2008)134:12(1021)",
       topics=("wind",)),
    _s("blocken2015", ["Blocken, B."], 2015, "Computational Fluid Dynamics for urban physics: Importance, scales, "
       "possibilities, limitations and ten tips and tricks towards accurate and reliable simulations",
       "Building and Environment 91, 219–245", doi="10.1016/j.buildenv.2015.02.015", topics=("wind",)),
    _s("lawson1975", ["Lawson, T. V.", "Penwarden, A. D."], 1975, "The effects of wind on people in the vicinity of "
       "buildings", "Proceedings of the 4th International Conference on Wind Effects on Buildings and Structures, "
       "Cambridge University Press, 605–622", topics=("wind",)),
    _s("anderson2017", ["Anderson, J. D."], 2017, "Fundamentals of Aerodynamics, 6. Auflage", "McGraw-Hill, New York",
       topics=("wind",)),
    _s("lagomarsino2006", ["Lagomarsino, S.", "Giovinazzi, S."], 2006, "Macroseismic and mechanical models for the "
       "vulnerability and damage assessment of current buildings", "Bulletin of Earthquake Engineering 4, 415–443",
       doi="10.1007/s10518-006-9024-z", topics=("erdbeben",)),
    _s("gutenberg1956", ["Gutenberg, B.", "Richter, C. F."], 1956, "Earthquake magnitude, intensity, energy, and "
       "acceleration (second paper)", "Bulletin of the Seismological Society of America 46(2), 105–145",
       doi="10.1785/BSSA0460020105", topics=("erdbeben",)),
    _s("sponheuer1960", ["Sponheuer, W."], 1960, "Methoden zur Herdtiefenbestimmung in der Makroseismik",
       "Freiberger Forschungshefte C 88, Akademie-Verlag, Berlin", topics=("erdbeben",)),
    _s("wald1999", ["Wald, D. J.", "Quitoriano, V.", "Heaton, T. H.", "Kanamori, H."], 1999, "Relationships between "
       "peak ground acceleration, peak ground velocity, and Modified Mercalli Intensity in California",
       "Earthquake Spectra 15(3), 557–564", doi="10.1193/1.1586058", topics=("erdbeben",)),
    _s("cornell1968", ["Cornell, C. A."], 1968, "Engineering seismic risk analysis", "Bulletin of the Seismological "
       "Society of America 58(5), 1583–1606", doi="10.1785/BSSA0580051583", topics=("erdbeben",)),
    _s("brooks2004", ["Brooks, H. E."], 2004, "On the relationship of tornado path length and width to intensity",
       "Weather and Forecasting 19(2), 310–319", doi="10.1175/1520-0434(2004)019<0310:OTROTP>2.0.CO;2",
       topics=("tornado",)),
    _s("holton2013", ["Holton, J. R.", "Hakim, G. J."], 2013, "An Introduction to Dynamic Meteorology, 5. Auflage",
       "Academic Press, Amsterdam", topics=("tornado",)),
    _s("beyer2025", ["Beyer, M.", "Wapler, K.", "Kühne, T."], 2025, "Tornadoes in Germany: intensity, temporal and "
       "spatial distribution", "Meteorologische Zeitschrift 34(4), 237–250", doi="10.1127/metz/1276",
       topics=("tornado",)),
    _s("gumbel1958", ["Gumbel, E. J."], 1958, "Statistics of Extremes", "Columbia University Press, New York",
       topics=("wahrscheinlichkeit",)),
    _s("coles2001", ["Coles, S."], 2001, "An Introduction to Statistical Modeling of Extreme Values",
       "Springer, London", doi="10.1007/978-1-4471-3675-0", topics=("wahrscheinlichkeit",)),
    _s("galileo1638", ["Galilei, G."], 1638, "Discorsi e dimostrazioni matematiche intorno a due nuove scienze",
       "Elsevier, Leiden", topics=("kaiju",)),
    _s("hokkanen1986", ["Hokkanen, J. E. I."], 1986, "The size of the largest land animal",
       "Journal of Theoretical Biology 118(4), 491–499",
       url="https://www.miketaylor.org.uk/dino/hokkanen/Size-Hokkanen.html", topics=("kaiju",)),
    _s("hanley1983", ["Hanley, J. A.", "Lippman-Hand, A."], 1983, "If nothing goes wrong, is everything all right? "
       "Interpreting zero numerators", "JAMA 249(13), 1743–1745", doi="10.1001/jama.1983.03330370053031",
       topics=("kaiju",)),
    _s("hanson2021", ["Hanson, R.", "Martin, D.", "McCarter, C.", "Paulson, J."], 2021, "If loud aliens explain human "
       "earliness, quiet aliens are also rare", "The Astrophysical Journal 922(2), 182", doi="10.3847/1538-4357/ac2369",
       topics=("aliens",)),
    _s("snyderbeattie2019", ["Snyder-Beattie, A. E.", "Ord, T.", "Bonsall, M. B."], 2019, "An upper bound for the "
       "background rate of human extinction", "Scientific Reports 9, 11054", doi="10.1038/s41598-019-47540-7",
       topics=("aliens",)),
]

SOURCES: dict[str, Source] = {s.key: s for s in _ALL}
KIND_NAMES = {"paper": "Fachliteratur", "norm": "Normen, Richtlinien und Skalen", "data": "Daten und Dienste"}


def cite(*keys: str) -> str:
    """Kurzzitat: „Lagomarsino & Giovinazzi (2006); Wald et al. (1999)“."""
    return "; ".join(SOURCES[k].short for k in keys)


def bibtex(keys=None) -> str:
    """BibTeX für alle (oder die angegebenen) Quellen – z. B. für Hausarbeiten."""
    entries = []
    for s in (SOURCES[k] for k in keys) if keys else SOURCES.values():
        kind = {"paper": "article" if any(c.isdigit() for c in s.venue) else "book"}.get(s.kind, "misc")
        names = [a if "," in a else "{" + a + "}" for a in s.authors if a != "et al."]   # Institutionen klammern
        fields = {"author": " and ".join(names) + (" and others" if "et al." in s.authors else ""),
                  "title": s.title, "year": s.year}
        if kind == "article":
            fields["journal"] = s.venue
        elif kind == "book":
            fields["publisher"] = s.venue
        else:
            fields["howpublished"] = s.venue
        if s.doi:
            fields["doi"] = s.doi
        if s.url:
            fields["url"] = s.url
        body = ",\n".join(f"  {k} = {{{_bib_escape(v)}}}" for k, v in fields.items())
        entries.append(f"@{kind}{{{s.key},\n{body}\n}}")
    return "\n\n".join(entries) + "\n"


def _bib_escape(text: str) -> str:
    return str(text).replace("&", r"\&").replace("%", r"\%")
