"""Synthetic end-to-end tests: no camera or real photos needed.

We render a fake box floor + a fake plate as image, run segmentation and
feature extraction, and check that the measured diameter matches the drawn
one. This validates the whole measurement chain except the physical camera.

Run: pytest tests/ -v   (or: python -m pytest)
"""

import math
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.calibration import Calibration  # noqa: E402
from docodetect.database import Database  # noqa: E402
from docodetect.features import extract, height_corrected_scale  # noqa: E402
from docodetect.matcher import match  # noqa: E402
from docodetect.pipeline import Pipeline  # noqa: E402
from docodetect.segmentation import segment  # noqa: E402

CFG = {
    "segmentation": {
        "blur_kernel": 7, "diff_threshold": 25, "morph_kernel": 15,
        "min_area_px": 5000, "border_margin_px": 5,
    },
}

MM_PER_PX = 0.2  # synthetic scale
CAL = Calibration(mm_per_px=MM_PER_PX, camera_height_mm=300.0,
                  image_width=1920, image_height=1080,
                  marker_size_mm=50.0, created_unix=0.0)


def make_background(w=1920, h=1080, fill=200):
    bg = np.full((h, w, 3), fill, dtype=np.uint8)
    noise = np.random.default_rng(42).integers(-5, 5, bg.shape, dtype=np.int16)
    return np.clip(bg.astype(np.int16) + noise, 0, 255).astype(np.uint8)


def draw_plate(bg, diameter_mm, center=(960, 540), color=(250, 250, 250)):
    img = bg.copy()
    r_px = int(round(diameter_mm / MM_PER_PX / 2))
    cv2.circle(img, center, r_px, color, thickness=-1)
    cv2.circle(img, center, r_px, (150, 150, 150), thickness=3)  # rim shading
    return img


def test_diameter_measurement_accuracy():
    bg = make_background()
    for d_mm in (160.0, 210.0):
        img = draw_plate(bg, d_mm)
        seg = segment(img, bg, CFG)
        assert not seg.touches_border
        feats = extract(img, seg, CAL)
        assert abs(feats.circle_diameter_mm - d_mm) < 3.0, (
            f"measured {feats.circle_diameter_mm} vs drawn {d_mm}"
        )
        # Pixelated contours overestimate the perimeter, so circularity of a
        # perfect circle lands around ~0.9 rather than 1.0. What matters is
        # that round items score clearly above elongated ones (~0.6-0.7).
        assert feats.circularity > 0.85


def test_border_detection():
    bg = make_background()
    # plate partially outside the frame
    img = draw_plate(bg, 210.0, center=(30, 540))
    seg = segment(img, bg, CFG)
    assert seg.touches_border


def test_height_compensation():
    # 270 mm plate, rim 25 mm above floor, camera at 300 mm:
    # it appears larger by factor 300/275
    apparent = 270.0 * 300.0 / 275.0
    corrected = height_corrected_scale(apparent, 25.0, 300.0)
    assert math.isclose(corrected, 270.0, abs_tol=0.01)


def test_two_plates_distinguishable_by_size():
    """The core use case: 250 vs 270 mm white plates must yield clearly
    different measurements (>> typical tolerance)."""
    bg = make_background()
    d1 = extract(draw_plate(bg, 250.0), segment(draw_plate(bg, 250.0), bg, CFG), CAL)
    d2 = extract(draw_plate(bg, 270.0), segment(draw_plate(bg, 270.0), bg, CFG), CAL)
    assert d2.circle_diameter_mm - d1.circle_diameter_mm > 15.0


# ---------- live article creation (no CSV) ----------

# Fuller config so Pipeline.create_article + matcher.match run end to end.
CREATE_CFG = {
    "segmentation": CFG["segmentation"],
    "matching": {
        "diameter_tolerance_mm": 6.0, "area_tolerance_pct": 12.0,
        "weights": {"geometry": 0.5, "color": 0.3, "shape": 0.2},
        "auto_accept_score": 0.85, "auto_accept_margin": 0.15, "top_k": 3,
    },
    "create": {"round_circularity_min": 0.80, "round_aspect_min": 0.80,
               "article_number_prefix": ""},
    "paths": {"db_file": ":placeholder:"},
}


def draw_bar(bg, length_mm, width_mm, center=(960, 540), color=(170, 170, 170)):
    """An elongated object (spoon/knife stand-in)."""
    img = bg.copy()
    L = int(round(length_mm / MM_PER_PX))
    W = int(round(width_mm / MM_PER_PX))
    x0, y0 = center[0] - L // 2, center[1] - W // 2
    cv2.rectangle(img, (x0, y0), (x0 + L, y0 + W), color, thickness=-1)
    return img


def _pipeline(db_path, background):
    """Pipeline wired to a temp DB + synthetic calibration, no file IO."""
    cfg = dict(CREATE_CFG)
    cfg["paths"] = {"db_file": str(db_path)}
    pipe = Pipeline.__new__(Pipeline)
    pipe.cfg = cfg
    pipe.cal = CAL
    pipe.background = background
    pipe.db = Database(cfg)
    pipe.db.init_schema()
    return pipe, cfg


def test_create_round_article_then_identify(tmp_path):
    bg = make_background()
    pipe, cfg = _pipeline(tmp_path / "t.sqlite3", bg)
    try:
        article, feats, _ = pipe.create_article(draw_plate(bg, 200.0), "Testteller")
        # round -> diameter_mm, no width/depth
        assert article.diameter_mm is not None and article.width_mm is None
        assert abs(article.diameter_mm - 200.0) < 3.0
        # stored as a reference -> identifiable immediately, not geometry-only
        result = match(feats, pipe.db, CAL, cfg)
        assert result.candidates
        assert result.candidates[0].article.article_number == article.article_number
        assert result.candidates[0].has_references
    finally:
        pipe.db.close()


def test_create_elongated_article_survives_area_check(tmp_path):
    """A spoon stored with diameter_mm would be killed by the matcher's area
    plausibility check on re-identify; width/depth must be used instead."""
    bg = make_background()
    pipe, cfg = _pipeline(tmp_path / "t.sqlite3", bg)
    try:
        article, feats, _ = pipe.create_article(draw_bar(bg, 150.0, 30.0), "Löffel")
        assert article.diameter_mm is None
        assert article.width_mm is not None and article.depth_mm is not None
        assert article.width_mm > article.depth_mm
        result = match(feats, pipe.db, CAL, cfg)
        assert result.candidates, "elongated article must survive geometry+area filter"
        assert result.candidates[0].article.article_number == article.article_number
    finally:
        pipe.db.close()


def test_generated_article_number_transliterates_and_dedupes(tmp_path):
    bg = make_background()
    pipe, _ = _pipeline(tmp_path / "t.sqlite3", bg)
    try:
        a1, _, _ = pipe.create_article(draw_bar(bg, 150.0, 30.0), "Löffel")
        a2, _, _ = pipe.create_article(draw_bar(bg, 150.0, 30.0), "Löffel")
        assert a1.article_number == "LOEFFEL"
        assert a2.article_number == "LOEFFEL-2"
    finally:
        pipe.db.close()


def test_two_phase_create_preview_then_commit(tmp_path):
    """derive_article must NOT persist anything (preview), commit_article
    persists article + reference – the UI confirm flow depends on this split."""
    bg = make_background()
    pipe, _ = _pipeline(tmp_path / "t.sqlite3", bg)
    try:
        img = draw_bar(bg, 150.0, 30.0)
        seg, feats = pipe.analyze(img)
        art = pipe.derive_article(seg, feats, "Vorschau Löffel")
        assert pipe.db.get_article(art.article_number) is None      # nothing saved yet
        assert art.width_mm is not None and art.depth_mm is not None
        pipe.commit_article(art, feats)
        assert pipe.db.get_article(art.article_number) is not None  # now persisted
        assert pipe.db.references_for(art.article_number)
        # discard path: derive again, never commit -> still absent
        art2 = pipe.derive_article(seg, feats, "Verworfen")
        assert pipe.db.get_article(art2.article_number) is None
    finally:
        pipe.db.close()


def test_auto_prompts_derivation():
    """SAM prompts are derived fully automatically from the locator blob:
    a padded bbox plus interior points spread along the object – with points
    on BOTH the head and the handle, so a dim handle is always prompted."""
    from docodetect.neural_seg import auto_prompts
    blob = np.zeros((1080, 1920), np.uint8)
    cv2.rectangle(blob, (500, 520), (1050, 560), 255, -1)          # handle
    cv2.ellipse(blob, (1150, 540), (110, 75), 0, 0, 360, 255, -1)  # head
    box, points = auto_prompts(blob, k=5)
    x1, y1, x2, y2 = box
    assert x1 <= 500 and y1 <= 465 and x2 >= 1260 and y2 >= 615    # covers blob + pad
    assert len(points) >= 3
    for px, py in points:
        assert blob[py, px] == 255, "prompt point outside the object"
    xs = [p[0] for p in points]
    assert min(xs) < 1000 and max(xs) > 1050, "points must cover handle AND head"


def test_neural_silhouette_integration():
    """End-to-end MobileSAM path (skipped unless requirements-seg-neural.txt
    is installed): the neural mask must be plausible for a synthetic object."""
    pytest.importorskip("mobile_sam")
    pytest.importorskip("torch")
    from docodetect.config import load_config, resolve
    if not resolve("models/mobile_sam.pt").exists():
        pytest.skip("MobileSAM checkpoint not downloaded")
    from docodetect.neural_seg import neural_silhouette
    bg = make_gray_background(fill=20)
    img = bg.copy()
    cv2.rectangle(img, (550, 521), (1050, 561), (190, 190, 190), -1)
    cv2.ellipse(img, (1150, 540), (110, 75), 0, 0, 360, (190, 190, 190), -1)
    blob = np.zeros(img.shape[:2], np.uint8)
    cv2.rectangle(blob, (545, 516), (1055, 566), 255, -1)
    cv2.ellipse(blob, (1150, 540), (115, 80), 0, 0, 360, 255, -1)
    cfg = {"segmentation": {"neural": {"enabled": True, "auto_download": False}}}
    mask = neural_silhouette(img, blob, cfg)
    assert mask is not None
    x, y, w, h = cv2.boundingRect(mask)
    assert w > 600 and 40 <= h <= 220                              # whole spoon, sane


def test_delete_article_removes_master_data_and_references(tmp_path):
    bg = make_background()
    pipe, _ = _pipeline(tmp_path / "t.sqlite3", bg)
    try:
        art, _, _ = pipe.create_article(draw_bar(bg, 150.0, 30.0), "Wegwerf")
        assert pipe.db.get_article(art.article_number) is not None
        assert pipe.db.references_for(art.article_number)
        assert pipe.db.delete_article(art.article_number) is True
        assert pipe.db.get_article(art.article_number) is None
        assert pipe.db.references_for(art.article_number) == []
        assert pipe.db.delete_article(art.article_number) is False  # already gone
    finally:
        pipe.db.close()


# ---------- robust segmentation: reflective objects + noise rejection ----------

from docodetect.segmentation import SegmentationError  # noqa: E402


def make_gray_background(w=1920, h=1080, fill=20):
    """Background with equal BGR channels (saturation ~0), so a neutral-gray
    object does not leak into the saturation-difference channel."""
    base = np.full((h, w), fill, dtype=np.int16)
    noise = np.random.default_rng(42).integers(-5, 5, (h, w), dtype=np.int16)
    gray = np.clip(base + noise, 0, 255).astype(np.uint8)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def draw_reflective_object(bg, center=(960, 540), axes=(200, 60), cell=10):
    """Elongated object filled with a fine two-tone pattern whose MEAN equals
    the background (here 20): every pixel is within the diff threshold of the
    background, so the plain difference is blind to it – but the local variance
    (specular-reflection stand-in) is high, so the texture cue recovers it."""
    img = bg.copy()
    h, w = img.shape[:2]
    obj = np.zeros((h, w), np.uint8)
    cv2.ellipse(obj, center, axes, 0, 0, 360, 255, thickness=-1)
    yy, xx = np.mgrid[0:h, 0:w]
    checker = np.where(((xx // cell) + (yy // cell)) % 2 == 0, 37, 3).astype(np.uint8)  # mean 20
    for ch in range(3):
        img[:, :, ch] = np.where(obj > 0, checker, img[:, :, ch])
    return img


def test_reflective_object_recovered_by_cues():
    bg = make_gray_background(fill=20)                   # near-black matte background
    img = draw_reflective_object(bg)
    # Baseline: region cue alone (old behaviour) cannot see it -> raises.
    cfg_off = {"segmentation": {**CFG["segmentation"],
                                "use_edge_cue": False, "use_texture_cue": False}}
    with pytest.raises(SegmentationError):
        segment(img, bg, cfg_off)
    # New behaviour: the recovery cues find the object.
    seg = segment(img, bg, CFG)
    assert not seg.touches_border
    assert seg.area_px >= CFG["segmentation"]["min_area_px"]
    feats = extract(img, seg, CAL)
    assert feats.aspect_ratio < 0.80                    # elongated
    m = cv2.moments(seg.contour)
    cx, cy = m["m10"] / m["m00"], m["m01"] / m["m00"]
    assert abs(cx - 960) < 120 and abs(cy - 540) < 120  # the centered object, not corner noise


def draw_spoon_bright_bowl_dim_handle(bg):
    """Models the real failure case: shiny bowl (region diff fires) + handle
    that reflects the dark background (mean == bg -> region-blind; only the
    texture cue sees its reflections). The whole spoon must come back as ONE
    contour – a partial region hit must not shrink it to the bowl."""
    img = bg.copy()
    h, w = img.shape[:2]
    handle = np.zeros((h, w), np.uint8)
    cv2.rectangle(handle, (550, 515), (1070, 565), 255, -1)
    yy, xx = np.mgrid[0:h, 0:w]
    checker = np.where(((xx // 10) + (yy // 10)) % 2 == 0, 37, 3).astype(np.uint8)  # mean 20
    for ch in range(3):
        img[:, :, ch] = np.where(handle > 0, checker, img[:, :, ch])
    cv2.ellipse(img, (1150, 540), (110, 75), 0, 0, 360, (200, 200, 200), -1)  # bowl
    return img


def test_partial_region_object_kept_whole():
    """Regression: the shiny bowl alone used to satisfy the region-support
    check, so the final contour collapsed to the bowl and the handle was lost."""
    bg = make_gray_background(fill=20)
    img = draw_spoon_bright_bowl_dim_handle(bg)
    seg = segment(img, bg, CFG)
    assert not seg.touches_border
    x, y, w, h = cv2.boundingRect(seg.contour)
    assert w > 550, f"only a fragment segmented (bbox width {w}px, bowl-only ≈225px)"
    assert seg.area_px > 40000                       # bowl alone is ~26000
    feats = extract(img, seg, CAL)
    assert feats.aspect_ratio < 0.5                  # spoon-elongated, not bowl-round


def test_corner_noise_blob_rejected():
    bg = make_background()
    H, W = bg.shape[:2]
    img = draw_plate(bg, 180.0)                          # real central object
    cv2.rectangle(img, (W - 150, H - 150), (W - 1, H - 1), (255, 255, 255), -1)
    seg = segment(img, bg, CFG)
    assert not seg.touches_border                        # central plate chosen, not the corner
    feats = extract(img, seg, CAL)
    assert abs(feats.circle_diameter_mm - 180.0) < 3.0
    # the corner blob ALONE is not a plausible object -> raises
    noise_only = bg.copy()
    cv2.rectangle(noise_only, (W - 150, H - 150), (W - 1, H - 1), (255, 255, 255), -1)
    with pytest.raises(SegmentationError):
        segment(noise_only, bg, CFG)


def draw_fork(bg, color=(250, 250, 250)):
    """Bright fork: handle + head with 4 tines pointing right; the 3 slots
    between the tines are open toward the head's end and painted in background
    color. Returns (image, slot_center_points, tine_center_points)."""
    img = bg.copy()
    cv2.rectangle(img, (500, 521), (1050, 561), color, -1)            # handle
    cv2.rectangle(img, (1050, 460), (1300, 622), color, -1)           # head
    slots, tines = [], []
    y = 460
    for i in range(4):                                                # 4 tines à 30px
        tines.append((1235, y + 15))
        y += 30
        if i < 3:                                                     # 3 slots à 14px
            cv2.rectangle(img, (1170, y), (1300, y + 14), (200, 200, 200), -1)
            slots.append((1235, y + 7))
            y += 14
    return img, slots, tines


def test_fork_tine_slots_stay_open():
    """The closings that keep one object in one piece must not permanently
    bridge the background-colored slots between fork tines – silhouette,
    perimeter and colour must describe the FORK, not a filled paddle."""
    bg = make_background()
    img, slots, tines = draw_fork(bg)
    seg = segment(img, bg, CFG)
    assert not seg.touches_border
    x, y, w, h = cv2.boundingRect(seg.contour)
    assert w > 700                                   # whole fork: handle + head
    for sx, sy in slots:
        assert seg.mask[sy, sx] == 0, f"slot ({sx},{sy}) filled in"
    for tx, ty in tines:
        assert seg.mask[ty, tx] == 255, f"tine ({tx},{ty}) missing"


def test_silhouette_is_tight():
    """The cues' dilation halo must never leak into the measurement: a plate
    measures within a small absolute budget of its drawn diameter."""
    bg = make_background()
    img = draw_plate(bg, 200.0)
    d = extract(img, segment(img, bg, CFG), CAL).circle_diameter_mm
    assert abs(d - 200.0) < 2.5, f"silhouette fat/thin: {d:.2f}mm vs 200mm"


def test_refined_blob_keeps_dark_neck():
    """A spoon's neck often mirrors the dark floor: bright bowl and bright
    handle joined by a near-invisible neck. The evidence-tightened blob path
    must keep the object in ONE piece without pinching the neck away."""
    bg = make_gray_background(fill=20)
    img = bg.copy()
    cv2.rectangle(img, (600, 525), (1030, 557), (200, 200, 200), -1)   # handle
    cv2.ellipse(img, (1150, 540), (100, 70), 0, 0, 360, (200, 200, 200), -1)  # bowl
    # neck: 18px stretch back at background level (mirrors the floor)
    img[500:580, 1032:1050] = bg[500:580, 1032:1050]
    seg = segment(img, bg, CFG)
    x, y, w, h = cv2.boundingRect(seg.contour)
    assert w > 550, f"object split/pinched at the dark neck (bbox width {w}px)"
    # the neck region itself must be part of the mask (no pinch-through)
    assert seg.mask[540, 1040] == 255, "neck pinched out of the mask"


def test_refined_blob_keeps_dark_bowl_side():
    """The shadow side of a 3D spoon bowl mirrors the black floor: a whole
    crescent of the bowl has (almost) no per-pixel evidence, only a faint rim
    glint marks its outline. The crescent must stay part of the silhouette –
    the contour must not cut through the bowl along the internal bright/dark
    edge (that is exactly what the old region-preferred path did)."""
    bg = make_gray_background(fill=20)
    img = bg.copy()
    cv2.ellipse(img, (960, 540), (110, 80), 0, 0, 360, (200, 200, 200), -1)
    # dark lune: the right ~25px of the bowl mirrors the floor
    lune = np.zeros(img.shape[:2], np.uint8)
    cv2.ellipse(lune, (960, 540), (110, 80), 0, 0, 360, 255, -1)
    cv2.ellipse(lune, (935, 540), (110, 80), 0, 0, 360, 0, -1)
    for ch in range(3):
        img[:, :, ch] = np.where(lune > 0, bg[:, :, ch], img[:, :, ch])
    # faint rim glint along the dark side (realistic for polished steel);
    # +28 gray is below the region diff_threshold but visible to Canny
    cv2.ellipse(img, (960, 540), (110, 80), 0, -70, 70, (48, 48, 48), 2)
    seg = segment(img, bg, CFG)
    assert seg.mask[540, 1050] == 255, "dark bowl side cut off the mask"
    x, y, w, h = cv2.boundingRect(seg.contour)
    assert w > 205, f"bowl truncated at the bright/dark edge (bbox width {w}px)"


def test_carve_is_noop_on_rim_shaded_plate():
    """The blur-transition band just inside a shaded rim is background-like –
    carving it would systematically shrink every plate by ~2 mm. The boundary
    guard must make carve a no-op here (carve on == carve off)."""
    bg = make_background()
    cfg_off = {"segmentation": {**CFG["segmentation"], "carve_concavities": False}}
    for d_mm in (160.0, 210.0):
        img = draw_plate(bg, d_mm)
        d_on = extract(img, segment(img, bg, CFG), CAL).circle_diameter_mm
        d_off = extract(img, segment(img, bg, cfg_off), CAL).circle_diameter_mm
        assert abs(d_on - d_off) < 0.2, f"carve shifted {d_mm}mm plate by {d_on - d_off:.2f}mm"


def test_carve_keeps_wide_reflective_part():
    """A SHORT reflective handle (<30% of the area, mean == background) must
    not be amputated by the carve: wide background-like areas are real parts,
    not slots."""
    bg = make_gray_background(fill=20)
    img = bg.copy()
    h_, w_ = img.shape[:2]
    handle = np.zeros((h_, w_), np.uint8)
    cv2.rectangle(handle, (890, 515), (1060, 565), 255, -1)          # short handle
    yy, xx = np.mgrid[0:h_, 0:w_]
    checker = np.where(((xx // 10) + (yy // 10)) % 2 == 0, 37, 3).astype(np.uint8)
    for ch in range(3):
        img[:, :, ch] = np.where(handle > 0, checker, img[:, :, ch])
    cv2.ellipse(img, (1150, 540), (110, 75), 0, 0, 360, (200, 200, 200), -1)
    seg = segment(img, bg, CFG)
    x, y, w, h = cv2.boundingRect(seg.contour)
    assert w > 320, f"handle amputated (bbox width {w}px, bowl-only ≈225px)"


def test_carve_never_unflags_border_touch():
    """An object whose background-like part crosses the frame edge must stay
    flagged as touching – the border check runs on the UNCARVED silhouette."""
    bg = make_gray_background(fill=20)
    img = bg.copy()
    h_, w_ = img.shape[:2]
    stub = np.zeros((h_, w_), np.uint8)
    cv2.rectangle(stub, (0, 500), (200, 580), 255, -1)               # crosses left edge
    yy, xx = np.mgrid[0:h_, 0:w_]
    checker = np.where(((xx // 10) + (yy // 10)) % 2 == 0, 37, 3).astype(np.uint8)
    for ch in range(3):
        img[:, :, ch] = np.where(stub > 0, checker, img[:, :, ch])
    cv2.circle(img, (350, 540), 150, (200, 200, 200), -1)            # bright body inside
    seg = segment(img, bg, CFG)
    assert seg.touches_border, "clipped object silently measured after carve"


def test_tapered_fan_tine_slots_carved():
    """Real forks have fan-shaped tines: the slots are WEDGES that taper to
    zero at the base and open through a narrow tip gap, drawn diagonally like
    in practice. The old per-component statistics merged these wedges with
    the outline skirt and kept them sealed."""
    bg = make_gray_background(fill=20)
    canvas = np.zeros(bg.shape[:2], np.uint8)
    cv2.rectangle(canvas, (400, 500), (900, 545), 255, -1)     # handle
    cv2.ellipse(canvas, (950, 522), (90, 60), 0, 0, 360, 255, -1)  # head web
    base = (990, 522)
    tips = [(1180, 462), (1185, 502), (1185, 542), (1180, 582)]
    for t in tips:
        cv2.line(canvas, base, t, 255, 16)                     # fanned tines
    M = cv2.getRotationMatrix2D((900, 522), -40, 1.0)
    canvas = cv2.warpAffine(canvas, M, (bg.shape[1], bg.shape[0]))
    img = bg.copy()
    for ch in range(3):
        img[:, :, ch] = np.where(canvas > 0, 150, img[:, :, ch])
    seg_r = segment(img, bg, CFG)
    open_slots = 0
    for a, b_ in ((tips[0], tips[1]), (tips[1], tips[2]), (tips[2], tips[3])):
        mx = (a[0] * 0.85 + base[0] * 0.15 + b_[0] * 0.85 + base[0] * 0.15) / 2
        my = (a[1] * 0.85 + base[1] * 0.15 + b_[1] * 0.85 + base[1] * 0.15) / 2
        p = M @ np.array([mx, my, 1.0])
        if seg_r.mask[int(round(p[1])), int(round(p[0]))] == 0:
            open_slots += 1
    assert open_slots == 3, f"only {open_slots}/3 tapered slots open"
    x, y, w, h = cv2.boundingRect(seg_r.contour)
    assert w > 500                                             # fork stays whole


def test_split_object_reports_multiple_plausible_parts():
    """If the object falls apart into two plausible blobs (spoon bowl vs.
    handle), only the best one is measured – but debug['n_plausible'] must
    say so, so the UI can warn instead of silently measuring a fragment."""
    bg = make_background()
    img = draw_plate(bg, 100.0, center=(600, 540))
    img = cv2.circle(img, (1300, 540), int(100.0 / MM_PER_PX / 2), (250, 250, 250), -1)
    seg = segment(img, bg, CFG)
    assert seg.debug is not None and seg.debug["n_plausible"] == 2
    # single object -> no false alarm
    seg_single = segment(draw_plate(bg, 200.0), bg, CFG)
    assert seg_single.debug["n_plausible"] == 1


def test_large_border_object_not_rejected_as_noise():
    bg = make_background()
    img = draw_plate(bg, 210.0, center=(30, 540))        # large plate clipped by the frame
    seg = segment(img, bg, CFG)
    assert seg.touches_border                            # flagged, not discarded as noise
    assert seg.area_px > CFG["segmentation"]["min_area_px"]
