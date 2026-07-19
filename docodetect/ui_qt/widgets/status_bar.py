"""Statusleisten-Inhalt: Kamera/FPS · Kalibrierstatus · Artikel · Stufe 2.

Reine Anzeige – die Werte kommen aus pipeline.get_status() bzw. vom
CameraWorker (Phase 4). Deutsches Zahlenformat (0,171 mm/px) wie im Plan.
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from docodetect.pipeline import PipelineStatus


def _de(num: float, digits: int = 3) -> str:
    """Deutsches Dezimalkomma ohne locale-Abhängigkeit."""
    return f"{num:.{digits}f}".replace(".", ",")


class StatusBarContent(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 2, 8, 2)
        lay.setSpacing(0)
        self.camera = QLabel("Kamera –")
        self.calibration = QLabel("")
        self.articles = QLabel("")
        self.stage2 = QLabel("")
        self.warn = QLabel("")            # z.B. „Fokus-Lock nicht verfügbar“
        self.warn.setObjectName("statusWarn")
        self.warn.hide()
        for i, w in enumerate((self.camera, self.calibration, self.articles,
                               self.stage2)):
            if i:
                lay.addWidget(QLabel("  ·  "))
            lay.addWidget(w)
        lay.addStretch(1)
        lay.addWidget(self.warn)

    def set_camera_text(self, text: str) -> None:
        self.camera.setText(text)

    def set_warning(self, text: str) -> None:
        """Dauerhafter Warnhinweis rechts (leer = ausblenden)."""
        self.warn.setText(text)
        self.warn.setVisible(bool(text))

    def update_status(self, st: PipelineStatus) -> None:
        if st.calibrated:
            when = datetime.fromtimestamp(st.calibrated_unix).strftime("%d.%m.")
            self.calibration.setText(
                f"Kalibriert {when} ({_de(st.mm_per_px)} mm/px)")
        else:
            self.calibration.setText("Nicht kalibriert")
        self.articles.setText(
            f"{st.article_count} Artikel"
            f" ({st.articles_with_references} eingelernt)")
        self.stage2.setText("S2 an" if st.stage2_enabled else "S2 aus")
