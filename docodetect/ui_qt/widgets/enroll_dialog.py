"""Einlern-Assistent: Artikelwahl + n Aufnahmen mit Fortschritt.

Ablauf: „Aufnahme 3 von 8 – Artikel etwas drehen, dann ‚Aufnehmen‘.“
Jeder Shot wird sofort VERMESSEN (measure_shot, im Worker – nichts wird
geschrieben), erscheint als Thumbnail mit Ø und ist per Klick + erneutem
„Aufnehmen“ einzeln wiederholbar. Erst „Speichern“ persistiert alle Shots
auf einmal (save_enrollment) – kein verwaister DB-Eintrag bei Abbruch.

Der Dialog besitzt KEINE Kamera: er bekommt die Frame-Quelle des
Hauptfensters (DemoSource/CameraWorker) und nutzt denselben
request_full_frame()/full_frame_ready-Weg wie alle Aktionen.
"""

from __future__ import annotations

from functools import partial

import cv2
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QComboBox, QCompleter, QDialog, QHBoxLayout,
                               QLabel, QListWidget, QListWidgetItem,
                               QPushButton, QSpinBox, QVBoxLayout)

from docodetect.pipeline import list_articles

from ..pipeline_worker import PipelineWorker
from ..qimage import bgr_to_qimage, downscale_width

_THUMB_W = 128


# ---------- Jobs (Worker-Thread) ----------

def _job_measure(frame, cfg: dict) -> dict:
    from docodetect.pipeline import measure_shot

    feats, seg = measure_shot(frame, cfg)   # raises SegmentationError
    thumb_src = frame.copy()
    cv2.polylines(thumb_src, [seg.contour], isClosed=True,
                  color=(0, 255, 0), thickness=max(2, frame.shape[1] // 640))
    return {"frame": frame, "feats": feats,
            "thumb": bgr_to_qimage(downscale_width(thumb_src, _THUMB_W)),
            "d_mm": feats.circle_diameter_mm}


def _job_save(cfg: dict, article_number: str, shots: list) -> dict:
    from docodetect.pipeline import save_enrollment

    n = save_enrollment(cfg, article_number,
                        [(s["frame"], s["feats"]) for s in shots])
    return {"n": n, "article_number": article_number}


class EnrollDialog(QDialog):
    """Nach Schließen: saved_count > 0 => Referenzen wurden angelegt
    (Aufrufer macht refresh_status())."""

    def __init__(self, cfg: dict, ui: dict, source, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.source = source
        self.saved_count = 0
        self._shots: list = []            # fertige Messungen (dict aus _job_measure)
        self._retake_index: int | None = None
        self._awaiting_frame = False
        self._worker: PipelineWorker | None = None
        self._target_shots = int(ui["enroll_shots"])

        self.setWindowTitle("Artikel einlernen")
        self.setModal(True)
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        # -- Artikelwahl: durchsuchbares Dropdown + Referenz-Anzeige --
        row = QHBoxLayout()
        row.addWidget(QLabel("Artikel:"))
        self.article_box = QComboBox()
        self.article_box.setEditable(True)
        self.article_box.setInsertPolicy(QComboBox.NoInsert)
        self._articles = list_articles(cfg)
        for a in self._articles:
            self.article_box.addItem(
                f"{a.name}  ({a.article_number})", a.article_number)
        completer = QCompleter(
            [self.article_box.itemText(i)
             for i in range(self.article_box.count())], self)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        self.article_box.setCompleter(completer)
        self.article_box.currentIndexChanged.connect(self._article_changed)
        row.addWidget(self.article_box, stretch=1)
        row.addWidget(QLabel("Aufnahmen:"))
        self.shots_spin = QSpinBox()
        self.shots_spin.setRange(1, 20)
        self.shots_spin.setValue(self._target_shots)
        self.shots_spin.valueChanged.connect(self._update_texts)
        row.addWidget(self.shots_spin)
        lay.addLayout(row)

        self.ref_label = QLabel("")
        self.ref_label.setObjectName("guideLabel")
        lay.addWidget(self.ref_label)

        # -- Fortschritt + Aufnehmen --
        self.progress_label = QLabel("")
        self.progress_label.setObjectName("resultHeadline")
        lay.addWidget(self.progress_label)

        self.capture_button = QPushButton("Aufnehmen")
        self.capture_button.setObjectName("primaryButton")
        self.capture_button.clicked.connect(self._capture)
        lay.addWidget(self.capture_button)

        self.hint_label = QLabel("")
        self.hint_label.setObjectName("guideLabel")
        self.hint_label.setWordWrap(True)
        lay.addWidget(self.hint_label)

        # -- Thumbnail-Leiste: Klick wählt eine Aufnahme zum Wiederholen --
        self.thumbs = QListWidget()
        self.thumbs.setViewMode(QListWidget.IconMode)
        self.thumbs.setIconSize(QSize(_THUMB_W, _THUMB_W * 9 // 16))
        self.thumbs.setFixedHeight(_THUMB_W)
        self.thumbs.setMovement(QListWidget.Static)
        self.thumbs.itemClicked.connect(self._thumb_clicked)
        lay.addWidget(self.thumbs)

        # -- Abschluss --
        btns = QHBoxLayout()
        btns.addStretch(1)
        self.save_button = QPushButton("Speichern")
        self.save_button.setObjectName("secondaryButton")
        self.save_button.clicked.connect(self._save)
        self.cancel_button = QPushButton("Abbrechen")
        self.cancel_button.setObjectName("secondaryButton")
        self.cancel_button.clicked.connect(self.reject)  # Esc macht dasselbe
        btns.addWidget(self.cancel_button)
        btns.addWidget(self.save_button)
        lay.addLayout(btns)

        source.full_frame_ready.connect(self._on_full_frame)
        self._article_changed()

    # ---------- Anzeige ----------

    def _current_article_number(self) -> str | None:
        return self.article_box.currentData()

    def _article_changed(self) -> None:
        nr = self._current_article_number()
        info = next((a for a in self._articles if a.article_number == nr), None)
        if info is None:
            self.ref_label.setText("Keinen Artikel gewählt.")
        else:
            self.ref_label.setText(
                f"{info.n_references} Referenz(en) vorhanden – neue Aufnahmen "
                "kommen dazu.")
        self._update_texts()

    def _update_texts(self) -> None:
        n, target = len(self._shots), self.shots_spin.value()
        busy = self._worker is not None or self._awaiting_frame
        if self._retake_index is not None:
            self.progress_label.setText(
                f"Aufnahme {self._retake_index + 1} wiederholen – Artikel "
                "neu ausrichten, dann „Aufnehmen“.")
        elif n < target:
            self.progress_label.setText(
                f"Aufnahme {n + 1} von {target} – Artikel etwas drehen, "
                "dann „Aufnehmen“.")
        else:
            self.progress_label.setText(
                f"{n} Aufnahmen fertig – „Speichern“ legt die Referenzen an.")
        self.capture_button.setEnabled(
            not busy and self._current_article_number() is not None
            and (self._retake_index is not None or n < target))
        self.save_button.setEnabled(not busy and n > 0)
        self.save_button.setText(f"Speichern ({n}/{target})")

    # ---------- Aufnehmen ----------

    def _capture(self) -> None:
        if self._awaiting_frame or self._worker is not None:
            return
        self._awaiting_frame = True
        self._update_texts()
        self.hint_label.setText("")
        self.source.request_full_frame()

    def _on_full_frame(self, frame) -> None:
        if not self._awaiting_frame:
            return  # Frame gehörte einer Hauptfenster-Aktion
        self._awaiting_frame = False
        self._start_worker(partial(_job_measure, frame, self.cfg),
                           self._measure_done)

    def _start_worker(self, job, on_done) -> None:
        w = PipelineWorker(job, self)
        w.finished_ok.connect(on_done)
        w.failed.connect(self._job_failed)
        w.finished.connect(w.deleteLater)
        w.finished.connect(self._worker_gone)
        self._worker = w
        self._update_texts()
        w.start()

    def _worker_gone(self) -> None:
        self._worker = None
        self._update_texts()

    def _measure_done(self, shot: dict) -> None:
        if self._retake_index is not None:
            self._shots[self._retake_index] = shot
            self._retake_index = None
        else:
            self._shots.append(shot)
        self._rebuild_thumbs()
        self._update_texts()

    def _job_failed(self, message: str) -> None:
        self._retake_index = None
        # Fehlertext nennt die Abhilfe (z.B. Randberührung: weiter zur Mitte).
        self.hint_label.setText(f"Aufnahme verworfen: {message}")
        self._update_texts()

    def _rebuild_thumbs(self) -> None:
        self.thumbs.clear()
        for i, shot in enumerate(self._shots):
            icon = QIcon(QPixmap.fromImage(shot["thumb"]))
            d = f"{shot['d_mm']:.1f}".replace(".", ",")
            item = QListWidgetItem(icon, f"{i + 1}: Ø {d} mm")
            item.setToolTip("Klicken und erneut „Aufnehmen“ ersetzt diese "
                            "Aufnahme.")
            self.thumbs.addItem(item)

    def _thumb_clicked(self, item: QListWidgetItem) -> None:
        self._retake_index = self.thumbs.row(item)
        self._update_texts()

    # ---------- Speichern ----------

    def _save(self) -> None:
        nr = self._current_article_number()
        if nr is None or not self._shots:
            return
        self._start_worker(partial(_job_save, self.cfg, nr, list(self._shots)),
                           self._save_done)
        self.save_button.setEnabled(False)

    def _save_done(self, result: dict) -> None:
        self.saved_count = result["n"]
        self.accept()
