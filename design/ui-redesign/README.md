# Handoff: Doco Detect — Automatic Detection System UI

## Overview
Doco Detect is a desktop + touchscreen application for an industrial **automatic object-detection / measurement system**. An operator places a physical part under a camera, presses **Identify**, and the system measures the object (e.g. diameter) and matches it against a taught article database. The redesigned UI (direction "2a", the "Technician workbench") presents:

- A **live camera view** with a calibrated crosshair and a detection overlay (bounding frame + measurement tag).
- A **tool rail** for the core workflows (Scan, Capture background, Calibrate, Teach).
- A **result column** with the recognized article, a measured-vs-database tolerance gauge, a confidence read-out, nearest candidates, and a session history log.
- A **large bottom action bar** whose primary control is a big, always-reachable **Identify** button (operator-first, touch-friendly).
- Two modal dialogs — **Calibrate** and **Teach article** — plus a **"no match"** result state.

The UI is **bilingual (German / English)** and supports **dark and light themes**.

## About the Design Files
The files in this bundle are **design references created in HTML** — prototypes that show the intended look, layout, copy, and behavior. **They are not production code to copy directly.** The `.dc.html` files use a bespoke streaming "Design Component" runtime (`support.js`, custom `<x-dc>` / `<dc-import>` / `<sc-for>` / `<sc-if>` tags) that is specific to the design tool — do **not** try to ship that runtime.

Your task is to **recreate these designs in the target codebase's existing environment** (React, Vue, SwiftUI, native desktop, etc.), using its established component library, styling approach, and patterns. If no front-end environment exists yet, pick the most appropriate framework for the project and implement the designs there. Treat the HTML as the source of truth for *appearance and interaction*, not structure.

## Fidelity
**High-fidelity (hifi).** Colors, typography, spacing, radii, and interactions are final. Recreate the UI pixel-accurately using the codebase's own libraries and patterns. Exact tokens are listed under **Design Tokens**.

The whole design is built at a reference window size of **1180 × 724 px** (the app window / chrome is illustrative — in the real app this is just the application viewport; adapt to the real window and make it responsive per the notes below).

---

## Screens / Views

### 1. Main workbench (default "match" state)
**Purpose:** Operator places a part, triggers identification, reads the result.

**Layout** — vertical stack inside the app window:
1. **Title bar** (height 40px) — centered app title, macOS-style traffic lights on the left. *This is prototype chrome; use the real OS/app window instead.*
2. **Body** (fills remaining height) — horizontal 3-part flex:
   - **Tool rail** — fixed width **78px**, left border 1px. Vertical stack of icon buttons, 14px vertical padding, 8px gap, centered. Buttons: Scan (active), Capture bg, Calibrate, Teach; a Settings (gear) button pinned to the bottom (`flex:1` spacer above it).
   - **Camera view** — `flex:1`, min-width 0. Contains a thin toolbar (Demo image selector + a live "● Live" indicator) then the camera stage (`flex:1`).
   - **Result column** — fixed width **372px**, left border 1px. Vertical stack: primary Identify button (secondary copy of the bottom bar's), Result card, Candidates, History (scrollable).
3. **Bottom action bar** (auto height, top border 1px, 14px padding, 12px gap): the big **Identify** button (`flex:1`) + three fixed **120px** secondary buttons (Capture background, Calibrate, Teach).
4. **Status bar** (auto height, top border 1px): camera name, calibration, article count, sensor state — separated by "·".

**Components:**

- **Tool-rail button** — 58×58px, border-radius 12px, icon (20px stroke) above an 8.5px uppercase-ish label. Default: `color: var(--dim)`, transparent bg, 1px transparent border. **Active** (Scan): `color: var(--accent)`, `background: var(--accentWeak)`, `border: 1px solid var(--accent)`. Cursor pointer. Clicking Calibrate/Teach opens the matching dialog.

- **Demo selector** — pill, min-width 190px, 6×11px padding, `background: var(--panel2)`, 1px border `var(--line)`, radius 8px. Label "Schüssel" (600/12px) + a CSS-triangle chevron in `var(--faint)`. (A `<select>` in production.)

- **Live indicator** — 7px dot in `var(--ok)` with a 1.8s opacity pulse (100%→35%→100%) + label "Live" (600/11px, `var(--ok)`).

- **Camera stage** — background `var(--stage)`. Contains (drawn as SVG in the prototype; in production this is the live video frame + an overlay canvas/SVG):
  - a lighter capture "plate" rectangle (`var(--plate)`),
  - faint crosshair lines (`var(--crosshair)`) centered H+V,
  - the detected object rendered as concentric circles (illustrative),
  - a **detection frame**: 200×200 (viewBox units) rounded rect, `stroke: var(--ok)` (match) / `var(--warn)` (no match), 2px, dashed `3 5`,
  - a **measurement tag** pinned to the frame's top-left: two mono pills — `Ø 141 mm` and `100%` (or `?` on no match) — colored `var(--ok)` / `var(--warn)`, white text, 12px mono, radius 7px.

- **Result card (match)** — 16px padding container with a bottom border.
  - Header row: left = check-badge (18px circle `var(--ok)` + white check) + "Erkannt"/"Detected" (700/12px, `var(--ok)`); right = "100%" (800/15px mono, `var(--ok)`).
  - Card: 1px border `var(--ok)`, `background: var(--okWeak)`, radius 11px, 13×14px padding.
    - Title row: "Schüssel 14" (700/16px) + SKU "DEMO-SCH14" (600/11px mono, `var(--dim)`).
    - Two stats: **Gemessen/Measured** "141 mm" and **Datenbank/Database** "141 ±6 mm" (labels 600/9.5px `var(--faint)`; values 700/16px mono).
    - **Tolerance gauge** (see below).

- **Tolerance gauge** — a 10px-tall track (`background: var(--track)`, 1px border `var(--line)`, radius 6px) with:
  - a tolerance band from **27%→73%** width, `background: var(--okWeak)`, dashed left/right borders in `var(--ok)`,
  - a measured-value marker: 14px circle `var(--ok)` centered (50%) with a 3px `var(--okWeak)` ring.
  - Below: mono 9.5px scale "135" … "✓ im Toleranzbereich / within tolerance" (`var(--ok)`, 700) … "147".

- **Candidates list** — section label "Weitere Kandidaten"/"Other candidates" (700/10px, letter-spacing .12em, `var(--faint)`), then rows: `background: var(--panel2)`, 1px border `var(--line)`, radius 9px, 9×11px padding, 7px gap. Each row: name (600/12.5px) + `DB 128 · Δ 13 mm` (600/10px mono, `var(--dim)`); a 74px mini confidence bar (6px track `var(--line)`, fill = candidate color at its %); the % (700/12px mono, candidate color). Colors: high `var(--ok)`, medium `var(--warn)`, low `var(--bad)`.
  - Data: `Schüssel 12 — DB 128 · Δ 13 mm — 42%` (warn); `Teller 20 — DB 198 · Δ 57 mm — 11%` (bad).

- **History (Verlauf)** — header row: label + "Leeren"/"Clear" action (600/10.5px, `var(--accent)`). List is **scrollable** (`flex:1; min-height:0; overflow-y:auto`). Each row (8×4px padding, 1px bottom border, 11px gap): status dot (8px), time (600/11px mono `var(--faint)`), name (600/12px, ellipsis), confidence (700/11px mono, colored). Dot colors: ok green, warn amber, **no-match red**.
  - Data: `14:32 Schüssel 14 100%` (ok), `14:31 Schüssel 14 98%` (ok), `14:30 Teller 20 71%` (warn), `14:29 Kein Treffer —` (dot red, text faint), `14:28 Schüssel 12 94%` (ok).

- **Primary Identify button** (bottom bar) — `flex:1`, height **72px**, no border, radius 15px, `background: var(--accent)`, white text, 13px gap, shadow `0 10px 24px -8px var(--accent)`. Contents: scan icon (24px) + a two-line label ["Identifizieren"/"Identify" 800/20px, line-height 1.05] and [sub-copy "Objekt platzieren – dann identifizieren" / "Place object – then identify" 600/11px, opacity .85] + a keyboard-hint chip "↵ Leertaste/Space" (700/11px mono, bg `rgba(255,255,255,.22)`, 5×9px, radius 7px). **Hover:** `background: var(--accentH)`, deeper shadow.

- **Secondary action button** (bottom bar) — fixed width 120px, height 72px, 1px border `var(--line)`, radius 15px, `background: var(--panel2)`, `color: var(--text)`, icon above 12px label, 5px gap.

- **Status bar** — 8×18px padding, `background: var(--bg)`, top border, 500/11.5px `var(--dim)`. First item has a 6px `var(--ok)` dot. Content DE: "Kamera Demo · Kalibriert 20.07. · 0,200 mm/px · 3 Artikel · 3 eingelernt · S2 aus". EN: "Camera Demo · Calibrated 07/20 · 0.200 mm/px · 3 articles · 3 taught · S2 off".

### 2. Calibrate dialog (Kalibrieren)
**Purpose:** Establish the mm-per-pixel scale from a reference object of known size.

**Layout:** full-window overlay — `position:absolute; inset:0; z-index:40`, `background: rgba(4,7,12,.55)`, backdrop-blur 3px, centered. Dialog card: **480px** wide, `background: var(--panel)`, 1px border `var(--line)`, radius 16px, shadow `0 30px 70px -20px rgba(0,0,0,.6)`, overflow hidden.
- **Header** (16×18px padding, bottom border): 32px rounded-9px badge (`background: var(--accentWeak)`, `color: var(--accent)`) with target icon + title "Kalibrieren"/"Calibrate" (700/16px) + close button (30px, 1px border `var(--line)`, `background: var(--panel2)`, "×").
- **Body** (18px padding):
  - Intro paragraph (400/12.5px, `var(--dim)`).
  - **Preview** (130px tall, 1px border, radius 11px): mini camera view (crosshair + dashed accent reference circle with a measured chord line) + a caption pill at the bottom "Objekt mittig auf dem Kreuz platzieren" / "Center the object on the crosshair" (700/11px mono, white on `rgba(4,7,12,.6)`).
  - Field row 1: **Referenzobjekt/Reference object** (read-only: "Kalibrierplatte · Ø 100 mm") + **Bekannter Durchmesser/Known diameter** (input, 130px, value "100 mm").
  - Field row 2: **Gemessen (Pixel)/Measured (pixels)** (read-only "500 px") + **Neuer Maßstab/New scale** (read-only "0,200 mm/px", `color: var(--accent)`).
  - Footer buttons: **Abbrechen/Cancel** (ghost, `flex:1`) + **Übernehmen/Apply** (primary `flex:1.4`, target icon).

**Field styles:** label 600/10px uppercase, letter-spacing .06em, `var(--faint)`. Input: 40px tall, 12px padding, `background: var(--panel2)`, 1px border `var(--line)`, radius 9px, 600/14px, no outline. Read-only value: same box but `background: var(--track)`, mono 600/14px, `var(--dim)`.

### 3. Teach dialog (Artikel einlernen)
**Purpose:** Register the current object as a new article.

Same overlay + card shell as Calibrate; header badge uses the **plus** icon; title "Artikel einlernen"/"Teach article".
- Intro paragraph.
- Field row 1: **Bezeichnung/Name** (input "Schüssel 14") + **Artikelnummer/Article number** (input, mono, "DEMO-SCH14", 150px).
- Field row 2: **Gemessener Durchmesser/Measured diameter** (read-only "141 mm") + **Toleranz ±/Tolerance ±** (input "6 mm", 110px).
- **Proben/Samples** field: 40px box (`background: var(--track)`) with three 9px `var(--ok)` dots + "3 / 3 erfasst" / "3 / 3 captured" (600/13px, `var(--ok)`).
- Footer: **Abbrechen/Cancel** (ghost) + **Einlernen/Teach** (primary, plus icon).

### 4. No-match state (Kein Treffer)
Same workbench, but when no article is within tolerance:
- Detection frame + measurement tag switch to **`var(--warn)`**; the confidence pill shows **`?`**.
- Result header: warn "!" badge (18px circle `var(--warn)`, white "!") + "Nicht gefunden"/"Not found" (700/12px, `var(--warn)`); right side shows "?".
- Result card: 1px border `var(--warn)`, `background: var(--warnWeak)`. Copy: "Kein Artikel im Toleranzbereich"/"No article within tolerance"; the measured value shown large ("141 mm", 800/22px mono); a full-width primary button "Als neuen Artikel einlernen"/"Teach as new article" (opens the Teach dialog).
- Candidates section label becomes "Am nächsten liegende Kandidaten"/"Closest candidates".
- Top history entry is the no-match row (red dot).

---

## Interactions & Behavior
- **Identify** (bottom bar, rail Scan, or **Space/Enter**): triggers a detection pass → populates the result card, updates confidence, prepends a history row.
- **Calibrate / Teach** buttons (both bottom bar and tool rail): open the respective modal. **× or Cancel** closes; **Apply / Teach** commits and closes.
- **No-match "Teach as new article"**: opens the Teach dialog pre-filled with the measured diameter.
- **Live indicator**: 1.8s infinite opacity pulse (`100% → 35% → 100%`).
- **Button hover**: primary buttons swap `var(--accent)` → `var(--accentH)` and deepen shadow; keep transitions short (~120–150ms ease).
- **Theme toggle** (Dark/Light) and **Language toggle** (DE/EN): global; re-theme and re-label the entire UI. (In the prototype these live in a page toolbar; in production wire to app settings.)
- **History**: newest first, scrollable, capped visually by the column height.
- **Responsive:** below ~1100px the 372px result column can collapse to a drawer/sheet; the bottom bar's primary Identify should remain full-width and thumb-reachable on touch. Minimum touch target 44px (rail/bar buttons already exceed this).

## State Management
- `theme`: `'dark' | 'light'`.
- `lang`: `'de' | 'en'`.
- `result`: `'match' | 'nomatch'` — drives the result card, frame color, confidence tag, candidate label, top history row.
- `dialog`: `'none' | 'calibrate' | 'teach'` — which modal is open.
- Detection payload (from the vision backend): `{ name, sku, measuredMm, dbMm, toleranceMm, confidence }`, plus `candidates[]` (`{ name, sku, dbMm, deltaMm, confidence }`) and `history[]` (`{ time, name, confidence, status }`).
- Calibration: `{ referenceName, knownMm, measuredPx, mmPerPx }`.
- Data fetching: identification, calibration, and teach are backend/vision-service calls; wire the buttons to those. The prototype uses static demo data.

## Design Tokens

**Colors — Dark theme**
| Token | Hex / value |
|---|---|
| `--bg` (window) | `#0f141b` |
| `--stage` (camera bg) | `#05070b` |
| `--panel` | `#161c25` |
| `--panel2` | `#1b2431` |
| `--line` (borders) | `#28303d` |
| `--text` | `#e8edf3` |
| `--dim` | `#8b97a8` |
| `--faint` | `#5c6675` |
| `--accent` | `#3d7dfb` |
| `--accentH` (hover) | `#5b93ff` |
| `--accentWeak` | `rgba(61,125,251,.16)` |
| `--ok` | `#31b46f` |
| `--okWeak` | `rgba(49,180,111,.15)` |
| `--warn` | `#e0a63a` |
| `--warnWeak` | `rgba(224,166,58,.15)` |
| `--bad` | `#e2604a` |
| `--track` | `#0e141c` |
| plate (capture area) | `#c9ced6` |
| crosshair | `rgba(0,0,0,.28)` |

**Colors — Light theme**
| Token | Hex / value |
|---|---|
| `--bg` | `#eef1f5` |
| `--stage` | `#dfe4ea` |
| `--panel` | `#ffffff` |
| `--panel2` | `#f4f7fa` |
| `--line` | `#e2e7ee` |
| `--text` | `#141a22` |
| `--dim` | `#5b6675` |
| `--faint` | `#98a2b0` |
| `--accent` | `#2f6fe0` |
| `--accentH` | `#1f5fd0` |
| `--accentWeak` | `rgba(47,111,224,.12)` |
| `--ok` | `#178a52` |
| `--okWeak` | `rgba(23,138,82,.11)` |
| `--warn` | `#b9781f` |
| `--warnWeak` | `rgba(185,120,31,.12)` |
| `--bad` | `#c8472f` |
| `--track` | `#eef1f5` |
| plate | `#cbd1d9` |
| crosshair | `rgba(0,0,0,.22)` |

Detected-object fill (both themes): `#6fa8ef` @ 55% opacity, stroke `#3f7fd6`.

**Typography**
- UI font: **IBM Plex Sans** (weights 400/500/600/700; 800 used for the big Identify label and no-match measured value). Google Fonts.
- Numeric / code font (measurements, SKUs, times, %): a **monospace** stack (`ui-monospace, 'IBM Plex Mono', Menlo, monospace`). Keep all numbers/codes monospace for technical legibility.
- Scale used: 8.5, 9.5, 10, 11, 11.5, 12, 12.5, 13, 14, 15, 16, 20, 22px. Section labels: 10px, letter-spacing ~.12em; field labels: 10px uppercase, letter-spacing .06em.

**Spacing:** paddings of 4, 6, 8, 9, 11, 13, 14, 16, 18px; gaps 5, 7, 8, 10, 11, 12, 13, 18px.

**Border radius:** 6 (gauge/chips), 7 (tag pills / kbd chip), 8 (selector), 9 (rows/inputs/badges), 11 (result card/dialog fields), 12 (rail buttons), 14 (window / secondary bar buttons), 15 (primary buttons), 16 (dialog card).

**Shadows:** primary button `0 10px 24px -8px var(--accent)` (hover `0 12px 30px -8px`); dialog `0 30px 70px -20px rgba(0,0,0,.6)`; window `0 24px 60px -20px rgba(0,0,0,.5)`.

**Sizes:** tool rail 78px; rail button 58px; result column 372px; secondary bar button 120px; primary bar / secondary bar buttons 72px tall; dialog 480px; dialog inputs 40px; reference window 1180×724.

## Assets
- **Fonts:** IBM Plex Sans (Google Fonts) + a monospace. No licensing concerns.
- **Icons:** simple line icons drawn as inline SVG in the prototype (magnifier/scan, camera, target/crosshair, plus, gear, checkmark, "!"). Replace with the codebase's existing icon set (e.g. Lucide/Feather-style, 1.7px stroke, round caps/joins) — no custom artwork required.
- **Camera frame & detected object:** placeholder SVG in the prototype. In production this is the real camera video feed plus a vision-generated overlay (bounding box + measurement annotations).
- No raster images or logos.

## Screenshots
Reference renders at 1180×724, in `screenshots/` (dark and light for each state):
- `match-dark.png` / `match-light.png` — main workbench, successful match.
- `nomatch-dark.png` / `nomatch-light.png` — "Kein Treffer" state.
- `calibrate-dark.png` / `calibrate-light.png` — Calibrate dialog.
- `teach-dark.png` / `teach-light.png` — Teach-article dialog.

## Files
- `Doco Detect.dc.html` — the presentation page: global Dark/Light + DE/EN toggles and the option turns (the final direction is turn "4"; no-match is turn "5"). Uses the design-tool runtime; reference only.
- `Doco Workbench.dc.html` — **the actual UI component** (workbench layout, result card, tolerance gauge, candidates, history, both dialogs, and the no-match state). Props: `theme`, `lang`, `font`, `result`, `openDialog`. This is the primary file to recreate.
- `support.js` — the design-tool runtime. **Do not port.**

> Tip: open `Doco Workbench.dc.html` and read the `renderVals()` logic + template markup for exact values; this README mirrors them.
