"""Demo-Szenen (synthetisches Testkit für --demo) – kein Qt, keine Kamera.

Das Kit muss die komplette Abnahme ohne Hardware tragen:
Hintergrund -> Kalibrieren (Marker) -> Identifizieren (Teller/Schüssel)
-> Rand-Warnung (Randbild). Hier wird geprüft, dass die synthetischen
Szenen durch die ECHTE Segmentierung/Kalibrierung laufen und die
gezeichneten Größen physikalisch konsistent sind (apparente Größe =
nominal * Z/(Z-h), Höhenkompensation rechnet zurück).
"""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.calibration import Calibration, calibrate_from_image  # noqa: E402
from docodetect.features import extract, height_corrected_scale  # noqa: E402
from docodetect.segmentation import segment  # noqa: E402
from docodetect.ui_qt.demo_scenes import (DEMO_ARTICLES, DEMO_MM_PER_PX,  # noqa: E402
                                          SCENE_NAMES, _MIN_SHIFT_PX,
                                          build_scene)

CFG = {
    "camera": {"width": 1920, "height": 1080},
    "calibration": {"aruco_dict": "DICT_4X4_50", "marker_id": 0,
                    "marker_size_mm": 136.0},
    "geometry": {"camera_height_mm": 300.0},
}

CAL = Calibration(mm_per_px=DEMO_MM_PER_PX, camera_height_mm=300.0,
                  image_width=1920, image_height=1080,
                  marker_size_mm=136.0, created_unix=0.0)


def scene(name, variant=0):
    return build_scene(CFG, name, variant)


def test_all_scenes_exist_and_are_1080p_bgr():
    for name in SCENE_NAMES:
        img = scene(name)
        assert img.shape == (1080, 1920, 3), name
        assert img.dtype == np.uint8, name


def test_marker_scene_calibrates_to_demo_scale():
    cal = calibrate_from_image(scene("Marker"), CFG)
    assert cal.mm_per_px == pytest.approx(DEMO_MM_PER_PX, rel=0.02)


@pytest.mark.parametrize("art", DEMO_ARTICLES)
def test_articles_measure_back_to_nominal(art):
    """Szene ist mit apparenter Größe gezeichnet; die Höhenkompensation muss
    exakt auf den Nominal-Ø der Demo-Stammdaten zurückrechnen."""
    bg = scene("Hintergrund")
    img = scene(art.scene_name)
    seg = segment(img, bg)
    assert not seg.touches_border, art.scene_name
    feats = extract(img, seg, CAL)
    corrected = height_corrected_scale(feats.circle_diameter_mm,
                                       art.height_mm, 300.0)
    assert corrected == pytest.approx(art.diameter_mm, abs=3.0), art.scene_name


def test_border_scene_touches_border():
    seg = segment(scene("Randbild"), scene("Hintergrund"))
    assert seg.touches_border


def test_variants_jitter_but_measure_same():
    """Varianten (fürs Einlernen) verschieben das Objekt, ändern aber die
    gemessene Größe praktisch nicht – Basis für enge Enrollment-Streuung.

    Geprüft wird gegen die ZUSAGE von _jitter (_MIN_SHIFT_PX), nicht gegen
    eine freie Zahl: bis 2026-08-08 stand hier `> 5.0` gegen einen
    PYTHONHASHSEED-abhängigen Zufallszug, und der Test fiel in 2,2 % der
    Läufe, wenn die Variante zufällig fast im Zentrum landete."""
    bg = scene("Hintergrund")
    d = []
    centers = []
    for v in range(3):
        img = build_scene(CFG, "Teller 18", v)
        seg = segment(img, bg)
        feats = extract(img, seg, CAL)
        d.append(feats.circle_diameter_mm)
        m = seg.contour.reshape(-1, 2).mean(axis=0)
        centers.append(m)
    assert max(d) - min(d) < 2.0
    # 2 px Messschlupf: der Kontur-Schwerpunkt ist nicht exakt der
    # gezeichnete Mittelpunkt. BEIDE Varianten müssen sich bewegt haben –
    # eine Variante, die still in der Mitte bleibt, ist derselbe Shot.
    for v in (1, 2):
        assert np.linalg.norm(centers[0] - centers[v]) > _MIN_SHIFT_PX - 2


def test_background_variants_share_floor_statistics():
    """Der Demo-Hintergrund (variant 0) dient als Referenz; Objekt-Szenen
    nutzen denselben Boden, sonst misst die Segmentierung das Rauschen."""
    bg0 = scene("Hintergrund", 0)
    bg_of_plate = scene("Teller 18", 0)
    h, w = bg0.shape[:2]
    corner = (slice(0, 100), slice(0, 100))  # Objekt liegt zentral
    diff = np.abs(bg0[corner].astype(int) - bg_of_plate[corner].astype(int))
    assert diff.mean() < 3.0
