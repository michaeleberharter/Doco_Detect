"""Admin-Panel Stufe 3 Teil A: Artikelliste mit wirksamem Vorfilter-Nominal.

Qt offscreen, Temp-DB unter tmp_path. Das wirksame Nominal kommt über
pipeline.nominal_size_mm (= matcher._nominal_size_mm) — der Test prüft
ausdrücklich max(width, depth) statt hypot (Fehler vom 2026-07-21).
Läuft im Test-Regime als EIGENER pytest-Aufruf in der UI-Schleife."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(scope="module")
def qapp():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from docodetect.ui_qt.app import make_app
    return make_app()


def _cfg(tmp_path):
    return {
        "calibration": {
            "file": str(tmp_path / "calibration.json"),
            "background_file": str(tmp_path / "background.png"),
        },
        "paths": {"db_file": str(tmp_path / "db.sqlite3"),
                  "captures_dir": str(tmp_path / "captures")},
        "analysis": {"output_dir": str(tmp_path / "runs")},
        "matching": {"diameter_tolerance_mm": 6.0, "top_k": 3},
        "stage2": {"enabled": False},
    }


def _db_mit_artikeln(cfg):
    from docodetect.database import Article, Database
    db = Database(cfg)
    db.init_schema()
    db.create_article(Article(article_number="T-270", name="Teller 27",
                              category="Teller", diameter_mm=270.0,
                              width_mm=None, depth_mm=None, height_mm=25.0,
                              color_desc=None, notes=None))
    db.create_article(Article(article_number="LOEFFEL-1", name="Loeffel",
                              category="Besteck", diameter_mm=None,
                              width_mm=186.9, depth_mm=45.0, height_mm=20.0,
                              color_desc=None, notes=None))
    db.create_article(Article(article_number="X-0", name="Ohne Masse",
                              category=None, diameter_mm=None, width_mm=None,
                              depth_mm=None, height_mm=None,
                              color_desc=None, notes=None))
    db.close()


def test_artikelliste_wirksames_nominal_und_band(qapp, tmp_path):
    from docodetect.ui_qt.admin.pages.articles_page import ArticlesPage
    cfg = _cfg(tmp_path)
    _db_mit_artikeln(cfg)
    page = ArticlesPage(cfg)
    zeilen = {z["artikelnummer"]: z for z in page.zeilen()}
    assert zeilen["LOEFFEL-1"]["nominal"] == "186,9"       # max, nie hypot
    assert zeilen["LOEFFEL-1"]["band"] == "180,9 – 192,9"
    assert zeilen["T-270"]["nominal"] == "270,0"
    assert zeilen["T-270"]["band"] == "264,0 – 276,0"
    assert zeilen["X-0"]["nominal"] == "—"
    assert zeilen["X-0"]["band"] == "—"
    assert zeilen["LOEFFEL-1"]["referenzen"] == "0"
    assert zeilen["LOEFFEL-1"]["breite"] == "186,9"
    assert zeilen["T-270"]["breite"] == "—"
    assert "3 Artikel" in page.kopf_text()
    assert "±6,0 mm" in page.kopf_text()


def test_artikelliste_leerzustand_ohne_db(qapp, tmp_path):
    from docodetect.ui_qt.admin.pages.articles_page import ArticlesPage
    page = ArticlesPage(_cfg(tmp_path))
    assert page.zeilen() == []
    assert "Keine Artikel" in page.kopf_text()


# ---------- Referenz-Kennzahlen (Stufe 3 Teil B1, Freigabe 2026-08-11) ----------

def _referenz_anlegen(cfg, artikel="T-270", n=2):
    from docodetect.database import Database
    from docodetect.features import Features
    db = Database(cfg)
    for d in [270.0 + 0.4 * i for i in range(n)]:
        db.add_reference(artikel, Features(
            equiv_diameter_mm=d, circle_diameter_mm=d, area_mm2=57255.0,
            perimeter_mm=848.0, circularity=0.95, aspect_ratio=1.0,
            mean_hsv=[0.0, 0.0, 200.0], solidity=0.99, hu_moments=[1.0] * 7,
            lab_center=[80.0, 0.0, 0.0], lab_rim=[80.0, 0.0, 0.0],
            hs_hist_center=[1.0], hs_hist_rim=[1.0]))
    db.close()


def test_detail_zeigt_kennzahlen_und_min_n_marker(qapp, tmp_path):
    from docodetect.ui_qt.admin.pages.articles_page import ArticlesPage
    cfg = _cfg(tmp_path)
    _db_mit_artikeln(cfg)
    _referenz_anlegen(cfg, "T-270", n=2)
    page = ArticlesPage(cfg)
    zeile = [i for i, z in enumerate(page.zeilen())
             if z["artikelnummer"] == "T-270"][0]
    page._tabelle.setCurrentCell(zeile, 0)
    d = page.detail_werte()
    assert d["artikel"] == "T-270"
    assert d["n_shots"] == 2
    assert "n=2 < 10" in d["marker"]            # MIN_N aus floor_analysis
    assert "Floor-Schätzung unsicher" in d["marker"]
    skalare = {z["merkmal"]: z for z in d["skalare"]}
    assert skalare["diameter_mm"]["mittel"] == "270,20"
    assert skalare["diameter_mm"]["sigma"] == "0,28"
    kanaele = {z["kanal"]: z for z in d["kanaele"]}
    assert "delta_e_center" in kanaele
    assert "hu_log" in kanaele


def test_detail_ohne_stats_und_sigma_null_marker(qapp, tmp_path):
    from docodetect.ui_qt.admin.pages.articles_page import ArticlesPage
    cfg = _cfg(tmp_path)
    _db_mit_artikeln(cfg)
    # X-0 hat keine Referenzen -> keine Statistik
    page = ArticlesPage(cfg)
    zeile = [i for i, z in enumerate(page.zeilen())
             if z["artikelnummer"] == "X-0"][0]
    page._tabelle.setCurrentCell(zeile, 0)
    assert "keine Enrollment-Statistik" in page.detail_werte()["marker"]
    # Zwei IDENTISCHE Shots -> sigma 0 bei n>1: verdaechtig-Marker
    _referenz_anlegen(cfg, "LOEFFEL-1", n=1)
    _referenz_anlegen(cfg, "LOEFFEL-1", n=1)
    page.reload()
    zeile = [i for i, z in enumerate(page.zeilen())
             if z["artikelnummer"] == "LOEFFEL-1"][0]
    page._tabelle.setCurrentCell(zeile, 0)
    d = page.detail_werte()
    assert d["n_shots"] == 2
    assert "σ=0" in d["marker"] and "verdächtig" in d["marker"]
