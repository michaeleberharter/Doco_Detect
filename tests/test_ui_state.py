"""Zustandsmaschine des Hauptfensters (PLAN 6.4) – pure Logik, kein Qt.

NO_CAMERA / NOT_READY / READY / BUSY: compute_state() ist eine reine
Funktion über (Kamera da?, Einrichtung fertig?, Pipeline läuft?), damit die
Übergänge ohne GUI testbar sind. Die Widget-Wirkung (Buttons an/aus) prüft
test_ui_qt_smoke.py.
"""

import sys
from pathlib import Path

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
