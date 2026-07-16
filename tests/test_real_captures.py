"""Regression suite on REAL captures from the photo box (data/captures/).

Synthetic mock-ups cannot reproduce the reflection structure of polished
steel – these tests pin the segmentation quality on the user's actual
cutlery photos. Golden areas were established on 2026-07-16 (self-calibrating
engine, no config, illumination-scaled edge thresholds, no texture seeds)
after visual inspection of overlays: bowls complete, fork-tine slots open,
mirror necks bridged, no glow fringe, contours tight. Measured against a
fresh era-2 empty capture; cross-reference variation is ~2%, well inside
AREA_TOL. Skipped when captures, background or scipy are not available.

Regenerate goldens after INTENDED behavior changes:
    python -m pytest tests/test_real_captures.py -q  # failures print actuals
"""

import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.config import resolve  # noqa: E402

# capture id -> mask area established after visual approval. IMPORTANT: a
# capture is only comparable while calibration/background.png matches its
# lighting era – re-lighting the box invalidates old captures (they are
# auto-skipped via the floor-compatibility gate below; archive them and
# record fresh goldens). Era 2 (dimmer lighting) started 2026-07-15 02:25;
# era-1 captures live in data/captures/archive_relight1/.
GOLDEN_AREAS = {
    "1784075122341": 45883,   # teaspoon
    "1784147898502": 45162,   # teaspoon diagonal
    "1784147942106": 71714,   # fork flat, pointing left
    "1784147956715": 73664,   # fork VERTICAL (mirror neck – bridge case)
    "1784148001298": 71501,   # fork flat, pointing right
    "1784148023691": 80974,   # serving spoon
    "1784152895463": 80019,   # serving spoon flat
    "1784152909645": 72168,   # fork diagonal (mirror heel – notch case)
    "1784152917062": 71666,   # fork flat
    "1784152931460": 45566,   # teaspoon bent
    "1784152943049": 73790,   # fork diagonal
    "1784152961451": 25238,   # small dim teaspoon (glow-fringe case)
}
AREA_TOL = 0.08            # masks may drift this much before we call it regression
MIN_STEEL_COVERAGE = 0.93  # strong-evidence pixels the mask must cover
STRONG_DIFF = 30           # era-2 "surely steel" gray diff (goldens are era-scoped)


def _available():
    if not resolve("data/captures").exists():
        return "no captures"
    if not resolve("calibration/background.png").exists():
        return "no background"
    try:
        import scipy  # noqa: F401
    except ImportError:
        return "scipy missing"
    return None


@pytest.mark.parametrize("capture_id", sorted(GOLDEN_AREAS))
def test_real_capture_segmentation(capture_id):
    reason = _available()
    if reason:
        pytest.skip(reason)
    path = resolve(f"data/captures/{capture_id}.png")
    if not path.exists():
        pytest.skip(f"capture {capture_id} not present")

    from docodetect.segmentation import segment

    bg = cv2.imread(str(resolve("calibration/background.png")))
    img = cv2.imread(str(path))

    # era gate: the capture's floor must match the CURRENT background –
    # after re-lighting the box, old captures are meaningless (not wrong)
    cue = cv2.GaussianBlur(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (3, 3), 0)
    bgc = cv2.GaussianBlur(cv2.cvtColor(bg, cv2.COLOR_BGR2GRAY), (3, 3), 0)
    if float(np.median(cv2.absdiff(cue, bgc))) > 6:
        pytest.skip(f"{capture_id}: anderes Beleuchtungs-Setup als der "
                    "aktuelle Hintergrund – Golden nicht vergleichbar")

    s = segment(img, bg)

    # 1. area close to the visually approved golden
    golden = GOLDEN_AREAS[capture_id]
    assert abs(s.area_px - golden) / golden <= AREA_TOL, (
        f"{capture_id}: area {s.area_px:.0f} vs golden {golden} "
        f"({(s.area_px - golden) / golden:+.1%})")

    # 2. no steel lost: the mask covers (nearly) all strong-evidence pixels
    strong = cv2.absdiff(cue, bgc) >= STRONG_DIFF
    coverage = float((strong & (s.mask > 0)).sum()) / max(1, int(strong.sum()))
    assert coverage >= MIN_STEEL_COVERAGE, (
        f"{capture_id}: steel coverage {coverage:.3f} – object material lost")

    # 3. sane result object
    assert not s.touches_border
    assert cv2.contourArea(s.contour) > 0


def test_background_duplicate_raises():
    """A capture that IS the background (empty box) must raise, not measure."""
    reason = _available()
    if reason:
        pytest.skip(reason)
    path = resolve("data/captures/1784152866853.png")
    if not path.exists():
        pytest.skip("capture not present")
    from docodetect.segmentation import segment, SegmentationError
    bg = cv2.imread(str(resolve("calibration/background.png")))
    img = cv2.imread(str(path))
    if float(np.median(cv2.absdiff(img, bg))) > 6:
        pytest.skip("anderes Beleuchtungs-Setup")
    with pytest.raises(SegmentationError):
        segment(img, bg)
