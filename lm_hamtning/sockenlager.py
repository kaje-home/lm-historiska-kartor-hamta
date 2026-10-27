"""Socknarna i arkivets lan -- ett lager, byggt en gang (beslut 2026-09-29).

Socken och stads ytor, en rad per socken eller stad, med arkivets lan,
socken och koder. Byggs ur `urval.koppla` for hela landet (18 s) och ligger
sedan i tjanstecachen, eftersom kopplingen bygger pa arkivets vokabular.

**Poangen ar anvandarens val, inte farten.** 2 425 av 2 473 kopplas utan
hjalp. Resten -- namn som arkivet skriver annorlunda (Kiruna, Åtvid) och
namn som finns i flera gamla lan -- valjer anvandaren en gang. Valen ligger
i en egen tabell, `val`, som inte rors nar lagret byggs om: nar vokabularen
hamtas pa nytt byggs `socknar` om och valen laggs pa igen.

Tabellen `socknar` (MultiPolygon, SWEREF 99 TM):

    sockenstadkod, sockenstadnamn, sockenstadtyp   ur Socken och stad
    lanskod       dagens lan (Kommun, lan och rike) for socknens lage
    hur           namn | annat namn | län | flera | valt | oklar | saknas
    arkiv         JSON: arkivets socknar att soka -- en, flera, eller ingen
    kandidater    JSON: det anvandaren kan valja mellan nar `arkiv` ar tom

En arkivsocken i JSON: {"lan", "socken", "reg_kod", "lms_nummer"}.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

from . import urval
from .register import anvandare, nu

FILNAMN = "socknar.gpkg"
LAGER = "socknar"
VAL = "val"
VALT = urval.VALT


def _arkiv(s) -> dict:
    return {"lan": s.lan.namn, "socken": s.namn, "reg_kod": s.reg_kod,
            "lms_nummer": s.lms_nummer}


def _las_val(ds) -> dict[str, list[dict]]:
    """Senaste valet per sockenstadkod."""
    lager = ds.GetLayerByName(VAL)
    if lager is None:
        return {}
    rader = sorted(((f["tid"], f.GetFID(), f["sockenstadkod"], f["arkiv"])
                    for f in lager), key=lambda r: (r[0], r[1]))
    return {kod: json.loads(a) for _, _, kod, a in rader}


def bygg(sokvag: str, socken_och_stad: str, lan: str | None, vokabular,
         omrade=None) -> dict[str, int]:
    """Bygg (om) `socknar`. `val` behalls. Returnerar antal per `hur`.

    `omrade` begransar till ett omrade (prov); utan det hela landet.
    """
    from osgeo import gdal, ogr, osr
    gdal.UseExceptions()
    if omrade is None:
        omrade = ("POLYGON((200000 6100000,1000000 6100000,1000000 7700000,"
                  "200000 7700000,200000 6100000))")
    socknar = urval.koppla(urval.socknar_i_omrade(omrade, socken_och_stad, lan),
                           vokabular)

    if os.path.exists(sokvag):
        ds = ogr.Open(sokvag, 1)
        for i in range(ds.GetLayerCount() - 1, -1, -1):
            if ds.GetLayer(i).GetName() == LAGER:
                ds.DeleteLayer(i)
    else:
        os.makedirs(os.path.dirname(os.path.abspath(sokvag)), exist_ok=True)
        ds = ogr.GetDriverByName("GPKG").CreateDataSource(sokvag)
    if ds.GetLayerByName(VAL) is None:
        v = ds.CreateLayer(VAL, geom_type=ogr.wkbNone)
        for n in ("sockenstadkod", "arkiv", "tid", "anvandare"):
            v.CreateField(ogr.FieldDefn(n, ogr.OFTString))
    val = _las_val(ds)

    srs = osr.SpatialReference()
    srs.ImportFromEPSG(3006)
    l = ds.CreateLayer(LAGER, srs, ogr.wkbMultiPolygon)
    for n, t in (("sockenstadkod", ogr.OFTString), ("sockenstadnamn", ogr.OFTString),
                 ("sockenstadtyp", ogr.OFTInteger), ("lanskod", ogr.OFTString),
                 ("hur", ogr.OFTString), ("arkiv", ogr.OFTString),
                 ("kandidater", ogr.OFTString)):
        l.CreateField(ogr.FieldDefn(n, t))
    l.SetMetadataItem("byggd", nu())

    antal: dict[str, int] = {}
    ds.StartTransaction()
    for s in socknar:
        if s.kod in val:
            hur, arkiv = VALT, val[s.kod]
        elif s.socken is not None:
            hur, arkiv = s.hur, [_arkiv(s.socken)]
        elif s.hur == urval.FLERA:
            hur, arkiv = s.hur, [_arkiv(k) for k in s.kandidater]
        else:
            hur, arkiv = s.hur, []
        f = ogr.Feature(l.GetLayerDefn())
        f["sockenstadkod"], f["sockenstadnamn"] = s.kod, s.namn
        f["sockenstadtyp"], f["lanskod"], f["hur"] = s.typ, s.lanskod, hur
        f["arkiv"] = json.dumps(arkiv, ensure_ascii=False)
        f["kandidater"] = json.dumps([_arkiv(k) for k in s.kandidater],
                                     ensure_ascii=False)
        f.SetGeometry(ogr.ForceToMultiPolygon(ogr.CreateGeometryFromWkb(s.wkb)))
        l.CreateFeature(f)
        antal[hur] = antal.get(hur, 0) + 1
    ds.CommitTransaction()
    ds = None
    return antal


def valj(sokvag: str, sockenstadkod: str, arkivsocknar: list,
         av: str | None = None) -> None:
    """Anvandarens val: vilka av arkivets socknar sockenstadkoden ar.

    Sparas i `val` och slar igenom direkt i `socknar`. En tom lista ar ocksa
    ett val: socknen finns inte i arkivet.
    """
    from osgeo import gdal, ogr
    gdal.UseExceptions()
    arkiv = json.dumps([_arkiv(s) for s in arkivsocknar], ensure_ascii=False)
    ds = ogr.Open(sokvag, 1)
    v = ds.GetLayerByName(VAL)
    f = ogr.Feature(v.GetLayerDefn())
    f["sockenstadkod"], f["arkiv"] = sockenstadkod, arkiv
    f["tid"], f["anvandare"] = nu(), av or anvandare()
    v.CreateFeature(f)
    l = ds.GetLayerByName(LAGER)
    l.SetAttributeFilter(f"sockenstadkod = '{sockenstadkod.replace(chr(39), '')}'")
    for r in l:
        r["hur"], r["arkiv"] = VALT, arkiv
        l.SetFeature(r)
    ds = None


@dataclass
class Granne:
    socken: object          # arkivets socken (tjanst.Socken)
    sockenstadnamn: str     # grannens namn i Socken och stad
    sockenstadkod: str


def grannar(sokvag: str, sockenstadkod: str, vokabular,
            avstand_m: float = 100.0) -> list[Granne]:
    """Grannsocknarna till `sockenstadkod`, med arkivets socknar.

    **Varfor.** Sockengranserna har andrats, och Socken och stad visar den
    senare indelningen. Marby och Sunne gjordes om radikalt under tidigt
    1900-tal: kartor fran 1800-talet och aldre over Vällviken ligger i Sunne,
    vilket ar ratt for sin tid, men Vällviken ligger i Marby pa dagens karta
    (anvandaren 2026-09-29). Vokabularen visar det: Vällviken finns under
    Marby i REG och under Sunne i bada arkiven. Urvalet letar darfor efter
    trakterna ocksa i grannsocknarna (urval._matcha).

    `avstand_m`: Socken och stads grannar moter varandra inte alltid exakt.
    """
    from osgeo import gdal, ogr
    gdal.UseExceptions()
    ds = ogr.Open(sokvag)
    l = ds.GetLayerByName(LAGER)
    l.SetAttributeFilter(f"sockenstadkod = '{sockenstadkod.replace(chr(39), '')}'")
    egen = None
    for f in l:
        g = f.GetGeometryRef().Buffer(avstand_m)
        egen = g if egen is None else egen.Union(g)
    if egen is None:
        return []
    l.SetAttributeFilter(None)
    l.SetSpatialFilter(egen)
    ut = []
    for f in l:
        if f["sockenstadkod"] == sockenstadkod or \
                not f.GetGeometryRef().Intersects(egen):
            continue
        for a in json.loads(f["arkiv"] or "[]"):
            s = vokabular.socken_i_lan(a["lan"], a["socken"])
            if s is not None and all(s is not x.socken for x in ut):
                ut.append(Granne(s, f["sockenstadnamn"], f["sockenstadkod"]))
    return ut


def socknar_i_omrade(sokvag: str, omrade, vokabular) -> list:
    """Som `urval.socknar_i_omrade` + `koppla`, men ur lagret -- med valen.

    Returnerar `urval.SockenIOmrade`. `socken` ar satt nar lagret pekar ut
    en arkivsocken; `flera` har alla i `kandidater`; `oklar` och `saknas`
    har det anvandaren kan valja mellan i `kandidater`.
    """
    from osgeo import gdal, ogr
    gdal.UseExceptions()
    g = urval._geom(omrade)
    ds = ogr.Open(sokvag)
    l = ds.GetLayerByName(LAGER)
    l.SetSpatialFilter(g)
    ut = []
    for f in l:
        sg = f.GetGeometryRef()
        if not sg.Intersects(g):
            continue
        yta = sg.Intersection(g).GetArea()
        if yta <= 0:
            continue
        s = urval.SockenIOmrade(f["sockenstadnamn"], f["sockenstadkod"],
                                f["sockenstadtyp"], yta, f["lanskod"] or "")
        s.hur = f["hur"]
        arkiv = [vokabular.socken_i_lan(a["lan"], a["socken"])
                 for a in json.loads(f["arkiv"] or "[]")]
        arkiv = [a for a in arkiv if a is not None]
        if len(arkiv) == 1:
            s.socken = arkiv[0]
        elif len(arkiv) > 1:
            s.hur, s.kandidater = urval.FLERA, arkiv
        if not arkiv:
            s.kandidater = [k for k in (vokabular.socken_i_lan(a["lan"], a["socken"])
                                        for a in json.loads(f["kandidater"] or "[]"))
                            if k is not None]
        ut.append(s)
    return sorted(ut, key=lambda s: -s.yta_m2)
