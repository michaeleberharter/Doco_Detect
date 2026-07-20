"""Drei-Band-Logik: PASS / DRIFT / FAIL je Merkmal."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.corpus.compare import (DRIFT, FAIL, PASS, QUANTUM, SOFT, band,
                                       compare_tier2, worst_band)
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
