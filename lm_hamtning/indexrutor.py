"""Lantmateriets indexrutor, 5 km i SWEREF 99 TM.

Overtagen ur LM Faltunderlag (verktyg/indexrutor.py, samma upphovsman och
licens) 2026-09-29, sa att rutorna visas och markeras pa samma satt i bada
pluginen: bara rutorna i kartans vy, som ett minneslager, rutnatet raknat
fram i stallet for last ur Lantmateriets fil. Andras har, andras dar.

Manga uppdrag beskrivs i rutor, inte i ytor: bestallningen sager vilka rutor som
ska tackas, och det ar sa man ar van att tanka. Verktyget tar emot bada.

**Rutnatet raknas fram, det hamtas inte -- och harledningen ar bevisad.**
Lantmateriet publicerar rutnatet som oppna data
(`lantmateriet.se/globalassets/geodata/oppna-data/index_5km.zip`). Den filen ar
1,8 MB zippad men 12,5 MB som GeoPackage, vilket ar for tungt att lagga i ett
plugin och en onodig sak att halla uppdaterad.

Alternativet -- att rakna fram beteckningen -- ar bara forsvarbart om det ar
*bevisat* ratt. Star fel ruta i uttag.txt ar uppdraget felredovisat, och da duger
ingen egen tolkning av kodningen. Darfor jamfordes `beteckna()` mot samtliga
**54 400 rutor** i Lantmateriets fil 2026-09-12: **noll avvikelser**. Andras
funktionen ska den provningen goras om, inte antas.

Kodningen: `702_49_50` betyder norr 7020000 plus 5 km, ost 490000 plus 0 km.
Tredje faltet ar tva siffror -- nordforskjutning och ostforskjutning i hela
kilometer inom 10-kilometersrutan, alltsa 0 eller 5.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

RUTA_M = 5000
BETECKNINGSFALT = "rutid"

# Taket finns for att en utzoomad karta annars ger hela Sverige: 54 400 rutor
# med etiketter ar inget nagon vill rita, och ingen valjer sitt arbetsomrade
# darifran anda.
TAK = 4000

_MONSTER = re.compile(r"^(?P<n>\d{3})_(?P<e>\d{2})_(?P<nn>\d)(?P<ee>\d)$")


@dataclass(frozen=True)
class Ruta:
    beteckning: str
    minx: float
    miny: float

    @property
    def maxx(self) -> float:
        return self.minx + RUTA_M

    @property
    def maxy(self) -> float:
        return self.miny + RUTA_M


def beteckna(minx: float, miny: float) -> str:
    """Sydvastra hornet -> Lantmateriets rutbeteckning.

    Verifierad mot alla 54 400 rutor i `index_5km`, se modulens inledning.
    """
    n, rest_n = divmod(int(miny), 10000)
    e, rest_e = divmod(int(minx), 10000)
    return f"{n:03d}_{e:02d}_{rest_n // 1000:01d}{rest_e // 1000:01d}"


def tolka(beteckning: str) -> Ruta:
    """Rutbeteckning -> utbredning. For inskrivna eller inklistrade rutor."""
    m = _MONSTER.match(beteckning.strip())
    if not m:
        raise ValueError(
            f"'{beteckning}' följer inte Lantmäteriets 5 km-beteckning "
            f"(t.ex. 702_49_50).")
    d = m.groupdict()
    miny = int(d["n"]) * 10000 + int(d["nn"]) * 1000
    minx = int(d["e"]) * 10000 + int(d["ee"]) * 1000
    if int(d["nn"]) not in (0, 5) or int(d["ee"]) not in (0, 5):
        raise ValueError(
            f"'{beteckning}': förskjutningen måste vara 0 eller 5 km i vardera "
            f"led för en 5 km-ruta.")
    return Ruta(beteckning.strip(), float(minx), float(miny))


def rutor_i(minx: float, miny: float, maxx: float, maxy: float) -> list[Ruta]:
    """Alla rutor som skar en utbredning."""
    ut: list[Ruta] = []
    x0 = int(minx // RUTA_M) * RUTA_M
    y0 = int(miny // RUTA_M) * RUTA_M
    x = x0
    while x < maxx:
        y = y0
        while y < maxy:
            ut.append(Ruta(beteckna(x, y), float(x), float(y)))
            y += RUTA_M
            if len(ut) > TAK:
                return ut
        x += RUTA_M
    return ut


def rutnatslager(minx: float, miny: float, maxx: float, maxy: float,
                 crs_id: str = "EPSG:3006"):
    """Ett minneslager med rutorna over en utbredning, att markera i.

    Returnerar (lager, antal). Overskrids taket ar lagret avkortat och antalet
    sager hur manga som kom med -- anroparen far tala om det.
    """
    from qgis.core import (QgsVectorLayer, QgsFeature, QgsGeometry,
                           QgsRectangle)

    rutor = rutor_i(minx, miny, maxx, maxy)
    lag = QgsVectorLayer(
        f"Polygon?crs={crs_id}&field={BETECKNINGSFALT}:string(16)",
        "Indexrutor 5 km", "memory")
    dp = lag.dataProvider()
    objekt = []
    for r in rutor:
        f = QgsFeature(lag.fields())
        f.setGeometry(QgsGeometry.fromRect(
            QgsRectangle(r.minx, r.miny, r.maxx, r.maxy)))
        f.setAttributes([r.beteckning])
        objekt.append(f)
    dp.addFeatures(objekt)
    lag.updateExtents()
    return lag, len(rutor)


def yta_av(lager, bara_markerade: bool = True):
    """(geometri, beteckningar) for valda rutor.

    Rutorna slas ihop till en yta. Ligger de intill varandra blir det en enda
    polygon, ligger de isar blir det flera delar -- bada ar giltiga
    arbetsomraden och resten av kedjan behandlar dem likadant.
    """
    from qgis.core import QgsGeometry
    objekt = list(lager.getSelectedFeatures() if bara_markerade
                  else lager.getFeatures())
    if not objekt:
        return None, []
    beteckningar = sorted(str(f[BETECKNINGSFALT]) for f in objekt)
    yta = QgsGeometry.unaryUnion([QgsGeometry(f.geometry()) for f in objekt])
    return yta, beteckningar
