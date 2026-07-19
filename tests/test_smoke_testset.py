"""Tests für docodetect/smoke_testset.py: das materialisierte Smoke-Set.

Der Generator muss deterministisch sein (zwei Läufe -> byteidentische
Bilder/Hintergrund, identische Referenz-Features), das dokumentierte Layout
liefern (7 Artikel x 2 Bilder = 14) und bestehende Einrichtung sichern
statt überschreiben.
"""

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.smoke_testset import ARTICLES, N_IMAGES, generate  # noqa: E402


def make_cfg(tmp_path, sub="run"):
    d = tmp_path / sub
    return {
        "camera": {"width": 1920, "height": 1080},
        "calibration": {
            "file": str(d / "calibration" / "calibration.json"),
            "background_file": str(d / "calibration" / "background.png"),
            "aruco_dict": "DICT_4X4_50", "marker_id": 0,
            "marker_size_mm": 136.0,
        },
        "geometry": {"camera_height_mm": 300.0},
        "features": {},
        "paths": {"db_file": str(d / "doco_detect.sqlite3"),
                  "reference_dir": str(d / "reference")},
    }


def _hashes(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*.png"))}


def test_layout_and_counts(tmp_path):
    cfg = make_cfg(tmp_path)
    out = tmp_path / "run" / "testset-smoke"
    summary = generate(cfg, out)
    dirs = sorted(p.name for p in out.iterdir() if p.is_dir())
    assert dirs == sorted(a.article_number for a in ARTICLES)
    pngs = list(out.rglob("*.png"))
    assert len(pngs) == N_IMAGES == 14
    for a in ARTICLES:
        assert len(list((out / a.article_number).glob("*.png"))) == 2
    # Randfall liegt bei TELLER-200
    assert any("rand" in p.name for p in (out / "TELLER-200").glob("*.png"))
    assert summary["n_images"] == 14
    assert summary["n_articles"] == len(ARTICLES) == 7


def test_calibration_background_db_created(tmp_path):
    from docodetect.pipeline import get_status, list_articles

    cfg = make_cfg(tmp_path)
    generate(cfg, tmp_path / "run" / "testset-smoke")
    st = get_status(cfg)
    assert st.calibrated and st.background_present
    assert st.mm_per_px == pytest.approx(0.2, rel=0.02)
    arts = {a.article_number: a for a in list_articles(cfg)}
    assert set(arts) == {a.article_number for a in ARTICLES}
    assert all(a.n_references == 3 for a in arts.values())  # je 3 Einlern-Shots
    # Die Höhen-Falle steht mit DB-Höhe 25 in den Stammdaten
    assert arts["TELLER-180-HOCH"].height_mm == 25.0
    assert arts["SCHUESSEL-140"].height_mm == 60.0


def test_deterministic_across_runs(tmp_path):
    """Fester Seed: zweiter Lauf erzeugt byteidentische PNGs (Testset UND
    Hintergrund) und identische Referenz-Features (DB-Timestamps ausgenommen)."""
    import sqlite3

    cfg1, cfg2 = make_cfg(tmp_path, "a"), make_cfg(tmp_path, "b")
    out1, out2 = tmp_path / "a" / "ts", tmp_path / "b" / "ts"
    generate(cfg1, out1)
    generate(cfg2, out2)
    assert _hashes(out1) == _hashes(out2)
    bg1 = Path(cfg1["calibration"]["background_file"]).read_bytes()
    bg2 = Path(cfg2["calibration"]["background_file"]).read_bytes()
    assert bg1 == bg2

    def features(db_path):
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT article_number, features_json FROM reference_features "
            "ORDER BY article_number, id").fetchall()
        conn.close()
        return rows
    assert features(cfg1["paths"]["db_file"]) == features(cfg2["paths"]["db_file"])


def test_existing_setup_backed_up_not_overwritten(tmp_path):
    cfg = make_cfg(tmp_path)
    for key in ("file", "background_file"):
        p = Path(cfg["calibration"][key])
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("ALT", encoding="utf-8")
    db = Path(cfg["paths"]["db_file"])
    db.write_text("ALTE-DB", encoding="utf-8")

    generate(cfg, tmp_path / "run" / "ts")
    # Backups mit .bak vor der Endung, Ignore-Muster bleiben gültig
    cal_dir = Path(cfg["calibration"]["file"]).parent
    assert list(cal_dir.glob("calibration.bak-*.json"))
    assert list(cal_dir.glob("background.bak-*.png"))
    assert list(db.parent.glob("doco_detect.bak-*.sqlite3"))
    # und die neuen Dateien sind echte neue Inhalte
    assert Path(cfg["calibration"]["file"]).read_text(encoding="utf-8") != "ALT"


def test_testset_images_identify_as_designed(tmp_path):
    """Stichprobe der Design-Erwartungen: ein TELLER-160-Bild wird accept/
    korrekt, das Randbild wird reject, ein 180-HOCH-Bild läuft in die
    beabsichtigte Verwechslung mit TELLER-180 (Höhenkompensations-Falle)."""
    from docodetect.camera import load_image
    from docodetect.config import load_config
    from docodetect.pipeline import Pipeline

    cfg = make_cfg(tmp_path)
    cfg["matching"] = load_config()["matching"]  # echte Toleranzen, unverändert
    out = tmp_path / "run" / "ts"
    generate(cfg, out)
    pipe = Pipeline(cfg)
    try:
        img = sorted((out / "TELLER-160").glob("*.png"))[0]
        rep = pipe.identify(load_image(img)).report
        assert rep.decision == "accept"
        assert rep.candidates[0].article_number == "TELLER-160"

        rand = next(p for p in (out / "TELLER-200").glob("*.png") if "rand" in p.name)
        assert pipe.identify(load_image(rand)).report.decision == "reject"

        trap = sorted((out / "TELLER-180-HOCH").glob("*.png"))[0]
        rep = pipe.identify(load_image(trap)).report
        cands = [c.article_number for c in rep.candidates]
        assert "TELLER-180-HOCH" not in cands   # Vorfilter wirft den Wahren raus
        assert cands and cands[0] == "TELLER-180"
    finally:
        pipe.close()
