"""Smoke-Tests für die Qt-UI: Instanziierung offscreen, keine Kamera.

PySide6 ist optional (requirements-ui-qt.txt) – ohne Installation werden
die Tests übersprungen, wie bei Stufe 2. Kein Pixel-Vergleich: geprüft wird,
dass Fenster/Widgets entstehen, die Statusleiste echte Fassaden-Werte zeigt
und die UI-Regel (nur pipeline-Imports) nicht crasht.
"""

import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from docodetect.ui_qt.app import make_app, ui_cfg  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return make_app()


def make_cfg(tmp_path):
    return {
        "calibration": {
            "file": str(tmp_path / "calibration.json"),
            "background_file": str(tmp_path / "background.png"),
        },
        "paths": {"db_file": str(tmp_path / "db.sqlite3")},
        "stage2": {"enabled": False},
    }


def test_ui_cfg_defaults_without_section():
    """Fehlende ui:-Sektion => Code-Fallbacks (Plan: Default im Code)."""
    ui = ui_cfg({})
    assert ui["preview_max_width"] == 960
    assert ui["preview_fps"] == 15
    assert ui["window_min_width"] == 1280


def test_ui_cfg_overrides():
    ui = ui_cfg({"ui": {"preview_fps": 5}})
    assert ui["preview_fps"] == 5
    assert ui["preview_max_width"] == 960


def test_main_window_unconfigured(qapp, tmp_path):
    """Fenster entsteht ohne Kalibrierung/DB; Status zeigt Einrichtungsbedarf."""
    from docodetect.ui_qt.main_window import MainWindow

    win = MainWindow(make_cfg(tmp_path))
    assert win.windowTitle() == "Doco Detect"
    assert not win.identify_button.isEnabled()
    assert win.status_content.calibration.text() == "Nicht kalibriert"
    assert win.status_content.articles.text() == "0 Artikel (0 eingelernt)"
    assert win.status_content.stage2.text() == "S2 aus"
    assert win.pipeline_status.ready is False


def test_main_window_demo_flag(qapp, tmp_path):
    from docodetect.ui_qt.main_window import MainWindow

    win = MainWindow(make_cfg(tmp_path), demo=True)
    assert "Demo" in win.windowTitle()


def test_status_bar_calibrated(qapp, tmp_path):
    from docodetect.calibration import Calibration
    from docodetect.ui_qt.main_window import MainWindow

    cfg = make_cfg(tmp_path)
    Calibration(mm_per_px=0.171, camera_height_mm=300.0, image_width=1920,
                image_height=1080, marker_size_mm=136.0,
                created_unix=time.time()).save(cfg["calibration"]["file"])
    win = MainWindow(cfg)
    assert win.status_content.calibration.text().startswith("Kalibriert ")
    assert "0,171 mm/px" in win.status_content.calibration.text()
