"""corpus-triage: Kategorisierung und Positions-Korrelation."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.corpus.triage import categorize, position_correlation
from docodetect.matcher import CandidateReport, MatchReport


def _golden(arts=("LOEFFEL-1",), label="LOEFFEL-1", decision="ambiguous"):
    return MatchReport(
        decision=decision, message="", label=label, verdict="wrong",
        candidates=[CandidateReport(article_number=a, name=a,
                                    nominal_size_mm=1.0, height_mm=0.0,
                                    corrected_diameter_mm=1.0,
                                    geometry_error_mm=0.0, has_references=True,
                                    n_shots=9) for a in arts])


def _fail(fields):
    return {"sha": "aa" * 32, "session": "s", "article": "A", "band": "fail",
            "error": None,
            "diffs": [{"field": f, "golden": 1.0, "actual": 2.0, "delta": 1.0,
                       "band": "fail"} for f in fields]}


def test_segmentation_change_wins_over_measurement_drift():
    """Aendert sich die Kontur, sind die Messwerte nur Folge — die
    Kategorie muss die Ursache benennen, nicht das Symptom."""
    got = categorize(_fail(["seg_area_px", "circle_diameter_mm"]), _golden())
    assert got == "segmentierungs_aenderung"


def test_pure_scalar_drift_is_measurement_drift():
    assert categorize(_fail(["circle_diameter_mm"]), _golden()) == "messwert_drift"


def test_gate_flip_is_its_own_category():
    assert categorize(_fail(["gate_passed"]), _golden()) == "gate_kipp"


def test_prefilter_kill_detected_when_truth_missing_from_candidates():
    """Kill = wahrer Artikel ueberlebte den Vorfilter nicht. Die
    Entscheidungs-Spalte ist dafuer NICHT der Schluessel."""
    g = _golden(arts=("LOEFFEL-5",), label="LOEFFEL-1")
    assert categorize(_fail(["top_k"]), g) == "vorfilter_kill"


def test_prefilter_kill_is_independent_of_the_decision():
    g = _golden(arts=("LOEFFEL-5",), label="LOEFFEL-1", decision="reject")
    assert categorize(_fail(["top_k"]), g) == "vorfilter_kill"


def test_label_suspicion_for_high_confidence_against_the_label():
    g = _golden(arts=("LOEFFEL-5",), label="LOEFFEL-1", decision="accept")
    g.candidates[0].posterior = 0.99
    g.gate_passed = True
    assert categorize(_fail([]), g) == "label_verdacht"


def test_pearson_finds_a_planted_relationship():
    """Je zentraler, desto kuerzer — die Signatur aus Spec 7.1."""
    from docodetect.corpus.triage import _pearson
    punkte = [{"dist": d, "delta": -8.0 + 0.02 * d} for d in range(0, 1000, 50)]
    r = _pearson([p["dist"] for p in punkte], [p["delta"] for p in punkte])
    assert r == pytest.approx(1.0, abs=1e-6)


def test_pearson_detects_the_inverse_relationship():
    from docodetect.corpus.triage import _pearson
    assert _pearson([0, 100, 200, 300], [-8.0, -6.0, -4.0, -2.0]) == pytest.approx(
        1.0, abs=1e-6)
    assert _pearson([0, 100, 200, 300], [-2.0, -4.0, -6.0, -8.0]) == pytest.approx(
        -1.0, abs=1e-6)


def test_pearson_is_zero_without_a_relationship():
    from docodetect.corpus.triage import _pearson
    assert _pearson([1, 2, 3], [5, 5, 5]) == 0.0


def test_pearson_handles_too_few_points():
    from docodetect.corpus.triage import _pearson
    assert _pearson([1.0], [2.0]) == 0.0
