"""Tests für Verlauf, Tastaturwege und Leerzustände (Phase 5 des
UI-Redesigns).

Run: pytest tests/test_ui_history.py -v
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from docodetect.matcher import CandidateReport, MatchReport  # noqa: E402
from docodetect.ui_qt import theme as theme_mod  # noqa: E402
from docodetect.ui_qt.app import apply_theme, make_app  # noqa: E402


@pytest.fixture
def qapp():
    app = make_app()
    yield app
    apply_theme(app, theme_mod.DEFAULT_THEME)


def make_cfg(tmp_path):
    return {
        "camera": {"width": 1920, "height": 1080},
        "calibration": {
            "file": str(tmp_path / "calibration.json"),
            "background_file": str(tmp_path / "background.png"),
            "aruco_dict": "DICT_4X4_50", "marker_id": 0, "marker_size_mm": 72.5,
        },
        "geometry": {"camera_height_mm": 300.0},
        "matching": {"diameter_tolerance_mm": 6.0, "top_k": 3},
        "paths": {"db_file": str(tmp_path / "db.sqlite3")},
        "ui": {"preview_fps": 5, "confirm_sound": False},
        "stage2": {"enabled": False},
    }


@pytest.fixture
def win(qapp, tmp_path):
    from docodetect.ui_qt.main_window import MainWindow
    w = MainWindow(make_cfg(tmp_path))
    yield w
    w.close()


def cand(nr="ART-1", name="Teller 18", posterior=0.92):
    return CandidateReport(
        article_number=nr, name=name, nominal_size_mm=180.0, height_mm=0.0,
        corrected_diameter_mm=181.0, geometry_error_mm=1.0,
        has_references=True, n_shots=5, posterior=posterior,
        log_score=-0.1, max_abs_z=0.5)


def report(decision, candidates=(), touches=False, measured=None):
    return MatchReport(decision=decision, message="Testreport",
                       candidates=list(candidates), touches_border=touches,
                       measured=measured or {})


# ---------- Verlauf ----------

def test_verlauf_sammelt_die_identifikationen_neueste_oben(win):
    win._show_report(report("accept", [cand(name="Teller 18")]))
    win._show_report(report("accept", [cand(name="Teller 20")]))
    assert win.history.count() == 2
    assert "Teller 20" in win.history.texts()[0], "neueste gehört nach oben"
    assert "Teller 18" in win.history.texts()[1]


def test_verlauf_faerbt_nach_zustand(win):
    from docodetect.ui_qt.widgets.history import entry_from_report

    for decision, touches, tone in (("accept", False, "accept"),
                                    ("ambiguous", False, "ambiguous"),
                                    ("reject", False, "reject"),
                                    ("reject", True, "border")):
        rep = report(decision, [cand()] if decision != "reject" else [],
                     touches=touches)
        assert entry_from_report(rep, tone).tone == tone


def test_verlauf_ohne_kandidat_nennt_den_zustand(win):
    from docodetect.ui_qt.widgets.history import entry_from_report

    assert entry_from_report(report("reject"), "reject").name == "Kein Treffer"
    assert "Bildrand" in entry_from_report(
        report("reject", touches=True), "border").name


def test_leeren_raeumt_nur_die_anzeige(win, tmp_path):
    """„Leeren" darf keine Messdaten vernichten: die dauerhafte Spur sind die
    Report-JSONs, der Verlauf ist nur die Sitzungsansicht."""
    captures = tmp_path / "caps"
    captures.mkdir()
    (captures / "r.json").write_text("{}", encoding="utf-8")

    win._show_report(report("accept", [cand()]))
    assert win.history.count() == 1
    win.history_clear.click()
    assert win.history.count() == 0
    assert (captures / "r.json").exists(), "Report-JSON wurde angefasst"


def test_verlauf_zeigt_leerhinweis_und_wieder_zeilen(win):
    assert win.history.count() == 0
    win._show_report(report("accept", [cand()]))
    assert win.history.count() == 1
    win.history.clear()
    assert win.history.count() == 0


# ---------- Tastatur ----------

def test_leertaste_und_eingabetaste_identifizieren(win):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeySequence

    shortcuts = {a.shortcut().toString() for a in win.actions()}
    for key in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
        assert QKeySequence(key).toString() in shortcuts


def test_ziffern_waehlen_kandidaten_nur_bei_ambiguous(win, tmp_path):
    """1..n bestätigen bei AMBIGUOUS den Kandidaten dieses Rangs – an der
    Box wird oft blind bedient. In anderen Zuständen passiert nichts."""
    import json

    rep = report("ambiguous", [cand("ART-1", "Teller 18", 0.5),
                               cand("ART-2", "Teller 20", 0.4)])
    p = tmp_path / "r.json"
    p.write_text(rep.to_json(), encoding="utf-8")
    rep.report_path = str(p)

    win._show_report(rep)
    win._choose_candidate_by_rank(2)
    saved = json.loads(p.read_text(encoding="utf-8"))
    assert saved["label"] == "ART-2"
    assert saved["verdict"] == "wrong"     # Platz 2 gewaehlt = Top-1 war falsch

    # Rang ausserhalb der Liste ändert nichts
    win._choose_candidate_by_rank(9)
    assert json.loads(p.read_text(encoding="utf-8"))["label"] == "ART-2"


def test_ziffern_wirken_nicht_bei_accept(win, tmp_path):
    import json

    rep = report("accept", [cand("ART-1")])
    p = tmp_path / "r.json"
    p.write_text(rep.to_json(), encoding="utf-8")
    rep.report_path = str(p)

    win._show_report(rep)
    win._choose_candidate_by_rank(1)
    assert json.loads(p.read_text(encoding="utf-8"))["verdict"] is None


# ---------- Leerzustände ----------

def test_einrichtungs_leerzustand_fuehrt_durch_die_schritte(qapp, tmp_path):
    from docodetect.ui_qt.main_window import MainWindow
    from docodetect.ui_qt.state import UiState

    win = MainWindow(make_cfg(tmp_path), demo=True)
    assert win.state is UiState.NOT_READY
    assert "Einrichtung nötig" in win.headline_text()
    assert "[offen]" in win.result_area.text()
    win.close()


def test_leerzustand_ueberschreibt_kein_vorhandenes_ergebnis(win):
    """Ein Kameraabriss nach einer Identifikation darf deren Anzeige nicht
    wegräumen – der Bediener will das Ergebnis noch lesen."""
    from docodetect.ui_qt.state import UiState

    win._show_report(report("accept", [cand()]))
    before = win.headline_text()
    win.set_state(UiState.NO_CAMERA)
    assert win.headline_text() == before
