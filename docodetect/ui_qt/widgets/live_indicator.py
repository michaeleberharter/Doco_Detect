"""„● Live"-Anzeige über der Vorschau: pulsierender Punkt + Text.

Der Entwurf animiert die Deckkraft in 1,8 s von 100 % auf 35 % und zurück.
QSS kennt keine Animationen, deshalb eine QVariantAnimation auf einem selbst
gezeichneten Punkt.

Die Animation läuft NUR, solange die Anzeige sichtbar ist (`showEvent`/
`hideEvent`): ein Timer, der im Hintergrund weiterläuft, kostet Bildrate in
der Live-Vorschau – und genau die soll flüssig bleiben.
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QRectF, QVariantAnimation, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

_DOT = 7                  # Entwurf
_PERIOD_MS = 1800         # Entwurf: 1,8 s
_MIN_OPACITY = 0.35       # Entwurf: 100 % -> 35 % -> 100 %


class _PulsingDot(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(_DOT, _DOT)
        self._opacity = 1.0
        self._color = QColor("#31b46f")
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(_PERIOD_MS // 2)
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(_MIN_OPACITY)
        self._anim.setEasingCurve(QEasingCurve.InOutSine)
        self._anim.valueChanged.connect(self._on_value)
        self._anim.finished.connect(self._bounce)

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def _on_value(self, value) -> None:
        self._opacity = float(value)
        self.update()

    def _bounce(self) -> None:
        """Hin und zurück statt Loop – so bleibt der Übergang weich."""
        if not self.isVisible():
            return
        start, end = self._anim.startValue(), self._anim.endValue()
        self._anim.setStartValue(end)
        self._anim.setEndValue(start)
        self._anim.start()

    def start(self) -> None:
        if self._anim.state() != QVariantAnimation.Running:
            self._anim.start()

    def stop(self) -> None:
        self._anim.stop()
        self._opacity = 1.0
        self.update()

    def is_running(self) -> bool:
        return self._anim.state() == QVariantAnimation.Running

    def showEvent(self, event) -> None:      # noqa: N802 (Qt-API)
        super().showEvent(event)
        self.start()

    def hideEvent(self, event) -> None:      # noqa: N802 (Qt-API)
        super().hideEvent(event)
        self._anim.stop()

    def paintEvent(self, event) -> None:     # noqa: N802 (Qt-API)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        c = QColor(self._color)
        c.setAlphaF(self._opacity)
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawEllipse(QRectF(0, 0, _DOT, _DOT))
        p.end()


class LiveIndicator(QWidget):
    """Punkt + Beschriftung. `set_live(False)` hält die Animation an und
    graut ab – z.B. wenn die Kamera getrennt ist."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("liveIndicator")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(7)
        self._dot = _PulsingDot(self)
        self._label = QLabel("Live", self)
        self._label.setObjectName("liveLabel")
        lay.addWidget(self._dot)
        lay.addWidget(self._label)
        self._live = True

    def set_live(self, live: bool, text: str | None = None) -> None:
        self._live = live
        self._label.setText(text or ("Live" if live else "Kein Bild"))
        self._label.setProperty("live", "yes" if live else "no")
        self._label.style().unpolish(self._label)
        self._label.style().polish(self._label)
        self.retheme()
        self._dot.start() if live else self._dot.stop()

    def retheme(self) -> None:
        from ..app import current_theme
        t = current_theme()
        self._dot.set_color(t["ok"] if self._live else t["faint"])

    def label_text(self) -> str:
        return self._label.text()
