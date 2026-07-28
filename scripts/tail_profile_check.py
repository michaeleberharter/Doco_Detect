#!/usr/bin/env python3
"""tail_profile_check.py — Wo entlang der Objektachse geht das Tail-Defizit
verloren? (read-only Diagnose)

Ausgangslage (C3): der Tail ist ein echtes Phaenomen, aber nur fuer die
harten Faelle — LOEFFEL-6, LOEFFEL-2, GABEL-1, LOEFFEL-3 und (grenzwertig)
LOEFFEL-7. LOEFFEL-4-b und LOEFFEL-12 sind vom Bulk nicht trennbar und
laufen hier als KONTROLLE, nicht als Fall. Zu klaeren: sitzt das ~5,5-mm-
Defizit an einem Ende (Trunkierung) oder verteilt es sich ueber die ganze
Laenge (echte Skalenverkuerzung)?

Methode: je Bild das Breitenprofil w(s) = Ausdehnung senkrecht zur PCA-
Hauptachse auf 1-mm-Raster. Landmarken, die von KEINEM Endpunkt definiert
sind (also gegen Endverlust immun):
  s_wmax  globales Breitenmaximum (Laffe / Zinkenblatt)
  s_wmin  Breitenminimum zwischen s_wmax und dem fernen Ende (Hals)
Zerlegung der Laenge in drei Strecken, Summe == ext_full:
  d_bowl   Laffenspitze -> s_wmax        (nahes Ende bis Breitenmax)
  d_mid    s_wmax -> s_wmin              (rein intern, endpunktfrei)
  d_handle s_wmin -> Stielende           (Hals bis fernes Ende)
Weil das Gesamtdefizit additiv in d_bowl+d_mid+d_handle zerfaellt, zeigt der
Anteil je Strecke, WO die Laenge fehlt.

Read-only: kein Messpfad-Eingriff, keine Schwellen, keine DB-Schreibzugriffe,
keine Schreibzugriffe nach corpus/. Kontur ueber den bekannten Tier-1-Replay
(bundle_cfg + measure_shot). Ausgabe nur nach reports/analysis/<run-id>/.

--------------------------------------------------------------------------
KONTROLLE VOR DER INTERPRETATION (hart): ueber die sauberen Gruppen (kein
Tail, n>=4) muss die Within-Group-Streuung von d_mid < 0,5 mm liegen — sonst
kann eine Landmarke mit 1-mm-Jitter die 5,5 mm nicht aufloesen. Haelt d_mid
die Schwelle nicht, wird geprueft, ob s_half (erste 50-%-Unterschreitung von
w_max Richtung fernes Ende) stabiler ist; erst wenn EINE Landmarke haelt,
wird ausgewertet.

ENTSCHEIDUNGSREGEL
  Defizit in d_bowl ODER d_handle, d_mid normal
      -> lokalisierter Endverlust; _snap_contour_to_edges wieder verdaechtig.
  Defizit anteilig auf alle drei Strecken
      -> echte Skalenverkuerzung, kein Endproblem.
  Defizit in d_mid, Enden normal
      -> unerwartet, eigenstaendig erklaerungsbeduerftig (getrennt melden).
--------------------------------------------------------------------------
"""

from __future__ import annotations

import argparse
import atexit
import copy
import csv
import json
import math
import shutil
import sqlite3
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
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

# Harte Faelle (C3): sha -> (Artikel, grenzwertig?). Die zwei Kontroll-Tails
# LOEFFEL-4-b (d78cbe71) und LOEFFEL-12 (957a3f77) stehen hier BEWUSST nicht —
# sie sind vom Bulk nicht trennbar und dienen nur als Kontrolle.
HARTE_FAELLE = {
    "cc1f627e": ("LOEFFEL-6", False),
    "b26a6160": ("LOEFFEL-2", False),
    "5bf6b431": ("GABEL-1", False),
    "4587d1a8": ("LOEFFEL-3", False),
    "8dc74a45": ("LOEFFEL-7", True),   # grenzwertig
}

TAIL_Z = 3.0
DMID_GATE = 0.5          # mm: max. tolerierbare d_mid-Streuung sauberer Gruppen
CROP = 200
HALF = CROP // 2
DENSIFY_STEP_PX = 0.5    # feiner als extent-check, damit 1-mm-Bins gefuellt sind


# ============================================================ Geometrie-Helfer
def _densify(poly: np.ndarray, step: float = DENSIFY_STEP_PX) -> np.ndarray:
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
    center = points.mean(axis=0)
    cov = np.cov((points - center).T)
    vals, vecs = np.linalg.eigh(cov)
    order = np.argsort(vals)[::-1]
    main = vecs[:, order[0]]
    minor = vecs[:, order[1]]
    return center, main / np.linalg.norm(main), minor / np.linalg.norm(minor)


def _proj(points: np.ndarray, axis: np.ndarray) -> np.ndarray:
    # einsum statt @, um die spuriose matmul-RuntimeWarning zu vermeiden
    return np.einsum("ij,j->i", points, axis)


def _profile(contour_i32: np.ndarray, mmpp: float):
    """Breitenprofil + Landmarken + Drei-Strecken-Zerlegung. None bei
    zu duennem Profil."""
    contour = contour_i32.astype(np.float64)
    dense = _densify(contour)
    c, u, v = _pca_axes(dense)

    t_orig = _proj(contour - c, u)                 # px, echte Extrempunkte
    s_dense = (_proj(dense - c, u) - _proj(dense - c, u).min()) * mmpp
    m_dense = _proj(dense - c, v) * mmpp
    L = float(s_dense.max())
    nb = int(math.floor(L)) + 1
    if nb < 5:
        return None

    # w(s) je 1-mm-Bin = Ausdehnung senkrecht zur Hauptachse
    w = np.full(nb, np.nan)
    binidx = np.clip(np.floor(s_dense).astype(int), 0, nb - 1)
    for b in range(nb):
        sel = binidx == b
        if sel.sum() >= 2:
            w[b] = m_dense[sel].max() - m_dense[sel].min()
    ii = np.arange(nb)
    good = ~np.isnan(w)
    if good.sum() < 3:
        return None
    w = np.interp(ii, ii[good], w[good])
    ws = np.convolve(w, np.ones(3) / 3.0, mode="same")   # leichte Glaettung

    i_wmax = int(np.argmax(ws))
    s_wmax = i_wmax + 0.5
    w_max = float(ws[i_wmax])
    near0 = s_wmax <= L / 2.0                      # Laffe am unteren Ende?
    if near0:
        i_wmin = i_wmax + int(np.argmin(ws[i_wmax:]))
    else:
        i_wmin = int(np.argmin(ws[:i_wmax + 1]))
    s_wmin = i_wmin + 0.5
    w_neck = float(ws[i_wmin])

    near_end = 0.0 if near0 else L
    far_end = L if near0 else 0.0
    d_bowl = abs(s_wmax - near_end)
    d_mid = abs(s_wmin - s_wmax)
    d_handle = abs(far_end - s_wmin)

    # s_half: von s_wmax Richtung fernes Ende erste 50-%-Unterschreitung
    half = 0.5 * w_max
    s_half = None
    if near0:
        for i in range(i_wmax, nb):
            if ws[i] < half:
                if i > i_wmax:
                    x0, x1 = ws[i - 1], ws[i]
                    frac = (x0 - half) / (x0 - x1) if x0 != x1 else 0.0
                    s_half = (i - 1 + 0.5) + frac
                else:
                    s_half = i + 0.5
                break
    else:
        for i in range(i_wmax, -1, -1):
            if ws[i] < half:
                if i < i_wmax:
                    x0, x1 = ws[i + 1], ws[i]
                    frac = (x0 - half) / (x0 - x1) if x0 != x1 else 0.0
                    s_half = (i + 1 + 0.5) - frac
                else:
                    s_half = i + 0.5
                break
    bowl_half_len = abs((s_half if s_half is not None else s_wmax) - near_end)

    lo_i, hi_i = int(np.argmin(t_orig)), int(np.argmax(t_orig))
    bowl_xy = contour[lo_i] if near0 else contour[hi_i]    # Laffenspitze
    handle_xy = contour[hi_i] if near0 else contour[lo_i]  # Stielende

    return dict(
        ext_full=round(L, 3), d_bowl=round(d_bowl, 3), d_mid=round(d_mid, 3),
        d_handle=round(d_handle, 3), w_max=round(w_max, 3),
        w_neck=round(w_neck, 3),
        s_half=round(float(s_half), 3) if s_half is not None else None,
        bowl_half_len=round(bowl_half_len, 3),
        sum_dev=round((d_bowl + d_mid + d_handle) - L, 4),
        bowl_xy=[round(float(bowl_xy[0]), 1), round(float(bowl_xy[1]), 1)],
        handle_xy=[round(float(handle_xy[0]), 1), round(float(handle_xy[1]), 1)],
    )


def _load_ref_stats(db_path: Path) -> dict:
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


# ================================================================ Worker
_CTX: dict = {}


def _worker_init(cfg: dict, root_str: str) -> None:
    _CTX["cfg"] = cfg
    _CTX["root"] = Path(root_str)
    _CTX["bundles"] = {}
    d = tempfile.mkdtemp(prefix="tail-profile-")
    _CTX["tmpdir"] = d
    atexit.register(shutil.rmtree, d, True)


def _bundle_for(session: str):
    if session not in _CTX["bundles"]:
        bdir = _CTX["root"] / session / "bundle"
        bcfg = bundle_cfg(_CTX["cfg"], bdir)
        tcfg = copy.deepcopy(bcfg)
        tcfg.setdefault("paths", {})
        tcfg["paths"]["db_file"] = str(Path(_CTX["tmpdir"]) / f"{session}.sqlite3")
        cal = Calibration.load(bdir / "calibration.json")
        _CTX["bundles"][session] = (tcfg, float(cal.mm_per_px),
                                    _load_ref_stats(bdir / "db.sqlite3"))
    return _CTX["bundles"][session]


def _measure_one(entry_dict: dict) -> dict:
    rec: dict = {
        "sha": entry_dict.get("sha", "?"),
        "session": entry_dict.get("session", "?"),
        "article": entry_dict.get("article", "?"),
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
        try:
            feats, seg = measure_shot(img, tcfg)
        except SegmentationError as exc:
            rec["error"] = f"SegmentationError: {exc}"
            return rec
        contour_i32 = seg.contour.reshape(-1, 2).astype(np.int32)
        if len(contour_i32) < 5:
            rec["error"] = "Kontur < 5 Punkte"
            return rec

        prof = _profile(contour_i32, mmpp)
        if prof is None:
            rec["error"] = "Profil zu duenn"
            return rec
        rec.update(prof)
        rec["mm_per_px"] = round(mmpp, 6)
        rec["contour"] = contour_i32.tolist()

        # is_tail (Enrollment-Stats aus Bundle-DB, wie extent-check)
        golden = MatchReport.from_json(
            (root / entry_dict["report_rel"]).read_text(encoding="utf-8"))
        gmeas = (golden.measured or {}).get("circle_diameter_mm")
        mu, sigma = ref_stats.get(rec["article"], (None, None))
        rec["has_stats"] = mu is not None
        if gmeas is not None and mu is not None and sigma:
            z = (float(gmeas) - mu) / sigma
            rec["z_eigen"] = round(z, 3)
            rec["is_tail"] = abs(z) > TAIL_Z
        else:
            rec["z_eigen"] = None
            rec["is_tail"] = False
    except Exception as exc:                                # noqa: BLE001
        rec["error"] = f"{type(exc).__name__}: {exc}"
    return rec


# =============================================================== Auswertung
CSV_COLS = ["sha", "session", "article", "is_tail", "has_stats", "z_eigen",
            "ext_full", "d_bowl", "d_mid", "d_handle", "w_max", "w_neck",
            "s_half", "bowl_half_len", "sum_dev", "mm_per_px", "error"]


def _write_csv(path: Path, records: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(CSV_COLS)
        for r in records:
            w.writerow(["" if r.get(c) is None else r.get(c) for c in CSV_COLS])


def _valid(records: list) -> list:
    return [r for r in records if r.get("error") is None
            and r.get("ext_full") is not None]


def _groups(valid: list) -> dict:
    g: dict = {}
    for r in valid:
        g.setdefault((r["article"], r["session"]), []).append(r)
    return g


# ---------------------------------------------------------------- Kontrolle
def _gate(valid: list) -> tuple[bool, bool]:
    """Streuung von d_mid und bowl_half_len (s_half) ueber SAUBERE Gruppen
    (kein Tail, n>=4). Rueckgabe (d_mid_haelt, s_half_haelt)."""
    g = _groups(valid)
    clean = {k: v for k, v in g.items()
             if len(v) >= 4 and not any(r["is_tail"] for r in v)}
    print("\n=== KONTROLLE — Landmarken-Stabilitaet (saubere Gruppen n>=4) ===")
    if not clean:
        print("  Keine saubere Gruppe n>=4 — Gate nicht pruefbar.")
        return False, False
    dmid_std, half_std = [], []
    for k, v in sorted(clean.items()):
        dm = np.std([r["d_mid"] for r in v], ddof=1)
        bh = np.std([r["bowl_half_len"] for r in v], ddof=1)
        dmid_std.append(dm)
        half_std.append(bh)
    dmid_std = np.array(dmid_std)
    half_std = np.array(half_std)
    print(f"  {len(clean)} saubere Gruppen.  Schwelle < {DMID_GATE} mm")
    print(f"  d_mid-Streuung:        median {np.median(dmid_std):.2f}  "
          f"max {dmid_std.max():.2f}  "
          f"Gruppen<{DMID_GATE}: {int((dmid_std < DMID_GATE).sum())}/{len(clean)}")
    print(f"  bowl_half_len (s_half): median {np.median(half_std):.2f}  "
          f"max {half_std.max():.2f}  "
          f"Gruppen<{DMID_GATE}: {int((half_std < DMID_GATE).sum())}/{len(clean)}")
    dmid_ok = np.median(dmid_std) < DMID_GATE
    half_ok = np.median(half_std) < DMID_GATE
    if dmid_ok:
        print("  -> d_mid haelt die Schwelle: Drei-Strecken-Zerlegung zulaessig.")
    elif half_ok:
        print("  -> d_mid zu jittrig, ABER s_half haelt: Auswertung ueber "
              "s_half (Laffe-vorne vs. Rest).")
    else:
        print("  *** WEDER d_mid NOCH s_half halten < 0,5 mm — keine Landmarke")
        print("      loest 5,5 mm auf. Interpretation blockiert. ***")
    return dmid_ok, half_ok


# ---------------------------------------------------------------- Analyse
def _hard_cases(valid: list) -> list:
    return [r for r in valid if str(r["sha"])[:8] in HARTE_FAELLE]


def _ws_rest(valid: list, article: str, session: str) -> list:
    return [r for r in valid if r["article"] == article
            and r["session"] == session and not r["is_tail"]]


def _analyse(valid: list, use_dmid: bool, use_half: bool) -> list:
    """Je harter Fall: Teilstrecken-Defizit gegen Within-Session-Median.
    Rueckgabe je Fall dict mit Defizitanteilen + Crop-Ende."""
    print("\n=== AUSWERTUNG — Teilstrecken-Defizit (within-session) ===")
    if use_dmid:
        segs = ["d_bowl", "d_mid", "d_handle"]
        print("  Zerlegung: d_bowl (Laffenspitze->Breitenmax) | d_mid (intern) "
              "| d_handle (Hals->Stielende)")
    elif use_half:
        segs = ["bowl_front", "rest"]
        print("  Fallback ueber s_half: bowl_front (Laffenspitze->s_half) | "
              "rest (s_half->Stielende)")
    else:
        print("  Keine tragende Landmarke — Auswertung uebersprungen.")
        return []
    out = []
    for r in sorted(_hard_cases(valid),
                    key=lambda r: HARTE_FAELLE[str(r["sha"])[:8]][0]):
        a, s = r["article"], r["session"]
        rest = _ws_rest(valid, a, s)
        art, grenz = HARTE_FAELLE[str(r["sha"])[:8]]
        if len(rest) < 3:
            print(f"\n  {art:<10} {s:<9} {str(r['sha'])[:8]}  Rest n={len(rest)} "
                  f"(<3) — nicht auswertbar")
            continue

        def cur(rec, seg):
            if seg == "bowl_front":
                return rec["bowl_half_len"]
            if seg == "rest":
                return rec["ext_full"] - rec["bowl_half_len"]
            return rec[seg]

        tot_def = float(np.median([x["ext_full"] for x in rest])) - r["ext_full"]
        print(f"\n  {art}{' (grenzw.)' if grenz else ''}  {s}  {str(r['sha'])[:8]}"
              f"   Rest n={len(rest)}   Gesamtdefizit ext_full = {tot_def:+.2f} mm")
        print(f"    {'Strecke':<12}{'Fall':>8}{'RestMed':>9}{'Δmm':>8}{'%Gesamt':>9}")
        seg_def = {}
        for seg in segs:
            med = float(np.median([cur(x, seg) for x in rest]))
            dv = med - cur(r, seg)
            seg_def[seg] = dv
            pct = 100 * dv / tot_def if abs(tot_def) > 1e-6 else float("nan")
            print(f"    {seg:<12}{cur(r, seg):>8.2f}{med:>9.2f}{dv:>8.2f}{pct:>8.1f}%")
        # Crop-Ende: groesstes End-Segment-Defizit
        end_seg = max((s for s in seg_def if s in ("d_bowl", "d_handle",
                       "bowl_front", "rest")), key=lambda s: seg_def[s],
                      default=None)
        crop_end = "bowl" if end_seg in ("d_bowl", "bowl_front") else "handle"
        out.append({"rec": r, "seg_def": seg_def, "tot_def": tot_def,
                    "crop_end": crop_end, "art": art})
    # Aggregat-Urteil
    print("\n  --- Entscheidungsregel ---")
    if use_dmid:
        for o in out:
            sd = o["seg_def"]
            frac = {k: (100 * sd[k] / o["tot_def"] if abs(o["tot_def"]) > 1e-6
                        else float("nan")) for k in sd}
            enden = frac["d_bowl"] + frac["d_handle"]
            mid = frac["d_mid"]
            if mid < 20 and enden > 70:
                urteil = "ENDVERLUST (d_mid normal)"
            elif 20 <= mid <= 45:
                urteil = "anteilig verteilt (Skalenverkuerzung)"
            elif mid > 55:
                urteil = "*** d_mid dominiert — unerwartet ***"
            else:
                urteil = "gemischt"
            print(f"    {o['art']:<10} d_bowl {frac['d_bowl']:.0f}% | "
                  f"d_mid {frac['d_mid']:.0f}% | d_handle {frac['d_handle']:.0f}%"
                  f"  -> {urteil}")
    return out


# ---------------------------------------------------------------- Crops
def _crop(img, contour, center_xy, out: Path) -> None:
    H, W = img.shape[:2]
    cx, cy = int(round(center_xy[0])), int(round(center_xy[1]))
    x0, y0 = cx - HALF, cy - HALF
    canvas = np.zeros((CROP, CROP, 3), dtype=np.uint8)
    sx0, sy0 = max(0, x0), max(0, y0)
    sx1, sy1 = min(W, x0 + CROP), min(H, y0 + CROP)
    if sx1 > sx0 and sy1 > sy0:
        canvas[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0] = img[sy0:sy1, sx0:sx1]
    pts = (np.asarray(contour) - np.array([x0, y0])).astype(np.int32).reshape(-1, 1, 2)
    cv2.polylines(canvas, [pts], True, (0, 255, 0), 1)
    cv2.circle(canvas, (cx - x0, cy - y0), 3, (0, 0, 255), 1)
    cv2.imwrite(str(out), canvas)


def _crops(root: Path, out_dir: Path, valid: list, analyse: list) -> int:
    crop_dir = out_dir / "crops"
    if crop_dir.exists():
        shutil.rmtree(crop_dir)
    crop_dir.mkdir(parents=True, exist_ok=True)
    by_sha = {str(r["sha"]): r for r in valid}
    n = 0
    for o in analyse:
        case = o["rec"]
        a, s = case["article"], case["session"]
        end_xy_key = "bowl_xy" if o["crop_end"] == "bowl" else "handle_xy"
        # Kontrolle: gleicher Artikel/Session, kein Tail, repraesentativ
        pool = [r for r in _ws_rest(valid, a, s) if str(r["sha"]) != str(case["sha"])]
        ctrl = None
        if pool:
            med = float(np.median([r["ext_full"] for r in pool]))
            ctrl = min(pool, key=lambda r: abs(r["ext_full"] - med))
        for kind, rec in (("case", case), ("ctrl", ctrl)):
            if rec is None:
                continue
            img = cv2.imread(str(root / rec["image_rel"]))
            if img is None:
                continue
            base = f"{o['art']}_{s}_{kind}_{str(rec['sha'])[:8]}_{o['crop_end']}"
            _crop(img, rec["contour"], rec[end_xy_key], crop_dir / f"{base}.png")
            n += 1
    return n


# ==================================================================== main
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-id", default="tail-profile-" + time.strftime("%Y%m%d-%H%M%S"))
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--no-crops", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    root = corpus_root(cfg)
    if not root.exists():
        print(f"Korpus-Verzeichnis fehlt: {root}", file=sys.stderr)
        return 2
    manifest = Manifest.load()
    images = sorted(manifest.images, key=lambda e: (e.session, e.sha))
    if args.limit:
        images = images[:args.limit]
    if not images:
        print("Kein Bild.", file=sys.stderr)
        return 2

    out_dir = PROJEKT / "reports" / "analysis" / args.run_id
    print(f"tail_profile_check — {len(images)} Aufnahmen, {args.workers} Worker")
    print(f"Ausgabe: {out_dir}")

    t0 = time.time()
    with ProcessPoolExecutor(max_workers=args.workers, initializer=_worker_init,
                             initargs=(cfg, str(root))) as ex:
        records = list(ex.map(_measure_one, [asdict(e) for e in images],
                              chunksize=1))
    dauer = time.time() - t0
    errs = [r for r in records if r.get("error")]
    print(f"gemessen in {dauer:.0f}s, Fehler: {len(errs)}")

    _write_csv(out_dir / "tail_profile.csv", records)
    print(f"CSV: {out_dir / 'tail_profile.csv'}")

    valid = _valid(records)
    if not valid:
        print("Keine gueltige Messung.", file=sys.stderr)
        return 2

    # sum_dev-Sanity: Zerlegung muss ext_full ergeben
    max_dev = max(abs(r["sum_dev"]) for r in valid)
    print(f"\nSumme d_bowl+d_mid+d_handle vs ext_full: max Abweichung "
          f"{max_dev:.4f} mm ({len(valid)} Bilder)")

    dmid_ok, half_ok = _gate(valid)
    analyse = _analyse(valid, dmid_ok, half_ok)

    if not args.no_crops and analyse:
        n = _crops(root, out_dir, valid, analyse)
        print(f"\n=== CROPS === {n} PNG(s) (200x200, 1:1) -> {out_dir / 'crops'}")
    return 0 if (dmid_ok or half_ok) else 2


if __name__ == "__main__":
    raise SystemExit(main())
