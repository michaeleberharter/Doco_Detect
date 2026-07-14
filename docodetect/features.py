"""Feature extraction from a segmented object.

Three feature groups:

1. Geometry (converted to mm via calibration):
   - equivalent diameter, min-enclosing-circle diameter, area, perimeter
   - circularity (1.0 = perfect circle), aspect ratio of min-area rect
   NOTE: raw values are valid for the FLOOR plane. Because a plate rim sits
   e.g. 25 mm above the floor it appears larger. Correction (pinhole model):
       true = measured * (Z - h) / Z
   with Z = camera height, h = object height. Since h depends on WHICH
   article it is, the correction is applied per-candidate in matcher.py,
   not here. Here we store floor-plane values.

2. Color: mean HSV inside the mask + a 32-bin hue histogram (normalized).
   Requires constant box lighting.

3. Shape: log-scaled Hu moments (rotation/scale invariant) for silhouette
   comparison (plate vs. bowl vs. oval platter).
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field

import cv2
import numpy as np

from .calibration import Calibration
from .segmentation import SegmentationResult

HUE_BINS = 32


@dataclass
class Features:
    # geometry, floor-plane mm
    equiv_diameter_mm: float
    circle_diameter_mm: float     # min enclosing circle – robust for round items
    area_mm2: float
    perimeter_mm: float
    circularity: float            # 4*pi*A / P^2
    aspect_ratio: float           # short/long side of minAreaRect, in (0,1]
    # color
    mean_hsv: list = field(default_factory=list)       # [h, s, v]
    hue_hist: list = field(default_factory=list)       # HUE_BINS floats, sums to 1
    mean_saturation: float = 0.0
    # shape
    hu_moments: list = field(default_factory=list)     # 7 log-scaled values

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @staticmethod
    def from_json(s: str) -> "Features":
        return Features(**json.loads(s))


def height_corrected_scale(measured_mm: float, object_height_mm: float,
                           camera_height_mm: float) -> float:
    """Convert a floor-plane measurement to the true size of a feature that
    sits `object_height_mm` above the floor (e.g. a plate rim)."""
    z = camera_height_mm
    h = min(object_height_mm, 0.8 * z)  # sanity clamp
    return measured_mm * (z - h) / z


def min_area_rect_mm(contour: np.ndarray, cal: Calibration,
                     object_height_mm: float = 0.0) -> tuple[float, float]:
    """Long and short side of the minimum-area rectangle in mm, height-corrected.

    Used when creating an elongated article (spoon, knife, oval platter): its
    footprint is described by width/depth instead of a single diameter."""
    (_, _), (rw, rh), _ = cv2.minAreaRect(contour)
    z = cal.camera_height_mm
    long_mm = height_corrected_scale(max(rw, rh) * cal.mm_per_px, object_height_mm, z)
    short_mm = height_corrected_scale(min(rw, rh) * cal.mm_per_px, object_height_mm, z)
    return round(long_mm, 2), round(short_mm, 2)


def describe_color_hsv(mean_hsv: list) -> str:
    """Rough German colour name from mean HSV (OpenCV ranges: H 0-180, S/V
    0-255). Cosmetic only – fills the article's `color_desc` for the DB view;
    the matcher compares colour via the enrolled histograms, not this string."""
    if not mean_hsv or len(mean_hsv) < 3:
        return ""
    h, s, v = mean_hsv[0], mean_hsv[1], mean_hsv[2]
    if s < 40:
        return "schwarz" if v < 60 else "grau" if v < 170 else "weiß"
    for bound, name in ((10, "rot"), (25, "orange"), (35, "gelb"), (85, "grün"),
                        (100, "türkis"), (130, "blau"), (150, "violett"),
                        (170, "pink")):
        if h <= bound:
            return name
    return "rot"


def extract(image: np.ndarray, seg: SegmentationResult, cal: Calibration) -> Features:
    c = seg.contour
    s = cal.mm_per_px

    area_px = cv2.contourArea(c)
    perim_px = cv2.arcLength(c, closed=True)
    (_, _), radius_px = cv2.minEnclosingCircle(c)

    equiv_d_mm = 2.0 * math.sqrt(area_px / math.pi) * s
    circle_d_mm = 2.0 * radius_px * s
    area_mm2 = area_px * s * s
    perim_mm = perim_px * s
    circularity = 4.0 * math.pi * area_px / (perim_px ** 2) if perim_px > 0 else 0.0

    (_, _), (rw, rh), _ = cv2.minAreaRect(c)
    aspect = min(rw, rh) / max(rw, rh) if max(rw, rh) > 0 else 0.0

    # --- color inside mask ---
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mean_hsv = cv2.mean(hsv, mask=seg.mask)[:3]
    hist = cv2.calcHist([hsv], [0], seg.mask, [HUE_BINS], [0, 180]).flatten()
    hist_sum = hist.sum()
    hue_hist = (hist / hist_sum).tolist() if hist_sum > 0 else [0.0] * HUE_BINS

    # --- shape (Hu moments, log-scaled for comparable magnitudes) ---
    hu = cv2.HuMoments(cv2.moments(c)).flatten()
    hu_log = [-math.copysign(1.0, v) * math.log10(abs(v)) if v != 0 else 0.0 for v in hu]

    return Features(
        equiv_diameter_mm=round(equiv_d_mm, 2),
        circle_diameter_mm=round(circle_d_mm, 2),
        area_mm2=round(area_mm2, 1),
        perimeter_mm=round(perim_mm, 2),
        circularity=round(circularity, 4),
        aspect_ratio=round(aspect, 4),
        mean_hsv=[round(v, 2) for v in mean_hsv],
        hue_hist=[round(v, 6) for v in hue_hist],
        mean_saturation=round(mean_hsv[1], 2),
        hu_moments=[round(v, 4) for v in hu_log],
    )


# ---------- distance helpers used by the matcher ----------

def color_distance(a: Features, b: Features) -> float:
    """0 (identical) .. 1 (very different). Bhattacharyya on hue histogram,
    blended with value/saturation difference so white vs. gray still differs."""
    ha = np.asarray(a.hue_hist, dtype=np.float32)
    hb = np.asarray(b.hue_hist, dtype=np.float32)
    bhatta = cv2.compareHist(ha, hb, cv2.HISTCMP_BHATTACHARYYA)  # 0..1

    dv = abs(a.mean_hsv[2] - b.mean_hsv[2]) / 255.0
    ds = abs(a.mean_hsv[1] - b.mean_hsv[1]) / 255.0
    return float(np.clip(0.6 * bhatta + 0.2 * dv + 0.2 * ds, 0.0, 1.0))


def shape_distance(a: Features, b: Features) -> float:
    """0 (identical) .. ~1. L1 on log-Hu moments (scaled) + circularity diff."""
    ha = np.asarray(a.hu_moments)
    hb = np.asarray(b.hu_moments)
    hu_d = float(np.abs(ha - hb).mean()) / 5.0  # empirical scale
    circ_d = abs(a.circularity - b.circularity)
    return float(np.clip(0.7 * hu_d + 0.3 * circ_d, 0.0, 1.0))
