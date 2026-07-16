"""Foreground segmentation as ONE global optimization (graph cut / MRF).

Design rationale (rewritten from scratch after the per-pixel/per-component
heuristic tower kept failing on real mirror-steel cutlery): a human does not
classify pixels – they perceive the closed region whose boundary follows the
visible edges. Formally that is a binary labeling with spatial coherence, and
it has an EXACT global solution.

THERE ARE NO TUNABLES. The engine self-calibrates every threshold from the
image pair itself; the constants below encode physics/geometry of the photo
box, not lighting. Rationale per stage:

1. EVIDENCE: per-pixel object evidence from the empty-box reference – the
   per-channel background difference, plus local texture excess (a mirror-dark
   handle carries reflection streaks; the matte floor is flat). Min-filtered so
   texture never smears beyond the true edge. The FLOOR NOISE CEILING (what
   the empty floor maximally produces) is measured per image via sigma
   clipping – every evidence threshold derives from it, so lighting drift
   re-calibrates everything automatically.
2. LOCATE: strong-evidence components give the ROI (union of all substantial
   components – a mirror-dark neck may split the object's evidence in two).
   The window SELF-EXPANDS: whenever the mask or any non-floor structure
   presses against a ROI edge that is not the frame edge, the window grows
   and the cut is re-solved – otherwise weak-evidence parts (glint-outlined
   mirror handles) would be silently amputated and a frame-crossing object
   could escape the border flag.
3. GRAPH CUT (the core): the data term only claims what is CERTAIN – floor
   pull below the measured noise ceiling, object pull on seeds. Seeds are
   the top half of each component's own evidence range (self-scaling: bloom
   glow around a bright object never reaches half its peak) plus textured
   pixels (the matte floor never shows texture excess; glow is smooth).
   EVERYTHING ELSE IS NEUTRAL – mirror zones, glow, shadows – and is decided
   by the contrast-sensitive smoothness: label changes are only cheap across
   visible edges, so the globally optimal boundary snaps onto the crisp
   physical contour and rejects the softly fading glow by itself.
4. COMPLETION (the human amodal rule), two levels: a pixel is object if
   every path from the true outside crosses a visible edge. Level 1 uses
   STRONG edges (steps, not ramps: a real metal edge concentrates its
   transition in 1-2 px, Sobel >= ~100, while glow/shadow ramps spread over
   many pixels, <= ~30) – zones they enclose become object even when only
   one object part borders them (mirror-dark bowl wedges). Level 2 BRIDGES
   two separate object components (a mirror neck between fork head and
   handle) through their distance lens – the shortest channel between the
   facing ends – when that channel contains substantially non-floor
   material: completing a gap between two parts is amodal perception,
   annexing a one-sided fringe (glow!) is not. Fork-tine slots open through
   edge-free mouths in both levels -> floor.
5. SNAP: the final contour is pulled onto the strongest nearby image
   gradients (manufactured cutlery has smooth outlines; corrections are
   smoothed along the contour, the base geometry keeps its sharp features).

Stage-1 dependencies: opencv, numpy, scipy (maximum_flow only).
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

# ---- internal constants (physics/geometry of the box, NOT lighting) ----
FLOOR_CLIP_SIGMA = 4.0    # floor ceiling = mean + 4*std of the clipped floor
LOCATOR_FACTOR = 5.0      # presence needs evidence 5x above the floor ceiling
LOCATOR_MIN = 10.0        # ...but never below 10 gray (sensor quantization)
SEED_FRACTION = 0.5       # object seeds = top half of a component's own range
COST_FLOOR = 80.0         # data pull toward floor (per px, sure-floor zone)
COST_SEED = 300.0         # data pull toward object (per px, seed zone)
COST_NONFLOOR = 0.25      # WEAK object preference for measurably-non-floor
                          # pixels: breaks exact ties toward object (a dim
                          # part behind the body's own strong edge is
                          # unreachable for flow and would default to floor).
                          # Deliberately tiny: large dim parts still win
                          # (area x 0.25 >> their cheap edge cut) but a
                          # glow-filled tine slot (small area) can never pay
                          # the cut across its edge-free mouth (~60/px)
LAM = 60.0                # smoothness: full price of cutting flat material
BETA_NUM = 0.105          # exp(-beta*step^2)=0.9 at the reference noise step
WALL_MIN_GRAD = 32.0      # edges are steps not ramps: real edges Sobel>=~100,
WALL_BG_FACTOR = 2.0      # glow/shadow ramps <=~30; scaled up on noisy floors
ILLUM_ANCHOR = 24.0       # floor gray at which BETA_NUM/WALL_MIN_GRAD were
                          # validated. Glow (bloom) and its rim gradients
                          # scale with ILLUMINATION, not with sensor noise -
                          # so these two gray-value constants must scale with
                          # the measured floor level or brighter lighting
                          # turns glow rims into "real edges" (user-found
                          # failure: slots sealed after re-lighting 2026-07-16)
BRIDGE_DENSITY = 0.10     # min fraction of above-ceiling px in a bridge lens
                          # (mirror necks carry 20-40%, true floor <1%)
NOTCH_KERNEL = 181        # concavity candidates: mask-close up to this mouth
                          # (wide enough for a fork's mirror heel; slots are
                          # protected by the visibility/density gates, not
                          # by the kernel size)
NOTCH_VIS_MAX = 0.45      # fill only if the boundary is INVISIBLE (slots have
NOTCH_DENS_MIN = 0.35     # visible tine edges >=0.8) and non-floor inside
MIN_AREA_FRAC = 0.01      # smallest measurable item covers ~1% of the frame
BORDER_MARGIN = 5         # px to the frame edge that count as "touching"
ROI_PAD = 40              # initial ROI padding around strong evidence


@dataclass
class SegmentationResult:
    mask: np.ndarray          # uint8 {0,255}, same size as input
    contour: np.ndarray       # largest external contour (Nx1x2 int32)
    touches_border: bool
    area_px: float
    # Intermediate maps ("evidence"/"cut"/"completed") so a UI can show what
    # each stage saw – tuning aid, not part of the matching data.
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
    """MORPH_CLOSE with outside-the-frame = background (zero-padded close).
    OpenCV's default border value for the erode half is +inf, which welds
    anything near the image border into a slab touching the border."""
    r = max(k.shape[0], k.shape[1]) // 2 + 1
    p = cv2.copyMakeBorder(m, r, r, r, r, cv2.BORDER_CONSTANT, value=0)
    p = cv2.morphologyEx(p, cv2.MORPH_CLOSE, k)
    return p[r:-r, r:-r]


def _local_std(gray: np.ndarray, tk: int) -> np.ndarray:
    g = gray.astype(np.float32)
    mean = cv2.boxFilter(g, -1, (tk, tk))
    mean_sq = cv2.boxFilter(g * g, -1, (tk, tk))
    return np.sqrt(np.maximum(mean_sq - mean * mean, 0.0))


def floor_ceiling(values: np.ndarray) -> float:
    """Highest value the empty floor produces in an evidence map: iterative
    sigma clipping starting from the guaranteed-floor lower percentiles, so
    the estimate is robust against the object covering up to ~50% of the
    frame (more cannot fit the box FOV). This ONE measured number anchors
    every threshold in the engine."""
    s = values[::4, ::4].astype(np.float32)
    m = s <= np.percentile(s, 50.0)
    mu = sd = 0.0
    for _ in range(4):
        mu, sd = float(s[m].mean()), float(s[m].std())
        m = s <= mu + FLOOR_CLIP_SIGMA * sd
    return max(2.0, mu + FLOOR_CLIP_SIGMA * sd)


# ---------- object selection (noise rejection among final components) ----------

def _border_frac(contour: np.ndarray, margin: int, W: int, H: int) -> float:
    """Fraction of the contour's arc length running along the frame border."""
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


def _select_object(contours: list, W: int, H: int, margin: int):
    """Pick the most object-like contour; reject small border-hugging noise
    blobs but never a large object. Returns (contour|None, n_plausible)."""
    frame_area = float(W * H)
    large_frac = 0.02
    min_sol = 0.30
    max_border = 0.35
    pen_w = 0.5

    best, best_score, plausible = None, -1.0, 0
    for c in contours:
        area = float(cv2.contourArea(c))
        is_large = area >= large_frac * frame_area
        bfrac = _border_frac(c, margin, W, H)
        sol = _solidity(c, area)
        if not is_large and (bfrac > max_border or sol < min_sol):
            continue
        plausible += 1
        cen = _centrality(c, W, H)
        score = area * max(sol, 1e-3) * (0.5 + 0.5 * cen) * (1.0 - pen_w * bfrac)
        if score > best_score:
            best, best_score = c, score
    return best, plausible


# ---------- contour snap (edge-truth polish) ----------

def _snap_contour_to_edges(mask: np.ndarray, gray: np.ndarray, wall_grad: float):
    """Pull every contour point along its local normal onto the strongest
    nearby image gradient; smooth the CORRECTION field along the contour so
    the outline stays manufactured-smooth while sharp base features (tine
    tips) survive. Points already sitting on a strong edge stay frozen.
    NO BOUNDARY WITHOUT AN EDGE: a point that finds no edge at all nearby
    (the cut sliced through a mirror wedge whose true outline is farther
    out, e.g. a fork heel) searches OUTWARD-ONLY for the nearest strong
    edge and jumps onto it – outward can only reclaim missed object, never
    annex glow, because glow boundaries sit on the (strong) true edge and
    are frozen."""
    search = 8
    reach = 48
    min_grad = 0.75 * wall_grad
    win = 15
    iters = 2
    freeze_grad = 1.5 * wall_grad

    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    gmag = cv2.magnitude(gx, gy)
    H, W = gray.shape

    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not cnts:
        return mask, None
    base = max(cnts, key=cv2.contourArea).reshape(-1, 2).astype(np.float32)
    if len(base) < 40:
        return mask, None
    pts = base.copy()
    kernel = np.ones(win, np.float32) / win
    offs = np.arange(-search, search + 1, dtype=np.float32)
    prior = np.exp(-(offs / (search * 0.75)) ** 2)

    for _ in range(iters):
        t = np.roll(pts, -4, axis=0) - np.roll(pts, 4, axis=0)
        norm = np.stack([-t[:, 1], t[:, 0]], axis=1)
        length = np.linalg.norm(norm, axis=1, keepdims=True)
        length[length == 0] = 1.0
        norm /= length
        # ensure the normals point OUTWARD (the extended search must never
        # eat into the object): probe the mask a few px along the normal
        px = np.clip(np.round(pts[:, 0] + norm[:, 0] * 3).astype(np.int32), 0, W - 1)
        py = np.clip(np.round(pts[:, 1] + norm[:, 1] * 3).astype(np.int32), 0, H - 1)
        if float((mask[py, px] > 0).mean()) > 0.5:
            norm = -norm
        sample = pts[:, None, :] + norm[:, None, :] * offs[None, :, None]
        xi = np.clip(np.round(sample[:, :, 0]).astype(np.int32), 0, W - 1)
        yi = np.clip(np.round(sample[:, :, 1]).astype(np.int32), 0, H - 1)
        vals = gmag[yi, xi]
        weighted = vals * prior[None, :]
        best_idx = np.argmax(weighted, axis=1)
        best_val = vals[np.arange(len(pts)), best_idx]
        shift = offs[best_idx]
        shift[best_val < min_grad] = 0.0
        # no boundary without an edge: edge-less points jump outward onto
        # the NEAREST strong edge (the outline the cut missed), if any –
        # but never onto ANOTHER part's outline: if object mask lies shortly
        # beyond the found edge, this is a slot/gap between parts, not a
        # missed outline (beyond a true outline there is only floor)
        lost = best_val < min_grad
        if lost.any():
            ext = np.arange(search + 1, reach + 1, dtype=np.float32)
            es = pts[lost, None, :] + norm[lost, None, :] * ext[None, :, None]
            exi = np.clip(np.round(es[:, :, 0]).astype(np.int32), 0, W - 1)
            eyi = np.clip(np.round(es[:, :, 1]).astype(np.int32), 0, H - 1)
            evals = gmag[eyi, exi] >= wall_grad
            hit = evals.any(axis=1)
            first = np.argmax(evals, axis=1).astype(np.float32) + search + 1
            beyond_obj = np.zeros(len(first), bool)
            for probe in (5.0, 10.0, 15.0):
                bp = (pts[lost] + norm[lost] * (first[:, None] + probe))
                bxi = np.clip(np.round(bp[:, 0]).astype(np.int32), 0, W - 1)
                byi = np.clip(np.round(bp[:, 1]).astype(np.int32), 0, H - 1)
                beyond_obj |= mask[byi, bxi] > 0
            eshift = np.where(hit & ~beyond_obj, first, 0.0)
            shift[lost] = eshift
        freeze = vals[:, search] >= freeze_grad
        shift[freeze] = 0.0
        pad = win // 2
        shift_smooth = np.convolve(
            np.concatenate([shift[-pad:], shift, shift[:pad]]), kernel, "valid")
        pts = pts + norm * shift_smooth[:, None]

    poly = np.round(pts).astype(np.int32)
    out = np.zeros_like(mask)
    cv2.fillPoly(out, [poly], 255)
    cnts, _ = cv2.findContours(out, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return mask, None
    best = max(cnts, key=cv2.contourArea)
    a0, a1 = float(cv2.countNonZero(mask)), float(cv2.contourArea(best))
    if a0 <= 0 or not (0.85 <= a1 / a0 <= 1.15):
        return mask, None
    final = np.zeros_like(mask)
    cv2.drawContours(final, [best], -1, 255, thickness=cv2.FILLED)
    return final, best


# ---------- edge-sealed completion helpers ----------

def _enclosed_zones(gmag: np.ndarray, obj_mask: np.ndarray, grad_thr: float,
                    roi: tuple) -> np.ndarray:
    """Zones inside the ROI from which every path to the ROI border crosses
    an edge (gradient >= grad_thr) or the object mask itself: flood fill from
    the border with edges+object as walls; whatever the flood cannot reach –
    and is not object already – is enclosed. Returns a bool array (ROI size)."""
    y0, y1, x0, x1 = roi
    walls = np.where((gmag >= grad_thr) | (obj_mask > 0),
                     np.uint8(255), np.uint8(0))
    walls_roi = cv2.dilate(walls[y0:y1, x0:x1],
                           cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
    free = cv2.bitwise_not(walls_roi)
    nfr, flab = cv2.connectedComponents(free, connectivity=8)
    border_labels = np.unique(np.concatenate(
        [flab[0], flab[-1], flab[:, 0], flab[:, -1]]))
    outside = np.isin(flab, border_labels[border_labels != 0]) & (free > 0)
    return (free > 0) & ~outside


def _fill_invisible_notches(mask: np.ndarray, gmag: np.ndarray,
                            d_eff: np.ndarray, ceil_d: float,
                            wall_grad: float) -> np.ndarray:
    """Amodal completion of one-sided mirror wedges (a fork's heel whose
    upper outline is optically invisible): candidate = concavities of the
    mask (large morphological close). Fill a candidate only when (a) its
    contact boundary with the object is INVISIBLE (a slot's boundary is the
    brightly visible tine edge – a human sees a real gap; the heel's cut-off
    line is no image edge at all – the human infers continuation) and (b) it
    contains substantially non-floor material. Glow can never qualify: it
    lies outside the silhouette and creates no concavity. Iterative: each
    fill narrows the remaining mouth, so wide wedges close in 2-3 rounds."""
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                       (NOTCH_KERNEL, NOTCH_KERNEL))
    out = mask.copy()
    for _ in range(3):
        cand = cv2.subtract(_close(out, kernel), out)
        n, lab, st, _ = cv2.connectedComponentsWithStats(cand, connectivity=8)
        filled = False
        for j in range(1, n):
            if st[j, cv2.CC_STAT_AREA] < 300:
                continue
            m = (lab == j).astype(np.uint8)
            dens = float((d_eff[m > 0] >= ceil_d).mean())
            if dens < NOTCH_DENS_MIN:
                continue
            ring = (cv2.dilate(m, np.ones((5, 5), np.uint8)) > 0) & (m == 0)
            contact = ring & (out > 0)
            if int(contact.sum()) <= 20:
                continue
            vis = float((gmag[contact] >= wall_grad).mean())
            if vis <= NOTCH_VIS_MAX:
                out[m > 0] = 255
                filled = True
        if not filled:
            break
    return out


def _bridging_zones(obj_roi: np.ndarray, d_roi: np.ndarray,
                    ceil_d: float) -> np.ndarray:
    """Amodal bridge between SEPARATE object components (mirror neck between
    fork head and handle). The DISTANCE LENS of a component pair – all
    pixels whose summed distance to both parts is (near) minimal – is
    exactly the shortest channel between their facing ends, nowhere else.
    The lens is filled only when it contains substantially non-floor
    material: a mirror neck always carries scattered above-noise reflections
    (20-40% of its pixels), true floor stays under ~1% by construction of
    the sigma-clipped ceiling. A one-sided glow fringe has no partner
    component; the floor between two genuinely separate items fails the
    density gate; fork-tine slots lie within one component and are never
    touched."""
    out = np.zeros(obj_roi.shape, bool)
    n_o, olab, ost, _ = cv2.connectedComponentsWithStats(obj_roi, connectivity=8)
    comps = [j for j in range(1, n_o) if ost[j, cv2.CC_STAT_AREA] >= 300]
    if len(comps) < 2:
        return out
    above = d_roi >= ceil_d
    dist = {j: cv2.distanceTransform(
        (olab != j).astype(np.uint8), cv2.DIST_L2, 3) for j in comps}
    for a in range(len(comps)):
        for b in range(a + 1, len(comps)):
            s = dist[comps[a]] + dist[comps[b]]
            gap = float(s.min())
            # bridge only across gaps shorter than the smaller part itself –
            # a neck is always short relative to the pieces it connects
            if gap > 0.75 * np.sqrt(float(min(ost[comps[a], cv2.CC_STAT_AREA],
                                              ost[comps[b], cv2.CC_STAT_AREA]))):
                continue
            lens = (s <= gap + max(6.0, 0.10 * gap)) & (obj_roi == 0)
            if not lens.any():
                continue
            if float(above[lens].mean()) >= BRIDGE_DENSITY:
                out |= lens
    return out


# ---------- the graph-cut core ----------

def _graphcut_labels(d_eff: np.ndarray, gray: np.ndarray, seeds: np.ndarray,
                     ceil_d: float, beta: float) -> np.ndarray:
    """Globally optimal object/background labeling of the ROI.
    Data term claims only certainty: floor pull below the measured noise
    ceiling, object pull on the seeds; everything between is NEUTRAL and is
    decided by the contrast-sensitive smoothness (label changes are cheap
    only across visible image edges). Solved exactly with maximum_flow."""
    try:
        from scipy.sparse import csr_matrix
        from scipy.sparse.csgraph import breadth_first_order, maximum_flow
    except ImportError as e:  # pragma: no cover
        raise SegmentationError(
            "scipy fehlt (pip install -r requirements.txt) – wird für die "
            "Graph-Cut-Segmentierung benötigt.") from e

    d = d_eff.astype(np.float32)
    g = gray.astype(np.float32)
    hh, ww = d.shape
    N = hh * ww

    # floor pull fades from full at the noise ceiling to zero at 2x ceiling;
    # seeds are locked to object; in between, measurably-non-floor pixels
    # get a WEAK object preference (tie-breaker, see COST_NONFLOOR) ramping
    # up to full weak strength at the presence level (5x ceiling)
    cost_obj = np.clip((2.0 * ceil_d - d) / ceil_d, 0, 1) * COST_FLOOR
    weak = COST_NONFLOOR * np.clip((d - 2.0 * ceil_d) / (3.0 * ceil_d), 0, 1)
    cost_bg = np.where(seeds > 0, COST_SEED, weak).astype(np.float32)
    cost_obj[seeds > 0] = 0.0
    # anchor the ROI frame ring to background – but ONLY where the ring is
    # actual floor. Where object/glow structure crosses the ring, leave the
    # data free so the mask can reach it (ring-touch drives ROI expansion,
    # frame-edge touch drives the border flag).
    ring = np.zeros((hh, ww), bool)
    ring[0, :] = ring[-1, :] = True
    ring[:, 0] = ring[:, -1] = True
    anchor = ring & (d < 2.0 * ceil_d)
    cost_obj[anchor] = 1000.0
    cost_bg[anchor] = 0.0

    dr = np.abs(g[:, 1:] - g[:, :-1])
    dd = np.abs(g[1:, :] - g[:-1, :])
    w_r = LAM * np.exp(-beta * dr ** 2)
    w_d = LAM * np.exp(-beta * dd ** 2)

    # graph size is bounded by the frame: a full-frame ROI (1920x1080) peaks
    # around ~1 GB transient working set in maximum_flow – fine on a desktop,
    # relevant if this ever moves to small/embedded hardware
    idx = np.arange(N).reshape(hh, ww)
    r1, r2 = idx[:, :-1].ravel(), idx[:, 1:].ravel()
    d1, d2 = idx[:-1, :].ravel(), idx[1:, :].ravel()
    all_px = idx.ravel()
    rows = np.concatenate([r1, r2, d1, d2, np.full(N, N), all_px])
    cols = np.concatenate([r2, r1, d2, d1, all_px, np.full(N, N + 1)])
    caps = np.concatenate([w_r.ravel(), w_r.ravel(), w_d.ravel(), w_d.ravel(),
                           cost_bg.ravel(), cost_obj.ravel()])
    caps_i = np.maximum(0, np.round(caps * 10)).astype(np.int32)
    graph = csr_matrix((caps_i, (rows, cols)), shape=(N + 2, N + 2))

    flow = maximum_flow(graph, N, N + 1).flow
    residual = graph - flow
    residual.data = np.maximum(residual.data, 0)
    residual.eliminate_zeros()
    reach, _ = breadth_first_order(residual, N, directed=True,
                                   return_predecessors=True)
    obj_nodes = reach[(reach >= 0) & (reach < N)]
    labels = np.zeros(N, np.uint8)
    labels[obj_nodes] = 255
    return labels.reshape(hh, ww)


# ---------- main entry ----------

def segment(image: np.ndarray, background: np.ndarray) -> SegmentationResult:
    """Self-calibrating segmentation of the single object in the box.
    There is deliberately NO cfg parameter – the engine has no tunables;
    every threshold derives from the image pair itself."""
    if image.shape != background.shape:
        raise SegmentationError(
            f"Image {image.shape} vs background {background.shape} mismatch. "
            "Recapture the background at the current camera settings."
        )

    H, W = image.shape[:2]
    margin = BORDER_MARGIN
    min_area = MIN_AREA_FRAC * H * W

    # --- 1. evidence + self-calibration ---
    cue = cv2.GaussianBlur(image, (3, 3), 0).astype(np.int16)
    bgc = cv2.GaussianBlur(background, (3, 3), 0).astype(np.int16)
    diff = cue.astype(np.float32) - bgc.astype(np.float32)
    # illumination-drift compensation: a lamp warming up shifts the WHOLE
    # floor additively vs the stored background; the per-channel median of
    # the signed difference (floor-dominated, object <=50%) measures that
    # offset exactly – subtract it so dim mirror parts are not swallowed by
    # a drift-inflated noise ceiling
    for ch in range(diff.shape[2]):
        diff[:, :, ch] -= float(np.median(diff[::4, ::4, ch]))
    d_diff = np.abs(diff).max(axis=2).astype(np.float32)
    gray = cv2.cvtColor(cv2.GaussianBlur(image, (3, 3), 0), cv2.COLOR_BGR2GRAY)
    bg_gray = cv2.cvtColor(cv2.GaussianBlur(background, (3, 3), 0),
                           cv2.COLOR_BGR2GRAY)
    tk = 15
    # texture on the RAW grayscale – blurring first would destroy exactly the
    # fine reflection signal this channel measures
    gray_raw = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    bg_raw = cv2.cvtColor(background, cv2.COLOR_BGR2GRAY)
    tex = np.maximum(0, _local_std(gray_raw, tk) - _local_std(bg_raw, tk))
    tex = cv2.erode(tex, cv2.getStructuringElement(cv2.MORPH_RECT, (tk, tk)))
    tex2 = 2.0 * tex
    # texture may only vouch for a pixel that is ITSELF measurably non-floor:
    # a narrow slot between textured metal inherits the neighbors' local-std
    # (the window overlaps them), but true floor seen through the slot has
    # zero brightness difference – mirror-steel streaks do not
    ceil_diff = floor_ceiling(d_diff)
    tex_valid = np.where(d_diff >= 2.0 * ceil_diff, tex2, 0.0).astype(np.float32)
    d_eff = np.maximum(d_diff, tex_valid)

    ceil_d = floor_ceiling(d_eff)          # the floor's evidence ceiling
    ceil_t = floor_ceiling(tex2)           # the floor's texture ceiling
    t_loc = max(LOCATOR_MIN, LOCATOR_FACTOR * ceil_d)

    # illumination level of this lighting era, relative to the anchor the
    # gray-value constants were validated at: glow amplitude and glow-rim
    # gradients scale with lighting, sensor noise does not. Clipped to the
    # realistic lamp/exposure range of the SAME black floor mat - a bright
    # floor can also mean bright albedo (gray mat), where object contrast
    # does NOT scale with the floor level
    illum = float(np.clip(np.median(bg_gray) / ILLUM_ANCHOR, 0.5, 3.0))

    # smoothness contrast scale: cutting across floor noise OR glow-rim
    # ramps (both scale with illumination) costs ~full LAM, real edges are
    # nearly free
    bg_step = max(1.0, illum, float(np.percentile(
        np.abs(bg_gray[:, 1:].astype(np.float32)
               - bg_gray[:, :-1].astype(np.float32)), 99.5)))
    beta = BETA_NUM / bg_step ** 2

    # --- 2. locate ROI + object seeds ---
    strong = np.where(d_eff >= t_loc, np.uint8(255), np.uint8(0))
    strong_d = cv2.dilate(strong, cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (25, 25)))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(strong_d, connectivity=8)
    boxes = []
    seeds = np.zeros((H, W), np.uint8)
    for j in range(1, n):
        if stats[j, cv2.CC_STAT_AREA] < max(300.0, min_area / 20.0):
            continue
        boxes.append(stats[j])
        # seeds = top half of THIS component's own evidence range. Bloom glow
        # around a bright part stays far below half its peak, so glow is
        # never seeded; dim objects self-scale their seed level down.
        sl = (slice(stats[j, cv2.CC_STAT_TOP],
                    stats[j, cv2.CC_STAT_TOP] + stats[j, cv2.CC_STAT_HEIGHT]),
              slice(stats[j, cv2.CC_STAT_LEFT],
                    stats[j, cv2.CC_STAT_LEFT] + stats[j, cv2.CC_STAT_WIDTH]))
        comp = labels[sl] == j
        peak = float(d_eff[sl][comp].max())
        t_seed = max(t_loc, SEED_FRACTION * peak)
        seeds[sl][comp & (d_eff[sl] >= t_seed)] = 255
    if not boxes:
        raise SegmentationError(
            "No usable object found - box empty, object too large for the "
            "frame, or lighting changed since the background capture?"
        )
    # NOTE: texture contributes to the evidence (locator, bands, gates) but
    # NEVER seeds on its own. Local-std windows straddling any strong edge
    # produce high-texture bands a few px wide on BOTH sides (optical blur
    # widens them past what the min-filter can erode), so texture anchors
    # inevitably leak into tine slots and glow zones along the outline -
    # at any window size. Dim mirror parts are carried by neutrality +
    # edges, the weak pull, and the amodal completion stages instead.

    bx = min(b[cv2.CC_STAT_LEFT] for b in boxes)
    by = min(b[cv2.CC_STAT_TOP] for b in boxes)
    bx2 = max(b[cv2.CC_STAT_LEFT] + b[cv2.CC_STAT_WIDTH] for b in boxes)
    by2 = max(b[cv2.CC_STAT_TOP] + b[cv2.CC_STAT_HEIGHT] for b in boxes)
    x0, y0 = max(0, bx - ROI_PAD), max(0, by - ROI_PAD)
    x1, y1 = min(W, bx2 + ROI_PAD), min(H, by2 + ROI_PAD)

    # --- 3+4. graph cut + completion, in a self-expanding window ---
    # Sobel walls for the completion are ROI-independent – compute once.
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    gmag = cv2.magnitude(gx, gy)
    # wall threshold: real edges are STEPS (transition in 1-2 px, Sobel
    # >= ~100) while glow/shadow RAMPS spread over many px (<= ~30); scaled
    # up when the reference floor itself is noisy
    bgx = cv2.Sobel(bg_gray, cv2.CV_32F, 1, 0, ksize=3)
    bgy = cv2.Sobel(bg_gray, cv2.CV_32F, 0, 1, ksize=3)
    bg_gmag = cv2.magnitude(bgx, bgy)
    bg_p = float(np.percentile(bg_gmag, 99.5))
    # completion walls scale with illumination (glow-rim ramps grow with the
    # light level); the SNAP keeps the unscaled base - after the cut, the
    # boundary sits on the true edge, which dominates any glow ripple in the
    # snap's local window, and over-freezing would unpin weaker real edges
    snap_grad = max(WALL_MIN_GRAD, WALL_BG_FACTOR * bg_p)
    wall_grad = max(WALL_MIN_GRAD * illum, WALL_BG_FACTOR * bg_p)
    # non-floor structure (for the ROI expansion trigger): opened so a few
    # stray noise pixels at the window edge cannot force an expansion
    hot = np.where(d_eff >= 2.0 * ceil_d, np.uint8(255), np.uint8(0))
    hot = cv2.morphologyEx(hot, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))

    grow = 80
    for _ in range(8):
        # graph cut
        cut_roi = _graphcut_labels(d_eff[y0:y1, x0:x1], gray[y0:y1, x0:x1],
                                   seeds[y0:y1, x0:x1], ceil_d, beta)
        cut = np.zeros((H, W), np.uint8)
        cut[y0:y1, x0:x1] = cut_roi

        n2, lab2, st2, _ = cv2.connectedComponentsWithStats(cut, connectivity=8)
        keep = np.zeros_like(cut)
        for j in range(1, n2):
            if st2[j, cv2.CC_STAT_AREA] >= max(500.0, min_area / 10.0):
                keep[lab2 == j] = 255
        if not keep.any():
            raise SegmentationError(
                "No object found. Is the box empty?"
            )

        # edge-sealed reachability completion, two levels:
        # level 1 – zones enclosed by STRONG edges become object even when
        # only one object part borders them (mirror-dark bowl wedges);
        # level 2 – zones enclosed by FAINT edges too, but only when they
        # BRIDGE two separate object components (mirror neck between fork
        # head and handle). Glow is one-sided and its ripples are faint, so
        # it can never qualify at either level.
        enclosed1 = _enclosed_zones(gmag, keep, wall_grad, (y0, y1, x0, x1))
        completed = keep.copy()
        completed[y0:y1, x0:x1][enclosed1] = 255
        bridges = _bridging_zones(completed[y0:y1, x0:x1],
                                  d_eff[y0:y1, x0:x1], ceil_d)
        if bridges.any():
            completed[y0:y1, x0:x1][bridges] = 255
            # the bridge sealed a leak path (open neck between two parts) –
            # zones enclosed by strong edges may only now be recognizable
            enclosed1b = _enclosed_zones(gmag, completed, wall_grad,
                                         (y0, y1, x0, x1))
            completed[y0:y1, x0:x1][enclosed1b] = 255
        completed = _close(completed, cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (7, 7)))

        # The locator only sees STRONG evidence, but object parts can be far
        # weaker (glint-outlined mirror handle, dim rim). If the mask OR any
        # non-floor structure presses against a ROI edge that is not the
        # frame edge, the window clipped the object: grow and re-solve.
        probe = cv2.bitwise_or(completed, hot)[y0:y1, x0:x1]
        t_l = x0 > 0 and int(np.count_nonzero(probe[:, :2])) >= 5
        t_r = x1 < W and int(np.count_nonzero(probe[:, -2:])) >= 5
        t_t = y0 > 0 and int(np.count_nonzero(probe[:2, :])) >= 5
        t_b = y1 < H and int(np.count_nonzero(probe[-2:, :])) >= 5
        if not (t_l or t_r or t_t or t_b):
            break
        if t_l:
            x0 = max(0, x0 - grow)
        if t_r:
            x1 = min(W, x1 + grow)
        if t_t:
            y0 = max(0, y0 - grow)
        if t_b:
            y1 = min(H, y1 + grow)
        grow *= 2

    # --- 4b. amodal fill of invisible-boundary mirror wedges (fork heel) ---
    completed = _fill_invisible_notches(completed, gmag, d_eff, ceil_d,
                                        wall_grad)

    # --- 5. choose the object among candidates (noise rejection) ---
    contours, _ = cv2.findContours(completed, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    contours = [c for c in contours if cv2.contourArea(c) >= min_area]
    if not contours:
        raise SegmentationError(
            "No usable object found - box empty, object too large for the "
            "frame, or lighting changed since the background capture?"
        )
    blob, n_plausible = _select_object(contours, W, H, margin)
    if blob is None:
        raise SegmentationError(
            "Only border/noise blobs found – no plausible object. "
            "Center the item and check lighting/background."
        )
    clean = np.zeros((H, W), np.uint8)
    cv2.drawContours(clean, [blob], -1, 255, thickness=cv2.FILLED)
    contour = blob

    # --- 6. snap onto the visible edges ---
    new_clean, new_contour = _snap_contour_to_edges(clean, gray, snap_grad)
    if new_contour is not None:
        clean, contour = new_clean, new_contour

    x, y, w, h = cv2.boundingRect(contour)
    touches = (
        x <= margin or y <= margin
        or x + w >= W - margin or y + h >= H - margin
    )
    if not touches:
        # a dim part (mirror steel, texture-only evidence) can cross the
        # frame edge without making it into the mask – if NON-FLOOR
        # STRUCTURE connected to the object reaches the frame edge, the
        # measurement cannot be trusted either
        both = cv2.bitwise_or(hot, clean)
        n_b, lab_b, st_b, _ = cv2.connectedComponentsWithStats(both, connectivity=8)
        for j in np.unique(lab_b[clean > 0]):
            if j == 0:
                continue
            bx, by = st_b[j, cv2.CC_STAT_LEFT], st_b[j, cv2.CC_STAT_TOP]
            bw, bh = st_b[j, cv2.CC_STAT_WIDTH], st_b[j, cv2.CC_STAT_HEIGHT]
            if (bx <= margin or by <= margin
                    or bx + bw >= W - margin or by + bh >= H - margin):
                touches = True
                break

    debug = {"evidence": np.clip(d_eff * 3, 0, 255).astype(np.uint8),
             "cut": cut, "completed": completed, "n_plausible": n_plausible,
             "floor_ceiling": ceil_d, "locator_threshold": t_loc,
             "wall_grad": wall_grad}
    return SegmentationResult(
        mask=clean,
        contour=contour,
        touches_border=touches,
        area_px=float(cv2.contourArea(contour)),
        debug=debug,
    )
