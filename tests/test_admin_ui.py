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
