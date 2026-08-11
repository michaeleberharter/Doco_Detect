"""Kontrakt des corpus_repro-Deselects (Korpus-Entdopplung 2026-08-11).

Ohne DOCODETECT_CORPUS_REPRO=1 werden GENAU die zwei teuren
Reproduktionstests deselektiert (tier1_full, tier2_decisions) — nicht
mehr, nicht weniger: corpus_smoke und der Manifest-Test bleiben. Mit der
Env-Variablen kommen beide vollständig zurück, und der Deselect meldet
sich sichtbar in der Terminal-Summary. Subprocess-pytest, damit der ECHTE
conftest-Hook geprüft wird, keine Nachbildung."""

import os
import subprocess
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
ENV = "DOCODETECT_CORPUS_REPRO"


def _collect(env_wert=None) -> str:
    env = dict(os.environ)
    env.pop(ENV, None)
    if env_wert is not None:
        env[ENV] = env_wert
    p = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q",
         "tests/test_corpus.py"],
        cwd=WURZEL, env=env, capture_output=True, text=True, timeout=120)
    return p.stdout


def test_ohne_env_genau_die_zwei_deselektiert():
    out = _collect(None)
    assert "test_corpus_tier1_full_reproduces" not in out
    assert "test_corpus_tier2_decisions_reproduce" not in out
    assert "test_corpus_smoke_subset_reproduces" in out      # bleibt
    assert "test_every_manifest_entry_has_its_files" in out  # bleibt
    assert "2 deselected" in out


def test_ohne_env_hinweiszeile_sichtbar():
    """Sichtbarkeit ist die Hauptsache: die Zeile kommt IMMER, nicht nur
    mit -rs — sie nennt Merge-Gate und Rückholweg."""
    out = _collect(None)
    assert "[korpus]" in out
    assert "corpus-run --tier 1 --check" in out
    assert f"{ENV}=1" in out


def test_mit_env_laufen_beide_wieder():
    out = _collect("1")
    assert "test_corpus_tier1_full_reproduces" in out
    assert "test_corpus_tier2_decisions_reproduce" in out
    assert "deselected" not in out
    assert "[korpus]" not in out                 # nichts weggelassen
