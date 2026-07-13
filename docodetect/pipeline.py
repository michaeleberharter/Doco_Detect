"""End-to-end pipeline: image -> segmentation -> features -> match.

Both the CLI and any future UI/REST service call ONLY this module, so the
process stays identical everywhere.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .calibration import Calibration, load_background, load_calibration
from .database import Database
from .features import Features, extract
from .matcher import MatchResult, match
from .segmentation import SegmentationError, SegmentationResult, segment


@dataclass
class IdentifyOutcome:
    features: Features | None
    segmentation: SegmentationResult | None
    result: MatchResult


class Pipeline:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.cal: Calibration = load_calibration(cfg)
        self.background: np.ndarray = load_background(cfg)
        self.db = Database(cfg)

    def analyze(self, image: np.ndarray) -> tuple[SegmentationResult, Features]:
        """Segment and measure – shared by enroll and identify."""
        seg = segment(image, self.background, self.cfg)
        if seg.touches_border:
            raise SegmentationError(
                "Object touches the frame border – measurement would be wrong. "
                "Center the item; if it does not fit, see README (FOV limitation)."
            )
        feats = extract(image, seg, self.cal)
        return seg, feats

    def identify(self, image: np.ndarray) -> IdentifyOutcome:
        try:
            seg, feats = self.analyze(image)
        except SegmentationError as e:
            return IdentifyOutcome(None, None,
                                   MatchResult("no_match", [], f"Segmentation: {e}"))
        result = match(feats, self.db, self.cal, self.cfg)
        return IdentifyOutcome(feats, seg, result)

    def enroll(self, image: np.ndarray, article_number: str,
               image_path: str | None = None) -> Features:
        _, feats = self.analyze(image)
        self.db.add_reference(article_number, feats, image_path)
        return feats

    def close(self) -> None:
        self.db.close()
