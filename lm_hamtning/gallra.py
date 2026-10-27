"""Gallringens forsta tva lager och traktfiltret (avsnitt 6). Inget granssnitt.

For varje socken:

1. **Sok hela socknen** i bada arkiven, en gang (avsnitt 3). Allt skrivs
   till registret.
2. **Lager 1, metadatafilter.** REG-akter med `kart=N` har ingen karta och
   gallras utan vidare -- 80 av 166 i Haggenas. Gratis: det star i sokningen.
3. **Metadata** for resten, ett anrop per akt, cachat. Ger sidregistret och
   trakterna: REG-sokningen har inga trakter alls.
4. **Lager 2, sidregistret.** Akter utan kartsida gallras.
5. **Traktfiltret**, om trakter ar valda:
   * REG: fastigheternas ursprungliga och gallande traktnamn (UTRA, GTRA).
   * LMS: huvudbyn (LSB).
   * LMS: byarna akten beror (RBY), via en RBY-sokning per trakt. Den
     sokningen matchar bynamnet i HELA LANDET (undersokning/AVSNITT4.md),
     sa traffarna gallras forst pa lan -- ur beteckningen, gratis -- och
     sedan pa RBY-postens socken, som kraver metadata.
   Akter som inte sager nagot om trakt behalls med skalet `socken`: det ar
   den vag avsnitt 5 anvisar for arkivposter utan motsvarighet.
6. **Kastade akter** -- senaste beslutet `kasta` -- visas aldrig igen.
7. **Åtgärd**, om bara de prioriterade ska med (prioritet.py): laga skifte,
   storskifte, avvittring, skattläggning (användaren 2026-09-29). Åtgärden
   står i sökningen, så de andra gallras före metadatan -- utan anrop.
   En akt utan åtgärd i sökningen behålls.

Varje akt far med sig *varfor* den ar med (`Skal`): grund, trakt, namnet i
akten, och om matchningen var exakt eller normaliserad.

Beslut 2026-09-29 (avsnitt 14): **osakra traffar visas gula** i
kontaktkartan. Osaker ar en akt som bara ar med genom osakra skal:
normaliserade namn, en by i RBY-listan, eller en trakt som arkivet har
sorterat under en grannsocken (`Kandidat.osaker`).

**Sockengranserna har andrats.** Marby och Sunne gjordes om under tidigt
1900-tal: aldre kartor over Vällviken ligger i Sunne, fast Vällviken ligger
i Marby pa dagens karta, och en sokning pa Marby och Vällviken gav inga
kartor (anvandaren 2026-09-29). Urvalet letar darfor upp trakterna ocksa i
grannsocknarna, utom dar grannen har ett eget stalle med samma namn
(`urval._matcha`). De soks har som `lanade`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import namn as _namn
from .prioritet import PRIORITERADE, vald
from .tjanst import REG, TjanstFel, las_lms_beteckning, samma_socken

FASTIGHET = "fastighet"     # REG: UTRA/GTRA
HUVUDBY = "huvudby"         # LMS: LSB
RBY = "rby"                 # LMS: byarna akten beror
SOCKEN = "socken"           # akten sager inget om trakt

INGEN_KARTA = "ingen karta (kart=N)"
INGA_KARTSIDOR = "inga kartsidor"
ANNAN_TRAKT = "annan trakt"
KASTAD = "kastad"
METADATA_FEL = "metadata kunde inte hämtas"
ANNAN_ATGARD = "annan åtgärd"
ANNAT_AR = "annat år"           # känt år utanför intervallet (från, till)


def inom_ar(ar, intervall) -> bool:
    """Ligger aktens år i intervallet (från, till), där en gräns kan vara None? Ett okänt
    år (None) räknas som inom: hellre en akt för mycket i kontaktkartan än en förlorad
    (användaren 2026-10-26: "tror årtal ska vara något slags intervall, inte exakt")."""
    if not intervall or ar is None:
        return True
    fran, till = intervall
    return (fran is None or ar >= fran) and (till is None or ar <= till)


@dataclass
class Skal:
    grund: str
    trakt: str              # vokabularens namn; tomt for SOCKEN
    i_akten: str            # namnet som det star i akten
    grad: str               # exakt | normaliserad; tomt for SOCKEN
    via_socken: str = ""    # trakten ligger har, men arkivet har den i
                            # grannsocknen (Vällviken: Marby -> LMS Sunne)

    @property
    def osakert(self) -> bool:
        return (self.grad == _namn.NORMALISERAD or self.grund == RBY
                or bool(self.via_socken))


@dataclass
class Kandidat:
    akt: object             # tjanst.Akt
    socken: str
    skal: list[Skal] = field(default_factory=list)
    utgallrad: str | None = None
    fel: str = ""

    @property
    def kvar(self) -> bool:
        return self.utgallrad is None

    @property
    def bara_rby(self) -> bool:
        """Med bara for att en by i RBY-listan heter som trakten."""
        m = [s for s in self.skal if s.grund != SOCKEN]
        return bool(m) and all(s.grund == RBY for s in m)

    @property
    def osaker(self) -> bool:
        """Visas gul i kontaktkartan (beslut 2026-09-29): akten ar bara med
        genom osakra skal -- normaliserade namn, en RBY-by, eller en trakt som
        arkivet har i en grannsocken."""
        m = [s for s in self.skal if s.grund != SOCKEN]
        return bool(m) and all(s.osakert for s in m)


@dataclass
class Resultat:
    kandidater: list[Kandidat] = field(default_factory=list)
    # Sokningar som misslyckades. En socken eller trakt som tjansten inte
    # svarar for far inte stoppa resten -- den redovisas har.
    fel: list[str] = field(default_factory=list)

    @property
    def kvar(self) -> list[Kandidat]:
        return [k for k in self.kandidater if k.kvar]

    def antal(self) -> dict[str, int]:
        """Hur manga som gallrats i varje lager, och hur manga som ar kvar."""
        ut: dict[str, int] = {"sökta": len(self.kandidater)}
        for k in self.kandidater:
            nyckel = k.utgallrad or "kvar"
            ut[nyckel] = ut.get(nyckel, 0) + 1
        return ut


def _skal_reg(akt, trakter: list[str], socken: str) -> list[Skal]:
    ut = []
    for f in akt.fastigheter:
        for namn_i_akten in dict.fromkeys((f.ursprunglig_trakt, f.gallande_trakt)):
            for t in trakter:
                g = _namn.grad(namn_i_akten, t, socken)
                if g:
                    ut.append(Skal(FASTIGHET, t, namn_i_akten, g))
    return _unika(ut)


def _skal_lsb(akt, trakter: list[str], socken: str) -> list[Skal]:
    # En akt i en annan socken ar med for sina RBY-byar, inte for sin
    # huvudby: Nygård i Lit ar inte Nygård i Haggenas.
    if not samma_socken(akt.socken, socken):
        return []
    ut = []
    for namn_i_akten in akt.trakter:
        for t in trakter:
            g = _namn.grad(namn_i_akten, t, socken)
            if g:
                ut.append(Skal(HUVUDBY, t, namn_i_akten, g))
    return _unika(ut)


def _skal_rby(akt, trakter: list[str], socken: str) -> list[Skal]:
    ut = []
    for by in akt.byar:
        if not samma_socken(by.socken, socken):
            continue
        for t in trakter:
            g = _namn.grad(by.trakt, t, socken)
            if g:
                ut.append(Skal(RBY, t, by.namn, g))
    return _unika(ut)


def _unika(skal: list[Skal]) -> list[Skal]:
    sett, ut = set(), []
    for s in skal:
        k = (s.grund, s.trakt, s.i_akten)
        if k not in sett:
            sett.add(k)
            ut.append(s)
    return ut


def _bedom(klient, register, k: Kandidat, valda, socken: str, kastade,
           via: str = "", atgarder=None, ar=None) -> None:
    """Lager 1, metadata, lager 2 och traktfiltret for en akt. Andrar `k`."""
    a = k.akt
    if a.nyckel in kastade:
        k.utgallrad = KASTAD
        return
    if a.arkiv == REG and a.har_karta is False:
        k.utgallrad = INGEN_KARTA
        return
    if atgarder is not None and not vald(a.atgarder, atgarder):
        k.utgallrad = ANNAN_ATGARD
        return
    if not inom_ar(a.ar, ar):                 # före metadatan: kostar inga anrop
        k.utgallrad = ANNAT_AR
        return
    try:
        full = klient.metadata(a)
    except TjanstFel as e:
        k.utgallrad, k.fel = METADATA_FEL, str(e).splitlines()[0]
        return
    register.spara_akter([full])
    k.akt = a = full
    if not a.antal_kartsidor:
        k.utgallrad = INGA_KARTSIDOR
        return
    if not valda:
        k.skal = [Skal(SOCKEN, "", "", "")]
        return
    if a.arkiv == REG:
        k.skal = _skal_reg(a, valda, socken)
        vet_trakt = bool(a.fastigheter)
    else:
        k.skal = _skal_lsb(a, valda, socken) + _skal_rby(a, valda, socken)
        # En akt i en annan socken ar bara med for sina RBY-byar.
        vet_trakt = bool(a.trakter) or bool(a.byar)
    for s in k.skal:
        s.via_socken = via
    if not k.skal:
        if vet_trakt:
            k.utgallrad = ANNAN_TRAKT
        else:
            k.skal = [Skal(SOCKEN, "", "", "")]


def gallra(klient, register, socknar, trakter: dict[str, list[str]] | None = None,
           lanade: list | None = None, framsteg=None, avbruten=None,
           bara_prioriterade: bool = False, atgarder=None,
           beteckningar: list[str] | None = None, ar=None) -> Resultat:
    """Gallra socknarnas akter. `socknar` ar tjanst.Socken.

    `ar` ar ett arintervall (fran, till), dar en grans kan vara None; akter med
    kant ar utanfor gallras som ANNAT_AR fore metadatan, akter utan ar behalls.

    `trakter` ar valda traktnamn per socken, med vokabularens namn:
    `{"Häggenås": ["Gungård", "Högen"]}`. None eller en socken som saknas =
    ingen traktfiltrering i den socknen.

    `lanade` ar trakter som arkivet har i en grannsocken
    (`urval.TraktIOmrade` med `via_socken`; se `urval.for_gallra`). De soks
    RIKTAT -- REG pa trakten, LMS pa traktens nummer -- inte som hela
    grannsocknen: Vällviken skulle annars kosta metadata for hela Sunne.

    `framsteg(text, andel)` och `avbruten() -> bool` ar valfria. Ett avbrott
    lamnar det som hunnits i registret och cachen; nasta korning fortsatter
    darifran utan att hamta nagot tva ganger.
    """
    # `atgarder`: åtgärdstyperna som ska med (prioritet.TYPER), None = alla;
    # bara_prioriterade är det äldre valet, de fyra prioriterade
    if atgarder is None and bara_prioriterade:
        atgarder = PRIORITERADE
    trakter = trakter or {}
    kastade = register.kastade()
    res = Resultat()
    sedda: set[str] = set()

    def meddela(text, andel):
        if framsteg:
            framsteg(text, andel)

    def stopp():
        return avbruten is not None and avbruten()

    for s in socknar:
        valda = trakter.get(s.namn)
        meddela(f"{s.namn}: söker i arkiven", 0.0)
        try:
            akter = klient.sok_socken(s)
        except TjanstFel as e:
            res.fel.append(f"{s.namn}: {str(e).splitlines()[0]}")
            continue
        if beteckningar:
            # sökning på aktbeteckning (2026-10-26): socknens sökning som vanligt (cachad),
            # bara de begärda akterna vidare -- tjänsten har inget pålitligt beteckningsfilter
            vill = {b.strip().casefold() for b in beteckningar}
            akter = [a for a in akter if a.beteckning.casefold() in vill]
        register.spara_akter(akter)
        kand = {a.nyckel: Kandidat(a, s.namn) for a in akter}

        # RBY: akter i andra socknar som namner en vald trakt bland sina byar.
        rby_hamtade: list = []
        if valda and s.i_lms:
            for t in valda:
                tr = s.trakt(t)
                if tr is None or not tr.lms_nummer:
                    continue
                try:
                    traffar = klient.sok_lms(s, tr.lms_nummer, rby=True)
                except TjanstFel as e:
                    res.fel.append(f"{s.namn}, {t} (RBY): {str(e).splitlines()[0]}")
                    continue
                for a in traffar:
                    b = las_lms_beteckning(a.beteckning)
                    if b is None or b.lan != s.lan.lms_bokstav:
                        continue        # annat lan: en annan by med samma namn
                    if a.nyckel not in kand:
                        kand[a.nyckel] = Kandidat(a, s.namn)
                        rby_hamtade.append(a)
            register.spara_akter(rby_hamtade)

        lista = [k for k in kand.values() if k.akt.nyckel not in sedda]
        for i, k in enumerate(lista):
            if stopp():
                return res
            meddela(f"{s.namn}: {k.akt.beteckning}", i / max(len(lista), 1))
            _bedom(klient, register, k, valda, s.namn, kastade,
                   atgarder=atgarder, ar=ar)
            sedda.add(k.akt.nyckel)
        res.kandidater += lista

    for t in lanade or []:
        n, tr = t.arkivsocken, t.arkivsocken.trakt(t.trakt)
        if tr is None:
            continue
        meddela(f"{t.via_socken}: {t.trakt} i {n.namn}", 0.0)
        akter = []
        try:
            if tr.i_reg and n.reg_kod:
                akter += klient.sok_reg(n, trakt=t.trakt)
            if tr.i_lms and tr.lms_nummer:
                akter += klient.sok_lms(n, tr.lms_nummer)
        except TjanstFel as e:
            res.fel.append(f"{t.trakt} i {n.namn}: {str(e).splitlines()[0]}")
            continue
        register.spara_akter(akter)
        for a in akter:
            if stopp():
                return res
            if a.nyckel in sedda:
                continue
            k = Kandidat(a, t.via_socken)
            _bedom(klient, register, k, [t.trakt], n.namn, kastade,
                   via=t.via_socken, atgarder=atgarder, ar=ar)
            sedda.add(a.nyckel)
            res.kandidater.append(k)
    meddela("klart", 1.0)
    return res


# ------------------------------------------------------------------ listan
CSV_RUBRIKER = ("arkiv", "beteckning", "år", "åtgärder", "socken", "trakter", "kartsidor", "sidor",
                "kvar", "varför inte", "osäker", "länk till akten (PDF hos Lantmäteriet)",
                "länk till akten (Lantmäteriets webbsida)")


def csv_rader(kandidater) -> list[list[str]]:
    """Gallringens akter som rader till en CSV-fil (användaren 2026-10-26: "många vill
    bara ha inventeringen"). Länkarna är aktens PDF i Lantmäteriets bildtjänst och
    akten i webbsidans visare (tjanst.url_webb, 2026-10-27)."""
    from .tjanst import url_pdf, url_webb
    ut = []
    for k in kandidater:
        a = k.akt
        ut.append([a.arkiv, a.beteckning, str(a.ar or ""), "; ".join(a.atgarder or []), a.socken or "",
                   "; ".join(a.trakter or []), str(getattr(a, "antal_kartsidor", None) or ""),
                   str(a.antal_sidor or ""), "ja" if k.kvar else "nej", k.utgallrad or "",
                   "ja" if k.osaker else "", url_pdf(a), url_webb(a)])
    return ut


def skriv_csv(fil: str, kandidater) -> int:
    """CSV med semikolon och BOM, så att Excel på svenska öppnar den rätt. -> antal rader."""
    import csv
    rader = csv_rader(kandidater)
    with open(fil, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(CSV_RUBRIKER)
        w.writerows(rader)
    return len(rader)
