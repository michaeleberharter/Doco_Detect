"""Baseline, Wilson-Grenzen, Drift-Klassifikation, Exit-Codes."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.corpus.report import (check_against_baseline, classify_drift,
                                      tier2_quotas, wilson)
from docodetect.matcher import CandidateReport, MatchReport
from docodetect.reporting import NO_MATCH


def test_wilson_centre_matches_the_point_estimate():
    p, lo, hi = wilson(46, 60)
    assert p == pytest.approx(0.7667, abs=1e-4)
    assert lo < p < hi


def test_wilson_matches_the_published_phase_b_numbers():
    """Gegenprobe an reports/analysis/phase-b-korrigiert/metrics.json."""
    p, lo, hi = wilson(46, 60)
    assert lo == pytest.approx(0.6456, abs=5e-3)
    assert hi == pytest.approx(0.8556, abs=5e-3)


def test_wilson_handles_zero_events():
    p, lo, hi = wilson(0, 25)
    assert p == 0.0 and lo == 0.0 and hi == pytest.approx(0.1332, abs=5e-3)


def test_wilson_is_safe_for_empty_samples():
    assert wilson(0, 0) == (0.0, 0.0, 0.0)


def _r(band, sha, delta=0.0, field="circle_diameter_mm"):
    return {"sha": sha, "session": "s", "article": "A", "tier": 1, "band": band,
            "error": None,
            "diffs": [{"field": field, "golden": 1.0, "actual": 1.0 + delta,
                       "delta": delta, "band": band}]}


def test_classify_drift_reports_none_when_everything_passes():
    assert classify_drift([_r("pass", "a"), _r("pass", "b")])["muster"] == "keine"


def test_classify_drift_recognises_a_uniform_shift():
    """Gleichmaessige kleine Verschiebung ueber viele Bilder = Bibliothek
    oder Plattform, nicht Code."""
    res = [_r("drift", f"{i:02x}", delta=0.10) for i in range(20)]
    got = classify_drift(res)
    assert got["muster"] == "uniform"
    assert got["betroffen"] == 20


def test_classify_drift_recognises_outliers():
    res = [_r("pass", f"{i:02x}") for i in range(20)]
    res.append(_r("drift", "ff", delta=0.19))
    got = classify_drift(res)
    assert got["muster"] == "ausreisser"
    assert got["betroffen"] == 1


def _run(band_counts):
    results = []
    for band, n in band_counts.items():
        results += [_r(band, f"{band}{i}") for i in range(n)]
    return {"results": results, "tier": 1, "n": len(results)}


def test_check_passes_when_everything_passes():
    code, meldungen = check_against_baseline(
        _run({"pass": 10}), {}, {}, accept_drift=False)
    assert code == 0


def test_check_fails_on_drift_by_default():
    """Auf gepinnter Umgebung ist jede Abweichung code-verursacht."""
    code, meldungen = check_against_baseline(
        _run({"pass": 9, "drift": 1}), {}, {}, accept_drift=False)
    assert code == 1
    assert any("DRIFT" in m for m in meldungen)


def test_check_tolerates_drift_with_accept_drift():
    code, _ = check_against_baseline(
        _run({"pass": 9, "drift": 1}), {}, {}, accept_drift=True)
    assert code == 0


def test_check_always_fails_on_fail_even_with_accept_drift():
    code, _ = check_against_baseline(
        _run({"pass": 9, "fail": 1}), {}, {}, accept_drift=True)
    assert code == 1


def test_check_flags_a_quota_below_the_baseline_wilson_floor():
    baseline = {"quotas": {"accuracy_top1": {"k": 46, "n": 60, "p": 0.7667,
                                             "wilson_lo": 0.6456,
                                             "wilson_hi": 0.8556}}}
    quotas = {"accuracy_top1": {"k": 30, "n": 60, "p": 0.5,
                                "wilson_lo": 0.3773, "wilson_hi": 0.6227}}
    code, meldungen = check_against_baseline(
        _run({"pass": 10}), quotas, baseline, accept_drift=False)
    assert code == 1
    assert any("accuracy_top1" in m for m in meldungen)


def test_check_accepts_a_quota_inside_the_baseline_interval():
    baseline = {"quotas": {"accuracy_top1": {"k": 46, "n": 60, "p": 0.7667,
                                             "wilson_lo": 0.6456,
                                             "wilson_hi": 0.8556}}}
    quotas = {"accuracy_top1": {"k": 44, "n": 60, "p": 0.7333,
                                "wilson_lo": 0.6098, "wilson_hi": 0.8284}}
    code, _ = check_against_baseline(
        _run({"pass": 10}), quotas, baseline, accept_drift=False)
    assert code == 0


# ---- tier2_quotas(): accuracy_top1/top3 muessen mit analysis.py uebereinstimmen ----

def _cand(nr):
    return CandidateReport(article_number=nr, name=nr, nominal_size_mm=200.0,
                           height_mm=0.0, corrected_diameter_mm=200.0,
                           geometry_error_mm=0.0, has_references=True, n_shots=2)


def _report(decision="accept", label=None, verdict=None, cands=()):
    return MatchReport(decision=decision, message="", candidates=list(cands),
                       label=label, verdict=verdict)


def test_tier2_quotas_accuracy_top1_respects_a_gate_rejection_over_the_label():
    """Fall 1784562586318.png: Rang-1-Kandidat == Label, aber das z-Gate hat
    verworfen (verdict='wrong') -> zaehlt NICHT als Top-1-Treffer, obwohl der
    Rang stimmt. So bleibt die Zahl identisch mit dem analyze-Befehl, der
    ueber judgement() (menschliches Urteil vor Label-Vergleich) rechnet."""
    r = _report(decision="reject", label="LOEFFEL-9", verdict="wrong",
               cands=[_cand("LOEFFEL-9")])
    q = tier2_quotas([r])
    assert q["accuracy_top1"]["k"] == 0
    assert q["accuracy_top1"]["n"] == 1


def test_tier2_quotas_accuracy_top1_counts_a_correct_verdict():
    r = _report(decision="accept", label="LOEFFEL-9", verdict="correct",
               cands=[_cand("LOEFFEL-9")])
    q = tier2_quotas([r])
    assert q["accuracy_top1"]["k"] == 1
    assert q["accuracy_top1"]["n"] == 1


def test_tier2_quotas_accuracy_top1_falls_back_to_the_label_without_a_verdict():
    r = _report(decision="accept", label="LOEFFEL-9", verdict=None,
               cands=[_cand("LOEFFEL-9")])
    q = tier2_quotas([r])
    assert q["accuracy_top1"]["k"] == 1
    assert q["accuracy_top1"]["n"] == 1


def test_tier2_quotas_accuracy_top1_ignores_reports_without_verdict_or_label():
    r = _report(decision="reject", label=None, verdict=None, cands=[])
    q = tier2_quotas([r])
    assert q["accuracy_top1"]["k"] == 0
    assert q["accuracy_top1"]["n"] == 0


def test_tier2_quotas_accuracy_top3_counts_a_correctly_rejected_no_match():
    """Kein Kandidat UND label == NO_MATCH zaehlt als Top-3-Treffer – der
    Sonderfall aus analysis.py, den top_k_accuracy() nicht kennt."""
    r = _report(decision="reject", label=NO_MATCH, verdict=None, cands=[])
    q = tier2_quotas([r])
    assert q["accuracy_top3"]["k"] == 1
    assert q["accuracy_top3"]["n"] == 1
