# Analyse-Export im Admin-Panel — Implementierungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans
> to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Export-Knöpfe auf der Analyse-Seite: der aktuell ausgewählte
(gültige) Lauf wird als Ordner-Kopie ODER ZIP an einen je Export frei
gewählten Ort AUSSERHALB des Projekts exportiert. Freigabe 2026-08-11.

**Abgrenzung (kommt so in die Spec):** Das ist NICHT `--publish`.
`publish_run` kopiert Aggregate ins **versionierte** `reports/archive`
(config-aufgelöst, CLI-only, Spec Punkt 6). Der Export ist eine private
Komplett-Kopie an einen frei gewählten Ort. Wiederverwendungs-Befund
2026-08-11: `analysis.publish_run` und `corpus/review.publish_review`
kopieren nur Top-Level-Dateien in ein config-aufgelöstes Ziel — für
freie externe Ziele + ZIP nicht passend, kein Umbau; übernommen wird
ihre Semantik „existiert bereits → Fehler, nie überschreiben".
`shutil.make_archive`/`copytree` werden erstmalig genutzt.

**Architecture:** Kopier-/ZIP-Logik liegt in einer additiven Fassade
`pipeline.export_analysis_run` — die Seite ruft nur und zeigt Fehlertexte
(Muster `_lauf_fehler`). Harte Auflage: aufgelöster Zielpfad
(`Path.resolve()`, folgt Symlinks — deckt den Symlink-Fall billig mit ab)
darf nicht im aufgelösten `project_root()` liegen; sonst Ablehnung mit
Hinweistext. Sync/Worker wird anhand der Dauer-Messung am echten Lauf
entschieden (<200 ms → synchron, Präzedenzfall Report-Laden; sonst
PipelineWorker) und in der Spec begründet.

## Global Constraints

- **Branch `feature/analyse-export`**, Commit je Task, kein Merge/Push.
- **Genehmigte Eingriffe in Bestandscode (abschließend):**
  1. `pipeline.py`: additive Fassade `export_analysis_run`.
  2. `analysis_page.py` (`LaufTab`): zwei Export-Knöpfe + Handler +
     Dialog-Nähte (additiv; bestehende Methoden unverändert).
  3. Spec: Vermerk Export ≠ publish + Sync-Begründung.
- TDD, Fehlschlag aus dem richtigen Grund; Python-3.9-Floor
  (PEP-604 nur mit `from __future__ import annotations` — neue Module
  haben ihn; `test_ui_facade.py` hat ihn NICHT).
- Tests nur gegen tmp_path; UI-Module einzeln je pytest-Aufruf.
- Fehlerfälle definiert und getestet: Ziel im Projekt-Root (auch via
  Symlink), Ziel existiert, Ziel nicht beschreibbar, Quelle verschwunden/
  ungültig, Abbruch im Dialog.
- Volle Suite + corpus-run-Doppel-Check EINMAL am Ende (Merge-Gate).

---

### Task 1: Fassade `pipeline.export_analysis_run`

**Files:**
- Modify: `docodetect/pipeline.py` (nach `nominal_size_mm`)
- Test: `tests/test_ui_facade.py` (ans Dateiende)

**Interfaces:**
- `export_analysis_run(run_dir, ziel, als_zip=False) -> Path` — prüft
  Quelle (report.md UND metrics.json — Listbarkeits-Kriterium, fängt
  auch „Lauf verschwand zwischen Auswahl und Export"), normalisiert bei
  ZIP die Endung auf `.zip` VOR den Zielprüfungen, lehnt Ziel im
  aufgelösten Projekt-Root ab, lehnt existierendes Ziel ab
  (publish-Präzedenz), kopiert per `shutil.copytree` bzw. zippt per
  `shutil.make_archive`. Kein cfg-Parameter — es gibt keine
  Config-Pfadauflösung; `project_root` wird IN der Funktion importiert
  (monkeypatch-fähig, wie `resolve` es intern macht). Guard-Verstöße:
  `ValueError` mit deutschem Hinweistext; IO-Fehler (`OSError`)
  propagieren mit System-Text — die Seite zeigt beide als Text.

- [ ] **Step 1: Fehlschlagende Tests** — ans Ende von
  `tests/test_ui_facade.py`:

```python
# ---------- Export von Analyse-Läufen (Freigabe 2026-08-11) ----------

import os  # noqa: E402
import zipfile  # noqa: E402

from docodetect.pipeline import export_analysis_run  # noqa: E402


def _mini_lauf(tmp_path, name="lauf"):
    d = tmp_path / name
    d.mkdir(parents=True)
    (d / "report.md").write_text("# Bericht", encoding="utf-8")
    (d / "metrics.json").write_text("{}", encoding="utf-8")
    (d / "a.png").write_bytes(b"png-a")
    (d / "b.csv").write_text("x;y", encoding="utf-8")
    return d


def test_export_ordner_kopiert_komplett(tmp_path):
    src = _mini_lauf(tmp_path)
    ziel = export_analysis_run(src, tmp_path / "raus" / "kopie")
    assert sorted(p.name for p in ziel.iterdir()) == [
        "a.png", "b.csv", "metrics.json", "report.md"]
    assert (ziel / "a.png").read_bytes() == b"png-a"


def test_export_zip_enthaelt_alles_und_ergaenzt_endung(tmp_path):
    src = _mini_lauf(tmp_path)
    ziel = export_analysis_run(src, tmp_path / "raus" / "archiv",
                               als_zip=True)
    assert ziel.name == "archiv.zip"
    with zipfile.ZipFile(ziel) as z:
        assert sorted(z.namelist()) == ["a.png", "b.csv",
                                        "metrics.json", "report.md"]


def test_export_ziel_im_projekt_wird_abgelehnt(tmp_path, monkeypatch):
    import docodetect.config as cfgmod
    projekt = tmp_path / "projekt"
    projekt.mkdir()
    monkeypatch.setattr(cfgmod, "project_root", lambda: projekt)
    src = _mini_lauf(tmp_path)
    with pytest.raises(ValueError, match="Projektverzeichnis"):
        export_analysis_run(src, projekt / "reports" / "kopie")


def test_export_symlink_ins_projekt_wird_abgelehnt(tmp_path, monkeypatch):
    import docodetect.config as cfgmod
    projekt = tmp_path / "projekt"
    (projekt / "unter").mkdir(parents=True)
    monkeypatch.setattr(cfgmod, "project_root", lambda: projekt)
    link = tmp_path / "harmlos"
    link.symlink_to(projekt / "unter")
    src = _mini_lauf(tmp_path)
    with pytest.raises(ValueError, match="Projektverzeichnis"):
        export_analysis_run(src, link / "kopie")


def test_export_ziel_existiert_nie_ueberschreiben(tmp_path):
    src = _mini_lauf(tmp_path)
    ziel = tmp_path / "raus" / "kopie"
    ziel.mkdir(parents=True)
    with pytest.raises(ValueError, match="existiert bereits"):
        export_analysis_run(src, ziel)


def test_export_quelle_ungueltig_oder_verschwunden(tmp_path):
    kaputt = tmp_path / "kaputt"
    kaputt.mkdir()
    (kaputt / "report.md").write_text("x", encoding="utf-8")  # ohne metrics
    with pytest.raises(ValueError, match="gültiger Analyse-Lauf"):
        export_analysis_run(kaputt, tmp_path / "raus1")
    with pytest.raises(ValueError, match="gültiger Analyse-Lauf"):
        export_analysis_run(tmp_path / "wegga", tmp_path / "raus2")


def test_export_ziel_nicht_beschreibbar(tmp_path):
    src = _mini_lauf(tmp_path)
    gesperrt = tmp_path / "gesperrt"
    gesperrt.mkdir()
    os.chmod(gesperrt, 0o500)
    try:
        with pytest.raises(OSError):
            export_analysis_run(src, gesperrt / "kopie")
    finally:
        os.chmod(gesperrt, 0o700)
```

- [ ] **Step 2: Fehlschlag verifizieren** — Run:
  `.venv/bin/pytest tests/test_ui_facade.py -k export -v`
  Expected: `ImportError: cannot import name 'export_analysis_run'`

- [ ] **Step 3: Implementieren** — in `pipeline.py` nach
  `nominal_size_mm`:

```python
def export_analysis_run(run_dir: str | Path, ziel: str | Path,
                        als_zip: bool = False) -> Path:
    """Analyse-Lauf KOMPLETT an einen frei gewählten Ort AUSSERHALB des
    Projekts exportieren (Ordner-Kopie oder ZIP). Freigabe 2026-08-11.

    Bewusst NICHT --publish: publish kopiert Aggregate ins VERSIONIERTE
    reports/archive (CLI-only, Spec Punkt 6) — der Export ist eine
    private Komplett-Kopie. Regeln:
    - Quelle muss ein gültiger Lauf sein (report.md UND metrics.json,
      Listbarkeits-Kriterium) — fängt auch den zwischen Auswahl und
      Export verschwundenen Ordner ab.
    - Ziel im aufgelösten Projekt-Root ist gesperrt: der Export würde
      als vermeintlicher Lauf in der Historie auftauchen oder den
      Git-Status verschmutzen. Path.resolve() folgt Symlinks — der
      Symlink-Umweg ins Projekt ist damit mit abgedeckt.
    - Ziel existiert: Fehler, nie stumm überschreiben (Semantik von
      publish_run/publish_review).
    Guard-Verstöße: ValueError mit Hinweistext; IO-Fehler (OSError,
    z. B. Ziel nicht beschreibbar) propagieren — die Seite zeigt beide
    als Fehlertext."""
    from .config import project_root
    src = Path(run_dir)
    if not ((src / "report.md").is_file()
            and (src / "metrics.json").is_file()):
        raise ValueError("Kein gültiger Analyse-Lauf (report.md und "
                         f"metrics.json erwartet): {src}")
    ziel = Path(ziel).expanduser().resolve()
    if als_zip and ziel.suffix.lower() != ".zip":
        ziel = ziel.with_name(ziel.name + ".zip")
    wurzel = Path(project_root()).resolve()
    if ziel == wurzel or wurzel in ziel.parents:
        raise ValueError("Export ins Projektverzeichnis ist gesperrt "
                         f"({wurzel}) — bitte einen Ort ausserhalb "
                         "wählen.")
    if ziel.exists():
        raise ValueError(f"Ziel existiert bereits: {ziel}. Export "
                         "überschreibt nie.")
    if als_zip:
        ziel.parent.mkdir(parents=True, exist_ok=True)
        return Path(shutil.make_archive(str(ziel)[:-len(".zip")], "zip",
                                        root_dir=src))
    return Path(shutil.copytree(src, ziel))
```

- [ ] **Step 4: Grün verifizieren** — Run:
  `.venv/bin/pytest tests/test_ui_facade.py -v` — Expected: PASS (alle).

- [ ] **Step 5: Commit**

```bash
git add docodetect/pipeline.py tests/test_ui_facade.py
git commit -m "feat(pipeline): export_analysis_run — Lauf-Export als Kopie oder ZIP"
```

---

### Task 2: Export-Knöpfe auf der Analyse-Seite

**Files:**
- Modify: `docodetect/ui_qt/admin/pages/analysis_page.py` (`LaufTab`)
- Modify: `tests/test_admin_analysis.py`

**Interfaces:**
- `LaufTab.export_ordner_button` / `export_zip_button` — nur aktiv,
  wenn ein Lauf ausgewählt ist (die Historie listet ohnehin nur gültige;
  Kriterium damit erfüllt). Zielwahl je Export über Datei-Dialog, kein
  gespeicherter Default.
- Dialog-Nähte (testbar per monkeypatch): `_frage_ordner_ziel() -> str`
  (Elternordner wählen, Ziel = <eltern>/<run_id>; "" = Abbruch) und
  `_frage_zip_ziel(vorschlag) -> str` (getSaveFileName, Filter
  `*.zip`, `DontConfirmOverwrite` — die Überschreib-Entscheidung trifft
  die Fassade: nie).
- `_export(als_zip)`: ruft `export_analysis_run`; Erfolg →
  `status` „Export fertig: <pfad>"; jeder Fehler → `status`
  „Export fehlgeschlagen: <text>" (kein Crash).

- [ ] **Step 1: Fehlschlagende Tests** — an `tests/test_admin_analysis.py`
  anhängen:

```python
# ---------- Export (Freigabe 2026-08-11) ----------

def test_export_knoepfe_erst_mit_auswahl_aktiv(qapp, tmp_path):
    from docodetect.ui_qt.admin.pages.analysis_page import LaufTab
    cfg = _cfg(tmp_path)
    _lauf(cfg["analysis"]["output_dir"], "lauf-a")
    tab = LaufTab(cfg)
    assert not tab.export_ordner_button.isEnabled()
    assert not tab.export_zip_button.isEnabled()
    tab.historie.setCurrentRow(0)
    assert tab.export_ordner_button.isEnabled()
    assert tab.export_zip_button.isEnabled()


def test_export_ordner_und_zip_ueber_dialognaht(qapp, tmp_path, monkeypatch):
    import zipfile
    from docodetect.ui_qt.admin.pages.analysis_page import LaufTab
    cfg = _cfg(tmp_path)
    _lauf(cfg["analysis"]["output_dir"], "lauf-a", pngs=("x.png",))
    tab = LaufTab(cfg)
    tab.historie.setCurrentRow(0)
    ziel_eltern = tmp_path / "raus"
    ziel_eltern.mkdir()
    monkeypatch.setattr(tab, "_frage_ordner_ziel",
                        lambda: str(ziel_eltern / "lauf-a"))
    tab._export(als_zip=False)
    assert "Export fertig" in tab.werte()["status"]
    assert sorted(p.name for p in (ziel_eltern / "lauf-a").iterdir()) == [
        "metrics.json", "report.md", "x.png"]
    monkeypatch.setattr(tab, "_frage_zip_ziel",
                        lambda vorschlag: str(ziel_eltern / "lauf-a.zip"))
    tab._export(als_zip=True)
    assert "Export fertig" in tab.werte()["status"]
    with zipfile.ZipFile(ziel_eltern / "lauf-a.zip") as z:
        assert sorted(z.namelist()) == ["metrics.json", "report.md",
                                        "x.png"]


def test_export_projekt_root_wird_abgelehnt_mit_text(qapp, tmp_path,
                                                     monkeypatch):
    from docodetect.config import project_root
    from docodetect.ui_qt.admin.pages.analysis_page import LaufTab
    cfg = _cfg(tmp_path)
    _lauf(cfg["analysis"]["output_dir"], "lauf-a")
    tab = LaufTab(cfg)
    tab.historie.setCurrentRow(0)
    verboten = str(Path(project_root()) / "reports" / "export-test")
    monkeypatch.setattr(tab, "_frage_ordner_ziel", lambda: verboten)
    tab._export(als_zip=False)
    w = tab.werte()
    assert "Export fehlgeschlagen" in w["status"]
    assert "Projektverzeichnis" in w["status"]
    assert not Path(verboten).exists()


def test_export_abbruch_im_dialog_aendert_nichts(qapp, tmp_path,
                                                 monkeypatch):
    from docodetect.ui_qt.admin.pages.analysis_page import LaufTab
    cfg = _cfg(tmp_path)
    _lauf(cfg["analysis"]["output_dir"], "lauf-a")
    tab = LaufTab(cfg)
    tab.historie.setCurrentRow(0)
    vorher = tab.werte()["status"]
    monkeypatch.setattr(tab, "_frage_ordner_ziel", lambda: "")
    tab._export(als_zip=False)
    assert tab.werte()["status"] == vorher
```

- [ ] **Step 2: Fehlschlag verifizieren** — Run:
  `.venv/bin/pytest tests/test_admin_analysis.py -k export -v`
  Expected: `AttributeError: ... 'export_ordner_button'`

- [ ] **Step 3: Implementieren** — `LaufTab`: Import
  `QFileDialog` + `export_analysis_run`; unter dem Refresh-Knopf eine
  Export-Zeile mit beiden Knöpfen (disabled); in
  `historie.currentRowChanged` zusätzlich `_update_export_buttons`;
  Nähte + `_export` wie in den Interfaces. `reload_historie()` setzt
  die Knöpfe zurück (Auswahl weg → inaktiv).

- [ ] **Step 4: Grün + Nachbarn** — Run:
  `.venv/bin/pytest tests/test_admin_analysis.py -v`
  Expected: PASS (alle, inkl. Stufe-2-Tests).

- [ ] **Step 5: Commit**

```bash
git add docodetect/ui_qt/admin/pages/analysis_page.py tests/test_admin_analysis.py
git commit -m "feat(admin): Export-Knoepfe fuer Analyse-Laeufe (Ordner/ZIP)"
```

---

### Task 3: Dauer-Messung + Spec-Vermerk

- [ ] **Step 1: Messen** — Kopie und ZIP des echten Laufs
  `reports/analysis/stufe2-abnahme` (35 Artefakte) nach
  `~/Documents/tmp/`, je 3 Wiederholungen, `time.perf_counter`.
  Entscheidung: <200 ms → synchron bleibt (Präzedenzfall Report-Laden,
  9 ms); sonst Umbau auf PipelineWorker (dann eigener Task, Melden
  nicht nötig — der Plan sieht beide Wege vor).
- [ ] **Step 2: Spec-Vermerk** (Punkt 6, Revision): Export ≠ publish
  (Kopie an frei gewählten Ort, publish bleibt CLI-only versioniert),
  Projekt-Root-Sperre, nie überschreiben, Sync-Begründung MIT der
  gemessenen Zahl.
- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-08-08-admin-panel-design.md
git commit -m "docs(spec): Export von Analyse-Laeufen — Abgrenzung zu publish, Root-Sperre, Messung"
```

---

### Task 4: Abschluss-Regime

- [ ] Auswahl-Testläufe: `test_admin_analysis.py` einzeln (UI-Schleife),
  `test_ui_facade.py` im Qt-freien Aufruf; danach die übrigen
  UI-Module einzeln (Regime wie Stufe 2), Vollausgabe nach
  `~/Documents/tmp/`.
- [ ] Volle Suite (Erwartung 844 + n passed, 2 skipped, 2 deselected)
  + corpus-run `--tier 1 --check` und `--tier 2 --check`
  (Erwartung: OK, false_accept_rate 0 von 44) — Merge-Gate.
- [ ] Abnahme-Stichprobe: echter Export (Ordner + ZIP) nach
  `~/Documents/tmp/`, Vergleich gegen Quelle mit
  `diff -r` bzw. Entpacken + `shasum -a 256` (Dateizahl und
  Prüfsummen, Befehle in der Meldung); Nachweis Root-Sperre mit echtem
  Ziel unter `reports/`.
- [ ] Abschlussmeldung, dann STOPP — Merge/Push erst nach Freigabe.
