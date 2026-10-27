"""Gallra: arbetsomrade -> socknar och trakter -> akter i kontaktkartan.

Ett fonster som inte laser QGIS, sa att man kan rita i kartan medan det ar
oppet. Tre steg, uppifran och ned:

1. **Arbetsomrade** -- valda objekt i ett polygonlager (indexrutor, Socken
   och stad, ett eget lager), en ritad yta, ett uttags arbetsomrade, eller
   socknar valda pa namn (avsnitt 6).
2. **Socknar och trakter** att bekrafta. Osakra trakter ar gula; trakter
   som arkivet har under en grannsocken star under grannen. Oklara socknar
   valjs i listan, och valet sparas i sockenlagret. "Alla akter i socknen"
   soker socknen utan traktfilter.
3. **Gallra** i bakgrunden; nar det ar klart oppnas kontaktkartan.

Allt som ror natet kor i bakgrunden (bakgrund.Jobb) med egen klient och eget
register. Granssnittet anvander sin egen klient och sitt eget register for
kontaktkartan.
"""
from __future__ import annotations

import os
import re

from qgis.PyQt.QtCore import QStringListModel, Qt
from qgis.PyQt.QtGui import QBrush, QIntValidator
from qgis.PyQt.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QCompleter,
                                 QDialog, QDialogButtonBox, QFileDialog,
                                 QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                                 QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
                                 QProgressBar, QPushButton, QRadioButton,
                                 QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                                 QWidget)
from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform,
                       QgsFeature, QgsFillSymbol, QgsGeometry,
                       QgsMapLayerProxyModel, QgsProject, QgsSettings,
                       QgsVectorFileWriter, QgsVectorLayer)
from qgis.gui import QgsMapLayerComboBox

from . import indexrutor
from . import installningar as _inst
from . import kommuner, ortnamn, sockenlager, steg, urval
from .bakgrund import Jobb
from .prioritet import PRIORITERADE, TYPER
from .gallra import (ANNAN_ATGARD, ANNAN_TRAKT, ANNAT_AR, INGA_KARTSIDOR, INGEN_KARTA,
                     KASTAD, METADATA_FEL)
from .kontaktkarta import GUL, Kontaktkarta
from .register import Register
from .tjanst import Klient, QgisTransport

SWEREF = QgsCoordinateReferenceSystem("EPSG:3006")
GRUPP = "Historiska kartor"             # lagergruppen i projektet
OMRADESLAGER = "Arbetsområde"
ALLA = "alla akter i socknen"
ROLL_SOCKEN = Qt.ItemDataRole.UserRole          # SockenIOmrade eller Socken
ROLL_TRAKT = Qt.ItemDataRole.UserRole + 1       # TraktIOmrade
ROLL_ALLA = Qt.ItemDataRole.UserRole + 2        # True for "alla akter"-raden
HUR = {urval.NAMN: "", urval.LAN: "avgjord med länet", urval.VALT: "",
       urval.ANNAT_NAMN: "", urval.OKLAR: "finns i flera län — välj",
       urval.SAKNAS: "finns inte med samma namn — välj"}


def _antal(n: int, en: str, flera: str) -> str:
    return f"{n} {en if n == 1 else flera}"


def uttagets_omrade(sokvag: str) -> str | None:
    """Arbetsomradesfilen i ett uttag (Faltunderlaget, september 2026):
    `<uttag>/omrade/utredningsomrade.gpkg`. En fil ges tillbaka som den ar."""
    if not sokvag:
        return None
    if os.path.isfile(sokvag):
        return sokvag
    f = os.path.join(sokvag, "omrade", "utredningsomrade.gpkg")
    return f if os.path.isfile(f) else None


def standardklient(inst) -> Klient:
    """Klienten mot tjansten, med cachen ur installningarna."""
    _inst.markera_cache(inst.cachekatalog)
    return Klient(transport=QgisTransport(), cache=inst.cachekatalog or None)


def till_sweref(geom: QgsGeometry, crs) -> QgsGeometry:
    g = QgsGeometry(geom)
    if crs.isValid() and crs != SWEREF:
        g.transform(QgsCoordinateTransform(crs, SWEREF, QgsProject.instance()))
    return g


# =========================================================================
# Installningarna
# =========================================================================

class ValjSocknarDialog(QDialog):
    """Välj socknar via län och kommun (användaren 2026-10-26: "kan man även tänka kommun
    eller blir det för mycket?" -- som mellanled: den som inte vet socknen vet kommunen).
    Tre listor: dagens län (ur tabellen kommuner.csv), kommunerna i länet, och socknar med
    kryssrutor: utan markerad kommun länets alla, med markerade kommuner bara deras
    (steg.socknar_per_kommun), inget ibockat som förval. Användaren bockar i, eller Bocka i
    alla. `valda()` ger de ibockade socknarna (tjanst.Socken)."""

    def __init__(self, vok, tabell: list[dict], parent=None):
        super().__init__(parent)
        self.vok, self.tabell = vok, tabell
        self.setWindowTitle("Välj socknar via län och kommun")
        self.resize(780, 500)
        self._per_kommun: dict[str, list] = {}
        self._socknar: list = []
        self._flera_lan = False
        lay = QVBoxLayout(self)
        intro = QLabel("Välj län: alla länets socknar visas. Klicka på en eller flera kommuner så visas "
                       "bara deras socknar (klicka igen för att avmarkera). Bocka i de du vill ha, eller "
                       "Bocka i alla. Gränserna är dagens: en socken över en kommungräns står under båda "
                       "kommunerna.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        rad = QHBoxLayout()
        self.lan_lista, self.kommun_lista, self.socken_lista = QListWidget(), QListWidget(), QListWidget()
        for rubrik, lista in (("Län", self.lan_lista), ("Kommun", self.kommun_lista), ("Socknar", self.socken_lista)):
            kol = QVBoxLayout()
            kol.addWidget(QLabel(f"<b>{rubrik}</b>"))
            kol.addWidget(lista)
            if lista is self.socken_lista:
                knapprad = QHBoxLayout()
                for text, pa in (("Bocka i alla", True), ("Bocka ur alla", False)):
                    k = QPushButton(text)
                    k.clicked.connect(lambda _=False, pa=pa: self._bocka_alla(pa))
                    knapprad.addWidget(k)
                kol.addLayout(knapprad)
            rad.addLayout(kol, 1)
        lay.addLayout(rad, 1)
        # klick markerar, klick igen avmarkerar, flera går bra -- utan Ctrl (ovana användare)
        self.kommun_lista.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.kommun_lista.setToolTip("Klicka på en kommun så visas dess socknar; klicka igen för att avmarkera. "
                                     "Flera kommuner går bra.")
        self.info = QLabel()
        lay.addWidget(self.info)
        knappar = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        knappar.accepted.connect(self.accept)
        knappar.rejected.connect(self.reject)
        lay.addWidget(knappar)
        if tabell:
            lan = sorted({(r["lanskod"], r["lansnamn"]) for r in tabell}, key=lambda x: x[1])
        else:                                        # utan tabell: arkivets län, inga kommuner
            lan = sorted({(steg.modern_lanskod(l.reg_nummer), l.namn) for l in vok.lan}, key=lambda x: x[1])
        for kod, namn in lan:
            it = QListWidgetItem(namn)
            it.setData(Qt.ItemDataRole.UserRole, kod)
            self.lan_lista.addItem(it)
        self.lan_lista.currentItemChanged.connect(self._lan_vald)
        self.kommun_lista.itemSelectionChanged.connect(self._kommuner_valda)
        self.socken_lista.itemChanged.connect(lambda _it: self._rakna())
        self._rakna()

    def _lan_vald(self, it, _forra=None) -> None:
        self.kommun_lista.clear()
        self.socken_lista.clear()
        self._per_kommun = {}
        if it is None:
            self._rakna()
            return
        kod = it.data(Qt.ItemDataRole.UserRole)
        for kk, namn in kommuner.kommuner_i_lan(self.tabell, kod):
            k = QListWidgetItem(namn)
            k.setData(Qt.ItemDataRole.UserRole, kk)
            self.kommun_lista.addItem(k)
        self._socknar, self._per_kommun = steg.socknar_per_kommun(self.vok, self.tabell, kod)
        self._flera_lan = len({s.lan.namn for s in self._socknar}) > 1   # Skåne: Kristianstad och Malmöhus
        self._fyll_socknar(self._socknar, ibockade=False)

    def _fyll_socknar(self, socknar: list, ibockade: bool) -> None:
        self.socken_lista.blockSignals(True)
        try:
            self.socken_lista.clear()
            for s in socknar:
                r = QListWidgetItem(f"{s.namn} ({s.lan.namn})" if self._flera_lan else s.namn)
                r.setFlags(r.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                r.setCheckState(Qt.CheckState.Checked if ibockade else Qt.CheckState.Unchecked)
                r.setData(Qt.ItemDataRole.UserRole, s)
                self.socken_lista.addItem(r)
        finally:
            self.socken_lista.blockSignals(False)
        self._rakna()

    def _kommuner_valda(self) -> None:
        """Utan markerad kommun syns länets alla socknar; med markerade kommuner bara deras
        (användaren 2026-10-26: "det borde vara så att man bara ser Strömsunds socknar").
        Inget är ibockat som förval: "man får bocka i de man vill ha"; Bocka i alla finns
        för den som vill ha hela kommunen."""
        valda = self.kommun_lista.selectedItems()
        if not valda:
            self._fyll_socknar(self._socknar, ibockade=False)
            return
        sedda, socknar = set(), []
        for k in valda:
            for s in self._per_kommun.get(k.data(Qt.ItemDataRole.UserRole), []):
                if (s.namn, s.lan.namn) not in sedda:
                    sedda.add((s.namn, s.lan.namn))
                    socknar.append(s)
        socknar.sort(key=lambda s: (s.namn.casefold(), s.lan.namn))
        self._fyll_socknar(socknar, ibockade=False)

    def _bocka_alla(self, pa: bool) -> None:
        self.socken_lista.blockSignals(True)
        try:
            for i in range(self.socken_lista.count()):
                self.socken_lista.item(i).setCheckState(Qt.CheckState.Checked if pa else Qt.CheckState.Unchecked)
        finally:
            self.socken_lista.blockSignals(False)
        self._rakna()

    def _rakna(self) -> None:
        n = len(self.valda())
        self.info.setText(f"{_antal(n, 'socken', 'socknar')} ibockade." if n else "Inga socknar ibockade.")

    def valda(self) -> list:
        """De ibockade socknarna (tjanst.Socken), i listans ordning."""
        return [self.socken_lista.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(self.socken_lista.count())
                if self.socken_lista.item(i).checkState() == Qt.CheckState.Checked]


from . import variant  # noqa: E402


class InstallningarDialog(QDialog):
    def __init__(self, inst: _inst.Installningar, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Historiska kartor — inställningar")
        self.inst = inst
        self.falt: dict[str, QLineEdit] = {}
        form = QFormLayout()
        for namn, etikett, mapp in (
                ("arkiv", "Arkiv (register och kartor)", True),
                ("cache", "Tjänstecache (tomt = i arkivet)", True),
                ("referensdata", "Referensdata", True),
                ("socken_och_stad", "Socken och stad (tomt = letas upp)", False),
                ("lan", "Kommun, län och rike (tomt = letas upp)", False),
                ("traktlager", "Traktlager (tomt = fastighetsindelningen, annars ortnamnsregistret)", None),
                ("traktlager_lager", "  lager i traktlagret", "text"),
                ("traktlager_traktfalt", "  fält för traktnamn", "text"),
                ("traktlager_sockenfalt", "  fält för socken (tomt = skärs mot Socken och stad)", "text"),
                ("ortnamn", "Ortnamnsregister, mapp med ortnamn_se.gpkg (tomt = referensdatan eller arkivets referens/ortnamn)", True),
                ("api_nyckel", "API-nyckel för Läs kartan (Anthropic; tomt = knappen är avstängd)", "text")):
            if variant.BARA_HAMTNING and namn == "api_nyckel":
                continue                                    # hämtningen för sig läser inga kartor
            rad = QHBoxLayout()
            if namn == "ortnamn" and not variant.BARA_HAMTNING:
                # Geotorget-kontot före ortnamnsregistret: pluginets eget, så att
                # det går utan Fältunderlaget (KRAV avsnitt 2, 2026-10-08)
                self.konto = self._kontoval(inst)
                form.addRow("Geotorget-konto (QGIS autentisering; fastighetsindelning, "
                            "markhöjd, ortofoton)", self.konto)
            f = QLineEdit(getattr(inst, namn))
            if namn == "api_nyckel":
                f.setEchoMode(QLineEdit.EchoMode.Password)
            self.falt[namn] = f
            rad.addWidget(f)
            if mapp != "text":
                b = QPushButton("…")
                b.clicked.connect(lambda _=False, f=f, m=mapp: self._valj(f, m))
                rad.addWidget(b)
            w = QWidget()
            w.setLayout(rad)
            form.addRow(etikett, w)
        self.hittat = QLabel()
        self.hittat.setWordWrap(True)
        leta = QPushButton("Leta upp i referensdatan")
        leta.clicked.connect(self._leta)
        knappar = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        knappar.accepted.connect(self._ok)
        knappar.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(leta)
        lay.addWidget(self.hittat)
        lay.addWidget(knappar)
        self.resize(760, 0)
        self._leta()

    def _valj(self, falt: QLineEdit, mapp) -> None:
        if mapp is True:
            v = QFileDialog.getExistingDirectory(self, "Välj mapp", falt.text())
        elif mapp is None:
            # Traktlagret kan vara en filgeodatabas (en mapp) eller en fil.
            v = QFileDialog.getExistingDirectory(
                self, "Välj traktlager (.gdb-mapp) — avbryt för att välja en fil",
                falt.text())
            if not v:
                v, _ = QFileDialog.getOpenFileName(self, "Välj traktlager", falt.text(),
                                                   "Vektorlager (*.gpkg *.shp)")
        else:
            v, _ = QFileDialog.getOpenFileName(self, "Välj fil", falt.text(),
                                               "Vektorlager (*.gpkg *.shp)")
        if v:
            falt.setText(v)

    def _leta(self) -> None:
        """Vad som hittas i referensdatan -- och det som ligger i arkivets referensmapp
        (hämtat med kontot), så att raden inte säger "hittas inte" om en fil som används
        (användaren 2026-10-27: Kommun, län och rike låg i arkivet)."""
        from . import fastighet
        r = _inst.hitta(self.falt["referensdata"].text())
        arkiv = self.falt["arkiv"].text()
        arkiv_ref = os.path.join(arkiv, "referens") if arkiv else ""
        lan_i_arkivet = (kommuner.filer(arkiv_ref) or [""])[0] if arkiv_ref else ""
        lan = r.lan or (f"{lan_i_arkivet} (i arkivets referensmapp)" if lan_i_arkivet else "— hittas inte")
        fast = list(r.fastighet) + (fastighet.filer(arkiv_ref) if arkiv_ref else [])
        fast_text = (f"{len(fast)} kommunfil{'er' if len(fast) != 1 else ''} ("
                     + ", ".join(os.path.basename(f) for f in fast[:4]) + (" …" if len(fast) > 4 else "") + ")"
                     if fast else "— inga; trakterna tas då ur ortnamnsregistret")
        reg = _inst.Installningar(arkiv=arkiv, referensdata=self.falt["referensdata"].text(),
                                  ortnamn=self.falt["ortnamn"].text()).ortnamnsregister()
        rader = [f"Socken och stad: {r.socken_och_stad or '— hittas inte'}",
                 f"Kommun, län och rike: {lan}",
                 f"Traktlager: {', '.join(r.traktlager) or '— inga'}",
                 f"Fastighetsindelning: {fast_text}",
                 f"Ortnamnsregistret: {reg or '— hittas inte'}"]
        if r.traktlager and not self.falt["traktlager"].text():
            self.falt["traktlager"].setText(r.traktlager[0])
        self.hittat.setText("\n".join(rader))

    @staticmethod
    def _kontoval(inst) -> QComboBox:
        """Konfigurationerna i QGIS autentisering; förvalt det sparade kontot, eller
        Fältunderlagets när pluginets eget inte är valt."""
        from .underlag import atkomst
        k = QComboBox()
        k.addItem("— inget konto —", "")
        try:
            for i, namn in sorted(atkomst.konfigurationer().items(), key=lambda z: z[1].lower()):
                k.addItem(f"{namn} ({i})", i)
        except Exception:                                  # noqa: BLE001
            pass
        nu = inst.authcfg or atkomst.sparat_id()
        k.setCurrentIndex(max(0, k.findData(nu)))
        return k

    def _ok(self) -> None:
        for namn, f in self.falt.items():
            setattr(self.inst, namn, f.text().strip())
        if getattr(self, "konto", None) is not None:        # inte i hämtningen för sig
            self.inst.authcfg = self.konto.currentData() or ""
        _inst.spara(self.inst)
        self.accept()


# =========================================================================
# Gallra
# =========================================================================

class GallraDialog(QDialog):
    """`klient_fabrik`: funktion som ger en ny klient -- en per trad. For
    prov mot testdatan ges en som svarar ur hk_fixtures."""

    def __init__(self, iface, parent=None, klient_fabrik=None, inst=None):
        super().__init__(parent)
        self.setWindowTitle("Historiska kartor — sök och hämta" if variant.BARA_HAMTNING else "Historiska kartor — gallra")
        self.setModal(False)
        self.iface = iface
        self.inst = inst or _inst.las()
        self.klient_fabrik = klient_fabrik or (lambda: standardklient(self.inst))
        self.vok = None
        self.omrade: str | None = None          # WKT i SWEREF 99 TM
        self.omrade_for_jobb: str | None = None  # området urvalet hämtades för
        self.urvalet: steg.Urval | None = None
        self.jobb: Jobb | None = None
        self.panel: Kontaktkarta | None = None
        self._ritverktyg = None
        self._forra_verktyg = None
        self._omradeslager = None
        self._indexlager = None

        lay = QVBoxLayout(self)
        topp = QHBoxLayout()
        self.saknas = QLabel()
        self.saknas.setWordWrap(True)
        self.saknas.setStyleSheet("color: #a04000")
        topp.addWidget(self.saknas, 1)
        b = QPushButton("Inställningar…")
        b.clicked.connect(self._installningar)
        topp.addWidget(b)
        lay.addLayout(topp)
        lay.addWidget(self._steg1())
        lay.addWidget(self._steg2(), 1)
        lay.addWidget(self._steg3())
        self.resize(720, 820)
        self._uppdatera_saknas()
        self._las_vokabular()

    # ------------------------------------------------------------ steg 1
    def _steg1(self) -> QGroupBox:
        g = QGroupBox("1. Arbetsområde")
        lay = QVBoxLayout(g)
        self.satt = QButtonGroup(self)

        self.r_lager = QRadioButton("Objekt i ett polygonlager")
        self.lager = QgsMapLayerComboBox()
        self.lager.setFilters(QgsMapLayerProxyModel.Filter.PolygonLayer)
        self.bara_valda = QCheckBox("bara valda objekt")
        self.bara_valda.setChecked(True)
        rad = QHBoxLayout()
        rad.addWidget(self.r_lager)
        rad.addWidget(self.lager, 1)
        rad.addWidget(self.bara_valda)
        lay.addLayout(rad)

        self.r_index = QRadioButton("Indexrutor 5 km")
        b = QPushButton("Visa rutorna i vyn")
        b.setToolTip("Lägger rutnätet över kartans vy och väljer markeringsverktyget "
                     "— markera rutorna som ska ingå.")
        b.clicked.connect(self._visa_indexrutor)
        self.index_status = QLabel("")
        rad = QHBoxLayout()
        rad.addWidget(self.r_index)
        rad.addWidget(b)
        rad.addWidget(self.index_status, 1)
        lay.addLayout(rad)

        self.r_rita = QRadioButton("Rita på kartan")
        self.rita_knapp = QPushButton("Rita…")
        self.rita_knapp.setToolTip("Vänsterklick sätter hörn, högerklick avslutar, Esc avbryter")
        self.rita_knapp.clicked.connect(self._rita)
        self.rita_status = QLabel("")
        rad = QHBoxLayout()
        rad.addWidget(self.r_rita)
        rad.addWidget(self.rita_knapp)
        rad.addWidget(self.rita_status, 1)
        lay.addLayout(rad)

        self.r_uttag = QRadioButton("Uttagets arbetsområde")
        self.uttag = QComboBox()
        self.uttag.setEditable(True)
        self.uttag.lineEdit().setPlaceholderText(
            "en mapp med omrade/utredningsomrade.gpkg, eller en ytfil — välj med …")
        self.uttag.setToolTip("Ett arbetsområde ur fil: <mapp>/omrade/utredningsomrade.gpkg eller en ytfil")
        self._fyll_uttag()
        self.uttag.activated.connect(lambda _i: self.r_uttag.setChecked(True))
        b = QPushButton("…")
        b.setToolTip("Välj en uttagsmapp eller en arbetsområdesfil")
        b.clicked.connect(self._valj_uttag)
        rad = QHBoxLayout()
        rad.addWidget(self.r_uttag)
        rad.addWidget(self.uttag, 1)
        rad.addWidget(b)
        if variant.BARA_HAMTNING:
            # Fältunderlagets uttag finns bara hos användaren själv (2026-10-26)
            for w in (self.r_uttag, self.uttag, b):
                w.hide()
        else:
            lay.addLayout(rad)

        # Sökning på namn och på beteckning (2026-10-26: hembygdsforskaren börjar med ett
        # namn, "allt om Lövberga", eller en beteckning ur en bok)
        self.r_ort = QRadioButton("By, gård eller trakt på namn")
        self.ortfalt = QLineEdit()
        self.ortfalt.setPlaceholderText("t.ex. Lövberga — slås upp bland arkivets trakter i hela landet")
        self.ortfalt.setToolTip("Namnet slås upp bland arkivets egna trakter, var det än ligger i landet; "
                                "socknen och trakten bockas i. Finns namnet inte som trakt men du har "
                                "ortnamnsregistret (Ortnamn Nedladdning) slås byar och gårdar upp där, och "
                                "en ruta om 1 km runt varje träff blir arbetsområdet.")
        self.ortfalt.textEdited.connect(lambda _t: self.r_ort.setChecked(True))
        rad = QHBoxLayout()
        rad.addWidget(self.r_ort)
        rad.addWidget(self.ortfalt, 1)
        lay.addLayout(rad)
        self.r_bet = QRadioButton("Aktbeteckning")
        self.betfalt = QLineEdit()
        self.betfalt.setPlaceholderText("t.ex. 23-HÄG-10 eller Y22-2:1 — flera med komma")
        self.betfalt.setToolTip("Socknen tas ur beteckningen, och bara de angivna akterna gallras.")
        self.betfalt.textEdited.connect(lambda _t: self.r_bet.setChecked(True))
        rad = QHBoxLayout()
        rad.addWidget(self.r_bet)
        rad.addWidget(self.betfalt, 1)
        lay.addLayout(rad)

        self.r_namn = QRadioButton("Socknar på namn")
        self.namn = QLineEdit()
        self.namn.setPlaceholderText("skriv en socken, t.ex. Häggenås")
        self.namn_modell = QStringListModel()
        c = QCompleter(self.namn_modell, self)
        c.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        c.setFilterMode(Qt.MatchFlag.MatchContains)
        self.namn.setCompleter(c)
        self.namn.returnPressed.connect(self._lagg_till_namn)
        self.namn.textEdited.connect(lambda _t: self.r_namn.setChecked(True))   # som r_ort och r_bet
        b = QPushButton("Lägg till")
        b.clicked.connect(self._lagg_till_namn)
        # län -> kommun -> socknar för den som inte vet socknen (användaren 2026-10-26)
        valj = QPushButton("Välj…")
        valj.setToolTip("Välj socknar via län och kommun: markera kommuner så bockas deras socknar i.")
        valj.clicked.connect(self._valj_socknar)
        # ta bort en tillagd socken (användaren 2026-10-26): knapp, Delete och dubbelklick
        ta_bort = QPushButton("Ta bort")
        ta_bort.setToolTip("Tar bort den markerade socknen ur listan (också Delete eller dubbelklick)")
        ta_bort.clicked.connect(self._ta_bort_namn)
        self.namnlista = QListWidget()
        self.namnlista.setMaximumHeight(60)
        self.namnlista.setToolTip("Socknar att söka i. Dubbelklick eller Delete tar bort en.")
        self.namnlista.itemDoubleClicked.connect(lambda _it: self._ta_bort_namn())
        self.namnlista.itemClicked.connect(lambda _it: self.r_namn.setChecked(True))
        self.namnlista.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        rad = QHBoxLayout()
        rad.addWidget(self.r_namn)
        rad.addWidget(self.namn, 1)
        rad.addWidget(b)
        rad.addWidget(valj)
        rad.addWidget(ta_bort)
        lay.addLayout(rad)
        lay.addWidget(self.namnlista)

        for i, r in enumerate((self.r_lager, self.r_index, self.r_rita, self.r_uttag,
                               self.r_namn)):
            self.satt.addButton(r, i)
        self.satt.addButton(self.r_ort, 10)
        self.satt.addButton(self.r_bet, 11)
        self.satt.buttonToggled.connect(self._satt_andrat)
        self.r_lager.setChecked(True)

        rad = QHBoxLayout()
        self.omrade_info = QLabel("Arbetsområdet visas i kartan när det är valt.")
        self.omrade_info.setStyleSheet("color: gray")
        self.spara_knapp = QPushButton("Spara område…")
        self.spara_knapp.setEnabled(False)
        self.spara_knapp.clicked.connect(self._spara_omrade)
        oppna = QPushButton("Öppna sparat…")
        oppna.clicked.connect(self._oppna_omrade)
        rad.addWidget(self.omrade_info, 1)
        rad.addWidget(self.spara_knapp)
        rad.addWidget(oppna)
        lay.addLayout(rad)

        # Jobbet (avsnitt 5b): arbetet görs område för område; akterna som
        # blir kvar sparas som jobbets, och Rektifiera visar dem
        rad = QHBoxLayout()
        jobbetikett = QLabel("Jobb:")
        rad.addWidget(jobbetikett)
        self.jobbnamn = QLineEdit()
        self.jobbnamn.setPlaceholderText("namn på jobbet, t.ex. ett område eller en ledning "
                                         "(tomt: uttagets namn eller dagens datum)")
        self.jobbnamn.setToolTip("Akterna som blir kvar efter gallringen sparas som jobbets, med "
                                 "området. I Rektifiera väljs jobbet, och dess kartor visas "
                                 "efter hur mycket av området de berör. Samma namn igen lägger "
                                 "till i jobbet.")
        rad.addWidget(self.jobbnamn, 1)
        if variant.BARA_HAMTNING:
            # jobbet hör till Rektifiera; den fristående hämtningen har inget sådant (2026-10-26)
            jobbetikett.hide()
            self.jobbnamn.hide()
        lay.addLayout(rad)

        hjalp = QPushButton("Hjälp")
        hjalp.setToolTip("Bruksanvisningens avsnitt om Gallra, i ett eget fönster")
        hjalp.clicked.connect(lambda: __import__(__name__.rsplit(".", 1)[0] + ".hjalp", fromlist=["visa"]).visa(
            "gallra", self))
        rad.addWidget(hjalp)
        self.hamta = QPushButton("Hämta socknar och trakter")
        self.hamta.clicked.connect(self._hamta)
        lay.addWidget(self.hamta)
        self._satt_andrat()
        return g

    def _satt_andrat(self, *_) -> None:
        """Knappen under arbetsområdet säger vad som händer (användaren 2026-10-26, för
        ovana: inget hämtas när socknarna valts på namn, trädet fylls ur vokabulären)."""
        if not hasattr(self, "hamta"):
            return
        if self.r_namn.isChecked():
            text, tips = "Visa socknarna", "Fyller listan nedan ur arkivets vokabulär; inget hämtas från nätet."
        elif self.r_bet.isChecked():
            text, tips = "Visa socknen", "Socknen tas ur beteckningen; inget hämtas från nätet."
        elif self.r_ort.isChecked():
            text, tips = "Sök namnet", "Namnet slås upp bland arkivets trakter, i andra hand i ortnamnsregistret."
        else:
            text, tips = "Hämta socknar och trakter", ("Räknar fram vilka socknar och trakter området rör, ur "
                                                       "Socken och stad och traktlagret eller ortnamnsregistret.")
        self.hamta.setText(text)
        self.hamta.setToolTip(tips)

    def _jobb(self) -> dict | None:
        """Jobbet att spara efter gallringen: området urvalet hämtades för.
        Socknar på namn ger inget jobb (inget område)."""
        if variant.BARA_HAMTNING:
            return None                 # jobben hör till Rektifiera (2026-10-26)
        if self.r_namn.isChecked() or not self.omrade_for_jobb:
            return None
        namn = self.jobbnamn.text().strip()
        if not namn and self.r_uttag.isChecked():
            namn = os.path.basename(os.path.normpath(
                self.uttag.currentData() or self.uttag.currentText() or ""))
        if not namn:
            import time
            namn = "Område " + time.strftime("%Y-%m-%d %H.%M")
            self.jobbnamn.setText(namn)
        return {"namn": namn, "omrade": self.omrade_for_jobb,
                "trakt_yta": getattr(self.urvalet, "trakt_yta", {}) or {}}

    # ------------------------------------------------------------ steg 2
    def _steg2(self) -> QGroupBox:
        g = QGroupBox("2. Socknar och trakter")
        lay = QVBoxLayout(g)
        self.trad = QTreeWidget()
        self.trad.setHeaderLabels(["Socken / trakt", "Källa", "Anmärkning"])
        self.trad.setColumnWidth(0, 260)
        self.trad.setColumnWidth(1, 90)
        self.trad.setToolTip("Socknen överst, dess trakter under. En trakt är ett byområde som arkivet "
                             "sorterar akterna under, ungefär en by med sin utmark. Bocka i ”alla akter i "
                             "socknen” för hela socknen, eller enskilda trakter; de två utesluter varandra.")
        self.trad.itemChanged.connect(self._trad_andrad)
        self.trad.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        lay.addWidget(self.trad)
        rad = QHBoxLayout()
        ta_bort = QPushButton("Ta bort markerade")
        ta_bort.setToolTip("Tar bort de markerade socknarna eller trakterna ur listan (också Delete). "
                           "Att bocka ur räcker annars: bara ibockat söks.")
        ta_bort.clicked.connect(self._ta_bort_i_tradet)
        rad.addWidget(ta_bort)
        rad.addStretch(1)
        lay.addLayout(rad)
        self.urvalsinfo = QLabel()
        self.urvalsinfo.setWordWrap(True)
        lay.addWidget(self.urvalsinfo)
        return g

    # ------------------------------------------------------------ steg 3
    def _steg3(self) -> QGroupBox:
        g = QGroupBox("3. Sök, välj och ladda ned" if variant.BARA_HAMTNING else "3. Gallra")
        lay = QVBoxLayout(g)
        rad = QHBoxLayout()
        # Knapparna säger ordningen. Anna 2026-10-27, första användaren: tog kontaktkartans
        # förhandsbilder för nedladdningen, "funderade å vad skillnaden mellan de knapparna var"
        self.gallra_knapp = QPushButton("Sök akter och visa kontaktkartan")
        self.gallra_knapp.clicked.connect(self._gallra)
        self.avbryt_knapp = QPushButton("Avbryt")
        self.avbryt_knapp.setEnabled(False)
        self.avbryt_knapp.clicked.connect(self._avbryt)
        self.ladda_knapp = QPushButton("Ladda ned de kartor du behållit")
        self.ladda_knapp.setToolTip(
            "Kartsidorna i akter du markerat Behåll i kontaktkartan hämtas i full "
            "upplösning som TIFF, lagras förlustfritt (ZSTD) i arkivet under "
            "kartor/<socken>/ och förs in i registret. Redan hämtade sidor hoppas "
            "över. Ca 10 s per sida.")
        self.ladda_knapp.clicked.connect(self._ladda_ned)
        self.aven_textakt = QCheckBox("även textakten")
        self.aven_textakt.setToolTip("Varje behållen akts textsidor -- protokoll, beskrivning, beslut -- "
                                     "sparas också som PDF bredvid kartorna, "
                                     "kartor/<socken>/<åtgärd>_<år>_<beteckning>_<socken>_textakt.pdf.")
        self.lista_knapp = QPushButton("Spara listan…")
        self.lista_knapp.setToolTip("Gallringens akter som CSV: beteckning, år, åtgärd, socken, trakter, "
                                    "sidor, beslut och länk till akten hos Lantmäteriet.")
        self.lista_knapp.setEnabled(False)
        self.lista_knapp.clicked.connect(self._spara_lista)
        self.senaste_kandidater: list = []
        rad.addWidget(self.gallra_knapp, 1)
        rad.addWidget(self.ladda_knapp, 1)
        rad.addWidget(self.aven_textakt)
        rad.addWidget(self.lista_knapp)
        rad.addWidget(self.avbryt_knapp)
        # Vilka sorters kartor (användaren 2026-10-01): en åtgärdstyp i taget,
        # laga skifte först. Gallras före metadatan, utan anrop. Valet minns.
        # Flode (flode.py) ritade inte rutorna i gruppen; en vanlig rad räcker
        typrad = QHBoxLayout()
        atg_etikett = QLabel("Åtgärder:")
        atg_etikett.setToolTip("Vilka slags förrättningar som tas med. Håll pekaren över en för förklaring. "
                               "Stjärnan ★ i kontaktkartan markerar de fyra första, som brukar ha de bästa kartorna.")
        typrad.addWidget(atg_etikett)
        sparat = QgsSettings().value("lm_historiska_kartor/gallra_atgarder", None)
        if sparat is None:                       # det äldre valet, bara prioriterade
            # arkeologens urval som förval bara i hela verktyget; den fristående tar alla
            # åtgärder tills användaren väljer (2026-10-26)
            prio = QgsSettings().value("lm_historiska_kartor/gallra_bara_prioriterade",
                                       not variant.BARA_HAMTNING, type=bool)
            sparat = list(PRIORITERADE) if prio else [t for t, _ in TYPER]
        elif isinstance(sparat, str):
            sparat = [sparat] if sparat else []
        self.atgard_rutor = {}
        from .prioritet import FORKLARING as _forklaring
        for typ, text in TYPER:
            ruta = QCheckBox(text)
            ruta.setToolTip(_forklaring.get(typ, ""))
            ruta.setChecked(typ in sparat)
            ruta.toggled.connect(self._spara_atgarder)
            self.atgard_rutor[typ] = ruta
            typrad.addWidget(ruta)
        # Årtal som intervall (användaren 2026-10-26: "tror årtal ska vara något slags
        # intervall, inte exakt"; "lämnas det tomt är det alla"): tomt fält = ingen gräns,
        # akter utan känt år behålls; gallras före metadatan; valet minns
        sparat_ar = QgsSettings().value("lm_historiska_kartor/gallra_ar", None) or ["", ""]
        if isinstance(sparat_ar, str):
            sparat_ar = [sparat_ar, ""]
        self.ar_fran, self.ar_till = QLineEdit(str(sparat_ar[0] or "")), QLineEdit(str(sparat_ar[1] or ""))
        typrad.addSpacing(12)
        for text, f in (("Årtal (fr.o.m.)", self.ar_fran), ("Årtal (t.o.m.)", self.ar_till)):
            f.setMaximumWidth(56)
            f.setValidator(QIntValidator(1000, 2100, f))
            f.setToolTip("Bara akter vars år ligger i intervallet, t.ex. 1820–1870. Tomt fält betyder "
                         "ingen gräns, båda tomma alla år; akter utan känt år behålls.")
            f.editingFinished.connect(self._spara_ar)
            typrad.addWidget(QLabel(text))
            typrad.addWidget(f)
        typrad.addStretch(1)
        lay.addLayout(typrad)
        lay.addLayout(rad)
        ordning = QLabel("Först Sök akter, sedan ✓ Behåll i kontaktkartan, sist Ladda ned. "
                         "Kontaktkartan visar små förhandsbilder; kartorna i full upplösning "
                         "hämtas av Ladda ned, som TIFF till kartor/<socken>/ i arkivmappen.")
        ordning.setStyleSheet("color: gray")
        ordning.setWordWrap(True)
        lay.addWidget(ordning)
        self.forlopp = QProgressBar()
        self.forlopp.setRange(0, 100)
        self.status = QLabel()
        if variant.BARA_HAMTNING:
            # synlig friskrivning i panelen, som matselfs plugin (användaren 2026-10-27)
            fri = QLabel("Fristående tillägg, inte från Lantmäteriet.")
            fri.setStyleSheet("color: gray")
            lay.addWidget(fri)
        self.status.setWordWrap(True)
        lay.addWidget(self.forlopp)
        lay.addWidget(self.status)
        return g

    # ------------------------------------------------------ installningar
    def _uppdatera_saknas(self) -> None:
        s = self.inst.saknas()
        self.saknas.setText("\n".join(s))
        self.saknas.setVisible(bool(s))
        har_karta = bool(self.inst.sokvag_socken_och_stad())
        for r in (self.r_lager, self.r_index, self.r_rita, self.r_uttag):
            r.setEnabled(har_karta)
        if not har_karta:
            self.r_namn.setChecked(True)
        self.gallra_knapp.setEnabled(bool(self.inst.arkiv))
        self.ladda_knapp.setEnabled(bool(self.inst.arkiv))

    def _installningar(self) -> None:
        d = InstallningarDialog(self.inst, self)
        if d.exec():
            self._uppdatera_saknas()

    # ---------------------------------------------------------- vokabular
    def _las_vokabular(self) -> None:
        self._starta("Läser arkivens socknar och trakter",
                     lambda f, a: steg.vokabular(self.klient_fabrik(), f, a),
                     self._vokabular_klar)

    def _vokabular_klar(self, vok) -> None:
        self.vok = vok
        self.namn_modell.setStringList(sorted(
            f"{s.namn} ({l.namn})" for l in vok.lan for s in l.socknar
            if s.trakter))
        self.status.setText("Klar att välja arbetsområde.")

    def _ta_bort_namn(self) -> None:
        """De markerade socknarna ur namnlistan (Ta bort, Delete, dubbelklick)."""
        for it in self.namnlista.selectedItems():
            self.namnlista.takeItem(self.namnlista.row(it))

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            if self.namnlista.hasFocus():
                self._ta_bort_namn()
                return
            if self.trad.hasFocus():
                self._ta_bort_i_tradet()
                return
        super().keyPressEvent(e)

    def _ta_bort_i_tradet(self) -> None:
        """Ta bort de markerade raderna i trädet (knappen Ta bort markerade, Delete): en
        socken med sina trakter, eller en enskild trakt (användaren 2026-10-26: "även i
        socknar å trakter måste man kunna ta bort"). Raden ”alla akter i socknen” tas inte
        bort, den bockas ur i stället."""
        valda = self.trad.selectedItems()
        toppar = [it for it in valda if it.parent() is None]
        for it in valda:
            p = it.parent()
            if p is None or p in toppar:
                continue
            if it.data(0, ROLL_ALLA):
                it.setCheckState(0, Qt.CheckState.Unchecked)
            else:
                p.removeChild(it)
        for it in toppar:
            self.trad.takeTopLevelItem(self.trad.indexOfTopLevelItem(it))

    def _valj_socknar(self) -> None:
        """Välj… vid Socknar på namn: län -> kommun -> socknar (ValjSocknarDialog); de
        ibockade läggs i namnlistan, utan dubbletter."""
        if self.vok is None:
            QMessageBox.information(self, "Välj socknar", "Arkivets vokabulär är inte hämtad än.")
            return
        # arbetsområdet är ett sätt i taget (användaren 2026-10-26: "så kör man på den söken
        # vi gjort nu ska inte indexrutor kunna vara markerad"): Välj… betyder socknar på namn
        self.r_namn.setChecked(True)
        d = ValjSocknarDialog(self.vok, kommuner.las_tabell(), self)
        if not d.exec():
            return
        finns = {self.namnlista.item(i).text() for i in range(self.namnlista.count())}
        valda = d.valda()
        for s in valda:
            t = f"{s.namn} ({s.lan.namn})"
            if t not in finns:
                self.namnlista.addItem(t)
                finns.add(t)
        if valda:
            self.r_namn.setChecked(True)

    def _lagg_till_namn(self) -> None:
        text = self.namn.text().strip()
        if not text or self.vok is None:
            return
        if "(" in text:
            namn, lan = text[:-1].split(" (", 1)
            s = self.vok.socken_i_lan(lan, namn)
        else:
            try:
                s = self.vok.socken(text)
            except KeyError as e:
                QMessageBox.information(self, "Socken", str(e.args[0]))
                return
        if s is None:
            return
        self.namnlista.addItem(f"{s.namn} ({s.lan.namn})")
        self.namn.clear()
        self.r_namn.setChecked(True)

    # --------------------------------------------------------- omradet
    def _rita(self) -> None:
        from .rita import RitaYta
        canvas = self.iface.mapCanvas()
        self._forra_verktyg = canvas.mapTool()
        self._ritverktyg = RitaYta(canvas)
        self._ritverktyg.klar.connect(self._ritat)
        self._ritverktyg.avbruten.connect(self._ritning_klar)
        canvas.setMapTool(self._ritverktyg)
        self.r_rita.setChecked(True)
        self.rita_status.setText("Rita i kartan: vänsterklick hörn, högerklick klart.")

    def _ritat(self, geom: QgsGeometry) -> None:
        crs = self.iface.mapCanvas().mapSettings().destinationCrs()
        self.omrade = till_sweref(geom, crs).asWkt()
        self.rita_status.setText(f"Ritad yta, {till_sweref(geom, crs).area() / 1e6:.1f} km².")
        self._ritning_klar()
        self.visa_omrade(self.omrade)

    def _ritning_klar(self) -> None:
        canvas = self.iface.mapCanvas()
        if self._forra_verktyg is not None:
            canvas.setMapTool(self._forra_verktyg)
        else:
            canvas.unsetMapTool(self._ritverktyg)

    # ------------------------------------------------- omradet i kartan
    @staticmethod
    def _lager_i_projektet(lager):
        """Lagret om det fortfarande finns i projektet, annars None."""
        if lager is None:
            return None
        try:
            return lager if QgsProject.instance().mapLayer(lager.id()) else None
        except RuntimeError:                # borttaget ur projektet
            return None

    def _grupp(self):
        rot = QgsProject.instance().layerTreeRoot()
        return rot.findGroup(GRUPP) or rot.insertGroup(0, GRUPP)

    @staticmethod
    def _gruppens_lager(namn: str) -> list:
        """Lagren med `namn` i pluginets grupp -- också de som ett tidigare
        Gallra-fönster lade dit. Fönstret minns bara sina egna, så rutorna och
        området från förra gången låg kvar under de nya (användaren 2026-10-02)."""
        g = QgsProject.instance().layerTreeRoot().findGroup(GRUPP)
        if g is None:
            return []
        return [n.layer() for n in g.findLayers() if n.layer() is not None
                and n.layer().name() == namn]

    def visa_omrade(self, wkt: str) -> None:
        """Arbetsomradet som lager i projektet, sa att det syns och kan sparas."""
        lager = self._lager_i_projektet(self._omradeslager)
        if lager is None:
            gamla = self._gruppens_lager(OMRADESLAGER)
            lager = gamla[0] if gamla else None
            self._omradeslager = lager
        for x in self._gruppens_lager(OMRADESLAGER):
            if lager is not None and x.id() != lager.id():
                QgsProject.instance().removeMapLayer(x.id())
        if lager is None:
            lager = QgsVectorLayer("MultiPolygon?crs=EPSG:3006", OMRADESLAGER, "memory")
            lager.renderer().setSymbol(QgsFillSymbol.createSimple(
                {"color": "30,100,200,35", "outline_color": "30,100,200",
                 "outline_width": "0.8"}))
            QgsProject.instance().addMapLayer(lager, False)
            self._grupp().insertLayer(0, lager)
            self._omradeslager = lager
        pr = lager.dataProvider()
        pr.truncate()
        f = QgsFeature()
        f.setGeometry(QgsGeometry.fromWkt(wkt))
        pr.addFeatures([f])
        lager.updateExtents()
        lager.triggerRepaint()
        self.spara_knapp.setEnabled(True)
        self.omrade_info.setText(
            f"Arbetsområdet: {QgsGeometry.fromWkt(wkt).area() / 1e6:.1f} km², "
            f"visas som lagret ”{OMRADESLAGER}”.")

    def _spara_omrade(self) -> None:
        lager = self._lager_i_projektet(self._omradeslager)
        if lager is None:
            return
        fil, _ = QFileDialog.getSaveFileName(self, "Spara arbetsområdet", "",
                                             "GeoPackage (*.gpkg)")
        if not fil:
            return
        if not fil.lower().endswith(".gpkg"):
            fil += ".gpkg"
        self.spara_omrade(fil)

    def spara_omrade(self, fil: str) -> None:
        lager = self._lager_i_projektet(self._omradeslager)
        opt = QgsVectorFileWriter.SaveVectorOptions()
        opt.driverName = "GPKG"
        opt.layerName = "arbetsomrade"
        opt.actionOnExistingFile = \
            QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile
        svar = QgsVectorFileWriter.writeAsVectorFormatV3(
            lager, fil, QgsProject.instance().transformContext(), opt)
        if svar[0] != QgsVectorFileWriter.WriterError.NoError:
            QMessageBox.warning(self, "Spara område", f"Kunde inte spara: {svar[1]}")
            return
        self.omrade_info.setText(f"Sparat: {fil}")

    def _oppna_omrade(self) -> None:
        fil, _ = QFileDialog.getOpenFileName(self, "Öppna arbetsområde", "",
                                             "Vektorlager (*.gpkg *.shp)")
        if fil:
            self.oppna_omrade(fil)

    def oppna_omrade(self, fil: str) -> None:
        """Lagg ett sparat omrade i kartan och anvand alla dess objekt."""
        lager = QgsVectorLayer(fil, os.path.splitext(os.path.basename(fil))[0], "ogr")
        if not lager.isValid():
            QMessageBox.warning(self, "Öppna arbetsområde", f"{fil} går inte att öppna.")
            return
        QgsProject.instance().addMapLayer(lager, False)
        self._grupp().insertLayer(0, lager)
        self.lager.setLayer(lager)
        self.bara_valda.setChecked(False)
        self.r_lager.setChecked(True)

    def _visa_indexrutor(self) -> None:
        """Rutnatet over kartans vy, som i Faltunderlaget: ett minneslager med
        bara de rutor som syns, hogst indexrutor.TAK."""
        c = self.iface.mapCanvas()
        e = c.extent()
        if c.mapSettings().destinationCrs() != SWEREF:
            e = QgsCoordinateTransform(c.mapSettings().destinationCrs(), SWEREF,
                                       QgsProject.instance()).transformBoundingBox(e)
        # alla rutnät och det förra området bort: en ny markering börjar
        for gammalt in self._gruppens_lager("Indexrutor 5 km"):
            QgsProject.instance().removeMapLayer(gammalt.id())
        for omr in self._gruppens_lager(OMRADESLAGER):
            omr.dataProvider().truncate()
            omr.triggerRepaint()
        lager, n = indexrutor.rutnatslager(e.xMinimum(), e.yMinimum(),
                                           e.xMaximum(), e.yMaximum())
        lager.renderer().setSymbol(QgsFillSymbol.createSimple(
            {"color": "0,0,0,0", "outline_color": "0,90,200", "outline_width": "0.4"}))
        QgsProject.instance().addMapLayer(lager, False)
        self._grupp().insertLayer(0, lager)
        lager.selectionChanged.connect(self._rutor_markerade)
        self._indexlager = lager
        self.iface.setActiveLayer(lager)
        try:
            self.iface.actionSelect().trigger()
        except AttributeError:
            pass
        self.r_index.setChecked(True)
        if n > indexrutor.TAK:
            self.index_status.setText(f"{indexrutor.TAK}+ rutor — zooma in, "
                                      "rutnätet är avkortat")
        else:
            self.index_status.setText(f"{n} rutor i vyn — markera dem i kartan.")

    def _rutor_markerade(self, *_):
        lager = self._lager_i_projektet(self._indexlager)
        if lager is None:
            return
        _, bet = indexrutor.yta_av(lager)
        if not bet:
            self.index_status.setText("Inga rutor markerade.")
        else:
            visa = ", ".join(bet[:6]) + (" …" if len(bet) > 6 else "")
            self.index_status.setText(
                f"{_antal(len(bet), 'ruta', 'rutor')} markerade ({len(bet) * 25} km²): {visa}")

    def _fyll_uttag(self) -> None:
        """Listan börjar tom: uttag väljs med … (Fältunderlagets målkatalog läses
        inte längre, KRAV avsnitt 2, 2026-10-08)."""
        self.uttag.clear()
        self.uttag.setCurrentIndex(-1)

    def _valj_uttag(self) -> None:
        v = QFileDialog.getExistingDirectory(self, "Välj uttagsmapp",
                                             self.uttag.currentData() or "")
        if not v:
            v, _ = QFileDialog.getOpenFileName(self, "Välj arbetsområdesfil", "",
                                               "GeoPackage (*.gpkg)")
        if v:
            self.uttag.addItem(os.path.basename(v.rstrip("/\\")), v)
            self.uttag.setCurrentIndex(self.uttag.count() - 1)
            self.r_uttag.setChecked(True)

    def omrade_wkt(self) -> str | None:
        """Arbetsomradet i SWEREF 99 TM, ur det satt som ar valt."""
        if self.r_rita.isChecked():
            return self.omrade
        if self.r_index.isChecked():
            lager = self._lager_i_projektet(self._indexlager)
            if lager is None:
                return None
            geom, _ = indexrutor.yta_av(lager)
            return till_sweref(geom, lager.crs()).asWkt() if geom else None
        if self.r_lager.isChecked():
            lager = self.lager.currentLayer()
            if lager is None:
                return None
            objekt = (lager.selectedFeatures() if self.bara_valda.isChecked()
                      else lager.getFeatures())
            geom = QgsGeometry.unaryUnion([f.geometry() for f in objekt])
            if geom is None or geom.isEmpty():
                return None
            return till_sweref(geom, lager.crs()).asWkt()
        if self.r_uttag.isChecked():
            f = uttagets_omrade(self.uttag.currentData() or self.uttag.currentText())
            if not f:
                return None
            lager = QgsVectorLayer(f, "omrade", "ogr")
            geom = QgsGeometry.unaryUnion([x.geometry() for x in lager.getFeatures()])
            return till_sweref(geom, lager.crs()).asWkt() if geom else None
        return None

    # ---------------------------------------------------------- hamta
    def _hamta(self) -> None:
        if self.vok is None:
            self.status.setText("Vokabulären läses fortfarande in …")
            return
        if self.r_namn.isChecked():
            self._visa_namn()
            return
        if self.r_bet.isChecked():
            self._visa_beteckningar()
            return
        if self.r_ort.isChecked():
            self._visa_ortnamn()
            return
        wkt = self.omrade_wkt()
        if not wkt:
            QMessageBox.information(self, "Arbetsområde",
                                    "Inget arbetsområde — markera indexrutor eller "
                                    "objekt, rita en yta eller ange ett uttag.")
            return
        self.visa_omrade(wkt)
        self.omrade_for_jobb = wkt
        self._starta("Hämtar socknar och trakter",
                     lambda f, a: steg.urval_for_omrade(self.inst, self.vok, wkt, f, a),
                     self._visa_urval)

    ORT_RUTA_M = 500.0      # halva sidan på rutan kring ett namn: 1 km, som en by

    def _visa_ortnamn(self) -> None:
        """By, gård eller trakt på namn: först arkivets egna trakter (vokabulären, som alla
        har), socknen och trakten ibockade; annars ortnamnsregistret som reserv, där en ruta
        om 1 km kring varje träff blir arbetsområdet."""
        from types import SimpleNamespace
        namn = self.ortfalt.text().strip()
        if not namn:
            QMessageBox.information(self, "Namn", "Skriv namnet på byn, gården eller trakten.")
            return
        traffar = steg.trakter_for_namn(self.vok, namn)
        if traffar:
            self.trad.clear()
            sedda = set()
            flera = len({id(s_) for s_, _ in traffar}) > 1
            for s_, t in traffar:
                if id(s_) not in sedda:
                    sedda.add(id(s_))
                    top = self._socken_rad(f"{s_.namn} ({s_.lan.namn})", s_, "namn")
                    if flera:
                        # samma namn i flera socknar: ingen förbockad, så att inte fem socknar
                        # söks av misstag (Lövberga finns i 5, 2026-10-26)
                        top.setCheckState(0, Qt.CheckState.Unchecked)
                    self._alla_rad(top, False)
                else:
                    top = next(self.trad.topLevelItem(i) for i in range(self.trad.topLevelItemCount())
                               if self.trad.topLevelItem(i).data(0, ROLL_SOCKEN) is s_)
                it = QTreeWidgetItem([t.namn, steg.kalla_rad("arkivet"), ""])
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                it.setCheckState(0, Qt.CheckState.Checked)
                it.setData(0, ROLL_TRAKT, SimpleNamespace(trakt=t.namn, socken=s_.namn, via_socken="",
                                                          kalla="arkivet", grad="exakt", kalla_namn=t.namn))
                top.addChild(it)
            self.urvalsinfo.setText(f"”{namn}” finns som trakt i {_antal(len(sedda), 'socken', 'socknar')} i "
                                    "arkivet. " + ("Bocka i din socken, och gallra." if flera else "Gallra."))
            self.status.setText("Bekräfta socken och trakt, och gallra.")
            return
        wkt = self._ort_omrade(namn)
        if not wkt:
            return
        self.visa_omrade(wkt)
        self.omrade_for_jobb = wkt
        self._starta("Hämtar socknar och trakter",
                     lambda f, a: steg.urval_for_omrade(self.inst, self.vok, wkt, f, a),
                     self._visa_urval)

    def _ort_omrade(self, namn: str) -> str | None:
        """Reserven för ett namn som inte är en trakt i arkivet: en ruta om 1 km kring varje
        ställe med det namnet i ortnamnsregistret, som arbetsområde."""
        reg = self.inst.ortnamnsregister()
        if not reg:
            QMessageBox.information(self, "Namn", f"”{namn}” finns inte som trakt i arkivet. Byar och gårdar "
                                    "som inte är trakter kan slås upp i ortnamnsregistret (Ortnamn Nedladdning, "
                                    "ortnamn_se.gpkg) om du har det -- se Kom igång. Annars: ange socknen och "
                                    "sök på alla akter i den.")
            return None
        lagen = ortnamn.namn_overallt(reg, namn)
        if not lagen:
            QMessageBox.information(self, "Namn", f"”{namn}” finns varken som trakt i arkivet eller som by, "
                                    "gård eller trakt i ortnamnsregistret. Pröva en annan stavning.")
            return None
        if len(lagen) > 20:
            QMessageBox.information(self, "Namn", f"”{namn}” finns på {len(lagen)} ställen i landet. "
                                    "Ange socknen i stället (Socknar på namn) eller rita en yta.")
            return None
        d = self.ORT_RUTA_M
        rutor = [QgsGeometry.fromWkt(f"POLYGON(({n.x - d} {n.y - d},{n.x + d} {n.y - d},{n.x + d} {n.y + d},"
                                     f"{n.x - d} {n.y + d},{n.x - d} {n.y - d}))") for n in lagen]
        self.status.setText(f"”{namn}”: {len(lagen)} ställe(n) i ortnamnsregistret, "
                            + ", ".join(sorted({n.socken for n in lagen})) + ".")
        return QgsGeometry.unaryUnion(rutor).asWkt()

    def _beteckningar(self) -> list[str]:
        return [b.strip() for b in re.split(r"[,;\s]+", self.betfalt.text()) if b.strip()]

    def _visa_beteckningar(self) -> None:
        """Aktbeteckning: socknen ur beteckningen, "alla akter" förvalt; gallringen tar sedan
        bara de angivna akterna (steg.Val.beteckningar)."""
        self.trad.clear()
        bet = self._beteckningar()
        if not bet:
            QMessageBox.information(self, "Aktbeteckning", "Skriv en aktbeteckning, t.ex. 23-HÄG-10 eller Y22-2:1.")
            return
        okanda, sedda = [], set()
        for b in bet:
            s = steg.socken_for_beteckning(self.vok, b)
            if s is None:
                okanda.append(b)
                continue
            if id(s) in sedda:
                continue
            sedda.add(id(s))
            top = self._socken_rad(s.namn, s, "beteckning")
            self._alla_rad(top, True)
        rader = [f"{_antal(len(bet) - len(okanda), 'akt', 'akter')} att söka: " + ", ".join(b for b in bet if b not in okanda) + "."]
        if okanda:
            rader.append("Känns inte igen: " + ", ".join(okanda) + " (formen är 23-HÄG-10 för REG och Y22-2:1 för LMS, "
                         "och socknen måste finnas i arkivet).")
        self.urvalsinfo.setText("\n".join(rader))
        self.status.setText("Gallra: bara de angivna akterna tas med.")

    def _spara_lista(self) -> None:
        """Gallringens akter som CSV (2026-10-26)."""
        from .gallra import skriv_csv
        if not self.senaste_kandidater:
            return
        # förslag i arkivet med dagens datum, och efteråt hela sökvägen med en knapp till
        # mappen (användaren 2026-10-27: listan hamnade i traktlagrets gdb-mapp, som var
        # fildialogens senaste, och "var hamnar de?")
        from datetime import date
        forslag = os.path.join(self.inst.arkiv or "", f"lista_{date.today().isoformat()}.csv")
        fil, _ = QFileDialog.getSaveFileName(self, "Spara listan", forslag, "CSV (*.csv)")
        if not fil:
            return
        try:
            n = skriv_csv(fil, self.senaste_kandidater)
        except OSError as e:
            QMessageBox.warning(self, "Spara listan", f"Gick inte: {e}")
            return
        self.status.setText(f"{_antal(n, 'akt', 'akter')} sparade i {fil}")
        ruta = QMessageBox(self)
        ruta.setWindowTitle("Spara listan")
        ruta.setText(f"{_antal(n, 'akt', 'akter')} sparade i\n{fil}")
        oppna = ruta.addButton("Öppna mappen", QMessageBox.ButtonRole.ActionRole)
        ruta.addButton(QMessageBox.StandardButton.Ok)
        ruta.exec()
        if ruta.clickedButton() is oppna:
            from .kontaktkarta import oppna_fil
            oppna_fil(os.path.dirname(fil))

    def _visa_namn(self) -> None:
        """Socknar pa namn: inga trakter ur kartan, "alla akter" forvalt."""
        self.trad.clear()
        for i in range(self.namnlista.count()):
            text = self.namnlista.item(i).text()
            namn, lan = text[:-1].split(" (", 1)
            s = self.vok.socken_i_lan(lan, namn)
            if s is None:
                continue
            top = self._socken_rad(s.namn, s, "namn")
            self._alla_rad(top, True)
            self._trakter_ur_vokabularen(top, s)
        self.urvalsinfo.setText("Socknar valda på namn: alla akter i socknen är förvalda. Bocka i trakter "
                                "i stället för att smalna av; en trakt är ungefär en by med sin utmark.")

    def _trad_andrad(self, it: QTreeWidgetItem, kolumn: int) -> None:
        """"Alla akter i socknen" och trakterna utesluter varandra (användaren 2026-10-26,
        Karlskoga: både "alla akter" och Bråten ibockade, och alla vann tyst): bockas en
        trakt i släpps "alla", bockas "alla" i släpps trakterna. Socknen bockas i när
        något under den bockas i."""
        if kolumn != 0 or it.parent() is None or it.checkState(0) != Qt.CheckState.Checked:
            return
        top = it.parent()
        self.trad.blockSignals(True)
        try:
            ar_alla = bool(it.data(0, ROLL_ALLA))
            for j in range(top.childCount()):
                c = top.child(j)
                if c is it:
                    continue
                if ar_alla or c.data(0, ROLL_ALLA):
                    c.setCheckState(0, Qt.CheckState.Unchecked)
            if top.checkState(0) != Qt.CheckState.Checked:
                top.setCheckState(0, Qt.CheckState.Checked)
        finally:
            self.trad.blockSignals(False)

    def _socken_rad(self, text: str, data, hur: str) -> QTreeWidgetItem:
        top = QTreeWidgetItem([text, "", hur])
        top.setFlags(top.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        top.setCheckState(0, Qt.CheckState.Checked)
        top.setData(0, ROLL_SOCKEN, data)
        self.trad.addTopLevelItem(top)
        top.setExpanded(True)
        return top

    def _alla_rad(self, top: QTreeWidgetItem, pa: bool) -> None:
        it = QTreeWidgetItem([ALLA, "", "utan traktfilter"])
        it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        it.setCheckState(0, Qt.CheckState.Checked if pa else Qt.CheckState.Unchecked)
        it.setData(0, ROLL_ALLA, True)
        top.addChild(it)

    def _trakter_ur_vokabularen(self, top, socken) -> None:
        for t in socken.trakter:
            it = QTreeWidgetItem([t.namn, steg.kalla_rad("arkivet"), ""])
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(0, Qt.CheckState.Unchecked)
            it.setData(0, ROLL_TRAKT, urval.TraktIOmrade(
                socken.namn, t.namn, t.namn, "exakt", "arkivet", arkivsocken=socken))
            top.addChild(it)

    def _visa_urval(self, u: steg.Urval) -> None:
        self.urvalet = u
        self.trad.clear()
        for s in u.socknar:
            top = self._socken_rad(f"{s.namn}", s, HUR.get(s.hur, s.hur))
            if s.socken is not None and s.socken.namn != s.namn:
                top.setText(2, f"i arkivet: {s.socken.namn}")
            if s.hur == urval.FLERA:
                top.setText(2, "söks i: " + ", ".join(
                    f"{k.namn} ({k.lan.namn})" for k in s.kandidater))
            if s.socken is None and s.hur != urval.FLERA:
                self._valjare(top, s)
            egna = [t for t in u.trakter if t.via_socken == "" and s.socken is not None
                    and t.socken == s.socken.namn]
            lanade = [t for t in u.trakter if t.via_socken and s.socken is not None
                      and t.via_socken == s.socken.namn]
            self._alla_rad(top, not egna and not lanade)
            if not egna and not lanade and s.socken is not None and s.hur != urval.FLERA:
                # ingen trakt ur kartan för socknen (inget traktlager eller register, eller
                # ett traktlager som inte täcker länet; 2026-10-26): arkivets egna trakter att
                # bocka i, som för socknar på namn
                self._trakter_ur_vokabularen(top, s.socken)
            for t in egna + lanade:
                osaker = t.grad == "normaliserad" or bool(t.via_socken)
                anm = []
                if t.grad == "normaliserad":
                    anm.append(f"normaliserad från {t.kalla_namn}")
                if t.via_socken:
                    anm.append(f"i arkivet under {t.socken}")
                namn = f"{t.trakt} ({t.socken})" if t.via_socken else t.trakt
                it = QTreeWidgetItem([namn, steg.kalla_rad(t.kalla), "; ".join(anm)])
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                it.setCheckState(0, Qt.CheckState.Checked)
                it.setData(0, ROLL_TRAKT, t)
                if osaker:
                    for c in range(3):
                        it.setBackground(c, QBrush(GUL))
                top.addChild(it)
        kalla = steg.kalla_text(u.kalla)
        rader = [f"{_antal(len(u.socknar), 'socken', 'socknar')}, "
                 f"{_antal(len(u.trakter), 'trakt', 'trakter')} ur {kalla}. "
                 "Gula är osäkra: normaliserade namn, eller trakter som arkivet "
                 "har under en grannsocken."] + u.meddelanden
        self.urvalsinfo.setText("\n".join(rader))
        self.status.setText("Bekräfta socknar och trakter, och gallra.")

    def _valjare(self, top, s) -> None:
        """Rullgardin for en socken som inte ar entydig i arkivet."""
        box = QComboBox()
        box.addItem("— välj socken i arkivet —", None)
        kand = s.kandidater or [x for l in self.vok.lan
                                if l.reg_nummer in urval._SAMMANSLAGNA.get(
                                    s.lanskod, {s.lanskod})
                                for x in l.socknar]
        for k in kand:
            box.addItem(f"{k.namn} ({k.lan.namn})", k)
        box.addItem("finns inte i arkivet", "ingen")
        box.currentIndexChanged.connect(lambda _i, s=s, box=box: self._valt(s, box))
        top.setCheckState(0, Qt.CheckState.Unchecked)
        self.trad.setItemWidget(top, 2, box)

    def _valt(self, s, box: QComboBox) -> None:
        v = box.currentData()
        if v is None or not self.inst.sockenlager:
            return
        sockenlager.valj(self.inst.sockenlager, s.kod, [] if v == "ingen" else [v])
        self._hamta()                  # hamta om med valet

    def _spara_atgarder(self, _=False) -> None:
        QgsSettings().setValue("lm_historiska_kartor/gallra_atgarder",
                               [t for t, r in self.atgard_rutor.items() if r.isChecked()])

    def _spara_ar(self) -> None:
        QgsSettings().setValue("lm_historiska_kartor/gallra_ar",
                               [self.ar_fran.text().strip(), self.ar_till.text().strip()])

    def _ar(self) -> tuple | None:
        """Årintervallet (fr.o.m., t.o.m.) ur fälten; en gräns kan saknas, båda tomma = None (alla)."""
        fran = int(self.ar_fran.text()) if self.ar_fran.text().strip().isdigit() else None
        till = int(self.ar_till.text()) if self.ar_till.text().strip().isdigit() else None
        return None if fran is None and till is None else (fran, till)

    # ------------------------------------------------------------- valet
    def val(self) -> steg.Val:
        """Det som ar ibockat, i den form gallringen tar emot."""
        val = steg.Val()
        valda = tuple(t for t, r in self.atgard_rutor.items() if r.isChecked())
        val.atgarder = None if len(valda) == len(self.atgard_rutor) else valda
        val.beteckningar = self._beteckningar() if self.r_bet.isChecked() else []
        val.ar = self._ar()
        sedda: set[int] = set()

        def lagg_till(socken):
            if id(socken) not in sedda:
                sedda.add(id(socken))
                val.socknar.append(socken)

        for i in range(self.trad.topLevelItemCount()):
            top = self.trad.topLevelItem(i)
            if top.checkState(0) != Qt.CheckState.Checked:
                continue
            data = top.data(0, ROLL_SOCKEN)
            if isinstance(data, urval.SockenIOmrade):
                if data.hur == urval.FLERA:
                    arkivsocknar = list(data.kandidater)
                elif data.socken is not None:
                    arkivsocknar = [data.socken]
                else:
                    continue
            else:
                arkivsocknar = [data]
            alla = False
            egna: list[str] = []
            for j in range(top.childCount()):
                c = top.child(j)
                if c.checkState(0) != Qt.CheckState.Checked:
                    continue
                if c.data(0, ROLL_ALLA):
                    alla = True
                    continue
                t = c.data(0, ROLL_TRAKT)
                if t.via_socken:
                    val.lanade.append(t)
                else:
                    egna.append(t.trakt)
            for s in arkivsocknar:
                if alla:
                    lagg_till(s)
                    val.trakter.pop(s.namn, None)
                elif egna and len(arkivsocknar) == 1:
                    lagg_till(s)
                    val.trakter[s.namn] = egna
        return val

    # ------------------------------------------------------------ gallra
    def _gallra(self) -> None:
        v = self.val()
        if not v.socknar and not v.lanade:
            QMessageBox.information(self, "Gallra", "Inget att gallra — bocka i "
                                    "socknar och trakter, eller alla akter i en socken.")
            return
        jobb = self._jobb()
        self._starta("Gallrar",
                     lambda f, a: steg.gallra(self.inst, self.klient_fabrik, v, f, a, jobb=jobb),
                     self._gallrat)

    def _gallrat(self, res) -> None:
        self.senaste_kandidater = list(res.kandidater)
        self.lista_knapp.setEnabled(bool(res.kandidater))
        n = res.antal()
        delar = [f"{n.get('sökta', 0)} akter sökta"]
        for nyckel, text in ((INGEN_KARTA, "utan karta"), (INGA_KARTSIDOR, "utan kartsida"),
                             (ANNAN_TRAKT, "annan trakt"), (ANNAN_ATGARD, "annan åtgärd"),
                             (ANNAT_AR, "annat år"), (KASTAD, "kastade tidigare"),
                             (METADATA_FEL, "metadata kunde inte hämtas")):
            if n.get(nyckel):
                delar.append(f"{n[nyckel]} {text}")
        delar.append(f"{n.get('kvar', 0)} kvar till kontaktkartan")
        if getattr(res, "jobb", None):
            delar.append(f"jobbet ”{res.jobb[0]}”: {_antal(res.jobb[1], 'akt', 'akter')}")
        if res.fel:
            delar.append(f"{_antal(len(res.fel), 'sökning', 'sökningar')} misslyckades")
        self.status.setToolTip("\n".join(res.fel))
        self.status.setText(" · ".join(delar))
        if not n.get("kvar"):
            # En tom kontaktkarta sager ingenting. Sag varfor i stallet.
            text = " · ".join(delar)
            if res.fel:
                text += "\n\nMisslyckade sökningar:\n" + "\n".join(
                    f.split(" {", 1)[0] for f in res.fel[:10])
            QMessageBox.information(self, "Inga akter kvar", text)
            return
        if res.fel:
            QMessageBox.warning(self, "Några sökningar misslyckades",
                                "Kontaktkartan visar det som gick att hämta.\n\n"
                                + "\n".join(f.split(" {", 1)[0] for f in res.fel[:10]))
        self._visa_kontaktkarta(res.kandidater)

    def _visa_kontaktkarta(self, kandidater) -> None:
        if self.panel is None:
            self.register = Register(self.inst.registerfil)
            self.panel = Kontaktkarta(self.register, self.klient_fabrik(),
                                      self.inst.miniatyrer, self.iface.mainWindow())
            self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.panel)
        self.panel.show()
        self.panel.raise_()
        self.panel.visa(kandidater)

    # ------------------------------------------------------------ ladda ned
    def _ladda_ned(self) -> None:
        if not self.inst.arkiv:
            QMessageBox.information(self, "Ladda ned", "Arkivet är inte angivet — se Inställningar.")
            return
        self._starta("Laddar ned behållna kartsidor",
                     lambda f, a: steg.ladda_ned(self.inst, self.klient_fabrik, f, a,
                                                 textakt=self.aven_textakt.isChecked()),
                     self._nedladdat)

    def _nedladdat(self, n) -> None:
        delar = [f"{_antal(len(n.hamtade), 'kartsida', 'kartsidor')} nedladdade "
                 f"({n.byte / 1e9:.2f} GB)"]
        if n.aterfunna:
            delar.append(f"{len(n.aterfunna)} fanns redan på disk och registrerades")
        if n.fel:
            delar.append(f"{_antal(len(n.fel), 'sida', 'sidor')} misslyckades")
        if getattr(n, "textakter", 0):
            delar.append(f"{_antal(n.textakter, 'textakt', 'textakter')} sparade")
        if getattr(n, "textakt_fel", None):
            delar.append(f"{_antal(len(n.textakt_fel), 'textakt', 'textakter')} misslyckades")
        if n.avbrutet:
            delar.append("avbrutet — fortsätter där det slutade nästa gång")
        mapp = os.path.join(self.inst.arkiv, "kartor")
        inget_behallet = getattr(n, "behallna", 1) == 0 and not (n.hamtade or n.aterfunna or n.fel)
        if inget_behallet:
            delar = ["Inga akter är markerade Behåll, så det finns inget att ladda ned."]
        elif not (n.hamtade or n.aterfunna or n.fel):
            delar = ["Inga nya kartsidor att ladda ned: alla behållna finns redan."]
        self.status.setText(" · ".join(delar) + "\n" + mapp)
        alla_fel = list(n.fel) + list(getattr(n, "textakt_fel", []))
        self.status.setToolTip("\n".join(alla_fel))
        if alla_fel:
            QMessageBox.warning(self, "Några sidor misslyckades", "\n".join(alla_fel[:15]))
        # Beskedet som ruta med knappen till mappen, som Spara listan (Anna 2026-10-27:
        # hittade inte kartorna utan tog förhandsbilderna i tjanstecache)
        ruta = QMessageBox(self)
        ruta.setWindowTitle("Ladda ned")
        if inget_behallet:
            ruta.setText("Inga akter är markerade Behåll.\n\nTryck Sök akter och visa kontaktkartan, "
                         "markera de akter du vill ha med ✓ Behåll, och tryck sedan Ladda ned igen.")
            ruta.addButton(QMessageBox.StandardButton.Ok)
            ruta.exec()
            return
        ruta.setText(" · ".join(delar) + f"\n\nKartorna ligger som TIFF i\n{mapp}\nen mapp per socken, "
                     "med åtgärd, år och beteckning i filnamnet.")
        oppna = ruta.addButton("Öppna mappen", QMessageBox.ButtonRole.ActionRole) if os.path.isdir(mapp) else None
        ruta.addButton(QMessageBox.StandardButton.Ok)
        ruta.exec()
        if oppna is not None and ruta.clickedButton() is oppna:
            from .kontaktkarta import oppna_fil
            oppna_fil(mapp)

    # ------------------------------------------------------------- jobb
    def _starta(self, namn: str, funktion, klar) -> None:
        if self.jobb is not None:
            self.status.setText("Vänta — ett jobb pågår redan.")
            return
        self.forlopp.setValue(0)
        self.status.setText(namn + " …")
        self.avbryt_knapp.setEnabled(True)
        for b in (self.hamta, self.gallra_knapp, self.ladda_knapp):
            b.setEnabled(False)
        j = Jobb(namn, funktion)
        j.meddelande.connect(lambda t, a: (self.status.setText(t),
                                           self.forlopp.setValue(int(100 * a))))
        j.klart.connect(lambda r: (self._jobb_klart(), klar(r)))
        j.fel.connect(self._jobb_fel)
        self.jobb = j.starta()

    def _jobb_klart(self) -> None:
        self.jobb = None
        self.forlopp.setValue(100)
        self.avbryt_knapp.setEnabled(False)
        self.hamta.setEnabled(True)
        self.gallra_knapp.setEnabled(bool(self.inst.arkiv))
        self.ladda_knapp.setEnabled(bool(self.inst.arkiv))

    def _jobb_fel(self, text: str) -> None:
        self._jobb_klart()
        self.forlopp.setValue(0)
        self.status.setText("Avbrutet." if text == "Avbrutet." else
                            "Fel: " + text.splitlines()[0])
        if text != "Avbrutet.":
            QMessageBox.warning(self, "Historiska kartor", text)

    def _avbryt(self) -> None:
        if self.jobb is not None:
            self.jobb.cancel()

    def closeEvent(self, e):
        if self._ritverktyg is not None:
            self._ritning_klar()
        super().closeEvent(e)
