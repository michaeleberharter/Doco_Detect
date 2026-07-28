"""Review-Dialog fuer STUFE 4: zeigt das bereits gerenderte Enrollment-
Diagnoseblatt in VOLLER Aufloesung und laesst VOR dem DB-Schreiben zwischen
Uebernehmen und Verwerfen entscheiden.

Bewusst KEIN DialogShell (der ist eine schmale, feste 480px-Karte fuer
Formulare): das Blatt ist ~3000x4300 px. In ein skaliertes Fensterchen
gequetscht waere die Heatmap unlesbar und die Entscheidung nicht treffbar.
Darum ein frei skalierbares/maximierbares Fenster mit ScrollArea (Bild in
nativer Aufloesung, scrollbar) plus „In externem Viewer oeffnen" (OS-Viewer,
fuers Zoomen).

Keine eigene Logik – nur Anzeige + Entscheidung. Das Blatt ist fertig
gerendert (pipeline.enrollment_sheet_for_shots), diese Klasse rechnet nichts.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QVBoxLayout)


class EnrollmentSheetDialog(QDialog):
    # eigene Ergebniscodes (0 = Rejected = Fenster geschlossen -> zurueck)
    UEBERNEHMEN = 2
    VERWERFEN = 3

    def __init__(self, sheet_png: str, parent=None):
        super().__init__(parent)
        self._sheet_png = str(sheet_png)
        self.setWindowTitle("Enrollment prüfen – Übernehmen oder Verwerfen")
        self.setModal(True)
        self.resize(1120, 900)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        info = QLabel(
            "Diagnoseblatt in voller Auflösung – scrollen; für Zoom „In "
            "externem Viewer öffnen“. Danach: Übernehmen speichert die "
            "Referenzen, Verwerfen sichert die Aufnahmen ohne DB-Eintrag.")
        info.setWordWrap(True)
        lay.addWidget(info)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(False)     # native Aufloesung -> scrollbar
        pix = QPixmap(self._sheet_png)
        self._image = QLabel(scroll)
        self._image.setPixmap(pix)           # NICHT skaliert
        self._image.resize(pix.size())
        scroll.setWidget(self._image)
        lay.addWidget(scroll, stretch=1)

        row = QHBoxLayout()
        open_btn = QPushButton("In externem Viewer öffnen")
        open_btn.clicked.connect(self._open_external)
        row.addWidget(open_btn)
        row.addStretch(1)
        discard_btn = QPushButton("Verwerfen")
        discard_btn.setObjectName("secondaryButton")
        discard_btn.clicked.connect(lambda: self.done(self.VERWERFEN))
        row.addWidget(discard_btn)
        keep_btn = QPushButton("Übernehmen")
        keep_btn.setObjectName("primaryButton")
        keep_btn.setDefault(True)
        keep_btn.clicked.connect(lambda: self.done(self.UEBERNEHMEN))
        row.addWidget(keep_btn)
        lay.addLayout(row)

    def _open_external(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(self._sheet_png))
