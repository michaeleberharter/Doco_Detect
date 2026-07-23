"""Baseline, Wilson-Grenzen, Drift-Klassifikation, Exit-Codes."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.corpus.report import (QUOTEN_SEMANTIK, check_against_baseline,
                                      classify_drift, tier2_quotas, wilson)
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


# ---- I1: Fehlerraten regressieren nach OBEN ------------------------------

# Die echte Baseline: 0 Fehlbuchungen auf 25 Annahmen.
_FAR_BASELINE = {"quotas": {"false_accept_rate": {
    "k": 0, "n": 25, "p": 0.0, "wilson_lo": 0.0, "wilson_hi": 0.1332}}}


def test_check_flags_a_rising_false_accept_rate():
    """5 Fehlbuchungen statt 0 sind eine Regression — die Untergrenzen-
    Pruefung kann das nie sehen (p < 0.0 ist unmoeglich)."""
    quotas = {"false_accept_rate": {"k": 5, "n": 25, "p": 0.2,
                                    "wilson_lo": 0.0888, "wilson_hi": 0.3901}}
    code, meldungen = check_against_baseline(
        _run({"pass": 10}), quotas, _FAR_BASELINE, accept_drift=False)
    assert code == 1, "steigende Fehlbuchungsrate meldete OK"
    assert any("false_accept_rate" in m for m in meldungen)


def test_check_accepts_a_false_accept_rate_inside_the_ceiling():
    """1/25 liegt noch unter der Wilson-Obergrenze der Baseline."""
    quotas = {"false_accept_rate": {"k": 1, "n": 25, "p": 0.04,
                                    "wilson_lo": 0.0071, "wilson_hi": 0.1961}}
    code, _ = check_against_baseline(
        _run({"pass": 10}), quotas, _FAR_BASELINE, accept_drift=False)
    assert code == 0


def test_check_does_not_flag_a_falling_false_accept_rate():
    """Weniger Fehlbuchungen sind eine Verbesserung, keine Regression."""
    baseline = {"quotas": {"false_accept_rate": {
        "k": 5, "n": 25, "p": 0.2, "wilson_lo": 0.0888, "wilson_hi": 0.3901}}}
    quotas = {"false_accept_rate": {"k": 0, "n": 25, "p": 0.0,
                                    "wilson_lo": 0.0, "wilson_hi": 0.1332}}
    code, _ = check_against_baseline(
        _run({"pass": 10}), quotas, baseline, accept_drift=False)
    assert code == 0


# ---- I2: fehlende Grenze ist ein Fehler, keine Erlaubnis ------------------

def test_check_fails_when_the_baseline_entry_lacks_its_floor():
    baseline = {"quotas": {"accuracy_top1": {"k": 46, "n": 60, "p": 0.7667}}}
    quotas = {"accuracy_top1": {"k": 10, "n": 60, "p": 0.1667,
                                "wilson_lo": 0.0929, "wilson_hi": 0.2811}}
    code, meldungen = check_against_baseline(
        _run({"pass": 10}), quotas, baseline, accept_drift=False)
    assert code == 1, "fehlendes wilson_lo schaltete die Kennzahl still ab"
    assert any("wilson_lo" in m for m in meldungen)


def test_check_fails_when_an_error_rate_entry_lacks_its_ceiling():
    baseline = {"quotas": {"false_accept_rate": {"k": 0, "n": 25, "p": 0.0,
                                                 "wilson_lo": 0.0}}}
    quotas = {"false_accept_rate": {"k": 5, "n": 25, "p": 0.2,
                                    "wilson_lo": 0.0888, "wilson_hi": 0.3901}}
    code, meldungen = check_against_baseline(
        _run({"pass": 10}), quotas, baseline, accept_drift=False)
    assert code == 1
    assert any("wilson_hi" in m for m in meldungen)


def test_check_ignores_the_decisions_block(tmp_path):
    """`decisions` ist eine Zaehlung ohne p — sie darf die Grenzen-Pruefung
    nicht als 'fehlende Grenze' triggern."""
    baseline = {"quotas": {"decisions": {"accept": 25, "ambiguous": 34}}}
    quotas = {"decisions": {"accept": 25, "ambiguous": 34}}
    code, meldungen = check_against_baseline(
        _run({"pass": 10}), quotas, baseline, accept_drift=False)
    assert code == 0, meldungen


# ---- Semantikwechsel 2026-07-23: verdict-Zaehlung gatet nicht mehr --------

def test_check_never_gates_on_the_verdict_count():
    """accuracy_top1_verdict ist eingefroren: sie kann eine Regression weder
    anzeigen noch ausschliessen. Ein Einbruch dort darf --check NICHT roten,
    sonst meldet das Gate Sicherheit, die es nicht geprueft hat."""
    baseline = {"quoten_semantik": QUOTEN_SEMANTIK,
                "quotas": {"accuracy_top1_verdict": {
                    "k": 46, "n": 60, "p": 0.7667,
                    "wilson_lo": 0.6456, "wilson_hi": 0.8556}}}
    quotas = {"accuracy_top1_verdict": {"k": 6, "n": 60, "p": 0.1,
                                        "wilson_lo": 0.0465, "wilson_hi": 0.2035}}
    code, meldungen = check_against_baseline(
        _run({"pass": 10}), quotas, baseline, accept_drift=False)
    assert code == 0, meldungen


def test_check_still_gates_on_the_raw_top1():
    """Gegenprobe zum vorigen Test: dieselbe Zahl unter dem Gate-Namen muss
    roten. Ohne diesen Test koennte NUR_INFO versehentlich wachsen und das
    Gate lautlos leerraeumen."""
    baseline = {"quoten_semantik": QUOTEN_SEMANTIK,
                "quotas": {"accuracy_top1": {
                    "k": 47, "n": 60, "p": 0.7833,
                    "wilson_lo": 0.6636, "wilson_hi": 0.8681}}}
    quotas = {"accuracy_top1": {"k": 6, "n": 60, "p": 0.1,
                                "wilson_lo": 0.0465, "wilson_hi": 0.2035}}
    code, meldungen = check_against_baseline(
        _run({"pass": 10}), quotas, baseline, accept_drift=False)
    assert code == 1
    assert any("accuracy_top1" in m for m in meldungen)


def test_check_reports_a_baseline_from_the_old_metric_semantics():
    """Eine Baseline ohne Semantik-Marke stammt aus der verdict-Aera. Ihre
    top1-Schranke beschreibt eine andere Groesse — das muss im Klartext
    stehen, sonst liest sich der gruene Lauf wie eine bestaetigte Quote."""
    baseline = {"quotas": {"accuracy_top1": {
        "k": 46, "n": 60, "p": 0.7667, "wilson_lo": 0.6456, "wilson_hi": 0.8556}}}
    quotas = {"accuracy_top1": {"k": 47, "n": 60, "p": 0.7833,
                                "wilson_lo": 0.6636, "wilson_hi": 0.8681}}
    code, meldungen = check_against_baseline(
        _run({"pass": 10}), quotas, baseline, accept_drift=False)
    assert code == 0, "der Hinweis darf den Exit-Code nicht drehen"
    assert any("Semantik" in m for m in meldungen)


def test_check_stays_quiet_when_the_semantics_match():
    baseline = {"quoten_semantik": QUOTEN_SEMANTIK, "quotas": {}}
    code, meldungen = check_against_baseline(
        _run({"pass": 10}), {}, baseline, accept_drift=False)
    assert code == 0
    assert not any("Semantik" in m for m in meldungen)


# ---- tier2_quotas(): accuracy_top1/top3 muessen mit analysis.py uebereinstimmen ----

def _cand(nr):
    return CandidateReport(article_number=nr, name=nr, nominal_size_mm=200.0,
                           height_mm=0.0, corrected_diameter_mm=200.0,
                           geometry_error_mm=0.0, has_references=True, n_shots=2)


def _report(decision="accept", label=None, verdict=None, cands=()):
    return MatchReport(decision=decision, message="", candidates=list(cands),
                       label=label, verdict=verdict)


def test_tier2_quotas_accuracy_top1_counts_a_gate_rejection_as_a_hit():
    """Der Fall dbb5f4ea (phase-b, LOEFFEL-9): Rang-1-Kandidat == Label, aber
    das z-Gate hat verworfen (max|z| 3.735 > 3.5) und der Mensch hat darum
    'falsch' gedrueckt.

    SEMANTIK seit 2026-07-23: accuracy_top1 zaehlt das als TREFFER — die
    Zuordnung war richtig, verworfen hat das Gate. Genau diese Trennung macht
    die Kennzahl als Regressions-Gate brauchbar: haette eine Matcher-Aenderung
    den Artikel von Rang 1 verdraengt, muss die Zahl fallen; ein eingefrorenes
    Mensch-Urteil kann das nie anzeigen."""
    r = _report(decision="reject", label="LOEFFEL-9", verdict="wrong",
               cands=[_cand("LOEFFEL-9")])
    q = tier2_quotas([r])
    assert q["accuracy_top1"]["k"] == 1
    assert q["accuracy_top1"]["n"] == 1
    # ... und die alte Zaehlung laeuft als Zusatzfeld unveraendert weiter:
    assert q["accuracy_top1_verdict"]["k"] == 0
    assert q["accuracy_top1_verdict"]["n"] == 1


def test_tier2_quotas_accuracy_top1_ignores_a_correct_verdict_on_a_wrong_rank():
    """Gegenrichtung: verdict='correct', aber Rang 1 ist ein anderer Artikel.
    Roh ist das ein Fehlschlag. Konstruiert, aber genau der Fall, in dem eine
    verdict-gefuehrte Kennzahl eine echte Verschlechterung zudecken wuerde."""
    r = _report(decision="accept", label="LOEFFEL-9", verdict="correct",
               cands=[_cand("LOEFFEL-4"), _cand("LOEFFEL-9")])
    q = tier2_quotas([r])
    assert q["accuracy_top1"]["k"] == 0
    assert q["accuracy_top1_verdict"]["k"] == 1


def test_tier2_quotas_accuracy_top1_counts_a_plain_hit():
    r = _report(decision="accept", label="LOEFFEL-9", verdict="correct",
               cands=[_cand("LOEFFEL-9")])
    q = tier2_quotas([r])
    assert q["accuracy_top1"]["k"] == 1
    assert q["accuracy_top1"]["n"] == 1
    assert q["accuracy_top1_verdict"]["k"] == 1


def test_tier2_quotas_accuracy_top1_needs_no_verdict():
    r = _report(decision="accept", label="LOEFFEL-9", verdict=None,
               cands=[_cand("LOEFFEL-9")])
    q = tier2_quotas([r])
    assert q["accuracy_top1"]["k"] == 1
    assert q["accuracy_top1"]["n"] == 1


def test_tier2_quotas_accuracy_top1_ignores_reports_without_a_label():
    """Ohne Label gibt es keine Wahrheit — der Report faellt aus dem Nenner.
    Auch dann, wenn ein verdict vorliegt: ein 'falsch' ohne Artikelangabe
    sagt nicht, was richtig gewesen waere."""
    r = _report(decision="reject", label=None, verdict="wrong", cands=[])
    q = tier2_quotas([r])
    assert q["accuracy_top1"]["n"] == 0
    # Die verdict-Zaehlung kennt den Fall dagegen (Nenner 1) — der Grund,
    # warum die beiden Kennzahlen verschiedene Nenner haben duerfen.
    assert q["accuracy_top1_verdict"]["n"] == 1


def test_tier2_quotas_top1_and_top3_share_one_denominator():
    """Vor dem Wechsel war n(top1) die Menge der beurteilbaren und n(top3)
    die der gelabelten Reports — zwei Grundmengen, deren Quoten man nicht
    nebeneinander lesen durfte."""
    reports = [
        _report(decision="accept", label="A", verdict="correct", cands=[_cand("A")]),
        _report(decision="reject", label=None, verdict="wrong", cands=[_cand("B")]),
        _report(decision="accept", label="C", verdict=None, cands=[_cand("D"), _cand("C")]),
    ]
    q = tier2_quotas(reports)
    assert q["accuracy_top1"]["n"] == q["accuracy_top3"]["n"] == 2
    assert q["accuracy_top1"]["k"] == 1        # nur A steht auf Rang 1
    assert q["accuracy_top3"]["k"] == 2        # C steht auf Rang 2


def test_tier2_quotas_accuracy_top3_counts_a_correctly_rejected_no_match():
    """Kein Kandidat UND label == NO_MATCH zaehlt als Top-3-Treffer – der
    Sonderfall aus analysis.py, den top_k_accuracy() nicht kennt."""
    r = _report(decision="reject", label=NO_MATCH, verdict=None, cands=[])
    q = tier2_quotas([r])
    assert q["accuracy_top3"]["k"] == 1
    assert q["accuracy_top3"]["n"] == 1
