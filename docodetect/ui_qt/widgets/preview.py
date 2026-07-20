"""Live-Vorschau: letterboxed Skalierung, Fadenkreuz, Rand-Warnung, Overlay.

Eigenes paintEvent statt QLabel.setPixmap: volle Kontrolle über Letterbox
(kein Verzerren), Fadenkreuz und den Warnrahmen, ohne Pixmap-Kaskaden bei
jedem Resize. Nach einer Identifikation kann ein annotiertes Ergebnisbild
für einige Sekunden „stehen“ (set_overlay) – Klick schaltet zurück zur
Live-Ansicht (und wieder hin).
"""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..app import current_theme

# Deckkraft des Fadenkreuzes über dem Live-Bild – der Farbton kommt aus dem
# Theme, nur die Transparenz ist eine Zeichenentscheidung.
_CROSS_ALPHA = 40


def _colors():
    """Zeichenfarben aus dem aktiven Theme. Die Auflösung ist in theme.py
    gecacht, der Aufruf pro Frame kostet daher nur ein Dict-Kopieren."""
    t = current_theme()
    cross = QColor(t["text"])
    cross.setAlpha(_CROSS_ALPHA)
    return {
        "bg": QColor(t["stage"]),        # Letterbox-Balken neben dem Bild
        "cross": cross,
        "warn": QColor(t["warn"]),       # Randberührung: eigener Zustand,
                                         # amber statt Reject-Rot
        "msg": QColor(t["dim"]),
        "busy_bg": QColor(t["panel"]),
        "busy_text": QColor(t["text"]),
    }


def fit_rect(cw: int, ch: int, iw: int, ih: int) -> QRect:
    """Letterbox: größtes Rechteck mit Bild-Seitenverhältnis im Container."""
    if iw <= 0 or ih <= 0 or cw <= 0 or ch <= 0:
        return QRect(0, 0, 0, 0)
    scale = min(cw / iw, ch / ih)
    w, h = int(iw * scale), int(ih * scale)
    return QRect((cw - w) // 2, (ch - h) // 2, w, h)


class PreviewWidget(QWidget):
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(640, 360)
        self._frame: QImage | None = None      # Live-Bild
        self._overlay: QImage | None = None    # annotiertes Ergebnisbild
        self._show_overlay = False
        self._message: str | None = None       # z.B. „Keine Kamera gefunden“
        self._warn_text: str | None = None     # Rand-Warnung (im Bild, kein Popup)
        self._busy_text: str | None = None     # dezenter Busy-Indikator
        self._overlay_timer = QTimer(self)
        self._overlay_timer.setSingleShot(True)
        self._overlay_timer.timeout.connect(self._overlay_expired)

    # ---------- API ----------

    def set_frame(self, img: QImage) -> None:
        self._frame = img
        self.update()

    def set_message(self, text: str | None) -> None:
        """Platzhalter-Text statt Bild (NO_CAMERA). None = Bild zeigen."""
        self._message = text
        self.update()

    def set_warning(self, text: str | None) -> None:
        """Rand-Warnung: roter Rahmen + Meldung IM Bild. None = aus."""
        self._warn_text = text
        self.update()

    def set_busy(self, text: str | None) -> None:
        """Dezenter Busy-Indikator über der Vorschau (None = aus)."""
        self._busy_text = text
        self.update()

    def set_overlay(self, img: QImage, secs: float) -> None:
        """Annotiertes Ergebnisbild einige Sekunden zeigen, dann zurück live."""
        self._overlay = img
        self._show_overlay = True
        self._overlay_timer.start(int(secs * 1000))
        self.update()

    def _overlay_expired(self) -> None:
        self._show_overlay = False
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt-API)
        if self._overlay is not None:
            # Klick wechselt zwischen Ergebnisbild und Live-Ansicht
            self._show_overlay = not self._show_overlay
            self._overlay_timer.stop()
            self.update()
        self.clicked.emit()

    # ---------- Zeichnen ----------

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt-API)
        p = QPainter(self)
        c = _colors()
        p.fillRect(self.rect(), c["bg"])
        img = self._overlay if (self._show_overlay and self._overlay) else self._frame

        if self._message:
            p.setPen(c["msg"])
            f = p.font()
            f.setPointSize(14)
            p.setFont(f)
            p.drawText(self.rect(), Qt.AlignCenter | Qt.TextWordWrap, self._message)
            p.end()
            return

        if img is not None:
            target = fit_rect(self.width(), self.height(),
                              img.width(), img.height())
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            p.drawImage(target, img)
            if not self._show_overlay:
                self._draw_crosshair(p, target, c)
            if self._warn_text:
                self._draw_warning(p, target, c)
            if self._busy_text:
                self._draw_busy(p, target, c)
        p.end()

    def _draw_crosshair(self, p: QPainter, r: QRect, c: dict) -> None:
        p.setPen(QPen(c["cross"], 1))
        cx, cy = r.center().x(), r.center().y()
        p.drawLine(r.left(), cy, r.right(), cy)
        p.drawLine(cx, r.top(), cx, r.bottom())
        p.drawEllipse(QRect(cx - 14, cy - 14, 28, 28))

    def _draw_busy(self, p: QPainter, r: QRect, c: dict) -> None:
        f = p.font()
        f.setPointSize(12)
        p.setFont(f)
        w = min(r.width() - 20, 320)
        pill = QRect(r.center().x() - w // 2, r.top() + 12, w, 36)
        pill_bg = QColor(c["busy_bg"])
        pill_bg.setAlpha(220)
        p.setPen(Qt.NoPen)
        p.setBrush(pill_bg)
        p.drawRoundedRect(pill, 18, 18)
        p.setPen(c["busy_text"])
        p.drawText(pill, Qt.AlignCenter, self._busy_text)

    def _draw_warning(self, p: QPainter, r: QRect, c: dict) -> None:
        """Objekt berührt den Bildrand: amber Rahmen + Banner. Bewusst NICHT
        das Reject-Rot – die Messung ist nicht falsch, sie ist nur nicht
        durchführbar (eigener vierter Anzeigezustand)."""
        p.setPen(QPen(c["warn"], 6))
        p.drawRect(r.adjusted(3, 3, -3, -3))
        f = p.font()
        f.setPointSize(13)
        f.setBold(True)
        p.setFont(f)
        banner = QRect(r.left(), r.top(), r.width(), 44)
        banner_bg = QColor(c["warn"])
        banner_bg.setAlpha(215)
        p.fillRect(banner, banner_bg)
        p.setPen(QColor("#ffffff"))
        p.drawText(banner, Qt.AlignCenter, self._warn_text)
