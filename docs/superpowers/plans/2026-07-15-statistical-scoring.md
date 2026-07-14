# Statistisches Scoring + Scoring-Dashboard — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Das Stage-1-Scoring durch ein statistisch fundiertes Modell ersetzen (Gauß-Log-Likelihood mit Enrollment-Statistiken, Fisher-adaptive Gewichte, LLR-Entscheidung ACCEPT/AMBIGUOUS/REJECT) und ein Streamlit-Dashboard "Scoring-Analyse" bauen, das jeden `MatchReport` transparent aufschlüsselt.

**Architecture:** Enrollment-Shots liefern pro Artikel und Merkmal Mittelwert+Streuung (`reference_stats`-Tabelle, aus `reference_features` rekonstruierbar). `features.py` bekommt Ring-Zonen-Farbmerkmale (Lab-ΔE + H-S-Histogramme) und Solidity. `matcher.py` wird komplett neu: harter Vorfilter (unverändert, höhenkompensiert) → z-Scores mit σ_eff = √(σ_enroll² + σ_floor²) → Fisher-adaptive Gewichte → Log-Score, Softmax-Posterior, drei Ausgänge. `pipeline.identify()` speichert Capture+Report-JSON nach `data/captures/`. Neue Streamlit-Seite rendert ausschließlich `MatchReport`-Objekte; Batch-Aggregation (`reporting.py`) wird von CLI `evaluate` UND UI genutzt.

**Tech Stack:** Python 3.11+, OpenCV, NumPy, SQLite, Streamlit, Plotly (nur UI), pytest.

## Global Constraints

- Kein Modelltraining — alle Statistiken aus Enrollment-Daten + Config.
- Alle Parameter zentral in `config/config.yaml`, mit Kommentaren dokumentiert.
- UI ruft ausschließlich `pipeline.py` (plus `reporting.py`, `database.py`, `camera.py`, `calibration.py` für Setup/Anzeige) auf — niemals `matcher.py`/`features.py` direkt.
- Alle Längen in mm; Höhenkompensation pro Kandidat im Vorfilter bleibt exakt wie gehabt (`features.height_corrected_scale`, angewendet in `matcher.py`).
- Windows/PowerShell: `.venv\Scripts\Activate.ps1`, `python -m pip`, Tests via `.\.venv\Scripts\python.exe -m pytest tests/ -v`.
- Kein Linter/Formatter im Repo — keinen einführen.
- Commits nach jedem abgeschlossenen Teil (1, 2, 3, 5, 4); Reihenfolge 1→2→3→5→4.
- Sentinel-Konvention für Altdaten: `solidity <= 0` bzw. leere Listen (`lab_center`, `hs_hist_center`, …) heißen "Merkmal nicht vorhanden" (alte Referenz-JSONs) — solche Merkmale werden in Statistik und Scoring übersprungen, nie mit 0 verrechnet.

## Zentrale Formeln (Referenz für alle Tasks)

```
σ_eff(f)   = sqrt(σ_enroll(f)² + σ_floor(f)²)          σ_floor aus config
z(f)       = d(f) / σ_eff(f)                            d = Distanz Messung↔Referenz
logL(f)    = -0.5 · z(f)²                                Gauß-Log-Likelihood (o. Konstante)
log_score  = Σ_f w_eff(f)·logL(f) / Σ_f w_eff(f)         über die beim Kandidaten verfügbaren f
D(f)       = Var_Kandidaten(Referenzwerte bzw. Distanzen) / Mittel_Kandidaten(σ_eff(f)²)
D_norm     = D / Σ D                                     (nur wenn ≥2 Kandidaten und Σ D > 0)
w_eff(f)   = w_global(f) · (1 + α·D_norm(f)), danach auf Summe 1 normiert
posterior  = softmax(log_score / T)
ACCEPT     : max|z| des Siegers ≤ max_z_accept  UND  (log_score₁−log_score₂) ≥ min_llr_margin
             UND Sieger hat Enrollment-Referenzen
AMBIGUOUS  : Gate bestanden, Margin nicht (oder Sieger ohne Referenzen)
REJECT     : Gate verfehlt oder kein Kandidat im Vorfilter
```

Fisher-Zähler pro Merkmalstyp: **Skalar-Merkmale** (diameter_mm, circularity, solidity) → Varianz der Kandidaten-**Referenzmittelwerte**; **Prototyp-Merkmale** (delta_e_*, hist_*, hu_log) → Varianz der **gemessenen Distanzen** d_i über die Kandidaten (Prototypen sind Vektoren, die Distanz-zur-Messung ist ihre skalare Einbettung).

## Merkmalskatalog (verbindliche Namen)

| Feature-Key       | Typ      | Distanz d                                              | σ_floor-Key          |
|-------------------|----------|--------------------------------------------------------|----------------------|
| `diameter_mm`     | Skalar   | \|circle_diameter_mm − Enrollment-Mittel\| (Floor-Ebene beidseitig); ohne Stats: \|höhenkorrigiert − Nominal\| | `diameter_mm` (1.5)  |
| `circularity`     | Skalar   | \|x − μ\|                                              | `circularity` (0.02) |
| `solidity`        | Skalar   | \|x − μ\|                                              | `solidity` (0.015)   |
| `delta_e_center`  | Prototyp | ΔE-CIE76(Lab_messung, Lab-Prototyp), Zentrum r<0.6     | `delta_e` (3.0)      |
| `delta_e_rim`     | Prototyp | dito, Rand r>0.75                                      | `delta_e` (3.0)      |
| `hist_center`     | Prototyp | Bhattacharyya(H-S-Hist, Prototyp-Hist), Zentrum        | `hist_bhattacharyya` (0.05) |
| `hist_rim`        | Prototyp | dito, Rand                                             | `hist_bhattacharyya` (0.05) |
| `hu_log`          | Prototyp | mean(\|Δ\|) über 7 log-Hu-Komponenten                  | `hu_log` (0.15)      |

Fläche bleibt NUR Vorfilter (korreliert voll mit Durchmesser). Globale Farbmerkmale (`mean_hsv`, `hue_hist`) bleiben in `Features` erhalten (Rückwärtskompatibilität alter Referenz-JSONs), gehen aber NICHT ins Scoring.

## File Structure

| Datei | Aktion | Verantwortung |
|---|---|---|
| `docodetect/features.py` | Modify | +solidity, +Ring-Zonen (Lab/H-S), `EnrollmentStats`, `compute_enrollment_stats()`, Distanzhelfer, `extract(…, cfg)` |
| `docodetect/database.py` | Modify | Tabelle `reference_stats` (+Migration), `stats_for()`, Rebuild bei add/delete |
| `docodetect/matcher.py` | Rewrite | Vorfilter (unverändert) + statistisches Scoring + `FeatureScore`/`CandidateReport`/`MatchReport` |
| `docodetect/pipeline.py` | Modify | `identify()` → `MatchReport`, speichert Capture+JSON nach `data/captures/` |
| `docodetect/cli.py` | Modify | enroll druckt Stats, identify druckt Report, evaluate nutzt `reporting.py` |
| `docodetect/reporting.py` | Create | `load_reports()`, `summarize()` → `BatchSummary` (CLI + UI teilen sich das) |
| `config/config.yaml` | Modify | `features`-Block, `matching` neu (sigma_floors, feature_weights, alpha, Gates); alte Keys ersetzt |
| `ui_common.py` | Create | Kamera-/Bild-Helfer aus app.py extrahiert (von app.py + Dashboard-Seite genutzt) |
| `app.py` | Modify | importiert ui_common; Identify-Tab + Config-Tab auf neue Keys/Entscheidungen |
| `pages/1_Scoring_Analyse.py` | Create | Dashboard: Einzel-Report + Batch-Tab, Plotly |
| `requirements-ui.txt` | Modify | +plotly (UI-Deps liegen in diesem Repo hier, nicht in requirements.txt) |
| `tests/test_scoring.py` | Create | Stats, Fisher, Sigma-Floor, 3 Entscheidungen, JSON-Roundtrip, Zonen, Batch |
| `tests/test_pipeline_synthetic.py` | Modify | CREATE_CFG + Assertions auf neue Matcher-API |
| `README.md` | Modify | Abschnitt "Scoring" (Formeln + σ_floor-Messanleitung) |
| `CLAUDE.md` | Modify | Matcher-Invariante + Report-Ablage aktualisieren |

---

# TEIL 1 — ENROLLMENT-STATISTIKEN

### Task 1: `EnrollmentStats` + `compute_enrollment_stats()` in features.py

**Files:**
- Modify: `docodetect/features.py`
- Test: `tests/test_scoring.py` (neu)

**Interfaces (Produces):**
```python
SCALAR_FEATURES = ("diameter_mm", "circularity", "solidity")
PROTO_FEATURES  = ("delta_e_center", "delta_e_rim", "hist_center", "hist_rim", "hu_log")
ALL_FEATURES    = SCALAR_FEATURES + PROTO_FEATURES

def scalar_value(feats: Features, name: str) -> float | None
    # "diameter_mm" -> feats.circle_diameter_mm; "circularity"; "solidity" (None wenn <= 0 / fehlt)

@dataclass
class EnrollmentStats:
    n_shots: int
    scalar_mean: dict[str, float]      # nur vorhandene Keys
    scalar_std: dict[str, float]       # ddof=1; 0.0 bei n==1
    proto: dict[str, list[float]]      # Feature-Key -> Prototyp-Vektor (Lab / Hist / Hu)
    proto_std: dict[str, float]        # RMS der Shot-Distanzen zum Prototyp; 0.0 bei n==1
    def to_json(self) -> str
    @staticmethod
    def from_json(s: str) -> "EnrollmentStats"

def compute_enrollment_stats(feats_list: list[Features]) -> EnrollmentStats
```
In Teil 1 füllt `compute_enrollment_stats` nur `diameter_mm`, `circularity` (Skalar) und `hu_log` (Prototyp) — `solidity` und Zonen kommen in Teil 2 dazu (Task 4 erweitert dieselbe Funktion). `hu_log_distance(a, b) = float(np.abs(np.asarray(a)-np.asarray(b)).mean())` wird hier schon als Modul-Funktion angelegt.

- [ ] **Step 1: Failing Tests schreiben** (`tests/test_scoring.py`, Kopfzeilen wie in test_pipeline_synthetic mit `sys.path.insert`):

```python
import json, math, sys
from pathlib import Path
import numpy as np
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.features import (Features, EnrollmentStats,
                                 compute_enrollment_stats, hu_log_distance)

def fake_features(diameter=200.0, circ=0.90, hu=None, **kw) -> Features:
    return Features(
        equiv_diameter_mm=diameter, circle_diameter_mm=diameter,
        area_mm2=3.14159 * (diameter / 2) ** 2, perimeter_mm=3.14159 * diameter,
        circularity=circ, aspect_ratio=1.0,
        mean_hsv=[0.0, 0.0, 200.0], hue_hist=[1.0 / 32] * 32,
        mean_saturation=0.0, hu_moments=hu or [3.2, 8.0, 10.0, 10.0, 10.0, 10.0, 10.0],
        **kw)

def test_enrollment_stats_mean_and_std():
    shots = [fake_features(diameter=d, circ=c)
             for d, c in ((199.0, 0.90), (200.0, 0.91), (201.0, 0.92))]
    st = compute_enrollment_stats(shots)
    assert st.n_shots == 3
    assert math.isclose(st.scalar_mean["diameter_mm"], 200.0)
    assert math.isclose(st.scalar_std["diameter_mm"], 1.0)          # ddof=1
    assert math.isclose(st.scalar_mean["circularity"], 0.91)
    assert st.proto["hu_log"] == pytest.approx([3.2, 8.0, 10.0, 10.0, 10.0, 10.0, 10.0])
    assert st.proto_std["hu_log"] == pytest.approx(0.0)

def test_enrollment_stats_single_shot_has_zero_std():
    st = compute_enrollment_stats([fake_features()])
    assert st.scalar_std["diameter_mm"] == 0.0
    assert st.proto_std["hu_log"] == 0.0

def test_enrollment_stats_json_roundtrip():
    st = compute_enrollment_stats([fake_features(199.0), fake_features(201.0)])
    st2 = EnrollmentStats.from_json(st.to_json())
    assert st2 == st
```

- [ ] **Step 2:** `.\.venv\Scripts\python.exe -m pytest tests/test_scoring.py -v` → FAIL (ImportError EnrollmentStats).
- [ ] **Step 3: Implementieren** in features.py (nach den bestehenden Distanz-Helfern):

```python
# ---------- enrollment statistics (basis for the statistical matcher) ----------

SCALAR_FEATURES = ("diameter_mm", "circularity", "solidity")
PROTO_FEATURES = ("delta_e_center", "delta_e_rim", "hist_center", "hist_rim", "hu_log")
ALL_FEATURES = SCALAR_FEATURES + PROTO_FEATURES


def scalar_value(feats: Features, name: str) -> float | None:
    """Scalar feature accessor. None = not present (old reference JSONs
    predate solidity; 0 is the dataclass default and physically impossible)."""
    if name == "diameter_mm":
        return float(feats.circle_diameter_mm)
    if name == "circularity":
        return float(feats.circularity)
    if name == "solidity":
        s = float(getattr(feats, "solidity", 0.0))
        return s if s > 0.0 else None
    raise KeyError(name)


def hu_log_distance(a: list, b: list) -> float:
    return float(np.abs(np.asarray(a, dtype=np.float64)
                        - np.asarray(b, dtype=np.float64)).mean())


@dataclass
class EnrollmentStats:
    """Per-article statistics over all enrolled shots. Scalars get mean+std;
    vector features get a prototype (mean vector) + the RMS of the per-shot
    distances to that prototype as spread. Keys absent = feature not
    available for this article (e.g. references enrolled before ring zones
    existed)."""
    n_shots: int
    scalar_mean: dict = field(default_factory=dict)
    scalar_std: dict = field(default_factory=dict)
    proto: dict = field(default_factory=dict)
    proto_std: dict = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @staticmethod
    def from_json(s: str) -> "EnrollmentStats":
        return EnrollmentStats(**json.loads(s))


def _proto_stats(vectors: list[list[float]], dist_fn) -> tuple[list[float], float]:
    arr = np.asarray(vectors, dtype=np.float64)
    proto = arr.mean(axis=0)
    if len(vectors) < 2:
        return proto.tolist(), 0.0
    d = [dist_fn(v, proto.tolist()) for v in vectors]
    return proto.tolist(), float(np.sqrt(np.mean(np.square(d))))


def compute_enrollment_stats(feats_list: list[Features]) -> EnrollmentStats:
    st = EnrollmentStats(n_shots=len(feats_list))
    for name in SCALAR_FEATURES:
        vals = [v for f in feats_list if (v := scalar_value(f, name)) is not None]
        if not vals:
            continue
        st.scalar_mean[name] = float(np.mean(vals))
        st.scalar_std[name] = float(np.std(vals, ddof=1)) if len(vals) > 1 else 0.0
    hu = [f.hu_moments for f in feats_list if f.hu_moments]
    if hu:
        st.proto["hu_log"], st.proto_std["hu_log"] = _proto_stats(hu, hu_log_distance)
    return st
```
(Task 4 erweitert dieselbe Funktion um solidity-taugliche Zonen-Prototypen — solidity läuft schon jetzt über `scalar_value` und liefert einfach keine Werte, solange das Feld fehlt.)

- [ ] **Step 4:** `.\.venv\Scripts\python.exe -m pytest tests/test_scoring.py -v` → PASS; `.\.venv\Scripts\python.exe -m pytest tests/ -v` → alles grün (Bestand unberührt).

### Task 2: DB-Tabelle `reference_stats` + Migration + sigma_floors-Config

**Files:**
- Modify: `docodetect/database.py`, `docodetect/cli.py`, `config/config.yaml`
- Test: `tests/test_scoring.py`

**Interfaces (Produces):**
```python
Database.stats_for(article_number: str) -> EnrollmentStats | None
Database.recompute_all_stats() -> int          # Migration/Repair, gibt Anzahl Artikel zurück
# add_reference() und delete_article() halten reference_stats automatisch aktuell
```

- [ ] **Step 1: Failing Tests:**

```python
from docodetect.database import Article, Database

def _db(tmp_path) -> Database:
    db = Database({"paths": {"db_file": str(tmp_path / "t.sqlite3")}})
    db.init_schema()
    return db

def _add_article(db, nr="TELLER-200", d=200.0):
    db.create_article(Article(article_number=nr, name=nr, category=None,
                              diameter_mm=d, width_mm=None, depth_mm=None,
                              height_mm=None, color_desc=None, notes=None))

def test_add_reference_maintains_stats(tmp_path):
    db = _db(tmp_path); _add_article(db)
    try:
        db.add_reference("TELLER-200", fake_features(199.0))
        db.add_reference("TELLER-200", fake_features(201.0))
        st = db.stats_for("TELLER-200")
        assert st is not None and st.n_shots == 2
        assert math.isclose(st.scalar_mean["diameter_mm"], 200.0)
        assert st.scalar_std["diameter_mm"] > 0
    finally:
        db.close()

def test_stats_missing_returns_none_and_delete_clears(tmp_path):
    db = _db(tmp_path); _add_article(db)
    try:
        assert db.stats_for("TELLER-200") is None
        db.add_reference("TELLER-200", fake_features())
        assert db.stats_for("TELLER-200") is not None
        db.delete_article("TELLER-200")
        assert db.stats_for("TELLER-200") is None
    finally:
        db.close()

def test_migration_backfills_stats_for_existing_db(tmp_path):
    """Bestands-DB: Referenzen existieren, reference_stats (noch) nicht ->
    init_schema legt die Tabelle an und recompute_all_stats füllt sie."""
    db = _db(tmp_path); _add_article(db)
    db.add_reference("TELLER-200", fake_features())
    db.conn.execute("DROP TABLE reference_stats")     # simuliert alte DB
    db.conn.commit(); db.close()
    db2 = Database({"paths": {"db_file": str(tmp_path / "t.sqlite3")}})
    try:
        db2.init_schema()                              # Migration
        assert db2.stats_for("TELLER-200") is not None
    finally:
        db2.close()
```

- [ ] **Step 2:** Test-run → FAIL (`stats_for` fehlt).
- [ ] **Step 3: Implementieren.** In `SCHEMA` ergänzen:

```sql
CREATE TABLE IF NOT EXISTS reference_stats (
    article_number TEXT PRIMARY KEY REFERENCES articles(article_number),
    stats_json TEXT NOT NULL,
    updated_unix REAL DEFAULT (unixepoch())
);
```

database.py (Import `EnrollmentStats, compute_enrollment_stats` aus features):

```python
def _recompute_stats(self, article_number: str) -> None:
    """reference_stats is a pure cache over reference_features - rebuilt on
    every change so it can never go stale."""
    feats = self.references_for(article_number)
    if not feats:
        self.conn.execute("DELETE FROM reference_stats WHERE article_number = ?",
                          (article_number,))
        return
    self.conn.execute(
        "INSERT INTO reference_stats (article_number, stats_json) VALUES (?, ?) "
        "ON CONFLICT(article_number) DO UPDATE SET stats_json=excluded.stats_json, "
        "updated_unix=unixepoch()",
        (article_number, compute_enrollment_stats(feats).to_json()))

def stats_for(self, article_number: str) -> EnrollmentStats | None:
    row = self.conn.execute(
        "SELECT stats_json FROM reference_stats WHERE article_number = ?",
        (article_number,)).fetchone()
    return EnrollmentStats.from_json(row["stats_json"]) if row else None

def recompute_all_stats(self) -> int:
    nrs = self.articles_with_references()
    for nr in nrs:
        self._recompute_stats(nr)
    self.conn.commit()
    return len(nrs)
```

- `add_reference()`: vor `commit()` → `self._recompute_stats(article_number)`.
- `delete_article()`: zusätzlich `DELETE FROM reference_stats WHERE article_number = ?`.
- `init_schema()`: nach `executescript` → `n = self.recompute_all_stats()`; print erweitert um `f"({n} Artikel-Statistiken aktualisiert)"`. Das IST die Migration: `init-db` einmal laufen lassen genügt für Bestands-DBs.
- `cli.py cmd_enroll`: nach der Shot-Schleife Stats drucken:

```python
    st = pipe.db.stats_for(args.article_number)
    if st and "diameter_mm" in st.scalar_mean:
        print(f"[enroll] Statistik ({st.n_shots} Shots): "
              f"Ø {st.scalar_mean['diameter_mm']:.1f} ± {st.scalar_std['diameter_mm']:.2f} mm, "
              f"Rundheit {st.scalar_mean['circularity']:.3f} ± {st.scalar_std['circularity']:.4f}")
```
(im `--images`-Zweig vor dem `return`, im Live-Zweig vor `pipe.close()`.)

- `config/config.yaml`, im `matching:`-Block ergänzen:

```yaml
  # Mess-Rauschboden pro Merkmal: sigma_eff = sqrt(sigma_enroll^2 + sigma_floor^2).
  # Startwerte geschätzt - aus echten Messreihen justieren: denselben Artikel
  # 15-20x neu auflegen, die Standardabweichung je Merkmal ist der Floor
  # (siehe README, Abschnitt "Scoring").
  sigma_floors:
    diameter_mm: 1.5          # mm
    circularity: 0.02
    solidity: 0.015
    delta_e: 3.0              # Delta-E CIE76, gilt für Zentrum- UND Rand-Zone
    hist_bhattacharyya: 0.05  # gilt für beide Zonen-Histogramme
    hu_log: 0.15              # mittlere |Differenz| der log-Hu-Momente
```

- [ ] **Step 4:** `.\.venv\Scripts\python.exe -m pytest tests/ -v` → PASS.
- [ ] **Step 5: Commit Teil 1** (Bestätigung einholen):

```powershell
git add docodetect/features.py docodetect/database.py docodetect/cli.py config/config.yaml tests/test_scoring.py docs/superpowers/plans/2026-07-15-statistical-scoring.md
git commit -m "Teil 1: Enrollment-Statistiken (Mittelwert/Std je Merkmal, reference_stats-Tabelle, sigma_floors)"
```

---

# TEIL 2 — RING-FARBMERKMALE + SOLIDITY

### Task 3: Zonen-Extraktion + solidity in `extract()`

**Files:**
- Modify: `docodetect/features.py`, `docodetect/pipeline.py`, `config/config.yaml`
- Test: `tests/test_scoring.py`

**Interfaces (Produces):**
```python
# Neue Features-Felder (alle mit Default -> alte JSONs laden weiter):
solidity: float = 0.0
lab_center: list = field(default_factory=list)      # [L, a, b], CIE (L 0..100)
lab_rim: list = field(default_factory=list)
hs_hist_center: list = field(default_factory=list)  # H*S Bins flach, Summe 1
hs_hist_rim: list = field(default_factory=list)

def extract(image, seg, cal, cfg: dict | None = None) -> Features   # cfg NEU, optional
def delta_e_cie76(a: list, b: list) -> float
def bhattacharyya_distance(a: list, b: list) -> float
```
`pipeline.analyze()` ruft `extract(image, seg, self.cal, self.cfg)` auf.

- [ ] **Step 1: Failing Tests** (synthetisches Bild: weißer Teller mit rotem Rand):

```python
import cv2
from docodetect.calibration import Calibration
from docodetect.features import (bhattacharyya_distance, delta_e_cie76, extract)
from docodetect.segmentation import segment

MM_PER_PX = 0.2
CAL = Calibration(mm_per_px=MM_PER_PX, camera_height_mm=300.0, image_width=1920,
                  image_height=1080, marker_size_mm=50.0, created_unix=0.0)
SEG_CFG = {"segmentation": {"blur_kernel": 7, "diff_threshold": 25,
                            "morph_kernel": 15, "min_area_px": 5000,
                            "border_margin_px": 5}}

def _bg(fill=200):
    bg = np.full((1080, 1920, 3), fill, dtype=np.uint8)
    noise = np.random.default_rng(42).integers(-5, 5, bg.shape, dtype=np.int16)
    return np.clip(bg.astype(np.int16) + noise, 0, 255).astype(np.uint8)

def _red_rim_plate(bg, d_mm=200.0):
    img = bg.copy()
    r = int(round(d_mm / MM_PER_PX / 2))
    cv2.circle(img, (960, 540), r, (40, 40, 220), -1)      # rote Fahne (BGR)
    cv2.circle(img, (960, 540), int(r * 0.62), (250, 250, 250), -1)  # weißes Zentrum
    return img

def test_ring_zones_separate_center_and_rim_color():
    bg = _bg()
    img = _red_rim_plate(bg)
    seg = segment(img, bg, SEG_CFG)
    feats = extract(img, seg, CAL, SEG_CFG)
    assert feats.solidity > 0.9                       # Vollkreis
    assert len(feats.lab_center) == 3 and len(feats.lab_rim) == 3
    assert delta_e_cie76(feats.lab_center, feats.lab_rim) > 25   # weiß vs rot
    assert feats.lab_center[0] > feats.lab_rim[0]                # Zentrum heller
    assert abs(sum(feats.hs_hist_center) - 1.0) < 1e-3
    assert bhattacharyya_distance(feats.hs_hist_center, feats.hs_hist_rim) > 0.3

def test_features_json_backward_compatible():
    """Alte Referenz-JSONs (ohne Zonen/Solidity) müssen weiter laden."""
    old = fake_features().to_json()
    d = json.loads(old)
    for k in ("solidity", "lab_center", "lab_rim", "hs_hist_center", "hs_hist_rim"):
        d.pop(k, None)
    f = Features.from_json(json.dumps(d))
    assert f.solidity == 0.0 and f.lab_center == []
```
(`fake_features` aus Task 1 unverändert — die neuen Felder haben Defaults.)

- [ ] **Step 2:** Test-run → FAIL (`solidity` unbekannt / `delta_e_cie76` fehlt).
- [ ] **Step 3: Implementieren.**

config.yaml — neue Sektion nach `segmentation:` (NICHT in `_REQUIRED_SECTIONS` aufnehmen — Code nutzt `.get` mit denselben Defaults):

```yaml
features:
  # Ring-Zonen über die Distanztransformation der Objektmaske:
  # r = 1 - dist/dist_max, r=0 innerstes Pixel, r=1 Kontur.
  # Zentrum r < center_max, Rand/Fahne r > rim_min; die Übergangszone
  # dazwischen wird bewusst ignoriert (Dekorkante liegt nie exakt).
  ring_zones:
    center_max: 0.60
    rim_min: 0.75
  # H-S-Histogramm pro Zone: [Hue-Bins, Sättigungs-Bins] (OpenCV H 0-180, S 0-256)
  hs_hist_bins: [16, 8]
```

features.py — im Docstring Gruppe 2 um Zonen ergänzen; Implementierung:

```python
def delta_e_cie76(a: list, b: list) -> float:
    """CIE76: euklidischer Abstand im Lab-Raum - für Geschirr-Unifarben genug."""
    return float(np.linalg.norm(np.asarray(a, dtype=np.float64)
                                - np.asarray(b, dtype=np.float64)))


def bhattacharyya_distance(a: list, b: list) -> float:
    return float(cv2.compareHist(np.asarray(a, dtype=np.float32),
                                 np.asarray(b, dtype=np.float32),
                                 cv2.HISTCMP_BHATTACHARYYA))


def _zone_masks(mask: np.ndarray, center_max: float, rim_min: float):
    """Normierter Radius über die Distanztransformation: funktioniert für
    runde UND längliche Objekte (r folgt der Objektform, nicht einem Kreis)."""
    dist = cv2.distanceTransform((mask > 0).astype(np.uint8), cv2.DIST_L2, 5)
    dmax = float(dist.max())
    if dmax <= 0:
        return None, None
    r = 1.0 - dist / dmax
    inside = mask > 0
    center = np.where(inside & (r < center_max), np.uint8(255), np.uint8(0))
    rim = np.where(inside & (r > rim_min), np.uint8(255), np.uint8(0))
    return center, rim


def _zone_color(image_bgr: np.ndarray, hsv: np.ndarray, zone: np.ndarray | None,
                bins: tuple[int, int]) -> tuple[list, list]:
    if zone is None or not zone.any():
        return [], []
    lab = cv2.cvtColor(image_bgr.astype(np.float32) / 255.0, cv2.COLOR_BGR2Lab)
    mean_lab = lab[zone > 0].mean(axis=0)
    hist = cv2.calcHist([hsv], [0, 1], zone, list(bins), [0, 180, 0, 256]).flatten()
    s = hist.sum()
    hist = (hist / s) if s > 0 else hist
    return [round(float(v), 3) for v in mean_lab], [round(float(v), 6) for v in hist]
```

In `extract()` (Signatur `def extract(image, seg, cal, cfg: dict | None = None)`):

```python
    hull_area = cv2.contourArea(cv2.convexHull(c))
    solidity = area_px / hull_area if hull_area > 0 else 0.0

    fcfg = (cfg or {}).get("features", {})
    zones = fcfg.get("ring_zones", {})
    center_max = float(zones.get("center_max", 0.60))
    rim_min = float(zones.get("rim_min", 0.75))
    bins = tuple(fcfg.get("hs_hist_bins", [16, 8]))
    zc, zr = _zone_masks(seg.mask, center_max, rim_min)
    lab_center, hist_center = _zone_color(image, hsv, zc, bins)
    lab_rim, hist_rim = _zone_color(image, hsv, zr, bins)
```
und die neuen Felder in den `Features(...)`-Konstruktor (`solidity=round(solidity, 4)`, …). Die Lab-Konvertierung läuft pro Zone auf dem Vollbild — bei 2 Zonen ok; wer mag, zieht `lab` vor die beiden `_zone_color`-Aufrufe (einmal konvertieren, als Parameter reingeben — so umsetzen).

pipeline.py `analyze()`: `feats = extract(image, seg, self.cal, self.cfg)`.

- [ ] **Step 4:** `.\.venv\Scripts\python.exe -m pytest tests/ -v` → PASS (Bestandstests rufen `extract(img, seg, CAL)` ohne cfg — Defaults greifen).

### Task 4: Zonen-Prototypen in `compute_enrollment_stats` + `proto_distance`

**Files:**
- Modify: `docodetect/features.py`
- Test: `tests/test_scoring.py`

**Interfaces (Produces):**
```python
def proto_distance(feature: str, feats: Features, stats: EnrollmentStats) -> float | None
    # None wenn Messung ODER Stats das Merkmal nicht haben (Altbestand, Bin-Mismatch)
```

- [ ] **Step 1: Failing Tests:**

```python
from docodetect.features import proto_distance

def fake_features_full(diameter=200.0, circ=0.90, sol=0.95,
                       lab_c=(95.0, 0.0, 0.0), lab_r=(95.0, 0.0, 0.0),
                       peak_c=0, peak_r=0, hu=None) -> Features:
    def hist(peak):
        h = [0.0] * 128; h[peak] = 1.0; return h
    f = fake_features(diameter, circ, hu)
    f.solidity = sol
    f.lab_center, f.lab_rim = list(lab_c), list(lab_r)
    f.hs_hist_center, f.hs_hist_rim = hist(peak_c), hist(peak_r)
    return f

def test_stats_include_zone_prototypes_and_solidity():
    shots = [fake_features_full(lab_c=(94.0, 0.0, 0.0)),
             fake_features_full(lab_c=(96.0, 0.0, 0.0))]
    st = compute_enrollment_stats(shots)
    assert math.isclose(st.scalar_mean["solidity"], 0.95)
    assert st.proto["delta_e_center"] == pytest.approx([95.0, 0.0, 0.0])
    assert st.proto_std["delta_e_center"] == pytest.approx(1.0)   # RMS von (1,1)
    assert "hist_center" in st.proto and "delta_e_rim" in st.proto

def test_stats_skip_zones_for_legacy_references():
    st = compute_enrollment_stats([fake_features(), fake_features()])  # ohne Zonen
    assert "delta_e_center" not in st.proto
    assert "solidity" not in st.scalar_mean
    assert "hu_log" in st.proto                                   # das gibt es immer

def test_proto_distance():
    st = compute_enrollment_stats([fake_features_full()])
    m = fake_features_full(lab_c=(90.0, 3.0, 4.0))
    assert proto_distance("delta_e_center", m, st) == pytest.approx(
        math.sqrt(25 + 9 + 16))
    assert proto_distance("hist_center", m, st) == pytest.approx(0.0, abs=1e-6)
    assert proto_distance("delta_e_center", fake_features(), st) is None  # Messung ohne Zone
    assert proto_distance("hist_center", m,
                          compute_enrollment_stats([fake_features()])) is None
```

- [ ] **Step 2:** Test-run → FAIL.
- [ ] **Step 3: Implementieren.** `compute_enrollment_stats` erweitern (nach dem hu-Block):

```python
    _PROTO_SRC = {  # Modul-Konstante: Feature-Key -> (Features-Attribut, Distanzfunktion)
        "delta_e_center": ("lab_center", delta_e_cie76),
        "delta_e_rim": ("lab_rim", delta_e_cie76),
        "hist_center": ("hs_hist_center", bhattacharyya_distance),
        "hist_rim": ("hs_hist_rim", bhattacharyya_distance),
    }
    for key, (attr, dist_fn) in _PROTO_SRC.items():
        vecs = [v for f in feats_list if (v := getattr(f, attr, None))]
        if not vecs or len({len(v) for v in vecs}) != 1:
            continue                       # fehlt/inkonsistent (alte Referenzen)
        st.proto[key], st.proto_std[key] = _proto_stats(vecs, dist_fn)
    # Histogramm-Prototypen renormieren (Mittel normierter Histogramme ist es fast,
    # aber numerisch sauber):
    for key in ("hist_center", "hist_rim"):
        if key in st.proto:
            s = sum(st.proto[key])
            if s > 0:
                st.proto[key] = [v / s for v in st.proto[key]]
```

`proto_distance`:

```python
_PROTO_MEASURED_ATTR = {"delta_e_center": "lab_center", "delta_e_rim": "lab_rim",
                        "hist_center": "hs_hist_center", "hist_rim": "hs_hist_rim",
                        "hu_log": "hu_moments"}
_PROTO_DIST_FN = {"delta_e_center": delta_e_cie76, "delta_e_rim": delta_e_cie76,
                  "hist_center": bhattacharyya_distance, "hist_rim": bhattacharyya_distance,
                  "hu_log": hu_log_distance}


def proto_distance(feature: str, feats: Features, stats: EnrollmentStats) -> float | None:
    """Distanz Messung -> Enrollment-Prototyp. None, wenn eine Seite das
    Merkmal nicht hat (Referenzen von vor den Ring-Zonen, Bin-Änderung in der
    Config) - das Merkmal fällt dann für diesen Kandidaten aus dem Scoring."""
    proto = stats.proto.get(feature)
    measured = getattr(feats, _PROTO_MEASURED_ATTR[feature], None)
    if not proto or not measured or len(proto) != len(measured):
        return None
    return _PROTO_DIST_FN[feature](measured, proto)
```
(`_PROTO_SRC` als Modul-Konstante neben den beiden Maps definieren, nicht in der Funktion.)

- [ ] **Step 4:** `.\.venv\Scripts\python.exe -m pytest tests/ -v` → PASS.
- [ ] **Step 5: Commit Teil 2** (Bestätigung einholen):

```powershell
git add docodetect/features.py docodetect/pipeline.py config/config.yaml tests/test_scoring.py
git commit -m "Teil 2: Ring-Farbzonen (Lab-Delta-E + H-S-Histogramme), Solidity, Zonen-Prototypen"
```

---

# TEIL 3 — NEUER MATCHER

### Task 5: Report-Dataclasses + Feature-Scoring (ohne Adaption)

**Files:**
- Rewrite: `docodetect/matcher.py`
- Test: `tests/test_scoring.py`

**Interfaces (Produces):**
```python
DECISION_ACCEPT = "accept"; DECISION_AMBIGUOUS = "ambiguous"; DECISION_REJECT = "reject"

@dataclass
class FeatureScore:
    feature: str
    measured: float | None      # Skalar-Messwert; None bei Prototyp-Merkmalen
    reference: float | None     # Enrollment-Mittel bzw. Nominal; None bei Prototypen
    distance: float
    sigma_enroll: float
    sigma_eff: float
    z: float
    log_contrib: float          # -0.5 z^2
    w_eff: float                # normiertes Gewicht dieses Merkmals (global)
    weighted: float             # Beitrag zum log_score: w_eff*logL / sum(w_eff verfügbarer f)

@dataclass
class CandidateReport:
    article_number: str; name: str
    nominal_size_mm: float; height_mm: float
    corrected_diameter_mm: float; geometry_error_mm: float
    has_references: bool; n_shots: int
    features: list[FeatureScore]
    log_score: float; posterior: float; max_abs_z: float

@dataclass
class MatchReport:
    decision: str; message: str
    candidates: list[CandidateReport]           # ALLE Vorfilter-Überlebenden, sortiert
    feature_names: list[str]                    # Anzeige-Reihenfolge
    fisher_d: dict; fisher_d_norm: dict         # {} wenn Adaption entfiel
    w_global: dict; w_eff: dict                 # jeweils normiert
    alpha: float
    llr_margin: float | None                    # None bei <2 Kandidaten
    max_z_winner: float | None
    gate_passed: bool
    thresholds: dict                            # max_z_accept, min_llr_margin, softmax_temperature, top_k
    measured: dict                              # asdict(Features) der Messung
    contour: list | None                        # [[x,y],...] fürs Overlay (ausgedünnt)
    touches_border: bool | None
    timestamp: str                              # ISO-8601
    image_path: str | None
    label: str | None                           # Ground-Truth (evaluate/Batch)
    def to_dict(self) -> dict
    def to_json(self) -> str
    @staticmethod
    def from_dict(d: dict) -> "MatchReport"
    @staticmethod
    def from_json(s: str) -> "MatchReport"

def match(measured: Features, db: Database, cal: Calibration, cfg: dict,
          image_path: str | None = None, label: str | None = None,
          contour: list | None = None, touches_border: bool | None = None) -> MatchReport
```
**Consumes:** `db.stats_for()` (Task 2), `scalar_value/proto_distance/PROTO_FEATURES/SCALAR_FEATURES` (Tasks 1/4), `height_corrected_scale`. `_nominal_size_mm(article)` aus dem alten matcher.py wird 1:1 übernommen, ebenso der Flächen-Plausibilitätscheck.

Scoring-Regeln (verbindlich):
- Kandidat MIT Stats: `diameter_mm`-Distanz = |Messung(Floor) − scalar_mean| (Floor-gegen-Floor, KEINE Höhenkorrektur — Enrollment maß dasselbe Objekt in derselben Höhe); übrige Merkmale nur, wenn im jeweiligen `scalar_mean`/`proto` vorhanden.
- Kandidat OHNE Stats (geometry-only): einziges Merkmal `diameter_mm` mit Distanz = geometry_error_mm (höhenkorrigiert vs. Nominal), sigma_enroll = 0, reference = Nominal. `has_references=False` ⇒ kann nie ACCEPT werden.
- σ_floor-Zuordnung: `{"delta_e_center": "delta_e", "delta_e_rim": "delta_e", "hist_center": "hist_bhattacharyya", "hist_rim": "hist_bhattacharyya"}`, sonst Key direkt.
- log_score = Σ w_eff·logL / Σ w_eff über die beim Kandidaten VERFÜGBAREN Merkmale (Renormierung pro Kandidat; `FeatureScore.weighted` enthält genau den renormierten Summanden).
- Posterior: softmax(log_scores/T), numerisch stabil (max abziehen).

- [ ] **Step 1: Failing Tests** (Sigma-Floor + Roundtrip; Fisher/Entscheidungen kommen in Task 6):

```python
from docodetect.matcher import MatchReport, match

MATCH_CFG = {"matching": {
    "diameter_tolerance_mm": 6.0, "area_tolerance_pct": 12.0,
    "sigma_floors": {"diameter_mm": 1.5, "circularity": 0.02, "solidity": 0.015,
                     "delta_e": 3.0, "hist_bhattacharyya": 0.05, "hu_log": 0.15},
    "feature_weights": {"diameter_mm": 0.50, "circularity": 0.07, "solidity": 0.06,
                        "delta_e_center": 0.08, "delta_e_rim": 0.08,
                        "hist_center": 0.07, "hist_rim": 0.07, "hu_log": 0.07},
    "adaptive_weight_alpha": 2.0, "softmax_temperature": 1.0,
    "max_z_accept": 3.5, "min_llr_margin": 2.0, "top_k": 3,
}}

def _matcher_db(tmp_path, articles):
    """articles: list of (nr, nominal_d, [ref-Features])"""
    db = _db(tmp_path)
    for nr, d, refs in articles:
        _add_article(db, nr, d)
        for f in refs:
            db.add_reference(nr, f)
    return db

def test_sigma_floor_dominates_when_enrollment_std_zero(tmp_path):
    db = _matcher_db(tmp_path, [("A", 200.0, [fake_features_full(), fake_features_full()])])
    try:
        rep = match(fake_features_full(), db, CAL, MATCH_CFG)
        fs = {f.feature: f for f in rep.candidates[0].features}
        assert fs["diameter_mm"].sigma_eff == pytest.approx(1.5)
        assert fs["delta_e_center"].sigma_eff == pytest.approx(3.0)
        assert fs["diameter_mm"].z == pytest.approx(0.0)
        assert rep.candidates[0].log_score == pytest.approx(0.0)
    finally:
        db.close()

def test_sigma_eff_combines_enroll_and_floor(tmp_path):
    shots = [fake_features_full(diameter=198.0), fake_features_full(diameter=202.0)]
    db = _matcher_db(tmp_path, [("A", 200.0, shots)])   # std = 2*sqrt(2) mm
    try:
        rep = match(fake_features_full(diameter=200.0), db, CAL, MATCH_CFG)
        fs = {f.feature: f for f in rep.candidates[0].features}
        expected = math.sqrt(np.std([198.0, 202.0], ddof=1) ** 2 + 1.5 ** 2)
        assert fs["diameter_mm"].sigma_eff == pytest.approx(expected)
    finally:
        db.close()

def test_geometry_only_candidate_scored_on_diameter_alone(tmp_path):
    db = _matcher_db(tmp_path, [("A", 200.0, [])])
    try:
        rep = match(fake_features_full(diameter=202.0), db, CAL, MATCH_CFG)
        c = rep.candidates[0]
        assert not c.has_references
        assert [f.feature for f in c.features] == ["diameter_mm"]
        assert c.features[0].reference == pytest.approx(200.0)
        assert c.features[0].distance == pytest.approx(2.0)
    finally:
        db.close()

def test_matchreport_json_roundtrip(tmp_path):
    db = _matcher_db(tmp_path, [("A", 200.0, [fake_features_full()])])
    try:
        rep = match(fake_features_full(), db, CAL, MATCH_CFG,
                    image_path="x.jpg", label="A", contour=[[1, 2], [3, 4]],
                    touches_border=False)
        rep2 = MatchReport.from_json(rep.to_json())
        assert rep2.to_dict() == rep.to_dict()
        assert rep2.candidates[0].features[0].feature == rep.candidates[0].features[0].feature
    finally:
        db.close()
```

- [ ] **Step 2:** Test-run → FAIL (Import).
- [ ] **Step 3: Implementieren** — matcher.py komplett neu. Gerüst:

```python
def _feature_rows(measured, art, stats, corrected_d, geo_err, nominal):
    """-> dict feature -> (distance, sigma_enroll, measured_v, reference_v)"""
    rows = {}
    if stats is None:
        rows["diameter_mm"] = (geo_err, 0.0, corrected_d, nominal)
        return rows
    for name in SCALAR_FEATURES:
        mv = scalar_value(measured, name)
        if mv is None or name not in stats.scalar_mean:
            continue
        ref = stats.scalar_mean[name]
        rows[name] = (abs(mv - ref), stats.scalar_std.get(name, 0.0), mv, ref)
    for name in PROTO_FEATURES:
        d = proto_distance(name, measured, stats)
        if d is not None:
            rows[name] = (d, stats.proto_std.get(name, 0.0), None, None)
    return rows
```

`match()`-Ablauf:
1. Vorfilter-Schleife wie im alten Code (inkl. Flächencheck), sammelt `(art, corrected_d, geo_err, nominal, stats, rows)`.
2. Leere Kandidatenliste → `MatchReport(decision=DECISION_REJECT, message="Kein Artikel innerhalb der Geometrie-Toleranz – Objekt vermutlich nicht in der Datenbank.", candidates=[], gate_passed=False, …)`.
3. w_global aus `feature_weights` auf Summe 1 normieren (über ALL_FEATURES; fehlende Keys = 0 — aber Config liefert alle 8). In Task 5: w_eff = w_global, fisher_d = {} (Adaption kommt in Task 6 an genau markierter Stelle).
4. Pro Kandidat: FeatureScores bauen (σ_eff, z, logL), `wsum = Σ w_eff[f]` über verfügbare f, `weighted = w_eff[f]*logL/wsum`, `log_score = Σ weighted`, `max_abs_z`.
5. Sortieren nach log_score desc, Posterior = softmax(log_scores/T) mit max-Abzug.
6. Entscheidung (Task 5 minimal, Task 6 final — in Task 5 schon die drei Konstanten + Gate/Margin-Logik anlegen, Tests dafür in Task 6).
7. Report bauen: `timestamp=datetime.now().isoformat(timespec="seconds")`, thresholds-Dict, `measured=asdict(measured)`.

`to_dict` = `dataclasses.asdict(self)`; `from_dict` rekonstruiert verschachtelt:

```python
@staticmethod
def from_dict(d: dict) -> "MatchReport":
    d = dict(d)
    d["candidates"] = [CandidateReport(**{**c, "features": [FeatureScore(**f) for f in c["features"]]})
                       for c in d.get("candidates", [])]
    return MatchReport(**d)
```

- [ ] **Step 4:** Neue Tests PASS. (Bestandstests test_pipeline_synthetic sind jetzt ROT — alte match()-API weg. Das ist der Zwischenzustand; Task 7 zieht sie nach. Bis dahin nur `tests/test_scoring.py` grün-pflichtig.)

### Task 6: Fisher-Adaption + Softmax + Entscheidungslogik

**Files:**
- Modify: `docodetect/matcher.py`
- Test: `tests/test_scoring.py`

- [ ] **Step 1: Failing Tests:**

```python
def test_fisher_boosts_the_discriminative_feature(tmp_path):
    """Zwei Kandidaten, identisch bis auf die Zentrumsfarbe -> delta_e_center
    muss das höchste w_eff bekommen (Kern der adaptiven Gewichtung)."""
    a_shots = [fake_features_full(lab_c=(95.0, 0.0, 0.0))] * 2
    b_shots = [fake_features_full(lab_c=(55.0, 10.0, 10.0))] * 2
    db = _matcher_db(tmp_path, [("A", 200.0, a_shots), ("B", 200.0, b_shots)])
    try:
        rep = match(fake_features_full(lab_c=(95.0, 0.0, 0.0)), db, CAL, MATCH_CFG)
        assert max(rep.w_eff, key=rep.w_eff.get) == "delta_e_center"
        assert rep.w_eff["delta_e_center"] > rep.w_global["delta_e_center"]
        assert rep.fisher_d_norm["delta_e_center"] == max(rep.fisher_d_norm.values())
        assert rep.candidates[0].article_number == "A"
    finally:
        db.close()

def test_alpha_zero_keeps_global_weights(tmp_path):
    cfg = {"matching": {**MATCH_CFG["matching"], "adaptive_weight_alpha": 0.0}}
    db = _matcher_db(tmp_path, [("A", 200.0, [fake_features_full()] * 2),
                                ("B", 200.0, [fake_features_full(lab_c=(55.0, 0, 0))] * 2)])
    try:
        rep = match(fake_features_full(), db, CAL, cfg)
        for f in rep.w_eff:
            assert rep.w_eff[f] == pytest.approx(rep.w_global[f])
    finally:
        db.close()

def test_single_candidate_skips_adaptation(tmp_path):
    db = _matcher_db(tmp_path, [("A", 200.0, [fake_features_full()] * 2)])
    try:
        rep = match(fake_features_full(), db, CAL, MATCH_CFG)
        assert rep.fisher_d == {}
        assert rep.w_eff == pytest.approx(rep.w_global)
    finally:
        db.close()

def test_decision_accept(tmp_path):
    db = _matcher_db(tmp_path, [("A", 200.0, [fake_features_full()] * 3)])
    try:
        rep = match(fake_features_full(), db, CAL, MATCH_CFG)
        assert rep.decision == "accept" and rep.gate_passed
        assert rep.max_z_winner == pytest.approx(0.0)
        assert rep.candidates[0].posterior == pytest.approx(1.0)
    finally:
        db.close()

def test_decision_ambiguous_on_small_margin(tmp_path):
    """Fast identische Artikel -> Gate ok, LLR-Margin < Schwelle -> ambiguous."""
    db = _matcher_db(tmp_path, [("A", 200.0, [fake_features_full()] * 2),
                                ("B", 200.0, [fake_features_full(diameter=200.5)] * 2)])
    try:
        rep = match(fake_features_full(diameter=200.2), db, CAL, MATCH_CFG)
        assert rep.decision == "ambiguous"
        assert rep.gate_passed and rep.llr_margin is not None
        assert rep.llr_margin < 2.0
    finally:
        db.close()

def test_decision_reject_on_gate(tmp_path):
    """Durchmesser passt, aber Farbe völlig anders -> max|z| >> 3.5 -> reject."""
    db = _matcher_db(tmp_path, [("A", 200.0, [fake_features_full(lab_c=(95.0, 0, 0),
                                                                 lab_r=(95.0, 0, 0))] * 2)])
    try:
        m = fake_features_full(lab_c=(20.0, 30.0, 30.0), lab_r=(20.0, 30.0, 30.0))
        rep = match(m, db, CAL, MATCH_CFG)
        assert rep.decision == "reject" and not rep.gate_passed
        assert rep.max_z_winner > 3.5
        assert "nicht in der Datenbank" in rep.message
    finally:
        db.close()

def test_geometry_only_winner_never_accepts(tmp_path):
    db = _matcher_db(tmp_path, [("A", 200.0, [])])
    try:
        rep = match(fake_features_full(), db, CAL, MATCH_CFG)
        assert rep.decision == "ambiguous"        # Gate ok, aber keine Referenzen
    finally:
        db.close()
```

- [ ] **Step 2:** Test-run → FAIL.
- [ ] **Step 3: Implementieren.** Fisher-Block zwischen Rows-Sammlung und Scoring:

```python
    # ---- adaptive Gewichte: Fisher-Ratio über das Kandidatenset ----
    # D_f = Varianz der Kandidaten-Lagen / mittlere Messvarianz. Skalare
    # Merkmale nutzen die Referenz-MITTELWERTE als Lage; Prototyp-Merkmale
    # die gemessene Distanz d_i (skalare Einbettung der Vektor-Prototypen).
    fisher_d, fisher_d_norm = {}, {}
    w_eff = dict(w_global)
    if len(prelim) >= 2 and alpha > 0:
        for f in ALL_FEATURES:
            locs, sig2 = [], []
            for cand in prelim:
                row = cand.rows.get(f)
                if row is None:
                    continue
                dist, s_enroll, _, ref = row
                locs.append(ref if f in SCALAR_FEATURES and ref is not None else dist)
                sig2.append(s_enroll ** 2 + _sigma_floor(f, floors) ** 2)
            if len(locs) >= 2 and np.mean(sig2) > 0:
                fisher_d[f] = float(np.var(locs) / np.mean(sig2))
        total = sum(fisher_d.values())
        if total > 0:
            fisher_d_norm = {f: v / total for f, v in fisher_d.items()}
            w_eff = {f: w_global[f] * (1.0 + alpha * fisher_d_norm.get(f, 0.0))
                     for f in w_global}
            s = sum(w_eff.values())
            w_eff = {f: v / s for f, v in w_eff.items()}
```

Entscheidung inkl. Stufe-2-Hook:

```python
    best = candidates[0]
    llr = (candidates[0].log_score - candidates[1].log_score
           if len(candidates) > 1 else None)
    gate = best.max_abs_z <= max_z_accept
    if not gate:
        decision = DECISION_REJECT
        message = (f"Objekt vermutlich nicht in der Datenbank: bestes Merkmal-z "
                   f"{best.max_abs_z:.1f} > {max_z_accept} ({best.article_number}). "
                   "Niemals automatisch buchen.")
    elif (llr is None or llr >= min_llr) and best.has_references:
        decision = DECISION_ACCEPT
        message = (f"{best.article_number} akzeptiert "
                   f"(max|z| {best.max_abs_z:.2f}, LLR-Margin "
                   f"{'∞' if llr is None else f'{llr:.2f}'}, "
                   f"Posterior {best.posterior:.0%}).")
    else:
        # TODO(stage-2): Genau diese AMBIGUOUS-Fälle später an Stufe 2
        # (DINOv2 + FAISS, docodetect/embeddings.py) übergeben und deren
        # Nearest-Neighbor-Votum als zusätzliches Merkmal einrechnen.
        decision = DECISION_AMBIGUOUS
        reason = ("keine Enrollment-Referenzen" if not best.has_references
                  else f"LLR-Margin {llr:.2f} < {min_llr}")
        message = (f"{len(candidates)} Kandidat(en), manuelle Auswahl nötig "
                   f"({reason}). Top: {best.article_number}.")
```

- [ ] **Step 4:** `.\.venv\Scripts\python.exe -m pytest tests/test_scoring.py -v` → PASS.

### Task 7: Config-Umstellung + Pipeline-Report-Ablage + CLI/App nachziehen

**Files:**
- Modify: `config/config.yaml`, `docodetect/pipeline.py`, `docodetect/cli.py`, `app.py`, `tests/test_pipeline_synthetic.py`, `CLAUDE.md`
- Test: `tests/test_scoring.py`, `tests/test_pipeline_synthetic.py`

**Interfaces (Produces):**
```python
@dataclass
class IdentifyOutcome:
    features: Features | None
    segmentation: SegmentationResult | None
    report: MatchReport            # ersetzt result: MatchResult

Pipeline.identify(image, *, source_path: str | None = None,
                  label: str | None = None) -> IdentifyOutcome
# Speichert (wenn cfg.paths.captures_dir gesetzt): Capture-JPG (nur bei
# source_path=None) und Report-JSON nach data/captures/<YYYYmmdd-HHMMSS-fff>.{jpg,json}.
```

- [ ] **Step 1: Failing Tests** (Report-Ablage):

```python
from docodetect.pipeline import Pipeline

def test_identify_writes_report_json(tmp_path, monkeypatch):
    import docodetect.config as cfgmod
    monkeypatch.setattr(cfgmod, "project_root", lambda: tmp_path)  # resolve() -> tmp
    bg = _bg()
    cfg = {"segmentation": SEG_CFG["segmentation"], "matching": MATCH_CFG["matching"],
           "features": {}, "paths": {"db_file": str(tmp_path / "t.sqlite3"),
                                     "captures_dir": "captures"}}
    pipe = Pipeline.__new__(Pipeline)
    pipe.cfg, pipe.cal, pipe.background = cfg, CAL, bg
    pipe.db = Database(cfg); pipe.db.init_schema()
    try:
        img = _red_rim_plate(bg)
        out = pipe.identify(img)
        jsons = list((tmp_path / "captures").glob("*.json"))
        jpgs = list((tmp_path / "captures").glob("*.jpg"))
        assert len(jsons) == 1 and len(jpgs) == 1
        rep = MatchReport.from_json(jsons[0].read_text(encoding="utf-8"))
        assert rep.decision == out.report.decision
        assert rep.image_path and rep.contour
    finally:
        pipe.db.close()

def test_identify_border_touch_becomes_reject_report(tmp_path):
    bg = _bg()
    cfg = {"segmentation": SEG_CFG["segmentation"], "matching": MATCH_CFG["matching"],
           "paths": {"db_file": str(tmp_path / "t.sqlite3")}}   # kein captures_dir -> kein IO
    pipe = Pipeline.__new__(Pipeline)
    pipe.cfg, pipe.cal, pipe.background = cfg, CAL, bg
    pipe.db = Database(cfg); pipe.db.init_schema()
    try:
        img = bg.copy()
        cv2.circle(img, (30, 540), 500, (250, 250, 250), -1)    # ragt aus dem Bild
        out = pipe.identify(img)
        assert out.report.decision == "reject"
        assert "Segment" in out.report.message
        assert out.report.candidates == []
    finally:
        pipe.db.close()
```

- [ ] **Step 2:** Test-run → FAIL.
- [ ] **Step 3: pipeline.py implementieren:**

```python
def _thin_contour(seg) -> list | None:
    if seg is None or seg.contour is None:
        return None
    pts = seg.contour.reshape(-1, 2)
    step = max(1, len(pts) // 400)          # Overlay braucht keine 10k Punkte
    return pts[::step].astype(int).tolist()

class Pipeline:
    def identify(self, image, *, source_path=None, label=None) -> IdentifyOutcome:
        try:
            seg, feats = self.analyze(image)
        except SegmentationError as e:
            seg_err = e.segmentation
            report = MatchReport(
                decision=DECISION_REJECT, message=f"Segmentierung: {e}",
                candidates=[], feature_names=[], fisher_d={}, fisher_d_norm={},
                w_global={}, w_eff={}, alpha=0.0, llr_margin=None,
                max_z_winner=None, gate_passed=False, thresholds={},
                measured={}, contour=_thin_contour(seg_err),
                touches_border=getattr(seg_err, "touches_border", None),
                timestamp=datetime.now().isoformat(timespec="seconds"),
                image_path=source_path, label=label)
            self._save_capture_and_report(report, image, source_path)
            return IdentifyOutcome(None, seg_err, report)
        report = match(feats, self.db, self.cal, self.cfg,
                       image_path=source_path, label=label,
                       contour=_thin_contour(seg), touches_border=seg.touches_border)
        self._save_capture_and_report(report, image, source_path)
        return IdentifyOutcome(feats, seg, report)

    def _save_capture_and_report(self, report, image, source_path) -> None:
        """Jede Identifikation hinterlässt Capture + Report-JSON in
        data/captures/ - Futter für das Scoring-Dashboard (Batch-Analyse).
        Ohne paths.captures_dir (z.B. synthetische Tests) wird nichts geschrieben."""
        cap = self.cfg.get("paths", {}).get("captures_dir")
        if not cap:
            return
        d = resolve(cap); d.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
        if report.image_path is None and image is not None:
            p = d / f"{ts}.jpg"
            cv2.imwrite(str(p), image)
            report.image_path = str(p)
        (d / f"{ts}.json").write_text(report.to_json(), encoding="utf-8")
```
(Imports: `cv2`, `datetime`, `resolve`, `DECISION_REJECT`, `MatchReport`, `match`.)

- [ ] **Step 4: config.yaml `matching:` final** (ersetzt `weights` + `auto_accept_*` — Dashboard/CLI kennen nur noch die neuen Gates):

```yaml
matching:
  # --- Stufe 1a: harter geometrischer Vorfilter (höhenkompensiert pro Artikel) ---
  diameter_tolerance_mm: 6.0  # Kandidat bleibt, wenn |gemessen - DB| <= Toleranz
  area_tolerance_pct: 12.0    # zusätzlicher Flächenfilter in Prozent (nur Vorfilter,
                              # Fläche geht NICHT ins Scoring - korreliert mit Ø)
  # --- Stufe 1b: statistisches Scoring (siehe README "Scoring") ---
  sigma_floors:               # (Kommentarblock aus Teil 1 unverändert)
    diameter_mm: 1.5
    circularity: 0.02
    solidity: 0.015
    delta_e: 3.0
    hist_bhattacharyya: 0.05
    hu_log: 0.15
  # Globale Merkmalsgewichte (werden normiert; Verhältnis zählt).
  feature_weights:
    diameter_mm: 0.50
    circularity: 0.07
    solidity: 0.06
    delta_e_center: 0.08
    delta_e_rim: 0.08
    hist_center: 0.07
    hist_rim: 0.07
    hu_log: 0.07
  # Fisher-adaptive Gewichtung über das Kandidatenset:
  # w_eff = w_global * (1 + alpha * D_norm). alpha=0 = reine Globalgewichte.
  adaptive_weight_alpha: 2.0
  softmax_temperature: 1.0    # Posterior = softmax(log_score / T); T>1 = weicher
  # Entscheidungsschwellen (ersetzen die alten auto_accept_score/auto_accept_margin):
  max_z_accept: 3.5           # absolutes Gate: max |z| des Siegers über alle Merkmale
  min_llr_margin: 2.0         # Log-Likelihood-Vorsprung Platz 1 vs. 2 (2.0 ≈ e² ≈ 7.4x)
  top_k: 3                    # Vorschläge bei AMBIGUOUS
```

- [ ] **Step 5: cli.py nachziehen.** `_print_result`:

```python
def _print_result(outcome):
    r = outcome.report
    print(f"\n[{r.decision.upper()}] {r.message}")
    if outcome.features:
        f = outcome.features
        print(f"  measured (floor plane): Ø {f.circle_diameter_mm:.1f} mm, "
              f"area {f.area_mm2 / 100:.1f} cm², circularity {f.circularity:.3f}")
    top_k = int(r.thresholds.get("top_k", 3))
    for i, c in enumerate(r.candidates[:top_k], 1):
        ref = "" if c.has_references else "  [keine Referenzen – nur Geometrie]"
        print(f"  {i}. {c.article_number}  {c.name}  "
              f"Posterior {c.posterior:.0%}  log-Score {c.log_score:.2f}  "
              f"max|z| {c.max_abs_z:.1f}  Δgeo {c.geometry_error_mm:.1f} mm{ref}")
```
`cmd_identify`: `outcome = pipe.identify(_get_image(args, cfg), source_path=getattr(args, "image", None))`. `cmd_evaluate` wird in Task 10 umgebaut — hier nur minimal lauffähig halten: `pred = outcome.report.candidates[0].article_number if outcome.report.candidates else "NO_MATCH"` und `outcome = pipe.identify(load_image(img_path), source_path=str(img_path), label=truth)`.

- [ ] **Step 6: app.py nachziehen** (nur bestehende Tabs; Dashboard = Teil 4):
  - Identify-Tab: `r = outcome.report`; Ampel `accept→st.success / ambiguous→st.warning / reject→st.error`; Kandidatentabelle:

```python
                    rows = [{
                        "Rang": i + 1, "Artikel": c.article_number, "Name": c.name,
                        "Posterior": f"{c.posterior:.0%}", "log-Score": round(c.log_score, 2),
                        "max |z|": round(c.max_abs_z, 2),
                        "Δ Geometrie (mm)": c.geometry_error_mm,
                        "Ø korrigiert (mm)": c.corrected_diameter_mm,
                        "Referenzen?": c.has_references,
                    } for i, c in enumerate(r.candidates[:3])]
```
    plus `st.caption("Details: Seite 📊 Scoring-Analyse (Sidebar).")`.
  - Config-Tab Matching-Slider ersetzen:

```python
    m["max_z_accept"] = st.slider("max_z_accept (absolutes Gate, max |z| des Siegers)",
                                  1.0, 6.0, float(m.get("max_z_accept", 3.5)))
    m["min_llr_margin"] = st.slider("min_llr_margin (Log-Likelihood-Vorsprung 1. vs 2.)",
                                    0.0, 10.0, float(m.get("min_llr_margin", 2.0)))
    m["adaptive_weight_alpha"] = st.slider("adaptive_weight_alpha (0 = keine Adaption)",
                                           0.0, 5.0, float(m.get("adaptive_weight_alpha", 2.0)))
```

- [ ] **Step 7: tests/test_pipeline_synthetic.py nachziehen:** `CREATE_CFG["matching"]` durch den MATCH_CFG-Block ersetzen (Werte wie Task 5); Assertions: `result.candidates[0].article.article_number` → `result.candidates[0].article_number`; `match(feats, pipe.db, CAL, cfg)` Rückgabe heißt weiter `result`, hat aber `decision in {"accept","ambiguous","reject"}` — konkrete alte Asserts (`has_references`, Kandidat 1 = angelegter Artikel) bleiben gültig.
- [ ] **Step 8: CLAUDE.md:** Bullet "Stage 1 matcher decision logic" ersetzen durch die neue Kurzbeschreibung (z-Gate + LLR-Margin, accept/ambiguous/reject, geometry-only nie accept) und im Datenfluss `MatchResult` → `MatchReport (accept|ambiguous|reject)`; Satz ergänzen, dass identify Capture+Report-JSON nach data/captures/ schreibt und das Dashboard (`pages/1_Scoring_Analyse.py`) nur MatchReports rendert.
- [ ] **Step 9:** `.\.venv\Scripts\python.exe -m pytest tests/ -v` → ALLE grün.
- [ ] **Step 10: Commit Teil 3** (Bestätigung einholen):

```powershell
git add docodetect/matcher.py docodetect/pipeline.py docodetect/cli.py config/config.yaml app.py tests/ CLAUDE.md
git commit -m "Teil 3: Statistischer Matcher (z-Scores, Fisher-Gewichte, LLR-Entscheidung, MatchReport-Ablage)"
```

---

# TEIL 5 — VALIDIERUNG (Integration + README)

### Task 8: Synthetisches Testkit end-to-end

**Files:**
- Test: `tests/test_scoring.py`

- [ ] **Step 1: Tests schreiben:**

```python
def _synth_pipeline(tmp_path, bg, matching_overrides=None):
    cfg = {"segmentation": SEG_CFG["segmentation"], "features": {},
           "matching": {**MATCH_CFG["matching"], **(matching_overrides or {})},
           "create": {"round_circularity_min": 0.80, "round_aspect_min": 0.80,
                      "article_number_prefix": ""},
           "paths": {"db_file": str(tmp_path / "t.sqlite3")}}
    pipe = Pipeline.__new__(Pipeline)
    pipe.cfg, pipe.cal, pipe.background = cfg, CAL, bg
    pipe.db = Database(cfg); pipe.db.init_schema()
    return pipe

def _plate(bg, d_mm, jitter=0):
    img = bg.copy()
    r = int(round(d_mm / MM_PER_PX / 2)) + jitter
    cv2.circle(img, (960, 540), r, (250, 250, 250), -1)
    cv2.circle(img, (960, 540), r, (150, 150, 150), 3)
    return img

def test_plates_250_vs_270_cleanly_separated(tmp_path):
    """Regime 'ähnliche Größe': Toleranz so weit, dass BEIDE Teller den
    Vorfilter überleben - das Scoring (Fisher boostet diameter) muss trennen."""
    bg = _bg()
    pipe = _synth_pipeline(tmp_path, bg, {"diameter_tolerance_mm": 25.0})
    try:
        for nr, d in (("TELLER-250", 250.0), ("TELLER-270", 270.0)):
            _add_article(pipe.db, nr, d)
            for j in (-1, 0, 1):                      # 3 Shots mit Pixel-Jitter
                seg, feats = pipe.analyze(_plate(bg, d, j))
                pipe.db.add_reference(nr, feats)
        for truth, d in (("TELLER-250", 250.0), ("TELLER-270", 270.0)):
            out = pipe.identify(_plate(bg, d))
            rep = out.report
            assert len(rep.candidates) == 2           # beide im Kandidatenset
            assert rep.candidates[0].article_number == truth
            assert rep.decision == "accept", rep.message
            assert rep.w_eff["diameter_mm"] > rep.w_global["diameter_mm"]  # Fisher greift
    finally:
        pipe.db.close()

def test_border_clipped_plate_is_segmentation_reject_not_scored(tmp_path):
    bg = _bg()
    pipe = _synth_pipeline(tmp_path, bg)
    try:
        _add_article(pipe.db, "TELLER-210", 210.0)
        img = bg.copy()
        cv2.circle(img, (30, 540), int(210.0 / MM_PER_PX / 2), (250, 250, 250), -1)
        out = pipe.identify(img)
        assert out.report.decision == "reject"
        assert "Segment" in out.report.message and out.report.candidates == []
    finally:
        pipe.db.close()

def test_unknown_object_rejected(tmp_path):
    """5. Testkit-Bild: Objekt, das keiner Artikelgeometrie entspricht."""
    bg = _bg()
    pipe = _synth_pipeline(tmp_path, bg)
    try:
        _add_article(pipe.db, "TELLER-270", 270.0)
        out = pipe.identify(_plate(bg, 120.0))        # viel zu klein
        assert out.report.decision == "reject"
    finally:
        pipe.db.close()
```

- [ ] **Step 2:** `.\.venv\Scripts\python.exe -m pytest tests/ -v` → PASS (sonst Matcher fixen, nicht Tests aufweichen).

### Task 9: README "Scoring" + σ_floor-Anleitung

**Files:**
- Modify: `README.md`

- [ ] **Step 1:** Nach dem Abschnitt "Höhenkompensation" neuen Abschnitt einfügen:

```markdown
## Scoring (Stufe 1, statistisch)

Jedes Merkmal f wird als Gauß-Messung modelliert:

    sigma_eff(f) = sqrt(sigma_enroll(f)² + sigma_floor(f)²)
    z(f)    = d(f) / sigma_eff(f)          d = Distanz Messung ↔ Enrollment-Referenz
    logL(f) = −0.5 · z(f)²                 (Log-Likelihood bis auf Konstante)

`sigma_enroll` kommt aus den Enrollment-Shots (Mittelwert/Std je Artikel,
Tabelle `reference_stats`), `sigma_floor` aus `matching.sigma_floors`
(Mess-Rauschboden, verhindert Division durch ~0 bei wenigen Shots).

**Merkmale:** Ø (mm), Rundheit, Solidity, ΔE-CIE76 + H-S-Histogramm getrennt
für Zentrum (r < 0.6) und Rand/Fahne (r > 0.75, `features.ring_zones`),
log-Hu-Momente. Fläche ist nur Vorfilter (korreliert voll mit Ø).

**Adaptive Gewichte (Fisher-Ratio):** pro Merkmal über das Kandidatenset
D_f = Var(Kandidaten-Lagen) / Mittel(sigma_eff²) — trennt ein Merkmal die
aktuellen Kandidaten gut, bekommt es mehr Gewicht:
w_eff = w_global · (1 + α · D_norm), α = `matching.adaptive_weight_alpha`
(0 = aus). Bei nur einem Kandidaten entfällt die Adaption.

**Entscheidung:**
- ACCEPT: max |z| des Siegers ≤ `max_z_accept` UND log-Score-Vorsprung zu
  Platz 2 ≥ `min_llr_margin` (2.0 ≈ e² ≈ 7.4× wahrscheinlicher) UND der
  Sieger hat eingelernte Referenzen.
- AMBIGUOUS: Gate bestanden, Margin nicht → Top-k zur manuellen Auswahl
  (hier übernimmt später Stufe 2 / DINOv2).
- REJECT: Gate verfehlt → "Objekt vermutlich nicht in der Datenbank",
  wird niemals automatisch gebucht.

Jede Identifikation legt Capture + `MatchReport`-JSON unter `data/captures/`
ab; die Streamlit-Seite **📊 Scoring-Analyse** schlüsselt jeden Report auf
(z-Werte, Gewichte, Posterior, Top-1-vs-Top-2) und aggregiert Ordner zu
Genauigkeit/Verwechslungsmatrix (gleiche Logik wie `evaluate`).

### sigma_floors aus einer echten Messreihe bestimmen

1. Einen Artikel wählen, 15–20× neu in die Box legen (jedes Mal anheben,
   leicht drehen/verschieben) und jeweils identifizieren oder einlernen.
2. Pro Merkmal die Standardabweichung über die Messreihe berechnen — bei
   `evaluate`/Batch-Reports stehen die Messwerte in den Report-JSONs
   (`measured`), sonst `enroll --shots 20` und `reference_stats` auslesen.
3. Diese Std je Merkmal ist der Floor → in `matching.sigma_floors` eintragen.
   Für ΔE/Histogramm: Distanzen der Einzelshots zum Mittel (steht als
   `proto_std` in `reference_stats`).
```

- [ ] **Step 2:** README-Workflow-Abschnitt: beim `identify`-Beispiel Zeile ergänzen `# -> legt Capture + Scoring-Report (JSON) unter data/captures/ ab`.
- [ ] **Step 3:** `.\.venv\Scripts\python.exe -m pytest tests/ -v` → grün (Doku-Task, Sicherheitslauf).
- [ ] **Step 4: Commit Teil 5** (Bestätigung einholen):

```powershell
git add tests/test_scoring.py README.md
git commit -m "Teil 5: Integrationstests (25/27-Trennung, Border-Reject, Unknown) + README-Scoring-Doku"
```

---

# TEIL 4 — SCORING-DASHBOARD

### Task 10: `reporting.py` + evaluate-Umbau

**Files:**
- Create: `docodetect/reporting.py`
- Modify: `docodetect/cli.py`
- Test: `tests/test_scoring.py`

**Interfaces (Produces):**
```python
@dataclass
class BatchSummary:
    total: int; labeled: int; correct: int
    accuracy: float                              # correct/labeled, 0.0 wenn labeled==0
    decision_counts: dict[str, int]              # accept/ambiguous/reject
    confusion: list[tuple[str, str, int]]        # (truth, predicted, n), nur Fehler, absteigend
    posteriors_correct: list[float]; posteriors_wrong: list[float]
    per_class: dict[str, dict[str, int]]         # truth -> {predicted: n}

def predicted_article(report: MatchReport) -> str        # Top-1 oder "NO_MATCH"
def summarize(reports: list[MatchReport]) -> BatchSummary
def load_reports(folder: str | Path, limit: int | None = None) -> list[tuple[Path, MatchReport]]
    # nach mtime absteigend; defekte JSONs überspringen
def format_summary(s: BatchSummary) -> str               # CLI-Textblock
```

- [ ] **Step 1: Failing Tests:**

```python
from docodetect.reporting import BatchSummary, load_reports, summarize

def _mini_report(decision, label, winner, posterior) -> MatchReport:
    cand = [CandidateReport(article_number=winner, name=winner, nominal_size_mm=200.0,
                            height_mm=0.0, corrected_diameter_mm=200.0,
                            geometry_error_mm=0.0, has_references=True, n_shots=2,
                            features=[], log_score=-0.1, posterior=posterior,
                            max_abs_z=0.5)] if winner != "NO_MATCH" else []
    return MatchReport(decision=decision, message="", candidates=cand,
                       feature_names=[], fisher_d={}, fisher_d_norm={}, w_global={},
                       w_eff={}, alpha=2.0, llr_margin=None, max_z_winner=0.5,
                       gate_passed=decision != "reject", thresholds={}, measured={},
                       contour=None, touches_border=False,
                       timestamp="2026-07-15T12:00:00", image_path=None, label=label)

def test_summarize_accuracy_confusion_and_posteriors():
    reps = [_mini_report("accept", "A", "A", 0.9),
            _mini_report("ambiguous", "A", "B", 0.6),
            _mini_report("reject", "C", "NO_MATCH", 0.0),
            _mini_report("accept", None, "A", 0.8)]      # ungelabelt zählt nicht in accuracy
    s = summarize(reps)
    assert s.total == 4 and s.labeled == 3 and s.correct == 1
    assert s.accuracy == pytest.approx(1 / 3)
    assert s.decision_counts == {"accept": 2, "ambiguous": 1, "reject": 1}
    assert ("A", "B", 1) in s.confusion and ("C", "NO_MATCH", 1) in s.confusion
    assert s.posteriors_correct == [0.9] and 0.6 in s.posteriors_wrong

def test_load_reports_skips_broken_json(tmp_path):
    (tmp_path / "a.json").write_text(_mini_report("accept", "A", "A", 0.9).to_json(),
                                     encoding="utf-8")
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    loaded = load_reports(tmp_path)
    assert len(loaded) == 1 and loaded[0][1].decision == "accept"
```
(Import `CandidateReport` oben ergänzen.)

- [ ] **Step 2:** Test-run → FAIL.
- [ ] **Step 3: reporting.py implementieren** (Modul-Docstring: "Batch-Aggregation über MatchReport-JSONs — EINE Implementierung für CLI `evaluate` und das Streamlit-Dashboard."). `summarize`: über Reports iterieren, `pred = predicted_article(r)`; wenn `r.label`: labeled++, korrekt→posteriors_correct.append(top-posterior), falsch→confusion-Counter + posteriors_wrong. `format_summary`: Accuracy-Zeile wie bisher (`=== top-1 accuracy: … ===`), Decision-Anteile in %, Confusion-Paare absteigend mit dem alten Hinweistext ("shortlist for stage 2").
- [ ] **Step 4: cli.py `cmd_evaluate`** ersetzen:

```python
def cmd_evaluate(args, cfg):
    from .reporting import format_summary, summarize
    pipe = Pipeline(cfg)
    reports = []
    for class_dir in sorted(p for p in Path(args.testset).iterdir() if p.is_dir()):
        for img_path in sorted(class_dir.glob("*.[jp][pn]g")):
            out = pipe.identify(load_image(img_path),
                                source_path=str(img_path), label=class_dir.name)
            reports.append(out.report)
            pred = out.report.candidates[0].article_number if out.report.candidates else "NO_MATCH"
            if pred != class_dir.name:
                print(f"  MISS {img_path.name}: {class_dir.name} -> {pred} "
                      f"[{out.report.decision}]")
    print(format_summary(summarize(reports)))
    pipe.close()
```
(Report-JSONs landen dabei automatisch in data/captures/ → Batch-Tab kann sie laden.)

- [ ] **Step 5:** `.\.venv\Scripts\python.exe -m pytest tests/ -v` → PASS.

### Task 11: `ui_common.py` + Dashboard-Seite (Einzel-Report)

**Files:**
- Create: `ui_common.py`, `pages/1_Scoring_Analyse.py`
- Modify: `app.py`, `requirements-ui.txt`

- [ ] **Step 1:** `requirements-ui.txt` → Zeile `plotly>=5.18` ergänzen; installieren: `python -m pip install plotly` (in aktivierter venv).
- [ ] **Step 2: ui_common.py:** aus app.py die Funktionen `get_camera`, `release_camera`, `capture_frame`, `resize_width`, `make_overlay` und die Konstante `CAMERA_HINT` unverändert hierher verschieben (gleiche Docstrings); zusätzlich:

```python
def draw_report_overlay(image: np.ndarray, report) -> np.ndarray:
    """Kontur-Overlay aus dem im MatchReport gespeicherten Polygon - funktioniert
    auch für aus JSON geladene Reports (keine SegmentationResult nötig)."""
    out = image.copy()
    if report.contour:
        pts = np.asarray(report.contour, dtype=np.int32).reshape(-1, 1, 2)
        color = (0, 0, 255) if report.touches_border else (0, 255, 0)
        cv2.polylines(out, [pts], isClosed=True, color=color, thickness=3)
    return out
```
app.py: die fünf Definitionen löschen, dafür `from ui_common import (CAMERA_HINT, capture_frame, get_camera, make_overlay, release_camera, resize_width)` (nur die dort noch genutzten Namen importieren). Smoke: `streamlit run app.py` startet ohne Fehler.
- [ ] **Step 3: pages/1_Scoring_Analyse.py** — vollständige Struktur:

```python
"""📊 Scoring-Analyse: rendert ausschließlich MatchReport-Objekte.

Datenquellen: live (pipeline.identify über die echte BoxCamera) oder
gespeicherte Report-JSONs aus data/captures/ (Pipeline legt sie bei jeder
Identifikation automatisch ab). Keine eigene Bildverarbeitung - alles kommt
aus docodetect/{pipeline,reporting}.py.
"""
from __future__ import annotations
from pathlib import Path
import cv2, numpy as np, pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from docodetect.config import load_config, resolve
from docodetect.pipeline import Pipeline
from docodetect.reporting import load_reports, predicted_article, summarize
from ui_common import CAMERA_HINT, capture_frame, draw_report_overlay, resize_width

st.set_page_config(page_title="Scoring-Analyse", layout="wide")
st.title("📊 Scoring-Analyse")
cfg = st.session_state.get("cfg") or load_config()

Z_GREEN, Z_YELLOW = 1.0, 2.5
DECISION_BADGE = {"accept": ("🟢 ACCEPT", st.success),
                  "ambiguous": ("🟡 AMBIGUOUS", st.warning),
                  "reject": ("🔴 REJECT", st.error)}

def z_color(z):
    return ("background-color:#1a7f37;color:white" if abs(z) < Z_GREEN
            else "background-color:#b58900;color:white" if abs(z) < Z_YELLOW
            else "background-color:#b02a37;color:white")
```

  Danach zwei Tabs `st.tabs(["Einzel-Report", "Batch-Auswertung"])`. Einzel-Report-Tab:
  1. **Quelle:** Button "🔍 Live identifizieren" (capture_frame → `Pipeline(cfg)` → `pipe.identify(frame)` → Report+Frame in `st.session_state["analysis_report"/"analysis_frame"]`) und darunter `st.selectbox` über `load_reports(resolve(cfg["paths"]["captures_dir"]), limit=25)` (Label = `f"{p.name} · {rep.decision} · {predicted_article(rep)}"`); Auswahl lädt Bild via `cv2.imread(rep.image_path)` (Fallback-Info, wenn Datei fehlt).
  2. **Gate-Ampel:** `DECISION_BADGE[rep.decision]`-Aufruf mit `rep.message`; drei `st.metric`: "max |z| Sieger" (`rep.max_z_winner` vs `rep.thresholds["max_z_accept"]` als Delta), "LLR-Margin" (vs `min_llr_margin`), "Posterior Top-1".
  3. **Bild + Overlay:** zwei Spalten, Original + `draw_report_overlay`; Caption nennt Randstatus (`rep.touches_border`).
  4. **Gemessene Merkmale:** `pd.DataFrame([rep.measured])` ausgewählter Spalten (Ø, Fläche, Rundheit, Solidity, Lab-Zonen) + pro Kandidat Zeile `corrected_diameter_mm` ("roh + höhenkompensiert pro Kandidat").
  5. **Kandidatentabelle:** pro Kandidat × Merkmal aus `c.features`: Distanz, σ_eff, z (Styler `.map(z_color, subset=["z"])`), logL, w_eff, weighted; Summenzeile log_score + Posterior in %. Eine Tabelle pro Kandidat (Expander, Top-k aufgeklappt) — Summen als letzte Zeile.
  6. **Balkendiagramm Log-Beiträge:** `px.bar` — x=Merkmal, y=`weighted`, color=Artikel (Top-k), `barmode="group"`, Titel "Gewichtete Log-Beiträge — welches Merkmal trägt die Entscheidung?".
  7. **Diskriminanz-Panel:** `go.Figure` mit zwei Bar-Traces w_global vs w_eff pro Merkmal + separater `px.bar` der `fisher_d_norm` (Hinweis-Caption, wenn leer: "Adaption entfiel — nur 1 Kandidat oder α=0").
  8. **Kontrast Top-1 vs Top-2** (nur wenn ≥2 Kandidaten): DataFrame pro Merkmal mit z₁, z₂, Δweighted = weighted₁−weighted₂, Spalte "Vorteil" = Artikelnummer des Besseren; Caption „direkte Antwort auf ‚warum A statt B?'".
- [ ] **Step 4: Smoke-Test:** `streamlit run app.py`, Seite öffnen, gespeicherten Report aus einem Test-Ordner laden (einen per `test_identify_writes_report_json`-Mechanik erzeugten JSON nach data/captures kopieren, falls leer). Zusätzlich Import-Smoke ohne Browser: `.\.venv\Scripts\python.exe -c "import ast; ast.parse(open('pages/1_Scoring_Analyse.py', encoding='utf-8').read())"`.

### Task 12: Batch-Tab

**Files:**
- Modify: `pages/1_Scoring_Analyse.py`

- [ ] **Step 1:** Batch-Tab implementieren:

```python
with tab_batch:
    folder = st.text_input("Report-Ordner", value=str(resolve(cfg["paths"]["captures_dir"])))
    reports = [r for _, r in load_reports(folder)]
    if not reports:
        st.info("Keine Report-JSONs gefunden.")
    else:
        s = summarize(reports)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Reports", s.total)
        c2.metric("Top-1-Accuracy", f"{s.accuracy:.1%}" if s.labeled else "– (keine Labels)")
        c3.metric("ACCEPT-Anteil", f"{s.decision_counts.get('accept', 0) / s.total:.0%}")
        c4.metric("REJECT-Anteil", f"{s.decision_counts.get('reject', 0) / s.total:.0%}")
        st.plotly_chart(px.pie(names=list(s.decision_counts), values=list(s.decision_counts.values()),
                               title="Entscheidungsverteilung"))
        if s.posteriors_correct or s.posteriors_wrong:
            df = pd.DataFrame([{"Posterior": p, "Ergebnis": "korrekt"} for p in s.posteriors_correct]
                              + [{"Posterior": p, "Ergebnis": "falsch"} for p in s.posteriors_wrong])
            st.plotly_chart(px.histogram(df, x="Posterior", color="Ergebnis", barmode="overlay",
                                         nbins=20, title="Posterior-Verteilung korrekt vs. falsch"))
        if s.per_class:
            labels = sorted(s.per_class)
            preds = sorted({p for row in s.per_class.values() for p in row})
            z = [[s.per_class[t].get(p, 0) for p in preds] for t in labels]
            st.plotly_chart(px.imshow(z, x=preds, y=labels, text_auto=True,
                                      title="Verwechslungsmatrix (Wahrheit × Vorhersage)"))
```
- [ ] **Step 2:** Smoke: Batch-Tab mit den durch `evaluate`/Tests erzeugten JSONs prüfen; `.\.venv\Scripts\python.exe -m pytest tests/ -v` → grün.
- [ ] **Step 3: Commit Teil 4** (Bestätigung einholen):

```powershell
git add docodetect/reporting.py docodetect/cli.py ui_common.py app.py pages/ requirements-ui.txt tests/test_scoring.py
git commit -m "Teil 4: Scoring-Dashboard (Einzel-Report + Batch), reporting.py fuer CLI+UI, Plotly"
```

---

## Self-Review (durchgeführt)

- **Spec-Abdeckung:** Punkte 1–2→Tasks 1–2; 3–6→Tasks 3–4 (Fläche bleibt Vorfilter: Task 7 config-Kommentar; Rundheit/Hu waren schon da, Solidity neu); 7–12→Tasks 5–7 (Hook: Task 6 TODO; deprecated-Keys: ersetzt in Task 7); 13–15→Tasks 10–12; 16–18→Tasks 1/2/5/6/8 (Tests) + Task 9 (README).
- **Bewusste Abweichung:** Plotly in `requirements-ui.txt` statt `requirements.txt` — Repo-Konvention (UI-Deps getrennt, Stage 1 bleibt headless); im Commit-Text nicht verstecken.
- **Typkonsistenz geprüft:** `stats_for`/`EnrollmentStats` (Task 2→5), `proto_distance` (Task 4→5), `MatchReport`-Felder (Task 5→7→10→11), `IdentifyOutcome.report` (Task 7→10/11), `BatchSummary` (Task 10→12), `fake_features`/`fake_features_full`/`_db`/`_add_article`/`_matcher_db` (Task 1→4→5→6→8).
- **Bekannter Zwischenzustand:** Nach Task 5/6 ist `tests/test_pipeline_synthetic.py` rot (alte Matcher-API); Task 7 zieht nach — Commit erfolgt erst am Ende von Teil 3, wenn ALLES grün ist.
