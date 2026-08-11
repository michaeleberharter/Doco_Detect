"""Analyse-Sektion (Stufe 2): Lauf, Historie, Artefakt-Betrachter.

Der Analyse-Lauf rendert 17 Matplotlib-Abschnitte plus CSV/JSON — das
sind Sekunden, nicht Millisekunden (Freigabe 2026-08-11, Gegenteil des
9-ms-Befunds beim Report-Laden). Er läuft deshalb im vorhandenen
PipelineWorker-Muster, seriell, kein zweiter QThread-Pfad (Spec
Abschnitt 4). Fortschritt ist indeterminat (Busy-Bar): run_analysis hat
keinen Callback, und einer wäre ein weiterer analysis.py-Eingriff.

Alle Pfade kommen aus pipeline-Fassaden (run_report_analysis löst Quelle
UND Ziel auf, list_analysis_runs setzt das Listbarkeits-Kriterium um);
die Seite konstruiert keine Pfade aus der Config. Der Betrachter blättert
nur unter dem Lauf-Pfad, den die Fassade geliefert hat. Kein --publish,
kein --archive aus der UI (Read-only-Definition, Spec Abschnitt 5).
Die Historie ist nach der DATEIZEIT von report.md sortiert und so
beschriftet — run_ids sind teils frei vergeben, Namen sortieren nichts."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QPlainTextEdit, QProgressBar, QPushButton,
                               QTabWidget, QVBoxLayout, QWidget)

from docodetect.pipeline import list_analysis_runs, run_report_analysis

from ...pipeline_worker import PipelineWorker
from ...widgets.common import section_label

_LEER_STATUS = ("Noch keine Analyse-Läufe — Quellordner wählen "
                "(leer = captures_dir) und starten.")


def _dateizeit(unix: float) -> str:
    return datetime.fromtimestamp(unix).strftime("%d.%m.%Y %H:%M")


class LaufTab(QWidget):
    """Lauf starten + Historie + Betrachter. EIN Worker zur Zeit."""

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self._worker: PipelineWorker | None = None
        self._laeufe: list = []
        self._pngs: list = []
        self._png_index = 0

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(8)

        start_zeile = QHBoxLayout()
        self.quelle = QLineEdit()
        self.quelle.setPlaceholderText("Quellordner (leer = captures_dir)")
        self.run_id_feld = QLineEdit()
        self.run_id_feld.setPlaceholderText("Run-ID (leer = Zeitstempel)")
        self.start_button = QPushButton("Analyse-Lauf starten")
        self.start_button.clicked.connect(self.starte_lauf)
        start_zeile.addWidget(self.quelle, stretch=2)
        start_zeile.addWidget(self.run_id_feld, stretch=1)
        start_zeile.addWidget(self.start_button)
        lay.addLayout(start_zeile)

        self.fortschritt = QProgressBar()
        self.fortschritt.setRange(0, 0)          # indeterminat (Busy)
        self.fortschritt.setVisible(False)
        lay.addWidget(self.fortschritt)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.status)

        rumpf = QHBoxLayout()
        links = QVBoxLayout()
        links.addWidget(section_label("Lauf-Historie (Dateizeit)"))
        self.historie = QListWidget()
        self.historie.setFixedWidth(280)
        self.historie.currentRowChanged.connect(self._zeige_zeile)
        links.addWidget(self.historie, stretch=1)
        self.ungueltig_label = QLabel("")
        self.ungueltig_label.setWordWrap(True)
        links.addWidget(self.ungueltig_label)
        self.refresh_button = QPushButton("Aktualisieren")
        self.refresh_button.clicked.connect(self.reload_historie)
        links.addWidget(self.refresh_button, alignment=Qt.AlignLeft)
        rumpf.addLayout(links)

        rechts = QVBoxLayout()
        rechts.addWidget(section_label("report.md"))
        self.report_text = QPlainTextEdit()
        self.report_text.setReadOnly(True)
        self.report_text.setMaximumHeight(180)
        rechts.addWidget(self.report_text)
        png_kopf = QHBoxLayout()
        self.zurueck_button = QPushButton("◀")
        self.zurueck_button.clicked.connect(lambda: self.blaettern(-1))
        self.vor_button = QPushButton("▶")
        self.vor_button.clicked.connect(lambda: self.blaettern(1))
        self.png_name = QLabel("")
        for w in (self.zurueck_button, self.vor_button):
            w.setFixedWidth(40)
        png_kopf.addWidget(self.zurueck_button)
        png_kopf.addWidget(self.vor_button)
        png_kopf.addWidget(self.png_name, stretch=1)
        rechts.addLayout(png_kopf)
        self.png_label = QLabel("")
        self.png_label.setAlignment(Qt.AlignCenter)
        self.png_label.setMinimumHeight(220)
        rechts.addWidget(self.png_label, stretch=1)
        rumpf.addLayout(rechts, stretch=1)
        lay.addLayout(rumpf, stretch=1)

        self.reload_historie()

    # ---------- Historie ----------

    def reload_historie(self) -> None:
        self._laeufe, ungueltig = list_analysis_runs(self.cfg)
        self.historie.blockSignals(True)
        self.historie.clear()
        for lauf in self._laeufe:
            self.historie.addItem(
                f"{lauf.run_id} — Dateizeit {_dateizeit(lauf.mtime_unix)}")
        self.historie.blockSignals(False)
        self.ungueltig_label.setText(
            f"ungültig, {ungueltig} Stück (ohne report.md und/oder "
            "metrics.json — nicht gelistet, nie verschwiegen)"
            if ungueltig else "")
        if not self._laeufe and self._worker is None:
            self.status.setText(_LEER_STATUS)

    # ---------- Lauf ----------

    def _baue_job(self):
        """Testnaht: der Job ist ohne Thread aufrufbar. Bindet cfg/Quelle/
        Run-ID als Closure; die Fassade konstruiert alles Weitere IM
        Worker-Thread (SQLite-Thread-Affinität)."""
        cfg = self.cfg
        quelle = self.quelle.text().strip() or None
        run_id = self.run_id_feld.text().strip() or None

        def job():
            return run_report_analysis(cfg, reports_dir=quelle,
                                       run_id=run_id)
        return job

    def starte_lauf(self) -> None:
        if self._worker is not None:             # seriell: einer zur Zeit
            return
        self.start_button.setEnabled(False)
        self.fortschritt.setVisible(True)
        self.status.setText("Analyse-Lauf läuft …")
        w = PipelineWorker(self._baue_job(), self)
        w.finished_ok.connect(self._lauf_fertig)
        w.failed.connect(self._lauf_fehler)
        w.finished.connect(self._worker_beendet)
        self._worker = w
        w.start()

    def _worker_beendet(self) -> None:
        if self._worker is not None:
            self._worker.deleteLater()
        self._worker = None

    def _lauf_fertig(self, out_pfad) -> None:
        self.fortschritt.setVisible(False)
        self.start_button.setEnabled(True)
        out_pfad = Path(out_pfad)
        self.status.setText(f"Lauf fertig: {out_pfad.name} — {out_pfad}")
        self.reload_historie()
        for i, lauf in enumerate(self._laeufe):
            if lauf.run_id == out_pfad.name:
                self.historie.setCurrentRow(i)
                break
        else:
            self.status.setText(
                f"Lauf fertig: {out_pfad.name} — {out_pfad}\n"
                "Hinweis: ohne metrics.json (z. B. leerer Quellordner) "
                "zählt der Lauf als „ungültig“ und wird nicht gelistet.")

    def _lauf_fehler(self, text: str) -> None:
        self.fortschritt.setVisible(False)
        self.start_button.setEnabled(True)
        self.status.setText(f"Analyse-Lauf fehlgeschlagen: {text} — "
                            "Quellordner prüfen, dann erneut starten.")

    # ---------- Betrachter ----------

    def _zeige_zeile(self, row: int) -> None:
        if not (0 <= row < len(self._laeufe)):
            return
        self.zeige_lauf(self._laeufe[row])

    def zeige_lauf(self, lauf) -> None:
        try:
            text = (lauf.path / "report.md").read_text(
                encoding="utf-8", errors="replace")
        except OSError as e:
            text = f"report.md nicht lesbar: {e}"
        self.report_text.setPlainText(text)
        self._pngs = sorted(lauf.path.glob("*.png"))
        self._png_index = 0
        self._zeige_png()

    def blaettern(self, delta: int) -> None:
        if not self._pngs:
            return
        self._png_index = max(0, min(len(self._pngs) - 1,
                                     self._png_index + delta))
        self._zeige_png()

    def _zeige_png(self) -> None:
        if not self._pngs:
            self.png_name.setText("keine PNG-Artefakte")
            self.png_label.setPixmap(QPixmap())
            return
        p = self._pngs[self._png_index]
        self.png_name.setText(
            f"{p.name} ({self._png_index + 1}/{len(self._pngs)})")
        pix = QPixmap(str(p))
        if pix.isNull():
            self.png_label.setText(f"PNG nicht lesbar: {p.name}")
        else:
            self.png_label.setPixmap(pix.scaled(
                self.png_label.size(), Qt.KeepAspectRatio,
                Qt.SmoothTransformation))

    # ---------- Testhilfe ----------

    def werte(self) -> dict:
        """Rohe Anzeige-Werte (Muster status_page.werte)."""
        erste = self.report_text.toPlainText().splitlines()
        return {
            "historie": [lauf.run_id for lauf in self._laeufe],
            "ungueltig": self.ungueltig_label.text(),
            "status": self.status.text(),
            "report_erste_zeile": erste[0] if erste else "",
            "png": (self._pngs[self._png_index].name
                    if self._pngs else ""),
        }


class AnalysisPage(QWidget):
    """Sektion „Analyse" des Admin-Fensters (Spec Stufe 2, Punkte 6+7)."""

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.lauf_tab = LaufTab(cfg)
        self.tabs.addTab(self.lauf_tab, "Analyse-Lauf")
        lay.addWidget(self.tabs)
