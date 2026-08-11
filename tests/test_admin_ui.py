"""Admin-Panel 1a: Schloss-Knopf, Passwort-Gate, Fenster, Status-Seite.

Qt-Tests offscreen; Muster wie test_ui_state.py. Läuft im Test-Regime der
Spec (Abschnitt 10) als EIGENER pytest-Aufruf in der UI-Schleife."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(scope="module")
def qapp():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from docodetect.ui_qt.app import make_app
    return make_app()


def test_lock_icon_registriert(qapp):
    from docodetect.ui_qt import icons
    assert "lock" in icons._BUILDERS


def test_tool_rail_hat_admin_knopf_mit_signal(qapp):
    from docodetect.ui_qt.widgets.tool_rail import ToolRail
    rail = ToolRail()
    empfangen = []
    rail.admin_requested.connect(lambda: empfangen.append(True))
    rail._admin.click()
    assert empfangen == [True]
    assert rail._admin.isEnabled()        # immer aktiv (Spec Abschnitt 3)


# ---------- Passwort-Gate (Task 4) ----------

def test_auth_dialog_festlegen_schreibt_datei(qapp, tmp_path):
    from docodetect.ui_qt.admin.auth_dialog import AdminAuthDialog
    f = tmp_path / "auth.json"
    dlg = AdminAuthDialog(festlegen=True, auth_file=f)
    dlg.eingabe.setText("geheim")
    dlg.wiederholung.setText("geheim")
    dlg._ok()
    assert dlg.result() == 1
    assert f.exists()


def test_auth_dialog_ungleiche_wiederholung_bleibt_offen(qapp, tmp_path):
    from docodetect.ui_qt.admin.auth_dialog import AdminAuthDialog
    f = tmp_path / "auth.json"
    dlg = AdminAuthDialog(festlegen=True, auth_file=f)
    dlg.eingabe.setText("geheim")
    dlg.wiederholung.setText("anders")
    dlg._ok()
    assert dlg.result() == 0
    assert not f.exists()
    assert "stimmen nicht überein" in dlg.fehler.text()


def test_auth_dialog_pruefen_falsch_dann_richtig(qapp, tmp_path):
    from docodetect import admin_auth
    from docodetect.ui_qt.admin.auth_dialog import AdminAuthDialog
    f = tmp_path / "auth.json"
    admin_auth.set_password("geheim", f)
    dlg = AdminAuthDialog(festlegen=False, auth_file=f)
    dlg.eingabe.setText("falsch")
    dlg._ok()
    assert dlg.result() == 0                      # offen, kein Lockout
    assert dlg.fehler.text() == "Falsches Passwort."
    dlg.eingabe.setText("geheim")
    dlg._ok()
    assert dlg.result() == 1


# ---------- Fenster-Gerüst + Status-Seite (Task 5) ----------

def _admin_cfg(tmp_path):
    """Minimal-Config wie test_ui_facade.make_cfg, plus captures_dir.
    analysis/matching seit Stufe 2: Analyse- und Artikel-Seite laufen
    damit gegen tmp_path, nie gegen reports/analysis/ des Repos."""
    return {
        "calibration": {
            "file": str(tmp_path / "calibration.json"),
            "background_file": str(tmp_path / "background.png"),
        },
        "paths": {"db_file": str(tmp_path / "db.sqlite3"),
                  "captures_dir": str(tmp_path / "captures")},
        "analysis": {"output_dir": str(tmp_path / "runs")},
        "matching": {"diameter_tolerance_mm": 6.0, "top_k": 3},
        "stage2": {"enabled": False},
    }


def test_admin_window_seiten_und_leerzustand(qapp, tmp_path):
    from docodetect.ui_qt.admin.admin_window import AdminWindow
    win = AdminWindow(_admin_cfg(tmp_path), camera_status=lambda: "Demo")
    assert win.sidebar.count() == 5           # Status..Diagnose (Spec §4)
    w = win.status_page.werte()
    assert w["kamera"] == "Demo"
    assert w["fingerprint"] == "nicht kalibriert"
    assert w["kalibriert"] == "nicht kalibriert"
    assert w["artikel"].startswith("0")
    assert w["sandbox"] == "–"
    win.close()


def test_admin_window_sidebar_wechselt_seiten(qapp, tmp_path):
    from docodetect.ui_qt.admin.admin_window import AdminWindow
    win = AdminWindow(_admin_cfg(tmp_path), camera_status=lambda: "Demo")
    win.sidebar.setCurrentRow(2)
    assert win.stack.currentIndex() == 2
    win.close()


def test_status_page_fingerprint_mit_einrichtung(qapp, tmp_path):
    import time

    import cv2
    import numpy as np

    from docodetect.calibration import Calibration
    from docodetect.ui_qt.admin.pages.status_page import StatusPage

    cfg = _admin_cfg(tmp_path)
    cfg["features"] = {"ring_zones": 3, "hs_hist_bins": [8, 8]}
    Calibration(mm_per_px=0.5, camera_height_mm=300.0, image_width=1920,
                image_height=1080, marker_size_mm=72.5,
                created_unix=time.time()).save(cfg["calibration"]["file"])
    cv2.imwrite(cfg["calibration"]["background_file"],
                np.zeros((8, 8, 3), dtype=np.uint8))
    seite = StatusPage(cfg, camera_status=lambda: "verbunden")
    w = seite.werte()
    assert len(w["background_sha256"]) == 64
    assert w["mm_per_px"] == "0,5000"


# ---------- Anbindung ans Hauptfenster (Task 6) ----------

def make_main_cfg(tmp_path):
    """Minimal-Config für ein Demo-MainWindow (wie test_ui_state.py)."""
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
        "matching": {"diameter_tolerance_mm": 6.0, "top_k": 3},
        "stage2": {"enabled": False},
    }


def test_schloss_oeffnet_admin_nur_mit_zugang(qapp, tmp_path, monkeypatch):
    from docodetect.ui_qt import main_window as mw_mod
    from docodetect.ui_qt.admin import auth_dialog

    win = mw_mod.MainWindow(make_main_cfg(tmp_path), demo=True)
    monkeypatch.setattr(auth_dialog, "ensure_admin_access",
                        lambda parent=None, auth_file=None: False)
    win._open_admin_panel()
    assert win._admin_window is None              # Zugang verweigert
    monkeypatch.setattr(auth_dialog, "ensure_admin_access",
                        lambda parent=None, auth_file=None: True)
    win._open_admin_panel()
    assert win._admin_window is not None
    assert win._camera_status_text() == "Demo"
    erstes = win._admin_window
    win._open_admin_panel()                       # fokussiert nur
    assert win._admin_window is erstes
    win._admin_window.close()
    win.close()


def test_admin_window_stufe2_seiten_real(qapp, tmp_path):
    from docodetect.ui_qt.admin.admin_window import AdminWindow
    from docodetect.ui_qt.admin.pages.analysis_page import AnalysisPage
    from docodetect.ui_qt.admin.pages.articles_page import ArticlesPage
    win = AdminWindow(_admin_cfg(tmp_path), camera_status=lambda: "Demo")
    assert win.sidebar.count() == 5
    assert isinstance(win.analysis_page, AnalysisPage)
    assert isinstance(win.articles_page, ArticlesPage)
    assert win.stack.widget(2) is win.analysis_page
    # Seit Stufe 4 ist die Artikel-Sektion ein Tab-Container
    # (Artikelliste | Einlern-Sessions) — bewusste Strukturänderung.
    assert win.stack.widget(3) is win.artikel_tabs
    assert win.artikel_tabs.widget(0) is win.articles_page
    win.close()


def test_admin_window_stufe4_sektionen_und_meldekanaele(qapp, tmp_path):
    from docodetect.ui_qt.admin.admin_window import AdminWindow
    from docodetect.ui_qt.admin.pages.camera_page import CameraPage
    from docodetect.ui_qt.admin.pages.config_page import ConfigPage
    from docodetect.ui_qt.admin.pages.segtest_page import SegTestPage
    from docodetect.ui_qt.admin.pages.sessions_page import SessionsPage
    win = AdminWindow(_admin_cfg(tmp_path), camera_status=lambda: "Demo")
    assert win.sidebar.count() == 5            # Sidebar bleibt bei fünf
    assert isinstance(win.segtest_page, SegTestPage)
    assert isinstance(win.config_page, ConfigPage)
    assert isinstance(win.camera_page, CameraPage)
    assert isinstance(win.sessions_page, SessionsPage)
    assert win.artikel_tabs.count() == 2       # Artikelliste | Sessions
    assert win.artikel_tabs.widget(0) is win.articles_page
    assert win.diagnose_tabs.count() == 3      # SegTest | Config | Kamera
    # Ohne Meldekanaele: SegTest deaktiviert, Fortsetzen nur Hinweis
    assert not win.segtest_page.aufnahme_button.isEnabled()
    assert "Hauptfenster" in win.sessions_page.fortsetzen_hinweis_text()
    win.close()


def test_main_window_meldekanaele_fuer_admin(qapp, tmp_path):
    from docodetect.ui_qt import main_window as mw_mod
    win = mw_mod.MainWindow(make_main_cfg(tmp_path), demo=True)
    # Fortsetzen-Pruefung: Demo startet NOT_READY (keine Kalibrierung)
    hinweis = win._fortsetzen_pruefen()
    assert hinweis is not None and "READY" in hinweis
    # Kamera-Warntext existiert (leer ist ok)
    assert isinstance(win._kamera_warnungs_text(), str)
    # Frame-Anforderung: Demo-Quelle liefert einen Frame
    empfangen = []
    ok = win._frame_fuer_admin(lambda f: empfangen.append(f))
    assert ok
    import time
    ende = time.monotonic() + 5.0
    while not empfangen and time.monotonic() < ende:
        qapp.processEvents()
    assert len(empfangen) == 1
    assert empfangen[0] is not None
    win.close()


def test_admin_window_close_wartet_auf_laufende_worker(qapp, tmp_path,
                                                       monkeypatch):
    """Review 2026-08-11: WA_DeleteOnClose darf keinen QThread im Lauf
    zerstoeren — beim Verwerfen waere das mitten in Dateibewegungen.
    Der Test beweist durch Ueberleben (ein zerstoerter laufender QThread
    waere ein qFatal-Abbruch des Prozesses)."""
    import time

    from docodetect.ui_qt.admin import admin_window as aw
    from docodetect.ui_qt.pipeline_worker import PipelineWorker
    win = aw.AdminWindow(_admin_cfg(tmp_path), camera_status=lambda: "Demo")
    tab = win.analysis_page.lauf_tab
    w = PipelineWorker(lambda: time.sleep(0.3) or "fertig", tab)
    w.finished.connect(lambda: setattr(tab, "_worker", None))
    tab._worker = w
    w.start()
    win.close()                                   # wartet via closeEvent
    assert tab._worker is None or not tab._worker.isRunning()


def test_main_window_kamera_frei_im_demo(qapp, tmp_path):
    from docodetect.ui_qt import main_window as mw_mod
    win = mw_mod.MainWindow(make_main_cfg(tmp_path), demo=True)
    assert win._kamera_frei_fuer_suche() is True   # DemoSource haelt nichts
    win.close()
