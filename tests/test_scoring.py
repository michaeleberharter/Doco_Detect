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

from docodetect.features import (Features, EnrollmentStats,  # noqa: E402
                                 compute_enrollment_stats, hu_log_distance)


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
