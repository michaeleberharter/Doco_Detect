"""Tests für die Lebenszyklus-Logik der Demo-Daten (docodetect/ui_qt/demo_seed.py).

Regression 2026-07-20: Die Demo-DB unter data/demo/ wird EINMAL geseedet und
ueberlebt Code-Aenderungen. Als Task 7 den Artikel DEMO-T19 und den
Radius-Jitter einfuehrte, blieb der alte Stand liegen:

  - DEMO-T19 fehlte  -> die "knapp"-Szene konnte nie zwei Kandidaten liefern
  - alle 5 Einlern-Shots pixelidentisch -> hu_proto_std ~ 0 -> sigma_eff faellt
    auf den Floor 0.15 -> z = 111 statt ~2 -> REJECT statt CONFIRM

Die alte Bedingung (`articles_with_references == 0`) konnte das nicht sehen:
Referenzen WAREN ja da, nur veraltete. Die Tests hier pinnen, dass ein
veralteter Demo-Stand erkannt und neu aufgebaut wird. Kein Qt noetig.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.config import load_config  # noqa: E402
from docodetect.database import Article, Database  # noqa: E402
from docodetect.ui_qt import demo_seed  # noqa: E402
from docodetect.ui_qt.demo_scenes import DEMO_ARTICLES  # noqa: E402


def demo_cfg(tmp_path, width=1920, height=1080):
    """Demo-Config komplett unter tmp_path (nie data/demo/ anfassen)."""
    cfg = load_config()
    cfg["camera"]["width"], cfg["camera"]["height"] = width, height
    cfg["calibration"]["file"] = str(tmp_path / "calibration.json")
    cfg["calibration"]["background_file"] = str(tmp_path / "background.png")
    cfg["paths"] = {"db_file": str(tmp_path / "demo.sqlite3"),
                    "reference_dir": str(tmp_path / "reference")}
    return cfg


def _seed_db(cfg, article_numbers, with_reference=True):
    """DB-Zustand direkt bauen (ohne Bildverarbeitung) – simuliert einen
    frueher geseedeten Stand."""
    from docodetect.features import Features

    db = Database(cfg)
    db.init_schema()
    for nr in article_numbers:
        db.create_article(Article(article_number=nr, name=nr, category="Teller",
                                  diameter_mm=200.0, width_mm=None, depth_mm=None,
                                  height_mm=10.0, color_desc=None, notes=None))
        if with_reference:
            db.add_reference(nr, Features(
                equiv_diameter_mm=200.0, circle_diameter_mm=200.0,
                area_mm2=31415.0, perimeter_mm=628.0, circularity=0.9,
                aspect_ratio=1.0, mean_hsv=[0.0, 0.0, 200.0], solidity=0.99,
                hu_moments=[1.0] * 7))
    db.close()


# ---------- Fingerabdruck der Demo-Definitionen ----------

def test_fingerprint_is_stable_within_and_across_calls():
    assert demo_seed.demo_fingerprint() == demo_seed.demo_fingerprint()
    assert len(demo_seed.demo_fingerprint()) >= 16


def test_fingerprint_changes_when_articles_change(monkeypatch):
    """Genau der Ausloeser der Regression: ein neuer Demo-Artikel muss den
    alten Seed-Stand ungueltig machen."""
    before = demo_seed.demo_fingerprint()
    extra = DEMO_ARTICLES + [DEMO_ARTICLES[0].__class__(
        "DEMO-NEU", "Neu", "Teller 18", 195.0, 10.0, "Teller",
        (250, 250, 250), (150, 150, 150))]
    monkeypatch.setattr("docodetect.ui_qt.demo_seed.DEMO_ARTICLES", extra)
    assert demo_seed.demo_fingerprint() != before


# ---------- seed_needed: erkennt veralteten/unvollstaendigen Stand ----------

def test_seed_needed_on_empty_demo_dir(tmp_path):
    needed, reason = demo_seed.seed_needed(demo_cfg(tmp_path))
    assert needed is True and reason


def test_seed_needed_when_fingerprint_stale(tmp_path):
    """Vollstaendige Artikel + Referenzen, aber mit ALTEM Code geseedet."""
    cfg = demo_cfg(tmp_path)
    _seed_db(cfg, [a.article_number for a in DEMO_ARTICLES])
    demo_seed._write_fingerprint(cfg, "veralteter-fingerabdruck")
    needed, reason = demo_seed.seed_needed(cfg)
    assert needed is True
    assert "definition" in reason.lower() or "geändert" in reason.lower()


def test_seed_needed_when_demo_article_missing(tmp_path):
    """DER Bug-Zustand des Users: DEMO-T19 fehlt, Rest hat Referenzen,
    Fingerabdruck (hypothetisch) aktuell -> muss trotzdem neu geseedet werden."""
    cfg = demo_cfg(tmp_path)
    without_t19 = [a.article_number for a in DEMO_ARTICLES
                   if a.article_number != "DEMO-T19"]
    assert "DEMO-T19" in [a.article_number for a in DEMO_ARTICLES]
    _seed_db(cfg, without_t19)
    demo_seed._write_fingerprint(cfg, demo_seed.demo_fingerprint())
    needed, reason = demo_seed.seed_needed(cfg)
    assert needed is True
    assert "DEMO-T19" in reason


def test_seed_needed_when_article_has_no_references(tmp_path):
    cfg = demo_cfg(tmp_path)
    _seed_db(cfg, [a.article_number for a in DEMO_ARTICLES], with_reference=False)
    demo_seed._write_fingerprint(cfg, demo_seed.demo_fingerprint())
    needed, _ = demo_seed.seed_needed(cfg)
    assert needed is True


def test_no_seed_needed_when_complete_and_current(tmp_path):
    cfg = demo_cfg(tmp_path)
    _seed_db(cfg, [a.article_number for a in DEMO_ARTICLES])
    demo_seed._write_fingerprint(cfg, demo_seed.demo_fingerprint())
    needed, reason = demo_seed.seed_needed(cfg)
    assert needed is False and reason == ""


# ---------- seed_demo: idempotent (Re-Seed ueberschreibt alten Stand) ----------

def test_seed_demo_is_idempotent_and_repairs(tmp_path, monkeypatch):
    """Zweimal seeden darf nicht scheitern (create_article wirft KeyError bei
    existierendem Artikel) – der Re-Seed ist der Reparaturweg. Nur EIN
    Demo-Artikel, damit der Test bezahlbar bleibt."""
    from docodetect.pipeline import calibrate, capture_background, list_articles
    from docodetect.ui_qt.demo_scenes import build_scene

    cfg = demo_cfg(tmp_path)
    one = [a for a in DEMO_ARTICLES if a.article_number == "DEMO-T18"]
    monkeypatch.setattr("docodetect.ui_qt.demo_seed.DEMO_ARTICLES", one)

    capture_background(build_scene(cfg, "Hintergrund"), cfg)
    calibrate(build_scene(cfg, "Marker"), cfg)

    demo_seed.seed_demo(cfg)
    assert demo_seed.seed_needed(cfg)[0] is False
    n_refs = {a.article_number: a.n_references for a in list_articles(cfg)}

    demo_seed.seed_demo(cfg)          # darf NICHT mit KeyError abbrechen
    again = {a.article_number: a.n_references for a in list_articles(cfg)}
    assert again == n_refs, "Re-Seed muss den alten Stand ersetzen, nicht anhaengen"
    assert demo_seed.seed_needed(cfg)[0] is False
