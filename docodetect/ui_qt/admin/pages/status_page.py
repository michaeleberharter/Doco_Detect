"""System-Status (Melde-Punkt 1a): rein lesende Übersicht.

Zwei Gruppen mit bewusster Kennzeichnung (Spec Abschnitt 8): „Optik &
Bestand" ist gegen Quellen AUSSERHALB des Panels prüfbar (CLI, Datei-Hash),
„Umgebung" sind die ausgenommenen Umgebungsfakten — sie beschreiben die
Maschine, nicht die Messung. Kein Worker: get_status/list_articles/
optics_fingerprint sind schnelle Lesezugriffe; 1a startet keinen zweiten
Thread-Pfad (Spec Abschnitt 4)."""

from __future__ import annotations

import shutil
from datetime import datetime
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFormLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from docodetect.config import resolve
from docodetect.pipeline import (get_status, list_articles,
                                 optics_fingerprint)

from ...widgets.common import section_label


def _fmt_bytes(n: float) -> str:
    for einheit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {einheit}".replace(".", ",")
        n /= 1024.0
    return f"{n:.1f} TB".replace(".", ",")


def _zeit(unix: float) -> str:
    return datetime.fromtimestamp(unix).strftime("%d.%m.%Y %H:%M")


class StatusPage(QWidget):
    def __init__(self, cfg: dict, camera_status: Callable[[], str],
                 parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self._camera_status = camera_status
        self._werte: dict = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(10)
        lay.setAlignment(Qt.AlignTop)
        lay.addWidget(section_label("Optik & Bestand"))
        self._form_optik = QFormLayout()
        lay.addLayout(self._form_optik)
        lay.addWidget(section_label("Umgebung (ausgenommen — nicht "
                                    "extern prüfbar)"))
        self._form_umgebung = QFormLayout()
        lay.addLayout(self._form_umgebung)
        self.refresh_button = QPushButton("Aktualisieren")
        self.refresh_button.clicked.connect(self.refresh)
        lay.addWidget(self.refresh_button, alignment=Qt.AlignLeft)
        self.refresh()

    @staticmethod
    def _leere(form: QFormLayout) -> None:
        while form.rowCount():
            form.removeRow(0)

    def _zeile(self, form: QFormLayout, titel: str, wert: str) -> None:
        lab = QLabel(wert)
        lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lab.setWordWrap(True)
        form.addRow(QLabel(titel), lab)

    def refresh(self) -> None:
        st = get_status(self.cfg)
        artikel = list_articles(self.cfg)
        fp = optics_fingerprint(self.cfg)
        db = resolve(self.cfg["paths"]["db_file"])
        bg = resolve(self.cfg["calibration"]["background_file"])

        w = {}
        w["artikel"] = (f"{st.article_count} (davon "
                        f"{st.articles_with_references} mit Referenzen)")
        w["referenzen"] = str(sum(a.n_references for a in artikel))
        w["kalibriert"] = (_zeit(st.calibrated_unix)
                           if st.calibrated_unix else "nicht kalibriert")
        w["mm_per_px"] = (f"{st.mm_per_px:.4f}".replace(".", ",")
                          if st.mm_per_px else "–")
        if fp is None:
            w["fingerprint"] = "nicht kalibriert"
        else:
            w["calibration_sha256"] = fp["calibration_sha256"]
            w["background_sha256"] = fp["background_sha256"]
            w["features_cfg_sha256"] = fp["features_cfg_sha256"]
        w["db"] = (f"{db} ({_fmt_bytes(db.stat().st_size)})"
                   if db.exists() else f"{db} (fehlt)")
        wurzel = db.parent if db.parent.exists() else resolve(".")
        w["plattenplatz"] = _fmt_bytes(shutil.disk_usage(wurzel).free)
        w["hintergrund"] = (f"vorhanden, Stand {_zeit(bg.stat().st_mtime)}"
                            if bg.exists() else "fehlt")
        w["kamera"] = self._camera_status()
        w["sandbox"] = "aktiv" if self.cfg.get("sandbox") else "–"
        self._werte = w

        self._leere(self._form_optik)
        self._zeile(self._form_optik, "Artikel", w["artikel"])
        self._zeile(self._form_optik, "Referenzen gesamt", w["referenzen"])
        self._zeile(self._form_optik, "Kalibriert am", w["kalibriert"])
        self._zeile(self._form_optik, "mm/px", w["mm_per_px"])
        if fp is None:
            self._zeile(self._form_optik, "Optik-Fingerprint",
                        w["fingerprint"])
        else:
            self._zeile(self._form_optik, "Kalibrierung (sha256)",
                        w["calibration_sha256"])
            self._zeile(self._form_optik, "Hintergrund (sha256)",
                        w["background_sha256"])
            self._zeile(self._form_optik, "features-Config (sha256)",
                        w["features_cfg_sha256"])
        self._leere(self._form_umgebung)
        self._zeile(self._form_umgebung, "Datenbank", w["db"])
        self._zeile(self._form_umgebung, "Freier Plattenplatz",
                    w["plattenplatz"])
        self._zeile(self._form_umgebung, "Hintergrund-Datei",
                    w["hintergrund"])
        self._zeile(self._form_umgebung, "Kamera", w["kamera"])
        self._zeile(self._form_umgebung, "Sandbox", w["sandbox"])

    def werte(self) -> dict:
        """Testhilfe (Muster main_window.headline_text): rohe Werte."""
        return dict(self._werte)
