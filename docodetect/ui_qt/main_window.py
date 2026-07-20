"""Hauptfenster: Vorschau links, Aktions-Panel rechts, Statusleiste unten.

Zustandsmaschine (state.py): NO_CAMERA / NOT_READY / READY / BUSY.
Alle Pipeline-Aktionen laufen im PipelineWorker (nie im GUI-Thread) und
erhalten das Bild als Argument vom jeweiligen Frame-Lieferanten (DemoSource
bzw. CameraWorker) – die UI besitzt keine Kamera und rechnet nie selbst.

Interface-Sprache: ein Begriff pro Aktion („Identifizieren“ →
„Automatisch übernommen“), Fehlertexte nennen immer die Abhilfe.
"""

from __future__ import annotations

from functools import partial

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QHBoxLayout,
                               QLabel, QMainWindow, QPushButton, QVBoxLayout,
                               QWidget)

from docodetect.pipeline import (confirm_result, format_measured,
                                 format_rank_line, get_status, headline,
                                 list_articles, reject_result)

from .app import ui_cfg
from .pipeline_worker import PipelineWorker
from .state import UiState, compute_state
from .widgets.preview import PreviewWidget
from .widgets.result_card import ResultCard
from .widgets.status_bar import StatusBarContent

# Feste Breite des Aktions-Panels: die Vorschau soll den restlichen Platz
# füllen; 360 px reichen für ResultCards mit Messwert-Zeile.
_PANEL_WIDTH = 360

_NO_CAMERA_TEXT = "Keine Kamera gefunden –\nVerbindung wird gesucht…"
_BORDER_WARNING = "Objekt berührt den Bildrand – weiter zur Mitte legen."

_IDENTIFY_TOOLTIPS = {
    UiState.NO_CAMERA: "Keine Kamera verbunden.",
    UiState.NOT_READY: "Erst einrichten: Hintergrund aufnehmen und kalibrieren.",
    UiState.READY: "Objekt mittig auflegen und identifizieren (Leertaste).",
    UiState.BUSY: "Bitte warten – Auswertung läuft.",
}

_BUSY_TEXTS = {
    "identify": "Auswertung läuft…",
    "background": "Hintergrund wird gespeichert…",
    "calibrate": "Kalibrierung läuft…",
    "seed": "Demo-Artikel werden eingelernt…",
}


# ---------- Jobs: laufen KOMPLETT im Worker-Thread ----------
# Die Pipeline wird IM Job konstruiert (SQLite-Thread-Affinität) und das
# Ergebnis GUI-fertig aufbereitet (QImage-Konvertierung ist threadsicher).

def _job_identify(frame, cfg: dict, preview_width: int) -> dict:
    from docodetect.pipeline import Pipeline, render_report_overlay

    from .qimage import bgr_to_qimage, downscale_width

    pipe = Pipeline(cfg)
    try:
        outcome = pipe.identify(frame)
    finally:
        pipe.close()
    annotated = render_report_overlay(frame, outcome.report)
    qimg = bgr_to_qimage(downscale_width(annotated, preview_width))
    return {"kind": "identify", "outcome": outcome, "annotated": qimg}


def _job_background(frame, cfg: dict) -> dict:
    from docodetect.pipeline import capture_background

    capture_background(frame, cfg)
    return {"kind": "background"}


def _job_calibrate(frame, cfg: dict) -> dict:
    from docodetect.pipeline import calibrate

    cal = calibrate(frame, cfg)
    return {"kind": "calibrate", "mm_per_px": cal.mm_per_px}


def _job_seed_demo(cfg: dict) -> dict:
    """Demo-Artikel anlegen + einlernen (5 Varianten pro Artikel), damit
    „Identifizieren“ im Demo-Modus ACCEPT/CONFIRM erreichen kann. Der Ablauf
    liegt in demo_seed.py (Qt-frei und damit ohne Fenster testbar)."""
    from .demo_seed import seed_demo

    return seed_demo(cfg)


class MainWindow(QMainWindow):
    def __init__(self, cfg: dict, demo: bool = False):
        super().__init__()
        self.cfg = cfg
        self.demo = demo
        self.ui = ui_cfg(cfg)
        self.source = None          # DemoSource | CameraWorker (Phase 4)
        self._busy = False
        self._pending: str | None = None   # angeforderte Aktion für den Frame
        self._worker: PipelineWorker | None = None
        self._seed_attempted = False
        self._last_report = None
        self._rank_lines: list = []          # QLabel je Rang 2/3 (accept)
        self._none_button = None             # „Keiner davon" (ambiguous)
        self._diagnose_label = None          # Rohmesswert-Diagnose (reject)
        self.state: UiState | None = None
        self.setWindowTitle("Doco Detect" + (" – Demo" if demo else ""))
        self.setMinimumSize(self.ui["window_min_width"],
                            self.ui["window_min_height"])

        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)
        root.addWidget(self._build_preview_area(), stretch=1)
        root.addWidget(self._build_action_panel())
        self.setCentralWidget(central)

        self.status_content = StatusBarContent()
        self.statusBar().addWidget(self.status_content, 1)

        self._wire_actions()
        if demo:
            self._attach_demo_source()
        else:
            self._attach_camera_worker()
        self.refresh_status()

    # ---------- Aufbau ----------

    def _build_preview_area(self) -> QWidget:
        wrap = QWidget()
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        # Schmale Demo-Leiste (nur --demo): Szenen umschalten ohne Hardware.
        self.demo_bar = QWidget()
        bar = QHBoxLayout(self.demo_bar)
        bar.setContentsMargins(0, 0, 0, 0)
        bar.addWidget(QLabel("Demo-Bild:"))
        self.demo_scene_box = QComboBox()
        bar.addWidget(self.demo_scene_box, stretch=1)
        self.demo_bar.setVisible(False)
        lay.addWidget(self.demo_bar)

        self.preview = PreviewWidget()
        lay.addWidget(self.preview, stretch=1)
        return wrap

    def _build_action_panel(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(_PANEL_WIDTH)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        title = QLabel("DOCO DETECT")
        title.setObjectName("appTitle")
        lay.addWidget(title)

        self.identify_button = QPushButton("Identifizieren")
        self.identify_button.setObjectName("primaryButton")
        lay.addWidget(self.identify_button)

        result_header = QLabel("Ergebnis")
        result_header.setObjectName("sectionLabel")
        lay.addWidget(result_header)

        self.result_headline = QLabel("")
        self.result_headline.setObjectName("resultHeadline")
        self.result_headline.setWordWrap(True)
        lay.addWidget(self.result_headline)

        self.result_area = QLabel("Noch kein Ergebnis.")
        self.result_area.setObjectName("guideLabel")
        self.result_area.setWordWrap(True)
        self.result_area.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        lay.addWidget(self.result_area)

        self.cards_box = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_box)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(8)
        lay.addWidget(self.cards_box)
        lay.addStretch(1)

        self.background_button = QPushButton("Hintergrund aufnehmen")
        self.calibrate_button = QPushButton("Kalibrieren")
        self.enroll_button = QPushButton("Artikel einlernen…")
        for b in (self.background_button, self.calibrate_button,
                  self.enroll_button):
            b.setObjectName("secondaryButton")
            lay.addWidget(b)
        return panel

    def _wire_actions(self) -> None:
        self.identify_button.clicked.connect(self.identify_now)
        self.background_button.clicked.connect(
            partial(self._start_capture_action, "background"))
        self.calibrate_button.clicked.connect(
            partial(self._start_capture_action, "calibrate"))
        self.enroll_button.clicked.connect(self._open_enroll_dialog)
        # Leertaste = Identifizieren, egal wo der Fokus im Fenster liegt.
        space = QAction("Identifizieren", self)
        space.setShortcut(QKeySequence(Qt.Key_Space))
        space.setShortcutContext(Qt.WindowShortcut)
        space.triggered.connect(self.identify_now)
        self.addAction(space)

    def _attach_demo_source(self) -> None:
        from .demo_scenes import SCENE_NAMES
        from .demo_source import DemoSource

        self.source = DemoSource(self.cfg, self)
        self._connect_source(self.source)
        self.demo_scene_box.addItems(SCENE_NAMES)
        self.demo_scene_box.currentTextChanged.connect(self.source.set_scene)
        self.demo_bar.setVisible(True)
        self.status_content.set_camera_text("Kamera Demo")
        self.source.start()

    def _attach_camera_worker(self) -> None:
        """Echte Kamera: der CameraWorker ist der einzige Kamera-Besitzer
        (PLAN §3); die UI reagiert nur auf seine Signale."""
        from .camera_worker import CameraWorker

        self.source = CameraWorker(self.cfg, self)
        self._connect_source(self.source)
        self.source.camera_connected.connect(self._on_camera_connected)
        self.source.camera_error.connect(self._on_camera_error)
        self.source.focus_warning.connect(self.status_content.set_warning)
        self.source.fps_update.connect(self._on_fps_update)
        self.status_content.set_camera_text("Kamera –")
        self.source.start()

    def _on_camera_connected(self) -> None:
        self.status_content.set_camera_text("Kamera verbunden")
        self.update_state()

    def _on_camera_error(self, message: str) -> None:
        """Verbindungsverlust: Zustand NO_CAMERA statt Crash; der Worker
        versucht selbst leise den Reconnect (alle paar Sekunden)."""
        self.status_content.set_camera_text("Kamera getrennt")
        if self._pending is not None:
            # Frame-Anforderung läuft ins Leere – Aktion sauber abbrechen,
            # sonst bliebe die UI für immer BUSY.
            self._pending = None
            self._busy = False
            self.preview.set_busy(None)
            self._set_headline("Aktion abgebrochen – Kamera getrennt.",
                               "reject")
        self.update_state()
        # Details nur ins Ergebnis-Panel, wenn keine Karte etwas Wichtigeres
        # zeigt – die Vorschau zeigt bereits „Keine Kamera gefunden…“.
        if self.state is UiState.NO_CAMERA and self._last_report is None:
            self.result_area.setText(message)

    def _on_fps_update(self, fps: float) -> None:
        self.status_content.set_camera_text(f"Kamera {fps:.0f} fps")

    def _connect_source(self, source) -> None:
        """Gemeinsame Verdrahtung für DemoSource und CameraWorker."""
        source.frame_ready.connect(self.preview.set_frame)
        source.full_frame_ready.connect(self._on_full_frame)

    # ---------- Zustandsmaschine ----------

    @property
    def camera_ok(self) -> bool:
        return self.source is not None and self.source.camera_ok

    def refresh_status(self) -> None:
        """Statusleiste + Zustand aus der Pipeline-Fassade (echte Werte)."""
        self.pipeline_status = get_status(self.cfg)
        self.status_content.update_status(self.pipeline_status)
        self.update_state()
        self._maybe_seed_demo()

    def update_state(self) -> None:
        self.set_state(compute_state(self.camera_ok,
                                     self.pipeline_status.ready, self._busy))

    def set_state(self, state: UiState) -> None:
        self.state = state
        self.identify_button.setEnabled(state is UiState.READY)
        self.identify_button.setToolTip(_IDENTIFY_TOOLTIPS[state])
        setup_ok = state in (UiState.NOT_READY, UiState.READY)
        self.background_button.setEnabled(setup_ok)
        self.calibrate_button.setEnabled(setup_ok)
        self.enroll_button.setEnabled(state is UiState.READY)
        self.enroll_button.setToolTip(
            "" if state is UiState.READY
            else "Einlernen braucht Kamera + Kalibrierung.")
        self.preview.set_message(
            _NO_CAMERA_TEXT if state is UiState.NO_CAMERA else None)
        if state is UiState.NOT_READY:
            self.result_area.setText(self._setup_guide())

    def _setup_guide(self) -> str:
        """Empty State als Handlungsanleitung: erledigte Schritte markiert."""
        st = self.pipeline_status
        bg = "erledigt" if st.background_present else "offen"
        cal = "erledigt" if st.calibrated else "offen"
        return ("Einrichtung nötig:\n\n"
                f"1. Box leeren, dann „Hintergrund aufnehmen“.   [{bg}]\n\n"
                f"2. Marker einlegen, dann „Kalibrieren“.   [{cal}]\n\n"
                "Danach ist „Identifizieren“ aktiv.")

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt-API)
        """Quelle stoppen und laufende Worker zu Ende laufen lassen – ein
        QThread darf nicht zerstört werden, solange er läuft."""
        if self.source is not None:
            self.source.stop()
        if self._worker is not None:
            self._worker.wait(10000)
        super().closeEvent(event)

    # ---------- Aktionen ----------

    def identify_now(self) -> None:
        if self.state is UiState.READY:
            self._start_capture_action("identify")

    def _start_capture_action(self, action: str) -> None:
        """Frischen Voll-Frame anfordern; der Frame löst dann den Job aus."""
        if self._busy or self.source is None or not self.camera_ok:
            return
        self._pending = action
        self._busy = True
        self.update_state()
        self.preview.set_busy(_BUSY_TEXTS[action])
        self.preview.set_warning(None)
        self.source.request_full_frame()

    def _on_full_frame(self, frame) -> None:
        action, self._pending = self._pending, None
        if action is None:
            return  # Frame war für einen anderen Empfänger (z.B. Dialog)
        jobs = {
            "identify": partial(_job_identify, frame, self.cfg,
                                self.ui["preview_max_width"]),
            "background": partial(_job_background, frame, self.cfg),
            "calibrate": partial(_job_calibrate, frame, self.cfg),
        }
        self._start_worker(jobs[action])

    def _start_worker(self, job) -> None:
        w = PipelineWorker(job, self)
        w.finished_ok.connect(self._on_job_done)
        w.failed.connect(self._on_job_failed)
        w.finished.connect(w.deleteLater)
        self._worker = w
        w.start()

    def _maybe_seed_demo(self) -> None:
        """Demo einsatzbereit machen: sobald Kalibrierung + Hintergrund da
        sind und der Demo-Stand fehlt ODER VERALTET ist, Artikel automatisch
        (neu) einlernen – einmal pro Programmlauf.

        „Veraltet" ist der entscheidende Teil (Regression 2026-07-20): die
        frühere Bedingung „noch keine Referenzen" hielt einen mit älterem
        Code geseedeten Stand für gültig, sodass die Demo still falsche
        Entscheidungen zeigte. Details: demo_seed.seed_needed."""
        if not (self.demo and not self._busy and not self._seed_attempted
                and self.pipeline_status.ready):
            return
        from .demo_seed import seed_needed
        needed, reason = seed_needed(self.cfg)
        if needed:
            print(f"[demo] Demo-Daten werden neu eingelernt: {reason}")
            self._seed_attempted = True
            self._busy = True
            self.update_state()
            self.preview.set_busy(_BUSY_TEXTS["seed"])
            self._start_worker(partial(_job_seed_demo, self.cfg))

    def _open_enroll_dialog(self) -> None:
        """Einlern-Assistent (modal). Nutzt dieselbe Frame-Quelle; nach dem
        Speichern wirken die neuen Referenzen sofort beim Identifizieren."""
        if self.state is not UiState.READY:
            return
        from .widgets.enroll_dialog import EnrollDialog

        dlg = EnrollDialog(self.cfg, self.ui, self.source, self)
        dlg.exec()
        if dlg.saved_count:
            self.refresh_status()
            self._set_headline(
                f"{dlg.saved_count} Referenz(en) gespeichert.", "accept")
            self.result_area.setText(
                "Die neuen Referenzen wirken ab sofort beim Identifizieren.")

    # ---------- Job-Ergebnisse ----------

    def _job_finished(self) -> None:
        self._busy = False
        self._worker = None
        self.preview.set_busy(None)

    def _on_job_done(self, result: dict) -> None:
        self._job_finished()
        kind = result["kind"]
        if kind == "background":
            self._set_headline("Hintergrund gespeichert.", "accept")
            self.refresh_status()   # Checkliste rückt weiter / READY
        elif kind == "calibrate":
            mm = f"{result['mm_per_px']:.3f}".replace(".", ",")
            self._set_headline(f"Kalibriert: {mm} mm/px.", "accept")
            self.refresh_status()
            if self.state is UiState.READY and not self.demo:
                self.result_area.setText(
                    "Bereit. Objekt mittig auflegen und „Identifizieren“ "
                    "drücken (Leertaste).")
        elif kind == "seed":
            self.refresh_status()
            self._set_headline("Demo-Artikel eingelernt.", "accept")
            self.result_area.setText(
                f"{result['n']} Demo-Artikel mit je 5 Referenzen angelegt. "
                "Jetzt z.B. „Teller 18“ wählen und identifizieren "
                "(Leertaste).")
        elif kind == "identify":
            self.update_state()
            self._show_report(result["outcome"].report, result["annotated"])

    def _on_job_failed(self, message: str) -> None:
        self._job_finished()
        self.refresh_status()
        self._set_headline("Aktion fehlgeschlagen.", "reject")
        # Pipeline-Fehlertexte nennen bereits die Abhilfe (z.B. „Marker
        # prüfen“, „weiter zur Mitte legen“) – unverändert anzeigen.
        self.result_area.setText(message)

    # ---------- Ergebnis-Darstellung ----------

    def _set_headline(self, text: str, tone: str = "neutral") -> None:
        self.result_headline.setText(text)
        self.result_headline.setProperty("tone", tone)
        self.result_headline.style().unpolish(self.result_headline)
        self.result_headline.style().polish(self.result_headline)

    def _clear_cards(self) -> None:
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._rank_lines = []
        self._none_button = None
        self._diagnose_label = None

    def _show_report(self, report, annotated=None) -> None:
        """Rendert einen MatchReport gemäß Entscheidung (accept/ambiguous/
        reject). `annotated` ist das optionale Overlay-Bild aus dem
        Identifizieren-Job (None in Tests, die _show_report direkt mit einem
        gebauten Report aufrufen)."""
        self._last_report = report
        self._clear_cards()
        if annotated is not None:
            self.preview.set_overlay(annotated, self.ui["result_overlay_secs"])
        touches = bool(report.touches_border)
        self.preview.set_warning(_BORDER_WARNING if touches else None)

        top_k = int(self.cfg["matching"].get("top_k", 3))
        cands = report.candidates[:top_k]

        if report.decision == "accept":
            best = cands[0]
            text, cls = headline(report.decision, best.name)
            self._set_headline(text, cls)
            self.result_area.setText("")
            self.cards_layout.addWidget(ResultCard(best, self.cfg))
            # Plätze 2-3 kompakt als Rang-Zeile statt volle Karte.
            for rank, c in enumerate(cands[1:], start=2):
                lbl = QLabel(format_rank_line(c, rank))
                lbl.setObjectName("rankLine")
                self.cards_layout.addWidget(lbl)
                self._rank_lines.append(lbl)
            if self.ui["confirm_sound"]:
                QApplication.beep()
        elif report.decision == "ambiguous":
            text, cls = headline(report.decision)
            self._set_headline(text, cls)
            self.result_area.setText(
                "Karte anklicken, um den richtigen Artikel zu bestätigen.")
            for c in cands:
                card = ResultCard(c, self.cfg, clickable=True)
                card.clicked.connect(self._confirm_candidate)
                self.cards_layout.addWidget(card)
            self._none_button = QPushButton("Keiner davon / manuell korrigieren")
            self._none_button.clicked.connect(self._manual_correction)
            self.cards_layout.addWidget(self._none_button)
        elif touches:
            self._set_headline("Objekt berührt den Bildrand.", "reject")
            self.result_area.setText(
                "Weiter zur Mitte legen, dann erneut „Identifizieren“ "
                "drücken. Passt das Objekt nicht vollständig ins Bild, kann "
                "es nicht gemessen werden (siehe README, FOV).")
        else:
            text, cls = headline(report.decision)
            self._set_headline(text, cls)
            self.result_area.setText(
                "Prüfen: Objekt richtig gelegt? Artikel eingelernt? "
                "Mit „Artikel einlernen…“ unten lässt sich der Artikel "
                "jetzt anlegen.\n\nDetails: " + report.message)
            # NO_MATCH-Diagnose: die Rohmesswerte zeigen, WAS gemessen wurde,
            # auch wenn kein Artikel passt (kein Kandidat, also kein Ø-Wert
            # aus format_diameter verfügbar).
            m = report.measured or {}
            if m:
                diag = QLabel(format_measured(m))
                diag.setObjectName("diagnoseLine")
                diag.setWordWrap(True)
                self.cards_layout.addWidget(diag)
                self._diagnose_label = diag

    def _save_verdict(self, report, correct: bool,
                      true_article: str | None = None) -> None:
        """Gemeinsamer Speicherweg für Kartenklick (AMBIGUOUS-Bestätigung)
        UND „Keiner davon"-Korrektur – eine Stelle, die über die
        pipeline-Fassade ins Report-JSON schreibt (nie reporting.py direkt,
        UI-Regel). `correct` entscheidet nur, welche Fassadenfunktion den
        Verdict setzt; beide landen im selben Report."""
        if correct:
            confirm_result(report, true_article)
        else:
            reject_result(report, true_article)

    def _confirm_candidate(self, article_number: str) -> None:
        """Karten-Klick bei AMBIGUOUS: visuell quittieren + im Report-JSON
        vermerken (Buchungs-Anbindung ist bewusst nicht Teil der UI)."""
        if self._last_report is None:
            return
        top1 = (self._last_report.candidates[0].article_number
                if self._last_report.candidates else None)
        try:
            self._save_verdict(self._last_report,
                               correct=(article_number == top1),
                               true_article=article_number)
        except ValueError as e:
            self._set_headline("Bestätigung nicht gespeichert.", "reject")
            self.result_area.setText(str(e))
            return
        # Die Karten selbst bleiben neutral (kein zustandsabhängiger Rahmen
        # mehr, Task 4) – die Bestätigung zeigt sich einzig über die
        # Headline.
        name = article_number
        for c in self._last_report.candidates:
            if c.article_number == article_number:
                name = c.name
                break
        self._set_headline(f"Bestätigt: {name}", "accept")
        self.result_area.setText("Auswahl wurde im Protokoll vermerkt.")

    def _manual_correction(self) -> None:
        """„Keiner davon": Artikel-Picker (oder Unbekannt), Ergebnis geht als
        verdict=wrong (+ wahrer Artikel) ins Report-JSON – kein Buchungs-
        Backend, nur Testprotokoll (Batch-Auswertung)."""
        if self._last_report is None:
            return
        from docodetect.ui_qt.widgets.correction_dialog import CorrectionDialog

        dlg = CorrectionDialog(list_articles(self.cfg), self)
        if dlg.exec() != QDialog.Accepted:
            return
        chosen = dlg.chosen()
        try:
            self._save_verdict(self._last_report, correct=False,
                               true_article=chosen)
        except ValueError as e:
            self._set_headline("Korrektur nicht gespeichert.", "reject")
            self.result_area.setText(str(e))
            return
        name = chosen or "Unbekannt"
        self._set_headline(f"Korrigiert: {name} — im Testprotokoll vermerkt.",
                           "confirm")
        self.result_area.setText("Auswahl wurde im Protokoll vermerkt.")

    # ---------- Testhilfen (analog ResultCard.all_text) ----------

    def headline_text(self) -> str:
        return self.result_headline.text()

    def rank_lines_count(self) -> int:
        return len(self._rank_lines)

    def none_of_these_button(self):
        return self._none_button

    def diagnose_text(self) -> str:
        return self._diagnose_label.text() if self._diagnose_label else ""
