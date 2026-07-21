"""Akzeptanz-Schicht (docodetect/corpus/accepted.py): ein versioniertes
Delta darf eine FAIL-Abweichung vom Original-Golden erklaeren, ohne das
Original zu veraendern. Siehe docs/superpowers/plans/
2026-07-21-vorfilter-laengliche-artikel.md, Punkt 2 der Nutzer-Vorgabe."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.corpus.accepted import load_all, resolve_diffs  # noqa: E402
from docodetect.corpus.compare import FAIL, PASS, compare_tier2, worst_band  # noqa: E402
from docodetect.matcher import CandidateReport, MatchReport  # noqa: E402


def _rep(decision, arts, llr=1.5, maxz=3.0, gate=True):
    return MatchReport(
        decision=decision, message="", gate_passed=gate,
        llr_margin=llr, max_z_winner=maxz,
        candidates=[CandidateReport(article_number=a, name=a, nominal_size_mm=1.0,
                                    height_mm=0.0, corrected_diameter_mm=1.0,
                                    geometry_error_mm=0.0, has_references=True,
                                    n_shots=9) for a in arts])


def _delta_file(tmp_path, images: dict, name="2026-07-21-test.json"):
    payload = {"fix_commit": "deadbeef", "results_doc": "docs/x.md", "images": images}
    p = tmp_path / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_load_all_leeres_verzeichnis_liefert_leeres_dict(tmp_path):
    assert load_all(tmp_path) == {}


def test_load_all_fehlendes_verzeichnis_liefert_leeres_dict(tmp_path):
    assert load_all(tmp_path / "does-not-exist") == {}


def test_load_all_liest_eintrag_mit_metadaten(tmp_path):
    _delta_file(tmp_path, {
        "abc12345": {"kategorie": "b", "reason": "Nachbarschaft",
                     "expected": {"decision": "accept", "candidates": ["L1"],
                                  "gate_passed": True, "llr_margin": None,
                                  "max_z_winner": 1.0}}})
    merged = load_all(tmp_path)
    assert set(merged) == {"abc12345"}
    assert merged["abc12345"]["kategorie"] == "b"
    assert merged["abc12345"]["_fix_commit"] == "deadbeef"
    assert merged["abc12345"]["_results_doc"] == "docs/x.md"


def test_load_all_mergt_mehrere_dateien_spaetere_gewinnt(tmp_path):
    _delta_file(tmp_path, {
        "abc12345": {"expected": {"decision": "accept", "candidates": ["L1"],
                                  "gate_passed": True, "llr_margin": None,
                                  "max_z_winner": 1.0}}}, name="a-erste.json")
    _delta_file(tmp_path, {
        "abc12345": {"expected": {"decision": "ambiguous", "candidates": ["L1", "L2"],
                                  "gate_passed": True, "llr_margin": 0.5,
                                  "max_z_winner": 1.0}}}, name="b-zweite.json")
    merged = load_all(tmp_path)
    assert merged["abc12345"]["expected"]["decision"] == "ambiguous"


def test_resolve_diffs_leere_diffs_bleiben_unangetastet(tmp_path):
    """Bereits PASS/DRIFT: kein Lookup noetig, Kurzschluss."""
    assert resolve_diffs("deadbeef01", _rep("accept", ["L1"]), [], tmp_path) == []


def test_resolve_diffs_ohne_delta_bleibt_fail(tmp_path):
    golden = _rep("accept", ["L1"])
    actual = _rep("ambiguous", ["L1"])
    diffs = compare_tier2(golden, actual)
    assert worst_band(resolve_diffs("nichtvorhanden", actual, diffs, tmp_path)) == FAIL


def test_resolve_diffs_mit_exakt_passendem_delta_wird_pass(tmp_path):
    """Kernfall: Replay weicht vom Original-Golden ab, matcht aber exakt
    das akzeptierte Delta - PASS statt FAIL."""
    sha8 = "abc12345"
    golden = _rep("accept", ["L1"], llr=5.0)
    actual = _rep("ambiguous", ["L1", "L2"], llr=1.7)
    _delta_file(tmp_path, {
        sha8: {"kategorie": "c", "reason": "Fisher-Gewichtung ueber groesseres "
                                          "Kandidatenset komprimiert die Margin",
               "expected": {"decision": "ambiguous", "candidates": ["L1", "L2"],
                            "gate_passed": True, "llr_margin": 1.7,
                            "max_z_winner": 3.0}}})
    diffs = compare_tier2(golden, actual)
    assert worst_band(diffs) == FAIL  # Ausgangslage: ohne Delta FAIL
    resolved = resolve_diffs(sha8, actual, diffs, tmp_path)
    assert worst_band(resolved) == PASS


def test_resolve_diffs_delta_erklaert_nicht_alles_bleibt_fail(tmp_path):
    """Ein Delta deckt genau EINEN neuen Zustand ab. Weicht der Replay auch
    davon ab (weitere, nicht akzeptierte Aenderung), bleibt es FAIL - kein
    stilles Durchwinken."""
    sha8 = "abc12345"
    golden = _rep("accept", ["L1"])
    actual = _rep("reject", [])  # weder Original noch Delta
    _delta_file(tmp_path, {
        sha8: {"expected": {"decision": "ambiguous", "candidates": ["L1", "L2"],
                            "gate_passed": True, "llr_margin": 1.7,
                            "max_z_winner": 3.0}}})
    diffs = compare_tier2(golden, actual)
    resolved = resolve_diffs(sha8, actual, diffs, tmp_path)
    assert worst_band(resolved) == FAIL
    assert any(d.field == "decision" for d in resolved)


def test_resolve_diffs_nutzt_nur_die_ersten_acht_zeichen_des_sha(tmp_path):
    sha8 = "abc12345"
    golden = _rep("accept", ["L1"], llr=5.0)
    actual = _rep("ambiguous", ["L1", "L2"], llr=1.7)
    _delta_file(tmp_path, {
        sha8: {"expected": {"decision": "ambiguous", "candidates": ["L1", "L2"],
                            "gate_passed": True, "llr_margin": 1.7,
                            "max_z_winner": 3.0}}})
    diffs = compare_tier2(golden, actual)
    voller_sha = sha8 + "9" * 56  # wie ein echter sha256-Hexdigest
    resolved = resolve_diffs(voller_sha, actual, diffs, tmp_path)
    assert worst_band(resolved) == PASS
