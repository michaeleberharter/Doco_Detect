"""Dialog fuer unterbrochene Einlern-Sessions – VOR dem Einlerndialog.

Design: docs/superpowers/specs/2026-08-05-crashsichere-einlern-session-design.md
Abschnitt 5.1.

Warum ein EIGENER Dialog und kein Banner im Einlerndialog: eine unterbrochene
Session gehoert zu IHREM Artikel, die Artikel-Combo dort zeigt aber
irgendeinen. Ein Banner koppelt beides sichtbar aneinander und legt nahe,
"Fortsetzen" bezoege sich auf den gewaehlten Artikel.

Mehrere Sessions je Artikel sind zulaessig (zwei Abstuerze hintereinander) und
stehen als getrennte Zeilen, unterschieden durch Alter und Aufnahmezahl.
Vorausgewaehlt ist die neueste; ausgefuehrt wird IMMER die markierte – es gibt
keinen Automatismus, der bei Mehrdeutigkeit raet.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QPushButton)

from .dialog_shell import DialogShell


def alter_text(sekunden: float) -> str:
    if sekunden < 90:
        return f"vor {int(sekunden)} s"
    if sekunden < 5400:
        return f"vor {int(sekunden // 60)} min"
    if sekunden < 172800:
        return f"vor {int(sekunden // 3600)} h"
    return f"vor {int(sekunden // 86400)} Tagen"


class OpenSessionsDialog(DialogShell):
    """Rueckgabe ueber `entscheidung` und `gewaehlt`:

        FORTSETZEN | VERWERFEN | SPAETER

    SPAETER tut ausdruecklich NICHTS – die Sessions bleiben offen und
    erscheinen beim naechsten Mal wieder. Es ist kein Verwerfen.
    """

    FORTSETZEN = "fortsetzen"
    VERWERFEN = "verwerfen"
    SPAETER = "spaeter"

    def __init__(self, sessions: list, parent=None):
        super().__init__("plus", "Unterbrochene Einlern-Sessions",
                         "Fortsetzen", parent)
        self.sessions = list(sessions)
        self.entscheidung = self.SPAETER
        self.gewaehlt = None

        self.card.setMinimumWidth(620)
        lay = self.body

        hinweis = QLabel(
            f"{len(self.sessions)} Einlern-Session(s) wurden nicht "
            "abgeschlossen. Die Aufnahmen sind gesichert.")
        hinweis.setObjectName("guideLabel")
        hinweis.setWordWrap(True)
        lay.addWidget(hinweis)

        self.liste = QListWidget()
        self.liste.setMinimumHeight(150)
        for i in self.sessions:
            optik = ("Optik unverändert" if i.fingerprint_ok
                     else "⚠ Kalibrierung geändert")
            eintrag = QListWidgetItem(
                f"{i.article_number}   {i.n_shots} von {i.target_shots} "
                f"Aufnahmen   {alter_text(i.age_secs)}   {optik}")
            eintrag.setData(Qt.UserRole, i)
            if not i.fingerprint_ok:
                eintrag.setToolTip(
                    "Nicht fortsetzbar: die Aufnahmen entstanden unter einer "
                    "anderen Kalibrierung. Alte Kalibrierung aus dem "
                    f"optik/-Ordner der Session zurückholen, verwerfen, oder "
                    "unter dem aktuellen Zustand neu einlernen.")
            self.liste.addItem(eintrag)
        self.liste.setCurrentRow(0)          # neueste ist vorausgewählt
        self.liste.currentRowChanged.connect(self._auswahl_geaendert)
        lay.addWidget(self.liste)

        self.grund_label = QLabel("")
        self.grund_label.setObjectName("guideLabel")
        self.grund_label.setWordWrap(True)
        lay.addWidget(self.grund_label)

        zeile = QHBoxLayout()
        self.verwerfen_button = QPushButton("Verwerfen")
        self.verwerfen_button.clicked.connect(self._verwerfen)
        zeile.addWidget(self.verwerfen_button)
        self.spaeter_button = QPushButton("Später – neu einlernen")
        self.spaeter_button.clicked.connect(self._spaeter)
        zeile.addWidget(self.spaeter_button)
        zeile.addStretch(1)
        lay.addLayout(zeile)

        self.fortsetzen_button = self.primary_button
        self.primary.connect(self._fortsetzen)
        self._auswahl_geaendert(0)

    # ---------- Auswahl ----------

    def aktuelle(self):
        eintrag = self.liste.currentItem()
        return eintrag.data(Qt.UserRole) if eintrag is not None else None

    def _auswahl_geaendert(self, _row: int) -> None:
        """Bei abweichendem Fingerabdruck ist Fortsetzen ABGEBLENDET und der
        Grund steht in der Zeile – nicht erst in einer Fehlermeldung nach dem
        Klick."""
        i = self.aktuelle()
        fortsetzbar = bool(i is not None and i.fingerprint_ok)
        self.fortsetzen_button.setEnabled(fortsetzbar)
        self.verwerfen_button.setEnabled(i is not None)
        if i is None:
            self.grund_label.setText("")
        elif fortsetzbar:
            self.grund_label.setText(
                f"Fortsetzen misst die {i.n_shots} Aufnahmen neu "
                f"(etwa {max(1, i.n_shots)} s).")
        else:
            self.grund_label.setText(
                "Nicht fortsetzbar: die Kalibrierung hat sich seit dieser "
                "Session geändert. Die Aufnahmen entstanden unter einem "
                "anderen Optikzustand — sie jetzt zu buchen würde zwei "
                "Zustände vermischen. Alte Kalibrierung aus dem optik/-Ordner "
                "zurückholen, verwerfen, oder neu einlernen.")

    # ---------- Entscheidungen ----------

    def _fortsetzen(self) -> None:
        i = self.aktuelle()
        if i is None or not i.fingerprint_ok:
            return
        self.entscheidung, self.gewaehlt = self.FORTSETZEN, i
        self.accept()

    def _verwerfen(self) -> None:
        i = self.aktuelle()
        if i is None:
            return
        self.entscheidung, self.gewaehlt = self.VERWERFEN, i
        self.accept()

    def _spaeter(self) -> None:
        self.entscheidung, self.gewaehlt = self.SPAETER, None
        self.reject()
