"""Tests für die dünne UI-Fassade in pipeline.py (get_status/list_articles).

Die Qt-UI (und jede weitere UI) ruft ausschließlich docodetect.pipeline auf.
get_status() muss auch VOR der Einrichtung funktionieren (keine Kalibrierung,
kein Hintergrund, keine DB) – daraus speist sich der NOT_READY-Zustand.
Keine Kamera, kein Qt nötig.
"""

import sys
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.calibration import Calibration  # noqa: E402
from docodetect.database import Database  # noqa: E402
from docodetect.pipeline import get_status, list_articles  # noqa: E402


def make_cfg(tmp_path):
    """Minimal-Config mit allen Pfaden unter tmp_path – nichts existiert."""
    return {
        "calibration": {
            "file": str(tmp_path / "calibration.json"),
            "background_file": str(tmp_path / "background.png"),
        },
        "paths": {"db_file": str(tmp_path / "db.sqlite3")},
        "stage2": {"enabled": False},
    }


def _seed_db(cfg, with_reference=False):
    """DB mit einem Artikel (und optional einer Referenz) anlegen."""
    from docodetect.features import Features

    db = Database(cfg)
    db.init_schema()
    from docodetect.database import Article
    db.create_article(Article(
        article_number="T-270", name="Teller flach 27", category="Teller",
        diameter_mm=270.0, width_mm=None, depth_mm=None, height_mm=25.0,
        color_desc=None, notes=None))
    if with_reference:
        feats = Features(
            equiv_diameter_mm=270.0, circle_diameter_mm=270.0, area_mm2=57255.0,
            perimeter_mm=848.0, circularity=0.95, aspect_ratio=1.0,
            mean_hsv=[0.0, 0.0, 200.0], solidity=0.99,
            hu_moments=[1.0] * 7,
            lab_center=[80.0, 0.0, 0.0], lab_rim=[80.0, 0.0, 0.0],
            hs_hist_center=[1.0], hs_hist_rim=[1.0])
        db.add_reference("T-270", feats)
    db.close()


# ---------- get_status: vor der Einrichtung ----------

def test_status_unconfigured(tmp_path):
    st = get_status(make_cfg(tmp_path))
    assert st.calibrated is False
    assert st.mm_per_px is None
    assert st.background_present is False
    assert st.article_count == 0
    assert st.articles_with_references == 0
    assert st.stage2_enabled is False
    assert st.ready is False


def test_status_does_not_create_files(tmp_path):
    """Eine Status-Abfrage darf keine Dateien anlegen (kein leeres sqlite)."""
    cfg = make_cfg(tmp_path)
    get_status(cfg)
    assert list(tmp_path.iterdir()) == []


# ---------- get_status: nach der Einrichtung ----------

def test_status_configured(tmp_path):
    cfg = make_cfg(tmp_path)
    Calibration(mm_per_px=0.171, camera_height_mm=300.0, image_width=1920,
                image_height=1080, marker_size_mm=136.0,
                created_unix=time.time()).save(cfg["calibration"]["file"])
    cv2.imwrite(cfg["calibration"]["background_file"],
                np.full((10, 10, 3), 200, dtype=np.uint8))
    _seed_db(cfg, with_reference=True)

    st = get_status(cfg)
    assert st.calibrated is True
    assert st.mm_per_px == pytest.approx(0.171)
    assert st.calibrated_unix is not None
    assert st.background_present is True
    assert st.article_count == 1
    assert st.articles_with_references == 1
    assert st.ready is True


def test_status_stage2_flag(tmp_path):
    cfg = make_cfg(tmp_path)
    cfg["stage2"] = {"enabled": True}
    assert get_status(cfg).stage2_enabled is True


def test_status_corrupt_calibration_is_not_calibrated(tmp_path):
    """Kaputte calibration.json => calibrated False, kein Crash."""
    cfg = make_cfg(tmp_path)
    Path(cfg["calibration"]["file"]).write_text("{kaputt", encoding="utf-8")
    st = get_status(cfg)
    assert st.calibrated is False
    assert st.ready is False


# ---------- list_articles ----------

def test_list_articles_empty_without_db(tmp_path):
    assert list_articles(make_cfg(tmp_path)) == []


def test_list_articles_with_reference_counts(tmp_path):
    cfg = make_cfg(tmp_path)
    _seed_db(cfg, with_reference=True)
    arts = list_articles(cfg)
    assert len(arts) == 1
    a = arts[0]
    assert a.article_number == "T-270"
    assert a.name == "Teller flach 27"
    assert a.diameter_mm == 270.0
    assert a.n_references == 1
