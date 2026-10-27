"""Lantmateriets Historiska kartor -- adresser, anrop och tolkning av svar.

**Tjansten ar oofficiell.** Den ar byggd for webbsidan, inte for oss, och kan
andras utan forvarning. Darfor ligger ALLT som ror den har: adresserna,
fragornas form, svarens form. Andras tjansten ska det racka att andra i den
har filen. Ingen annan modul far bygga en adress eller lasa ett falt ur ett
ratt svar.

**Utveckling mot testdata.** Transporten ar utbytbar. `Fixturer` svarar ur
`hk_fixtures/` och kanner igen exakt de anrop som sparades 2026-09-27; ett
anrop den inte kanner igen ar ett fel, inte ett natverksanrop. Tjansten var
stangd en hel dag under forarbetet, och varje anrop vi slipper gora ar ett
vi inte behover forklara.

**Hygglig klient** (avsnitt 6): ett anrop i taget, en paus mellan dem, och en
diskcache sa att inget hamtas tva ganger.

Tva former pa samma sak
-----------------------
Sokningen och metadatat beskriver en akt med samma faltkoder men i olika
form. Sokningen: `{"para": {"afds": ["23-HÄG-10"]}, "pg": {"atg": [...]}}` --
gemener, varden i listor. Metadatat: `{"paragraphs": [{"name": "AFDS",
"text": "23-HÄG-10"}], "paragraphGroups": [...]}` -- versaler, ett varde per
post, och samma namn kan upprepas (`AVAILABLE_COLON_TYPES` finns tva ganger i
varje SIDA). Bada gors om till `_Post` innan nagot lases.

Vad sokningen INTE innehaller
-----------------------------
Upptackt vid genomgangen av testdatan 2026-09-28, och det styr gallringen:

* **REG-sokningen har varken trakt, fastighet eller sidtyp.** Bara
  beteckning, datum, atgard, antal bilder (`anbi`) och flaggan `kart` (J/N).
  I Haggenas har 86 av 166 akter `kart=J`. Trakterna och sidregistret kommer
  forst med metadatat, ett anrop per akt.
* **LMS-sokningen har trakten** (`lsb.sby`, "Andersgård nr 1") men varken
  sidtyp eller kartflagga. Sidregistret kraver metadata ocksa har.
"""
from __future__ import annotations

import binascii
import hashlib
import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime

BAS = "https://historiskakartor.lantmateriet.se"

REG = "REG"
LMS = "LMS"
ARKIV = (REG, LMS)

# Sidtyper som ar kartor. REG markerar handlingarna med HTYP, LMS med egna
# koder. `KARTA-F` (fargkartor) ar den enda REG-kartkod som finns i testdatan;
# prefixet tar ocksa andra KARTA-varianter om de finns.
_KARTTYP_LMS = "LMS_KARTA"

# Sokningens storsta sida. Haggenas ar 166 + 24 akter, sa en sida racker for
# en socken -- men `_sok` bladdrar anda om svaret sager att det finns fler.
SIDSTORLEK = 2000


class TjanstFel(RuntimeError):
    """Tjansten svarade inte, eller svarade med nagot som inte ar JSON."""


class EjIFixtur(TjanstFel):
    """Anropet finns inte i testdatan. Ett fel -- aldrig ett tyst natanrop."""


# =========================================================================
# Adresser
# =========================================================================

def _url_vokabular() -> str:
    return f"{BAS}/data/archive-service/LM_LMS/counties"


def _url_atgarder(arkiv: str) -> str:
    return f"{BAS}/data/archive-service/{arkiv}/measures"


def _url_karttyper() -> str:
    return f"{BAS}/data/archive-service/LMS/maptypes"


def _url_sok(arkiv: str, forsta: int = 1) -> str:
    return (f"{BAS}/data/metadata-service/query/{arkiv.lower()}"
            f"?firstMatch={forsta}&pageSize={SIDSTORLEK}")


def _url_metadata(arkiv: str, bas: str, ktun: str) -> str:
    if arkiv == REG:
        return f"{BAS}/data/search-service/REG/metadata/{bas}/{ktun}"
    return f"{BAS}/data/search-service/LMS/metadata/documentcode/{bas}:{ktun}"


# Bildtjansten. Kartlagd 2026-09-28 ur webbsidans egen kod (index-*.js):
# visarens knappar bygger adresserna sa har, och de har provats en gang var.
#
#   TIFF  {bas}_{ktun}_{HLNR}_{SIDN}.tiff   en sida, okomprimerad RGB:
#         23-hag-10 s. 1 ar 6150 x 5812 px, 254 dpi, 107 MB, 10 s. Inget
#         Content-Length, inget stod for Range -- storleken syns forst efterat.
#   PDF   document.pdf?archive={bas}&id={akt-id}   hela akten, 4,1 MB for
#         23-hag-10. Kartsidan ligger dar i full upplosning men som JPEG med
#         kvalitet ~50; textsidorna 1-bit CCITT. Duger till miniatyrer.
#   size/document.pdf?...   PDF:ens storlek i byte, som text, utan att hamta.

def _akt_id(akt: "Akt") -> str:
    """Aktens id i bildtjanstens adresser: som webbsidan skriver det.

    REG: `AFDS` med versal forst och resten gemener -- "23-häg-10" (sidans
    `El`). LMS: `ALMS` som den ar -- "Y22-2:1".
    """
    if akt.arkiv == REG:
        b = akt.beteckning
        return b[:1].upper() + b[1:].lower()
    return akt.beteckning


def url_tiff(akt: "Akt", sida: "Sida") -> str:
    return url_tiff_for(akt.bas, akt.ktun, sida.handling, sida.sidn)


def url_tiff_for(bas: str, ktun: str, handling: int, sidn: int) -> str:
    """Samma adress ur registrets falt, utan Akt- och Sida-objekt."""
    return f"{BAS}/data/image-service/{bas}_{ktun}_{handling}_{sidn}.tiff"


def url_pdf(akt: "Akt") -> str:
    from urllib.parse import urlencode
    return (f"{BAS}/data/image-service/document.pdf?"
            + urlencode({"archive": akt.bas, "id": _akt_id(akt)}))


ARKIVNAMN = {REG: "Lantmäterimyndigheternas arkiv", LMS: "Lantmäteristyrelsens arkiv"}


def kallhanvisning(arkiv: str, beteckning: str, atgard: str | None, ar: int | None) -> str:
    """Kartan som källa, tre rader: kartarkiv, karttyp och kartakt med år -- den form
    Fornreg vill ha (användaren 2026-10-27: "när man registrerar lämningar i Fornreg ska
    det se ut som detta"), men allmän nog för en fotnot. Karttypen är aktens första
    åtgärd som arkivet skriver den."""
    typ = (atgard or "").split(";")[0].strip() or "Okänd"
    return (f"Kartarkiv: {ARKIVNAMN.get(arkiv, arkiv)}\nKarttyp: {typ}\n"
            f"Kartakt: {beteckning}" + (f"/{ar}" if ar else ""))


def kallhanvisning_for(akt: "Akt") -> str:
    return kallhanvisning(akt.arkiv, akt.beteckning, "; ".join(akt.atgarder or []), akt.ar)


def url_webb(akt: "Akt") -> str:
    """Akten i webbsidans egen visare (adressen kartlagd i webbläsaren 2026-10-27):
    sex led efter /hk/viewer/internal -- id som i bildtjänsten, ktun, delarkivet,
    arkivet, och två led som bara syns i fliktiteln (webbsidan skriver beteckningen,
    för LMS socken och trakt, och åtgärden). Utan de två sista svarar sidan 404, men
    innehållet i dem spelar ingen roll. Här beteckningen och första åtgärden."""
    from urllib.parse import quote
    led = [_akt_id(akt), akt.ktun, akt.bas, akt.arkiv, akt.beteckning,
           (akt.atgarder or ["Akt"])[0]]
    return f"{BAS}/hk/viewer/internal/" + "/".join(quote(x, safe="") for x in led)


def url_pdf_storlek(akt: "Akt") -> str:
    from urllib.parse import urlencode
    return (f"{BAS}/data/image-service/size/document.pdf?"
            + urlencode({"archive": akt.bas, "id": _akt_id(akt)}))


# =========================================================================
# Transport
# =========================================================================

class QgisTransport:
    """Anrop genom QGIS natverkslager, sa att proxyinstallningar foljer med."""

    def __init__(self, tidsgrans_s: int = 60):
        self.tidsgrans_s = tidsgrans_s

    def __call__(self, metod: str, url: str, kropp: bytes | None,
                 accept: str = "application/json") -> bytes:
        from qgis.core import QgsNetworkAccessManager
        from qgis.PyQt.QtCore import QUrl
        from qgis.PyQt.QtNetwork import QNetworkRequest

        beg = QNetworkRequest(QUrl(url))
        beg.setAttribute(QNetworkRequest.Attribute.FollowRedirectsAttribute, True)
        beg.setRawHeader(b"Accept", accept.encode())
        if metod == "POST":
            beg.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader,
                          "application/json")
            svar = QgsNetworkAccessManager.blockingPost(beg, kropp or b"",
                                                        forceRefresh=True)
        else:
            svar = QgsNetworkAccessManager.blockingGet(beg, forceRefresh=True)
        status = svar.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        if svar.error() or (status and int(status) >= 400):
            raise TjanstFel(f"Historiska kartor svarade inte ({status or '–'}): "
                            f"{svar.errorString()}\n{url}")
        return bytes(svar.content())


class UrllibTransport:
    """Utan QGIS -- for skript och prov. Foljer inte QGIS proxyinstallningar."""

    def __init__(self, tidsgrans_s: int = 60):
        self.tidsgrans_s = tidsgrans_s

    def __call__(self, metod: str, url: str, kropp: bytes | None,
                 accept: str = "application/json") -> bytes:
        import urllib.error
        import urllib.request
        from urllib.parse import quote, urlsplit, urlunsplit

        # Sockenkoden `23-häg` hamnar aldrig i adressen, men `firstMatch` och
        # beteckningar kan. Koda det som inte ar ASCII, lat resten vara.
        d = urlsplit(url)
        url = urlunsplit(d._replace(path=quote(d.path, safe="/:@-._~!$&'()*+,;=")))
        huvud = {"Accept": accept}
        if metod == "POST":
            huvud["Content-Type"] = "application/json"
        beg = urllib.request.Request(url, data=kropp, headers=huvud, method=metod)
        try:
            with urllib.request.urlopen(beg, timeout=self.tidsgrans_s) as s:
                return s.read()
        except (urllib.error.URLError, OSError) as e:
            raise TjanstFel(f"Historiska kartor svarade inte: {e}\n{url}") from e


class Fixturer:
    """Svarar ur `hk_fixtures/`. Kanner bara igen de sparade anropen.

    Nyckeln ar metod, adress och -- for sokningar -- de falt i fragan som
    skiljer de sparade svaren at. Ovriga falt maste ha sina forval; en fraga
    med t.ex. ett artal ar inte den som sparades och far inte besvaras med den.
    """

    def __init__(self, katalog: str):
        self.katalog = katalog
        self.anrop: list[tuple[str, str]] = []

    def _fil(self, *delar: str) -> bytes:
        with open(os.path.join(self.katalog, *delar), "rb") as f:
            return f.read()

    def __call__(self, metod: str, url: str, kropp: bytes | None,
                 accept: str = "application/json") -> bytes:
        self.anrop.append((metod, url))
        # Bildtjansten svarar 406 pa "Accept: application/json" (sett mot
        # tjansten 2026-09-29). Testdatan ska inte kunna svara dar tjansten
        # inte gor det.
        if "/image-service/" in url and accept == "application/json":
            raise TjanstFel("Historiska kartor svarade inte (406): Not Acceptable "
                            + url)
        sok = url.split("?")[0]
        if metod == "GET" and sok == _url_vokabular():
            return self._fil("vokabular", "LM_LMS_counties.json")
        if metod == "GET" and sok == _url_karttyper():
            return self._fil("vokabular", "LMS_maptypes.json")
        for a in ARKIV:
            if metod == "GET" and sok == _url_atgarder(a):
                return self._fil("vokabular", f"{a}_measures.json")
        if metod == "GET" and sok == _url_metadata(REG, "lm23", "000462nb"):
            return self._fil("metadata", "REG_23-hag-10.json")
        if metod == "GET" and sok == _url_metadata(
                LMS, "lms2", "4c4d535f5932322d323a31"):
            return self._fil("metadata", "LMS_Y22-2-1.json")
        pdf = {"archive=lm23&id=23-h%C3%A4g-10": "REG_23-hag-10.pdf",
               "archive=lms2&id=Y22-2%3A1": "LMS_Y22-2-1.pdf"}
        fraga = url.split("?", 1)[-1]
        if metod == "GET" and fraga in pdf:
            if sok == f"{BAS}/data/image-service/document.pdf":
                return self._fil("bilder", pdf[fraga])
            if sok == f"{BAS}/data/image-service/size/document.pdf":
                return str(os.path.getsize(os.path.join(
                    self.katalog, "bilder", pdf[fraga]))).encode()
        if metod == "POST" and url == _url_sok(REG):
            f = json.loads(kropp or b"{}")
            if f == reg_fraga_ra("23", "23-häg"):
                return self._fil("sok", "haggenas_reg.json")
        if metod == "POST" and url == _url_sok(LMS):
            f = json.loads(kropp or b"{}")
            if f == lms_fraga_ra("Y", "22"):
                return self._fil("sok", "haggenas_lms.json")
            if f == lms_fraga_ra("Y", "22", ["2"]):
                return self._fil("sok", "haggenas_lms_andersgard.json")
            if f == lms_fraga_ra("Y", "22", ["7"], rby=True):
                return self._fil("sok", "haggenas_lms_gungard_rby.json")
            if f == lms_fraga_ra("Y", "31", ["4"], rby=True):
                return self._fil("sok", "lit_lms_boda_rby.json")
        raise EjIFixtur(f"finns inte i testdatan: {metod} {url} "
                        f"{(kropp or b'').decode('utf-8', 'replace')}")


# =========================================================================
# Fragor
# =========================================================================

def reg_fraga_ra(lan: str, socken: str, trakt: str = "", atgard: str = "",
                 ar_min: int = 0, ar_max: int = 0) -> dict:
    """REG-sokningens fraga. Koderna ar REG:s: lan `23`, socken `23-häg`.

    `atgard` ar det numeriska id:t ur REG/measures. Forkortningar som `"SS"`
    ignoreras TYST av tjansten -- sokningen ger da allt, inte ingenting.
    Webbsidan kapar `yearMax` vid 1928; gor vi det inte far vi fler svar an
    den som jamfor med sidan.
    """
    if ar_max:
        ar_max = min(ar_max, 1928)
    return {"county": lan, "municipality": "", "parish": socken,
            "village": trakt.upper(), "task": atgard, "document": "",
            "yearMin": ar_min, "yearMax": ar_max, "openSearch": ""}


def lms_fraga_ra(lan: str, socken: str, trakter: list[str] | None = None,
                 atgard: str = "", ar_min: int = 0, ar_max: int = 0,
                 rby: bool = False) -> dict:
    """LMS-sokningens fraga. Koderna ar LMS:s: lan `Y`, socken `22`, trakt `2`.

    `task` ar ett mellanslag nar ingen atgard ar vald -- sa skickar webbsidan
    den. `scanned` ar alltid sant: odigitaliserade akter ar inget att galla.

    `rby` -- provat 2026-09-28 (avsnitt 4 punkt 4):

    * `False`: trakten matchas mot aktens huvudby (LSB). Andersgård: 3 akter.
    * `True`: trakten matchas BARA mot RBY-listorna, inte mot huvudbyn.
      Andersgård: 0 akter. Gungård: 2 (Y22-2:1 och Y22-2:2, bada med
      Andersgård som huvudby). En hel trakt kraver alltsa bada sokningarna.
    * **`True` matchar pa bynamnet i hela landet.** Lit/Boda gav 37 akter:
      Y22-2:1 fran Haggenas (ratt -- RBY:n namner Boda i Lit) men ocksa
      Storskiften i Edebo, Sorunda, Ljusdal ... dar en by heter Boda.
      Traffarna maste darfor filtreras lokalt pa RBY-postens `SOCK_NAMN` --
      numren duger inte, de ar aktens egna (se `By`).
    * Utan trakt spelar flaggan ingen roll: Haggenas ger 24 akter med bada.
    """
    if ar_min:
        ar_min = max(ar_min, 1600)
    return {"county": lan, "parish": socken, "settlements": list(trakter or []),
            "task": atgard or " ", "yearMin": ar_min, "yearMax": ar_max,
            "surveyor": "", "scanned": True, "rbySelected": rby,
            "openSearch": "", "mapTypeId": "detaljerade"}


# =========================================================================
# Vokabular
# =========================================================================

@dataclass
class Trakt:
    namn: str
    i_reg: bool
    i_lms: bool
    lms_nummer: list[str]


@dataclass
class Socken:
    namn: str
    lan: "Lan" = field(repr=False)
    reg_kod: str            # "23-häg" -- REG:s sockenkod, lan och kortkod
    lms_nummer: str         # "22"
    i_reg: bool
    i_lms: bool
    trakter: list[Trakt] = field(repr=False)

    def trakt(self, namn: str) -> Trakt | None:
        n = namn.casefold()
        return next((t for t in self.trakter if t.namn.casefold() == n), None)


@dataclass
class Lan:
    namn: str
    reg_nummer: str         # "23"
    reg_bokstav: str        # "Z" -- dagens lansbokstav, anvands inte i fragor
    lms_bokstav: str        # "Y" -- LMS:s, fore 1970-talets omnumrering
    socknar: list[Socken] = field(repr=False)


class Vokabular:
    """Lan, socknar och trakter med bada arkivens koder.

    Filen ar 15,7 MB for hela landet och andras sallan. Den cachas och hamtas
    om bara pa begaran.
    """

    def __init__(self, ra: list[dict]):
        self.lan: list[Lan] = []
        for l in ra:
            lan = Lan(namn=l["name"], reg_nummer=l.get("lmNumber", ""),
                      reg_bokstav=l.get("lmLetter", ""),
                      lms_bokstav=l.get("lmsLetter", ""), socknar=[])
            for p in l.get("parishes", []):
                kort = p.get("lmShortCode") or ""
                lan.socknar.append(Socken(
                    namn=p["name"], lan=lan,
                    reg_kod=f"{lan.reg_nummer}-{kort}" if kort else "",
                    lms_nummer=p.get("lmsNumber") or "",
                    i_reg=bool(p.get("lm")), i_lms=bool(p.get("lms")),
                    trakter=[Trakt(namn=v["name"], i_reg=bool(v.get("lm")),
                                   i_lms=bool(v.get("lms")),
                                   lms_nummer=list(v.get("lmsNumbers") or []))
                             for v in p.get("villages", [])]))
            self.lan.append(lan)

    def lan_med(self, nummer_eller_bokstav: str) -> Lan | None:
        k = nummer_eller_bokstav.strip().upper()
        return next((l for l in self.lan
                     if k in (l.reg_nummer, l.reg_bokstav.upper(),
                              l.lms_bokstav.upper())), None)

    def socken(self, namn: str, lan: str | None = None) -> Socken:
        """Socknen med namnet. Lanet behovs bara nar namnet finns i flera."""
        n = namn.casefold()
        kandidater = [s for l in self.lan for s in l.socknar
                      if s.namn.casefold() == n
                      and (lan is None or l is self.lan_med(lan))]
        if not kandidater:
            raise KeyError(f"socknen {namn} finns inte i vokabulären")
        if len(kandidater) > 1:
            raise KeyError(f"{namn} finns i flera län: "
                           + ", ".join(s.lan.namn for s in kandidater))
        return kandidater[0]

    def socken_i_lan(self, lan_namn: str, socken_namn: str) -> Socken | None:
        """Exakt uppslag pa lanets och socknens namn, som sockenlagret sparar dem."""
        return next((s for l in self.lan if l.namn == lan_namn
                     for s in l.socknar if s.namn == socken_namn), None)

    def socken_med_reg_kod(self, kod: str) -> Socken | None:
        k = kod.casefold()
        return next((s for l in self.lan for s in l.socknar
                     if s.reg_kod.casefold() == k), None)

    def socken_med_lms_kod(self, lan_bokstav: str,
                           nummer: str) -> Socken | None:
        lan = self.lan_med(lan_bokstav)
        if lan is None:
            return None
        return next((s for s in lan.socknar if s.lms_nummer == nummer), None)


@dataclass
class Atgard:
    namn: str
    id: str
    nyckelord: list[str]


def _atgarder(ra: list[dict]) -> list[Atgard]:
    return [Atgard(namn=a["name"], id=str(a["id"]),
                   nyckelord=list(a.get("keyword") or [])) for a in ra]


# =========================================================================
# Akter och sidor
# =========================================================================

@dataclass
class Sida:
    lopnr: int              # visarens sidnummer: 1.tiff, 2.tiff ...
    handling: int           # HLNR -- vilken handling i akten
    sidn: int               # sidnummer inom handlingen; borjar om per handling
    sidtyp: str             # KARTA-F, AKT, LMS_KARTA, LMS_TEXT
    guid: str               # AIP -- unik for sidan i hela arkivet
    djvu: str = ""          # DJVU_COLON_NAME
    tiff: str = ""          # TIFF_COLON_NAME -- sokvag pa servern, ej adress
    typer: dict[str, str] = field(default_factory=dict)  # mimetyp -> namn

    @property
    def karta(self) -> bool:
        return self.sidtyp.upper().startswith("KARTA") or \
            self.sidtyp.upper() == _KARTTYP_LMS

    @property
    def har_tiff(self) -> bool:
        """Webbsidan erbjuder TIFF bara nar sidan listar `image/tiff`."""
        return "image/tiff" in self.typer


@dataclass
class Fastighet:
    """En FAST-grupp i en REG-akt. Namnen i versaler, som i arkivet."""
    fnr: str
    ursprunglig_trakt: str  # UTRA -- namnet nar akten upprattades
    gallande_trakt: str     # GTRA -- dagens namn, t.ex. HÄGGENÅS-HÖGEN
    block: str = ""
    enhet: str = ""
    kommun: str = ""        # GKOM


@dataclass
class By:
    """En RBY-post i en LMS-akt: en by akten beror.

    **Bara namnen gar att lita pa.** I testdatan har alla 22 byar i Y22-2:1
    `NR=2` och `SOCK_NR=22` -- aktens egna nummer -- aven byarna i As, Lit
    och Follinge. Numren ar alltsa kopierade, inte byns egna, och anvands inte.
    """
    namn: str               # "Backegård nr 1-2"
    socken: str             # "Häggenås socken"

    @property
    def trakt(self) -> str:
        return utan_nummer(self.namn)


_NR = re.compile(r"\s+nr\s+[\d\s,\-–o]+$", re.IGNORECASE)


def utan_nummer(namn: str) -> str:
    """"Andersgård nr 1" -> "Andersgård", "Munkflohögen nr 1-11" -> ...

    LMS skriver hemmansnumren efter bynamnet; vokabularen gor det inte.
    Det ar ingen normalisering av stavningen -- bara ett borttaget tillagg.
    """
    return _NR.sub("", namn).strip()


def utan_socken(namn: str) -> str:
    """"Häggenås socken" -> "Häggenås". "Lits socken" -> "Lits" -- genitivet
    star kvar; det gar inte att ta bort utan att veta om namnet slutar pa s.
    Jamfor med `samma_socken`."""
    return re.sub(r"\s+(socken|sn)$", "", namn.strip(), flags=re.IGNORECASE)


def samma_socken(a: str, b: str) -> bool:
    """LMS skriver socknen i genitiv: "Lits socken", "Ås socken",
    "Häggenås socken". Lit = Lits, men Häggenås = Häggenås."""
    a, b = a.casefold().strip(), b.casefold().strip()
    return a == b or a == b + "s" or a + "s" == b


@dataclass
class Akt:
    arkiv: str              # REG | LMS
    bas: str                # lm23 | lms2 -- delarkivet, ingar i adressen
    ktun: str               # aktens id i delarkivet
    beteckning: str         # 23-HÄG-10 | Y22-2:1
    atgarder: list[str]     # "Storskifte" -- som arkivet skriver, forsta
    atgardskoder: list[str]  # stor bokstav; kan saknas (REG)
    ar: int | None
    datum: str | None       # ISO om dagen ar kand, annars None
    antal_sidor: int | None  # ANBI
    har_karta: bool | None  # REG-sokningens `kart`; None = vet inte
    lan: str = ""
    socken: str = ""        # sockennamn som arkivet skriver det
    trakter: list[str] = field(default_factory=list)
    fastigheter: list[Fastighet] = field(default_factory=list)
    byar: list[By] = field(default_factory=list)
    anmarkning: str = ""
    period: str = ""        # LMS VAR, "1762-71"
    lantmatare: str = ""    # LMS UAV
    huvudakt: list[str] = field(default_factory=list)  # HAKT
    sidor: list[Sida] | None = None  # None = sidregistret ar inte hamtat
    ra_sok: dict | None = field(default=None, repr=False)
    ra_metadata: dict | None = field(default=None, repr=False)

    @property
    def nyckel(self) -> str:
        """Unik i bada arkiven, och densamma for alla anvandare."""
        return f"{self.arkiv}:{self.bas}:{self.ktun}"

    @property
    def kartsidor(self) -> list[Sida] | None:
        return None if self.sidor is None else [s for s in self.sidor if s.karta]

    @property
    def antal_kartsidor(self) -> int | None:
        k = self.kartsidor
        return None if k is None else len(k)

    @property
    def gallande_trakter(self) -> list[str]:
        return _unika(f.gallande_trakt for f in self.fastigheter)

    @property
    def fastighetsnummer(self) -> list[str]:
        return _unika(f.fnr for f in self.fastigheter)


def _unika(varden) -> list[str]:
    ut: list[str] = []
    for v in varden:
        if v and v not in ut:
            ut.append(v)
    return ut


@dataclass
class LmsBeteckning:
    lan: str
    socken: str
    trakt: str
    akt: str


def las_lms_beteckning(beteckning: str) -> LmsBeteckning | None:
    """`Y22-2:1` = lan Y, socken 22, trakt 2, akt 1. None om formen avviker.

    Lansbokstaven kan vara tva tecken i andra lan an Jamtland (inte i LMS,
    men for sakerhets skull): allt fore forsta siffran.
    """
    m = re.fullmatch(r"([A-ZÅÄÖ]+)(\d+)-(\d+):(\w+)", beteckning.strip())
    return LmsBeteckning(*m.groups()) if m else None


def ktun_text(ktun: str) -> str:
    """LMS-aktens KTUN ar beteckningen hexkodad: `LMS_Y22-2:1`. REG:s ar det
    inte, och ges da tillbaka som den ar."""
    try:
        return binascii.unhexlify(ktun).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return ktun


class _Post:
    """En akt i vilken som helst av de tva formerna, lasbar pa samma satt."""

    def __init__(self, falt: dict[str, list[str]],
                 grupper: dict[str, list[dict[str, list[str]]]]):
        self.falt = falt
        self.grupper = grupper

    @classmethod
    def ur_sok(cls, d: dict) -> "_Post":
        falt = {k.upper(): list(v) for k, v in (d.get("para") or {}).items()}
        grupper = {g.upper(): [{k.upper(): list(v) for k, v in e.items()}
                               for e in lista]
                   for g, lista in (d.get("pg") or {}).items()}
        return cls(falt, grupper)

    @classmethod
    def ur_metadata(cls, d: dict) -> "_Post":
        def samla(stycken):
            ut: dict[str, list[str]] = {}
            for p in stycken or []:
                ut.setdefault(p["name"].upper(), []).append(p.get("text", ""))
            return ut
        falt = samla(d.get("paragraphs"))
        grupper: dict[str, list[dict[str, list[str]]]] = {}
        for g in d.get("paragraphGroups") or []:
            grupper.setdefault(g["name"].upper(), []).append(
                samla(g.get("paragraphs")))
        return cls(falt, grupper)

    def ett(self, namn: str, ur: dict | None = None) -> str:
        v = (ur if ur is not None else self.falt).get(namn) or [""]
        return v[0]

    def grupp(self, namn: str) -> list[dict[str, list[str]]]:
        return self.grupper.get(namn, [])


def _ar_och_datum(*kandidater: str) -> tuple[int | None, str | None]:
    """Forsta kandidat med ett ar. `17740305` -> (1774, "1774-03-05");
    `17710000` -> (1771, None); `00000000` hoppas over."""
    for k in kandidater:
        k = (k or "").strip()
        if len(k) >= 4 and k[:4].isdigit() and int(k[:4]) > 0:
            ar = int(k[:4])
            if len(k) >= 8 and k[:8].isdigit() and k[4:8] != "0000":
                try:
                    return ar, datetime.strptime(k[:8], "%Y%m%d").date().isoformat()
                except ValueError:
                    pass
            return ar, None
    return None, None


def _versal_forst(s: str) -> str:
    """"STORSKIFTE" -> "Storskifte". REG skriver versaler, LMS inte."""
    s = s.strip()
    return s[:1].upper() + s[1:].lower() if s.isupper() else s


def _int(s: str) -> int | None:
    try:
        return int(s)
    except (TypeError, ValueError):
        return None


def _sidor(post: _Post) -> list[Sida]:
    ut: list[Sida] = []
    for i, g in enumerate(post.grupp("SIDA"), start=1):
        typer: dict[str, str] = {}
        for t in g.get("AVAILABLE_COLON_TYPES", []):
            mime, _, namn = t.partition(" ")
            typer[mime] = namn
        # Visarens sidnummer ar platsen i SIDA-listan: webbsidan slar upp
        # sida N som SIDA[N-1] (`Fu` i index-*.js). TIFF-namnet ("3.tiff")
        # sammanfaller med det i testakterna men ar inte det sidan anvander.
        ut.append(Sida(
            lopnr=i,
            handling=_int(post.ett("HLNR", g)) or 0,
            sidn=_int(post.ett("SIDN", g)) or 0,
            sidtyp=post.ett("HTYP", g),
            guid=post.ett("AIP", g),
            djvu=post.ett("DJVU_COLON_NAME", g),
            tiff=post.ett("TIFF_COLON_NAME", g),
            typer=typer))
    return ut


def tolka_akt(arkiv: str, post: _Post, ra_sok: dict | None = None,
              ra_metadata: dict | None = None) -> Akt:
    """En akt ur sokning eller metadata. Sidorna finns bara i metadatat."""
    p = post
    atg = p.grupp("ATG")
    # Samma ordning som webbsidan (index-*.js, `Ll` och `vu`), sa att arets
    # akt har samma ar i pluginet som pa sidan. PULD sist, for poster utan
    # nagot av de andra: den ar inte alltid aktens ar -- Y22-2:2 har PULD
    # 1841 men UART 1836, och sidan visar 1836.
    if arkiv == LMS:
        ar, datum = _ar_och_datum(p.ett("UART"), p.ett("UARF"), p.ett("ARTA"),
                                  p.ett("PULD"))
    else:
        ar, datum = _ar_och_datum(p.ett("FDAT"), p.ett("UDT"), p.ett("UDFR"),
                                  p.ett("PULD"))
    kart = p.ett("KART")
    akt = Akt(
        arkiv=arkiv, bas=p.ett("BASE"), ktun=p.ett("KTUN"),
        beteckning=p.ett("IDHR") or p.ett("AFDS") or p.ett("ALMS"),
        atgarder=[_versal_forst(p.ett("ATGBESK", g)) for g in atg
                  if p.ett("ATGBESK", g)],
        atgardskoder=[p.ett("ATGFORK", g) for g in atg if p.ett("ATGFORK", g)],
        ar=ar, datum=datum, antal_sidor=_int(p.ett("ANBI")),
        har_karta={"J": True, "N": False}.get(kart.upper()) if kart else None,
        anmarkning=p.ett("ANM"), period=p.ett("VAR"), lantmatare=p.ett("UAV"),
        huvudakt=[h for h in p.falt.get("HAKT", []) if h],
        ra_sok=ra_sok, ra_metadata=ra_metadata)

    if arkiv == LMS:
        lsb = p.grupp("LSB")
        if lsb:
            akt.lan = p.ett("LAN", lsb[0])
            akt.socken = utan_socken(p.ett("SOCN", lsb[0]))
            akt.trakter = _unika(utan_nummer(p.ett("SBY", g)) for g in lsb)
        akt.byar = [By(namn=p.ett("NAMN", g),
                       socken=utan_socken(p.ett("SOCK_NAMN", g)))
                    for g in p.grupp("RBY")]
    else:
        lan = p.grupp("LAN")
        if lan:
            akt.lan = _versal_forst(p.ett("LANN", lan[0]))
        sock = p.grupp("SOCK")
        if sock:
            akt.socken = _versal_forst(p.ett("SOCKENNAMN", sock[0]))
        akt.fastigheter = [Fastighet(
            fnr=p.ett("FNR", g), ursprunglig_trakt=p.ett("UTRA", g),
            gallande_trakt=p.ett("GTRA", g), block=p.ett("UBLO", g),
            enhet=p.ett("UENH", g), kommun=p.ett("GKOM", g))
            for g in p.grupp("FAST")]
        akt.trakter = _unika(f.ursprunglig_trakt for f in akt.fastigheter)

    if ra_metadata is not None:
        akt.sidor = _sidor(p)
    return akt


# =========================================================================
# Klienten
# =========================================================================

class Klient:
    """Hygglig klient: ett anrop i taget, paus mellan dem, diskcache.

    `transport` ar en funktion (metod, url, kropp) -> bytes. Forval: QGIS
    natverkslager om QGIS finns, annars urllib.

    `cache` ar tjanstecachens katalog (avsnitt 5). Utan den cachas ingenting
    -- bara lampligt i prov.

    `max_alder_s` per anrop: None = ett cachat svar galler for alltid. Arkivet
    andras sallan; vill man ha farska svar fragar man efter dem.
    """

    def __init__(self, transport=None, cache: str | None = None,
                 paus_s: float = 1.0, klocka=time.monotonic, sov=time.sleep):
        if transport is None:
            try:
                import qgis.core  # noqa: F401
                transport = QgisTransport()
            except ImportError:
                transport = UrllibTransport()
        self.transport = transport
        self.cache = cache
        self.paus_s = paus_s
        self._klocka = klocka
        self._sov = sov
        self._senast: float | None = None
        self.natanrop = 0       # hur manga anrop som faktiskt gick ut

    # ---------------------------------------------------------------- cache
    def _cachefil(self, del_: str, namn: str) -> str | None:
        if not self.cache:
            return None
        return os.path.join(self.cache, del_, namn + ".json")

    @staticmethod
    def _las_cache(fil: str | None, max_alder_s: float | None):
        if not fil or not os.path.exists(fil):
            return None
        if max_alder_s is not None and \
                time.time() - os.path.getmtime(fil) > max_alder_s:
            return None
        try:
            with open(fil, encoding="utf-8") as f:
                return json.load(f)["svar"]
        except (OSError, ValueError, KeyError):
            return None     # trasig cachefil -- hamta om

    @staticmethod
    def _skriv_cache(fil: str | None, metod: str, url: str,
                     fraga: dict | None, svar) -> None:
        if not fil:
            return
        os.makedirs(os.path.dirname(fil), exist_ok=True)
        tmp = f"{fil}.{os.getpid()}.{threading.get_ident()}.delvis"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"metod": metod, "url": url, "fraga": fraga,
                       "hamtad": datetime.now().isoformat(timespec="seconds"),
                       "svar": svar}, f, ensure_ascii=False)
        os.replace(tmp, fil)

    # ---------------------------------------------------------------- anrop
    def _skicka(self, metod: str, url: str, kropp: bytes | None,
                accept: str = "application/json") -> bytes:
        """Ett anrop, efter pausen. Det enda stallet dar natet anvands.

        `accept`: bildtjansten svarar 406 Not Acceptable pa
        "Accept: application/json" -- PDF:erna hamtas med sin egen typ.
        Upptackt 2026-09-29 nar kontaktkartan for Lit bara visade tomma rutor.
        """
        if self._senast is not None and self.paus_s > 0:
            vanta = self.paus_s - (self._klocka() - self._senast)
            if vanta > 0:
                self._sov(vanta)
        try:
            if accept == "application/json":
                return self.transport(metod, url, kropp)
            return self.transport(metod, url, kropp, accept=accept)
        finally:
            self._senast = self._klocka()
            self.natanrop += 1

    def _anropa(self, metod: str, url: str, fraga: dict | None,
                cachefil: str | None, max_alder_s: float | None):
        svar = self._las_cache(cachefil, max_alder_s)
        if svar is not None:
            return svar
        kropp = (json.dumps(fraga, ensure_ascii=False).encode("utf-8")
                 if fraga is not None else None)
        ra = self._skicka(metod, url, kropp)
        try:
            svar = json.loads(ra.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as e:
            # En stangd tjanst svarar ofta med en HTML-sida och status 200.
            borjan = ra[:120].decode("utf-8", "replace").strip()
            raise TjanstFel(f"Historiska kartor svarade inte med JSON: "
                            f"{borjan!r}\n{url}") from e
        self._skriv_cache(cachefil, metod, url, fraga, svar)
        return svar

    # ------------------------------------------------------------ vokabular
    def vokabular(self, max_alder_s: float | None = None) -> Vokabular:
        ra = self._anropa("GET", _url_vokabular(), None,
                          self._cachefil("vokabular", "counties"), max_alder_s)
        return Vokabular(ra)

    def atgarder(self, arkiv: str,
                 max_alder_s: float | None = None) -> list[Atgard]:
        ra = self._anropa("GET", _url_atgarder(arkiv), None,
                          self._cachefil("vokabular", f"{arkiv}_measures"),
                          max_alder_s)
        return _atgarder(ra)

    # ------------------------------------------------------------- sokning
    def _sok(self, arkiv: str, fraga: dict,
             max_alder_s: float | None) -> list[dict]:
        nyckel = hashlib.sha1(json.dumps(fraga, sort_keys=True,
                                         ensure_ascii=False).encode()).hexdigest()
        dokument: list[dict] = []
        forsta = 1
        while True:
            svar = self._anropa(
                "POST", _url_sok(arkiv, forsta), fraga,
                self._cachefil("sok", f"{arkiv}_{nyckel[:16]}_{forsta}"),
                max_alder_s)
            sida = svar.get("documents") or []
            dokument.extend(sida)
            totalt = svar.get("total_matches") or 0
            if not sida or len(dokument) >= totalt:
                return dokument
            forsta += len(sida)

    def sok_reg(self, socken: Socken, trakt: str = "", atgard: str = "",
                max_alder_s: float | None = None) -> list[Akt]:
        fraga = reg_fraga_ra(socken.lan.reg_nummer, socken.reg_kod, trakt, atgard)
        akter = [tolka_akt(REG, _Post.ur_sok(d), ra_sok=d)
                 for d in self._sok(REG, fraga, max_alder_s)]
        # REG-sokningens poster saknar socken och lan; de ar fragans.
        for a in akter:
            a.lan = a.lan or socken.lan.namn
            a.socken = a.socken or socken.namn
        return akter

    def sok_lms(self, socken: Socken, trakter: list[str] | None = None,
                atgard: str = "", rby: bool = False,
                max_alder_s: float | None = None) -> list[Akt]:
        """`trakter` ar trakternas LMS-nummer (`["2"]`), inte namn."""
        fraga = lms_fraga_ra(socken.lan.lms_bokstav, socken.lms_nummer,
                             trakter, atgard, rby=rby)
        akter = [tolka_akt(LMS, _Post.ur_sok(d), ra_sok=d)
                 for d in self._sok(LMS, fraga, max_alder_s)]
        # Socknen som vokabularen skriver den, inte i LMS:s genitiv ("Lits").
        for a in akter:
            if samma_socken(a.socken, socken.namn):
                a.socken = socken.namn
        return akter

    def sok_socken(self, socken: Socken,
                   max_alder_s: float | None = None) -> list[Akt]:
        """Hela socknen ur bada arkiven. Filtreringen gors lokalt (avsnitt 3)."""
        akter: list[Akt] = []
        if socken.i_reg and socken.reg_kod:
            akter += self.sok_reg(socken, max_alder_s=max_alder_s)
        if socken.i_lms and socken.lms_nummer:
            akter += self.sok_lms(socken, max_alder_s=max_alder_s)
        return akter

    # ---------------------------------------------------------------- bilder
    def pdf_storlek(self, akt: Akt) -> int | None:
        """Akt-PDF:ens storlek i byte, utan att hamta den. Ett litet anrop."""
        try:
            return int(self._skicka("GET", url_pdf_storlek(akt), None,
                                    accept="text/plain, */*").strip())
        except ValueError:
            return None

    def akt_pdf(self, akt: Akt) -> str:
        """Hela aktens PDF, i cachen. Hamtas en gang; miniatyrerna gors ur den
        (avsnitt 4 punkt 2). Kraver cache -- en PDF ar for stor att halla i
        minnet i onodan.

        Filen far sitt namn forst nar den ar komplett och borjar med `%PDF`:
        en felsida sparas annars lika garna som en akt.
        """
        if not self.cache:
            raise TjanstFel("akt_pdf kräver en tjänstecache")
        fil = os.path.join(self.cache, "pdf", f"{akt.arkiv}_{akt.bas}_{akt.ktun}.pdf")
        if os.path.exists(fil):
            return fil
        ra = self._skicka("GET", url_pdf(akt), None, accept="application/pdf, */*")
        if not ra.startswith(b"%PDF"):
            raise TjanstFel(f"{akt.beteckning}: PDF:en är ingen PDF: "
                            f"{ra[:80].decode('utf-8', 'replace')!r}")
        os.makedirs(os.path.dirname(fil), exist_ok=True)
        # Trad-id med: bakgrundsuppgiften och forstoringen kan hamta samtidigt.
        tmp = f"{fil}.{os.getpid()}.{threading.get_ident()}.delvis"
        with open(tmp, "wb") as f:
            f.write(ra)
        os.replace(tmp, fil)
        return fil

    def hamta_tiff(self, bas: str, ktun: str, handling: int, sidn: int,
                   mal: str) -> str:
        """En sida som TIFF, till `mal`. Okomprimerad fran tjansten: 107 MB
        for 23-hag-10 s. 1, ca 10 s (avsnitt 4 punkt 1). Filen far sitt namn
        forst nar den ar komplett och ar en TIFF."""
        ra = self._skicka("GET", url_tiff_for(bas, ktun, handling, sidn), None,
                          accept="image/tiff, */*")
        if not (ra.startswith(b"II*\x00") or ra.startswith(b"MM\x00*")):
            raise TjanstFel(f"{bas}_{ktun}_{handling}_{sidn}: svaret är ingen TIFF: "
                            f"{ra[:80].decode('utf-8', 'replace')!r}")
        os.makedirs(os.path.dirname(os.path.abspath(mal)), exist_ok=True)
        tmp = f"{mal}.{os.getpid()}.{threading.get_ident()}.delvis"
        with open(tmp, "wb") as f:
            f.write(ra)
        os.replace(tmp, mal)
        return mal

    # ------------------------------------------------------------ metadata
    def metadata(self, akt: Akt, max_alder_s: float | None = None) -> Akt:
        """Hela akten: sidregister, fastigheter (REG), byar (LMS).

        Ett anrop per akt. Soknings-posten foljer med in i den nya akten, sa
        att inget som bara sokningen visste gar forlorat (REG-sokningens
        `kart`-flagga finns inte i metadatat).
        """
        url = _url_metadata(akt.arkiv, akt.bas, akt.ktun)
        svar = self._anropa("GET", url, None,
                            self._cachefil("metadata",
                                           f"{akt.arkiv}_{akt.bas}_{akt.ktun}"),
                            max_alder_s)
        docs = svar.get("documents") or []
        if len(docs) != 1:
            raise TjanstFel(f"{akt.beteckning}: metadata gav {len(docs)} "
                            f"akter, väntade 1\n{url}")
        ny = tolka_akt(akt.arkiv, _Post.ur_metadata(docs[0]),
                       ra_sok=akt.ra_sok, ra_metadata=docs[0])
        if ny.har_karta is None:
            ny.har_karta = akt.har_karta
        ny.lan = ny.lan or akt.lan
        if not ny.socken or samma_socken(ny.socken, akt.socken):
            ny.socken = akt.socken or ny.socken
        return ny
