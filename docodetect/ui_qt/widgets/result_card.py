"""Kandidaten-Karte: Name, Nummer, Ø gemessen vs. DB, Score-Balken.

Farbcodierung über die Qt-Property "tone" (accept/confirm/neutral) – die
Farben selbst stehen in style.qss. Die Karte rechnet NIE selbst: alle Werte
kommen fertig aus dem MatchReport (CandidateReport), inkl. der bereits
höhenkompensierten Ø-Werte.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QLabel, QProgressBar, QVBoxLayout


def _de(num: float, digits: int = 1) -> str:
    s = f"{num:.{digits}f}".rstrip("0").rstrip(".")
    return s.replace(".", ",")


class ResultCard(QFrame):
    clicked = Signal(str)   # article_number (manuelle Bestätigung bei AMBIGUOUS)

    def __init__(self, cand, tol_mm: float, tone: str = "neutral",
                 clickable: bool = False, parent=None):
        super().__init__(parent)
        self.article_number = cand.article_number
        self._clickable = clickable
        self.setObjectName("resultCard")
        self.setProperty("tone", tone)
        if clickable:
            self.setCursor(Qt.PointingHandCursor)
            self.setToolTip("Klicken bestätigt diesen Artikel.")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(4)

        name = QLabel(cand.name)
        name.setObjectName("cardName")
        name.setWordWrap(True)
        lay.addWidget(name)

        number = QLabel(cand.article_number)
        number.setObjectName("cardDim")
        lay.addWidget(number)

        # Die Zahl, die Vertrauen schafft: gemessen vs. Datenbank (beides mm,
        # höhenkompensiert aus dem Matcher – die UI rechnet nie selbst).
        measure = QLabel(
            f"Ø gemessen {_de(cand.corrected_diameter_mm)} mm · "
            f"Datenbank {_de(cand.nominal_size_mm)} mm (±{_de(tol_mm)})")
        measure.setObjectName("cardMeasure")
        measure.setWordWrap(True)
        lay.addWidget(measure)

        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(int(round(cand.posterior * 100)))
        bar.setFormat(f"{cand.posterior:.0%}")
        bar.setTextVisible(True)
        bar.setFixedHeight(16)
        lay.addWidget(bar)

        if not cand.has_references:
            hint = QLabel("Keine Referenzen – nur Geometrie, "
                          "Artikel zuerst einlernen.")
            hint.setObjectName("cardDim")
            hint.setWordWrap(True)
            lay.addWidget(hint)

    def set_tone(self, tone: str) -> None:
        self.setProperty("tone", tone)
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt-API)
        if self._clickable:
            self.clicked.emit(self.article_number)
        super().mousePressEvent(event)
