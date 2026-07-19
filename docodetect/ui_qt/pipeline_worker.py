"""PipelineWorker: genau EINE Pipeline-Aktion im Hintergrund, dann Ende.

Der GUI-Thread blockiert nie (kein identify/enroll/calibrate im Main-Thread,
DINOv2 in Stufe 2 kann Sekunden dauern). Der Job ist ein Callable, das die
Pipeline SELBST im Worker-Thread konstruiert – wichtig wegen SQLite-Thread-
Affinität (eine im GUI-Thread geöffnete Connection darf im Worker nicht
benutzt werden). Signale laufen als QueuedConnection zurück in die GUI –
keine eigenen Locks nötig.
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal


class PipelineWorker(QThread):
    finished_ok = Signal(object)   # Ergebnis-Objekt des Jobs
    failed = Signal(str)           # verständliche Fehlermeldung

    def __init__(self, job, parent=None):
        super().__init__(parent)
        self._job = job

    def run(self) -> None:  # läuft im Worker-Thread
        try:
            self.finished_ok.emit(self._job())
        except Exception as e:  # noqa: BLE001 – UI zeigt JEDEN Fehler lesbar
            self.failed.emit(str(e))
