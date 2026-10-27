"""Kommun, län och rike -- Lantmäteriets administrativa indelning som referens.

Produkten *Kommun, län och rike Nedladdning* (STAC-samlingen kommun-lan-rike, CC BY 4.0;
avgiftsfri, utan juridisk prövning, men beställs på Geotorget) är ett geopackage för hela
landet med kommunernas och länens ytor. Den ersätter SCB:s länsfil och kommunfil sedan
2026-10-26 (användaren: "är ju de officiella"; "kanske ska byta det från scb åxå, på alla
ställen och använda detta -- scb blev bara för att jag hade det på datorn"). Används till:

  - länet för en socken i Socken och stad (urval.socknar_i_omrade), så att socknar med
    samma namn i flera län skiljs åt;
  - kommunerna en ruta eller en socken ligger i, för fastighetsindelningen per kommun
    (fastighet.py);
  - tabellen socken -> kommun (`kommuner.csv`, byggd med `bygg_tabell` och medskickad i
    pluginet), så att en användare kan gå län -> kommun -> socknar utan referensdata.

Nedladdningen kräver Geotorget-kontot (401/403 utan), så `hamta` körs i QGIS som
fastighetsindelningen, och filen läggs i arkivets referens/kommun-lan-rike. Den som laddar
ner för hand lägger geopackaget i referensdatan; `hitta` letar på namnet.

Fältnamnen slås upp tolerant (kommunkod, kommunnamn, lanskod, lansnamn oavsett skiftläge,
eller ett fält som innehåller ordet), eftersom specifikationen har status Test och modellen
kan ändras.
"""
from __future__ import annotations

import csv
import glob
import json
import os
import urllib.request
import zipfile

STAC = "https://api.lantmateriet.se/stac-vektor/v1"
SAMLING = "kommun-lan-rike"
MAPP = "kommun-lan-rike"                 # arkiv/referens/kommun-lan-rike
PRODUKT = "Kommun, län och rike"
PRODUKTSIDA = "https://geotorget.lantmateriet.se/geodataprodukter/kommun-lan-rike-nedladdning-api"
TABELL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kommuner.csv")
MINSTA_ANDEL = 0.02     # av socknens yta i kommunen: Häggenås skar Strömsund med 1,2 av 490 km2,
                        # bara för att socken- och kommunlagren är olika generaliserade (2026-10-01)
RUBRIKER = ("lanskod", "lansnamn", "kommunkod", "kommunnamn", "sockenstadkod", "socken", "typ", "andel")


# ------------------------------------------------------------------ filen
def ar_kommunfil(filnamn: str, mapp: str = "") -> bool:
    """Ser namnet ut som Kommun, län och rike? "kommun" i filnamnet men inte
    "kommunikation" (Topografi 10:s tema heter så och ligger i samma referensdata),
    eller ett geopackage i mappen kommun-lan-rike."""
    fl = filnamn.lower()
    if not fl.endswith(".gpkg"):
        return False
    if MAPP in mapp.lower().replace("_", "-"):
        return True
    return "kommun" in fl and "kommunikation" not in fl


def hitta(*mappar: str, djup: int = 4) -> str:
    """Geopackaget på namn (`ar_kommunfil`) i mapparna, först funnet; tomt om det inte
    finns."""
    for rot in mappar:
        if not rot or not os.path.isdir(rot):
            continue
        bas = rot.rstrip("\\/").count(os.sep)
        for mapp, under, filer_ in os.walk(rot):
            if mapp.count(os.sep) - bas >= djup:
                under[:] = []
            under[:] = [u for u in under if not u.lower().endswith(".gdb")]
            for f in sorted(filer_):
                if ar_kommunfil(f, mapp):
                    return os.path.join(mapp, f)
    return ""


def filer(referensmapp: str) -> list[str]:
    """Geopackagen i referensmapp/kommun-lan-rike (hämtade med `hamta`)."""
    return sorted(glob.glob(os.path.join(referensmapp, MAPP, "*.gpkg")))


def _lager(ds, ord_: tuple[str, ...], inte: tuple[str, ...] = ()):
    """Lagret vars namn innehåller något av `ord_` och inget av `inte`."""
    for i in range(ds.GetLayerCount()):
        n = ds.GetLayer(i).GetName().lower()
        if any(o in n for o in ord_) and not any(x in n for x in inte):
            return ds.GetLayer(i)
    raise KeyError(f"inget lager {ord_} i filen: {[ds.GetLayer(i).GetName() for i in range(ds.GetLayerCount())]}")


def _falt(lager, *kandidater: str) -> str:
    """Fältet som heter som en kandidat (oavsett skiftläge), annars ett som innehåller den."""
    d = lager.GetLayerDefn()
    namn = [d.GetFieldDefn(j).GetName() for j in range(d.GetFieldCount())]
    for k in kandidater:
        for n in namn:
            if n.lower() == k.lower():
                return n
    for k in kandidater:
        for n in namn:
            if k.lower() in n.lower():
                return n
    raise KeyError(f"inget fält {kandidater} i lagret {lager.GetName()}: {namn}")


def oppna(fil: str, vilket: str):
    """(datakälla, lager, kodfält, namnfält) för "kommun" eller "lan". Datakällan måste
    hållas vid liv så länge lagret läses."""
    from osgeo import ogr
    ds = ogr.Open(fil)
    if ds is None:
        raise OSError(f"går inte att öppna {fil}")
    # Lantmäteriets fil (hämtad 2026-10-26): lagren kommun, lan, rike; fälten lanskod,
    # kommunkod, beslutatnamn ("Östersunds kommun", "Jämtlands län") och namnkortform
    # ("Östersund", "Jämtland"). Kommunen får kortformen, länet det beslutade namnet,
    # som arkivets vokabulär skriver det.
    if vilket == "kommun":
        lg = _lager(ds, ("kommun",))
        return ds, lg, _falt(lg, "kommunkod"), _falt(lg, "kommunnamn", "namnkortform", "namn")
    lg = _lager(ds, ("lan", "län"), inte=("rike",))
    return ds, lg, _falt(lg, "lanskod", "länskod"), _falt(lg, "lansnamn", "länsnamn", "beslutatnamn", "namn")


# ------------------------------------------------------------------ uppslag
def kommunkoder(ruta, fil: str) -> list[str]:
    """Kommunerna (fyrsiffrig kod) som verkligen skär rutan (x0, y0, x1, y1 i SWEREF 99
    TM). Katalogens rutor överlappar: en sökning på Häggenås gav fyra kommuner, fast
    socknen bara ligger i Östersunds (2026-10-01)."""
    from osgeo import ogr
    if not fil or not os.path.exists(fil):
        return []
    ds, lg, kod, _ = oppna(fil, "kommun")
    x0, y0, x1, y1 = ruta
    lg.SetSpatialFilterRect(x0, y0, x1, y1)       # grovt (bara rutor) ...
    yta = ogr.CreateGeometryFromWkt(f"POLYGON(({x0} {y0},{x1} {y0},{x1} {y1},{x0} {y1},{x0} {y0}))")
    return sorted({str(f.GetField(kod)).zfill(4) for f in lg      # ... sedan exakt
                   if f.GetGeometryRef() is not None and f.GetGeometryRef().Intersects(yta)})


def _kommuner_for_yta(yta, lg, kod: str, namn: str, minst: float) -> list[tuple[str, float, str]]:
    """[(kommunkod, andel, kommunnamn)] för kommunerna som täcker minst `minst` av ytan."""
    x0, x1, y0, y1 = yta.GetEnvelope()
    lg.SetSpatialFilterRect(x0, y0, x1, y1)
    a0 = yta.GetArea()
    ut = []
    for f in lg:
        g = f.GetGeometryRef()
        if g is None or a0 <= 0:
            continue
        a = g.Intersection(yta).GetArea()
        if a > minst * a0:
            ut.append((str(f.GetField(kod)).zfill(4), a / a0, str(f.GetField(namn) or "")))
    return sorted(ut)


def kommuner_for_yta(yta, fil: str, minst: float = MINSTA_ANDEL) -> list[tuple[str, float, str]]:
    """[(kommunkod, andel, kommunnamn)] för kommunerna ytan (ogr-geometri) ligger i."""
    if not fil or not os.path.exists(fil):
        return []
    ds, lg, kod, namn = oppna(fil, "kommun")
    return _kommuner_for_yta(yta, lg, kod, namn, minst)


def socknens_kommuner(sockenlager: str, socken: str, fil: str) -> list[str]:
    """Kommunerna som socknens yta (ur arkivets sockenlager) ligger i, minst MINSTA_ANDEL
    av socknen: en ruta runt Häggenås skar fyra kommuner; socknen själv ligger bara i
    Östersunds (2026-10-01)."""
    from osgeo import ogr
    if not fil or not os.path.exists(fil) or not sockenlager or not os.path.exists(sockenlager):
        return []
    sds = ogr.Open(sockenlager)
    sl = sds.GetLayerByName("socknar")
    sl.SetAttributeFilter(f"sockenstadnamn = '{socken.replace(chr(39), '')}'")
    ytor = [f.GetGeometryRef().Clone() for f in sl if f.GetGeometryRef() is not None]
    if not ytor:
        return []
    ds, lg, kod, namn = oppna(fil, "kommun")
    return sorted({k for yta in ytor for k, _, _ in _kommuner_for_yta(yta, lg, kod, namn, MINSTA_ANDEL)})


def lanskoder(ytor: dict, fil: str, hogst_m: float = 10_000) -> dict[str, str]:
    """Dagens länskod för varje yta ({nyckel: ogr-geometri}): länet med störst överlapp
    mot hela ytan, inte en punkt i den. Finns ingen överlapp alls, närmaste länet inom
    `hogst_m`: länsytorna är generaliserade, Storsjön är ett hål i Jämtland och öarna i
    den saknas; Norderön (41 km2) rörde inget län (provat 2026-09-29)."""
    if not fil or not os.path.exists(fil):
        return {}
    ds, ll, kod, _ = oppna(fil, "lan")
    ut: dict[str, str] = {}
    for nyckel, g in ytor.items():
        ll.SetSpatialFilter(g.Buffer(hogst_m))
        basta, narmast = 0.0, None
        for f in ll:
            lg = f.GetGeometryRef()
            if lg is None:
                continue
            if lg.Intersects(g):
                a = lg.Intersection(g).GetArea()
                if a > basta:
                    basta, ut[nyckel] = a, str(f.GetField(kod)).zfill(2)
            elif basta == 0:
                d = lg.Distance(g)
                if narmast is None or d < narmast[0]:
                    narmast = (d, str(f.GetField(kod)).zfill(2))
        if basta == 0 and narmast is not None:
            ut[nyckel] = narmast[1]
    return ut


# ------------------------------------------------------------------ hämtning
def katalogpost() -> dict:
    """Den aktuella filen i STAC-katalogen: {id, titel, href, byte, uppdaterad}. Katalogen
    är öppen; själva filen kräver kontot."""
    with urllib.request.urlopen(f"{STAC}/collections/{SAMLING}/items/aktuell", timeout=60) as svar:
        it = json.load(svar)
    a = it["assets"]["data"]
    return {"id": it["id"], "titel": it["properties"].get("title", it["id"]), "href": a["href"],
            "byte": a.get("file:size"), "uppdaterad": it["properties"].get("updated", "")}


def hamta(referensmapp: str, authcfg: str, feedback=None) -> str:
    """Hämta den aktuella filen till referensmapp/kommun-lan-rike med Geotorget-kontot;
    en äldre fil ersätts. -> geopackaget. Kastar underlag.atkomst.SaknarAtkomst med ett
    begripligt besked när kontot inte har produkten beställd."""
    from .underlag import nedladdning
    mal = os.path.join(referensmapp, MAPP)
    os.makedirs(mal, exist_ok=True)
    k = katalogpost()
    zipfil = os.path.join(mal, os.path.basename(k["href"]))
    nedladdning.hamta_fil(k["href"], zipfil, authcfg, produkt=PRODUKT, etikett=k["titel"], feedback=feedback)
    nya = []
    with zipfile.ZipFile(zipfil) as z:
        for n in z.namelist():
            z.extract(n, mal)
            nya.append(os.path.join(mal, n))
    os.remove(zipfil)
    gpkg = next((p for p in nya if p.lower().endswith(".gpkg")), "")
    for gammal in filer(referensmapp):
        if os.path.normcase(gammal) != os.path.normcase(gpkg):
            os.remove(gammal)
    return gpkg


# ------------------------------------------------------------------ tabellen socken -> kommun
def bygg_tabell(socken_och_stad: str, fil: str, minst: float = MINSTA_ANDEL) -> list[dict]:
    """Socken -> kommun för hela landet ur Socken och stad och kommunfilen: en rad per
    (socken, kommun) där kommunen täcker minst `minst` av socknen, med `andel`. Socknens
    delytor (omradesnummer) slås ihop först. Länsnamnet ur länslagret om det finns."""
    from osgeo import ogr
    sds = ogr.Open(socken_och_stad)
    sl = sds.GetLayer("sockenstad") or sds.GetLayer(0)
    ytor: dict[str, object] = {}
    info: dict[str, tuple[str, int]] = {}
    for f in sl:
        g = f.GetGeometryRef()
        if g is None:
            continue
        kod = str(f["sockenstadkod"])
        ytor[kod] = g.Clone() if kod not in ytor else ytor[kod].Union(g)
        info[kod] = (str(f["sockenstadnamn"]), int(f["sockenstadtyp"] or 0))
    ds, kl, kkod, knamn = oppna(fil, "kommun")
    lan: dict[str, str] = {}
    try:
        lds, ll, lkod, lnamn = oppna(fil, "lan")
        lan = {str(f.GetField(lkod)).zfill(2): str(f.GetField(lnamn) or "") for f in ll}
    except (KeyError, OSError):
        pass
    ut = []
    for kod, yta in ytor.items():
        for kk, andel, namn in _kommuner_for_yta(yta, kl, kkod, knamn, minst):
            ut.append({"lanskod": kk[:2], "lansnamn": lan.get(kk[:2], ""), "kommunkod": kk, "kommunnamn": namn,
                       "sockenstadkod": kod, "socken": info[kod][0], "typ": info[kod][1], "andel": round(andel, 3)})
    return sorted(ut, key=lambda r: (r["lanskod"], r["kommunnamn"], r["socken"]))


def skriv_tabell(rader: list[dict], fil: str = TABELL) -> int:
    """Tabellen som CSV med semikolon; första raden är källan."""
    with open(fil, "w", encoding="utf-8", newline="") as fh:
        fh.write("# Källa: Lantmäteriet, Kommun, län och rike (CC BY 4.0) och Socken och stad; "
                 "byggd med kommuner.bygg_tabell\n")
        w = csv.DictWriter(fh, RUBRIKER, delimiter=";")
        w.writeheader()
        w.writerows(rader)
    return len(rader)


def las_tabell(fil: str = TABELL) -> list[dict]:
    """Tabellen ur CSV:n; tom lista om filen saknas."""
    if not fil or not os.path.exists(fil):
        return []
    with open(fil, encoding="utf-8", newline="") as fh:
        rader = [r for r in fh if not r.startswith("#")]
    ut = list(csv.DictReader(rader, delimiter=";"))
    for r in ut:
        r["typ"] = int(r.get("typ") or 0)
        r["andel"] = float(r.get("andel") or 0)
    return ut


def kommunnamn(koder, tabell: list[dict] | None = None) -> list[str]:
    """Kommunernas namn ur tabellen som följer med (okänd kod: koden själv), i given ordning."""
    tabell = las_tabell() if tabell is None else tabell
    namn = {r["kommunkod"]: r["kommunnamn"] for r in tabell}
    return [namn.get(str(k).zfill(4), str(k)) for k in koder]


def kommuner_i_lan(tabell: list[dict], lanskod: str) -> list[tuple[str, str]]:
    """[(kommunkod, kommunnamn)] i länet (dagens tvåsiffriga länskod), i namnordning."""
    return sorted({(r["kommunkod"], r["kommunnamn"]) for r in tabell if r["lanskod"] == lanskod},
                  key=lambda x: x[1])


def socknar_i_kommun(tabell: list[dict], kommunkod: str) -> list[tuple[str, str, int]]:
    """[(sockenstadkod, socken, typ)] i kommunen, i namnordning; en socken över en
    kommungräns står under båda kommunerna."""
    return sorted({(r["sockenstadkod"], r["socken"], r["typ"]) for r in tabell if r["kommunkod"] == kommunkod},
                  key=lambda x: x[1])
