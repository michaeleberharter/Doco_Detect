"""Passwort-Gate des Admin-Bereichs (Spec Abschnitt 3).

Eine Dialogklasse, zwei Modi: Festlegen (Auth-Datei fehlt — zweimal
eingeben) und Prüfen. Kein Lockout: Fehlertext, Feld markiert, fertig.
Die Hash-Logik liegt Qt-frei in docodetect/admin_auth.py."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QLineEdit,
                               QVBoxLayout)

from docodetect import admin_auth


class AdminAuthDialog(QDialog):
    def __init__(self, festlegen: bool, parent=None,
                 auth_file: str | Path | None = None):
        super().__init__(parent)
        self._festlegen = festlegen
        self._auth_file = auth_file
        self.setWindowTitle("Admin-Passwort festlegen" if festlegen
                            else "Admin-Bereich")
        self.setMinimumWidth(360)
        lay = QVBoxLayout(self)
        hinweis = QLabel(
            "Erstes Öffnen: Admin-Passwort festlegen. Vergessen? Datei "
            f"{admin_auth.AUTH_FILE} löschen, dann neu vergeben."
            if festlegen else "Admin-Passwort eingeben.")
        hinweis.setWordWrap(True)
        lay.addWidget(hinweis)
        self.eingabe = QLineEdit()
        self.eingabe.setEchoMode(QLineEdit.Password)
        self.eingabe.setPlaceholderText("Passwort")
        lay.addWidget(self.eingabe)
        self.wiederholung = QLineEdit()
        self.wiederholung.setEchoMode(QLineEdit.Password)
        self.wiederholung.setPlaceholderText("Wiederholen")
        self.wiederholung.setVisible(festlegen)
        lay.addWidget(self.wiederholung)
        self.fehler = QLabel("")
        self.fehler.setObjectName("diagnoseLine")
        self.fehler.setWordWrap(True)
        lay.addWidget(self.fehler)
        knoepfe = QDialogButtonBox(QDialogButtonBox.Ok
                                   | QDialogButtonBox.Cancel)
        knoepfe.accepted.connect(self._ok)
        knoepfe.rejected.connect(self.reject)
        lay.addWidget(knoepfe)

    def _ok(self) -> None:
        pw = self.eingabe.text()
        if self._festlegen:
            if not pw:
                self.fehler.setText("Passwort darf nicht leer sein.")
                return
            if pw != self.wiederholung.text():
                self.fehler.setText("Passwörter stimmen nicht überein.")
                return
            admin_auth.set_password(pw, self._auth_file)
            self.accept()
            return
        if admin_auth.verify_password(pw, self._auth_file):
            self.accept()
        else:
            self.fehler.setText("Falsches Passwort.")   # kein Lockout
            self.eingabe.selectAll()
            self.eingabe.setFocus()


def ensure_admin_access(parent=None,
                        auth_file: str | Path | None = None) -> bool:
    """True = Zugang gewährt (Passwort neu gesetzt oder korrekt),
    False = abgebrochen. Kapselt beide Modi für das Hauptfenster."""
    dlg = AdminAuthDialog(not admin_auth.is_configured(auth_file),
                          parent, auth_file)
    return dlg.exec() == QDialog.Accepted
