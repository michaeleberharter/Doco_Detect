"""Drei-Band-Vergleich Golden gegen Replay.

PASS  : Delta <= Rundungsquantum      -> nicht unterscheidbar
DRIFT : Quantum < Delta <= weiche Stufe -> messbar, aber klein
FAIL  : Delta > weiche Stufe            -> Regression

Auf gepinnter Umgebung ist JEDE Abweichung code-verursacht, deshalb bricht
`corpus-run --check` per Default auch bei DRIFT (siehe runner.py). Die
Trennung existiert fuer die zwei legitimen Ereignisse — bewusstes
Bibliotheks-Update und Plattformwechsel Mac->Windows — und damit die
Triage 'uniforme Drift' von 'Ausreisser' unterscheiden kann.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from ..pipeline import _thin_contour

PASS = "pass"
DRIFT = "drift"
FAIL = "fail"

_SCHWERE = {PASS: 0, DRIFT: 1, FAIL: 2}

# Halbe Rundungsschritte aus docodetect/features.py:185-195. Wird dort die
# Rundung geaendert, schlaegt tests/test_corpus_compare.py an.
QUANTUM = {
    "equiv_diameter_mm": 0.005,     # round(x, 2)
    "circle_diameter_mm": 0.005,    # round(x, 2)
    "perimeter_mm": 0.005,          # round(x, 2)
    "mean_saturation": 0.005,       # round(x, 2)
    "area_mm2": 0.05,               # round(x, 1)
    "circularity": 5e-05,           # round(x, 4)
    "aspect_ratio": 5e-05,          # round(x, 4)
    "solidity": 5e-05,              # round(x, 4)
    "hu_moments": 5e-05,            # round(x, 4), Vektor
    "mean_hsv": 0.005,              # round(x, 2), Vektor
    "hue_hist": 5e-07,              # round(x, 6), Vektor
    "hs_hist_center": 5e-07,
    "hs_hist_rim": 5e-07,
    "lab_center": 5e-04,            # round(x, 3), Vektor
    "lab_rim": 5e-04,
    # Segmentierungs-Signale: Pixelgroessen, ganzzahlig gefuehrt
    "seg_area_px": 0.5,
    "centroid_x": 0.05,
    "centroid_y": 0.05,
    # Tier-2-Gleitkommagroessen
    "llr_margin": 5e-05,
    "max_z_winner": 5e-05,
}

# Weiche Stufe: ab hier ist es keine Drift mehr, sondern eine Regression.
SOFT = {
    "equiv_diameter_mm": 0.2,
    "circle_diameter_mm": 0.2,
    "perimeter_mm": 0.5,
    "mean_saturation": 0.5,
    "area_mm2": 20.0,
    "circularity": 0.01,
    "aspect_ratio": 0.01,
    "solidity": 0.01,
    "hu_moments": 0.01,
    "mean_hsv": 0.5,
    "hue_hist": 0.001,
    "hs_hist_center": 0.001,
    "hs_hist_rim": 0.001,
    "lab_center": 0.05,
    "lab_rim": 0.05,
    "seg_area_px": 200.0,
    "centroid_x": 2.0,
    "centroid_y": 2.0,
    "llr_margin": 0.05,
    "max_z_winner": 0.05,
}

_QUANTUM_DEFAULT = 5e-05
_SOFT_DEFAULT = 0.01


@dataclass
class FieldDiff:
    field: str
    golden: object
    actual: object
    delta: float
    band: str


def band(field: str, golden: float, actual: float) -> str:
    delta = abs(float(actual) - float(golden))
    if delta <= QUANTUM.get(field, _QUANTUM_DEFAULT):
        return PASS
    return DRIFT if delta <= SOFT.get(field, _SOFT_DEFAULT) else FAIL


def worst_band(diffs: list) -> str:
    return max((d.band for d in diffs), key=lambda b: _SCHWERE[b], default=PASS)


def _scalar_diff(field: str, golden, actual) -> FieldDiff | None:
    if golden is None or actual is None:
        # Beide fehlen = kein Befund; nur eines fehlt = harte Aenderung.
        if golden is None and actual is None:
            return None
        return FieldDiff(field, golden, actual, float("nan"), FAIL)
    return FieldDiff(field, golden, actual, float(actual) - float(golden),
                     band(field, golden, actual))


def _vector_diff(field: str, golden, actual) -> FieldDiff | None:
    if not golden and not actual:
        return None
    golden, actual = list(golden or []), list(actual or [])
    if len(golden) != len(actual):
        return FieldDiff(field, f"len={len(golden)}", f"len={len(actual)}",
                         float("nan"), FAIL)
    if not golden:
        return None
    idx = max(range(len(golden)), key=lambda i: abs(actual[i] - golden[i]))
    d = actual[idx] - golden[idx]
    return FieldDiff(field, golden[idx], actual[idx], d,
                     band(field, golden[idx], actual[idx]))


_TIER1_SKALARE = ("equiv_diameter_mm", "circle_diameter_mm", "area_mm2",
                  "perimeter_mm", "circularity", "aspect_ratio", "solidity",
                  "mean_saturation")
_TIER1_VEKTOREN = ("mean_hsv", "hue_hist", "hu_moments", "lab_center",
                   "lab_rim", "hs_hist_center", "hs_hist_rim")


def compare_tier1(golden, measured, seg_contour=None,
                  centroid: list | None = None) -> list:
    """Golden-Report gegen eine frische Messung (Features + Segmentierung).

    `seg_contour` ist die VOLLE Replay-Kontur (SegmentationResult.contour).
    golden.contour ist dagegen bereits die von pipeline._thin_contour
    ausgeduennte Fassung, die auch im Report-JSON landet — ein Vergleich
    voll-gegen-ausgeduennt erzeugt einen reinen Ausduennungsfehler von ein
    paar Dutzend Pixeln (siehe Modul-Docstring/Aufgabenhistorie). Deshalb
    wird die Replay-Kontur hier mit DERSELBEN Funktion ausgeduennt, bevor
    die Flaechen verglichen werden: ausgeduennt gegen ausgeduennt.
    """
    gm = golden.measured or {}
    out = []
    for f in _TIER1_SKALARE:
        d = _scalar_diff(f, gm.get(f), getattr(measured, f, None))
        if d is not None:
            out.append(d)
    for f in _TIER1_VEKTOREN:
        d = _vector_diff(f, gm.get(f), getattr(measured, f, None))
        if d is not None:
            out.append(d)
    import cv2
    import numpy as np

    def _area_px(points) -> float:
        pts = np.asarray(points, dtype=np.int32).reshape(-1, 1, 2)
        return float(cv2.contourArea(pts))

    golden_area_px = _area_px(golden.contour) if golden.contour else None
    actual_area_px = None
    if seg_contour is not None:
        thin = _thin_contour(SimpleNamespace(
            contour=np.asarray(seg_contour, dtype=np.int32)))
        if thin:
            actual_area_px = _area_px(thin)
    d = _scalar_diff("seg_area_px", golden_area_px, actual_area_px)
    if d is not None:
        out.append(d)
    for name, i in (("centroid_x", 0), ("centroid_y", 1)):
        g = golden.centroid_px[i] if golden.centroid_px else None
        a = centroid[i] if centroid else None
        d = _scalar_diff(name, g, a)
        if d is not None:
            out.append(d)
    return out


def compare_tier2(golden, actual) -> list:
    """Golden-Report gegen einen frischen Replay-Report.

    decision, Top-k-Reihenfolge und gate_passed werden EXAKT verglichen —
    das sind die Groessen, an denen eine Fehlbuchung haengt. llr_margin und
    max_z_winner laufen ueber die Drei-Band-Logik.
    """
    out = []
    if golden.decision != actual.decision:
        out.append(FieldDiff("decision", golden.decision, actual.decision,
                             float("nan"), FAIL))
    g_top = [c.article_number for c in golden.candidates]
    a_top = [c.article_number for c in actual.candidates]
    if g_top != a_top:
        out.append(FieldDiff("top_k", ",".join(g_top) or "-",
                             ",".join(a_top) or "-", float("nan"), FAIL))
    if bool(golden.gate_passed) != bool(actual.gate_passed):
        out.append(FieldDiff("gate_passed", golden.gate_passed,
                             actual.gate_passed, float("nan"), FAIL))
    for f in ("llr_margin", "max_z_winner"):
        d = _scalar_diff(f, getattr(golden, f), getattr(actual, f))
        if d is not None:
            out.append(d)
    return out
