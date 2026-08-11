"""Admin-Panel Stufe 4: Diagnose-Seiten (Config-Ansicht, Kamera-Diagnose,
Segmentierungs-Test).

Qt offscreen, alles gegen tmp_path bzw. gemockte Fassaden. Kein Test
öffnet eine Kamera (conftest-Stolperdraht bleibt der Wächter); Frames
werden gestellt. Läuft im Test-Regime als EIGENER pytest-Aufruf."""

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


def _cfg(tmp_path):
    return {
        "camera": {"index": 1, "width": 1920, "height": 1080},
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


# ---------- Config-Ansicht (Spec Punkt 11) ----------

def test_config_ansicht_zeigt_herkunft(qapp, tmp_path, monkeypatch):
    from docodetect.ui_qt.admin.pages import config_page as mod
    daten = [("camera.index", "1", "config.local.yaml"),
             ("camera.width", "1920", "config.yaml"),
             ("matching.top_k", "3", "config.yaml")]
    monkeypatch.setattr(mod, "config_with_origin", lambda: daten)
    seite = mod.ConfigPage(_cfg(tmp_path))
    assert seite.zeilen() == daten
    assert "read-only" in seite.hinweis_text()
    assert "keinen Schreibpfad" in seite.hinweis_text()


def test_config_ansicht_fehler_statt_crash(qapp, tmp_path, monkeypatch):
    from docodetect.ui_qt.admin.pages import config_page as mod

    def kaputt():
        raise FileNotFoundError("config.yaml fehlt")

    monkeypatch.setattr(mod, "config_with_origin", kaputt)
    seite = mod.ConfigPage(_cfg(tmp_path))
    assert seite.zeilen() == []
    assert "Config nicht lesbar" in seite.hinweis_text()
    assert "config.yaml fehlt" in seite.hinweis_text()
