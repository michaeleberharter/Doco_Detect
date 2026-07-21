"""Session-Fingerprints: mm_per_px, sigma_floors, exakter DB-Abgleich."""

import json
import math
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.corpus.bundle import (SessionBundle, bundle_cfg,
                                      copy_db_readonly, db_match_ratio,
                                      recover_mm_per_px, recover_sigma_floors,
                                      write_session_json)
from docodetect.matcher import (CandidateReport, FeatureScore, MatchReport)


def _kreis_kontur(radius_px: float, n: int = 512) -> list:
    return [[round(radius_px * math.cos(2 * math.pi * i / n) + 2000),
             round(radius_px * math.sin(2 * math.pi * i / n) + 1000)]
            for i in range(n)]


def _report(*, d_mm=190.5, radius_px=1209.4, refs=(("LOEFFEL-1", 194.43, 9),)):
    cands = []
    for art, ref, n in refs:
        cands.append(CandidateReport(
            article_number=art, name=art, nominal_size_mm=197.47, height_mm=0.0,
            corrected_diameter_mm=d_mm, geometry_error_mm=0.0,
            has_references=True, n_shots=n,
            features=[FeatureScore(feature="diameter_mm", measured=d_mm,
                                   reference=ref, distance=0.1,
                                   sigma_enroll=1.9, sigma_eff=2.42,
                                   z=0.04, log_contrib=-0.001, w_eff=0.52,
                                   weighted=-0.0005),
                      FeatureScore(feature="circularity", measured=0.22,
                                   reference=0.21, distance=0.01,
                                   sigma_enroll=0.008, sigma_eff=0.0215,
                                   z=0.7, log_contrib=-0.24, w_eff=0.08,
                                   weighted=-0.02)]))
    return MatchReport(decision="ambiguous", message="", candidates=cands,
                       measured={"circle_diameter_mm": d_mm},
                       contour=_kreis_kontur(radius_px))


def test_recover_mm_per_px_from_contour_and_measurement():
    r = _report(d_mm=190.5, radius_px=1209.4)
    got = recover_mm_per_px(r)
    assert got == pytest.approx(190.5 / (2 * 1209.4), rel=1e-3)


def test_recover_mm_per_px_none_without_contour():
    r = _report()
    r.contour = None
    assert recover_mm_per_px(r) is None


def test_recover_sigma_floors_inverts_the_quadrature_sum():
    # sigma_eff^2 = sigma_enroll^2 + sigma_floor^2
    r = _report()
    floors = recover_sigma_floors(r)
    assert floors["diameter_mm"] == pytest.approx(
        math.sqrt(2.42 ** 2 - 1.9 ** 2), abs=0.01)
    assert floors["circularity"] == pytest.approx(
        math.sqrt(0.0215 ** 2 - 0.008 ** 2), abs=0.001)


def _db(path: Path, rows):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE reference_stats (article_number TEXT PRIMARY KEY, "
                "stats_json TEXT NOT NULL, updated_unix REAL)")
    for art, mean, n in rows:
        con.execute("INSERT INTO reference_stats VALUES (?,?,?)",
                    (art, json.dumps({"n_shots": n,
                                      "scalar_mean": {"diameter_mm": mean}}), 0.0))
    con.commit()
    con.close()


def test_db_match_ratio_is_one_for_the_matching_snapshot(tmp_path):
    p = tmp_path / "match.sqlite3"
    _db(p, [("LOEFFEL-1", 194.43, 9)])
    assert db_match_ratio([_report()], p) == 1.0


def test_db_match_ratio_is_zero_for_a_foreign_snapshot(tmp_path):
    p = tmp_path / "fremd.sqlite3"
    _db(p, [("LOEFFEL-1", 188.11, 9)])
    assert db_match_ratio([_report()], p) == 0.0


def test_db_match_ratio_notices_a_differing_shot_count(tmp_path):
    p = tmp_path / "andere_shots.sqlite3"
    _db(p, [("LOEFFEL-1", 194.43, 8)])
    assert db_match_ratio([_report()], p) == 0.0


def test_copy_db_readonly_produces_a_readable_equal_copy(tmp_path):
    src, dst = tmp_path / "src.sqlite3", tmp_path / "dst.sqlite3"
    _db(src, [("LOEFFEL-1", 194.43, 9)])
    copy_db_readonly(src, dst)
    assert db_match_ratio([_report()], dst) == 1.0


def test_copy_db_readonly_never_writes_to_the_source(tmp_path):
    src, dst = tmp_path / "src.sqlite3", tmp_path / "dst.sqlite3"
    _db(src, [("LOEFFEL-1", 194.43, 9)])
    vorher = src.read_bytes()
    copy_db_readonly(src, dst)
    assert src.read_bytes() == vorher


def test_bundle_cfg_points_at_the_bundle_and_disables_captures(tmp_path):
    cfg = {"paths": {"db_file": "doco_detect.sqlite3", "captures_dir": "data/captures"},
           "calibration": {"file": "calibration/calibration.json",
                           "background_file": "calibration/background.png"}}
    out = bundle_cfg(cfg, tmp_path)
    assert out["paths"]["captures_dir"] is None       # Replay schreibt nichts
    assert out["paths"]["db_file"] == str(tmp_path / "db.sqlite3")
    assert out["calibration"]["file"] == str(tmp_path / "calibration.json")
    assert out["calibration"]["background_file"] == str(tmp_path / "background.png")
    assert cfg["paths"]["captures_dir"] == "data/captures"   # Original unberuehrt


# ---- tier2_ready: das einzige Tor nach Tier 2 ----------------------------

def _bundle(**kw) -> SessionBundle:
    basis = {"name": "phase-b", "bundle_dir": "phase-b/bundle", "has_db": True,
             "db_verified": 1.0, "mm_per_px": 0.0787}
    basis.update(kw)
    return SessionBundle(**basis)


def test_tier2_ready_requires_db_and_full_verification():
    assert _bundle(has_db=True, db_verified=1.0).tier2_ready is True


def test_tier2_ready_is_false_without_a_db():
    assert _bundle(has_db=False, db_verified=1.0).tier2_ready is False


def test_tier2_ready_is_false_just_below_full_verification():
    """Ein fast passender Snapshot ist eine ANDERE Datenbank, kein
    'fast richtig' — 0,99 darf Tier 2 nicht oeffnen."""
    assert _bundle(db_verified=0.99).tier2_ready is False
    assert _bundle(db_verified=0.999999).tier2_ready is False


def test_tier2_ready_is_false_without_any_verification():
    assert _bundle(db_verified=0.0).tier2_ready is False


# ---- write_session_json --------------------------------------------------

def test_write_session_json_roundtrips_every_field(tmp_path):
    b = _bundle(sigma_floors={"diameter_mm": 1.5}, tier=2, provenance="backup")
    p = write_session_json(tmp_path / "phase-b" / "bundle", b)
    assert p == tmp_path / "phase-b" / "bundle" / "session.json"
    got = json.loads(p.read_text(encoding="utf-8"))
    assert got == {"name": "phase-b", "bundle_dir": "phase-b/bundle",
                   "has_db": True, "db_verified": 1.0, "mm_per_px": 0.0787,
                   "sigma_floors": {"diameter_mm": 1.5}, "tier": 2,
                   "provenance": "backup"}


def test_write_session_json_creates_missing_directories(tmp_path):
    ziel = tmp_path / "neu" / "tief" / "bundle"
    assert not ziel.exists()
    p = write_session_json(ziel, _bundle())
    assert p.exists()


def test_write_session_json_overwrites_an_older_state(tmp_path):
    write_session_json(tmp_path, _bundle(tier=2, db_verified=1.0))
    write_session_json(tmp_path, _bundle(tier=1, db_verified=0.4))
    got = json.loads((tmp_path / "session.json").read_text(encoding="utf-8"))
    assert got["tier"] == 1 and got["db_verified"] == 0.4
