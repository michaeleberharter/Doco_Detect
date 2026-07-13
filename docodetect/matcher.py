"""Stage 1 matcher: deterministic candidate filtering + scoring.

Flow for one measured object:

1. GEOMETRY FILTER (hard): for every article, apply the height compensation
   with THAT article's height_mm and compare the corrected measured diameter
   (round items: min-enclosing-circle; non-round: uses width/depth from DB)
   against the nominal size. Outside tolerance -> candidate eliminated.
   This alone usually reduces hundreds of articles to a handful.

2. SCORING (soft): remaining candidates are ranked by a weighted score of
   geometry closeness, color distance and shape distance against the
   article's ENROLLED reference features. Articles without references are
   scored on geometry only (flagged in the result).

3. DECISION: score >= auto_accept_score AND margin to the runner-up
   >= auto_accept_margin -> AUTO. Otherwise -> CONFIRM with top_k proposals.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .calibration import Calibration
from .database import Article, Database
from .features import Features, color_distance, height_corrected_scale, shape_distance


@dataclass
class Candidate:
    article: Article
    score: float                 # 0..1, higher = better
    corrected_diameter_mm: float # measured diameter after height compensation
    geometry_error_mm: float
    color_dist: float | None = None
    shape_dist: float | None = None
    has_references: bool = False


@dataclass
class MatchResult:
    decision: str                     # "auto" | "confirm" | "no_match"
    candidates: list[Candidate] = field(default_factory=list)
    message: str = ""


def _nominal_size_mm(article: Article) -> float | None:
    """Nominal footprint size to compare against the measured circle diameter.
    Round items: diameter. Non-round: the diagonal-ish max of width/depth,
    since min-enclosing-circle of a rectangle equals its diagonal."""
    if article.diameter_mm:
        return float(article.diameter_mm)
    if article.width_mm and article.depth_mm:
        return float(np.hypot(article.width_mm, article.depth_mm))
    if article.width_mm:
        return float(article.width_mm)
    return None


def match(measured: Features, db: Database, cal: Calibration, cfg: dict) -> MatchResult:
    m = cfg["matching"]
    tol_mm = float(m["diameter_tolerance_mm"])
    area_tol = float(m["area_tolerance_pct"]) / 100.0
    weights = m["weights"]
    w_sum = sum(weights.values())
    wg, wc, ws = (weights["geometry"] / w_sum, weights["color"] / w_sum,
                  weights["shape"] / w_sum)

    candidates: list[Candidate] = []

    for art in db.all_articles():
        nominal = _nominal_size_mm(art)
        if nominal is None:
            continue  # article has no size data – cannot participate in stage 1

        h = float(art.height_mm or 0.0)
        corrected_d = height_corrected_scale(
            measured.circle_diameter_mm, h, cal.camera_height_mm
        )
        geo_err = abs(corrected_d - nominal)
        if geo_err > tol_mm:
            continue

        # secondary area plausibility check (same height correction, area ~ scale^2)
        corr = (cal.camera_height_mm - min(h, 0.8 * cal.camera_height_mm)) / cal.camera_height_mm
        corrected_area = measured.area_mm2 * corr * corr
        nominal_area = np.pi * (nominal / 2.0) ** 2
        if art.diameter_mm and abs(corrected_area - nominal_area) / nominal_area > area_tol * 2:
            continue

        geo_score = max(0.0, 1.0 - geo_err / tol_mm)  # 1 at perfect, 0 at tolerance edge

        refs = db.references_for(art.article_number)
        if refs:
            c_dists = [color_distance(measured, r) for r in refs]
            s_dists = [shape_distance(measured, r) for r in refs]
            c_d, s_d = float(min(c_dists)), float(min(s_dists))
            score = wg * geo_score + wc * (1.0 - c_d) + ws * (1.0 - s_d)
            cand = Candidate(art, round(score, 4), round(corrected_d, 1),
                             round(geo_err, 2), round(c_d, 4), round(s_d, 4), True)
        else:
            # geometry-only fallback; cap score so it cannot auto-accept blindly
            score = min(geo_score, 0.79)
            cand = Candidate(art, round(score, 4), round(corrected_d, 1),
                             round(geo_err, 2), None, None, False)

        candidates.append(cand)

    candidates.sort(key=lambda c: c.score, reverse=True)
    top = candidates[: int(m["top_k"])]

    if not candidates:
        return MatchResult("no_match", [], "No article within geometric tolerance. "
                           "Unknown item, bad segmentation, or tolerances too tight.")

    best = candidates[0]
    margin = best.score - (candidates[1].score if len(candidates) > 1 else 0.0)
    if (best.score >= float(m["auto_accept_score"])
            and margin >= float(m["auto_accept_margin"])
            and best.has_references):
        return MatchResult("auto", top,
                           f"Auto-accepted {best.article.article_number} "
                           f"(score {best.score:.2f}, margin {margin:.2f}).")

    return MatchResult("confirm", top,
                       f"{len(candidates)} candidate(s) – manual confirmation needed "
                       f"(best score {best.score:.2f}, margin {margin:.2f}).")
