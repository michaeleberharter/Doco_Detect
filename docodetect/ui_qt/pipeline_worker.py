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
    progress = Signal(int, int)    # (fertig, gesamt) – nur bei with_progress

    def __init__(self, job, parent=None, *, with_progress: bool = False):
        """with_progress=True reicht dem Job `progress=self.progress.emit`
        herein. Explizites Flag statt inspect.signature-Magie: der Aufrufer
        weiss, ob sein Job Fortschritt meldet, und der Worker raet nicht.

        Gebraucht wird es von remeasure_session – die Wiederherstellung einer
        unterbrochenen Session misst jede Aufnahme neu (~1 s je Shot) und
        saehe ohne Anzeige aus wie ein Haenger. Ein vermuteter Haenger an der
        Box fuehrt zum Abschiessen der App, also genau zu dem Absturz, gegen
        den dieses Paket gebaut ist."""
        super().__init__(parent)
        self._job = job
        self._with_progress = with_progress

    def run(self) -> None:  # läuft im Worker-Thread
        try:
            if self._with_progress:
                self.finished_ok.emit(self._job(progress=self.progress.emit))
            else:
                self.finished_ok.emit(self._job())
        except Exception as e:  # noqa: BLE001 – UI zeigt JEDEN Fehler lesbar
            self.failed.emit(str(e))
