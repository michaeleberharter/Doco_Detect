"""Strichicons, in Qt gezeichnet statt als Dateien gebündelt.

Der Entwurf nutzt Feather-/Lucide-artige Linienicons (1,7 px Strich, runde
Enden). Sie hier zu ZEICHNEN statt SVGs zu laden hat einen konkreten Grund:
jedes Icon erscheint in mehreren Farben (Schiene normal/aktiv, Zustands-
Badges in Grün/Amber/Rot, dazu beide Themes). Eine QIcon aus einer SVG-Datei
lässt sich nicht ohne Weiteres umfärben – hier ist die Farbe schlicht ein
Argument.

Alle Icons sind in einem 24x24-Raster definiert und werden auf die
gewünschte Kantenlänge skaliert; der Strich skaliert mit.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QIcon, QIconEngine, QPainter, QPainterPath,
                           QPen, QPixmap)

_GRID = 24.0
_STROKE = 1.7          # Strichstärke im 24er-Raster (Entwurf)

NAMES = ("scan", "camera", "target", "plus", "gear", "check", "alert",
         "help")


def _pen(color: str, width: float) -> QPen:
    p = QPen(QColor(color))
    p.setWidthF(width)
    p.setCapStyle(Qt.RoundCap)
    p.setJoinStyle(Qt.RoundJoin)
    return p


def _scan(path: QPainterPath) -> None:
    """Lupe – Hauptaktion „Identifizieren"."""
    path.addEllipse(QPointF(10.5, 10.5), 6.0, 6.0)
    path.moveTo(15.0, 15.0)
    path.lineTo(20.0, 20.0)


def _camera(path: QPainterPath) -> None:
    """Kamera – „Hintergrund aufnehmen"."""
    path.moveTo(9.2, 6.5)
    path.lineTo(10.4, 4.6)
    path.lineTo(13.6, 4.6)
    path.lineTo(14.8, 6.5)
    path.addRoundedRect(QRectF(3.2, 6.5, 17.6, 13.0), 2.6, 2.6)
    path.addEllipse(QPointF(12.0, 13.0), 3.7, 3.7)


def _target(path: QPainterPath) -> None:
    """Zielkreuz – „Kalibrieren" (ArUco-Marker mittig)."""
    path.addEllipse(QPointF(12.0, 12.0), 8.0, 8.0)
    path.addEllipse(QPointF(12.0, 12.0), 2.4, 2.4)
    for x1, y1, x2, y2 in ((12, 1.4, 12, 5.2), (12, 18.8, 12, 22.6),
                           (1.4, 12, 5.2, 12), (18.8, 12, 22.6, 12)):
        path.moveTo(x1, y1)
        path.lineTo(x2, y2)


def _plus(path: QPainterPath) -> None:
    """Plus – „Artikel einlernen"."""
    path.moveTo(12.0, 5.0)
    path.lineTo(12.0, 19.0)
    path.moveTo(5.0, 12.0)
    path.lineTo(19.0, 12.0)


def _gear(path: QPainterPath) -> None:
    """Zahnrad – Theme-Umschalter (einziger Zweck, siehe main_window)."""
    path.addEllipse(QPointF(12.0, 12.0), 3.2, 3.2)
    path.addEllipse(QPointF(12.0, 12.0), 7.0, 7.0)
    import math
    for i in range(8):
        a = math.pi * i / 4.0
        path.moveTo(12 + 7.0 * math.cos(a), 12 + 7.0 * math.sin(a))
        path.lineTo(12 + 9.6 * math.cos(a), 12 + 9.6 * math.sin(a))


def _check(path: QPainterPath) -> None:
    """Haken – Badge im ACCEPT-Zustand."""
    path.moveTo(5.5, 12.5)
    path.lineTo(10.0, 17.0)
    path.lineTo(18.5, 7.5)


def _alert(path: QPainterPath) -> None:
    """Ausrufezeichen – Badge bei AMBIGUOUS/REJECT/Randberührung."""
    path.moveTo(12.0, 5.5)
    path.lineTo(12.0, 14.0)
    path.moveTo(12.0, 18.2)
    path.lineTo(12.0, 18.4)


def _help(path: QPainterPath) -> None:
    """Fragezeichen im Kreis – Hilfe (ToolRail, Ebene 2)."""
    path.addEllipse(QPointF(12.0, 12.0), 8.0, 8.0)
    path.moveTo(9.4, 9.3)
    path.cubicTo(9.6, 7.6, 11.0, 6.6, 12.4, 6.7)
    path.cubicTo(14.0, 6.8, 15.2, 8.0, 15.1, 9.5)
    path.cubicTo(15.0, 10.7, 14.2, 11.3, 13.3, 11.9)
    path.cubicTo(12.6, 12.4, 12.1, 12.9, 12.1, 13.9)
    path.moveTo(12.1, 17.0)
    path.lineTo(12.1, 17.2)


def _lock(path: QPainterPath) -> None:
    """Schloss – Admin-Bereich (ToolRail, Spec Abschnitt 3)."""
    path.addRoundedRect(6.0, 11.0, 12.0, 8.0, 2.0, 2.0)
    path.moveTo(8.5, 11.0)
    path.lineTo(8.5, 8.0)
    path.arcTo(8.5, 4.5, 7.0, 7.0, 180.0, -180.0)
    path.lineTo(15.5, 11.0)


_BUILDERS = {"scan": _scan, "camera": _camera, "target": _target,
             "plus": _plus, "gear": _gear, "check": _check, "alert": _alert,
             "lock": _lock, "help": _help}


def paint(painter: QPainter, name: str, rect: QRectF, color: str,
          stroke: float = _STROKE) -> None:
    """Icon `name` in `rect` zeichnen. Der Painter-Zustand bleibt erhalten."""
    builder = _BUILDERS.get(name)
    if builder is None:
        raise KeyError(f"Unbekanntes Icon '{name}'. Bekannt: {sorted(_BUILDERS)}")
    path = QPainterPath()
    builder(path)
    scale = min(rect.width(), rect.height()) / _GRID
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.translate(rect.center().x() - _GRID * scale / 2.0,
                      rect.center().y() - _GRID * scale / 2.0)
    painter.scale(scale, scale)
    painter.setPen(_pen(color, stroke))
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(path)
    painter.restore()


def pixmap(name: str, size: int, color: str, dpr: float = 1.0) -> QPixmap:
    """Transparente QPixmap mit dem Icon – `dpr` für scharfe High-DPI-Icons.

    Der Backing-Store ist PHYSISCH (`size * dpr` Pixel), gezeichnet wird aber
    LOGISCH: `setDevicePixelRatio(dpr)` weist den Painter an, in
    device-unabhängigen Einheiten zu arbeiten (Qt legt den dpr-Transform
    selbst auf). Deshalb ist das Ziel-Rect `size` (nicht `size * dpr`) und der
    Strich `_STROKE` (nicht `_STROKE * dpr`) – sonst skaliert man ein zweites
    Mal und rendert nur das linke obere Viertel.

    Backing per `ceil`, nicht `int`: bei krummem `size * dpr` (z.B. dpr 1.5)
    würde `int()` eine Pixelreihe abschneiden, sodass die effektive dpr
    (Backing/logisch) nicht mehr dem gesetzten `dpr` entspräche. `ceil`
    rundet AUF, also nie Anschnitt – höchstens ein subpixelbreiter
    transparenter Rand rechts/unten. Für die real genutzten `size ∈ {18,20,24}`
    und `dpr ∈ {1,1.5,2,2.5,3}` ist `size * dpr` ohnehin ganzzahlig, `ceil`
    also ein No-op und die logische Größe exakt `size`; den gesetzten `dpr`
    beizubehalten (statt Backing/size) hält die Pixmap-dpr deckungsgleich mit
    der des Ziel-Screens, sodass beim Compositing kein Nachskalieren entsteht.
    """
    backing = math.ceil(size * dpr)
    px = QPixmap(backing, backing)
    px.setDevicePixelRatio(dpr)
    px.fill(Qt.transparent)
    p = QPainter(px)
    paint(p, name, QRectF(0, 0, size, size), color)
    p.end()
    return px


class _StrokeIconEngine(QIconEngine):
    """QIcon-Engine, die das Strichicon bei JEDER Anfrage frisch in das
    geforderte Ziel-Rect/-Auflösung zeichnet – also genau einmal und bei der
    tatsächlichen Zielauflösung rasterisiert. Damit teilen die QToolButtons
    der Schiene (`setIcon`) und die direkt gemalten Badges denselben
    Renderpfad wie `result_card` (`icons.paint`); es gibt keine zweite,
    dpr-blinde Rasterisierung mehr."""

    def __init__(self, name: str, color: str):
        super().__init__()
        self._name = name
        self._color = color

    def paint(self, painter: QPainter, rect, mode, state) -> None:  # noqa: N802
        painter.setRenderHint(QPainter.Antialiasing, True)
        paint(painter, self._name, QRectF(rect), self._color)

    def scaledPixmap(self, size, mode, state, scale) -> QPixmap:  # noqa: N802
        # `size` ist die LOGISCHE Zielgröße, `scale` die Ziel-dpr. Der Painter
        # zeichnet dank gesetztem dpr in logischen Einheiten – deshalb Ziel-
        # Rect = logische `size`, nicht size*scale (siehe pixmap()).
        w = max(1, math.ceil(size.width() * scale))
        h = max(1, math.ceil(size.height() * scale))
        px = QPixmap(w, h)
        px.setDevicePixelRatio(scale)
        px.fill(Qt.transparent)
        p = QPainter(px)
        paint(p, self._name, QRectF(0, 0, size.width(), size.height()),
              self._color)
        p.end()
        return px

    def pixmap(self, size, mode, state) -> QPixmap:  # noqa: N802
        # Ohne dpr-Information (z.B. QIcon.pixmap(w, h)): physisch = logisch.
        return self.scaledPixmap(size, mode, state, 1.0)

    def clone(self) -> "QIconEngine":
        return _StrokeIconEngine(self._name, self._color)


def icon(name: str, size: int, color: str) -> QIcon:
    """QIcon mit `_StrokeIconEngine` – rendert bei jeder vom Widget
    geforderten Größe und dpr frisch. `size` wird nicht mehr fixiert (die
    Engine ist größenunabhängig); der Parameter bleibt nur für die
    bestehenden Aufrufer erhalten."""
    return QIcon(_StrokeIconEngine(name, color))
