"""Paneler som går att dra smala och låga (användaren 2026-10-01: "tar mycket
plats på skärmen annars").

`Flode` lägger knappar i rader som bryts när panelen blir smal, i stället för
en rad som tvingar fram bredden (Rektifiera-panelen gick inte under 516 px).
`skalbar` lägger panelens innehåll i en rullningsyta, så att panelen kan göras
lägre än innehållet.
"""
from __future__ import annotations

from qgis.PyQt.QtCore import QPoint, QRect, QSize, Qt
from qgis.PyQt.QtWidgets import QFrame, QLayout, QScrollArea, QWidget


class Flode(QLayout):
    """Radbrytande layout (Qt:s FlowLayout-exempel)."""

    def __init__(self, parent=None, avstand: int = 4):
        super().__init__(parent)
        self._delar = []
        self._avstand = avstand
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._delar.append(item)

    def count(self):
        return len(self._delar)

    def itemAt(self, i):
        return self._delar[i] if 0 <= i < len(self._delar) else None

    def takeAt(self, i):
        return self._delar.pop(i) if 0 <= i < len(self._delar) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, bredd):
        return self._lagg(QRect(0, 0, bredd, 0), prova=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._lagg(rect, prova=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QSize()
        for d in self._delar:
            s = s.expandedTo(d.minimumSize())
        m = self.contentsMargins()
        return s + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _lagg(self, rect, prova: bool) -> int:
        m = self.contentsMargins()
        r = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, radhojd = r.x(), r.y(), 0
        for d in self._delar:
            if d.widget() is not None and not d.widget().isVisible() and not prova:
                continue
            s = d.sizeHint()
            if x + s.width() > r.right() + 1 and radhojd > 0:
                x, y = r.x(), y + radhojd + self._avstand
                radhojd = 0
            if not prova:
                d.setGeometry(QRect(QPoint(x, y), s))
            x += s.width() + self._avstand
            radhojd = max(radhojd, s.height())
        return y + radhojd - rect.y() + m.bottom()


def skalbar(w: QWidget) -> QScrollArea:
    """Innehållet i en rullningsyta utan ram: panelen får vara mindre än innehållet."""
    yta = QScrollArea()
    yta.setWidget(w)
    yta.setWidgetResizable(True)
    yta.setFrameShape(QFrame.Shape.NoFrame)
    yta.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    return yta
