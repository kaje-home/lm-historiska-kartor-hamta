"""Urvalet: vilka socknar och trakter ett arbetsomrade beror (avsnitt 6).

Arbetsomradet ar en polygon i SWEREF 99 TM -- ritad, indexrutor, valda
objekt eller ett uttags arbetsomrade; hur den kom till angar inte den har
modulen.

Socknar
-------
Arbetsomradet skars mot Socken och stad. Sockennamnen kopplas sedan till
vokabularens socknar (och darmed arkivens koder). Provat mot Jamtland
2026-09-29 (undersokning/SOCKNAR.md):

* **Pa namn.** Nastan alla riktiga socknar har samma namn i bada.
* **Stader och koping** heter annorlunda: `Östersund` (typ 2) ar
  `Östersunds stad`, `Frösö` ar `Frösö köping`. De provas darefter och
  markeras `annat namn`.
* **Namn som finns i flera lan** (201 i hela landet, Ås, Berg, Fors ...)
  avgors med dagens lan for socknens lage (Lantmateriets Kommun, lan och rike,
  kommuner.py; SCB:s lansfil till 2026-10-26). Dagens 21 lan mot arkivets
  24 gamla; skillnaden ar Skane och Vastra Gotaland, som tas med
  `_SAMMANSLAGNA`. Finns namnet i flera av de gamla lanen inom ett
  sammanslaget (Löderup: Kristianstad och Malmohus) soks alla -- `flera`.
  Gar det inte att avgora alls far anvandaren valja bland `kandidater`.

Hela landet 2026-09-29, 2 473 socknar och stader: 2 048 pa namn, 295 med
lanet, 84 under annat namn, 29 flera/oklara, 17 saknas (arkivet har ett
annat namn: Kiruna, Falun, Kungsbacka, Åtvid ...). `geosearch` hjalper inte
for de sista: den svarar med dagens lan ("Skåne län") och for Kiruna med
ingenting.

Vokabularens *pseudosocknar* -- `Järnvägar`, `Utredningar` ... -- finns inte
i Socken och stad och kommer aldrig med har. Om de ska sokas for ett
arbetsomrade ar inte avgjort (2026-09-29).

Trakter
-------
Ur traktlagret nar det finns (ytor som ror arbetsomradet), annars ur
ortnamnsregistret (namn vars lage ligger i arbetsomradet; fastighetsnamn
forst, bebyggelse bara for det som blir kvar -- se ortnamn.py). Namnen
matchas mot vokabularens trakter i socknen med namn.py. Anvandaren bekraftar.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import namn as _namn
from .ortnamn import TRAKT, BEBYGGELSE

# Dagens lan -> de gamla lanen i arkivet.
_SAMMANSLAGNA = {"12": {"11", "12"}, "14": {"14", "15", "16"}}

NAMN = "namn"
ANNAT_NAMN = "annat namn"
LAN = "län"
FLERA = "flera"
VALT = "valt"           # anvandarens val i sockenlagret
OKLAR = "oklar"
SAKNAS = "saknas"


@dataclass
class SockenIOmrade:
    namn: str               # som i Socken och stad
    kod: str                # sockenstadkod
    typ: int                # 1 socken, 2 stad
    yta_m2: float           # den del av arbetsomradet som ligger i socknen
    lanskod: str = ""       # dagens lan, ur Kommun, lan och rike; tomt om filen saknas
    socken: object = None   # tjanst.Socken nar kopplingen lyckats
    hur: str = SAKNAS
    kandidater: list = field(default_factory=list)
    wkb: bytes = field(default=b"", repr=False)   # hela socknen, inte bara delen


@dataclass
class TraktIOmrade:
    socken: str             # vokabularens sockennamn -- dar ARKIVET har trakten
    trakt: str              # vokabularens traktnamn
    kalla_namn: str         # namnet i traktlagret eller ortnamnsregistret
    grad: str               # exakt | normaliserad
    kalla: str              # traktlager | TRAKTTX | BEBTX
    via_socken: str = ""    # socknen trakten ligger i, nar arkivet har den i
                            # en grannsocken (Vällviken: Marby -> LMS Sunne)
    arkivsocken: object = field(default=None, repr=False)   # tjanst.Socken


def _geom(omrade):
    from osgeo import ogr
    if isinstance(omrade, (bytes, bytearray)):
        return ogr.CreateGeometryFromWkb(bytes(omrade))
    if isinstance(omrade, str):
        return ogr.CreateGeometryFromWkt(omrade)
    return omrade


def socknar_i_omrade(omrade, socken_och_stad: str,
                     lan: str | None = None) -> list[SockenIOmrade]:
    """Socknar som arbetsomradet ror, storst del forst. Sammanslagna per kod."""
    from osgeo import gdal, ogr
    gdal.UseExceptions()
    g = _geom(omrade)
    ds = ogr.Open(socken_och_stad)
    lager = ds.GetLayer("sockenstad") or ds.GetLayer(0)
    lager.SetSpatialFilter(g)
    ut: dict[str, SockenIOmrade] = {}
    lage: dict[str, object] = {}
    for f in lager:
        sg = f.GetGeometryRef()
        if not sg.Intersects(g):
            continue
        yta = sg.Intersection(g).GetArea()
        if yta <= 0:
            continue
        kod = f["sockenstadkod"]
        if kod in ut:
            ut[kod].yta_m2 += yta
            lage[kod] = lage[kod].Union(sg)
        else:
            ut[kod] = SockenIOmrade(f["sockenstadnamn"], kod,
                                    f["sockenstadtyp"], yta)
            lage[kod] = sg.Clone()
    if lan:
        # Lanet med storst overlapp mot HELA socknen -- inte en punkt i den -- ur
        # Lantmateriets Kommun, lan och rike (kommuner.lanskoder; forut SCB:s lansfil,
        # bytt 2026-10-26). Finns ingen overlapp alls, narmaste lanet inom 10 km.
        from . import kommuner
        for kod, lk in kommuner.lanskoder(lage, lan).items():
            ut[kod].lanskod = lk
    for kod, s in ut.items():
        s.wkb = bytes(lage[kod].ExportToWkb())
    return sorted(ut.values(), key=lambda s: -s.yta_m2)


def _alternativ(s: SockenIOmrade) -> list[str]:
    """Andra namn arkivet kan ha. Stadsformerna provas aven for typ 1:
    Falun, Kungsbacka och Kiruna ar socknar i Socken och stad men stader i
    arkivet (`Falu stad`, `Kungsbacka stad`, `Kiruna stad`)."""
    n = s.namn
    gen = n if n.endswith("s") else n + "s"
    ut = [f"{gen} stad", f"{n} stad"]
    if n.endswith("n"):
        ut.append(f"{n[:-1]} stad")         # Falun -> Falu stad
    return ut + [f"{n} köping", f"{gen} köping"]


STAD = 2                # sockenstadtyp i Socken och stad: 1 socken, 2 stad


def sla_ihop_stad(socknar: list[SockenIOmrade]) -> list[SockenIOmrade]:
    """Socken och stad som ar kopplade till samma arkivsocken blir en rad. Socken och
    stad har Sollefteå socken (2493) och Sollefteå stad (4025) som egna ytor, men
    arkivet har ett Sollefteå: tradet fick Sollefteå tva ganger och varje trakt
    letades upp tva ganger (anvandaren 2026-10-27, "Sollefteå kommer 2 ggr i
    listan"). Socknen behalls, stadens yta laggs till. Östersund och Östersunds
    stad ar tva arkivsocknar och rors inte."""
    ut: list[SockenIOmrade] = []
    for s in socknar:
        samma = None
        if s.socken is not None:
            for x in ut:
                if x.socken is None:
                    continue
                if x.socken is s.socken or (x.socken.namn == s.socken.namn
                                            and x.socken.lan is s.socken.lan):
                    samma = x
                    break
        if samma is None:
            ut.append(s)
        elif samma.typ == STAD and s.typ != STAD:
            s.yta_m2 += samma.yta_m2
            ut[ut.index(samma)] = s
        else:
            samma.yta_m2 += s.yta_m2
    return ut


def koppla(socknar: list[SockenIOmrade], vokabular) -> list[SockenIOmrade]:
    """Koppla varje socken till vokabularen. Andrar och returnerar listan."""
    alla = [x for l in vokabular.lan for x in l.socknar]
    per_namn: dict[str, list] = {}
    for x in alla:
        per_namn.setdefault(x.namn.casefold(), []).append(x)

    for s in socknar:
        kand, hur = per_namn.get(s.namn.casefold(), []), NAMN
        if not kand:
            for alt in _alternativ(s):
                kand = per_namn.get(alt.casefold(), [])
                if kand:
                    hur = ANNAT_NAMN
                    break
        if not kand:
            s.hur, s.kandidater = SAKNAS, []
            continue
        if len(kand) > 1 and s.lanskod:
            gamla = _SAMMANSLAGNA.get(s.lanskod, {s.lanskod})
            i_lanet = [x for x in kand if x.lan.reg_nummer in gamla]
            if len(i_lanet) == 1:
                kand, hur = i_lanet, LAN
            elif len(i_lanet) > 1:
                # Samma namn i tva av de gamla lanen inom ett sammanslaget
                # (Loderup: Kristianstad och Malmohus). Sok alla.
                s.kandidater, s.hur = i_lanet, FLERA
                continue
        s.kandidater = kand
        if len(kand) == 1:
            s.socken, s.hur = kand[0], hur
        else:
            s.hur = OKLAR
    return socknar


def att_soka(socknar: list[SockenIOmrade]) -> list:
    """Vokabularens socknar som ska sokas: de kopplade, och alla kandidater
    for `flera`. Oklara och saknade kraver anvandarens val och kommer inte med."""
    ut: list = []
    for s in socknar:
        for x in ([s.socken] if s.socken is not None else
                  s.kandidater if s.hur == FLERA else []):
            if all(x is not y for y in ut):
                ut.append(x)
    return ut


def trakter_ur_traktlager(omrade, traktlager, socknar,
                          grannar: dict | None = None, kalla: str = "traktlager") -> list[TraktIOmrade]:
    """Traktlagrets ytor som ror arbetsomradet, matchade per socken.

    `grannar`: sockenstadkod -> [sockenlager.Granne]. Med den letas trakterna
    ocksa i grannsocknarna (se `_matcha`); traktlagret maste da vara last for
    grannarna ocksa, sa att deras egna namn syns. `kalla` ar markningen pa
    trakterna: "traktlager" for ett eget lager, "fastighetsindelning" for
    Lantmateriets traktytor (fastighet.traktlager).
    """
    from osgeo import ogr
    g = _geom(omrade)
    ut: list[TraktIOmrade] = []
    for s in socknar:
        if s.socken is None:
            continue
        namn_i = []
        for y in traktlager.i_socken(s.namn):
            if ogr.CreateGeometryFromWkb(y.wkb).Intersects(g):
                namn_i.append(y.namn)
        gr = (grannar or {}).get(s.kod, [])
        pa_kartan = {x.sockenstadkod: {_namn.nyckel(y.namn, x.sockenstadnamn)
                                       for y in traktlager.i_socken(x.sockenstadnamn)}
                     for x in gr}
        ut += _matcha(s, namn_i, kalla, gr, pa_kartan)
    return ut


def trakternas_yta(omrade, traktlager, trakter: list[TraktIOmrade]) -> dict:
    """(arkivets socken, trakt) -> (namnet i traktlagret, hur mycket av
    arbetsomradet dess ytor tacker i m2) -- avsnitt 5b: jobbets akter sorteras
    efter det. Bara ytor som ror omradet raknas. Namnet i lagret ar med sa att
    tva trakter i arkivet som ar samma yta inte raknas tva ganger."""
    from osgeo import ogr
    g = _geom(omrade)
    per_namn: dict[str, list] = {}
    for y in traktlager.ytor:
        per_namn.setdefault(y.namn, []).append(y)
    ut: dict = {}
    for t in trakter:
        yta = 0.0
        for y in per_namn.get(t.kalla_namn, []):
            yg = ogr.CreateGeometryFromWkb(y.wkb)
            if yg.Intersects(g):
                yta += yg.Intersection(g).GetArea()
        nyckel = (t.socken, t.trakt)
        if yta >= ut.get(nyckel, ("", 0.0))[1]:
            ut[nyckel] = (t.kalla_namn, yta)
    return ut


def trakter_ur_ortnamn(omrade, lagen, socknar,
                       grannar: dict | None = None) -> list[TraktIOmrade]:
    """Ortnamn vars lage ligger i arbetsomradet. `lagen` ar ortnamn.Namnlage
    for socknarna -- och for grannsocknarna, nar `grannar` anges, sa att
    deras egna namn syns (ortnamn.namn_i_socken)."""
    from osgeo import ogr
    g = _geom(omrade)
    pa_kartan: dict[str, set[str]] = {}
    for n in lagen:
        pa_kartan.setdefault(n.sockenkod, set()).add(_namn.nyckel(n.namn, n.socken))
    ut: list[TraktIOmrade] = []
    for s in socknar:
        if s.socken is None:
            continue
        inne = []
        for n in lagen:
            if n.sockenkod != s.kod:
                continue
            p = ogr.Geometry(ogr.wkbPoint)
            p.AddPoint_2D(n.x, n.y)
            if p.Within(g):
                inne.append(n)
        gr = (grannar or {}).get(s.kod, [])
        traffar = _matcha(s, [n.namn for n in inne if n.namntyp == TRAKT], TRAKT,
                          gr, pa_kartan)
        klara = {(t.socken, t.trakt) for t in traffar}
        rest = _matcha(s, [n.namn for n in inne if n.namntyp == BEBYGGELSE],
                       BEBYGGELSE, gr, pa_kartan)
        ut += traffar + [t for t in rest if (t.socken, t.trakt) not in klara]
    return ut


def _per_socken(nyckel: str) -> bool:
    """Namn som varje socken har sitt eget av: prastbordet, socknen sjalv."""
    return nyckel == "SN" or nyckel.endswith(" SN") or nyckel.endswith("PRÄSTBORD")


def _matcha(s: SockenIOmrade, lagernamn: list[str], kalla: str,
            grannar: list, pa_kartan: dict[str, set[str]] | None = None
            ) -> list[TraktIOmrade]:
    """Lagrets namn mot socknens trakter -- och mot grannsocknarnas.

    **Sockengranserna har andrats.** Marby och Sunne gjordes om under tidigt
    1900-tal; kartor over Vällviken fran 1800-talet och aldre ligger i Sunne,
    fast Vällviken ligger i Marby pa dagens karta (anvandaren 2026-09-29).
    Vokabularen har Vällviken under Marby i REG och under Sunne i bada
    arkiven. En trakt letas darfor alltid upp ocksa i grannsocknarna -- inte
    bara nar socknen saknar den.

    **Men inte om grannen har ett eget stalle med samma namn.** `pa_kartan`
    ar grannarnas namn pa dagens karta (ortnamn eller traktlager). Har Oviken
    en Backen pa kartan ar arkivets Backen i Oviken Ovikens egen, inte
    Marbys. Har Sunne ingen Vällviken pa kartan men arkivet har den dar, ar
    det troligen samma stalle, flyttat med gransen. Provat mot Marby
    2026-09-29: det som blir kvar mot Sunne ar Fjällsågen, Grimsved, Månsåsen,
    Rise och Vällviken -- omradet dar gransen flyttades. Prastbordet lanas
    aldrig: varje socken har sitt eget.
    """
    egen = s.socken
    m = _namn.matcha([t.namn for t in egen.trakter], lagernamn, egen.namn)
    ut = [TraktIOmrade(egen.namn, p.arkiv, p.lager, p.grad, kalla, arkivsocken=egen)
          for p in m.par]

    for n in dict.fromkeys(lagernamn):
        nyckel = _namn.nyckel(n, egen.namn)
        if _per_socken(nyckel):
            continue
        for gr in grannar:
            if nyckel in (pa_kartan or {}).get(gr.sockenstadkod, set()):
                continue            # grannens eget stalle med samma namn
            for t in gr.socken.trakter:
                if t.namn.casefold() == _namn.utan_nummer(n).casefold().strip():
                    grad = _namn.EXAKT
                elif _namn.nyckel(t.namn, gr.socken.namn) == nyckel:
                    grad = _namn.NORMALISERAD
                else:
                    continue
                ut.append(TraktIOmrade(gr.socken.namn, t.namn, n, grad, kalla,
                                       via_socken=egen.namn, arkivsocken=gr.socken))
    return ut


def for_gallra(trakter: list[TraktIOmrade]):
    """Urvalets trakter i den form gallra.gallra tar emot.

    Returnerar (egna, lanade): `egna` ar {socken: [trakt]} for trakter i sin
    egen socken, `lanade` de som arkivet har i en grannsocken.
    """
    egna: dict[str, list[str]] = {}
    for t in trakter:
        if not t.via_socken and t.trakt not in egna.setdefault(t.socken, []):
            egna[t.socken].append(t.trakt)
    lanade = [t for t in trakter if t.via_socken]
    return egna, lanade
