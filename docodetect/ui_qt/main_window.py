"""Hauptfenster: Layout (Vorschau links, Aktions-Panel rechts, Statusleiste).

Phase 1: Platzhalter-Layout + echte Statuswerte aus pipeline.get_status().
Die Zustandsmaschine (NO_CAMERA/NOT_READY/READY/BUSY) folgt in Phase 2,
die Pipeline-Anbindung in Phase 3, die echte Kamera in Phase 4.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QMainWindow, QPushButton,
                               QVBoxLayout, QWidget)

from docodetect.pipeline import get_status

from .app import ui_cfg
from .widgets.status_bar import StatusBarContent

# Feste Breite des Aktions-Panels: die Vorschau soll den restlichen Platz
# füllen; 360 px reichen für ResultCards mit Messwert-Zeile.
_PANEL_WIDTH = 360


class MainWindow(QMainWindow):
    def __init__(self, cfg: dict, demo: bool = False):
        super().__init__()
        self.cfg = cfg
        self.demo = demo
        self.ui = ui_cfg(cfg)
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
        self.refresh_status()

    # ---------- Aufbau ----------

    def _build_preview_area(self) -> QWidget:
        """Phase-1-Platzhalter – wird in Phase 2 durch das Preview-Widget
        (Skalierung, Fadenkreuz, Rand-Warnrahmen) ersetzt."""
        self.preview_placeholder = QLabel(
            "Vorschau\n\n(Kamera folgt in Phase 4, Demo-Quelle in Phase 2)")
        self.preview_placeholder.setObjectName("previewPlaceholder")
        self.preview_placeholder.setAlignment(Qt.AlignCenter)
        self.preview_placeholder.setMinimumSize(640, 360)
        return self.preview_placeholder

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
        self.identify_button.setEnabled(False)  # Phase 3 verdrahtet die Aktion
        self.identify_button.setToolTip("Pipeline-Anbindung folgt in Phase 3.")
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
            b.setEnabled(False)  # Phase 3/5 verdrahten die Aktionen
            lay.addWidget(b)
        return panel

    # ---------- Status ----------

    def refresh_status(self) -> None:
        """Statusleiste aus der Pipeline-Fassade füllen (echte Werte)."""
        self.pipeline_status = get_status(self.cfg)
        self.status_content.update_status(self.pipeline_status)
