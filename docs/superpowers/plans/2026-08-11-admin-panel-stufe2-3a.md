# Admin-Panel Stufe 2 + Stufe 3 Teil A — Implementierungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans
> to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Stufe 2 vollständig (Analyse-Lauf-Seite + Bewertungs-Übersicht,
Spec Abschnitt 6, Punkte 6+7, inkl. Listbarkeits-Kriterium) und Stufe 3
**nur Teil A** (Artikelliste mit Referenzzahl, Nominalmaßen und wirksamem
Vorfilter-Nominal) — gemäß Spec
[2026-08-08-admin-panel-design.md](../specs/2026-08-08-admin-panel-design.md)
und Freigabe 2026-08-11 (Melde-Punkt run_analysis-Fassade, vier
Ergänzungen).

**Ausdrücklich NICHT gebaut:** Diagnoseblätter (Stufe 3 Teil B — 334 von
359 `reference_features.image_path` NULL, verifiziert 2026-08-11 per
Read-only-Query), der Wrapper um `build_enrollment_sheet`, Einlern-Sessions
(Punkt 9), Stufe 4, Push.

**Architecture:** Das Panel bleibt reine Konsumentenschicht. Neue
UI-Module importieren nur `docodetect.pipeline` (inkl. der dort
re-exportierten Typen/Konstanten `MatchReport`/`NO_MATCH`),
`docodetect.config.resolve` und ui_qt-interne Module. `analysis.py` wird
an GENAU EINER Stelle additiv erweitert (`out_dir`-Parameter, Default =
heutiges Verhalten — Präzedenzfall `load_reports(sort_by=…)` aus 1a).
Der Analyse-Lauf läuft im vorhandenen **PipelineWorker-Muster** (Freigabe-
Ergänzung 1: 17 Matplotlib-Abschnitte sind Sekunden, nicht Millisekunden;
kein zweiter QThread-Pfad, seriell).

**Belege aus dem Melde-Punkt (2026-08-11, abgenommen):**
- `run_analysis` löst Pfade an `analysis.py:1319-1322` auf (Quelle mit
  Parameter + Config-Fallback, Ziel OHNE Parameter), `publish_run` an
  `analysis.py:1393-1394`.
- Aufrufer repo-weit (inkl. Subagenten-Gegencheck über `scripts/`,
  `docodetect/corpus/`, dynamische Importe): Produktivcode NUR
  `cli.py:581/588` (`cmd_analyze`), Tests `tests/test_analysis.py`
  (Zeilen 129/206/249/273/301 bzw. 276/287). Kein Aufrufer übergibt mehr
  als vier Argumente → fünfter Parameter am Ende ist unsichtbar.
- `publish_run` wird NICHT berührt (`--publish` bleibt CLI-only, Spec
  Punkt 6; Sandbox-Sperre `cli.py:1056` unberührt).
- `report_detail.py:19` bezieht aus `matcher` NUR den Typ `MatchReport`
  (einzige Fundstelle) — Re-Export-Lösung genehmigt, kein Stopp.
- `report.md` wird genau einmal geschrieben (`analysis.py:1378`); kein
  Pfad schreibt es nach (Audit 2026-08-11) → mtime-Sortierung der
  Lauf-Historie ist stabil (Freigabe-Ergänzung 4, Auflage erfüllt).

## Global Constraints

- **Branch `feature/admin-panel-stufe2`**, Commit nach jedem Task, kein
  Merge, kein Push. Melden nur bei Abweichungen, die die Spec ändern oder
  Bestandscode über die genehmigten Stellen hinaus berühren.
- **Genehmigte Eingriffe in Bestandscode (abschließend):**
  1. `analysis.py`: additiver `out_dir`-Parameter (Task 1).
  2. `pipeline.py`: additive Fassaden/Dataclass-Erweiterung (Task 2).
  3. `reports_page.py:25-27` + `report_detail.py:19-21`: Import-Umstellung
     auf pipeline-Bezüge (Task 3, Freigabe-Ergänzung 2).
  4. `admin_window.py`: zwei Platzhalter durch echte Seiten ersetzen
     (Task 7).
  5. `tests/test_admin_ui.py::_admin_cfg`: um `analysis`/`matching`-Keys
     ergänzt (nötig, damit die neuen Seiten gegen tmp_path laufen, nie
     gegen `reports/analysis/` des Repos).
  Alles andere sind Neuanlagen.
- **TDD:** Test zuerst, Fehlschlag aus dem RICHTIGEN Grund verifizieren,
  dann Code. Der Test wird nicht an den Code angepasst.
- **Python-Floor 3.9:** PEP-604 nur mit `from __future__ import
  annotations` (alle neuen Module haben ihn; `tests/test_analysis.py` und
  `tests/test_ui_facade.py` haben ihn NICHT — dort keine `X | Y`-
  Annotationen).
- **Tests nur gegen tmp_path** — echte DB/`data/`/`calibration/`/
  `reports/analysis/` werden nie berührt. UI-Module EINZELN je
  pytest-Aufruf (Segfault-Regel, docs/ui-qt-testsuite-segfault.md);
  `test_ui_qt_smoke.py`: Summary zählt, nicht der Exit-Code.
- **Read-only am Bestand:** Analyse-Artefakte unter
  `reports/analysis/<run_id>/` sind Ausgabebereich (Spec Abschnitt 5).
  `archive`/`--publish` werden aus der UI NICHT angeboten.
- **NO_MATCH ist ein Sonderwert, keine Artikelnummer** (auch in der
  Bewertungs-Übersicht: eigener Zustand „— kein Kandidat").
- Sprache/Stil wie Bestand: deutsche Docstrings/UI-Texte, Dezimalkomma,
  ~79 Zeichen.
- Lange Läufe (volle Suite, corpus-run-Doppel-Check) EINMAL am Ende
  (Task 8). Vorher nur betroffene Module.

---

### Task 1: Additiver `out_dir`-Parameter in `analysis.run_analysis`

**Files:**
- Modify: `docodetect/analysis.py` (Signatur Zeile 1309, Zielpfad 1322)
- Test: `tests/test_analysis.py` (ans Dateiende)

**Interfaces:**
- `run_analysis(cfg, reports_dir=None, run_id=None, archive=False,
  out_dir: str | Path | None = None) -> Path` — `out_dir` ist das
  ELTERN-Verzeichnis (run_id wird innen angehängt, damit die
  Default-run_id-Erzeugung an einer Stelle bleibt). Default `None` =
  heutiges Verhalten, Spiegelbild des `reports_dir`-Musters.

- [ ] **Step 1: Fehlschlagenden Test schreiben** — ans Ende von
  `tests/test_analysis.py`:

```python
def test_run_analysis_out_dir_lenkt_nur_das_ziel(tmp_path, monkeypatch):
    """Additiver out_dir-Parameter (2026-08-11, Admin-Panel Stufe 2):
    Default = heutiges Verhalten (analysis.output_dir aus der Config);
    mit out_dir landet der Lauf unter <out_dir>/<run_id>, die Config
    wird fuer das Ziel nicht mehr angefasst."""
    import docodetect.config as cfgmod
    monkeypatch.setattr(cfgmod, "project_root", lambda: tmp_path)
    reports_dir = tmp_path / "caps"
    reports_dir.mkdir()                    # leer -> schneller "Keine Reports"-Lauf
    cfg = {"matching": dict(MATCHING),
           "analysis": {"output_dir": "reports/analysis"},
           "geometry": {"camera_height_mm": 300.0},
           "paths": {"db_file": str(tmp_path / "t.sqlite3")}}
    ziel = tmp_path / "anderswo"
    out = run_analysis(cfg, reports_dir, run_id="umgeleitet", out_dir=ziel)
    assert out == ziel / "umgeleitet"
    assert (out / "report.md").exists()
    assert not (tmp_path / "reports" / "analysis" / "umgeleitet").exists()
```

- [ ] **Step 2: Fehlschlag verifizieren**

Run: `.venv/bin/pytest tests/test_analysis.py -k out_dir -v`
Expected: `TypeError: run_analysis() got an unexpected keyword argument 'out_dir'`

- [ ] **Step 3: Implementieren** — Signatur + Zielpfad-Zeile:

```python
def run_analysis(cfg: dict, reports_dir: str | Path | None = None,
                 run_id: str | None = None, archive: bool = False,
                 out_dir: str | Path | None = None) -> Path:
```

  Docstring ergänzen (nach dem archive-Absatz):

```python
    out_dir (additiv 2026-08-11, Admin-Panel Stufe 2): ELTERN-Verzeichnis
    der Artefakte statt <analysis.output_dir>; run_id wird angehängt.
    Default None = bisheriges Verhalten — Spiegelbild von reports_dir,
    damit die pipeline-Fassade Quell- UND Zielpfad auflösen kann.
```

  Zeile 1322 ersetzen durch:

```python
    base = Path(out_dir) if out_dir else resolve(
        cfg.get("analysis", {}).get("output_dir", "reports/analysis"))
    out = base / run_id
```

- [ ] **Step 4: Tests grün verifizieren**

Run: `.venv/bin/pytest tests/test_analysis.py -v`
Expected: PASS (alle, inkl. der bestehenden end_to_end/archive/publish-Tests
— kein bestehender Aufrufer ändert sein Verhalten)

- [ ] **Step 5: Commit**

```bash
git add docodetect/analysis.py tests/test_analysis.py
git commit -m "feat(analysis): additiver out_dir-Parameter fuer run_analysis (Stufe 2)"
```

---

### Task 2: pipeline-Fassaden + ArticleInfo-Erweiterung + NO_MATCH-Re-Export

**Files:**
- Modify: `docodetect/pipeline.py` (Import-Block, `ArticleInfo`, neue
  Dataclass `AnalysisRunInfo`, drei Funktionen nach `list_articles`)
- Test: `tests/test_ui_facade.py` (ans Dateiende)

**Interfaces:**
- Re-Export: `from .reporting import NO_MATCH  # noqa: F401` im
  Import-Block (Präzedens: `display`-Import Zeile 30). `MatchReport` ist
  dort bereits importiert — beide sind damit über pipeline beziehbar.
- `ArticleInfo` additiv: `width_mm: float | None = None`,
  `depth_mm: float | None = None` (Defaults ans Ende — kein bestehender
  Konstruktor ändert sich); `list_articles` befüllt beide.
- `AnalysisRunInfo(run_id: str, path: Path, mtime_unix: float)` —
  `mtime_unix` ist die DATEIZEIT von `report.md` (Freigabe-Ergänzung 4:
  so beschriften, nicht als „Laufzeitpunkt").
- `run_report_analysis(cfg, reports_dir=None, run_id=None) -> Path` —
  löst Quelle (Default `paths.captures_dir`) UND Ziel
  (`analysis.output_dir`) auf, delegiert mit `out_dir=`. Ohne
  archive/publish.
- `list_analysis_runs(cfg) -> tuple[list[AnalysisRunInfo], int]` —
  Listbarkeits-Kriterium: gültig = `report.md` UND `metrics.json`;
  Rückgabe (gültige, Zahl der ungültigen Ordner); Dateizeit absteigend.
- `nominal_size_mm(article) -> float | None` — delegiert an
  `matcher._nominal_size_mm`, KEINE zweite Implementierung der
  max/hypot-Regel (Freigabe-Ergänzung 3).

- [ ] **Step 1: Fehlschlagende Tests schreiben** — ans Ende von
  `tests/test_ui_facade.py` (Datei hat kein `from __future__` — keine
  PEP-604-Annotationen):

```python
# ---------- Stufe-2/3A-Fassaden (Admin-Panel, Freigabe 2026-08-11) ----------

import math  # noqa: E402

from docodetect.pipeline import (AnalysisRunInfo, ArticleInfo,  # noqa: E402
                                 NO_MATCH, list_analysis_runs,
                                 nominal_size_mm, run_report_analysis)


def test_no_match_ist_ueber_pipeline_beziehbar():
    assert NO_MATCH == "NO_MATCH"


def test_run_report_analysis_loest_quelle_und_ziel_auf(tmp_path, monkeypatch):
    import docodetect.config as cfgmod
    monkeypatch.setattr(cfgmod, "project_root", lambda: tmp_path)
    caps = tmp_path / "captures"
    caps.mkdir()
    cfg = make_cfg(tmp_path)
    cfg["paths"]["captures_dir"] = str(caps)
    out = run_report_analysis(cfg, run_id="fassade")
    assert out == tmp_path / "reports" / "analysis" / "fassade"
    md = (out / "report.md").read_text(encoding="utf-8")
    assert str(caps) in md                 # Quelle = captures_dir-Default


def test_run_report_analysis_expliziter_quellordner(tmp_path, monkeypatch):
    import docodetect.config as cfgmod
    monkeypatch.setattr(cfgmod, "project_root", lambda: tmp_path)
    quelle = tmp_path / "eigene"
    quelle.mkdir()
    cfg = make_cfg(tmp_path)
    cfg["analysis"] = {"output_dir": str(tmp_path / "ziel")}
    out = run_report_analysis(cfg, reports_dir=quelle, run_id="expl")
    assert out == tmp_path / "ziel" / "expl"
    assert str(quelle) in (out / "report.md").read_text(encoding="utf-8")


def test_list_analysis_runs_kriterium_und_zaehlung(tmp_path):
    import os
    base = tmp_path / "runs"
    cfg = make_cfg(tmp_path)
    cfg["analysis"] = {"output_dir": str(base)}
    for name, dateien in (("gut1", ("report.md", "metrics.json")),
                          ("gut2", ("report.md", "metrics.json")),
                          ("nur-md", ("report.md",)),
                          ("leer", ())):
        (base / name).mkdir(parents=True)
        for f in dateien:
            (base / name / f).write_text("x", encoding="utf-8")
    (base / "notiz.txt").write_text("x", encoding="utf-8")  # kein Ordner
    os.utime(base / "gut2" / "report.md", (1000, 1000))     # aelter machen
    laeufe, ungueltig = list_analysis_runs(cfg)
    assert [r.run_id for r in laeufe] == ["gut1", "gut2"]   # Dateizeit absteigend
    assert ungueltig == 2                                   # nur-md + leer
    assert laeufe[0].path == base / "gut1"
    assert isinstance(laeufe[0], AnalysisRunInfo)


def test_list_analysis_runs_ohne_verzeichnis(tmp_path):
    cfg = make_cfg(tmp_path)
    cfg["analysis"] = {"output_dir": str(tmp_path / "gibtsnicht")}
    assert list_analysis_runs(cfg) == ([], 0)


def test_nominal_size_mm_max_nicht_hypot():
    """Die max/hypot-Regel lebt in matcher._nominal_size_mm und wird von
    der Fassade nur durchgereicht — der hypot-Fehler vom 2026-07-21 darf
    nicht als Zweitimplementierung in einer UI wiederkehren."""
    laenglich = ArticleInfo(article_number="L-1", name="Loeffel",
                            category=None, diameter_mm=None, height_mm=None,
                            n_references=0, width_mm=186.9, depth_mm=45.0)
    assert nominal_size_mm(laenglich) == 186.9
    assert nominal_size_mm(laenglich) != pytest.approx(
        math.hypot(186.9, 45.0))
    rund = ArticleInfo(article_number="T-1", name="Teller", category=None,
                       diameter_mm=270.0, height_mm=None, n_references=0)
    assert nominal_size_mm(rund) == 270.0
    ohne = ArticleInfo(article_number="X-1", name="Ohne", category=None,
                       diameter_mm=None, height_mm=None, n_references=0)
    assert nominal_size_mm(ohne) is None


def test_list_articles_liefert_breite_und_tiefe(tmp_path):
    from docodetect.database import Article, Database
    cfg = make_cfg(tmp_path)
    db = Database(cfg)
    db.init_schema()
    db.create_article(Article(article_number="L-1", name="Loeffel",
                              category=None, diameter_mm=None,
                              width_mm=186.9, depth_mm=45.0, height_mm=20.0,
                              color_desc=None, notes=None))
    db.close()
    infos = list_articles(cfg)
    assert infos[0].width_mm == 186.9
    assert infos[0].depth_mm == 45.0
```

- [ ] **Step 2: Fehlschlag verifizieren**

Run: `.venv/bin/pytest tests/test_ui_facade.py -v`
Expected: `ImportError: cannot import name 'AnalysisRunInfo'` (bzw.
`NO_MATCH`/`list_analysis_runs`/…)

- [ ] **Step 3: Implementieren** — in `docodetect/pipeline.py`:

  Import-Block (nach dem `display`-Import, Zeile ~30):

```python
from .reporting import NO_MATCH  # noqa: F401 — Re-Export: UIs beziehen
# Konstanten/Typen ueber pipeline, nie reporting/matcher direkt (Spec
# Zugriffsweg, Revision 2026-08-11); MatchReport oben ebenso.
```

  `ArticleInfo` erweitern (Felder ans Ende, Docstring-Zusatz):

```python
    n_references: int
    # Additiv 2026-08-11 (Stufe 3 Teil A): minAreaRect-Seiten der
    # laenglichen Artikel — Nominal ist max(width, depth), nie hypot.
    width_mm: float | None = None
    depth_mm: float | None = None
```

  `list_articles`: `width_mm=a.width_mm, depth_mm=a.depth_mm` ergänzen.

  Nach `ArticleInfo` die neue Dataclass:

```python
@dataclass
class AnalysisRunInfo:
    """Gueltiger Analyse-Lauf unter analysis.output_dir (Listbarkeits-
    Kriterium, Spec Stufe 2): report.md UND metrics.json vorhanden.
    mtime_unix ist die DATEIZEIT von report.md — report.md wird genau
    einmal am Laufende geschrieben (analysis.py, Audit 2026-08-11:
    kein Pfad schreibt es neu), Anzeige beschriftet sie als Dateizeit."""
    run_id: str
    path: Path
    mtime_unix: float
```

  Nach `list_articles` die drei Fassaden:

```python
def run_report_analysis(cfg: dict,
                        reports_dir: str | Path | None = None,
                        run_id: str | None = None) -> Path:
    """Analyse-Lauf fuer UIs: Quell- UND Zielpfad werden HIER aufgeloest,
    analysis.run_analysis rechnet nur noch (Spec Stufe 2, Zugriffsweg;
    Freigabe 2026-08-11). Bewusst ohne archive und ohne publish — beides
    bleibt CLI-only: archive verschiebt Report-JSONs aus dem Bestand
    (Read-only-Definition, Spec Abschnitt 5), publish schreibt ins
    versionierte Archiv."""
    from .analysis import run_analysis
    src = resolve(reports_dir) if reports_dir else resolve(
        cfg.get("paths", {}).get("captures_dir", "data/captures"))
    out_base = resolve(cfg.get("analysis", {}).get("output_dir",
                                                   "reports/analysis"))
    return run_analysis(cfg, reports_dir=src, run_id=run_id,
                        out_dir=out_base)


def list_analysis_runs(cfg: dict) -> tuple[list[AnalysisRunInfo], int]:
    """Lauf-Historie unter analysis.output_dir: (gueltige Laeufe, Zahl
    der ungueltigen Ordner). Gueltig = report.md UND metrics.json
    (Listbarkeits-Kriterium, Spec Stufe 2) — der Rest wird gezaehlt,
    nie verschwiegen. Sortiert nach DATEIZEIT von report.md, neueste
    zuerst: run_ids sind teils frei vergeben (phase-b-korrigiert,
    stufeA-v2), Namen sortieren hier nichts (Freigabe-Ergaenzung 4)."""
    base = resolve(cfg.get("analysis", {}).get("output_dir",
                                               "reports/analysis"))
    if not base.is_dir():
        return [], 0
    gueltig: list[AnalysisRunInfo] = []
    ungueltig = 0
    for d in sorted(base.iterdir()):
        if not d.is_dir():
            continue
        report_md = d / "report.md"
        if report_md.is_file() and (d / "metrics.json").is_file():
            gueltig.append(AnalysisRunInfo(
                run_id=d.name, path=d,
                mtime_unix=report_md.stat().st_mtime))
        else:
            ungueltig += 1
    gueltig.sort(key=lambda r: r.mtime_unix, reverse=True)
    return gueltig, ungueltig


def nominal_size_mm(article) -> float | None:
    """Wirksames Vorfilter-Nominal (Stufe 3 Teil A): diameter_mm bei
    runden, max(width, depth) bei laenglichen Artikeln — EXAKT
    matcher._nominal_size_mm, hier nur oeffentlich gemacht. Die Regel
    wird nirgends dupliziert (der hypot-Fehler vom 2026-07-21 entstand
    genau so). Nimmt Article wie ArticleInfo (duck-typed)."""
    from .matcher import _nominal_size_mm
    return _nominal_size_mm(article)
```

- [ ] **Step 4: Tests grün verifizieren**

Run: `.venv/bin/pytest tests/test_ui_facade.py -v`
Expected: PASS (alle, inkl. der 1a-Fassaden-Tests)

- [ ] **Step 5: Commit**

```bash
git add docodetect/pipeline.py tests/test_ui_facade.py
git commit -m "feat(pipeline): Stufe-2/3A-Fassaden + NO_MATCH-Re-Export + ArticleInfo-Masse"
```

---

### Task 3: Import-Umstellung reports_page/report_detail auf pipeline-Bezüge

**Files:**
- Modify: `docodetect/ui_qt/admin/pages/reports_page.py` (Zeilen 25-27)
- Modify: `docodetect/ui_qt/admin/pages/report_detail.py` (Zeilen 19-21)

Genehmigt 2026-08-11 (Freigabe-Ergänzung 2). Kein Verhaltens-, nur
Bezugswechsel; die bestehenden Tests `test_admin_reports.py` decken beide
Module und bleiben unverändert (= der Nachweis, dass sich nichts ändert).

- [ ] **Step 1: reports_page.py** — aus

```python
from docodetect.pipeline import (load_saved_reports,
                                 report_predicted_article)
from docodetect.reporting import NO_MATCH
```

  wird

```python
from docodetect.pipeline import (NO_MATCH, load_saved_reports,
                                 report_predicted_article)
```

- [ ] **Step 2: report_detail.py** — aus

```python
from docodetect.matcher import MatchReport
from docodetect.pipeline import (format_measured, render_report_overlay,
                                 report_judgement)
```

  wird

```python
from docodetect.pipeline import (MatchReport, format_measured,
                                 render_report_overlay, report_judgement)
```

- [ ] **Step 3: Verifizieren (bestehende Tests, unverändert)**

Run: `.venv/bin/pytest tests/test_admin_reports.py -v`
Expected: PASS; danach
`grep -rn "docodetect.reporting\|docodetect.matcher" docodetect/ui_qt/` → leer

- [ ] **Step 4: Commit**

```bash
git add docodetect/ui_qt/admin/pages/reports_page.py docodetect/ui_qt/admin/pages/report_detail.py
git commit -m "refactor(admin): Typ- und Konstanten-Bezug ueber pipeline (Zugriffsweg)"
```

---

### Task 4: Analyse-Seite — Lauf im Worker, Historie, Artefakt-Betrachter

**Files:**
- Create: `docodetect/ui_qt/admin/pages/analysis_page.py` (LaufTab +
  AnalysisPage-Gerüst; BewertungsTab kommt in Task 5 in DIESELBE Datei)
- Test: Create `tests/test_admin_analysis.py`

**Interfaces:**
- Consumes: `pipeline.run_report_analysis`, `pipeline.list_analysis_runs`,
  `PipelineWorker` (vorhandenes Muster, seriell — Freigabe-Ergänzung 1).
- Produces:
  - `LaufTab(cfg, parent=None)` mit `quelle`, `run_id_feld`,
    `start_button`, `fortschritt` (indeterminater QProgressBar —
    `run_analysis` hat keinen Callback; Sektionen melden keinen
    Fortschritt), `status`, `historie` (QListWidget),
    `ungueltig_label`, Betrachter (`report_text`, `png_label`,
    `png_name`, `vor`/`zurueck`), `refresh_button`.
  - Methoden: `reload_historie()`, `starte_lauf()`, `_baue_job()`
    (Testnaht: Job ohne Thread aufrufbar), `_lauf_fertig(pfad)`,
    `_lauf_fehler(text)`, `zeige_lauf(info)`, `blaettern(delta)`;
    Testhilfe `werte() -> dict`.
  - `AnalysisPage(cfg, parent=None)` mit `tabs`, `lauf_tab`.
- Fehlerbild: Kopfzeile + Abhilfe-Text im `status`-Label (Muster
  Hauptfenster), nie Crash. Leerzustand Historie: Handlungsanleitung.
- Worker-Lebenszyklus wie Hauptfenster: EIN `self._worker`, Start-Button
  deaktiviert solange er läuft (seriell), Referenz erst nach
  `finished`-Signal freigeben.

- [ ] **Step 1: Fehlschlagende Tests schreiben** —
  `tests/test_admin_analysis.py` (vollständige Datei):

```python
"""Admin-Panel Stufe 2: Analyse-Lauf-Seite (Worker, Historie, Betrachter).

Qt offscreen, alles gegen tmp_path. Der Worker-Test nutzt einen
monkeypatchten Fassaden-Aufruf (schnell, deterministisch) und wartet
per processEvents-Schleife — kein sleep, kein zweiter Thread-Pfad."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(scope="module")
def qapp():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from docodetect.ui_qt.app import make_app
    return make_app()


def _cfg(tmp_path):
    return {
        "calibration": {
            "file": str(tmp_path / "calibration.json"),
            "background_file": str(tmp_path / "background.png"),
        },
        "paths": {"db_file": str(tmp_path / "db.sqlite3"),
                  "captures_dir": str(tmp_path / "captures")},
        "analysis": {"output_dir": str(tmp_path / "runs")},
        "matching": {"diameter_tolerance_mm": 6.0, "top_k": 3},
        "stage2": {"enabled": False},
    }


def _lauf(base, run_id, pngs=(), gueltig=True, inhalt="# Bericht\nZeile 2"):
    d = Path(base) / run_id
    d.mkdir(parents=True)
    (d / "report.md").write_text(inhalt, encoding="utf-8")
    if gueltig:
        (d / "metrics.json").write_text("{}", encoding="utf-8")
    # 1x1-PNG reicht dem Betrachter
    px = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00"
          b"\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx"
          b"\x9cc\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01\x87\xa1N\xe8\x00"
          b"\x00\x00\x00IEND\xaeB`\x82")
    for name in pngs:
        (d / name).write_bytes(px)
    return d


def test_historie_gueltig_und_ungueltig(qapp, tmp_path):
    from docodetect.ui_qt.admin.pages.analysis_page import LaufTab
    cfg = _cfg(tmp_path)
    _lauf(cfg["analysis"]["output_dir"], "lauf-a", pngs=("b.png", "a.png"))
    _lauf(cfg["analysis"]["output_dir"], "kaputt", gueltig=False)
    (Path(cfg["analysis"]["output_dir"]) / "leer").mkdir()
    tab = LaufTab(cfg)
    w = tab.werte()
    assert w["historie"] == ["lauf-a"]
    assert "ungültig, 2 Stück" in w["ungueltig"]


def test_historie_leerzustand(qapp, tmp_path):
    from docodetect.ui_qt.admin.pages.analysis_page import LaufTab
    tab = LaufTab(_cfg(tmp_path))
    w = tab.werte()
    assert w["historie"] == []
    assert w["ungueltig"] == ""
    assert "Noch keine Analyse-Läufe" in w["status"]


def test_betrachter_zeigt_report_und_blaettert(qapp, tmp_path):
    from docodetect.ui_qt.admin.pages.analysis_page import LaufTab
    cfg = _cfg(tmp_path)
    _lauf(cfg["analysis"]["output_dir"], "lauf-a", pngs=("b.png", "a.png"))
    tab = LaufTab(cfg)
    tab.historie.setCurrentRow(0)
    w = tab.werte()
    assert w["report_erste_zeile"] == "# Bericht"
    assert w["png"] == "a.png"            # alphabetisch, erstes zuerst
    tab.blaettern(1)
    assert tab.werte()["png"] == "b.png"
    tab.blaettern(1)                       # klemmt am Ende, kein Wrap
    assert tab.werte()["png"] == "b.png"
    tab.blaettern(-1)
    assert tab.werte()["png"] == "a.png"


def test_lauf_im_worker_aktualisiert_historie(qapp, tmp_path, monkeypatch):
    from docodetect.ui_qt.admin.pages import analysis_page as mod
    cfg = _cfg(tmp_path)

    def fake_run(cfg_, reports_dir=None, run_id=None):
        return _lauf(cfg_["analysis"]["output_dir"], run_id or "neu",
                     pngs=("x.png",))

    monkeypatch.setattr(mod, "run_report_analysis", fake_run)
    tab = mod.LaufTab(cfg)
    tab.run_id_feld.setText("wlauf")
    tab.starte_lauf()
    assert not tab.start_button.isEnabled()      # seriell: gesperrt
    ende = time.monotonic() + 10.0
    while tab._worker is not None and time.monotonic() < ende:
        qapp.processEvents()
    assert tab._worker is None, "Worker nicht fertig geworden"
    w = tab.werte()
    assert "wlauf" in w["status"]
    assert w["historie"] == ["wlauf"]
    assert tab.start_button.isEnabled()


def test_lauf_fehler_zeigt_text_statt_crash(qapp, tmp_path):
    from docodetect.ui_qt.admin.pages.analysis_page import LaufTab
    tab = LaufTab(_cfg(tmp_path))
    tab._lauf_fehler("kein Plattenplatz")
    w = tab.werte()
    assert "Analyse-Lauf fehlgeschlagen" in w["status"]
    assert "kein Plattenplatz" in w["status"]
    assert tab.start_button.isEnabled()
```

- [ ] **Step 2: Fehlschlag verifizieren**

Run: `.venv/bin/pytest tests/test_admin_analysis.py -v`
Expected: ERROR `ModuleNotFoundError: ...pages.analysis_page`

- [ ] **Step 3: Implementieren** — `analysis_page.py` mit Modul-Docstring
  (Worker-Begründung: Sekunden statt Millisekunden, Freigabe-Ergänzung 1;
  Fortschritt indeterminat, weil `run_analysis` keinen Callback hat und
  ein solcher ein weiterer analysis.py-Eingriff wäre), `LaufTab` wie in
  den Interfaces, `AnalysisPage` mit QTabWidget (Tab „Analyse-Lauf";
  „Bewertungs-Übersicht" folgt in Task 5). Kernpunkte:
  - `starte_lauf()`: `PipelineWorker(self._baue_job(), self)`,
    `finished_ok→_lauf_fertig`, `failed→_lauf_fehler`, Button sperren,
    Busy-Bar an; `_baue_job()` bindet cfg/Quelle/run_id als Closure —
    die Fassade konstruiert alles Weitere IM Worker-Thread (SQLite-
    Affinität).
  - `_lauf_fertig`: Busy aus, Button frei, Status
    „Lauf fertig: <run_id> — <pfad>", `reload_historie()`, neuen Lauf
    selektieren (falls gültig; ein Lauf ohne metrics.json — z. B. leerer
    Quellordner — erscheint als ungültig: Status weist darauf hin).
  - Worker-Referenz in `_worker`, auf `finished` → `None` setzen
    (Signal-Reihenfolge: `finished_ok`/`failed` kommen VOR `finished`).
  - Betrachter: PNGs = `sorted(info.path.glob("*.png"))` (Pfad kam aus
    der Fassade — keine eigene Config-Pfadkonstruktion), `report.md`
    als Text; Historie-Zeile „<run_id> — Dateizeit TT.MM.JJJJ HH:MM".

- [ ] **Step 4: Tests grün verifizieren**

Run: `.venv/bin/pytest tests/test_admin_analysis.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add docodetect/ui_qt/admin/pages/analysis_page.py tests/test_admin_analysis.py
git commit -m "feat(admin): Analyse-Lauf-Seite — Worker, Historie, Artefakt-Betrachter (Stufe 2)"
```

---

### Task 5: Bewertungs-Übersicht (zweiter Tab der Analyse-Sektion)

**Files:**
- Modify: `docodetect/ui_qt/admin/pages/analysis_page.py` (BewertungsTab
  + Einhängen in AnalysisPage)
- Modify: `tests/test_admin_analysis.py`

**Interfaces:**
- `BewertungsTab(cfg, parent=None)` mit `reload()`, Tabelle
  (Artikel | Richtig | Falsch | unbewertet | Quote), `gesamt_label`;
  Testhilfen `zeilen() -> list[dict]`, `gesamt_text() -> str`.
- Reine Zählung auf Anzeige-Ebene über `load_saved_reports` +
  `report_judgement` + `report_predicted_article` (Spec Punkt 7, keine
  Kennzahlen-Nachrechnung). Gruppiert nach VORHERGESAGTEM Artikel;
  `NO_MATCH` als eigener Zustand „— kein Kandidat". Quote = Richtig /
  (Richtig + Falsch), „–" ohne bewertete. Synchron geladen (identisch
  zur Reports-Sektion: 9 ms für den Bestand, Befund 2026-08-11).

- [ ] **Step 1: Fehlschlagende Tests** — an `tests/test_admin_analysis.py`
  anhängen (Report-Helfer im Stil von `test_admin_reports._bestand`):

```python
def _rep(decision, verdict=None, artikel=None):
    from docodetect.pipeline import MatchReport
    from docodetect.matcher import CandidateReport
    cands = []
    if artikel:
        cands = [CandidateReport(
            article_number=artikel, name=artikel, nominal_size_mm=180.0,
            height_mm=0.0, corrected_diameter_mm=181.0,
            geometry_error_mm=1.0, has_references=True, n_shots=9,
            features=[], log_score=-0.4, posterior=0.9, max_abs_z=1.0)]
    return MatchReport(decision=decision, message="", verdict=verdict,
                       candidates=cands)


def test_bewertungsuebersicht_zaehlt_je_artikel(qapp, tmp_path):
    from docodetect.ui_qt.admin.pages.analysis_page import BewertungsTab
    cfg = _cfg(tmp_path)
    caps = Path(cfg["paths"]["captures_dir"])
    caps.mkdir(parents=True)
    daten = [("a.json", _rep("accept", "correct", "A-1")),
             ("b.json", _rep("accept", "wrong", "A-1")),
             ("c.json", _rep("ambiguous", None, "B-2")),
             ("d.json", _rep("reject", "correct", None))]   # NO_MATCH
    for name, rep in daten:
        (caps / name).write_text(rep.to_json(), encoding="utf-8")
    tab = BewertungsTab(cfg)
    zeilen = {z["artikel"]: z for z in tab.zeilen()}
    assert zeilen["A-1"] == {"artikel": "A-1", "richtig": 1, "falsch": 1,
                             "unbewertet": 0, "quote": "50 %"}
    assert zeilen["B-2"]["unbewertet"] == 1
    assert zeilen["B-2"]["quote"] == "–"
    assert "— kein Kandidat" in zeilen          # NIE als Artikelnummer
    assert "NO_MATCH" not in zeilen
    assert "2 von 3 richtig" in tab.gesamt_text()


def test_bewertungsuebersicht_leerzustand(qapp, tmp_path):
    from docodetect.ui_qt.admin.pages.analysis_page import BewertungsTab
    tab = BewertungsTab(_cfg(tmp_path))
    assert tab.zeilen() == []
    assert "Keine Reports" in tab.gesamt_text()


def test_analysis_page_hat_beide_tabs(qapp, tmp_path):
    from docodetect.ui_qt.admin.pages.analysis_page import AnalysisPage
    page = AnalysisPage(_cfg(tmp_path))
    assert page.tabs.count() == 2
    assert page.tabs.tabText(0) == "Analyse-Lauf"
    assert page.tabs.tabText(1) == "Bewertungs-Übersicht"
```

- [ ] **Step 2: Fehlschlag verifizieren** (ImportError `BewertungsTab`)

- [ ] **Step 3: Implementieren** — `BewertungsTab` (Aggregation als reine
  Funktion `_aggregiere(eintraege) -> tuple[list[dict], str]` im Modul,
  Tabelle read-only, Refresh-Knopf) und `AnalysisPage.tabs.addTab(...)`.

- [ ] **Step 4: Tests grün**, Run wie Task 4.

- [ ] **Step 5: Commit**

```bash
git add docodetect/ui_qt/admin/pages/analysis_page.py tests/test_admin_analysis.py
git commit -m "feat(admin): Bewertungs-Uebersicht als zweiter Analyse-Tab (Stufe 2)"
```

---

### Task 6: Artikel-Seite (Stufe 3 Teil A)

**Files:**
- Create: `docodetect/ui_qt/admin/pages/articles_page.py`
- Test: Create `tests/test_admin_articles.py`

**Interfaces:**
- Consumes: `pipeline.list_articles` (erweitert), `pipeline.nominal_size_mm`,
  `cfg["matching"]["diameter_tolerance_mm"]` (Anzeige-Ebene, wie
  `result_card.py:87`).
- Produces: `ArticlesPage(cfg, parent=None)` mit Tabelle
  (Artikelnummer | Name | Kategorie | Referenzen | Ø | Breite | Tiefe |
  Höhe | Vorfilter-Nominal | Toleranzband), `kopf_label`
  („n Artikel · Vorfilter-Toleranz ±x mm"), `refresh_button`, Testhilfen
  `zeilen()`, `kopf_text()`. Fehlende Maße: „—"; Band =
  „nominal−tol – nominal+tol" mit Dezimalkomma. Leerzustand mit
  Handlungsanleitung. Synchron (DB-Lesezugriff wie Status-Seite).

- [ ] **Step 1: Fehlschlagende Tests** — `tests/test_admin_articles.py`
  (qapp-Fixture + `_cfg` wie test_admin_analysis, dann):

```python
def _db_mit_artikeln(cfg):
    from docodetect.database import Article, Database
    db = Database(cfg)
    db.init_schema()
    db.create_article(Article(article_number="T-270", name="Teller 27",
                              category="Teller", diameter_mm=270.0,
                              width_mm=None, depth_mm=None, height_mm=25.0,
                              color_desc=None, notes=None))
    db.create_article(Article(article_number="LOEFFEL-1", name="Loeffel",
                              category="Besteck", diameter_mm=None,
                              width_mm=186.9, depth_mm=45.0, height_mm=20.0,
                              color_desc=None, notes=None))
    db.create_article(Article(article_number="X-0", name="Ohne Masse",
                              category=None, diameter_mm=None, width_mm=None,
                              depth_mm=None, height_mm=None,
                              color_desc=None, notes=None))
    db.close()


def test_artikelliste_wirksames_nominal_und_band(qapp, tmp_path):
    from docodetect.ui_qt.admin.pages.articles_page import ArticlesPage
    cfg = _cfg(tmp_path)
    _db_mit_artikeln(cfg)
    page = ArticlesPage(cfg)
    zeilen = {z["artikelnummer"]: z for z in page.zeilen()}
    assert zeilen["LOEFFEL-1"]["nominal"] == "186,9"       # max, nie hypot
    assert zeilen["LOEFFEL-1"]["band"] == "180,9 – 192,9"
    assert zeilen["T-270"]["nominal"] == "270,0"
    assert zeilen["T-270"]["band"] == "264,0 – 276,0"
    assert zeilen["X-0"]["nominal"] == "—"
    assert zeilen["X-0"]["band"] == "—"
    assert zeilen["LOEFFEL-1"]["referenzen"] == "0"
    assert "3 Artikel" in page.kopf_text()
    assert "±6,0 mm" in page.kopf_text()


def test_artikelliste_leerzustand_ohne_db(qapp, tmp_path):
    from docodetect.ui_qt.admin.pages.articles_page import ArticlesPage
    page = ArticlesPage(_cfg(tmp_path))
    assert page.zeilen() == []
    assert "Keine Artikel" in page.kopf_text()
```

- [ ] **Step 2: Fehlschlag verifizieren** (ModuleNotFoundError)

- [ ] **Step 3: Implementieren** — `articles_page.py`; Nominal NUR über
  `pipeline.nominal_size_mm` (Freigabe-Ergänzung 3 — keine zweite
  Implementierung), Formatierung Dezimalkomma, eine Nachkommastelle.

- [ ] **Step 4: Tests grün**: `.venv/bin/pytest tests/test_admin_articles.py -v`

- [ ] **Step 5: Commit**

```bash
git add docodetect/ui_qt/admin/pages/articles_page.py tests/test_admin_articles.py
git commit -m "feat(admin): Artikelliste mit wirksamem Vorfilter-Nominal (Stufe 3 Teil A)"
```

---

### Task 7: AdminWindow-Verdrahtung

**Files:**
- Modify: `docodetect/ui_qt/admin/admin_window.py` (Analyse- und
  Artikel-Platzhalter durch echte Seiten ersetzen; nur „Diagnose" bleibt
  Platzhalter)
- Modify: `tests/test_admin_ui.py` (`_admin_cfg` um `analysis`/`matching`
  ergänzen — Isolation gegen `reports/analysis/` des Repos; neuer Test)

- [ ] **Step 1: Fehlschlagenden Test schreiben** — an `test_admin_ui.py`
  anhängen und `_admin_cfg` erweitern:

```python
        "analysis": {"output_dir": str(tmp_path / "runs")},
        "matching": {"diameter_tolerance_mm": 6.0, "top_k": 3},
```

```python
def test_admin_window_stufe2_seiten_real(qapp, tmp_path):
    from docodetect.ui_qt.admin.admin_window import AdminWindow
    from docodetect.ui_qt.admin.pages.analysis_page import AnalysisPage
    from docodetect.ui_qt.admin.pages.articles_page import ArticlesPage
    win = AdminWindow(_admin_cfg(tmp_path), camera_status=lambda: "Demo")
    assert win.sidebar.count() == 5
    assert isinstance(win.analysis_page, AnalysisPage)
    assert isinstance(win.articles_page, ArticlesPage)
    assert win.stack.widget(2) is win.analysis_page
    assert win.stack.widget(3) is win.articles_page
    win.close()
```

- [ ] **Step 2: Fehlschlag verifizieren** (`AttributeError: analysis_page`)

- [ ] **Step 3: Implementieren** — `admin_window.py`: Importe + Seiten
  statt der beiden Platzhalter, `self.analysis_page`/`self.articles_page`.

- [ ] **Step 4: Tests grün**: `.venv/bin/pytest tests/test_admin_ui.py -v`

- [ ] **Step 5: Commit**

```bash
git add docodetect/ui_qt/admin/admin_window.py tests/test_admin_ui.py
git commit -m "feat(admin): Analyse- und Artikel-Seite im Admin-Fenster verdrahtet"
```

---

### Task 8: Abschluss-Regime (blockierender Melde-Punkt = Abschlussmeldung)

**Files:** keine Code-Änderungen. Vollausgaben nach `~/Documents/tmp/`.

- [ ] **Step 1: Auswahl-Testläufe** — UI-Module EINZELN, Vollausgabe in
  Datei; danach der Qt-freie Block:

```bash
OUT="$HOME/Documents/tmp/2026-08-11-stufe2-tests.txt"; : > "$OUT"
for m in tests/test_ui_*.py tests/test_camera_worker.py \
         tests/test_demo_scenes.py tests/test_demo_seed_state.py \
         tests/test_icon_hidpi.py tests/test_admin_ui.py \
         tests/test_admin_reports.py tests/test_admin_analysis.py \
         tests/test_admin_articles.py; do
    echo "== $m ==" >> "$OUT"; .venv/bin/pytest "$m" >> "$OUT" 2>&1 || true
done
.venv/bin/pytest tests/test_pipeline_synthetic.py tests/test_enroll_session*.py \
    tests/test_admin_auth.py tests/test_analysis.py tests/test_ui_facade.py \
    >> "$OUT" 2>&1
grep -h "passed\|failed\|error" "$OUT"
```

- [ ] **Step 2: Dauer-Messung** (Freigabe-Ergänzung 1) — EIN Lauf über den
  echten Bestand via Fassade (Ausgabebereich `reports/analysis/`,
  read-only an Quelle/DB), Dauer mit in die Abschlussmeldung:

```bash
time .venv/bin/python -c "from docodetect.config import load_config; \
from docodetect.pipeline import run_report_analysis; \
print(run_report_analysis(load_config(), run_id='stufe2-abnahme'))"
```

- [ ] **Step 3: Volle Suite** (seriell; Erwartung 825 + n passed,
  2 skipped, 2 deselected, ~10 min) + **corpus-run-Doppel-Check**
  (`--tier 1 --check` und `--tier 2 --check`, Erwartung: keine
  Abweichung, false_accept_rate 0 von 44) — Vollausgaben in Dateien.

- [ ] **Step 4: Abnahme-Stichprobe** — Panel-Werte per Offscreen-Instanz
  der Seiten gegen die ECHTE Config abgelesen (rein lesend), verglichen
  mit CLI/jq: Historie gegen `ls`+Kriteriums-Check, Bewertungs-Zählung
  gegen `jq`-Aggregat über die Report-JSONs, Artikel-Nominale gegen
  `list-articles`/`sqlite3`-ro + händisches max(width, depth),
  Lauf-Artefakte gegen den CLI-`analyze`-Lauf. Stammdaten-Regel
  (CLAUDE.md „Messgrößen", README:49-54, matcher-Docstring) in der
  Meldung zitieren.

- [ ] **Step 5: Abschlussmeldung und STOPP** — Inhalt gemäß Auftrag
  (Roh-Summaries, Suite, Korpus, Stichproben-Tabelle, Abweichungsliste,
  Commit-Liste, Diff-Umfang) — dann auf Freigabe warten. Kein Merge,
  kein Push.
