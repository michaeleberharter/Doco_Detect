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
    """Minimal-Config wie test_ui_facade.make_cfg, plus captures_dir."""
    return {
        "calibration": {
            "file": str(tmp_path / "calibration.json"),
            "background_file": str(tmp_path / "background.png"),
        },
        "paths": {"db_file": str(tmp_path / "db.sqlite3"),
                  "captures_dir": str(tmp_path / "captures")},
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
