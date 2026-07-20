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
    assert win.result_headline.text() == "✓ Automatisch übernommen: Teller flach 18"
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


def test_camera_worker_without_camera_goes_no_camera(qapp, tmp_path):
    """Ersatz-Abnahme Phase 4 (Kamera nicht angeschlossen): App startet ohne
    Kamera sauber in NO_CAMERA („Keine Kamera gefunden…“), kein Crash, kein
    Einfrieren; der Reconnect läuft leise im Hintergrund weiter (Thread
    lebt); stop() beendet den Worker prompt (unterbricht das Reconnect-
    Warten)."""
    from docodetect.ui_qt.main_window import MainWindow
    from docodetect.ui_qt.state import UiState

    cfg = make_cfg(tmp_path)
    cfg["camera"].update(index=99, warmup_frames=0)  # Index existiert sicher nicht
    win = MainWindow(cfg, demo=False)
    errors = []
    win.source.camera_error.connect(lambda m: errors.append(m))
    try:
        # Warten bis der ERSTE Öffnungsversuch gescheitert ist (Signal
        # angekommen) – der Startzustand ist bereits NO_CAMERA.
        assert _wait_until(
            qapp, lambda: win.status_content.camera.text() == "Kamera getrennt",
            timeout=15)
        assert win.state is UiState.NO_CAMERA
        assert not win.source.camera_ok
        assert win.preview._message and "Keine Kamera" in win.preview._message
        assert not win.identify_button.isEnabled()
        # Reconnect läuft leise: Thread lebt, KEINE weitere Fehlermeldung folgt
        assert win.source.isRunning()
        time.sleep(0.5)
        qapp.processEvents()
        assert len(errors) == 1
        # Identifizieren im NO_CAMERA-Zustand ist ein No-Op, kein Crash
        win.identify_now()
        assert not win._busy
    finally:
        t0 = time.time()
        win.close()  # closeEvent -> source.stop() -> wait()
        assert time.time() - t0 < 8.0
        assert not win.source.isRunning()


def test_camera_worker_focus_warning_signal(qapp, tmp_path):
    """Auf macOS (kein DSHOW) muss die Fokus-Lock-Warnung als Signal kommen,
    sobald eine Kamera verbindet – hier direkt der Warntext-Kontrakt."""
    from docodetect.ui_qt.camera_worker import FOCUS_WARNING

    assert "Windows" in FOCUS_WARNING
    assert "Fokus-Lock" in FOCUS_WARNING


def test_status_bar_warning_label(qapp):
    from docodetect.ui_qt.widgets.status_bar import StatusBarContent

    bar = StatusBarContent()
    assert not bar.warn.isVisibleTo(bar)
    bar.set_warning("Fokus-Lock nicht verfügbar")
    assert bar.warn.isVisibleTo(bar)
    bar.set_warning("")
    assert not bar.warn.isVisibleTo(bar)


def test_enroll_dialog_demo_flow(qapp, tmp_path):
    """Phase-5-Abnahme: Einlern-Durchlauf legt Referenzen an, die
    anschließend beim Identifizieren wirken; einzelne Aufnahme wiederholbar;
    Randberührung wird als handlungsleitender Fehler verworfen."""
    from docodetect.config import load_config
    from docodetect.pipeline import (Pipeline, calibrate, capture_background,
                                     list_articles)
    from docodetect.ui_qt.demo_scenes import DEMO_ARTICLES, build_scene
    from docodetect.ui_qt.main_window import MainWindow
    from docodetect.ui_qt.state import UiState
    from docodetect.ui_qt.widgets.enroll_dialog import EnrollDialog

    cfg = load_config()
    cfg["calibration"]["file"] = str(tmp_path / "calibration.json")
    cfg["calibration"]["background_file"] = str(tmp_path / "background.png")
    cfg["paths"] = {"db_file": str(tmp_path / "demo.sqlite3"),
                    "captures_dir": str(tmp_path / "captures"),
                    "reference_dir": str(tmp_path / "reference")}
    capture_background(build_scene(cfg, "Hintergrund"), cfg)
    calibrate(build_scene(cfg, "Marker"), cfg)
    # Einen Artikel mit 1 Referenz anlegen -> kein Auto-Seed, schneller Test
    art = DEMO_ARTICLES[0]
    pipe = Pipeline(cfg)
    pipe.db.init_schema()
    pipe.create_article(build_scene(cfg, art.scene_name, 1), art.name,
                        article_number=art.article_number,
                        height_mm=art.height_mm, category=art.category)
    pipe.close()

    win = MainWindow(cfg, demo=True)
    assert win.state is UiState.READY
    win.demo_scene_box.setCurrentText("Teller 18")

    dlg = EnrollDialog(cfg, win.ui, win.source, win)
    assert dlg.article_box.currentData() == art.article_number
    assert "1 Referenz" in dlg.ref_label.text()
    dlg.shots_spin.setValue(2)
    assert "Aufnahme 1 von 2" in dlg.progress_label.text()

    dlg._capture()
    assert _wait_until(qapp, lambda: len(dlg._shots) == 1
                       and dlg._worker is None)
    assert "Ø" in dlg.thumbs.item(0).text()
    dlg._capture()
    assert _wait_until(qapp, lambda: len(dlg._shots) == 2
                       and dlg._worker is None)
    assert "Speichern (2/2)" in dlg.save_button.text()

    # Aufnahme 1 wiederholen: ersetzt, Anzahl bleibt 2
    dlg._thumb_clicked(dlg.thumbs.item(0))
    assert "wiederholen" in dlg.progress_label.text()
    dlg._capture()
    assert _wait_until(qapp, lambda: dlg._worker is None
                       and dlg._retake_index is None)
    assert len(dlg._shots) == 2

    # Randbild -> Aufnahme verworfen mit Abhilfe-Text, Shots unverändert
    win.demo_scene_box.setCurrentText("Randbild")
    dlg.shots_spin.setValue(3)
    dlg._capture()
    assert _wait_until(qapp, lambda: dlg._worker is None
                       and dlg.hint_label.text() != "")
    assert "verworfen" in dlg.hint_label.text()
    assert len(dlg._shots) == 2

    # Speichern -> Referenzen in der DB (1 vorhandene + 2 neue)
    win.demo_scene_box.setCurrentText("Teller 18")
    dlg._save()
    assert _wait_until(qapp, lambda: dlg.saved_count == 2)
    arts = {a.article_number: a for a in list_articles(cfg)}
    assert arts[art.article_number].n_references == 3

    # ... und sie wirken beim Identifizieren (ACCEPT mit 3 Shots)
    win.refresh_status()
    win.identify_now()
    assert _wait_until(qapp, lambda: not win._busy)
    assert win._last_report.decision == "accept"
    best = win._last_report.candidates[0]
    assert best.article_number == art.article_number
    assert best.n_shots == 3
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


def test_result_card_shows_helper_strings_and_channel_bars(qapp):
    """ResultCard zeigt Ø/Δ ausschließlich über die zentralen Helfer
    (pipeline.format_diameter/format_delta) und ein Teilscore-Balken je
    Kanal; ein Kanal ohne Merkmale (hier: geometry-only) bleibt None statt
    fälschlich 100 % anzuzeigen."""
    from docodetect.matcher import CandidateReport, FeatureScore
    from docodetect.ui_qt.widgets.result_card import ResultCard

    cand = CandidateReport(
        article_number="S-140", name="Schüssel 14", nominal_size_mm=140.0,
        height_mm=60.0, corrected_diameter_mm=141.0, geometry_error_mm=2.4,
        has_references=True, n_shots=3,
        features=[FeatureScore(feature="diameter_mm", measured=141.0,
                               reference=140.0, distance=1.0, sigma_enroll=0.0,
                               sigma_eff=1.5, z=0.67, log_contrib=-0.22,
                               w_eff=0.5, weighted=-0.11)],
        log_score=-0.11, posterior=0.87, max_abs_z=0.67)
    cfg = {"matching": {"diameter_tolerance_mm": 6.0}}
    card = ResultCard(cand, cfg)
    texts = card.all_text()   # neue Testhilfe fuer Offscreen-Tests
    assert "Ø 141,0 mm (höhenkorrigiert, h = 60 mm)" in texts
    assert "Δ 2,4 mm von ±6,0" in texts
    bars = card.channel_bars()  # dict Kanal -> QProgressBar|None
    assert bars["geometry"] is not None
    assert bars["color"] is None and bars["shape"] is None
