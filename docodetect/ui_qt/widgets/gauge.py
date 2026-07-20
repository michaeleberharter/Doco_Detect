"""Toleranzbalken: gemessener Ø gegen das Toleranzband der Stammdaten.

Der Entwurf zeigt eine Spur mit eingerücktem Toleranzband (27–73 % der
Breite) und den Skalenenden 135 / 147 bei Nominal 141 ±6. Beides passt nur
zusammen, wenn die Spur breiter ist als das Band – im Entwurf steht das
nicht explizit, hier ist die Rechnung:

    Spur = Nominal ± 2 · Toleranz   ->   Band (± Toleranz) liegt bei 25–75 %

Das ist praktisch die Optik des Entwurfs, beschriftet die Bandkanten wie
dort mit Nominal ∓ Toleranz, und – wichtiger – ein Messwert AUSSERHALB der
Toleranz bleibt darstellbar, statt am Rand zu kleben.

Die Toleranz ist global (`matching.diameter_tolerance_mm`) und KEIN
Artikelattribut; sie wird nur angezeigt, nie hier verändert.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..app import current_theme

_TRACK_H = 10             # Entwurf
_MARKER = 14              # Entwurf
_SCALE_H = 16             # Platz für die Beschriftung darunter
_SPAN_FACTOR = 2.0        # Spur = Nominal ± 2 · Toleranz (siehe Modul-Doku)


class ToleranceGauge(QWidget):
    """Zeigt EINEN Messwert gegen EIN Toleranzband. Rechnet nichts nach:
    Nominal, Messwert und Toleranz kommen fertig von aussen."""

    def __init__(self, nominal_mm: float, measured_mm: float,
                 tolerance_mm: float, parent=None):
        super().__init__(parent)
        self.setObjectName("toleranceGauge")
        self._nominal = float(nominal_mm)
        self._measured = float(measured_mm)
        self._tol = float(tolerance_mm)
        self.setFixedHeight(_MARKER + _SCALE_H + 4)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    # ---------- abgeleitete Groessen ----------

    @property
    def in_tolerance(self) -> bool:
        return abs(self._measured - self._nominal) <= self._tol

    def _fraction(self) -> float:
        """Position des Messwerts auf der Spur, 0..1 (geklemmt)."""
        span = self._tol * _SPAN_FACTOR
        if span <= 0:
            return 0.5
        f = 0.5 + (self._measured - self._nominal) / (2.0 * span)
        return max(0.0, min(1.0, f))

    def status_text(self) -> str:
        if self.in_tolerance:
            return "im Toleranzbereich"
        return f"{abs(self._measured - self._nominal):.1f} mm ausserhalb".replace(
            ".", ",")

    # ---------- Zeichnen ----------

    def paintEvent(self, event) -> None:      # noqa: N802 (Qt-API)
        t = current_theme()
        tone = "ok" if self.in_tolerance else "warn"
        color = QColor(t[tone])
        weak = QColor(t[tone + "Weak"])

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        pad = _MARKER / 2.0
        track = QRectF(pad, (_MARKER - _TRACK_H) / 2.0,
                       max(1.0, self.width() - 2 * pad), _TRACK_H)

        # Spur
        p.setPen(QPen(QColor(t["line"]), 1))
        p.setBrush(QColor(t["track"]))
        p.drawRoundedRect(track, 6, 6)

        # Toleranzband: 25–75 % der Spur (Nominal ± Toleranz)
        band = QRectF(track.left() + track.width() * 0.25, track.top(),
                      track.width() * 0.5, track.height())
        p.setPen(Qt.NoPen)
        p.setBrush(weak)
        p.drawRect(band)
        dashed = QPen(color, 1)
        dashed.setStyle(Qt.DashLine)
        p.setPen(dashed)
        p.drawLine(band.topLeft(), band.bottomLeft())
        p.drawLine(band.topRight(), band.bottomRight())

        # Messwert-Marker
        cx = track.left() + track.width() * self._fraction()
        cy = track.center().y()
        p.setPen(Qt.NoPen)
        p.setBrush(weak)
        p.drawEllipse(QRectF(cx - _MARKER / 2.0 - 1.5, cy - _MARKER / 2.0 - 1.5,
                             _MARKER + 3, _MARKER + 3))
        p.setBrush(color)
        p.drawEllipse(QRectF(cx - _MARKER / 2.0, cy - _MARKER / 2.0,
                             _MARKER, _MARKER))

        # Skala: Bandkanten links/rechts, Status mittig
        f = p.font()
        f.setFamily(_mono_family())
        f.setPixelSize(10)
        p.setFont(f)
        y = int(_MARKER + 2)
        row = QRectF(0, y, self.width(), _SCALE_H)
        p.setPen(QColor(t["faint"]))
        p.drawText(row, Qt.AlignLeft | Qt.AlignVCenter,
                   _mm(self._nominal - self._tol))
        p.drawText(row, Qt.AlignRight | Qt.AlignVCenter,
                   _mm(self._nominal + self._tol))
        # Ohne Symbolzeichen: IBM Plex Mono trägt weder ✓ noch ⚠ und Qt
        # ersetzt sie durch fremde Glyphen (aus ✓ wird ein √). Die Farbe
        # trägt die Aussage ohnehin.
        p.setPen(color)
        f.setBold(True)
        p.setFont(f)
        p.drawText(row, Qt.AlignHCenter | Qt.AlignVCenter, self.status_text())
        p.end()


def _mm(value: float) -> str:
    return f"{value:.0f}"


def _mono_family() -> str:
    from .. import fonts
    return fonts.families()["mono"]
