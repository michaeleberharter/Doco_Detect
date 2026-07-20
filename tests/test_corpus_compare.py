"""Drei-Band-Logik: PASS / DRIFT / FAIL je Merkmal."""

import sys
from dataclasses import asdict
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.corpus.compare import (DRIFT, FAIL, PASS, QUANTUM, SOFT, band,
                                       compare_tier1, compare_tier2, worst_band)
from docodetect.features import Features
from docodetect.matcher import CandidateReport, MatchReport


def test_identical_values_pass():
    assert band("circle_diameter_mm", 190.5, 190.5) == PASS


def test_within_rounding_quantum_passes():
    assert band("circle_diameter_mm", 190.5, 190.504) == PASS


def test_beyond_quantum_but_within_soft_step_is_drift():
    assert band("circle_diameter_mm", 190.5, 190.6) == DRIFT


def test_beyond_soft_step_fails():
    assert band("circle_diameter_mm", 190.5, 190.8) == FAIL


def test_shape_features_use_the_tight_quantum():
    assert band("solidity", 0.6043, 0.60433) == PASS
    assert band("solidity", 0.6043, 0.6100) == DRIFT
    assert band("solidity", 0.6043, 0.6200) == FAIL


def test_quantum_table_matches_features_rounding():
    """Verankerung: die Quanten sind die halben Rundungsschritte aus
    docodetect/features.py:185-195. Aendert sich dort die Rundung, muss
    diese Tabelle mitgezogen werden — dieser Test macht das sichtbar."""
    assert QUANTUM["circle_diameter_mm"] == 0.005    # round(x, 2)
    assert QUANTUM["equiv_diameter_mm"] == 0.005     # round(x, 2)
    assert QUANTUM["perimeter_mm"] == 0.005          # round(x, 2)
    assert QUANTUM["area_mm2"] == 0.05               # round(x, 1)
    assert QUANTUM["circularity"] == 5e-05           # round(x, 4)
    assert QUANTUM["aspect_ratio"] == 5e-05          # round(x, 4)
    assert QUANTUM["solidity"] == 5e-05              # round(x, 4)
    assert QUANTUM["llr_margin"] == 5e-05
    assert QUANTUM["max_z_winner"] == 5e-05


def test_soft_step_for_tier2_floats_is_five_hundredths():
    assert SOFT["llr_margin"] == 0.05
    assert SOFT["max_z_winner"] == 0.05


def test_worst_band_reports_the_most_severe():
    from docodetect.corpus.compare import FieldDiff
    diffs = [FieldDiff("a", 1.0, 1.0, 0.0, PASS),
             FieldDiff("b", 1.0, 1.2, 0.2, DRIFT)]
    assert worst_band(diffs) == DRIFT
    diffs.append(FieldDiff("c", 1.0, 9.0, 8.0, FAIL))
    assert worst_band(diffs) == FAIL
    assert worst_band([]) == PASS


def _rep(decision, arts, llr=1.5, maxz=3.0, gate=True):
    return MatchReport(
        decision=decision, message="", gate_passed=gate,
        llr_margin=llr, max_z_winner=maxz,
        candidates=[CandidateReport(article_number=a, name=a, nominal_size_mm=1.0,
                                    height_mm=0.0, corrected_diameter_mm=1.0,
                                    geometry_error_mm=0.0, has_references=True,
                                    n_shots=9) for a in arts])


def test_tier2_identical_reports_all_pass():
    a = _rep("ambiguous", ["L1", "L5"])
    b = _rep("ambiguous", ["L1", "L5"])
    assert worst_band(compare_tier2(a, b)) == PASS


def test_tier2_decision_change_is_an_exact_fail():
    a = _rep("accept", ["L1"])
    b = _rep("ambiguous", ["L1"])
    diffs = compare_tier2(a, b)
    assert worst_band(diffs) == FAIL
    assert any(d.field == "decision" and d.band == FAIL for d in diffs)


def test_tier2_topk_reordering_is_an_exact_fail():
    a = _rep("ambiguous", ["L1", "L5"])
    b = _rep("ambiguous", ["L5", "L1"])
    assert any(d.field == "top_k" and d.band == FAIL for d in compare_tier2(a, b))


def test_tier2_gate_flip_is_an_exact_fail():
    a = _rep("accept", ["L1"], gate=True)
    b = _rep("accept", ["L1"], gate=False)
    assert any(d.field == "gate_passed" and d.band == FAIL
               for d in compare_tier2(a, b))


def test_tier2_small_margin_move_is_drift_not_failure():
    """Ohne Drei-Band-Logik waere Tier 2 implizit bit-exakt und wuerde beim
    ersten Bibliotheks-Update flaechendeckend kippen."""
    a = _rep("ambiguous", ["L1", "L5"], llr=1.5)
    b = _rep("ambiguous", ["L1", "L5"], llr=1.52)
    diffs = compare_tier2(a, b)
    assert worst_band(diffs) == DRIFT


def test_tier2_large_margin_move_fails():
    a = _rep("ambiguous", ["L1", "L5"], llr=1.5)
    b = _rep("ambiguous", ["L1", "L5"], llr=2.9)
    assert worst_band(compare_tier2(a, b)) == FAIL


def test_tier2_tolerates_missing_margin_on_single_candidate():
    a = _rep("accept", ["L1"], llr=None)
    b = _rep("accept", ["L1"], llr=None)
    assert worst_band(compare_tier2(a, b)) == PASS


# --- compare_tier1: Golden-Report gegen frische Messung -------------------

_TIER1_SKALAR_FELDER = ("equiv_diameter_mm", "circle_diameter_mm", "area_mm2",
                        "perimeter_mm", "circularity", "aspect_ratio",
                        "solidity", "mean_saturation")

# Ein Quadrat 0,0 bis 10,10 in Bildkoordinaten; cv2.contourArea davon ist
# exakt 100.0 (Shoelace-Formel fuer ein achsparalleles Quadrat).
_SQUARE_CONTOUR = [[0, 0], [0, 10], [10, 10], [10, 0]]


def _square_area_px() -> float:
    import cv2
    import numpy as np
    pts = np.asarray(_SQUARE_CONTOUR, dtype=np.int32).reshape(-1, 1, 2)
    return float(cv2.contourArea(pts))


def _features(**overrides) -> Features:
    """Vollstaendiges Features-Objekt mit plausiblen Default-Werten."""
    defaults = dict(
        equiv_diameter_mm=190.50,
        circle_diameter_mm=192.00,
        area_mm2=2850.0,
        perimeter_mm=600.00,
        circularity=0.9500,
        aspect_ratio=0.9900,
        mean_hsv=[10.0, 50.0, 200.0],
        hue_hist=[1.0 / 32] * 32,
        mean_saturation=45.00,
        hu_moments=[1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0],
        solidity=0.9800,
        lab_center=[70.0, 5.0, 10.0],
        lab_rim=[60.0, 3.0, 8.0],
        hs_hist_center=[0.1] * 10,
        hs_hist_rim=[0.1] * 10,
    )
    defaults.update(overrides)
    return Features(**defaults)


def _golden_report(features: Features, contour=None, centroid_px=None) -> MatchReport:
    """Golden-MatchReport mit `measured` = asdict(features), wie ihn enroll/
    match tatsaechlich schreiben (docodetect/matcher.py:249,354)."""
    return MatchReport(decision="accept", message="", gate_passed=True,
                       measured=asdict(features), contour=contour,
                       centroid_px=centroid_px)


def test_tier1_identical_features_all_scalars_pass():
    feats = _features()
    golden = _golden_report(feats)
    diffs = compare_tier1(golden, feats)
    skalar_diffs = [d for d in diffs if d.field in _TIER1_SKALAR_FELDER]
    assert len(skalar_diffs) == 8
    assert all(d.band == PASS for d in skalar_diffs)


def test_tier1_scalar_just_above_quantum_is_drift():
    golden = _golden_report(_features())
    actual = _features(circle_diameter_mm=192.00 + 0.01)  # > 0.005, <= 0.2
    diffs = compare_tier1(golden, actual)
    d = next(d for d in diffs if d.field == "circle_diameter_mm")
    assert d.band == DRIFT


def test_tier1_scalar_beyond_soft_step_fails():
    golden = _golden_report(_features())
    actual = _features(circle_diameter_mm=192.00 + 1.0)  # > 0.2 (SOFT)
    diffs = compare_tier1(golden, actual)
    d = next(d for d in diffs if d.field == "circle_diameter_mm")
    assert d.band == FAIL


def test_tier1_vector_finds_the_largest_single_component_deviation():
    golden = _golden_report(_features())
    # Nur die Saettigung (Index 1) weicht ab, H und V bleiben identisch.
    actual = _features(mean_hsv=[10.0, 50.0 + 0.3, 200.0])
    diffs = compare_tier1(golden, actual)
    d = next(d for d in diffs if d.field == "mean_hsv")
    assert d.golden == 50.0
    assert d.actual == pytest.approx(50.3)
    assert d.band == DRIFT  # 0.3 liegt zwischen QUANTUM (0.005) und SOFT (0.5)


def test_tier1_vector_length_mismatch_fails():
    golden = _golden_report(_features())
    actual = _features(hu_moments=[1.0, 2.0, 3.0, 4.0, 5.0, 6.0])  # 6 statt 7
    diffs = compare_tier1(golden, actual)
    d = next(d for d in diffs if d.field == "hu_moments")
    assert d.band == FAIL


def test_tier1_missing_golden_contour_but_replay_has_area_fails():
    """Befund 1: Segmentierung findet jetzt ein Objekt, wo der Golden keines
    hatte -> darf nicht stillschweigend uebersprungen werden."""
    feats = _features()
    golden = _golden_report(feats, contour=None)
    diffs = compare_tier1(golden, feats, seg_area_px=1234.0)
    d = next(d for d in diffs if d.field == "seg_area_px")
    assert d.band == FAIL


def test_tier1_golden_has_contour_but_replay_area_missing_fails():
    """Umgekehrter Fall von Befund 1: der Golden hatte ein Objekt, der Replay
    findet keines mehr."""
    feats = _features()
    golden = _golden_report(feats, contour=_SQUARE_CONTOUR)
    diffs = compare_tier1(golden, feats, seg_area_px=None)
    d = next(d for d in diffs if d.field == "seg_area_px")
    assert d.band == FAIL


def test_tier1_missing_golden_centroid_but_replay_has_one_fails():
    feats = _features()
    golden = _golden_report(feats, centroid_px=None)
    diffs = compare_tier1(golden, feats, centroid=[12.0, 34.0])
    xy = [d for d in diffs if d.field in ("centroid_x", "centroid_y")]
    assert len(xy) == 2
    assert all(d.band == FAIL for d in xy)


def test_tier1_both_sides_without_segmentation_signal_is_no_finding():
    feats = _features()
    golden = _golden_report(feats, contour=None, centroid_px=None)
    diffs = compare_tier1(golden, feats, seg_area_px=None, centroid=None)
    fields = {d.field for d in diffs}
    assert "seg_area_px" not in fields
    assert "centroid_x" not in fields
    assert "centroid_y" not in fields


def test_tier1_matching_contour_and_centroid_pass():
    feats = _features()
    golden = _golden_report(feats, contour=_SQUARE_CONTOUR, centroid_px=[12.0, 34.0])
    diffs = compare_tier1(golden, feats, seg_area_px=_square_area_px(),
                          centroid=[12.0, 34.0])
    seg_diffs = [d for d in diffs
                if d.field in ("seg_area_px", "centroid_x", "centroid_y")]
    assert len(seg_diffs) == 3
    assert all(d.band == PASS for d in seg_diffs)
