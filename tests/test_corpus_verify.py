"""Konsistenz-Waechter: has_db:true ohne Buendel-DB muss LAUT scheitern."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.corpus.verify import pruefe_bundle_db_konsistenz


def _session(root: Path, name: str, *, has_db: bool, mit_db: bool) -> None:
    bundle = root / name / "bundle"
    bundle.mkdir(parents=True)
    (bundle / "session.json").write_text(json.dumps(
        {"name": name, "bundle_dir": f"{name}/bundle", "has_db": has_db,
         "db_verified": 1.0 if has_db else 0.0, "mm_per_px": 0.0787,
         "sigma_floors": {}, "tier": 2 if has_db else 1, "provenance": "x"}),
        encoding="utf-8")
    if mit_db:
        (bundle / "db.sqlite3").write_bytes(b"snapshot")


def test_konsistente_tier2_session_geht_durch(tmp_path):
    _session(tmp_path, "phase-b", has_db=True, mit_db=True)
    pruefe_bundle_db_konsistenz(tmp_path)      # wirft nicht


def test_tier1_session_ohne_db_ist_in_ordnung(tmp_path):
    """has_db:false erwartet keine DB — kein Befund."""
    _session(tmp_path, "phase-a", has_db=False, mit_db=False)
    pruefe_bundle_db_konsistenz(tmp_path)      # wirft nicht


def test_has_db_true_ohne_buendel_db_bricht_laut_ab(tmp_path):
    _session(tmp_path, "phase-b", has_db=True, mit_db=False)
    with pytest.raises(RuntimeError) as exc:
        pruefe_bundle_db_konsistenz(tmp_path)
    # Meldung nennt Session, Symptom und die stille Gefahr.
    assert "phase-b" in str(exc.value)
    assert "db.sqlite3" in str(exc.value)
    assert "gruen" in str(exc.value)


def test_meldung_nennt_alle_verletzer(tmp_path):
    _session(tmp_path, "phase-b", has_db=True, mit_db=False)
    _session(tmp_path, "phase-c2", has_db=True, mit_db=False)
    _session(tmp_path, "phase-a", has_db=False, mit_db=False)   # ok
    with pytest.raises(RuntimeError) as exc:
        pruefe_bundle_db_konsistenz(tmp_path)
    assert "phase-b" in str(exc.value)
    assert "phase-c2" in str(exc.value)


def test_runs_verzeichnis_wird_nicht_mitgeprueft(tmp_path):
    """runs/<id>/ traegt Replay-Artefakte, keine Session-Buendel — eine
    dort liegende session.json darf den Waechter nicht ausloesen."""
    _session(tmp_path, "phase-b", has_db=True, mit_db=True)
    fremd = tmp_path / "runs" / "20260101-000000" / "bundle"
    fremd.mkdir(parents=True)
    (fremd / "session.json").write_text(
        json.dumps({"name": "run-artefakt", "has_db": True}), encoding="utf-8")
    pruefe_bundle_db_konsistenz(tmp_path)      # wirft nicht


def test_leerer_korpus_ist_kein_befund(tmp_path):
    pruefe_bundle_db_konsistenz(tmp_path)      # keine Sessions -> wirft nicht
