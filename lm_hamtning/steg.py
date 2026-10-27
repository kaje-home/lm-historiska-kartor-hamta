"""Gallringens steg som jobb: fristaende fran dialogen, sa att de gar att
prova utan granssnitt och kora i bakgrunden (bakgrund.Jobb).

    vokabular     arkivens lan, socknar och trakter (15,7 MB, cachad)
    urval         arbetsomrade -> socknar och trakter att bekrafta
    gallra        socknar och bekraftade trakter -> akter till kontaktkartan
    ladda_ned     behallna akters kartsidor -> TIFF i arkivet

Varje jobb oppnar sitt eget register och sin egen klient; se bakgrund.py.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from . import gallra as _gallra
from . import fastighet, nedladdning, ortnamn, sockenlager, traktlager, urval, variant
from .register import Register


@dataclass
class Urval:
    socknar: list = field(default_factory=list)     # urval.SockenIOmrade
    trakter: list = field(default_factory=list)     # urval.TraktIOmrade
    kalla: str = ""                                 # de använda källorna med " och " emellan:
                                                    # traktlager, fastighetsindelning, ortnamn; eller ingen
    meddelanden: list[str] = field(default_factory=list)
    # (arkivets socken, trakt) -> hur mycket av omradet trakten ror, m2
    # (traktlagret); jobbets akter sorteras efter det (avsnitt 5b)
    trakt_yta: dict = field(default_factory=dict)


def vokabular(klient, framsteg=None, avbruten=None):
    if framsteg:
        framsteg("Läser arkivens socknar och trakter", 0.0)
    return klient.vokabular()


def sockenlager_klart(inst, vok, framsteg=None) -> str:
    """Sockenlagret i tjanstecachen; byggs forsta gangen (ca 20 s)."""
    sl = inst.sockenlager
    if not os.path.exists(sl):
        if framsteg:
            framsteg("Bygger socknarna i arkivets län (en gång, ca 20 s)", 0.05)
        sockenlager.bygg(sl, inst.sokvag_socken_och_stad(), inst.sokvag_lan() or None,
                         vok)
    return sl


def urval_for_omrade(inst, vok, omrade_wkt: str, framsteg=None, avbruten=None) -> Urval:
    """Socknarna arbetsomradet ror och trakterna i det (avsnitt 6)."""
    ut = Urval()
    sl = sockenlager_klart(inst, vok, framsteg)
    if framsteg:
        framsteg("Socknar i arbetsområdet", 0.4)
    ut.socknar = urval.sla_ihop_stad(sockenlager.socknar_i_omrade(sl, omrade_wkt, vok))
    kopplade = [s for s in ut.socknar if s.socken is not None]
    grannar = {s.kod: sockenlager.grannar(sl, s.kod, vok) for s in kopplade}
    namn_alla = {s.namn for s in kopplade} | {g.sockenstadnamn for gr in grannar.values()
                                             for g in gr}
    if framsteg:
        framsteg("Trakter i arbetsområdet", 0.6)
    # traktkällorna i ordning (avsnitt 5): det egna traktlagret, fastighetsindelningens
    # traktytor, ortnamnsregistret; det som blir över får arkivets lista i dialogen.
    # Ett traktlager täcker inte alla län (användaren 2026-10-26: ett ritat område i
    # Karlskoga med Jämtlands traktlager gav hela socknen, 224 akter), så varje socken
    # tas ur den första källan som har en trakt i den.
    kallor = _traktkallor(inst, omrade_wkt, namn_alla, ut.meddelanden, framsteg, avbruten)
    ut.trakter, ut.trakt_yta, anvanda, utan = trakter_ur_kallor(omrade_wkt, kallor, kopplade, grannar)
    reg = inst.ortnamnsregister() if utan else None
    lager_namn = kalla_text(" och ".join(k for k, _ in kallor))
    if utan and reg:
        lan_u = {s.lanskod for s in utan if s.lanskod} or {""}
        namn_u = {s.namn for s in utan} | {g.sockenstadnamn for s in utan for g in grannar.get(s.kod, [])}
        lagen = [n for namn in sorted(namn_u) for l in lan_u for n in ortnamn.namn_i_socken(reg, namn, l)]
        extra = urval.trakter_ur_ortnamn(omrade_wkt, lagen, utan, grannar)
        ut.trakter += extra
        anvanda.append("ortnamn")
        if kallor and extra:
            ut.meddelanden.append(lager_namn[:1].upper() + lager_namn[1:] + " täcker inte "
                                  + ", ".join(s.namn for s in utan)
                                  + ": trakterna där är tagna ur ortnamnsregistret.")
    elif utan and kallor:
        ut.meddelanden.append(lager_namn[:1].upper() + lager_namn[1:] + " täcker inte "
                              + ", ".join(s.namn for s in utan)
                              + ", och inget ortnamnsregister finns. Bocka i trakter ur arkivets lista "
                              "under socknen, eller alla akter.")
    elif utan:
        ut.meddelanden.append(
            "Varken traktlager, fastighetsindelning eller ortnamnsregister finns — trakterna kan "
            "inte väljas ur kartan. Välj ”alla akter i socknen”, eller bocka i trakter ur arkivets lista.")
    ut.kalla = " och ".join(anvanda) or "ingen"
    for s in ut.socknar:
        if s.socken is None and s.hur != urval.FLERA:
            ut.meddelanden.append(f"{s.namn}: finns inte entydigt i arkivet — välj i listan.")
    if framsteg:
        framsteg("klart", 1.0)
    return ut


KALLOR = {"traktlager": "traktlagret", "fastighetsindelning": "fastighetsindelningen",
          "ortnamn": "ortnamnsregistret"}


def kalla_text(kalla: str) -> str:
    """Urvalets källa i klartext för dialogen: "traktlager och ortnamn" ->
    "traktlagret och ortnamnsregistret"; tomt eller "ingen" -> ett streck."""
    if not kalla or kalla == "ingen":
        return "—"
    return " och ".join(KALLOR.get(k, k) for k in kalla.split(" och "))


KALLA_RAD = {"traktlager": "traktlagret", "fastighetsindelning": "fastighetsindelningen",
             ortnamn.TRAKT: "ortnamnsregistret (trakt)", ortnamn.BEBYGGELSE: "ortnamnsregistret (by eller gård)",
             "arkivet": "arkivets lista"}


def kalla_rad(kalla: str) -> str:
    """Traktens källa i klartext för kolumnen Källa i trädet (2026-10-27: den sa TRAKTTX,
    registrets interna kod). Okända koder som de är."""
    return KALLA_RAD.get(kalla, kalla)


def trakter_ur_kallor(omrade_wkt: str, kallor, socknar, grannar):
    """Trakterna i området ur traktkällorna i ordning. `kallor`: [(namn, traktlager.Traktlager
    eller en funktion som får socknarna som ännu saknar trakter och ger ett Traktlager eller
    None)] -- funktionen gör att fastighetsindelningen bara läses, och hämtas, när det egna
    traktlagret inte räckte. Varje socken tas ur den första källan som har en trakt i den
    (egen eller lånad från grannen); de senare källorna rör den inte.
    -> (trakter, trakt_yta, använda källor, socknar som ingen källa täcker)."""
    trakter, trakt_yta, anvanda = [], {}, []
    utan = [s for s in socknar if s.socken is not None]
    for namn_k, tl in kallor:
        if not utan:
            break
        if callable(tl):
            tl = tl(utan)
        if tl is None:
            continue
        nya = urval.trakter_ur_traktlager(omrade_wkt, tl, utan, grannar, kalla=namn_k)
        if not nya:
            continue
        trakter += nya
        trakt_yta.update(urval.trakternas_yta(omrade_wkt, tl, nya))
        anvanda.append(namn_k)
        utan = [s for s in utan if not any(t.socken == s.socken.namn or t.via_socken == s.socken.namn
                                           for t in nya)]
    return trakter, trakt_yta, anvanda, utan


def _traktkallor(inst, omrade_wkt: str, namn_alla: set, meddelanden: list,
                 framsteg=None, avbruten=None) -> list:
    """Traktkällorna som finns, för trakter_ur_kallor: det egna traktlagret (inställningen)
    och fastighetsindelningens traktytor (fastighet.traktlager) ur filerna i arkivets
    referensmapp och referensdatan. Den senare läses först när den behövs, och i hela
    verktyget hämtas den då för områdets kommuner med Geotorget-kontot om den saknas, som
    automatiken gör (hämtningen för sig har inget konto: filen laddas ner för hand, se
    Kom igång). Nekas hämtningen sägs det i `meddelanden`, inte som fel."""
    sos = inst.sokvag_socken_och_stad()
    ut = []
    if inst.traktlager and os.path.exists(inst.traktlager):
        ut.append(("traktlager", traktlager.las(
            inst.traktlager, inst.traktlager_lager or None, inst.traktlager_traktfalt or "TRAKT",
            sos, inst.traktlager_sockenfalt or None, bara_socknar=namn_alla)))
    if not sos:
        return ut

    def fastighetsindelningen(utan):
        from osgeo import ogr
        g = ogr.CreateGeometryFromWkt(omrade_wkt)
        x0, x1, y0, y1 = g.GetEnvelope()
        koder = fastighet.kommunkoder((x0, y0, x1, y1), inst.sokvag_lan())
        filer_ = inst.fastighetsfiler(koder)
        saknade = [k for k in koder if not any(f"kn{k}" in os.path.basename(f).lower() for f in filer_)]
        if saknade and inst.arkiv and not variant.BARA_HAMTNING:
            filer_ += _hamta_fastighetsindelning(inst, saknade, meddelanden, framsteg, avbruten)
        if not filer_:
            return None
        if framsteg:
            framsteg("Trakter ur fastighetsindelningen", 0.7)
        tl = fastighet.traktlager(filer_, sos, bara_socknar=namn_alla)
        return tl if tl.ytor else None

    ut.append(("fastighetsindelning", fastighetsindelningen))
    return ut


def _hamta_fastighetsindelning(inst, koder: list, meddelanden: list, framsteg=None, avbruten=None) -> list:
    """Fastighetsindelningen för kommunerna till arkivets referensmapp med pluginets
    Geotorget-konto (fastighet.hamta). Utan konto, eller nekat (produkten kräver juridisk
    prövning), blir det ett besked och inga filer."""
    from . import kommuner
    from .underlag import atkomst
    auth = atkomst.sparat_id()
    namn = ", ".join(kommuner.kommunnamn(koder))
    if not auth:
        meddelanden.append(f"Fastighetsindelningen för {namn} finns inte och hämtas inte: "
                           "Geotorget-kontot saknas i inställningarna.")
        return []
    try:
        if framsteg:
            framsteg(f"Hämtar fastighetsindelningen för {namn}", 0.6)
        return fastighet.hamta(koder, os.path.join(inst.arkiv, "referens"), auth, framsteg, avbruten)
    except Exception as e:  # noqa: BLE001 -- beskedet ur atkomst är skrivet för användaren
        meddelanden.append(f"Fastighetsindelningen för {namn} kunde inte hämtas: "
                           + (str(e).splitlines() or ["okänt fel"])[0])
        return []


@dataclass
class Val:
    """Det anvandaren bekraftat, i den form gallra.gallra tar emot."""
    socknar: list = field(default_factory=list)                 # tjanst.Socken
    trakter: dict[str, list[str]] = field(default_factory=dict)
    lanade: list = field(default_factory=list)                  # urval.TraktIOmrade
    bara_prioriterade: bool = False                             # prioritet.py
    atgarder: tuple | None = None                               # prioritet.TYPER, None = alla
    beteckningar: list[str] = field(default_factory=list)       # sökning på aktbeteckning: bara dessa
    ar: tuple | None = None                                     # årtal (fr.o.m., t.o.m.), None/tomt = alla


def gallra(inst, klient_fabrik, val: Val, framsteg=None, avbruten=None,
           jobb: dict | None = None):
    """Gallra i bakgrunden. Eget register och egen klient i jobbets trad.

    `jobb` {"namn", "omrade" (WKT), "trakt_yta"}: akterna som blir kvar sparas
    som jobbets (avsnitt 5b), med hur mycket av omradet deras trakter ror.
    Resultatet far `jobb` = (namn, antal akter)."""
    with Register(inst.registerfil) as r:
        res = _gallra.gallra(klient_fabrik(), r, val.socknar, val.trakter,
                             val.lanade, framsteg=framsteg, avbruten=avbruten,
                             bara_prioriterade=val.bara_prioriterade,
                             atgarder=val.atgarder, beteckningar=val.beteckningar or None,
                             ar=val.ar)
        if jobb and jobb.get("omrade"):
            from osgeo import ogr
            yta = ogr.CreateGeometryFromWkt(jobb["omrade"]).GetArea()
            akter = jobbets_akter(res.kvar, jobb.get("trakt_yta") or {}, yta)
            akter = {n: y for n, y in akter.items() if r.akt(n) is not None}
            if akter:
                r.spara_jobb(jobb["namn"], jobb["omrade"], akter)
            res.jobb = (jobb["namn"], len(akter))
        return res


def jobbets_akter(kandidater, trakt_yta: dict, omrade_m2: float | None = None) -> dict:
    """{akt: berord yta i m2, eller None} -- summan av aktens trakters yta i
    omradet, varje yta i traktlagret en gang och hogst hela omradet. En akt har
    ofta samma trakt som ursprunglig och gallande, eller tva namn for samma yta
    (HÄG-122: 125 km2 i ett omrade pa 75, 2026-10-02). `trakt_yta`: se
    urval.trakternas_yta. Akter med bara socknen som skal far None."""
    ut = {}
    for k in kandidater:
        ytor: dict[str, float] = {}           # per yta i traktlagret
        for t in {s.trakt for s in k.skal if s.trakt}:
            v = trakt_yta.get((k.socken, t))
            if v:
                ytor[v[0]] = max(ytor.get(v[0], 0.0), v[1])
        y = sum(ytor.values())
        if omrade_m2:
            y = min(y, omrade_m2)
        ut[k.akt.nyckel] = y or None
    return ut


def ladda_ned(inst, klient_fabrik, framsteg=None, avbruten=None, textakt: bool = False):
    """Behallna kartsidor till arkivet, i bakgrunden. `textakt`: också varje behållen
    akts textsidor som PDF (textakt.py), de som inte redan finns."""
    with Register(inst.registerfil) as r:
        k = klient_fabrik()
        n = nedladdning.ladda_ned(inst.arkiv, inst.cachekatalog, k, r,
                                  framsteg=framsteg, avbruten=avbruten)
        if textakt and not n.avbrutet:
            from . import textakt as _ta
            for a in r.behallna_akter():
                if avbruten is not None and avbruten():
                    n.avbrutet = True
                    break
                if os.path.exists(_ta.sokvag(inst.arkiv, a)) or not _ta.textsidor(r, a["nyckel"]):
                    continue
                if framsteg:
                    framsteg(f"{a['beteckning']}: textakten", 1.0)
                try:
                    _ta.spara(k, r, inst.arkiv, a["nyckel"])
                    n.textakter += 1
                except Exception as e:                     # noqa: BLE001 -- en akt stoppar inte resten
                    n.textakt_fel.append(f"{a['beteckning']} textakten: {str(e).splitlines()[0]}")
        return n


def trakter_for_namn(vok, namn: str) -> list:
    """Arkivets trakter med namnet `namn`, i vilken socken och vilket län som helst:
    [(tjanst.Socken, tjanst.Trakt)]. Vokabulären har alla trakter i landet, så sökning på
    namn kräver inget nedladdat register (användaren 2026-10-26: "alla har väl inte det på
    sin dator?"). Stora och små bokstäver spelar ingen roll."""
    n = namn.strip().casefold()
    if not n:
        return []
    ut = []
    for l in vok.lan:
        for s in l.socknar:
            for t in s.trakter:
                if t.namn.casefold() == n:
                    ut.append((s, t))
    return ut


def modern_lanskod(reg_nummer: str) -> str:
    """Dagens länskod för arkivets län: 11 och 12 → 12 (Skåne), 14, 15 och 16 → 14 (Västra
    Götaland), övriga sig själva (urval._SAMMANSLAGNA)."""
    for ny, gamla in urval._SAMMANSLAGNA.items():
        if reg_nummer in gamla:
            return ny
    return reg_nummer


def socknar_per_kommun(vok, tabell: list[dict], lanskod: str) -> tuple[list, dict]:
    """Välj socknar via län och kommun (användaren 2026-10-26: "kan man även tänka kommun
    eller blir det för mycket?" -- som mellanled: den som inte vet socknen vet kommunen).

    Arkivets socknar i dagens län `lanskod` -- alla arkivlän som ingår, t.ex. Kristianstad
    och Malmöhus för Skåne -- i namnordning, och kommunerna de ligger i enligt tabellen
    kommuner.csv (kommuner.py): ([Socken], {kommunkod: [Socken]}). Tabellens namn är
    Socken och stads; de paras som urval.koppla: lika namn, annars stadsformerna
    (Östersund → Östersunds stad). En socken som inte finns i tabellen står i listan
    utan kommun, så att den ändå går att bocka i; inget tappas."""
    socknar = sorted((s for l in vok.lan if modern_lanskod(l.reg_nummer) == lanskod for s in l.socknar),
                     key=lambda s: (s.namn.casefold(), s.lan.namn))
    per_namn: dict[str, list] = {}
    for s in socknar:
        per_namn.setdefault(s.namn.casefold(), []).append(s)
    ut: dict[str, list] = {}
    for r in tabell:
        if r["lanskod"] != lanskod:
            continue
        kand = per_namn.get(r["socken"].casefold())
        if not kand:
            for alt in urval._alternativ(urval.SockenIOmrade(r["socken"], "", int(r.get("typ") or 1), 0.0)):
                kand = per_namn.get(alt.casefold())
                if kand:
                    break
        for s in kand or []:
            lista = ut.setdefault(r["kommunkod"], [])
            if all(s is not x for x in lista):
                lista.append(s)
    return socknar, ut


def socken_for_beteckning(vok, beteckning: str):
    """Arkivsocknen en aktbeteckning hör till, ur vokabulären: REG `23-HÄG-10` -> socknen med
    reg_kod `23-häg`; LMS `Y22-2:1` -> län Y, socken 22. None när formen inte känns igen
    eller socknen saknas."""
    from . import tjanst as _tj
    b = beteckning.strip()
    m = re.fullmatch(r"(\d+)-([A-ZÅÄÖa-zåäö]+)-(\d+\w*)", b)
    if m:
        kod = f"{m.group(1)}-{m.group(2)}".casefold()
        for l in vok.lan:
            for s in l.socknar:
                if (s.reg_kod or "").casefold() == kod:
                    return s
        return None
    lb = _tj.las_lms_beteckning(b.upper())
    if lb is None:
        return None
    for l in vok.lan:
        if l.lms_bokstav != lb.lan:
            continue
        for s in l.socknar:
            if s.lms_nummer == lb.socken:
                return s
    return None
