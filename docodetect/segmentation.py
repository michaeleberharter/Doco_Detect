"""Foreground segmentation via background subtraction.

Inside the photo box we have a fixed camera, fixed background and constant
lighting -> a simple absolute difference against the empty-box reference is
robust and fast. No neural segmentation needed.

Pitfalls handled here:
- White porcelain on light background: we diff in BOTH grayscale and
  saturation channels and take the max, which catches low-contrast objects.
- Specular highlights create holes in the mask -> morphological closing.
- Objects touching the frame border cannot be measured correctly -> flagged.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


class SegmentationError(RuntimeError):
    pass


@dataclass
class SegmentationResult:
    mask: np.ndarray          # uint8 {0,255}, same size as input
    contour: np.ndarray       # largest external contour (Nx1x2 int32)
    touches_border: bool
    area_px: float


def segment(image: np.ndarray, background: np.ndarray, cfg: dict) -> SegmentationResult:
    seg = cfg["segmentation"]
    if image.shape != background.shape:
        raise SegmentationError(
            f"Image {image.shape} vs background {background.shape} mismatch. "
            "Recapture the background at the current camera settings."
        )

    k = int(seg["blur_kernel"]) | 1  # force odd
    img_b = cv2.GaussianBlur(image, (k, k), 0)
    bg_b = cv2.GaussianBlur(background, (k, k), 0)

    # Gray difference
    diff_gray = cv2.absdiff(
        cv2.cvtColor(img_b, cv2.COLOR_BGR2GRAY),
        cv2.cvtColor(bg_b, cv2.COLOR_BGR2GRAY),
    )
    # Saturation difference (helps with white-on-white / colored decor)
    diff_sat = cv2.absdiff(
        cv2.cvtColor(img_b, cv2.COLOR_BGR2HSV)[:, :, 1],
        cv2.cvtColor(bg_b, cv2.COLOR_BGR2HSV)[:, :, 1],
    )
    diff = cv2.max(diff_gray, diff_sat)

    _, mask = cv2.threshold(diff, int(seg["diff_threshold"]), 255, cv2.THRESH_BINARY)

    mk = int(seg["morph_kernel"]) | 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (mk, mk))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours = [c for c in contours if cv2.contourArea(c) >= float(seg["min_area_px"])]
    if not contours:
        raise SegmentationError(
            "No object found. Is the box empty, or is diff_threshold too high?"
        )

    contour = max(contours, key=cv2.contourArea)

    # Fill only the chosen contour into a clean mask (drop stray blobs).
    clean = np.zeros(mask.shape, dtype=np.uint8)
    cv2.drawContours(clean, [contour], -1, 255, thickness=cv2.FILLED)

    margin = int(seg["border_margin_px"])
    x, y, w, h = cv2.boundingRect(contour)
    H, W = mask.shape
    touches = (
        x <= margin or y <= margin
        or x + w >= W - margin or y + h >= H - margin
    )

    return SegmentationResult(
        mask=clean,
        contour=contour,
        touches_border=touches,
        area_px=float(cv2.contourArea(contour)),
    )
