"""TERRA-Sim – wiederverwendbare Module.

Jedes Modul ist für sich allein nutzbar und tauscht nur einfache Datentypen aus:

* Bounding-Box als Tupel ``(west, south, east, north)`` in WGS84-Grad
* Geodaten als ``geopandas.GeoDataFrame``
* Raster als ``numpy``-Arrays

So lassen sich einzelne Dateien in eigene Projekte kopieren, ohne den Rest
von TERRA-Sim mitzunehmen.
"""
