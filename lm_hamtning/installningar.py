"""Installningarna: var arkivet, cachen och referensdatan ligger (avsnitt 5).

Lagras per QGIS-profil i QSettings, som Faltunderlagets -- det ar sokvagar,
inte hemligheter, och de ar desamma vecka efter vecka.

**Referensdatan letas upp.** Anvandaren pekar ut en mapp (t.ex.
`C:\\Lantmäteriet Kartor`), och pluginet hittar lagren i den pa namn:
Socken och stad, Kommun, lan och rike, traktlagret, fastighetsindelningens
kommunfiler, ortnamnsregistret. Hittas nagot inte sags det, och
det kan pekas ut for hand (avsnitt 5: "med vagledning nar nagot inte kanns
igen"). Utan referensdata fungerar pluginet anda, med farre mojligheter:
utan Socken och stad gar urvalet bara pa socknar valda pa namn.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, fields

from .fastighet import ar_fil as _ar_fastighetsfil
from .kommuner import ar_kommunfil as _ar_kommunfil
from .ortnamn import registret as _ortnamnsregistret
from . import variant

PREFIX = "lm_historiska_kartor/"

# En textfil i tjänstecachen som säger vad mappen är. Anna 2026-10-27, första
# användaren: tog miniatyrerna i tjanstecache/miniatyrer (JPG, 20 dpi, tekniska namn)
# för de nedladdade kartorna -- "bildkvalitet kass", "tappar aktnamnet".
LAS_MIG_CACHE = "LÄS MIG.txt"
TEXT_CACHE = """Det här är pluginets arbetsfiler (LM Historiska kartor).

Här ligger kontaktkartans små förhandsbilder (mappen miniatyrer: JPG i låg
upplösning med tekniska namn) och svar från Lantmäteriets tjänster, så att
inget behöver hämtas två gånger. Inget här är till för att öppnas i QGIS.

Kartorna i full upplösning hamnar inte här. De hämtas av knappen Ladda ned
i pluginet, sedan du markerat Behåll i kontaktkartan, och läggs som TIFF i
mappen kartor i arkivmappen, en undermapp per socken, med åtgärd, år och
aktbeteckning i filnamnet.
"""
TEXT_CACHE_HAMTNING = """
Mappen kan tas bort när du vill; pluginet bygger upp den igen vid behov,
men då hämtas förhandsbilderna om.
"""
TEXT_CACHE_HELA = """
Hela verktyget har också sina arbetsfiler här: automatikens historik, lästa
kartor, passpunkter. Ta inte bort mappen i onödan.
"""


def markera_cache(katalog: str) -> None:
    """Skriver LÄS MIG.txt i tjänstecachen om den saknas. Fel ignoreras: cachen
    är inget krav och texten är bara en upplysning."""
    if not katalog:
        return
    fil = os.path.join(katalog, LAS_MIG_CACHE)
    if os.path.exists(fil):
        return
    try:
        os.makedirs(katalog, exist_ok=True)
        with open(fil, "w", encoding="utf-8") as f:
            f.write(TEXT_CACHE + (TEXT_CACHE_HAMTNING if variant.BARA_HAMTNING else TEXT_CACHE_HELA))
    except OSError:
        pass


@dataclass
class Installningar:
    arkiv: str = ""                 # registret och kartorna
    cache: str = ""                 # tjanstecachen; tom = <arkiv>/tjanstecache
    referensdata: str = ""          # mappen som letas igenom
    socken_och_stad: str = ""       # tom = letas upp i referensdatan
    lan: str = ""                   # Kommun, lan och rike (Lantmateriet, kommuner.py); tom = letas upp
    traktlager: str = ""            # tom = inget eget traktlager
    traktlager_lager: str = ""
    traktlager_traktfalt: str = "TRAKT"
    traktlager_sockenfalt: str = ""
    ortnamn: str = ""               # mapp med ortnamn_se.gpkg; tom = arkivets referens/ortnamn
    authcfg: str = ""               # Geotorget-kontot (QGIS autentisering); tom = Faltunderlagets som forval
    api_nyckel: str = ""            # Anthropic, for "Las kartan" (lasning.py); bara i QSettings

    # ------------------------------------------------------------ harledda
    @property
    def registerfil(self) -> str:
        return os.path.join(self.arkiv, "register.gpkg") if self.arkiv else ""

    @property
    def cachekatalog(self) -> str:
        if self.cache:
            return self.cache
        return os.path.join(self.arkiv, "tjanstecache") if self.arkiv else ""

    @property
    def sockenlager(self) -> str:
        return os.path.join(self.cachekatalog, "socknar.gpkg") if self.cachekatalog else ""

    @property
    def miniatyrer(self) -> str:
        return os.path.join(self.cachekatalog, "miniatyrer") if self.cachekatalog else ""

    def sokvag_socken_och_stad(self) -> str:
        return self.socken_och_stad or hitta(self.referensdata).socken_och_stad

    def sokvag_lan(self) -> str:
        """Kommun, lan och rike: installningen, annars referensdatan (nedladdad for hand),
        annars arkivets referens/kommun-lan-rike (hamtad med kontot, kommuner.hamta)."""
        if self.lan:
            return self.lan
        r = hitta(self.referensdata).lan
        if r:
            return r
        from . import kommuner
        f = kommuner.filer(os.path.join(self.arkiv, "referens")) if self.arkiv else []
        return f[0] if f else ""

    def ortnamnsregister(self) -> str | None:
        """Ortnamn Nedladdning (`ortnamn_se.gpkg`): inställningens mapp, annars
        arkivets `referens/ortnamn`, annars referensdatan (`hitta`; 2026-10-27, så att
        den får ligga bredvid de andra nedladdade lagren). Fältunderlagets arkiv läses
        inte (KRAV avsnitt 2, 2026-10-08)."""
        for a in (self.ortnamn,
                  os.path.join(self.arkiv, "referens", "ortnamn") if self.arkiv else ""):
            r = _ortnamnsregistret(a) if a else None
            if r:
                return r
        return hitta(self.referensdata).ortnamn or None

    def fastighetsfiler(self, koder=None) -> list[str]:
        """Fastighetsindelningens geopackage (fastighet.py): arkivets referens/fastighetsindelning
        (hämtade med kontot) och de i referensdatan (nedladdade för hand, `hitta`). `koder`:
        bara de kommunerna (kn2380 i filnamnet); tomt = alla. En fil utan kommunkod i namnet
        (levererad per län eller omdöpt) läses alltid (användaren 2026-10-27: "är väl län
        och inte kommun?" -- produkten är per kommun, men namnet ska inte avgöra)."""
        import re
        from .fastighet import filer as _fastighetsfiler
        ut = _fastighetsfiler(os.path.join(self.arkiv, "referens")) if self.arkiv else []
        setts = {os.path.normcase(os.path.abspath(f)) for f in ut}
        for f in hitta(self.referensdata).fastighet:
            if os.path.normcase(os.path.abspath(f)) not in setts:
                ut.append(f)
        if koder:
            ut = [f for f in ut if not re.search(r"kn\d{4}", os.path.basename(f).lower())
                  or any(f"kn{k}" in os.path.basename(f).lower() for k in koder)]
        return ut

    def saknas(self) -> list[str]:
        """Vad som saknas, i klartext -- visas i panelen, inte som fel."""
        ut = []
        if not self.arkiv:
            ut.append("Arkivet är inte angivet — besluten och kartorna har ingenstans att ta vägen.")
        if not self.sokvag_socken_och_stad():
            ut.append("Socken och stad hittas inte — arbetsområdet kan bara anges som socknar på namn.")
        if not self.sokvag_lan():
            ut.append("Kommun, län och rike hittas inte — socknar med samma namn i flera län måste väljas för hand.")
        return ut


@dataclass
class Referens:
    socken_och_stad: str = ""
    lan: str = ""                   # Kommun, lan och rike (geopackage)
    traktlager: list[str] = field(default_factory=list)   # kandidater (.gdb, .gpkg)
    fastighet: list[str] = field(default_factory=list)    # fastighetsindelningens kommunfiler
    ortnamn: str = ""               # Ortnamn Nedladdning (ortnamn_se.gpkg)


def hitta(rot: str, djup: int = 4) -> Referens:
    """Leta upp referenslagren i `rot` pa namn. Tomt for det som inte finns."""
    ut = Referens()
    if not rot or not os.path.isdir(rot):
        return ut
    bas = rot.rstrip("\\/").count(os.sep)
    for mapp, undermappar, filer in os.walk(rot):
        if mapp.count(os.sep) - bas >= djup:
            undermappar[:] = []
        # En filgeodatabas ar en mapp; titta inte in i den.
        for u in list(undermappar):
            if u.lower().endswith(".gdb"):
                if "trakt" in u.lower():
                    ut.traktlager.append(os.path.join(mapp, u))
                undermappar.remove(u)
        for f in filer:
            fl = f.lower()
            p = os.path.join(mapp, f)
            if fl == "sockenstad.gpkg" and not ut.socken_och_stad:
                ut.socken_och_stad = p
            elif not ut.lan and _ar_kommunfil(f, mapp):
                ut.lan = p                        # Kommun, lan och rike (Lantmateriet)
            elif _ar_fastighetsfil(f):
                ut.fastighet.append(p)
            elif fl == "ortnamn_se.gpkg" and not ut.ortnamn:
                ut.ortnamn = p
            elif "trakt" in fl and fl.endswith(".gpkg"):
                ut.traktlager.append(p)
    return ut


def las() -> Installningar:
    from qgis.PyQt.QtCore import QSettings
    s = QSettings()
    i = Installningar()
    for f in fields(Installningar):
        v = s.value(PREFIX + f.name, None, type=str)
        if v:
            setattr(i, f.name, v)
    return i


def spara(i: Installningar) -> None:
    from qgis.PyQt.QtCore import QSettings
    s = QSettings()
    for f in fields(Installningar):
        s.setValue(PREFIX + f.name, getattr(i, f.name) or "")



