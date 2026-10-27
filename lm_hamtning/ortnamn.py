"""Traktlagen ur ortnamnsregistret i Faltunderlagets arkiv.

Beslut 2026-09-28
-----------------
Utan eget traktlager (avsnitt 5, traktlagrets steg 3) tas trakternas lage ur
Ortnamn Nedladdning -- hela Sverige i en fil, `ortnamn_se.gpkg`, som
Faltunderlaget redan hamtat till sitt arkiv. Inte ur Ortnamn Direkt: den
behovs da inte for detta, och registret ar lokalt, avgiftsfritt och utan
juridisk provning.

Provat mot Haggenas: 24 av arkivets 40 trakter finns som namntypen `TRAKTTX`
(fastighetsnamn) med exakt samma namn -- lika manga som det egna traktlagret
for Jamtland. **Efter namnnormaliseringen 33** (namn.py), fler an specens
krav pa traktlagret (minst 31). Registret har dagens namn med sockenprefix,
som REG:s GTRA: `Häggenås-högen`, `Häggenås-svedje`. De sju som blir kvar
ar trakter som inte langre finns, plus `Flakamarken` (bara som terrangnamn).

**Matcha mot `TRAKTTX` forst**, och mot `BEBTX` bara for det som blir kvar.
Annars vinner ett exakt bebyggelsenamn (`Högen`) over ett normaliserat
fastighetsnamn (`Häggenås-högen`), och det ar fastighetsnamnet som ar
trakten. I Haggenas tillfor `BEBTX` inget.

**Lage, inte yta.** Ett namn ar en punkt dar kartografen satte texten -- ofta
mitt i inagorna, men inte alltid. Det duger for att valja trakter inom ett
arbetsomrade och for grovplacering, inte for att skara.

**Pluginet skriver aldrig i Faltunderlagets arkiv** (avsnitt 2). Registret
oppnas darfor skrivskyddat pa SQLite-niva, inte bara av god vilja.

Sokvagen till arkivet tas ur Faltunderlagets installning om den finns,
annars ur pluginets egen (avsnitt 5).
"""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from urllib.request import pathname2url

FILNAMN = "ortnamn_se.gpkg"

TRAKT = "TRAKTTX"           # fastighetsnamn -- det som motsvarar en trakt
BEBYGGELSE = "BEBTX"        # bebyggelse; ibland det enda som finns kvar
NAMNTYPER = (TRAKT, BEBYGGELSE)


@dataclass
class Namnlage:
    namn: str
    namntyp: str            # TRAKTTX eller BEBTX
    x: int                  # SWEREF 99 TM
    y: int
    socken: str
    sockenkod: str          # Socken och stads kod, "2537"

    @property
    def som_trakt(self) -> bool:
        return self.namntyp == TRAKT


def registret(arkiv: str | None) -> str | None:
    """Sokvagen till ortnamnsregistret, eller None om det inte finns."""
    if not arkiv:
        return None
    p = os.path.join(arkiv, FILNAMN)
    return p if os.path.isfile(p) else None


def _oppna(sokvag: str) -> sqlite3.Connection:
    uri = "file:" + pathname2url(os.path.abspath(sokvag)) + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


def namn_overallt(register: str, namn: str,
                  namntyper: tuple[str, ...] = NAMNTYPER) -> list[Namnlage]:
    """Alla ställen i landet som heter `namn` (by, gård eller trakt), oavsett socken och
    län -- för sökning på namn (användaren 2026-10-26: "de flesta hembygdsforskare börjar
    med ett namn"). Stora och små bokstäver spelar ingen roll."""
    k = _oppna(register)
    try:
        rader = k.execute(
            f"SELECT ortnamn, detaljtyp, ekoordinat, nkoordinat, sockenstadnamn, "
            f"sockenstadkod FROM ortnamn WHERE ortnamn = ? COLLATE NOCASE "
            f"AND detaljtyp IN ({','.join('?' * len(namntyper))}) "
            f"ORDER BY sockenstadnamn, detaljtyp", (namn.strip(), *namntyper)).fetchall()
    finally:
        k.close()
    return [Namnlage(r[0], r[1], r[2], r[3], r[4], r[5] or "") for r in rader]


def namn_i_socken(register: str, socken: str, lanskod: str,
                  namntyper: tuple[str, ...] = NAMNTYPER) -> list[Namnlage]:
    """Namn av `namntyper` i socknen. `lanskod` ar REG:s lansnummer, "23".

    Socknen anges med namn, som i vokabularen: registret har Socken och
    stads namn och kod, och namnen stammer for de socknar som provats. Lanet
    behovs eftersom sockennamn upprepas mellan lan.
    """
    k = _oppna(register)
    try:
        rader = k.execute(
            f"SELECT ortnamn, detaljtyp, ekoordinat, nkoordinat, sockenstadnamn, "
            f"sockenstadkod FROM ortnamn WHERE sockenstadnamn = ? AND lanskod = ? "
            f"AND detaljtyp IN ({','.join('?' * len(namntyper))}) "
            f"ORDER BY ortnamn", (socken, lanskod, *namntyper)).fetchall()
    finally:
        k.close()
    return [Namnlage(namn=r[0], namntyp=r[1], x=r[2], y=r[3], socken=r[4],
                     sockenkod=r[5] or "") for r in rader]
