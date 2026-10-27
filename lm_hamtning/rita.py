"""Rita arbetsomradet i kartan: vanster klick satter hornen, hoger klick
avslutar, Esc avbryter. Ytan kommer i kartans koordinatsystem."""
from __future__ import annotations

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor
from qgis.core import QgsGeometry, QgsPointXY, QgsWkbTypes
from qgis.gui import QgsMapTool, QgsRubberBand


class RitaYta(QgsMapTool):
    klar = pyqtSignal(QgsGeometry)
    avbruten = pyqtSignal()

    def __init__(self, canvas):
        super().__init__(canvas)
        self.punkter: list[QgsPointXY] = []
        self.band = QgsRubberBand(canvas, QgsWkbTypes.GeometryType.PolygonGeometry)
        self.band.setColor(QColor(30, 100, 200, 180))
        self.band.setFillColor(QColor(30, 100, 200, 40))
        self.band.setWidth(2)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def _visa(self, rorlig: QgsPointXY | None = None) -> None:
        pts = self.punkter + ([rorlig] if rorlig is not None else [])
        self.band.setToGeometry(QgsGeometry.fromPolygonXY([pts]) if len(pts) >= 3
                                else QgsGeometry.fromPolylineXY(pts), None)

    def canvasMoveEvent(self, e):
        if self.punkter:
            self._visa(self.toMapCoordinates(e.pos()))

    def canvasReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.punkter.append(self.toMapCoordinates(e.pos()))
            self._visa()
        elif e.button() == Qt.MouseButton.RightButton:
            if len(self.punkter) >= 3:
                g = QgsGeometry.fromPolygonXY([self.punkter])
                self.rensa()
                self.klar.emit(g)
            else:
                self.rensa()
                self.avbruten.emit()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.rensa()
            self.avbruten.emit()

    def rensa(self) -> None:
        self.punkter = []
        self.band.reset(QgsWkbTypes.GeometryType.PolygonGeometry)

    def deactivate(self):
        self.rensa()
        super().deactivate()
