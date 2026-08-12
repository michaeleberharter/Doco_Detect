"""Config-Ansicht (Stufe 4, Spec Punkt 11): effektive Config als Baum,
je Key mit Herkunft — strikt read-only.

Es gibt KEINEN Schreibpfad und keinen Export: genau der Fehlermodus, der
zur Entfernung der Streamlit-UI führte (Spec Abschnitt 2). Die Herkunft
je Key kommt aus pipeline.config_with_origin (getrenntes Laden beider
YAML-Schichten auf Anzeige-Ebene); die Seite kennt keine Pfade."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QLabel, QPushButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from docodetect.pipeline import config_with_origin


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
            self._zeilen = list(config_with_origin())
        except Exception as e:  # noqa: BLE001 — Anzeige, nie Crash
            self._zeilen = []
            self.baum.clear()
            self.hinweis.setText(f"Config nicht lesbar: {e}")
            return
        self.hinweis.setText(
            "Effektive Konfiguration, read-only — es gibt keinen "
            "Schreibpfad und keinen Export. Lokale Werte "
            "(config.local.yaml) überdecken die geteilte config.yaml.")
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

    # ---------- Testhilfen ----------

    def zeilen(self) -> list:
        return list(self._zeilen)

    def hinweis_text(self) -> str:
        return self.hinweis.text()
