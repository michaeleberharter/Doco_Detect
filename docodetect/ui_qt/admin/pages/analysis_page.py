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
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QPlainTextEdit, QProgressBar,
                               QPushButton, QTableWidget, QTableWidgetItem,
                               QTabWidget, QVBoxLayout, QWidget)

from docodetect.pipeline import (NO_MATCH, export_analysis_run,
                                 list_analysis_runs, load_saved_reports,
                                 natuerlicher_schluessel, report_judgement,
                                 report_predicted_article,
                                 run_report_analysis)

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
        # Export (Freigabe 2026-08-11): nur mit ausgewähltem Lauf aktiv —
        # die Historie listet ohnehin nur gültige Läufe. Ziel je Export
        # über den Dialog, kein gespeicherter Default.
        export_zeile = QHBoxLayout()
        self.export_ordner_button = QPushButton("Exportieren als Ordner …")
        self.export_ordner_button.clicked.connect(
            lambda: self._export(als_zip=False))
        self.export_zip_button = QPushButton("Exportieren als ZIP …")
        self.export_zip_button.clicked.connect(
            lambda: self._export(als_zip=True))
        for b in (self.export_ordner_button, self.export_zip_button):
            b.setEnabled(False)
            export_zeile.addWidget(b)
        links.addLayout(export_zeile)
        self.historie.currentRowChanged.connect(self._update_export_buttons)
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
        self._update_export_buttons(self.historie.currentRow())

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

    # ---------- Export (Freigabe 2026-08-11) ----------

    def _update_export_buttons(self, row: int) -> None:
        aktiv = 0 <= row < len(self._laeufe)
        self.export_ordner_button.setEnabled(aktiv)
        self.export_zip_button.setEnabled(aktiv)

    def _frage_ordner_ziel(self) -> str:
        """Dialog-Naht: Elternordner wählen, Ziel = <eltern>/<run_id>.
        Leerer String = Abbruch."""
        lauf = self._laeufe[self.historie.currentRow()]
        eltern = QFileDialog.getExistingDirectory(
            self, "Zielordner wählen — der Lauf wird als Unterordner "
                  f"„{lauf.run_id}“ angelegt")
        return str(Path(eltern) / lauf.run_id) if eltern else ""

    def _frage_zip_ziel(self, vorschlag: str) -> str:
        """Dialog-Naht: ZIP-Ziel wählen. DontConfirmOverwrite — ob
        überschrieben wird, entscheidet die Fassade (nie)."""
        pfad, _filter = QFileDialog.getSaveFileName(
            self, "Lauf als ZIP exportieren", vorschlag,
            "ZIP-Archiv (*.zip)", options=QFileDialog.DontConfirmOverwrite)
        return pfad

    def _export(self, als_zip: bool) -> None:
        row = self.historie.currentRow()
        if not (0 <= row < len(self._laeufe)):
            return
        lauf = self._laeufe[row]
        ziel = (self._frage_zip_ziel(f"{lauf.run_id}.zip") if als_zip
                else self._frage_ordner_ziel())
        if not ziel:
            return                          # Abbruch im Dialog
        try:
            pfad = export_analysis_run(lauf.path, ziel, als_zip=als_zip)
        except Exception as e:  # noqa: BLE001 — jeder Fehler als Text
            self.status.setText(f"Export fehlgeschlagen: {e}")
            return
        self.status.setText(f"Export fertig: {pfad}")

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


_KEIN_KANDIDAT = "— kein Kandidat"     # NO_MATCH ist ein Zustand, kein Artikel


def _aggregiere(eintraege):
    """Reine Zählung auf Anzeige-Ebene (Spec Punkt 7, keine Kennzahlen-
    Nachrechnung): je VORHERGESAGTEM Artikel richtig/falsch/unbewertet.
    -> (zeilen, gesamt_text)."""
    zaehler: dict = {}
    for _pfad, rep in eintraege:
        pred = report_predicted_article(rep)
        key = _KEIN_KANDIDAT if pred == NO_MATCH else pred
        z = zaehler.setdefault(key, {"richtig": 0, "falsch": 0,
                                     "unbewertet": 0})
        urteil = report_judgement(rep)
        if urteil is True:
            z["richtig"] += 1
        elif urteil is False:
            z["falsch"] += 1
        else:
            z["unbewertet"] += 1
    zeilen = []
    artikel = sorted((k for k in zaehler if k != _KEIN_KANDIDAT),
                     key=natuerlicher_schluessel)
    if _KEIN_KANDIDAT in zaehler:
        artikel.append(_KEIN_KANDIDAT)
    for k in artikel:
        z = zaehler[k]
        bewertet = z["richtig"] + z["falsch"]
        quote = (f"{100 * z['richtig'] / bewertet:.0f} %"
                 if bewertet else "–")
        zeilen.append({"artikel": k, "richtig": z["richtig"],
                       "falsch": z["falsch"],
                       "unbewertet": z["unbewertet"], "quote": quote})
    if not eintraege:
        return [], "Keine Reports — erst identifizieren und bewerten."
    richtig = sum(z["richtig"] for z in zeilen)
    bewertet = richtig + sum(z["falsch"] for z in zeilen)
    unbewertet = sum(z["unbewertet"] for z in zeilen)
    if bewertet:
        gesamt = (f"{richtig} von {bewertet} richtig "
                  f"({100 * richtig / bewertet:.0f} %) · "
                  f"{unbewertet} unbewertet")
    else:
        gesamt = f"0 bewertet · {unbewertet} unbewertet"
    return zeilen, gesamt


class BewertungsTab(QWidget):
    """Aggregation der Verdicts aus den geladenen Reports (Spec Punkt 7).
    Synchron geladen — identisch zur Reports-Sektion (9 ms für den
    Bestand, Befund 2026-08-11)."""

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self._zeilen: list = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(8)
        kopf = QHBoxLayout()
        self.refresh_button = QPushButton("Aktualisieren")
        self.refresh_button.clicked.connect(self.reload)
        kopf.addWidget(self.refresh_button, alignment=Qt.AlignLeft)
        self.gesamt_label = QLabel("")
        self.gesamt_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        kopf.addWidget(self.gesamt_label, stretch=1)
        lay.addLayout(kopf)
        self._tabelle = QTableWidget(0, 5)
        self._tabelle.setHorizontalHeaderLabels(
            ["Artikel", "Richtig", "Falsch", "unbewertet", "Quote"])
        self._tabelle.verticalHeader().setVisible(False)
        self._tabelle.setEditTriggers(QTableWidget.NoEditTriggers)
        lay.addWidget(self._tabelle, stretch=1)
        self.reload()

    def reload(self) -> None:
        self._zeilen, gesamt = _aggregiere(load_saved_reports(self.cfg))
        self.gesamt_label.setText(gesamt)
        self._tabelle.setRowCount(len(self._zeilen))
        for r, z in enumerate(self._zeilen):
            for c, wert in enumerate([z["artikel"], z["richtig"],
                                      z["falsch"], z["unbewertet"],
                                      z["quote"]]):
                self._tabelle.setItem(r, c, QTableWidgetItem(str(wert)))
        self._tabelle.resizeColumnsToContents()

    # ---------- Testhilfen ----------

    def zeilen(self) -> list:
        return [dict(z) for z in self._zeilen]

    def gesamt_text(self) -> str:
        return self.gesamt_label.text()


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
        self.bewertung_tab = BewertungsTab(cfg)
        self.tabs.addTab(self.bewertung_tab, "Bewertungs-Übersicht")
        lay.addWidget(self.tabs)
