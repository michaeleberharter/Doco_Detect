"""Einlern-Assistent: Artikelwahl + n Aufnahmen mit Fortschritt.

Ablauf: „Aufnahme 3 von 12 – Artikel etwas drehen, dann ‚Aufnehmen‘.“

Seit dem Session-Umbau ist die PLATTE die Wahrheit, nicht der Arbeitsspeicher:
jede Aufnahme wird sofort als Roh-PNG verankert (`stage_frame`), vermessen
(`measure_shot`) und dann per Journalzeile übernommen (`append_shot`). Ein
Absturz kostet damit höchstens die laufende Aufnahme, nie die Session — vorher
lagen alle N Frames bis zum Speichern ausschließlich im RAM, und am 2026-08-01
waren 12 Shots deshalb weg.

Der Dialog besitzt KEINE Kamera: er bekommt die Frame-Quelle des
Hauptfensters (DemoSource/CameraWorker) und nutzt denselben
request_full_frame()/full_frame_ready-Weg wie alle Aktionen.
"""

from __future__ import annotations

import time
from functools import partial

import cv2
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QComboBox, QCompleter, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QMessageBox,
                               QProgressBar, QPushButton, QSpinBox)

from docodetect.pipeline import list_articles

from ..camera_worker import _RECONNECT_SECS
from ..pipeline_worker import PipelineWorker
from ..qimage import bgr_to_qimage, downscale_width
from .dialog_shell import DialogShell, read_only

_THUMB_W = 128

# Zeitgrenze fuers stumme Warten auf einen Frame. Als VIELFACHES der
# Reconnect-Konstante, nicht als Literal: der Normalpfad kostet ~76 ms
# (ein Intervall bei preview_fps 15 plus ~9 ms MJPG-Decode, beides gemessen),
# das Risiko ist der laufende Reconnect. Ein Frame waehrend eines
# Wiederverbindens braucht legitim ueber _RECONNECT_SECS — zwei Zyklen passen
# hinein, ohne auszuloesen. Der Timer meldet deshalb einen ZUSTAND und keinen
# Fehler: waehrend eines Ausfalls kann keine endliche Grenze Fehlausloesungen
# vermeiden, also darf sie nichts behaupten.
_FRAME_TIMEOUT_MS = int(2 * _RECONNECT_SECS * 1000)

# Nach so langer Worker-Laufzeit erscheint zusaetzlich „Trotzdem schliessen“.
# Der Schliessschutz ist eine SCHWELLE, kein Schloss — und er darf das sein,
# weil das Journal ein erzwungenes Schliessen ungefaehrlich gemacht hat: die
# Aufnahmen liegen auf der Platte, die Session bleibt offen.
_SCHLIESSSCHUTZ_MS = 30_000


# ---------- Jobs (Worker-Thread) ----------

def _job_capture(frame, cfg: dict, session, i=None) -> dict:
    """Ein Klick = EIN Job mit drei Schritten, seriell.

    stage_frame verankert das Rohbild BEVOR gemessen wird und prueft dabei den
    Fingerabdruck; wirft measure_shot (Randberuehrung), bleibt das PNG als
    Waise liegen und es entsteht keine Journalzeile — der Fehlerpfad gewinnt
    Material, statt es zu verlieren."""
    from docodetect.pipeline import append_shot, measure_shot, stage_frame

    raw = stage_frame(cfg, session, frame)
    feats, seg = measure_shot(frame, cfg)     # raises SegmentationError
    session = append_shot(cfg, session, raw, feats, i=i)
    thumb_src = frame.copy()
    cv2.polylines(thumb_src, [seg.contour], isClosed=True,
                  color=(0, 255, 0), thickness=max(2, frame.shape[1] // 640))
    i_neu = session.shots[-1].i if i is None else i
    return {"session": session, "i": i_neu,
            "thumb": bgr_to_qimage(downscale_width(thumb_src, _THUMB_W)),
            "d_mm": feats.circle_diameter_mm}


def _job_remeasure(cfg: dict, session, progress=None) -> dict:
    """Fortsetzen: jede Aufnahme aus ihrem PNG neu vermessen (~1 s je Shot).
    LESEND — das Journal wird nicht angefasst, gebucht werden spaeter die
    Journalwerte."""
    from docodetect.pipeline import remeasure_session

    neu, abweichungen = remeasure_session(cfg, session, progress=progress)
    thumbs = {}
    for shot in neu.shots:
        bild = cv2.imread(str(shot.raw_path))
        if bild is not None:
            thumbs[shot.i] = bgr_to_qimage(downscale_width(bild, _THUMB_W))
    return {"session": neu, "abweichungen": abweichungen, "thumbs": thumbs}


def _job_sheet(cfg: dict, session) -> dict:
    """Diagnoseblatt aus den Aufnahmen der Session rendern (Segmentierung je
    Shot – darum im Worker). Die Frames kommen von der Platte."""
    import tempfile
    from pathlib import Path

    from docodetect.pipeline import enrollment_sheet_for_shots

    shots = [(cv2.imread(str(s.raw_path)), s.features) for s in session.shots]
    out = Path(tempfile.mkdtemp(prefix="docodetect_sheet_")) / \
        f"{session.info.article_number}_enrollment.png"
    png = enrollment_sheet_for_shots(
        cfg, session.info.article_number, shots, out=out)
    return {"sheet": str(png)}


def _job_commit(cfg: dict, session, sheet_png: str | None = None) -> dict:
    """Buchen unter U1 (erst alle Dateien, dann eine Transaktion), danach das
    Diagnoseblatt best-effort ablegen: der DB-Eintrag steht bereits, ein
    Kopierfehler darf ihn nicht rueckgaengig machen."""
    from docodetect.pipeline import commit_enroll_session, persist_enrollment_sheet

    n = commit_enroll_session(cfg, session)
    sheet_dest = warn = None
    if sheet_png:
        try:
            sheet_dest = str(persist_enrollment_sheet(
                cfg, session.info.article_number, sheet_png))
        except Exception as exc:                       # noqa: BLE001
            warn = f"Diagnoseblatt nicht gesichert: {exc}"
    return {"n": n, "article_number": session.info.article_number,
            "sheet_dest": sheet_dest, "warn": warn}


def _job_discard(cfg: dict, session, sheet_png: str | None = None) -> dict:
    from docodetect.pipeline import discard_enroll_session

    dest = discard_enroll_session(cfg, session, sheet_png=sheet_png)
    return {"dest": str(dest), "n": session.info.n_shots}


class EnrollDialog(DialogShell):
    """Nach Schließen: saved_count > 0 => Referenzen wurden angelegt
    (Aufrufer macht refresh_status()).

    `fortsetzen` (SessionInfo) startet den Dialog auf einer unterbrochenen
    Session statt auf einer neuen."""

    def __init__(self, cfg: dict, ui: dict, source, parent=None,
                 fortsetzen=None):
        super().__init__("plus", "Artikel einlernen", "Speichern", parent)
        self.cfg = cfg
        self.source = source
        self.saved_count = 0
        self._session = None              # EnrollSession | None – die Wahrheit
        self._thumbs: dict = {}           # i -> QImage
        self._retake_index: int | None = None
        self._awaiting_frame = False
        self._worker: PipelineWorker | None = None
        self._worker_start = 0.0
        self._target_shots = int(ui["enroll_shots"])

        self.card.setMinimumWidth(560)     # mehr als der Entwurf: die
        # Thumbnail-Leiste braucht Breite, sonst passen keine drei Aufnahmen
        # nebeneinander.
        lay = self.body
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

        # Toleranz NUR zur Information: sie ist global
        # (matching.diameter_tolerance_mm) und KEIN Artikelattribut.
        tol = float(cfg["matching"]["diameter_tolerance_mm"])
        tol_box, _ = read_only(
            "Toleranz ± (global, aus der Konfiguration)",
            f"{tol:.1f} mm".replace(".", ","))
        lay.addWidget(tol_box)

        # -- Fortschritt + Aufnehmen --
        self.progress_label = QLabel("")
        self.progress_label.setObjectName("resultHeadline")
        lay.addWidget(self.progress_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        lay.addWidget(self.progress_bar)

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

        # -- Abschluss: die Hauptaktion der Hülle IST das Speichern --
        self.save_button = self.primary_button
        self.primary.connect(self._save)

        source.full_frame_ready.connect(self._on_full_frame)

        self._frame_timer = QTimer(self)
        self._frame_timer.setSingleShot(True)
        self._frame_timer.timeout.connect(self._frame_ausgeblieben)
        self._kamera_fehler = ""
        for name, slot in (("camera_error", self._kamera_fehler_gesehen),
                           ("camera_connected", self._kamera_wieder_da)):
            signal = getattr(source, name, None)
            if signal is not None:
                signal.connect(slot)

        if fortsetzen is not None:
            self._fortsetzen_starten(fortsetzen)
        else:
            self._article_changed()

    # ---------- Fortsetzen ----------

    def _fortsetzen_starten(self, info) -> None:
        """Unterbrochene Session laden und ihre Aufnahmen neu vermessen.
        ~1 s je Shot – ohne Anzeige sähe das aus wie ein Hänger, und ein
        vermuteter Hänger an der Box führt zum Abschießen der App."""
        from docodetect.pipeline import load_enroll_session

        session = load_enroll_session(self.cfg, info.path)
        self._session = session
        self._waehle_artikel(session.info.article_number)
        self.shots_spin.setValue(session.info.target_shots)
        self._sperre_artikelwahl()
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, max(1, session.info.n_shots))
        self.progress_bar.setValue(0)
        self.progress_label.setText("Session wird wiederhergestellt …")
        self._start_worker(partial(_job_remeasure, self.cfg, session),
                           self._remeasure_done, with_progress=True)

    def _remeasure_done(self, result: dict) -> None:
        self.progress_bar.setVisible(False)
        self._session = result["session"]
        self._thumbs = dict(result["thumbs"])
        self._rebuild_thumbs()
        abw = result["abweichungen"]
        if abw:
            self.hint_label.setText(self._abweichungstext(abw))
        else:
            self.hint_label.setText(
                f"Session wiederhergestellt – {self._n_shots()} Aufnahmen.")
        self._update_texts()

    def _abweichungstext(self, abw: list) -> str:
        """Befund mit ZWEI Auswegen. Der Text muss sagen, WELCHE Werte gebucht
        werden – sonst nimmt der Leser an, es seien die eben gemessenen."""
        betroffen = sorted({a["i"] for a in abw})
        zeilen = "; ".join(
            f"Aufnahme {a['i'] + 1}: {a['merkmal']} {a['journal']:.3f} → "
            f"{a['neu']:.3f} (Δ {a['delta']:.3f}, Toleranz {a['toleranz']:.3f})"
            for a in abw[:3])
        return (
            f"⚠ Wiederherstellung: {len(betroffen)} von {self._n_shots()} "
            f"Aufnahmen weichen von den gespeicherten Messwerten ab. {zeilen}. "
            "Gebucht werden die GESPEICHERTEN Werte aus dem Journal, nicht die "
            "eben neu gemessenen. Sie können speichern wie es ist – das "
            "Diagnoseblatt im nächsten Schritt zeigt die Streuung über alle "
            "Aufnahmen – oder verwerfen und neu einlernen; die Aufnahmen "
            "bleiben unter data/verworfen/ erhalten.")

    def _waehle_artikel(self, nummer: str) -> None:
        for i in range(self.article_box.count()):
            if self.article_box.itemData(i) == nummer:
                self.article_box.setCurrentIndex(i)
                return

    def _sperre_artikelwahl(self) -> None:
        """Eine Session ist an ihren Artikel gebunden. Es gibt bewusst KEINEN
        eigenen Weg zum Wechseln – wer wechseln will, schließt den Dialog und
        beantwortet die Rückfrage. Ein dritter Knopf bildete nur dieselben zwei
        Fälle an anderer Stelle ab."""
        self.article_box.setEnabled(False)
        self.shots_spin.setEnabled(False)
        self.ref_label.setText(
            "Artikel ist für diese Session festgelegt — zum Wechseln Dialog "
            "schließen.")

    # ---------- Anzeige ----------

    def _n_shots(self) -> int:
        return self._session.info.n_shots if self._session else 0

    def _current_article_number(self) -> str | None:
        if self._session is not None:
            return self._session.info.article_number
        return self.article_box.currentData()

    def _article_changed(self) -> None:
        if self._session is not None:
            return                       # gesperrt, Text steht schon
        nr = self.article_box.currentData()
        info = next((a for a in self._articles if a.article_number == nr), None)
        if info is None:
            self.ref_label.setText("Keinen Artikel gewählt.")
        else:
            self.ref_label.setText(
                f"{info.n_references} Referenz(en) vorhanden – neue Aufnahmen "
                "kommen dazu.")
        self._update_texts()

    def _update_texts(self) -> None:
        n, target = self._n_shots(), self.shots_spin.value()
        busy = self._worker is not None or self._awaiting_frame
        if self._retake_index is not None:
            self.progress_label.setText(
                f"Aufnahme {self._retake_index + 1} wiederholen – Artikel "
                "neu ausrichten, dann „Aufnehmen“.")
        elif busy and self.progress_bar.isVisible():
            pass                          # Wiederherstellung schreibt selbst
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
        if self._session is None:
            nr = self.article_box.currentData()
            if nr is None:
                return
            # Die Session entsteht LAZY, beim ersten „Aufnehmen“: ein
            # geoeffneter und wieder geschlossener Dialog darf keinen leeren
            # Session-Ordner hinterlassen.
            from docodetect.pipeline import begin_enroll_session
            try:
                self._session = begin_enroll_session(
                    self.cfg, nr, target_shots=self.shots_spin.value())
            except Exception as e:                     # noqa: BLE001
                self.hint_label.setText(f"Session nicht angelegt: {e}")
                return
            self._sperre_artikelwahl()
        self._awaiting_frame = True
        self._update_texts()
        self.hint_label.setText("")
        self._frame_timer.start(_FRAME_TIMEOUT_MS)
        self.source.request_full_frame()

    def _on_full_frame(self, frame) -> None:
        if not self._awaiting_frame:
            return  # Frame gehörte einer Hauptfenster-Aktion
        self._frame_timer.stop()
        self._awaiting_frame = False
        self._start_worker(
            partial(_job_capture, frame, self.cfg, self._session,
                    self._retake_index),
            self._measure_done)

    def _frame_ausgeblieben(self) -> None:
        """Meldet einen ZUSTAND, keinen Fehler, und gibt den Knopf frei.

        Waehrend eines laufenden Reconnects kann keine endliche Grenze
        Fehlausloesungen vermeiden – deshalb behauptet der Timer nichts,
        sondern beendet nur das stumme Warten. Ohne ihn bliebe der Dialog
        dauerhaft „busy“: beide Knoepfe aus, keine Meldung. Genau die
        Bedienlage, aus der heraus jemand die App abschiesst."""
        if not self._awaiting_frame:
            return
        self._awaiting_frame = False
        self.hint_label.setText(
            f"Kamera nicht verbunden – Verbindung wird gesucht. "
            f"({self._kamera_fehler}) Erneut versuchen."
            if self._kamera_fehler else
            "Noch kein Bild von der Kamera erhalten – erneut versuchen.")
        self._update_texts()

    def _kamera_fehler_gesehen(self, text: str) -> None:
        self._kamera_fehler = text

    def _kamera_wieder_da(self) -> None:
        self._kamera_fehler = ""

    def _start_worker(self, job, on_done, *, with_progress: bool = False) -> None:
        w = PipelineWorker(job, self, with_progress=with_progress)
        w.finished_ok.connect(on_done)
        w.failed.connect(self._job_failed)
        w.finished.connect(w.deleteLater)
        w.finished.connect(self._worker_gone)
        if with_progress:
            w.progress.connect(self._progress)
        self._worker = w
        self._worker_start = time.monotonic()
        self._update_texts()
        w.start()

    def _progress(self, fertig: int, gesamt: int) -> None:
        self.progress_bar.setRange(0, gesamt)
        self.progress_bar.setValue(fertig)
        self.progress_label.setText(
            f"Aufnahme {fertig} von {gesamt} wird neu vermessen")

    def _worker_gone(self) -> None:
        self._worker = None
        self._update_texts()

    def _measure_done(self, result: dict) -> None:
        self._session = result["session"]
        self._thumbs[result["i"]] = result["thumb"]
        self._retake_index = None
        self._rebuild_thumbs()
        self._update_texts()

    def _job_failed(self, message: str) -> None:
        self._retake_index = None
        self.progress_bar.setVisible(False)
        # Fehlertext nennt die Abhilfe (z.B. Randberührung: weiter zur Mitte).
        self.hint_label.setText(f"Aufnahme verworfen: {message}")
        self._update_texts()

    def _rebuild_thumbs(self) -> None:
        self.thumbs.clear()
        if self._session is None:
            return
        for shot in self._session.shots:
            bild = self._thumbs.get(shot.i)
            icon = QIcon(QPixmap.fromImage(bild)) if bild is not None else QIcon()
            d = f"{shot.d_mm:.1f}".replace(".", ",")
            item = QListWidgetItem(icon, f"{shot.i + 1}: Ø {d} mm")
            item.setToolTip("Klicken und erneut „Aufnehmen“ ersetzt diese "
                            "Aufnahme.")
            self.thumbs.addItem(item)

    def _thumb_clicked(self, item: QListWidgetItem) -> None:
        self._retake_index = self.thumbs.row(item)
        self._update_texts()

    # ---------- Speichern ----------

    def _save(self) -> None:
        if self._session is None or self._n_shots() == 0:
            return
        self.hint_label.setText("Diagnoseblatt wird erstellt "
                                "(Segmentierung je Aufnahme) …")
        self._start_worker(partial(_job_sheet, self.cfg, self._session),
                           self._sheet_ready)

    def _sheet_ready(self, result: dict) -> None:
        """Blatt fertig -> Review-Dialog modal zeigen. exec() laeuft eine
        eigene Event-Schleife: der Render-Worker ist beim Rueckkehr sauber
        abgeraeumt, das naechste _start_worker also unkritisch."""
        from .enrollment_sheet_dialog import EnrollmentSheetDialog

        dlg = EnrollmentSheetDialog(result["sheet"], self)
        decision = dlg.exec()
        if decision == EnrollmentSheetDialog.UEBERNEHMEN:
            self.hint_label.setText("Speichern …")
            self._start_worker(
                partial(_job_commit, self.cfg, self._session, result["sheet"]),
                self._save_done)
        elif decision == EnrollmentSheetDialog.VERWERFEN:
            self.hint_label.setText("Verworfene Aufnahmen werden gesichert …")
            self._start_worker(
                partial(_job_discard, self.cfg, self._session, result["sheet"]),
                self._discard_done)
        else:
            self.hint_label.setText(
                "Prüfung abgebrochen – Aufnahmen bleiben, erneut „Speichern“.")
            self._update_texts()

    def _save_done(self, result: dict) -> None:
        self.saved_count = result["n"]
        if result.get("warn"):
            QMessageBox.warning(self, "Diagnoseblatt", result["warn"])
        self._session = None            # gebucht und weggeraeumt
        self.accept()

    def _discard_done(self, result: dict) -> None:
        """Verworfen: Aufnahmen sind gesichert (nicht in der DB). Dialog
        zuruecksetzen, damit direkt neu aufgenommen werden kann."""
        self._session = None
        self._thumbs.clear()
        self._retake_index = None
        self._rebuild_thumbs()
        self.article_box.setEnabled(True)
        self.shots_spin.setEnabled(True)
        self.hint_label.setText(
            f"Verworfen – {result['n']} Aufnahmen + Blatt gesichert unter "
            f"{result['dest']} (kein DB-Eintrag, nichts gelöscht).")
        self._article_changed()

    # ---------- Schliessen ----------

    def closeEvent(self, event) -> None:
        """Zwei getrennte Fragen: laeuft ein Worker, und liegen ungespeicherte
        Aufnahmen vor?

        Das Warten auf einen FRAME ist ausdruecklich KEIN laufender Worker —
        waehrend dessen ist der Dialog durchgehend schliessbar, und der
        6-s-Timer entsperrt ihn ohnehin."""
        if self._worker is not None and not self._darf_trotzdem_schliessen():
            event.ignore()
            return
        if self._session is not None and self._n_shots() > 0:
            if not self._abbrechen_beantwortet():
                event.ignore()
                return
        super().closeEvent(event)

    def _darf_trotzdem_schliessen(self) -> bool:
        """Schwelle, kein Schloss. Nach _SCHLIESSSCHUTZ_MS erscheint der
        Ausweg — erzwungenes Schliessen kostet nur den laufenden Job, weil die
        Aufnahmen im Journal liegen und die Session offen bleibt."""
        laeuft = (time.monotonic() - self._worker_start) * 1000
        if laeuft < _SCHLIESSSCHUTZ_MS:
            rest = int((_SCHLIESSSCHUTZ_MS - laeuft) / 1000)
            self.hint_label.setText(
                f"{self.progress_label.text()} — bitte noch einen Moment. "
                f"Die Aufnahmen sind bereits gesichert. "
                f"(Abbrechen ist in {rest} s möglich.)")
            return False
        antwort = QMessageBox.question(
            self, "Trotzdem schließen?",
            "Ein Vorgang läuft noch. Trotzdem schließen?\n\n"
            "Die Aufnahmen sind bereits gesichert — die Session bleibt offen "
            "und lässt sich später fortsetzen. Verloren geht nur der laufende "
            "Vorgang.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return antwort == QMessageBox.Yes

    def _abbrechen_beantwortet(self) -> bool:
        """Bewusstes Abbrechen hinterlaesst nur dann eine offene Session, wenn
        der Mensch das ausdruecklich waehlt. Vorbelegt ist VERWERFEN."""
        box = QMessageBox(self)
        box.setWindowTitle("Aufnahmen nicht gespeichert")
        box.setText(f"{self._n_shots()} Aufnahmen sind noch nicht gespeichert.")
        verwerfen = box.addButton("Verwerfen", QMessageBox.DestructiveRole)
        behalten = box.addButton("Für später behalten", QMessageBox.AcceptRole)
        weiter = box.addButton("Weiter aufnehmen", QMessageBox.RejectRole)
        box.setDefaultButton(verwerfen)
        box.exec()
        geklickt = box.clickedButton()
        if geklickt is weiter:
            return False
        if geklickt is behalten:
            return True                  # Session bleibt offen
        from docodetect.pipeline import discard_enroll_session
        try:
            discard_enroll_session(self.cfg, self._session)
        except Exception as e:                         # noqa: BLE001
            QMessageBox.warning(self, "Verwerfen", f"Nicht verworfen: {e}")
            return False
        self._session = None
        return True
