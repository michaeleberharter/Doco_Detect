"""Reports-Sektion (Melde-Punkt 1b): Browser + Prefilter-Kills + Detail.

Zwei Sichten als Tabs (die Kill-Sicht ist eine EIGENE Sicht, kein Filter
im Browser — Review-Festlegung 2026-08-08), darüber ein Stack mit der
Einzelreport-Ansicht (Doppelklick öffnet, „Zurück" schließt). Daten kommen
ausschließlich über `pipeline.load_saved_reports` (Dateiname-Sortierung,
neueste zuerst); geladen wird synchron — Befund 2026-08-11: 23 Reports in
9 ms, ein Worker-Thread wäre reines Teardown-Risiko ohne Nutzen
(Abweichung von Spec „im Worker", am Melde-Punkt gemeldet).

Die „letzte Live-Identifikation" ist nach „Aktualisieren" der oberste
Browser-Eintrag — jede Identifikation liegt als Report-JSON in
captures_dir; es braucht keinen dritten Meldekanal vom Hauptfenster."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QStackedWidget, QTableWidget,
                               QTableWidgetItem, QTabWidget, QVBoxLayout,
                               QWidget)

from docodetect.pipeline import (NO_MATCH, load_saved_reports,
                                 report_predicted_article)

from .prefilter_view import PrefilterView
from .report_detail import ReportDetailView

# Obergrenze des Browsers (Spec Abschnitt 6, Punkt 3): Zukunftsschutz für
# den Box-Betrieb — Befund 2026-08-11: aktuell 23 Report-JSONs, 9 ms.
_LIMIT = 500

_KEIN_KANDIDAT = "— kein Kandidat"     # NO_MATCH ist ein Zustand, kein Artikel
_BEWERTUNGEN = {"Richtig": True, "Falsch": False, "unbewertet": None}


def _tone(report) -> str:
    """Anzeigezustand — dieselben vier wie MainWindow.report_tone."""
    if report.touches_border:
        return "border"
    if report.decision in ("accept", "ambiguous"):
        return report.decision
    return "reject"


def _artikel_text(report) -> str:
    pred = report_predicted_article(report)
    return _KEIN_KANDIDAT if pred == NO_MATCH else pred


def _bewertung_text(report) -> str:
    from docodetect.pipeline import report_judgement
    urteil = report_judgement(report)
    return {True: "Richtig", False: "Falsch", None: "unbewertet"}[urteil]


def _zeit_text(stem: str) -> str:
    try:
        return datetime.strptime(stem + "000", "%Y%m%d-%H%M%S-%f") \
            .strftime("%d.%m.%Y %H:%M:%S")
    except ValueError:
        return stem                        # Fremddatei: Name roh anzeigen


def _gefiltert(eintraege, entscheidung, bewertung, artikel, von, bis):
    """Reine Filterfunktion über (Path, MatchReport)-Paare. Zeitraum
    vergleicht lexikografisch auf dem Dateinamens-Stem (ms-Zeitstempel)."""
    out = []
    for pfad, rep in eintraege:
        if entscheidung and _tone(rep) != entscheidung:
            continue
        if bewertung and _bewertung_text(rep) != bewertung:
            continue
        if artikel and artikel not in _artikel_text(rep):
            continue
        stem = pfad.stem
        if von and stem < von:
            continue
        if bis and stem > bis + "￿":  # bis-Präfix inklusiv
            continue
        out.append((pfad, rep))
    return out


class BrowserTab(QWidget):
    doppelklick = Signal(int)              # Zeile in der GEFILTERTEN Liste

    def __init__(self, parent=None):
        super().__init__(parent)
        self._alle: list = []
        self._limit_aktiv = False
        self._nachlader = None             # lädt ALLE (ohne Limit) nach
        self.gefiltert: list = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(8)

        filter_zeile = QHBoxLayout()
        self._f_entscheidung = QComboBox()
        self._f_entscheidung.addItems(["Alle", "accept", "ambiguous",
                                       "reject", "border"])
        self._f_bewertung = QComboBox()
        self._f_bewertung.addItems(["Alle", "Richtig", "Falsch",
                                    "unbewertet"])
        self._f_artikel = QLineEdit()
        self._f_artikel.setPlaceholderText("Artikel enthält …")
        self._f_von = QLineEdit()
        self._f_von.setPlaceholderText("von (JJJJMMTT[-HHMMSS])")
        self._f_bis = QLineEdit()
        self._f_bis.setPlaceholderText("bis")
        for w, label in ((self._f_entscheidung, "Entscheidung"),
                         (self._f_bewertung, "Bewertung"),
                         (self._f_artikel, None), (self._f_von, None),
                         (self._f_bis, None)):
            if label:
                filter_zeile.addWidget(QLabel(label))
            filter_zeile.addWidget(w)
        filter_zeile.addStretch(1)
        lay.addLayout(filter_zeile)
        self._f_entscheidung.currentTextChanged.connect(self._anwenden)
        self._f_bewertung.currentTextChanged.connect(self._anwenden)
        self._f_artikel.textChanged.connect(self._anwenden)
        self._f_von.editingFinished.connect(self._anwenden)
        self._f_bis.editingFinished.connect(self._anwenden)

        self._hinweis = QLabel("")
        self._hinweis.setWordWrap(True)
        lay.addWidget(self._hinweis)

        self._tabelle = QTableWidget(0, 4)
        self._tabelle.setHorizontalHeaderLabels(
            ["Zeitpunkt", "Entscheidung", "Artikel", "Bewertung"])
        self._tabelle.verticalHeader().setVisible(False)
        self._tabelle.setEditTriggers(QTableWidget.NoEditTriggers)
        self._tabelle.setSelectionBehavior(QTableWidget.SelectRows)
        self._tabelle.setSortingEnabled(False)
        self._tabelle.cellDoubleClicked.connect(
            lambda row, _c: self.doppelklick.emit(row))
        lay.addWidget(self._tabelle, stretch=1)

    # ---------- Daten & Filter ----------

    def set_data(self, eintraege: list, limit_aktiv: bool,
                 nachlader=None) -> None:
        self._alle = eintraege
        self._limit_aktiv = limit_aktiv
        self._nachlader = nachlader
        self._anwenden()

    def set_filter(self, entscheidung=None, bewertung=None, artikel="",
                   von="", bis="") -> None:
        """Testhilfe + programmatischer Weg: setzt Controls und wendet an."""
        self._f_entscheidung.setCurrentText(entscheidung or "Alle")
        self._f_bewertung.setCurrentText(bewertung or "Alle")
        self._f_artikel.setText(artikel)
        self._f_von.setText(von)
        self._f_bis.setText(bis)
        self._anwenden()

    def _anwenden(self) -> None:
        von, bis = self._f_von.text().strip(), self._f_bis.text().strip()
        basis = self._alle
        # Zeitraum gesetzt und Obergrenze aktiv: gezielt ALLES nachladen,
        # sonst fehlte der Zeitraum jenseits der neuesten _LIMIT (Spec §6).
        if (von or bis) and self._limit_aktiv and self._nachlader:
            basis = self._nachlader()
        ent = self._f_entscheidung.currentText()
        bew = self._f_bewertung.currentText()
        self.gefiltert = _gefiltert(
            basis, "" if ent == "Alle" else ent,
            "" if bew == "Alle" else bew,
            self._f_artikel.text().strip(), von, bis)
        self._tabelle.setRowCount(len(self.gefiltert))
        for r, (pfad, rep) in enumerate(self.gefiltert):
            for c, wert in enumerate([_zeit_text(pfad.stem), _tone(rep),
                                      _artikel_text(rep),
                                      _bewertung_text(rep)]):
                self._tabelle.setItem(r, c, QTableWidgetItem(wert))
        self._tabelle.resizeColumnsToContents()
        self._hinweis.setText(
            f"Zeigt die neuesten {len(self._alle)} Reports — ältere "
            "vorhanden, Zeitraum-Filter setzen, um sie zu laden."
            if self._limit_aktiv and not (von or bis) else "")

    # ---------- Testhilfen ----------

    def zeilen(self) -> list:
        return [{"zeit": _zeit_text(p.stem), "entscheidung": _tone(r),
                 "artikel": _artikel_text(r), "bewertung": _bewertung_text(r)}
                for p, r in self.gefiltert]

    def hinweis_text(self) -> str:
        return self._hinweis.text()


class ReportsPage(QWidget):
    """Sektion „Reports" des Admin-Fensters: Übersicht (Tabs) + Detail."""

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._stack = QStackedWidget()
        lay.addWidget(self._stack)

        uebersicht = QWidget()
        u_lay = QVBoxLayout(uebersicht)
        u_lay.setContentsMargins(0, 0, 0, 0)
        kopf = QHBoxLayout()
        kopf.setContentsMargins(16, 10, 16, 0)
        self.refresh_button = QPushButton("Aktualisieren")
        self.refresh_button.clicked.connect(self.reload)
        kopf.addWidget(self.refresh_button, alignment=Qt.AlignLeft)
        kopf.addStretch(1)
        u_lay.addLayout(kopf)
        self.tabs = QTabWidget()
        self.browser = BrowserTab()
        self.kills = PrefilterView()
        self.tabs.addTab(self.browser, "Browser")
        self.tabs.addTab(self.kills, "Prefilter-Kills")
        u_lay.addWidget(self.tabs, stretch=1)
        self._stack.addWidget(uebersicht)

        detail_wrap = QWidget()
        d_lay = QVBoxLayout(detail_wrap)
        d_lay.setContentsMargins(0, 0, 0, 0)
        zurueck_zeile = QHBoxLayout()
        zurueck_zeile.setContentsMargins(16, 10, 16, 0)
        self.zurueck_button = QPushButton("← Zurück zur Liste")
        self.zurueck_button.clicked.connect(self.zurueck)
        zurueck_zeile.addWidget(self.zurueck_button, alignment=Qt.AlignLeft)
        zurueck_zeile.addStretch(1)
        d_lay.addLayout(zurueck_zeile)
        self.detail = ReportDetailView()
        d_lay.addWidget(self.detail, stretch=1)
        self._stack.addWidget(detail_wrap)

        self.browser.doppelklick.connect(self.zeige_detail_fuer_zeile)
        self.kills.detail_angefordert.connect(self._zeige_report_index)
        self._eintraege: list = []
        self.reload()

    # ---------- Laden ----------

    def reload(self) -> None:
        alle = load_saved_reports(self.cfg, limit=_LIMIT + 1)
        limit_aktiv = len(alle) > _LIMIT
        self._eintraege = alle[:_LIMIT]
        self.browser.set_data(self._eintraege, limit_aktiv,
                              nachlader=lambda: load_saved_reports(self.cfg))
        self.kills.set_data(self._eintraege)

    # ---------- Navigation ----------

    def zeige_detail_fuer_zeile(self, row: int) -> None:
        pfad, rep = self.browser.gefiltert[row]
        self.detail.set_report(pfad, rep)
        self._stack.setCurrentIndex(1)

    def _zeige_report_index(self, index: int) -> None:
        pfad, rep = self._eintraege[index]
        self.detail.set_report(pfad, rep)
        self._stack.setCurrentIndex(1)

    def zurueck(self) -> None:
        self._stack.setCurrentIndex(0)

    def aktueller_index(self) -> int:
        return self._stack.currentIndex()
