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


def _lauf(band="pass", tier=1, sha="a" * 64):
    return {"sha": sha, "session": "s", "article": "A", "tier": tier,
            "band": band, "diffs": [], "error": None}


def _run_dict(results, tier=1):
    return {"results": list(results), "tier": tier, "dauer_s": 0.1,
            "n": len(results), "neu_gerechnet": len(results),
            "bilder_pro_s": 10.0, "code_fingerprint": "x" * 64,
            "config_fingerprint": "y" * 64}


def _isoliere_korpus(monkeypatch, tmp_path, run_stub):
    """Alle Schreibpfade von corpus-run nach tmp_path umbiegen.

    cli.main() laedt sonst die echte config/config.yaml, und cmd_corpus_run
    schriebe damit in den echten, ausserhalb des Repos liegenden Korpus
    (Task-7-Review, Befund 1). Gibt die Liste zurueck, in der die tatsaechlich
    an run_corpus uebergebene Config landet — so kann der Test aktiv pruefen,
    wohin geschrieben wurde.
    """
    from docodetect.config import load_config as _echtes_load_config

    def _test_config(path=None):
        cfg = _echtes_load_config(path)
        cfg.setdefault("paths", {})["corpus_dir"] = str(tmp_path / "korpus")
        return cfg

    monkeypatch.setattr(cli, "load_config", _test_config)
    monkeypatch.setattr("docodetect.corpus.report.BASELINE_PATH",
                        tmp_path / "baseline.json")
    monkeypatch.setattr("docodetect.corpus.manifest.MANIFEST_PATH",
                        tmp_path / "manifest.json")

    gesehen: list = []

    def _run_corpus(cfg, **kw):
        gesehen.append(cfg)
        return run_stub(cfg, **kw)

    monkeypatch.setattr("docodetect.corpus.runner.run_corpus", _run_corpus)
    return gesehen


def _echter_korpus() -> Path:
    """Der Pfad, in den die Tests vor dem Fix real hineingeschrieben haben."""
    from docodetect.config import project_root
    from docodetect.corpus.manifest import DEFAULT_CORPUS_DIR
    return (project_root() / DEFAULT_CORPUS_DIR).resolve()


def test_check_exits_nonzero_on_regression(monkeypatch, tmp_path):
    vorher = _echter_korpus().exists()
    _isoliere_korpus(monkeypatch, tmp_path,
                     lambda cfg, **kw: _run_dict([_lauf("fail")]))
    with pytest.raises(SystemExit) as e:
        cli.main(["corpus-run", "--check", "--tier", "1",
                  "--run-id", "test-regression"])
    assert e.value.code == 1
    assert (tmp_path / "korpus" / "runs" / "test-regression"
            / "summary.md").exists()
    assert _echter_korpus().exists() is vorher, \
        "Test hat den echten Korpus-Ordner angelegt"


def test_check_exits_zero_when_clean(monkeypatch, tmp_path):
    vorher = _echter_korpus().exists()
    _isoliere_korpus(monkeypatch, tmp_path,
                     lambda cfg, **kw: _run_dict([_lauf("pass")]))
    with pytest.raises(SystemExit) as e:
        cli.main(["corpus-run", "--check", "--tier", "1",
                  "--run-id", "test-sauber"])
    assert e.value.code == 0
    assert (tmp_path / "korpus" / "runs" / "test-sauber"
            / "summary.md").exists()
    assert _echter_korpus().exists() is vorher, \
        "Test hat den echten Korpus-Ordner angelegt"


def test_corpus_run_schreibt_ausschliesslich_unter_tmp_path(monkeypatch,
                                                            tmp_path):
    """Invariante: kein corpus-run-Test fasst den echten Korpus an.

    Prueft die Wurzel, die cmd_corpus_run tatsaechlich benutzt — nicht die,
    die der Test zu setzen glaubt.
    """
    from docodetect.corpus.manifest import corpus_root

    gesehen = _isoliere_korpus(monkeypatch, tmp_path,
                               lambda cfg, **kw: _run_dict([_lauf("pass")]))
    cli.main(["corpus-run", "--tier", "1", "--run-id", "test-pfad"])

    assert gesehen, "run_corpus wurde nie aufgerufen"
    wurzel = corpus_root(gesehen[0])
    assert wurzel.is_relative_to(tmp_path.resolve()), \
        f"corpus-run wuerde nach {wurzel} schreiben, nicht unter tmp_path"
    erzeugt = [p for p in tmp_path.rglob("summary.md")]
    assert erzeugt, "unter tmp_path ist kein Bericht entstanden"


def test_tier2_warnt_bei_unvollstaendigen_quoten(monkeypatch, tmp_path,
                                                 capsys):
    """--check darf bei fehlenden Replay-Reports nicht mit 0 enden."""
    _isoliere_korpus(
        monkeypatch, tmp_path,
        lambda cfg, **kw: _run_dict([_lauf("pass", tier=2, sha="a" * 64),
                                     _lauf("pass", tier=2, sha="b" * 64)],
                                    tier=2))
    # Kein einziger Replay-Report unter runs/<run_id>/replay/ — genau das
    # Szenario "alles aus dem Cache".
    with pytest.raises(SystemExit) as e:
        cli.main(["corpus-run", "--check", "--tier", "2",
                  "--run-id", "test-luecke"])
    assert e.value.code == 1, "unvollstaendige Tier-2-Quoten meldeten OK"
    ausgabe = capsys.readouterr().out
    assert "unvollstaendig" in ausgabe.lower()
