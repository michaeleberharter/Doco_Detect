#!/usr/bin/env python3
"""tail_extent_check.py — Diagnose des anisotropen Tail-Effekts (read-only).

VERDIKT (2026-07-28): Ansatz GETRAGEN. Reproduziert die 8 Tails der Analyse
bitgenau (is_tail via reference_stats faengt auch die vom Vorfilter
verworfenen Ausreisser) und liefert die Extent-Messung, auf der C1-C7 aufbauen.
Das Fundament der Serie — hier weiterarbeiten, nicht bei profile/overlay.

Frage (siehe docs/2026-07-27-scoring-analyse.md, Abschnitt 5/9): Bei acht
Korpus-Aufnahmen faellt die gemessene Laenge ~4 % unter das eigene
Enrollment-Mittel, die Breite bleibt erhalten. Die Achsen-Flip-Hypothese ist
erledigt (min_area_rect_mm liegt nicht auf dem Messpfad; minEnclosingCircle
ist beim Loeffel stabil zweipunktbestimmt). Der beobachtete Rueckgang ist ein
echter Rueckgang des maximalen Punktabstands. Dieses Skript klaert, OB die
Konturenden beschnitten werden oder das ganze Objekt kleiner gemessen wird.

Es AENDERT NICHTS. Kein Schreibzugriff auf features/matcher/segmentation,
config, DB oder corpus/. Die Konturen kommen ueber den vorhandenen
Tier-1-Replay-Pfad (bundle_cfg + measure_shot), NICHT ueber eine neu gebaute
Segmentierung. Ausgabe geht ausschliesslich nach reports/analysis/<run-id>/
(gitignored).

--------------------------------------------------------------------------
ENTSCHEIDUNGSREGEL (Ergebnis pro Artikel, Tail vs. Rest):

  (A) ext_full bei Tail kurz, ext_p98 normal, (ext_full - ext_p98) bei Tail
      deutlich KLEINER als beim Rest
      -> Enden werden beschnitten. Der aeusserste Punkt, der normalerweise
         ueber das 98-%-Band hinausragt, fehlt. Naechster Verdaechtiger:
         segmentation._snap_contour_to_edges (Reflexkante vor der Spitze).

  (B) ext_full UND ext_p98 um denselben ABSOLUTEN Betrag kurz
      -> das ganze Objekt wird kleiner gemessen, kein Trunkierungsproblem.
         Ursache bei Massstab/Optik -> Punkte 1-2 der Sequenz (Kalibrierung,
         Marker-Auflage, Verzeichnung).

  (C) support_pos springt bei Tail-Bildern auf andere Konturstellen als beim
      Rest
      -> geometrische Instabilitaet des Extrempunkts. Dritter Fall, separat
         melden (nicht mit A/B vermengen).

KONTROLLE (Projektionsrechnung): Fuer den rundesten Artikel im Korpus muss
ext_full ~= circle_diameter_mm und ext_full / lat_p98 ~= 1 sein. Trifft das
nicht zu, stimmt die Projektionsrechnung — dann erst DAS klaeren, bevor die
Tail-Zahlen interpretiert werden.

SCHRITT 0 (Vorbedingung): Fuer jede Aufnahme wird geprueft, wie viele
Huellpunkte auf dem minEnclosingCircle liegen (Toleranz ~1 px) und ob
circle_diameter_mm == groesster paarweiser Huellpunktabstand gilt
(Zweipunkt-Fall). Trifft das nicht flaechendeckend zu, bricht das Skript VOR
der Interpretation ab — dann ist die Argumentation oben hinfaellig.
--------------------------------------------------------------------------

Aufruf:
    python scripts/tail_extent_check.py [--run-id NAME] [--workers N]
                                        [--sessions s1,s2] [--articles a1,a2]
                                        [--limit N] [--no-crops]
"""

from __future__ import annotations

import argparse
import atexit
import copy
import csv
import json
import shutil
import sqlite3
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import cv2
import numpy as np

PROJEKT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJEKT))

from docodetect.calibration import Calibration                       # noqa: E402
from docodetect.config import load_config                            # noqa: E402
from docodetect.corpus.bundle import bundle_cfg                      # noqa: E402
from docodetect.corpus.manifest import Manifest, corpus_root         # noqa: E402
from docodetect.matcher import MatchReport                           # noqa: E402
from docodetect.pipeline import measure_shot                         # noqa: E402
from docodetect.segmentation import SegmentationError                # noqa: E402

# ------------------------------------------------------------------ Konstanten
SUPPORT_TOL_PX = 1.0     # "auf dem Kreis": |dist(center) - radius| <= 1 px
TAIL_Z = 3.0             # Tail-Definition: |z_eigen| > 3 (Doc Abschnitt 5)
CROP = 200               # Kantenlaenge der 1:1-Crops in px (nicht skaliert)
HALF = CROP // 2
DENSIFY_STEP_PX = 1.0    # Bogenlaengen-Resampling fuer robuste Perzentile
# Gate: so hoch muss der Anteil der Zweipunkt-Faelle sein, damit die
# Argumentation "echter Rueckgang des max. Punktabstands" traegt.
TWO_POINT_GATE = 0.90
# KONTROLLE: erlaubte Abweichung von 1.0 fuer ext_full/circle_d und
# ext_full/lat_p98 beim rundesten Artikel.
ROUND_TOL = 0.05


# ============================================================ Geometrie-Helfer
def _densify(poly: np.ndarray, step: float = DENSIFY_STEP_PX) -> np.ndarray:
    """Geschlossenes Polygon bogenlaengen-gleichmaessig nachsamplen. Macht
    Perzentile (p1/p99 ...) und die PCA-Achse unabhaengig davon, dass
    CHAIN_APPROX_SIMPLE gerade Kanten auf ihre Endpunkte kollabiert. Die
    Eckpunkte bleiben enthalten, die Extrema aendern sich also nicht."""
    p = poly.astype(np.float64)
    n = len(p)
    out = []
    for i in range(n):
        a, b = p[i], p[(i + 1) % n]
        d = float(np.hypot(*(b - a)))
        k = max(1, int(d / step))
        for j in range(k):
            out.append(a + (b - a) * (j / k))
    return np.asarray(out, dtype=np.float64)


def _pca_axes(points: np.ndarray):
    """Haupt- und Nebenachse (Einheitsvektoren) plus Schwerpunkt aus der
    Kovarianz der Punkte. Hauptachse = groesste Varianz = Objektlaenge."""
    center = points.mean(axis=0)
    cov = np.cov((points - center).T)
    vals, vecs = np.linalg.eigh(cov)          # aufsteigend
    order = np.argsort(vals)[::-1]
    main = vecs[:, order[0]]
    minor = vecs[:, order[1]]
    return center, main / np.linalg.norm(main), minor / np.linalg.norm(minor)


def _circle_support(contour_i32: np.ndarray, tol: float = SUPPORT_TOL_PX):
    """minEnclosingCircle + die Huellpunkte, die (bis auf tol) auf ihm liegen.
    Liefert (center, radius, support_xy, n_support, maxdist_px). Erwartet die
    int32-Kontur — cv2.minEnclosingCircle/convexHull akzeptieren kein float64."""
    (cx, cy), radius = cv2.minEnclosingCircle(contour_i32)
    center = np.array([cx, cy], dtype=np.float64)
    hull = cv2.convexHull(contour_i32).reshape(-1, 2).astype(np.float64)
    d = np.hypot(hull[:, 0] - cx, hull[:, 1] - cy)
    on = hull[np.abs(d - radius) <= tol]
    # groesster paarweiser Huellpunktabstand (Durchmesser der Punktmenge)
    diffs = hull[:, None, :] - hull[None, :, :]
    maxdist = float(np.sqrt((diffs ** 2).sum(-1)).max())
    return center, float(radius), on, int(len(on)), maxdist


def _proj(points: np.ndarray, axis: np.ndarray) -> np.ndarray:
    """Skalarprojektion der Punkte auf eine Achse. Bewusst per einsum statt
    `points @ axis`: die (N,2)@(2,)-matmul loest auf manchen numpy/CPU-
    Kombinationen eine SPURIOSE 'divide by zero'-RuntimeWarning aus (Werte
    sind endlich und korrekt). einsum vermeidet den SIMD-Pfad."""
    return np.einsum("ij,j->i", points, axis)


def _pctl(a: np.ndarray, lo: float, hi: float) -> float:
    return float(np.percentile(a, hi) - np.percentile(a, lo))


def _load_ref_stats(db_path: Path) -> dict:
    """{article: (enroll_mean_diameter, enroll_std_diameter)} aus der
    reference_stats-Tabelle einer Bundle-DB (read-only). Leeres dict, wenn die
    DB fehlt (Tier-1-Sessions haben keine) — dann bleibt is_tail fuer diese
    Session unbestimmt.

    Die z_eigen-Definition der Analyse (Doc Abschnitt 5) misst gegen das
    Enrollment-MITTEL, nicht gegen den Report-Kandidaten. Genau darum ist die
    Bundle-DB die richtige Quelle: die extremsten Tail-Faelle wurden vom
    Geometrie-Vorfilter aus der Kandidatenliste geworfen (siehe Doc Abschnitt
    10, 'Vorfilter-Kills') — aus dem Report allein waeren sie unsichtbar,
    obwohl gerade sie die Ausreisser sind. mean/std sind ueber alle Bundles
    und die Live-DB identisch (sync aendert nur die articles-Nominale, nicht
    reference_stats)."""
    out: dict = {}
    if not db_path.is_file():
        return out
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        for art, sj in con.execute(
                "SELECT article_number, stats_json FROM reference_stats"):
            s = json.loads(sj)
            mu = s.get("scalar_mean", {}).get("diameter_mm")
            sd = s.get("scalar_std", {}).get("diameter_mm")
            if mu is not None:
                out[art] = (float(mu), float(sd) if sd is not None else None)
    except sqlite3.Error:
        return {}
    finally:
        con.close()
    return out


def _z(measured_diam, mu, sigma):
    """z_eigen = (gemessener Kreis-Ø - Enrollment-Mittel) / Enrollment-Std."""
    if measured_diam is None or mu is None or not sigma or sigma <= 0:
        return None
    return (float(measured_diam) - mu) / sigma


# ================================================================ Worker-Teil
# Ein Worker haelt seine Bundle-Configs und einen temporaeren DB-Ordner. Der
# DB-Pfad wird bewusst aus dem Bundle heraus in den Tempordner umgeleitet:
# Database.__init__ -> sqlite3.connect LEGT die Datei an, wenn sie fehlt, und
# Tier-1-Bundles haben per Konstruktion keine db.sqlite3. Ohne Umleitung
# schriebe der Lauf in den fingerprint-verifizierten Session-Zustand hinein.
_CTX: dict = {}


def _worker_init(cfg: dict, root_str: str) -> None:
    _CTX["cfg"] = cfg
    _CTX["root"] = Path(root_str)
    _CTX["bundles"] = {}
    d = tempfile.mkdtemp(prefix="tail-extent-")
    _CTX["tmpdir"] = d
    atexit.register(shutil.rmtree, d, True)


def _bundle_for(session: str):
    """(tier1_cfg, mm_per_px, ref_stats) je Session, einmal pro Worker
    gebaut. ref_stats stammt aus der Bundle-DB (leer bei Tier-1-Sessions)."""
    if session not in _CTX["bundles"]:
        bdir = _CTX["root"] / session / "bundle"
        bcfg = bundle_cfg(_CTX["cfg"], bdir)
        tcfg = copy.deepcopy(bcfg)
        tcfg.setdefault("paths", {})
        tcfg["paths"]["db_file"] = str(Path(_CTX["tmpdir"]) / f"{session}.sqlite3")
        cal = Calibration.load(bdir / "calibration.json")
        ref_stats = _load_ref_stats(bdir / "db.sqlite3")
        _CTX["bundles"][session] = (tcfg, float(cal.mm_per_px), ref_stats)
    return _CTX["bundles"][session]


def _measure_one(entry_dict: dict) -> dict:
    """Eine Aufnahme replayen und alle Extent-Groessen berechnen. Reine
    dicts als Rueckgabe (Prozessgrenze)."""
    rec: dict = {
        "sha": entry_dict.get("sha", "?"),
        "session": entry_dict.get("session", "?"),
        "article": entry_dict.get("article", "?"),
        "label": entry_dict.get("label"),
        "verdict": entry_dict.get("verdict"),
        "tier": entry_dict.get("tier"),
        "image_rel": entry_dict.get("image_rel"),
        "error": None,
    }
    try:
        root = _CTX["root"]
        tcfg, mmpp, ref_stats = _bundle_for(rec["session"])
        img = cv2.imread(str(root / entry_dict["image_rel"]))
        if img is None:
            rec["error"] = "Bild nicht lesbar"
            return rec

        # --- Kontur ueber den Tier-1-Replay-Pfad (keine neue Segmentierung) ---
        try:
            feats, seg = measure_shot(img, tcfg)
        except SegmentationError as exc:
            rec["error"] = f"SegmentationError: {exc}"
            return rec
        contour_i32 = seg.contour.reshape(-1, 2).astype(np.int32)
        contour = contour_i32.astype(np.float64)      # nur fuer numpy-Mathematik
        if len(contour) < 5:
            rec["error"] = "Kontur < 5 Punkte"
            return rec

        rec["circle_diameter_mm"] = float(feats.circle_diameter_mm)
        rec["aspect_ratio"] = float(feats.aspect_ratio)

        # --- Schritt 0: Stuetzpunkte / Zweipunkt-Pruefung ---
        center_c, radius, support_xy, n_support, maxdist_px = _circle_support(contour_i32)
        rec["n_support"] = n_support
        rec["maxdist_mm"] = round(maxdist_px * mmpp, 3)
        diam_from_circle_mm = 2.0 * radius * mmpp
        rec["diam_check_mm"] = round(diam_from_circle_mm, 3)
        # Reproduziert die frische Messung den gespeicherten Kreis-Ø?
        rec["diam_reproduces"] = abs(diam_from_circle_mm
                                     - feats.circle_diameter_mm) <= 0.01
        # Zweipunkt-Fall: Kreisdurchmesser == groesster Huellpunktabstand
        rec["two_point"] = abs(2.0 * radius - maxdist_px) <= SUPPORT_TOL_PX

        # --- PCA-Achsen (aus bogenlaengen-gleichmaessiger Kontur) ---
        dense = _densify(contour)
        center, main, minor = _pca_axes(dense)

        proj_main_orig = _proj(contour - center, main)   # exakte Extrema
        span = proj_main_orig.max() - proj_main_orig.min()
        rec["ext_full"] = round(span * mmpp, 3)

        proj_main = _proj(dense - center, main)
        proj_minor = _proj(dense - center, minor)
        rec["ext_p99"] = round(_pctl(proj_main, 0.5, 99.5) * mmpp, 3)
        rec["ext_p98"] = round(_pctl(proj_main, 1.0, 99.0) * mmpp, 3)
        rec["lat_p98"] = round(_pctl(proj_minor, 1.0, 99.0) * mmpp, 3)
        rec["ext_full_minus_ext_p98"] = round(rec["ext_full"] - rec["ext_p98"], 3)

        # Extrempunkte entlang der Hauptachse (die "Enden")
        lo_i = int(np.argmin(proj_main_orig))
        hi_i = int(np.argmax(proj_main_orig))
        rec["extreme_lo_xy"] = [float(contour[lo_i][0]), float(contour[lo_i][1])]
        rec["extreme_hi_xy"] = [float(contour[hi_i][0]), float(contour[hi_i][1])]

        # support_pos: Lage jedes Stuetzpunkts entlang der Hauptachse, [0,1]
        if n_support and span > 0:
            sp = _proj(support_xy - center, main)
            pos = (sp - proj_main_orig.min()) / span
            rec["support_pos"] = [round(float(v), 3) for v in pos]
            rec["support_xy"] = [[round(float(x), 1), round(float(y), 1)]
                                 for x, y in support_xy]
        else:
            rec["support_pos"] = []
            rec["support_xy"] = []

        rec["mm_per_px"] = round(mmpp, 6)
        # Kontur mitfuehren, damit die Crops keine zweite Segmentierung
        # brauchen (nur fuer die spaeter ausgewaehlten 16 wirklich genutzt).
        rec["contour"] = contour.astype(np.int32).tolist()

        # --- is_tail: z_eigen gegen Enrollment-Mittel/-Std (Bundle-DB) ---
        # Report-zeitlicher Mess-Ø aus dem Golden; mu/sigma aus reference_stats
        # (NICHT aus dem Kandidaten — der Vorfilter wirft gerade die Ausreisser
        # heraus, siehe _load_ref_stats).
        golden = MatchReport.from_json(
            (root / entry_dict["report_rel"]).read_text(encoding="utf-8"))
        gmeas = (golden.measured or {}).get("circle_diameter_mm")
        rec["circle_diameter_mm_golden"] = gmeas
        mu, sigma = ref_stats.get(rec["article"], (None, None))
        rec["mu_diam"] = round(mu, 3) if mu is not None else None
        rec["sigma_diam"] = round(sigma, 4) if sigma is not None else None
        z_g = _z(gmeas, mu, sigma)
        z_f = _z(rec["circle_diameter_mm"], mu, sigma)
        rec["z_eigen_golden"] = round(z_g, 3) if z_g is not None else None
        rec["z_eigen_fresh"] = round(z_f, 3) if z_f is not None else None
        rec["has_stats"] = mu is not None
        rec["is_tail"] = (z_g is not None and abs(z_g) > TAIL_Z)
    except Exception as exc:                                   # noqa: BLE001
        rec["error"] = f"{type(exc).__name__}: {exc}"
    return rec


# =============================================================== Auswertung
CSV_COLS = [
    "sha", "session", "article", "label", "verdict", "tier",
    "is_tail", "has_stats", "z_eigen_golden", "z_eigen_fresh",
    "circle_diameter_mm", "circle_diameter_mm_golden", "diam_reproduces",
    "n_support", "two_point", "maxdist_mm", "diam_check_mm",
    "ext_full", "ext_p99", "ext_p98", "lat_p98", "ext_full_minus_ext_p98",
    "aspect_ratio", "mu_diam", "sigma_diam",
    "support_pos", "support_xy", "mm_per_px", "error",
]


def _write_csv(path: Path, records: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(CSV_COLS)
        for r in records:
            row = []
            for c in CSV_COLS:
                v = r.get(c)
                if c == "support_pos":
                    v = ";".join(str(x) for x in (v or []))
                elif c == "support_xy":
                    v = "|".join(f"{x},{y}" for x, y in (v or []))
                row.append("" if v is None else v)
            w.writerow(row)


def _med_iqr(vals: list):
    a = np.asarray([v for v in vals if v is not None], dtype=float)
    if len(a) == 0:
        return None, None, None
    return (float(np.median(a)),
            float(np.percentile(a, 25)),
            float(np.percentile(a, 75)))


def _fmt(triplet) -> str:
    m, q1, q3 = triplet
    if m is None:
        return "     —"
    return f"{m:6.2f} [{q1:5.2f},{q3:5.2f}]"


def _valid(records: list) -> list:
    return [r for r in records if r.get("error") is None
            and r.get("ext_full") is not None]


# ------------------------------------------------------------------- Schritt 0
def _schritt0_gate(valid: list) -> bool:
    n = len(valid)
    two = sum(1 for r in valid if r.get("two_point"))
    n_support = [r.get("n_support", 0) for r in valid]
    repro = sum(1 for r in valid if r.get("diam_reproduces"))
    named = [r for r in valid if r["article"] != "_unbewertet"]
    with_stats = sum(1 for r in named if r.get("has_stats"))
    frac = two / n if n else 0.0
    print("\n=== SCHRITT 0 — Zweipunkt-Vorbedingung ===")
    print(f"  gueltige Aufnahmen:                     {n}")
    print(f"  Kreis-Ø == max. Huellpunktabstand:      {two}/{n}  ({frac:.1%})"
          f"   <- entscheidendes Kriterium")
    print(f"  n_support==2 (Info; Toleranz faengt    "
          f"{sum(1 for x in n_support if x == 2)}/{n}")
    print(f"    Randpunkte mit ein, median {int(np.median(n_support)) if n_support else 0})")
    print(f"  frische Messung reproduziert Kreis-Ø:   {repro}/{n}")
    print(f"  benannte Bilder mit Enrollment-Stats:   {with_stats}/{len(named)}"
          f"   (Rest: Tier-1-Session ohne Bundle-DB -> is_tail unbestimmt)")
    if frac < TWO_POINT_GATE:
        print("\n  *** STOPP ***")
        print("  Der Zweipunkt-Fall gilt NICHT flaechendeckend "
              f"(< {TWO_POINT_GATE:.0%}).")
        print("  Der maximale Punktabstand ist dann nicht die gemessene Groesse,")
        print("  und die gesamte Argumentation (echter Laengenrueckgang) ist")
        print("  hinfaellig. Interpretation abgebrochen; CSV wurde dennoch")
        print("  geschrieben. Zuerst diese Annahme klaeren.")
        return False
    print("  -> Vorbedingung erfuellt, Interpretation zulaessig.")
    return True


# ------------------------------------------------------------------- Kontrolle
def _kontrolle(valid: list) -> None:
    """Projektionsrechnung pruefen.

    Primaer: ext_full ~= circle_diameter_mm. Fuer eine Stadion-Form (Besteck)
    ist der Enclosing-Circle-Ø exakt die Laenge, ext_full muss ihn treffen.
    Dieser Test gilt IMMER und validiert die Hauptachsen-Projektion.

    Isotropie (ext_full/lat_p98 ~= 1) setzt einen RUNDEN Artikel voraus. Der
    Korpus ist reines Besteck (aspect ~0.2); ein runder Kontrollkoerper
    existiert nicht. Statt einer sinnlosen Isotropie-Pruefung wird die
    Nebenachse ueber die Stadion-Beziehung lat_p98 ~= aspect_ratio * ext_full
    validiert — das prueft die Nebenachsen-Projektion ohne runden Koerper."""
    by_art: dict = {}
    for r in valid:
        by_art.setdefault(r["article"], []).append(r)
    kandidaten = [(a, float(np.median([x["aspect_ratio"] for x in rs])), rs)
                  for a, rs in by_art.items()
                  if len(rs) >= 3 and a not in ("_unbewertet",)]
    print("\n=== KONTROLLE — Projektionsrechnung ===")
    if not kandidaten:
        print("  Kein Artikel mit >=3 Messungen gefunden — uebersprungen.")
        return
    art, asp, rs = max(kandidaten, key=lambda t: t[1])
    ext_full = float(np.median([x["ext_full"] for x in rs]))
    circ = float(np.median([x["circle_diameter_mm"] for x in rs]))
    lat = float(np.median([x["lat_p98"] for x in rs]))
    r_circ = ext_full / circ if circ else float("nan")
    print(f"  rundester Artikel: {art}  (median aspect_ratio {asp:.3f}, "
          f"n={len(rs)})")
    print(f"  ext_full={ext_full:.2f}  circle_diameter_mm={circ:.2f}  "
          f"lat_p98={lat:.2f}")
    print(f"  (1) ext_full/circle_d          = {r_circ:.3f}  (soll ~1)")
    ok = abs(r_circ - 1.0) <= ROUND_TOL
    if asp >= 0.80:
        r_iso = ext_full / lat if lat else float("nan")
        print(f"  (2) ext_full/lat_p98           = {r_iso:.3f}  (soll ~1, "
              f"runder Koerper)")
        ok = ok and abs(r_iso - 1.0) <= ROUND_TOL
    else:
        exp_lat = asp * ext_full
        r_lat = lat / exp_lat if exp_lat else float("nan")
        print(f"  (2) lat_p98/(aspect*ext_full)  = {r_lat:.3f}  (soll ~1; "
              f"kein runder Artikel im Korpus)")
        ok = ok and abs(r_lat - 1.0) <= 0.10
    if ok:
        print("  -> Projektionsrechnung plausibel.")
    else:
        print("  *** WARNUNG: Projektionsrechnung weicht ab. Erst DAS "
              "klaeren, bevor die Tail-Zahlen interpretiert werden. ***")


# ------------------------------------------------------------------- Schritt 2
def _schritt2_summary(valid: list) -> None:
    metrics = ["ext_full", "ext_p99", "ext_p98", "lat_p98",
               "ext_full_minus_ext_p98"]
    tail = [r for r in valid if r.get("is_tail")]
    rest = [r for r in valid if not r.get("is_tail")]
    signs = [r.get("z_eigen_golden") for r in tail if r.get("z_eigen_golden") is not None]
    neg = sum(1 for z in signs if z < 0)
    print("\n=== SCHRITT 2 — Extent-Median [IQR], Tail vs. Rest ===")
    print(f"  Tail-Aufnahmen (|z_eigen|>{TAIL_Z:.0f}): {len(tail)}  "
          f"(negativ {neg}, positiv {len(signs) - neg})   Rest: {len(rest)}")
    print(f"  {'metric':<24}{'TAIL':>22}{'REST':>22}")
    for m in metrics:
        tval = _med_iqr([r.get(m) for r in tail])
        rval = _med_iqr([r.get(m) for r in rest])
        print(f"  {m:<24}{_fmt(tval):>22}{_fmt(rval):>22}")

    # pro Artikel, nur Artikel mit mindestens einem Tail-Mitglied
    arts = sorted({r["article"] for r in tail})
    print("\n  --- pro Artikel (nur Artikel mit Tail-Mitglied) ---")
    for a in arts:
        at = [r for r in tail if r["article"] == a]
        ar = [r for r in rest if r["article"] == a]
        print(f"\n  Artikel {a}   Tail n={len(at)}  Rest n={len(ar)}")
        print(f"    {'metric':<24}{'TAIL':>22}{'REST':>22}")
        for m in metrics:
            print(f"    {m:<24}"
                  f"{_fmt(_med_iqr([r.get(m) for r in at])):>22}"
                  f"{_fmt(_med_iqr([r.get(m) for r in ar])):>22}")
    print("\n  Lesart: (A) Trunkierung -> ext_full kurz, ext_p98 normal, "
          "(ext_full-ext_p98) bei Tail kleiner.")
    print("          (B) Massstab    -> ext_full UND ext_p98 gleich viel "
          "kuerzer (absolut).")
    print("          (C) Instabil    -> support_pos springt (CSV-Spalte).")


# ------------------------------------------------------------------- Schritt 3
def _pick_controls(valid: list, tails: list) -> list:
    """Je Tail eine artikelgleiche Nicht-Tail-Kontrolle, repraesentativ
    (ext_full am naechsten zum Nicht-Tail-Median des Artikels), moeglichst
    ohne Wiederholung."""
    used = set()
    controls = []
    for t in tails:
        base = [r for r in valid
                if r["article"] == t["article"] and not r.get("is_tail")
                and r["sha"] not in used]
        # gleiche Session bevorzugen (Session-Bulk-Offset nicht mit dem
        # Tail-Effekt vermengen); sonst artikelgleich aus anderer Session.
        pool = [r for r in base if r["session"] == t["session"]] or base
        if not pool:
            controls.append(None)
            continue
        med = float(np.median([r["ext_full"] for r in pool]))
        pick = min(pool, key=lambda r: abs(r["ext_full"] - med))
        used.add(pick["sha"])
        controls.append(pick)
    return controls


def _crop(img: np.ndarray, contour: np.ndarray, center_xy, out: Path) -> None:
    """200x200-Ausschnitt in Originalaufloesung um center_xy, Kontur
    eingezeichnet, NICHT skaliert. Randnahe Fenster werden schwarz gepolstert,
    damit die Kachel exakt 200x200 bleibt."""
    H, W = img.shape[:2]
    cx, cy = int(round(center_xy[0])), int(round(center_xy[1]))
    x0, y0 = cx - HALF, cy - HALF
    canvas = np.zeros((CROP, CROP, 3), dtype=np.uint8)
    sx0, sy0 = max(0, x0), max(0, y0)
    sx1, sy1 = min(W, x0 + CROP), min(H, y0 + CROP)
    if sx1 > sx0 and sy1 > sy0:
        canvas[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0] = img[sy0:sy1, sx0:sx1]
    pts = (contour - np.array([x0, y0])).astype(np.int32).reshape(-1, 1, 2)
    cv2.polylines(canvas, [pts], True, (0, 255, 0), 1)
    cv2.circle(canvas, (cx - x0, cy - y0), 3, (0, 0, 255), 1)
    cv2.imwrite(str(out), canvas)


def _schritt3_crops(root: Path, out_dir: Path, valid: list) -> int:
    tails = [r for r in valid if r.get("is_tail")]
    controls = _pick_controls(valid, tails)
    crop_dir = out_dir / "crops"
    # Vorherige Crops (z. B. aus einem frueheren Lauf mit derselben run-id)
    # entfernen, sonst mischen sich verwaiste PNGs mit dem aktuellen Satz.
    if crop_dir.exists():
        shutil.rmtree(crop_dir)
    crop_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for rank, (t, c) in enumerate(zip(tails, controls), 1):
        for kind, rec in (("tail", t), ("ctrl", c)):
            if rec is None:
                continue
            img = cv2.imread(str(root / rec["image_rel"]))
            if img is None:
                continue
            contour = np.asarray(rec["contour"], dtype=np.int32)
            base = (f"{rank:02d}_{kind}_{rec['article']}_{rec['session']}"
                    f"_{str(rec['sha'])[:8]}")
            _crop(img, contour, rec["extreme_lo_xy"],
                  crop_dir / f"{base}_end_lo.png")
            _crop(img, contour, rec["extreme_hi_xy"],
                  crop_dir / f"{base}_end_hi.png")
            n += 2
    return n


# ==================================================================== main
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-id", default=time.strftime("%Y%m%d-%H%M%S"))
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--sessions", default=None,
                    help="Kommagetrennt: nur diese Sessions")
    ap.add_argument("--articles", default=None,
                    help="Kommagetrennt: nur diese Artikel")
    ap.add_argument("--limit", type=int, default=None,
                    help="nur die ersten N Aufnahmen (Test)")
    ap.add_argument("--no-crops", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    root = corpus_root(cfg)
    if not root.exists():
        print(f"Korpus-Verzeichnis fehlt: {root}", file=sys.stderr)
        return 2
    manifest = Manifest.load()
    if not manifest.images:
        print("Korpus-Manifest ist leer.", file=sys.stderr)
        return 2

    # ALLE Bilder ueber den Tier-1-Replay-Pfad (nicht nur die 8). Sortiert
    # wie der Runner, damit --limit stabil denselben Ausschnitt trifft.
    images = sorted(manifest.images, key=lambda e: (e.session, e.sha))
    if args.sessions:
        s = set(args.sessions.split(","))
        images = [e for e in images if e.session in s]
    if args.articles:
        a = set(args.articles.split(","))
        images = [e for e in images if e.article in a]
    if args.limit:
        images = images[:args.limit]
    if not images:
        print("Auswahl trifft kein Bild.", file=sys.stderr)
        return 2

    out_dir = PROJEKT / "reports" / "analysis" / args.run_id
    print(f"tail_extent_check — {len(images)} Aufnahmen, {args.workers} Worker")
    print(f"Korpus: {root}")
    print(f"Ausgabe: {out_dir}")

    from dataclasses import asdict
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=args.workers, initializer=_worker_init,
                             initargs=(cfg, str(root))) as ex:
        records = list(ex.map(_measure_one, [asdict(e) for e in images],
                              chunksize=1))
    dauer = time.time() - t0
    errs = [r for r in records if r.get("error")]
    print(f"gemessen in {dauer:.0f}s "
          f"({len(images) / dauer:.2f} Bilder/s), Fehler: {len(errs)}")
    for r in errs[:12]:
        print(f"  ! {r['session']}/{str(r['sha'])[:8]} {r['article']}: {r['error']}")

    csv_path = out_dir / "tail_extent.csv"
    _write_csv(csv_path, records)
    print(f"CSV: {csv_path}")

    valid = _valid(records)
    if not valid:
        print("Keine gueltige Messung — Abbruch.", file=sys.stderr)
        return 2

    gate_ok = _schritt0_gate(valid)
    _kontrolle(valid)
    if not gate_ok:
        return 2

    _schritt2_summary(valid)

    if not args.no_crops:
        n_crops = _schritt3_crops(root, out_dir, valid)
        print(f"\n=== SCHRITT 3 — Crops ===")
        print(f"  {n_crops} PNG(s) (200x200, 1:1) -> {out_dir / 'crops'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
