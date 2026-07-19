"""End-to-end pipeline: image -> segmentation -> features -> match.

Both the CLI and any future UI/REST service call ONLY this module, so the
process stays identical everywhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import cv2
import numpy as np

from .calibration import (Calibration, load_background, load_calibration,
                          run_calibration, save_background)
from .config import resolve
from .database import Article, Database
from .features import (Features, describe_color_hsv, extract,
                       height_corrected_scale, min_area_rect_mm)
from .matcher import DECISION_REJECT, MatchReport, match
from .segmentation import SegmentationError, SegmentationResult, segment


@dataclass
class IdentifyOutcome:
    features: Features | None
    segmentation: SegmentationResult | None
    report: MatchReport


@dataclass
class PipelineStatus:
    """Einrichtungszustand für UIs (Statusleiste + NOT_READY-Führung).
    Muss auch VOR jeder Einrichtung funktionieren – get_status() setzt
    keine Kalibrierung voraus und legt keine Dateien an."""
    calibrated: bool
    mm_per_px: float | None
    calibrated_unix: float | None
    background_present: bool
    article_count: int
    articles_with_references: int
    stage2_enabled: bool

    @property
    def ready(self) -> bool:
        """Identifizieren möglich (Kalibrierung + Hintergrund vorhanden)."""
        return self.calibrated and self.background_present


@dataclass
class ArticleInfo:
    """Artikel-Zeile fürs UI (Einlern-Dropdown, Listen) – Stammdaten plus
    Referenzanzahl, ohne dass die UI database.py anfassen muss."""
    article_number: str
    name: str
    category: str | None
    diameter_mm: float | None
    height_mm: float | None
    n_references: int


def get_status(cfg: dict) -> PipelineStatus:
    """Reine Status-Abfrage ohne Nebenwirkungen: fehlende/kaputte Dateien
    bedeuten 'nicht eingerichtet', nie eine Exception. Insbesondere wird
    KEINE leere SQLite-Datei angelegt (sqlite3.connect würde das tun)."""
    mm_per_px = calibrated_unix = None
    try:
        cal = load_calibration(cfg)
        mm_per_px, calibrated_unix = cal.mm_per_px, cal.created_unix
    except Exception:
        pass

    background_present = resolve(cfg["calibration"]["background_file"]).exists()

    article_count = with_refs = 0
    if resolve(cfg["paths"]["db_file"]).exists():
        db = Database(cfg)
        try:
            article_count = len(db.all_articles())
            with_refs = len(db.articles_with_references())
        except Exception:
            pass  # DB ohne Schema o.ä. -> zählt als leer
        finally:
            db.close()

    return PipelineStatus(
        calibrated=mm_per_px is not None, mm_per_px=mm_per_px,
        calibrated_unix=calibrated_unix, background_present=background_present,
        article_count=article_count, articles_with_references=with_refs,
        stage2_enabled=bool(cfg.get("stage2", {}).get("enabled", False)))


def capture_background(image: np.ndarray, cfg: dict):
    """Einzelbild-Fassade: Hintergrund-Referenz aus einem Frame speichern.
    Dünne Weiterleitung an calibration.py, damit die UI-Regel hält (UIs
    importieren nur pipeline)."""
    return save_background(image, cfg)


def calibrate(image: np.ndarray, cfg: dict) -> Calibration:
    """Einzelbild-Fassade: ArUco-Kalibrierung aus einem Frame. Wirft
    RuntimeError mit handlungsleitender Meldung, wenn kein Marker gefunden
    wird (calibration.py)."""
    return run_calibration(image, cfg)


def measure_shot(image: np.ndarray, cfg: dict) -> tuple[Features, SegmentationResult]:
    """Einzel-Shot fürs Einlernen VERMESSEN, ohne etwas zu persistieren –
    erste Hälfte des Zwei-Schritt-Ablaufs (analyze -> save_reference), damit
    ein Einlern-Dialog einzelne Aufnahmen wiederholen kann, ohne verwaiste
    Referenzen in der DB zu hinterlassen. Raises SegmentationError
    (Randberührung) wie enroll."""
    pipe = Pipeline(cfg)
    try:
        seg, feats = pipe.analyze(image)
    finally:
        pipe.close()
    return feats, seg


def save_enrollment(cfg: dict, article_number: str,
                    shots: list) -> int:
    """Zweite Hälfte des Einlern-Ablaufs: alle bestätigten Shots
    [(image, Features), ...] auf einmal persistieren – Referenzfoto nach
    paths.reference_dir/<artikel>/ (wie CLI und Streamlit) + Features in die
    DB (Enrollment-Statistik wird dabei aktualisiert)."""
    ref_dir = resolve(cfg["paths"]["reference_dir"]) / article_number
    ref_dir.mkdir(parents=True, exist_ok=True)
    pipe = Pipeline(cfg)
    try:
        ts = int(datetime.now().timestamp() * 1000)
        for i, (img, feats) in enumerate(shots):
            path = ref_dir / f"{ts}_{i}.jpg"
            cv2.imwrite(str(path), img)
            pipe.save_reference(article_number, feats, str(path))
    finally:
        pipe.close()
    return len(shots)


def confirm_result(report: MatchReport, article_number: str):
    """Manuelle Bestätigung einer AMBIGUOUS-Auswahl (Karten-Klick in der UI):
    Top-1 bestätigt = korrekt, anderer Kandidat = falsch mit wahrem Artikel.
    Schreibt ins gespeicherte Report-JSON (Batch-Auswertung liest es)."""
    from .reporting import predicted_article, save_verdict
    return save_verdict(report, correct=(article_number == predicted_article(report)),
                        true_article=article_number)


def render_report_overlay(image: np.ndarray, report: MatchReport) -> np.ndarray:
    """Annotiertes Ergebnisbild: Kontur (rot bei Randberührung, sonst grün)
    plus Ø-Maßlinie mit mm-Beschriftung. Arbeitet nur mit dem MatchReport
    (Kontur-Polygon + Messwerte) – funktioniert daher auch für aus JSON
    geladene Reports. Das Eingangsbild bleibt unverändert (Kopie)."""
    out = image.copy()
    if not report.contour:
        return out
    pts = np.asarray(report.contour, dtype=np.int32).reshape(-1, 1, 2)
    color = (0, 0, 255) if report.touches_border else (0, 255, 0)
    thickness = max(2, image.shape[1] // 640)
    cv2.polylines(out, [pts], isClosed=True, color=color, thickness=thickness)

    # Beschriftung: der höhenkompensierte Ø des Top-Kandidaten (dieselbe
    # Zahl wie auf der ResultCard – zwei verschiedene mm-Werte im selben
    # Ergebnis würden nur verwirren); ohne Kandidaten der Boden-Ebenen-Wert.
    d_mm = (report.measured or {}).get("circle_diameter_mm")
    if report.candidates:
        d_mm = report.candidates[0].corrected_diameter_mm
    if d_mm and not report.touches_border:
        # Maßlinie horizontal über die Konturbreite auf Schwerpunkthöhe
        xy = pts.reshape(-1, 2)
        cx, cy = report.centroid_px or xy.mean(axis=0)
        x0, x1 = int(xy[:, 0].min()), int(xy[:, 0].max())
        y = int(cy)
        cv2.line(out, (x0, y), (x1, y), (255, 255, 255), thickness)
        for x in (x0, x1):
            cv2.line(out, (x, y - 6 * thickness), (x, y + 6 * thickness),
                     (255, 255, 255), thickness)
        label = f"Ø {d_mm:.1f} mm".replace(".", ",")
        scale = image.shape[1] / 1500.0
        cv2.putText(out, label, (int(cx) + 4 * thickness, y - 4 * thickness),
                    cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0),
                    thickness * 3, cv2.LINE_AA)
        cv2.putText(out, label, (int(cx) + 4 * thickness, y - 4 * thickness),
                    cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255),
                    thickness, cv2.LINE_AA)
    return out


def list_articles(cfg: dict) -> list[ArticleInfo]:
    """Artikel + Referenzanzahl fürs UI. Leere Liste, solange keine DB
    existiert (kein Anlegen als Nebenwirkung, wie get_status)."""
    if not resolve(cfg["paths"]["db_file"]).exists():
        return []
    db = Database(cfg)
    try:
        counts = db.reference_counts()
        return [ArticleInfo(
            article_number=a.article_number, name=a.name, category=a.category,
            diameter_mm=a.diameter_mm, height_mm=a.height_mm,
            n_references=counts.get(a.article_number, 0))
            for a in db.all_articles()]
    except Exception:
        return []
    finally:
        db.close()


def _thin_contour(seg: SegmentationResult | None) -> list | None:
    """Konturpolygon fürs Report-Overlay – ausgedünnt, ein 4K-Teller braucht
    keine 10k Punkte im JSON."""
    if seg is None or seg.contour is None:
        return None
    pts = seg.contour.reshape(-1, 2)
    step = max(1, len(pts) // 400)
    return pts[::step].astype(int).tolist()


def _centroid_px(seg: SegmentationResult | None) -> list | None:
    """Objektschwerpunkt [x, y] in px – Grundlage der Positionsanalyse
    (Messfehler über die Bildposition, z.B. Randverzerrung des Objektivs)."""
    if seg is None or seg.contour is None:
        return None
    m = cv2.moments(seg.contour)
    if m["m00"] == 0:
        return None
    return [round(m["m10"] / m["m00"], 1), round(m["m01"] / m["m00"], 1)]


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
        feats = extract(image, seg, self.cal, self.cfg)
        return seg, feats

    def identify(self, image: np.ndarray, *, source_path: str | None = None,
                 label: str | None = None) -> IdentifyOutcome:
        try:
            seg, feats = self.analyze(image)
        except SegmentationError as e:
            # Keep the (border-touching) segmentation, if any, so the UI can
            # still show the contour that caused the rejection.
            seg_err = e.segmentation
            report = MatchReport(
                decision=DECISION_REJECT, message=f"Segmentierung: {e}",
                contour=_thin_contour(seg_err),
                touches_border=getattr(seg_err, "touches_border", None),
                timestamp=datetime.now().isoformat(timespec="seconds"),
                image_path=source_path, label=label,
                centroid_px=_centroid_px(seg_err),
                image_size=[image.shape[1], image.shape[0]] if image is not None else None)
            self._save_capture_and_report(report, image)
            return IdentifyOutcome(None, seg_err, report)
        report = match(feats, self.db, self.cal, self.cfg,
                       image_path=source_path, label=label,
                       contour=_thin_contour(seg), touches_border=seg.touches_border)
        report.centroid_px = _centroid_px(seg)
        report.image_size = [image.shape[1], image.shape[0]]
        self._save_capture_and_report(report, image)
        return IdentifyOutcome(feats, seg, report)

    def _save_capture_and_report(self, report: MatchReport,
                                 image: np.ndarray | None) -> None:
        """Jede Identifikation hinterlässt Capture + Report-JSON in
        data/captures/ – Futter für das Scoring-Dashboard (Batch-Analyse).
        Ohne paths.captures_dir (z.B. synthetische Tests) wird nichts
        geschrieben; bei identify --image bleibt image_path das Original."""
        cap = self.cfg.get("paths", {}).get("captures_dir")
        if not cap:
            return
        d = resolve(cap)
        d.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
        if report.image_path is None and image is not None:
            p = d / f"{ts}.jpg"
            cv2.imwrite(str(p), image)
            report.image_path = str(p)
        json_path = d / f"{ts}.json"
        report.report_path = str(json_path)   # Feedback (richtig/falsch) schreibt hierhin zurück
        json_path.write_text(report.to_json(), encoding="utf-8")

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
