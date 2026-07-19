"""Hauptfenster: Vorschau links, Aktions-Panel rechts, Statusleiste unten.

Zustandsmaschine (state.py): NO_CAMERA / NOT_READY / READY / BUSY – ein
Enum, ein set_state(); der Empty State ist eine Handlungsanleitung
(Einrichtungs-Checkliste), kein toter Bildschirm. Bildquelle ist entweder
die DemoSource (--demo) oder der CameraWorker (Phase 4) – beide mit
derselben Signal-Schnittstelle.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QMainWindow,
                               QPushButton, QVBoxLayout, QWidget)

from docodetect.pipeline import get_status

from .app import ui_cfg
from .state import UiState, compute_state
from .widgets.preview import PreviewWidget
from .widgets.status_bar import StatusBarContent

# Feste Breite des Aktions-Panels: die Vorschau soll den restlichen Platz
# füllen; 360 px reichen für ResultCards mit Messwert-Zeile.
_PANEL_WIDTH = 360

_NO_CAMERA_TEXT = ("Keine Kamera gefunden –\nVerbindung wird gesucht…")

_IDENTIFY_TOOLTIPS = {
    UiState.NO_CAMERA: "Keine Kamera verbunden.",
    UiState.NOT_READY: "Erst einrichten: Hintergrund aufnehmen und kalibrieren.",
    UiState.READY: "Objekt mittig auflegen und identifizieren (Leertaste).",
    UiState.BUSY: "Bitte warten – Auswertung läuft.",
}


class MainWindow(QMainWindow):
    def __init__(self, cfg: dict, demo: bool = False):
        super().__init__()
        self.cfg = cfg
        self.demo = demo
        self.ui = ui_cfg(cfg)
        self.source = None          # DemoSource | CameraWorker (Phase 4)
        self._busy = False
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

        if demo:
            self._attach_demo_source()
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

        self.result_area = QLabel("Noch kein Ergebnis.")
        self.result_area.setObjectName("guideLabel")
        self.result_area.setWordWrap(True)
        self.result_area.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        lay.addWidget(self.result_area, stretch=1)

        self.background_button = QPushButton("Hintergrund aufnehmen")
        self.calibrate_button = QPushButton("Kalibrieren")
        self.enroll_button = QPushButton("Artikel einlernen…")
        for b in (self.background_button, self.calibrate_button,
                  self.enroll_button):
            b.setObjectName("secondaryButton")
            lay.addWidget(b)
        return panel

    def _attach_demo_source(self) -> None:
        from .demo_scenes import SCENE_NAMES
        from .demo_source import DemoSource

        self.source = DemoSource(self.cfg, self)
        self.source.frame_ready.connect(self.preview.set_frame)
        self.demo_scene_box.addItems(SCENE_NAMES)
        self.demo_scene_box.currentTextChanged.connect(self.source.set_scene)
        self.demo_bar.setVisible(True)
        self.source.start()

    # ---------- Zustandsmaschine ----------

    @property
    def camera_ok(self) -> bool:
        return self.source is not None and self.source.camera_ok

    def refresh_status(self) -> None:
        """Statusleiste + Zustand aus der Pipeline-Fassade (echte Werte)."""
        self.pipeline_status = get_status(self.cfg)
        self.status_content.update_status(self.pipeline_status)
        self.update_state()

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
