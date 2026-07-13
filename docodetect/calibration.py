"""Calibration: px->mm scale at the box floor plane + background reference.

Procedure:
1. `capture-background`: photograph the EMPTY box. This image is the
   reference for background subtraction. Redo whenever lighting or the
   floor mat changes.
2. `calibrate`: place a printed ArUco marker (DICT_4X4_50, id 0, exactly
   50.0 mm edge length, flat on the floor) and run calibration. We measure
   the marker's edge length in pixels and derive mm_per_px for the FLOOR
   plane. Objects elevated above the floor appear larger; the matcher
   compensates per candidate using its height from the database
   (see features.height_corrected_scale).

The result is stored as JSON so every module reads the same numbers.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np

from .config import resolve


@dataclass
class Calibration:
    mm_per_px: float
    camera_height_mm: float
    image_width: int
    image_height: int
    marker_size_mm: float
    created_unix: float

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(asdict(self), fh, indent=2)

    @staticmethod
    def load(path: str | Path) -> "Calibration":
        with open(path, "r", encoding="utf-8") as fh:
            return Calibration(**json.load(fh))


def _get_aruco_detector(dict_name: str):
    aruco_dict = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, dict_name))
    params = cv2.aruco.DetectorParameters()
    # Sub-pixel corner refinement -> better scale accuracy.
    params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    return cv2.aruco.ArucoDetector(aruco_dict, params)


def calibrate_from_image(image: np.ndarray, cfg: dict) -> Calibration:
    """Detect the ArUco marker and compute mm_per_px at the floor plane."""
    cal_cfg = cfg["calibration"]
    detector = _get_aruco_detector(cal_cfg["aruco_dict"])

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    corners, ids, _ = detector.detectMarkers(gray)

    if ids is None or cal_cfg["marker_id"] not in ids.flatten():
        raise RuntimeError(
            f"ArUco marker id {cal_cfg['marker_id']} not found. "
            "Check print quality, lighting and that the marker lies flat."
        )

    idx = list(ids.flatten()).index(cal_cfg["marker_id"])
    pts = corners[idx].reshape(4, 2)  # 4 corners, order: TL, TR, BR, BL

    # Mean of the 4 edge lengths in px.
    edges_px = [np.linalg.norm(pts[i] - pts[(i + 1) % 4]) for i in range(4)]
    edge_px = float(np.mean(edges_px))
    spread = (max(edges_px) - min(edges_px)) / edge_px
    if spread > 0.05:
        print(f"[calibration] WARNING: marker edge lengths differ by {spread:.1%} "
              "– marker not flat or strong perspective distortion.")

    mm_per_px = cal_cfg["marker_size_mm"] / edge_px

    cal = Calibration(
        mm_per_px=mm_per_px,
        camera_height_mm=float(cfg["geometry"]["camera_height_mm"]),
        image_width=image.shape[1],
        image_height=image.shape[0],
        marker_size_mm=float(cal_cfg["marker_size_mm"]),
        created_unix=time.time(),
    )
    return cal


def run_calibration(image: np.ndarray, cfg: dict) -> Calibration:
    cal = calibrate_from_image(image, cfg)
    out = resolve(cfg["calibration"]["file"])
    cal.save(out)
    print(f"[calibration] mm_per_px = {cal.mm_per_px:.5f}  -> saved to {out}")
    fov_w = cal.mm_per_px * cal.image_width
    fov_h = cal.mm_per_px * cal.image_height
    print(f"[calibration] visible floor area: {fov_w:.0f} x {fov_h:.0f} mm")
    if min(fov_w, fov_h) < 220:
        print("[calibration] NOTE: plates larger than ~"
              f"{min(fov_w, fov_h) - 20:.0f} mm will touch the frame border "
              "and be rejected. See README (FOV limitation).")
    return cal


def save_background(image: np.ndarray, cfg: dict) -> Path:
    out = resolve(cfg["calibration"]["background_file"])
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), image)
    print(f"[calibration] background reference saved to {out}")
    return out


def load_background(cfg: dict) -> np.ndarray:
    path = resolve(cfg["calibration"]["background_file"])
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(
            f"Background reference missing ({path}). Run 'capture-background' first."
        )
    return img


def load_calibration(cfg: dict) -> Calibration:
    path = resolve(cfg["calibration"]["file"])
    if not path.exists():
        raise FileNotFoundError(
            f"Calibration missing ({path}). Run 'calibrate' first."
        )
    return Calibration.load(path)
