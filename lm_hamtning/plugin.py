"""Skalet: menyn och verktygsknappen. Arbetet ligger i modulerna."""
from __future__ import annotations

# QAction ligger i QtWidgets i Qt 5 men i QtGui i Qt 6 (QGIS 4).
try:
    from qgis.PyQt.QtGui import QAction
except ImportError:
    from qgis.PyQt.QtWidgets import QAction

from . import variant  # noqa: E402

# den fristående hämtningen får en egen meny och ett eget knappnamn (variant.py)
MENY = "&Historiska kartor (hämta)" if variant.BARA_HAMTNING else "&Historiska kartor"


def _lever(w) -> bool:
    """Finns Qt-objektet bakom Python-referensen kvar?"""
    try:
        from qgis.PyQt import sip
        return not sip.isdeleted(w)
    except Exception:                                    # noqa: BLE001
        try:
            w.objectName()
            return True
        except RuntimeError:
            return False


class HistoriskaKartor:
    def __init__(self, iface):
        self.iface = iface
        self.atgarder: list = []
        self.dialog = None
        self.rektifiera_panel = None
        self.kartnamn = None

    def initGui(self):
        from . import diagnos
        diagnos.starta()                    # logg över tysta QGIS-avslut (2026-10-08)
        diagnos.notera("pluginet laddat")
        gallra = QAction("Sök och hämta…" if variant.BARA_HAMTNING else "Gallra…", self.iface.mainWindow())
        gallra.setToolTip("Historiska kartor: sök akter för ett arbetsområde, "
                          "gallra dem, granska kartorna i kontaktkartan och ladda ner de behållna.")
        gallra.triggered.connect(self.gallra)
        rekt = None
        if not variant.BARA_HAMTNING:
            rekt = QAction("Rektifiera…", self.iface.mainWindow())
            rekt.setToolTip("Historiska kartor: arbetslistan över nedladdade kartor, "
                            "punktverktyget, automatiken och registreringen av rektifieringar.")
            rekt.triggered.connect(self.rektifiera)
        inst = QAction("Inställningar…", self.iface.mainWindow())
        inst.triggered.connect(self.installningar)
        kom = QAction("Kom igång…", self.iface.mainWindow())
        kom.setToolTip("Vad som finns och vad som saknas, med en knapp för varje sak.")
        kom.triggered.connect(self.kom_igang)
        for a in (kom, gallra, rekt, inst):
            if a is None:
                continue
            self.iface.addPluginToMenu(MENY, a)
            self.atgarder.append(a)
        self.iface.addToolBarIcon(gallra)
        if not variant.BARA_HAMTNING:
            from .kartnamn import Kartnamn
            self.kartnamn = Kartnamn()      # beteckningen mitt på varje tänd karta

    def kom_igang(self):
        from . import installningar
        from .komigang import KomIgangDialog
        d = KomIgangDialog(installningar.las(), self.iface.mainWindow())
        d.exec()
        if self.dialog:
            self.dialog.inst = installningar.las()
            self.dialog._uppdatera_saknas()

    def gallra(self):
        from . import installningar
        from .dialog import GallraDialog
        if not installningar.las().arkiv:
            self.kom_igang()                # första gången: det som saknas, med knappar
            if not installningar.las().arkiv:
                return
        # Samma fonster hela sessionen: urvalet och kontaktkartan ska finnas
        # kvar om man stanger och oppnar igen.
        if self.dialog is None:
            self.dialog = GallraDialog(self.iface, self.iface.mainWindow())
        self.dialog.show()
        self.dialog.raise_()

    def rektifiera(self):
        # i en egen modul: hämtningen för sig byggs utan den (variant.py)
        from .rektifiera_start import oppna
        oppna(self)

    def installningar(self):
        from .dialog import InstallningarDialog
        from . import installningar
        i = installningar.las()
        if InstallningarDialog(i, self.iface.mainWindow()).exec() and self.dialog:
            self.dialog.inst = installningar.las()
            self.dialog._uppdatera_saknas()

    def unload(self):
        if self.kartnamn is not None:
            self.kartnamn.stang()
            self.kartnamn = None
        for a in self.atgarder:
            self.iface.removePluginMenu(MENY, a)
            self.iface.removeToolBarIcon(a)
            a.deleteLater()
        self.atgarder = []
        # En panel som redan är raderad (stängd av användaren, eller av QGIS vid
        # projektbyte) får inte röras: removeDockWidget på ett dött C++-objekt
        # kraschade QGIS vid omladdning 2026-10-03 och 2026-10-05
        if self.rektifiera_panel is not None:
            if _lever(self.rektifiera_panel):
                try:
                    # sökytans band ligger i kartvyn och blev annars herrelöst
                    # vid omladdning (2026-10-08)
                    self.rektifiera_panel._satt_sokyta(None)
                except Exception:                        # noqa: BLE001
                    pass
                try:
                    self.iface.removeDockWidget(self.rektifiera_panel)
                    self.rektifiera_panel.deleteLater()
                except RuntimeError:
                    pass
            try:
                self.rektifiera_register.stang()
            except Exception:                            # noqa: BLE001
                pass
            self.rektifiera_panel = None
        # Kvarblivna paneler från tidigare omladdningar (en andra Rektifiera bakom
        # den första, användaren 2026-10-08): alla pluginets dockor tas bort
        try:
            from qgis.PyQt.QtWidgets import QDockWidget
            for w in self.iface.mainWindow().findChildren(QDockWidget):
                if type(w).__name__ in ("RektifieraPanel", "PunktPanel") and \
                        type(w).__module__.startswith(__name__.split(".")[0]) and _lever(w):
                    try:
                        self.iface.removeDockWidget(w)
                        w.deleteLater()
                    except RuntimeError:
                        pass
        except Exception:                                # noqa: BLE001
            pass
        if self.dialog is not None:
            if _lever(self.dialog):
                try:
                    if self.dialog.panel is not None and _lever(self.dialog.panel):
                        self.dialog.panel.avbryt()
                        self.iface.removeDockWidget(self.dialog.panel)
                        self.dialog.panel.deleteLater()
                    self.dialog.close()
                    self.dialog.deleteLater()
                except RuntimeError:
                    pass
            self.dialog = None
