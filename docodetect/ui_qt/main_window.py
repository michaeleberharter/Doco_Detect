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

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QHBoxLayout,
                               QLabel, QMainWindow, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from docodetect.pipeline import (confirm_no_match, confirm_result,
                                 format_measured, get_status, headline,
                                 list_articles, reject_result)

from .app import apply_theme, current_theme, ui_cfg
from .pipeline_worker import PipelineWorker
from .state import UiState, compute_state
from .widgets.action_bar import ActionBar
from .widgets.common import section_label
from .widgets.live_indicator import LiveIndicator
from .widgets.preview import PreviewWidget
from .widgets.preview import Detection
from .widgets.result_card import (CandidateRow, MessageCard, ResultCard,
                                  ResultHeader)
from .widgets.verdict_bar import VerdictBar
from .widgets.status_bar import StatusBarContent
from .widgets.tool_rail import ToolRail

# Feste Breite der Ergebnisspalte (Entwurf: 372 px) – die Vorschau bekommt
# den Rest. Der Wert ist bewusst fix: die Karte soll beim Fensterziehen
# nicht atmen, das Bild schon.
_PANEL_WIDTH = 372

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
    "seed": "Demo-Artikel werden eingelernt…",
}


# ---------- Jobs: laufen KOMPLETT im Worker-Thread ----------
# Die Pipeline wird IM Job konstruiert (SQLite-Thread-Affinität) und das
# Ergebnis GUI-fertig aufbereitet (QImage-Konvertierung ist threadsicher).

def _job_identify(frame, cfg: dict, preview_width: int) -> dict:
    """Der Job liefert das ROHE Bild, nicht das annotierte.

    `pipeline.render_report_overlay()` zeichnet Kontur und Maßlinie ins
    Bild und wird mit der Streamlit-UI und der CLI geteilt – es bleibt
    unverändert. Die Qt-Vorschau legt ihren eigenen Erkennungsrahmen samt
    Maß-Chips darüber (widgets/preview.Detection), weil der Entwurf eine
    andere Optik verlangt und ein Overlay im Bild sonst doppelt läge."""
    from docodetect.pipeline import Pipeline

    from .qimage import bgr_to_qimage, downscale_width

    pipe = Pipeline(cfg)
    try:
        outcome = pipe.identify(frame)
    finally:
        pipe.close()
    qimg = bgr_to_qimage(downscale_width(frame, preview_width))
    return {"kind": "identify", "outcome": outcome, "frame": qimg}


def _job_background(frame, cfg: dict) -> dict:
    from docodetect.pipeline import capture_background

    capture_background(frame, cfg)
    return {"kind": "background"}


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
        self._rank_lines: list = []          # CandidateRow je weiterem Rang
        self._none_button = None             # „Keiner davon" (ambiguous)
        self._diagnose_label = None          # Rohmesswert-Diagnose (reject)
        self._verdict_bar = None             # Richtig/Falsch (accept, reject)
        self._calibrate_dialog = None        # offener Kalibrier-Dialog
        self.state: UiState | None = None
        self.setWindowTitle("Doco Detect" + (" – Demo" if demo else ""))
        self.setMinimumSize(self.ui["window_min_width"],
                            self.ui["window_min_height"])

        # Aufbau wie im Entwurf: Icon-Schiene | Live-Bild | Ergebnisspalte,
        # darunter über die volle Breite die Aktionsleiste.
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        body = QWidget()
        body_lay = QHBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(0)
        self.tool_rail = ToolRail()
        body_lay.addWidget(self.tool_rail)
        body_lay.addWidget(self._build_preview_area(), stretch=1)
        body_lay.addWidget(self._build_action_panel())
        root.addWidget(body, stretch=1)

        self.action_bar = ActionBar()
        self.identify_button = self.action_bar.identify_button
        self.background_button = self.action_bar.background_button
        self.calibrate_button = self.action_bar.calibrate_button
        self.enroll_button = self.action_bar.enroll_button
        root.addWidget(self.action_bar)
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
        wrap.setObjectName("previewArea")
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Schmale Leiste über dem Bild. Rechts die Live-Anzeige des Entwurfs
        # (immer da), links die Demo-Szenenwahl – die ist ein reines
        # Entwicklerwerkzeug und NUR im --demo-Modus sichtbar (`demo_bar`),
        # kein Produktfeature.
        toolbar = QWidget()
        toolbar.setObjectName("previewToolbar")
        bar = QHBoxLayout(toolbar)
        bar.setContentsMargins(16, 10, 16, 10)
        bar.setSpacing(10)

        self.demo_bar = QWidget()
        demo_lay = QHBoxLayout(self.demo_bar)
        demo_lay.setContentsMargins(0, 0, 0, 0)
        demo_lay.setSpacing(10)
        demo_label = QLabel("Demo-Bild")
        demo_label.setObjectName("toolbarLabel")
        demo_lay.addWidget(demo_label)
        self.demo_scene_box = QComboBox()
        self.demo_scene_box.setMinimumWidth(190)
        demo_lay.addWidget(self.demo_scene_box)
        self.demo_bar.setVisible(False)
        bar.addWidget(self.demo_bar)

        bar.addStretch(1)
        self.live_indicator = LiveIndicator()
        bar.addWidget(self.live_indicator)
        lay.addWidget(toolbar)

        self.preview = PreviewWidget()
        lay.addWidget(self.preview, stretch=1)
        return wrap

    def _build_action_panel(self) -> QWidget:
        """Ergebnisspalte: Kopfzeile, Ergebnisbereich, Kandidaten, Verlauf.

        Der Inhalt scrollt, der Rahmen nicht – bei drei Kandidaten plus
        Verlauf reicht die Fensterhöhe sonst nicht."""
        panel = QWidget()
        panel.setObjectName("resultColumn")
        panel.setFixedWidth(_PANEL_WIDTH)
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(8)

        self.result_header = ResultHeader()
        lay.addWidget(self.result_header)
        # Gleicher Name wie bisher: Tests und Aufrufer greifen darauf zu.
        self.result_headline = self.result_header.text

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

        # Platzhalter der Phase 2: Kandidaten und Verlauf bekommen ihren
        # Inhalt in Phase 3 bzw. 5, die Abschnitte stehen aber schon.
        self.candidates_label = section_label("Weitere Kandidaten")
        lay.addWidget(self.candidates_label)
        self.candidates_box = QWidget()
        self.candidates_layout = QVBoxLayout(self.candidates_box)
        self.candidates_layout.setContentsMargins(0, 0, 0, 0)
        self.candidates_layout.setSpacing(7)
        lay.addWidget(self.candidates_box)

        history_row = QHBoxLayout()
        history_row.setContentsMargins(0, 0, 0, 0)
        self.history_label = section_label("Verlauf")
        history_row.addWidget(self.history_label)
        history_row.addStretch(1)
        self.history_clear = QPushButton("Leeren")
        self.history_clear.setObjectName("linkButton")
        self.history_clear.setCursor(Qt.PointingHandCursor)
        history_row.addWidget(self.history_clear)
        lay.addLayout(history_row)

        self.history_box = QWidget()
        self.history_layout = QVBoxLayout(self.history_box)
        self.history_layout.setContentsMargins(0, 0, 0, 0)
        self.history_layout.setSpacing(0)
        lay.addWidget(self.history_box)

        lay.addStretch(1)
        scroll.setWidget(inner)
        outer.addWidget(scroll)
        return panel

    def _wire_actions(self) -> None:
        self.identify_button.clicked.connect(self.identify_now)
        self.background_button.clicked.connect(
            partial(self._start_capture_action, "background"))
        self.calibrate_button.clicked.connect(self._open_calibrate_dialog)
        self.enroll_button.clicked.connect(self._open_enroll_dialog)
        # Icon-Schiene löst dieselben Aktionen aus wie die untere Leiste.
        self._rail_actions = {
            "identify": self.identify_now,
            "background": partial(self._start_capture_action, "background"),
            "calibrate": self._open_calibrate_dialog,
            "enroll": self._open_enroll_dialog,
        }
        self.tool_rail.triggered.connect(
            lambda key: self._rail_actions[key]())
        self.tool_rail.theme_toggle.connect(self.toggle_theme)
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
        # Die Schiene spiegelt exakt dieselbe Freigabe wie die untere Leiste.
        self.tool_rail.set_enabled_actions(
            identify=state is UiState.READY, background=setup_ok,
            calibrate=setup_ok, enroll=state is UiState.READY)
        self.live_indicator.set_live(state is not UiState.NO_CAMERA)
        self.preview.set_message(
            _NO_CAMERA_TEXT if state is UiState.NO_CAMERA else None)
        if state is UiState.NOT_READY:
            self.result_area.setText(self._setup_guide())

    def toggle_theme(self) -> None:
        """Zahnrad in der Schiene: dunkel <-> hell, ohne Neustart.

        Der Wert wird bewusst NICHT in die config zurückgeschrieben – das
        Erscheinungsbild der Fotobox gehört in config.local.yaml und wird
        dort gesetzt, nicht von der laufenden App überschrieben."""
        app = QApplication.instance()
        new = "light" if current_theme().is_dark else "dark"
        apply_theme(app, new)
        self.retheme()

    def retheme(self) -> None:
        """Alles neu einfärben, was Qt nicht per Stylesheet erreicht:
        selbst gezeichnete Icons, Punkte und Flächen."""
        self.tool_rail.retheme()
        self.action_bar.retheme()
        self.live_indicator.retheme()
        self.preview.update()

    def changeEvent(self, event) -> None:        # noqa: N802 (Qt-API)
        """Auf einen Themewechsel reagieren, egal wer ihn ausgelöst hat.

        `apply_theme()` setzt Palette und Stylesheet – die gezeichneten Icons
        erreicht es nicht. Statt jeden Aufrufer daran zu erinnern, `retheme()`
        nachzuschieben, hängen wir uns an das Ereignis, das Qt dabei ohnehin
        verschickt. Ohne das blieben die Icons in der Farbe des alten Themes
        stehen und wären im hellen Theme praktisch unsichtbar."""
        super().changeEvent(event)
        if event.type() == QEvent.PaletteChange:
            self.retheme()

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
        # Kalibrieren fehlt hier bewusst: das macht der Kalibrier-Dialog
        # selbst, er hört auf dieselbe Frame-Quelle.
        jobs = {
            "identify": partial(_job_identify, frame, self.cfg,
                                self.ui["preview_max_width"]),
            "background": partial(_job_background, frame, self.cfg),
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

    def _open_calibrate_dialog(self) -> None:
        """Kalibrier-Dialog: Anleitung, Live-Vorschau, Maßstab.

        Bewusst `open()` statt `exec()`: `exec()` startet eine verschachtelte
        Ereignisschleife, in der die Kamera-Signale des Hauptfensters
        auflaufen – der Dialog braucht sie aber. Nebeneffekt: der Ablauf
        bleibt von aussen steuerbar und damit testbar."""
        if self.state not in (UiState.NOT_READY, UiState.READY):
            return
        from .widgets.calibrate_dialog import CalibrateDialog

        dlg = CalibrateDialog(self.cfg, self.source, self)
        dlg.finished.connect(partial(self._calibrate_dialog_closed, dlg))
        self._calibrate_dialog = dlg
        dlg.open()

    def _calibrate_dialog_closed(self, dlg, _result: int) -> None:
        if dlg.calibrated:
            self.refresh_status()
            self._set_headline("Kalibrierung aktualisiert.", "accept")
            if self.state is UiState.READY and not self.demo:
                self.result_area.setText(
                    "Bereit. Objekt mittig auflegen und „Identifizieren“ "
                    "drücken (Leertaste).")
        self._calibrate_dialog = None
        dlg.deleteLater()

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
        elif kind == "seed":
            self.refresh_status()
            self._set_headline("Demo-Artikel eingelernt.", "accept")
            self.result_area.setText(
                f"{result['n']} Demo-Artikel mit je 5 Referenzen angelegt. "
                "Jetzt z.B. „Teller 18“ wählen und identifizieren "
                "(Leertaste).")
        elif kind == "identify":
            self.update_state()
            self._show_report(result["outcome"].report, result["frame"])

    def _on_job_failed(self, message: str) -> None:
        self._job_finished()
        self.refresh_status()
        self._set_headline("Aktion fehlgeschlagen.", "reject")
        # Pipeline-Fehlertexte nennen bereits die Abhilfe (z.B. „Marker
        # prüfen“, „weiter zur Mitte legen“) – unverändert anzeigen.
        self.result_area.setText(message)

    # ---------- Ergebnis-Darstellung ----------

    def _set_headline(self, text: str, tone: str = "neutral",
                      value: str = "") -> None:
        self.result_header.show_state(tone, text, value)

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _clear_cards(self) -> None:
        self._clear_layout(self.cards_layout)
        self._clear_layout(self.candidates_layout)
        self._rank_lines = []
        self._none_button = None
        self._diagnose_label = None
        self._verdict_bar = None
        self.candidates_label.setVisible(False)

    @staticmethod
    def report_tone(report) -> str:
        """Anzeigezustand eines Reports – VIER Stück.

        `border` ist ein eigener Zustand und bewusst kein Reject: das Objekt
        berührt den Bildrand, die Messung ist damit nicht durchführbar, aber
        nichts wurde falsch erkannt."""
        if report.touches_border:
            return "border"
        if report.decision in ("accept", "ambiguous"):
            return report.decision
        return "reject"

    def _detection_for(self, report) -> Detection | None:
        """Erkennungsrahmen + Mess-Chips fürs Vorschaubild, aus dem Report.
        Der Rahmen ist die Hüllbox der Kontur, auf die Bildgröße normiert."""
        if not report.contour or not report.image_size:
            return None
        xs = [p[0] for p in report.contour]
        ys = [p[1] for p in report.contour]
        iw, ih = float(report.image_size[0]), float(report.image_size[1])
        if iw <= 0 or ih <= 0:
            return None
        pad = 0.012                      # etwas Luft um das Objekt
        x0, x1 = min(xs) / iw - pad, max(xs) / iw + pad
        y0, y1 = min(ys) / ih - pad, max(ys) / ih + pad

        chips = []
        d_mm = (report.candidates[0].corrected_diameter_mm if report.candidates
                else (report.measured or {}).get("circle_diameter_mm"))
        if d_mm:
            chips.append(f"Ø {d_mm:.1f} mm".replace(".", ","))
        chips.append(f"{report.candidates[0].posterior * 100:.0f} %"
                     if report.candidates else "?")
        return Detection(bbox=(x0, y0, x1 - x0, y1 - y0),
                         tone=self.report_tone(report), chips=chips)

    def _show_report(self, report, frame_image=None) -> None:
        """Rendert einen MatchReport in einem der vier Anzeigezustände.
        `frame_image` ist das rohe Vorschaubild aus dem Identifizieren-Job
        (None in Tests, die _show_report direkt mit einem Report aufrufen);
        Rahmen und Maß-Chips zeichnet die Vorschau selbst."""
        self._last_report = report
        self._clear_cards()
        tone = self.report_tone(report)
        if frame_image is not None:
            self.preview.set_overlay(frame_image, self.ui["result_overlay_secs"],
                                     detection=self._detection_for(report))
        # Randberührung wird an BEIDEN Stellen gemeldet: im Bild (dort schaut
        # der Bediener hin) und als Karte in der Spalte (dort steht, was zu
        # tun ist). Der Balken im Bild ist jetzt amber statt rot – der
        # Zustand ist eine Platzierungsfrage, keine Ablehnung.
        self.preview.set_warning(_BORDER_WARNING if tone == "border" else None)

        top_k = int(self.cfg["matching"].get("top_k", 3))
        cands = report.candidates[:top_k]
        {"accept": self._render_accept, "ambiguous": self._render_ambiguous,
         "border": self._render_border}.get(
            tone, self._render_reject)(report, cands)

    # ---------- die vier Zustände ----------

    def _render_accept(self, report, cands) -> None:
        best = cands[0]
        # Ohne Artikelnamen: den zeigt die Karte direkt darunter gross – in
        # der Kopfzeile wiederholt, drängt er die Kennzahl an den Rand.
        text, cls = headline(report.decision)
        self._set_headline(text, cls, f"{best.posterior * 100:.0f} %")
        self.result_area.setText("")
        card = ResultCard(best, self.cfg, tone="accept")
        self.cards_layout.addWidget(card)
        # Bewertung sitzt AUF der Karte, tritt zurueck und blockiert nichts –
        # ist aber erreichbar, denn sie speist die Scoring-Analyse.
        self._add_verdict_bar("Stimmt das Ergebnis?", "Falsch…", host=card)
        self._add_candidate_rows(cands[1:], start_rank=2, clickable=False)
        if self.ui["confirm_sound"]:
            QApplication.beep()

    def _render_ambiguous(self, report, cands) -> None:
        text, cls = headline(report.decision)
        value = f"{cands[0].posterior * 100:.0f} %" if cands else ""
        self._set_headline(text, cls, value)
        self.result_area.setText("")
        card = MessageCard(
            "ambiguous", "Unsicher – bitte wählen",
            subtitle="Kein Kandidat liegt weit genug vorn. Den richtigen "
                     "Artikel unten antippen.")
        self.cards_layout.addWidget(card)
        self._add_candidate_rows(cands, start_rank=1, clickable=True)
        self._none_button = QPushButton("Keiner davon / manuell korrigieren")
        self._none_button.setObjectName("secondaryButton")
        self._none_button.clicked.connect(self._manual_correction)
        self.candidates_layout.addWidget(self._none_button)

    def _render_border(self, report, cands) -> None:
        """Vierter Zustand: Objekt berührt den Bildrand. Amber statt rot –
        es wurde nichts falsch erkannt, es lässt sich nur nicht messen.
        Ohne Bewertungsleiste: hier gibt es kein Ergebnis zu beurteilen."""
        self._set_headline("Objekt berührt den Bildrand", "border", "–")
        self.result_area.setText("")
        self.cards_layout.addWidget(MessageCard(
            "border", "Neu platzieren",
            subtitle="Objekt weiter zur Mitte legen, dann erneut "
                     "„Identifizieren“ drücken. Passt es nicht vollständig "
                     "ins Bild, kann es nicht gemessen werden "
                     "(siehe README, FOV)."))

    def _render_reject(self, report, cands) -> None:
        text, cls = headline(report.decision)
        self._set_headline(text, cls, "?")
        self.result_area.setText("")
        m = report.measured or {}
        d = m.get("circle_diameter_mm")
        card = MessageCard(
            "reject", "Kein Artikel im Toleranzbereich",
            subtitle=report.message,
            big_value=(f"{d:.1f} mm".replace(".", ",") if d else None),
            action_text="Als neuen Artikel einlernen")
        card.action.connect(self._open_enroll_dialog)
        self.cards_layout.addWidget(card)
        self._add_verdict_bar("Ablehnung richtig?", "Falsch…", host=card)
        self._verdict_bar.wrong_button.setToolTip(
            "Objekt ist doch in der Datenbank – wahren Artikel wählen.")
        self._verdict_bar.correct_button.setToolTip(
            "Objekt ist tatsächlich nicht in der Datenbank.")
        # Rohmesswerte: sie zeigen, WAS gemessen wurde, auch wenn kein
        # Artikel passt (kein Kandidat, also kein Ø aus format_diameter).
        if m:
            diag = QLabel(format_measured(m))
            diag.setObjectName("diagnoseLine")
            diag.setWordWrap(True)
            self.cards_layout.addWidget(diag)
            self._diagnose_label = diag
        self._add_candidate_rows(cands, start_rank=1, clickable=True,
                                 title="Am nächsten liegende Kandidaten")

    # ---------- Bausteine ----------

    def _add_candidate_rows(self, cands, start_rank: int, clickable: bool,
                            title: str = "Weitere Kandidaten") -> None:
        if not cands:
            return
        self.candidates_label.setText(title.upper())
        self.candidates_label.setVisible(True)
        for i, c in enumerate(cands, start=start_rank):
            row = CandidateRow(c, self.cfg, rank=i, clickable=clickable)
            if clickable:
                row.clicked.connect(self._confirm_candidate)
            self.candidates_layout.addWidget(row)
            self._rank_lines.append(row)

    def _add_verdict_bar(self, prompt: str, wrong_text: str,
                         host=None) -> None:
        bar = VerdictBar(prompt, wrong_text)
        bar.correct.connect(self._verdict_correct)
        bar.wrong.connect(self._manual_correction)
        if host is not None:
            host.add_footer(bar)
        else:
            self.cards_layout.addWidget(bar)
        self._verdict_bar = bar

    def _verdict_correct(self) -> None:
        """„Richtig": bei ACCEPT bestätigt es den Sieger, bei REJECT die
        Ablehnung selbst („Objekt ist nicht in der Datenbank") – zwei
        verschiedene Urteile, deshalb zwei Fassadenaufrufe."""
        rep = self._last_report
        if rep is None:
            return
        try:
            if self.report_tone(rep) == "accept":
                confirm_result(rep, rep.candidates[0].article_number)
            else:
                confirm_no_match(rep)
        except ValueError as e:
            self._set_headline("Bewertung nicht gespeichert.", "reject")
            self.result_area.setText(str(e))
            return
        if self._verdict_bar is not None:
            self._verdict_bar.acknowledge("Als richtig vermerkt.")

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
        self._set_headline(f"Korrigiert: {name}", "ambiguous")
        self.result_area.setText("Auswahl wurde im Protokoll vermerkt.")
        if self._verdict_bar is not None:
            self._verdict_bar.acknowledge(f"Korrigiert auf {name}.")

    # ---------- Testhilfen (analog ResultCard.all_text) ----------

    def headline_text(self) -> str:
        return self.result_headline.text()

    def rank_lines_count(self) -> int:
        return len(self._rank_lines)

    def none_of_these_button(self):
        return self._none_button

    def diagnose_text(self) -> str:
        return self._diagnose_label.text() if self._diagnose_label else ""
