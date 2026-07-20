# Mehrkandidaten-Entscheidungspfad (beide UIs) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die bestehende Dreiwege-Entscheidung (accept/ambiguous/reject) in beiden UIs vollständig sichtbar machen: zentrale Format-Helfer, Teilscore-Anzeige, „Keiner davon"-Korrekturpfad, knappe Demo-Szenarien und Schwellen-Randfall-Tests.

**Architecture:** Matcher bleibt logisch unverändert (nur additives Feld `margin_to_next` + Umzug von `channel_scores` aus analysis.py). Neues UI-freies Modul `docodetect/display.py` liefert alle Anzeige-Strings/Prozente; `pipeline.py` re-exportiert sie (UI-Regel: UIs importieren nur pipeline). Qt- und Streamlit-UI rendern dieselben Helfer.

**Tech Stack:** Python 3.9 (venv `.venv/bin/python`), pytest, PySide6 (offscreen-Tests), Streamlit, OpenCV/NumPy. Keine neuen Abhängigkeiten.

**Spec:** `docs/superpowers/specs/2026-07-20-multi-candidate-decision-ui-design.md`

## Global Constraints

- Wire-Namen bleiben exakt `"accept"` / `"ambiguous"` / `"reject"` (`MatchReport.decision`); Anzeige-Begriffe AUTO_ACCEPT/CONFIRM/NO_MATCH existieren NUR in der Anzeige.
- Keine Änderung an Schwellen/Toleranzen/Scoring-Formeln in `config/config.yaml` oder `matcher.py`.
- Alle Schwellen in Tests aus `load_config()` — niemals Zahlen duplizieren.
- UIs importieren ausschließlich `docodetect.pipeline` (+ Qt/cv2 fürs Rendern).
- Python 3.9: jede neue Datei beginnt mit `from __future__ import annotations`; keine `X | Y`-Typen zur Laufzeit (nur in Annotationen).
- Deutsch mit Dezimalkomma in allen Anzeige-Strings.
- Nach JEDEM Task: `.venv/bin/python -m pytest tests/ -q` grün; am Ende zusätzlich `evaluate data/testset-smoke` == 11/14 mit denselben drei Abweichungen (Baseline-Schutz).
- Tests dürfen NIE nach `data/captures/` schreiben (cfg-Fixture ohne `captures_dir`).
- Alle Test-/Pythonläufe mit `.venv/bin/python` (System-`python` existiert nicht).

---

### Task 1: Matcher — `margin_to_next` + Umzug `channel_scores`

**Files:**
- Modify: `docodetect/matcher.py`
- Modify: `docodetect/analysis.py` (nur Import statt Definition)
- Test: `tests/test_matching_decisions.py` (neu, wird hier begonnen)

**Interfaces:**
- Produces: `CandidateReport.margin_to_next: float | None` (eigener log_score − nächstplatzierter; letzter/einziger: None). `matcher.CHANNELS: dict`, `matcher.channel_scores(candidate) -> dict` (unverändertes Verhalten, neuer Wohnort). `analysis.CHANNELS`/`analysis.channel_scores` bleiben importierbar (Re-Export).

- [ ] **Step 1: Failing Tests schreiben** — neue Datei `tests/test_matching_decisions.py`:

```python
"""Entscheidungs- und Randfall-Tests gegen den ECHTEN Matcher mit den
ECHTEN Schwellen aus config/config.yaml (Fixture, nie duplizieren).
Synthetische Feature-Vektoren, keine Kamera. Spec:
docs/superpowers/specs/2026-07-20-multi-candidate-decision-ui-design.md
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.calibration import Calibration  # noqa: E402
from docodetect.config import load_config  # noqa: E402
from docodetect.database import Article, Database  # noqa: E402
from docodetect.features import Features  # noqa: E402
from docodetect.matcher import match  # noqa: E402


@pytest.fixture()
def cfg(tmp_path):
    """Echte config.yaml (Schwellen NIE duplizieren); DB nach tmp,
    KEIN captures_dir -> identify/match schreiben nie nach data/."""
    c = load_config()
    c["paths"] = {"db_file": str(tmp_path / "t.sqlite3")}
    return c


@pytest.fixture()
def cal(cfg):
    return Calibration(mm_per_px=0.2,
                       camera_height_mm=float(cfg["geometry"]["camera_height_mm"]),
                       image_width=1920, image_height=1080,
                       marker_size_mm=50.0, created_unix=0.0)


def fake(d=200.0, lab=(95.0, 0.0, 0.0), peak=0):
    """Voller Feature-Satz (Zonen + Solidity), damit Kandidaten MIT
    Referenzen über alle Merkmale gescort werden."""
    def hist(p):
        h = [0.0] * 128
        h[p] = 1.0
        return h
    return Features(
        equiv_diameter_mm=d, circle_diameter_mm=d,
        area_mm2=3.14159 * (d / 2) ** 2, perimeter_mm=3.14159 * d,
        circularity=0.90, aspect_ratio=1.0,
        mean_hsv=[0.0, 0.0, 200.0], hue_hist=[1.0 / 32] * 32,
        mean_saturation=0.0,
        hu_moments=[3.2, 8.0, 10.0, 10.0, 10.0, 10.0, 10.0],
        solidity=0.95, lab_center=list(lab), lab_rim=list(lab),
        hs_hist_center=hist(peak), hs_hist_rim=hist(peak))


def make_db(cfg, articles):
    """articles: Liste (nr, diameter_mm, height_mm, [ref-Features])."""
    db = Database(cfg)
    db.init_schema()
    for nr, d, h, refs in articles:
        db.create_article(Article(article_number=nr, name=nr, category=None,
                                  diameter_mm=d, width_mm=None, depth_mm=None,
                                  height_mm=h, color_desc=None, notes=None))
        for f in refs:
            db.add_reference(nr, f)
    return db


# ---------- Task 1: margin_to_next ----------

def test_margin_to_next_ranked(cfg, cal, tmp_path):
    """Drei Kandidaten: Platz 1 tragt margin zum Zweiten (== llr_margin),
    der letzte None."""
    db = make_db(cfg, [
        ("A", 200.0, 0.0, [fake(200.0)] * 2),
        ("B", 200.0, 0.0, [fake(201.5)] * 2),
        ("C", 200.0, 0.0, [fake(203.0)] * 2),
    ])
    try:
        rep = match(fake(200.0), db, cal, cfg)
        assert len(rep.candidates) == 3
        c0, c1, c2 = rep.candidates
        assert c0.margin_to_next == pytest.approx(c0.log_score - c1.log_score)
        assert c0.margin_to_next == pytest.approx(rep.llr_margin)
        assert c1.margin_to_next == pytest.approx(c1.log_score - c2.log_score)
        assert c2.margin_to_next is None
    finally:
        db.close()


def test_margin_to_next_single_candidate_is_none(cfg, cal, tmp_path):
    db = make_db(cfg, [("A", 200.0, 0.0, [fake(200.0)] * 2)])
    try:
        rep = match(fake(200.0), db, cal, cfg)
        assert rep.candidates[0].margin_to_next is None
    finally:
        db.close()


def test_old_report_json_without_margin_field_loads(cfg, cal, tmp_path):
    """Rueckwaertskompatibilitaet: Alt-JSONs ohne margin_to_next laden."""
    from docodetect.matcher import MatchReport
    db = make_db(cfg, [("A", 200.0, 0.0, [fake(200.0)] * 2)])
    try:
        d = match(fake(200.0), db, cal, cfg).to_dict()
        for c in d["candidates"]:
            c.pop("margin_to_next")
        rep = MatchReport.from_dict(d)
        assert rep.candidates[0].margin_to_next is None
    finally:
        db.close()
```

- [ ] **Step 2: Fehlschlag verifizieren**

Run: `.venv/bin/python -m pytest tests/test_matching_decisions.py -q`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'margin_to_next'` bzw. AttributeError (Feld existiert noch nicht).

- [ ] **Step 3: `matcher.py` erweitern** — drei Änderungen:

(a) In der Dataclass `CandidateReport` (nach `max_abs_z: float = 0.0`) ergänzen:

```python
    margin_to_next: float | None = None   # log_score-Abstand zum Naechstplatzierten
```

(b) In `match()` DIREKT NACH `candidates.sort(key=lambda c: c.log_score, reverse=True)` einfügen:

```python
    for i, c in enumerate(candidates):
        c.margin_to_next = (round(c.log_score - candidates[i + 1].log_score, 4)
                            if i + 1 < len(candidates) else None)
```

(c) Umzug `channel_scores`: In `docodetect/analysis.py` die Definitionen von `CHANNELS` (dict Kanal→Merkmalsliste) und `def channel_scores(...)` **ausschneiden** (verbatim, NICHT neu tippen) und in `matcher.py` direkt unter der Dataclass `FeatureScore` einfügen. In `analysis.py` an derselben Stelle ersetzen durch:

```python
from .matcher import CHANNELS, channel_scores  # noqa: F401  (Wohnort jetzt matcher.py)
```

Achtung: `analysis.py` importiert bereits aus `.matcher` — die neue Import-Zeile mit dem bestehenden `from .matcher import ...`-Import zusammenführen.

- [ ] **Step 4: Tests grün verifizieren (inkl. Regression)**

Run: `.venv/bin/python -m pytest tests/test_matching_decisions.py tests/test_analysis.py tests/test_scoring.py -q`
Expected: PASS (test_analysis nutzt `channel_scores` weiter über analysis — Re-Export).

- [ ] **Step 5: Commit**

```bash
git add docodetect/matcher.py docodetect/analysis.py tests/test_matching_decisions.py
git commit -m "matcher: margin_to_next pro Kandidat; channel_scores zieht von analysis nach matcher um (Re-Export bleibt)"
```

---

### Task 2: `docodetect/display.py` — zentrale Anzeige-Helfer

**Files:**
- Create: `docodetect/display.py`
- Modify: `docodetect/pipeline.py` (Re-Export)
- Test: `tests/test_display.py` (neu)

**Interfaces:**
- Consumes: `matcher.CandidateReport` (Felder `corrected_diameter_mm`, `height_mm`, `geometry_error_mm`, `name`, `posterior`, `features`), `matcher.CHANNELS`.
- Produces (exakte Signaturen, von Task 4-6 benutzt):
  - `format_diameter(c: CandidateReport) -> str`
  - `format_delta(c: CandidateReport, cfg: dict) -> str`
  - `format_rank_line(c: CandidateReport, rank: int) -> str`
  - `channel_percentages(c: CandidateReport) -> dict`  (Keys `geometry`/`color`/`shape`, Werte `float 0..1` oder `None`)
  - `headline(decision: str, best_name: str | None = None) -> tuple`  ((Text, Statusklasse) mit Statusklasse ∈ {"accept","confirm","reject"})
  - Alle via `from docodetect.pipeline import ...` erreichbar.

- [ ] **Step 1: Failing Tests** — neue Datei `tests/test_display.py`:

```python
"""Tests der zentralen Anzeige-Helfer (docodetect/display.py) — beide UIs
nutzen exakt diese Strings; Format hier festgeschrieben (Dezimalkomma)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.matcher import CandidateReport, FeatureScore  # noqa: E402
from docodetect.pipeline import (channel_percentages, format_delta,  # noqa: E402
                                 format_diameter, format_rank_line, headline)


def cand(corrected=141.0, h=60.0, err=2.4, posterior=0.61, name="Teller 20",
         features=None):
    return CandidateReport(
        article_number="X", name=name, nominal_size_mm=140.0, height_mm=h,
        corrected_diameter_mm=corrected, geometry_error_mm=err,
        has_references=True, n_shots=3, features=features or [],
        log_score=0.0, posterior=posterior, max_abs_z=0.0)


def fs(feature, weighted):
    return FeatureScore(feature=feature, measured=None, reference=None,
                        distance=0.0, sigma_enroll=0.0, sigma_eff=1.0,
                        z=0.0, log_contrib=weighted, w_eff=0.1,
                        weighted=weighted)


CFG = {"matching": {"diameter_tolerance_mm": 6.0}}


def test_format_diameter_with_height():
    assert format_diameter(cand()) == "Ø 141,0 mm (höhenkorrigiert, h = 60 mm)"


def test_format_diameter_floor_plane():
    assert format_diameter(cand(corrected=180.0, h=0.0)) == "Ø 180,0 mm (Bodenebene)"


def test_format_delta():
    assert format_delta(cand(), CFG) == "Δ 2,4 mm von ±6,0"


def test_format_rank_line():
    assert format_rank_line(cand(), 2) == "2. Teller 20 · 61 %"


def test_headline_mapping():
    assert headline("accept", "Teller 20") == ("✓ Automatisch übernommen: Teller 20", "accept")
    assert headline("accept") == ("✓ Automatisch übernommen", "accept")
    assert headline("ambiguous") == ("Bitte bestätigen", "confirm")
    assert headline("reject") == ("Kein Treffer", "reject")


def test_channel_percentages_perfect_match_is_one():
    c = cand(features=[fs("diameter_mm", 0.0), fs("delta_e_center", 0.0),
                       fs("hu_log", 0.0)])
    pct = channel_percentages(c)
    assert pct["geometry"] == pytest.approx(1.0)
    assert pct["color"] == pytest.approx(1.0)
    assert pct["shape"] == pytest.approx(1.0)


def test_channel_percentages_geometry_only_has_none_channels():
    """Geometry-only-Kandidat: Farbe/Form ohne Merkmale -> None (UI graut
    die Balken aus, statt faelschlich 100 % zu zeigen)."""
    c = cand(features=[fs("diameter_mm", -0.5)])
    pct = channel_percentages(c)
    assert 0.0 < pct["geometry"] < 1.0
    assert pct["color"] is None and pct["shape"] is None
```

- [ ] **Step 2: Fehlschlag verifizieren**

Run: `.venv/bin/python -m pytest tests/test_display.py -q`
Expected: FAIL — `ImportError: cannot import name 'channel_percentages' from 'docodetect.pipeline'`.

- [ ] **Step 3: `docodetect/display.py` anlegen** (komplett):

```python
"""Zentrale Anzeige-Helfer für ALLE UIs (Qt + Streamlit).

Eine Implementierung pro String — beide UIs zeigen exakt dieselben Texte
(deutsch, Dezimalkomma). UI-Code importiert diese Funktionen über
docodetect.pipeline (Re-Export), nie direkt Untermodule.

Anzeige-Mapping (Wire-Namen bleiben unangetastet, siehe Spec 2026-07-20):
accept -> "Automatisch übernommen", ambiguous -> "Bitte bestätigen",
reject -> "Kein Treffer".
"""

from __future__ import annotations

import math

from .matcher import CHANNELS, CandidateReport


def _de(x: float, nd: int = 1) -> str:
    """Zahl deutsch formatieren (Dezimalkomma)."""
    return f"{x:.{nd}f}".replace(".", ",")


def format_diameter(c: CandidateReport) -> str:
    """Kandidatenspezifischer mm-Wert — NIE ein globaler 'gemessener' Wert:
    derselbe Pixelkreis ergibt je Kandidat (Höhe!) einen anderen Ø."""
    if c.height_mm:
        return (f"Ø {_de(c.corrected_diameter_mm)} mm "
                f"(höhenkorrigiert, h = {_de(c.height_mm, 0)} mm)")
    return f"Ø {_de(c.corrected_diameter_mm)} mm (Bodenebene)"


def format_delta(c: CandidateReport, cfg: dict) -> str:
    tol = float(cfg["matching"]["diameter_tolerance_mm"])
    return f"Δ {_de(c.geometry_error_mm)} mm von ±{_de(tol)}"


def format_rank_line(c: CandidateReport, rank: int) -> str:
    return f"{rank}. {c.name} · {c.posterior * 100:.0f} %"


def channel_percentages(c: CandidateReport) -> dict:
    """Teilscore je Kanal als exp(Summe gewichteter Log-Beiträge) in (0,1]
    (1,0 = perfekte Übereinstimmung — ehrliche Likelihood-Darstellung).
    Kanäle ohne Merkmale (z. B. geometry-only-Kandidat) -> None, damit die
    UI ausgraut statt fälschlich 100 % zu zeigen."""
    by_feature = {f.feature: f.weighted for f in c.features}
    out = {}
    for ch, feats in CHANNELS.items():
        present = [by_feature[f] for f in feats if f in by_feature]
        out[ch] = math.exp(sum(present)) if present else None
    return out


def headline(decision: str, best_name: str | None = None) -> tuple:
    """(Text, Statusklasse) für die Ergebnis-Überschrift beider UIs.
    Statusklasse: accept | confirm | reject (Farbsteuerung)."""
    if decision == "accept":
        text = ("✓ Automatisch übernommen" if not best_name
                else f"✓ Automatisch übernommen: {best_name}")
        return (text, "accept")
    if decision == "ambiguous":
        return ("Bitte bestätigen", "confirm")
    return ("Kein Treffer", "reject")
```

- [ ] **Step 4: Re-Export in `pipeline.py`** — bei den bestehenden Imports ergänzen:

```python
from .display import (channel_percentages, format_delta, format_diameter,  # noqa: F401
                      format_rank_line, headline)
```

Kommentar dahinter: `# Re-Export: UIs importieren Anzeige-Helfer NUR über pipeline`.

- [ ] **Step 5: Tests grün**

Run: `.venv/bin/python -m pytest tests/test_display.py -q`
Expected: PASS (8 Tests).

- [ ] **Step 6: Commit**

```bash
git add docodetect/display.py docodetect/pipeline.py tests/test_display.py
git commit -m "display.py: zentrale Anzeige-Helfer (Ø/Δ/Rang/Teilscores/Headline), Re-Export via pipeline"
```

---

### Task 3: Entscheidungs- und Schwellen-Randfall-Tests

**Files:**
- Modify: `tests/test_matching_decisions.py` (Fälle ergänzen)

**Interfaces:**
- Consumes: Fixtures/Helper aus Task 1 (`cfg`, `cal`, `fake`, `make_db`).
- Produces: Festgeschriebenes Schwellenverhalten (`<=` beim z-Gate, `>=` beim LLR-Margin) als Regressionsnetz — keine neuen Runtime-Symbole.

Diese Tests pinnen EXISTIERENDES Verhalten (kein Rot-Grün-Zyklus; sie
müssen sofort grün sein — ist einer rot, ist das ein echter Befund: STOPP
und melden, nicht die Erwartung anpassen).

- [ ] **Step 1: Fälle anhängen** an `tests/test_matching_decisions.py`:

```python
# ---------- Entscheidungsregeln mit echten Schwellen ----------

def test_auto_accept_clear_winner(cfg, cal, tmp_path):
    db = make_db(cfg, [("A", 200.0, 0.0, [fake(200.0)] * 3)])
    try:
        rep = match(fake(200.0), db, cal, cfg)
        assert rep.decision == "accept" and rep.gate_passed
    finally:
        db.close()


def test_confirm_wegen_margin(cfg, cal, tmp_path):
    """Zwei fast identische Artikel: Gate ok, Margin unter Schwelle."""
    db = make_db(cfg, [("A", 200.0, 0.0, [fake(200.0)] * 2),
                       ("B", 200.0, 0.0, [fake(200.5)] * 2)])
    try:
        rep = match(fake(200.2), db, cal, cfg)
        assert rep.decision == "ambiguous" and rep.gate_passed
        assert rep.llr_margin < float(cfg["matching"]["min_llr_margin"])
    finally:
        db.close()


def test_confirm_ohne_referenzen(cfg, cal, tmp_path):
    """Geometry-only-Sieger kann NIE accept werden."""
    db = make_db(cfg, [("A", 200.0, 0.0, [])])
    try:
        rep = match(fake(200.0), db, cal, cfg)
        assert rep.decision == "ambiguous"
        assert not rep.candidates[0].has_references
    finally:
        db.close()


def test_no_match_gate_bei_fremder_farbe(cfg, cal, tmp_path):
    """Ø passt, Farbe völlig fremd -> max|z| über Gate -> reject
    ('score zu niedrig' ist in der Statistik-Semantik NO_MATCH,
    nicht CONFIRM — Spec-Entscheidung 3)."""
    db = make_db(cfg, [("A", 200.0, 0.0, [fake(200.0, lab=(95.0, 0.0, 0.0))] * 2)])
    try:
        rep = match(fake(200.0, lab=(20.0, 30.0, 30.0)), db, cal, cfg)
        assert rep.decision == "reject" and not rep.gate_passed
        assert rep.max_z_winner > float(cfg["matching"]["max_z_accept"])
    finally:
        db.close()


def test_no_match_leerer_vorfilter(cfg, cal, tmp_path):
    db = make_db(cfg, [("A", 300.0, 0.0, [])])
    try:
        rep = match(fake(200.0), db, cal, cfg)
        assert rep.decision == "reject" and rep.candidates == []
    finally:
        db.close()


# ---------- Randfälle EXAKT auf der Schwelle ----------

def test_gate_boundary_z_exakt_gleich_schwelle_akzeptiert(cfg, cal, tmp_path):
    """max|z| == max_z_accept MUSS bestehen (<=, nicht <). Konstruktion:
    sigma_enroll=0 (identische Shots) -> sigma_eff == sigma_floor; Distanz
    = z * floor exakt. 3.5 * 1.5 = 5.25 mm <= 6 mm Toleranz (Vorfilter ok).
    Binaer exakt: 5.25/1.5 == 3.5."""
    zmax = float(cfg["matching"]["max_z_accept"])
    floor = float(cfg["matching"]["sigma_floors"]["diameter_mm"])
    d_ref = 200.0
    d_meas = d_ref + zmax * floor
    assert d_meas - d_ref <= float(cfg["matching"]["diameter_tolerance_mm"])
    db = make_db(cfg, [("A", d_ref, 0.0, [fake(d_ref)] * 2)])
    try:
        rep = match(fake(d_meas), db, cal, cfg)
        assert rep.max_z_winner == pytest.approx(zmax)
        assert rep.gate_passed and rep.decision == "accept"
    finally:
        db.close()


def test_gate_boundary_knapp_darueber_rejected(cfg, cal, tmp_path):
    zmax = float(cfg["matching"]["max_z_accept"])
    floor = float(cfg["matching"]["sigma_floors"]["diameter_mm"])
    d_ref = 200.0
    d_meas = d_ref + (zmax + 0.01) * floor
    db = make_db(cfg, [("A", d_ref, 0.0, [fake(d_ref)] * 2)])
    try:
        rep = match(fake(d_meas), db, cal, cfg)
        assert not rep.gate_passed and rep.decision == "reject"
    finally:
        db.close()


def test_margin_boundary_exakt_gleich_schwelle_akzeptiert(cfg, cal, tmp_path):
    """LLR-Margin == min_llr_margin MUSS accepten (>=). Konstruktion:
    Sieger A mit Referenzen, alle z == 0 -> log_score 0. B OHNE Referenzen
    (geometry-only): einziges Merkmal ist der Ø, dessen weighted == logL
    (wsum-Renormierung auf EIN Merkmal) -> llr == 0.5 * z_B^2 EXAKT.
    z_B = 2 -> llr = 2.0 == min_llr_margin (Config-Default)."""
    min_llr = float(cfg["matching"]["min_llr_margin"])
    floor = float(cfg["matching"]["sigma_floors"]["diameter_mm"])
    z_b = (2.0 * min_llr) ** 0.5
    geo_err_b = z_b * floor          # 3.0 mm bei Default-Config
    assert geo_err_b <= float(cfg["matching"]["diameter_tolerance_mm"])
    db = make_db(cfg, [("A", 200.0, 0.0, [fake(200.0)] * 2),
                       ("B", 200.0 - geo_err_b, 0.0, [])])
    try:
        rep = match(fake(200.0), db, cal, cfg)
        assert rep.candidates[0].article_number == "A"
        assert rep.llr_margin == pytest.approx(min_llr, abs=1e-3)
        assert rep.decision == "accept"
    finally:
        db.close()


def test_margin_boundary_knapp_darunter_confirm(cfg, cal, tmp_path):
    min_llr = float(cfg["matching"]["min_llr_margin"])
    floor = float(cfg["matching"]["sigma_floors"]["diameter_mm"])
    geo_err_b = ((2.0 * min_llr) ** 0.5 - 0.1) * floor   # llr < Schwelle
    db = make_db(cfg, [("A", 200.0, 0.0, [fake(200.0)] * 2),
                       ("B", 200.0 - geo_err_b, 0.0, [])])
    try:
        rep = match(fake(200.0), db, cal, cfg)
        assert rep.llr_margin < min_llr
        assert rep.decision == "ambiguous"
    finally:
        db.close()


# ---------- Höhenkompensation kandidatenspezifisch ----------

def test_hoehenkorrektur_pro_kandidat_formel(cfg, cal, tmp_path):
    """Gleicher Pixelkreis, zwei Kandidaten mit h=0 und h=60: der
    korrigierte mm-Wert MUSS pro Kandidat der Formel
    true = measured * (Z - h) / Z entsprechen (Z aus config)."""
    z_cam = float(cfg["geometry"]["camera_height_mm"])
    measured = 175.0
    db = make_db(cfg, [
        ("FLACH", measured, 0.0, []),                                # h=0
        ("SCHUESSEL", measured * (z_cam - 60.0) / z_cam, 60.0, []),  # h=60
    ])
    try:
        rep = match(fake(measured), db, cal, cfg)
        by = {c.article_number: c for c in rep.candidates}
        assert set(by) == {"FLACH", "SCHUESSEL"}
        assert by["FLACH"].corrected_diameter_mm == pytest.approx(measured)
        assert by["SCHUESSEL"].corrected_diameter_mm == pytest.approx(
            measured * (z_cam - 60.0) / z_cam)
        assert (by["FLACH"].corrected_diameter_mm
                != by["SCHUESSEL"].corrected_diameter_mm)
    finally:
        db.close()


# ---------- border_clipped bleibt Fehlerpfad ----------

def test_border_clipped_erzeugt_kein_match_ergebnis(cfg, cal, tmp_path):
    """identify() mit angeschnittenem Objekt -> reject ohne Kandidaten
    (kein Match-Ergebnis, keine Messwert-Luege)."""
    import cv2
    import numpy as np
    from docodetect.database import Database as _DB
    from docodetect.pipeline import Pipeline

    bg = np.full((1080, 1920, 3), 200, dtype=np.uint8)
    noise = np.random.default_rng(42).integers(-5, 5, bg.shape, dtype=np.int16)
    bg = np.clip(bg.astype(np.int16) + noise, 0, 255).astype(np.uint8)

    pipe = Pipeline.__new__(Pipeline)
    pipe.cfg, pipe.cal, pipe.background = cfg, cal, bg
    pipe.db = _DB(cfg)
    pipe.db.init_schema()
    try:
        img = bg.copy()
        cv2.circle(img, (30, 540), 500, (250, 250, 250), -1)  # ragt links raus
        out = pipe.identify(img)
        assert out.report.decision == "reject"
        assert out.report.candidates == []
        assert out.report.touches_border is True
    finally:
        pipe.db.close()
```

- [ ] **Step 2: Grün verifizieren (Pinning-Tests)**

Run: `.venv/bin/python -m pytest tests/test_matching_decisions.py -q`
Expected: PASS (alle; bei Rot: STOPP — Befund melden, Erwartung NICHT anpassen).

- [ ] **Step 3: Commit**

```bash
git add tests/test_matching_decisions.py
git commit -m "tests: Entscheidungsregeln + exakte Schwellen-Randfaelle (z-Gate <=, LLR >=), Hoehenformel, border_clipped"
```

---

### Task 4: Qt ResultCard — Helfer-Strings + Teilscore-Balken + neutrale Rahmen

**Files:**
- Modify: `docodetect/ui_qt/widgets/result_card.py`
- Test: `tests/test_ui_qt_smoke.py` (bestehende Karten-Tests anpassen/ergänzen)

**Interfaces:**
- Consumes: `pipeline.format_diameter/format_delta/channel_percentages` (Task 2), `CandidateReport`.
- Produces: `ResultCard(candidate, cfg, clickable: bool = False)` — Konstruktor nimmt jetzt `cfg` (für `format_delta`). Bestehendes Signal `clicked(str)` bleibt.

Hinweis für den Umsetzer: ERST die aktuelle Datei lesen
(`docodetect/ui_qt/widgets/result_card.py`) — sie existiert mit Signal
`clicked = Signal(str)` und posterior-Balken. Die folgenden Blöcke
integrieren, vorhandene Ø-/Δ-Formatierung durch die Helfer ERSETZEN
(keine Doppel-Formatierung stehen lassen).

- [ ] **Step 1: Smoke-Test ergänzen** in `tests/test_ui_qt_smoke.py` (Muster der vorhandenen Offscreen-Tests der Datei übernehmen — `qapp`-Fixture existiert dort):

```python
def test_result_card_shows_helper_strings_and_channel_bars(qapp):
    from docodetect.matcher import CandidateReport, FeatureScore
    from docodetect.ui_qt.widgets.result_card import ResultCard

    cand = CandidateReport(
        article_number="S-140", name="Schüssel 14", nominal_size_mm=140.0,
        height_mm=60.0, corrected_diameter_mm=141.0, geometry_error_mm=2.4,
        has_references=True, n_shots=3,
        features=[FeatureScore(feature="diameter_mm", measured=141.0,
                               reference=140.0, distance=1.0, sigma_enroll=0.0,
                               sigma_eff=1.5, z=0.67, log_contrib=-0.22,
                               w_eff=0.5, weighted=-0.11)],
        log_score=-0.11, posterior=0.87, max_abs_z=0.67)
    cfg = {"matching": {"diameter_tolerance_mm": 6.0}}
    card = ResultCard(cand, cfg)
    texts = card.all_text()   # neue Testhilfe, siehe Step 3
    assert "Ø 141,0 mm (höhenkorrigiert, h = 60 mm)" in texts
    assert "Δ 2,4 mm von ±6,0" in texts
    bars = card.channel_bars()  # dict Kanal -> QProgressBar|None
    assert bars["geometry"] is not None
    assert bars["color"] is None and bars["shape"] is None
```

- [ ] **Step 2: Fehlschlag verifizieren**

Run: `.venv/bin/python -m pytest tests/test_ui_qt_smoke.py -q -k result_card`
Expected: FAIL (Konstruktor-Signatur/`all_text`/`channel_bars` existieren noch nicht).

- [ ] **Step 3: `ResultCard` umbauen.** Kernpunkte (vollständige Bausteine):

(a) Konstruktor-Signatur: `def __init__(self, candidate, cfg, clickable=False, parent=None):` — Aufrufer reicht `cfg` durch. Ø-/Δ-Zeilen ersetzen durch:

```python
from docodetect.pipeline import channel_percentages, format_delta, format_diameter

self._diameter_label = QLabel(format_diameter(candidate))
self._delta_label = QLabel(format_delta(candidate, cfg))
```

(b) Teilscore-Balken (nach dem bestehenden Posterior-Balken einfügen):

```python
_CHANNEL_TITLES = {"geometry": "Geometrie", "color": "Farbe", "shape": "Form"}

def _build_channel_bars(self, candidate):
    """Drei Mini-Balken (Geometrie/Farbe/Form); Kanal ohne Daten -> grauer
    Text 'keine Daten' statt Balken (None), nie falsche 100 %."""
    self._channel_bars = {}
    row = QHBoxLayout()
    for ch, pct in channel_percentages(candidate).items():
        col = QVBoxLayout()
        title = QLabel(_CHANNEL_TITLES[ch])
        title.setObjectName("channelTitle")
        col.addWidget(title)
        if pct is None:
            na = QLabel("keine Daten")
            na.setObjectName("channelNoData")
            col.addWidget(na)
            self._channel_bars[ch] = None
        else:
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(round(pct * 100))
            bar.setTextVisible(False)
            bar.setFixedHeight(6)
            col.addWidget(bar)
            self._channel_bars[ch] = bar
        row.addLayout(col)
    return row
```

(c) Neutrale Rahmen: jede zustandsabhängige Rahmenfarbe der Karte entfernen (QSS-Selektoren/Property wie `state="accept"` auf der Karte löschen — Status zeigt NUR die Headline, Spec C). Der `clickable`-Hover-Stil bleibt.

(d) Testhilfen (am Ende der Klasse):

```python
def all_text(self) -> str:
    """Alle sichtbaren Label-Texte (fuer Offscreen-Tests)."""
    return " | ".join(lbl.text() for lbl in self.findChildren(QLabel))

def channel_bars(self) -> dict:
    return dict(self._channel_bars)
```

(e) Alle Aufrufer der Karte anpassen: `grep -n "ResultCard(" docodetect/ui_qt/` — jede Stelle bekommt das `cfg`-Argument (MainWindow hält `self.cfg`).

- [ ] **Step 4: Grün verifizieren**

Run: `.venv/bin/python -m pytest tests/test_ui_qt_smoke.py tests/test_ui_state.py -q`
Expected: PASS. Schlagen Alt-Tests fehl, weil sie alte Ø-Formatierung asserten: Assertions auf die NEUEN Helfer-Strings umstellen (die Helfer sind die Spezifikation).

- [ ] **Step 5: Commit**

```bash
git add docodetect/ui_qt/widgets/result_card.py tests/test_ui_qt_smoke.py
git commit -m "qt: ResultCard nutzt zentrale Helfer, Teilscore-Balken (Geometrie/Farbe/Form), neutrale Rahmen"
```

---

### Task 5: Qt MainWindow — Headline, Plätze 2–3, „Keiner davon", NO_MATCH-Diagnose

**Files:**
- Create: `docodetect/ui_qt/widgets/correction_dialog.py`
- Modify: `docodetect/ui_qt/main_window.py`
- Test: `tests/test_ui_state.py` (Zustände), `tests/test_ui_qt_smoke.py` (Dialog)

**Interfaces:**
- Consumes: `pipeline.headline/format_rank_line/list_articles`, bestehender Verdict-Weg des Ambiguous-Kartenklicks (`_confirm_candidate` in main_window.py — Aufrufkette per `grep -n "save_verdict\|_confirm_candidate" docodetect/ui_qt/main_window.py` verifizieren und WIEDERVERWENDEN).
- Produces: `CorrectionDialog(articles: list, parent=None)` mit `chosen() -> str | None` (Artikelnummer oder None = „Unbekannt"); MainWindow-Ergebnisbereich rendert accept/ambiguous/reject gemäß Spec C.

- [ ] **Step 1: Failing State-Test** in `tests/test_ui_state.py` (bestehende Report-Bau-Helfer der Datei nutzen; Muster dort abschauen):

```python
def test_show_report_headline_and_rank_lines(qapp, main_window_factory):
    """accept: Headline 'Automatisch übernommen' + Siegerkarte + kompakte
    Plätze 2-3; ambiguous: 'Bitte bestätigen' + Keiner-davon-Button;
    reject: 'Kein Treffer' + Rohmesswert-Diagnose."""
    win = main_window_factory()
    rep = make_report(decision="accept", n_candidates=3)   # Helfer der Datei
    win._show_report(rep)
    assert "Automatisch übernommen" in win.headline_text()
    assert win.rank_lines_count() == 2                     # Plätze 2 und 3

    rep2 = make_report(decision="ambiguous", n_candidates=2)
    win._show_report(rep2)
    assert "Bitte bestätigen" in win.headline_text()
    assert win.none_of_these_button() is not None

    rep3 = make_report(decision="reject", n_candidates=0,
                       measured={"circle_diameter_mm": 123.4,
                                 "circularity": 0.91, "area_mm2": 11958.0})
    win._show_report(rep3)
    assert "Kein Treffer" in win.headline_text()
    assert "123,4" in win.diagnose_text()
```

Hinweis: Existieren `main_window_factory`/`make_report` unter anderem Namen, die vorhandenen Pendants der Datei verwenden — NICHT doppelt bauen. Fehlen die Abfrage-Helfer (`headline_text`, `rank_lines_count`, `none_of_these_button`, `diagnose_text`), werden sie in Step 3 als schlanke Testhilfen am MainWindow ergänzt.

- [ ] **Step 2: Fehlschlag verifizieren**

Run: `.venv/bin/python -m pytest tests/test_ui_state.py -q -k headline_and_rank`
Expected: FAIL.

- [ ] **Step 3: Umsetzung.**

(a) Neue Datei `docodetect/ui_qt/widgets/correction_dialog.py` (komplett):

```python
"""Dialog „Keiner davon / manuell korrigieren" (CONFIRM-Pfad).

Durchsuchbare Artikelliste (gleiches Muster wie der Einlern-Dialog) plus
Option „Unbekannt". Ergebnis fließt als verdict=wrong (+ wahrer Artikel)
in das Report-JSON — Futter für die Verwechslungsmatrix der
Batch-Auswertung. Kein Buchungs-Backend (Spec: Nicht-Ziele).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QCompleter, QDialog,
                               QDialogButtonBox, QLabel, QRadioButton,
                               QVBoxLayout)

UNKNOWN_LABEL = "Unbekannt / nicht in der Liste"


class CorrectionDialog(QDialog):
    def __init__(self, articles: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manuell korrigieren")
        self.setModal(True)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Welcher Artikel liegt wirklich in der Box?"))

        self._pick_known = QRadioButton("Artikel auswählen:")
        self._pick_known.setChecked(True)
        lay.addWidget(self._pick_known)

        self._combo = QComboBox()
        self._combo.setEditable(True)
        self._combo.setInsertPolicy(QComboBox.NoInsert)
        for a in articles:
            self._combo.addItem(f"{a.name}  ({a.article_number})",
                                a.article_number)
        comp = QCompleter([self._combo.itemText(i)
                           for i in range(self._combo.count())], self)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setFilterMode(Qt.MatchContains)
        self._combo.setCompleter(comp)
        lay.addWidget(self._combo)

        self._pick_unknown = QRadioButton(UNKNOWN_LABEL)
        lay.addWidget(self._pick_unknown)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def chosen(self) -> str | None:
        """Artikelnummer der Wahl; None = Unbekannt."""
        if self._pick_unknown.isChecked():
            return None
        return self._combo.currentData()
```

(b) MainWindow `_show_report`-Bereich umbauen (Anker: bestehende Verzweigung `report.decision == ...`, siehe `grep -n "decision ==" docodetect/ui_qt/main_window.py`):

```python
from docodetect.pipeline import format_rank_line, headline, list_articles

# accept-Zweig:
best = report.candidates[0]
text, cls = headline(report.decision, best.name)
self._set_headline(text, cls)
self._add_card(ResultCard(best, self.cfg))
for rank, c in enumerate(report.candidates[1:3], start=2):
    lbl = QLabel(format_rank_line(c, rank))
    lbl.setObjectName("rankLine")
    self._results_layout.addWidget(lbl)
    self._rank_lines.append(lbl)

# ambiguous-Zweig: Karten wie bisher (clickable=True, cfg durchreichen), danach:
self._none_button = QPushButton("Keiner davon / manuell korrigieren")
self._none_button.clicked.connect(self._manual_correction)
self._results_layout.addWidget(self._none_button)

# reject-Zweig (nach der bestehenden Randfall-Sonderbehandlung, die bleibt):
text, cls = headline(report.decision)
self._set_headline(text, cls)
m = report.measured or {}
if m:
    diag = QLabel("Gemessen: Ø {} mm (Bodenebene) · Rundheit {} · Fläche {} cm²".format(
        f"{m.get('circle_diameter_mm', 0):.1f}".replace(".", ","),
        f"{m.get('circularity', 0):.2f}".replace(".", ","),
        f"{m.get('area_mm2', 0) / 100:.0f}"))
    diag.setObjectName("diagnoseLine")
    diag.setWordWrap(True)
    self._results_layout.addWidget(diag)
    self._diagnose_label = diag
```

(c) `_manual_correction` (neue Methode; die Verdict-Speicherung ruft EXAKT dieselbe Kette wie `_confirm_candidate`, nur mit `correct=False` und gewähltem Artikel):

```python
def _manual_correction(self):
    from docodetect.ui_qt.widgets.correction_dialog import CorrectionDialog
    dlg = CorrectionDialog(list_articles(self.cfg), self)
    if dlg.exec() != QDialog.Accepted or self._last_report is None:
        return
    chosen = dlg.chosen()
    self._save_verdict(self._last_report, correct=False, true_article=chosen)
    name = chosen or "Unbekannt"
    self._set_headline(f"Korrigiert: {name} — im Testprotokoll vermerkt.", "confirm")
```

Existiert noch kein gemeinsamer `_save_verdict`-Helfer, den Code aus `_confirm_candidate` dorthin EXTRAHIEREN (eine Speicherstelle, kein Duplikat) — Signatur: `_save_verdict(self, report, correct: bool, true_article: str | None = None)`.

(d) Testhilfen am MainWindow (analog `all_text` der Karte):

```python
def headline_text(self) -> str: return self._headline.text()
def rank_lines_count(self) -> int: return len(self._rank_lines)
def none_of_these_button(self): return getattr(self, "_none_button", None)
def diagnose_text(self) -> str:
    lbl = getattr(self, "_diagnose_label", None)
    return lbl.text() if lbl else ""
```

`_rank_lines`/`_none_button`/`_diagnose_label` beim Ergebnis-Leeren (bestehende Clear-Methode) mit zurücksetzen.

(e) QSS: `#rankLine`, `#diagnoseLine`, `#channelTitle`, `#channelNoData` dezent (kleine Schrift, gedämpfte Farbe) in `style.qss` ergänzen — Paletten-Kommentarkopf der Datei beachten.

- [ ] **Step 4: Grün verifizieren (alle UI-Tests + Alt-Assertions auf „Erkannt" anpassen)**

Run: `grep -rn "Erkannt" tests/` — Treffer auf `"Automatisch übernommen"` umstellen. Dann: `.venv/bin/python -m pytest tests/test_ui_state.py tests/test_ui_qt_smoke.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add docodetect/ui_qt/ tests/test_ui_state.py tests/test_ui_qt_smoke.py
git commit -m "qt: Entscheidungs-Headline via Helfer, kompakte Plaetze 2-3, Keiner-davon-Dialog mit Artikel-Picker, NO_MATCH-Diagnose"
```

---

### Task 6: Streamlit — gleiche Pfade mit Bordmitteln

**Files:**
- Modify: `app.py` (Identify-Ergebnisblock; Anker: `st.session_state.get("identify_result")`)

**Interfaces:**
- Consumes: `pipeline.headline/format_diameter/format_delta/format_rank_line/channel_percentages`, `reporting.save_verdict`-Weg — WICHTIG: über denselben Mechanismus wie die bestehende Feedback-Funktion der Scoring-Seite (`grep -n "save_verdict" pages/1_Scoring_Analyse.py app.py ui_common.py` und den vorhandenen Weg wiederverwenden; falls app.py bisher keinen hat, die Funktion aus `docodetect.reporting` via pipeline… NEIN: `reporting` ist kein UI-Verbots-Modul — Scoring-Seite importiert es bereits direkt; demselben Muster folgen).
- Produces: `_render_identify_result(res, cfg)`-Funktion in app.py — einzige Render-Stelle des Identify-Ergebnisses.

- [ ] **Step 1: Ergebnisblock ersetzen.** Zuerst lesen: `sed -n '280,340p' app.py` (Identify-Abschnitt). Den bisherigen Anzeige-Code des `identify_result` durch EINEN Aufruf `_render_identify_result(res, cfg)` ersetzen und die Funktion (oberhalb, bei den anderen Helpern von app.py) einfügen:

```python
def _render_identify_result(res, cfg):
    """Entscheidungsanzeige — nutzt dieselben Helfer wie die Qt-App
    (inhaltlich identisch, Streamlit-Bordmittel)."""
    from docodetect.pipeline import (channel_percentages, format_delta,
                                     format_diameter, format_rank_line,
                                     headline)
    from docodetect.reporting import save_verdict

    report = res["report"]                       # MatchReport
    best = report.candidates[0] if report.candidates else None
    text, cls = headline(report.decision, best.name if best else None)
    {"accept": st.success, "confirm": st.warning, "reject": st.error}[cls](text)

    if report.decision == "reject":
        m = report.measured or {}
        if m:
            st.caption("Gemessen: Ø {:.1f} mm (Bodenebene) · Rundheit {:.2f} · "
                       "Fläche {:.0f} cm²".format(
                           m.get("circle_diameter_mm", 0),
                           m.get("circularity", 0),
                           m.get("area_mm2", 0) / 100).replace(".", ","))
        st.caption(report.message)
        return

    def _candidate_block(c):
        st.markdown(f"**{c.name}**  \n{c.article_number}")
        st.caption(f"{format_diameter(c)} · {format_delta(c, cfg)}")
        st.progress(min(1.0, c.posterior),
                    text=f"Gesamt {c.posterior * 100:.0f} %")
        cols = st.columns(3)
        titles = {"geometry": "Geometrie", "color": "Farbe", "shape": "Form"}
        for col, (ch, pct) in zip(cols, channel_percentages(c).items()):
            with col:
                if pct is None:
                    st.caption(f"{titles[ch]}: keine Daten")
                else:
                    st.progress(min(1.0, pct), text=titles[ch])

    if report.decision == "accept":
        _candidate_block(best)
        for rank, c in enumerate(report.candidates[1:3], start=2):
            st.caption(format_rank_line(c, rank))
        return

    # ambiguous: Kandidaten auswählbar + „Keiner davon"
    top_k = int(report.thresholds.get("top_k", 3))
    for c in report.candidates[:top_k]:
        _candidate_block(c)
        if st.button(f"✓ {c.article_number} bestätigen", key=f"conf_{c.article_number}"):
            save_verdict(report, True, c.article_number)
            st.success(f"Bestätigt: {c.name} — im Testprotokoll vermerkt.")
    with st.expander("Keiner davon / manuell korrigieren"):
        arts = _cached_articles(cfg)             # siehe unten
        labels = ["Unbekannt / nicht in der Liste"] + [
            f"{a.name}  ({a.article_number})" for a in arts]
        pick = st.selectbox("Wahrer Artikel", labels, key="none_of_these_pick")
        if st.button("Korrektur speichern", key="none_of_these_save"):
            nr = None if pick == labels[0] else arts[labels.index(pick) - 1].article_number
            save_verdict(report, False, nr)
            st.info(f"Korrigiert: {nr or 'Unbekannt'} — im Testprotokoll vermerkt.")


def _cached_articles(cfg):
    from docodetect.pipeline import list_articles
    if "articles_cache" not in st.session_state:
        st.session_state.articles_cache = list_articles(cfg)
    return st.session_state.articles_cache
```

Wichtig: `save_verdict(report, ...)` braucht `report.report_path` — das ist bei Pipeline-Identifys gesetzt; wenn der bestehende Code das Report-Objekt nur als dict speichert, das echte `MatchReport`-Objekt in `st.session_state.identify_result` ablegen (Anker prüfen). Signatur von `save_verdict` vor Benutzung verifizieren: `grep -n "def save_verdict" docodetect/reporting.py` — Aufrufform exakt übernehmen (sie ist `save_verdict(report, correct, true_article=None)`-artig; bei Abweichung den echten Namen verwenden, nicht raten).

- [ ] **Step 2: Syntax-/Import-Smoke**

Run: `.venv/bin/python -c "import ast; ast.parse(open('app.py', encoding='utf-8').read()); print('app.py ok')"`
Expected: `app.py ok`. Zusätzlich manueller Kurzcheck möglich: `streamlit run app.py` startet ohne Traceback (kein automatisierter Browsertest nötig).

- [ ] **Step 3: Volle Suite (Streamlit-UI hat keine pytest-Abdeckung, aber nichts anderes darf brechen)**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add app.py
git commit -m "streamlit: Entscheidungspfade ueber zentrale Helfer (Headline, Teilscores, Plaetze 2-3, Keiner-davon mit Artikelwahl)"
```

---

### Task 7: Demo-Szenarien — TELLER-19, Knapp-Bild, Unbekannt-Bild

**Files:**
- Modify: `docodetect/ui_qt/demo_scenes.py`
- Test: `tests/test_ui_qt_smoke.py` (E2E-Demo-Tests ergänzen)

**Interfaces:**
- Consumes: bestehende Strukturen in demo_scenes.py: `DemoArticle`-Dataclass, Artikel-Seed-Liste, Szenen-Registry + `build_scene(cfg, name, variant)` (Namen zuerst lesen: `sed -n '1,120p' docodetect/ui_qt/demo_scenes.py`).
- Produces: Demo-Artikel `TELLER-19` (Ø 190, h 0, 3 Referenz-Shots wie die übrigen); Szenen `"Teller 19/20 (knapp)"` (Objekt in 195 mm gezeichnet, Farbe/Form identisch zu TELLER-19/20) und `"Unbekanntes Objekt"` (Ø 120 mm) — beide erscheinen im Demo-Dropdown (das Dropdown speist sich aus der Szenen-Registry; KEINE UI-Änderung nötig).

- [ ] **Step 1: Failing E2E-Tests** in `tests/test_ui_qt_smoke.py` — exakt dem Muster des bestehenden `test_demo_end_to_end_identify` folgen (gleiche Fixtures/Seed-Helfer der Datei; nur Szene + Assertions unterscheiden sich):

```python
def test_demo_confirm_scene_is_ambiguous(qapp, demo_env):
    """Knapp-Bild 195 mm zwischen TELLER-19 (190) und TELLER-20 (200):
    beide im Toleranzfenster, identische Farbe/Form -> CONFIRM."""
    rep = identify_demo_scene(demo_env, "Teller 19/20 (knapp)")
    assert rep.decision == "ambiguous"
    nrs = {c.article_number for c in rep.candidates}
    assert {"TELLER-19", "TELLER-20"} <= nrs


def test_demo_no_match_scene_is_reject(qapp, demo_env):
    rep = identify_demo_scene(demo_env, "Unbekanntes Objekt")
    assert rep.decision == "reject"
    assert rep.candidates == []
```

Hinweis: Heißen die Fixtures/Helfer der Datei anders (`demo_env`/`identify_demo_scene` sind Platzhalter für das VORHANDENE Muster), die vorhandenen Namen verwenden — den Identify-Weg des bestehenden E2E-Tests kopieren, nicht neu erfinden.

- [ ] **Step 2: Fehlschlag verifizieren**

Run: `.venv/bin/python -m pytest tests/test_ui_qt_smoke.py -q -k "confirm_scene or no_match_scene"`
Expected: FAIL (Szene unbekannt / Artikel fehlt).

- [ ] **Step 3: demo_scenes.py erweitern.**

(a) Artikel-Seed: `TELLER-19` als `DemoArticle` mit Ø 190,0 / h 0 analog zum bestehenden `TELLER-18`-Eintrag (gleiche Farbe/Zeichenfunktion, 3 Referenz-Shots wie die übrigen — der Seed-Mechanismus behandelt alle Artikel gleich).

(b) Szenen-Registry, zwei Einträge nach dem Muster der bestehenden:

- `"Teller 19/20 (knapp)"`: zeichnet denselben Teller-Typ mit **apparenter Größe 195,0 mm** zentriert (exakt zwischen den Nominalen; ±5 ≤ 6 mm Toleranz → beide Kandidaten bleiben, Margin < Schwelle → ambiguous).
- `"Unbekanntes Objekt"`: Teller-Typ mit **Ø 120,0 mm** (nächster Artikel 190 → 70 mm > 6 mm → leerer Vorfilter → reject).

(c) Kommentar an beide Einträge: `# Spec 2026-07-20: erzwingt CONFIRM (knappes Fenster)` bzw. `# Spec 2026-07-20: erzwingt NO_MATCH (ausserhalb aller Toleranzen)`.

- [ ] **Step 4: Grün + Alt-Demo-Regression**

Run: `.venv/bin/python -m pytest tests/test_ui_qt_smoke.py -q`
Expected: PASS — auch der bestehende E2E-Test (TELLER-18 bleibt accept: Abstand 190↔180 = 10 mm > 6 → keine Wechselwirkung).

- [ ] **Step 5: Commit**

```bash
git add docodetect/ui_qt/demo_scenes.py tests/test_ui_qt_smoke.py
git commit -m "demo: TELLER-19 + Szenen 'Teller 19/20 (knapp)' (CONFIRM) und 'Unbekanntes Objekt' (NO_MATCH)"
```

---

### Task 8: Abschluss — Gesamtverifikation + Baseline-Schutz

**Files:**
- Keine Code-Änderungen (nur Verifikation; bei Rot: STOPP und melden).

**Interfaces:**
- Consumes: alles Vorherige.
- Produces: Nachweis der Erfolgskriterien aus der Spec.

- [ ] **Step 1: Volle Suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS (vorher 113 + neue Tests; 15 skipped unverändert).

- [ ] **Step 2: Baseline-Schutz (Erfolgskriterium 2)**

Run: `.venv/bin/python -m docodetect.cli evaluate data/testset-smoke 2>&1 | tail -8`
Expected: `=== top-1 accuracy: 11/14 (78.6 %) ===`, decisions `accept: 13`, `reject: 1`, confusion `TELLER-180-HOCH -> TELLER-180: 2x` und `TELLER-200 -> NO_MATCH: 1x`. JEDE Abweichung = STOPP + melden (Logik-Regression).

- [ ] **Step 3: Captures aufräumen (evaluate hat 14 Report-JSONs erzeugt)**

Run: `rm data/captures/*.json && ls data/captures/ | wc -l`
Expected: `0`.

- [ ] **Step 4: Demo-Sichtprüfung (Erfolgskriterium 3, manuell)**

Run: `.venv/bin/python -m docodetect.ui_qt --demo`
Prüfen: Szene „Teller 19/20 (knapp)" → gelbe „Bitte bestätigen"-Ansicht mit zwei Karten + „Keiner davon"-Button; „Unbekanntes Objekt" → rote „Kein Treffer"-Ansicht mit Diagnosezeile; TELLER-18 → grün „✓ Automatisch übernommen". (Headless-Umgebung: Schritt dokumentiert überspringen.)

- [ ] **Step 5: Spec + Plan committen**

```bash
git add docs/superpowers/specs/2026-07-20-multi-candidate-decision-ui-design.md docs/superpowers/plans/2026-07-20-multi-candidate-decision-ui.md
git commit -m "docs: Spec + Plan Mehrkandidaten-Entscheidungspfad (beide UIs)"
```
