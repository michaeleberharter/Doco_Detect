"""Replay des ECHTEN Real-Capture-Testsets, falls lokal vorhanden.

Der Bestand entsteht erst an der Windows-Box — am Mac skippt dieser Test
sauber und SICHTBAR (-rs), er schlaegt nicht fehl und wird nicht still
uebergangen (Ablage-Regel der Spec). Bewusst eine eigene Datei getrennt
von test_testset_harness.py: dort ist testset.manifest.MANIFEST_PATH
modulweit auf den Trockenlauf-Bestand gepatcht, hier muss das ECHTE
Manifest (testset/manifest.json) gelten.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.config import load_config  # noqa: E402
# Alias: pytest wuerde eine importierte "test*"-Funktion als Testfall einsammeln
from docodetect.testset.manifest import TestsetManifest  # noqa: E402
from docodetect.testset.manifest import testset_root as ts_root  # noqa: E402
from docodetect.testset.replay import replay_testset  # noqa: E402


def test_reales_testset_replay_falls_vorhanden(tmp_path):
    manifest = TestsetManifest.load()
    if not manifest.captures:
        pytest.skip("kein Testset-Manifest (testset/manifest.json) — der "
                    "Bestand entsteht erst an der Windows-Box")
    cfg = load_config()
    root = ts_root(cfg)
    if not root.exists():
        pytest.skip(f"Testset-Ordner fehlt lokal: {root} "
                    f"(paths.testset_dir in config.local.yaml pruefen)")

    out = replay_testset(cfg, run_id=f"pytest-{tmp_path.name}")
    m = out["metrics"]
    # Rein berichtend, aber nicht stumm: kaputte Buendel und die
    # false_accept-Invariante sind auch hier Fehler.
    assert m["fehler"] == 0, [r for r in out["ergebnisse"]
                              if r["band"] == "fehler"]
    assert m["false_accept"] == 0, "false_accept-Invariante verletzt"
    if not m["vergleichbar"]:
        # Mac gegen Windows-Buendel: Strukturlauf ok, Zahlen nicht —
        # genau das meldet der Waechter; Abweichungen sind dann erwartbar.
        pytest.skip("Plattform weicht vom Aufnahmezustand ab — "
                    "Strukturlauf gruen, Zahlenvergleich nicht moeglich: "
                    + "; ".join(out["plattform_meldungen"]))
    assert m["abweichungen"] == 0, [r for r in out["ergebnisse"]
                                    if r["band"] == "abweichung"]
