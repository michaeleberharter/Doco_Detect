"""Kamera-Diagnose (Stufe 4, Spec Punkt 12).

Zeigt Konfiguration (Index, Backend), Focus-Lock-Fähigkeit, den
Kamera-Zustand des Hauptfensters und dessen letzte Fokus-/Readback-
Warnung — mit dem festen Hinweis, dass die Readback-Warnung auf
Mac/AVFoundation erwartbar ist (Kamera-Props per cv2 nicht setzbar).

Kamera-Alleinbesitz (Spec Abschnitt 4): camera.probe_cameras ÖFFNET
echte Geräte — die Suche ist deshalb NUR aktiv, wenn das Hauptfenster
keine Kamera hält („verbunden" → gesperrt mit Hinweis). Das Admin-
Fenster besitzt nie eine Kamera; die Suche läuft im PipelineWorker
(probe blockiert sekundenlang) und gibt die Geräte sofort wieder frei.
camera.py ist per CLAUDE.md erlaubter UI-Import."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFormLayout, QLabel, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from docodetect.camera import (capture_backend, focus_lock_supported,
                               probe_cameras)

from ...pipeline_worker import PipelineWorker
from ...widgets.common import section_label

_MAC_HINWEIS = ("Hinweis: Auf Mac/AVFoundation ist die Readback-Warnung "
                "erwartbar und kein Fehler — Kamera-Eigenschaften sind "
                "per cv2 nicht setzbar, das Profil kommt aus dem "
                "CameraController.")
_SUCHE_GESPERRT = ("Kamera in Benutzung durch die Bedienoberfläche — "
                   "Suche ist nur bei getrennter Kamera möglich "
                   "(die Suche öffnet Geräte).")


class CameraPage(QWidget):
    """Rein anzeigend; einzige Aktion ist die gegatete Geräte-Suche."""

    def __init__(self, cfg: dict, camera_status: Callable[[], str],
                 kamera_warnung: Callable[[], str] | None = None,
                 parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self._camera_status = camera_status
        self._kamera_warnung = kamera_warnung
        self._worker: PipelineWorker | None = None
        self._suche_zeilen: list = []
        self._werte: dict = {}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(8)
        lay.setAlignment(Qt.AlignTop)
        lay.addWidget(section_label("Konfiguration & Zustand"))
        self._form = QFormLayout()
        lay.addLayout(self._form)
        self.hinweis = QLabel(_MAC_HINWEIS)
        self.hinweis.setWordWrap(True)
        lay.addWidget(self.hinweis)

        lay.addWidget(section_label("Geräte-Suche"))
        self.suche_hinweis = QLabel("")
        self.suche_hinweis.setWordWrap(True)
        lay.addWidget(self.suche_hinweis)
        self.suche_button = QPushButton("Kameras suchen")
        self.suche_button.clicked.connect(self.suche_starten)
        lay.addWidget(self.suche_button, alignment=Qt.AlignLeft)
        self._tabelle = QTableWidget(0, 3)
        self._tabelle.setHorizontalHeaderLabels(
            ["Index", "liefert Bild", "Auflösung"])
        self._tabelle.verticalHeader().setVisible(False)
        self._tabelle.setEditTriggers(QTableWidget.NoEditTriggers)
        lay.addWidget(self._tabelle)
        self.refresh_button = QPushButton("Aktualisieren")
        self.refresh_button.clicked.connect(self.refresh)
        lay.addWidget(self.refresh_button, alignment=Qt.AlignLeft)
        self.refresh()

    def refresh(self) -> None:
        w = {}
        w["index"] = str(self.cfg.get("camera", {}).get("index", 0))
        try:
            w["backend"] = str(capture_backend(self.cfg.get("camera")))
        except Exception:  # noqa: BLE001
            w["backend"] = "—"
        w["focus_lock"] = ("verfügbar" if focus_lock_supported()
                           else "nicht verfügbar (Mac/AVFoundation)")
        w["zustand"] = self._camera_status()
        w["warnung"] = (self._kamera_warnung() or "—"
                        if self._kamera_warnung else "—")
        w["hinweis"] = _MAC_HINWEIS
        self._werte = w

        while self._form.rowCount():
            self._form.removeRow(0)
        for titel, wert in (("Konfigurierter Index", w["index"]),
                            ("Backend", w["backend"]),
                            ("Focus-Lock", w["focus_lock"]),
                            ("Kamera-Zustand", w["zustand"]),
                            ("Letzte Warnung", w["warnung"])):
            lab = QLabel(wert)
            lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self._form.addRow(QLabel(titel), lab)

        gesperrt = w["zustand"] == "verbunden"
        self.suche_button.setEnabled(not gesperrt
                                     and self._worker is None)
        self.suche_hinweis.setText(_SUCHE_GESPERRT if gesperrt else
                                   "Probiert die Indizes 0–3 durch und "
                                   "gibt die Geräte sofort wieder frei.")
        self._werte["suche_hinweis"] = self.suche_hinweis.text()

    # ---------- Suche (gegated, im Worker) ----------

    def suche_starten(self) -> None:
        if self._worker is not None or self._camera_status() == "verbunden":
            return
        self.suche_button.setEnabled(False)
        kamera_cfg = self.cfg.get("camera")
        w = PipelineWorker(lambda: probe_cameras(kamera_cfg), self)
        w.finished_ok.connect(self._suche_fertig)
        w.failed.connect(self._suche_fehler)
        w.finished.connect(self._worker_beendet)
        self._worker = w
        w.start()

    def _worker_beendet(self) -> None:
        if self._worker is not None:
            self._worker.deleteLater()
        self._worker = None
        self.refresh()

    def _suche_fertig(self, gefunden) -> None:
        self._suche_zeilen = [
            {"index": idx, "ok": bool(ok),
             "aufloesung": f"{b}×{h}" if ok else "—"}
            for idx, ok, b, h in gefunden]
        self._tabelle.setRowCount(len(self._suche_zeilen))
        for r, z in enumerate(self._suche_zeilen):
            for c, wert in enumerate([str(z["index"]),
                                      "ja" if z["ok"] else "nein",
                                      z["aufloesung"]]):
                self._tabelle.setItem(r, c, QTableWidgetItem(wert))
        self._tabelle.resizeColumnsToContents()

    def _suche_fehler(self, text: str) -> None:
        self.suche_hinweis.setText(f"Suche fehlgeschlagen: {text}")
        self._werte["suche_hinweis"] = text

    # ---------- Testhilfen ----------

    def werte(self) -> dict:
        return dict(self._werte)

    def suche_zeilen(self) -> list:
        return [dict(z) for z in self._suche_zeilen]
