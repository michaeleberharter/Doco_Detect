"""Session-Fingerprints: mm_per_px, sigma_floors, exakter DB-Abgleich."""

import json
import math
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.corpus.bundle import (bundle_cfg, copy_db_readonly,
                                      db_match_ratio, recover_mm_per_px,
                                      recover_sigma_floors)
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
