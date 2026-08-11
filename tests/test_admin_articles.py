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
