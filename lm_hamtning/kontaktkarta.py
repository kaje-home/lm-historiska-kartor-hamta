"""Kontaktkartan: gallringens tredje lager (avsnitt 6).

En dockad panel med miniatyrer av kartsidorna, 20 per vy.

**Musen i forsta hand, tangenterna som alternativ** (beslut 2026-09-29;
specen sa forst tvartom). Med musen:

    ✓ ? ✕ pa miniatyren     behall / osaker / kasta -- ett klick per akt
    knappraden under         samma for vald akt, forstora, vy fram och bak
    hogerklick               samma val i en meny
    dubbelklick              forstora; i forstoringen finns samma knappar

Med tangenterna:

    pilar           stega
    mellanslag      behall
    x               kasta
    o               osaker
    Enter           forstora
    PgUp / PgDn     foregaende / nasta vy

Efter ett beslut flyttas markoren till nasta akt utan beslut, och vid vyns
slut till nasta vy. En akt med flera kartblad visar forsta bladet och en
raknare. Besluten sparas direkt i registret, sa en kastad akt dyker aldrig
upp igen (gallra.py later bli dem).

**Osakra traffar ar gula** (beslut 2026-09-29): akter som bara ar med genom
normaliserade namn, en RBY-by eller en trakt i en grannsocken
(`Kandidat.osaker`). Beslut visas som ram: gron behall, orange osaker;
kastade blir grå med kryss.

Miniatyrerna hamtas i bakgrunden av en QgsTask, en akt i taget med
klientens paus. Vyn som visas gar forst i kon. Registret anvands bara i
granssnittstraden.
"""
from __future__ import annotations

import threading

from qgis.PyQt.QtCore import QEvent, QPoint, QRect, Qt, QSize, pyqtSignal
from qgis.PyQt.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from qgis.PyQt.QtWidgets import (QCheckBox, QDialog, QDockWidget, QHBoxLayout, QLabel,
                                 QListView, QListWidget, QListWidgetItem,
                                 QMenu, QPushButton, QScrollArea, QStyle,
                                 QStyledItemDelegate,
                                 QVBoxLayout, QWidget)
from qgis.core import QgsApplication, QgsTask

from .flode import Flode, skalbar
from .prioritet import prioriterad
from . import miniatyr
from .register import BESLUT

PER_VY = 20
IKON = 180
KNAPP = 26                              # knapparna pa miniatyren
ZOOMSTEG = 1.25                         # ett hack pa mushjulet
# Relativ 60-dpi-bilden. Storst = 150-dpi-bildens egen upplosning: langre in
# blir det bara storre pixlar, och Y22-2:1 ar redan 7 000 px bred dar.
ZOOM_MIN, ZOOM_MAX = 0.05, 150 / 60
TEXT_HOJD = 40                          # tva rader
# marginal, ikon, text, knappar, marginal
RUTA = QSize(IKON + 16, 4 + IKON + 4 + TEXT_HOJD + 6 + KNAPP + 4)
GUL = QColor(255, 230, 128)
FARG_BESLUT = {"behall": QColor(40, 160, 60), "osaker": QColor(230, 140, 20),
               "kasta": QColor(200, 40, 40)}
TANGENT = {Qt.Key.Key_Space: "behall", Qt.Key.Key_X: "kasta",
           Qt.Key.Key_O: "osaker"}
KNAPPAR = (("behall", "✓", "Behåll"), ("osaker", "?", "Osäker"),
           ("kasta", "✕", "Kasta"))
HJALP = ("Klicka ✓ ? ✕ på kartan · dubbelklick förstorar · "
         "högerklick meny\n"
         "Tangenter: pilar · mellanslag behåll · o osäker · x kasta · "
         "Enter förstora · PgUp/PgDn vy")


def oppna_fil(fil: str) -> None:
    """Filen i systemets program för filtypen (PDF-läsaren)."""
    from qgis.PyQt.QtCore import QUrl
    from qgis.PyQt.QtGui import QDesktopServices
    QDesktopServices.openUrl(QUrl.fromLocalFile(fil))


def text_for(k) -> str:
    a = k.akt
    rad1 = f"{a.ar or '–'} {', '.join(a.atgarder) or ''}".strip()
    if prioriterad(a.atgarder):
        rad1 = "★ " + rad1
    rad2 = a.beteckning
    n = a.antal_kartsidor or 0
    if n > 1:
        rad2 += f" · 1/{n}"
    return f"{rad1}\n{rad2}"


def forklaring(k) -> str:
    """Verktygstipset: varfor akten ar med."""
    a = k.akt
    rader = [f"{a.arkiv} {a.beteckning} — {', '.join(a.atgarder)} {a.ar or ''}",
             f"{a.socken}" + (f", {', '.join(a.trakter)}" if a.trakter else "")]
    if a.anmarkning:
        rader.append(a.anmarkning)
    for s in k.skal:
        if s.grund == "socken":
            rader.append("med: hela socknen")
            continue
        t = f"med: {s.trakt} ({s.grund}: {s.i_akten}, {s.grad})"
        if s.via_socken:
            t += f" — trakten ligger i {s.via_socken}"
        rader.append(t)
    if k.osaker:
        rader.append("OSÄKER träff")
    if prioriterad(a.atgarder):
        rader.append("★ laga skifte, storskifte, avvittring eller skattläggning: de förrättningar som "
                     "brukar ha de bästa kartorna; de visas först")
    return "\n".join(rader)


def markerad(pixmap: QPixmap, beslut: str | None) -> QPixmap:
    """Miniatyren med beslutet ritat ovanpa."""
    if not beslut:
        return pixmap
    ut = QPixmap(pixmap)
    p = QPainter(ut)
    penna = QPen(FARG_BESLUT[beslut])
    penna.setWidth(8)
    p.setPen(penna)
    if beslut == "kasta":
        p.fillRect(ut.rect(), QColor(255, 255, 255, 170))
        p.drawLine(0, 0, ut.width(), ut.height())
        p.drawLine(ut.width(), 0, 0, ut.height())
    else:
        p.drawRect(ut.rect().adjusted(4, 4, -4, -4))
    p.end()
    return ut


class MiniatyrUppgift(QgsTask):
    """Hamtar forsta kartbladets miniatyr for varje akt, i kons ordning."""

    klar = pyqtSignal(str, str)         # akt-nyckel, sokvag
    misslyckad = pyqtSignal(str, str)   # akt-nyckel, felet

    def __init__(self, klient, katalog: str, akter: list):
        super().__init__("Miniatyrer för kontaktkartan", QgsTask.Flag.CanCancel)
        self.klient = klient
        self.katalog = katalog
        self._las = threading.Lock()
        self._ko = list(akter)
        self._antal = max(len(akter), 1)

    def forst(self, nycklar: list[str]) -> None:
        """Lagg akterna med `nycklar` forst i kon -- vyn som visas."""
        with self._las:
            fram = [a for a in self._ko if a.nyckel in nycklar]
            self._ko = fram + [a for a in self._ko if a.nyckel not in nycklar]

    def _nasta(self):
        with self._las:
            return self._ko.pop(0) if self._ko else None

    def gor_en(self, akt) -> None:
        try:
            filer = miniatyr.kartsidor(self.klient, akt, self.katalog,
                                       bara_forsta=True)
            if filer:
                self.klar.emit(akt.nyckel, filer[0])
            else:
                self.misslyckad.emit(akt.nyckel, "ingen kartsida")
        except Exception as e:          # en akt far inte stoppa resten
            self.misslyckad.emit(akt.nyckel, str(e).splitlines()[0])

    def run(self) -> bool:
        gjorda = 0
        while not self.isCanceled():
            akt = self._nasta()
            if akt is None:
                return True
            self.gor_en(akt)
            gjorda += 1
            self.setProgress(100 * gjorda / self._antal)
        return False


class _Bildyta(QScrollArea):
    """Bilden i forstoringen: Ctrl + mushjul zoomar kring pekaren, vanster
    musknapp drar bilden, hogerklick ger menyn."""

    zoom = pyqtSignal(float, QPoint)        # faktor, punkt i viewporten
    meny = pyqtSignal(QPoint)               # global punkt
    ny_storlek = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag: QPoint | None = None
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(
            lambda pos: self.meny.emit(self.mapToGlobal(pos)))

    def wheelEvent(self, e):
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            steg = e.angleDelta().y()
            if steg:
                pos = (e.position().toPoint() if hasattr(e, "position")
                       else e.pos())
                self.zoom.emit(ZOOMSTEG if steg > 0 else 1 / ZOOMSTEG, pos)
            e.accept()
        else:
            super().wheelEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = _pos(e)
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            nu = _pos(e)
            d = nu - self._drag
            self._drag = nu
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - d.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - d.y())
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._drag = None
        self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
        super().mouseReleaseEvent(e)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.ny_storlek.emit()


def _pos(e) -> QPoint:
    return e.position().toPoint() if hasattr(e, "position") else e.pos()


class Forstoring(QDialog):
    """Kartbladen i storre skala, med samma beslut som panelen.

    `beslut` ar satt nar dialogen stangs med Behall, Osaker eller Kasta.

    Musen: knapparna, hogerklicksmenyn (samma val som i panelen, plus blad
    och zoom), Ctrl + mushjul zoomar kring pekaren, vanster knapp drar.
    Tangenter: pilar byter blad, mellanslag / o / x beslutar, Ctrl+0 anpassa,
    Ctrl++ / Ctrl+- zoom, Esc stanger utan beslut.

    Bilden oppnas anpassad till fonstret. `skala` ar relativ 60-dpi-bilden
    (miniatyr.DPI_STOR); None = anpassad. Over 1 byts kallan mot en rendering
    i DPI_SKARP, sa att detaljerna inte bara blir storre pixlar.
    """

    def __init__(self, klient, katalog: str, kandidat, parent=None, register=None):
        super().__init__(parent)
        self.klient, self.katalog, self.k = klient, katalog, kandidat
        self.register = register
        self.blad = 0
        self.beslut: str | None = None
        self.skala: float | None = None
        self._kallor: dict[int, QPixmap] = {}
        self.setWindowTitle(kandidat.akt.beteckning)
        self.etikett = QLabel()
        self.yta = _Bildyta()
        self.yta.setWidget(self.etikett)
        self.yta.setWidgetResizable(False)
        self.yta.zoom.connect(self.zooma)
        self.yta.meny.connect(self._visa_meny)
        # Anpassningen raknas om nar BILDYTAN far ny storlek, inte dialogen:
        # nar dialogen andras har layouten annu inte gett ytan sin storlek,
        # och kartan fyllde inte fonstret (sett i QGIS 2026-09-29).
        self.yta.ny_storlek.connect(self._om_anpassad)
        self.rubrik = QLabel()
        self.rubrik.setStyleSheet("font-weight: bold")
        self.detaljer = QLabel()
        self.detaljer.setWordWrap(True)
        self.detaljer.setStyleSheet("color: #555")
        rad = QHBoxLayout()
        self.forra_blad = QPushButton("◀ Förra bladet")
        self.nasta_blad = QPushButton("Nästa blad ▶")
        self.forra_blad.clicked.connect(lambda: self._blad(-1))
        self.nasta_blad.clicked.connect(lambda: self._blad(1))
        rad.addWidget(self.forra_blad)
        rad.addWidget(self.nasta_blad)
        anpassa = QPushButton("Anpassa")
        anpassa.setToolTip("Hela bladet i fönstret (Ctrl+0)")
        anpassa.clicked.connect(self.anpassa)
        rad.addWidget(anpassa)
        # Ett blad i en akt med flera kan tas med eller hoppas över för sig
        # (användaren 2026-10-01); beslutet gäller sidan, nedladdningen följer det.
        self.ta_med = QCheckBox("Ta med bladet")
        self.ta_med.setToolTip("Bocka ur för att inte ladda ned just det här kartbladet. "
                               "Aktens beslut (Behåll/Kasta) gäller resten.")
        self.ta_med.toggled.connect(self._ta_med_andrad)
        rad.addWidget(self.ta_med)
        rad.addStretch()
        self.knappar: dict[str, QPushButton] = {}
        for b, tecken, namn in KNAPPAR:
            k = QPushButton(f"{tecken} {namn}")
            k.setStyleSheet(f"color: {FARG_BESLUT[b].name()}; font-weight: bold")
            k.clicked.connect(lambda _=False, b=b: self._besluta(b))
            rad.addWidget(k)
            self.knappar[b] = k
        stang = QPushButton("Stäng")
        stang.clicked.connect(self.reject)
        rad.addWidget(stang)
        hjalp = QLabel("Ctrl + mushjul zoomar · dra med musen · högerklick meny")
        hjalp.setStyleSheet("color: gray")
        lay = QVBoxLayout(self)
        lay.addWidget(self.rubrik)
        lay.addWidget(self.detaljer)
        lay.addWidget(self.yta)
        lay.addLayout(rad)
        lay.addWidget(hjalp)
        self.resize(1200, 900)
        self._visa()

    # ------------------------------------------------------------- beslut
    def _besluta(self, beslut: str) -> None:
        self.beslut = beslut
        self.accept()

    def meny(self) -> QMenu:
        """Hogerklicksmenyn: samma beslut som i panelen, blad och zoom."""
        m = QMenu(self)
        for b, tecken, namn in KNAPPAR:
            m.addAction(f"{tecken} {namn}", lambda b=b: self._besluta(b))
        m.addSeparator()
        n = len(self.k.akt.kartsidor or [])
        a = m.addAction("◀ Förra bladet", lambda: self._blad(-1))
        a.setEnabled(self.blad > 0)
        a = m.addAction("Nästa blad ▶", lambda: self._blad(1))
        a.setEnabled(self.blad + 1 < n)
        m.addSeparator()
        m.addAction("Zooma in", lambda: self.zooma(ZOOMSTEG))
        m.addAction("Zooma ut", lambda: self.zooma(1 / ZOOMSTEG))
        m.addAction("Anpassa till fönstret", self.anpassa)
        m.addAction("100 %", lambda: self.satt_skala(1.0))
        m.addSeparator()
        m.addAction("Öppna akten som PDF hos Lantmäteriet", self._oppna_hos_lantmateriet)
        m.addAction("Öppna akten på Lantmäteriets webbsida", lambda: self._oppna_hos_lantmateriet(webb=True))
        m.addSeparator()
        m.addAction("Stäng", self.reject)
        return m

    def _oppna_hos_lantmateriet(self, webb: bool = False) -> None:
        """Hela akten i webbläsaren: som PDF ur Lantmäteriets bildtjänst (2026-10-26:
        länk för den som vill läsa vidare hos källan), eller i webbsidans egen visare
        (tjanst.url_webb, 2026-10-27)."""
        from qgis.PyQt.QtCore import QUrl
        from qgis.PyQt.QtGui import QDesktopServices
        from .tjanst import url_pdf, url_webb
        QDesktopServices.openUrl(QUrl((url_webb if webb else url_pdf)(self.k.akt)))

    def _visa_meny(self, global_pos: QPoint) -> None:
        self.meny().exec(global_pos)

    def _ta_med_andrad(self, med: bool) -> None:
        akt = self.k.akt
        s = (akt.kartsidor or [])[self.blad]
        self.register.satt_beslut(akt.nyckel, "behall" if med else "kasta", sida=s.guid)
        self._visa()

    # --------------------------------------------------------------- blad
    def _blad(self, steg: int) -> None:
        n = len(self.k.akt.kartsidor or [])
        if 0 <= self.blad + steg < n:
            self.blad += steg
            self._visa()

    def _kalla(self, dpi: int) -> QPixmap | None:
        """Bladet renderat i `dpi`, en gang per blad och upplosning."""
        if dpi not in self._kallor:
            akt = self.k.akt
            s = (akt.kartsidor or [])[self.blad]
            pdf = self.klient.akt_pdf(akt)
            f = miniatyr.sida_ur_pdf(pdf, s.lopnr,
                                     f"{self.katalog}/{miniatyr.filnamn(akt, s, dpi)}", dpi)
            self._kallor[dpi] = QPixmap(f)
        return self._kallor[dpi]

    def _visa(self):
        akt = self.k.akt
        sidor = akt.kartsidor or []
        if not sidor:
            self.rubrik.setText("Ingen kartsida.")
            return
        s = sidor[self.blad]
        self._kallor = {}
        self.skala = None
        # Samma text som under miniatyren, och forklaringen fran verktygstipset:
        # i forstoringen ska man se vad det ar man tittar pa.
        rad1 = f"{akt.ar or '–'} {', '.join(akt.atgarder)}".strip()
        self.rubrik.setText(f"{rad1} — {akt.arkiv} {akt.beteckning} — kartblad "
                            f"{self.blad + 1} av {len(sidor)} (sida {s.lopnr})")
        self.detaljer.setText(" · ".join(forklaring(self.k).splitlines()[1:]))
        self.setWindowTitle(f"{akt.beteckning} — {rad1}")
        self.forra_blad.setEnabled(self.blad > 0)
        self.nasta_blad.setEnabled(self.blad + 1 < len(sidor))
        self.ta_med.setVisible(self.register is not None and len(sidor) > 1)
        if self.register is not None:
            self.ta_med.blockSignals(True)
            self.ta_med.setChecked(self.register.gallande_beslut(akt.nyckel, s.guid) != "kasta")
            self.ta_med.blockSignals(False)
            if not self.ta_med.isChecked():
                self.rubrik.setText(self.rubrik.text() + " — tas inte med")
        self._rita()

    # --------------------------------------------------------------- zoom
    def _anpassad_skala(self) -> float:
        bas = self._kalla(miniatyr.DPI_STOR)
        v = self.yta.viewport().size()
        if bas is None or bas.isNull() or bas.width() == 0:
            return 1.0
        # 2 % marginal: exakt passform ger rullningslister, som krymper ytan,
        # som ger en ny passform ...
        return 0.98 * min(v.width() / bas.width(), v.height() / bas.height())

    def aktuell_skala(self) -> float:
        return self._anpassad_skala() if self.skala is None else self.skala

    def _rita(self) -> None:
        s = self.aktuell_skala()
        dpi = miniatyr.DPI_SKARP if s > 1.0 else miniatyr.DPI_STOR
        kalla = self._kalla(dpi)
        if kalla is None or kalla.isNull():
            return
        faktor = s * miniatyr.DPI_STOR / dpi
        bild = kalla.scaled(max(1, int(kalla.width() * faktor)),
                            max(1, int(kalla.height() * faktor)),
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation)
        self.etikett.setPixmap(bild)
        self.etikett.resize(bild.size())

    def satt_skala(self, skala: float | None, kring: QPoint | None = None) -> None:
        """Ny skala; punkten `kring` (i viewporten) star kvar under pekaren."""
        gammal = self.aktuell_skala()
        if skala is not None:
            skala = min(max(skala, ZOOM_MIN), ZOOM_MAX)
        v = self.yta.viewport()
        if kring is None:
            kring = QPoint(v.width() // 2, v.height() // 2)
        # Punkten i bilden, i den gamla skalan.
        i_bild = self.etikett.mapFrom(v, kring)
        self.skala = skala
        self._rita()
        ny = self.aktuell_skala()
        r = ny / gammal if gammal else 1.0
        self.yta.horizontalScrollBar().setValue(int(i_bild.x() * r - kring.x()))
        self.yta.verticalScrollBar().setValue(int(i_bild.y() * r - kring.y()))

    def zooma(self, faktor: float, kring: QPoint | None = None) -> None:
        self.satt_skala(self.aktuell_skala() * faktor, kring)

    def anpassa(self) -> None:
        self.satt_skala(None)

    def _om_anpassad(self) -> None:
        if self.skala is None and self._kallor:
            self._rita()

    def keyPressEvent(self, e):
        ctrl = bool(e.modifiers() & Qt.KeyboardModifier.ControlModifier)
        if ctrl and e.key() == Qt.Key.Key_0:
            self.anpassa()
        elif ctrl and e.key() in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.zooma(ZOOMSTEG)
        elif ctrl and e.key() == Qt.Key.Key_Minus:
            self.zooma(1 / ZOOMSTEG)
        elif e.key() == Qt.Key.Key_Right:
            self._blad(1)
        elif e.key() == Qt.Key.Key_Left:
            self._blad(-1)
        elif e.key() in TANGENT and not e.modifiers():
            self._besluta(TANGENT[e.key()])
        else:
            super().keyPressEvent(e)


class _Ruta(QStyledItemDelegate):
    """Ritar en akt: bakgrunden forst (gul om osaker), sedan akten utan Qt:s
    markering, och markeringen som bla ram ovanpa.

    Qt:s egen markering tonade miniatyren bla, dolde den gula bakgrunden och
    kapade texten (sett i QGIS 2026-09-29). Det som ar viktigt att se -- ar
    akten osaker, och vilken karta ar det -- far inte forsvinna for att akten
    ar vald.
    """

    MARGINAL = 4            # sa att ramen inte skar texten

    klick = pyqtSignal(str, str)        # akt-nyckel, beslut

    def __init__(self, parent, beslut_for):
        super().__init__(parent)
        self._beslut_for = beslut_for   # nyckel -> gallande beslut eller None

    @staticmethod
    def knappar(rect: QRect) -> list[tuple[QRect, str]]:
        """Knapparna ✓ ? ✕ nederst i rutan, centrerade."""
        bredd = len(KNAPPAR) * KNAPP + (len(KNAPPAR) - 1) * 8
        x = rect.center().x() - bredd // 2
        y = rect.bottom() - _Ruta.MARGINAL - KNAPP
        return [(QRect(x + i * (KNAPP + 8), y, KNAPP, KNAPP), b)
                for i, (b, _, _) in enumerate(KNAPPAR)]

    def editorEvent(self, event, model, option, index):
        typ = event.type()
        if typ in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease,
                   QEvent.Type.MouseButtonDblClick):
            pos = (event.position().toPoint() if hasattr(event, "position")
                   else event.pos())
            for r, b in self.knappar(option.rect):
                if r.contains(pos):
                    if (typ == QEvent.Type.MouseButtonRelease
                            and event.button() == Qt.MouseButton.LeftButton):
                        self.klick.emit(index.data(Qt.ItemDataRole.UserRole), b)
                    return True     # ett klick pa knappen ar inget annat
        return super().editorEvent(event, model, option, index)

    def _rita_knappar(self, painter, rect: QRect, nyckel: str) -> None:
        galler = self._beslut_for(nyckel)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        f = painter.font()
        f.setBold(True)
        f.setPointSize(11)
        painter.setFont(f)
        for r, b in self.knappar(rect):
            farg = FARG_BESLUT[b]
            tecken = next(t for bb, t, _ in KNAPPAR if bb == b)
            penna = QPen(farg)
            penna.setWidth(2)
            painter.setPen(penna)
            painter.setBrush(farg if galler == b else QColor(255, 255, 255, 220))
            painter.drawEllipse(r.adjusted(1, 1, -1, -1))
            painter.setPen(QColor("white") if galler == b else farg)
            painter.drawText(r, Qt.AlignmentFlag.AlignCenter, tecken)
        painter.restore()

    def paint(self, painter, option, index):
        """Hela rutan ritas har, pa fasta platser: kartan centrerad i en
        IKON x IKON-yta, tva textrader under, knapparna nederst. Qt:s egen
        layout placerade texten olika beroende pa bildens form, och under en
        kvadratisk karta hamnade den under knapparna (QGIS 2026-09-29)."""
        yta = option.rect
        vald = bool(option.state & QStyle.StateFlag.State_Selected)
        bak = index.data(Qt.ItemDataRole.BackgroundRole)
        painter.save()
        if bak is not None:
            painter.fillRect(yta, bak)
        m = self.MARGINAL
        ikonyta = QRect(yta.left() + m, yta.top() + m, yta.width() - 2 * m, IKON)
        ikon = index.data(Qt.ItemDataRole.DecorationRole)
        if ikon is not None:
            pm = ikon.pixmap(QSize(IKON, IKON))
            skala = pm.devicePixelRatio() or 1.0
            b, h = int(pm.width() / skala), int(pm.height() / skala)
            painter.drawPixmap(QRect(ikonyta.center().x() - b // 2,
                                     ikonyta.center().y() - h // 2, b, h), pm)
        textyta = QRect(yta.left() + m, ikonyta.bottom() + 4, yta.width() - 2 * m,
                        TEXT_HOJD)
        painter.setFont(option.font)
        painter.setPen(QColor("black"))
        painter.drawText(textyta, Qt.AlignmentFlag.AlignHCenter
                         | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                         index.data(Qt.ItemDataRole.DisplayRole) or "")
        painter.restore()
        self._rita_knappar(painter, yta, index.data(Qt.ItemDataRole.UserRole))
        if vald:
            painter.save()
            penna = QPen(QColor(30, 100, 200))
            penna.setWidth(3)
            painter.setPen(penna)
            painter.drawRect(yta.adjusted(1, 1, -2, -2))
            painter.restore()

    def sizeHint(self, option, index):
        return RUTA


class _Lista(QListWidget):
    tangent = pyqtSignal(str)

    def keyPressEvent(self, e):
        if e.key() in TANGENT and not e.modifiers():
            self.tangent.emit(TANGENT[e.key()])
        elif e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.tangent.emit("forstora")
        elif e.key() == Qt.Key.Key_PageDown:
            self.tangent.emit("nasta")
        elif e.key() == Qt.Key.Key_PageUp:
            self.tangent.emit("forra")
        else:
            super().keyPressEvent(e)


class Kontaktkarta(QDockWidget):
    """Panelen. `visa(kandidater)` fyller den; `klient` hamtar PDF:erna."""

    beslut_fattat = pyqtSignal(str, str)    # akt-nyckel, beslut

    def __init__(self, register, klient, katalog: str, parent=None):
        super().__init__("Kontaktkarta", parent)
        self.setObjectName("LMHistoriskaKartorKontaktkarta")
        self.register, self.klient, self.katalog = register, klient, katalog
        self.kandidater: list = []
        self.vy = 0
        self.bilder: dict[str, QPixmap] = {}
        self.fel: dict[str, str] = {}
        self.beslut: dict[str, str] = {}
        self.uppgift: MiniatyrUppgift | None = None

        self.lista = _Lista()
        self.lista.setViewMode(QListView.ViewMode.IconMode)
        self.lista.setIconSize(QSize(IKON, IKON))
        # Ikon, ram och tva rader text -- lagre an sa kapas texten under en
        # kvadratisk karta ("1774 Storskif...", sett i QGIS 2026-09-29).
        self.lista.setGridSize(QSize(RUTA.width() + 8, RUTA.height() + 8))
        self.lista.setResizeMode(QListView.ResizeMode.Adjust)
        self.lista.setMovement(QListView.Movement.Static)
        self.lista.setWordWrap(True)
        self.lista.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.ritare = _Ruta(self.lista, self.beslut.get)
        # Ett klick pa miniatyrens knapp flyttar inte markoren: med musen valjer
        # man sjalv, och vyn ska inte hoppa. Tangenter, knappraden och
        # forstoringen gar vidare till nasta akt utan beslut.
        self.ritare.klick.connect(lambda n, b: self._besluta(b, n, flytta=False))
        self.lista.setItemDelegate(self.ritare)
        self.lista.tangent.connect(self._tangent)
        self.lista.itemDoubleClicked.connect(lambda _: self._forstora())
        self.lista.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.lista.customContextMenuRequested.connect(self._meny)
        self.status = QLabel()

        rad = Flode()
        self.knappar: dict[str, QPushButton] = {}
        for b, tecken, namn in KNAPPAR:
            k = QPushButton(f"{tecken} {namn}")
            k.setStyleSheet(f"color: {FARG_BESLUT[b].name()}; font-weight: bold")
            k.clicked.connect(lambda _=False, b=b: self._besluta(b))
            rad.addWidget(k)
            self.knappar[b] = k
        self.knapp_forstora = QPushButton("Förstora")
        self.knapp_forstora.clicked.connect(self._forstora)
        rad.addWidget(self.knapp_forstora)
        self.knapp_utan = QPushButton("Nästa utan beslut")
        self.knapp_utan.setToolTip("Hoppa till nästa akt utan beslut, även i andra vyer")
        self.knapp_utan.clicked.connect(self.nasta_utan_beslut)
        rad.addWidget(self.knapp_utan)
        self.knapp_forra = QPushButton("◀ Förra vyn")
        self.knapp_forra.setToolTip("Föregående vy")
        self.knapp_forra.clicked.connect(lambda: self._tangent("forra"))
        self.knapp_nasta = QPushButton("Nästa vy ▶")
        self.knapp_nasta.setToolTip("Nästa vy")
        self.knapp_nasta.clicked.connect(lambda: self._tangent("nasta"))
        rad.addWidget(self.knapp_forra)
        rad.addWidget(self.knapp_nasta)

        hjalp = QLabel(HJALP)
        hjalp.setStyleSheet("color: gray")
        hjalp.setWordWrap(True)
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(self.status)
        lay.addWidget(self.lista)
        lay.addLayout(rad)
        lay.addWidget(hjalp)
        self.setWidget(skalbar(w))

    # ------------------------------------------------------------ innehall
    def visa(self, kandidater: list, starta: bool = True) -> None:
        """Visa akterna som ar kvar efter gallringens tva forsta lager."""
        self.avbryt()
        # Prioriterade åtgärder först, annars i gallringens ordning (prioritet.py)
        self.kandidater = sorted((k for k in kandidater if k.kvar),
                                 key=lambda k: not prioriterad(k.akt.atgarder))
        self.beslut.clear()             # ritaren haller samma ordbok
        self._miniatyrer_klara = 0      # raknas i statusraden: det tar minuter for hundratals akter
        for k in self.kandidater:
            b = self.register.gallande_beslut(k.akt.nyckel)
            if b:
                self.beslut[k.akt.nyckel] = b
        self.vy = 0
        self._fyll()
        if starta and self.kandidater:
            self.uppgift = MiniatyrUppgift(self.klient, self.katalog,
                                           [k.akt for k in self.kandidater])
            self.uppgift.klar.connect(self._bild_klar)
            self.uppgift.misslyckad.connect(self._bild_fel)
            self.uppgift.forst(self._nycklar_i_vy())
            QgsApplication.taskManager().addTask(self.uppgift)

    def ladda_synkront(self) -> None:
        """Alla miniatyrer i den har traden -- for prov och skript."""
        u = MiniatyrUppgift(self.klient, self.katalog, [k.akt for k in self.kandidater])
        u.klar.connect(self._bild_klar)
        u.misslyckad.connect(self._bild_fel)
        for k in self.kandidater:
            u.gor_en(k.akt)

    def avbryt(self) -> None:
        if self.uppgift is not None:
            try:
                self.uppgift.cancel()
            except RuntimeError:
                pass                    # redan borta
            self.uppgift = None

    def closeEvent(self, e):
        self.avbryt()
        super().closeEvent(e)

    # ----------------------------------------------------------------- vyn
    def _antal_vyer(self) -> int:
        return max(1, -(-len(self.kandidater) // PER_VY))

    def _i_vy(self) -> list:
        return self.kandidater[self.vy * PER_VY:(self.vy + 1) * PER_VY]

    def _nycklar_i_vy(self) -> list[str]:
        return [k.akt.nyckel for k in self._i_vy()]

    def _fyll(self, markera: int = 0) -> None:
        self.lista.clear()
        for k in self._i_vy():
            it = QListWidgetItem(text_for(k))
            it.setToolTip(forklaring(k))
            it.setData(Qt.ItemDataRole.UserRole, k.akt.nyckel)
            # Fast storlek: Qt raknar annars hojden for snalt nar texten
            # bryts, och ramen for vald akt skar andra raden.
            it.setSizeHint(RUTA)
            if k.osaker:
                it.setBackground(GUL)
            self._ikon(it, k.akt.nyckel)
            self.lista.addItem(it)
        if self.lista.count():
            self.lista.setCurrentRow(min(markera, self.lista.count() - 1))
        self._statusrad()
        if self.uppgift is not None:
            self.uppgift.forst(self._nycklar_i_vy())

    def _ikon(self, it: QListWidgetItem, nyckel: str) -> None:
        bild = self.bilder.get(nyckel)
        if bild is None:
            bild = QPixmap(IKON, IKON)
            bild.fill(QColor(235, 235, 235))
            if nyckel in self.fel:
                it.setToolTip(it.toolTip() + f"\nMiniatyren kunde inte göras: "
                              f"{self.fel[nyckel]}")
        # Samma bild nar akten ar vald: Qt tonar annars den valda ikonen
        # blå, och halva kartan forsvinner. Valet syns som ram (stilen).
        pm = markerad(bild, self.beslut.get(nyckel))
        ikon = QIcon(pm)
        ikon.addPixmap(pm, QIcon.Mode.Selected)
        it.setIcon(ikon)

    def _statusrad(self) -> None:
        self.knapp_forra.setEnabled(self.vy > 0)
        self.knapp_nasta.setEnabled(self.vy + 1 < self._antal_vyer())
        b = [self.beslut[k.akt.nyckel] for k in self.kandidater
             if k.akt.nyckel in self.beslut]
        utan = len(self.kandidater) - len(b)
        per_vy: dict[int, int] = {}
        for i, k in enumerate(self.kandidater):
            if k.akt.nyckel not in self.beslut:
                per_vy[i // PER_VY + 1] = per_vy.get(i // PER_VY + 1, 0) + 1
        var = ""
        if utan:
            var = " (" + ", ".join(f"vy {v}: {n}" for v, n in sorted(per_vy.items())) + ")"
        # miniatyrerna hamtas i bakgrunden, en akt i taget (anvandaren 2026-10-26: "tar lang
        # tid" -- en ovan ska se att det pagar, inte tro att det hangt sig)
        klara, tot = getattr(self, "_miniatyrer_klara", 0), len(self.kandidater)
        bilder = (f" · miniatyrer {klara} av {tot} hämtade, resten kommer i bakgrunden" if klara < tot
                  else f" · alla {tot} miniatyrer hämtade")
        self.status.setText(
            f"Vy {self.vy + 1} av {self._antal_vyer()} · {len(self.kandidater)} akter · "
            f"behållna {b.count('behall')} · osäkra {b.count('osaker')} · "
            f"kastade {b.count('kasta')} · utan beslut {utan}{var}{bilder}")
        self.knapp_utan.setEnabled(bool(utan))

    def _item(self, nyckel: str) -> QListWidgetItem | None:
        for i in range(self.lista.count()):
            it = self.lista.item(i)
            if it.data(Qt.ItemDataRole.UserRole) == nyckel:
                return it
        return None

    def _bild_klar(self, nyckel: str, fil: str) -> None:
        self._miniatyrer_klara = getattr(self, "_miniatyrer_klara", 0) + 1
        self._statusrad()
        bild = QPixmap(fil)
        if bild.isNull():
            self._bild_fel(nyckel, "bilden kunde inte läsas")
            return
        self.bilder[nyckel] = bild.scaled(
            IKON, IKON, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        it = self._item(nyckel)
        if it is not None:
            self._ikon(it, nyckel)

    def _bild_fel(self, nyckel: str, text: str) -> None:
        self._miniatyrer_klara = getattr(self, "_miniatyrer_klara", 0) + 1
        self._statusrad()
        self.fel[nyckel] = text
        it = self._item(nyckel)
        if it is not None:
            self._ikon(it, nyckel)

    # ------------------------------------------------------------ tangenter
    def _tangent(self, vad: str) -> None:
        if vad in BESLUT:
            self._besluta(vad)
        elif vad == "forstora":
            self._forstora()
        elif vad == "nasta" and self.vy + 1 < self._antal_vyer():
            self.vy += 1
            self._fyll()
        elif vad == "forra" and self.vy > 0:
            self.vy -= 1
            self._fyll()

    def _aktuell(self):
        it = self.lista.currentItem()
        if it is None:
            return None
        n = it.data(Qt.ItemDataRole.UserRole)
        return next((k for k in self.kandidater if k.akt.nyckel == n), None)

    def _meny(self, pos) -> None:
        it = self.lista.itemAt(pos)
        if it is None:
            return
        self.lista.setCurrentItem(it)
        m = QMenu(self.lista)
        for b, tecken, namn in KNAPPAR:
            m.addAction(f"{tecken} {namn}", lambda b=b: self._besluta(b))
        m.addSeparator()
        m.addAction("Förstora", self._forstora)
        self._textakt_val(m)
        k = self._aktuell()
        if k is not None:
            # samma länk som i Förstora-fönstret; manualen lovade den här (2026-10-27)
            m.addSeparator()
            m.addAction("Öppna akten som PDF hos Lantmäteriet", lambda: self._oppna_hos_lantmateriet(k))
            m.addAction("Öppna akten på Lantmäteriets webbsida", lambda: self._oppna_hos_lantmateriet(k, webb=True))
        m.exec(self.lista.viewport().mapToGlobal(pos))

    def _oppna_hos_lantmateriet(self, k, webb: bool = False) -> None:
        from qgis.PyQt.QtCore import QUrl
        from qgis.PyQt.QtGui import QDesktopServices
        from .tjanst import url_pdf, url_webb
        QDesktopServices.openUrl(QUrl((url_webb if webb else url_pdf)(k.akt)))

    def _textakt_val(self, m: QMenu) -> None:
        """Textakten, ett val per akt (textakt.py; användaren 2026-10-19)."""
        import os
        from . import textakt
        k = self._aktuell()
        rad = self.register.akt(k.akt.nyckel) if k is not None else None
        if rad is None:
            return
        m.addSeparator()
        fil = textakt.sokvag(os.path.dirname(self.register.sokvag), rad)
        if os.path.exists(fil):
            m.addAction("Öppna textakten", lambda: oppna_fil(fil))
            return
        n = sum(1 for s in (k.akt.sidor or []) if not s.karta)
        a = m.addAction(f"Spara textakten i arkivet ({n} sidor)", lambda: self._spara_textakt(k))
        a.setEnabled(n > 0)
        a.setToolTip("Aktens protokoll och beskrivning som PDF bredvid kartorna")

    def _spara_textakt(self, k) -> None:
        import os
        from qgis.PyQt.QtWidgets import QApplication, QMessageBox
        from . import textakt
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            fil, n = textakt.spara(self.klient, self.register, os.path.dirname(self.register.sokvag),
                                   k.akt.nyckel)
        except Exception as e:                          # noqa: BLE001
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Textakten", f"{k.akt.beteckning}: {e}")
            return
        QApplication.restoreOverrideCursor()
        self.status.setText(f"Textakten för {k.akt.beteckning} sparad ({n} sidor): {fil}")

    def _besluta(self, beslut: str, nyckel: str | None = None,
                 flytta: bool = True) -> None:
        """Beslut for `nyckel`, eller for vald akt. Ett klick pa en miniatyrs
        knapp valjer ocksa den akten, sa att markoren foljer musen."""
        if nyckel is not None:
            it = self._item(nyckel)
            if it is not None:
                self.lista.setCurrentItem(it)
        k = self._aktuell()
        if k is None:
            return
        n = k.akt.nyckel
        self.register.satt_beslut(n, beslut)
        self.beslut[n] = beslut
        self._ikon(self.lista.currentItem(), n)
        self._statusrad()
        self.beslut_fattat.emit(n, beslut)
        if flytta:
            self._till_nasta()

    def _valj_rad(self, rad: int) -> None:
        """Markera raden och rulla fram den. Utan rullningen hamnade akter
        mitt i vyn utanfor den smala panelen och blev liggande utan beslut
        (sett 2026-09-29: 8 akter i vy 1)."""
        self.lista.setCurrentRow(rad)
        it = self.lista.item(rad)
        if it is not None:
            self.lista.scrollToItem(it, QListWidget.ScrollHint.EnsureVisible)

    def _till_nasta(self) -> None:
        """Nasta akt utan beslut i vyn; finns ingen, nasta vy."""
        rad = self.lista.currentRow()
        for i in list(range(rad + 1, self.lista.count())) + list(range(0, rad)):
            if self.lista.item(i).data(Qt.ItemDataRole.UserRole) not in self.beslut:
                self._valj_rad(i)
                return
        if self.vy + 1 < self._antal_vyer():
            self.vy += 1
            self._fyll()

    def nasta_utan_beslut(self) -> None:
        """Nasta akt utan beslut efter markoren, i vilken vy som helst."""
        start = self.vy * PER_VY + max(self.lista.currentRow(), 0)
        n = len(self.kandidater)
        for steg in range(1, n + 1):
            i = (start + steg) % n
            if self.kandidater[i].akt.nyckel not in self.beslut:
                if i // PER_VY != self.vy:
                    self.vy = i // PER_VY
                    self._fyll(markera=i % PER_VY)
                self._valj_rad(i % PER_VY)
                return

    def _forstora(self) -> None:
        k = self._aktuell()
        if k is None:
            return
        d = Forstoring(self.klient, self.katalog, k, self, register=self.register)
        d.exec()
        if d.beslut:
            self._besluta(d.beslut, k.akt.nyckel)
