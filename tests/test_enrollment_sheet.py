"""Tests fuers Enrollment-Diagnoseblatt (docodetect.enrollment_sheet).

Zwei Wege werden geprueft:
  - der volle Weg mit echten (synthetischen) Bildern: einlernen ueber
    save_enrollment, dann build_enrollment_sheet -> PNG. Deckt Segmentierung,
    Geometrie (Felder 1-3) und Rendering ab.
  - der bildlose Weg (Altbestand, image_path=None): compute_sheet_metrics und
    render_sheet muessen ohne Kontur durchlaufen, Felder 4/5 aus features_json.

Keine Kamera, kein Qt. Nur Temp-Verzeichnisse.
"""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.features import Features  # noqa: E402


def _marker_cfg(tmp_path):
    return {
        "calibration": {
            "file": str(tmp_path / "calibration.json"),
            "background_file": str(tmp_path / "background.png"),
            "aruco_dict": "DICT_4X4_50", "marker_id": 0, "marker_size_mm": 136.0,
        },
        "camera": {"width": 1920, "height": 1080},
        "geometry": {"camera_height_mm": 300.0},
        "paths": {"db_file": str(tmp_path / "db.sqlite3"),
                  "reference_dir": str(tmp_path / "reference")},
        "stage2": {"enabled": False},
    }


def _synthetic_feats(n=6, outlier=2):
    """n leicht variierende Referenz-Features, Shot `outlier` deutlich daneben
    (groesserer Durchmesser + verschobene Farbe) -> muss in der Auffaelligkeit
    auftauchen."""
    out = []
    rng = np.random.default_rng(42)
    for i in range(n):
        bump = 6.0 if i == outlier else 0.0
        jit = float(rng.normal(0, 0.2))
        out.append(Features(
            equiv_diameter_mm=180.0 + bump + jit,
            circle_diameter_mm=182.0 + bump + jit,
            area_mm2=25000.0 + 400.0 * (bump / 6.0) + jit,
            perimeter_mm=560.0 + jit,
            circularity=0.95 - 0.03 * (i == outlier) + 0.001 * jit,
            aspect_ratio=1.0 - 0.02 * (i == outlier),
            mean_hsv=[10.0, 20.0, 200.0],
            hu_moments=[1.0 + 0.01 * i] * 7,
            solidity=0.99 - 0.005 * (i == outlier),
            lab_center=[80.0 + (5.0 if i == outlier else jit), 0.0, 0.0],
            lab_rim=[78.0 + jit, 1.0, 1.0],
            hs_hist_center=[0.25, 0.25, 0.25, 0.25],
            hs_hist_rim=[0.4, 0.3, 0.2, 0.1]))
    return out


# ---------- voller Weg: echte Bilder ----------

def test_build_enrollment_sheet_from_enrolled_images(tmp_path):
    from docodetect.pipeline import (calibrate, capture_background,
                                     measure_shot, save_enrollment)
    from docodetect.database import Article, Database
    from docodetect.enrollment_sheet import build_enrollment_sheet
    from docodetect.ui_qt.demo_scenes import build_scene

    cfg = _marker_cfg(tmp_path)
    capture_background(build_scene(cfg, "Hintergrund"), cfg)
    calibrate(build_scene(cfg, "Marker"), cfg)

    db = Database(cfg)
    db.init_schema()
    db.create_article(Article(
        article_number="T-180", name="Teller flach 18", category="Teller",
        diameter_mm=182.0, width_mm=None, depth_mm=None, height_mm=20.0,
        color_desc=None, notes=None))
    db.close()

    shots = []
    for v in range(1, 7):
        img = build_scene(cfg, "Teller 18", v)
        feats, _ = measure_shot(img, cfg)
        shots.append((img, feats))
    assert save_enrollment(cfg, "T-180", shots) == 6

    # image_path in Aufnahmereihenfolge gesetzt (Vorbedingung Felder 1-3)
    meta = Database(cfg).references_with_meta("T-180")
    assert len(meta) == 6
    assert all(ip and ip.endswith(".png") for ip, _ in meta)
    assert [ip for ip, _ in meta] == sorted(ip for ip, _ in meta)  # geordnet

    out = build_enrollment_sheet(cfg, article_number="T-180",
                                 out=tmp_path / "sheet.png")
    assert out.exists() and out.stat().st_size > 5000


# ---------- bildloser Weg: Altbestand (image_path=None) ----------

def test_metrics_without_images_runs_on_features(tmp_path):
    from docodetect.enrollment_sheet import compute_sheet_metrics

    feats = _synthetic_feats(n=6, outlier=2)
    geoms = [None] * 6                      # kein Bild
    m = compute_sheet_metrics(feats, geoms, stored_stats=None)

    assert m.n_shots == 6
    assert m.n_with_image == 0
    assert m.highlight_shot is None          # ohne Kontur kein Feld-1-Ausreisser
    keys = {r.key for r in m.rows}
    # Skalare aus den Features und Vektor-Merkmale sind da, ext_full/lat_p98 NICHT
    assert {"diameter_mm", "circularity", "aspect_ratio", "area"} <= keys
    assert {"delta_e_center", "hu_log"} <= keys
    assert "ext_full" not in keys and "lat_p98" not in keys
    # der ausgelenkte Shot 3 (1-basiert) faellt bei mehreren Merkmalen auf
    assert int(np.argmax(m.conspicuity)) == 2
    assert m.conspicuity[2] >= 2


def test_scalar_row_has_classic_and_robust_z(tmp_path):
    from docodetect.enrollment_sheet import compute_sheet_metrics

    feats = _synthetic_feats(n=6, outlier=2)
    m = compute_sheet_metrics(feats, [None] * 6, stored_stats=None)
    row = next(r for r in m.rows if r.key == "diameter_mm")
    assert row.extreme_shot == 3            # der Ausreisser
    assert np.isfinite(row.z_classic_extreme)
    assert np.isfinite(row.z_robust_extreme)
    assert abs(row.z_robust_extreme) > 2.0  # klar auffaellig


def test_render_with_too_few_shots_no_crash(tmp_path):
    """N<3: keine Leave-one-out-Statistik – Blatt rendert trotzdem (Hinweis
    statt leerer Tabelle, die matplotlib sonst mit IndexError quittiert)."""
    from docodetect.enrollment_sheet import compute_sheet_metrics, render_sheet

    m = compute_sheet_metrics(_synthetic_feats(n=2), [None, None], None)
    assert m.rows == []
    out = render_sheet(m, [None, None], tmp_path / "n2.png", "N=2")
    assert out.exists() and out.stat().st_size > 2000


def test_render_sheet_without_images(tmp_path):
    """Rendering muss ohne jede Kontur durchlaufen (Felder 1-3 leer)."""
    from docodetect.enrollment_sheet import compute_sheet_metrics, render_sheet

    feats = _synthetic_feats(n=5, outlier=1)
    geoms = [None] * 5
    m = compute_sheet_metrics(feats, geoms, stored_stats=None)
    out = render_sheet(m, geoms, tmp_path / "altbestand.png",
                       title="Test", subnote="")
    assert out.exists() and out.stat().st_size > 3000


def test_mixed_missing_images_counts_reported(tmp_path):
    from docodetect.enrollment_sheet import compute_sheet_metrics

    feats = _synthetic_feats(n=6, outlier=2)
    geoms = [None] * 6
    m = compute_sheet_metrics(feats, geoms, stored_stats=None)
    assert m.n_shots - m.n_with_image == 6   # alle fehlen -> im Blattkopf sichtbar


# ---------- STUFE 4: Verwerfen sichert statt zu loeschen ----------

def test_discard_enrollment_saves_frames_not_db(tmp_path):
    """Verworfenes Enrollment landet im Verworfen-Ordner (Frames + info.json),
    OHNE DB- oder reference_dir-Eintrag – der Pfad-/DB-Vertrag bleibt unberuehrt."""
    from docodetect.pipeline import discard_enrollment

    cfg = {"paths": {"reference_dir": str(tmp_path / "reference")}}
    feats = _synthetic_feats(n=3)
    frames = [np.full((60, 80, 3), 30 * i + 20, np.uint8) for i in range(3)]
    shots = list(zip(frames, feats))

    dest = discard_enrollment(cfg, "GABEL-9", shots, sheet_png=None)

    assert dest.exists()
    assert "verworfen" in str(dest)
    assert len(sorted(dest.glob("*.png"))) == 3          # gesichert, nicht geloescht
    assert (dest / "info.json").exists()
    # reference_dir des Artikels bleibt unberuehrt (kein Speichern in die DB-Welt)
    assert not (tmp_path / "reference" / "GABEL-9").exists()


# ---------- (11) contour-band ----------

def test_build_contour_band(tmp_path):
    """Eigenständiges Konturband-Blatt: mehrere eingelernte Shots -> PNG."""
    from docodetect.database import Article, Database
    from docodetect.enrollment_sheet import build_contour_band
    from docodetect.pipeline import (calibrate, capture_background, measure_shot,
                                     save_enrollment)
    from docodetect.ui_qt.demo_scenes import build_scene

    cfg = _marker_cfg(tmp_path)
    capture_background(build_scene(cfg, "Hintergrund"), cfg)
    calibrate(build_scene(cfg, "Marker"), cfg)
    db = Database(cfg)
    db.init_schema()
    db.create_article(Article(
        article_number="T-180", name="Teller flach 18", category="Teller",
        diameter_mm=182.0, width_mm=None, depth_mm=None, height_mm=20.0,
        color_desc=None, notes=None))
    db.close()
    shots = []
    for v in range(1, 5):
        img = build_scene(cfg, "Teller 18", v)
        feats, _ = measure_shot(img, cfg)
        shots.append((img, feats))
    save_enrollment(cfg, "T-180", shots)

    out = build_contour_band(cfg, "T-180", out=tmp_path / "cb.png")
    assert out.exists() and out.stat().st_size > 3000
