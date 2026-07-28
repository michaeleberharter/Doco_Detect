#!/usr/bin/env python3
"""tail_completion_check.py — Feuert die Auswaerts-Vervollstaendigung im Tail
schwaecher als in der Referenz? (read-only, instrumentiert)

VERDIKT (2026-07-28): Instrumentierung GETRAGEN, Hypothese WIDERLEGT. Der
ext-Auswaertslauf (reach=48) feuert NIE (0/165 Bilder); die amodalen Zweige
(_enclosed/_bridging/_notches) unterscheiden sich Tail vs. Referenz
inkonsistent (3x weniger, 2x mehr) und sind flaechen-additiv, koennen also den
Laengen-Defizit nicht treiben. Der zunaechst gefundene n_frozen-Unterschied
war ein Normalisierungsartefakt (C7: frozen_frac = n_frozen/n_contour ~ 1.0
fuer Tails UND Kontrollen). Keine am Schreibtisch festnagelbare Segmentierungs-
Ursache. Einziger schwacher Lead: gmag auf der Kontur 5/5 niedriger im Tail
(p=0,03), aber innerhalb 1 Sigma der Kontrollspanne -> Wiederholtest muss
Beleuchtung/Kontrast variieren. Die Monkeypatch-Technik selbst ist
wiederverwendbar (segmentation.py bleibt unangetastet).

C5 hat den Verdaechtigen gewechselt: nicht Trunkierung nach innen, sondern
unterschiedlich starke Vervollstaendigung nach AUSSEN — der ext-Auswaertslauf
(reach=48 px) und die amodalen Zweige _enclosed_zones/_bridging_zones/
_fill_invisible_notches/_annex_transparent_parts. Alle schwellengesteuert, also
BINAER pro Bild: hat der Zweig gefeuert oder nicht — das ist nicht
rauschbodenbegrenzt.

Dieses Skript AENDERT segmentation.py NICHT. Es monkeypatcht die relevanten
Funktionen im laufenden Prozess mit Wrappern, die je Bild protokollieren, wie
stark jeder Vervollstaendigungs-Zweig gewirkt hat. Der ext-/frozen-/area-guard-
Teil steckt intern in _snap_contour_to_edges; dafuer laeuft ein zeilentreuer
REPLIKAT der inneren Rechnung (mirror von segmentation.py:237-319) NUR zur
Messung — die ECHTE (unveraenderte) Funktion treibt weiterhin die Maske, das
Replikat fasst sie nicht an.

Read-only: kein Messpfad-Eingriff, keine Schwellen, keine Schreibzugriffe nach
corpus/. Kontur ueber den bekannten Tier-1-Replay. Ausgabe nur nach
reports/analysis/<run-id>/.

ENTSCHEIDUNGSREGEL
  Referenzen zeigen systematisch MEHR ext-Punkte / groesseres
    ext_shift_at_ends als die Tails -> Unter-Vervollstaendigung bestaetigt
    (Referenz zu lang, nicht Tail zu kurz).
  Kein Unterschied in den Zweigen -> Effekt entsteht frueher (Graph-Cut/
    Evidenz) oder physisch -> Schluss am Schreibtisch.
  Tails zeigen MEHR Vervollstaendigung -> gegenlaeufig, getrennt melden.
"""

from __future__ import annotations

import argparse
import atexit
import copy
import csv
import shutil
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

import docodetect.segmentation as seg                               # noqa: E402
from docodetect.calibration import Calibration                      # noqa: E402
from docodetect.config import load_config                           # noqa: E402
from docodetect.corpus.bundle import bundle_cfg                     # noqa: E402
from docodetect.corpus.manifest import Manifest, corpus_root        # noqa: E402
from docodetect.matcher import MatchReport                          # noqa: E402
from docodetect.pipeline import measure_shot                        # noqa: E402
from docodetect.segmentation import SegmentationError               # noqa: E402
import docodetect.corpus.bundle as cbundle                          # noqa: E402

HARTE_FAELLE = {"cc1f627e": "LOEFFEL-6", "b26a6160": "LOEFFEL-2",
                "5bf6b431": "GABEL-1", "4587d1a8": "LOEFFEL-3",
                "8dc74a45": "LOEFFEL-7"}
TAIL_Z = 3.0

# ---- Metrik-Sammler je Bild (Worker-global; vor jedem Bild zurueckgesetzt) --
_M: dict = {}
_ORIG: dict = {}


def _snap_metrics(mask, gray, wall_grad):
    """Zeilentreues Replikat von _snap_contour_to_edges (segmentation.py:237-319),
    NUR zur Messung. Zaehlt ext-Auswaertsspruenge, frozen-Punkte, den
    Flaechenwaechter — und ordnet ext-Spruenge den axialen Enden zu."""
    # Konstanten spiegeln segmentation.py:237-242
    search, reach, win, iters = 8, 48, 15, 2
    min_grad = 0.75 * wall_grad
    freeze_grad = 1.5 * wall_grad
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    gmag = cv2.magnitude(gx, gy)
    H, W = gray.shape
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    out = dict(snap_ran=False, n_ext_points=0, ext_shift_max_px=0.0,
               ext_shift_ends_px=0.0, n_frozen=0, area_guard_hit=False,
               repl_area=0.0, gmag_contour_med=0.0, snap_grad=float(wall_grad),
               n_contour=0)
    if not cnts:
        return out
    base = max(cnts, key=cv2.contourArea).reshape(-1, 2).astype(np.float32)
    if len(base) < 40:
        return out
    out["snap_ran"] = True
    out["n_contour"] = int(len(base))
    # axiale Enden (10 % naechst den beiden Extrempunkten der Hauptachse)
    c0 = base.mean(0)
    cov = np.cov((base - c0).T)
    vals, vecs = np.linalg.eigh(cov)
    u = vecs[:, int(np.argmax(vals))]
    proj = np.einsum("ij,j->i", base - c0, u)   # @ triggert spuriose RuntimeWarning
    p10, p90 = np.percentile(proj, [10, 90])
    ends = (proj <= p10) | (proj >= p90)

    pts = base.copy()
    kernel = np.ones(win, np.float32) / win
    offs = np.arange(-search, search + 1, dtype=np.float32)
    prior = np.exp(-(offs / (search * 0.75)) ** 2)
    for it in range(iters):
        t = np.roll(pts, -4, axis=0) - np.roll(pts, 4, axis=0)
        norm = np.stack([-t[:, 1], t[:, 0]], axis=1)
        length = np.linalg.norm(norm, axis=1, keepdims=True)
        length[length == 0] = 1.0
        norm /= length
        px = np.clip(np.round(pts[:, 0] + norm[:, 0] * 3).astype(np.int32), 0, W - 1)
        py = np.clip(np.round(pts[:, 1] + norm[:, 1] * 3).astype(np.int32), 0, H - 1)
        if float((mask[py, px] > 0).mean()) > 0.5:
            norm = -norm
        sample = pts[:, None, :] + norm[:, None, :] * offs[None, :, None]
        xi = np.clip(np.round(sample[:, :, 0]).astype(np.int32), 0, W - 1)
        yi = np.clip(np.round(sample[:, :, 1]).astype(np.int32), 0, H - 1)
        vals_s = gmag[yi, xi]
        best_idx = np.argmax(vals_s * prior[None, :], axis=1)
        best_val = vals_s[np.arange(len(pts)), best_idx]
        shift = offs[best_idx].copy()
        shift[best_val < min_grad] = 0.0
        lost = best_val < min_grad
        if lost.any():
            ext = np.arange(search + 1, reach + 1, dtype=np.float32)
            es = pts[lost, None, :] + norm[lost, None, :] * ext[None, :, None]
            exi = np.clip(np.round(es[:, :, 0]).astype(np.int32), 0, W - 1)
            eyi = np.clip(np.round(es[:, :, 1]).astype(np.int32), 0, H - 1)
            evals = gmag[eyi, exi] >= wall_grad
            hit = evals.any(axis=1)
            first = np.argmax(evals, axis=1).astype(np.float32) + search + 1
            beyond = np.zeros(len(first), bool)
            for probe in (5.0, 10.0, 15.0):
                bp = pts[lost] + norm[lost] * (first[:, None] + probe)
                bxi = np.clip(np.round(bp[:, 0]).astype(np.int32), 0, W - 1)
                byi = np.clip(np.round(bp[:, 1]).astype(np.int32), 0, H - 1)
                beyond |= mask[byi, bxi] > 0
            eshift = np.where(hit & ~beyond, first, 0.0)
            shift[lost] = eshift
            fired = eshift > 0
            if it == 0:
                out["n_ext_points"] = int(fired.sum())
            if fired.any():
                out["ext_shift_max_px"] = max(out["ext_shift_max_px"],
                                              float(eshift[fired].max()))
                end_lost = ends[np.where(lost)[0]]
                ef = eshift[fired]
                ee = ef[end_lost[fired]]
                if ee.size:
                    out["ext_shift_ends_px"] = max(out["ext_shift_ends_px"],
                                                   float(ee.max()))
        freeze = vals_s[:, search] >= freeze_grad
        if it == 0:
            out["n_frozen"] = int(freeze.sum())
            # gmag AM Konturpunkt (Offset 0) = Kantenstaerke, die das Objekt
            # tatsaechlich zeigt — die EINGANGSgroesse hinter dem Freeze
            out["gmag_contour_med"] = float(np.median(vals_s[:, search]))
        shift[freeze] = 0.0
        pad = win // 2
        shift_smooth = np.convolve(
            np.concatenate([shift[-pad:], shift, shift[:pad]]), kernel, "valid")
        pts = pts + norm * shift_smooth[:, None]
    poly = np.round(pts).astype(np.int32)
    o = np.zeros_like(mask)
    cv2.fillPoly(o, [poly], 255)
    cnts2, _ = cv2.findContours(o, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if cnts2:
        a0 = float(cv2.countNonZero(mask))
        a1 = float(cv2.contourArea(max(cnts2, key=cv2.contourArea)))
        out["repl_area"] = a1
        out["area_guard_hit"] = not (a0 > 0 and 0.85 <= a1 / a0 <= 1.15)
    return out


def _install():
    """Wrappt die Vervollstaendigungs-Funktionen im seg-Modul. Die Originale
    bleiben unveraendert und treiben weiter die Maske; die Wrapper messen nur."""
    _ORIG["snap"] = seg._snap_contour_to_edges
    _ORIG["enc"] = seg._enclosed_zones
    _ORIG["brg"] = seg._bridging_zones
    _ORIG["anx"] = seg._annex_transparent_parts
    _ORIG["ntc"] = seg._fill_invisible_notches

    def snap(mask, gray, wall_grad):
        m = _snap_metrics(mask, gray, wall_grad)
        for k, v in m.items():
            _M[k] = v
        return _ORIG["snap"](mask, gray, wall_grad)

    def enc(*a, **k):
        r = _ORIG["enc"](*a, **k)
        _M["enclosed_px"] = _M.get("enclosed_px", 0) + int(np.count_nonzero(r))
        return r

    def brg(*a, **k):
        r = _ORIG["brg"](*a, **k)
        _M["bridging_px"] = _M.get("bridging_px", 0) + int(np.count_nonzero(r))
        return r

    def anx(mask, *a, **k):
        r = _ORIG["anx"](mask, *a, **k)
        _M["annex_px"] = _M.get("annex_px", 0) + int(cv2.countNonZero(r)) - int(cv2.countNonZero(mask))
        return r

    def ntc(mask, *a, **k):
        r = _ORIG["ntc"](mask, *a, **k)
        _M["notches_px"] = _M.get("notches_px", 0) + int(cv2.countNonZero(r)) - int(cv2.countNonZero(mask))
        return r

    seg._snap_contour_to_edges = snap
    seg._enclosed_zones = enc
    seg._bridging_zones = brg
    seg._annex_transparent_parts = anx
    seg._fill_invisible_notches = ntc


# ================================================================ Worker
_CTX: dict = {}


def _worker_init(cfg, root_str):
    _CTX["cfg"] = cfg
    _CTX["root"] = Path(root_str)
    _CTX["bundles"] = {}
    _CTX["tmp"] = tempfile.mkdtemp(prefix="tail-compl-")
    atexit.register(shutil.rmtree, _CTX["tmp"], True)
    _install()


def _bundle_for(session):
    if session not in _CTX["bundles"]:
        bdir = _CTX["root"] / session / "bundle"
        tc = copy.deepcopy(bundle_cfg(_CTX["cfg"], bdir))
        tc.setdefault("paths", {})
        tc["paths"]["db_file"] = str(Path(_CTX["tmp"]) / f"{session}.sqlite3")
        cal = Calibration.load(bdir / "calibration.json")
        # reference_stats fuer is_tail
        stats = {}
        dbp = bdir / "db.sqlite3"
        if dbp.is_file():
            import sqlite3, json
            con = sqlite3.connect(f"file:{dbp}?mode=ro", uri=True)
            try:
                for art, sj in con.execute(
                        "SELECT article_number, stats_json FROM reference_stats"):
                    s = json.loads(sj)
                    mu = s.get("scalar_mean", {}).get("diameter_mm")
                    sd = s.get("scalar_std", {}).get("diameter_mm")
                    if mu is not None:
                        stats[art] = (float(mu), float(sd) if sd else None)
            finally:
                con.close()
        _CTX["bundles"][session] = (tc, float(cal.mm_per_px), stats)
    return _CTX["bundles"][session]


DEFAULTS = dict(enclosed_px=0, bridging_px=0, annex_px=0, notches_px=0,
                n_ext_points=0, ext_shift_max_px=0.0, ext_shift_ends_px=0.0,
                n_frozen=0, area_guard_hit=False, snap_ran=False, repl_area=0.0,
                gmag_contour_med=0.0, snap_grad=0.0, n_contour=0)


def _measure_one(entry):
    rec = {"sha": entry["sha"], "session": entry["session"],
           "article": entry["article"], "error": None}
    try:
        root = _CTX["root"]
        tc, mmpp, stats = _bundle_for(rec["session"])
        img = cv2.imread(str(root / entry["image_rel"]))
        if img is None:
            rec["error"] = "Bild nicht lesbar"
            return rec
        _M.clear()
        _M.update(DEFAULTS)
        try:
            _, sg = measure_shot(img, tc)
        except SegmentationError as exc:
            rec["error"] = f"SegmentationError: {exc}"
            return rec
        rec.update({k: _M.get(k) for k in DEFAULTS})
        rec["mmpp"] = mmpp
        rec["ext_shift_ends_mm"] = round(_M["ext_shift_ends_px"] * mmpp, 3)
        rec["ext_shift_max_mm"] = round(_M["ext_shift_max_px"] * mmpp, 3)
        rec["seg_area"] = int(cv2.countNonZero(sg.mask))
        golden = MatchReport.from_json(
            (root / entry["report_rel"]).read_text(encoding="utf-8"))
        gm = (golden.measured or {}).get("circle_diameter_mm")
        mu, sigma = stats.get(rec["article"], (None, None))
        rec["is_tail"] = (gm is not None and mu is not None and sigma
                          and abs((gm - mu) / sigma) > TAIL_Z)
    except Exception as exc:                                # noqa: BLE001
        rec["error"] = f"{type(exc).__name__}: {exc}"
    return rec


# =============================================================== Auswertung
COLS = ["sha", "session", "article", "is_tail", "snap_ran", "n_ext_points",
        "ext_shift_max_px", "ext_shift_max_mm", "ext_shift_ends_px",
        "ext_shift_ends_mm", "n_frozen", "n_contour", "gmag_contour_med",
        "snap_grad", "area_guard_hit", "enclosed_px",
        "bridging_px", "annex_px", "notches_px", "seg_area", "repl_area",
        "mmpp", "error"]


def _fmt(vals):
    a = np.array([v for v in vals if v is not None], float)
    if a.size == 0:
        return "  —"
    return f"{np.median(a):.1f} [{a.min():.0f}..{a.max():.0f}]"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default="tail-compl-" + time.strftime("%Y%m%d-%H%M%S"))
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    cfg = load_config()
    root = corpus_root(cfg)
    man = Manifest.load()
    images = sorted(man.images, key=lambda e: (e.session, e.sha))
    if args.limit:
        images = images[:args.limit]
    out_dir = PROJEKT / "reports" / "analysis" / args.run_id
    print(f"tail_completion_check — {len(images)} Bilder, {args.workers} Worker")

    with ProcessPoolExecutor(max_workers=args.workers, initializer=_worker_init,
                             initargs=(cfg, str(root))) as ex:
        recs = list(ex.map(_measure_one, [asdict(e) for e in images], chunksize=1))
    errs = [r for r in recs if r["error"]]
    ok = [r for r in recs if not r["error"] and r.get("snap_ran") is not None]
    print(f"gemessen, Fehler: {len(errs)}")

    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "tail_completion.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(COLS)
        for r in recs:
            w.writerow(["" if r.get(c) is None else r.get(c) for c in COLS])
    print(f"CSV: {out_dir / 'tail_completion.csv'}")

    valid = [r for r in ok if r.get("error") is None and "n_ext_points" in r]
    by8 = {e.sha[:8]: e for e in man.images}
    hard_groups = {}
    for sha8, art in HARTE_FAELLE.items():
        e = by8.get(sha8)
        if e:
            hard_groups[(art, e.session)] = sha8

    print("\n=== AUSWERTUNG: harter Fall vs. Referenz (gleicher Artikel/Session) ===")
    keys = ["n_ext_points", "ext_shift_ends_mm", "ext_shift_max_mm", "n_frozen",
            "enclosed_px", "bridging_px", "notches_px", "annex_px"]
    verdicts = []
    for (art, sess), tsha in sorted(hard_groups.items()):
        grp = [r for r in valid if r["article"] == art and r["session"] == sess]
        tail = [r for r in grp if str(r["sha"])[:8] == tsha]
        refs = [r for r in grp if not r["is_tail"]]
        if not tail or len(refs) < 3:
            print(f"\n  {art} {sess}: Tail={len(tail)} Ref={len(refs)} — uebersprungen")
            continue
        t = tail[0]
        print(f"\n  --- {art}  {sess}  (Ref n={len(refs)}) ---")
        print(f"    {'Groesse':<18}{'TAIL':>12}{'REFERENZ median[min..max]':>30}")
        row = {"article": art}
        for k in keys:
            rv = [r[k] for r in refs]
            print(f"    {k:<18}{str(t[k]):>12}{_fmt(rv):>30}")
            row[k] = (t[k], float(np.median([x for x in rv if x is not None]))
                      if any(x is not None for x in rv) else None)
        # area_guard fraction
        ag = sum(1 for r in refs if r["area_guard_hit"])
        print(f"    {'area_guard(ref)':<18}{str(t['area_guard_hit']):>12}"
              f"{ag}/{len(refs)} refs".rjust(30))
        verdicts.append(row)

    # Aggregat: feuert der ext-Zweig an den Enden im Tail schwaecher?
    print("\n  === Entscheidung (ext an den Enden = Auswaerts-Vervollstaendigung) ===")
    less = same = more = 0
    for row in verdicts:
        te, re = row["ext_shift_ends_mm"]
        tn, rn = row["n_ext_points"]
        # "schwaecher" = Tail deutlich unter Referenz-Median
        if (re is not None and te < re - 0.3) or (rn is not None and tn < rn - 1):
            less += 1
            tag = "Tail < Ref (weniger Auswaerts-Vervollst.)"
        elif (re is not None and te > re + 0.3) or (rn is not None and tn > rn + 1):
            more += 1
            tag = "Tail > Ref (mehr — gegenlaeufig!)"
        else:
            same += 1
            tag = "kein Unterschied"
        print(f"    {row['article']:<11} ext_ends {te:.2f}/{re if re else 0:.2f} mm  "
              f"n_ext {tn}/{rn if rn else 0}  -> {tag}")
    print(f"\n  Bilanz ueber {len(verdicts)} harte Faelle: "
          f"weniger {less} | kein Unterschied {same} | mehr {more}")
    if less > same + more:
        print("  -> UNTER-VERVOLLSTAENDIGUNG bestaetigt: Referenz zu lang, "
              "nicht Tail zu kurz.")
    elif same >= less + more:
        print("  -> kein Zweig-Unterschied: Effekt entsteht frueher "
              "(Graph-Cut/Evidenz) oder physisch. Schluss am Schreibtisch.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
