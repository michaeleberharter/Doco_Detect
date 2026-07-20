"""Ergebnisdarstellung der Ergebnisspalte: Siegerkarte, Zustandskarte,
Kandidatenzeile.

Vier Anzeigezustände (theme.TONES): accept, ambiguous, border, reject.
`border` – das Objekt berührt den Bildrand – ist bewusst ein EIGENER
Zustand in Amber und nicht als Ablehnung eingefärbt: die Messung ist nicht
falsch, sie ist nur nicht durchführbar.

Die Karten rechnen NIE selbst. Alle Zahlen kommen fertig aus dem
MatchReport; die mm-Strings stammen aus den zentralen Anzeige-Helfern in
docodetect.pipeline (Re-Export aus display.py), damit die Qt- und die
Streamlit-UI exakt denselben Text zeigen.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QProgressBar,
                               QPushButton, QVBoxLayout, QWidget)

from docodetect.pipeline import (channel_percentages, format_delta,
                                 format_diameter)

from .common import transparent_for_mouse
from .gauge import ToleranceGauge

_CHANNEL_TITLES = {"geometry": "Geometrie", "color": "Farbe", "shape": "Form"}


def _de(x: float, nd: int = 1) -> str:
    return f"{x:.{nd}f}".replace(".", ",")


def _stat(title: str, value: str, parent=None) -> QWidget:
    """Beschriftetes Zahlenfeld („Gemessen 141 mm") wie im Entwurf."""
    box = QWidget(parent)
    box.setObjectName("cardBox")
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(1)
    t = QLabel(title.upper(), box)
    t.setObjectName("statLabel")
    v = QLabel(value, box)
    v.setObjectName("statValue")
    lay.addWidget(t)
    lay.addWidget(v)
    return box


class ResultCard(QFrame):
    """Karte des Siegers: Artikel, Messwert gegen Stammdaten, Toleranzbalken.

    Die Teilscore-Balken (Geometrie/Farbe/Form) stecken in einem
    einklappbaren Detailbereich – standardmäßig zu, damit die Karte ruhig
    bleibt, aber nicht verloren."""

    clicked = Signal(str)          # article_number (Auswahl bei AMBIGUOUS)

    def __init__(self, candidate, cfg, clickable: bool = False,
                 tone: str = "accept", parent=None):
        super().__init__(parent)
        self.article_number = candidate.article_number
        self._clickable = clickable
        self.setObjectName("resultCard")
        self.setProperty("tone", tone)
        if clickable:
            self.setCursor(Qt.PointingHandCursor)
            self.setToolTip("Klicken bestätigt diesen Artikel.")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 13, 14, 13)
        lay.setSpacing(10)

        # Kopf: Name links, Artikelnummer rechts (Entwurf)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        name = QLabel(candidate.name, self)
        name.setObjectName("cardName")
        name.setWordWrap(True)
        head.addWidget(name, stretch=1)
        number = QLabel(candidate.article_number, self)
        number.setObjectName("cardSku")
        number.setAlignment(Qt.AlignRight | Qt.AlignTop)
        head.addWidget(number)
        lay.addLayout(head)

        tol = float(cfg["matching"]["diameter_tolerance_mm"])
        stats = QHBoxLayout()
        stats.setContentsMargins(0, 0, 0, 0)
        stats.setSpacing(18)
        stats.addWidget(_stat("Gemessen",
                              f"{_de(candidate.corrected_diameter_mm)} mm", self))
        stats.addWidget(_stat("Datenbank",
                              f"{_de(candidate.nominal_size_mm)} ±{_de(tol, 0)} mm",
                              self))
        stats.addStretch(1)
        lay.addLayout(stats)

        self.gauge = ToleranceGauge(candidate.nominal_size_mm,
                                    candidate.corrected_diameter_mm, tol, self)
        lay.addWidget(self.gauge)

        # Die zentralen Helfer bleiben sichtbar: sie nennen u.a., mit welcher
        # Artikelhöhe der Ø korrigiert wurde – dieselbe Zeile wie in Streamlit.
        self._diameter_label = QLabel(format_diameter(candidate), self)
        self._diameter_label.setObjectName("cardMeasure")
        self._diameter_label.setWordWrap(True)
        lay.addWidget(self._diameter_label)

        self._delta_label = QLabel(format_delta(candidate, cfg), self)
        self._delta_label.setObjectName("cardMeasure")
        self._delta_label.setWordWrap(True)
        lay.addWidget(self._delta_label)

        if not candidate.has_references:
            hint = QLabel("Keine Referenzen – nur Geometrie, "
                          "Artikel zuerst einlernen.", self)
            hint.setObjectName("cardHint")
            hint.setWordWrap(True)
            lay.addWidget(hint)

        lay.addWidget(self._build_details(candidate))

    # ---------- Detailbereich ----------

    def _build_details(self, candidate) -> QWidget:
        wrap = QWidget(self)
        wrap.setObjectName("cardBox")
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self.details_toggle = QPushButton("Details ▾", wrap)
        self.details_toggle.setObjectName("detailsToggle")
        self.details_toggle.setCursor(Qt.PointingHandCursor)
        self.details_toggle.setCheckable(True)
        lay.addWidget(self.details_toggle, alignment=Qt.AlignLeft)

        self.details_box = QWidget(wrap)
        self.details_box.setObjectName("cardBox")
        box = QVBoxLayout(self.details_box)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        caption = QLabel("Teilscores – 100 % = perfekte Übereinstimmung",
                         self.details_box)
        caption.setObjectName("channelTitle")
        caption.setWordWrap(True)
        box.addWidget(caption)
        box.addLayout(self._build_channel_bars(candidate))
        self.details_box.setVisible(False)          # Default: eingeklappt
        lay.addWidget(self.details_box)

        self.details_toggle.toggled.connect(self._toggle_details)
        return wrap

    def _toggle_details(self, on: bool) -> None:
        self.details_box.setVisible(on)
        self.details_toggle.setText("Details ▴" if on else "Details ▾")

    def _build_channel_bars(self, candidate):
        """Drei Mini-Balken (Geometrie/Farbe/Form); Kanal ohne Daten -> grauer
        Text 'keine Daten' statt Balken (None), nie falsche 100 %."""
        self._channel_bars = {}
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        for ch, pct in channel_percentages(candidate).items():
            col = QVBoxLayout()
            col.setSpacing(2)
            title = QLabel(_CHANNEL_TITLES[ch], self.details_box)
            title.setObjectName("channelTitle")
            col.addWidget(title)
            if pct is None:
                na = QLabel("keine Daten", self.details_box)
                na.setObjectName("channelNoData")
                col.addWidget(na)
                self._channel_bars[ch] = None
            else:
                bar = QProgressBar(self.details_box)
                bar.setRange(0, 100)
                bar.setValue(round(pct * 100))
                bar.setTextVisible(False)
                bar.setFixedHeight(6)
                col.addWidget(bar)
                self._channel_bars[ch] = bar
            row.addLayout(col)
        return row

    # ---------- Interaktion / Testhilfen ----------

    def add_footer(self, widget: QWidget) -> None:
        """Zusatzzeile unten AUF der Karte (die Richtig/Falsch-Bewertung)."""
        self.layout().addWidget(widget)

    def mousePressEvent(self, event) -> None:      # noqa: N802 (Qt-API)
        if self._clickable:
            self.clicked.emit(self.article_number)
        super().mousePressEvent(event)

    def all_text(self) -> str:
        """Alle Label-Texte (fuer Offscreen-Tests)."""
        return " | ".join(lbl.text() for lbl in self.findChildren(QLabel))

    def channel_bars(self) -> dict:
        return dict(self._channel_bars)


class ResultHeader(QWidget):
    """Kopfzeile der Ergebnisspalte: Zustands-Badge + Text links, Kennzahl
    rechts (Entwurf: Posterior in Prozent, „?" wenn es keinen gibt)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("resultHeader")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        self.badge = _Badge(self)
        lay.addWidget(self.badge)

        self.text = QLabel("", self)
        self.text.setObjectName("resultHeadline")
        self.text.setWordWrap(True)
        lay.addWidget(self.text, stretch=1)

        self.value = QLabel("", self)
        self.value.setObjectName("resultValue")
        self.value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(self.value)

    def show_state(self, tone: str, text: str, value: str = "") -> None:
        self.badge.set_tone(tone)
        # Das führende ✓ aus dem gemeinsamen headline()-Helfer entfällt hier:
        # das Badge links sagt dasselbe, und IBM Plex Sans trägt das Zeichen
        # nicht (Qt ersetzt es durch ein √). Der Wortlaut bleibt unangetastet
        # und identisch zur Streamlit-UI.
        self.text.setText(text[1:].strip() if text.startswith("✓") else text)
        self.text.setProperty("tone", tone)
        self.text.style().unpolish(self.text)
        self.text.style().polish(self.text)
        self.value.setText(value)
        self.value.setProperty("tone", tone)
        self.value.style().unpolish(self.value)
        self.value.style().polish(self.value)


class _Badge(QWidget):
    """18-px-Kreis in der Zustandsfarbe mit Haken bzw. Ausrufezeichen."""

    _SIZE = 18

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(self._SIZE, self._SIZE)
        self._tone = "accept"

    def set_tone(self, tone: str) -> None:
        self._tone = tone
        self.update()

    def paintEvent(self, event) -> None:      # noqa: N802 (Qt-API)
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QColor, QPainter

        from .. import icons
        from ..app import current_theme

        t = current_theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(t.tone_color(self._tone)))
        p.drawEllipse(QRectF(0, 0, self._SIZE, self._SIZE))
        name = "check" if self._tone == "accept" else "alert"
        icons.paint(p, name, QRectF(3, 3, self._SIZE - 6, self._SIZE - 6),
                    "#ffffff", stroke=2.4)
        p.end()


class MessageCard(QFrame):
    """Zustandskarte ohne Artikel: AMBIGUOUS, REJECT und Randberührung.

    Optional mit grossem Messwert (Entwurf: „141 mm" im Nicht-gefunden-
    Zustand) und einer Handlungstaste („Als neuen Artikel einlernen")."""

    action = Signal()

    def __init__(self, tone: str, title: str, subtitle: str | None = None,
                 big_value: str | None = None, action_text: str | None = None,
                 parent=None):
        super().__init__(parent)
        self.setObjectName("resultCard")
        self.setProperty("tone", tone)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 13, 14, 13)
        lay.setSpacing(8)

        self.title_label = QLabel(title, self)
        self.title_label.setObjectName("cardName")
        self.title_label.setWordWrap(True)
        lay.addWidget(self.title_label)

        if subtitle:
            sub = QLabel(subtitle, self)
            sub.setObjectName("cardHint")
            sub.setWordWrap(True)
            lay.addWidget(sub)

        if big_value:
            cap = QLabel("GEMESSEN", self)
            cap.setObjectName("statLabel")
            lay.addWidget(cap)
            val = QLabel(big_value, self)
            val.setObjectName("bigValue")
            lay.addWidget(val)

        if action_text:
            self.action_button = QPushButton(action_text, self)
            self.action_button.setObjectName("primaryButton")
            self.action_button.setCursor(Qt.PointingHandCursor)
            self.action_button.clicked.connect(self.action.emit)
            lay.addWidget(self.action_button)

    def add_footer(self, widget: QWidget) -> None:
        """Zusatzzeile unten AUF der Karte (die Richtig/Falsch-Bewertung)."""
        self.layout().addWidget(widget)

    def all_text(self) -> str:
        return " | ".join(lbl.text() for lbl in self.findChildren(QLabel))


class CandidateRow(QFrame):
    """Eine Zeile der Kandidatenliste: Name, DB-Maß und Δ, Balken, Prozent."""

    clicked = Signal(str)

    def __init__(self, candidate, cfg, rank: int, clickable: bool = False,
                 parent=None):
        super().__init__(parent)
        self.article_number = candidate.article_number
        self._clickable = clickable
        self.setObjectName("candidateRow")
        if clickable:
            self.setCursor(Qt.PointingHandCursor)
            self.setToolTip("Klicken bestätigt diesen Artikel.")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(11, 9, 11, 9)
        lay.setSpacing(10)

        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(1)
        name = QLabel(f"{rank}. {candidate.name}", self)
        name.setObjectName("rowName")
        left.addWidget(name)
        # Δ kommt aus dem zentralen Helfer, damit Qt und Streamlit dieselbe
        # Zahl im selben Format zeigen (der Entwurf gibt nur das Layout vor,
        # nicht die Formatierung).
        meta = QLabel(f"DB {_de(candidate.nominal_size_mm, 0)} · "
                      f"{format_delta(candidate, cfg)}", self)
        meta.setObjectName("rowMeta")
        left.addWidget(meta)
        lay.addLayout(left, stretch=1)

        self.bar = QProgressBar(self)
        self.bar.setRange(0, 100)
        self.bar.setValue(int(round(candidate.posterior * 100)))
        self.bar.setTextVisible(False)
        self.bar.setFixedSize(74, 6)
        self.bar.setProperty("tone", _posterior_tone(candidate.posterior))
        lay.addWidget(self.bar)

        pct = QLabel(f"{candidate.posterior * 100:.0f} %", self)
        pct.setObjectName("rowPercent")
        pct.setProperty("tone", _posterior_tone(candidate.posterior))
        lay.addWidget(pct)

        transparent_for_mouse(name, meta, pct)

    def mousePressEvent(self, event) -> None:      # noqa: N802 (Qt-API)
        if self._clickable:
            self.clicked.emit(self.article_number)
        super().mousePressEvent(event)

    def all_text(self) -> str:
        return " | ".join(lbl.text() for lbl in self.findChildren(QLabel))


def _posterior_tone(posterior: float) -> str:
    """Farbstufe der Kandidatenzeile (Entwurf: hoch grün, mittel amber,
    niedrig rot). Rein visuell – die Entscheidung trifft der Matcher."""
    if posterior >= 0.6:
        return "high"
    if posterior >= 0.25:
        return "mid"
    return "low"
