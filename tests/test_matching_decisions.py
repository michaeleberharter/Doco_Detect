"""Entscheidungs- und Randfall-Tests gegen den ECHTEN Matcher mit den
ECHTEN Schwellen aus config/config.yaml (Fixture, nie duplizieren).
Synthetische Feature-Vektoren, keine Kamera. Spec:
docs/superpowers/specs/2026-07-20-multi-candidate-decision-ui-design.md
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.calibration import Calibration  # noqa: E402
from docodetect.config import load_config  # noqa: E402
from docodetect.database import Article, Database  # noqa: E402
from docodetect.features import Features  # noqa: E402
from docodetect.matcher import match  # noqa: E402


@pytest.fixture()
def cfg(tmp_path):
    """Echte config.yaml (Schwellen NIE duplizieren); DB nach tmp,
    KEIN captures_dir -> identify/match schreiben nie nach data/."""
    c = load_config()
    c["paths"] = {"db_file": str(tmp_path / "t.sqlite3")}
    return c


@pytest.fixture()
def cal(cfg):
    return Calibration(mm_per_px=0.2,
                       camera_height_mm=float(cfg["geometry"]["camera_height_mm"]),
                       image_width=1920, image_height=1080,
                       marker_size_mm=50.0, created_unix=0.0)


def fake(d=200.0, lab=(95.0, 0.0, 0.0), peak=0):
    """Voller Feature-Satz (Zonen + Solidity), damit Kandidaten MIT
    Referenzen über alle Merkmale gescort werden."""
    def hist(p):
        h = [0.0] * 128
        h[p] = 1.0
        return h
    return Features(
        equiv_diameter_mm=d, circle_diameter_mm=d,
        area_mm2=3.14159 * (d / 2) ** 2, perimeter_mm=3.14159 * d,
        circularity=0.90, aspect_ratio=1.0,
        mean_hsv=[0.0, 0.0, 200.0], hue_hist=[1.0 / 32] * 32,
        mean_saturation=0.0,
        hu_moments=[3.2, 8.0, 10.0, 10.0, 10.0, 10.0, 10.0],
        solidity=0.95, lab_center=list(lab), lab_rim=list(lab),
        hs_hist_center=hist(peak), hs_hist_rim=hist(peak))


def make_db(cfg, articles):
    """articles: Liste (nr, diameter_mm, height_mm, [ref-Features])."""
    db = Database(cfg)
    db.init_schema()
    for nr, d, h, refs in articles:
        db.create_article(Article(article_number=nr, name=nr, category=None,
                                  diameter_mm=d, width_mm=None, depth_mm=None,
                                  height_mm=h, color_desc=None, notes=None))
        for f in refs:
            db.add_reference(nr, f)
    return db


# ---------- Task 1: margin_to_next ----------

def test_margin_to_next_ranked(cfg, cal, tmp_path):
    """Drei Kandidaten: Platz 1 tragt margin zum Zweiten (== llr_margin),
    der letzte None."""
    db = make_db(cfg, [
        ("A", 200.0, 0.0, [fake(200.0)] * 2),
        ("B", 200.0, 0.0, [fake(201.5)] * 2),
        ("C", 200.0, 0.0, [fake(203.0)] * 2),
    ])
    try:
        rep = match(fake(200.0), db, cal, cfg)
        assert len(rep.candidates) == 3
        c0, c1, c2 = rep.candidates
        assert c0.margin_to_next == pytest.approx(c0.log_score - c1.log_score)
        assert c0.margin_to_next == pytest.approx(rep.llr_margin)
        assert c1.margin_to_next == pytest.approx(c1.log_score - c2.log_score)
        assert c2.margin_to_next is None
    finally:
        db.close()


def test_margin_to_next_single_candidate_is_none(cfg, cal, tmp_path):
    db = make_db(cfg, [("A", 200.0, 0.0, [fake(200.0)] * 2)])
    try:
        rep = match(fake(200.0), db, cal, cfg)
        assert rep.candidates[0].margin_to_next is None
    finally:
        db.close()


def test_old_report_json_without_margin_field_loads(cfg, cal, tmp_path):
    """Rueckwaertskompatibilitaet: Alt-JSONs ohne margin_to_next laden."""
    from docodetect.matcher import MatchReport
    db = make_db(cfg, [("A", 200.0, 0.0, [fake(200.0)] * 2)])
    try:
        d = match(fake(200.0), db, cal, cfg).to_dict()
        for c in d["candidates"]:
            c.pop("margin_to_next")
        rep = MatchReport.from_dict(d)
        assert rep.candidates[0].margin_to_next is None
    finally:
        db.close()
