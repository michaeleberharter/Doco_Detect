"""Dialog „Keiner davon / manuell korrigieren" (CONFIRM-Pfad).

Durchsuchbare Artikelliste (gleiches Muster wie der Einlern-Dialog) plus
Option „Unbekannt". Ergebnis fließt als verdict=wrong (+ wahrer Artikel)
in das Report-JSON — Futter für die Verwechslungsmatrix der
Batch-Auswertung. Kein Buchungs-Backend (Spec: Nicht-Ziele).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QCompleter, QDialog,
                               QDialogButtonBox, QLabel, QRadioButton,
                               QVBoxLayout)

UNKNOWN_LABEL = "Unbekannt / nicht in der Liste"


class CorrectionDialog(QDialog):
    def __init__(self, articles: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manuell korrigieren")
        self.setModal(True)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Welcher Artikel liegt wirklich in der Box?"))

        self._pick_known = QRadioButton("Artikel auswählen:")
        self._pick_known.setChecked(True)
        lay.addWidget(self._pick_known)

        self._combo = QComboBox()
        self._combo.setEditable(True)
        self._combo.setInsertPolicy(QComboBox.NoInsert)
        for a in articles:
            self._combo.addItem(f"{a.name}  ({a.article_number})",
                                a.article_number)
        comp = QCompleter([self._combo.itemText(i)
                           for i in range(self._combo.count())], self)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setFilterMode(Qt.MatchContains)
        self._combo.setCompleter(comp)
        lay.addWidget(self._combo)

        self._pick_unknown = QRadioButton(UNKNOWN_LABEL)
        lay.addWidget(self._pick_unknown)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def chosen(self) -> str | None:
        """Artikelnummer der Wahl; None = Unbekannt."""
        if self._pick_unknown.isChecked():
            return None
        return self._combo.currentData()
