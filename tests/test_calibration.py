"""Archivierung statt Ueberschreiben beim Schreiben von Kalibrier-Artefakten.

Der dritte Ueberschreiben-statt-Verschieben-Vorfall (LOEFFEL-14) hat eine
Messreihe korpus-unfaehig gemacht. save_background/run_calibration muessen
den bestehenden Stand mit Zeitstempel wegsichern, bevor sie neu schreiben.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect import calibration
from docodetect.calibration import _archiviere_vorhandene, save_background


def test_archiviert_nichts_wenn_die_datei_fehlt(tmp_path):
    assert _archiviere_vorhandene(tmp_path / "gibtsnicht.png") is None


def test_archiviert_bestehende_datei_mit_zeitstempel(tmp_path):
    p = tmp_path / "background.png"
    p.write_bytes(b"alt")
    ziel = _archiviere_vorhandene(p)
    assert ziel is not None
    assert not p.exists()                      # verschoben, nicht kopiert
    assert ziel.read_bytes() == b"alt"
    assert ziel.name.startswith("background-") and ziel.suffix == ".png"


def test_kollision_in_derselben_sekunde_verliert_nichts(tmp_path, monkeypatch):
    """Zwei Sicherungen in derselben Sekunde duerfen sich nicht gegenseitig
    ueberschreiben — sonst waere die Archivierung selbst der Datenverlust."""
    monkeypatch.setattr(calibration.time, "strftime", lambda *a: "20260101-000000")
    p = tmp_path / "background.png"
    p.write_bytes(b"erste")
    erst = _archiviere_vorhandene(p)
    p.write_bytes(b"zweite")
    zweit = _archiviere_vorhandene(p)
    assert erst != zweit
    assert erst.read_bytes() == b"erste"
    assert zweit.read_bytes() == b"zweite"


def test_save_background_sichert_den_alten_stand(tmp_path):
    ziel = tmp_path / "background.png"
    cfg = {"calibration": {"background_file": str(ziel)}}

    alt = np.zeros((8, 8, 3), np.uint8)
    save_background(alt, cfg)
    assert ziel.exists()

    neu = np.full((8, 8, 3), 255, np.uint8)
    save_background(neu, cfg)
    # Der neue Hintergrund steht am festen Pfad ...
    import cv2
    assert int(cv2.imread(str(ziel)).mean()) == 255
    # ... und der alte liegt unter einem Zeitstempel-Namen daneben.
    archive = [p for p in tmp_path.glob("background-*.png")]
    assert len(archive) == 1
    assert int(cv2.imread(str(archive[0])).mean()) == 0
