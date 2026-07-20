"""Linke Icon-Schiene: die vier Arbeitsschritte plus Theme-Umschalter.

Der Entwurf zeigt hier dieselben Aktionen wie die untere Leiste – bewusste
Redundanz: die Schiene ist der Orientierungsanker („wo bin ich"), die
Leiste die Bedienfläche für die Hand. Beide lösen dieselben Signale aus,
das Hauptfenster verdrahtet sie an genau eine Stelle.

Die Icons kommen aus icons.py und werden bei jedem Themewechsel neu
gezeichnet (`retheme()`), weil ihre Farbe vom Zustand abhängt: aktiv =
Akzentfarbe, sonst gedimmt.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QToolButton, QVBoxLayout, QWidget

from .. import icons
from ..app import current_theme

_RAIL_WIDTH = 78          # Entwurf
_BUTTON = 58              # Entwurf: 58x58, radius 12
_ICON = 20                # Entwurf: 20px Strichicon über dem Label

# (Schlüssel, Icon, Label) – Labels wie im Entwurf abgekürzt, damit sie in
# 58 px Breite passen.
_ACTIONS = (
    ("identify", "scan", "Scan"),
    ("background", "camera", "Hint."),
    ("calibrate", "target", "Kalib."),
    ("enroll", "plus", "Lernen"),
)


class ToolRail(QWidget):
    triggered = Signal(str)          # "identify" | "background" | ...
    theme_toggle = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("toolRail")
        self.setFixedWidth(_RAIL_WIDTH)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 14, 0, 14)
        lay.setSpacing(8)
        lay.setAlignment(Qt.AlignHCenter)

        self._buttons: dict = {}
        for key, icon_name, label in _ACTIONS:
            # NUR „Scan" ist einrastbar: es markiert den aktiven Bereich.
            # Die anderen drei sind Aktionen – blieben sie eingerastet,
            # sähe „Kalibrieren" nach einem Klick dauerhaft aktiv aus.
            b = self._make_button(icon_name, label, checkable=(key == "identify"))
            b.clicked.connect(lambda _=False, k=key: self.triggered.emit(k))
            self._buttons[key] = b
            lay.addWidget(b, alignment=Qt.AlignHCenter)

        lay.addStretch(1)             # Zahnrad unten angeheftet (Entwurf)
        self._gear = self._make_button("gear", "")
        self._gear.setToolTip("Zwischen dunklem und hellem Erscheinungsbild "
                              "wechseln")
        self._gear.clicked.connect(self.theme_toggle.emit)
        lay.addWidget(self._gear, alignment=Qt.AlignHCenter)

        self._buttons["identify"].setChecked(True)
        self.retheme()

    def _make_button(self, icon_name: str, label: str,
                     checkable: bool = False) -> QToolButton:
        b = QToolButton(self)
        b.setObjectName("railButton")
        b.setProperty("iconName", icon_name)
        b.setText(label)
        b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon
                             if label else Qt.ToolButtonIconOnly)
        b.setIconSize(QSize(_ICON, _ICON))
        b.setFixedSize(_BUTTON, _BUTTON)
        b.setCheckable(checkable)
        b.setCursor(Qt.PointingHandCursor)
        return b

    # ---------- Zustand ----------

    def retheme(self) -> None:
        """Icons in den Farben des aktiven Themes neu zeichnen."""
        t = current_theme()
        for b in list(self._buttons.values()) + [self._gear]:
            color = t["accent"] if b.isChecked() else t["dim"]
            b.setIcon(icons.icon(b.property("iconName"), _ICON, color))

    def set_enabled_actions(self, **states: bool) -> None:
        """z.B. set_enabled_actions(identify=False, background=True) – das
        Hauptfenster spiegelt hier seine Zustandsmaschine hinein."""
        for key, on in states.items():
            if key in self._buttons:
                self._buttons[key].setEnabled(on)

    def button(self, key: str) -> QToolButton | None:
        return self._buttons.get(key)
