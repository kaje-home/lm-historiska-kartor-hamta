"""Fastighetsindelningen som referens: hämtning ur Lantmäteriets STAC-katalog.

En zip med ett geopackage per kommun (`fastighetsindelning_kn2380.zip`,
Östersund 22,6 MB). Katalogen är öppen; nedladdningen kräver Geotorget-kontot
(401 utan), så den körs i QGIS med pluginets eget konto (underlag.atkomst;
Fältunderlagets bara som förval i samma profil) -- som markhöjdmodellen
(terrang.py).

**Villkor (avsnitt 11, användaren 2026-09-29):** inga ägaruppgifter läses,
fastighetsnummer används bara för att matcha akter, och ingenting ur
fastighetsindelningen exporteras till fältdatorn eller i tipsen. Pluginet läser
bara gränslinjerna och ytornas geometri.

**Trakterna (2026-10-27, användaren: "om en användare ansöker om fastighetsindelning
på LM, kan hen få trakterna därifrån?").** Varje kommunfil har lagret `traktyta`:
Lantmäteriets egna traktytor, fastigheterna sammanslagna per trakt, med namnet i
`etikett` (versaler, "HÄGGENÅS-HÖGEN", samma namnsystem som arkivets REG-trakter;
"OUTRETT OMRÅDE" för det outredda). `traktlager()` läser dem som ett traktlager
(traktlager.py: delat på socken mot Socken och stad, kvarteren i städerna bort) och
är den andra traktkällan i Gallra, efter det egna traktlagret och före
ortnamnsregistret (steg.py). Produkten är avgiftsfri men kräver juridisk prövning
och har personuppgiftsvillkor, så trakterna följer aldrig med pluginet: varje
användare läser sin egen nedladdade fil, i arkivets referens/fastighetsindelning
(hämtad med kontot) eller i referensdatan (nedladdad för hand).
"""
from __future__ import annotations

import glob
import json
import os
import urllib.request
import zipfile

STAC = "https://api.lantmateriet.se/stac-vektor/v1"
MAPP = "fastighetsindelning"
PRODUKT = "Fastighetsindelning Nedladdning, vektor"
PRODUKTSIDA = "https://geotorget.lantmateriet.se/geodataprodukter/fastighetsindelning-nedladdning-vektor-api"
TRAKTLAGER = "traktyta"          # Lantmäteriets traktytor i varje kommunfil
TRAKTFALT = "etikett"            # traktnamnet, versaler


def ar_fil(filnamn: str) -> bool:
    """Ett geopackage ur produkten, som zippen packas upp (`fastighetsindelning_kn2380.gpkg`)."""
    n = filnamn.lower()
    return n.startswith("fastighetsindelning") and n.endswith(".gpkg")


def kommunkoder(ruta, fil: str) -> list[str]:
    """Kommunerna som verkligen skär rutan (SWEREF 99 TM), ur Lantmäteriets Kommun, län
    och rike (`fil`, kommuner.py; förut SCB:s kommunfil, bytt 2026-10-26). Katalogens
    rutor överlappar: en sökning på Häggenås gav fyra kommuner, fast socknen bara ligger
    i Östersunds (2026-10-01)."""
    from . import kommuner
    return kommuner.kommunkoder(ruta, fil)


def socknens_kommuner(sockenlager: str, socken: str, fil: str) -> list[str]:
    """Kommunerna som socknens yta ligger i (kommuner.socknens_kommuner)."""
    from . import kommuner
    return kommuner.socknens_kommuner(sockenlager, socken, fil)


def kommun(kod: str) -> dict:
    """Kommunens fil i katalogen: {id, titel, href, byte}."""
    with urllib.request.urlopen(f"{STAC}/collections/fastighetsindelning/items/{kod}",
                                timeout=60) as svar:
        f = json.load(svar)
    a = f["assets"]["data"]
    return {"id": f["id"], "titel": f["properties"].get("title", f["id"]),
            "href": a["href"], "byte": a.get("file:size")}


def filer(referensmapp: str) -> list[str]:
    return sorted(glob.glob(os.path.join(referensmapp, MAPP, "*.gpkg")))


def traktlager(filer_: list[str], socken_och_stad: str, bara_socknar: set[str] | None = None):
    """Lantmäteriets traktytor (`traktyta`, namnet i `etikett`) ur kommunfilerna som ett
    traktlager.Traktlager, delat på socken mot Socken och stad precis som ett eget lager
    (traktlager.las: kvarteren i städerna bort, OUTRETT OMRÅDE bort, skärvorna för sig).
    Filer utan lagret hoppas över. Bara traktnamn och gränser läses; filerna ändras inte."""
    from osgeo import ogr
    from . import traktlager as _tl
    ut = _tl.Traktlager()
    for fil in filer_:
        ds = ogr.Open(fil)
        har = ds is not None and ds.GetLayerByName(TRAKTLAGER) is not None
        ds = None
        if not har:
            continue
        d = _tl.las(fil, TRAKTLAGER, TRAKTFALT, socken_och_stad, None, bara_socknar)
        ut.ytor += d.ytor
        ut.skrap += d.skrap
        ut.i_stad += d.i_stad
        ut.utanfor += d.utanfor
        ut.skarvor += d.skarvor
    return ut


class _Aterkoppling:
    """underlag.nedladdning (kopierad ur Fältunderlaget) vill ha ett feedback-objekt."""

    def __init__(self, framsteg, avbruten):
        self._f, self._a, self._text = framsteg, avbruten, ""

    def isCanceled(self):
        return bool(self._a and self._a())

    def setProgress(self, p):
        if self._f:
            self._f(self._text, p / 100)

    def setProgressText(self, t):
        self._text = t


def hamta(koder: list[str], referensmapp: str, authcfg: str, framsteg=None,
          avbruten=None) -> list[str]:
    """Fastighetsindelningen för kommunerna till `referensmapp/fastighetsindelning`.
    Kommuner som redan finns hoppas över. -> geopackagen."""
    from .underlag import nedladdning
    mal = os.path.join(referensmapp, MAPP)
    os.makedirs(mal, exist_ok=True)
    ut = []
    for kod in koder:
        befintliga = glob.glob(os.path.join(mal, f"*kn{kod}*.gpkg"))
        if befintliga:
            ut += befintliga
            continue
        k = kommun(kod)
        befintliga = glob.glob(os.path.join(mal, f"*kn{k['id']}*.gpkg"))
        if befintliga:
            ut += befintliga
            continue
        zipfil = os.path.join(mal, os.path.basename(k["href"]))
        nedladdning.hamta_fil(k["href"], zipfil, authcfg, produkt="Fastighetsindelning",
                              etikett=k["titel"], feedback=_Aterkoppling(framsteg, avbruten))
        with zipfile.ZipFile(zipfil) as z:
            for n in z.namelist():
                if n.lower().endswith(".gpkg"):
                    z.extract(n, mal)
                    ut.append(os.path.join(mal, n))
        os.remove(zipfil)
    return ut


# ------------------------------------------------------------- grovplacering
# Kartan läggs där aktens fastigheter ligger (KRAV avsnitt 7, användaren
# 2026-10-01). Fastighetsnumren används bara här, för att hitta läget.

def aktens_fastigheter(ra_metadata: str | dict | None) -> list[tuple[str, str, int]]:
    """(trakt, block, enhet) ur aktens FAST-grupper: gällande beteckning
    (GTRA/GBLO/GENH), annars den ursprungliga (UTRA/UBLO/UENH)."""
    if not ra_metadata:
        return []
    m = json.loads(ra_metadata) if isinstance(ra_metadata, str) else ra_metadata
    ut = []
    for g in m.get("paragraphGroups") or []:
        if g.get("name") != "FAST":
            continue
        p = {x.get("name"): (x.get("text") or "").strip() for x in g.get("paragraphs") or []}
        for t, b, e in (("GTRA", "GBLO", "GENH"), ("UTRA", "UBLO", "UENH")):
            if p.get(t) and p.get(b) and p.get(e, "").isdigit():
                ut.append((p[t].upper(), p[b], int(p[e])))
                break
    return list(dict.fromkeys(ut))


def aktens_kommuner(ra_metadata: str | dict | None) -> dict:
    """{(trakt, block, enhet): kommun} för aktens gällande beteckningar (GTRA/GBLO/GENH
    med GKOM, versaler som fastighetsindelningens `kommunnamn`). Samma beteckning finns
    i flera kommuner: Västbyn i Frösö (Östersund) och i Offerdal (Krokom) -- FRJ-47 s. 1
    lades 38 km fel (2026-10-18). Ursprungliga beteckningar (UKOM "Z-FRÖSÖ", ett gammalt
    registerområde) får ingen kommun."""
    if not ra_metadata:
        return {}
    m = json.loads(ra_metadata) if isinstance(ra_metadata, str) else ra_metadata
    ut = {}
    for g in m.get("paragraphGroups") or []:
        if g.get("name") != "FAST":
            continue
        p = {x.get("name"): (x.get("text") or "").strip() for x in g.get("paragraphs") or []}
        if p.get("GTRA") and p.get("GBLO") and p.get("GENH", "").isdigit():
            kom = p.get("GKOM", "").upper()
            ut[(p["GTRA"].upper(), p["GBLO"], int(p["GENH"]))] = kom if kom and not kom.startswith("Z-") else None
    return ut


def ytor(filer_: list[str], fastigheter, kommuner: dict | None = None) -> list[tuple[float, float, float]]:
    """(x, y, yta m²) för varje område av fastigheterna, ur `registerenhetsomradesyta`.
    `kommuner` (aktens_kommuner): en fastighet med känd kommun räknas bara i den."""
    from osgeo import ogr
    sokt = set(fastigheter)
    trakter = sorted({t for t, _, _ in sokt})
    if not trakter:
        return []
    ut = []
    for fil in filer_:
        ds = ogr.Open(fil)
        lg = ds.GetLayerByName("registerenhetsomradesyta") if ds else None
        if lg is None:
            continue
        lg.SetAttributeFilter("trakt IN (" + ",".join("'" + t.replace("'", "''") + "'"
                                                      for t in trakter) + ")")
        for f in lg:
            nyckel = (str(f.GetField("trakt")).upper(), str(f.GetField("block")), int(f.GetField("enhet") or 0))
            if nyckel not in sokt:
                continue
            kom = (kommuner or {}).get(nyckel)
            if kom and str(f.GetField("kommunnamn") or "").upper() != kom:
                continue                                  # samma beteckning i en annan kommun
            g = f.GetGeometryRef()
            if g is None:
                continue
            c = g.Centroid()
            ut.append((c.GetX(), c.GetY(), g.GetArea()))
    return ut


def basta_lage(punkter, bredd_m: float, hojd_m: float) -> tuple[float, float, int] | None:
    """Där flest av områdena ryms inom kartans utbredning (bredd x höjd, utan
    vridning): byn med sina små skiften för en inägokarta, hela området för en
    utmarkskarta. -> (x, y, antal) eller None."""
    if not punkter:
        return None
    import numpy as np
    p = np.asarray(punkter, float)
    halv = np.array([bredd_m / 2, hojd_m / 2])
    bast = None
    for c in p[:, :2]:
        inne = np.all(np.abs(p[:, :2] - c) <= halv, axis=1)
        nyckel = (int(inne.sum()), float(p[inne, 2].sum()))
        if bast is None or nyckel > bast[0]:
            bast = (nyckel, inne)
    inne = bast[1]
    x, y = p[inne, :2].mean(axis=0)
    return float(x), float(y), int(inne.sum())


def lagen(punkter, bredd_m: float, hojd_m: float, antal: int = 3) -> list[tuple[float, float, str]]:
    """Förslag på kartans läge ur fastighetsytorna, bästa först: där flest
    ytor ryms inom kartans utbredning, sedan samma sak bland ytorna som blev
    över. En akts fastigheter ligger ofta i flera klungor -- HÄG-73: ett
    tiotal små skiften i byn och sex stora skogsskiften 12 km bort, där
    utmarkskartan ligger."""
    import numpy as np
    p = np.asarray(punkter, float).reshape(-1, 3)
    halv = np.array([bredd_m / 2, hojd_m / 2])
    kvar = np.ones(len(p), bool)
    ut = []
    while kvar.any() and len(ut) < antal:
        q = p[kvar]
        bast = None
        for c in q[:, :2]:
            inne = np.all(np.abs(q[:, :2] - c) <= halv, axis=1)
            nyckel = (int(inne.sum()), float(q[inne, 2].sum()))
            if bast is None or nyckel > bast[0]:
                bast = (nyckel, inne)
        x, y = q[bast[1], :2].mean(axis=0)
        ha = q[bast[1], 2].sum() / 1e4
        ut.append((float(x), float(y), f"aktens fastigheter: {int(bast[1].sum())} av {len(p)} "
                                       f"ytor, {ha:.0f} ha"))
        kvar &= ~np.all(np.abs(p[:, :2] - [x, y]) <= halv, axis=1)
    return ut
