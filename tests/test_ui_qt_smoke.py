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
        "camera": {"width": 1920, "height": 1080},
        "calibration": {
            "file": str(tmp_path / "calibration.json"),
            "background_file": str(tmp_path / "background.png"),
            "aruco_dict": "DICT_4X4_50", "marker_id": 0,
            "marker_size_mm": 136.0,
        },
        "geometry": {"camera_height_mm": 300.0},
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


def test_main_window_unconfigured_is_no_camera(qapp, tmp_path):
    """Ohne Quelle (kein Demo, CameraWorker erst Phase 4): NO_CAMERA mit
    Platzhalter-Text; Status zeigt Einrichtungsbedarf."""
    from docodetect.ui_qt.main_window import MainWindow
    from docodetect.ui_qt.state import UiState

    win = MainWindow(make_cfg(tmp_path))
    assert win.windowTitle() == "Doco Detect"
    assert win.state is UiState.NO_CAMERA
    assert not win.identify_button.isEnabled()
    assert not win.background_button.isEnabled()
    assert win.preview._message and "Keine Kamera" in win.preview._message
    assert win.status_content.calibration.text() == "Nicht kalibriert"
    assert win.status_content.articles.text() == "0 Artikel (0 eingelernt)"
    assert win.status_content.stage2.text() == "S2 aus"
    assert win.pipeline_status.ready is False


def test_main_window_demo_not_ready_shows_guide(qapp, tmp_path):
    """Demo-Quelle da, aber keine Einrichtung: NOT_READY, Identifizieren aus,
    Setup-Buttons an, Ergebnisbereich zeigt die Checklisten-Führung."""
    from docodetect.ui_qt.main_window import MainWindow
    from docodetect.ui_qt.state import UiState

    win = MainWindow(make_cfg(tmp_path), demo=True)
    assert "Demo" in win.windowTitle()
    assert win.state is UiState.NOT_READY
    assert not win.identify_button.isEnabled()
    assert win.background_button.isEnabled()
    assert win.calibrate_button.isEnabled()
    assert not win.enroll_button.isEnabled()
    assert "Einrichtung nötig" in win.result_area.text()
    assert "[offen]" in win.result_area.text()
    assert win.demo_bar.isVisibleTo(win)
    assert win.preview._message is None  # Vorschau zeigt Demo-Bild


def test_main_window_demo_ready(qapp, tmp_path):
    """Kalibrierung + Hintergrund + eingelernter Artikel vorhanden -> READY,
    Identifizieren aktiv (kein Auto-Seed, weil Referenzen existieren)."""
    import cv2
    import numpy as np

    from docodetect.calibration import Calibration
    from docodetect.database import Article, Database
    from docodetect.features import Features
    from docodetect.ui_qt.main_window import MainWindow
    from docodetect.ui_qt.state import UiState

    cfg = make_cfg(tmp_path)
    Calibration(mm_per_px=0.2, camera_height_mm=300.0, image_width=1920,
                image_height=1080, marker_size_mm=136.0,
                created_unix=time.time()).save(cfg["calibration"]["file"])
    cv2.imwrite(cfg["calibration"]["background_file"],
                np.full((10, 10, 3), 200, dtype=np.uint8))
    db = Database(cfg)
    db.init_schema()
    db.create_article(Article(article_number="X", name="X", category=None,
                              diameter_mm=100.0, width_mm=None, depth_mm=None,
                              height_mm=None, color_desc=None, notes=None))
    db.add_reference("X", Features(
        equiv_diameter_mm=100, circle_diameter_mm=100, area_mm2=7854,
        perimeter_mm=314, circularity=0.95, aspect_ratio=1.0))
    db.close()
    win = MainWindow(cfg, demo=True)
    assert win.state is UiState.READY
    assert win.identify_button.isEnabled()
    assert win.enroll_button.isEnabled()


def test_demo_source_emits_frames(qapp, tmp_path):
    """DemoSource liefert Vorschau-QImage (downscaled) und volle Auflösung."""
    from PySide6.QtGui import QImage

    from docodetect.ui_qt.demo_source import DemoSource

    src = DemoSource(make_cfg(tmp_path))
    frames, fulls = [], []
    src.frame_ready.connect(frames.append)
    src.full_frame_ready.connect(fulls.append)
    src.start()
    src.stop()
    assert frames and isinstance(frames[0], QImage)
    assert frames[0].width() == 960  # ui.preview_max_width Fallback
    src.set_scene("Teller 18")
    src.request_full_frame()
    assert fulls and fulls[0].shape == (1080, 1920, 3)


def test_apply_demo_paths_redirects_everything(tmp_path):
    from docodetect.ui_qt.demo_source import apply_demo_paths

    cfg = make_cfg(tmp_path)
    demo = apply_demo_paths(cfg)
    for value in (demo["calibration"]["file"],
                  demo["calibration"]["background_file"],
                  demo["paths"]["db_file"], demo["paths"]["captures_dir"],
                  demo["paths"]["reference_dir"]):
        assert value.startswith("data/demo/")
    # Original unangetastet (deepcopy)
    assert cfg["paths"]["db_file"].endswith("db.sqlite3")


def _wait_until(qapp, cond, timeout=90.0):
    """Event-Schleife treiben, bis cond() wahr ist (Worker-Signale sind
    QueuedConnections und brauchen processEvents)."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        qapp.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_demo_end_to_end_identify(qapp, tmp_path):
    """Der Phase-3-Abnahmepfad als Test: Hintergrund aufnehmen ->
    Kalibrieren -> (Auto-Seed) -> Teller 18 ACCEPT -> Teller 20 ACCEPT ->
    Randbild rote Rand-Warnung. GUI-Thread bleibt frei (Worker-Threads)."""
    from docodetect.config import load_config
    from docodetect.ui_qt.main_window import MainWindow
    from docodetect.ui_qt.state import UiState

    cfg = load_config()
    cfg["calibration"]["file"] = str(tmp_path / "calibration.json")
    cfg["calibration"]["background_file"] = str(tmp_path / "background.png")
    cfg["paths"] = {"db_file": str(tmp_path / "demo.sqlite3"),
                    "captures_dir": str(tmp_path / "captures"),
                    "reference_dir": str(tmp_path / "reference")}
    win = MainWindow(cfg, demo=True)
    assert win.state is UiState.NOT_READY

    # Schritt 1: Hintergrund (Szene "Hintergrund" ist Default)
    win.background_button.click()
    assert _wait_until(qapp, lambda: not win._busy)
    assert win.pipeline_status.background_present
    assert "[erledigt]" in win.result_area.text()  # Checkliste rückt weiter

    # Schritt 2: Kalibrieren mit Marker-Szene -> READY -> Auto-Seed (3 Artikel)
    win.demo_scene_box.setCurrentText("Marker")
    win.calibrate_button.click()
    assert _wait_until(
        qapp, lambda: (not win._busy
                       and win.pipeline_status.articles_with_references == 3))
    assert win.state is UiState.READY
    assert win.identify_button.isEnabled()

    # Teller 18 -> ACCEPT, Karte grün, plausibler Ø (nominal 180 mm)
    win.demo_scene_box.setCurrentText("Teller 18")
    win.identify_now()
    assert _wait_until(qapp, lambda: not win._busy)
    assert win._last_report.decision == "accept"
    assert win.result_headline.text() == "Erkannt: Teller flach 18"
    best = win._last_report.candidates[0]
    assert best.article_number == "DEMO-T18"
    assert abs(best.corrected_diameter_mm - 180.0) < 4.0
    assert win.cards_layout.count() >= 1
    assert win.preview._overlay is not None      # annotiertes Ergebnisbild
    assert win.preview._warn_text is None

    # Teller 20 -> korrekter Artikel
    win.demo_scene_box.setCurrentText("Teller 20")
    win.identify_now()
    assert _wait_until(qapp, lambda: not win._busy)
    assert win._last_report.decision == "accept"
    assert win._last_report.candidates[0].article_number == "DEMO-T20"

    # Randbild -> rote Rand-Warnung statt Messwert
    win.demo_scene_box.setCurrentText("Randbild")
    win.identify_now()
    assert _wait_until(qapp, lambda: not win._busy)
    assert win._last_report.decision == "reject"
    assert win._last_report.touches_border
    assert win.preview._warn_text and "Bildrand" in win.preview._warn_text
    assert "Bildrand" in win.result_headline.text()
    win.close()


def test_fit_rect_letterbox_math():
    """Kein Verzerren: Seitenverhältnis bleibt, Rechteck zentriert."""
    from docodetect.ui_qt.widgets.preview import fit_rect

    r = fit_rect(1000, 500, 1920, 1080)  # Container breiter als Bild
    assert r.height() == 500 and r.width() == 888  # 500 * 16/9
    assert r.x() == (1000 - 888) // 2 and r.y() == 0
    r = fit_rect(1920, 2000, 1920, 1080)  # Container höher als Bild
    assert r.width() == 1920 and r.height() == 1080
    assert r.y() == (2000 - 1080) // 2
    assert fit_rect(100, 100, 0, 0).isEmpty()


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
