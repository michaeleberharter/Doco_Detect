#!/usr/bin/env python3
"""tail_overlay_check.py — Wo sitzt das Tail-Defizit? Starre Ueberlagerung
statt Landmarken. (read-only)

VERDIKT (2026-07-28): Ansatz GESCHEITERT am ~1-mm-Silhouetten-Rauschboden.
Die starre Schwerpunkt-/PCA-Ausrichtung hat ~1 mm axialen Restfehler, ueber
die steilen Profilgradienten zu 2-9 mm Schein-Defizit verstaerkt — so gross
wie das Signal selbst. Der Kontroll-Durchlauf (Referenz gegen Referenz) faellt
in ALLEN Gruppen durch (paarweise = vs-Mean, also fundamental, keine
Mittelungs-Unschaerfe). NICHT erneut versuchen, bevor der Rauschboden am Rig
bekannt/gesenkt ist. Die Vorzeichenstruktur (woelben, C5b) ist rauschbodenfrei
und traegt — der Betrag/die Lokalisierung nicht.

C2 ist am Landmarkenrauschen gescheitert (Taille/s_half zu jittrig). C4 misst
stattdessen ein Differenzmass, das ueber die GANZE Kontur mittelt: Tail-Kontur
gegen die gemittelte Referenz desselben Artikels/derselben Session, starr auf
Schwerpunkt + PCA-Hauptachse ausgerichtet (KEINE elastische Registrierung).

Je hartem Fall (LOEFFEL-6, -2, -3, GABEL-1, LOEFFEL-7):
  Referenz  = alle Nicht-Tail-Bilder desselben Artikels/derselben Session,
              zum mittleren Breitenprofil gemittelt.
  Kontrolle = jedes Referenzbild leave-one-out gegen die uebrigen — dieselbe
              Prozedur, damit der Rauschboden der Methode selbst sichtbar wird.

Messgroesse: halbe Breite W+(s), W-(s) senkrecht zur Achse auf 1-mm-Raster,
Achse auf den Schwerpunkt zentriert, Vorzeichen ueber das Breitenmaximum
(Laffe an das negative Ende). Differenz D(s) = W_ref(s) - W_tail(s); das
Integral ueber D ist die fehlende Flaeche, geteilt durch die mittlere Breite
ergibt ein LAENGEN-Defizit in mm. Kumuliert ueber s zeigt der Sprung, WO die
Laenge fehlt.

VORBEDINGUNG (statt der gescheiterten 0,5-mm-Gates): der Kontroll-Durchlauf
muss ein Gesamtdefizit nahe null liefern (|Median| deutlich < 2 mm). Sonst ist
die Ausrichtung selbst das Problem -> melden, nicht interpretieren.

ENTSCHEIDUNGSREGEL
  Defizit in den ersten/letzten 10 mm konzentriert, Rumpf flach, Kontrollen
    unauffaellig  -> Endverlust (Codestelle _snap_contour_to_edges).
  Defizit ueber die ganze Laenge verteilt  -> Optik/Massstab/Box.
  Kontrollen zeigen aehnliche Ausschlaege wie die Tails  -> Methode traegt
    nicht, kein Ergebnis.

Read-only: kein Messpfad-Eingriff, keine Schwellen, keine Schreibzugriffe nach
corpus/. Ausgabe nur nach reports/analysis/<run-id>/.
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

# Harte Faelle (C3): sha8 -> Artikel. Session wird aus dem Manifest geholt.
HARTE_FAELLE = {
    "cc1f627e": "LOEFFEL-6", "b26a6160": "LOEFFEL-2", "5bf6b431": "GABEL-1",
    "4587d1a8": "LOEFFEL-3", "8dc74a45": "LOEFFEL-7",
}
TAIL_Z = 3.0
END_MM = 10.0            # "erste/letzte 10 mm"
CTRL_GATE_MM = 2.0       # Kontroll-Gesamtdefizit muss darunter liegen
CROP = 200
HALF = CROP // 2
DENSIFY_STEP_PX = 0.5


# ============================================================ Geometrie
def _densify(poly, step=DENSIFY_STEP_PX):
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


def _pca_axes(points):
    center = points.mean(axis=0)
    cov = np.cov((points - center).T)
    vals, vecs = np.linalg.eigh(cov)
    order = np.argsort(vals)[::-1]
    return center, vecs[:, order[0]], vecs[:, order[1]]


def _proj(points, axis):
    return np.einsum("ij,j->i", points, axis)


def _aligned(contour_i32, mmpp):
    """Kontur auf Schwerpunkt + Hauptachse ausrichten, Laffe (Breitenmax) ans
    NEGATIVE Ende. Rueckgabe (s_dense, m_dense mm, laffe_xy, handle_xy)."""
    contour = contour_i32.astype(np.float64)
    dense = _densify(contour)
    c, u, _ = _pca_axes(dense)
    u = u / np.linalg.norm(u)
    sd = _proj(dense - c, u)
    v = np.array([-u[1], u[0]])
    md = _proj(dense - c, v)
    # Breitenmax-Seite bestimmen (grob): welche Haelfte ist breiter?
    neg, pos = sd < 0, sd >= 0
    wn = (md[neg].max() - md[neg].min()) if neg.any() else 0.0
    wp = (md[pos].max() - md[pos].min()) if pos.any() else 0.0
    if wp > wn:                       # Laffe auf positiver Seite -> umdrehen
        u = -u
        sd = -sd
        v = np.array([-u[1], u[0]])
        md = _proj(dense - c, v)
    so = _proj(contour - c, u)
    laffe = contour[int(np.argmin(so))]
    handle = contour[int(np.argmax(so))]
    return sd * mmpp, md * mmpp, laffe, handle


def _halfwidths(sd, md, grid):
    """W+(s), W-(s) auf gemeinsamem 1-mm-Raster (0 ausserhalb der Spanne)."""
    Wp = np.zeros(len(grid))
    Wm = np.zeros(len(grid))
    b = np.floor(sd - grid[0]).astype(int)
    for gi in range(len(grid)):
        sel = b == gi
        if sel.sum() >= 2:
            mm = md[sel]
            Wp[gi] = max(mm.max(), 0.0)
            Wm[gi] = max(-mm.min(), 0.0)
    return Wp, Wm


def _load_ref_stats(db_path):
    out = {}
    if not Path(db_path).is_file():
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
    finally:
        con.close()
    return out


# ================================================================ Worker
_CTX = {}


def _worker_init(cfg, root_str):
    _CTX["cfg"] = cfg
    _CTX["root"] = Path(root_str)
    _CTX["bundles"] = {}
    d = tempfile.mkdtemp(prefix="tail-overlay-")
    _CTX["tmpdir"] = d
    atexit.register(shutil.rmtree, d, True)


def _bundle_for(session):
    if session not in _CTX["bundles"]:
        bdir = _CTX["root"] / session / "bundle"
        tcfg = copy.deepcopy(bundle_cfg(_CTX["cfg"], bdir))
        tcfg.setdefault("paths", {})
        tcfg["paths"]["db_file"] = str(Path(_CTX["tmpdir"]) / f"{session}.sqlite3")
        cal = Calibration.load(bdir / "calibration.json")
        _CTX["bundles"][session] = (tcfg, float(cal.mm_per_px),
                                    _load_ref_stats(bdir / "db.sqlite3"))
    return _CTX["bundles"][session]


def _measure_one(entry):
    rec = {"sha": entry["sha"], "session": entry["session"],
           "article": entry["article"], "image_rel": entry["image_rel"],
           "error": None}
    try:
        root = _CTX["root"]
        tcfg, mmpp, ref_stats = _bundle_for(rec["session"])
        img = cv2.imread(str(root / entry["image_rel"]))
        if img is None:
            rec["error"] = "Bild nicht lesbar"
            return rec
        try:
            _, seg = measure_shot(img, tcfg)
        except SegmentationError as exc:
            rec["error"] = f"SegmentationError: {exc}"
            return rec
        contour = seg.contour.reshape(-1, 2).astype(np.int32)
        if len(contour) < 5:
            rec["error"] = "Kontur < 5"
            return rec
        rec["contour"] = contour.tolist()
        rec["mm_per_px"] = mmpp
        golden = MatchReport.from_json(
            (root / entry["report_rel"]).read_text(encoding="utf-8"))
        gmeas = (golden.measured or {}).get("circle_diameter_mm")
        mu, sigma = ref_stats.get(rec["article"], (None, None))
        rec["is_tail"] = (gmeas is not None and mu is not None and sigma
                          and abs((gmeas - mu) / sigma) > TAIL_Z)
    except Exception as exc:                                # noqa: BLE001
        rec["error"] = f"{type(exc).__name__}: {exc}"
    return rec


# =============================================================== Overlay-Kern
def _mean_reference(refs, grid):
    """Mittleres Halbbreitenprofil + per-s-Streuung ueber die Referenzbilder."""
    Ps, Ms = [], []
    for r in refs:
        sd, md, _, _ = _aligned(np.asarray(r["contour"], np.int32), r["mm_per_px"])
        wp, wm = _halfwidths(sd, md, grid)
        Ps.append(wp)
        Ms.append(wm)
    Ps, Ms = np.array(Ps), np.array(Ms)
    tot = Ps + Ms
    spread = float(np.mean(np.std(tot, axis=0, ddof=1))) if len(refs) > 1 else 0.0
    return Ps.mean(0), Ms.mean(0), spread


def _overlay(tail, refs, grid):
    """D(s) = W_ref - W_tail; Regionen-Zerlegung + Laengen-Defizit."""
    rp, rm, spread = _mean_reference(refs, grid)
    sd, md, laffe, handle = _aligned(np.asarray(tail["contour"], np.int32),
                                     tail["mm_per_px"])
    tp, tm = _halfwidths(sd, md, grid)
    D = (rp + rm) - (tp + tm)                       # mm (fehlende Gesamtbreite)
    ref_tot = rp + rm
    present = ref_tot > 0.5
    if present.sum() < 5:
        return None
    lo_i = int(np.argmax(present))
    hi_i = len(present) - 1 - int(np.argmax(present[::-1]))
    s_lo, s_hi = grid[lo_i], grid[hi_i]
    w_mean = float(ref_tot[present].mean())
    dA = float(D[present].sum())                    # mm^2 (1-mm-Bins)
    len_def = dA / w_mean if w_mean else float("nan")   # mm

    def region_len(a, b):
        sel = present & (grid >= a) & (grid < b)
        return float(D[sel].sum()) / w_mean if w_mean else 0.0

    first = region_len(s_lo, s_lo + END_MM)
    last = region_len(s_hi - END_MM, s_hi + 1)
    bulk = len_def - first - last
    # Ausrichtungsguete: RMS von D im Rumpf, in mm
    bulk_sel = present & (grid >= s_lo + END_MM) & (grid < s_hi - END_MM)
    resid = float(np.sqrt(np.mean(D[bulk_sel] ** 2))) if bulk_sel.any() else float("nan")
    cum = np.cumsum(np.where(present, D, 0.0)) / w_mean
    return dict(len_def=len_def, first=first, last=last, bulk=bulk,
                ref_spread=spread, resid=resid, w_mean=w_mean,
                s_lo=s_lo, s_hi=s_hi, grid=grid, cum=cum, present=present,
                laffe=laffe.tolist(), handle=handle.tolist())


def _grid_for(images):
    lo, hi = [], []
    for r in images:
        sd, _, _, _ = _aligned(np.asarray(r["contour"], np.int32), r["mm_per_px"])
        lo.append(sd.min())
        hi.append(sd.max())
    return np.arange(math.floor(min(lo)) - 1, math.ceil(max(hi)) + 2, 1.0)


# =============================================================== Crops
def _crop(img, contour, xy, out):
    H, W = img.shape[:2]
    cx, cy = int(round(xy[0])), int(round(xy[1]))
    x0, y0 = cx - HALF, cy - HALF
    canvas = np.zeros((CROP, CROP, 3), np.uint8)
    sx0, sy0 = max(0, x0), max(0, y0)
    sx1, sy1 = min(W, x0 + CROP), min(H, y0 + CROP)
    if sx1 > sx0 and sy1 > sy0:
        canvas[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0] = img[sy0:sy1, sx0:sx1]
    pts = (np.asarray(contour) - np.array([x0, y0])).astype(np.int32).reshape(-1, 1, 2)
    cv2.polylines(canvas, [pts], True, (0, 255, 0), 1)
    cv2.circle(canvas, (cx - x0, cy - y0), 3, (0, 0, 255), 1)
    cv2.imwrite(str(out), canvas)


# ==================================================================== main
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-id", default="tail-overlay-" + time.strftime("%Y%m%d-%H%M%S"))
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--no-crops", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    root = corpus_root(cfg)
    manifest = Manifest.load()
    by_sha = {e.sha[:8]: e for e in manifest.images}
    # Zielgruppen: (Artikel, Session) der harten Faelle
    ziel = set()
    for sha8, art in HARTE_FAELLE.items():
        e = by_sha.get(sha8)
        if e:
            ziel.add((e.article, e.session))
    images = [e for e in manifest.images if (e.article, e.session) in ziel]
    print(f"tail_overlay_check — {len(images)} Bilder aus {len(ziel)} Gruppen")
    out_dir = PROJEKT / "reports" / "analysis" / args.run_id
    print(f"Ausgabe: {out_dir}")

    with ProcessPoolExecutor(max_workers=args.workers, initializer=_worker_init,
                             initargs=(cfg, str(root))) as ex:
        recs = list(ex.map(_measure_one, [asdict(e) for e in images], chunksize=1))
    ok = [r for r in recs if not r["error"] and r.get("contour")]
    for r in recs:
        if r["error"]:
            print(f"  ! {r['session']}/{r['sha'][:8]} {r['article']}: {r['error']}")

    groups = {}
    for r in ok:
        groups.setdefault((r["article"], r["session"]), []).append(r)

    rows = []
    crops = []      # (case_rec, ctrl_rec, end_name)
    print("\n=== KONTROLLE + AUSWERTUNG (Laengen-Defizit in mm) ===")
    print("  Regel: Enden konzentriert->Endverlust | verteilt->Optik | "
          "Kontrolle ~ Tail->Methode traegt nicht\n")
    for (art, sess), imgs in sorted(groups.items()):
        tails = [r for r in imgs if r["is_tail"]]
        refs = [r for r in imgs if not r["is_tail"]]
        if len(refs) < 3 or not tails:
            print(f"  {art} {sess}: Referenz n={len(refs)}, Tails={len(tails)} "
                  f"— uebersprungen")
            continue
        grid = _grid_for(imgs)

        # --- Kontrolle: leave-one-out ueber die Referenzen ---
        ctrl = []
        for i, r in enumerate(refs):
            others = refs[:i] + refs[i + 1:]
            res = _overlay(r, others, grid)
            if res:
                ctrl.append(res)
        c_tot = np.array([c["len_def"] for c in ctrl])
        c_med = float(np.median(c_tot))
        c_absmed = float(np.median(np.abs(c_tot)))
        c_first = float(np.median([c["first"] for c in ctrl]))
        c_last = float(np.median([c["last"] for c in ctrl]))
        c_bulk = float(np.median([c["bulk"] for c in ctrl]))
        gate = c_absmed < CTRL_GATE_MM

        print(f"  --- {art}  {sess}  (Referenz n={len(refs)}) ---")
        print(f"    KONTROLLE (LOO): |Gesamtdefizit| Median {c_absmed:.2f} mm  "
              f"(Median {c_med:+.2f})  {'OK' if gate else '*** > 2mm: Ausrichtung ***'}")
        print(f"      Kontroll-Verteilung  erste10 {c_first:+.2f} | letzte10 "
              f"{c_last:+.2f} | Rumpf {c_bulk:+.2f} mm  (Rauschboden)")

        for t in tails:
            res = _overlay(t, refs, grid)
            if not res:
                continue
            tot = res["len_def"]
            end = "laffe" if res["first"] >= res["last"] else "handle"
            rows.append({"article": art, "session": sess, "sha": t["sha"][:8],
                         "kind": "tail", "len_def": round(tot, 2),
                         "first10": round(res["first"], 2),
                         "last10": round(res["last"], 2),
                         "bulk": round(res["bulk"], 2),
                         "resid_mm": round(res["resid"], 2),
                         "ref_spread_mm": round(res["ref_spread"], 2)})
            fr = lambda x: 100 * x / tot if abs(tot) > 1e-6 else float("nan")
            print(f"    TAIL {t['sha'][:8]}: Gesamt {tot:+.2f} mm  |  "
                  f"erste10 {res['first']:+.2f} ({fr(res['first']):.0f}%) | "
                  f"letzte10 {res['last']:+.2f} ({fr(res['last']):.0f}%) | "
                  f"Rumpf {res['bulk']:+.2f} ({fr(res['bulk']):.0f}%)")
            print(f"      Ausrichtungs-Restfehler(Rumpf) {res['resid']:.2f} mm, "
                  f"Referenz-Streuung {res['ref_spread']:.2f} mm")
            # Urteil
            if not gate:
                urteil = "Ausrichtung defekt -> nicht interpretierbar"
            elif abs(res["resid"]) > 2 * res["ref_spread"] + 0.5:
                urteil = "Rumpf-Restfehler hoch -> Ausrichtung/Form fragwuerdig"
            else:
                efr = (abs(res["first"]) + abs(res["last"]))
                bfr = abs(res["bulk"])
                if efr > 2 * bfr:
                    seite = "beide Enden" if min(abs(res["first"]), abs(res["last"])) > 0.4 * max(abs(res["first"]), abs(res["last"])) else ("Laffe" if abs(res["first"]) > abs(res["last"]) else "Stiel")
                    urteil = f"ENDVERLUST ({seite})"
                elif bfr > efr:
                    urteil = "VERTEILT (Optik/Massstab)"
                else:
                    urteil = "gemischt"
            print(f"      -> {urteil}")
            # Crop-Kandidat
            ctrl_img = min(refs, key=lambda r: abs(
                _overlay(r, [x for x in refs if x is not r], grid)["len_def"]
                if len(refs) > 1 else 0.0))
            crops.append((t, ctrl_img, end, res, art, sess))
        print()

    # CSV
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "tail_overlay.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        cols = ["article", "session", "sha", "kind", "len_def", "first10",
                "last10", "bulk", "resid_mm", "ref_spread_mm"]
        w.writerow(cols)
        for r in rows:
            w.writerow([r[c] for c in cols])
    print(f"CSV: {out_dir / 'tail_overlay.csv'}")

    if not args.no_crops and crops:
        cdir = out_dir / "crops"
        if cdir.exists():
            shutil.rmtree(cdir)
        cdir.mkdir(parents=True, exist_ok=True)
        n = 0
        for t, ctrl, end, res, art, sess in crops:
            xy = res["laffe"] if end == "laffe" else res["handle"]
            img = cv2.imread(str(root / t["image_rel"]))
            if img is not None:
                _crop(img, t["contour"], xy, cdir / f"{art}_{sess}_tail_{t['sha'][:8]}_{end}.png")
                n += 1
            cres = _overlay(ctrl, [x for x in groups[(art, sess)] if not x["is_tail"] and x is not ctrl], _grid_for(groups[(art, sess)]))
            cxy = (cres["laffe"] if end == "laffe" else cres["handle"]) if cres else xy
            cimg = cv2.imread(str(root / ctrl["image_rel"]))
            if cimg is not None:
                _crop(cimg, ctrl["contour"], cxy, cdir / f"{art}_{sess}_ctrl_{ctrl['sha'][:8]}_{end}.png")
                n += 1
        print(f"CROPS: {n} PNG -> {cdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
