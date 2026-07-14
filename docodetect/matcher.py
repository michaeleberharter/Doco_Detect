"""Stage 1 matcher: statistical scoring with adaptive feature weights.

Für jedes gemessene Objekt:

1. VORFILTER (hart, unverändert): Höhenkompensation mit der Artikelhöhe aus
   der DB, dann diameter_tolerance_mm / area_tolerance_pct gegen die
   Stammdaten. Reduziert hunderte Artikel auf eine Handvoll Kandidaten.

2. STATISTISCHES SCORING: pro Kandidat und Merkmal
       d      = Distanz Messung <-> Enrollment-Referenz
       sigma  = sqrt(sigma_enroll^2 + sigma_floor^2)
       z      = d / sigma
       logL   = -0.5 * z^2          (Gauß-Log-Likelihood bis auf Konstante)
   Gesamt-Log-Score = gewichtetes Mittel der logL über die beim Kandidaten
   verfügbaren Merkmale. Kandidaten MIT Enrollment-Statistiken werden
   Floor-Ebene gegen Floor-Ebene verglichen (Enrollment maß dasselbe Objekt
   in derselben Höhe – keine doppelte Höhenkorrektur); Kandidaten OHNE
   Referenzen laufen geometry-only (höhenkorrigierter Ø gegen Nominal) und
   können nie ACCEPT werden.

3. ADAPTIVE GEWICHTE (Fisher-Ratio über das Kandidatenset):
       D_f = Var(Kandidaten-Lagen) / Mittel(sigma_eff^2)
   Skalare Merkmale nutzen die Referenz-Mittelwerte als Lage, Prototyp-
   Merkmale die gemessene Distanz d_i (skalare Einbettung der Vektoren).
   w_eff = w_global * (1 + alpha * D_norm), normiert. Trennt ein Merkmal die
   aktuellen Kandidaten gut, bekommt es mehr Gewicht. Bei nur einem
   Kandidaten oder alpha=0 entfällt die Adaption.

4. ENTSCHEIDUNG: ACCEPT / AMBIGUOUS / REJECT über das absolute max|z|-Gate
   (matching.max_z_accept) und den Log-Likelihood-Ratio-Vorsprung zu Platz 2
   (matching.min_llr_margin). Siehe README, Abschnitt "Scoring".

Der MatchReport enthält ALLE Zwischengrößen (pro Kandidat und Merkmal:
Messwert, Referenz, Distanz, sigma, z, Log-Beitrag; dazu Fisher-D, Gewichte,
Posterior, Gate-Status) und ist JSON-serialisierbar – die Streamlit-Seite
"Scoring-Analyse" rendert ausschließlich diese Reports.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime

import numpy as np

from .calibration import Calibration
from .database import Article, Database
from .features import (ALL_FEATURES, PROTO_FEATURES, SCALAR_FEATURES,
                       EnrollmentStats, Features, height_corrected_scale,
                       proto_distance, scalar_value)

DECISION_ACCEPT = "accept"
DECISION_AMBIGUOUS = "ambiguous"
DECISION_REJECT = "reject"

# Merkmal -> Key in matching.sigma_floors (Zonen teilen sich einen Floor)
_FLOOR_KEY = {
    "delta_e_center": "delta_e", "delta_e_rim": "delta_e",
    "hist_center": "hist_bhattacharyya", "hist_rim": "hist_bhattacharyya",
}


def _sigma_floor(feature: str, floors: dict) -> float:
    return float(floors[_FLOOR_KEY.get(feature, feature)])


@dataclass
class FeatureScore:
    feature: str
    measured: float | None      # Skalar-Messwert; None bei Prototyp-Merkmalen
    reference: float | None     # Enrollment-Mittel bzw. Nominal; None bei Prototypen
    distance: float
    sigma_enroll: float
    sigma_eff: float
    z: float
    log_contrib: float          # -0.5 * z^2
    w_eff: float                # normiertes globales Gewicht dieses Merkmals
    weighted: float             # Beitrag zum log_score (pro Kandidat renormiert)


@dataclass
class CandidateReport:
    article_number: str
    name: str
    nominal_size_mm: float
    height_mm: float
    corrected_diameter_mm: float   # höhenkompensierter Mess-Ø (Vorfilter-Wert)
    geometry_error_mm: float       # |korrigiert - Nominal| (Vorfilter)
    has_references: bool
    n_shots: int
    features: list[FeatureScore] = field(default_factory=list)
    log_score: float = 0.0
    posterior: float = 0.0
    max_abs_z: float = 0.0


@dataclass
class MatchReport:
    decision: str                       # accept | ambiguous | reject
    message: str
    candidates: list[CandidateReport] = field(default_factory=list)
    feature_names: list = field(default_factory=list)
    fisher_d: dict = field(default_factory=dict)        # {} wenn Adaption entfiel
    fisher_d_norm: dict = field(default_factory=dict)
    w_global: dict = field(default_factory=dict)        # normiert
    w_eff: dict = field(default_factory=dict)           # normiert
    alpha: float = 0.0
    llr_margin: float | None = None                     # None bei <2 Kandidaten
    max_z_winner: float | None = None
    gate_passed: bool = False
    thresholds: dict = field(default_factory=dict)
    measured: dict = field(default_factory=dict)        # asdict(Features) der Messung
    contour: list | None = None                         # [[x,y],...] fürs Overlay
    touches_border: bool | None = None
    timestamp: str = ""
    image_path: str | None = None
    label: str | None = None                            # Ground-Truth (evaluate/Batch)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @staticmethod
    def from_dict(d: dict) -> "MatchReport":
        d = dict(d)
        d["candidates"] = [
            CandidateReport(**{**c, "features": [FeatureScore(**f) for f in c["features"]]})
            for c in d.get("candidates", [])
        ]
        return MatchReport(**d)

    @staticmethod
    def from_json(s: str) -> "MatchReport":
        return MatchReport.from_dict(json.loads(s))


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


def _feature_rows(measured: Features, stats: EnrollmentStats | None,
                  corrected_d: float, geo_err: float, nominal: float) -> dict:
    """-> dict feature -> (distance, sigma_enroll, measured_v, reference_v).
    Ohne Stats bleibt nur der Ø gegen die Stammdaten (geometry-only)."""
    rows: dict = {}
    if stats is None:
        rows["diameter_mm"] = (geo_err, 0.0, corrected_d, nominal)
        return rows
    for name in SCALAR_FEATURES:
        mv = scalar_value(measured, name)
        if mv is None or name not in stats.scalar_mean:
            continue
        ref = stats.scalar_mean[name]
        rows[name] = (abs(mv - ref), stats.scalar_std.get(name, 0.0), mv, ref)
    for name in PROTO_FEATURES:
        d = proto_distance(name, measured, stats)
        if d is not None:
            rows[name] = (d, stats.proto_std.get(name, 0.0), None, None)
    return rows


def match(measured: Features, db: Database, cal: Calibration, cfg: dict,
          image_path: str | None = None, label: str | None = None,
          contour: list | None = None,
          touches_border: bool | None = None) -> MatchReport:
    m = cfg["matching"]
    tol_mm = float(m["diameter_tolerance_mm"])
    area_tol = float(m["area_tolerance_pct"]) / 100.0
    floors = m["sigma_floors"]
    alpha = float(m.get("adaptive_weight_alpha", 2.0))
    temperature = float(m.get("softmax_temperature", 1.0)) or 1.0
    max_z_accept = float(m.get("max_z_accept", 3.5))
    min_llr = float(m.get("min_llr_margin", 2.0))
    thresholds = {"max_z_accept": max_z_accept, "min_llr_margin": min_llr,
                  "softmax_temperature": temperature, "top_k": int(m.get("top_k", 3))}
    now = datetime.now().isoformat(timespec="seconds")

    w_cfg = m["feature_weights"]
    w_sum = sum(float(w_cfg.get(f, 0.0)) for f in ALL_FEATURES)
    w_global = {f: float(w_cfg.get(f, 0.0)) / w_sum for f in ALL_FEATURES}

    # ---- Vorfilter (hart, höhenkompensiert pro Kandidat – wie gehabt) ----
    prelim: list[tuple[Article, float, float, float, EnrollmentStats | None, dict]] = []
    for art in db.all_articles():
        nominal = _nominal_size_mm(art)
        if nominal is None:
            continue  # article has no size data – cannot participate in stage 1

        h = float(art.height_mm or 0.0)
        corrected_d = height_corrected_scale(
            measured.circle_diameter_mm, h, cal.camera_height_mm)
        geo_err = abs(corrected_d - nominal)
        if geo_err > tol_mm:
            continue

        # secondary area plausibility check (same height correction, area ~ scale^2)
        corr = (cal.camera_height_mm - min(h, 0.8 * cal.camera_height_mm)) / cal.camera_height_mm
        corrected_area = measured.area_mm2 * corr * corr
        nominal_area = np.pi * (nominal / 2.0) ** 2
        if art.diameter_mm and abs(corrected_area - nominal_area) / nominal_area > area_tol * 2:
            continue

        stats = db.stats_for(art.article_number)
        rows = _feature_rows(measured, stats, corrected_d, geo_err, nominal)
        prelim.append((art, corrected_d, geo_err, nominal, stats, rows))

    if not prelim:
        return MatchReport(
            decision=DECISION_REJECT,
            message="Kein Artikel innerhalb der Geometrie-Toleranz – Objekt "
                    "vermutlich nicht in der Datenbank (oder Segmentierung/"
                    "Toleranzen prüfen). Niemals automatisch buchen.",
            feature_names=list(ALL_FEATURES), w_global=w_global, w_eff=dict(w_global),
            alpha=alpha, gate_passed=False, thresholds=thresholds,
            measured=asdict(measured), contour=contour,
            touches_border=touches_border, timestamp=now,
            image_path=image_path, label=label)

    # ---- adaptive Gewichte: Fisher-Ratio über das Kandidatenset ----
    # D_f = Varianz der Kandidaten-Lagen / mittlere Messvarianz. Skalare
    # Merkmale nutzen die Referenz-MITTELWERTE als Lage; Prototyp-Merkmale
    # die gemessene Distanz d_i (skalare Einbettung der Vektor-Prototypen).
    fisher_d: dict = {}
    fisher_d_norm: dict = {}
    w_eff = dict(w_global)
    if len(prelim) >= 2 and alpha > 0:
        for f in ALL_FEATURES:
            locs, sig2 = [], []
            for (_, _, _, _, _, rows) in prelim:
                row = rows.get(f)
                if row is None:
                    continue
                dist, s_enroll, _, ref = row
                locs.append(ref if f in SCALAR_FEATURES and ref is not None else dist)
                sig2.append(s_enroll ** 2 + _sigma_floor(f, floors) ** 2)
            if len(locs) >= 2 and np.mean(sig2) > 0:
                fisher_d[f] = float(np.var(locs) / np.mean(sig2))
        total = sum(fisher_d.values())
        if total > 0:
            fisher_d_norm = {f: v / total for f, v in fisher_d.items()}
            w_eff = {f: w_global[f] * (1.0 + alpha * fisher_d_norm.get(f, 0.0))
                     for f in w_global}
            s = sum(w_eff.values())
            w_eff = {f: v / s for f, v in w_eff.items()}

    # ---- Scoring pro Kandidat ----
    candidates: list[CandidateReport] = []
    for (art, corrected_d, geo_err, nominal, stats, rows) in prelim:
        scores: list[FeatureScore] = []
        wsum = sum(w_eff[f] for f in rows)
        for f in ALL_FEATURES:
            row = rows.get(f)
            if row is None:
                continue
            dist, s_enroll, mv, ref = row
            sigma_eff = math.sqrt(s_enroll ** 2 + _sigma_floor(f, floors) ** 2)
            z = dist / sigma_eff
            log_contrib = -0.5 * z * z
            scores.append(FeatureScore(
                feature=f, measured=mv, reference=ref, distance=round(dist, 4),
                sigma_enroll=round(s_enroll, 4), sigma_eff=round(sigma_eff, 4),
                z=round(z, 4), log_contrib=round(log_contrib, 4),
                w_eff=round(w_eff[f], 4),
                weighted=round(w_eff[f] * log_contrib / wsum, 4) if wsum > 0 else 0.0))
        log_score = sum(s.weighted for s in scores)
        candidates.append(CandidateReport(
            article_number=art.article_number, name=art.name,
            nominal_size_mm=round(nominal, 2), height_mm=float(art.height_mm or 0.0),
            corrected_diameter_mm=round(corrected_d, 2),
            geometry_error_mm=round(geo_err, 2),
            has_references=stats is not None,
            n_shots=stats.n_shots if stats else 0,
            features=scores, log_score=round(log_score, 4),
            max_abs_z=round(max((abs(s.z) for s in scores), default=0.0), 4)))

    candidates.sort(key=lambda c: c.log_score, reverse=True)

    # Posterior: Softmax der Log-Scores (numerisch stabil, optionale Temperatur)
    ls = np.asarray([c.log_score for c in candidates], dtype=np.float64) / temperature
    e = np.exp(ls - ls.max())
    post = e / e.sum()
    for c, p in zip(candidates, post):
        c.posterior = round(float(p), 4)

    # ---- Entscheidung: absolutes Gate + LLR-Margin ----
    best = candidates[0]
    llr = (round(candidates[0].log_score - candidates[1].log_score, 4)
           if len(candidates) > 1 else None)
    gate = best.max_abs_z <= max_z_accept
    if not gate:
        decision = DECISION_REJECT
        message = (f"Objekt vermutlich nicht in der Datenbank: bestes Merkmal-z "
                   f"{best.max_abs_z:.1f} > {max_z_accept} ({best.article_number}). "
                   "Niemals automatisch buchen.")
    elif (llr is None or llr >= min_llr) and best.has_references:
        decision = DECISION_ACCEPT
        message = (f"{best.article_number} akzeptiert "
                   f"(max|z| {best.max_abs_z:.2f}, LLR-Margin "
                   f"{'∞' if llr is None else f'{llr:.2f}'}, "
                   f"Posterior {best.posterior:.0%}).")
    else:
        # TODO(stage-2): Genau diese AMBIGUOUS-Fälle später an Stufe 2
        # (DINOv2 + FAISS, docodetect/embeddings.py) übergeben und deren
        # Nearest-Neighbor-Votum als zusätzliches Merkmal einrechnen.
        decision = DECISION_AMBIGUOUS
        reason = ("keine Enrollment-Referenzen" if not best.has_references
                  else f"LLR-Margin {llr:.2f} < {min_llr}")
        message = (f"{len(candidates)} Kandidat(en), manuelle Auswahl nötig "
                   f"({reason}). Top: {best.article_number}.")

    return MatchReport(
        decision=decision, message=message, candidates=candidates,
        feature_names=list(ALL_FEATURES), fisher_d=fisher_d,
        fisher_d_norm=fisher_d_norm, w_global=w_global, w_eff=w_eff,
        alpha=alpha, llr_margin=llr, max_z_winner=best.max_abs_z,
        gate_passed=gate, thresholds=thresholds, measured=asdict(measured),
        contour=contour, touches_border=touches_border, timestamp=now,
        image_path=image_path, label=label)
