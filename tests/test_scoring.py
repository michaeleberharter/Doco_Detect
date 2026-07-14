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


# ---------- Teil 3: statistischer Matcher ----------

from docodetect.matcher import MatchReport, match  # noqa: E402

MATCH_CFG = {"matching": {
    "diameter_tolerance_mm": 6.0, "area_tolerance_pct": 12.0,
    "sigma_floors": {"diameter_mm": 1.5, "circularity": 0.02, "solidity": 0.015,
                     "delta_e": 3.0, "hist_bhattacharyya": 0.05, "hu_log": 0.15},
    "feature_weights": {"diameter_mm": 0.50, "circularity": 0.07, "solidity": 0.06,
                        "delta_e_center": 0.08, "delta_e_rim": 0.08,
                        "hist_center": 0.07, "hist_rim": 0.07, "hu_log": 0.07},
    "adaptive_weight_alpha": 2.0, "softmax_temperature": 1.0,
    "max_z_accept": 3.5, "min_llr_margin": 2.0, "top_k": 3,
}}


def _matcher_db(tmp_path, articles):
    """articles: list of (nr, nominal_d, [ref-Features])"""
    db = _db(tmp_path)
    for nr, d, refs in articles:
        _add_article(db, nr, d)
        for f in refs:
            db.add_reference(nr, f)
    return db


def test_sigma_floor_dominates_when_enrollment_std_zero(tmp_path):
    db = _matcher_db(tmp_path, [("A", 200.0, [fake_features_full(), fake_features_full()])])
    try:
        rep = match(fake_features_full(), db, CAL, MATCH_CFG)
        fs = {f.feature: f for f in rep.candidates[0].features}
        assert fs["diameter_mm"].sigma_eff == pytest.approx(1.5)
        assert fs["delta_e_center"].sigma_eff == pytest.approx(3.0)
        assert fs["diameter_mm"].z == pytest.approx(0.0)
        assert rep.candidates[0].log_score == pytest.approx(0.0)
    finally:
        db.close()


def test_sigma_eff_combines_enroll_and_floor(tmp_path):
    shots = [fake_features_full(diameter=198.0), fake_features_full(diameter=202.0)]
    db = _matcher_db(tmp_path, [("A", 200.0, shots)])
    try:
        rep = match(fake_features_full(diameter=200.0), db, CAL, MATCH_CFG)
        fs = {f.feature: f for f in rep.candidates[0].features}
        expected = math.sqrt(np.std([198.0, 202.0], ddof=1) ** 2 + 1.5 ** 2)
        assert fs["diameter_mm"].sigma_eff == pytest.approx(expected, abs=1e-3)
    finally:
        db.close()


def test_geometry_only_candidate_scored_on_diameter_alone(tmp_path):
    db = _matcher_db(tmp_path, [("A", 200.0, [])])
    try:
        rep = match(fake_features_full(diameter=202.0), db, CAL, MATCH_CFG)
        c = rep.candidates[0]
        assert not c.has_references
        assert [f.feature for f in c.features] == ["diameter_mm"]
        assert c.features[0].reference == pytest.approx(200.0)
        assert c.features[0].distance == pytest.approx(2.0)
    finally:
        db.close()


def test_matchreport_json_roundtrip(tmp_path):
    db = _matcher_db(tmp_path, [("A", 200.0, [fake_features_full()])])
    try:
        rep = match(fake_features_full(), db, CAL, MATCH_CFG,
                    image_path="x.jpg", label="A", contour=[[1, 2], [3, 4]],
                    touches_border=False)
        rep2 = MatchReport.from_json(rep.to_json())
        assert rep2.to_dict() == rep.to_dict()
        assert rep2.candidates[0].features[0].feature == rep.candidates[0].features[0].feature
    finally:
        db.close()


def test_fisher_boosts_the_discriminative_feature(tmp_path):
    """Konstruierter Fall: zwei Kandidaten, identisch bis auf die Zentrums-
    farbe -> delta_e_center muss das höchste w_eff bekommen (Kern der
    adaptiven Gewichtung). Uniforme Globalgewichte isolieren den Mechanismus
    (mit Produktionsgewichten würde das dominante Ø-Gewicht den Boost-Faktor
    1+alpha kaufmännisch überstimmen – gewollt, Ø ist dort bewusst schwer)."""
    uniform = dict.fromkeys(MATCH_CFG["matching"]["feature_weights"], 1.0)
    cfg = {"matching": {**MATCH_CFG["matching"], "feature_weights": uniform}}
    a_shots = [fake_features_full(lab_c=(95.0, 0.0, 0.0))] * 2
    b_shots = [fake_features_full(lab_c=(55.0, 10.0, 10.0))] * 2
    db = _matcher_db(tmp_path, [("A", 200.0, a_shots), ("B", 200.0, b_shots)])
    try:
        rep = match(fake_features_full(lab_c=(95.0, 0.0, 0.0)), db, CAL, cfg)
        assert max(rep.w_eff, key=rep.w_eff.get) == "delta_e_center"
        assert rep.w_eff["delta_e_center"] > rep.w_global["delta_e_center"]
        assert rep.fisher_d_norm["delta_e_center"] == max(rep.fisher_d_norm.values())
        assert rep.candidates[0].article_number == "A"
    finally:
        db.close()


def test_alpha_zero_keeps_global_weights(tmp_path):
    cfg = {"matching": {**MATCH_CFG["matching"], "adaptive_weight_alpha": 0.0}}
    db = _matcher_db(tmp_path, [("A", 200.0, [fake_features_full()] * 2),
                                ("B", 200.0, [fake_features_full(lab_c=(55.0, 0.0, 0.0))] * 2)])
    try:
        rep = match(fake_features_full(), db, CAL, cfg)
        for f in rep.w_eff:
            assert rep.w_eff[f] == pytest.approx(rep.w_global[f])
    finally:
        db.close()


def test_single_candidate_skips_adaptation(tmp_path):
    db = _matcher_db(tmp_path, [("A", 200.0, [fake_features_full()] * 2)])
    try:
        rep = match(fake_features_full(), db, CAL, MATCH_CFG)
        assert rep.fisher_d == {}
        assert rep.w_eff == pytest.approx(rep.w_global)
    finally:
        db.close()


def test_decision_accept(tmp_path):
    db = _matcher_db(tmp_path, [("A", 200.0, [fake_features_full()] * 3)])
    try:
        rep = match(fake_features_full(), db, CAL, MATCH_CFG)
        assert rep.decision == "accept" and rep.gate_passed
        assert rep.max_z_winner == pytest.approx(0.0)
        assert rep.candidates[0].posterior == pytest.approx(1.0)
    finally:
        db.close()


def test_decision_ambiguous_on_small_margin(tmp_path):
    """Fast identische Artikel -> Gate ok, LLR-Margin < Schwelle -> ambiguous."""
    db = _matcher_db(tmp_path, [("A", 200.0, [fake_features_full()] * 2),
                                ("B", 200.0, [fake_features_full(diameter=200.5)] * 2)])
    try:
        rep = match(fake_features_full(diameter=200.2), db, CAL, MATCH_CFG)
        assert rep.decision == "ambiguous"
        assert rep.gate_passed and rep.llr_margin is not None
        assert rep.llr_margin < 2.0
    finally:
        db.close()


def test_decision_reject_on_gate(tmp_path):
    """Durchmesser passt, aber Farbe völlig anders -> max|z| >> 3.5 -> reject."""
    db = _matcher_db(tmp_path, [("A", 200.0, [fake_features_full(lab_c=(95.0, 0.0, 0.0),
                                                                 lab_r=(95.0, 0.0, 0.0))] * 2)])
    try:
        m = fake_features_full(lab_c=(20.0, 30.0, 30.0), lab_r=(20.0, 30.0, 30.0))
        rep = match(m, db, CAL, MATCH_CFG)
        assert rep.decision == "reject" and not rep.gate_passed
        assert rep.max_z_winner > 3.5
        assert "nicht in der Datenbank" in rep.message
    finally:
        db.close()


def test_geometry_only_winner_never_accepts(tmp_path):
    db = _matcher_db(tmp_path, [("A", 200.0, [])])
    try:
        rep = match(fake_features_full(), db, CAL, MATCH_CFG)
        assert rep.decision == "ambiguous"        # Gate ok, aber keine Referenzen
    finally:
        db.close()


def test_no_candidate_is_reject(tmp_path):
    db = _matcher_db(tmp_path, [("A", 300.0, [])])   # weit außerhalb der Toleranz
    try:
        rep = match(fake_features_full(diameter=200.0), db, CAL, MATCH_CFG)
        assert rep.decision == "reject" and rep.candidates == []
    finally:
        db.close()


# ---------- Teil 3: Pipeline speichert Capture + Report-JSON ----------

from docodetect.pipeline import Pipeline  # noqa: E402


def test_identify_writes_report_json(tmp_path, monkeypatch):
    import docodetect.config as cfgmod
    monkeypatch.setattr(cfgmod, "project_root", lambda: tmp_path)  # resolve() -> tmp
    bg = _bg()
    cfg = {"segmentation": SEG_CFG["segmentation"], "matching": MATCH_CFG["matching"],
           "features": {}, "paths": {"db_file": str(tmp_path / "t.sqlite3"),
                                     "captures_dir": "captures"}}
    pipe = Pipeline.__new__(Pipeline)
    pipe.cfg, pipe.cal, pipe.background = cfg, CAL, bg
    pipe.db = Database(cfg); pipe.db.init_schema()
    try:
        img = _red_rim_plate(bg)
        out = pipe.identify(img)
        jsons = list((tmp_path / "captures").glob("*.json"))
        jpgs = list((tmp_path / "captures").glob("*.jpg"))
        assert len(jsons) == 1 and len(jpgs) == 1
        rep = MatchReport.from_json(jsons[0].read_text(encoding="utf-8"))
        assert rep.decision == out.report.decision
        assert rep.image_path and rep.contour
    finally:
        pipe.db.close()


def test_identify_border_touch_becomes_reject_report(tmp_path):
    bg = _bg()
    cfg = {"segmentation": SEG_CFG["segmentation"], "matching": MATCH_CFG["matching"],
           "paths": {"db_file": str(tmp_path / "t.sqlite3")}}   # kein captures_dir -> kein IO
    pipe = Pipeline.__new__(Pipeline)
    pipe.cfg, pipe.cal, pipe.background = cfg, CAL, bg
    pipe.db = Database(cfg); pipe.db.init_schema()
    try:
        img = bg.copy()
        cv2.circle(img, (30, 540), 500, (250, 250, 250), -1)    # ragt aus dem Bild
        out = pipe.identify(img)
        assert out.report.decision == "reject"
        assert "Segment" in out.report.message
        assert out.report.candidates == []
    finally:
        pipe.db.close()


# ---------- Teil 5: synthetisches Testkit end-to-end ----------

# Weitwinkligere Test-Kalibrierung: bei 0.2 mm/px passt ein 270er-Teller nicht
# in 1920x1080 (die reale FOV-Limitierung!); mit 0.3 mm/px passen 250 UND 270.
CAL_WIDE = Calibration(mm_per_px=0.3, camera_height_mm=300.0, image_width=1920,
                       image_height=1080, marker_size_mm=50.0, created_unix=0.0)


def _synth_pipeline(tmp_path, bg, matching_overrides=None, cal=CAL):
    cfg = {"segmentation": SEG_CFG["segmentation"], "features": {},
           "matching": {**MATCH_CFG["matching"], **(matching_overrides or {})},
           "create": {"round_circularity_min": 0.80, "round_aspect_min": 0.80,
                      "article_number_prefix": ""},
           "paths": {"db_file": str(tmp_path / "t.sqlite3")}}
    pipe = Pipeline.__new__(Pipeline)
    pipe.cfg, pipe.cal, pipe.background = cfg, cal, bg
    pipe.db = Database(cfg)
    pipe.db.init_schema()
    return pipe


def _plate(bg, d_mm, jitter=0, mm_per_px=MM_PER_PX):
    img = bg.copy()
    r = int(round(d_mm / mm_per_px / 2)) + jitter
    cv2.circle(img, (960, 540), r, (250, 250, 250), -1)
    cv2.circle(img, (960, 540), r, (150, 150, 150), 3)
    return img


def test_plates_250_vs_270_cleanly_separated(tmp_path):
    """Regime 'ähnliche Größe': Toleranz so weit, dass BEIDE Teller den
    Vorfilter überleben - das Scoring (Fisher boostet den Ø) muss trennen."""
    bg = _bg()
    pipe = _synth_pipeline(tmp_path, bg, {"diameter_tolerance_mm": 25.0},
                           cal=CAL_WIDE)
    try:
        for nr, d in (("TELLER-250", 250.0), ("TELLER-270", 270.0)):
            _add_article(pipe.db, nr, d)
            for j in (-1, 0, 1):                      # 3 Shots mit Pixel-Jitter
                seg, feats = pipe.analyze(_plate(bg, d, j, mm_per_px=0.3))
                pipe.db.add_reference(nr, feats)
        for truth, d in (("TELLER-250", 250.0), ("TELLER-270", 270.0)):
            out = pipe.identify(_plate(bg, d, mm_per_px=0.3))
            rep = out.report
            assert len(rep.candidates) == 2           # beide im Kandidatenset
            assert rep.candidates[0].article_number == truth
            assert rep.decision == "accept", rep.message
            assert rep.w_eff["diameter_mm"] > rep.w_global["diameter_mm"]  # Fisher greift
    finally:
        pipe.db.close()


def test_border_clipped_plate_is_segmentation_reject_not_scored(tmp_path):
    bg = _bg()
    pipe = _synth_pipeline(tmp_path, bg)
    try:
        _add_article(pipe.db, "TELLER-210", 210.0)
        img = bg.copy()
        cv2.circle(img, (30, 540), int(210.0 / MM_PER_PX / 2), (250, 250, 250), -1)
        out = pipe.identify(img)
        assert out.report.decision == "reject"
        assert "Segment" in out.report.message and out.report.candidates == []
    finally:
        pipe.db.close()


def test_unknown_object_rejected(tmp_path):
    """Testkit-Bild 5: Objekt, das keiner Artikelgeometrie entspricht."""
    bg = _bg()
    pipe = _synth_pipeline(tmp_path, bg)
    try:
        _add_article(pipe.db, "TELLER-270", 270.0)
        out = pipe.identify(_plate(bg, 120.0))        # viel zu klein
        assert out.report.decision == "reject"
    finally:
        pipe.db.close()
