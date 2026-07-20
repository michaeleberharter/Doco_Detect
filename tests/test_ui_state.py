"""Zustandsmaschine des Hauptfensters (PLAN 6.4) – pure Logik, kein Qt.

NO_CAMERA / NOT_READY / READY / BUSY: compute_state() ist eine reine
Funktion über (Kamera da?, Einrichtung fertig?, Pipeline läuft?), damit die
Übergänge ohne GUI testbar sind. Die Widget-Wirkung (Buttons an/aus) prüft
test_ui_qt_smoke.py.

Zusätzlich (Task 5): die Ergebnis-Zustände des MainWindow (accept/ambiguous/
reject als Headline + Kartenbild) – die einzigen Tests hier, die Qt
brauchen; die `qapp`-Fixture überspringt sauber, falls PySide6 fehlt, ohne
die Tests oben (pure Logik) zu berühren.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.ui_qt.state import UiState, compute_state  # noqa: E402


def test_no_camera_wins_over_not_ready():
    assert compute_state(camera_ok=False, ready=False, busy=False) is UiState.NO_CAMERA


def test_not_ready_when_setup_missing():
    assert compute_state(camera_ok=True, ready=False, busy=False) is UiState.NOT_READY


def test_ready_in_normal_operation():
    assert compute_state(camera_ok=True, ready=True, busy=False) is UiState.READY


def test_busy_while_pipeline_runs():
    assert compute_state(camera_ok=True, ready=True, busy=True) is UiState.BUSY


def test_busy_survives_camera_loss():
    """Kamera stirbt WÄHREND einer Aktion: die laufende Aktion bleibt BUSY,
    erst nach deren Ende wird NO_CAMERA sichtbar (Neuberechnung im Handler)."""
    assert compute_state(camera_ok=False, ready=True, busy=True) is UiState.BUSY
    assert compute_state(camera_ok=False, ready=True, busy=False) is UiState.NO_CAMERA


# ---------- Ergebnis-Darstellung (_show_report): accept/ambiguous/reject ----------

def make_cfg(tmp_path):
    """Minimal-Config für ein Demo-MainWindow (keine echte Kamera nötig)."""
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


@pytest.fixture(scope="module")
def qapp():
    """Wie test_ui_qt_smoke.py: offscreen, PySide6 optional."""
    import os

    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from docodetect.ui_qt.app import make_app
    return make_app()


@pytest.fixture
def main_window_factory(qapp, tmp_path):
    """MainWindow im Demo-Modus (keine Kamera-Hardware nötig) für Tests der
    Ergebnis-Darstellung."""
    def factory():
        from docodetect.ui_qt.main_window import MainWindow
        return MainWindow(make_cfg(tmp_path), demo=True)
    return factory


def make_report(decision: str, n_candidates: int = 0, measured: dict | None = None):
    """MatchReport ohne echten Pipeline-Lauf – genug für _show_report()."""
    from docodetect.matcher import CandidateReport, MatchReport

    candidates = [
        CandidateReport(
            article_number=f"ART-{i}", name=f"Artikel {i}",
            nominal_size_mm=180.0, height_mm=20.0,
            corrected_diameter_mm=180.0, geometry_error_mm=1.0,
            has_references=True, n_shots=5,
            posterior=max(0.9 - i * 0.25, 0.05), log_score=-0.1 * i, max_abs_z=0.5)
        for i in range(n_candidates)
    ]
    return MatchReport(decision=decision, message="Testreport",
                       candidates=candidates, measured=measured or {})


def test_show_report_headline_and_rank_lines(qapp, main_window_factory):
    """accept: Headline 'Automatisch übernommen' + Siegerkarte + kompakte
    Plätze 2-3; ambiguous: 'Bitte bestätigen' + Keiner-davon-Button;
    reject: 'Kein Treffer' + Rohmesswert-Diagnose."""
    win = main_window_factory()
    rep = make_report(decision="accept", n_candidates=3)
    win._show_report(rep)
    assert "Automatisch übernommen" in win.headline_text()
    assert win.rank_lines_count() == 2                     # Plätze 2 und 3

    rep2 = make_report(decision="ambiguous", n_candidates=2)
    win._show_report(rep2)
    assert "Bitte bestätigen" in win.headline_text()
    assert win.none_of_these_button() is not None

    rep3 = make_report(decision="reject", n_candidates=0,
                       measured={"circle_diameter_mm": 123.4,
                                 "circularity": 0.91, "area_mm2": 11958.0})
    win._show_report(rep3)
    assert "Kein Treffer" in win.headline_text()
    assert "123,4" in win.diagnose_text()
