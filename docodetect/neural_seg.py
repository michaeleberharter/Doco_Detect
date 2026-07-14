"""Optional neural silhouette (SAM family) with AUTOMATIC prompts.

Motivation: reflective cutlery on a near-black floor is the pathological case
for classical background subtraction – parts of the object look exactly like
the background. A promptable segmentation model (MobileSAM) produces
pixel-precise silhouettes there, but needs prompts. We derive them
AUTOMATICALLY from the classical locator (the selected cue blob): its bounding
box plus a few interior points spread along the object. Nobody draws anything.

Division of labour:
- classical cues (segmentation.py phases 1-3): FIND the object, reject noise,
  guard the frame border – unchanged, well tested.
- this module: given the located blob, return a precise silhouette mask.
- segmentation.py: sanity-checks the result and falls back to the classical
  refinement whenever this module returns None (package not installed,
  checkpoint missing, model output implausible).

All heavy imports (torch, mobile_sam) happen lazily inside functions, exactly
like embeddings.py – stage 1 keeps working without them.
"""

from __future__ import annotations

import shutil
import threading
import urllib.request

import cv2
import numpy as np

from .config import resolve

_MODELS = {
    "mobile_sam": {
        "package": "mobile_sam",
        "registry_key": "vit_t",
        "checkpoint": "models/mobile_sam.pt",
        "urls": ["https://raw.githubusercontent.com/ChaoningZhang/MobileSAM/"
                 "master/weights/mobile_sam.pt",
                 "https://github.com/ultralytics/assets/releases/download/"
                 "v8.3.0/mobile_sam.pt"],
    },
    "hq_tiny": {  # Light HQ-SAM: same speed class, crisper thin structures
        "package": "segment_anything_hq",
        "registry_key": "vit_tiny",
        "checkpoint": "models/sam_hq_vit_tiny.pth",
        "urls": ["https://huggingface.co/lkeab/hq-sam/resolve/main/"
                 "sam_hq_vit_tiny.pth"],
    },
}
_MIN_CHECKPOINT_BYTES = 30_000_000  # sanity floor against truncated downloads

_predictors: dict = {}      # model name -> predictor, loaded once per process
_unavailable_reason = None  # remember why loading failed – warn only once
# One lock for load AND inference: SamPredictor.set_image mutates shared
# state, and Streamlit serves every browser session from a thread of the
# same process – unlocked concurrent predicts corrupt each other's masks.
_lock = threading.Lock()


def _download_checkpoint(ckpt, urls) -> None:
    ckpt.parent.mkdir(parents=True, exist_ok=True)
    tmp = ckpt.with_suffix(".part")
    try:
        for i, url in enumerate(urls):
            try:
                with urllib.request.urlopen(url, timeout=60) as resp, \
                        open(tmp, "wb") as fh:
                    shutil.copyfileobj(resp, fh)
                break
            except Exception:
                if i == len(urls) - 1:
                    raise
        if tmp.stat().st_size < _MIN_CHECKPOINT_BYTES:
            raise IOError(f"download truncated ({tmp.stat().st_size} bytes)")
        tmp.replace(ckpt)
    finally:
        tmp.unlink(missing_ok=True)


def auto_prompts(blob_mask: np.ndarray, k: int = 5, pad: int = 12):
    """Derive SAM prompts from the classical locator blob – no user input.

    Returns (box, points): `box` = [x1, y1, x2, y2] around the blob with
    padding, `points` = up to k interior points placed at successive maxima of
    the distance transform with neighbourhood suppression, so they spread
    along the whole object (bowl AND dim handle – forcing the model to keep
    low-contrast parts).
    """
    m = (blob_mask > 0).astype(np.uint8)
    H, W = m.shape
    x, y, w, h = cv2.boundingRect(m)
    box = [max(0, x - pad), max(0, y - pad),
           min(W - 1, x + w + pad), min(H - 1, y + h + pad)]

    dist = cv2.distanceTransform(m, cv2.DIST_L2, 3)
    suppress = max(30, int(0.15 * max(w, h)))
    points = []
    for _ in range(k):
        _, max_v, _, max_loc = cv2.minMaxLoc(dist)
        if max_v < 3:
            break
        points.append(list(max_loc))
        cv2.circle(dist, max_loc, suppress, 0, -1)
    return box, points


def _load_predictor(ncfg: dict):
    """Load the configured SAM variant once per process. NEVER raises: every
    failure sets _unavailable_reason and returns None so the caller falls back
    to the classical refinement. A missing/failed checkpoint is re-checked
    when the file appears later (long-lived Streamlit process); a missing
    package is latched for the process lifetime."""
    global _unavailable_reason
    name = ncfg.get("model", "hq_tiny")
    spec = _MODELS.get(name)
    if spec is None:
        _unavailable_reason = f"unbekanntes Modell '{name}'"
        print(f"[neural_seg] {_unavailable_reason} – klassische Segmentierung aktiv.")
        return None
    if name in _predictors:
        return _predictors[name]
    ckpt = resolve(ncfg.get("checkpoint") or spec["checkpoint"])
    if _unavailable_reason is not None:
        if _unavailable_reason.startswith("checkpoint") and ckpt.exists():
            _unavailable_reason = None  # user fixed it – retry below
        else:
            return None
    try:
        import importlib

        import torch  # noqa: F401
        mod = importlib.import_module(spec["package"])
    except ImportError as e:
        _unavailable_reason = f"package missing ({e})"
        print(f"[neural_seg] KI-Segmentierung nicht verfügbar: {_unavailable_reason}. "
              "Installation: pip install -r requirements-seg-neural.txt "
              "– es läuft die klassische Segmentierung.")
        return None

    try:
        if not ckpt.exists():
            if not ncfg.get("auto_download", True):
                _unavailable_reason = f"checkpoint missing ({ckpt})"
                print(f"[neural_seg] {_unavailable_reason} – klassische Segmentierung aktiv.")
                return None
            print(f"[neural_seg] lade {name}-Checkpoint (~40 MB) nach {ckpt} ...")
            _download_checkpoint(ckpt, spec["urls"])
            print("[neural_seg] Checkpoint geladen.")

        device = ncfg.get("device", "cpu")
        # some checkpoints (HQ-SAM) store CUDA tensors and their loader passes
        # no map_location – force the target device during model construction
        import functools

        import torch as _torch
        _orig_load = _torch.load
        _torch.load = functools.partial(_orig_load, map_location=device)
        try:
            sam = mod.sam_model_registry[spec["registry_key"]](checkpoint=str(ckpt))
        finally:
            _torch.load = _orig_load
        sam.to(device)
        sam.eval()
        _predictors[name] = mod.SamPredictor(sam)
        print(f"[neural_seg] {name} bereit ({device}).")
        return _predictors[name]
    except Exception as e:
        _unavailable_reason = f"checkpoint/Modell-Load fehlgeschlagen ({e})"
        print(f"[neural_seg] {_unavailable_reason} – klassische Segmentierung aktiv. "
              f"Ggf. {ckpt} löschen, damit der Download neu startet.")
        return None


def _mask_score(mask_bool: np.ndarray, evidence: np.ndarray,
                blob_dilated: np.ndarray) -> float:
    """How well a candidate mask matches CLASSICAL knowledge: it should cover
    the strong background-difference evidence and not wander outside the
    located blob. Used to pick the best of SAM's multimask proposals."""
    ev_total = int(cv2.countNonZero(evidence))
    cov = (float(np.count_nonzero(mask_bool & (evidence > 0))) / ev_total
           if ev_total else 0.0)
    area = float(np.count_nonzero(mask_bool))
    outside = (float(np.count_nonzero(mask_bool & (blob_dilated == 0))) / area
               if area else 1.0)
    return cov - 0.7 * outside


def neural_silhouette(image_bgr: np.ndarray, blob_mask: np.ndarray,
                      cfg: dict, evidence: np.ndarray | None = None
                      ) -> np.ndarray | None:
    """Precise object mask from a SAM variant, prompted by the classical
    locator. Smarter querying: negative background points, three multimask
    proposals scored against classical evidence, and one refinement iteration
    (best mask fed back as a prompt – smooths hallucinated notches).

    Returns a uint8 {0,255} mask or None when the model is unavailable or its
    output fails the plausibility checks (caller falls back to classical)."""
    ncfg = cfg["segmentation"].get("neural", {})
    try:
        with _lock:  # load once + serialized inference (shared predictor state)
            predictor = _load_predictor(ncfg)
            if predictor is None:
                return None
            import torch

            box, points = auto_prompts(blob_mask, k=int(ncfg.get("points", 5)))
            if not points:
                return None
            # Run on a CROP around the object, not the full frame: SAM resizes
            # its input to 1024px and decodes masks from 256px logits – on the
            # full 1920px frame that seals thin fork-tine slots. The crop
            # restores the effective resolution.
            H, W = image_bgr.shape[:2]
            pad = int(ncfg.get("roi_pad_px", 60))
            rx1, ry1 = max(0, box[0] - pad), max(0, box[1] - pad)
            rx2, ry2 = min(W, box[2] + pad), min(H, box[3] + pad)
            crop = image_bgr[ry1:ry2, rx1:rx2]
            box_c = np.array([box[0] - rx1, box[1] - ry1,
                              box[2] - rx1, box[3] - ry1], dtype=np.float32)
            pts_c = np.array([[px - rx1, py - ry1] for px, py in points],
                             dtype=np.float32)
            lbl = np.ones(len(points), dtype=np.int32)
            blob_dil = cv2.dilate(blob_mask, cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE, (31, 31)))[ry1:ry2, rx1:rx2]
            ev_crop = (evidence[ry1:ry2, rx1:rx2] if evidence is not None
                       else blob_mask[ry1:ry2, rx1:rx2])
            predictor.set_image(crop, image_format="BGR")
            with torch.inference_mode():
                masks, _, logits = predictor.predict(
                    point_coords=pts_c, point_labels=lbl, box=box_c,
                    multimask_output=False,
                )
                best_mask = masks[0]
                base_score = _mask_score(best_mask, ev_crop, blob_dil)
                base_area = float(np.count_nonzero(best_mask))
                # one refinement iteration (mask fed back as prompt): smooths
                # hallucinated boundary notches and often tightens the
                # silhouette. Accepted only if it does not hurt the
                # classical-evidence score AND does not cover meaningfully
                # MORE background-like pixels than the first mask – that is
                # exactly the failure mode of sealing fork-tine slots, while
                # shrinking (plates) and filling tiny notches stay allowed.
                try:
                    masks2, _, _ = predictor.predict(
                        point_coords=pts_c, point_labels=lbl, box=box_c,
                        mask_input=logits[0:1],
                        multimask_output=False,
                    )
                    non_ev = ev_crop == 0
                    bg_gain = (float(np.count_nonzero(masks2[0] & non_ev))
                               - float(np.count_nonzero(best_mask & non_ev)))
                    if (bg_gain <= max(50.0, 0.005 * base_area)
                            and _mask_score(masks2[0], ev_crop, blob_dil)
                            >= base_score):
                        best_mask = masks2[0]
                except Exception:
                    pass  # refinement is a bonus, never a requirement
            mask = np.zeros((H, W), dtype=np.uint8)
            mask[ry1:ry2, rx1:rx2] = best_mask.astype(np.uint8) * 255
    except Exception as e:  # never let the neural path break a measurement
        print(f"[neural_seg] Vorhersage fehlgeschlagen ({e}) – klassischer Fallback.")
        return None

    # plausibility: single largest component, sane size vs the locator blob,
    # and it must actually overlap the blob
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None
    largest = max(cnts, key=cv2.contourArea)
    clean = np.zeros_like(mask)
    cv2.drawContours(clean, [largest], -1, 255, thickness=cv2.FILLED)
    blob_area = float(cv2.countNonZero(blob_mask))
    area = float(cv2.countNonZero(clean))
    if blob_area <= 0 or not (0.4 * blob_area <= area <= 1.6 * blob_area):
        print(f"[neural_seg] Maske unplausibel (Fläche {area:.0f} vs Blob "
              f"{blob_area:.0f}) – klassischer Fallback.")
        return None
    overlap = cv2.countNonZero(cv2.bitwise_and(clean, blob_mask))
    if overlap < 0.5 * min(area, blob_area):
        print("[neural_seg] Maske deckt den Locator-Blob nicht – klassischer Fallback.")
        return None
    return clean
