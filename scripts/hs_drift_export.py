"""H-S-Drift-Attribution — plattform-neutraler Export-Harness (REPORT-ONLY).

Laeuft identisch auf Mac und Windows. Fuer jedes Korpus-Bild werden die
Zwischenwerte der Farb-/Zonen-Kette exportiert (Zonengroessen, dmax exakt,
sha256 von dist/Zonenmasken/hsv-im-Objekt, volle [16,8]-Integer-Zaehlmatrix,
S-Mittel, Lab-Zonenmittel) UND das Endergebnis gegen den Golden-Report
gestellt (Bhattacharyya, max-Bin-Delta).

SELBSTVALIDIERUNG: der Harness repliziert die cv2-Aufrufe aus
features.extract() und PRUEFT je Bild, dass die nachgerechneten
hs_hist_center/rim, lab_center und hue_hist BYTE-GLEICH zu measure_shot()
sind. Erst dann zaehlen seine Zwischenwerte als Beleg (Schutz gegen
Divergenz zum Messpfad).

NICHT im Messpfad, aendert nichts. Aufruf mit der venv:
    .venv/Scripts/python.exe scripts/hs_drift_export.py [--limit N]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.config import load_config
from docodetect.corpus.bundle import bundle_cfg
from docodetect.corpus.manifest import Manifest, corpus_root
from docodetect.pipeline import measure_shot
from docodetect.segmentation import SegmentationError

OUT_DIR = (Path(__file__).resolve().parent.parent
           / "reports" / "archive" / "hs-drift-attribution-2026-07-24")


def _sha(a: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()


def _maxbin(win: list, gold: list):
    """(max |Delta|, signierter Delta am argmax, argmax-Index) win vs golden."""
    if not win or not gold or len(win) != len(gold):
        return None
    w = np.asarray(win, dtype=np.float64)
    g = np.asarray(gold, dtype=np.float64)
    i = int(np.argmax(np.abs(w - g)))
    return float(abs(w[i] - g[i])), float(w[i] - g[i]), i


def _bhatta(win: list, gold: list):
    if not win or not gold or len(win) != len(gold):
        return None
    return float(cv2.compareHist(np.asarray(win, np.float32),
                                 np.asarray(gold, np.float32),
                                 cv2.HISTCMP_BHATTACHARYYA))


def process(entry, root: Path, cfg: dict, tmp_db: str) -> dict | None:
    bcfg = bundle_cfg(cfg, root / entry.session / "bundle")
    bcfg.setdefault("paths", {})["db_file"] = tmp_db          # keine Buendel-DB anfassen
    img = cv2.imread(str(root / entry.image_rel))
    if img is None:
        return {"sha": entry.sha, "error": "Bild nicht lesbar"}
    try:
        feats, seg = measure_shot(img, bcfg)
    except SegmentationError:
        return {"sha": entry.sha, "skip": "SegmentationError"}
    if not feats.hs_hist_center:
        return {"sha": entry.sha, "skip": "keine Zonen"}

    # --- exakte Replikation von features.extract()'s Farb-/Zonen-Block ---
    fcfg = bcfg.get("features", {})
    zones = fcfg.get("ring_zones", {})
    center_max = float(zones.get("center_max", 0.60))
    rim_min = float(zones.get("rim_min", 0.75))
    bins = tuple(fcfg.get("hs_hist_bins", [16, 8]))

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mean_hsv = cv2.mean(hsv, mask=seg.mask)[:3]
    huehist = cv2.calcHist([hsv], [0], seg.mask, [32], [0, 180]).flatten()
    hs = huehist.sum()
    hue_win = (huehist / hs).tolist() if hs > 0 else [0.0] * 32
    fullhs = cv2.calcHist([hsv], [0, 1], seg.mask, [16, 8],
                          [0, 180, 0, 256]).flatten()

    dist = cv2.distanceTransform((seg.mask > 0).astype(np.uint8), cv2.DIST_L2, 5)
    dmax = float(dist.max())
    r = 1.0 - dist / dmax
    inside = seg.mask > 0
    center = np.where(inside & (r < center_max), np.uint8(255), np.uint8(0))
    rim = np.where(inside & (r > rim_min), np.uint8(255), np.uint8(0))
    lab = cv2.cvtColor(img.astype(np.float32) / 255.0, cv2.COLOR_BGR2Lab)

    def zone(z):
        mean_lab = lab[z > 0].mean(axis=0)
        h = cv2.calcHist([hsv], [0, 1], z, list(bins), [0, 180, 0, 256]).flatten()
        t = h.sum()
        return mean_lab, ((h / t) if t > 0 else h)

    ml_c, hn_c = zone(center)
    ml_r, hn_r = zone(rim)
    hs_c_round = [round(float(v), 6) for v in hn_c]
    hs_r_round = [round(float(v), 6) for v in hn_r]
    lab_c_round = [round(float(v), 3) for v in ml_c]
    lab_r_round = [round(float(v), 3) for v in ml_r]

    # --- SELBSTVALIDIERUNG: byte-gleich zum Messpfad ---
    val = {
        "hs_center": hs_c_round == list(feats.hs_hist_center),
        "hs_rim": hs_r_round == list(feats.hs_hist_rim),
        "lab_center": lab_c_round == list(feats.lab_center),
        "lab_rim": lab_r_round == list(feats.lab_rim),
        "hue": [round(v, 6) for v in hue_win] == list(feats.hue_hist),
    }
    valid = all(val.values())

    # --- Golden-Vergleich (Mac-Werte) ---
    gm = json.loads((root / entry.report_rel).read_text(encoding="utf-8")).get("measured") or {}

    def cmp(win, key):
        g = gm.get(key)
        mb = _maxbin(win, g)
        return {"maxdelta": mb[0] if mb else None,
                "signed_at_argmax": mb[1] if mb else None,
                "argmax": mb[2] if mb else None,
                "bhatta_win_vs_golden": _bhatta(win, g)}

    return {
        "sha": entry.sha, "session": entry.session, "article": entry.article,
        "valid": valid, "validation": val,
        "center_px": int(np.count_nonzero(center)),
        "rim_px": int(np.count_nonzero(rim)),
        "obj_px": int(np.count_nonzero(inside)),
        "dmax_hex": float(dmax).hex(), "dmax": dmax,
        "dist_sha": _sha(dist),
        "center_mask_sha": _sha(center), "rim_mask_sha": _sha(rim),
        "hsv_masked_sha": hashlib.sha256(hsv[inside].tobytes()).hexdigest(),
        "fullhs_counts": [int(round(v)) for v in fullhs],
        "fullhs_sha": _sha(np.asarray([int(round(v)) for v in fullhs], dtype=np.int64)),
        "mean_S_hex": float(mean_hsv[1]).hex(), "mean_S": float(mean_hsv[1]),
        "mean_S_golden": gm.get("mean_saturation"),
        "lab_center_full": [float(v) for v in ml_c],
        "lab_rim_full": [float(v) for v in ml_r],
        "lab_center_golden": gm.get("lab_center"),
        "cmp_hs_center": cmp(list(feats.hs_hist_center), "hs_hist_center"),
        "cmp_hs_rim": cmp(list(feats.hs_hist_rim), "hs_hist_rim"),
        "cmp_hue": cmp(list(feats.hue_hist), "hue_hist"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out", default=str(OUT_DIR))
    args = ap.parse_args()

    cfg = load_config()
    root = corpus_root(cfg)
    images = sorted(Manifest.load().images, key=lambda e: (e.session, e.sha))
    if args.limit:
        images = images[:args.limit]

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    tmp_db = str(Path(tempfile.mkdtemp(prefix="hsdrift-")) / "empty.sqlite3")

    records, n_valid, n_skip, n_invalid = {}, 0, 0, 0
    for i, e in enumerate(images, 1):
        rec = process(e, root, cfg, tmp_db)
        if rec is None or rec.get("skip") or rec.get("error"):
            n_skip += 1
            print(f"[{i}/{len(images)}] {e.sha[:8]} SKIP/ERR: {rec}")
            continue
        records[e.sha] = rec
        if rec["valid"]:
            n_valid += 1
        else:
            n_invalid += 1
            print(f"[{i}/{len(images)}] {e.sha[:8]} !! SELBSTVALIDIERUNG FEHLGESCHLAGEN: {rec['validation']}")
        if i % 20 == 0:
            print(f"[{i}/{len(images)}] ... valid={n_valid} invalid={n_invalid} skip={n_skip}")

    payload = {"generated_on": {"platform": __import__("platform").platform(),
                                "machine": __import__("platform").machine(),
                                "python": __import__("platform").python_version(),
                                "cv2": cv2.__version__, "numpy": np.__version__,
                                "sqlite": __import__("sqlite3").sqlite_version},
               "n": len(records), "n_valid": n_valid,
               "n_invalid": n_invalid, "n_skip": n_skip,
               "images": records}
    out = outdir / "windows_export.json"
    out.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"\n=== {n_valid} valid / {n_invalid} invalid / {n_skip} skip -> {out} ===")
    if n_invalid:
        print("!! ABBRUCH-WUERDIG: Harness divergiert vom Messpfad. Belege ungueltig.")


if __name__ == "__main__":
    main()
