"""Traktens lage och referenslagren runt den (avsnitt 5 och 7).

**Lage** for grovplaceringen och referenslagren, i ordning:
traktlagret (traktens yta i socknen), fastighetsindelningens traktytor
(fastighet.traktlager, 2026-10-27 -- samma ordning som i Gallra, anvandaren:
"vi testar det"), ortnamnsregistret (traktnamnets lage), socknen.

**Referenslagren** behovs for att HITTA passpunkter. De laggs i en tillfallig
grupp i projektet, bara det som ror omradet, och tas bort nar man ar klar.
Kallor (KRAV avsnitt 2 och 5; pluginet hamtar sitt underlag sjalv sedan
2026-10-08 och laser varken uttag eller Faltunderlagets arkiv):

    historiska ortofoton  Lantmateriets WMS, ca 1960 och 1975, med Geotorget-kontot
    ekonomiska kartan     arkivets referens/ekonomiska_kartan (ekonomiska.py)
    skuggbild             raknas ur markhojdmodellen i arkivets referens (skuggbild.py)
    Topografi 10/50       akerkanter och strander (markkantlinje), vattendrag, vagar
    traktlagret           trakternas granser
    arkivet               redan rektifierade kartor i socknen

Rasterindexet over utpekade uttag togs bort 2026-10-12 (oanvant sedan 2026-10-08).
"""
from __future__ import annotations

import glob
import os
from dataclasses import dataclass, field

from . import namn as _namn

WMS_HISTORISKA = "https://maps.lantmateriet.se/historiska-ortofoton/wms/v1"
HISTORISKA_LAGER = (("OI.Histortho_60", "Historiskt ortofoto ca 1960"),
                    ("OI.Histortho_75", "Historiskt ortofoto ca 1975"))
TOPO50 = (("mark", "markkantlinje", "Åkerkanter och stränder (Topografi 50)", "120,90,40"),
          ("hydrografi", "hydrolinje", "Vattendrag (Topografi 50)", "40,110,190"),
          ("kommunikation", "vaglinje", "Vägar (Topografi 50)", "160,60,40"),
          ("kommunikation", "ovrig_vag", "Övriga vägar (Topografi 50)", "160,110,80"))


@dataclass
class Lage:
    x: float                    # SWEREF 99 TM
    y: float
    bredd_m: float
    hojd_m: float
    kalla: str                  # traktlager | fastighetsindelning | ortnamn | socken
    trakter: list[str] = field(default_factory=list)   # det som hittades

    def ruta(self, marginal_m: float = 2000.0) -> tuple[float, float, float, float]:
        b, h = self.bredd_m / 2 + marginal_m, self.hojd_m / 2 + marginal_m
        return (self.x - b, self.y - h, self.x + b, self.y + h)


def traktdelar(inst, socken: str, trakter: list[str], hogst: int | None = None,
               alltid: bool = False) -> list[tuple[float, float, str]]:
    """Trakternas skilda delar som egna lägen, största först: [(x, y, text)], bara när
    trakterna är mer än en del (startregler.TRAKTDELAR; ÖVERGÅRDEN i Rödön är två
    delar 4 km isär och traktens mitt hamnar mellan dem). Delar under
    TRAKTDEL_MINST_HA räknas inte; högst `hogst` (TRAKTDELAR_HOGST). `alltid`: också
    när TRAKTDELAR är av (punktverktygets Annat läge)."""
    from osgeo import ogr
    from . import startregler
    if not (startregler.TRAKTDELAR or alltid) or not trakter:
        return []
    ytor, _ = _traktytor(inst, socken, trakter)
    delar = []
    for y in ytor:
        g = ogr.CreateGeometryFromWkb(y.wkb)
        multi = ogr.GT_Flatten(g.GetGeometryType()) == ogr.wkbMultiPolygon
        for d in ([g.GetGeometryRef(i) for i in range(g.GetGeometryCount())] if multi else [g]):
            delar.append((d.GetArea(), d.Centroid(), y.namn))
    if len(delar) < 2:
        return []
    stora = sorted((d for d in delar if d[0] >= startregler.TRAKTDEL_MINST_HA * 1e4), key=lambda d: -d[0])
    return [(c.GetX(), c.GetY(), f"traktdel: {namn} ({yta / 1e4:.0f} ha)")
            for yta, c, namn in stora[:hogst or startregler.TRAKTDELAR_HOGST]]


def _fastighetsindelningen(inst, socken: str, socken_och_stad: str):
    """Fastighetsindelningens traktytor for socknen (fastighet.traktlager), ur filerna for
    socknens kommuner nar sockenlagret och Kommun, lan och rike finns, annars alla filerna;
    None utan filer. Bara traktnamn och granser lases."""
    from . import fastighet
    koder = []
    sl = inst.sockenlager
    if sl and os.path.exists(sl) and inst.sokvag_lan():
        try:
            koder = fastighet.socknens_kommuner(sl, socken, inst.sokvag_lan())
        except Exception:  # noqa: BLE001 -- utan koder lases alla filerna
            koder = []
    filer_ = inst.fastighetsfiler(koder) or (inst.fastighetsfiler() if koder else [])
    if not filer_:
        return None
    tl = fastighet.traktlager(filer_, socken_och_stad, bara_socknar={socken})
    return tl if tl.ytor else None


def _traktytor(inst, socken: str, trakter: list[str]):
    """Trakternas ytor i socknen ur den forsta kallan som har dem: det egna traktlagret,
    annars fastighetsindelningens traktytor (lat: lases bara nar det egna inte hade
    trakten, som i Gallra). -> (ytor, kalla); ([], "") utan traff."""
    sos = inst.sokvag_socken_och_stad()
    if not sos or not trakter:
        return [], ""
    from . import traktlager
    nycklar = {_namn.nyckel(t, socken) for t in trakter}
    kallor = []
    if inst.traktlager and os.path.exists(inst.traktlager):
        kallor.append(("traktlager", lambda: traktlager.las(
            inst.traktlager, inst.traktlager_lager or None, inst.traktlager_traktfalt or "TRAKT",
            sos, inst.traktlager_sockenfalt or None, bara_socknar={socken})))
    kallor.append(("fastighetsindelning", lambda: _fastighetsindelningen(inst, socken, sos)))
    for kalla, las_ in kallor:
        tl = las_()
        if tl is None:
            continue
        ytor = [y for y in tl.i_socken(socken) if _namn.nyckel(y.namn, socken) in nycklar]
        if ytor:
            return ytor, kalla
    return [], ""


def traktlage(inst, socken: str, trakter: list[str]) -> Lage | None:
    """Var akten ligger: traktens yta ur traktlagret, annars ur fastighetsindelningen,
    annars traktens lage ur ortnamnen, annars socknen."""
    from osgeo import ogr
    ytor, kalla = _traktytor(inst, socken, trakter)
    if ytor:
        g = None
        for y in ytor:
            yg = ogr.CreateGeometryFromWkb(y.wkb)
            g = yg if g is None else g.Union(yg)
        x0, x1, y0, y1 = g.GetEnvelope()
        c = g.Centroid()
        return Lage(c.GetX(), c.GetY(), x1 - x0, y1 - y0, kalla,
                    sorted({y.namn for y in ytor}))
    reg = inst.ortnamnsregister()
    if reg and trakter:
        nycklar = {_namn.nyckel(t, socken) for t in trakter}
        lagen = [n for n in _alla_lan(reg, socken)
                 if _namn.nyckel(n.namn, socken) in nycklar]
        if lagen:
            xs, ys = [n.x for n in lagen], [n.y for n in lagen]
            return Lage(sum(xs) / len(xs), sum(ys) / len(ys),
                        max(max(xs) - min(xs), 1500), max(max(ys) - min(ys), 1500),
                        "ortnamn", sorted({n.namn for n in lagen}))
    sl = inst.sockenlager
    if sl and os.path.exists(sl):
        ds = ogr.Open(sl)
        l = ds.GetLayerByName("socknar")
        l.SetAttributeFilter(f"sockenstadnamn = '{socken.replace(chr(39), '')}'")
        for f in l:
            g = f.GetGeometryRef()
            x0, x1, y0, y1 = g.GetEnvelope()
            c = g.PointOnSurface()
            return Lage(c.GetX(), c.GetY(), x1 - x0, y1 - y0, "socken", [])
    return None


def _alla_lan(reg, socken):
    """Ortnamn i socknen oavsett lan -- lanskoden ar okand har."""
    import sqlite3
    from urllib.request import pathname2url
    k = sqlite3.connect("file:" + pathname2url(os.path.abspath(reg)) + "?mode=ro", uri=True)
    try:
        from .ortnamn import Namnlage
        return [Namnlage(r[0], r[1], r[2], r[3], r[4], r[5] or "") for r in k.execute(
            "SELECT ortnamn, detaljtyp, ekoordinat, nkoordinat, sockenstadnamn, "
            "sockenstadkod FROM ortnamn WHERE sockenstadnamn = ? AND detaljtyp IN "
            "('TRAKTTX', 'BEBTX')", (socken,))]
    finally:
        k.close()


# =========================================================================
# Topografi 10 och 50
# =========================================================================

# Topografi 10 har samma lager som Topografi 50, men vattnet heter hydro_ln23
# i stallet for hydrografi_ln23 (nedladdat 2026-10-01).
TEMA_TOPO10 = {"hydrografi": "hydro"}


def topografi_mapp(referensdata: str) -> tuple[str | None, str]:
    """(mapp, "10" eller "50"): Topografi 10 om den finns, annars 50."""
    if not referensdata or not os.path.isdir(referensdata):
        return None, ""
    for skala in ("10", "50"):
        hitt = [m for m in glob.glob(os.path.join(referensdata, f"*Topografi {skala} *"))
                if os.path.isdir(m)]
        if hitt:
            return sorted(hitt)[-1], skala
    return None, ""


def topografi_fil(referensdata: str, tema: str) -> str | None:
    """Temats geopackage i den finaste Topografi som finns (mark, hydrografi ...)."""
    mapp, skala = topografi_mapp(referensdata)
    if mapp is None:
        return None
    t = TEMA_TOPO10.get(tema, tema) if skala == "10" else tema
    hitt = glob.glob(os.path.join(mapp, f"{t}_*", f"{t}_*.gpkg"))
    return hitt[0] if hitt else None


KMR_TYPER = ("Fäbod", "Bytomt/gårdstomt", "Fossil åker", "Lägenhetsbebyggelse")


def kmr_fil(referensdata: str) -> str | None:
    """Kulturmiljöregistrets lämningar som GeoPackage (Riksantikvarieämbetets uttag,
    "lämningar_län_<län>.gpkg" eller "lämningar_kommun_..."), i referensdatans mapp
    eller en undermapp; den senaste om flera finns."""
    if not referensdata or not os.path.isdir(referensdata):
        return None
    hitt = (glob.glob(os.path.join(referensdata, "lämningar_*.gpkg"))
            + glob.glob(os.path.join(referensdata, "*", "lämningar_*.gpkg")))
    return max(hitt, key=os.path.getmtime) if hitt else None


def kmr_lager(fil: str) -> str | None:
    """Lagret med lämningarnas ytor och deras attribut ("..._polygon" med fältet
    lamningstyp), eller None."""
    from osgeo import ogr
    ds = ogr.Open(fil) if fil and os.path.exists(fil) else None
    if ds is None:
        return None
    for i in range(ds.GetLayerCount()):
        lg = ds.GetLayer(i)
        if lg.GetName().endswith("_polygon") and lg.GetLayerDefn().GetFieldIndex("lamningstyp") >= 0:
            return lg.GetName()
    return None


def topografi_fil_skala(referensdata: str, tema: str, skala: str) -> str | None:
    """Temats geopackage i en bestämd Topografi (lämningarna finns bara i 50)."""
    if not referensdata or not os.path.isdir(referensdata):
        return None
    t = TEMA_TOPO10.get(tema, tema) if skala == "10" else tema
    hitt = glob.glob(os.path.join(referensdata, f"*Topografi {skala} *", f"{t}_*", f"{t}_*.gpkg"))
    return sorted(hitt)[-1] if hitt else None


def topografi50(referensdata: str) -> list[tuple[str, str, str, str]]:
    """(fil, lager, namn, farg) for Topografi-lagren som finns -- Topografi 10
    om den finns (noggrannare stränder och åkerkanter), annars 50."""
    ut = []
    _, skala = topografi_mapp(referensdata)
    for tema, lager, namn, farg in TOPO50:
        fil = topografi_fil(referensdata, tema)
        if fil:
            ut.append((fil, lager, namn.replace("Topografi 50", f"Topografi {skala}"), farg))
    return ut
