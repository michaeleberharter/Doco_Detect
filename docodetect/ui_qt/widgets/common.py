"""Kleine gemeinsame Bausteine des Redesign-Layouts.

Hier landet, was QSS nicht kann und was sonst in jedem Widget einzeln
nachgebaut werden müsste – vor allem die Sperrung der Abschnittslabels:
`letter-spacing` gibt es in Qt-Stylesheets nicht, das muss über QFont laufen.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLabel, QWidget

# Entwurf: Abschnittslabels 10px/700, letter-spacing .12em -> 112 %.
_SECTION_SPACING = 112.0


def set_letter_spacing(widget: QWidget, percent: float = _SECTION_SPACING) -> None:
    f = widget.font()
    f.setLetterSpacing(QFont.PercentageSpacing, percent)
    widget.setFont(f)


def section_label(text: str, parent: QWidget | None = None) -> QLabel:
    """Abschnittsüberschrift („WEITERE KANDIDATEN", „VERLAUF").

    Gross geschrieben wird der TEXT, nicht per Stylesheet: QSS kennt
    `text-transform` nicht (die frühere Regel im Stylesheet war wirkungslos)."""
    lbl = QLabel(text.upper(), parent)
    lbl.setObjectName("sectionLabel")
    set_letter_spacing(lbl)
    return lbl


def transparent_for_mouse(*widgets: QWidget) -> None:
    """Kindlabels in einem Button dürfen dessen Klick nicht schlucken.
    Betrifft die grosse Identifizieren-Fläche, die Icon, Titel, Unterzeile
    und Tasten-Chip als echte Labels enthält."""
    for w in widgets:
        w.setAttribute(Qt.WA_TransparentForMouseEvents, True)
