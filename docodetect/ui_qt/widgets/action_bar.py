"""Untere Aktionsleiste: grosse Identifizieren-Fläche + drei Sekundärbuttons.

Beide Buttontypen tragen Icon UND mehrzeiligen Text. QToolButton bricht
Text nicht um, deshalb sind es QPushButtons mit einem eigenen Layout aus
Labels; die Labels sind für Mausereignisse durchlässig, damit ein Klick auf
die Schrift den Button auslöst und nicht ins Leere geht.

Die Buttons heissen weiter identify_button / background_button /
calibrate_button / enroll_button – das Hauptfenster und die Tests greifen
darauf zu, nur ihr Ort im Fenster hat sich geändert.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                               QWidget)

from .. import icons
from ..app import current_theme
from .common import transparent_for_mouse


def _mark_disabled(widget: QWidget, off: bool) -> None:
    """Kindlabels beim Deaktivieren mit ausgrauen.

    Nötig, weil Qt-Stylesheets den Zustand des Eltern-Buttons nicht an
    Kindwidgets vererben: sonst bliebe die Beschriftung eines gesperrten
    Buttons in voller Deckkraft stehen."""
    widget.setProperty("off", "yes" if off else "no")
    widget.style().unpolish(widget)
    widget.style().polish(widget)

_BAR_HEIGHT = 72          # Entwurf: Primär- und Sekundärbuttons 72 px hoch
_SECONDARY_WIDTH = 120    # Entwurf
_PRIMARY_ICON = 24
_SECONDARY_ICON = 20


class _IconLabel(QLabel):
    """Label, das ein Strichicon in Themefarbe zeigt (QIcon lässt sich nicht
    umfärben, ein gezeichnetes Pixmap schon)."""

    def __init__(self, name: str, size: int, role: str, parent=None):
        super().__init__(parent)
        self._name, self._size, self._role = name, size, role
        self.setFixedSize(size, size)
        self.retheme()

    def retheme(self) -> None:
        t = current_theme()
        color = "#ffffff" if self._role == "onAccent" else t["text"]
        dpr = self.devicePixelRatioF() or 1.0
        self.setPixmap(icons.pixmap(self._name, self._size, color, dpr))


class IdentifyButton(QPushButton):
    """Die Hauptaktion: Icon + zweizeilige Beschriftung + Tasten-Chip."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("barPrimary")
        self.setMinimumHeight(_BAR_HEIGHT)
        self.setCursor(Qt.PointingHandCursor)

        row = QHBoxLayout(self)
        row.setContentsMargins(18, 8, 18, 8)
        row.setSpacing(13)
        row.addStretch(1)

        self._icon = _IconLabel("scan", _PRIMARY_ICON, "onAccent", self)
        row.addWidget(self._icon)

        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(1)
        self.title = QLabel("Identifizieren", self)
        self.title.setObjectName("primaryTitle")
        self.subtitle = QLabel("Objekt platzieren – dann identifizieren", self)
        self.subtitle.setObjectName("primarySub")
        text.addWidget(self.title)
        text.addWidget(self.subtitle)
        row.addLayout(text)

        # Bewusst ohne Sondersymbol: das Leerzeichen-Zeichen (␣, U+2423) fehlt
        # in IBM Plex Mono und erschiene als Ersatzglyphe.
        self.kbd = QLabel("Leertaste", self)
        self.kbd.setObjectName("primaryKbd")
        self.kbd.setAlignment(Qt.AlignCenter)
        row.addWidget(self.kbd)
        row.addStretch(1)

        transparent_for_mouse(self._icon, self.title, self.subtitle, self.kbd)

    def retheme(self) -> None:
        self._icon.retheme()

    def changeEvent(self, event) -> None:        # noqa: N802 (Qt-API)
        super().changeEvent(event)
        if event.type() == QEvent.EnabledChange:
            off = not self.isEnabled()
            for w in (self.title, self.subtitle, self.kbd):
                _mark_disabled(w, off)


class ActionButton(QPushButton):
    """Sekundäraktion: Icon über umbrechendem Text, feste Breite."""

    def __init__(self, icon_name: str, text: str, parent=None):
        super().__init__(parent)
        self.setObjectName("barButton")
        self.setFixedWidth(_SECONDARY_WIDTH)
        self.setMinimumHeight(_BAR_HEIGHT)
        self.setCursor(Qt.PointingHandCursor)

        # Eng gerechnet: 72 px Hoehe muessen Icon (20) + Abstand + zwei
        # Textzeilen tragen, sonst schneidet Qt die zweite Zeile ab.
        col = QVBoxLayout(self)
        col.setContentsMargins(4, 6, 4, 6)
        col.setSpacing(4)
        col.setAlignment(Qt.AlignCenter)

        self._icon = _IconLabel(icon_name, _SECONDARY_ICON, "normal", self)
        col.addWidget(self._icon, alignment=Qt.AlignHCenter)

        self.label = QLabel(text, self)
        self.label.setObjectName("secondaryLabel")
        self.label.setWordWrap(True)
        self.label.setAlignment(Qt.AlignCenter)
        col.addWidget(self.label)

        transparent_for_mouse(self._icon, self.label)

    def retheme(self) -> None:
        self._icon.retheme()

    def changeEvent(self, event) -> None:        # noqa: N802 (Qt-API)
        super().changeEvent(event)
        if event.type() == QEvent.EnabledChange:
            _mark_disabled(self.label, not self.isEnabled())

    def label_text(self) -> str:
        """Sichtbarer Text. Bewusst NICHT `text()`: QPushButton.text() ist
        eine Qt-API, die der Stil zum Zeichnen nutzt – die Beschriftung
        steckt hier in einem Kindlabel."""
        return self.label.text()


class ActionBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("actionBar")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(12)

        self.identify_button = IdentifyButton(self)
        lay.addWidget(self.identify_button, stretch=1)

        self.background_button = ActionButton("camera", "Hintergrund\naufnehmen", self)
        self.calibrate_button = ActionButton("target", "Kalibrieren", self)
        self.enroll_button = ActionButton("plus", "Artikel\neinlernen…", self)
        for b in (self.background_button, self.calibrate_button,
                  self.enroll_button):
            lay.addWidget(b)

    def retheme(self) -> None:
        for b in (self.identify_button, self.background_button,
                  self.calibrate_button, self.enroll_button):
            b.retheme()
