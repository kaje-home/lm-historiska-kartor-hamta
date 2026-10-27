"""Ett jobb i bakgrunden, sa att QGIS inte laser sig under natanropen.

Gallringen av Haggenas ar omkring 110 anrop med paus -- ett par minuter.
Det far inte ske i granssnittstraden.

**Jobbet far inte dela sqlite-anslutning eller klient med granssnittet.**
sqlite3 vagrar anvandas i en annan trad an den som oppnade anslutningen, och
klientens paus ar inte tradsaker. Jobbet oppnar darfor sitt eget register och
sin egen klient (se dialog.py); cachen pa disk delas, och det ar poangen.
"""
from __future__ import annotations

import traceback

from qgis.PyQt.QtCore import pyqtSignal
from qgis.core import QgsApplication, QgsTask


class Jobb(QgsTask):
    """Kor `funktion(framsteg, avbruten)` i en egen trad.

    `framsteg(text, andel)` far anropas fran jobbet; `avbruten()` ar sant nar
    anvandaren avbrutit. Resultatet kommer med `klart`, felet med `fel` --
    bada i granssnittstraden.
    """

    klart = pyqtSignal(object)
    fel = pyqtSignal(str)
    meddelande = pyqtSignal(str, float)

    def __init__(self, namn: str, funktion):
        super().__init__(namn, QgsTask.Flag.CanCancel)
        self.funktion = funktion
        self.resultat = None
        self.felet = ""

    def run(self) -> bool:
        def framsteg(text, andel):
            self.setProgress(100 * max(0.0, min(1.0, andel)))
            self.meddelande.emit(text, andel)
        try:
            self.resultat = self.funktion(framsteg, self.isCanceled)
            return not self.isCanceled()
        except Exception as e:          # visas for anvandaren, inte bara i loggen
            self.felet = f"{e}\n\n{traceback.format_exc(limit=4)}"
            return False

    def finished(self, lyckades: bool) -> None:
        if lyckades:
            self.klart.emit(self.resultat)
        elif self.felet:
            self.fel.emit(self.felet)
        else:
            self.fel.emit("Avbrutet.")

    def starta(self) -> "Jobb":
        QgsApplication.taskManager().addTask(self)
        return self
