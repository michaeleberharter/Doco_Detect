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
