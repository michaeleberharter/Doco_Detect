"""Verlauf der laufenden Sitzung: was wurde wann als was erkannt.

Bewusst NUR im Speicher und nur für diese Sitzung. Die dauerhafte Spur sind
die MatchReport-JSONs unter `paths.captures_dir`; sie werden von der
Scoring-Analyse ausgewertet. „Leeren" räumt deshalb ausschliesslich die
Anzeige auf und fasst keine Datei an – sonst verlöre man Messdaten durch
einen Klick, der nach Aufräumen aussieht.

Jede Zeile trägt die Farbe ihres Anzeigezustands (accept/ambiguous/border/
reject), damit eine Serie von Fehlschlägen sofort ins Auge fällt.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout,
                               QWidget)

from ..app import current_theme

_DOT = 8                  # Entwurf
_MAX_ROWS = 50            # mehr sieht niemand an; hält die Spalte flott


@dataclass
class HistoryEntry:
    time: str
    name: str
    value: str
    tone: str


def entry_from_report(report, tone: str) -> HistoryEntry:
    """MatchReport -> Verlaufszeile. Ohne Kandidat steht der Zustand statt
    eines Artikelnamens da (der Bediener soll den Fehlschlag wiederfinden)."""
    when = datetime.now().strftime("%H:%M")
    if report.candidates and tone in ("accept", "ambiguous"):
        top = report.candidates[0]
        return HistoryEntry(when, top.name, f"{top.posterior * 100:.0f} %", tone)
    name = ("Bildrand berührt" if tone == "border" else "Kein Treffer")
    return HistoryEntry(when, name, "–", tone)


class _Dot(QWidget):
    def __init__(self, tone: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(_DOT, _DOT)
        self._tone = tone

    def paintEvent(self, event) -> None:      # noqa: N802 (Qt-API)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(current_theme().tone_color(self._tone)))
        p.drawEllipse(QRectF(0, 0, _DOT, _DOT))
        p.end()


class HistoryRow(QWidget):
    def __init__(self, entry: HistoryEntry, parent=None):
        super().__init__(parent)
        self.setObjectName("historyRow")
        self.entry = entry
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 5, 2, 5)
        lay.setSpacing(11)

        lay.addWidget(_Dot(entry.tone, self))

        self.time_label = QLabel(entry.time, self)
        self.time_label.setObjectName("historyTime")
        lay.addWidget(self.time_label)

        self.name_label = QLabel(entry.name, self)
        self.name_label.setObjectName("historyName")
        # Lange Artikelnamen dürfen die Spalte nicht sprengen.
        self.name_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        lay.addWidget(self.name_label, stretch=1)

        self.value_label = QLabel(entry.value, self)
        self.value_label.setObjectName("historyValue")
        self.value_label.setProperty("tone", entry.tone)
        lay.addWidget(self.value_label)

    def text(self) -> str:
        return (f"{self.time_label.text()} {self.name_label.text()} "
                f"{self.value_label.text()}")


class HistoryList(QWidget):
    """Neueste Identifikation oben."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("historyList")
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(0)
        self._empty = QLabel("Noch keine Identifikation in dieser Sitzung.",
                             self)
        self._empty.setObjectName("historyEmpty")
        self._empty.setWordWrap(True)
        self._lay.addWidget(self._empty)
        self._rows: list = []

    def add(self, entry: HistoryEntry) -> HistoryRow:
        row = HistoryRow(entry, self)
        self._lay.insertWidget(0, row)          # neueste oben
        self._rows.insert(0, row)
        while len(self._rows) > _MAX_ROWS:
            old = self._rows.pop()
            self._lay.removeWidget(old)
            old.deleteLater()
        self._empty.setVisible(False)
        return row

    def clear(self) -> None:
        """Nur die ANZEIGE leeren – die Report-JSONs bleiben unangetastet."""
        for row in self._rows:
            self._lay.removeWidget(row)
            row.deleteLater()
        self._rows = []
        self._empty.setVisible(True)

    def count(self) -> int:
        return len(self._rows)

    def texts(self) -> list:
        return [r.text() for r in self._rows]
