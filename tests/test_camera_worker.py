"""CameraWorker: zwei Robustheitsluecken – Schritt 6.

Design: docs/superpowers/specs/2026-08-05-crashsichere-einlern-session-design.md
Abschnitt 6.

BEIDE Befunde firmieren als ROBUSTHEITSVERBESSERUNG, nicht als Behebung des
Absturzes vom 2026-08-01. Die Aktenlage verortet jenen "beim Speichern des
Enrollments", also im PipelineWorker mit _job_save — beim Speichern laeuft
weder eine Kamera-Oeffnung noch der Grab-Loop. Diese Tests belegen also nichts
ueber jenen Absturz.

Gemeinsames Symptom beider Befunde im Einlerndialog: "Aufnehmen haengt ohne
Meldung". Deshalb EIN Paket und derselbe Testansatz — eine Kamera-Attrappe,
die nie liefert.

Ohne QApplication, ohne Event-Loop, ohne gestarteten Thread: `run()` und
`_grab_loop()` sind gewoehnliche Methoden und werden direkt aufgerufen. Damit
beruehren diese Tests die bekannte Qt-Segfault-Flaeche gar nicht.
"""

import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

pytest.importorskip("PySide6", reason="Qt-UI optional (requirements-ui-qt.txt)")

from docodetect.camera import CameraError  # noqa: E402
from docodetect.ui_qt import camera_worker as cw  # noqa: E402


def _cfg():
    return {"camera": {"index": 0, "width": 640, "height": 480},
            "ui": {"preview_fps": 15, "preview_max_width": 320}}


class _Signale:
    """Signale abfangen, ohne Qt zu starten. Die Instanzattribute
    ueberschatten die Klassen-Signals – der Worker ruft nur .emit()."""

    def __init__(self):
        self.gesendet = []

    def emit(self, *a):
        self.gesendet.append(a)


def _worker(monkeypatch):
    """CameraWorker ohne QObject-Konstruktion: __init__ von Hand ausfuehren,
    Signale durch Attrappen ersetzen. So braucht der Test keine QApplication."""
    w = cw.CameraWorker.__new__(cw.CameraWorker)
    w.cfg = _cfg()
    w.ui = cw.ui_cfg(w.cfg)
    w.camera_ok = False
    w._stop_event = threading.Event()
    w._want_full = threading.Event()
    w._announced_error = False
    for name in ("frame_ready", "full_frame_ready", "camera_error",
                 "camera_connected", "focus_warning", "fps_update"):
        setattr(w, name, _Signale())
    return w


class _Cap:
    """VideoCapture-Attrappe. grab_ok/retrieve_ok steuern die beiden Pfade
    getrennt – genau die Trennung, um die es in Befund 3 geht.

    Der Abbruch haengt bewusst an grab(): das ist die EINZIGE Stelle, die in
    jeder Runde durchlaufen wird. Ein Stopper am Emissionspfad greift nicht,
    wenn Frames verworfen werden (FPS-Takt) oder _want_full nach einem
    erfolgreichen Retrieve geloescht ist – beides ist Normalbetrieb."""

    def __init__(self, grab_ok=True, retrieve_ok=True, max_runden=500,
                 worker=None, stop_nach=None, want_full_halten=False):
        self.grab_ok, self.retrieve_ok = grab_ok, retrieve_ok
        self.grabs = self.retrieves = 0
        self.max_runden = max_runden
        self.worker, self.stop_nach = worker, stop_nach
        self.want_full_halten = want_full_halten

    def grab(self):
        self.grabs += 1
        if self.grabs > self.max_runden:
            raise AssertionError("Endlosschleife: der Loop endete nie")
        if self.worker is not None:
            if self.want_full_halten:
                self.worker._want_full.set()   # Retrieve in jeder Runde erzwingen
            if self.stop_nach is not None and self.grabs >= self.stop_nach:
                self.worker._stop_event.set()
        return self.grab_ok

    def retrieve(self):
        self.retrieves += 1
        if not self.retrieve_ok:
            return False, None
        import numpy as np
        return True, np.zeros((8, 8, 3), dtype=np.uint8)


class _Cam:
    def __init__(self, cap):
        self.capture_device = cap


# ---------- Befund 3: Retrieve-Fehler erreichen die Schwelle nie ----------

def test_kamera_die_greift_aber_nichts_liefert_meldet_verbindungsverlust(monkeypatch):
    """Der Kern von Befund 3. Vorher wurde jeder Retrieve-Fehler vom naechsten
    erfolgreichen grab() geloescht – _MAX_GRAB_FAILS war auf diesem Pfad
    unerreichbar, und die Vorschau fror lautlos ein."""
    w = _worker(monkeypatch)
    cap = _Cap(grab_ok=True, retrieve_ok=False)
    w._want_full.set()          # erzwingt retrieve unabhaengig vom FPS-Takt

    w._grab_loop(_Cam(cap))

    assert cap.retrieves >= cw._MAX_GRAB_FAILS, "der Retrieve-Pfad zaehlt mit"
    assert w.camera_error.gesendet, "es wird gemeldet statt still zu haengen"
    assert "Verbindung verloren" in w.camera_error.gesendet[0][0]
    assert w.camera_ok is False


def test_grab_fehler_meldet_weiterhin(monkeypatch):
    """Der bereits vorher funktionierende Pfad darf nicht kippen."""
    w = _worker(monkeypatch)
    cap = _Cap(grab_ok=False)
    w._grab_loop(_Cam(cap))
    assert cap.grabs >= cw._MAX_GRAB_FAILS
    assert "Verbindung verloren" in w.camera_error.gesendet[0][0]


def test_verworfene_frames_erhoehen_den_retrieve_zaehler_nicht(monkeypatch):
    """Ohne want_full und innerhalb des FPS-Intervalls wird bewusst nur
    gegrabbt. Das ist NORMALBETRIEB und darf den Retrieve-Zaehler nicht
    beruehren – genau dafuer gibt es zwei Zaehler statt einem."""
    w = _worker(monkeypatch)
    cap = _Cap(grab_ok=True, retrieve_ok=True, max_runden=60,
               worker=w, stop_nach=50)
    monkeypatch.setattr(cw, "bgr_to_qimage", lambda img: img)
    monkeypatch.setattr(cw, "downscale_width", lambda img, w_: img)

    w._grab_loop(_Cam(cap))
    assert cap.grabs >= 50
    assert cap.retrieves < cap.grabs, "die meisten Frames wurden verworfen"
    assert w.camera_error.gesendet == [], "Verwerfen ist kein Fehler"


def test_ein_erfolgreicher_retrieve_setzt_den_zaehler_zurueck(monkeypatch):
    """Neun Fehlschlaege, dann Erfolg, dann wieder Fehlschlaege: die Schwelle
    darf nicht ueber getrennte Stoerungen hinweg aufaddieren."""
    w = _worker(monkeypatch)

    class _Wechsel(_Cap):
        def retrieve(self):
            self.retrieves += 1
            if self.retrieves == cw._MAX_GRAB_FAILS - 1:   # genau einmal Erfolg
                import numpy as np
                return True, np.zeros((8, 8, 3), dtype=np.uint8)
            return False, None

    # want_full_halten: nach einem erfolgreichen Retrieve loescht der Worker
    # das Flag – ohne Nachsetzen wuerde danach nur noch gegrabbt.
    cap = _Wechsel(grab_ok=True, worker=w, want_full_halten=True,
                   max_runden=200)
    monkeypatch.setattr(cw, "bgr_to_qimage", lambda img: img)
    monkeypatch.setattr(cw, "downscale_width", lambda img, w_: img)
    w._grab_loop(_Cam(cap))

    # Ohne Ruecksetzen haette die Schwelle schon bei _MAX_GRAB_FAILS Retrieves
    # gegriffen; der eine Erfolg dazwischen verschiebt sie um genau so viele
    # Runden, wie vor ihm gescheitert sind.
    assert cap.retrieves > cw._MAX_GRAB_FAILS, \
        "nach dem Erfolg wurde neu gezaehlt, nicht weiteraddiert"
    assert w.camera_error.gesendet, "am Ende wird trotzdem gemeldet"


# ---------- Befund 2: nicht-CameraError verlaesst QThread.run() ----------

def test_fehlender_config_key_meldet_und_beendet_den_thread(monkeypatch):
    """Vorher verliess der KeyError run(): Thread tot, KEIN Signal, camera_ok
    dauerhaft False, und stop() wartete spaeter 8 s auf einen toten Thread.

    load_config prueft nur die Existenz von SEKTIONEN, nicht einzelner Keys –
    eine camera:-Sektion ohne index laedt sauber und faellt erst hier auf."""
    w = _worker(monkeypatch)

    class _Boom:
        def __init__(self, cfg):
            pass

        def open(self):
            raise KeyError("index")

    monkeypatch.setattr(cw, "BoxCamera", _Boom)
    w.run()                                   # darf NICHT werfen

    assert w.camera_error.gesendet, "der Fehler wird gemeldet"
    text = w.camera_error.gesendet[0][0]
    assert "KeyError" in text, "der Typ steht in der Meldung"
    assert "Konfiguration" in text
    assert "kein Verbindungsproblem" in text
    assert w.camera_ok is False


def test_nicht_transientes_wird_NICHT_alle_drei_sekunden_wiederholt(monkeypatch):
    """Ein fehlender Config-Key repariert sich nicht von selbst. Alle drei
    Sekunden erneut daran zu scheitern erzeugte nur eine Endlosschleife hinter
    einer stummen Oberflaeche."""
    w = _worker(monkeypatch)
    versuche = {"n": 0}

    class _Boom:
        def __init__(self, cfg):
            versuche["n"] += 1

        def open(self):
            raise ValueError("kaputte Konfiguration")

    monkeypatch.setattr(cw, "BoxCamera", _Boom)
    w.run()
    assert versuche["n"] == 1, "genau ein Versuch, kein Reconnect-Takt"
    assert len(w.camera_error.gesendet) == 1


def test_cameraerror_bleibt_transient_und_wird_wiederholt(monkeypatch):
    """Die Unterscheidung ist der eigentliche Inhalt: ein abgezogenes
    USB-Kabel IST voruebergehend und rechtfertigt den 3-s-Takt."""
    w = _worker(monkeypatch)
    versuche = {"n": 0}

    class _Weg:
        def __init__(self, cfg):
            versuche["n"] += 1

        def open(self):
            if versuche["n"] >= 3:
                w._stop_event.set()           # Schleife beenden
            raise CameraError("Cannot open camera index 0.")

    monkeypatch.setattr(cw, "BoxCamera", _Weg)
    monkeypatch.setattr(cw, "_RECONNECT_SECS", 0.0)   # kein echtes Warten
    w.run()
    assert versuche["n"] >= 2, "es wird erneut versucht"
    assert len(w.camera_error.gesendet) == 1, \
        "aber nur EINMAL gemeldet (kein Spam bei jedem Versuch)"
