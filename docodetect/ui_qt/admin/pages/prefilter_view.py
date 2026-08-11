"""Prefilter-Kill-Sicht (Melde-Punkt 1b): eigene Sicht, kein Filter.

Zeigt JEDEN vom Geometrie-Vorfilter verworfenen Kandidaten über alle
geladenen Reports — laut C-Serie sitzt dort das gesamte
False-Accept-Risiko. Wo ein Verdict/Label den wahren Artikel benennt,
wird markiert, ob DER unter den Kills war (die Auswertung des
Fixpunkt-Tests 2026-08-01, Befund 5, als stehende Sicht). Datenquelle
ist ausschließlich die `prefiltered`-Liste der Report-JSONs; eine leere
Liste heißt „keiner protokolliert" — auch bei Altbestand vor `59edc46`,
der das Feld noch nicht trug."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QLabel, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from .report_detail import kill_abstand_text


class PrefilterView(QWidget):
    detail_angefordert = Signal(int)      # Index in die geladene Report-Liste

    def __init__(self, parent=None):
        super().__init__(parent)
        self._zeilen: list = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(8)
        self._kopf = QLabel("")
        self._kopf.setWordWrap(True)
        lay.addWidget(self._kopf)
        self._tabelle = QTableWidget(0, 5)
        self._tabelle.setHorizontalHeaderLabels(
            ["Zeitpunkt", "Artikel", "Grund", "Abstand", ""])
        self._tabelle.verticalHeader().setVisible(False)
        self._tabelle.setEditTriggers(QTableWidget.NoEditTriggers)
        self._tabelle.setSelectionBehavior(QTableWidget.SelectRows)
        self._tabelle.cellDoubleClicked.connect(
            lambda row, _c: self.detail_angefordert.emit(
                self._zeilen[row]["report_index"]))
        lay.addWidget(self._tabelle, stretch=1)

    def set_data(self, eintraege: list) -> None:
        """`eintraege` = geladene (Path, MatchReport)-Paare des Browsers."""
        self._zeilen = []
        reports_mit_kills = 0
        for idx, (pfad, rep) in enumerate(eintraege):
            if not rep.prefiltered:
                continue
            reports_mit_kills += 1
            for kill in rep.prefiltered:
                self._zeilen.append({
                    "zeit": pfad.stem,
                    "artikel": kill.get("article_number", "?"),
                    "grund": kill.get("reason", "?"),
                    "abstand": kill_abstand_text(kill),
                    # Markierung: der laut Verdict/Label WAHRE Artikel
                    # kam gar nicht erst ins Kandidatenset.
                    "wahrer_artikel": bool(
                        rep.label
                        and kill.get("article_number") == rep.label),
                    "report_index": idx,
                })
        self._tabelle.setRowCount(len(self._zeilen))
        for r, z in enumerate(self._zeilen):
            marker = "WAHRER ARTIKEL" if z["wahrer_artikel"] else ""
            for c, wert in enumerate([z["zeit"], z["artikel"], z["grund"],
                                      z["abstand"], marker]):
                item = QTableWidgetItem(wert)
                if z["wahrer_artikel"]:
                    item.setForeground(Qt.red)
                self._tabelle.setItem(r, c, item)
        self._tabelle.resizeColumnsToContents()
        if self._zeilen:
            self._kopf.setText(
                f"{len(self._zeilen)} Prefilter-Kills in "
                f"{reports_mit_kills} von {len(eintraege)} geladenen "
                "Reports. Leere Kill-Liste heißt „keiner protokolliert“ — "
                "auch bei Reports vor der Messpfad-Runde (59edc46).")
        else:
            self._kopf.setText(
                "Keine Prefilter-Kills in den geladenen Reports. "
                "(Altbestand vor 59edc46 trägt das Feld nicht.)")

    # ---------- Testhilfen ----------

    def zeilen(self) -> list:
        return [dict(z) for z in self._zeilen]

    def kopf_text(self) -> str:
        return self._kopf.text()
