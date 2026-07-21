"""corpus-diff: neu kaputt / repariert / weiterhin kaputt."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.corpus.diff import diff_runs, format_diff


def _lauf(root: Path, run_id: str, baender: dict, quotas=None):
    d = root / "runs" / run_id
    (d / "failures").mkdir(parents=True, exist_ok=True)
    (d / "metrics.json").write_text(json.dumps(
        {"run_id": run_id, "tier": 1, "n": len(baender),
         "baender": {}, "quotas": quotas or {}}))
    for sha, band in baender.items():
        if band != "pass":
            (d / "failures" / f"{sha}.json").write_text(json.dumps(
                {"sha": sha, "session": "s", "article": "A", "band": band,
                 "diffs": [], "error": None}))


def test_diff_detects_newly_broken(tmp_path):
    _lauf(tmp_path, "a", {"aaaaaaaa": "pass"})
    _lauf(tmp_path, "b", {"aaaaaaaa": "fail"})
    d = diff_runs(tmp_path, "a", "b")
    assert d["neu_kaputt"] == ["aaaaaaaa"]
    assert d["repariert"] == []


def test_diff_detects_repaired(tmp_path):
    _lauf(tmp_path, "a", {"aaaaaaaa": "fail"})
    _lauf(tmp_path, "b", {"aaaaaaaa": "pass"})
    d = diff_runs(tmp_path, "a", "b")
    assert d["repariert"] == ["aaaaaaaa"]
    assert d["neu_kaputt"] == []


def test_diff_detects_still_broken(tmp_path):
    _lauf(tmp_path, "a", {"aaaaaaaa": "fail"})
    _lauf(tmp_path, "b", {"aaaaaaaa": "fail"})
    assert diff_runs(tmp_path, "a", "b")["weiterhin_kaputt"] == ["aaaaaaaa"]


def test_diff_reports_metric_deltas(tmp_path):
    _lauf(tmp_path, "a", {"x": "pass"},
          quotas={"accuracy_top1": {"p": 0.7667, "k": 46, "n": 60}})
    _lauf(tmp_path, "b", {"x": "pass"},
          quotas={"accuracy_top1": {"p": 0.8000, "k": 48, "n": 60}})
    d = diff_runs(tmp_path, "a", "b")
    assert d["metrik_deltas"]["accuracy_top1"]["delta"] == pytest.approx(0.0333, abs=1e-4)


def test_format_diff_mentions_all_three_groups(tmp_path):
    _lauf(tmp_path, "a", {"aa": "fail", "bb": "pass", "cc": "fail"})
    _lauf(tmp_path, "b", {"aa": "pass", "bb": "fail", "cc": "fail"})
    text = format_diff(diff_runs(tmp_path, "a", "b"))
    assert "neu kaputt" in text and "repariert" in text and "weiterhin kaputt" in text


def test_diff_raises_for_a_missing_run(tmp_path):
    _lauf(tmp_path, "a", {"x": "pass"})
    with pytest.raises(FileNotFoundError):
        diff_runs(tmp_path, "a", "fehlt")
