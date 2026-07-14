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

2. Color: mean HSV inside the mask + a 32-bin hue histogram (normalized) –
   kept for backward compatibility with old reference JSONs. NEW: ring-zone
   color features via the distance transform of the mask (normalized radius
   r = 1 - dist/dist_max): mean CIE-Lab + H-S histogram separately for the
   CENTER (r < ring_zones.center_max) and the RIM (r > ring_zones.rim_min);
   the transition band between them is deliberately ignored (a decor edge
   never sits exactly on the boundary). Requires constant box lighting.

3. Shape: log-scaled Hu moments (rotation/scale invariant) for silhouette
   comparison (plate vs. bowl vs. oval platter), circularity and solidity
   (contour area / convex hull area).
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
    # color (global – backward compatible with pre-ring-zone references)
    mean_hsv: list = field(default_factory=list)       # [h, s, v]
    hue_hist: list = field(default_factory=list)       # HUE_BINS floats, sums to 1
    mean_saturation: float = 0.0
    # shape
    hu_moments: list = field(default_factory=list)     # 7 log-scaled values
    solidity: float = 0.0                              # area / hull area; 0 = missing (old JSON)
    # ring-zone color (empty lists = enrolled before zones existed)
    lab_center: list = field(default_factory=list)     # [L, a, b], CIE (L 0..100)
    lab_rim: list = field(default_factory=list)
    hs_hist_center: list = field(default_factory=list) # H*S bins flat, sums to 1
    hs_hist_rim: list = field(default_factory=list)

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


def _zone_masks(mask: np.ndarray, center_max: float, rim_min: float):
    """Ring zones via normalized radius from the distance transform:
    r = 1 - dist/dist_max (r=0 innermost pixel, r=1 at the contour). Works
    for round AND elongated objects because r follows the object's shape,
    not a fitted circle. Returns (center_mask, rim_mask) or (None, None)."""
    dist = cv2.distanceTransform((mask > 0).astype(np.uint8), cv2.DIST_L2, 5)
    dmax = float(dist.max())
    if dmax <= 0:
        return None, None
    r = 1.0 - dist / dmax
    inside = mask > 0
    center = np.where(inside & (r < center_max), np.uint8(255), np.uint8(0))
    rim = np.where(inside & (r > rim_min), np.uint8(255), np.uint8(0))
    return center, rim


def _zone_color(lab: np.ndarray, hsv: np.ndarray, zone: np.ndarray | None,
                bins: tuple[int, int]) -> tuple[list, list]:
    """Mean CIE-Lab + normalized H-S histogram inside one zone mask."""
    if zone is None or not zone.any():
        return [], []
    mean_lab = lab[zone > 0].mean(axis=0)
    hist = cv2.calcHist([hsv], [0, 1], zone, list(bins), [0, 180, 0, 256]).flatten()
    total = hist.sum()
    hist = (hist / total) if total > 0 else hist
    return [round(float(v), 3) for v in mean_lab], [round(float(v), 6) for v in hist]


def extract(image: np.ndarray, seg: SegmentationResult, cal: Calibration,
            cfg: dict | None = None) -> Features:
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

    hull_area = cv2.contourArea(cv2.convexHull(c))
    solidity = area_px / hull_area if hull_area > 0 else 0.0

    # --- color inside mask ---
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mean_hsv = cv2.mean(hsv, mask=seg.mask)[:3]
    hist = cv2.calcHist([hsv], [0], seg.mask, [HUE_BINS], [0, 180]).flatten()
    hist_sum = hist.sum()
    hue_hist = (hist / hist_sum).tolist() if hist_sum > 0 else [0.0] * HUE_BINS

    # --- ring-zone color (center vs. rim, transition band ignored) ---
    fcfg = (cfg or {}).get("features", {})
    zones = fcfg.get("ring_zones", {})
    center_max = float(zones.get("center_max", 0.60))
    rim_min = float(zones.get("rim_min", 0.75))
    bins = tuple(fcfg.get("hs_hist_bins", [16, 8]))
    zc, zr = _zone_masks(seg.mask, center_max, rim_min)
    # float Lab: L in 0..100, a/b centered at 0 -> CIE76 distances are correct
    lab = cv2.cvtColor(image.astype(np.float32) / 255.0, cv2.COLOR_BGR2Lab)
    lab_center, hist_center = _zone_color(lab, hsv, zc, bins)
    lab_rim, hist_rim = _zone_color(lab, hsv, zr, bins)

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
        solidity=round(solidity, 4),
        lab_center=lab_center,
        lab_rim=lab_rim,
        hs_hist_center=hist_center,
        hs_hist_rim=hist_rim,
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


def delta_e_cie76(a: list, b: list) -> float:
    """CIE76: euklidischer Abstand im Lab-Raum – für Geschirr-Unifarben genug."""
    return float(np.linalg.norm(np.asarray(a, dtype=np.float64)
                                - np.asarray(b, dtype=np.float64)))


def bhattacharyya_distance(a: list, b: list) -> float:
    return float(cv2.compareHist(np.asarray(a, dtype=np.float32),
                                 np.asarray(b, dtype=np.float32),
                                 cv2.HISTCMP_BHATTACHARYYA))


# ---------- enrollment statistics (basis for the statistical matcher) ----------

SCALAR_FEATURES = ("diameter_mm", "circularity", "solidity")
PROTO_FEATURES = ("delta_e_center", "delta_e_rim", "hist_center", "hist_rim", "hu_log")
ALL_FEATURES = SCALAR_FEATURES + PROTO_FEATURES


def scalar_value(feats: Features, name: str) -> float | None:
    """Scalar feature accessor. None = not present (old reference JSONs
    predate solidity; 0 is the dataclass default and physically impossible)."""
    if name == "diameter_mm":
        return float(feats.circle_diameter_mm)
    if name == "circularity":
        return float(feats.circularity)
    if name == "solidity":
        s = float(getattr(feats, "solidity", 0.0))
        return s if s > 0.0 else None
    raise KeyError(name)


def hu_log_distance(a: list, b: list) -> float:
    return float(np.abs(np.asarray(a, dtype=np.float64)
                        - np.asarray(b, dtype=np.float64)).mean())


@dataclass
class EnrollmentStats:
    """Per-article statistics over all enrolled shots. Scalars get mean+std;
    vector features get a prototype (mean vector) + the RMS of the per-shot
    distances to that prototype as spread. Keys absent = feature not
    available for this article (e.g. references enrolled before ring zones
    existed)."""
    n_shots: int
    scalar_mean: dict = field(default_factory=dict)
    scalar_std: dict = field(default_factory=dict)
    proto: dict = field(default_factory=dict)
    proto_std: dict = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @staticmethod
    def from_json(s: str) -> "EnrollmentStats":
        return EnrollmentStats(**json.loads(s))


def _proto_stats(vectors: list, dist_fn) -> tuple[list, float]:
    arr = np.asarray(vectors, dtype=np.float64)
    proto = arr.mean(axis=0)
    if len(vectors) < 2:
        return proto.tolist(), 0.0
    d = [dist_fn(v, proto.tolist()) for v in vectors]
    return proto.tolist(), float(np.sqrt(np.mean(np.square(d))))


# Feature-Key -> (Features-Attribut der Messung, Distanzfunktion)
_PROTO_SRC = {
    "delta_e_center": ("lab_center", delta_e_cie76),
    "delta_e_rim": ("lab_rim", delta_e_cie76),
    "hist_center": ("hs_hist_center", bhattacharyya_distance),
    "hist_rim": ("hs_hist_rim", bhattacharyya_distance),
    "hu_log": ("hu_moments", hu_log_distance),
}


def compute_enrollment_stats(feats_list: list[Features]) -> EnrollmentStats:
    st = EnrollmentStats(n_shots=len(feats_list))
    for name in SCALAR_FEATURES:
        vals = [v for f in feats_list if (v := scalar_value(f, name)) is not None]
        if not vals:
            continue
        st.scalar_mean[name] = float(np.mean(vals))
        st.scalar_std[name] = float(np.std(vals, ddof=1)) if len(vals) > 1 else 0.0
    for key, (attr, dist_fn) in _PROTO_SRC.items():
        vecs = [v for f in feats_list if (v := getattr(f, attr, None))]
        if not vecs or len({len(v) for v in vecs}) != 1:
            continue                       # fehlt/inkonsistent (alte Referenzen)
        st.proto[key], st.proto_std[key] = _proto_stats(vecs, dist_fn)
    # Histogramm-Prototypen renormieren (das Mittel normierter Histogramme ist
    # es fast, aber numerisch sauber):
    for key in ("hist_center", "hist_rim"):
        if key in st.proto:
            s = sum(st.proto[key])
            if s > 0:
                st.proto[key] = [v / s for v in st.proto[key]]
    return st


def proto_distance(feature: str, feats: Features, stats: EnrollmentStats) -> float | None:
    """Distanz Messung -> Enrollment-Prototyp. None, wenn eine Seite das
    Merkmal nicht hat (Referenzen von vor den Ring-Zonen, Bin-Änderung in der
    Config) – das Merkmal fällt dann für diesen Kandidaten aus dem Scoring."""
    attr, dist_fn = _PROTO_SRC[feature]
    proto = stats.proto.get(feature)
    measured = getattr(feats, attr, None)
    if not proto or not measured or len(proto) != len(measured):
        return None
    return dist_fn(measured, proto)
