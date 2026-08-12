"""Segmentierungs-Test (Stufe 4, Spec Punkt 10): „warum erkennt er nichts?"

Testaufnahme über die Frame-Quelle des HAUPTFENSTERS (frame_anfordern =
Spec-§4-Meldekanal „Voll-Frame auf Anforderung", request_full_frame-
Muster) — das Admin-Fenster besitzt keine Kamera und öffnet keine.
Messung via pipeline.measure_shot (kein DB-Schreibzugriff) im
PipelineWorker; Anzeige Maske, Kontur-Overlay und Messwerte.
SegmentationError ist hier das erwartete Diagnose-Ergebnis und wird als
Text gezeigt, nie als Crash. Ohne Frame-Quelle (keine Kamera): Seite
deaktiviert mit Hinweis (Spec Abschnitt 4)."""

from __future__ import annotations

from typing import Callable, Optional

import cv2
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from docodetect.pipeline import SegmentationError, measure_shot  # noqa: F401

from ...pipeline_worker import PipelineWorker
from ...qimage import bgr_to_qimage, downscale_width
from ...widgets.common import section_label

_OHNE_QUELLE = ("Segmentierungs-Test deaktiviert — keine Kamera-"
                "Frame-Quelle (Hauptfenster ohne Kamera oder Admin "
                "ohne Anbindung). An der Box mit verbundener Kamera "
                "oder im Demo-Modus verfügbar.")


def _de(x, stellen: int = 2) -> str:
    return f"{float(x):.{stellen}f}".replace(".", ",")


class SegTestPage(QWidget):
    """Eine Aktion (Testaufnahme), rein diagnostisch, kein DB-Zugriff."""

    def __init__(self, cfg: dict,
                 frame_anfordern: Optional[Callable] = None,
                 parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self._frame_anfordern = frame_anfordern
        self._worker: PipelineWorker | None = None
        self._werte: dict = {"messwerte": {}, "maske_gesetzt": False,
                             "overlay_gesetzt": False, "status": ""}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(8)
        kopf = QHBoxLayout()
        self.aufnahme_button = QPushButton("Testaufnahme")
        self.aufnahme_button.clicked.connect(self.testaufnahme)
        kopf.addWidget(self.aufnahme_button, alignment=Qt.AlignLeft)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        kopf.addWidget(self.status, stretch=1)
        lay.addLayout(kopf)

        bilder = QHBoxLayout()
        links = QVBoxLayout()
        links.addWidget(section_label("Maske"))
        self.maske_label = QLabel("—")
        self.maske_label.setAlignment(Qt.AlignCenter)
        self.maske_label.setMinimumSize(240, 160)
        links.addWidget(self.maske_label, stretch=1)
        bilder.addLayout(links)
        rechts = QVBoxLayout()
        rechts.addWidget(section_label("Kontur-Overlay"))
        self.overlay_label = QLabel("—")
        self.overlay_label.setAlignment(Qt.AlignCenter)
        self.overlay_label.setMinimumSize(240, 160)
        rechts.addWidget(self.overlay_label, stretch=1)
        bilder.addLayout(rechts)
        lay.addLayout(bilder, stretch=1)

        lay.addWidget(section_label("Messwerte"))
        self._tabelle = QTableWidget(0, 2)
        self._tabelle.setHorizontalHeaderLabels(["Größe", "Wert"])
        self._tabelle.verticalHeader().setVisible(False)
        self._tabelle.setEditTriggers(QTableWidget.NoEditTriggers)
        self._tabelle.setMaximumHeight(220)
        lay.addWidget(self._tabelle)

        if self._frame_anfordern is None:
            self.aufnahme_button.setEnabled(False)
            self._set_status(_OHNE_QUELLE)

    def _set_status(self, text: str) -> None:
        self.status.setText(text)
        self._werte["status"] = text

    # ---------- Ablauf ----------

    def testaufnahme(self) -> None:
        if self._frame_anfordern is None or self._worker is not None:
            return
        self.aufnahme_button.setEnabled(False)
        self._warte_auf_frame = True
        self._set_status("Warte auf Frame vom Hauptfenster …")
        ok = self._frame_anfordern(self._frame_erhalten)
        if not ok:
            self._warte_auf_frame = False
            self.aufnahme_button.setEnabled(True)
            self._set_status(_OHNE_QUELLE)

    def _frame_erhalten(self, frame) -> None:
        """Slot (gebundene QObject-Methode → QueuedConnection, läuft im
        GUI-Thread; siehe MainWindow._frame_fuer_admin). Unangeforderte
        Frames — z. B. eine Identifikation des Hauptfensters — werden
        über das Warte-Flag verworfen."""
        if not getattr(self, "_warte_auf_frame", False):
            return
        self._warte_auf_frame = False
        cfg = self.cfg
        self._set_status("Messe …")
        w = PipelineWorker(lambda: (frame, measure_shot(frame, cfg)), self)
        w.finished_ok.connect(self._messung_fertig)
        w.failed.connect(self._messung_fehler)
        w.finished.connect(self._worker_beendet)
        self._worker = w
        w.start()

    def _worker_beendet(self) -> None:
        if self._worker is not None:
            self._worker.deleteLater()
        self._worker = None
        self.aufnahme_button.setEnabled(self._frame_anfordern is not None)

    def _messung_fertig(self, ergebnis) -> None:
        frame, (feats, seg) = ergebnis
        maske_bgr = cv2.cvtColor(seg.mask, cv2.COLOR_GRAY2BGR)
        self._zeige(self.maske_label, maske_bgr)
        self._werte["maske_gesetzt"] = True
        overlay = np.ascontiguousarray(frame).copy()
        cv2.drawContours(overlay, [seg.contour], -1, (0, 255, 0), 3)
        self._zeige(self.overlay_label, overlay)
        self._werte["overlay_gesetzt"] = True
        mess = {
            "Ø (minEnclosingCircle) [mm]": _de(feats.circle_diameter_mm),
            "Ø (äquivalent) [mm]": _de(feats.equiv_diameter_mm),
            "Fläche [mm²]": _de(feats.area_mm2, 0),
            "Zirkularität": _de(feats.circularity),
            "Seitenverhältnis": _de(feats.aspect_ratio),
            "Randberührung": "ja" if seg.touches_border else "nein",
        }
        self._werte["messwerte"] = mess
        self._tabelle.setRowCount(len(mess))
        for r, (k, v) in enumerate(mess.items()):
            self._tabelle.setItem(r, 0, QTableWidgetItem(k))
            self._tabelle.setItem(r, 1, QTableWidgetItem(v))
        self._tabelle.resizeColumnsToContents()
        self._set_status("Messung fertig — Werte unten, Maske/Overlay "
                         "oben.")

    def _messung_fehler(self, text: str) -> None:
        # SegmentationError landet hier: DAS ist die Diagnose-Antwort.
        self._set_status(f"Nicht messbar: {text}")

    def _zeige(self, label: QLabel, bgr) -> None:
        img = bgr_to_qimage(downscale_width(bgr, 480))
        label.setPixmap(QPixmap.fromImage(img).scaled(
            label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    # ---------- Testhilfe ----------

    def werte(self) -> dict:
        return {"messwerte": dict(self._werte["messwerte"]),
                "maske_gesetzt": self._werte["maske_gesetzt"],
                "overlay_gesetzt": self._werte["overlay_gesetzt"],
                "status": self._werte["status"]}
