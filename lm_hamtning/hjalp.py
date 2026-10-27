"""Hjälp där man står (punkt 6, användaren 2026-10-02): en knapp i varje panel
öppnar rätt avsnitt i LÄS_MIG.md, i ett eget fönster som kan stå öppet
bredvid arbetet. Avsnittet hittas på rubriken; texten är hela bruksanvisningen
så att man kan läsa vidare.

Hämtningen för sig har sin egen manual (LÄS_MIG_hamtning.md, kopierad som LÄS_MIG.md
i bygget) med andra rubriker: där öppnar knapparna avsnittet Sök och hämta
(AVSNITT_HAMTNING; 2026-10-27, användaren: en fristående manual som inte blandar in
den stora).
"""
from __future__ import annotations

import os
import re

from . import variant

FIL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "LÄS_MIG.md")

# knappens avsnitt -> rubrik i LÄS_MIG (början av rubrikraden)
AVSNITT = {"komigang": "Första gången", "gallra": "Gallra", "kontaktkarta": "Kontaktkartan",
           "nedladdning": "Ladda ned", "rektifiera": "Rektifiera", "punktverktyget": "Punktverktyget",
           "automatiken": "Automatiken", "sammanfoga": "Blad med flera kartor", "filerna": "Filerna"}
AVSNITT_HAMTNING = {"komigang": "Första gången", "gallra": "Sök och hämta", "kontaktkarta": "Sök och hämta",
                    "nedladdning": "Sök och hämta"}


def las() -> str:
    try:
        with open(FIL, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return "LÄS_MIG.md saknas."


def rubrik_for(avsnitt: str) -> str:
    tabell = AVSNITT_HAMTNING if variant.BARA_HAMTNING else AVSNITT
    return tabell.get(avsnitt, avsnitt)


def avsnitt_text(avsnitt: str, text: str | None = None) -> str:
    """Avsnittet med rubriken, fram till nästa rubrik på samma eller högre nivå."""
    text = las() if text is None else text
    rubrik = rubrik_for(avsnitt)
    m = re.search(r"^(#{1,6})\s+" + re.escape(rubrik) + r".*$", text, re.MULTILINE)
    if not m:
        return ""
    niva = len(m.group(1))
    slut = re.compile(r"^#{1," + str(niva) + r"}\s", re.MULTILINE)
    n = slut.search(text, m.end())
    return text[m.start():n.start() if n else len(text)].strip()


_fonster = {}


def visa(avsnitt: str, parent=None):
    """Hjälpfönstret, ett per avsnitt, bläddrat till rubriken."""
    from qgis.PyQt.QtGui import QTextDocument
    from qgis.PyQt.QtWidgets import QDialog, QTextBrowser, QVBoxLayout
    d = _fonster.get(avsnitt)
    try:
        if d is not None and d.isVisible():
            d.raise_()
            return d
    except RuntimeError:
        d = None
    d = QDialog(parent)
    d.setWindowTitle(f"Hjälp — {rubrik_for(avsnitt)}")
    d.setWindowFlags(d.windowFlags() | __import__("qgis.PyQt.QtCore", fromlist=["Qt"]).Qt.WindowType.Window)
    lay = QVBoxLayout(d)
    tb = QTextBrowser()
    tb.setOpenExternalLinks(True)
    tb.setMarkdown(las())
    lay.addWidget(tb)
    d.resize(720, 640)
    # till rubriken: första förekomsten av rubriktexten som egen rad
    if not tb.find(rubrik_for(avsnitt), QTextDocument.FindFlag.FindCaseSensitively):
        tb.find(rubrik_for(avsnitt))
    tb.textCursor().clearSelection()
    d.show()
    _fonster[avsnitt] = d
    return d
