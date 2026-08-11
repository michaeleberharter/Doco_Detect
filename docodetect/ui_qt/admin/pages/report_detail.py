"""Einzelreport-Ansicht (Melde-Punkt 1b): die acht Felder der Spec.

Entscheidungs-Badge, Gate-Ampel, Aufnahme + Kontur-Overlay,
Kandidatentabelle, z je Merkmal (Sieger), Rohmesswerte, Prefilter-Kills,
Verdict-Zeile — alles aus EINEM MatchReport, nichts wird nachgerechnet
(Nachbau-Dokument 2026-08-01: „alles im Report-JSON"). Rendert Tabellen
und Labels; die Chart-Panels des alten Streamlit-Dialogs sind bewusst
nicht Teil von 1b (Spec Abschnitt 6, Punkt 4 nennt die acht Felder)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QScrollArea,
                               QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from docodetect.pipeline import (MatchReport, format_measured,
                                 render_report_overlay, report_judgement)

from ...widgets.common import section_label


def _de(x: float, stellen: int = 2) -> str:
    return f"{x:.{stellen}f}".replace(".", ",")


def kill_abstand_text(kill: dict) -> str:
    """Klartext für einen Prefilter-Kill — geteilte Formatierung mit der
    Kill-Sicht. reason='diameter': Abstand über der Ø-Toleranz;
    reason='area': prozentuale Flächenabweichung (Ø-Gate war bestanden)."""
    if kill.get("reason") == "area" and kill.get("area_error_pct") is not None:
        return (f"Fläche {kill['area_error_pct']:+.1f} % "
                "(Ø-Gate bestanden)").replace(".", ",")
    return (f"Ø {kill.get('over_tolerance_mm', 0):+.2f} mm über Toleranz "
            f"({_de(kill.get('tolerance_mm', 0), 1)} mm)").replace(".", ",")


def _tabelle(spalten: list, zeilen: list) -> QTableWidget:
    t = QTableWidget(len(zeilen), len(spalten))
    t.setHorizontalHeaderLabels(spalten)
    t.verticalHeader().setVisible(False)
    t.setEditTriggers(QTableWidget.NoEditTriggers)
    for r, zeile in enumerate(zeilen):
        for c, wert in enumerate(zeile):
            t.setItem(r, c, QTableWidgetItem(str(wert)))
    t.resizeColumnsToContents()
    t.setMinimumHeight(min(320, 40 + 26 * len(zeilen)))
    return t


class ReportDetailView(QWidget):
    """Reine Anzeige; `werte()` ist die Testhilfe mit den Rohwerten."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._werte: dict = {}
        aussen = QVBoxLayout(self)
        aussen.setContentsMargins(0, 0, 0, 0)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        aussen.addWidget(self._scroll)
        self._inhalt = None

    # ---------- Aufbau je Report ----------

    def set_report(self, pfad, report: MatchReport) -> None:
        self._werte = self._berechne(pfad, report)
        inhalt = QWidget()
        lay = QVBoxLayout(inhalt)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(10)
        lay.setAlignment(Qt.AlignTop)

        badge = QLabel(self._werte["badge"])
        badge.setObjectName("detailBadge")
        badge.setWordWrap(True)
        lay.addWidget(badge)

        lay.addWidget(section_label("Gate-Ampel"))
        gate = QLabel(f"max |z| Sieger: {self._werte['gate_max_z']}   ·   "
                      f"LLR-Margin: {self._werte['gate_margin']}   ·   "
                      f"Posterior Top-1: {self._werte['gate_posterior']}")
        gate.setWordWrap(True)
        lay.addWidget(gate)

        lay.addWidget(section_label("Aufnahme + Kontur-Overlay"))
        lay.addWidget(self._bild_widget(report))

        lay.addWidget(section_label("Rohmesswerte"))
        mess = QLabel(self._werte["messwerte"])
        mess.setWordWrap(True)
        lay.addWidget(mess)

        lay.addWidget(section_label("Kandidaten"))
        lay.addWidget(_tabelle(
            ["#", "Artikel", "Name", "Posterior", "log-Score", "max |z|",
             "Margin"],
            [[k["rang"], k["artikel"], k["name"], k["posterior"],
              k["log_score"], k["max_z"], k["margin"]]
             for k in self._werte["kandidaten"]]))

        lay.addWidget(section_label("z je Merkmal (Sieger)"))
        merkmale = self._werte["merkmale"]
        if merkmale:
            lay.addWidget(_tabelle(
                ["Merkmal", "Messwert", "Referenz", "Distanz", "σ_enroll",
                 "σ_eff", "z", "logL", "w_eff", "gewichtet"],
                [[m["merkmal"], m["messwert"], m["referenz"], m["distanz"],
                  m["sigma_enroll"], m["sigma_eff"], m["z"],
                  m["log_contrib"], m["w_eff"], m["gewichtet"]]
                 for m in merkmale]))
        else:
            lay.addWidget(QLabel("keine Merkmals-Scores (kein Kandidat "
                                 "oder nur Geometrie)"))

        lay.addWidget(section_label("Prefilter-Kills"))
        kills = self._werte["kills"]
        if isinstance(kills, str):
            lay.addWidget(QLabel(kills))
        else:
            lay.addWidget(_tabelle(
                ["Artikel", "Grund", "Abstand"],
                [[k["artikel"], k["grund"], k["abstand"]] for k in kills]))

        lay.addWidget(section_label("Bewertung"))
        lay.addWidget(QLabel(self._werte["verdict"]))

        self._scroll.setWidget(inhalt)
        self._inhalt = inhalt

    # ---------- Werte (Testhilfe + Renderquelle) ----------

    @staticmethod
    def _berechne(pfad, r: MatchReport) -> dict:
        w: dict = {}
        w["badge"] = f"{r.decision.upper()} — {r.message}" if r.message \
            else r.decision.upper()
        th = r.thresholds or {}
        if r.max_z_winner is None:
            w["gate_max_z"] = "–"
        else:
            gate = th.get("max_z_accept")
            w["gate_max_z"] = _de(r.max_z_winner) + (
                f" (Gate ≤ {_de(gate)})" if gate is not None else "")
        if r.llr_margin is None:
            w["gate_margin"] = ("∞ (1 Kandidat)" if len(r.candidates) == 1
                                else "–")
        else:
            mind = th.get("min_llr_margin")
            w["gate_margin"] = _de(r.llr_margin) + (
                f" (≥ {_de(mind)})" if mind is not None else "")
        w["gate_posterior"] = (f"{r.candidates[0].posterior * 100:.0f} %"
                               if r.candidates else "?")
        w["messwerte"] = format_measured(r.measured) if r.measured else "–"
        w["bild"] = ("vorhanden" if r.image_path
                     and Path(r.image_path).exists()
                     else "Bild nicht verfügbar.")
        w["kandidaten"] = [
            {"rang": i, "artikel": c.article_number, "name": c.name,
             "posterior": f"{c.posterior * 100:.0f} %",
             "log_score": _de(c.log_score),
             "max_z": _de(c.max_abs_z),
             "margin": (_de(c.margin_to_next)
                        if c.margin_to_next is not None else "–")}
            for i, c in enumerate(r.candidates, start=1)]
        sieger = r.candidates[0] if r.candidates else None
        w["merkmale"] = [
            {"merkmal": f.feature,
             "messwert": (_de(f.measured, 3) if f.measured is not None
                          else "–"),
             "referenz": (_de(f.reference, 3) if f.reference is not None
                          else "–"),
             "distanz": _de(f.distance, 3),
             "sigma_enroll": _de(f.sigma_enroll, 3),
             "sigma_eff": _de(f.sigma_eff, 3),
             "z": _de(f.z), "log_contrib": _de(f.log_contrib, 3),
             "w_eff": _de(f.w_eff, 3), "gewichtet": _de(f.weighted, 3)}
            for f in (sieger.features if sieger else [])]
        if r.prefiltered:
            w["kills"] = [{"artikel": k.get("article_number", "?"),
                           "grund": k.get("reason", "?"),
                           "abstand": kill_abstand_text(k)}
                          for k in r.prefiltered]
        else:
            w["kills"] = "keine protokolliert"
        urteil = report_judgement(r)
        text = {True: "Richtig", False: "Falsch", None: "unbewertet"}[urteil]
        w["verdict"] = text + (f" · Artikel: {r.label}" if r.label else "")
        return w

    def _bild_widget(self, r: MatchReport) -> QWidget:
        if self._werte["bild"] != "vorhanden":
            return QLabel(self._werte["bild"])
        import cv2

        from ...qimage import bgr_to_qimage, downscale_width
        from PySide6.QtGui import QPixmap

        img = cv2.imread(r.image_path)
        if img is None:
            self._werte["bild"] = "Bild nicht verfügbar."
            return QLabel(self._werte["bild"])
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        for variante in (img, render_report_overlay(img, r)):
            lab = QLabel()
            lab.setPixmap(QPixmap.fromImage(
                bgr_to_qimage(downscale_width(variante, 420))))
            lay.addWidget(lab)
        lay.addStretch(1)
        return w

    def werte(self) -> dict:
        return dict(self._werte)
