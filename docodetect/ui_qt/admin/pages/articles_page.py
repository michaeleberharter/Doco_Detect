"""Artikel-Sektion (Stufe 3 Teil A): Liste, rein anzeigend.

Stammdaten + Referenzzahl über pipeline.list_articles; dazu als eigene
Spalte das WIRKSAME Vorfilter-Nominal (diameter_mm bei runden,
max(width, depth) bei länglichen Artikeln) samt Toleranzband aus
matching.diameter_tolerance_mm. Die Nominal-Regel kommt ausschließlich
aus pipeline.nominal_size_mm (= matcher._nominal_size_mm) — keine
Zweitimplementierung; der hypot-Fehler vom 2026-07-21 entstand genau so
(Freigabe-Ergänzung 3, 2026-08-11). Die Anzeige speist sich aus der
articles-Tabelle der DB — post-sync seit 2026-07-24 (CLAUDE.md
„Messgrößen"), der Vorfilter nutzt immer diese Stammdaten.

Diagnoseblätter sind Teil B (nach dem Neu-Enrollment) und hier bewusst
nicht enthalten. Synchron geladen: ein DB-Lesezugriff wie die
Status-Seite, kein Worker nötig."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from docodetect.pipeline import list_articles, nominal_size_mm

_SPALTEN = ["Artikelnummer", "Name", "Kategorie", "Referenzen", "Ø [mm]",
            "Breite [mm]", "Tiefe [mm]", "Höhe [mm]",
            "Vorfilter-Nominal [mm]", "Toleranzband [mm]"]


def _de(x, stellen: int = 1) -> str:
    """Dezimalkomma; None/fehlend als Gedankenstrich."""
    if x is None:
        return "—"
    return f"{x:.{stellen}f}".replace(".", ",")


class ArticlesPage(QWidget):
    """Sektion „Artikel" des Admin-Fensters (Spec Stufe 3, Teil A)."""

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self._zeilen: list = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(8)
        kopf = QHBoxLayout()
        self.refresh_button = QPushButton("Aktualisieren")
        self.refresh_button.clicked.connect(self.reload)
        kopf.addWidget(self.refresh_button, alignment=Qt.AlignLeft)
        self.kopf_label = QLabel("")
        self.kopf_label.setWordWrap(True)
        self.kopf_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        kopf.addWidget(self.kopf_label, stretch=1)
        lay.addLayout(kopf)
        self._tabelle = QTableWidget(0, len(_SPALTEN))
        self._tabelle.setHorizontalHeaderLabels(_SPALTEN)
        self._tabelle.verticalHeader().setVisible(False)
        self._tabelle.setEditTriggers(QTableWidget.NoEditTriggers)
        self._tabelle.setSelectionBehavior(QTableWidget.SelectRows)
        lay.addWidget(self._tabelle, stretch=1)
        self.reload()

    def reload(self) -> None:
        artikel = list_articles(self.cfg)
        tol = self.cfg.get("matching", {}).get("diameter_tolerance_mm")
        self._zeilen = []
        for a in artikel:
            nominal = nominal_size_mm(a)
            if nominal is not None and tol is not None:
                band = f"{_de(nominal - tol)} – {_de(nominal + tol)}"
            else:
                band = "—"
            self._zeilen.append({
                "artikelnummer": a.article_number, "name": a.name,
                "kategorie": a.category or "—",
                "referenzen": str(a.n_references),
                "durchmesser": _de(a.diameter_mm),
                "breite": _de(a.width_mm), "tiefe": _de(a.depth_mm),
                "hoehe": _de(a.height_mm),
                "nominal": _de(nominal), "band": band,
            })
        if self._zeilen:
            self.kopf_label.setText(
                f"{len(self._zeilen)} Artikel · Vorfilter-Toleranz "
                f"±{_de(tol)} mm (matching.diameter_tolerance_mm) · "
                "Nominal: Ø bei runden, max(Breite, Tiefe) bei länglichen "
                "Artikeln")
        else:
            self.kopf_label.setText(
                "Keine Artikel — erst anlegen (create-article) oder "
                "einlernen; ohne Datenbank bleibt die Liste leer.")
        self._tabelle.setRowCount(len(self._zeilen))
        reihenfolge = ("artikelnummer", "name", "kategorie", "referenzen",
                       "durchmesser", "breite", "tiefe", "hoehe",
                       "nominal", "band")
        for r, z in enumerate(self._zeilen):
            for c, key in enumerate(reihenfolge):
                self._tabelle.setItem(r, c, QTableWidgetItem(z[key]))
        self._tabelle.resizeColumnsToContents()

    # ---------- Testhilfen ----------

    def zeilen(self) -> list:
        return [dict(z) for z in self._zeilen]

    def kopf_text(self) -> str:
        return self.kopf_label.text()
