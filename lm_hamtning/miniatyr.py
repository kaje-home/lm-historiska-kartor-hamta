"""Miniatyrer av kartsidorna, gjorda ur akt-PDF:en (avsnitt 4 punkt 2).

Tjansten har ingen miniatyrtjanst. Akt-PDF:en har daremot varje sida, och
QGIS:s egen GDAL rastrerar den direkt: en underdatamangd per sida,
`PDF:<n>:<fil>`, med oppningsvalet `DPI`. Inget nytt beroende.

Provat 2026-09-28 pa 23-hag-10: 20 dpi ger kartsidan 484 x 458 px, tydlig
nog att se om kartan ar vard att oppna, och alla tio sidorna tar 1,5 s.

**PDF-sidan ar visarens sida.** PDF:en har lika manga sidor som metadatat
har SIDA-poster, i samma ordning (23-hag-10: 10 och 10, kartan forst;
Y22-2:1: 4 och 4). Stammer antalet inte ar kopplingen okand, och det ar ett
fel -- en miniatyr av fel sida ar varre an ingen.
"""
from __future__ import annotations

import os

DPI = 20            # kontaktkartan
DPI_STOR = 60       # forstoringen: 23-hag-10 s. 1 blir ca 1450 px
DPI_SKARP = 150     # forstoringen inzoomad: 23-hag-10 s. 1 ca 3600 px

# GDAL lagger annars en .aux.xml bredvid varje PDF den oppnar -- i cachen,
# en per akt, till ingen nytta.
_UTAN_AUX = {"GDAL_PAM_ENABLED": "NO"}


class MiniatyrFel(RuntimeError):
    pass


def antal_sidor(pdf: str) -> int:
    from osgeo import gdal
    gdal.UseExceptions()
    with gdal.config_options(_UTAN_AUX):
        ds = gdal.Open(pdf)
        sub = ds.GetMetadata("SUBDATASETS") or {}
    n = sum(1 for k in sub if k.endswith("_NAME"))
    return n or 1           # en sida: inga underdatamangder


def sida_ur_pdf(pdf: str, sidnr: int, mal: str, dpi: int = DPI) -> str:
    """Sidan `sidnr` (1-baserad) som JPEG. Ett befintligt `mal` ateranvands."""
    from osgeo import gdal
    gdal.UseExceptions()
    if os.path.exists(mal):
        return mal
    os.makedirs(os.path.dirname(os.path.abspath(mal)), exist_ok=True)
    kalla = f"PDF:{sidnr}:{pdf}" if antal_sidor(pdf) > 1 else pdf
    tmp = f"{mal}.{os.getpid()}.delvis.jpg"
    try:
        with gdal.config_options(_UTAN_AUX):
            ds = gdal.OpenEx(kalla, gdal.OF_RASTER, open_options=[f"DPI={dpi}"])
            gdal.Translate(tmp, ds, format="JPEG", creationOptions=["QUALITY=85"])
            ds = None
        os.replace(tmp, mal)
    finally:
        for rest in (tmp, tmp + ".aux.xml"):
            if os.path.exists(rest):
                os.remove(rest)
    return mal


def filnamn(akt, sida, dpi: int = DPI) -> str:
    return f"{akt.arkiv}_{akt.bas}_{akt.ktun}_s{sida.lopnr}_{dpi}dpi.jpg"


def kartsidor(klient, akt, katalog: str, dpi: int = DPI,
              bara_forsta: bool = False) -> list[str]:
    """Miniatyrer av aktens kartsidor, i `katalog`. Hamtar PDF:en vid behov.

    `akt` maste ha sidregistret (metadata). `bara_forsta`: kontaktkartan
    visar forsta kartbladet och en raknare (avsnitt 6).
    """
    sidor = akt.kartsidor
    if sidor is None:
        raise MiniatyrFel(f"{akt.beteckning}: sidregistret är inte hämtat")
    if not sidor:
        return []
    if bara_forsta:
        sidor = sidor[:1]
    klara = [os.path.join(katalog, filnamn(akt, s, dpi)) for s in sidor]
    if all(os.path.exists(f) for f in klara):
        return klara
    pdf = klient.akt_pdf(akt)
    n = antal_sidor(pdf)
    if n != len(akt.sidor):
        raise MiniatyrFel(f"{akt.beteckning}: PDF:en har {n} sidor men "
                          f"metadatat {len(akt.sidor)} — sidorna går inte att koppla")
    return [sida_ur_pdf(pdf, s.lopnr, f, dpi) for s, f in zip(sidor, klara)]
