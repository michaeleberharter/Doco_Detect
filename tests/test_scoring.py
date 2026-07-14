"""Tests für das statistische Scoring: Enrollment-Statistiken, Ring-Zonen,
Fisher-adaptive Gewichte, Entscheidungslogik, Report-Serialisierung, Batch.

Run: pytest tests/test_scoring.py -v
"""

import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2  # noqa: E402

from docodetect.calibration import Calibration  # noqa: E402
from docodetect.features import (Features, EnrollmentStats,  # noqa: E402
                                 bhattacharyya_distance, compute_enrollment_stats,
                                 delta_e_cie76, extract, hu_log_distance)
from docodetect.segmentation import segment  # noqa: E402

MM_PER_PX = 0.2
CAL = Calibration(mm_per_px=MM_PER_PX, camera_height_mm=300.0, image_width=1920,
                  image_height=1080, marker_size_mm=50.0, created_unix=0.0)
SEG_CFG = {"segmentation": {"blur_kernel": 7, "diff_threshold": 25,
                            "morph_kernel": 15, "min_area_px": 5000,
                            "border_margin_px": 5}}


def _bg(fill=200):
    bg = np.full((1080, 1920, 3), fill, dtype=np.uint8)
    noise = np.random.default_rng(42).integers(-5, 5, bg.shape, dtype=np.int16)
    return np.clip(bg.astype(np.int16) + noise, 0, 255).astype(np.uint8)


def _red_rim_plate(bg, d_mm=200.0):
    img = bg.copy()
    r = int(round(d_mm / MM_PER_PX / 2))
    cv2.circle(img, (960, 540), r, (40, 40, 220), -1)      # rote Fahne (BGR)
    cv2.circle(img, (960, 540), int(r * 0.62), (250, 250, 250), -1)  # weißes Zentrum
    return img


def fake_features(diameter=200.0, circ=0.90, hu=None, **kw) -> Features:
    return Features(
        equiv_diameter_mm=diameter, circle_diameter_mm=diameter,
        area_mm2=3.14159 * (diameter / 2) ** 2, perimeter_mm=3.14159 * diameter,
        circularity=circ, aspect_ratio=1.0,
        mean_hsv=[0.0, 0.0, 200.0], hue_hist=[1.0 / 32] * 32,
        mean_saturation=0.0, hu_moments=hu or [3.2, 8.0, 10.0, 10.0, 10.0, 10.0, 10.0],
        **kw)


# ---------- Teil 1: Enrollment-Statistiken ----------

def test_enrollment_stats_mean_and_std():
    shots = [fake_features(diameter=d, circ=c)
             for d, c in ((199.0, 0.90), (200.0, 0.91), (201.0, 0.92))]
    st = compute_enrollment_stats(shots)
    assert st.n_shots == 3
    assert math.isclose(st.scalar_mean["diameter_mm"], 200.0)
    assert math.isclose(st.scalar_std["diameter_mm"], 1.0)          # ddof=1
    assert math.isclose(st.scalar_mean["circularity"], 0.91)
    assert st.proto["hu_log"] == pytest.approx([3.2, 8.0, 10.0, 10.0, 10.0, 10.0, 10.0])
    assert st.proto_std["hu_log"] == pytest.approx(0.0)


def test_enrollment_stats_single_shot_has_zero_std():
    st = compute_enrollment_stats([fake_features()])
    assert st.scalar_std["diameter_mm"] == 0.0
    assert st.proto_std["hu_log"] == 0.0


def test_enrollment_stats_json_roundtrip():
    st = compute_enrollment_stats([fake_features(199.0), fake_features(201.0)])
    st2 = EnrollmentStats.from_json(st.to_json())
    assert st2 == st


def test_hu_log_distance():
    assert hu_log_distance([1.0, 2.0], [2.0, 4.0]) == pytest.approx(1.5)


# ---------- Teil 2: Ring-Zonen + Solidity ----------

def test_ring_zones_separate_center_and_rim_color():
    bg = _bg()
    img = _red_rim_plate(bg)
    seg = segment(img, bg, SEG_CFG)
    feats = extract(img, seg, CAL, SEG_CFG)
    assert feats.solidity > 0.9                       # Vollkreis
    assert len(feats.lab_center) == 3 and len(feats.lab_rim) == 3
    assert delta_e_cie76(feats.lab_center, feats.lab_rim) > 25   # weiß vs rot
    assert feats.lab_center[0] > feats.lab_rim[0]                # Zentrum heller
    assert abs(sum(feats.hs_hist_center) - 1.0) < 1e-3
    assert bhattacharyya_distance(feats.hs_hist_center, feats.hs_hist_rim) > 0.3


def test_features_json_backward_compatible():
    """Alte Referenz-JSONs (ohne Zonen/Solidity) müssen weiter laden."""
    old = fake_features().to_json()
    d = json.loads(old)
    for k in ("solidity", "lab_center", "lab_rim", "hs_hist_center", "hs_hist_rim"):
        d.pop(k, None)
    f = Features.from_json(json.dumps(d))
    assert f.solidity == 0.0 and f.lab_center == []


# ---------- Teil 2: Zonen-Prototypen + proto_distance ----------

from docodetect.features import proto_distance  # noqa: E402


def fake_features_full(diameter=200.0, circ=0.90, sol=0.95,
                       lab_c=(95.0, 0.0, 0.0), lab_r=(95.0, 0.0, 0.0),
                       peak_c=0, peak_r=0, hu=None) -> Features:
    def hist(peak):
        h = [0.0] * 128
        h[peak] = 1.0
        return h
    f = fake_features(diameter, circ, hu)
    f.solidity = sol
    f.lab_center, f.lab_rim = list(lab_c), list(lab_r)
    f.hs_hist_center, f.hs_hist_rim = hist(peak_c), hist(peak_r)
    return f


def test_stats_include_zone_prototypes_and_solidity():
    shots = [fake_features_full(lab_c=(94.0, 0.0, 0.0)),
             fake_features_full(lab_c=(96.0, 0.0, 0.0))]
    st = compute_enrollment_stats(shots)
    assert math.isclose(st.scalar_mean["solidity"], 0.95)
    assert st.proto["delta_e_center"] == pytest.approx([95.0, 0.0, 0.0])
    assert st.proto_std["delta_e_center"] == pytest.approx(1.0)   # RMS von (1,1)
    assert "hist_center" in st.proto and "delta_e_rim" in st.proto


def test_stats_skip_zones_for_legacy_references():
    st = compute_enrollment_stats([fake_features(), fake_features()])  # ohne Zonen
    assert "delta_e_center" not in st.proto
    assert "solidity" not in st.scalar_mean
    assert "hu_log" in st.proto                                   # das gibt es immer


def test_proto_distance():
    st = compute_enrollment_stats([fake_features_full()])
    m = fake_features_full(lab_c=(90.0, 3.0, 4.0))
    assert proto_distance("delta_e_center", m, st) == pytest.approx(
        math.sqrt(25 + 9 + 16))
    assert proto_distance("hist_center", m, st) == pytest.approx(0.0, abs=1e-6)
    assert proto_distance("delta_e_center", fake_features(), st) is None  # Messung ohne Zone
    assert proto_distance("hist_center", m,
                          compute_enrollment_stats([fake_features()])) is None


# ---------- Teil 1: reference_stats-Tabelle ----------

from docodetect.database import Article, Database  # noqa: E402


def _db(tmp_path) -> Database:
    db = Database({"paths": {"db_file": str(tmp_path / "t.sqlite3")}})
    db.init_schema()
    return db


def _add_article(db, nr="TELLER-200", d=200.0):
    db.create_article(Article(article_number=nr, name=nr, category=None,
                              diameter_mm=d, width_mm=None, depth_mm=None,
                              height_mm=None, color_desc=None, notes=None))


def test_add_reference_maintains_stats(tmp_path):
    db = _db(tmp_path); _add_article(db)
    try:
        db.add_reference("TELLER-200", fake_features(199.0))
        db.add_reference("TELLER-200", fake_features(201.0))
        st = db.stats_for("TELLER-200")
        assert st is not None and st.n_shots == 2
        assert math.isclose(st.scalar_mean["diameter_mm"], 200.0)
        assert st.scalar_std["diameter_mm"] > 0
    finally:
        db.close()


def test_stats_missing_returns_none_and_delete_clears(tmp_path):
    db = _db(tmp_path); _add_article(db)
    try:
        assert db.stats_for("TELLER-200") is None
        db.add_reference("TELLER-200", fake_features())
        assert db.stats_for("TELLER-200") is not None
        db.delete_article("TELLER-200")
        assert db.stats_for("TELLER-200") is None
    finally:
        db.close()


def test_migration_backfills_stats_for_existing_db(tmp_path):
    """Bestands-DB: Referenzen existieren, reference_stats (noch) nicht ->
    init_schema legt die Tabelle an und recompute_all_stats füllt sie."""
    db = _db(tmp_path); _add_article(db)
    db.add_reference("TELLER-200", fake_features())
    db.conn.execute("DROP TABLE reference_stats")     # simuliert alte DB
    db.conn.commit(); db.close()
    db2 = Database({"paths": {"db_file": str(tmp_path / "t.sqlite3")}})
    try:
        db2.init_schema()                              # Migration
        assert db2.stats_for("TELLER-200") is not None
    finally:
        db2.close()
