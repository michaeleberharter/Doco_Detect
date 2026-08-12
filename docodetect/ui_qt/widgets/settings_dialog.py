"""Einstellungsdialog: Kategorienliste links, Seiten rechts (modal).

Bewusst ein DIALOG und keine Vollseite im Hauptfenster: die Live-Vorschau
bleibt sichtbar, ein Theme-Wechsel wirkt sofort dahinter. Erreichbar über
das Zahnrad der Icon-Schiene; der frühere Direkt-Toggle ist ersetzt.

Persistenz — wichtigste Regel des Vorgangs (2026-08-12): Werte gehen
AUSSCHLIESSLICH nach QSettings (docodetect.ui_qt.settings). config.yaml
wird niemals geschrieben; „Auf Werksvorgabe zurücksetzen" löscht nur die
QSettings-Keys der Seite, der Wert fällt auf die config-Kette zurück.

Änderungen wirken SOFORT (kein OK/Abbrechen-Paar, nur „Schließen"):
Theme und Touch-Modus werden direkt angewandt, alles Übrige liest das
Hauptfenster über das `geaendert`-Signal nach. Zwei Einstellungen wirken
prinzipbedingt erst nach Neustart (QT_SCALE_FACTOR und QT_IM_MODULE stehen
vor der QApplication-Erzeugung): UI-Skalierung und der Tastatur-Anteil des
Touch-Modus. Beide sind einheitlich gekennzeichnet, und beim Schließen
erscheint ein Hinweis, wenn eine davon geändert wurde — kein Auto-Neustart.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QHBoxLayout,
                               QLabel, QListWidget, QMessageBox, QPushButton,
                               QSpinBox, QStackedWidget, QVBoxLayout, QWidget)

from .. import settings, touch
from ..app import apply_theme, ui_cfg
from ..hilfe import anker as hilfe_anker
from ..hilfe.fenster import HilfeLink
from .dialog_shell import DialogShell

_NEUSTART_MARKER = "wirksam nach Neustart"

_THEME_EINTRAEGE = (("Hell", "light"), ("Dunkel", "dark"),
                    ("System", "system"))


def _feld(titel: str, widget: QWidget, zusatz: str | None = None) -> QWidget:
    """Beschriftetes Feld im Stil der dialog_shell-Bausteine; `zusatz`
    (z.B. der Neustart-Marker) steht klein hinter dem Titel."""
    box = QWidget()
    box.setObjectName("cardBox")
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(4)
    text = titel.upper() + (f"   ({zusatz})" if zusatz else "")
    lbl = QLabel(text, box)
    lbl.setObjectName("fieldLabel")
    lay.addWidget(lbl)
    lay.addWidget(widget)
    return box


class _Seite(QWidget):
    """Eine Dialogseite: Felder oben, Reset unten. `keys` sind die
    QSettings-Keys, die der Reset dieser Seite löscht."""

    def __init__(self, keys: tuple, dialog: "SettingsDialog"):
        super().__init__()
        self._keys = keys
        self._dialog = dialog
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(12)

    def abschliessen(self) -> None:
        self.lay.addStretch(1)
        reset = QPushButton("Auf Werksvorgabe zurücksetzen")
        reset.setObjectName("secondaryButton")
        reset.setToolTip("Löscht die gespeicherten Werte dieser Seite — "
                         "es gilt wieder die Vorgabe der Konfiguration.")
        reset.clicked.connect(self._reset)
        self.lay.addWidget(reset, alignment=Qt.AlignLeft)

    def _reset(self) -> None:
        settings.zuruecksetzen(self._keys)
        self._dialog.neu_laden()


class SettingsDialog(DialogShell):
    """`geaendert` feuert nach jeder persistierten Änderung — das
    Hauptfenster liest dann settings.effective_ui neu."""

    geaendert = Signal()

    def __init__(self, cfg: dict, parent=None):
        super().__init__("gear", "Einstellungen", "Schließen", parent)
        self.cfg = cfg
        self._laden = False                 # Schreib-Guard beim Befüllen
        self.card.setMinimumWidth(680)

        eff = settings.effective_ui(cfg)
        # Neustart-Verfolgung: Stand beim Öffnen.
        self._start_scale = int(eff["scale_percent"])
        self._start_touch = bool(eff["touch_mode"])

        row = QHBoxLayout()
        row.setSpacing(14)
        self.kategorien = QListWidget()
        self.kategorien.setFixedWidth(170)
        self.kategorien.addItems(["Darstellung", "Rückmeldung", "Bedienung"])
        row.addWidget(self.kategorien)
        self.stack = QStackedWidget()
        row.addWidget(self.stack, stretch=1)
        self.body.addLayout(row)

        self._baue_darstellung()
        self._baue_rueckmeldung()
        self._baue_bedienung()
        self.kategorien.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.kategorien.setCurrentRow(0)

        self.cancel_button.setVisible(False)   # Änderungen wirken sofort —
        self.primary.connect(self.accept)      # es gibt nichts abzubrechen.
        self.neu_laden()

    # ---------- Seiten ----------

    def _baue_darstellung(self) -> None:
        seite = _Seite((settings.KEY_THEME, settings.KEY_SCALE,
                        settings.KEY_OVERLAY_SECS), self)

        self.theme_box = QComboBox()
        for label, wert in _THEME_EINTRAEGE:
            self.theme_box.addItem(label, wert)
        self.theme_box.currentIndexChanged.connect(self._theme_gewaehlt)
        seite.lay.addWidget(_feld("Erscheinungsbild", self.theme_box))

        self.scale_box = QComboBox()
        self.scale_box.currentIndexChanged.connect(self._scale_gewaehlt)
        seite.lay.addWidget(_feld("UI-Skalierung", self.scale_box,
                                  zusatz=_NEUSTART_MARKER))
        self.scale_hinweis = QLabel("")
        self.scale_hinweis.setObjectName("dialogHint")
        self.scale_hinweis.setWordWrap(True)
        self.scale_hinweis.setVisible(False)
        seite.lay.addWidget(self.scale_hinweis)
        self.scale_hilfe = HilfeLink(self.cfg)
        seite.lay.addWidget(self.scale_hilfe, alignment=Qt.AlignLeft)

        self.overlay_spin = QSpinBox()
        self.overlay_spin.setRange(1, 30)
        self.overlay_spin.setSuffix(" s")
        # Erst der fertige Wert schreibt/synct — nicht jeder Tastendruck
        # (sonst liefe je Ziffer sync + geaendert + Fenster-Rekonfiguration).
        self.overlay_spin.setKeyboardTracking(False)
        self.overlay_spin.valueChanged.connect(
            lambda v: self._schreibe(settings.KEY_OVERLAY_SECS, int(v)))
        seite.lay.addWidget(_feld("Ergebnis-Standzeit", self.overlay_spin))

        seite.abschliessen()
        self.stack.addWidget(seite)

    def _baue_rueckmeldung(self) -> None:
        seite = _Seite((settings.KEY_CONFIRM_SOUND,), self)
        self.sound_check = QCheckBox("Bestätigungston bei automatischer "
                                     "Übernahme")
        self.sound_check.toggled.connect(
            lambda on: self._schreibe(settings.KEY_CONFIRM_SOUND, bool(on)))
        seite.lay.addWidget(_feld("Ton", self.sound_check))
        seite.abschliessen()
        self.stack.addWidget(seite)

    def _baue_bedienung(self) -> None:
        seite = _Seite((settings.KEY_VERDICT, settings.KEY_PAUSE_MIN,
                        settings.KEY_TOUCH), self)

        self.verdict_check = QCheckBox("Bewertungs-Buttons (Richtig/Falsch) "
                                       "anzeigen")
        self.verdict_check.toggled.connect(
            lambda on: self._schreibe(settings.KEY_VERDICT, bool(on)))
        seite.lay.addWidget(_feld("Bewertung", self.verdict_check))

        self.pause_spin = QSpinBox()
        self.pause_spin.setRange(0, 180)
        self.pause_spin.setSuffix(" min")
        self.pause_spin.setSpecialValueText("nie")
        self.pause_spin.setKeyboardTracking(False)   # wie overlay_spin
        self.pause_spin.setToolTip(
            "Hält nur die Vorschau-ANZEIGE an — Kamera und Messbereitschaft "
            "laufen weiter; jede Berührung oder Auslösung setzt fort.")
        self.pause_spin.valueChanged.connect(
            lambda v: self._schreibe(settings.KEY_PAUSE_MIN, int(v)))
        seite.lay.addWidget(_feld("Vorschau pausieren nach Inaktivität",
                                  self.pause_spin))

        self.touch_check = QCheckBox("Touch-Modus (Stationseigenschaft)")
        self.touch_check.toggled.connect(self._touch_gewaehlt)
        seite.lay.addWidget(_feld("Touch", self.touch_check))
        touch_info = QLabel(
            "Grössere Trefferflächen und kinetisches Scrollen wirken "
            f"sofort. Die Bildschirmtastatur ist erst {_NEUSTART_MARKER} "
            "aktiv (Artikelname beim Einlernen, Admin-Passwort).")
        touch_info.setObjectName("dialogHint")
        touch_info.setWordWrap(True)
        seite.lay.addWidget(touch_info)

        seite.abschliessen()
        self.stack.addWidget(seite)

    # ---------- Befüllen ----------

    def neu_laden(self) -> None:
        """Alle Controls aus den EFFEKTIVEN Werten befüllen (nach Reset und
        beim Öffnen) und die Wirkung sofort herstellen."""
        eff = settings.effective_ui(self.cfg)
        self._laden = True
        try:
            idx = self.theme_box.findData(eff["theme"])
            self.theme_box.setCurrentIndex(idx if idx >= 0 else
                                           self.theme_box.findData("dark"))
            self._fuelle_scale(eff)
            self.overlay_spin.setValue(int(eff["result_overlay_secs"]))
            self.sound_check.setChecked(bool(eff["confirm_sound"]))
            self.verdict_check.setChecked(bool(eff["verdict_buttons_visible"]))
            self.pause_spin.setValue(int(eff["preview_pause_minutes"]))
            self.touch_check.setChecked(bool(eff["touch_mode"]))
        finally:
            self._laden = False
        app = QApplication.instance()
        if app is not None:
            # Nur bei ABWEICHUNG anwenden: das blosse Öffnen des Dialogs
            # soll nicht app-weit Stylesheet+Repolish neu durchlaufen
            # (Review-Befund M5) — wohl aber einen Reset sichtbar machen.
            if app.property("docoThemeChoice") != eff["theme"]:
                apply_theme(app, eff["theme"])
            if touch.ist_aktiv(app) != bool(eff["touch_mode"]):
                touch.anwenden(app, bool(eff["touch_mode"]))
        self.geaendert.emit()

    def _fuelle_scale(self, eff: dict) -> None:
        """Nur anbietbare Stufen (Auflage 1): das skalierte Mindestfenster
        muss in die verfügbare Geometrie des Zielschirms passen. Ein
        gespeicherter, inzwischen zu grosser Wert wird NICHT angeboten,
        sondern als Hinweis benannt."""
        ui = ui_cfg(self.cfg)
        stufen = settings.erlaubte_skalierungen(
            ui["window_min_width"], ui["window_min_height"],
            *self._basis_geometrie())
        gespeichert = int(eff["scale_percent"])
        self.scale_box.clear()
        for s in stufen:
            self.scale_box.addItem(f"{s} %", s)
        idx = self.scale_box.findData(gespeichert)
        if idx >= 0:
            self.scale_box.setCurrentIndex(idx)
            self.scale_hinweis.setVisible(False)
            self.scale_hilfe.set_zustand(None)
        else:
            # Größten anbietbaren Wert ANZEIGEN, aber nichts schreiben —
            # gespeichert bleibt gespeichert, bis der Mensch neu wählt.
            self.scale_box.setCurrentIndex(self.scale_box.count() - 1)
            self.scale_hinweis.setText(
                f"Gespeichert sind {gespeichert} % — mehr, als dieser "
                "Bildschirm für die Mindestfenstergrösse zulässt. Beim "
                "nächsten Start gilt der gespeicherte Wert; hier wählbar "
                "sind nur passende Stufen.")
            self.scale_hinweis.setVisible(True)
            self.scale_hilfe.set_zustand(hilfe_anker.SETTINGS_SCALE_ZU_GROSS)

    def _basis_geometrie(self) -> tuple:
        """Verfügbare Zielschirm-Geometrie, zurückgerechnet auf 100 %:
        availableGeometry liefert bereits durch QT_SCALE_FACTOR geteilte
        Einheiten, also mit dem aktiven Faktor multiplizieren."""
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:                      # offscreen-Extremfall
            return (10 ** 6, 10 ** 6)
        avail = screen.availableGeometry()
        f = settings.aktueller_scale_faktor()
        return (avail.width() * f, avail.height() * f)

    # ---------- Änderungs-Handler ----------

    def _schreibe(self, key: str, wert) -> None:
        if self._laden:
            return
        settings.setze(key, wert)
        self.geaendert.emit()

    def _theme_gewaehlt(self) -> None:
        if self._laden:
            return
        wahl = self.theme_box.currentData()
        settings.setze(settings.KEY_THEME, wahl)
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, wahl)          # sofort, auch hinter dem Dialog
        self.geaendert.emit()

    def _scale_gewaehlt(self) -> None:
        if self._laden:
            return
        wert = self.scale_box.currentData()
        if wert is None:
            return
        settings.setze(settings.KEY_SCALE, int(wert))
        self.scale_hinweis.setVisible(False)
        self.scale_hilfe.set_zustand(None)
        self.geaendert.emit()

    def _touch_gewaehlt(self, on: bool) -> None:
        if self._laden:
            return
        settings.setze(settings.KEY_TOUCH, bool(on))
        app = QApplication.instance()
        if app is not None:
            touch.anwenden(app, bool(on))   # Layout sofort; Tastatur: Neustart
        self.geaendert.emit()

    # ---------- Schließen: Neustart-Hinweis ----------

    def _neustart_aenderungen(self) -> list:
        eff = settings.effective_ui(self.cfg)
        aus = []
        if int(eff["scale_percent"]) != self._start_scale:
            aus.append(f"UI-Skalierung {self._start_scale} % → "
                       f"{eff['scale_percent']} %")
        if bool(eff["touch_mode"]) != self._start_touch:
            aus.append("Bildschirmtastatur wird "
                       + ("aktiviert" if eff["touch_mode"] else "deaktiviert"))
        return aus

    def done(self, result: int) -> None:  # noqa: N802 (Qt-API)
        aenderungen = self._neustart_aenderungen()
        if aenderungen:
            QMessageBox.information(
                self, "Wirksam nach Neustart",
                "Diese Änderungen greifen erst beim nächsten Start der "
                "Anwendung:\n\n– " + "\n– ".join(aenderungen)
                + "\n\nDie Anwendung startet nicht automatisch neu.")
            # Hinweis nur einmal je Änderung: neuen Stand als Referenz merken.
            eff = settings.effective_ui(self.cfg)
            self._start_scale = int(eff["scale_percent"])
            self._start_touch = bool(eff["touch_mode"])
        super().done(result)
