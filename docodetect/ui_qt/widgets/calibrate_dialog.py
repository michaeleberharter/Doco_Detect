"""Kalibrieren-Dialog: Maßstab (mm/px) der Bodenebene aus dem ArUco-Marker.

Die Hülle stammt aus dem Entwurf, der INHALT ist der echte Ablauf der App:
der Maßstab kommt aus einem gedruckten ArUco-Marker, dessen Kantenlänge in
der Konfiguration steht. Der Entwurf zeigte stattdessen ein Eingabefeld
„bekannter Durchmesser" – das gibt es hier bewusst NICHT, es gäbe eine
zweite, konkurrierende Quelle für den Maßstab.

Reihenfolge: erst Hintergrund aufnehmen, dann kalibrieren. Fehlt der
Hintergrund, sagt das der Dialog, statt es den Bediener später beim
Identifizieren merken zu lassen.

Der Dialog besitzt KEINE Kamera: er bekommt die Frame-Quelle des
Hauptfensters und nutzt denselben request_full_frame()/full_frame_ready-Weg
wie alle anderen Aktionen.
"""

from __future__ import annotations

from datetime import datetime
from functools import partial

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QSizePolicy

from docodetect.config import resolve

from ..pipeline_worker import PipelineWorker
from .dialog_shell import DialogShell, field_row, read_only

_PREVIEW_H = 130          # Entwurf


def _job_calibrate(frame, cfg: dict) -> dict:
    from docodetect.pipeline import calibrate

    cal = calibrate(frame, cfg)
    # Die Kantenlänge in px steckt implizit im Maßstab – so muss
    # calibration.py dafür nichts zusätzlich zurückgeben.
    edge_px = cal.marker_size_mm / cal.mm_per_px if cal.mm_per_px else 0.0
    return {"mm_per_px": cal.mm_per_px, "edge_px": edge_px,
            "created_unix": cal.created_unix}


def _de(value: float, digits: int = 3) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


class _MiniPreview(QLabel):
    """Kleine Live-Vorschau im Dialog – zeigt, was die Kamera gerade sieht."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dialogPreview")
        self.setFixedHeight(_PREVIEW_H)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setAlignment(Qt.AlignCenter)
        self.setText("Warte auf Kamerabild…")

    def set_frame(self, img) -> None:
        if img is None or img.isNull():
            return
        self.setPixmap(QPixmap.fromImage(img).scaled(
            self.width(), self.height(), Qt.KeepAspectRatio,
            Qt.SmoothTransformation))


class CalibrateDialog(DialogShell):
    """Nach Schließen: `calibrated` True, wenn ein neuer Maßstab entstand
    (Aufrufer macht refresh_status())."""

    def __init__(self, cfg: dict, source, parent=None):
        super().__init__("target", "Kalibrieren", "Kalibrieren", parent)
        self.cfg = cfg
        self.source = source
        self.calibrated = False
        self._awaiting_frame = False
        self._worker: PipelineWorker | None = None

        cal_cfg = cfg["calibration"]
        self.add_intro(
            "Gedruckten ArUco-Marker flach und mittig auf den Boden der Box "
            "legen, dann „Kalibrieren“. Daraus ergibt sich der Maßstab in "
            "mm pro Pixel für die Bodenebene.")

        self.preview = _MiniPreview(self)
        self.body.addWidget(self.preview)

        self.hint = QLabel("", self)
        self.hint.setObjectName("dialogHint")
        self.hint.setWordWrap(True)
        self.body.addWidget(self.hint)

        marker, _ = read_only(
            "Referenzobjekt",
            f"{cal_cfg['aruco_dict']} · ID {cal_cfg['marker_id']} · "
            f"{_de(float(cal_cfg['marker_size_mm']), 1)} mm")
        size_box, self.edge_value = read_only("Gemessen (Kante)", "–")
        self.body.addWidget(field_row(marker, size_box))

        scale_box, self.scale_value = read_only("Maßstab", "–", accent=True)
        date_box, self.date_value = read_only("Kalibriert am", "–")
        self.body.addWidget(field_row(scale_box, date_box))

        self.status = QLabel("", self)
        self.status.setObjectName("dialogStatus")
        self.status.setWordWrap(True)
        self.body.addWidget(self.status)

        self.primary.connect(self._start)
        source.frame_ready.connect(self.preview.set_frame)
        source.full_frame_ready.connect(self._on_full_frame)

        self._show_existing()
        self._check_background()

    # ---------- Anzeige ----------

    def _show_existing(self) -> None:
        """Vorhandene Kalibrierung zeigen – der Bediener sieht sofort, ob
        und wann zuletzt kalibriert wurde."""
        from docodetect.pipeline import get_status

        st = get_status(self.cfg)
        if st.calibrated:
            self.scale_value.setText(f"{_de(st.mm_per_px)} mm/px")
            self.date_value.setText(
                datetime.fromtimestamp(st.calibrated_unix).strftime("%d.%m.%Y"))
            self.status.setText("Bestehende Kalibrierung – „Kalibrieren“ "
                                "ersetzt sie.")

    def _check_background(self) -> None:
        """Reihenfolge-Hinweis aus dem Auftrag: erst Hintergrund, dann
        kalibrieren."""
        bg = resolve(self.cfg["calibration"]["background_file"])
        if not bg.exists():
            self.hint.setText(
                "Hinweis: Es gibt noch keine Hintergrund-Aufnahme. Zuerst die "
                "Box leeren und „Hintergrund aufnehmen“ – ohne sie kann nicht "
                "identifiziert werden.")
            self.hint.setVisible(True)
        else:
            self.hint.setVisible(False)

    def _set_busy(self, busy: bool) -> None:
        self.primary_button.setEnabled(not busy)
        self.primary_button.setText("Messe…" if busy else "Kalibrieren")

    # ---------- Ablauf ----------

    def _start(self) -> None:
        if self._awaiting_frame or self._worker is not None:
            return
        self._awaiting_frame = True
        self._set_busy(True)
        self.status.setText("")
        self.source.request_full_frame()

    def _on_full_frame(self, frame) -> None:
        if not self._awaiting_frame:
            return          # Frame gehörte einer Hauptfenster-Aktion
        self._awaiting_frame = False
        w = PipelineWorker(partial(_job_calibrate, frame, self.cfg), self)
        w.finished_ok.connect(self._done)
        w.failed.connect(self._failed)
        w.finished.connect(w.deleteLater)
        w.finished.connect(self._worker_gone)
        self._worker = w
        w.start()

    def _worker_gone(self) -> None:
        self._worker = None

    def _done(self, result: dict) -> None:
        self.calibrated = True
        self._set_busy(False)
        self.scale_value.setText(f"{_de(result['mm_per_px'])} mm/px")
        self.edge_value.setText(f"{result['edge_px']:.1f} px".replace(".", ","))
        self.date_value.setText(
            datetime.fromtimestamp(result["created_unix"]).strftime("%d.%m.%Y"))
        self.status.setText("Kalibrierung gespeichert.")
        self.set_primary_text("Fertig")
        self.primary.disconnect(self._start)
        self.primary.connect(self.accept)

    def _failed(self, message: str) -> None:
        self._set_busy(False)
        # Der Fehlertext aus calibration.py nennt bereits die Abhilfe
        # (Druckqualität, Beleuchtung, Marker flach auflegen).
        self.status.setText(message)
