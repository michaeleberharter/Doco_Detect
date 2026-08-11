"""Admin-Panel Stufe 2: Analyse-Lauf-Seite (Worker, Historie, Betrachter).

Qt offscreen, alles gegen tmp_path — nie gegen reports/analysis/ des
Repos. Der Worker-Test nutzt eine monkeypatchte Fassade (schnell,
deterministisch) und wartet per processEvents-Schleife — kein sleep,
kein zweiter Thread-Pfad. Läuft im Test-Regime als EIGENER pytest-Aufruf
in der UI-Schleife (Segfault-Regel)."""

from __future__ import annotations

import os
import sys
import time
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


# 1x1-PNG (Standard-Bytes) — reicht dem Betrachter.
_PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00"
        b"\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx"
        b"\x9cc\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01\x87\xa1N\xe8\x00"
        b"\x00\x00\x00IEND\xaeB`\x82")


def _lauf(base, run_id, pngs=(), gueltig=True, inhalt="# Bericht\nZeile 2"):
    d = Path(base) / run_id
    d.mkdir(parents=True)
    (d / "report.md").write_text(inhalt, encoding="utf-8")
    if gueltig:
        (d / "metrics.json").write_text("{}", encoding="utf-8")
    for name in pngs:
        (d / name).write_bytes(_PNG)
    return d


def test_historie_gueltig_und_ungueltig(qapp, tmp_path):
    from docodetect.ui_qt.admin.pages.analysis_page import LaufTab
    cfg = _cfg(tmp_path)
    _lauf(cfg["analysis"]["output_dir"], "lauf-a", pngs=("b.png", "a.png"))
    _lauf(cfg["analysis"]["output_dir"], "kaputt", gueltig=False)
    (Path(cfg["analysis"]["output_dir"]) / "leer").mkdir()
    tab = LaufTab(cfg)
    w = tab.werte()
    assert w["historie"] == ["lauf-a"]
    assert "ungültig, 2 Stück" in w["ungueltig"]


def test_historie_leerzustand(qapp, tmp_path):
    from docodetect.ui_qt.admin.pages.analysis_page import LaufTab
    tab = LaufTab(_cfg(tmp_path))
    w = tab.werte()
    assert w["historie"] == []
    assert w["ungueltig"] == ""
    assert "Noch keine Analyse-Läufe" in w["status"]


def test_betrachter_zeigt_report_und_blaettert(qapp, tmp_path):
    from docodetect.ui_qt.admin.pages.analysis_page import LaufTab
    cfg = _cfg(tmp_path)
    _lauf(cfg["analysis"]["output_dir"], "lauf-a", pngs=("b.png", "a.png"))
    tab = LaufTab(cfg)
    tab.historie.setCurrentRow(0)
    w = tab.werte()
    assert w["report_erste_zeile"] == "# Bericht"
    assert w["png"] == "a.png"            # alphabetisch, erstes zuerst
    tab.blaettern(1)
    assert tab.werte()["png"] == "b.png"
    tab.blaettern(1)                       # klemmt am Ende, kein Wrap
    assert tab.werte()["png"] == "b.png"
    tab.blaettern(-1)
    assert tab.werte()["png"] == "a.png"


def test_lauf_im_worker_aktualisiert_historie(qapp, tmp_path, monkeypatch):
    from docodetect.ui_qt.admin.pages import analysis_page as mod
    cfg = _cfg(tmp_path)

    def fake_run(cfg_, reports_dir=None, run_id=None):
        return _lauf(cfg_["analysis"]["output_dir"], run_id or "neu",
                     pngs=("x.png",))

    monkeypatch.setattr(mod, "run_report_analysis", fake_run)
    tab = mod.LaufTab(cfg)
    tab.run_id_feld.setText("wlauf")
    tab.starte_lauf()
    assert not tab.start_button.isEnabled()      # seriell: gesperrt
    ende = time.monotonic() + 10.0
    while tab._worker is not None and time.monotonic() < ende:
        qapp.processEvents()
    assert tab._worker is None, "Worker nicht fertig geworden"
    w = tab.werte()
    assert "wlauf" in w["status"]
    assert w["historie"] == ["wlauf"]
    assert tab.start_button.isEnabled()


def test_lauf_fehler_zeigt_text_statt_crash(qapp, tmp_path):
    from docodetect.ui_qt.admin.pages.analysis_page import LaufTab
    tab = LaufTab(_cfg(tmp_path))
    tab._lauf_fehler("kein Plattenplatz")
    w = tab.werte()
    assert "Analyse-Lauf fehlgeschlagen" in w["status"]
    assert "kein Plattenplatz" in w["status"]
    assert tab.start_button.isEnabled()
