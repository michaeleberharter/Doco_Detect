# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Geschirr-Identifikation für DO&CO: a photo box (40×30×30 cm) with a fixed
overhead camera (UGREEN FineCam Lite 4K, 300 mm above the floor) identifies
plates/bowls/cups by measuring their geometry and color, then matching
against an article database. Two stages:

1. **Stage 1 (deterministic, always on):** graph-cut segmentation →
   geometric measurement in mm (diameter, area, circularity, shape) + color
   histogram → hard geometry filter + weighted scoring against the article
   DB. The segmentation (`docodetect/segmentation.py`) is ONE global
   optimization instead of a rule cascade, and it is **fully
   self-calibrating – it has NO config keys** (`segment(image, background)`,
   no cfg parameter): every threshold derives from the image pair (floor
   noise ceiling via sigma clipping, per-component object seeds = top half
   of each component's own evidence range, texture seeds gated by per-pixel
   non-floorness, edge scale from the reference floor). Stages: evidence →
   exact min-cut (scipy `maximum_flow`, data term claims only certainty,
   everything else neutral so the boundary lands on the strongest edge) →
   edge-sealed reachability completion + amodal bridging (distance lens
   between split components; invisible-boundary notch fill; fork-tine slots
   open through edge-free mouths stay floor) → contour snap with
   outward-only edge reach. Development/validation happens against REAL
   captures in `data/captures/` pinned by `tests/test_real_captures.py`
   goldens (`paths.save_captures`). `docodetect/neural_seg.py` (MobileSAM)
   is retired from the pipeline and kept only for experiments.
2. **Stage 2 (optional, not yet wired into the pipeline):** DINOv2
   embeddings + FAISS nearest-neighbor for cases where stage 1 leaves
   ambiguous candidates. Lives entirely in `docodetect/embeddings.py`;
   `pipeline.py` does not call it yet.

## Commands

```bash
# setup
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # stage 1 (opencv, numpy, PyYAML)
pip install -r requirements-stage2.txt   # optional: stage 2 (torch, faiss)
pip install -r requirements-ui.txt       # optional: Streamlit test UI

# tests (synthetic, no camera/hardware needed)
python -m pytest tests/ -v
python -m pytest tests/test_pipeline_synthetic.py::test_height_compensation -v  # single test

# CLI workflow (see README.md for the full sequence)
python -m docodetect.cli init-db
python -m docodetect.cli import-articles data/articles_example.csv
python -m docodetect.cli capture-background      # empty box
python -m docodetect.cli calibrate               # ArUco marker in box
python -m docodetect.cli enroll ART-NR --shots 8
python -m docodetect.cli identify [--image foto.jpg]
python -m docodetect.cli evaluate data/testset/   # accuracy + confusion pairs

# Streamlit test UI (live camera, no CLI typing)
streamlit run app.py

# generate the printable ArUco calibration marker
python scripts/generate_marker.py
```

There is no configured linter/formatter in this repo — don't invent one.

## Architecture

**`pipeline.py` is the single entry point every caller (CLI, `app.py`,
future services) must go through.** It orchestrates
`segmentation.py` → `features.py` → `matcher.py`/`database.py` and nothing
else should reimplement that flow — new UIs/scripts call
`Pipeline.identify()` / `.enroll()` / `.analyze()`, never the lower-level
modules directly (except `calibration.py`/`camera.py`/`database.py` for
setup actions like capturing a background or importing articles).

Data flow for `identify()`:
```
image (BGR ndarray)
  → segmentation.segment()   evidence (channel-diff + texture) → graph cut → edge completion → contour, border-touch flag
  → features.extract()       contour+calibration → mm-correct geometry, ring-zone Lab/H-S color
                             (center vs. rim), Hu-moment shape, solidity
  → matcher.match()          per-article height-compensated geometry filter → statistical
                             scoring (z-scores vs. enrollment stats, Fisher-adaptive weights)
  → MatchReport(decision: accept|ambiguous|reject, per-feature z/logL breakdown,
                posterior, gate status – fully JSON-serializable)
```
Every `identify()` also writes the `MatchReport` JSON to
`paths.captures_dir`, plus a capture JPG when no `source_path` was given
(skipped entirely when the config key is absent, e.g. in synthetic tests).
The Streamlit UI passes the raw `save_captures` PNG as `source_path`, so
the report references that file instead of duplicating it. The page
`pages/1_Scoring_Analyse.py` renders ONLY these reports (live or loaded
from disk) — it never re-implements scoring; batch aggregation lives in
`docodetect/reporting.py`, shared by CLI `evaluate` and the UI.

Key invariants that explain a lot of the code:

- **All calibration is for the floor plane.** An object's rim sits above
  the floor and therefore appears larger. `features.height_corrected_scale()`
  converts a floor-plane measurement to true size using
  `object_height_mm` (from the DB) and `camera_height_mm` (from config) —
  applied **per article candidate** in `matcher.py`, never in
  `features.py` itself, since the correction depends on which article is
  being tested.
- **`config/config.yaml` is the single source of truth** for every
  tunable (camera, geometry, calibration, matching tolerances/weights/
  decision thresholds, paths). Load it via
  `docodetect.config.load_config()`; never hardcode a parameter that
  already has a config key. `config.resolve()` turns a config-relative
  path into an absolute one (project root = parent of `config/`).
  **Exception by design: the segmentation has NO config keys at all** – it
  self-calibrates on the image pair. Do not add segmentation tunables; if
  a segmentation is wrong, the capture in `data/captures/` is the test
  case and the fix is a better rule, not a knob (user decision 2026-07-16).
- **FOV limitation:** at 70° diagonal FOV / 300 mm height the visible
  floor is ~37×21 cm; objects whose contour touches the frame border
  cannot be measured correctly. `segmentation.py` detects this
  (`touches_border`) and `pipeline.analyze()` raises `SegmentationError`
  rather than returning a wrong measurement. `pipeline.identify()` catches
  that and turns it into a `reject` `MatchReport` with an explanatory
  message (so the failure still lands in the captures log); `pipeline.enroll()`
  does **not** catch it — callers must handle `SegmentationError` themselves
  when enrolling.
- **Autofocus must be off.** `camera.py`'s `BoxCamera` locks focus via UVC
  properties on open; a fixed focus value is required because the
  px→mm scale (from calibration) drifts if focus changes between shots.
  Every camera consumer should go through `BoxCamera`, not raw
  `cv2.VideoCapture`, and should open/close it around use rather than
  holding it open indefinitely (other processes, e.g. the CLI, need the
  device free).
- **Stage 1 matcher decision logic** (`matcher.py`): a hard geometry
  tolerance filter first (usually collapses hundreds of articles to a
  handful), then statistical scoring: per feature z = distance / sigma_eff
  with sigma_eff = sqrt(sigma_enroll² + sigma_floor²) (enrollment stats from
  the `reference_stats` table, floors from `matching.sigma_floors`), log-
  likelihood −0.5z², Fisher-adaptive weights over the candidate set
  (`adaptive_weight_alpha`), softmax posterior. `accept` requires the
  winner's max|z| ≤ `max_z_accept` *and* a log-score margin ≥
  `min_llr_margin` over the runner-up *and* enrolled references —
  articles without references are geometry-only and can never accept.
  Failing the z-gate means `reject` ("probably not in the database"),
  which must never be booked automatically. Candidates with enrollment
  stats are compared floor-plane vs. floor-plane (no double height
  correction); only the pre-filter uses `height_corrected_scale`.
- **`database.py`** is a thin SQLite wrapper (`articles` = master data
  imported from CSV, `reference_features` = enrolled photos' `Features` as
  JSON) explicitly designed to be swapped for the real DO&CO database
  later by reimplementing the same API — don't couple other modules to
  SQLite specifics beyond this module.
- **`embeddings.py`** does all heavy imports (torch/faiss/PIL) lazily so
  stage 1 works without those packages installed; it's a standalone
  optional module, not yet called from `pipeline.py`.

## Test UI (`app.py`)

Streamlit app that drives the exact same `Pipeline`/`calibration`/
`camera`/`database` calls as the CLI — no separate image-processing logic.
It exclusively uses the real `BoxCamera` (never `st.camera_input`, which
has the wrong resolution and no focus lock); every action shoots a fresh
frame through the shared, lazily-opened/closed camera object in
`st.session_state` so the device isn't left locked open between actions.
