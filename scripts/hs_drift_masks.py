"""H-S-Drift: Windows-Zonenmasken einer kuratierten Teilmenge fuer das
Kreuz-Zonen-Experiment am Mac (REPORT-ONLY, aendert nichts).

Der einzige DIREKTE K1/K2-Schnitt: auf dem Mac die Merkmale einmal mit den
mac-eigenen Zonen und einmal mit DIESEN importierten Windows-Zonen rechnen.
Die Masken MUESSEN von Windows stammen — Neuerzeugung auf dem Mac haette
genau die Eigenschaft (mac-eigene Zonen), die geprueft werden soll.
"""
from __future__ import annotations

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

SUBSET = {
    "262f2338": "GABEL-4-FAIL",
    "5bf6b431": "GABEL-1-FAIL-rueckenlage",
    "5bed31ea": "LOEFFEL-6-median-drift",
    "07ed04d1": "LOEFFEL-10-meanS",
    "73f7ede8": "GABEL-2-stabil",
}
OUT = (Path(__file__).resolve().parent.parent / "reports" / "archive"
       / "hs-drift-attribution-2026-07-24" / "windows_zone_masks.npz")


def main():
    cfg = load_config()
    root = corpus_root(cfg)
    tmp = str(Path(tempfile.mkdtemp(prefix="hsmask-")) / "e.sqlite3")
    entries = {e.sha[:8]: e for e in Manifest.load().images
               if e.sha[:8] in SUBSET}
    arrays = {}
    for sha8, e in entries.items():
        bcfg = bundle_cfg(cfg, root / e.session / "bundle")
        bcfg.setdefault("paths", {})["db_file"] = tmp
        img = cv2.imread(str(root / e.image_rel))
        feats, seg = measure_shot(img, bcfg)
        z = bcfg.get("features", {}).get("ring_zones", {})
        cmax, rmin = float(z.get("center_max", 0.60)), float(z.get("rim_min", 0.75))
        dist = cv2.distanceTransform((seg.mask > 0).astype(np.uint8), cv2.DIST_L2, 5)
        r = 1.0 - dist / float(dist.max())
        inside = seg.mask > 0
        center = np.where(inside & (r < cmax), np.uint8(255), np.uint8(0))
        rim = np.where(inside & (r > rmin), np.uint8(255), np.uint8(0))
        lbl = SUBSET[sha8]
        arrays[f"{lbl}__center"] = center
        arrays[f"{lbl}__rim"] = rim
        print(f"{sha8} {lbl}: center_px={int((center>0).sum())} rim_px={int((rim>0).sum())}")
    np.savez_compressed(OUT, **arrays)
    print(f"saved {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
