"""Namnnormalisering: arkivets traktnamn mot lagrets (avsnitt 5).

Reglerna, i den ordning specen anger dem:

1. versaler
2. sockenprefix bort: `HÄGGENÅS-HÖGEN`, `HÄGGENÅS PRÄSTBORD` -> `HÖGEN`,
   `PRÄSTBORD` -- samma sak som REG-akternas UTRA/GTRA
3. tillagg bort, efter kommatecken och efter ` MED `:
   `Munkflohögen,västra`, `Österåsen med halasjön` -> `MUNKFLOHÖGEN`, `ÖSTERÅSEN`
4. vanliga stavningsvarianter likstalls: -arne/-arna, ou/o, å/o i andelsen:
   Högarne/Högarna, Kougsta/Kogsta

Dessutom, fore regel 1: hemmansnumret bort (`Andersgård nr 1`), eftersom LMS
skriver det och ingen annan gor det.

**En matchning som kraver mer an versaler ar `normaliserad`**, och visas som
sadan (avsnitt 5). Den ar sannolikt ratt men inte sakert: `Munkflohögen,västra`
och `Munkflohögen,östra` blir bada `MUNKFLOHÖGEN`, vilket ar ratt som lage men
inte som grans.

**Bestamd form likstalls inte i allmanhet.** En regel som tar bort -et och -en
tar ocksa `Högen` till `HÖG` och `Storhögen` till `STORHÖG` -- for mycket for
att vara tyst. Ett undantag: `PRÄSTBORDET` = `PRÄSTBORD`. Arkivet skriver
bestamd form, Jamtlandslagret obestamd, och prastbordet finns i varje socken.

**Sockenprefixet kan sta i genitiv**: `LITS PRÄSTBORD`, `BERGS PRÄSTBORD`
(provat mot Jamtlandslagret 2026-09-29).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .tjanst import utan_nummer

EXAKT = "exakt"
NORMALISERAD = "normaliserad"

_VOKAL = "AEIOUYÅÄÖ"


def _utan_socken(n: str, socken: str | None) -> str:
    if not socken:
        return n
    s = socken.upper()
    for prefix in (s + "-", s + " ", s + "S-", s + "S "):
        if n.startswith(prefix) and len(n) > len(prefix):
            return n[len(prefix):].strip()
    return n


def _utan_tillagg(n: str) -> str:
    n = n.split(",", 1)[0]
    n = re.split(r"\s+MED\s+", n, maxsplit=1)[0]
    return n.strip()


def _stavning(n: str) -> str:
    n = re.sub(r"PRÄSTBORDET$", "PRÄSTBORD", n)
    n = re.sub(r"ARNE$", "ARNA", n)
    n = n.replace("OU", "O")
    # Å/O i andelsen: sista vokalen, om den ar Å.
    n = re.sub(rf"Å(?=[^{_VOKAL}]*$)", "O", n)
    return n


def nyckel(namn: str, socken: str | None = None) -> str:
    """Den fullt normaliserade formen. Tva namn med samma nyckel matchar."""
    n = utan_nummer(namn).upper().strip()
    n = re.sub(r"\s+", " ", n)
    n = _utan_socken(n, socken)
    n = _utan_tillagg(n)
    return _stavning(n)


def grad(a: str, b: str, socken: str | None = None) -> str | None:
    """`exakt`, `normaliserad` eller None."""
    if utan_nummer(a).casefold().strip() == utan_nummer(b).casefold().strip():
        return EXAKT
    if nyckel(a, socken) == nyckel(b, socken):
        return NORMALISERAD
    return None


@dataclass
class Par:
    arkiv: str
    lager: str
    grad: str


@dataclass
class Matchning:
    par: list[Par] = field(default_factory=list)
    bara_arkiv: list[str] = field(default_factory=list)   # nas via socknen
    bara_lager: list[str] = field(default_factory=list)   # finns inte i arkivet

    def antal(self, *grader: str) -> int:
        """Hur manga arkivnamn som fick en motsvarighet av nagon av graderna."""
        return len({p.arkiv for p in self.par if p.grad in grader})


def matcha(arkivnamn: list[str], lagernamn: list[str],
           socken: str | None = None) -> Matchning:
    """Varje arkivnamn mot lagrets namn, i bada riktningarna (avsnitt 5).

    Ett exakt par gar fore ett normaliserat: finns `Kogsta` i bada ar det
    paret, och `Kougsta` far sitt eget, normaliserade. Flera arkivnamn kan
    fa samma lagernamn -- `Munkflohögen,västra` och `,östra` -- och ett
    arkivnamn kan fa flera om lagret har samma namn pa flera stallen.
    """
    m = Matchning()
    exakt = {}
    for l in lagernamn:
        exakt.setdefault(utan_nummer(l).casefold().strip(), []).append(l)
    norm = {}
    for l in lagernamn:
        norm.setdefault(nyckel(l, socken), []).append(l)

    anvanda: set[str] = set()
    for a in arkivnamn:
        traff = exakt.get(utan_nummer(a).casefold().strip())
        g = EXAKT
        if not traff:
            traff, g = norm.get(nyckel(a, socken)), NORMALISERAD
        if not traff:
            m.bara_arkiv.append(a)
            continue
        for l in dict.fromkeys(traff):
            m.par.append(Par(a, l, g))
            anvanda.add(l)
    m.bara_lager = [l for l in dict.fromkeys(lagernamn) if l not in anvanda]
    return m
