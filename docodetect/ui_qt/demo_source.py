"""Demo-Bildquelle: dieselbe Signal-Schnittstelle wie der CameraWorker,
aber Bilder aus dem synthetischen Testkit (demo_scenes) statt Kamera.

full_frame_ready liefert die Szene in Kamera-Originalauflösung – die
Pipeline merkt keinen Unterschied. --demo leitet zusätzlich alle Pfade
nach data/demo/ um (apply_demo_paths), damit der Demo-Modus die echte
Einrichtung (DB, Kalibrierung, Hintergrund, Captures) nie anfasst.
"""

from __future__ import annotations

import copy

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QImage

from .app import ui_cfg
from .demo_scenes import SCENE_NAMES, build_scene
from .qimage import bgr_to_qimage, downscale_width

DEMO_DIR = "data/demo"


def apply_demo_paths(cfg: dict) -> dict:
    """Kopie der Config mit allen Schreib-Pfaden unter data/demo/ –
    Demo und echte Einrichtung können sich nie gegenseitig überschreiben."""
    cfg = copy.deepcopy(cfg)
    cfg["calibration"]["file"] = f"{DEMO_DIR}/calibration.json"
    cfg["calibration"]["background_file"] = f"{DEMO_DIR}/background.png"
    cfg["paths"]["db_file"] = f"{DEMO_DIR}/demo.sqlite3"
    cfg["paths"]["captures_dir"] = f"{DEMO_DIR}/captures"
    cfg["paths"]["reference_dir"] = f"{DEMO_DIR}/reference"
    return cfg


class DemoSource(QObject):
    """Läuft im GUI-Thread (statische Bilder, kein I/O) – bewusst dieselben
    Signale wie der CameraWorker (Phase 4), damit MainWindow quellenagnostisch
    bleibt."""

    frame_ready = Signal(QImage)          # Vorschau (downscaled)
    full_frame_ready = Signal(object)     # np.ndarray BGR, Originalauflösung
    camera_error = Signal(str)            # in der Demo nie emittiert

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.ui = ui_cfg(cfg)
        self._scene_name = SCENE_NAMES[0]
        self._full: np.ndarray | None = None
        self._preview: QImage | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(max(1, int(1000 / self.ui["preview_fps"])))
        self._timer.timeout.connect(self._tick)

    # ---------- CameraWorker-kompatible API ----------

    def start(self) -> None:
        self._render()
        self._timer.start()
        self._tick()

    def stop(self) -> None:
        self._timer.stop()

    def request_full_frame(self) -> None:
        """Nächster kompletter Frame in voller Auflösung – hier sofort."""
        if self._full is None:
            self._render()
        self.full_frame_ready.emit(self._full)

    @property
    def camera_ok(self) -> bool:
        return True

    # ---------- Demo-spezifisch ----------

    def set_scene(self, name: str) -> None:
        if name != self._scene_name:
            self._scene_name = name
            self._render()
            self._tick()

    @property
    def scene_name(self) -> str:
        return self._scene_name

    def _render(self) -> None:
        self._full = build_scene(self.cfg, self._scene_name)
        self._preview = bgr_to_qimage(
            downscale_width(self._full, self.ui["preview_max_width"]))

    def _tick(self) -> None:
        if self._preview is not None:
            self.frame_ready.emit(self._preview)
