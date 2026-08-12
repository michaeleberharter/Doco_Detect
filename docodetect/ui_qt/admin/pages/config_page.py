"""Config-Ansicht (Stufe 4, Spec Punkt 11): effektive Config als Baum,
je Key mit Herkunft — strikt read-only.

Es gibt KEINEN Schreibpfad und keinen Export: genau der Fehlermodus, der
zur Entfernung der Streamlit-UI führte (Spec Abschnitt 2). Die Herkunft
je Key kommt aus pipeline.config_with_origin (getrenntes Laden beider
YAML-Schichten auf Anzeige-Ebene); die Seite kennt keine Pfade.

Seit dem Einstellungsdialog (2026-08-12) gibt es über den YAML-Schichten
eine dritte: QSettings (Benutzer). Sie wird HIER auf Anzeige-Ebene über
die Zeilen gelegt — pipeline.config_with_origin bleibt unangetastet
(pipeline.py ist in dem Vorgang nur-lesend). Ohne das Overlay zeigte die
Seite nicht mehr die effektiven ui-Werte."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QLabel, QPushButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from docodetect.pipeline import config_with_origin

from ... import settings as ui_settings


class ConfigPage(QWidget):
    """Read-only-Baum der effektiven Config mit Herkunft je Key."""

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self._zeilen: list = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(8)
        self.hinweis = QLabel("")
        self.hinweis.setWordWrap(True)
        self.hinweis.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.hinweis)
        self.baum = QTreeWidget()
        self.baum.setColumnCount(3)
        self.baum.setHeaderLabels(["Key", "Wert", "Herkunft"])
        self.baum.setRootIsDecorated(True)
        lay.addWidget(self.baum, stretch=1)
        self.refresh_button = QPushButton("Aktualisieren")
        self.refresh_button.clicked.connect(self.reload)
        lay.addWidget(self.refresh_button, alignment=Qt.AlignLeft)
        self.reload()

    def reload(self) -> None:
        try:
            self._zeilen = self._mit_qsettings_ebene(
                list(config_with_origin()))
        except Exception as e:  # noqa: BLE001 — Anzeige, nie Crash
            self._zeilen = []
            self.baum.clear()
            self.hinweis.setText(f"Config nicht lesbar: {e}")
            return
        self.hinweis.setText(
            "Effektive Konfiguration, read-only — es gibt keinen "
            "Schreibpfad und keinen Export. Lokale Werte "
            "(config.local.yaml) überdecken die geteilte config.yaml; "
            "Bediener-Einstellungen (QSettings, Einstellungsdialog) "
            "überdecken beide im ui-Abschnitt.")
        self.baum.clear()
        gruppen: dict = {}
        for key, wert, herkunft in self._zeilen:
            sektion, _, rest = key.partition(".")
            eltern = gruppen.get(sektion)
            if eltern is None:
                eltern = QTreeWidgetItem(self.baum, [sektion, "", ""])
                gruppen[sektion] = eltern
            QTreeWidgetItem(eltern, [rest or sektion, wert, herkunft])
        self.baum.expandAll()
        for spalte in range(3):
            self.baum.resizeColumnToContents(spalte)

    @staticmethod
    def _mit_qsettings_ebene(zeilen: list) -> list:
        """QSettings-Overlay auf Anzeige-Ebene (nur ui.*-Keys):

        - gesetzter Key mit config-Gegenstück -> Wert ersetzt, Herkunft
          „QSettings (Benutzer)"
        - Dialog-Key ohne config-Zeile -> zusätzliche Zeile (gesetzter
          Wert oder Code-Werksvorgabe), damit die Ansicht die effektiven
          Werte VOLLSTÄNDIG zeigt. Der Nachtrag läuft über ALLE
          Dialog-Keys, nicht nur die vier neuen: fällt ein ui:-Key aus
          der config, bliebe sein Override sonst still unsichtbar."""
        gesetzt = ui_settings.gesetzte_ui_keys()
        vorhandene = set()
        out = []
        for key, wert, herkunft in zeilen:
            feld = key[3:] if key.startswith("ui.") else None
            if feld is not None:
                vorhandene.add(feld)
            if feld is not None and feld in gesetzt:
                out.append((key, str(gesetzt[feld]), "QSettings (Benutzer)"))
            else:
                out.append((key, wert, herkunft))
        for schluessel in ui_settings.ALLE_KEYS:
            feld = schluessel.split("/", 1)[1]
            if feld in vorhandene:
                continue
            if feld in gesetzt:
                out.append((f"ui.{feld}", str(gesetzt[feld]),
                            "QSettings (Benutzer)"))
            else:
                out.append((f"ui.{feld}",
                            str(ui_settings.werksvorgabe(schluessel)),
                            "Werksvorgabe (Code)"))
        return out

    # ---------- Testhilfen ----------

    def zeilen(self) -> list:
        return list(self._zeilen)

    def hinweis_text(self) -> str:
        return self.hinweis.text()
