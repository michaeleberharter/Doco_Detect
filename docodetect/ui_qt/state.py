"""Zustandsmaschine des Hauptfensters (PLAN 6.4) – bewusst Qt-frei.

Vier explizite Zustände statt verstreuter Flags; compute_state() ist eine
reine Funktion, damit die Übergänge ohne GUI testbar sind. Die Wirkung
(Buttons, Vorschau-Text, Setup-Führung) zieht MainWindow.set_state().
"""

from __future__ import annotations

from enum import Enum, auto


class UiState(Enum):
    NO_CAMERA = auto()   # Platzhalter "Keine Kamera gefunden", nur Demo/Setup
    NOT_READY = auto()   # Kamera läuft, Hintergrund/Kalibrierung fehlt
    READY = auto()       # Normalbetrieb
    BUSY = auto()        # Pipeline-Aktion läuft, Aktionen gesperrt


def compute_state(camera_ok: bool, ready: bool, busy: bool) -> UiState:
    """BUSY gewinnt: eine laufende Aktion bleibt sichtbar, auch wenn die
    Kamera währenddessen stirbt – nach dem Aktions-Ende wird neu berechnet
    und NO_CAMERA sichtbar. Danach: ohne Kamera nützt Einrichtung nichts."""
    if busy:
        return UiState.BUSY
    if not camera_ok:
        return UiState.NO_CAMERA
    if not ready:
        return UiState.NOT_READY
    return UiState.READY
