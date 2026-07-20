"""Live-Vorschau: letterboxed Skalierung, Fadenkreuz, Rand-Warnung, Overlay.

Eigenes paintEvent statt QLabel.setPixmap: volle Kontrolle über Letterbox
(kein Verzerren), Fadenkreuz und den Warnrahmen, ohne Pixmap-Kaskaden bei
jedem Resize. Nach einer Identifikation kann ein annotiertes Ergebnisbild
für einige Sekunden „stehen“ (set_overlay) – Klick schaltet zurück zur
Live-Ansicht (und wieder hin).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..app import current_theme


@dataclass
class Detection:
    """Was nach einer Identifikation über dem eingefrorenen Bild liegt.

    `bbox` ist auf die Bildgröße NORMIERT (0..1), damit die Vorschau ihn
    unabhängig von ihrer eigenen Skalierung und vom Downscale des
    Vorschaubilds zeichnen kann.

    Bewusst hier statt in `pipeline.render_report_overlay()`: jenes Overlay
    wird mit der Streamlit-UI und der CLI geteilt und bleibt unverändert –
    Qt zeichnet seinen Rahmen selbst und braucht das Bild dafür nicht
    anzufassen."""
    bbox: tuple                       # (x, y, w, h), je 0..1
    tone: str = "accept"              # accept | ambiguous | border | reject
    chips: list = field(default_factory=list)   # ["Ø 141,0 mm", "87 %"]

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
        self._overlay: QImage | None = None    # eingefrorenes Ergebnisbild
        self._detection: Detection | None = None
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

    def set_overlay(self, img: QImage, secs: float,
                    detection: Detection | None = None) -> None:
        """Ergebnisbild einige Sekunden einfrieren, dann zurück live.
        `detection` legt Erkennungsrahmen und Maß-Chips darüber."""
        self._overlay = img
        self._detection = detection
        self._show_overlay = True
        self._overlay_timer.start(int(secs * 1000))
        self.update()

    def _overlay_expired(self) -> None:
        self._show_overlay = False
        self.update()

    def detection(self) -> Detection | None:
        """Aktuell gezeichnete Erkennung (Testhilfe)."""
        return self._detection if self._show_overlay else None

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
            elif self._detection is not None:
                self._draw_detection(p, target, self._detection)
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

    def _draw_detection(self, p: QPainter, r: QRect, det: Detection) -> None:
        """Erkennungsrahmen (gestrichelt, in der Zustandsfarbe) plus die
        Mess-Chips oben links – die Optik des Entwurfs.

        save()/restore() ist hier NICHT kosmetisch: die Chips setzen einen
        Füllpinsel, und ohne Zurücksetzen füllte der anschliessende
        Warnrahmen das gesamte Bild in Amber."""
        p.save()
        t = current_theme()
        color = QColor(t.tone_color(det.tone))
        x, y, w, h = det.bbox
        box = QRectF(r.left() + x * r.width(), r.top() + y * r.height(),
                     max(2.0, w * r.width()), max(2.0, h * r.height()))

        pen = QPen(color, 2)
        pen.setStyle(Qt.CustomDashLine)
        pen.setDashPattern([3, 5])                  # Entwurf
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(box, 6, 6)

        if not det.chips:
            p.restore()
            return
        f = p.font()
        f.setFamily(_mono_family())
        f.setPixelSize(12)
        f.setBold(True)
        p.setFont(f)
        fm = p.fontMetrics()
        # Chips über dem Rahmen; kein Platz nach oben -> nach innen klappen
        cy = box.top() - fm.height() - 12
        if cy < r.top() + 2:
            cy = box.top() + 6
        # Bei randberührenden Objekten liegt die Hüllbox am Bildrand – die
        # Chips würden sonst halb aus dem Bild ragen.
        cx = max(float(r.left()) + 4.0, box.left())
        for text in det.chips:
            tw = fm.horizontalAdvance(text) + 18
            pill = QRectF(cx, cy, tw, fm.height() + 8)
            p.setPen(Qt.NoPen)
            p.setBrush(color)
            p.drawRoundedRect(pill, 7, 7)
            p.setPen(QColor("#ffffff"))
            p.drawText(pill, Qt.AlignCenter, text)
            cx += tw + 6
        p.restore()

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
        # Nur Rahmen, keine Fläche: der Pinsel könnte vom Erkennungsrahmen
        # noch gesetzt sein und würde das Bild komplett einfärben.
        p.setPen(QPen(c["warn"], 6))
        p.setBrush(Qt.NoBrush)
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


def _mono_family() -> str:
    from .. import fonts
    return fonts.families()["mono"]
