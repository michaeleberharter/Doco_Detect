"""corpus-run: Argument-Parsing und Exit-Codes."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect import cli


def test_corpus_run_is_registered():
    with pytest.raises(SystemExit) as e:
        cli.main(["corpus-run", "--help"])
    assert e.value.code == 0


def test_corpus_build_is_registered():
    with pytest.raises(SystemExit) as e:
        cli.main(["corpus-build", "--help"])
    assert e.value.code == 0


def test_corpus_diff_is_registered():
    with pytest.raises(SystemExit) as e:
        cli.main(["corpus-diff", "--help"])
    assert e.value.code == 0


def test_corpus_triage_is_registered():
    with pytest.raises(SystemExit) as e:
        cli.main(["corpus-triage", "--help"])
    assert e.value.code == 0


def test_check_exits_nonzero_on_regression(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "docodetect.corpus.runner.run_corpus",
        lambda cfg, **kw: {"results": [{"sha": "a" * 64, "session": "s",
                                        "article": "A", "tier": 1,
                                        "band": "fail", "diffs": [],
                                        "error": None}],
                           "tier": 1, "dauer_s": 0.1, "n": 1,
                           "neu_gerechnet": 1, "bilder_pro_s": 10.0,
                           "code_fingerprint": "x" * 64,
                           "config_fingerprint": "y" * 64})
    monkeypatch.setattr("docodetect.corpus.report.BASELINE_PATH",
                        tmp_path / "baseline.json")
    monkeypatch.setattr("docodetect.corpus.manifest.MANIFEST_PATH",
                        tmp_path / "manifest.json")
    with pytest.raises(SystemExit) as e:
        cli.main(["corpus-run", "--check", "--tier", "1"])
    assert e.value.code == 1


def test_check_exits_zero_when_clean(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "docodetect.corpus.runner.run_corpus",
        lambda cfg, **kw: {"results": [{"sha": "a" * 64, "session": "s",
                                        "article": "A", "tier": 1,
                                        "band": "pass", "diffs": [],
                                        "error": None}],
                           "tier": 1, "dauer_s": 0.1, "n": 1,
                           "neu_gerechnet": 1, "bilder_pro_s": 10.0,
                           "code_fingerprint": "x" * 64,
                           "config_fingerprint": "y" * 64})
    monkeypatch.setattr("docodetect.corpus.report.BASELINE_PATH",
                        tmp_path / "baseline.json")
    monkeypatch.setattr("docodetect.corpus.manifest.MANIFEST_PATH",
                        tmp_path / "manifest.json")
    with pytest.raises(SystemExit) as e:
        cli.main(["corpus-run", "--check", "--tier", "1"])
    assert e.value.code == 0
