"""Synthetic end-to-end tests: no camera or real photos needed.

We render a fake box floor + a fake plate as image, run segmentation and
feature extraction, and check that the measured diameter matches the drawn
one. This validates the whole measurement chain except the physical camera.

Run: pytest tests/ -v   (or: python -m pytest)
"""

import math
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.calibration import Calibration  # noqa: E402
from docodetect.features import extract, height_corrected_scale  # noqa: E402
from docodetect.segmentation import segment  # noqa: E402

CFG = {
    "segmentation": {
        "blur_kernel": 7, "diff_threshold": 25, "morph_kernel": 15,
        "min_area_px": 5000, "border_margin_px": 5,
    },
}

MM_PER_PX = 0.2  # synthetic scale
CAL = Calibration(mm_per_px=MM_PER_PX, camera_height_mm=300.0,
                  image_width=1920, image_height=1080,
                  marker_size_mm=50.0, created_unix=0.0)


def make_background(w=1920, h=1080):
    bg = np.full((h, w, 3), 200, dtype=np.uint8)
    noise = np.random.default_rng(42).integers(-5, 5, bg.shape, dtype=np.int16)
    return np.clip(bg.astype(np.int16) + noise, 0, 255).astype(np.uint8)


def draw_plate(bg, diameter_mm, center=(960, 540), color=(250, 250, 250)):
    img = bg.copy()
    r_px = int(round(diameter_mm / MM_PER_PX / 2))
    cv2.circle(img, center, r_px, color, thickness=-1)
    cv2.circle(img, center, r_px, (150, 150, 150), thickness=3)  # rim shading
    return img


def test_diameter_measurement_accuracy():
    bg = make_background()
    for d_mm in (160.0, 210.0):
        img = draw_plate(bg, d_mm)
        seg = segment(img, bg, CFG)
        assert not seg.touches_border
        feats = extract(img, seg, CAL)
        assert abs(feats.circle_diameter_mm - d_mm) < 3.0, (
            f"measured {feats.circle_diameter_mm} vs drawn {d_mm}"
        )
        # Pixelated contours overestimate the perimeter, so circularity of a
        # perfect circle lands around ~0.9 rather than 1.0. What matters is
        # that round items score clearly above elongated ones (~0.6-0.7).
        assert feats.circularity > 0.85


def test_border_detection():
    bg = make_background()
    # plate partially outside the frame
    img = draw_plate(bg, 210.0, center=(30, 540))
    seg = segment(img, bg, CFG)
    assert seg.touches_border


def test_height_compensation():
    # 270 mm plate, rim 25 mm above floor, camera at 300 mm:
    # it appears larger by factor 300/275
    apparent = 270.0 * 300.0 / 275.0
    corrected = height_corrected_scale(apparent, 25.0, 300.0)
    assert math.isclose(corrected, 270.0, abs_tol=0.01)


def test_two_plates_distinguishable_by_size():
    """The core use case: 250 vs 270 mm white plates must yield clearly
    different measurements (>> typical tolerance)."""
    bg = make_background()
    d1 = extract(draw_plate(bg, 250.0), segment(draw_plate(bg, 250.0), bg, CFG), CAL)
    d2 = extract(draw_plate(bg, 270.0), segment(draw_plate(bg, 270.0), bg, CFG), CAL)
    assert d2.circle_diameter_mm - d1.circle_diameter_mm > 15.0
