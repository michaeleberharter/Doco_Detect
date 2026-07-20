# Korpus-Regressions-Harness — Implementierungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ein zweistufiges Regressions-Harness, das jede Änderung am Messpfad gegen 143 echte, bewertete Aufnahmen prüft und Drift von Regression unterscheidet.

**Architecture:** Neues Paket `docodetect/corpus/` mit sechs Modulen (manifest, bundle, compare, runner, triage, cli). Der Replay läuft ausschliesslich über `pipeline.measure_shot()` und `Pipeline.identify()` gegen eine pro Session gebaute Bündel-Config mit `paths.captures_dir: None` — dadurch bleibt der Messpfad unberührt und der Replay schreibt nichts. Parallelisierung über `concurrent.futures.ProcessPoolExecutor` aus der stdlib.

**Tech Stack:** Python 3, OpenCV, NumPy, PyYAML, sqlite3, multiprocessing — alles bereits vorhanden.

**Spec:** [docs/superpowers/specs/2026-07-20-corpus-harness-design.md](../specs/2026-07-20-corpus-harness-design.md)

## Global Constraints

- **Messpfad read-only.** `pipeline.py`, `segmentation.py`, `features.py`, `matcher.py`, `calibration.py`, `database.py` werden NICHT verändert. Keine Ausnahme.
- **Keine neuen Pflicht-Dependencies.** Nur stdlib plus das bereits Installierte.
- **Keine Schwellen-/Gewichtsänderungen.** Weder in `config.yaml` noch in `config.local.yaml`.
- **Echte Daten read-only.** `doco_detect.sqlite3`, `data/reference/`, `calibration/` werden nur gelesen. DB-Kopien ausschliesslich über `sqlite3`-Backup-API aus einer `mode=ro`-Verbindung.
- **Destruktives = Verschieben** nach `backups/<datum>-<zweck>/`, nie löschen.
- **Tests laufen ohne Hardware.** `tests/conftest.py` sperrt `cv2.VideoCapture` (autouse). Kein neuer Code darf daran vorbei ein Gerät öffnen.
- **Bestehende Tests bleiben unberührt.** Keine Änderung an vorhandenen Testdateien ausser der Marker-Registrierung in `tests/conftest.py` (Task 10).
- **Branch:** `feature/corpus-harness`. `git push` erst nach Rückfrage.
- Alle Masse in mm. Kommentare und Meldungen auf Deutsch, wie im Bestand.

---

### Task 1: Config-Key und Manifest-Grundlage

**Files:**
- Modify: `config/config.yaml` (Sektion `paths`, ans Ende)
- Create: `docodetect/corpus/__init__.py`
- Create: `docodetect/corpus/manifest.py`
- Test: `tests/test_corpus_manifest.py`

**Interfaces:**
- Consumes: `docodetect.config.resolve`, `docodetect.config.project_root`
- Produces:
  - `sha256_file(path: Path) -> str`
  - `corpus_root(cfg: dict) -> Path`
  - `MANIFEST_PATH` (Konstante, `Path`)
  - `ImageEntry` dataclass: `sha`, `session`, `article`, `image_rel`, `report_rel`, `label`, `verdict`, `tier`
  - `Manifest` dataclass: `version: int`, `generated: str`, `sessions: dict`, `images: list[ImageEntry]`
  - `Manifest.load() -> Manifest`, `Manifest.save(self) -> Path`, `Manifest.by_sha(self) -> dict`

- [ ] **Step 1: Config-Key ergänzen**

An das Ende der `paths`-Sektion in `config/config.yaml`:

```yaml
  # Korpus des Regressions-Harness (docodetect/corpus). Bewusst AUSSERHALB
  # des Repos: der Korpus enthaelt hunderte 4K-PNGs. Versioniert wird nur
  # corpus/manifest.json im Repo, dessen Pfade relativ zu diesem Verzeichnis
  # sind. Auf dem Windows-Rechner per config.local.yaml umbiegen.
  corpus_dir: ../Doco_Detect_corpus
```

- [ ] **Step 2: Failing test schreiben**

`tests/test_corpus_manifest.py`:

```python
"""Manifest des Regressions-Korpus: Hashing, Pfad-Aufloesung, Round-Trip."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.corpus.manifest import (ImageEntry, Manifest, corpus_root,
                                        sha256_file)


def test_sha256_file_is_stable_and_content_based(tmp_path):
    a, b = tmp_path / "a.bin", tmp_path / "b.bin"
    a.write_bytes(b"doco")
    b.write_bytes(b"doco")
    assert sha256_file(a) == sha256_file(b)
    assert len(sha256_file(a)) == 64
    b.write_bytes(b"detect")
    assert sha256_file(a) != sha256_file(b)


def test_corpus_root_resolves_relative_to_project(tmp_path):
    cfg = {"paths": {"corpus_dir": str(tmp_path / "korpus")}}
    assert corpus_root(cfg) == tmp_path / "korpus"


def test_corpus_root_defaults_when_key_missing():
    root = corpus_root({"paths": {}})
    assert root.name == "Doco_Detect_corpus"


def test_manifest_roundtrip_preserves_entries(tmp_path, monkeypatch):
    path = tmp_path / "manifest.json"
    monkeypatch.setattr("docodetect.corpus.manifest.MANIFEST_PATH", path)
    m = Manifest(
        version=1, generated="2026-07-20T12:00:00",
        sessions={"phase-b": {"tier": 2, "db_verified": 1.0, "n_images": 1}},
        images=[ImageEntry(sha="ab" * 32, session="phase-b", article="LOEFFEL-1",
                           image_rel="phase-b/images/LOEFFEL-1/abababab.png",
                           report_rel="phase-b/reports/abababab.json",
                           label="LOEFFEL-1", verdict="correct", tier=2)])
    m.save()
    back = Manifest.load()
    assert back.version == 1
    assert back.sessions["phase-b"]["tier"] == 2
    assert len(back.images) == 1
    assert back.images[0].article == "LOEFFEL-1"
    assert back.by_sha()["ab" * 32].label == "LOEFFEL-1"


def test_manifest_load_returns_empty_when_absent(tmp_path, monkeypatch):
    monkeypatch.setattr("docodetect.corpus.manifest.MANIFEST_PATH",
                        tmp_path / "fehlt.json")
    m = Manifest.load()
    assert m.images == []
    assert m.sessions == {}


def test_manifest_is_written_sorted_for_stable_diffs(tmp_path, monkeypatch):
    path = tmp_path / "manifest.json"
    monkeypatch.setattr("docodetect.corpus.manifest.MANIFEST_PATH", path)
    mk = lambda sha: ImageEntry(sha=sha, session="s", article="A",
                                image_rel=f"s/images/A/{sha[:8]}.png",
                                report_rel=f"s/reports/{sha[:8]}.json",
                                label="A", verdict="correct", tier=1)
    Manifest(version=1, generated="x", sessions={},
             images=[mk("ff" * 32), mk("00" * 32)]).save()
    shas = [e["sha"] for e in json.loads(path.read_text())["images"]]
    assert shas == sorted(shas)
```

- [ ] **Step 3: Test laufen lassen, Fehlschlag bestätigen**

Run: `.venv/bin/python -m pytest tests/test_corpus_manifest.py -q`
Expected: FAIL mit `ModuleNotFoundError: No module named 'docodetect.corpus'`

- [ ] **Step 4: Paket und Manifest implementieren**

`docodetect/corpus/__init__.py`:

```python
"""Regressions-Korpus: Replay echter Aufnahmen gegen die Original-Reports.

Der Korpus liegt AUSSERHALB des Repos (paths.corpus_dir); versioniert ist
nur corpus/manifest.json. Siehe docs/superpowers/specs/
2026-07-20-corpus-harness-design.md.
"""
```

`docodetect/corpus/manifest.py`:

```python
"""Manifest des Regressions-Korpus.

Einzige versionierte Datei des Korpus. Alle Pfade darin sind relativ zu
paths.corpus_dir, damit der Korpus 1:1 auf den Windows-Rechner umziehen
kann: Ordner kopieren, corpus_dir in config.local.yaml setzen, fertig.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..config import project_root

MANIFEST_PATH = project_root() / "corpus" / "manifest.json"

DEFAULT_CORPUS_DIR = "../Doco_Detect_corpus"


def sha256_file(path: str | Path, chunk: int = 1 << 20) -> str:
    """Inhalts-Hash einer Datei. Blockweise, damit 4K-PNGs nicht komplett
    in den Speicher müssen."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def corpus_root(cfg: dict) -> Path:
    """Wurzel des Korpus, relativ zum Projekt aufgelöst."""
    raw = cfg.get("paths", {}).get("corpus_dir") or DEFAULT_CORPUS_DIR
    p = Path(raw)
    return p if p.is_absolute() else (project_root() / p).resolve()


@dataclass
class ImageEntry:
    sha: str
    session: str
    article: str          # wahrer Artikel; "_unbewertet" ohne Label
    image_rel: str
    report_rel: str
    label: str | None
    verdict: str | None
    tier: int             # hoechste Stufe, die dieses Bild fahren kann (1 oder 2)


@dataclass
class Manifest:
    version: int = 1
    generated: str = ""
    sessions: dict = field(default_factory=dict)
    images: list = field(default_factory=list)

    def by_sha(self) -> dict:
        return {e.sha: e for e in self.images}

    def save(self) -> Path:
        MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": self.version,
            "generated": self.generated,
            "sessions": dict(sorted(self.sessions.items())),
            # sortiert -> stabile git-Diffs, auch wenn der Build die
            # Reihenfolge der Quellen aendert
            "images": [asdict(e) for e in sorted(self.images, key=lambda e: e.sha)],
        }
        MANIFEST_PATH.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
        return MANIFEST_PATH

    @staticmethod
    def load() -> "Manifest":
        if not MANIFEST_PATH.exists():
            return Manifest()
        d = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        return Manifest(version=d.get("version", 1), generated=d.get("generated", ""),
                        sessions=d.get("sessions", {}),
                        images=[ImageEntry(**e) for e in d.get("images", [])])
```

- [ ] **Step 5: Tests laufen lassen, grün bestätigen**

Run: `.venv/bin/python -m pytest tests/test_corpus_manifest.py -q`
Expected: PASS, 6 passed

- [ ] **Step 6: Commit**

```bash
git add config/config.yaml docodetect/corpus/ tests/test_corpus_manifest.py
git commit -m "feat(corpus): Manifest-Grundlage und paths.corpus_dir"
```

---

### Task 2: Session-Fingerprints und Bündel-Verifikation

**Files:**
- Create: `docodetect/corpus/bundle.py`
- Test: `tests/test_corpus_bundle.py`

**Interfaces:**
- Consumes: `docodetect.matcher.MatchReport`, `docodetect.corpus.manifest.sha256_file`
- Produces:
  - `recover_mm_per_px(report: MatchReport) -> float | None`
  - `recover_sigma_floors(report: MatchReport) -> dict`
  - `db_match_ratio(reports: list[MatchReport], db_path: Path) -> float`
  - `copy_db_readonly(src: Path, dst: Path) -> None`
  - `SessionBundle` dataclass: `name`, `bundle_dir`, `has_db`, `db_verified`, `mm_per_px`, `sigma_floors`, `tier`
  - `write_session_json(bundle_dir: Path, bundle: SessionBundle) -> Path`
  - `bundle_cfg(cfg: dict, bundle_dir: Path) -> dict`

Der DB-Abgleich ist der Kern: er entscheidet, ob eine Session Tier 2 fahren darf. Die Prüfgrösse ist `candidates[].features[].reference` für `diameter_mm` plus `n_shots` gegen `reference_stats.scalar_mean["diameter_mm"]` — ein exakter Fliesskomma-Vergleich, kein Indiz.

- [ ] **Step 1: Failing test schreiben**

`tests/test_corpus_bundle.py`:

```python
"""Session-Fingerprints: mm_per_px, sigma_floors, exakter DB-Abgleich."""

import json
import math
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.corpus.bundle import (bundle_cfg, copy_db_readonly,
                                      db_match_ratio, recover_mm_per_px,
                                      recover_sigma_floors)
from docodetect.matcher import (CandidateReport, FeatureScore, MatchReport)


def _kreis_kontur(radius_px: float, n: int = 512) -> list:
    return [[round(radius_px * math.cos(2 * math.pi * i / n) + 2000),
             round(radius_px * math.sin(2 * math.pi * i / n) + 1000)]
            for i in range(n)]


def _report(*, d_mm=190.5, radius_px=1209.4, refs=(("LOEFFEL-1", 194.43, 9),)):
    cands = []
    for art, ref, n in refs:
        cands.append(CandidateReport(
            article_number=art, name=art, nominal_size_mm=197.47, height_mm=0.0,
            corrected_diameter_mm=d_mm, geometry_error_mm=0.0,
            has_references=True, n_shots=n,
            features=[FeatureScore(feature="diameter_mm", measured=d_mm,
                                   reference=ref, distance=0.1,
                                   sigma_enroll=1.9, sigma_eff=2.42,
                                   z=0.04, log_contrib=-0.001, w_eff=0.52,
                                   weighted=-0.0005),
                      FeatureScore(feature="circularity", measured=0.22,
                                   reference=0.21, distance=0.01,
                                   sigma_enroll=0.008, sigma_eff=0.0215,
                                   z=0.7, log_contrib=-0.24, w_eff=0.08,
                                   weighted=-0.02)]))
    return MatchReport(decision="ambiguous", message="", candidates=cands,
                       measured={"circle_diameter_mm": d_mm},
                       contour=_kreis_kontur(radius_px))


def test_recover_mm_per_px_from_contour_and_measurement():
    r = _report(d_mm=190.5, radius_px=1209.4)
    got = recover_mm_per_px(r)
    assert got == pytest.approx(190.5 / (2 * 1209.4), rel=1e-3)


def test_recover_mm_per_px_none_without_contour():
    r = _report()
    r.contour = None
    assert recover_mm_per_px(r) is None


def test_recover_sigma_floors_inverts_the_quadrature_sum():
    # sigma_eff^2 = sigma_enroll^2 + sigma_floor^2
    r = _report()
    floors = recover_sigma_floors(r)
    assert floors["diameter_mm"] == pytest.approx(
        math.sqrt(2.42 ** 2 - 1.9 ** 2), abs=0.01)
    assert floors["circularity"] == pytest.approx(
        math.sqrt(0.0215 ** 2 - 0.008 ** 2), abs=0.001)


def _db(path: Path, rows):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE reference_stats (article_number TEXT PRIMARY KEY, "
                "stats_json TEXT NOT NULL, updated_unix REAL)")
    for art, mean, n in rows:
        con.execute("INSERT INTO reference_stats VALUES (?,?,?)",
                    (art, json.dumps({"n_shots": n,
                                      "scalar_mean": {"diameter_mm": mean}}), 0.0))
    con.commit()
    con.close()


def test_db_match_ratio_is_one_for_the_matching_snapshot(tmp_path):
    p = tmp_path / "match.sqlite3"
    _db(p, [("LOEFFEL-1", 194.43, 9)])
    assert db_match_ratio([_report()], p) == 1.0


def test_db_match_ratio_is_zero_for_a_foreign_snapshot(tmp_path):
    p = tmp_path / "fremd.sqlite3"
    _db(p, [("LOEFFEL-1", 188.11, 9)])
    assert db_match_ratio([_report()], p) == 0.0


def test_db_match_ratio_notices_a_differing_shot_count(tmp_path):
    p = tmp_path / "andere_shots.sqlite3"
    _db(p, [("LOEFFEL-1", 194.43, 8)])
    assert db_match_ratio([_report()], p) == 0.0


def test_copy_db_readonly_produces_a_readable_equal_copy(tmp_path):
    src, dst = tmp_path / "src.sqlite3", tmp_path / "dst.sqlite3"
    _db(src, [("LOEFFEL-1", 194.43, 9)])
    copy_db_readonly(src, dst)
    assert db_match_ratio([_report()], dst) == 1.0


def test_copy_db_readonly_never_writes_to_the_source(tmp_path):
    src, dst = tmp_path / "src.sqlite3", tmp_path / "dst.sqlite3"
    _db(src, [("LOEFFEL-1", 194.43, 9)])
    vorher = src.read_bytes()
    copy_db_readonly(src, dst)
    assert src.read_bytes() == vorher


def test_bundle_cfg_points_at_the_bundle_and_disables_captures(tmp_path):
    cfg = {"paths": {"db_file": "doco_detect.sqlite3", "captures_dir": "data/captures"},
           "calibration": {"file": "calibration/calibration.json",
                           "background_file": "calibration/background.png"}}
    out = bundle_cfg(cfg, tmp_path)
    assert out["paths"]["captures_dir"] is None       # Replay schreibt nichts
    assert out["paths"]["db_file"] == str(tmp_path / "db.sqlite3")
    assert out["calibration"]["file"] == str(tmp_path / "calibration.json")
    assert out["calibration"]["background_file"] == str(tmp_path / "background.png")
    assert cfg["paths"]["captures_dir"] == "data/captures"   # Original unberuehrt
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag bestätigen**

Run: `.venv/bin/python -m pytest tests/test_corpus_bundle.py -q`
Expected: FAIL mit `ModuleNotFoundError: No module named 'docodetect.corpus.bundle'`

- [ ] **Step 3: bundle.py implementieren**

```python
"""Session-Buendel: Fingerprints, Verifikation, Replay-Config.

Reports tragen kein Session-Feld (das Einbetten wuerde pipeline.py
beruehren und ist aufgeschoben). Die Zuordnung laeuft deshalb ueber drei
aus den Reports REKONSTRUIERBARE Fingerprints — siehe Spec 1.1.
"""

from __future__ import annotations

import copy
import json
import math
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path

import cv2
import numpy as np

# Merkmalsname im Report -> Name des sigma_floor in der Config
FLOOR_NAMES = {
    "diameter_mm": "diameter_mm",
    "circularity": "circularity",
    "solidity": "solidity",
    "delta_e_center": "delta_e",
    "delta_e_rim": "delta_e",
    "hist_center": "hist_bhattacharyya",
    "hist_rim": "hist_bhattacharyya",
    "hu_log": "hu_log",
}


def recover_mm_per_px(report) -> float | None:
    """Kalibrier-Fingerprint: der gespeicherte Kreis-Ø in mm geteilt durch
    den aus der Kontur gerechneten Kreis-Ø in px. Die Kontur ist auf ~400
    Punkte ausgeduennt, das Ergebnis daher auf ~0,1 % genau — genug, um
    Kalibrier-Epochen zu TRENNEN, nicht um eine Kalibrierung zu ersetzen."""
    d_mm = (report.measured or {}).get("circle_diameter_mm")
    if not d_mm or not report.contour:
        return None
    pts = np.asarray(report.contour, dtype=np.float32).reshape(-1, 1, 2)
    if len(pts) < 3:
        return None
    _, radius_px = cv2.minEnclosingCircle(pts)
    if radius_px <= 0:
        return None
    return float(d_mm) / (2.0 * float(radius_px))


def recover_sigma_floors(report) -> dict:
    """Config-Fingerprint: sigma_eff^2 = sigma_enroll^2 + sigma_floor^2,
    also floor = sqrt(eff^2 - enroll^2). Liefert je Floor-Name den Median
    ueber alle Kandidaten/Merkmale."""
    samples: dict = {}
    for cand in report.candidates:
        for f in cand.features:
            name = FLOOR_NAMES.get(f.feature)
            if name is None:
                continue
            var = f.sigma_eff ** 2 - f.sigma_enroll ** 2
            if var > 0:
                samples.setdefault(name, []).append(math.sqrt(var))
    out = {}
    for name, vals in samples.items():
        vals.sort()
        out[name] = round(vals[len(vals) // 2], 4)
    return out


def db_match_ratio(reports: list, db_path: str | Path) -> float:
    """Anteil der Kandidaten-Referenzwerte, die EXAKT zu diesem DB-Snapshot
    passen. Geprueft wird das Enrollment-Mittel des Ø plus n_shots — beides
    steht im Report und in reference_stats. 1.0 = dieser Snapshot ist der
    Zustand, gegen den damals gematcht wurde. Alles darunter heisst:
    falsche DB, Session faellt auf Tier 1 zurueck."""
    db_path = Path(db_path)
    if not db_path.exists():
        return 0.0
    stats: dict = {}
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        for art, sj in con.execute(
                "SELECT article_number, stats_json FROM reference_stats"):
            s = json.loads(sj)
            stats[art] = (s.get("n_shots"),
                          s.get("scalar_mean", {}).get("diameter_mm"))
    except sqlite3.Error:
        return 0.0
    finally:
        con.close()

    hit = total = 0
    for r in reports:
        for cand in r.candidates:
            ref = next((f.reference for f in cand.features
                        if f.feature == "diameter_mm"), None)
            if ref is None:
                continue
            total += 1
            got = stats.get(cand.article_number)
            if got and got[0] == cand.n_shots and got[1] is not None \
                    and abs(got[1] - ref) < 1e-9:
                hit += 1
    return hit / total if total else 0.0


def copy_db_readonly(src: str | Path, dst: str | Path) -> None:
    """DB-Snapshot ziehen, ohne die Quelle anzufassen: Backup-API auf einer
    mode=ro-Verbindung. Die echte doco_detect.sqlite3 wird dabei nur
    gelesen — kein Schreibzugriff, kein Journal, kein Schema-Eingriff."""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    quelle = sqlite3.connect(f"file:{Path(src)}?mode=ro", uri=True)
    ziel = sqlite3.connect(dst)
    try:
        quelle.backup(ziel)
    finally:
        ziel.close()
        quelle.close()


@dataclass
class SessionBundle:
    name: str
    bundle_dir: str
    has_db: bool
    db_verified: float          # Anteil exakt passender Referenzwerte (0..1)
    mm_per_px: float | None
    sigma_floors: dict = field(default_factory=dict)
    tier: int = 1
    provenance: str = ""

    @property
    def tier2_ready(self) -> bool:
        """Tier 2 nur bei vollstaendig verifiziertem Snapshot. Ein knapp
        verfehlter Abgleich ist KEIN 'fast richtig', sondern eine andere
        Datenbank."""
        return self.has_db and self.db_verified >= 1.0


def write_session_json(bundle_dir: str | Path, bundle: SessionBundle) -> Path:
    p = Path(bundle_dir) / "session.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(asdict(bundle), indent=2, ensure_ascii=False) + "\n",
                 encoding="utf-8")
    return p


def bundle_cfg(cfg: dict, bundle_dir: str | Path) -> dict:
    """Replay-Config: zeigt auf das Buendel statt auf den Live-Zustand und
    schaltet das Schreiben von Captures ab (pipeline._save_capture_and_report
    kehrt bei captures_dir=None sofort zurueck). Das Original-cfg bleibt
    unveraendert."""
    b = Path(bundle_dir)
    out = copy.deepcopy(cfg)
    out.setdefault("paths", {})
    out.setdefault("calibration", {})
    out["paths"]["db_file"] = str(b / "db.sqlite3")
    out["paths"]["captures_dir"] = None
    out["calibration"]["file"] = str(b / "calibration.json")
    out["calibration"]["background_file"] = str(b / "background.png")
    return out
```

- [ ] **Step 4: Tests laufen lassen, grün bestätigen**

Run: `.venv/bin/python -m pytest tests/test_corpus_bundle.py -q`
Expected: PASS, 10 passed

- [ ] **Step 5: Commit**

```bash
git add docodetect/corpus/bundle.py tests/test_corpus_bundle.py
git commit -m "feat(corpus): Session-Fingerprints und Buendel-Verifikation"
```

---

### Task 3: Drei-Band-Vergleich

**Files:**
- Create: `docodetect/corpus/compare.py`
- Test: `tests/test_corpus_compare.py`

**Interfaces:**
- Produces:
  - `PASS`, `DRIFT`, `FAIL` (str-Konstanten)
  - `QUANTUM: dict[str, float]`, `SOFT: dict[str, float]`
  - `band(field: str, golden: float, actual: float) -> str`
  - `FieldDiff` dataclass: `field`, `golden`, `actual`, `delta`, `band`
  - `compare_tier1(golden: MatchReport, measured: Features, seg_area_px: float, centroid: list | None) -> list[FieldDiff]`
  - `compare_tier2(golden: MatchReport, actual: MatchReport) -> list[FieldDiff]`
  - `worst_band(diffs: list[FieldDiff]) -> str`

Die Quanten folgen exakt den `round()`-Aufrufen in `docodetect/features.py:185-195`. Ein eigener Test verankert das, damit die Tabelle nicht still von `features.py` abdriftet.

- [ ] **Step 1: Failing test schreiben**

`tests/test_corpus_compare.py`:

```python
"""Drei-Band-Logik: PASS / DRIFT / FAIL je Merkmal."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.corpus.compare import (DRIFT, FAIL, PASS, QUANTUM, SOFT, band,
                                       compare_tier2, worst_band)
from docodetect.matcher import CandidateReport, MatchReport


def test_identical_values_pass():
    assert band("circle_diameter_mm", 190.5, 190.5) == PASS


def test_within_rounding_quantum_passes():
    assert band("circle_diameter_mm", 190.5, 190.504) == PASS


def test_beyond_quantum_but_within_soft_step_is_drift():
    assert band("circle_diameter_mm", 190.5, 190.6) == DRIFT


def test_beyond_soft_step_fails():
    assert band("circle_diameter_mm", 190.5, 190.8) == FAIL


def test_shape_features_use_the_tight_quantum():
    assert band("solidity", 0.6043, 0.60433) == PASS
    assert band("solidity", 0.6043, 0.6100) == DRIFT
    assert band("solidity", 0.6043, 0.6200) == FAIL


def test_quantum_table_matches_features_rounding():
    """Verankerung: die Quanten sind die halben Rundungsschritte aus
    docodetect/features.py:185-195. Aendert sich dort die Rundung, muss
    diese Tabelle mitgezogen werden — dieser Test macht das sichtbar."""
    assert QUANTUM["circle_diameter_mm"] == 0.005    # round(x, 2)
    assert QUANTUM["equiv_diameter_mm"] == 0.005     # round(x, 2)
    assert QUANTUM["perimeter_mm"] == 0.005          # round(x, 2)
    assert QUANTUM["area_mm2"] == 0.05               # round(x, 1)
    assert QUANTUM["circularity"] == 5e-05           # round(x, 4)
    assert QUANTUM["aspect_ratio"] == 5e-05          # round(x, 4)
    assert QUANTUM["solidity"] == 5e-05              # round(x, 4)
    assert QUANTUM["llr_margin"] == 5e-05
    assert QUANTUM["max_z_winner"] == 5e-05


def test_soft_step_for_tier2_floats_is_five_hundredths():
    assert SOFT["llr_margin"] == 0.05
    assert SOFT["max_z_winner"] == 0.05


def test_worst_band_reports_the_most_severe():
    from docodetect.corpus.compare import FieldDiff
    diffs = [FieldDiff("a", 1.0, 1.0, 0.0, PASS),
             FieldDiff("b", 1.0, 1.2, 0.2, DRIFT)]
    assert worst_band(diffs) == DRIFT
    diffs.append(FieldDiff("c", 1.0, 9.0, 8.0, FAIL))
    assert worst_band(diffs) == FAIL
    assert worst_band([]) == PASS


def _rep(decision, arts, llr=1.5, maxz=3.0, gate=True):
    return MatchReport(
        decision=decision, message="", gate_passed=gate,
        llr_margin=llr, max_z_winner=maxz,
        candidates=[CandidateReport(article_number=a, name=a, nominal_size_mm=1.0,
                                    height_mm=0.0, corrected_diameter_mm=1.0,
                                    geometry_error_mm=0.0, has_references=True,
                                    n_shots=9) for a in arts])


def test_tier2_identical_reports_all_pass():
    a = _rep("ambiguous", ["L1", "L5"])
    b = _rep("ambiguous", ["L1", "L5"])
    assert worst_band(compare_tier2(a, b)) == PASS


def test_tier2_decision_change_is_an_exact_fail():
    a = _rep("accept", ["L1"])
    b = _rep("ambiguous", ["L1"])
    diffs = compare_tier2(a, b)
    assert worst_band(diffs) == FAIL
    assert any(d.field == "decision" and d.band == FAIL for d in diffs)


def test_tier2_topk_reordering_is_an_exact_fail():
    a = _rep("ambiguous", ["L1", "L5"])
    b = _rep("ambiguous", ["L5", "L1"])
    assert any(d.field == "top_k" and d.band == FAIL for d in compare_tier2(a, b))


def test_tier2_gate_flip_is_an_exact_fail():
    a = _rep("accept", ["L1"], gate=True)
    b = _rep("accept", ["L1"], gate=False)
    assert any(d.field == "gate_passed" and d.band == FAIL
               for d in compare_tier2(a, b))


def test_tier2_small_margin_move_is_drift_not_failure():
    """Ohne Drei-Band-Logik waere Tier 2 implizit bit-exakt und wuerde beim
    ersten Bibliotheks-Update flaechendeckend kippen."""
    a = _rep("ambiguous", ["L1", "L5"], llr=1.5)
    b = _rep("ambiguous", ["L1", "L5"], llr=1.52)
    diffs = compare_tier2(a, b)
    assert worst_band(diffs) == DRIFT


def test_tier2_large_margin_move_fails():
    a = _rep("ambiguous", ["L1", "L5"], llr=1.5)
    b = _rep("ambiguous", ["L1", "L5"], llr=2.9)
    assert worst_band(compare_tier2(a, b)) == FAIL


def test_tier2_tolerates_missing_margin_on_single_candidate():
    a = _rep("accept", ["L1"], llr=None)
    b = _rep("accept", ["L1"], llr=None)
    assert worst_band(compare_tier2(a, b)) == PASS
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag bestätigen**

Run: `.venv/bin/python -m pytest tests/test_corpus_compare.py -q`
Expected: FAIL mit `ModuleNotFoundError: No module named 'docodetect.corpus.compare'`

- [ ] **Step 3: compare.py implementieren**

```python
"""Drei-Band-Vergleich Golden gegen Replay.

PASS  : Delta <= Rundungsquantum      -> nicht unterscheidbar
DRIFT : Quantum < Delta <= weiche Stufe -> messbar, aber klein
FAIL  : Delta > weiche Stufe            -> Regression

Auf gepinnter Umgebung ist JEDE Abweichung code-verursacht, deshalb bricht
`corpus-run --check` per Default auch bei DRIFT (siehe runner.py). Die
Trennung existiert fuer die zwei legitimen Ereignisse — bewusstes
Bibliotheks-Update und Plattformwechsel Mac->Windows — und damit die
Triage 'uniforme Drift' von 'Ausreisser' unterscheiden kann.
"""

from __future__ import annotations

from dataclasses import dataclass

PASS = "pass"
DRIFT = "drift"
FAIL = "fail"

_SCHWERE = {PASS: 0, DRIFT: 1, FAIL: 2}

# Halbe Rundungsschritte aus docodetect/features.py:185-195. Wird dort die
# Rundung geaendert, schlaegt tests/test_corpus_compare.py an.
QUANTUM = {
    "equiv_diameter_mm": 0.005,     # round(x, 2)
    "circle_diameter_mm": 0.005,    # round(x, 2)
    "perimeter_mm": 0.005,          # round(x, 2)
    "mean_saturation": 0.005,       # round(x, 2)
    "area_mm2": 0.05,               # round(x, 1)
    "circularity": 5e-05,           # round(x, 4)
    "aspect_ratio": 5e-05,          # round(x, 4)
    "solidity": 5e-05,              # round(x, 4)
    "hu_moments": 5e-05,            # round(x, 4), Vektor
    "mean_hsv": 0.005,              # round(x, 2), Vektor
    "hue_hist": 5e-07,              # round(x, 6), Vektor
    "hs_hist_center": 5e-07,
    "hs_hist_rim": 5e-07,
    "lab_center": 5e-04,            # round(x, 3), Vektor
    "lab_rim": 5e-04,
    # Segmentierungs-Signale: Pixelgroessen, ganzzahlig gefuehrt
    "seg_area_px": 0.5,
    "centroid_x": 0.05,
    "centroid_y": 0.05,
    # Tier-2-Gleitkommagroessen
    "llr_margin": 5e-05,
    "max_z_winner": 5e-05,
}

# Weiche Stufe: ab hier ist es keine Drift mehr, sondern eine Regression.
SOFT = {
    "equiv_diameter_mm": 0.2,
    "circle_diameter_mm": 0.2,
    "perimeter_mm": 0.5,
    "mean_saturation": 0.5,
    "area_mm2": 20.0,
    "circularity": 0.01,
    "aspect_ratio": 0.01,
    "solidity": 0.01,
    "hu_moments": 0.01,
    "mean_hsv": 0.5,
    "hue_hist": 0.001,
    "hs_hist_center": 0.001,
    "hs_hist_rim": 0.001,
    "lab_center": 0.05,
    "lab_rim": 0.05,
    "seg_area_px": 200.0,
    "centroid_x": 2.0,
    "centroid_y": 2.0,
    "llr_margin": 0.05,
    "max_z_winner": 0.05,
}

_QUANTUM_DEFAULT = 5e-05
_SOFT_DEFAULT = 0.01


@dataclass
class FieldDiff:
    field: str
    golden: object
    actual: object
    delta: float
    band: str


def band(field: str, golden: float, actual: float) -> str:
    delta = abs(float(actual) - float(golden))
    if delta <= QUANTUM.get(field, _QUANTUM_DEFAULT):
        return PASS
    return DRIFT if delta <= SOFT.get(field, _SOFT_DEFAULT) else FAIL


def worst_band(diffs: list) -> str:
    return max((d.band for d in diffs), key=lambda b: _SCHWERE[b], default=PASS)


def _scalar_diff(field: str, golden, actual) -> FieldDiff | None:
    if golden is None or actual is None:
        # Beide fehlen = kein Befund; nur eines fehlt = harte Aenderung.
        if golden is None and actual is None:
            return None
        return FieldDiff(field, golden, actual, float("nan"), FAIL)
    return FieldDiff(field, golden, actual, float(actual) - float(golden),
                     band(field, golden, actual))


def _vector_diff(field: str, golden, actual) -> FieldDiff | None:
    if not golden and not actual:
        return None
    golden, actual = list(golden or []), list(actual or [])
    if len(golden) != len(actual):
        return FieldDiff(field, f"len={len(golden)}", f"len={len(actual)}",
                         float("nan"), FAIL)
    if not golden:
        return None
    idx = max(range(len(golden)), key=lambda i: abs(actual[i] - golden[i]))
    d = actual[idx] - golden[idx]
    return FieldDiff(field, golden[idx], actual[idx], d,
                     band(field, golden[idx], actual[idx]))


_TIER1_SKALARE = ("equiv_diameter_mm", "circle_diameter_mm", "area_mm2",
                  "perimeter_mm", "circularity", "aspect_ratio", "solidity",
                  "mean_saturation")
_TIER1_VEKTOREN = ("mean_hsv", "hue_hist", "hu_moments", "lab_center",
                   "lab_rim", "hs_hist_center", "hs_hist_rim")


def compare_tier1(golden, measured, seg_area_px: float | None = None,
                  centroid: list | None = None) -> list:
    """Golden-Report gegen eine frische Messung (Features + Segmentierung)."""
    gm = golden.measured or {}
    out = []
    for f in _TIER1_SKALARE:
        d = _scalar_diff(f, gm.get(f), getattr(measured, f, None))
        if d is not None:
            out.append(d)
    for f in _TIER1_VEKTOREN:
        d = _vector_diff(f, gm.get(f), getattr(measured, f, None))
        if d is not None:
            out.append(d)
    if seg_area_px is not None and golden.contour:
        import cv2
        import numpy as np
        pts = np.asarray(golden.contour, dtype=np.int32).reshape(-1, 1, 2)
        d = _scalar_diff("seg_area_px", float(cv2.contourArea(pts)),
                         float(seg_area_px))
        if d is not None:
            out.append(d)
    if centroid and golden.centroid_px:
        for name, i in (("centroid_x", 0), ("centroid_y", 1)):
            d = _scalar_diff(name, golden.centroid_px[i], centroid[i])
            if d is not None:
                out.append(d)
    return out


def compare_tier2(golden, actual) -> list:
    """Golden-Report gegen einen frischen Replay-Report.

    decision, Top-k-Reihenfolge und gate_passed werden EXAKT verglichen —
    das sind die Groessen, an denen eine Fehlbuchung haengt. llr_margin und
    max_z_winner laufen ueber die Drei-Band-Logik.
    """
    out = []
    if golden.decision != actual.decision:
        out.append(FieldDiff("decision", golden.decision, actual.decision,
                             float("nan"), FAIL))
    g_top = [c.article_number for c in golden.candidates]
    a_top = [c.article_number for c in actual.candidates]
    if g_top != a_top:
        out.append(FieldDiff("top_k", ",".join(g_top) or "-",
                             ",".join(a_top) or "-", float("nan"), FAIL))
    if bool(golden.gate_passed) != bool(actual.gate_passed):
        out.append(FieldDiff("gate_passed", golden.gate_passed,
                             actual.gate_passed, float("nan"), FAIL))
    for f in ("llr_margin", "max_z_winner"):
        d = _scalar_diff(f, getattr(golden, f), getattr(actual, f))
        if d is not None:
            out.append(d)
    return out
```

- [ ] **Step 4: Tests laufen lassen, grün bestätigen**

Run: `.venv/bin/python -m pytest tests/test_corpus_compare.py -q`
Expected: PASS, 15 passed

- [ ] **Step 5: Commit**

```bash
git add docodetect/corpus/compare.py tests/test_corpus_compare.py
git commit -m "feat(corpus): Drei-Band-Vergleich fuer Tier 1 und Tier 2"
```

---

### Task 4: corpus-build

**Files:**
- Create: `docodetect/corpus/build.py`
- Modify: `docodetect/cli.py` (Befehl registrieren)
- Test: `tests/test_corpus_build.py`

**Interfaces:**
- Consumes: alles aus Task 1–2, `docodetect.reporting.load_reports`
- Produces:
  - `SOURCES: list[tuple[str, str, str]]` — (Session-Name, Report-Ordner, Bild-Suchordner)
  - `build_corpus(cfg: dict, *, dry_run: bool = False) -> dict` — Statistik-Dict
  - `cmd_corpus_build(args, cfg)` in `cli.py`

Der Build ist idempotent: er hasht jedes Bild, überspringt bereits vorhandene und meldet nur, was neu dazukam. Aufgenommen werden **ausschliesslich** Reports mit `verdict` — plus die unbewerteten derselben Session unter `_unbewertet` für Tier 1.

- [ ] **Step 1: Failing test schreiben**

`tests/test_corpus_build.py`:

```python
"""corpus-build: Idempotenz, Dedup per Hash, Tier-Herabstufung."""

import json
import shutil
import sqlite3
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.corpus import build as corpus_build
from docodetect.corpus.manifest import Manifest


@pytest.fixture
def welt(tmp_path, monkeypatch):
    """Miniaturprojekt: eine Session, zwei Bilder, ein passender DB-Snapshot."""
    quelle = tmp_path / "quelle"
    (quelle / "reports").mkdir(parents=True)
    korpus = tmp_path / "korpus"
    monkeypatch.setattr("docodetect.corpus.manifest.MANIFEST_PATH",
                        tmp_path / "manifest.json")

    kal = tmp_path / "calibration"
    kal.mkdir()
    cv2.imwrite(str(kal / "background.png"), np.zeros((40, 40, 3), np.uint8))
    (kal / "calibration.json").write_text(json.dumps(
        {"mm_per_px": 0.0787, "camera_height_mm": 300.0, "image_width": 40,
         "image_height": 40, "marker_size_mm": 72.5, "created_unix": 1.0}))

    db = tmp_path / "db.sqlite3"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE reference_stats (article_number TEXT PRIMARY KEY,"
                " stats_json TEXT NOT NULL, updated_unix REAL)")
    con.execute("INSERT INTO reference_stats VALUES (?,?,?)",
                ("LOEFFEL-1", json.dumps({"n_shots": 9,
                 "scalar_mean": {"diameter_mm": 194.43}}), 0.0))
    con.commit(); con.close()

    for i, (verdict, label) in enumerate([("correct", "LOEFFEL-1"), (None, None)]):
        img = quelle / f"bild_{i}.png"
        cv2.imwrite(str(img), np.full((40, 40, 3), 10 * (i + 1), np.uint8))
        rep = {
            "decision": "accept", "message": "", "candidates": [{
                "article_number": "LOEFFEL-1", "name": "L1",
                "nominal_size_mm": 197.47, "height_mm": 0.0,
                "corrected_diameter_mm": 190.5, "geometry_error_mm": 0.0,
                "has_references": True, "n_shots": 9,
                "features": [{"feature": "diameter_mm", "measured": 190.5,
                              "reference": 194.43, "distance": 0.1,
                              "sigma_enroll": 1.9, "sigma_eff": 2.42, "z": 0.04,
                              "log_contrib": -0.001, "w_eff": 0.52,
                              "weighted": -0.0005}],
                "log_score": -0.1, "posterior": 0.9, "max_abs_z": 0.04,
                "margin_to_next": None}],
            "measured": {"circle_diameter_mm": 190.5},
            "contour": [[0, 0], [10, 0], [10, 10], [0, 10]],
            "timestamp": "2026-07-20T17:31:42", "image_path": str(img),
            "label": label, "verdict": verdict,
        }
        (quelle / "reports" / f"r_{i}.json").write_text(json.dumps(rep))

    cfg = {"paths": {"corpus_dir": str(korpus)}}
    monkeypatch.setattr(corpus_build, "SOURCES", [
        ("test-session", str(quelle / "reports"), str(quelle))])
    monkeypatch.setattr(corpus_build, "BUNDLE_QUELLEN", {
        "test-session": {"background": str(kal / "background.png"),
                         "calibration": str(kal / "calibration.json"),
                         "db": str(db)}})
    return cfg, korpus, quelle


def test_build_creates_the_expected_layout(welt):
    cfg, korpus, _ = welt
    corpus_build.build_corpus(cfg)
    assert (korpus / "test-session" / "bundle" / "session.json").exists()
    assert (korpus / "test-session" / "bundle" / "background.png").exists()
    assert (korpus / "test-session" / "bundle" / "db.sqlite3").exists()
    assert list((korpus / "test-session" / "images" / "LOEFFEL-1").glob("*.png"))


def test_build_sorts_unjudged_images_into_unbewertet(welt):
    cfg, korpus, _ = welt
    corpus_build.build_corpus(cfg)
    assert list((korpus / "test-session" / "images" / "_unbewertet").glob("*.png"))


def test_unjudged_images_are_tier1_only(welt):
    cfg, _, _ = welt
    corpus_build.build_corpus(cfg)
    m = Manifest.load()
    unbewertet = [e for e in m.images if e.article == "_unbewertet"]
    assert unbewertet and all(e.tier == 1 for e in unbewertet)


def test_verified_db_lifts_the_session_to_tier2(welt):
    cfg, _, _ = welt
    corpus_build.build_corpus(cfg)
    m = Manifest.load()
    assert m.sessions["test-session"]["db_verified"] == 1.0
    assert m.sessions["test-session"]["tier"] == 2


def test_mismatching_db_forces_tier1(welt, tmp_path, monkeypatch):
    cfg, _, _ = welt
    fremd = tmp_path / "fremd.sqlite3"
    con = sqlite3.connect(fremd)
    con.execute("CREATE TABLE reference_stats (article_number TEXT PRIMARY KEY,"
                " stats_json TEXT NOT NULL, updated_unix REAL)")
    con.execute("INSERT INTO reference_stats VALUES (?,?,?)",
                ("LOEFFEL-1", json.dumps({"n_shots": 9,
                 "scalar_mean": {"diameter_mm": 111.11}}), 0.0))
    con.commit(); con.close()
    corpus_build.BUNDLE_QUELLEN["test-session"]["db"] = str(fremd)
    corpus_build.build_corpus(cfg)
    m = Manifest.load()
    assert m.sessions["test-session"]["db_verified"] == 0.0
    assert m.sessions["test-session"]["tier"] == 1
    assert all(e.tier == 1 for e in m.images)


def test_build_is_idempotent(welt):
    cfg, _, _ = welt
    erst = corpus_build.build_corpus(cfg)
    zweit = corpus_build.build_corpus(cfg)
    assert erst["neu"] == 2
    assert zweit["neu"] == 0
    assert zweit["gesamt"] == erst["gesamt"]


def test_build_deduplicates_identical_images(welt):
    cfg, _, quelle = welt
    # dasselbe Bild ein zweites Mal, unter anderem Namen und mit eigenem Report
    doppelt = quelle / "bild_doppelt.png"
    shutil.copy(quelle / "bild_0.png", doppelt)
    rep = json.loads((quelle / "reports" / "r_0.json").read_text())
    rep["image_path"] = str(doppelt)
    (quelle / "reports" / "r_doppelt.json").write_text(json.dumps(rep))
    stat = corpus_build.build_corpus(cfg)
    assert stat["uebersprungen_dublette"] == 1


def test_build_never_writes_into_the_source_db(welt):
    cfg, _, _ = welt
    db = Path(corpus_build.BUNDLE_QUELLEN["test-session"]["db"])
    vorher = db.read_bytes()
    corpus_build.build_corpus(cfg)
    assert db.read_bytes() == vorher
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag bestätigen**

Run: `.venv/bin/python -m pytest tests/test_corpus_build.py -q`
Expected: FAIL mit `ModuleNotFoundError: No module named 'docodetect.corpus.build'`

- [ ] **Step 3: build.py implementieren**

```python
"""corpus-build: Korpus aus Captures, archivierten Reports und Backups bauen.

Idempotent und hash-dedupliziert. Aufgenommen werden die drei sauberen
Sessions der Bestandsaufnahme (Spec 1.2); erster_test_loeffel (gemischte
Aufloesung, 3 bewertete) und smoke-v2-uiqt (synthetisch, Bilder fehlen)
bleiben bewusst draussen.
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from ..config import project_root, resolve
from ..reporting import load_reports
from .bundle import (SessionBundle, copy_db_readonly, db_match_ratio,
                     recover_mm_per_px, recover_sigma_floors,
                     write_session_json)
from .manifest import ImageEntry, Manifest, corpus_root, sha256_file

_P = project_root()

# (Session, Report-Ordner, Bild-Suchordner). Reihenfolge = Aufnahme-Reihenfolge.
SOURCES = [
    ("test-2-loeffel", str(_P / "reports/analysis/test_2_loeffel/reports"),
     str(_P / "data/captures")),
    ("phase-a", str(_P / "reports/analysis/test_n_60_loeffel/reports"),
     str(_P / "data/captures")),
    ("phase-b", str(_P / "data/captures"), str(_P / "data/captures")),
]

# Buendel-Quellen je Session. Die DB-Zuordnung stammt aus dem exakten
# Referenz-Abgleich der Bestandsaufnahme (Spec 1.2) und wird beim Build
# erneut verifiziert — sie wird hier NICHT geglaubt, nur vorgeschlagen.
BUNDLE_QUELLEN = {
    "test-2-loeffel": {
        "background": str(_P / "calibration/background.png"),
        "calibration": str(_P / "calibration/calibration.json"),
        "db": str(_P / "backups/2026-07-20-neue-position/doco_detect.sqlite3"),
    },
    "phase-a": {
        "background": str(_P / "calibration/background.png"),
        "calibration": str(_P / "calibration/calibration.json"),
        "db": None,      # kein passender Snapshot -> Tier-1-only
    },
    "phase-b": {
        "background": str(_P / "calibration/background.png"),
        "calibration": str(_P / "calibration/calibration.json"),
        "db": str(_P / "doco_detect.sqlite3"),
    },
}

# Zusaetzliche Fundorte fuer Capture-PNGs, wenn image_path ins Leere zeigt.
BILD_POOLS = [str(_P / "data/captures"),
              str(_P / "backups/2026-07-20-vor-ab-test/captures")]


def _finde_bild(image_path: str | None, such_dir: str) -> Path | None:
    if not image_path:
        return None
    direkt = Path(image_path)
    if direkt.exists():
        return direkt
    name = direkt.name
    for pool in [such_dir, *BILD_POOLS]:
        p = Path(pool) / name
        if p.exists():
            return p
    return None


def build_corpus(cfg: dict, *, dry_run: bool = False) -> dict:
    root = corpus_root(cfg)
    manifest = Manifest.load()
    bekannt = manifest.by_sha()
    stat = {"neu": 0, "gesamt": 0, "uebersprungen_dublette": 0,
            "uebersprungen_ohne_bild": 0, "sessions": {}}
    eintraege = list(manifest.images)
    gesehen = set(bekannt)

    for session, report_dir, such_dir in SOURCES:
        if not Path(report_dir).is_dir():
            continue
        paare = load_reports(report_dir)
        reports = [r for _, r in paare]
        if not reports:
            continue

        quellen = BUNDLE_QUELLEN.get(session, {})
        bundle_dir = root / session / "bundle"
        db_ziel = bundle_dir / "db.sqlite3"
        verified, has_db = 0.0, False
        if quellen.get("db") and Path(quellen["db"]).exists():
            verified = db_match_ratio(reports, quellen["db"])
            has_db = verified >= 1.0

        mmpp = [v for v in (recover_mm_per_px(r) for r in reports) if v]
        mmpp_median = sorted(mmpp)[len(mmpp) // 2] if mmpp else None
        floors = {}
        for r in reports:
            floors.update(recover_sigma_floors(r))

        sb = SessionBundle(
            name=session, bundle_dir=str(bundle_dir.relative_to(root)),
            has_db=has_db, db_verified=round(verified, 4),
            mm_per_px=mmpp_median, sigma_floors=floors,
            tier=2 if has_db else 1,
            provenance=(f"DB-Abgleich {verified:.0%} gegen {quellen.get('db')}"
                        if quellen.get("db") else
                        "kein DB-Snapshot verfuegbar -> Tier-1-only"))

        if not dry_run:
            bundle_dir.mkdir(parents=True, exist_ok=True)
            for key, ziel in (("background", "background.png"),
                              ("calibration", "calibration.json")):
                q = quellen.get(key)
                if q and Path(q).exists():
                    shutil.copy2(q, bundle_dir / ziel)
            if has_db:
                copy_db_readonly(quellen["db"], db_ziel)
            elif db_ziel.exists():
                db_ziel.unlink()
            write_session_json(bundle_dir, sb)

        n_session = 0
        for _, rep in paare:
            bild = _finde_bild(rep.image_path, such_dir)
            if bild is None:
                stat["uebersprungen_ohne_bild"] += 1
                continue
            sha = sha256_file(bild)
            if sha in gesehen:
                stat["uebersprungen_dublette"] += 1
                continue
            gesehen.add(sha)

            artikel = rep.label if (rep.label and rep.verdict) else "_unbewertet"
            bild_rel = f"{session}/images/{artikel}/{sha[:8]}.png"
            rep_rel = f"{session}/reports/{sha[:8]}.json"
            if not dry_run:
                ziel_bild = root / bild_rel
                ziel_bild.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(bild, ziel_bild)
                ziel_rep = root / rep_rel
                ziel_rep.parent.mkdir(parents=True, exist_ok=True)
                ziel_rep.write_text(rep.to_json(), encoding="utf-8")

            eintraege.append(ImageEntry(
                sha=sha, session=session, article=artikel, image_rel=bild_rel,
                report_rel=rep_rel, label=rep.label, verdict=rep.verdict,
                # Tier 2 braucht Buendel-DB UND ein Urteil
                tier=2 if (sb.tier2_ready and artikel != "_unbewertet") else 1))
            stat["neu"] += 1
            n_session += 1

        stat["sessions"][session] = {
            "tier": sb.tier, "db_verified": sb.db_verified,
            "mm_per_px": sb.mm_per_px, "neu": n_session,
            "n_images": sum(1 for e in eintraege if e.session == session)}

    manifest.images = eintraege
    manifest.sessions = {s: v for s, v in stat["sessions"].items()}
    manifest.generated = datetime.now().isoformat(timespec="seconds")
    stat["gesamt"] = len(eintraege)
    if not dry_run:
        manifest.save()
    return stat
```

- [ ] **Step 4: CLI-Befehl registrieren**

In `docodetect/cli.py` die Funktion vor `def main(` einfügen:

```python
def cmd_corpus_build(args, cfg):
    """Regressions-Korpus aus Captures, archivierten Reports und Backups bauen."""
    from .corpus.build import build_corpus
    stat = build_corpus(cfg, dry_run=args.dry_run)
    print(f"[corpus-build] {stat['neu']} neu, {stat['gesamt']} gesamt "
          f"({stat['uebersprungen_dublette']} Dubletten, "
          f"{stat['uebersprungen_ohne_bild']} ohne Bild)")
    for s, v in stat["sessions"].items():
        print(f"  {s:16} Tier {v['tier']}  DB-Abgleich {v['db_verified']:.0%}  "
              f"{v['n_images']} Bilder (+{v['neu']})")
    if args.dry_run:
        print("[corpus-build] dry-run – nichts geschrieben.")
```

Im `main()`-Parser hinter dem `analyze`-Block:

```python
    p = sub.add_parser("corpus-build",
                       help="Regressions-Korpus aufbauen/aktualisieren "
                            "(idempotent, dedupliziert per SHA-256)")
    p.add_argument("--dry-run", action="store_true",
                   help="nur zaehlen, nichts schreiben")
```

Und im Dispatch-Dict hinter `"analyze": cmd_analyze,`:

```python
        "corpus-build": cmd_corpus_build,
```

- [ ] **Step 5: Tests laufen lassen, grün bestätigen**

Run: `.venv/bin/python -m pytest tests/test_corpus_build.py -q`
Expected: PASS, 8 passed

- [ ] **Step 6: CLI-Hilfe prüfen**

Run: `.venv/bin/python -m docodetect.cli corpus-build --help`
Expected: Hilfetext mit `--dry-run`, kein Traceback

- [ ] **Step 7: Commit**

```bash
git add docodetect/corpus/build.py docodetect/cli.py tests/test_corpus_build.py
git commit -m "feat(corpus): corpus-build mit Hash-Dedup und Tier-Herabstufung"
```

---

### Task 5: Runner mit ProcessPool und Cache

**Files:**
- Create: `docodetect/corpus/runner.py`
- Test: `tests/test_corpus_runner.py`

**Interfaces:**
- Consumes: Task 1–3, `docodetect.pipeline.measure_shot`, `docodetect.pipeline.Pipeline`
- Produces:
  - `code_fingerprint() -> str`
  - `config_fingerprint(cfg: dict) -> str`
  - `RunResult` dataclass: `sha`, `session`, `article`, `tier`, `band`, `diffs`, `error`
  - `run_one(entry_dict: dict, root_str: str, cfg: dict) -> dict`
  - `run_corpus(cfg, *, sessions=None, articles=None, tier=None, subset=None, workers=8, changed_only=False) -> dict`

`run_one` muss auf Modulebene stehen und pro Worker einen Kontext-Cache halten — sonst lädt jeder Task Hintergrund und Kalibrierung neu.

- [ ] **Step 1: Failing test schreiben**

`tests/test_corpus_runner.py`:

```python
"""Runner: Fingerprints, Filter, deterministische Reihenfolge, Cache."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.corpus.manifest import ImageEntry
from docodetect.corpus.runner import (auswahl, code_fingerprint,
                                      config_fingerprint)


def _e(sha, session="phase-b", article="LOEFFEL-1", tier=2):
    return ImageEntry(sha=sha, session=session, article=article,
                      image_rel=f"{session}/images/{article}/{sha[:8]}.png",
                      report_rel=f"{session}/reports/{sha[:8]}.json",
                      label=article, verdict="correct", tier=tier)


def test_code_fingerprint_is_stable_within_a_run():
    assert code_fingerprint() == code_fingerprint()
    assert len(code_fingerprint()) == 64


def test_config_fingerprint_reacts_to_a_threshold_change():
    a = {"matching": {"max_z_accept": 3.5}, "features": {}, "geometry": {}}
    b = {"matching": {"max_z_accept": 3.4}, "features": {}, "geometry": {}}
    assert config_fingerprint(a) != config_fingerprint(b)


def test_config_fingerprint_ignores_irrelevant_sections():
    a = {"matching": {"max_z_accept": 3.5}, "features": {}, "geometry": {},
         "camera": {"index": 0}}
    b = {"matching": {"max_z_accept": 3.5}, "features": {}, "geometry": {},
         "camera": {"index": 1}}
    assert config_fingerprint(a) == config_fingerprint(b)


def test_auswahl_is_deterministic_and_sorted():
    e = [_e("cc" * 32), _e("aa" * 32), _e("bb" * 32)]
    got = [x.sha for x in auswahl(e)]
    assert got == sorted(got)
    assert got == [x.sha for x in auswahl(list(reversed(e)))]


def test_auswahl_filters_by_session():
    e = [_e("aa" * 32, session="phase-a"), _e("bb" * 32, session="phase-b")]
    assert [x.session for x in auswahl(e, sessions=["phase-b"])] == ["phase-b"]


def test_auswahl_filters_by_article():
    e = [_e("aa" * 32, article="LOEFFEL-1"), _e("bb" * 32, article="LOEFFEL-5")]
    got = auswahl(e, articles=["LOEFFEL-5"])
    assert [x.article for x in got] == ["LOEFFEL-5"]


def test_auswahl_tier2_filter_drops_tier1_entries():
    e = [_e("aa" * 32, tier=1), _e("bb" * 32, tier=2)]
    assert [x.tier for x in auswahl(e, tier=2)] == [2]


def test_auswahl_tier1_filter_keeps_everything():
    """Tier 1 laeuft auf JEDEM Bild – auch auf den Tier-2-faehigen."""
    e = [_e("aa" * 32, tier=1), _e("bb" * 32, tier=2)]
    assert len(auswahl(e, tier=1)) == 2


def test_subset_takes_a_stable_prefix():
    e = [_e(f"{i:02x}" * 32) for i in range(10)]
    a = [x.sha for x in auswahl(e, subset=3)]
    b = [x.sha for x in auswahl(list(reversed(e)), subset=3)]
    assert a == b and len(a) == 3
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag bestätigen**

Run: `.venv/bin/python -m pytest tests/test_corpus_runner.py -q`
Expected: FAIL mit `ModuleNotFoundError: No module named 'docodetect.corpus.runner'`

- [ ] **Step 3: runner.py implementieren**

```python
"""Runner: Tier-1- und Tier-2-Replay ueber einen ProcessPool.

Der Replay ruft ausschliesslich pipeline.measure_shot() und
Pipeline.identify() gegen eine Buendel-Config mit captures_dir=None. Damit
bleibt der Messpfad unberuehrt UND der Lauf schreibt nichts nach
data/captures.
"""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..config import project_root
from .bundle import bundle_cfg
from .compare import FAIL, PASS, compare_tier1, compare_tier2, worst_band
from .manifest import ImageEntry, Manifest, corpus_root

# Quelldateien, deren Aenderung jedes Ergebnis ungueltig macht.
CODE_DATEIEN = ("segmentation.py", "features.py", "matcher.py", "pipeline.py",
                "calibration.py", "database.py")

# Config-Teilbaeume, die das Ergebnis beeinflussen. camera/ui/paths sind
# bewusst NICHT dabei — ein anderer Kamera-Index aendert kein Messergebnis
# auf gespeicherten Bildern.
CONFIG_TEILE = ("matching", "features", "geometry")

DEFAULT_WORKERS = 8   # gemessenes Optimum, 10 bringt nichts (Spec 5.1)


def code_fingerprint() -> str:
    h = hashlib.sha256()
    basis = project_root() / "docodetect"
    for name in CODE_DATEIEN:
        p = basis / name
        h.update(name.encode())
        h.update(p.read_bytes() if p.exists() else b"")
    return h.hexdigest()


def config_fingerprint(cfg: dict) -> str:
    teil = {k: cfg.get(k, {}) for k in CONFIG_TEILE}
    return hashlib.sha256(
        json.dumps(teil, sort_keys=True, default=str).encode()).hexdigest()


def auswahl(images: list, *, sessions=None, articles=None, tier=None,
            subset=None) -> list:
    """Deterministische, gefilterte Aufgabenliste. Sortiert nach
    (Session, SHA), damit Laeufe vergleichbar bleiben und --subset stabil
    denselben Ausschnitt trifft."""
    out = list(images)
    if sessions:
        out = [e for e in out if e.session in set(sessions)]
    if articles:
        out = [e for e in out if e.article in set(articles)]
    if tier == 2:
        out = [e for e in out if e.tier >= 2]
    out.sort(key=lambda e: (e.session, e.sha))
    return out[:subset] if subset else out


@dataclass
class RunResult:
    sha: str
    session: str
    article: str
    tier: int
    band: str
    diffs: list = field(default_factory=list)
    error: str | None = None


# --- Worker ---------------------------------------------------------------

_CTX: dict = {}


def _worker_init(cfg: dict, root_str: str) -> None:
    _CTX["cfg"] = cfg
    _CTX["root"] = Path(root_str)
    _CTX["bundles"] = {}


def _bundle_for(session: str) -> dict:
    """Buendel-Config je Session, einmal pro Worker gebaut."""
    if session not in _CTX["bundles"]:
        bdir = _CTX["root"] / session / "bundle"
        _CTX["bundles"][session] = bundle_cfg(_CTX["cfg"], bdir)
    return _CTX["bundles"][session]


def run_one(entry_dict: dict, tier: int) -> dict:
    """Ein Bild replayen. Laeuft im Worker-Prozess, gibt reine dicts zurueck
    (Dataclasses ueber Prozessgrenzen sind unnoetig fehleranfaellig)."""
    import cv2

    from ..matcher import MatchReport
    from ..pipeline import Pipeline, measure_shot
    from ..segmentation import SegmentationError

    e = ImageEntry(**entry_dict)
    root, bcfg = _CTX["root"], _bundle_for(e.session)
    res = RunResult(sha=e.sha, session=e.session, article=e.article,
                    tier=e.tier, band=PASS)
    try:
        golden = MatchReport.from_json(
            (root / e.report_rel).read_text(encoding="utf-8"))
        img = cv2.imread(str(root / e.image_rel))
        if img is None:
            res.error = "Bild nicht lesbar"
            res.band = FAIL
            return asdict(res)

        if tier == 2 and e.tier >= 2:
            pipe = Pipeline(bcfg)
            try:
                outcome = pipe.identify(img, source_path=str(root / e.image_rel),
                                        label=e.label)
            finally:
                pipe.close()
            # Replay-Report ablegen: daraus rechnet report.tier2_quotas() die
            # Kennzahlen. Muss hier passieren, weil der Report nur im Worker
            # existiert — captures_dir ist im Buendel bewusst None, die
            # Pipeline schreibt also selbst nichts.
            replay = root / "runs" / "_replay"
            replay.mkdir(parents=True, exist_ok=True)
            rep = outcome.report
            rep.label, rep.verdict = e.label, e.verdict
            (replay / f"{e.sha[:8]}.json").write_text(rep.to_json(),
                                                      encoding="utf-8")
            diffs = compare_tier2(golden, rep)
        else:
            try:
                feats, seg = measure_shot(img, bcfg)
                centroid = None
                m = cv2.moments(seg.contour)
                if m["m00"]:
                    centroid = [round(m["m10"] / m["m00"], 1),
                                round(m["m01"] / m["m00"], 1)]
                diffs = compare_tier1(golden, feats, seg.area_px, centroid)
            except SegmentationError:
                # Golden brach ebenfalls ab -> reproduziert; sonst Regression.
                if golden.touches_border or golden.decision == "reject":
                    diffs = []
                else:
                    res.error = "SegmentationError, Golden war messbar"
                    res.band = FAIL
                    return asdict(res)

        res.diffs = [asdict(d) for d in diffs]
        res.band = worst_band(diffs)
    except Exception as exc:                       # noqa: BLE001
        res.error = f"{type(exc).__name__}: {exc}"
        res.band = FAIL
    return asdict(res)


# --- Orchestrierung -------------------------------------------------------

def _cache_path(root: Path) -> Path:
    return root / ".cache" / "results.json"


def _cache_key(sha: str, tier: int, code_fp: str, cfg_fp: str) -> str:
    return f"{sha}:{tier}:{code_fp[:16]}:{cfg_fp[:16]}"


def run_corpus(cfg: dict, *, sessions=None, articles=None, tier: int = 1,
               subset=None, workers: int = DEFAULT_WORKERS,
               changed_only: bool = False) -> dict:
    import time

    root = corpus_root(cfg)
    manifest = Manifest.load()
    aufgaben = auswahl(manifest.images, sessions=sessions, articles=articles,
                       tier=tier, subset=subset)
    code_fp, cfg_fp = code_fingerprint(), config_fingerprint(cfg)

    cache: dict = {}
    cp = _cache_path(root)
    if changed_only and cp.exists():
        cache = json.loads(cp.read_text(encoding="utf-8"))

    offen, ergebnisse = [], []
    for e in aufgaben:
        k = _cache_key(e.sha, tier, code_fp, cfg_fp)
        if changed_only and k in cache:
            ergebnisse.append(cache[k])
        else:
            offen.append(e)

    t0 = time.time()
    if offen:
        with ProcessPoolExecutor(max_workers=workers, initializer=_worker_init,
                                 initargs=(cfg, str(root))) as ex:
            frisch = list(ex.map(run_one, [asdict(e) for e in offen],
                                 [tier] * len(offen), chunksize=1))
        ergebnisse.extend(frisch)
        for e, r in zip(offen, frisch):
            cache[_cache_key(e.sha, tier, code_fp, cfg_fp)] = r
    dauer = time.time() - t0

    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps(cache), encoding="utf-8")

    ergebnisse.sort(key=lambda r: (r["session"], r["sha"]))
    return {"results": ergebnisse, "tier": tier, "dauer_s": round(dauer, 1),
            "n": len(ergebnisse), "neu_gerechnet": len(offen),
            "bilder_pro_s": round(len(offen) / dauer, 2) if dauer > 0 and offen else None,
            "code_fingerprint": code_fp, "config_fingerprint": cfg_fp}
```

- [ ] **Step 4: Tests laufen lassen, grün bestätigen**

Run: `.venv/bin/python -m pytest tests/test_corpus_runner.py -q`
Expected: PASS, 9 passed

- [ ] **Step 5: Commit**

```bash
git add docodetect/corpus/runner.py tests/test_corpus_runner.py
git commit -m "feat(corpus): paralleler Runner mit Code-/Config-Fingerprint-Cache"
```

---

### Task 6: Baseline, Wilson-Grenzen und Lauf-Berichte

**Files:**
- Create: `docodetect/corpus/report.py`
- Test: `tests/test_corpus_report.py`

**Interfaces:**
- Produces:
  - `wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float, float]` — (p, lo, hi)
  - `tier2_quotas(reports: list[MatchReport]) -> dict`
  - `classify_drift(results: list[dict]) -> dict` — `{"muster": "uniform"|"ausreisser"|"keine", ...}`
  - `write_run(root: Path, run_id: str, run: dict, quotas: dict) -> Path`
  - `BASELINE_PATH`, `load_baseline() -> dict`, `save_baseline(payload: dict) -> Path`
  - `check_against_baseline(run: dict, quotas: dict, baseline: dict, *, accept_drift: bool) -> tuple[int, list[str]]`

`tier2_quotas` nutzt `reporting.summarize()` und `reporting.top_k_accuracy()` — keine zweite Zählimplementierung.

- [ ] **Step 1: Failing test schreiben**

`tests/test_corpus_report.py`:

```python
"""Baseline, Wilson-Grenzen, Drift-Klassifikation, Exit-Codes."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.corpus.report import (check_against_baseline, classify_drift,
                                      wilson)


def test_wilson_centre_matches_the_point_estimate():
    p, lo, hi = wilson(46, 60)
    assert p == pytest.approx(0.7667, abs=1e-4)
    assert lo < p < hi


def test_wilson_matches_the_published_phase_b_numbers():
    """Gegenprobe an reports/analysis/phase-b-korrigiert/metrics.json."""
    p, lo, hi = wilson(46, 60)
    assert lo == pytest.approx(0.6456, abs=5e-3)
    assert hi == pytest.approx(0.8556, abs=5e-3)


def test_wilson_handles_zero_events():
    p, lo, hi = wilson(0, 25)
    assert p == 0.0 and lo == 0.0 and hi == pytest.approx(0.1332, abs=5e-3)


def test_wilson_is_safe_for_empty_samples():
    assert wilson(0, 0) == (0.0, 0.0, 0.0)


def _r(band, sha, delta=0.0, field="circle_diameter_mm"):
    return {"sha": sha, "session": "s", "article": "A", "tier": 1, "band": band,
            "error": None,
            "diffs": [{"field": field, "golden": 1.0, "actual": 1.0 + delta,
                       "delta": delta, "band": band}]}


def test_classify_drift_reports_none_when_everything_passes():
    assert classify_drift([_r("pass", "a"), _r("pass", "b")])["muster"] == "keine"


def test_classify_drift_recognises_a_uniform_shift():
    """Gleichmaessige kleine Verschiebung ueber viele Bilder = Bibliothek
    oder Plattform, nicht Code."""
    res = [_r("drift", f"{i:02x}", delta=0.10) for i in range(20)]
    got = classify_drift(res)
    assert got["muster"] == "uniform"
    assert got["betroffen"] == 20


def test_classify_drift_recognises_outliers():
    res = [_r("pass", f"{i:02x}") for i in range(20)]
    res.append(_r("drift", "ff", delta=0.19))
    got = classify_drift(res)
    assert got["muster"] == "ausreisser"
    assert got["betroffen"] == 1


def _run(band_counts):
    results = []
    for band, n in band_counts.items():
        results += [_r(band, f"{band}{i}") for i in range(n)]
    return {"results": results, "tier": 1, "n": len(results)}


def test_check_passes_when_everything_passes():
    code, meldungen = check_against_baseline(
        _run({"pass": 10}), {}, {}, accept_drift=False)
    assert code == 0


def test_check_fails_on_drift_by_default():
    """Auf gepinnter Umgebung ist jede Abweichung code-verursacht."""
    code, meldungen = check_against_baseline(
        _run({"pass": 9, "drift": 1}), {}, {}, accept_drift=False)
    assert code == 1
    assert any("DRIFT" in m for m in meldungen)


def test_check_tolerates_drift_with_accept_drift():
    code, _ = check_against_baseline(
        _run({"pass": 9, "drift": 1}), {}, {}, accept_drift=True)
    assert code == 0


def test_check_always_fails_on_fail_even_with_accept_drift():
    code, _ = check_against_baseline(
        _run({"pass": 9, "fail": 1}), {}, {}, accept_drift=True)
    assert code == 1


def test_check_flags_a_quota_below_the_baseline_wilson_floor():
    baseline = {"quotas": {"accuracy_top1": {"k": 46, "n": 60, "p": 0.7667,
                                             "wilson_lo": 0.6456,
                                             "wilson_hi": 0.8556}}}
    quotas = {"accuracy_top1": {"k": 30, "n": 60, "p": 0.5,
                                "wilson_lo": 0.3773, "wilson_hi": 0.6227}}
    code, meldungen = check_against_baseline(
        _run({"pass": 10}), quotas, baseline, accept_drift=False)
    assert code == 1
    assert any("accuracy_top1" in m for m in meldungen)


def test_check_accepts_a_quota_inside_the_baseline_interval():
    baseline = {"quotas": {"accuracy_top1": {"k": 46, "n": 60, "p": 0.7667,
                                             "wilson_lo": 0.6456,
                                             "wilson_hi": 0.8556}}}
    quotas = {"accuracy_top1": {"k": 44, "n": 60, "p": 0.7333,
                                "wilson_lo": 0.6098, "wilson_hi": 0.8284}}
    code, _ = check_against_baseline(
        _run({"pass": 10}), quotas, baseline, accept_drift=False)
    assert code == 0
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag bestätigen**

Run: `.venv/bin/python -m pytest tests/test_corpus_report.py -q`
Expected: FAIL mit `ModuleNotFoundError: No module named 'docodetect.corpus.report'`

- [ ] **Step 3: report.py implementieren**

```python
"""Lauf-Berichte, Baseline und Exit-Code-Logik."""

from __future__ import annotations

import json
import math
import statistics
from datetime import datetime
from pathlib import Path

from ..config import project_root
from ..reporting import summarize, top_k_accuracy
from .compare import DRIFT, FAIL

BASELINE_PATH = project_root() / "corpus" / "baseline.json"

# Ab so vielen betroffenen Bildern UND so kleiner relativer Streuung gilt
# eine Drift als uniform (Bibliothek/Plattform) statt als Ausreisser (Code).
UNIFORM_MIN_ANTEIL = 0.5
UNIFORM_MAX_STREUUNG = 0.25


def wilson(k: int, n: int, z: float = 1.96) -> tuple:
    """Punktschaetzer plus Wilson-Score-Intervall. Wilson statt Normal-
    approximation, weil die Quoten hier oft nahe 0 oder 1 liegen (FAR!)."""
    if n <= 0:
        return 0.0, 0.0, 0.0
    p = k / n
    d = 1.0 + z * z / n
    mitte = (p + z * z / (2 * n)) / d
    rand = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return round(p, 4), round(max(0.0, mitte - rand), 4), round(min(1.0, mitte + rand), 4)


def tier2_quotas(reports: list) -> dict:
    """Kennzahlen ueber Replay-Reports. Nutzt dieselbe Aggregation wie
    `analyze`, damit die Zahlen zwischen den Werkzeugen identisch bleiben."""
    s = summarize(reports)
    h1, n1 = top_k_accuracy(reports, 1)
    h3, n3 = top_k_accuracy(reports, 3)
    akzeptiert = [r for r in reports if r.decision == "accept"]
    falsch_akzeptiert = sum(
        1 for r in akzeptiert
        if r.label and r.candidates and r.candidates[0].article_number != r.label)

    def q(k, n):
        p, lo, hi = wilson(k, n)
        return {"k": k, "n": n, "p": p, "wilson_lo": lo, "wilson_hi": hi}

    return {
        "accuracy_top1": q(h1, n1),
        "accuracy_top3": q(h3, n3),
        "auto_accept_rate": q(len(akzeptiert), len(reports)),
        "false_accept_rate": q(falsch_akzeptiert, len(akzeptiert)),
        "decisions": s.decision_counts,
    }


def classify_drift(results: list) -> dict:
    """Uniforme Drift (Bibliothek/Plattform) von Ausreissern (Code) trennen.

    Uniform = viele Bilder, alle ungefaehr gleich stark verschoben.
    Ausreisser = wenige Bilder, beliebige Groesse. Genau diese Trennung
    entscheidet, ob ein --accept-drift-Lauf gerechtfertigt ist.
    """
    betroffen = [r for r in results if r["band"] == DRIFT]
    if not betroffen:
        return {"muster": "keine", "betroffen": 0, "anteil": 0.0}
    deltas = []
    for r in betroffen:
        werte = [abs(d["delta"]) for d in r["diffs"]
                 if d["band"] == DRIFT and isinstance(d["delta"], (int, float))
                 and not math.isnan(d["delta"])]
        if werte:
            deltas.append(max(werte))
    anteil = len(betroffen) / max(1, len(results))
    streuung = 0.0
    if len(deltas) > 1 and statistics.mean(deltas) > 0:
        streuung = statistics.pstdev(deltas) / statistics.mean(deltas)
    uniform = anteil >= UNIFORM_MIN_ANTEIL and streuung <= UNIFORM_MAX_STREUUNG
    return {"muster": "uniform" if uniform else "ausreisser",
            "betroffen": len(betroffen), "anteil": round(anteil, 3),
            "delta_median": round(statistics.median(deltas), 6) if deltas else 0.0,
            "streuung": round(streuung, 3)}


def load_baseline() -> dict:
    if not BASELINE_PATH.exists():
        return {}
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def save_baseline(payload: dict) -> Path:
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return BASELINE_PATH


def check_against_baseline(run: dict, quotas: dict, baseline: dict, *,
                           accept_drift: bool) -> tuple:
    """Exit-Code plus Klartext-Meldungen.

    0 = in Ordnung, 1 = Regression. Per Default brechen DRIFT und FAIL
    beide: auf derselben Maschine mit denselben Bibliotheken ist jede
    Abweichung code-verursacht, und nur so bleibt --check bisect-tauglich.
    """
    meldungen, code = [], 0
    fails = [r for r in run["results"] if r["band"] == FAIL]
    drifts = [r for r in run["results"] if r["band"] == DRIFT]

    if fails:
        code = 1
        meldungen.append(f"FAIL: {len(fails)} Bild(er) ausserhalb der weichen Stufe")
    if drifts:
        if accept_drift:
            meldungen.append(f"DRIFT: {len(drifts)} Bild(er) – toleriert "
                             "(--accept-drift). Re-Baselining mit Begruendung faellig.")
        else:
            code = 1
            meldungen.append(f"DRIFT: {len(drifts)} Bild(er) ausserhalb des "
                             "Rundungsquantums – auf gepinnter Umgebung ist das "
                             "code-verursacht (--accept-drift zum Tolerieren)")

    for name, jetzt in (quotas or {}).items():
        alt = (baseline.get("quotas") or {}).get(name)
        if not alt or not isinstance(jetzt, dict) or "p" not in jetzt:
            continue
        if jetzt["p"] < alt.get("wilson_lo", 0.0):
            code = 1
            meldungen.append(
                f"{name}: {jetzt['p']:.4f} unter Baseline-Wilson-Untergrenze "
                f"{alt['wilson_lo']:.4f} (Baseline p={alt.get('p')})")
    return code, meldungen


def write_run(root: Path, run_id: str, run: dict, quotas: dict) -> Path:
    """runs/<run_id>/ mit summary.md, metrics.json und failures/."""
    out = root / "runs" / run_id
    (out / "failures").mkdir(parents=True, exist_ok=True)

    drift = classify_drift(run["results"])
    zaehler = {}
    for r in run["results"]:
        zaehler[r["band"]] = zaehler.get(r["band"], 0) + 1

    (out / "metrics.json").write_text(json.dumps(
        {"run_id": run_id, "generated": datetime.now().isoformat(timespec="seconds"),
         "tier": run["tier"], "n": run["n"], "dauer_s": run["dauer_s"],
         "bilder_pro_s": run["bilder_pro_s"], "baender": zaehler,
         "drift": drift, "quotas": quotas,
         "code_fingerprint": run["code_fingerprint"],
         "config_fingerprint": run["config_fingerprint"]},
        indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    for r in run["results"]:
        if r["band"] == "pass":
            continue
        (out / "failures" / f"{r['sha'][:8]}.json").write_text(
            json.dumps({**r, "image_rel": f"{r['session']}/images/"
                                          f"{r['article']}/{r['sha'][:8]}.png"},
                       indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    zeilen = [f"# Korpus-Lauf `{run_id}`", "",
              f"- Tier: {run['tier']}",
              f"- Bilder: {run['n']} (neu gerechnet: {run['neu_gerechnet']})",
              f"- Laufzeit: {run['dauer_s']} s"
              + (f" = {run['bilder_pro_s']} Bilder/s" if run["bilder_pro_s"] else ""),
              "", "## Baender", ""]
    for b in ("pass", "drift", "fail"):
        zeilen.append(f"- {b.upper()}: {zaehler.get(b, 0)}")
    zeilen += ["", "## Drift-Klassifikation", "",
               f"- Muster: **{drift['muster']}**",
               f"- betroffen: {drift['betroffen']} ({drift['anteil']:.1%})",
               f"- Delta-Median: {drift['delta_median']}",
               f"- relative Streuung: {drift['streuung']}", ""]
    if drift["muster"] == "uniform":
        zeilen.append("> Gleichmaessige Verschiebung ueber viele Bilder — Muster "
                      "Bibliothek/Plattform, nicht Code.")
    elif drift["muster"] == "ausreisser":
        zeilen.append("> Einzelne Bilder betroffen — Muster Code-Regression.")
    if quotas:
        zeilen += ["", "## Tier-2-Quoten", "",
                   "| Kennzahl | k/n | p | Wilson |", "|---|---|---|---|"]
        for name, q in quotas.items():
            if isinstance(q, dict) and "p" in q:
                zeilen.append(f"| {name} | {q['k']}/{q['n']} | {q['p']:.4f} | "
                              f"{q['wilson_lo']:.4f} … {q['wilson_hi']:.4f} |")
    (out / "summary.md").write_text("\n".join(zeilen) + "\n", encoding="utf-8")
    return out
```

- [ ] **Step 4: Tests laufen lassen, grün bestätigen**

Run: `.venv/bin/python -m pytest tests/test_corpus_report.py -q`
Expected: PASS, 14 passed

- [ ] **Step 5: Commit**

```bash
git add docodetect/corpus/report.py tests/test_corpus_report.py
git commit -m "feat(corpus): Wilson-Quoten, Drift-Klassifikation und Baseline-Check"
```

---

### Task 7: corpus-run CLI

**Files:**
- Modify: `docodetect/cli.py`
- Test: `tests/test_corpus_cli.py`

**Interfaces:**
- Consumes: Task 5–6
- Produces: `cmd_corpus_run(args, cfg)`; Exit-Code über `SystemExit`

- [ ] **Step 1: Failing test schreiben**

`tests/test_corpus_cli.py`:

```python
"""corpus-run: Argument-Parsing und Exit-Codes."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect import cli


def test_corpus_run_is_registered():
    with pytest.raises(SystemExit) as e:
        cli.main(["corpus-run", "--help"])
    assert e.value.code == 0


def test_corpus_build_is_registered():
    with pytest.raises(SystemExit) as e:
        cli.main(["corpus-build", "--help"])
    assert e.value.code == 0


def test_corpus_diff_is_registered():
    with pytest.raises(SystemExit) as e:
        cli.main(["corpus-diff", "--help"])
    assert e.value.code == 0


def test_corpus_triage_is_registered():
    with pytest.raises(SystemExit) as e:
        cli.main(["corpus-triage", "--help"])
    assert e.value.code == 0


def test_check_exits_nonzero_on_regression(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "docodetect.corpus.runner.run_corpus",
        lambda cfg, **kw: {"results": [{"sha": "a" * 64, "session": "s",
                                        "article": "A", "tier": 1,
                                        "band": "fail", "diffs": [],
                                        "error": None}],
                           "tier": 1, "dauer_s": 0.1, "n": 1,
                           "neu_gerechnet": 1, "bilder_pro_s": 10.0,
                           "code_fingerprint": "x" * 64,
                           "config_fingerprint": "y" * 64})
    monkeypatch.setattr("docodetect.corpus.report.BASELINE_PATH",
                        tmp_path / "baseline.json")
    monkeypatch.setattr("docodetect.corpus.manifest.MANIFEST_PATH",
                        tmp_path / "manifest.json")
    with pytest.raises(SystemExit) as e:
        cli.main(["corpus-run", "--check", "--tier", "1"])
    assert e.value.code == 1


def test_check_exits_zero_when_clean(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "docodetect.corpus.runner.run_corpus",
        lambda cfg, **kw: {"results": [{"sha": "a" * 64, "session": "s",
                                        "article": "A", "tier": 1,
                                        "band": "pass", "diffs": [],
                                        "error": None}],
                           "tier": 1, "dauer_s": 0.1, "n": 1,
                           "neu_gerechnet": 1, "bilder_pro_s": 10.0,
                           "code_fingerprint": "x" * 64,
                           "config_fingerprint": "y" * 64})
    monkeypatch.setattr("docodetect.corpus.report.BASELINE_PATH",
                        tmp_path / "baseline.json")
    monkeypatch.setattr("docodetect.corpus.manifest.MANIFEST_PATH",
                        tmp_path / "manifest.json")
    with pytest.raises(SystemExit) as e:
        cli.main(["corpus-run", "--check", "--tier", "1"])
    assert e.value.code == 0
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag bestätigen**

Run: `.venv/bin/python -m pytest tests/test_corpus_cli.py -q`
Expected: FAIL — `corpus-run` ist noch nicht registriert (SystemExit code 2)

- [ ] **Step 3: cmd_corpus_run in cli.py ergänzen**

Neben `cmd_corpus_build` einfügen:

```python
def cmd_corpus_run(args, cfg):
    """Korpus-Replay: Tier 1 (Messung) bzw. Tier 2 (Entscheidung)."""
    import sys
    from datetime import datetime

    from .corpus import report as corpus_report
    from .corpus import runner as corpus_runner
    from .corpus.manifest import corpus_root
    from .matcher import MatchReport

    run = corpus_runner.run_corpus(
        cfg, sessions=args.session, articles=args.article, tier=args.tier,
        subset=args.subset, workers=args.workers, changed_only=args.changed_only)

    quotas = {}
    if args.tier == 2:
        root = corpus_root(cfg)
        reports = []
        for r in run["results"]:
            p = root / "runs" / "_replay" / f"{r['sha'][:8]}.json"
            if p.exists():
                reports.append(MatchReport.from_json(p.read_text(encoding="utf-8")))
        if reports:
            quotas = corpus_report.tier2_quotas(reports)

    run_id = args.run_id or datetime.now().strftime("%Y%m%d-%H%M%S")
    out = corpus_report.write_run(corpus_root(cfg), run_id, run, quotas)
    print(f"[corpus-run] {run['n']} Bilder, Tier {run['tier']}, "
          f"{run['dauer_s']} s"
          + (f" ({run['bilder_pro_s']} Bilder/s)" if run["bilder_pro_s"] else ""))
    print(f"[corpus-run] Bericht: {out / 'summary.md'}")

    if args.update_baseline:
        corpus_report.save_baseline({
            "generated": datetime.now().isoformat(timespec="seconds"),
            "run_id": run_id, "tier": run["tier"], "n": run["n"],
            "quotas": quotas, "code_fingerprint": run["code_fingerprint"],
            "config_fingerprint": run["config_fingerprint"]})
        print(f"[corpus-run] Baseline aktualisiert: {corpus_report.BASELINE_PATH}")
        print("[corpus-run] ACHTUNG: Begruendung im Commit ist Pflicht.")

    if args.check:
        code, meldungen = corpus_report.check_against_baseline(
            run, quotas, corpus_report.load_baseline(),
            accept_drift=args.accept_drift)
        for m in meldungen:
            print(f"[corpus-run] {m}")
        print("[corpus-run] " + ("OK" if code == 0 else "REGRESSION"))
        sys.exit(code)
```

Im `main()`-Parser hinter dem `corpus-build`-Block:

```python
    p = sub.add_parser("corpus-run", help="Korpus-Replay gegen die Goldens")
    p.add_argument("--tier", type=int, choices=(1, 2), default=1)
    p.add_argument("--session", action="append",
                   help="nur diese Session (mehrfach angebbar)")
    p.add_argument("--article", action="append",
                   help="nur diesen Artikel (mehrfach angebbar)")
    p.add_argument("--subset", type=int, default=None,
                   help="nur die ersten N Bilder (deterministisch)")
    p.add_argument("--workers", type=int, default=8,
                   help="Prozesse (Default 8 – gemessenes Optimum)")
    p.add_argument("--changed-only", action="store_true",
                   help="Ergebnis-Cache nutzen; invalidiert bei Code- oder "
                        "Schwellenaenderung automatisch")
    p.add_argument("--run-id", default=None)
    p.add_argument("--check", action="store_true",
                   help="gegen baseline.json pruefen, Exit 1 bei Regression")
    p.add_argument("--accept-drift", action="store_true",
                   help="DRIFT tolerieren (nur bei bewusstem Bibliotheks-"
                        "Update oder Plattformwechsel; Re-Baselining faellig)")
    p.add_argument("--update-baseline", action="store_true",
                   help="Baseline aus diesem Lauf neu schreiben "
                        "(Begruendung im Commit ist Pflicht)")
```

Im Dispatch-Dict:

```python
        "corpus-run": cmd_corpus_run,
```

- [ ] **Step 4: Platzhalter für corpus-diff und corpus-triage registrieren**

Damit `tests/test_corpus_cli.py` vollständig grün wird, jetzt schon die Parser anlegen (Implementierung folgt in Task 8/9):

```python
    p = sub.add_parser("corpus-diff", help="zwei Korpus-Laeufe vergleichen")
    p.add_argument("run_a")
    p.add_argument("run_b")

    p = sub.add_parser("corpus-triage",
                       help="Failures eines Laufs clustern (nur Befunde)")
    p.add_argument("run_id")
```

Und im Dispatch-Dict:

```python
        "corpus-diff": cmd_corpus_diff,
        "corpus-triage": cmd_corpus_triage,
```

Dazu die beiden Funktionen (Rumpf, Task 8/9 füllt sie):

```python
def cmd_corpus_diff(args, cfg):
    """Zwei Korpus-Laeufe gegeneinander stellen."""
    from .corpus.diff import diff_runs, format_diff
    from .corpus.manifest import corpus_root
    print(format_diff(diff_runs(corpus_root(cfg), args.run_a, args.run_b)))


def cmd_corpus_triage(args, cfg):
    """Failures clustern und findings.md schreiben. Nur Befunde."""
    from .corpus.manifest import corpus_root
    from .corpus.triage import triage_run
    out = triage_run(cfg, corpus_root(cfg), args.run_id)
    print(f"[corpus-triage] Befunde: {out}")
```

- [ ] **Step 5: Tests laufen lassen, grün bestätigen**

Run: `.venv/bin/python -m pytest tests/test_corpus_cli.py -q`
Expected: PASS, 6 passed

- [ ] **Step 6: Commit**

```bash
git add docodetect/cli.py tests/test_corpus_cli.py
git commit -m "feat(corpus): corpus-run mit --check, --accept-drift, --update-baseline"
```

---

### Task 8: corpus-diff

**Files:**
- Create: `docodetect/corpus/diff.py`
- Test: `tests/test_corpus_diff.py`

**Interfaces:**
- Produces:
  - `diff_runs(root: Path, run_a: str, run_b: str) -> dict` — Schlüssel `neu_kaputt`, `repariert`, `weiterhin_kaputt`, `metrik_deltas`
  - `format_diff(d: dict) -> str`

- [ ] **Step 1: Failing test schreiben**

`tests/test_corpus_diff.py`:

```python
"""corpus-diff: neu kaputt / repariert / weiterhin kaputt."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.corpus.diff import diff_runs, format_diff


def _lauf(root: Path, run_id: str, baender: dict, quotas=None):
    d = root / "runs" / run_id
    (d / "failures").mkdir(parents=True, exist_ok=True)
    (d / "metrics.json").write_text(json.dumps(
        {"run_id": run_id, "tier": 1, "n": len(baender),
         "baender": {}, "quotas": quotas or {}}))
    for sha, band in baender.items():
        if band != "pass":
            (d / "failures" / f"{sha}.json").write_text(json.dumps(
                {"sha": sha, "session": "s", "article": "A", "band": band,
                 "diffs": [], "error": None}))


def test_diff_detects_newly_broken(tmp_path):
    _lauf(tmp_path, "a", {"aaaaaaaa": "pass"})
    _lauf(tmp_path, "b", {"aaaaaaaa": "fail"})
    d = diff_runs(tmp_path, "a", "b")
    assert d["neu_kaputt"] == ["aaaaaaaa"]
    assert d["repariert"] == []


def test_diff_detects_repaired(tmp_path):
    _lauf(tmp_path, "a", {"aaaaaaaa": "fail"})
    _lauf(tmp_path, "b", {"aaaaaaaa": "pass"})
    d = diff_runs(tmp_path, "a", "b")
    assert d["repariert"] == ["aaaaaaaa"]
    assert d["neu_kaputt"] == []


def test_diff_detects_still_broken(tmp_path):
    _lauf(tmp_path, "a", {"aaaaaaaa": "fail"})
    _lauf(tmp_path, "b", {"aaaaaaaa": "fail"})
    assert diff_runs(tmp_path, "a", "b")["weiterhin_kaputt"] == ["aaaaaaaa"]


def test_diff_reports_metric_deltas(tmp_path):
    _lauf(tmp_path, "a", {"x": "pass"},
          quotas={"accuracy_top1": {"p": 0.7667, "k": 46, "n": 60}})
    _lauf(tmp_path, "b", {"x": "pass"},
          quotas={"accuracy_top1": {"p": 0.8000, "k": 48, "n": 60}})
    d = diff_runs(tmp_path, "a", "b")
    assert d["metrik_deltas"]["accuracy_top1"]["delta"] == pytest.approx(0.0333, abs=1e-4)


def test_format_diff_mentions_all_three_groups(tmp_path):
    _lauf(tmp_path, "a", {"aa": "fail", "bb": "pass", "cc": "fail"})
    _lauf(tmp_path, "b", {"aa": "pass", "bb": "fail", "cc": "fail"})
    text = format_diff(diff_runs(tmp_path, "a", "b"))
    assert "neu kaputt" in text and "repariert" in text and "weiterhin kaputt" in text


def test_diff_raises_for_a_missing_run(tmp_path):
    _lauf(tmp_path, "a", {"x": "pass"})
    with pytest.raises(FileNotFoundError):
        diff_runs(tmp_path, "a", "fehlt")
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag bestätigen**

Run: `.venv/bin/python -m pytest tests/test_corpus_diff.py -q`
Expected: FAIL mit `ModuleNotFoundError: No module named 'docodetect.corpus.diff'`

- [ ] **Step 3: diff.py implementieren**

```python
"""corpus-diff: zwei Laeufe gegeneinander stellen."""

from __future__ import annotations

import json
from pathlib import Path


def _lade(root: Path, run_id: str) -> tuple:
    d = root / "runs" / run_id
    mp = d / "metrics.json"
    if not mp.exists():
        raise FileNotFoundError(f"Lauf '{run_id}' hat keine metrics.json ({mp})")
    metrics = json.loads(mp.read_text(encoding="utf-8"))
    kaputt = set()
    fd = d / "failures"
    if fd.is_dir():
        kaputt = {p.stem for p in fd.glob("*.json")}
    return metrics, kaputt


def diff_runs(root: Path, run_a: str, run_b: str) -> dict:
    ma, ka = _lade(root, run_a)
    mb, kb = _lade(root, run_b)
    deltas = {}
    qa, qb = ma.get("quotas") or {}, mb.get("quotas") or {}
    for name in sorted(set(qa) & set(qb)):
        a, b = qa[name], qb[name]
        if isinstance(a, dict) and isinstance(b, dict) and "p" in a and "p" in b:
            deltas[name] = {"a": a["p"], "b": b["p"],
                            "delta": round(b["p"] - a["p"], 4)}
    return {"run_a": run_a, "run_b": run_b,
            "neu_kaputt": sorted(kb - ka),
            "repariert": sorted(ka - kb),
            "weiterhin_kaputt": sorted(ka & kb),
            "metrik_deltas": deltas}


def format_diff(d: dict) -> str:
    z = [f"=== corpus-diff: {d['run_a']} -> {d['run_b']} ===", ""]
    for titel, key in (("neu kaputt", "neu_kaputt"),
                       ("repariert", "repariert"),
                       ("weiterhin kaputt", "weiterhin_kaputt")):
        z.append(f"{titel}: {len(d[key])}")
        for sha in d[key][:20]:
            z.append(f"    {sha}")
        if len(d[key]) > 20:
            z.append(f"    … und {len(d[key]) - 20} weitere")
        z.append("")
    if d["metrik_deltas"]:
        z.append("Metrik-Deltas:")
        for name, v in d["metrik_deltas"].items():
            z.append(f"    {name:22} {v['a']:.4f} -> {v['b']:.4f}  ({v['delta']:+.4f})")
    return "\n".join(z)
```

- [ ] **Step 4: Tests laufen lassen, grün bestätigen**

Run: `.venv/bin/python -m pytest tests/test_corpus_diff.py -q`
Expected: PASS, 6 passed

- [ ] **Step 5: Commit**

```bash
git add docodetect/corpus/diff.py tests/test_corpus_diff.py
git commit -m "feat(corpus): corpus-diff mit Metrik-Deltas"
```

---

### Task 9: corpus-triage

**Files:**
- Create: `docodetect/corpus/triage.py`
- Test: `tests/test_corpus_triage.py`

**Interfaces:**
- Produces:
  - `KATEGORIEN` (tuple der Kategorienamen)
  - `categorize(failure: dict, golden) -> str`
  - `position_correlation(cfg, root, manifest) -> dict` — der Diskriminator-Test aus Spec 7.1
  - `triage_run(cfg: dict, root: Path, run_id: str) -> Path`

Triage erzeugt **nur** Befunde. Kein Schreibzugriff ausserhalb von `runs/<run_id>/findings.md`.

- [ ] **Step 1: Failing test schreiben**

`tests/test_corpus_triage.py`:

```python
"""corpus-triage: Kategorisierung und Positions-Korrelation."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.corpus.triage import categorize, position_correlation
from docodetect.matcher import CandidateReport, MatchReport


def _golden(arts=("LOEFFEL-1",), label="LOEFFEL-1", decision="ambiguous"):
    return MatchReport(
        decision=decision, message="", label=label, verdict="wrong",
        candidates=[CandidateReport(article_number=a, name=a,
                                    nominal_size_mm=1.0, height_mm=0.0,
                                    corrected_diameter_mm=1.0,
                                    geometry_error_mm=0.0, has_references=True,
                                    n_shots=9) for a in arts])


def _fail(fields):
    return {"sha": "aa" * 32, "session": "s", "article": "A", "band": "fail",
            "error": None,
            "diffs": [{"field": f, "golden": 1.0, "actual": 2.0, "delta": 1.0,
                       "band": "fail"} for f in fields]}


def test_segmentation_change_wins_over_measurement_drift():
    """Aendert sich die Kontur, sind die Messwerte nur Folge — die
    Kategorie muss die Ursache benennen, nicht das Symptom."""
    got = categorize(_fail(["seg_area_px", "circle_diameter_mm"]), _golden())
    assert got == "segmentierungs_aenderung"


def test_pure_scalar_drift_is_measurement_drift():
    assert categorize(_fail(["circle_diameter_mm"]), _golden()) == "messwert_drift"


def test_gate_flip_is_its_own_category():
    assert categorize(_fail(["gate_passed"]), _golden()) == "gate_kipp"


def test_prefilter_kill_detected_when_truth_missing_from_candidates():
    """Kill = wahrer Artikel ueberlebte den Vorfilter nicht. Die
    Entscheidungs-Spalte ist dafuer NICHT der Schluessel."""
    g = _golden(arts=("LOEFFEL-5",), label="LOEFFEL-1")
    assert categorize(_fail(["top_k"]), g) == "vorfilter_kill"


def test_prefilter_kill_is_independent_of_the_decision():
    g = _golden(arts=("LOEFFEL-5",), label="LOEFFEL-1", decision="reject")
    assert categorize(_fail(["top_k"]), g) == "vorfilter_kill"


def test_label_suspicion_for_high_confidence_against_the_label():
    g = _golden(arts=("LOEFFEL-5",), label="LOEFFEL-1", decision="accept")
    g.candidates[0].posterior = 0.99
    g.gate_passed = True
    assert categorize(_fail([]), g) == "label_verdacht"


def test_pearson_finds_a_planted_relationship():
    """Je zentraler, desto kuerzer — die Signatur aus Spec 7.1."""
    from docodetect.corpus.triage import _pearson
    punkte = [{"dist": d, "delta": -8.0 + 0.02 * d} for d in range(0, 1000, 50)]
    r = _pearson([p["dist"] for p in punkte], [p["delta"] for p in punkte])
    assert r == pytest.approx(1.0, abs=1e-6)


def test_pearson_detects_the_inverse_relationship():
    from docodetect.corpus.triage import _pearson
    assert _pearson([0, 100, 200, 300], [-8.0, -6.0, -4.0, -2.0]) == pytest.approx(
        1.0, abs=1e-6)
    assert _pearson([0, 100, 200, 300], [-2.0, -4.0, -6.0, -8.0]) == pytest.approx(
        -1.0, abs=1e-6)


def test_pearson_is_zero_without_a_relationship():
    from docodetect.corpus.triage import _pearson
    assert _pearson([1, 2, 3], [5, 5, 5]) == 0.0


def test_pearson_handles_too_few_points():
    from docodetect.corpus.triage import _pearson
    assert _pearson([1.0], [2.0]) == 0.0
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag bestätigen**

Run: `.venv/bin/python -m pytest tests/test_corpus_triage.py -q`
Expected: FAIL mit `ModuleNotFoundError: No module named 'docodetect.corpus.triage'`

- [ ] **Step 3: triage.py implementieren**

```python
"""corpus-triage: Failures clustern und Hypothesen aufschreiben.

Erzeugt AUSSCHLIESSLICH Befunde. Keine Code-, Schwellen- oder
Baseline-Aenderung — das ist die Trennlinie, die diesen Befehl
vertrauenswuerdig macht.
"""

from __future__ import annotations

import json
import math
import sqlite3
import statistics
from datetime import datetime
from pathlib import Path

from ..matcher import MatchReport
from .manifest import Manifest

KATEGORIEN = ("segmentierungs_aenderung", "vorfilter_kill", "gate_kipp",
              "messwert_drift", "label_verdacht", "unklar")

_SEG_FELDER = {"seg_area_px", "centroid_x", "centroid_y"}


def _pearson(xs: list, ys: list) -> float:
    if len(xs) < 2:
        return 0.0
    mx, my = statistics.mean(xs), statistics.mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
    return round(num / den, 4) if den else 0.0


def categorize(failure: dict, golden) -> str:
    felder = {d["field"] for d in failure.get("diffs", [])}

    # Kill zuerst pruefen: er ist eine Aussage ueber die Kandidatenliste,
    # nicht ueber die Entscheidung (Spec 7.1).
    if golden is not None and golden.label:
        kandidaten = [c.article_number for c in golden.candidates]
        if golden.label not in kandidaten:
            if felder & {"top_k", "decision"} or not felder:
                if golden.candidates and golden.gate_passed \
                        and golden.candidates[0].posterior >= 0.95:
                    return "label_verdacht"
                return "vorfilter_kill"

    if felder & _SEG_FELDER:
        return "segmentierungs_aenderung"
    if "gate_passed" in felder:
        return "gate_kipp"
    if felder:
        return "messwert_drift"
    return "unklar"


def position_correlation(cfg: dict, root: Path, manifest: Manifest) -> dict:
    """Diskriminator-Test aus Spec 7.1: haengt der Messfehler vom Abstand
    zur Bildmitte ab?

    Je Capture: circle_diameter_mm minus Enrollment-Mittel des WAHREN
    Artikels, gegen den Schwerpunkt-Abstand zur Bildmitte. Ersetzt den
    nicht durchfuehrbaren Einlern-Shot-Vergleich (image_path ist NULL).
    """
    punkte = []
    for session in sorted({e.session for e in manifest.images}):
        db = root / session / "bundle" / "db.sqlite3"
        if not db.exists():
            continue
        mittel = {}
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            for art, sj in con.execute(
                    "SELECT article_number, stats_json FROM reference_stats"):
                m = json.loads(sj).get("scalar_mean", {}).get("diameter_mm")
                if m:
                    mittel[art] = m
        finally:
            con.close()

        for e in manifest.images:
            if e.session != session or not e.label or e.label not in mittel:
                continue
            rp = root / e.report_rel
            if not rp.exists():
                continue
            r = MatchReport.from_json(rp.read_text(encoding="utf-8"))
            d_mm = (r.measured or {}).get("circle_diameter_mm")
            if not d_mm or not r.centroid_px or not r.image_size:
                continue
            cx, cy = r.image_size[0] / 2.0, r.image_size[1] / 2.0
            dist = math.hypot(r.centroid_px[0] - cx, r.centroid_px[1] - cy)
            punkte.append({"sha": e.sha, "article": e.label, "dist": dist,
                           "delta": d_mm - mittel[e.label]})

    xs = [p["dist"] for p in punkte]
    ys = [p["delta"] for p in punkte]
    r = _pearson(xs, ys)
    if not punkte:
        deutung = "keine auswertbaren Punkte (kein Buendel-DB-Snapshot?)"
    elif abs(r) < 0.3:
        deutung = ("Ausgang B: keine Positionsabhaengigkeit. Hypothese (i) "
                   "faellt; es bleiben minAreaRect/minEnclosingCircle-Versatz "
                   "und/oder Segmentierung.")
    else:
        deutung = ("Ausgang A: Positionsabhaengigkeit bestaetigt. Der Messfehler "
                   "haengt vom Abstand zur Bildmitte ab — positionsabhaengige "
                   "Projektion blaeht die Stammdaten auf.")
    return {"n": len(punkte), "pearson_r": r, "deutung": deutung,
            "punkte": punkte}


def triage_run(cfg: dict, root: Path, run_id: str) -> Path:
    lauf = root / "runs" / run_id
    fd = lauf / "failures"
    if not fd.is_dir():
        raise FileNotFoundError(f"Lauf '{run_id}' hat keinen failures-Ordner")

    manifest = Manifest.load()
    per_sha = manifest.by_sha()
    cluster: dict = {k: [] for k in KATEGORIEN}
    for p in sorted(fd.glob("*.json")):
        fail = json.loads(p.read_text(encoding="utf-8"))
        eintrag = next((e for s, e in per_sha.items() if s.startswith(fail["sha"][:8])),
                       None)
        golden = None
        if eintrag:
            rp = root / eintrag.report_rel
            if rp.exists():
                golden = MatchReport.from_json(rp.read_text(encoding="utf-8"))
        kat = categorize(fail, golden)
        cluster[kat].append({**fail, "image_rel":
                             eintrag.image_rel if eintrag else None})

    korr = position_correlation(cfg, root, manifest)

    z = [f"# Triage-Befunde `{run_id}`", "",
         f"Erzeugt {datetime.now().isoformat(timespec='seconds')}.", "",
         "> Dieser Bericht enthaelt **nur Befunde**. Keine Code-, Schwellen- "
         "oder Baseline-Aenderung wurde vorgenommen.", "",
         "## Kategorien", ""]
    for kat in KATEGORIEN:
        eintraege = cluster[kat]
        if not eintraege:
            continue
        z.append(f"### {kat} ({len(eintraege)})")
        z.append("")
        for f in eintraege[:25]:
            felder = ", ".join(sorted({d["field"] for d in f.get("diffs", [])})) or "–"
            z.append(f"- `{f['sha'][:8]}` · {f['session']}/{f['article']} · "
                     f"Felder: {felder}"
                     + (f" · [PNG]({f['image_rel']})" if f.get("image_rel") else ""))
        if len(eintraege) > 25:
            z.append(f"- … und {len(eintraege) - 25} weitere")
        z.append("")

    z += ["## Diskriminator: Position gegen Messfehler", "",
          f"- Punkte: {korr['n']}",
          f"- Pearson r: {korr['pearson_r']}",
          f"- Deutung: {korr['deutung']}", ""]

    out = lauf / "findings.md"
    out.write_text("\n".join(z) + "\n", encoding="utf-8")
    (lauf / "position_correlation.json").write_text(
        json.dumps(korr, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out
```

- [ ] **Step 4: Tests laufen lassen, grün bestätigen**

Run: `.venv/bin/python -m pytest tests/test_corpus_triage.py -q`
Expected: PASS, 10 passed

- [ ] **Step 5: Commit**

```bash
git add docodetect/corpus/triage.py tests/test_corpus_triage.py
git commit -m "feat(corpus): corpus-triage mit Kategorien und Positions-Diskriminator"
```

---

### Task 10: Pytest-Integration mit corpus-Markern

**Files:**
- Create: `tests/test_corpus.py`
- Modify: `tests/conftest.py` (nur Marker-Registrierung ergänzen)

**Interfaces:**
- Consumes: Task 1–9

Beide Marker skippen mit klarer Meldung, wenn der Korpus lokal fehlt — Muster wie `tests/test_real_captures.py::_available`.

- [ ] **Step 1: Marker in conftest.py registrieren**

In `tests/conftest.py`, in `pytest_configure`, nach dem bestehenden `hardware`-Block:

```python
    config.addinivalue_line(
        "markers",
        "corpus: voller Lauf gegen den Regressions-Korpus – "
        "uebersprungen, solange paths.corpus_dir lokal fehlt")
    config.addinivalue_line(
        "markers",
        "corpus_smoke: festes 20-Bilder-Subset des Korpus fuer den Alltag")
```

- [ ] **Step 2: Failing test schreiben**

`tests/test_corpus.py`:

```python
"""Regressionssuite gegen den Korpus echter Aufnahmen.

Zwei Marker:
    pytest -m corpus_smoke   festes 20-Bilder-Subset (Alltag, ~40 s)
    pytest -m corpus         voller Lauf (~6 min auf dem Mac)

Beide werden uebersprungen, solange der Korpus lokal fehlt — er liegt
ausserhalb des Repos (paths.corpus_dir). Aufbau: siehe README.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.config import load_config
from docodetect.corpus.manifest import Manifest, corpus_root

SMOKE_N = 20


def _grund() -> str | None:
    """Warum der Korpus-Lauf hier nicht moeglich ist – oder None."""
    cfg = load_config()
    root = corpus_root(cfg)
    if not root.is_dir():
        return (f"Korpus fehlt ({root}). Aufbau: "
                "python -m docodetect.cli corpus-build")
    m = Manifest.load()
    if not m.images:
        return ("Manifest ist leer. Aufbau: "
                "python -m docodetect.cli corpus-build")
    return None


def _lauf(**kwargs) -> dict:
    from docodetect.corpus.runner import run_corpus
    return run_corpus(load_config(), **kwargs)


@pytest.mark.corpus_smoke
def test_corpus_smoke_subset_reproduces():
    grund = _grund()
    if grund:
        pytest.skip(grund)
    run = _lauf(tier=1, subset=SMOKE_N, workers=8)
    schlecht = [r for r in run["results"] if r["band"] != "pass"]
    assert not schlecht, (
        f"{len(schlecht)} von {run['n']} Bildern ausserhalb des "
        f"Rundungsquantums: "
        + ", ".join(f"{r['sha'][:8]}={r['band']}" for r in schlecht[:5]))


@pytest.mark.corpus
def test_corpus_tier1_full_reproduces():
    grund = _grund()
    if grund:
        pytest.skip(grund)
    run = _lauf(tier=1, workers=8)
    schlecht = [r for r in run["results"] if r["band"] != "pass"]
    assert not schlecht, (
        f"{len(schlecht)} von {run['n']} Bildern weichen ab: "
        + ", ".join(f"{r['sha'][:8]}={r['band']}" for r in schlecht[:10]))


@pytest.mark.corpus
def test_corpus_tier2_decisions_reproduce():
    grund = _grund()
    if grund:
        pytest.skip(grund)
    m = Manifest.load()
    if not any(e.tier >= 2 for e in m.images):
        pytest.skip("keine Session mit verifiziertem DB-Snapshot im Korpus")
    run = _lauf(tier=2, workers=8)
    schlecht = [r for r in run["results"] if r["band"] == "fail"]
    assert not schlecht, (
        f"{len(schlecht)} Entscheidungen weichen ab: "
        + ", ".join(f"{r['sha'][:8]}" for r in schlecht[:10]))


@pytest.mark.corpus
def test_every_manifest_entry_has_its_files():
    grund = _grund()
    if grund:
        pytest.skip(grund)
    root = corpus_root(load_config())
    fehlend = [e.sha[:8] for e in Manifest.load().images
               if not (root / e.image_rel).exists()
               or not (root / e.report_rel).exists()]
    assert not fehlend, f"Manifest verweist ins Leere: {fehlend[:10]}"
```

- [ ] **Step 3: Skip-Verhalten ohne Korpus prüfen**

Run: `.venv/bin/python -m pytest tests/test_corpus.py -m "corpus or corpus_smoke" -q -rs`
Expected: alle 4 SKIPPED mit Meldung "Korpus fehlt … corpus-build" (solange kein Korpus gebaut ist)

- [ ] **Step 4: Bestehende Suite prüfen, keine Regression**

Run: `.venv/bin/python -m pytest -q`
Expected: alle bisherigen Tests unverändert grün, die 4 corpus-Tests SKIPPED

- [ ] **Step 5: Commit**

```bash
git add tests/test_corpus.py tests/conftest.py
git commit -m "test(corpus): Marker corpus und corpus_smoke mit sauberem Skip"
```

---

### Task 11: Erstlauf, Baseline und Bericht

**Files:**
- Create: `corpus/manifest.json` (erzeugt)
- Create: `corpus/baseline.json` (erzeugt)
- Modify: `.gitignore`

Dieser Task erzeugt echte Daten und wird NICHT blind ausgeführt: die Zahlen aus jedem Schritt gehören in den Bericht an den Auftraggeber.

- [ ] **Step 1: .gitignore ergänzen**

```
# Korpus-Laufartefakte (der Korpus selbst liegt ausserhalb des Repos)
corpus/runs/
```

- [ ] **Step 2: Korpus bauen**

Run: `.venv/bin/python -m docodetect.cli corpus-build`
Expected: drei Sessions; `phase-b` und `test-2-loeffel` mit DB-Abgleich 100 % und Tier 2, `phase-a` mit Tier 1. Gesamt ~143 Bilder.

**Notieren:** Bilder je Session und Artikel, Snapshot-Abdeckung, was übersprungen wurde.

- [ ] **Step 3: Idempotenz belegen**

Run: `.venv/bin/python -m docodetect.cli corpus-build`
Expected: `0 neu`, gleiche Gesamtzahl wie in Step 2.

- [ ] **Step 4: Voller Tier-1-Lauf mit Zeitmessung**

Run: `time .venv/bin/python -m docodetect.cli corpus-run --tier 1 --run-id erstlauf-tier1`
Expected: Bericht unter `<corpus_dir>/runs/erstlauf-tier1/summary.md`

**Notieren:** Laufzeit, Bilder/s, Bandverteilung. Ziel laut Spec: 143 Bilder < 6 min. Weicht die Messung ab, gehört die echte Zahl in den Bericht — nicht die Zielzahl.

- [ ] **Step 5: Voller Tier-2-Lauf**

Run: `.venv/bin/python -m docodetect.cli corpus-run --tier 2 --run-id erstlauf-tier2`
Expected: Quoten für die Tier-2-Sessions

**Prüfen und berichten:** Reproduziert Tier 2 die damaligen Entscheidungen? Laut Spec 1.3 ist das UNGEPRÜFT. Eine Abweichung ist ein Befund — **nicht** die Baseline anpassen, sondern melden.

Gegenprobe: `accuracy_top1` für `phase-b` sollte 46/60 = 0,7667 treffen (`reports/analysis/phase-b-korrigiert/metrics.json`).

- [ ] **Step 6: Cache-Wirkung belegen**

Run: `time .venv/bin/python -m docodetect.cli corpus-run --tier 1 --changed-only --run-id cache-probe`
Expected: deutlich schneller, `neu gerechnet: 0`. Ziel laut Spec: < 30 s.

- [ ] **Step 7: Baseline erzeugen**

Run: `.venv/bin/python -m docodetect.cli corpus-run --tier 2 --run-id baseline-init --update-baseline`
Expected: `corpus/baseline.json` geschrieben

- [ ] **Step 8: --check gegen die frische Baseline**

Run: `.venv/bin/python -m docodetect.cli corpus-run --tier 2 --check --changed-only; echo "Exit: $?"`
Expected: `Exit: 0`

- [ ] **Step 9: Triage ausführen**

Run: `.venv/bin/python -m docodetect.cli corpus-triage erstlauf-tier2`
Expected: `findings.md` plus `position_correlation.json`

**Berichten:** Kategorien-Verteilung, und vor allem das Ergebnis des Positions-Diskriminators (Ausgang A oder B, mit `n` und `pearson_r`).

- [ ] **Step 10: Die zwei Härtefall-PNGs sichten**

Die Captures `1784562435798` und `1784562504239` im Korpus lokalisieren (SHA über das Manifest) und visuell prüfen:
- Ist die Stielspitze vollständig segmentiert, oder frisst der Bildrand Kontur?
- Wie liegt der Löffel relativ zur Bildmitte?

Overlay erzeugen mit `pipeline.render_report_overlay(bild, golden_report)`.

**Berichten:** Befund je Bild, im Klartext.

- [ ] **Step 11: Manifest und Baseline committen**

```bash
git add corpus/manifest.json corpus/baseline.json .gitignore
git commit -m "feat(corpus): Erstlauf – Manifest und Baseline aus dem vollen Lauf

Baseline aus <run_id>, Tier 2 ueber die Sessions mit verifiziertem
DB-Snapshot. Zahlen und Triage-Befunde siehe Bericht."
```

---

### Task 12: Dokumentation

**Files:**
- Modify: `CLAUDE.md`
- Modify: `README.md`

- [ ] **Step 1: CLAUDE.md ergänzen**

Nach dem Abschnitt „Daten & Tests" einfügen:

```markdown
## Regressions-Korpus

- **Vor jedem Merge: `corpus-run --check`.** Exit 1 = Regression. DRIFT
  bricht per Default mit — auf gepinnter Umgebung ist jede Abweichung
  code-verursacht. `--accept-drift` nur bei bewusstem Bibliotheks-Update
  oder Plattformwechsel Mac↔Windows, danach Re-Baselining mit Begründung.
- Alltag: `pytest -m corpus_smoke` (20 Bilder). Vollständig:
  `pytest -m corpus`. Beide skippen sauber ohne lokalen Korpus.
- Der Korpus liegt AUSSERHALB des Repos (`paths.corpus_dir`, Default
  `../Doco_Detect_corpus`). Versioniert sind nur `corpus/manifest.json`
  und `corpus/baseline.json`.
- **Baseline-Änderung nur über `corpus-run --update-baseline` MIT
  Begründung im Commit.** Eine Baseline, die man ohne Erklärung
  nachzieht, misst nichts mehr.
- `corpus-triage` erzeugt NUR Befunde — nie Code-, Schwellen- oder
  Baseline-Änderungen.
```

- [ ] **Step 2: README.md ergänzen**

Vor dem Abschnitt über die Auswertung einfügen:

````markdown
## Regressions-Korpus (echte Aufnahmen)

Der Korpus hält ~143 echte, bewertete Aufnahmen aus drei Sessions und
prüft jede Messpfad-Änderung dagegen. Die Original-MatchReports SIND die
Goldens: sie enthalten Label, Urteil und die damals gemessenen Werte.

### Aufbau

```bash
python -m docodetect.cli corpus-build      # idempotent, dedupliziert per SHA-256
python -m docodetect.cli corpus-run --tier 1
python -m docodetect.cli corpus-run --tier 2 --check
```

Der Korpus liegt unter `paths.corpus_dir` (Default `../Doco_Detect_corpus`),
bewusst ausserhalb des Repos — er enthält hunderte 4K-PNGs. Versioniert
sind nur `corpus/manifest.json` und `corpus/baseline.json`.

### Zwei Stufen

**Tier 1 (jedes Bild, ohne DB)** replayt Segmentierung und Merkmale gegen
den Golden desselben Bildes. Der aktuelle Code reproduziert die
Messwerte bit-exakt, deshalb liegt die PASS-Schwelle beim
Rundungsquantum (Ø ±0,005 mm, Rundheit/Solidity ±0,00005).

**Tier 2 (nur mit verifiziertem DB-Snapshot)** replayt die komplette
Pipeline und vergleicht Entscheidung, Top-k-Reihenfolge und Gate exakt;
`llr_margin` und `max_z_winner` laufen über dieselbe Drei-Band-Logik.

Bänder: **PASS** (≤ Quantum) · **DRIFT** (≤ weiche Stufe) · **FAIL**.
`--check` bricht per Default bei DRIFT *und* FAIL.

### Sync Mac ↔ Windows

Der Korpus zieht als Ordner um; alle Manifest-Pfade sind relativ.

1. `<corpus_dir>` auf den Zielrechner kopieren (rsync, Stick, Netzlaufwerk)
2. dort in `config/config.local.yaml`:
   ```yaml
   paths:
     corpus_dir: D:/Doco_Detect_corpus
   ```
3. `python -m docodetect.cli corpus-run --tier 1` — das Manifest kommt aus git

Der erste Lauf auf Windows wird mit hoher Wahrscheinlichkeit DRIFT
melden (andere OpenCV-Build-Optionen). Das ist der dokumentierte Fall für
`--accept-drift` plus anschliessendes Re-Baselining auf dieser Plattform.

### Baseline-Regel

`corpus/baseline.json` ändert sich NUR über
`corpus-run --update-baseline`, und der Commit muss begründen, warum die
alten Zahlen nicht mehr gelten. Ohne diese Regel misst die Baseline
irgendwann nur noch den Status quo.

### Laufzeit (gemessen auf dem MacBook, 10 Kerne)

| Lauf | Dauer |
|---|---|
| Voller Korpus (143 Bilder, Tier 1) | ~5 min |
| `--changed-only` ohne Änderung | < 30 s |
| `pytest -m corpus_smoke` (20 Bilder) | ~40 s |

Die Segmentierung kostet 2,83 s je 4K-Bild und ist
speicherbandbreiten-gebunden: acht Worker bringen Faktor 1,5, mehr
bringt nichts. 1000 Bilder wären ~32 min.
````

- [ ] **Step 3: Kompletter Testlauf**

Run: `.venv/bin/python -m pytest -q`
Expected: alles grün; corpus-Tests laufen oder skippen sauber

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "docs(corpus): Merge-Regel in CLAUDE.md, Aufbau und Sync im README"
```

---

### ZWISCHENSTOPP nach Task 11 — Pflicht

**Task 12 darf NICHT beginnen, bevor der Erstlauf-Bericht vorgelegt und
abgenommen ist.** Vorzulegen sind die vier Befunde aus Task 11:

1. **Tier-2-Reproduktion** — reproduziert der Replay die damaligen
   Entscheidungen? Laut Spec 1.3 ungeprüft. Gegenprobe: `accuracy_top1`
   für `phase-b` gegen 46/60 = 0,7667 aus
   `reports/analysis/phase-b-korrigiert/metrics.json`.
2. **Diskriminator-Test** — `n` und `pearson_r` aus
   `position_correlation.json`, plus Ausgang A oder B.
3. **PNG-Sichtung** der zwei Härtefälle `1784562435798` und
   `1784562504239`: Stielspitze vollständig segmentiert? Lage zur Bildmitte?
4. **Laufzeitmessung** — gemessene Sekunden und Bilder/s, nicht die Zielzahl.

Dazu die Korpus-Statistik (Bilder je Session und Artikel,
Snapshot-Abdeckung) und die Baseline-Werte.

---

### Task 13: Übergabebericht

**Files:**
- Create: `docs/superpowers/reports/2026-07-20-corpus-harness-abschluss.md`

**Adressat:** eine Claude-Sitzung **ohne jeden Vorkontext**. Keine Verweise
auf „das Besprochene", alle Pfade ausgeschrieben, jeder Fachbegriff (Kill,
Drei-Band, Bündel, Tier 1/2) in je einem Halbsatz definiert.

- [ ] **Step 1: Bericht mit genau vier Abschnitten schreiben**

**1. PLAN WAR** — Auftrag und die zwölf Tasks in wenigen Sätzen.

**2. GEÄNDERT WURDE** — vollständig: neue und geänderte Dateien/Module, die
vier CLI-Befehle mit je einem Erklärsatz, neue Config-Keys, Branch und
Commits. Ausdrücklich auch, was **nicht** angefasst wurde: Messpfad
(`pipeline.py`, `segmentation.py`, `features.py`, `matcher.py`), die echte
`doco_detect.sqlite3`, Schwellen und Gewichte.

**3. ABWEICHUNGEN VOM PLAN** — jede einzeln mit Begründung. Mindestens die
drei bereits bekannten:
- die vier `corpus-*`-Befehle hängen in `docodetect/cli.py` statt in einem
  paket-eigenen CLI-Einstieg
- `report.py` und `diff.py` kamen als Module dazu
- `run_one` legt Replay-Reports unter `runs/_replay/` ab (in der
  Plan-Selbstprüfung gefunden)

Plus alles, was während der Umsetzung dazukam.

**4. ZIEL ERREICHT?** — ehrliche Bewertung gegen Messbares: Testlauf-Zahlen,
gemessene Laufzeit samt Hochrechnung auf 1000 Bilder, Baseline-Werte,
Tier-2-Reproduktionsbefund, Triage-Ergebnis. Danach offene Punkte als Liste.

Wo etwas nicht erreicht wurde, steht das als Nicht-Erreicht da — nicht als
weichgespülter Teilerfolg.

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/reports/
git commit -m "docs(corpus): Uebergabebericht zum Regressions-Harness"
```

---

## Selbstprüfung des Plans

**Spec-Abdeckung:**

| Spec-Abschnitt | Task |
|---|---|
| 1 Bestandsaufnahme | bereits erledigt (in der Spec dokumentiert) |
| 2 Ablage, Config, DB-Snapshots | 1, 2, 4 |
| 3 Tier 1, drei Bänder | 3, 5 |
| 4 Tier 2, Vergleichslogik | 3, 5 |
| 5 Runner, Cache, Filter, Ausgabe | 5, 6, 7 |
| 5.1 Performance | 7 (`--workers 8`), 11 (Messung), 12 (Doku) |
| 6 Baseline | 6, 7, 11 |
| 7 Diff und Triage | 8, 9 |
| 7.1 Kills, Diskriminator, Randlagen | 9 (`categorize`, `position_correlation`), 11 (PNG-Sichtung) |
| 8 Tests, Marker | 10 |
| 9 Modulaufbau | 1–9 |
| 10 Invarianten | Global Constraints |
| 11 Aufgeschoben | nicht Teil dieses Plans |

**Abweichung vom Spec-Modulaufbau:** Die Spec nennt `cli.py` im Paket. Der
Plan hängt die vier Befehle stattdessen direkt in `docodetect/cli.py` ein —
so wie alle 16 bestehenden Befehle. Ein zweiter CLI-Einstieg im Paket wäre
ein abweichendes Muster ohne Gewinn. Dafür kam `report.py` und `diff.py`
als eigene Module dazu.

**Typ-Konsistenz geprüft:** `ImageEntry`-Felder identisch in Task 1/4/5;
`FieldDiff` in Task 3 definiert, in 5/6/9 gelesen; `band`-Werte durchgängig
die Konstanten aus `compare.py`; `run_corpus`-Rückgabeschlüssel in Task 5
definiert, in 6/7 gelesen; `corpus_root(cfg)` überall gleich aufgerufen.

**In der Selbstprüfung gefunden und behoben:** `cmd_corpus_run` (Task 7) liest
die Tier-2-Quoten aus `runs/_replay/<sha8>.json`. Diese Dateien schrieb
zunächst niemand — der Replay-Report existiert nur im Worker-Prozess, weil
`captures_dir` im Bündel bewusst `None` ist. Task 5 Step 3 legt ihn jetzt
explizit ab (rein additiv in `runner.py`, kein Eingriff in den Messpfad).
Ohne diese Ergänzung wäre die Baseline ohne Quoten geblieben.

**Ein Verhalten, das der Umsetzer kennen muss:** `--changed-only` liefert
Ergebnisse aus dem Cache, ohne `runs/_replay/` neu zu füllen. Für Tier 2
heisst das: ein reiner Cache-Treffer-Lauf hat keine frischen Quoten. Das ist
richtig so — die Quoten des letzten echten Laufs stehen in dessen
`metrics.json`, und `--check` prüft bei unverändertem Fingerprint ohnehin
nichts Neues. Wer Quoten erzwingen will, lässt `--changed-only` weg.
