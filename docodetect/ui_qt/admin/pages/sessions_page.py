"""Einlern-Sessions (Stufe 4, Spec Punkte 9+13): Anzeige + Aktionen.

Verwerfen ist die EINZIGE bestandsverändernde Aktion des Panels und
ruft exakt die bestehenden Fassaden: plan_discard_enroll_session für
den Bestätigungsdialog (betroffene Pfade), discard_enroll_session für
die Ausführung (sichert nach data/verworfen/, löscht nichts) — kein
neuer Ablauf, kein zweiter Pfad (Spec Punkt 13). Die Ausführung läuft
im PipelineWorker (Dateibewegungen + DB, im Job konstruiert).

Fortsetzen delegiert an den BESTEHENDEN Einlern-Dialog des
Hauptfensters (Meldekanäle fortsetzen_pruefen/fortsetzen): nur bei
Zustand READY; sonst — oder ohne Anbindung — Hinweistext STATT Knopf."""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QMessageBox,
                               QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from docodetect.pipeline import (discard_enroll_session,
                                 list_enroll_sessions, load_enroll_session,
                                 plan_discard_enroll_session)

from ...pipeline_worker import PipelineWorker

_SPALTEN = ["Artikel", "angelegt", "Shots", "Zustand", "Fingerprint",
            "Alter"]
_OHNE_ANBINDUNG = ("Fortsetzen nur über das Hauptfenster verfügbar "
                   "(Admin ohne Dialog-Anbindung).")


def _alter_text(sekunden: float) -> str:
    if sekunden < 3600:
        return f"{sekunden / 60:.0f} min"
    if sekunden < 86400:
        return f"{sekunden / 3600:.1f} h".replace(".", ",")
    return f"{sekunden / 86400:.1f} Tage".replace(".", ",")


class SessionsPage(QWidget):
    """Tab „Einlern-Sessions" der Artikel-Sektion."""

    def __init__(self, cfg: dict,
                 fortsetzen_pruefen: Optional[Callable] = None,
                 fortsetzen: Optional[Callable] = None,
                 parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self._fortsetzen_pruefen = fortsetzen_pruefen
        self._fortsetzen = fortsetzen
        self._infos: list = []
        self._worker: PipelineWorker | None = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(8)
        self.hinweis = QLabel("")
        self.hinweis.setWordWrap(True)
        self.hinweis.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.hinweis)
        self.tabelle = QTableWidget(0, len(_SPALTEN))
        self.tabelle.setHorizontalHeaderLabels(_SPALTEN)
        self.tabelle.verticalHeader().setVisible(False)
        self.tabelle.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabelle.setSelectionBehavior(QTableWidget.SelectRows)
        self.tabelle.currentCellChanged.connect(
            lambda *_: self._update_buttons())
        lay.addWidget(self.tabelle, stretch=1)

        zeile = QHBoxLayout()
        self.verwerfen_button = QPushButton("Verwerfen …")
        self.verwerfen_button.clicked.connect(self.verwerfen)
        zeile.addWidget(self.verwerfen_button)
        self.fortsetzen_button = QPushButton("Fortsetzen")
        self.fortsetzen_button.clicked.connect(self.fortsetzen)
        zeile.addWidget(self.fortsetzen_button)
        self.fortsetzen_hinweis = QLabel("")
        self.fortsetzen_hinweis.setWordWrap(True)
        zeile.addWidget(self.fortsetzen_hinweis, stretch=1)
        lay.addLayout(zeile)
        self.refresh_button = QPushButton("Aktualisieren")
        self.refresh_button.clicked.connect(self.reload)
        lay.addWidget(self.refresh_button, alignment=Qt.AlignLeft)
        self.reload()

    # ---------- Laden ----------

    def reload(self) -> None:
        try:
            self._infos = list_enroll_sessions(self.cfg)
        except KeyError:
            # Schlanke Config (z. B. Demo/Test ohne enroll_sessions_dir):
            # Leerzustand statt Crash.
            self._infos = []
            self.tabelle.setRowCount(0)
            self.hinweis.setText("enroll_sessions_dir nicht konfiguriert "
                                 "— keine Session-Anzeige.")
            self._update_buttons()
            return
        self.tabelle.setRowCount(len(self._infos))
        for r, info in enumerate(self._infos):
            werte = [info.article_number, info.created,
                     f"{info.n_shots}/{info.target_shots}", info.zustand,
                     "ok" if info.fingerprint_ok else "abweichend",
                     _alter_text(info.age_secs)]
            for c, wert in enumerate(werte):
                self.tabelle.setItem(r, c, QTableWidgetItem(str(wert)))
        self.tabelle.resizeColumnsToContents()
        if not self._infos:
            self.hinweis.setText(
                "Keine offenen Einlern-Sessions — unterbrochene Sessions "
                "erscheinen hier automatisch.")
        else:
            self.hinweis.setText(f"{len(self._infos)} offene Session(s). "
                                 "Verwerfen sichert nach data/verworfen/ — "
                                 "es wird nie gelöscht.")
        self._update_buttons()

    def _auswahl(self):
        row = self.tabelle.currentRow()
        if 0 <= row < len(self._infos):
            return self._infos[row]
        return None

    def _update_buttons(self) -> None:
        gewaehlt = self._auswahl() is not None
        laeuft = self._worker is not None
        self.verwerfen_button.setEnabled(gewaehlt and not laeuft)
        if self._fortsetzen_pruefen is None or self._fortsetzen is None:
            self.fortsetzen_button.setVisible(False)
            self.fortsetzen_hinweis.setText(_OHNE_ANBINDUNG)
            return
        hinweis = self._fortsetzen_pruefen()
        if hinweis:
            # Spec Punkt 13: Hinweistext STATT Knopf.
            self.fortsetzen_button.setVisible(False)
            self.fortsetzen_hinweis.setText(hinweis)
        else:
            self.fortsetzen_button.setVisible(True)
            self.fortsetzen_button.setEnabled(gewaehlt and not laeuft)
            self.fortsetzen_hinweis.setText("")

    # ---------- Verwerfen (einzige bestandsverändernde Aktion) ----------

    def _bestaetigen(self, text: str) -> bool:
        """Dialog-Naht (monkeypatchbar): Bestätigung mit Pfaden."""
        antwort = QMessageBox.question(
            self, "Session verwerfen?", text,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return antwort == QMessageBox.Yes

    def verwerfen(self) -> None:
        info = self._auswahl()
        if info is None or self._worker is not None:
            return
        session = load_enroll_session(self.cfg, info.path)
        plan = plan_discard_enroll_session(self.cfg, session)
        zeilen = [f"Session-Ordner: {info.path}",
                  f"Artikel: {plan['article_number']} — "
                  f"{info.n_shots} Shot(s)",
                  f"Rückumzug: {plan['n']} Datei(en) aus dem "
                  "Referenz-Bereich zurück in die Session"]
        for e in plan["plan"][:4]:
            zeilen.append(f"  {e.get('aktion', '?')}: "
                          f"{e.get('ziel', '')} → {e.get('quelle', '')}")
        zeilen.append("Danach wird der VOLLSTÄNDIGE Ordner in den "
                      "Verworfen-Bereich verschoben (data/verworfen/, "
                      "Nachbar des Referenz-Ordners) — nichts wird "
                      "gelöscht.")
        if not self._bestaetigen("\n".join(zeilen)):
            return
        cfg = self.cfg
        pfad = info.path
        self.verwerfen_button.setEnabled(False)
        self.hinweis.setText("Verwerfe — Dateien werden gesichert …")
        w = PipelineWorker(
            lambda: discard_enroll_session(
                cfg, load_enroll_session(cfg, pfad)), self)
        w.finished_ok.connect(self._verworfen)
        w.failed.connect(self._verwerfen_fehler)
        w.finished.connect(self._worker_beendet)
        self._worker = w
        w.start()

    def _worker_beendet(self) -> None:
        if self._worker is not None:
            self._worker.deleteLater()
        self._worker = None
        self._update_buttons()

    def _verworfen(self, ziel) -> None:
        self.reload()
        self.hinweis.setText(f"Session verworfen, gesichert unter {ziel} "
                             "— nichts gelöscht.")

    def _verwerfen_fehler(self, text: str) -> None:
        self.reload()
        self.hinweis.setText(f"Verwerfen fehlgeschlagen: {text}")

    # ---------- Fortsetzen (Delegation, Spec Punkt 13) ----------

    def fortsetzen(self) -> None:
        info = self._auswahl()
        if (info is None or self._worker is not None
                or self._fortsetzen is None
                or self._fortsetzen_pruefen is None
                or self._fortsetzen_pruefen()):
            return
        self._fortsetzen(info)
        # Der Dialog lief modal im Hauptfenster; die Session kann jetzt
        # gebucht/verändert sein — Stand nachladen (Review 2026-08-11).
        self.reload()

    # ---------- Testhilfen ----------

    def zeilen(self) -> list:
        return [{"artikel": i.article_number,
                 "shots": f"{i.n_shots}/{i.target_shots}",
                 "zustand": i.zustand,
                 "fingerprint": "ok" if i.fingerprint_ok else "abweichend"}
                for i in self._infos]

    def hinweis_text(self) -> str:
        return self.hinweis.text()

    def fortsetzen_hinweis_text(self) -> str:
        return self.fortsetzen_hinweis.text()
