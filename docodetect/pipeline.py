"""End-to-end pipeline: image -> segmentation -> features -> match.

Both the CLI and any future UI/REST service call ONLY this module, so the
process stays identical everywhere.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .calibration import Calibration, load_background, load_calibration
from .database import Article, Database
from .features import (Features, describe_color_hsv, extract,
                       height_corrected_scale, min_area_rect_mm)
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
        seg = segment(image, self.background)
        if seg.touches_border:
            raise SegmentationError(
                "Object touches the frame border – measurement would be wrong. "
                "Center the item; if it does not fit, see README (FOV limitation).",
                segmentation=seg,
            )
        feats = extract(image, seg, self.cal)
        return seg, feats

    def identify(self, image: np.ndarray) -> IdentifyOutcome:
        try:
            seg, feats = self.analyze(image)
        except SegmentationError as e:
            # Keep the (border-touching) segmentation, if any, so the UI can
            # still show the contour that caused the rejection.
            return IdentifyOutcome(None, e.segmentation,
                                   MatchResult("no_match", [], f"Segmentation: {e}"))
        result = match(feats, self.db, self.cal, self.cfg)
        return IdentifyOutcome(feats, seg, result)

    def enroll(self, image: np.ndarray, article_number: str,
               image_path: str | None = None) -> tuple[Features, SegmentationResult]:
        """Measure AND store in one step (CLI flow). Returns (features,
        segmentation) so callers can show the measured contour. UIs that want
        a confirm step call analyze() first and save_reference() on confirm."""
        seg, feats = self.analyze(image)
        self.db.add_reference(article_number, feats, image_path)
        return feats, seg

    def save_reference(self, article_number: str, feats: Features,
                       image_path: str | None = None) -> None:
        """Second half of the two-step enroll flow: persist an already-measured
        (and user-approved) reference."""
        self.db.add_reference(article_number, feats, image_path)

    def create_article(self, image: np.ndarray, name: str, *,
                       article_number: str | None = None,
                       height_mm: float = 0.0,
                       category: str | None = None,
                       notes: str | None = None,
                       image_path: str | None = None,
                       add_reference: bool = True
                       ) -> tuple[Article, Features, SegmentationResult]:
        """Create a brand-new article straight from one live shot – no CSV.

        The footprint is derived from the measurement: round items get
        `diameter_mm`, elongated items (spoon, knife, oval platter) get
        `width_mm`/`depth_mm` – the latter matters because the matcher's area
        plausibility check only runs when `diameter_mm` is set and would
        otherwise reject a non-round item on re-identification. When a real
        `height_mm` is given, the stored size is the height-corrected true
        size, so re-measuring the same object stays self-consistent.

        By default the same shot is stored as the first reference so the
        article is identifiable immediately (colour + shape, not geometry
        only). `article_number` is auto-derived from `name` when omitted.

        Returns (article, features, segmentation) – the segmentation lets a
        UI show the same measured contour/mask preview as identify, so a bad
        segmentation is visible before trusting the new article.

        Raises SegmentationError (object touches the border – like enroll,
        NOT caught here) and KeyError (article_number already exists).
        """
        seg, feats = self.analyze(image)
        article = self.derive_article(seg, feats, name, article_number=article_number,
                                      height_mm=height_mm, category=category, notes=notes)
        self.commit_article(article, feats if add_reference else None, image_path)
        return article, feats, seg

    def derive_article(self, seg: SegmentationResult, feats: Features, name: str, *,
                       article_number: str | None = None,
                       height_mm: float = 0.0,
                       category: str | None = None,
                       notes: str | None = None) -> Article:
        """Build the article master data from a measurement WITHOUT persisting
        anything – first half of the two-step (preview -> confirm) create flow.
        Only reads the DB (to derive a unique article number)."""
        cc = self.cfg.get("create", {})
        circ_min = float(cc.get("round_circularity_min", 0.80))
        aspect_min = float(cc.get("round_aspect_min", 0.80))
        z = self.cal.camera_height_mm

        diameter_mm = width_mm = depth_mm = None
        if feats.circularity >= circ_min and feats.aspect_ratio >= aspect_min:
            diameter_mm = round(
                height_corrected_scale(feats.circle_diameter_mm, height_mm, z), 2)
        else:
            width_mm, depth_mm = min_area_rect_mm(seg.contour, self.cal, height_mm)

        number = article_number or self.db.generate_article_number(
            name, cc.get("article_number_prefix", ""))
        return Article(
            article_number=number, name=name, category=category,
            diameter_mm=diameter_mm, width_mm=width_mm, depth_mm=depth_mm,
            height_mm=(height_mm or None),
            color_desc=describe_color_hsv(feats.mean_hsv),
            notes=(notes or "Automatisch per Kamera angelegt."),
        )

    def commit_article(self, article: Article, feats: Features | None = None,
                       image_path: str | None = None) -> None:
        """Second half of the two-step create flow: insert the previewed
        article and (optionally) its first reference. Raises KeyError if the
        article number was taken in the meantime."""
        self.db.create_article(article)
        if feats is not None:
            self.db.add_reference(article.article_number, feats, image_path)

    def close(self) -> None:
        self.db.close()
