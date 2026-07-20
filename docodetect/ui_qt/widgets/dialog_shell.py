"""Gemeinsame Dialog-Hülle des Entwurfs: Kopf mit Badge und Titel, Rumpf,
Fußzeile mit Abbrechen + Hauptaktion.

Der Entwurf zeigt eine schwebende Karte mit runden Ecken und Schatten. Qt
zeichnet runde Ecken nur an einem rahmenlosen Fenster mit transparentem
Hintergrund – deshalb `FramelessWindowHint` plus eine gerundete Karte
darin. Weil damit auch die Titelleiste entfällt, ist der Kopf ziehbar.

ABWEICHUNG: Der abgedunkelte Hintergrund („backdrop") des Entwurfs fehlt.
Ein Dialog ist unter Qt ein eigenes Fenster und kann das Hauptfenster nicht
überlagern-dimmen, ohne dass man ein zusätzliches Overlay-Widget über das
Hauptfenster legt; der Aufwand steht in keinem Verhältnis. Modal ist er
trotzdem.

Die Felder (`field_row`, `read_only`) folgen den Maßen des Entwurfs:
Label 10px versal, Eingabe/Anzeige 40px hoch, Radius 9.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QDialog, QFrame, QGraphicsDropShadowEffect,
                               QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                               QWidget)

from .. import icons
from ..app import current_theme
from .common import transparent_for_mouse

_WIDTH = 480              # Entwurf
_BADGE = 32               # Entwurf


class _Header(QWidget):
    """Kopfzeile – zugleich Ziehgriff, weil das Fenster rahmenlos ist."""

    def __init__(self, icon_name: str, title: str, dialog: QDialog):
        super().__init__(dialog)
        self.setObjectName("dialogHeader")
        self._dialog = dialog
        self._drag_from = None

        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)

        self.badge = QLabel(self)
        self.badge.setObjectName("dialogBadge")
        self.badge.setFixedSize(_BADGE, _BADGE)
        self.badge.setAlignment(Qt.AlignCenter)
        self._icon_name = icon_name
        lay.addWidget(self.badge)

        self.title = QLabel(title, self)
        self.title.setObjectName("dialogTitle")
        lay.addWidget(self.title, stretch=1)

        self.close_button = QPushButton("×", self)
        self.close_button.setObjectName("dialogClose")
        self.close_button.setFixedSize(30, 30)
        self.close_button.setCursor(Qt.PointingHandCursor)
        self.close_button.clicked.connect(dialog.reject)
        lay.addWidget(self.close_button)

        transparent_for_mouse(self.badge, self.title)
        self.retheme()

    def retheme(self) -> None:
        t = current_theme()
        dpr = self.devicePixelRatioF() or 1.0
        self.badge.setPixmap(icons.pixmap(self._icon_name, 18, t["accent"], dpr))

    def mousePressEvent(self, event) -> None:      # noqa: N802 (Qt-API)
        if event.button() == Qt.LeftButton:
            self._drag_from = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event) -> None:       # noqa: N802 (Qt-API)
        if self._drag_from is not None:
            now = event.globalPosition().toPoint()
            self._dialog.move(self._dialog.pos() + (now - self._drag_from))
            self._drag_from = now

    def mouseReleaseEvent(self, event) -> None:    # noqa: N802 (Qt-API)
        self._drag_from = None


class DialogShell(QDialog):
    """Basis für Kalibrieren- und Einlern-Dialog.

    Unterklassen füllen `self.body` und benennen die Hauptaktion über
    `set_primary_text`. `primary` feuert, wenn sie gedrückt wird."""

    primary = Signal()

    def __init__(self, icon_name: str, title: str, primary_text: str,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)   # Platz für den Schatten

        self.card = QFrame(self)
        self.card.setObjectName("dialogCard")
        self.card.setMinimumWidth(_WIDTH)
        outer.addWidget(self.card)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(60)
        shadow.setOffset(0, 18)
        shadow.setColor(QColor(0, 0, 0, 170))
        self.card.setGraphicsEffect(shadow)

        card_lay = QVBoxLayout(self.card)
        card_lay.setContentsMargins(0, 0, 0, 0)
        card_lay.setSpacing(0)

        self.header = _Header(icon_name, title, self)
        card_lay.addWidget(self.header)

        body_wrap = QWidget(self.card)
        body_wrap.setObjectName("dialogBody")
        self.body = QVBoxLayout(body_wrap)
        self.body.setContentsMargins(18, 18, 18, 18)
        self.body.setSpacing(12)
        card_lay.addWidget(body_wrap, stretch=1)

        footer = QWidget(self.card)
        footer.setObjectName("dialogFooter")
        f = QHBoxLayout(footer)
        f.setContentsMargins(18, 0, 18, 18)
        f.setSpacing(10)
        self.cancel_button = QPushButton("Abbrechen", footer)
        self.cancel_button.setObjectName("secondaryButton")
        self.cancel_button.clicked.connect(self.reject)
        f.addWidget(self.cancel_button, stretch=1)
        self.primary_button = QPushButton(primary_text, footer)
        self.primary_button.setObjectName("primaryButton")
        self.primary_button.clicked.connect(self.primary.emit)
        f.addWidget(self.primary_button, stretch=2)   # Entwurf: 1 : 1,4
        card_lay.addWidget(footer)

    def set_primary_text(self, text: str) -> None:
        self.primary_button.setText(text)

    def add_intro(self, text: str) -> QLabel:
        lbl = QLabel(text, self)
        lbl.setObjectName("dialogIntro")
        lbl.setWordWrap(True)
        self.body.addWidget(lbl)
        return lbl


# ---------- Feld-Bausteine des Entwurfs ----------

def _labelled(title: str, widget: QWidget) -> QWidget:
    box = QWidget()
    box.setObjectName("cardBox")
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(4)
    lbl = QLabel(title.upper(), box)
    lbl.setObjectName("fieldLabel")
    lay.addWidget(lbl)
    lay.addWidget(widget)
    return box


def read_only(title: str, value: str, accent: bool = False) -> tuple:
    """Anzeigefeld (kein Eingabefeld) -> (Container, Wert-Label).

    Der Kalibrier-Dialog besteht fast nur aus solchen Feldern: die Werte
    kommen aus der Konfiguration bzw. aus der Messung, nichts davon wird
    von Hand eingetippt."""
    value_label = QLabel(value)
    value_label.setObjectName("fieldValueAccent" if accent else "fieldValue")
    value_label.setMinimumHeight(40)
    return _labelled(title, value_label), value_label


def field_row(*widgets: QWidget) -> QWidget:
    row = QWidget()
    row.setObjectName("cardBox")
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(12)
    for w in widgets:
        lay.addWidget(w, stretch=1)
    return row
