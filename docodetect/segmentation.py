"""Foreground segmentation: background subtraction + illumination-robust recovery.

Inside the photo box the camera, background and lighting are fixed, so an
absolute difference against the empty-box reference is the primary cue and
stays authoritative for measurement whenever it fires (accurate silhouette).

But a mirror-like object (stainless-steel cutlery) on a dark, low-contrast
background reflects the background: its body has ~background brightness, so the
plain difference is near zero and the object is missed. Two extra cues recover
it, without touching the geometry of high-contrast items:

- Region cue: gray + saturation difference vs. the background (as before).
- Edge cue: Canny silhouette – finds an object via its outline/rim even when
  its interior matches the background brightness.
- Texture cue: local standard deviation – specular highlights and varied
  reflections light up against the uniform matte background.

Final silhouette prefers the region mask when it supports the blob, so white
porcelain etc. measure exactly as before; only region-weak (reflective) objects
fall back to the recovered outline. Object selection is scored (area, solidity,
centrality, border contact) so a border-hugging noise blob no longer wins over
the real object. Objects touching the frame border are flagged (not measurable).
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class SegmentationResult:
    mask: np.ndarray          # uint8 {0,255}, same size as input
    contour: np.ndarray       # largest external contour (Nx1x2 int32)
    touches_border: bool
    area_px: float
    # Intermediate cue masks ("region"/"recover"/"union") so a UI can show
    # which channel saw what – tuning aid, not part of the matching data.
    debug: dict | None = None


class SegmentationError(RuntimeError):
    """Raised when an image cannot be measured. When an object WAS found but
    reaches the frame edge (border touch), the offending SegmentationResult is
    attached as `.segmentation` so a UI can still show WHY it failed. It stays
    None when nothing usable was segmented (empty box / no object)."""

    def __init__(self, message: str, segmentation: SegmentationResult | None = None):
        super().__init__(message)
        self.segmentation = segmentation


def _close(m: np.ndarray, k: np.ndarray) -> np.ndarray:
    """MORPH_CLOSE with outside-the-frame = background, done by zero-padding
    before the close and cropping afterwards. OpenCV's default border value
    for the erode half is +inf, which welds anything within kernel reach of
    the image border into a solid slab touching the border – a phantom
    protrusion that inflates minEnclosingCircle and falsely trips the
    border-touch flag. Zero-padding removes the slab while an object that
    GENUINELY reaches the frame edge keeps its border contact."""
    r = max(k.shape[0], k.shape[1]) // 2 + 1
    p = cv2.copyMakeBorder(m, r, r, r, r, cv2.BORDER_CONSTANT, value=0)
    p = cv2.morphologyEx(p, cv2.MORPH_CLOSE, k)
    return p[r:-r, r:-r]


# ---------- recovery cues (illumination-robust) ----------

def _edge_mask(gray: np.ndarray, bg_gray: np.ndarray, seg: dict):
    """Filled silhouette from the edges the object ADDS over the empty box:
    catches objects whose interior matches the background but whose outline/rim
    has contrast. Differential (image edges minus background edges) so a
    textured empty box does not hallucinate a phantom object.
    Returns (filled silhouette, raw undilated differential edges) – the raw
    edges trace the TRUE outline and are reused to tighten the final blob."""
    # canny_high default 90: a dim handle only ~25 gray levels above a dark
    # floor yields a Sobel magnitude of ~100 – with 120 hysteresis never seeds
    # and the whole handle is invisible to this cue.
    lo, hi = int(seg.get("canny_low", 40)), int(seg.get("canny_high", 90))
    ed = int(seg.get("edge_dilate_kernel", 5)) | 1
    rc = int(seg.get("recover_close_kernel", 25)) | 1
    ek = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ed, ed))
    edges_raw = cv2.subtract(
        cv2.Canny(gray, lo, hi),
        cv2.dilate(cv2.Canny(bg_gray, lo, hi), ek),  # jitter tolerance
    )
    edges = cv2.dilate(edges_raw, ek)
    edges = _close(edges, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (rc, rc)))
    cnts, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = np.zeros(gray.shape, dtype=np.uint8)
    if cnts:
        cv2.drawContours(out, cnts, -1, 255, thickness=cv2.FILLED)
    return out, edges_raw


def _local_std(gray: np.ndarray, tk: int) -> np.ndarray:
    g = gray.astype(np.float32)
    mean = cv2.boxFilter(g, -1, (tk, tk))
    mean_sq = cv2.boxFilter(g * g, -1, (tk, tk))
    return np.sqrt(np.maximum(mean_sq - mean * mean, 0.0))


def _texture_mask(gray: np.ndarray, bg_gray: np.ndarray, seg: dict,
                  kernel: np.ndarray) -> np.ndarray:
    """Local standard deviation the object ADDS over the empty box: specular
    highlights / varied reflections stand out against the matte background.
    Differential (image std minus background std) so an already-textured empty
    box is not mistaken for an object."""
    tk = int(seg.get("texture_kernel", 15)) | 1
    excess = _local_std(gray, tk) - _local_std(bg_gray, tk)
    mask = (excess > float(seg.get("texture_threshold", 12.0))).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)   # despeckle
    mask = _close(mask, kernel)                              # fill
    return mask


# ---------- object selection ----------

def _border_frac(contour: np.ndarray, margin: int, W: int, H: int) -> float:
    """Fraction of the contour's ARC LENGTH that runs along the frame border.
    Arc length (not point count) because CHAIN_APPROX_SIMPLE collapses a long
    straight border edge to two points, which would otherwise be undercounted."""
    pts = contour.reshape(-1, 2).astype(np.float64)
    if len(pts) < 2:
        return 0.0
    nxt = np.roll(pts, -1, axis=0)
    seg_len = np.hypot(nxt[:, 0] - pts[:, 0], nxt[:, 1] - pts[:, 1])
    mid = (pts + nxt) / 2.0
    near = ((mid[:, 0] <= margin) | (mid[:, 1] <= margin)
            | (mid[:, 0] >= W - 1 - margin) | (mid[:, 1] >= H - 1 - margin))
    total = seg_len.sum()
    return float(seg_len[near].sum() / total) if total > 0 else 0.0


def _solidity(contour: np.ndarray, area: float) -> float:
    hull_area = cv2.contourArea(cv2.convexHull(contour))
    return float(area / hull_area) if hull_area > 0 else 0.0


def _centrality(contour: np.ndarray, W: int, H: int) -> float:
    m = cv2.moments(contour)
    if m["m00"] == 0:
        return 0.0
    cx, cy = m["m10"] / m["m00"], m["m01"] / m["m00"]
    dist = np.hypot(cx - W / 2.0, cy - H / 2.0)
    return float(1.0 - dist / np.hypot(W / 2.0, H / 2.0))


def _select_object(contours: list, seg: dict, W: int, H: int, margin: int):
    """Pick the most object-like contour. Rejects small border-hugging noise
    blobs, but never a large object (which may legitimately touch the border).
    Returns (best contour or None, number of plausible candidates) – more than
    one plausible candidate usually means the object fell apart in the masks
    (e.g. spoon bowl and handle separated) and a UI should warn."""
    frame_area = float(W * H)
    large_frac = float(seg.get("large_object_area_frac", 0.02))
    min_sol = float(seg.get("min_solidity", 0.30))
    max_border = float(seg.get("border_contact_max_frac", 0.35))
    pen_w = float(seg.get("border_penalty_weight", 0.5))

    best, best_score, plausible = None, -1.0, 0
    for c in contours:
        area = float(cv2.contourArea(c))
        is_large = area >= large_frac * frame_area
        bfrac = _border_frac(c, margin, W, H)
        sol = _solidity(c, area)
        # hard reject border/noise blobs – unless the blob is large (a big
        # centered plate clipped by the frame must survive to be flagged).
        if not is_large and (bfrac > max_border or sol < min_sol):
            continue
        plausible += 1
        cen = _centrality(c, W, H)
        score = area * max(sol, 1e-3) * (0.5 + 0.5 * cen) * (1.0 - pen_w * bfrac)
        if score > best_score:
            best, best_score = c, score
    return best, plausible


def _carve_open_concavities(mask: np.ndarray, contour: np.ndarray,
                            diff: np.ndarray, seg: dict):
    """Re-open slot-shaped, background-consistent concavities (fork-tine
    slots) that the closing steps bridged. A slot is defined by FOUR
    semantically real conditions:
    1. BACKGROUND-LIKE against an ADAPTIVE threshold: min(diff_threshold,
       Otsu over the diff inside the mask). The Otsu cap separates 'slot'
       from 'dim object' even when the whole object sits barely above the
       global threshold (dim cutlery mirroring the dark floor), which would
       otherwise flood most of the body into one bg-like blob.
    2. DEEP: only pixels > carve_min_depth_px inside the object are candidate
       seeds – the outline blur band / a shaded plate rim are shallow and are
       excluded BEFORE component analysis, so they can never merge with and
       disqualify a slot.
    3. THIN: inscribed width <= carve_max_width_px – a wide background-like
       area is a real reflective part (dim handle), not a slot.
    4. NARROW MOUTH: the candidate must open to the outside through a mouth
       whose boundary contact is <= carve_max_mouth_px. A fork slot opens
       through its narrow tip gap; the dark shadow side of a bowl 'opens'
       along its whole outer arc and is kept. Enclosed candidates are skipped
       (carving an interior hole is a no-op after the FILLED redraw anyway).
    Guard: if the largest remaining contour drops below carve_min_frac of the
    original area, the whole carve is rejected. touches_border is evaluated
    on the UNCARVED silhouette by the caller."""
    thr = int(seg["diff_threshold"])
    inside = mask > 0
    vals = diff[inside]
    if vals.size == 0:
        return mask, contour
    otsu_t, _ = cv2.threshold(vals.reshape(-1, 1), 0, 255,
                              cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    t = max(8.0, min(float(thr), float(otsu_t)))
    inside_bg = (diff < t) & inside
    if not inside_bg.any():
        return mask, contour

    max_r = float(seg.get("carve_max_width_px", 32)) / 2.0
    min_depth = float(seg.get("carve_min_depth_px", 15))
    max_mouth = float(seg.get("carve_max_mouth_px", 48))
    dist_in = cv2.distanceTransform(mask, cv2.DIST_L2, 3)

    # candidate seeds: bg-like AND deeper than the outline band
    cand = np.where(inside_bg & (dist_in > min_depth), np.uint8(255), np.uint8(0))
    if not cand.any():
        return mask, contour
    mouth_zone = (dist_in <= min_depth) & inside          # outer band
    # 1px boundary ring, so `contact` measures the LENGTH of the opening arc
    boundary_ring = cv2.subtract(mask, cv2.erode(
        mask, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))))
    bridge = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (int(2 * min_depth) + 3, int(2 * min_depth) + 3))
    # lid pixels a mouth may pass through: bg-like or only weakly elevated
    passable = (diff < 2 * t) & mouth_zone

    n, labels, stats, _ = cv2.connectedComponentsWithStats(cand, connectivity=8)
    carve = np.zeros_like(mask)
    for i in range(1, n):
        x, y, w, h = stats[i, cv2.CC_STAT_LEFT], stats[i, cv2.CC_STAT_TOP], \
            stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT]
        comp = (labels == i).astype(np.uint8) * 255
        comp_pad = np.pad((labels[y:y + h, x:x + w] == i).astype(np.uint8), 1)
        if cv2.distanceTransform(comp_pad, cv2.DIST_L2, 3).max() > max_r:
            continue  # wide: real reflective part – keep
        mouth = cv2.dilate(comp, bridge)
        mouth[~passable] = 0
        if not mouth.any():
            continue  # enclosed trench: FILLED redraw refills it – no point
        contact = cv2.countNonZero(cv2.bitwise_and(mouth, boundary_ring))
        if contact > max_mouth:
            continue  # opens along a wide front: dark bowl side – keep
        carve = cv2.bitwise_or(carve, comp)
        carve = cv2.bitwise_or(carve, mouth)
    if not carve.any():
        return mask, contour

    carved = cv2.subtract(mask, carve)
    # snap remaining thin blur-bleed seals – but only LOCALLY around the
    # carved slots, so a thin outline shell elsewhere (shaded plate rim) can
    # never be detached by this opening
    small = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    opened = cv2.morphologyEx(carved, cv2.MORPH_OPEN, small)
    near_carve = cv2.dilate(carve, cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (9, 9))) > 0
    carved = np.where(near_carve, opened, carved)
    cnts, _ = cv2.findContours(carved, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return mask, contour

    # 3) final area guard
    best = max(cnts, key=cv2.contourArea)
    min_frac = float(seg.get("carve_min_frac", 0.55))
    if cv2.contourArea(best) < min_frac * cv2.contourArea(contour):
        return mask, contour
    out = np.zeros_like(mask)
    cv2.drawContours(out, [best], -1, 255, thickness=cv2.FILLED)
    return out, best


# ---------- main entry ----------

def segment(image: np.ndarray, background: np.ndarray, cfg: dict) -> SegmentationResult:
    seg = cfg["segmentation"]
    if image.shape != background.shape:
        raise SegmentationError(
            f"Image {image.shape} vs background {background.shape} mismatch. "
            "Recapture the background at the current camera settings."
        )

    H, W = image.shape[:2]
    margin = int(seg["border_margin_px"])
    mk = int(seg["morph_kernel"]) | 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (mk, mk))

    k = int(seg["blur_kernel"]) | 1  # force odd
    img_b = cv2.GaussianBlur(image, (k, k), 0)
    bg_b = cv2.GaussianBlur(background, (k, k), 0)
    img_gray = cv2.cvtColor(img_b, cv2.COLOR_BGR2GRAY)
    bg_gray = cv2.cvtColor(bg_b, cv2.COLOR_BGR2GRAY)
    # Edge/texture cues need sharp detail, so run them on a only lightly
    # denoised grayscale (the heavy blur_kernel is for the region diff). They
    # are differential vs. the background, so a textured empty box is not
    # mistaken for an object.
    cue_gray = cv2.GaussianBlur(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), (3, 3), 0)
    bg_cue_gray = cv2.GaussianBlur(cv2.cvtColor(background, cv2.COLOR_BGR2GRAY), (3, 3), 0)

    # Optional: compensate a global brightness offset (auto-exposure drift)
    # estimated from an outer border ring assumed to be background.
    if seg.get("illum_normalize", False):
        bw = max(1, int(float(seg.get("illum_border_frac", 0.05)) * min(H, W)))
        ring = np.ones((H, W), dtype=bool)
        ring[bw:H - bw, bw:W - bw] = False
        offset = float(np.median(img_gray[ring].astype(np.int16))
                       - np.median(bg_gray[ring].astype(np.int16)))
        img_gray = np.clip(img_gray.astype(np.int16) - round(offset), 0, 255).astype(np.uint8)

    # --- Phase 1: region cue (brightness + saturation difference) ---
    diff_gray = cv2.absdiff(img_gray, bg_gray)
    hsv_img = cv2.cvtColor(img_b, cv2.COLOR_BGR2HSV)
    hsv_bg = cv2.cvtColor(bg_b, cv2.COLOR_BGR2HSV)
    diff_sat = cv2.absdiff(hsv_img[:, :, 1], hsv_bg[:, :, 1])
    # HSV saturation is numerically unstable for near-black pixels (S explodes
    # as V -> 0), so tiny per-channel sensor noise flips it past the threshold
    # on a dark floor -> phantom objects in an EMPTY box. Only trust the
    # saturation difference where at least one frame is reasonably bright.
    v_gate = int(seg.get("sat_min_value", 40))
    diff_sat[cv2.max(hsv_img[:, :, 2], hsv_bg[:, :, 2]) < v_gate] = 0
    diff = cv2.max(diff_gray, diff_sat)
    _, mask_region = cv2.threshold(diff, int(seg["diff_threshold"]), 255, cv2.THRESH_BINARY)
    mask_region = _close(mask_region, kernel)
    mask_region = cv2.morphologyEx(mask_region, cv2.MORPH_OPEN, kernel)

    # --- Phase 2: recovery cues (illumination-robust, additive) ---
    mask_recover = np.zeros((H, W), dtype=np.uint8)
    edges_raw = np.zeros((H, W), dtype=np.uint8)
    mask_tex = np.zeros((H, W), dtype=np.uint8)
    if seg.get("use_edge_cue", True):
        edge_fill, edges_raw = _edge_mask(cue_gray, bg_cue_gray, seg)
        mask_recover = cv2.bitwise_or(mask_recover, edge_fill)
    if seg.get("use_texture_cue", True):
        mask_tex = _texture_mask(cue_gray, bg_cue_gray, seg, kernel)
        mask_recover = cv2.bitwise_or(mask_recover, mask_tex)

    # --- Phase 3: fuse, find candidates, select the object ---
    mask_union = cv2.bitwise_or(mask_region, mask_recover)
    rk = int(seg.get("recover_close_kernel", 25)) | 1
    rkernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (rk, rk))
    # Close with the larger recovery kernel: a weakly-marked junction (e.g. the
    # neck between a spoon's shiny bowl and its dim handle) must not split the
    # object into two blobs of which only one would be selected.
    mask_union = _close(mask_union, rkernel)

    contours, _ = cv2.findContours(mask_union, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours = [c for c in contours if cv2.contourArea(c) >= float(seg["min_area_px"])]
    if not contours:
        raise SegmentationError(
            "No object found. Is the box empty, or is diff_threshold too high?"
        )

    blob, n_plausible = _select_object(contours, seg, W, H, margin)
    if blob is None:
        raise SegmentationError(
            "Only border/noise blobs found – no plausible object. "
            "Center the item and check lighting/background."
        )

    # --- Phase 4: final silhouette – ONE rule for every object: tight where
    # there is per-pixel evidence, generous where the object is dark. From the
    # located blob only the UNSUPPORTED outer boundary band is removed (that
    # band is the dilation halo of the recovery cues). Dark real parts without
    # evidence – a spoon neck or the shadow side of a bowl mirroring the black
    # floor – lie deeper than the band and stay. This replaces the former
    # region-vs-recovered path split, whose two branches each cut dark object
    # parts in a different way.
    blob_fill = np.zeros((H, W), dtype=np.uint8)
    cv2.drawContours(blob_fill, [blob], -1, 255, thickness=cv2.FILLED)
    # Solidify: where the cues cover a dark object part only raggedly (shadow
    # side of a bowl), the raw contour meanders inward and the outer-band
    # trim below would land DEEP inside that real part and hollow it out.
    # Closing removes the fjords; slots sealed by it are re-opened by the
    # carve at the end.
    blob_fill = _close(blob_fill, rkernel)
    blob_area = float(cv2.countNonZero(blob_fill))

    # --- Phase 4a: optional NEURAL silhouette (MobileSAM), prompted fully
    # automatically from the located blob. Pixel-precise on reflective steel;
    # everything below stays as the automatic fallback (model not installed,
    # checkpoint missing, or implausible output).
    contour = None
    neural_mask = None
    if seg.get("neural", {}).get("enabled", False):
        from .neural_seg import neural_silhouette
        evidence_strong = cv2.bitwise_and(
            np.where(diff >= int(seg["diff_threshold"]),
                     np.uint8(255), np.uint8(0)), blob_fill)
        neural_mask = neural_silhouette(image, blob_fill, cfg,
                                        evidence=evidence_strong)
        if neural_mask is not None:
            # Safety net: SAM judges by appearance, so an object part that
            # perfectly mirrors the floor (shadow side of a bowl, a dim
            # handle) can be dropped although the locator blob contains it.
            # Reinstate substantial DEEP blob-core regions missing from the
            # neural mask – genuine slots among them are re-opened by the
            # carve right below, thin halo rests stay excluded via the
            # width floor.
            hk_n = (int(seg.get("edge_dilate_kernel", 5)) | 1) + 4
            core = cv2.erode(blob_fill, cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE, (hk_n, hk_n)))
            missing = cv2.subtract(core, neural_mask)
            nmiss, mlabels, mstats, _ = cv2.connectedComponentsWithStats(
                missing, connectivity=8)
            for i in range(1, nmiss):
                if mstats[i, cv2.CC_STAT_AREA] < 500:
                    continue
                mx, my, mw, mh = mstats[i, cv2.CC_STAT_LEFT], \
                    mstats[i, cv2.CC_STAT_TOP], mstats[i, cv2.CC_STAT_WIDTH], \
                    mstats[i, cv2.CC_STAT_HEIGHT]
                comp = np.pad((mlabels[my:my + mh, mx:mx + mw] == i).astype(np.uint8), 1)
                if cv2.distanceTransform(comp, cv2.DIST_L2, 3).max() < 8:
                    continue  # thin halo remnant, not a real part
                neural_mask[my:my + mh, mx:mx + mw][comp[1:-1, 1:-1] > 0] = 255
            ncnts, _ = cv2.findContours(neural_mask, cv2.RETR_EXTERNAL,
                                        cv2.CHAIN_APPROX_SIMPLE)
            if ncnts:
                contour = max(ncnts, key=cv2.contourArea)

    if contour is None:
        # Boundary evidence must be TIGHT: the strong diff (its skirt is only
        # ~3px, same as classic background subtraction), the raw undilated
        # edges, the de-smeared texture map – and the FAINT diff only after
        # eroding away its wide blur skirt, so a dim part supports its
        # interior without inflating any boundary.
        thr_main = int(seg["diff_threshold"])
        low_thr = int(seg.get("refine_diff_threshold", max(10, thr_main // 2)))
        wk = (int(seg["blur_kernel"]) | 1) + 2
        weak_core = cv2.erode(
            np.where(diff >= low_thr, np.uint8(255), np.uint8(0)),
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (wk, wk)))
        supported = np.where(diff >= thr_main, np.uint8(255), np.uint8(0))
        supported = cv2.bitwise_or(supported, weak_core)
        supported = cv2.bitwise_or(supported, edges_raw)
        tk = int(seg.get("texture_kernel", 15)) | 1
        tex_tight = cv2.erode(mask_tex,
                              cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (tk, tk)))
        supported = cv2.bitwise_or(supported, tex_tight)
        supported = cv2.bitwise_and(supported, blob_fill)

        hk = (int(seg.get("edge_dilate_kernel", 5)) | 1) + 4
        band = cv2.subtract(blob_fill, cv2.erode(
            blob_fill, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (hk, hk))))
        refined = cv2.subtract(blob_fill, cv2.subtract(band, supported))

        ec, _ = cv2.findContours(refined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        best_e = max(ec, key=cv2.contourArea) if ec else None
        if (best_e is not None and blob_area > 0
                and cv2.contourArea(best_e) >=
                float(seg.get("refine_min_frac", 0.5)) * blob_area):
            contour = best_e
        else:
            # evidence too sparse to trust – fall back to the solidified blob
            solid = _close(blob_fill, rkernel)
            sc, _ = cv2.findContours(solid, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            contour = max(sc, key=cv2.contourArea) if sc else blob

    # Fill only the chosen contour into a clean mask (drop stray blobs, fill
    # specular-highlight holes).
    clean = np.zeros((H, W), dtype=np.uint8)
    cv2.drawContours(clean, [contour], -1, 255, thickness=cv2.FILLED)

    # Border flag from the UNCARVED silhouette: carving only shrinks, and a
    # frame-clipped object must stay flagged even if the clipped part looked
    # like background (reflective handle crossing the frame edge). On the
    # neural path the flag comes from the LOCATOR blob – strictly more
    # conservative than the model mask.
    x, y, w, h = cv2.boundingRect(blob if neural_mask is not None else contour)
    touches = (
        x <= margin or y <= margin
        or x + w >= W - margin or y + h >= H - margin
    )

    # --- Phase 5: re-open bridged open concavities (fork-tine slots) ---
    # Also on the neural path: SAM's 256px mask decoder can seal thin slots
    # even though the rest of the silhouette is pixel-precise – the carve
    # re-opens them from the raw background difference.
    if seg.get("carve_concavities", True):
        # sharper diff for the carve: the heavy region blur bleeds bright tine
        # light into narrow/tapered slots and would lift their centre above
        # the background level
        diff_sharp = cv2.absdiff(cue_gray, bg_cue_gray)
        clean, contour = _carve_open_concavities(clean, contour, diff_sharp, seg)

    debug = {"region": mask_region, "recover": mask_recover, "union": mask_union,
             "n_plausible": n_plausible}
    if neural_mask is not None:
        debug["neural"] = neural_mask
    return SegmentationResult(
        mask=clean,
        contour=contour,
        touches_border=touches,
        area_px=float(cv2.contourArea(contour)),
        debug=debug,
    )
