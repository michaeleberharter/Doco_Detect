"""Kandidaten-Karte: Name, Nummer, Ø/Δ (zentrale Helfer), Posterior-Balken +
Teilscore-Balken (Geometrie/Farbe/Form).

Die Karte ist visuell neutral – KEIN zustandsabhängiger Rahmen mehr; Status
wird ausschließlich über die Headline im MainWindow signalisiert (Task 5).
Der clickable-Hover (Cursor + Tooltip bei AMBIGUOUS-Bestätigung) bleibt.
Die Karte rechnet NIE selbst: alle Werte kommen fertig aus dem MatchReport
(CandidateReport); Ø/Δ-Strings kommen aus den zentralen Anzeige-Helfern in
docodetect.pipeline (Re-Export aus display.py), damit Qt- und Streamlit-UI
exakt denselben Text zeigen.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QProgressBar,
                               QVBoxLayout)

from docodetect.pipeline import (channel_percentages, format_delta,
                                 format_diameter)

_CHANNEL_TITLES = {"geometry": "Geometrie", "color": "Farbe", "shape": "Form"}


class ResultCard(QFrame):
    clicked = Signal(str)   # article_number (manuelle Bestätigung bei AMBIGUOUS)

    def __init__(self, candidate, cfg, clickable: bool = False, parent=None):
        super().__init__(parent)
        self.article_number = candidate.article_number
        self._clickable = clickable
        self.setObjectName("resultCard")
        if clickable:
            self.setCursor(Qt.PointingHandCursor)
            self.setToolTip("Klicken bestätigt diesen Artikel.")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(4)

        name = QLabel(candidate.name)
        name.setObjectName("cardName")
        name.setWordWrap(True)
        lay.addWidget(name)

        number = QLabel(candidate.article_number)
        number.setObjectName("cardDim")
        lay.addWidget(number)

        # Die Zahlen, die Vertrauen schaffen: kandidatenspezifischer,
        # höhenkompensierter Ø sowie Δ zur Toleranz – beide Strings kommen
        # aus den zentralen Helfern, nie hier neu formatiert.
        self._diameter_label = QLabel(format_diameter(candidate))
        self._diameter_label.setObjectName("cardMeasure")
        self._diameter_label.setWordWrap(True)
        lay.addWidget(self._diameter_label)

        self._delta_label = QLabel(format_delta(candidate, cfg))
        self._delta_label.setObjectName("cardMeasure")
        self._delta_label.setWordWrap(True)
        lay.addWidget(self._delta_label)

        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(int(round(candidate.posterior * 100)))
        bar.setFormat(f"{candidate.posterior:.0%}")
        bar.setTextVisible(True)
        bar.setFixedHeight(16)
        lay.addWidget(bar)

        lay.addLayout(self._build_channel_bars(candidate))

        if not candidate.has_references:
            hint = QLabel("Keine Referenzen – nur Geometrie, "
                          "Artikel zuerst einlernen.")
            hint.setObjectName("cardDim")
            hint.setWordWrap(True)
            lay.addWidget(hint)

    def _build_channel_bars(self, candidate):
        """Drei Mini-Balken (Geometrie/Farbe/Form); Kanal ohne Daten -> grauer
        Text 'keine Daten' statt Balken (None), nie falsche 100 %."""
        self._channel_bars = {}
        row = QHBoxLayout()
        for ch, pct in channel_percentages(candidate).items():
            col = QVBoxLayout()
            title = QLabel(_CHANNEL_TITLES[ch])
            title.setObjectName("channelTitle")
            col.addWidget(title)
            if pct is None:
                na = QLabel("keine Daten")
                na.setObjectName("channelNoData")
                col.addWidget(na)
                self._channel_bars[ch] = None
            else:
                bar = QProgressBar()
                bar.setRange(0, 100)
                bar.setValue(round(pct * 100))
                bar.setTextVisible(False)
                bar.setFixedHeight(6)
                col.addWidget(bar)
                self._channel_bars[ch] = bar
            row.addLayout(col)
        return row

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt-API)
        if self._clickable:
            self.clicked.emit(self.article_number)
        super().mousePressEvent(event)

    def all_text(self) -> str:
        """Alle sichtbaren Label-Texte (fuer Offscreen-Tests)."""
        return " | ".join(lbl.text() for lbl in self.findChildren(QLabel))

    def channel_bars(self) -> dict:
        return dict(self._channel_bars)
