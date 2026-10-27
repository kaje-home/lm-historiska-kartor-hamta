"""Kom igång: vad som finns och vad som saknas, med en knapp för varje sak
(användaren 2026-10-02: ett verktyg som de flesta med lite GIS-vana ska kunna
köra ganska direkt). Första starten krävde annars att man pekade ut mappar,
laddade ner lager själv och installerade OpenCV i OSGeo4W-skalet.

`kontroller(inst)` är ren Python (provas utan QGIS); dialogen visar raderna
med grönt, gult och rött och gör det som går att göra: väljer mappar, öppnar
Geotorget, installerar OpenCV i en egen mapp som automatiken läser
(`lm_historiska_kartor/pythonbibliotek`), hämtar det som kräver kontot.

**Tonen (användaren 2026-10-27):** den publika målgruppen är 65+, inte datorvan men
mycket intresserad av kartor och har provat QGIS lite grann; den andra gruppen är
arkeologer och historiker som kan GIS. Nivån läggs på den första: varje extern
datamängd får en rad som säger vad den ger, och "Gör så här: 1) … 2) … 3)" med
knappen till rätt produktsida på Geotorget, inte till startsidan.
"""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass

from . import arkivfil, fastighet, installningar as _inst, kommuner, referens, variant

GEOTORGET = "https://geotorget.lantmateriet.se/"
KOMMUN_LAN_RIKE = kommuner.PRODUKTSIDA     # Lantmäteriets Kommun, län och rike (ersatte SCB:s län 2026-10-26)
# produktsidorna på Geotorget: knappen vid raden öppnar rätt sida
SOCKEN_OCH_STAD = "https://geotorget.lantmateriet.se/geodataprodukter/socken-stad-nedladdning-vektor"
TOPOGRAFI_10 = "https://geotorget.lantmateriet.se/geodataprodukter/topografi-10-nedladdning-vektor"
ORTNAMN = "https://geotorget.lantmateriet.se/geodataprodukter/ortnamn-nedladdning-vektor-api"
SIDOR = {"geotorget": GEOTORGET, "kommun_lan_rike": KOMMUN_LAN_RIKE, "socken_och_stad": SOCKEN_OCH_STAD,
         "topografi10": TOPOGRAFI_10, "fastighetsindelning": fastighet.PRODUKTSIDA, "ortnamn": ORTNAMN}
OPENCV_PAKET = "opencv-python-headless"
OK, VARNING, SAKNAS, INFO = "ok", "varning", "saknas", "info"
STEGET = "Sök och hämta" if variant.BARA_HAMTNING else "Gallra"     # menyvalet som använder trakterna


@dataclass
class Kontroll:
    namn: str
    status: str          # OK, VARNING, SAKNAS, INFO
    text: str
    atgard: str = ""     # "arkiv", "referensdata", "kommuner", "opencv", en nyckel i SIDOR (öppnar sidan), ""
    atgardstext: str = ""


def python_exe() -> str:
    return os.path.join(sys.prefix, "python.exe") if os.name == "nt" else sys.executable


def pythonbibliotek() -> str:
    """Mappen automatiken lägger till i PYTHONPATH (inställningen)."""
    try:
        from qgis.core import QgsSettings
        return QgsSettings().value("lm_historiska_kartor/pythonbibliotek", "", type=str)
    except ImportError:
        return ""


def har_opencv(extra: str = "") -> bool:
    """Går OpenCV att importera i den Python automatiken körs med?"""
    env = dict(os.environ)
    rot = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sokvag = [rot] + ([extra] if extra and os.path.isdir(extra) else [])
    env["PYTHONPATH"] = os.pathsep.join(sokvag + [env.get("PYTHONPATH", "")])
    try:
        r = subprocess.run([python_exe(), "-c", "import cv2, scipy; print(cv2.__version__)"],
                           capture_output=True, text=True, timeout=60, env=env,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0


def kontroller(inst: _inst.Installningar, faltunderlag_auth: str = "",
               prova_opencv: bool = True) -> list[Kontroll]:
    ut: list[Kontroll] = []
    if inst.arkiv and os.path.isdir(inst.arkiv):
        ut.append(Kontroll("Arkiv", OK, inst.arkiv))
    else:
        ut.append(Kontroll("Arkiv", SAKNAS, "Mappen där registret och de nedladdade kartorna "
                           "läggs. Välj en tom mapp, eller en som pluginet redan skrivit i.",
                           "arkiv", "Välj mapp…"))
    ut.append(Kontroll("GDAL med ZSTD", OK, "kartorna lagras förlustfritt") if arkivfil._har_zstd()
              else Kontroll("GDAL med ZSTD", SAKNAS, "QGIS GDAL saknar ZSTD-komprimering. Alla "
                            "officiella QGIS-byggen från 3.40 har den — uppdatera QGIS."))
    if inst.referensdata and os.path.isdir(inst.referensdata):
        ut.append(Kontroll("Referensdata", OK, inst.referensdata))
    else:
        ut.append(Kontroll("Referensdata", SAKNAS, "En mapp på din dator där du lägger de lager du laddar "
                           "ner från Lantmäteriet (Socken och stad, Ortnamn …). Skapa gärna en tom mapp, "
                           "t.ex. Lantmäteriet, och välj den; pluginet hittar lagren i den på namn.",
                           "referensdata", "Välj mapp…"))
    sos = inst.sokvag_socken_och_stad()
    ut.append(Kontroll("Socken och stad", OK, sos) if sos else
              Kontroll("Socken och stad", SAKNAS, "Socknarnas gränser; utan den kan arbetsområdet bara "
                       "anges som socknar på namn. Gör så här: 1) tryck Öppna Geotorget och ladda ner "
                       "Socken och stad Nedladdning, vektor för hela Sverige (gratis; du behöver ett "
                       "Geotorget-konto, som också är gratis); 2) packa upp och lägg filen sockenstad.gpkg i "
                       "mappen Referensdata ovan; 3) tryck Kontrollera igen.",
                       "socken_och_stad", "Öppna Geotorget"))
    lan = inst.sokvag_lan()
    if lan:
        ut.append(Kontroll("Kommun, län och rike", OK, lan))
    elif faltunderlag_auth and not variant.BARA_HAMTNING:
        ut.append(Kontroll("Kommun, län och rike", VARNING, "Lantmäteriets kommun- och länsytor, avgiftsfria. "
                           "Gör så här: 1) beställ produkten Kommun, Län och Rike Nedladdning på Geotorget, "
                           "fliken Beställning, med samma konto som i QGIS (utan juridisk prövning; "
                           "behörigheten kommer inom en kvart); 2) tryck Hämta, så läggs filen i arkivets "
                           "referensmapp. Utan den måste socknar med samma namn i flera län väljas för hand, "
                           "och fastighetsindelningen kan inte väljas per kommun.", "kommuner", "Hämta"))
    else:
        ut.append(Kontroll("Kommun, län och rike", VARNING, "Lantmäteriets kommun- och länsgränser, så att "
                           "socknar med samma namn i flera län skiljs åt av sig själva. Gör så här: 1) tryck "
                           "Öppna Geotorget och beställ Kommun, Län och Rike Nedladdning (gratis, utan "
                           "prövning; du behöver ett Geotorget-konto); 2) ladda ner filen och lägg den i "
                           "mappen Referensdata ovan; 3) tryck Kontrollera igen. Utan filen måste sådana "
                           "socknar väljas för hand.", "kommun_lan_rike", "Öppna Geotorget"))
    # hämtningen för sig behöver varken Topografi 10, fastighetsindelningen, Geotorget-kontot
    # eller OpenCV: de hör till rektifieringen (variant.py)
    if not variant.BARA_HAMTNING:
        mapp, skala = referens.topografi_mapp(inst.referensdata)
        if skala == "10":
            ut.append(Kontroll("Topografi 10", OK, mapp))
        elif skala == "50":
            ut.append(Kontroll("Topografi 10", VARNING, "Topografi 50 finns och används. Topografi 10 "
                               "ger noggrannare gränser och stränder. Gör så här: 1) tryck Öppna Geotorget "
                               "och beställ Topografi 10 Nedladdning, vektor (gratis; Lantmäteriet prövar "
                               "ansökan, det tar några veckor); 2) ladda ner ditt län och lägg mappen i "
                               "Referensdata, med \"Topografi 10\" i mappnamnet; 3) tryck Kontrollera igen.",
                               "topografi10", "Öppna Geotorget"))
        else:
            ut.append(Kontroll("Topografi 10", SAKNAS, "Vägar, vatten, åkerkanter och ortnamn som automatiken "
                               "passar kartan mot. Gör så här: 1) tryck Öppna Geotorget och beställ Topografi 10 "
                               "Nedladdning, vektor (gratis; Lantmäteriet prövar ansökan, det tar några veckor); "
                               "2) ladda ner ditt län och lägg mappen i Referensdata, med \"Topografi 10\" i "
                               "mappnamnet; 3) tryck Kontrollera igen. Topografi 50 duger i nödfall.",
                               "topografi10", "Öppna Geotorget"))
    if inst.traktlager and os.path.exists(inst.traktlager):
        ut.append(Kontroll("Traktlager", OK, inst.traktlager))
    else:
        ut.append(Kontroll("Traktlager", INFO, "Valfritt: ett eget lager med trakternas ytor, om du har ett, "
                           "utpekat under Alla inställningar… En trakt är ett byområde som arkivet sorterar "
                           "akterna under. Utan eget lager tas trakterna ur fastighetsindelningen, annars "
                           "deras lägen ur ortnamnsregistret, annars ur arkivets egen lista."))
    fast = inst.fastighetsfiler()
    antal_fast = f"{len(fast)} kommun{'er' if len(fast) != 1 else ''}"
    if fast:
        ut.append(Kontroll("Fastighetsindelning", OK, antal_fast + f": trakternas ytor i {STEGET}"
                           + ("" if variant.BARA_HAMTNING else
                              ", grovplacering på aktens fastigheter och gränser att passa mot")))
    elif variant.BARA_HAMTNING:
        ut.append(Kontroll("Fastighetsindelning", INFO, "Valfritt: trakternas ytor när eget traktlager saknas, "
                           "så att ett ritat område kan säga vilka trakter det rör. Gör så här: 1) tryck Öppna "
                           "Geotorget och beställ Fastighetsindelning Nedladdning, vektor (gratis; Lantmäteriet "
                           "prövar ansökan, det tar några veckor); 2) när du fått klartecken: ladda ner filen "
                           "för din kommun och packa upp den (fastighetsindelning_kn2380.gpkg, siffrorna är "
                           "kommunens kod); 3) lägg filen i mappen Referensdata ovan och tryck Kontrollera "
                           "igen. Pluginet läser bara traktnamn och gränser, aldrig fastighetsbeteckningar "
                           "eller ägare.", "fastighetsindelning", "Öppna Geotorget"))
    else:
        ut.append(Kontroll("Fastighetsindelning", INFO, "Hämtas av sig själv med Geotorget-kontot: för "
                           "kartans kommuner när automatiken körs, och för arbetsområdets när Gallra behöver "
                           "trakter och eget traktlager saknas. Ger trakternas ytor i Gallra, grovplacering "
                           "på aktens fastigheter och gränser att passa mot. Produkten kräver att "
                           "Lantmäteriet prövar ansökan (några veckor; beställ på Geotorget); filerna kan "
                           "också laddas ner för hand till referensdatan.", "fastighetsindelning",
                           "Öppna Geotorget"))
    if not variant.BARA_HAMTNING:
        if faltunderlag_auth:
            ut.append(Kontroll("Geotorget-konto", OK, "markhöjdmodell, fastighetsindelning och "
                               "historiska ortofoton hämtas från Lantmäteriet"))
        else:
            ut.append(Kontroll("Geotorget-konto", VARNING, "Ett Geotorget-konto i QGIS autentisering, "
                               "valt under Inställningar…. Utan det: ingen markhöjdmodell, ingen "
                               "fastighetsindelning och inga historiska ortofoton; ekonomiska kartan "
                               "(öppna data) och allt annat fungerar."))
    reg = inst.ortnamnsregister()
    ut.append(Kontroll("Ortnamnsregistret", OK, reg) if reg else
              Kontroll("Ortnamnsregistret", INFO, "Valfritt: byar och gårdar att söka på, och trakternas "
                       "lägen när traktlager och fastighetsindelning saknas. Gör så här: 1) tryck Öppna "
                       "Geotorget och ladda ner Ortnamn Nedladdning, vektor för hela Sverige (gratis, utan "
                       "prövning; du behöver ett Geotorget-konto, som också är gratis); 2) lägg filen "
                       "ortnamn_se.gpkg i mappen Referensdata ovan; 3) tryck Kontrollera igen.",
                       "ortnamn", "Öppna Geotorget"))
    if prova_opencv and not variant.BARA_HAMTNING:
        extra = pythonbibliotek()
        if har_opencv(extra):
            ut.append(Kontroll("OpenCV", OK, "automatiken (Lägg in läget, Finjustera, Sammanfoga blad) "
                               "kan köras" + (f"; biblioteket i {extra}" if extra else "")))
        else:
            ut.append(Kontroll("OpenCV", SAKNAS, "Bildbiblioteket som automatiken och sammanfogningen "
                               "räknar med. Installeras i en egen mapp i arkivet med en knapp; QGIS "
                               "egen Python rörs inte.", "opencv", "Installera OpenCV"))
    sl = inst.sockenlager
    ut.append(Kontroll("Socknarna i arkivets län", OK, sl) if sl and os.path.exists(sl) else
              Kontroll("Socknarna i arkivets län", INFO, f"Byggs av sig själv första gången {STEGET} "
                       "öppnas (omkring 20 sekunder), ur Socken och stad."))
    return ut


def installera_opencv(malmapp: str):
    """Kommandot som installerar OpenCV i `malmapp` (körs av dialogen i en process)."""
    return [python_exe(), "-m", "pip", "install", "--target", malmapp, "--upgrade", OPENCV_PAKET]


# =========================================================================
# Dialogen
# =========================================================================

FARG = {OK: "#1a9850", VARNING: "#e08a00", SAKNAS: "#d7191c", INFO: "#777777"}
TECKEN = {OK: "●", VARNING: "●", SAKNAS: "●", INFO: "○"}


class KomIgangDialog:
    """Byggs som en QDialog; klassen är en fabrik så att modulen går att läsa utan Qt."""

    def __new__(cls, inst, parent=None):
        from qgis.PyQt.QtWidgets import (QDialog, QFileDialog, QGridLayout, QLabel, QPushButton,
                                         QScrollArea, QVBoxLayout, QWidget)
        from qgis.core import QgsSettings

        class _Dialog(QDialog):
            def __init__(self):
                super().__init__(parent)
                self.inst = inst
                self.setWindowTitle("Historiska kartor — kom igång")
                self.process = None
                lay = QVBoxLayout(self)
                intro = QLabel("Det här behöver pluginet. Grönt finns, gult går att klara sig utan, "
                               "rött måste ordnas. Knapparna gör det som går att göra härifrån.")
                intro.setWordWrap(True)
                lay.addWidget(intro)
                self.yta = QWidget()
                self.rutnat = QGridLayout(self.yta)
                rulle = QScrollArea()
                rulle.setWidgetResizable(True)
                rulle.setWidget(self.yta)
                lay.addWidget(rulle, 1)
                self.logg = QLabel()
                self.logg.setWordWrap(True)
                self.logg.setStyleSheet("color: gray")
                lay.addWidget(self.logg)
                rad = QVBoxLayout()
                knappar = QWidget()
                k = QGridLayout(knappar)
                igen = QPushButton("Kontrollera igen")
                igen.clicked.connect(self.fyll)
                inst_knapp = QPushButton("Alla inställningar…")
                inst_knapp.clicked.connect(self._installningar)
                stang = QPushButton("Stäng")
                stang.clicked.connect(self.close)
                hjalp = QPushButton("Hjälp")
                hjalp.clicked.connect(lambda: __import__(__name__.rsplit(".", 1)[0] + ".hjalp", fromlist=["visa"]).visa(
                    "komigang", self))
                for i, b in enumerate((igen, inst_knapp, hjalp, stang)):
                    k.addWidget(b, 0, i)
                rad.addWidget(knappar)
                lay.addLayout(rad)
                self.resize(820, 620)
                self.fyll()

            def fyll(self) -> None:
                while self.rutnat.count():
                    w = self.rutnat.takeAt(0).widget()
                    if w is not None:
                        w.deleteLater()
                from .underlag import atkomst
                auth = atkomst.sparat_id()
                self.kontroller = kontroller(self.inst, auth)
                for i, kk in enumerate(self.kontroller):
                    pr = QLabel(TECKEN[kk.status])
                    pr.setStyleSheet(f"color: {FARG[kk.status]}; font-size: 16px")
                    namn = QLabel(f"<b>{kk.namn}</b>")
                    text = QLabel(kk.text)
                    text.setWordWrap(True)
                    self.rutnat.addWidget(pr, i, 0)
                    self.rutnat.addWidget(namn, i, 1)
                    self.rutnat.addWidget(text, i, 2)
                    if kk.atgard:
                        b = QPushButton(kk.atgardstext)
                        b.clicked.connect(lambda _=False, a=kk.atgard: self.atgard(a))
                        self.rutnat.addWidget(b, i, 3)
                self.rutnat.setColumnStretch(2, 1)
                rott = sum(1 for kk in self.kontroller if kk.status == SAKNAS)
                self.logg.setText(f"Allt som krävs finns. Börja med {STEGET}…" if not rott else
                                  f"{rott} sak{'er' if rott > 1 else ''} måste ordnas innan allt fungerar.")

            def atgard(self, a: str) -> None:
                if a in ("arkiv", "referensdata"):
                    v = QFileDialog.getExistingDirectory(self, "Välj mapp", getattr(self.inst, a) or "")
                    if v:
                        setattr(self.inst, a, v)
                        _inst.spara(self.inst)
                        self.fyll()
                elif a in SIDOR:
                    from qgis.PyQt.QtGui import QDesktopServices
                    from qgis.PyQt.QtCore import QUrl
                    QDesktopServices.openUrl(QUrl(SIDOR[a]))
                elif a == "kommuner":
                    self._hamta_kommuner()
                elif a == "opencv":
                    self._installera_opencv()

            def _hamta_kommuner(self) -> None:
                """Kommun, län och rike till arkivets referensmapp med Geotorget-kontot
                (kommuner.hamta); nekas det sägs varför (produkten inte beställd)."""
                from .underlag import atkomst
                ref = os.path.join(self.inst.arkiv, "referens") if self.inst.arkiv else ""
                if not ref:
                    self.logg.setText("Ange arkivet först: filen läggs i arkivets referensmapp.")
                    return
                self.logg.setText("Hämtar Kommun, län och rike från Lantmäteriet …")
                try:
                    fil = kommuner.hamta(ref, atkomst.kontrollera(self.inst.authcfg))
                except Exception as e:  # noqa: BLE001 -- beskedet ur atkomst är skrivet för användaren
                    self.logg.setOpenExternalLinks(True)
                    self.logg.setText(str(e).splitlines()[0] + " Beställ produkten på "
                                      f"<a href=\"{KOMMUN_LAN_RIKE}\">Geotorget</a> (fliken Beställning, avgiftsfri) "
                                      "och tryck Hämta igen om en stund.")
                    return
                self.logg.setText(f"Hämtad: {fil}")
                self.fyll()

            def _installera_opencv(self) -> None:
                from qgis.PyQt.QtCore import QProcess
                if self.process is not None:
                    return
                if not self.inst.arkiv:
                    self.logg.setText("Välj arkivmappen först: OpenCV läggs i en egen mapp i den.")
                    return
                mal = os.path.join(self.inst.arkiv, "pythonbibliotek")
                os.makedirs(mal, exist_ok=True)
                cmd = installera_opencv(mal)
                self.logg.setText("Installerar OpenCV … (en minut; QGIS kan användas under tiden)")
                p = QProcess(self)
                p.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
                self._ut = ""
                p.readyReadStandardOutput.connect(
                    lambda: setattr(self, "_ut", self._ut + bytes(p.readAllStandardOutput()).decode("utf-8", "replace")))

                def klar(*_):
                    self.process = None
                    if p.exitCode() == 0:
                        QgsSettings().setValue("lm_historiska_kartor/pythonbibliotek", mal)
                        self.logg.setText(f"OpenCV installerat i {mal}.")
                    else:
                        sista = [r for r in self._ut.splitlines() if r.strip()][-4:]
                        self.logg.setText("Installationen misslyckades: " + " ".join(sista))
                    p.deleteLater()
                    self.fyll()
                p.finished.connect(klar)
                self.process = p
                p.start(cmd[0], cmd[1:])

            def _installningar(self) -> None:
                from .dialog import InstallningarDialog
                if InstallningarDialog(self.inst, self).exec():
                    self.inst = _inst.las()
                    self.fyll()

        return _Dialog()
