"""Gemeinsame Test-Absicherung: der Testlauf fasst NIE echte Hardware an.

Hintergrund (2026-07-20): `test_camera_worker_without_camera_goes_no_camera`
öffnete mit Index 99 ein echtes `cv2.VideoCapture`. Auch ein nicht
existierender Index lässt AVFoundation die Geräte enumerieren – macOS zeigt
dann den Kamera-Berechtigungsdialog, und unter Index 0 hinge auf dem Mac die
FaceTime-Kamera statt der UGREEN in der Box.

Zwei Mechanismen:

1. `block_real_camera` (autouse): sperrt jeden Kamerazugriff. `BoxCamera.open`
   meldet sauber `CameraError` – exakt der Pfad, den die UI ohnehin behandelt
   – und `cv2.VideoCapture` ist zusätzlich als Stolperdraht verlegt, damit
   auch künftiger Code nicht versehentlich am Fixture vorbei ein Gerät
   öffnet.
2. Marker `hardware`: Tests, die zwingend eine angeschlossene Kamera
   brauchen, werden standardmäßig übersprungen und laufen nur mit
   DOCODETECT_HW_TESTS=1 (dann greift auch die Sperre aus 1 nicht).

Die Golden-/Regressionssuite (tests/test_real_captures.py) arbeitet
ausschließlich auf gespeicherten Bildern und ist von beidem unberührt.
"""

import os

import pytest

HW_ENV = "DOCODETECT_HW_TESTS"
CORPUS_REPRO_ENV = "DOCODETECT_CORPUS_REPRO"


def hardware_tests_enabled() -> bool:
    return os.environ.get(HW_ENV, "").strip() == "1"


def corpus_repro_enabled() -> bool:
    return os.environ.get(CORPUS_REPRO_ENV, "").strip() == "1"


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        f"hardware: braucht eine echte, angeschlossene Kamera – "
        f"übersprungen, solange {HW_ENV}=1 nicht gesetzt ist")
    config.addinivalue_line(
        "markers",
        "corpus: voller Lauf gegen den Regressions-Korpus – "
        "uebersprungen, solange paths.corpus_dir lokal fehlt")
    config.addinivalue_line(
        "markers",
        "corpus_smoke: festes 20-Bilder-Subset des Korpus fuer den Alltag")
    config.addinivalue_line(
        "markers",
        f"corpus_repro: volle Korpus-Reproduktion (tier1/tier2, ~550 s) — "
        f"per Default deselektiert, weil das Merge-Gate corpus-run --tier "
        f"1/2 --check strikt mehr prueft (Nachweis 2026-08-11). "
        f"Zurueckholen: {CORPUS_REPRO_ENV}=1")


def pytest_collection_modifyitems(config, items):
    # Korpus-Entdopplung (2026-08-11): die beiden teuren Reproduktionstests
    # laufen per Default NICHT mit — das Merge-Gate ist corpus-run --tier 1
    # --check UND --tier 2 --check, und das prueft strikt mehr (Drift,
    # Baseline-Quoten, Vollstaendigkeit). Echte Deselektion statt Skip,
    # damit die Zaehlung („2 deselected") in jeder Summary steht; die
    # Klartext-Zeile dazu druckt pytest_terminal_summary IMMER.
    if not corpus_repro_enabled():
        weg = [i for i in items if "corpus_repro" in i.keywords]
        if weg:
            items[:] = [i for i in items if "corpus_repro" not in i.keywords]
            config.hook.pytest_deselected(items=weg)
            config._corpus_repro_deselektiert = [i.nodeid for i in weg]
    if hardware_tests_enabled():
        return
    skip_hw = pytest.mark.skip(
        reason=f"Hardware-Test – nur mit {HW_ENV}=1 (echte Kamera nötig)")
    for item in items:
        if "hardware" in item.keywords:
            item.add_marker(skip_hw)


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Sichtbarkeit des corpus_repro-Deselects: IMMER eine Klartext-Zeile,
    auch bei gruenem Lauf und ohne -rs. Entfaellt nur, wenn die
    Korpus-Tests gar nicht kollektiert wurden (Auswahl-Lauf einzelner
    Module) — dann gab es nichts zu deselektieren."""
    weg = getattr(config, "_corpus_repro_deselektiert", None)
    if weg:
        terminalreporter.write_line(
            f"[korpus] Reproduktionstests tier1/tier2 (~550 s) nicht "
            f"gelaufen ({len(weg)} deselektiert) — Merge-Gate ist "
            f"corpus-run --tier 1 --check UND --tier 2 --check; "
            f"zurueckholen: {CORPUS_REPRO_ENV}=1")


@pytest.fixture(autouse=True)
def block_real_camera(request, monkeypatch):
    """Kein Test öffnet ein echtes Aufnahmegerät (siehe Modul-Docstring)."""
    if hardware_tests_enabled() or "hardware" in request.keywords:
        return

    import cv2

    from docodetect.camera import BoxCamera, CameraError

    def _blocked_open(self):
        raise CameraError(
            "Testlauf ohne Hardware: Kamera-Zugriff ist gesperrt "
            f"(nur mit {HW_ENV}=1). Siehe tests/conftest.py.")

    def _tripwire(*args, **kwargs):
        raise AssertionError(
            "Ein Test wollte cv2.VideoCapture öffnen. Im Testlauf ist das "
            f"gesperrt (macOS-Berechtigungsdialog!). Test mit "
            f"@pytest.mark.hardware markieren oder {HW_ENV}=1 setzen.")

    monkeypatch.setattr(BoxCamera, "open", _blocked_open)
    monkeypatch.setattr(cv2, "VideoCapture", _tripwire)
