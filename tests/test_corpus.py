"""Regressionssuite gegen den Korpus echter Aufnahmen.

Zwei Marker:
    pytest -m corpus_smoke   festes 20-Bilder-Subset (Alltag, ~40 s)
    pytest -m corpus         voller Lauf (~6 min auf dem Mac)

Beide werden uebersprungen, solange der Korpus lokal fehlt — er liegt
ausserhalb des Repos (paths.corpus_dir). Aufbau: siehe README.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.config import load_config
from docodetect.corpus.manifest import Manifest, corpus_root

SMOKE_N = 20


def _grund() -> str | None:
    """Warum der Korpus-Lauf hier nicht moeglich ist – oder None."""
    cfg = load_config()
    root = corpus_root(cfg)
    if not root.is_dir():
        return (f"Korpus fehlt ({root}). Aufbau: "
                "python -m docodetect.cli corpus-build")
    m = Manifest.load()
    if not m.images:
        return ("Manifest ist leer. Aufbau: "
                "python -m docodetect.cli corpus-build")
    return None


def _lauf(**kwargs) -> dict:
    from docodetect.corpus.runner import run_corpus
    return run_corpus(load_config(), **kwargs)


@pytest.mark.corpus_smoke
def test_corpus_smoke_subset_reproduces():
    grund = _grund()
    if grund:
        pytest.skip(grund)
    run = _lauf(tier=1, subset=SMOKE_N, workers=8)
    schlecht = [r for r in run["results"] if r["band"] != "pass"]
    assert not schlecht, (
        f"{len(schlecht)} von {run['n']} Bildern ausserhalb des "
        f"Rundungsquantums: "
        + ", ".join(f"{r['sha'][:8]}={r['band']}" for r in schlecht[:5]))


@pytest.mark.corpus
def test_corpus_tier1_full_reproduces():
    grund = _grund()
    if grund:
        pytest.skip(grund)
    run = _lauf(tier=1, workers=8)
    schlecht = [r for r in run["results"] if r["band"] != "pass"]
    assert not schlecht, (
        f"{len(schlecht)} von {run['n']} Bildern weichen ab: "
        + ", ".join(f"{r['sha'][:8]}={r['band']}" for r in schlecht[:10]))


@pytest.mark.corpus
def test_corpus_tier2_decisions_reproduce():
    grund = _grund()
    if grund:
        pytest.skip(grund)
    m = Manifest.load()
    if not any(e.tier >= 2 for e in m.images):
        pytest.skip("keine Session mit verifiziertem DB-Snapshot im Korpus")
    run = _lauf(tier=2, workers=8)
    schlecht = [r for r in run["results"] if r["band"] == "fail"]
    assert not schlecht, (
        f"{len(schlecht)} Entscheidungen weichen ab: "
        + ", ".join(f"{r['sha'][:8]}" for r in schlecht[:10]))


@pytest.mark.corpus
def test_every_manifest_entry_has_its_files():
    grund = _grund()
    if grund:
        pytest.skip(grund)
    root = corpus_root(load_config())
    fehlend = [e.sha[:8] for e in Manifest.load().images
               if not (root / e.image_rel).exists()
               or not (root / e.report_rel).exists()]
    assert not fehlend, f"Manifest verweist ins Leere: {fehlend[:10]}"
