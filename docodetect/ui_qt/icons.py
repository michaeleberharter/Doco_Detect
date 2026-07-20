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

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QIcon, QPainter, QPainterPath, QPen,
                           QPixmap)

_GRID = 24.0
_STROKE = 1.7          # Strichstärke im 24er-Raster (Entwurf)

NAMES = ("scan", "camera", "target", "plus", "gear", "check", "alert")


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


_BUILDERS = {"scan": _scan, "camera": _camera, "target": _target,
             "plus": _plus, "gear": _gear, "check": _check, "alert": _alert}


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
    """Transparente QPixmap mit dem Icon – dpr für scharfe High-DPI-Icons."""
    px = QPixmap(int(size * dpr), int(size * dpr))
    px.setDevicePixelRatio(dpr)
    px.fill(Qt.transparent)
    p = QPainter(px)
    paint(p, name, QRectF(0, 0, size * dpr, size * dpr), color,
          _STROKE * dpr)
    p.end()
    return px


def icon(name: str, size: int, color: str) -> QIcon:
    return QIcon(pixmap(name, size, color))
