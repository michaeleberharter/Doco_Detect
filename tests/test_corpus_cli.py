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


# ---- C1: --update-baseline darf die Quoten nicht ausloeschen -------------

def _baseline_mit_quoten(p: Path) -> dict:
    """Eine Baseline im Zustand der echten corpus/baseline.json."""
    import json
    payload = {"generated": "2026-07-21T01:58:53", "run_id": "final-tier2",
               "tier": 2, "n": 60,
               "quotas": {"accuracy_top1": {"k": 46, "n": 60, "p": 0.7667,
                                            "wilson_lo": 0.6456,
                                            "wilson_hi": 0.8556},
                          "false_accept_rate": {"k": 0, "n": 25, "p": 0.0,
                                                "wilson_lo": 0.0,
                                                "wilson_hi": 0.1332}},
               "code_fingerprint": "a" * 64, "config_fingerprint": "b" * 64}
    p.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def test_update_baseline_verweigert_leere_quoten(monkeypatch, tmp_path, capsys):
    """--tier 1 (Default) fuellt keine Quoten. Ein ersetzendes Schreiben
    wuerde die Soll-Quoten dauerhaft loeschen und JEDE Kennzahl fuer immer
    abschalten."""
    import json
    bl = tmp_path / "baseline.json"
    vorher = _baseline_mit_quoten(bl)
    _isoliere_korpus(monkeypatch, tmp_path,
                     lambda cfg, **kw: _run_dict([_lauf("pass")]))
    with pytest.raises(SystemExit) as e:
        cli.main(["corpus-run", "--update-baseline", "--tier", "1",
                  "--run-id", "test-leer"])
    assert e.value.code != 0, "leere Quoten wurden klaglos geschrieben"
    assert json.loads(bl.read_text(encoding="utf-8")) == vorher, \
        "Baseline wurde trotz Verweigerung ueberschrieben"
    assert "quota" in capsys.readouterr().out.lower()


def test_update_baseline_schreibt_mit_tier2_quoten(monkeypatch, tmp_path):
    """Gegenprobe: mit echten Tier-2-Quoten laeuft --update-baseline durch."""
    import json

    from docodetect.matcher import MatchReport

    bl = tmp_path / "baseline.json"
    _baseline_mit_quoten(bl)
    _isoliere_korpus(
        monkeypatch, tmp_path,
        lambda cfg, **kw: _run_dict([_lauf("pass", tier=2, sha="a" * 64)],
                                    tier=2))
    replay = tmp_path / "korpus" / "runs" / "test-voll" / "replay"
    replay.mkdir(parents=True, exist_ok=True)
    rep = MatchReport(decision="accept", message="", candidates=[],
                      measured={})
    rep.label, rep.verdict = "A", "correct"
    (replay / f"{'a' * 8}.json").write_text(rep.to_json(), encoding="utf-8")

    cli.main(["corpus-run", "--update-baseline", "--tier", "2",
              "--run-id", "test-voll"])
    got = json.loads(bl.read_text(encoding="utf-8"))
    assert got["run_id"] == "test-voll"
    assert got["quotas"], "Quoten fehlen in der neu geschriebenen Baseline"


# ---- I4: --check auf einem Teil-Lauf ist kein gruenes Gate ---------------

@pytest.mark.parametrize("filter_args", [
    ["--subset", "5"],
    ["--session", "phase-b"],
    ["--article", "LOEFFEL-1"],
])
def test_check_auf_gefiltertem_lauf_ist_keine_freigabe(monkeypatch, tmp_path,
                                                       capsys, filter_args):
    _baseline_mit_quoten(tmp_path / "baseline.json")
    _isoliere_korpus(monkeypatch, tmp_path,
                     lambda cfg, **kw: _run_dict([_lauf("pass")]))
    with pytest.raises(SystemExit) as e:
        cli.main(["corpus-run", "--check", "--tier", "1",
                  "--run-id", "test-teil"] + filter_args)
    assert e.value.code == 1, f"{filter_args} meldete ein gruenes Gate"
    assert "teil" in capsys.readouterr().out.lower()


def test_check_mit_weniger_bildern_als_die_baseline_fuehrt(monkeypatch,
                                                           tmp_path, capsys):
    """Die Baseline fuehrt n=60. Ein ungefilterter Lauf ueber 3 Bilder deckt
    den Korpus nicht ab — z.B. weil das Manifest geschrumpft ist."""
    _baseline_mit_quoten(tmp_path / "baseline.json")
    _isoliere_korpus(
        monkeypatch, tmp_path,
        lambda cfg, **kw: _run_dict([_lauf("pass", sha=c * 64)
                                     for c in "abc"]))
    with pytest.raises(SystemExit) as e:
        cli.main(["corpus-run", "--check", "--tier", "1",
                  "--run-id", "test-kurz"])
    assert e.value.code == 1, "Teil-Abdeckung meldete OK"
    ausgabe = capsys.readouterr().out
    assert "60" in ausgabe and "3" in ausgabe


def test_check_mit_voller_abdeckung_bleibt_gruen(monkeypatch, tmp_path):
    """Gegenprobe: ungefiltert und n >= Baseline-n -> Exit 0."""
    _baseline_mit_quoten(tmp_path / "baseline.json")
    _isoliere_korpus(
        monkeypatch, tmp_path,
        lambda cfg, **kw: _run_dict([_lauf("pass", sha=f"{i:064d}")
                                     for i in range(60)]))
    with pytest.raises(SystemExit) as e:
        cli.main(["corpus-run", "--check", "--tier", "1",
                  "--run-id", "test-voll-ok"])
    assert e.value.code == 0


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
