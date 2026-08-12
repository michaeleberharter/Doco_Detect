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

from docodetect.pipeline import (list_articles, min_shots_floor,
                                 nominal_size_mm, reference_statistics)

from ...widgets.common import section_label

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
        # Dynamischer Anker: leere Liste -> „Artikel wird nie erkannt",
        # sonst Einlern-Qualität (Kennzahlen-Marker); gesetzt in reload().
        from ...hilfe.fenster import HilfeLink
        self.hilfe_link = HilfeLink(cfg, text="Hilfe")
        kopf.addWidget(self.hilfe_link, alignment=Qt.AlignLeft)
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
        self._tabelle.currentCellChanged.connect(
            lambda *_: self._zeige_detail())
        lay.addWidget(self._tabelle, stretch=1)

        # --- Referenz-Kennzahlen (Stufe 3 Teil B1, Freigabe 2026-08-11):
        # Enrollment-Statistik aus reference_stats, KEINE Bilder (B2).
        lay.addWidget(section_label("Referenz-Kennzahlen (Enrollment)"))
        self.detail_kopf = QLabel("Artikel auswählen — zeigt Streuung der "
                                  "eingelernten Shots (unzuverlässiges "
                                  "Enrollment erkennen).")
        self.detail_kopf.setWordWrap(True)
        self.detail_kopf.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.detail_kopf)
        detail_zeile = QHBoxLayout()
        self._skalar_tabelle = QTableWidget(0, 3)
        self._skalar_tabelle.setHorizontalHeaderLabels(
            ["Merkmal", "Mittel", "σ_enroll"])
        self._kanal_tabelle = QTableWidget(0, 2)
        self._kanal_tabelle.setHorizontalHeaderLabels(
            ["Distanzkanal", "proto_std"])
        for t in (self._skalar_tabelle, self._kanal_tabelle):
            t.verticalHeader().setVisible(False)
            t.setEditTriggers(QTableWidget.NoEditTriggers)
            t.setMaximumHeight(190)
            detail_zeile.addWidget(t)
        lay.addLayout(detail_zeile)
        self._detail: dict = {}
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
        from ...hilfe import anker as hilfe_anker
        if self._zeilen:
            self.kopf_label.setText(
                f"{len(self._zeilen)} Artikel · Vorfilter-Toleranz "
                f"±{_de(tol)} mm (matching.diameter_tolerance_mm) · "
                "Nominal: Ø bei runden, max(Breite, Tiefe) bei länglichen "
                "Artikeln")
            self.hilfe_link.set_zustand(hilfe_anker.ADMIN_ARTIKEL_QUALITAET)
        else:
            self.kopf_label.setText(
                "Keine Artikel — erst anlegen (create-article) oder "
                "einlernen; ohne Datenbank bleibt die Liste leer.")
            self.hilfe_link.set_zustand(hilfe_anker.ADMIN_ARTIKEL_LEER)
        self._tabelle.setRowCount(len(self._zeilen))
        reihenfolge = ("artikelnummer", "name", "kategorie", "referenzen",
                       "durchmesser", "breite", "tiefe", "hoehe",
                       "nominal", "band")
        for r, z in enumerate(self._zeilen):
            for c, key in enumerate(reihenfolge):
                self._tabelle.setItem(r, c, QTableWidgetItem(z[key]))
        self._tabelle.resizeColumnsToContents()

    # ---------- Referenz-Kennzahlen (Teil B1) ----------

    def _zeige_detail(self) -> None:
        row = self._tabelle.currentRow()
        if not (0 <= row < len(self._zeilen)):
            self._detail = {}
            return
        artikel = self._zeilen[row]["artikelnummer"]
        stats = reference_statistics(self.cfg, artikel)
        skalare, kanaele, marker = [], [], []
        n = 0
        if stats is None:
            marker.append("keine Enrollment-Statistik (nie eingelernt "
                          "oder DB fehlt)")
        else:
            n = stats.n_shots
            min_n = min_shots_floor()
            if n < min_n:
                marker.append(f"n={n} < {min_n} — Floor-Schätzung "
                              "unsicher (MIN_N der Floor-Analyse)")
            null_sigma = [m for m, s in sorted(stats.scalar_std.items())
                          if s == 0.0 and n > 1]
            if null_sigma:
                marker.append("σ=0 bei n>1 (" + ", ".join(null_sigma)
                              + ") — verdächtig: identische Shots?")
            for m in sorted(stats.scalar_mean):
                skalare.append({
                    "merkmal": m,
                    "mittel": _de(stats.scalar_mean[m], 2),
                    "sigma": _de(stats.scalar_std.get(m), 2)})
            for k in sorted(stats.proto_std):
                kanaele.append({"kanal": k,
                                "std": _de(stats.proto_std[k], 3)})
        self._detail = {"artikel": artikel, "n_shots": n,
                        "marker": " · ".join(marker) if marker else "—",
                        "skalare": skalare, "kanaele": kanaele}
        kopf = f"{artikel} — {n} Shot(s)"
        if marker:
            kopf += " · " + " · ".join(marker)
        self.detail_kopf.setText(kopf)
        self._skalar_tabelle.setRowCount(len(skalare))
        for r, z in enumerate(skalare):
            for c, key in enumerate(("merkmal", "mittel", "sigma")):
                self._skalar_tabelle.setItem(r, c,
                                             QTableWidgetItem(z[key]))
        self._kanal_tabelle.setRowCount(len(kanaele))
        for r, z in enumerate(kanaele):
            self._kanal_tabelle.setItem(r, 0, QTableWidgetItem(z["kanal"]))
            self._kanal_tabelle.setItem(r, 1, QTableWidgetItem(z["std"]))
        for t in (self._skalar_tabelle, self._kanal_tabelle):
            t.resizeColumnsToContents()

    # ---------- Testhilfen ----------

    def zeilen(self) -> list:
        return [dict(z) for z in self._zeilen]

    def kopf_text(self) -> str:
        return self.kopf_label.text()

    def detail_werte(self) -> dict:
        return {"artikel": self._detail.get("artikel", ""),
                "n_shots": self._detail.get("n_shots", 0),
                "marker": self._detail.get("marker", ""),
                "skalare": [dict(z) for z in
                            self._detail.get("skalare", [])],
                "kanaele": [dict(z) for z in
                            self._detail.get("kanaele", [])]}
