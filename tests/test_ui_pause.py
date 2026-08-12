"""Tests der Vorschau-Pause (MainWindow, 2026-08-12) — inklusive der
MESSPFAD-AUFLAGE aus der Freigabe:

    „Pause aktiv, Auslösung -> gemessener Frame ist nachweislich neuer
    als der letzte vor der Pause zugestellte."

Die FakeSource nummeriert ihre Frames durch; jeder emittierte Frame
(Vorschau wie Voll-Frame) trägt eine streng steigende Nummer — genau wie
die echte Grab-Schleife, die request_full_frame() immer mit dem NÄCHSTEN
frisch gegrabten Frame beantwortet und keinen Cache kennt
(camera_worker._grab_loop). Gegated wird ausschliesslich die Zustellung
an das Vorschau-Widget; der Kamera-Worker-Lebenszyklus wird nicht
angefasst (Auftrag; docs/ui-qt-testsuite-segfault.md).

Läuft im Test-Regime als EIGENER pytest-Aufruf.

Run: pytest tests/test_ui_pause.py -v
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import QObject, Signal  # noqa: E402

from docodetect.ui_qt import theme as theme_mod  # noqa: E402
from docodetect.ui_qt.app import apply_theme, make_app  # noqa: E402
from docodetect.ui_qt.main_window import _PAUSE_TEXT  # noqa: E402
from docodetect.ui_qt.state import UiState  # noqa: E402


@pytest.fixture
def qapp():
    app = make_app(theme="dark")            # Theme-Pinnung: nie "system"
    yield app
    apply_theme(app, theme_mod.DEFAULT_THEME)


def make_cfg(tmp_path):
    return {
        "camera": {"width": 1920, "height": 1080},
        "calibration": {
            "file": str(tmp_path / "calibration.json"),
            "background_file": str(tmp_path / "background.png"),
            "aruco_dict": "DICT_4X4_50", "marker_id": 0,
            "marker_size_mm": 72.5,
        },
        "geometry": {"camera_height_mm": 300.0},
        "matching": {"diameter_tolerance_mm": 6.0, "top_k": 3},
        "paths": {"db_file": str(tmp_path / "db.sqlite3")},
        "ui": {"preview_fps": 5, "confirm_sound": False},
        "stage2": {"enabled": False},
    }


class FakeSource(QObject):
    """Nummerierte Frames, CameraWorker-kompatible Signale/Slots. Signale
    als `object`, damit die Nummern statt QImages durchpassen — das
    Vorschau-Widget wird in den Tests durch einen Recorder ersetzt."""

    frame_ready = Signal(object)
    full_frame_ready = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.counter = 0
        self.camera_ok = True

    def start(self):
        pass

    def stop(self):
        pass

    def request_full_frame(self):
        # Wie die echte Grab-Schleife: der NÄCHSTE Frame, nie ein alter.
        self.counter += 1
        self.full_frame_ready.emit(self.counter)

    def emit_preview(self):
        self.counter += 1
        self.frame_ready.emit(self.counter)
        return self.counter


@pytest.fixture
def win(qapp, tmp_path):
    """MainWindow mit FakeSource statt (geblocktem) CameraWorker."""
    from docodetect.ui_qt.main_window import MainWindow

    w = MainWindow(make_cfg(tmp_path))
    if w.source is not None:
        w.source.stop()
    fake = FakeSource(w)
    w.source = fake
    w._connect_source(fake)
    # Zustand nachziehen: der geblockte CameraWorker hinterließ NO_CAMERA,
    # und bei NO_CAMERA pausiert _pause_aktivieren bewusst nicht (W3).
    w.update_state()
    assert w.state is not UiState.NO_CAMERA
    yield w
    w.close()


@pytest.fixture
def zugestellt(win, monkeypatch):
    """Recorder statt Vorschau-Widget: was kommt WIRKLICH an?"""
    frames = []
    monkeypatch.setattr(win.preview, "set_frame", frames.append)
    return frames


# ---------- Gate: nur die Zustellung ----------

def test_ohne_pause_werden_frames_zugestellt(win, zugestellt):
    win.source.emit_preview()
    win.source.emit_preview()
    assert zugestellt == [1, 2]


def test_pause_stoppt_die_zustellung_und_zeigt_die_meldung(win, zugestellt):
    win.source.emit_preview()
    win._pause_aktivieren()
    win.source.emit_preview()
    win.source.emit_preview()
    assert zugestellt == [1]                       # nichts mehr zugestellt
    assert win.preview._message == _PAUSE_TEXT


def test_pause_gated_den_messpfad_nicht(win, zugestellt):
    """full_frame_ready läuft auch pausiert ungefiltert — die Messung darf
    von der Anzeige-Pause nichts merken."""
    voll = []
    win.source.full_frame_ready.connect(voll.append)
    win._pause_aktivieren()
    win.source.request_full_frame()
    assert voll == [1]


# ---------- MESSPFAD-AUFLAGE: Frische-Nachweis ----------

def test_ausloesung_bei_pause_misst_nachweislich_frischen_frame(
        win, zugestellt, monkeypatch):
    """Pause aktiv, Auslösung: (1) die Pause wird VOR der Messung
    aufgehoben, (2) der gemessene Frame ist strikt neuer als der letzte
    vor der Pause zugestellte — nie ein gecachter alter."""
    gemessen = []
    monkeypatch.setattr(win, "_start_worker",
                        lambda job: gemessen.append(job.args[0]))

    letzter_vor_pause = win.source.emit_preview()   # id 1, zugestellt
    win._pause_aktivieren()
    win.source.emit_preview()                       # id 2, verworfen (Pause)
    assert zugestellt == [letzter_vor_pause]

    win.set_state(UiState.READY)
    win._start_capture_action("identify")           # Auslösung

    assert not win._preview_pausiert, "Auslösung muss die Pause aufheben"
    assert len(gemessen) == 1
    assert gemessen[0] > letzter_vor_pause, (
        "Gemessen wurde ein Frame, der nicht nachweislich frischer ist "
        f"als der letzte zugestellte ({gemessen[0]} <= {letzter_vor_pause})")
    # und zwar der NÄCHSTE der Quelle — kein zwischengespeicherter:
    assert gemessen[0] == win.source.counter


# ---------- Timer-/Filter-Lebenszyklus ----------

def test_default_null_installiert_keinen_filter(win):
    """Werksvorgabe 0 = nie: kein App-EventFilter, kein Timer — der
    Bestand (und jede andere Test-Datei) läuft unbeeinflusst."""
    assert int(win.ui["preview_pause_minutes"]) == 0
    assert not win._pause_filter_installiert
    assert not win._pause_timer.isActive()


def test_einstellung_schaltet_timer_und_filter(win):
    win.ui["preview_pause_minutes"] = 5
    win._pause_konfigurieren()
    assert win._pause_filter_installiert
    assert win._pause_timer.isActive()
    assert win._pause_timer.interval() == 5 * 60_000

    win.ui["preview_pause_minutes"] = 0
    win._pause_konfigurieren()
    assert not win._pause_filter_installiert
    assert not win._pause_timer.isActive()


def test_null_stellen_hebt_laufende_pause_auf(win, zugestellt):
    win.ui["preview_pause_minutes"] = 5
    win._pause_konfigurieren()
    win._pause_aktivieren()
    win.ui["preview_pause_minutes"] = 0
    win._pause_konfigurieren()
    assert not win._preview_pausiert
    win.source.emit_preview()
    assert zugestellt == [1]


def test_aktivitaet_hebt_pause_auf_und_startet_countdown_neu(win):
    win.ui["preview_pause_minutes"] = 5
    win._pause_konfigurieren()
    win._pause_aktivieren()
    win._aktivitaet()
    assert not win._preview_pausiert
    assert win._pause_timer.isActive()


def test_no_camera_pausiert_nicht_aber_countdown_lebt_weiter(win):
    """Review-Befund W3: läuft der Countdown während eines Kamera-Ausfalls
    ab, darf das Feature nicht dauerhaft sterben — der single-shot-Timer
    muss neu starten, sonst pausiert die Vorschau nach dem Reconnect nie
    mehr (und ohne Bediener kommt kein Event, das das heilt)."""
    win.ui["preview_pause_minutes"] = 5
    win._pause_konfigurieren()
    win.set_state(UiState.NO_CAMERA)
    win._pause_timer.stop()            # Countdown ist gerade abgelaufen
    win._pause_aktivieren()
    assert not win._preview_pausiert   # bei NO_CAMERA wird nicht pausiert
    assert win._pause_timer.isActive(), "Timer muss weiterlaufen (W3)"


def test_zustandswechsel_ueberschreibt_pausetext_nicht(win):
    """update_state (z.B. Kamera-Reconnect) darf eine stehende Pause nicht
    optisch aufheben, während das Gate weiter Frames verwirft."""
    win._pause_aktivieren()
    win.set_state(UiState.READY)
    assert win.preview._message == _PAUSE_TEXT


def test_close_entfernt_den_filter(qapp, tmp_path):
    from docodetect.ui_qt.main_window import MainWindow

    w = MainWindow(make_cfg(tmp_path))
    w.ui["preview_pause_minutes"] = 5
    w._pause_konfigurieren()
    assert w._pause_filter_installiert
    w.close()
    assert not w._pause_filter_installiert
