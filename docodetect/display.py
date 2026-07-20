"""Zentrale Anzeige-Helfer für ALLE UIs (Qt + Streamlit).

Eine Implementierung pro String — beide UIs zeigen exakt dieselben Texte
(deutsch, Dezimalkomma). UI-Code importiert diese Funktionen über
docodetect.pipeline (Re-Export), nie direkt Untermodule.

Anzeige-Mapping (Wire-Namen bleiben unangetastet, siehe Spec 2026-07-20):
accept -> "Automatisch übernommen", ambiguous -> "Bitte bestätigen",
reject -> "Kein Treffer".
"""

from __future__ import annotations

import math

from .matcher import CHANNELS, CandidateReport


def _de(x: float, nd: int = 1) -> str:
    """Zahl deutsch formatieren (Dezimalkomma)."""
    return f"{x:.{nd}f}".replace(".", ",")


def format_diameter(c: CandidateReport) -> str:
    """Kandidatenspezifischer mm-Wert — NIE ein globaler 'gemessener' Wert:
    derselbe Pixelkreis ergibt je Kandidat (Höhe!) einen anderen Ø."""
    if c.height_mm:
        return (f"Ø {_de(c.corrected_diameter_mm)} mm "
                f"(höhenkorrigiert, h = {_de(c.height_mm, 0)} mm)")
    return f"Ø {_de(c.corrected_diameter_mm)} mm (Bodenebene)"


def format_delta(c: CandidateReport, cfg: dict) -> str:
    tol = float(cfg["matching"]["diameter_tolerance_mm"])
    return f"Δ {_de(c.geometry_error_mm)} mm von ±{_de(tol)}"


def format_rank_line(c: CandidateReport, rank: int) -> str:
    return f"{rank}. {c.name} · {c.posterior * 100:.0f} %"


def channel_percentages(c: CandidateReport) -> dict:
    """Teilscore je Kanal als exp(Summe gewichteter Log-Beiträge) in (0,1]
    (1,0 = perfekte Übereinstimmung — ehrliche Likelihood-Darstellung).
    Kanäle ohne Merkmale (z. B. geometry-only-Kandidat) -> None, damit die
    UI ausgraut statt fälschlich 100 % zu zeigen."""
    by_feature = {f.feature: f.weighted for f in c.features}
    out = {}
    for ch, feats in CHANNELS.items():
        present = [by_feature[f] for f in feats if f in by_feature]
        out[ch] = math.exp(sum(present)) if present else None
    return out


def format_measured(measured: dict) -> str:
    """Rohmesswert-Diagnosezeile für NO_MATCH (kein Kandidat, also kein Ø
    aus format_diameter verfügbar) — dieselbe Zeile in Qt und Streamlit.
    Fehlende Keys werden wie bisher als 0 behandelt."""
    diameter = _de(measured.get("circle_diameter_mm", 0))
    circularity = _de(measured.get("circularity", 0), 2)
    area = f"{measured.get('area_mm2', 0) / 100:.0f}"
    return (f"Gemessen: Ø {diameter} mm (Bodenebene) · Rundheit {circularity} · "
            f"Fläche {area} cm²")


def headline(decision: str, best_name: str | None = None) -> tuple:
    """(Text, Statusklasse) für die Ergebnis-Überschrift beider UIs.
    Statusklasse: accept | confirm | reject (Farbsteuerung)."""
    if decision == "accept":
        text = ("✓ Automatisch übernommen" if not best_name
                else f"✓ Automatisch übernommen: {best_name}")
        return (text, "accept")
    if decision == "ambiguous":
        return ("Bitte bestätigen", "confirm")
    return ("Kein Treffer", "reject")
