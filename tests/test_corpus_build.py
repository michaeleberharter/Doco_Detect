"""corpus-build: Idempotenz, Dedup per Hash, Tier-Herabstufung."""

import json
import shutil
import sqlite3
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.corpus import build as corpus_build
from docodetect.corpus.manifest import Manifest


@pytest.fixture
def welt(tmp_path, monkeypatch):
    """Miniaturprojekt: eine Session, zwei Bilder, ein passender DB-Snapshot."""
    quelle = tmp_path / "quelle"
    (quelle / "reports").mkdir(parents=True)
    korpus = tmp_path / "korpus"
    monkeypatch.setattr("docodetect.corpus.manifest.MANIFEST_PATH",
                        tmp_path / "manifest.json")

    kal = tmp_path / "calibration"
    kal.mkdir()
    cv2.imwrite(str(kal / "background.png"), np.zeros((40, 40, 3), np.uint8))
    (kal / "calibration.json").write_text(json.dumps(
        {"mm_per_px": 0.0787, "camera_height_mm": 300.0, "image_width": 40,
         "image_height": 40, "marker_size_mm": 72.5, "created_unix": 1.0}))

    db = tmp_path / "db.sqlite3"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE reference_stats (article_number TEXT PRIMARY KEY,"
                " stats_json TEXT NOT NULL, updated_unix REAL)")
    con.execute("INSERT INTO reference_stats VALUES (?,?,?)",
                ("LOEFFEL-1", json.dumps({"n_shots": 9,
                 "scalar_mean": {"diameter_mm": 194.43}}), 0.0))
    con.commit(); con.close()

    for i, (verdict, label) in enumerate([("correct", "LOEFFEL-1"), (None, None)]):
        img = quelle / f"bild_{i}.png"
        cv2.imwrite(str(img), np.full((40, 40, 3), 10 * (i + 1), np.uint8))
        rep = {
            "decision": "accept", "message": "", "candidates": [{
                "article_number": "LOEFFEL-1", "name": "L1",
                "nominal_size_mm": 197.47, "height_mm": 0.0,
                "corrected_diameter_mm": 190.5, "geometry_error_mm": 0.0,
                "has_references": True, "n_shots": 9,
                "features": [{"feature": "diameter_mm", "measured": 190.5,
                              "reference": 194.43, "distance": 0.1,
                              "sigma_enroll": 1.9, "sigma_eff": 2.42, "z": 0.04,
                              "log_contrib": -0.001, "w_eff": 0.52,
                              "weighted": -0.0005}],
                "log_score": -0.1, "posterior": 0.9, "max_abs_z": 0.04,
                "margin_to_next": None}],
            "measured": {"circle_diameter_mm": 190.5},
            "contour": [[0, 0], [10, 0], [10, 10], [0, 10]],
            "timestamp": "2026-07-20T17:31:42", "image_path": str(img),
            "label": label, "verdict": verdict,
        }
        (quelle / "reports" / f"r_{i}.json").write_text(json.dumps(rep))

    cfg = {"paths": {"corpus_dir": str(korpus)}}
    monkeypatch.setattr(corpus_build, "SOURCES", [
        ("test-session", str(quelle / "reports"), str(quelle))])
    monkeypatch.setattr(corpus_build, "BUNDLE_QUELLEN", {
        "test-session": {"background": str(kal / "background.png"),
                         "calibration": str(kal / "calibration.json"),
                         "db": str(db)}})
    return cfg, korpus, quelle


def test_build_creates_the_expected_layout(welt):
    cfg, korpus, _ = welt
    corpus_build.build_corpus(cfg)
    assert (korpus / "test-session" / "bundle" / "session.json").exists()
    assert (korpus / "test-session" / "bundle" / "background.png").exists()
    assert (korpus / "test-session" / "bundle" / "db.sqlite3").exists()
    assert list((korpus / "test-session" / "images" / "LOEFFEL-1").glob("*.png"))


def test_build_sorts_unjudged_images_into_unbewertet(welt):
    cfg, korpus, _ = welt
    corpus_build.build_corpus(cfg)
    assert list((korpus / "test-session" / "images" / "_unbewertet").glob("*.png"))


def test_unjudged_images_are_tier1_only(welt):
    cfg, _, _ = welt
    corpus_build.build_corpus(cfg)
    m = Manifest.load()
    unbewertet = [e for e in m.images if e.article == "_unbewertet"]
    assert unbewertet and all(e.tier == 1 for e in unbewertet)


def test_verified_db_lifts_the_session_to_tier2(welt):
    cfg, _, _ = welt
    corpus_build.build_corpus(cfg)
    m = Manifest.load()
    assert m.sessions["test-session"]["db_verified"] == 1.0
    assert m.sessions["test-session"]["tier"] == 2


def test_mismatching_db_forces_tier1(welt, tmp_path, monkeypatch):
    cfg, _, _ = welt
    fremd = tmp_path / "fremd.sqlite3"
    con = sqlite3.connect(fremd)
    con.execute("CREATE TABLE reference_stats (article_number TEXT PRIMARY KEY,"
                " stats_json TEXT NOT NULL, updated_unix REAL)")
    con.execute("INSERT INTO reference_stats VALUES (?,?,?)",
                ("LOEFFEL-1", json.dumps({"n_shots": 9,
                 "scalar_mean": {"diameter_mm": 111.11}}), 0.0))
    con.commit(); con.close()
    corpus_build.BUNDLE_QUELLEN["test-session"]["db"] = str(fremd)
    corpus_build.build_corpus(cfg)
    m = Manifest.load()
    assert m.sessions["test-session"]["db_verified"] == 0.0
    assert m.sessions["test-session"]["tier"] == 1
    assert all(e.tier == 1 for e in m.images)


def test_build_is_idempotent(welt):
    cfg, _, _ = welt
    erst = corpus_build.build_corpus(cfg)
    zweit = corpus_build.build_corpus(cfg)
    assert erst["neu"] == 2
    assert zweit["neu"] == 0
    assert zweit["gesamt"] == erst["gesamt"]


def test_build_deduplicates_identical_images(welt):
    cfg, _, quelle = welt
    # dasselbe Bild ein zweites Mal, unter anderem Namen und mit eigenem Report
    doppelt = quelle / "bild_doppelt.png"
    shutil.copy(quelle / "bild_0.png", doppelt)
    rep = json.loads((quelle / "reports" / "r_0.json").read_text())
    rep["image_path"] = str(doppelt)
    (quelle / "reports" / "r_doppelt.json").write_text(json.dumps(rep))
    stat = corpus_build.build_corpus(cfg)
    assert stat["uebersprungen_dublette"] == 1


def test_build_never_writes_into_the_source_db(welt):
    cfg, _, _ = welt
    db = Path(corpus_build.BUNDLE_QUELLEN["test-session"]["db"])
    vorher = db.read_bytes()
    corpus_build.build_corpus(cfg)
    assert db.read_bytes() == vorher
