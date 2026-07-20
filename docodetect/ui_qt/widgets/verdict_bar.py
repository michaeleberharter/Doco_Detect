"""Richtig/Falsch-Bewertung einer Identifikation.

Diese Bewertung ist kein Beiwerk: sie landet im Report-JSON und ist die
Datengrundlage der Scoring-Analyse (Erfolgsrate, Verwechslungsmatrix,
Fehler-Attribution). Sie muss deshalb in ALLEN Anzeigezuständen erreichbar
sein – auch bei ACCEPT, wo man sie am ehesten vergisst, und gerade bei
REJECT: dass Bediener ein `reject` als „falsch" bewerten, war 2026-07-20
der Auslöser für die Fehldeutung „Vorfilter-Kill" in der Auswertung.

Bei ACCEPT tritt die Leiste bewusst zurück (Textlinks, kein Modal) und
blockiert nichts; bei AMBIGUOUS/REJECT führt „Falsch" direkt in die Wahl
des wahren Artikels.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                               QWidget)


class VerdictBar(QWidget):
    """`correct` = Top-1 bestätigt, `wrong` = wahren Artikel wählen."""

    correct = Signal()
    wrong = Signal()

    def __init__(self, prompt: str = "Stimmt das Ergebnis?",
                 wrong_text: str = "Falsch…", parent=None):
        super().__init__(parent)
        self.setObjectName("verdictBar")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(10)

        # Die Frage darf schrumpfen, die Tasten nicht: in der 372 px breiten
        # Ergebnisspalte sprengt eine lange Zeile sonst die ganze Karte.
        self.prompt = QLabel(prompt, self)
        self.prompt.setObjectName("verdictPrompt")
        self.prompt.setWordWrap(True)
        self.prompt.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        lay.addWidget(self.prompt, stretch=1)

        self.correct_button = QPushButton("Richtig", self)
        self.correct_button.setObjectName("verdictYes")
        self.correct_button.setCursor(Qt.PointingHandCursor)
        self.correct_button.clicked.connect(self.correct.emit)
        lay.addWidget(self.correct_button)

        self.wrong_button = QPushButton(wrong_text, self)
        self.wrong_button.setObjectName("verdictNo")
        self.wrong_button.setCursor(Qt.PointingHandCursor)
        self.wrong_button.clicked.connect(self.wrong.emit)
        lay.addWidget(self.wrong_button)

    def acknowledge(self, text: str) -> None:
        """Nach der Bewertung: quittieren statt verschwinden – der Bediener
        soll sehen, dass sein Urteil angekommen ist."""
        self.prompt.setText(text)
        self.correct_button.setEnabled(False)
        self.wrong_button.setEnabled(False)
