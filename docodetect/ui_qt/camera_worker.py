"""CameraWorker: der EINZIGE Kamera-Besitzer der App (PLAN §3).

QThread mit Grab-Schleife über die geteilte BoxCamera-Initialisierung
(4K, MJPG, Fokus-Lock – camera.py, keine Kopie). Es gibt genau ein
Kamera-Handle: alle Pipeline-Aktionen erhalten ihr Bild über
request_full_frame() als Argument, niemand anders öffnet ein VideoCapture.

- Vorschau: cap.grab() kamera-getaktet, aber nur ~preview_fps Frames werden
  dekodiert (retrieve) und downscaled emittiert – überzählige Frames werden
  per grab() verworfen, damit der Treiber-Puffer nicht altert (sonst zeigt
  die Vorschau die Vergangenheit).
- request_full_frame(): threadsicher (threading.Event); der nächste
  komplette Frame geht unverändert (BGR, Originalauflösung) an
  full_frame_ready – das ist das Bild für die Pipeline.
- Fehlerpfad: Kamera fehlt/stirbt -> camera_error (nur bei Übergang, kein
  Spam), dann leiser Reconnect-Versuch alle paar Sekunden bis stop().
"""

from __future__ import annotations

import threading
import time

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from docodetect.camera import BoxCamera, CameraError

from .app import ui_cfg
from .qimage import bgr_to_qimage, downscale_width

_RECONNECT_SECS = 3.0
_MAX_GRAB_FAILS = 10

FOCUS_WARNING = ("Fokus-Lock nicht verfügbar – Messbetrieb nur unter "
                 "Windows verlässlich.")


class CameraWorker(QThread):
    frame_ready = Signal(QImage)        # Vorschau (downscaled)
    full_frame_ready = Signal(object)   # np.ndarray BGR, Originalauflösung
    camera_error = Signal(str)          # bei Verbindungsverlust (Übergang)
    camera_connected = Signal()         # nach (Re-)Connect
    focus_warning = Signal(str)         # "" = Lock ok, sonst Warntext
    fps_update = Signal(float)          # gemessene Vorschau-FPS

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.ui = ui_cfg(cfg)
        self.camera_ok = False
        self._stop_event = threading.Event()
        self._want_full = threading.Event()
        self._announced_error = False   # camera_error nur bei Übergang

    # ---------- API (GUI-Thread) ----------

    def request_full_frame(self) -> None:
        self._want_full.set()

    def stop(self) -> None:
        """Blockiert kurz, bis der Thread wirklich beendet ist – ein QThread
        darf nicht zerstört werden, solange er läuft."""
        self._stop_event.set()
        self.wait(8000)

    # ---------- Worker-Thread ----------

    def run(self) -> None:
        while not self._stop_event.is_set():
            cam = BoxCamera(self.cfg)
            try:
                cam.open()
            except CameraError as e:
                self.camera_ok = False
                if not self._announced_error:
                    self._announced_error = True
                    self.camera_error.emit(
                        f"{e} – Verbindung wird alle "
                        f"{_RECONNECT_SECS:.0f} s neu versucht.")
                # leiser Reconnect: interruptierbares Warten
                self._stop_event.wait(_RECONNECT_SECS)
                continue
            except Exception as e:      # noqa: BLE001
                # Alles, was NICHT CameraError ist, verliesse sonst
                # QThread.run(): der Thread waere tot, KEIN camera_error-Signal
                # kaeme an, camera_ok bliebe dauerhaft False und stop() wartete
                # spaeter 8 s auf einen toten Thread. BoxCamera.open()
                # subskriptiert direkt (camera.py: index/width/height, dazu
                # backend in capture_backend) und wirft dort KeyError -
                # load_config prueft nur die Existenz von SEKTIONEN, nicht
                # einzelner Keys.
                #
                # Bewusst KEIN Reconnect: ein CameraError ist voruebergehend
                # (USB abgezogen) und rechtfertigt den 3-s-Takt. Ein fehlender
                # Config-Key ist es nicht - alle drei Sekunden erneut daran zu
                # scheitern erzeugte nur eine Endlosschleife hinter einer
                # stummen Oberflaeche. Nicht-Transientes beendet den Thread mit
                # stehender Meldung.
                self.camera_ok = False
                self._announced_error = True
                self.camera_error.emit(
                    f"Kamera kann nicht geöffnet werden "
                    f"({type(e).__name__}: {e}). Das ist kein "
                    "Verbindungsproblem – Konfiguration prüfen "
                    "(camera.index / width / height / backend).")
                return
            self.camera_ok = True
            self._announced_error = False
            self.camera_connected.emit()
            self.focus_warning.emit("" if cam.focus_locked else FOCUS_WARNING)
            try:
                self._grab_loop(cam)
            finally:
                cam.close()
        self.camera_ok = False

    def _grab_loop(self, cam: BoxCamera) -> None:
        cap = cam.capture_device
        interval = 1.0 / float(self.ui["preview_fps"])
        preview_w = int(self.ui["preview_max_width"])
        last_emit = 0.0
        # ZWEI getrennte Zaehler, nicht einer: der bewusste Verwurf
        # ueberzaehliger Frames (grab ohne retrieve, weiter unten) ist
        # Normalbetrieb und darf einen Retrieve-Zaehler weder erhoehen noch
        # zuruecksetzen. Mit einem geteilten Zaehler wurde jeder
        # Retrieve-Fehler vom naechsten erfolgreichen grab() geloescht -
        # _MAX_GRAB_FAILS war auf dem Retrieve-Pfad damit UNERREICHBAR, und
        # eine Kamera, die greift aber nichts liefert (realer USB-Zustand),
        # fror die Vorschau lautlos ein: kein Fehler, kein Reconnect-Versuch.
        grab_fails = retrieve_fails = 0
        emitted = 0
        fps_t0 = time.monotonic()

        def _verbindung_verloren() -> None:
            self.camera_ok = False
            self._announced_error = True
            self.camera_error.emit(
                "Kamera-Verbindung verloren – Verbindung wird "
                "gesucht… (USB prüfen)")

        while not self._stop_event.is_set():
            if not cap.grab():
                grab_fails += 1
                if grab_fails >= _MAX_GRAB_FAILS:
                    _verbindung_verloren()
                    return  # -> Reconnect-Schleife in run()
                self._stop_event.wait(0.05)
                continue
            grab_fails = 0

            now = time.monotonic()
            want_full = self._want_full.is_set()
            if not want_full and now - last_emit < interval:
                continue  # überzähligen Frame verwerfen (grab ohne decode)

            ok, frame = cap.retrieve()
            if not ok or frame is None:
                retrieve_fails += 1
                if retrieve_fails >= _MAX_GRAB_FAILS:
                    _verbindung_verloren()
                    return  # -> Reconnect-Schleife in run()
                continue
            retrieve_fails = 0
            if want_full:
                self._want_full.clear()
                self.full_frame_ready.emit(frame)
            self.frame_ready.emit(
                bgr_to_qimage(downscale_width(frame, preview_w)))
            last_emit = now

            emitted += 1
            if now - fps_t0 >= 2.0:
                self.fps_update.emit(emitted / (now - fps_t0))
                emitted, fps_t0 = 0, now
