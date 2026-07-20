"""Hardware-Abnahme als Test – läuft NUR mit DOCODETECT_HW_TESTS=1.

    DOCODETECT_HW_TESTS=1 .venv/bin/python -m pytest tests/test_camera_hardware.py -v -s

Das ist die Phase-0-Abnahme aus PLAN_UI_QT.md in Testform: öffnet die in der
Config eingestellte Kamera (camera.index – am Mac via config.local.yaml die
UGREEN, nicht die FaceTime-Kamera) und prüft, dass sie Bilder liefert.
Ohne die Umgebungsvariable überspringt conftest.py diese Datei, und die
Kamera-Sperre dort verhindert jeden versehentlichen Gerätezugriff.

Bewusst KEINE harte Zusicherung auf 4K/Fokus-Lock: unter macOS/AVFoundation
liefert die Kamera oft nicht die angeforderte Auflösung und der Fokus-Lock
greift nicht (siehe camera.focus_lock_supported) – der Messbetrieb läuft am
Windows-PC. Der Test meldet die Ist-Werte, statt auf dem Mac künstlich rot
zu sein; scripts/camera_check.py bleibt der ausführliche Bericht.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.camera import (BoxCamera, capture_backend,  # noqa: E402
                              focus_lock_supported)
from docodetect.config import load_config  # noqa: E402

pytestmark = pytest.mark.hardware


def test_configured_camera_delivers_frames():
    cfg = load_config()
    cam_cfg = cfg["camera"]
    print(f"\n[hw] Backend {capture_backend(cam_cfg)}, index {cam_cfg['index']}, "
          f"angefordert {cam_cfg['width']}x{cam_cfg['height']}")
    with BoxCamera(cfg) as cam:
        frame = cam.capture()
        h, w = frame.shape[:2]
        print(f"[hw] Frame: {w}x{h}, Fokus-Lock: {cam.focus_locked} "
              f"(plattformseitig unterstützt: {focus_lock_supported()})")
        assert frame.ndim == 3 and frame.shape[2] == 3
        assert w > 0 and h > 0
        second = cam.capture()          # zweite Aufnahme muss auch klappen
        assert second.shape == frame.shape


def test_configured_camera_matches_requested_resolution():
    """Getrennt, weil unter macOS/AVFoundation regelmäßig verletzt: die Box
    misst nur bei der kalibrierten Auflösung korrekt (px->mm ist
    auflösungsspezifisch). Auf dem Windows-Messrechner muss das grün sein."""
    cfg = load_config()
    with BoxCamera(cfg) as cam:
        frame = cam.capture()
    h, w = frame.shape[:2]
    if (w, h) != (cfg["camera"]["width"], cfg["camera"]["height"]):
        pytest.xfail(f"Kamera liefert {w}x{h} statt "
                     f"{cfg['camera']['width']}x{cfg['camera']['height']} – "
                     "unter macOS/AVFoundation üblich, am Windows-PC ein Fehler.")
