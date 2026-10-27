"""Textakten (användaren 2026-10-19: "i vissa fall kan man även vilja ha textakten
för kartan, borde va ett val", "1 val per akt"; filnamnen som i dag "med korrekt
aktbeteckning för att kunna referera till kartan i tex en rapport").

Aktens textsidor -- protokoll, beskrivning, beslut -- ur aktens PDF (samma fil som
gallringens miniatyrer görs ur, tjanst.Klient.akt_pdf), som en PDF bredvid kartorna:
`kartor/<socken>/<åtgärd>_<år>_<beteckning>_<socken>_textakt.pdf`, namngiven som
kartsidorna (nedladdning.filnamn). Sidorna kopieras som de är, inget skannas om.
Utan pypdf sparas hela aktens PDF under samma namn.
"""
from __future__ import annotations

import os
import shutil

from .nedladdning import _rent

MALL = "{atgard}_{ar}_{beteckning}_{socken}_textakt.pdf"


def relativ_sokvag(akt) -> str:
    """`akt` är en registerrad (eller ordbok med samma fält)."""
    atgard = (akt["atgard"] or "").split(";")[0]
    namn = MALL.format(atgard=_rent(atgard), ar=akt["ar"] or "u.å.",
                       beteckning=_rent(akt["beteckning"]), socken=_rent(akt["socken"] or ""))
    return "/".join(("kartor", _rent(akt["socken"] or ""), namn))


def sokvag(arkiv: str, akt) -> str:
    return os.path.join(arkiv, *relativ_sokvag(akt).split("/"))


def textsidor(register, nyckel: str) -> list[int]:
    """Aktens sidor som inte är kartor (löpnummer, 1-baserade), ur registrets sidregister.
    Tom lista när sidregistret inte är hämtat eller akten bara har kartor."""
    return [int(s["lopnr"]) for s in register.sidor(nyckel) if not s["karta"]]


def tjanstens_akt(akt):
    """En tjanst.Akt ur registerraden: det akt_pdf behöver (arkiv, bas, ktun, beteckning)."""
    from .tjanst import Akt
    return Akt(arkiv=akt["arkiv"], bas=akt["bas"], ktun=akt["ktun"], beteckning=akt["beteckning"],
               atgarder=[], atgardskoder=[], ar=akt["ar"], datum=None, antal_sidor=None, har_karta=None)


def sidor_ur_pdf(pdf: str, sidor: list[int], mal: str) -> int:
    """Sidorna (1-baserade) ur `pdf` till `mal`. -> antal sidor i `mal`. Utan pypdf
    kopieras hela filen."""
    os.makedirs(os.path.dirname(os.path.abspath(mal)), exist_ok=True)
    tmp = f"{mal}.{os.getpid()}.delvis"
    try:
        try:
            from pypdf import PdfReader, PdfWriter
        except ImportError:
            shutil.copyfile(pdf, tmp)
            os.replace(tmp, mal)
            return 0
        las = PdfReader(pdf)
        skriv = PdfWriter()
        for n in sidor:
            if 1 <= n <= len(las.pages):
                skriv.add_page(las.pages[n - 1])
        with open(tmp, "wb") as fh:
            skriv.write(fh)
        os.replace(tmp, mal)
        return len(skriv.pages)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def spara(klient, register, arkiv: str, nyckel: str) -> tuple[str, int]:
    """Aktens textsidor i arkivet. -> (sökväg, antal sidor). RuntimeError när
    akten saknas i registret eller inte har några textsidor."""
    akt = register.akt(nyckel)
    if akt is None:
        raise RuntimeError("Akten finns inte i registret.")
    sidor = textsidor(register, nyckel)
    if not sidor:
        raise RuntimeError("Akten har inga textsidor i sidregistret (bara kartor, "
                           "eller sidregistret är inte hämtat).")
    pdf = klient.akt_pdf(tjanstens_akt(akt))
    mal = sokvag(arkiv, akt)
    return mal, sidor_ur_pdf(pdf, sidor, mal)
