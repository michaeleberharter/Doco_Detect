# Admin-Panel Stufe 4 + Stufe 3 Teil B1 — Implementierungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans
> to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Stufe 4 vollständig (Spec Abschnitt 6, Punkte 10–13:
Segmentierungs-Test, Config-Ansicht read-only, Kamera-Diagnose,
Session-Aktionen) plus Stufe 3 **Teil B1**: Referenz-Kennzahlen aus
`reference_stats` auf der Artikelseite — ohne Bilder. Freigabe 2026-08-11.

**Korpus-Referenzpunkt:** vor dem ersten Code auf dem heutigen main
gemessen (Ergebnis in der Abschlussmeldung neben dem Endergebnis) — Stufe 4
ist die erste Stufe, die den Messpfad auslöst und Bestand verschiebt.

**Ausdrücklich NICHT gebaut:** Löschen (`delete-article`/-`references`,
Spec Abschnitt 7 — keine cli.py-Extraktion), Diagnoseblätter/Bilder
(Teil B2, nach Neu-Enrollment; `image_path` 334/359 NULL, 2026-08-11
erneut verifiziert), Duplikat-/Nachbarschaftsinfo (Befund unten), Stufe 5.

## Investigations-Befunde (2026-08-11, Grundlage dieses Plans)

- **`reference_stats`-Schema:** eine Zeile je Artikel:
  `article_number` (PK), `stats_json`, `updated_unix`. `stats_json` =
  `{n_shots, scalar_mean{diameter_mm,circularity,solidity},
  scalar_std{...}, proto{5 Vektoren}, proto_std{delta_e_center,
  delta_e_rim, hist_center, hist_rim, hu_log}}`. Lese-API existiert:
  `Database.stats_for(article_number) -> EnrollmentStats | None`
  (`database.py:349`; Dataclass `features.py:329`). `updated_unix` hat
  KEINEN Getter — wird bewusst weggelassen statt einen DB-Eingriff zu
  machen (Abschlussmeldung).
- **`MIN_N = 10`** ist Modul-Konstante `floor_analysis.py:59` — Bezug für
  die UI über eine lazy pipeline-Fassade `min_shots_floor()` (kein
  floor_analysis-Import beim pipeline-Modulimport).
- **`scripts/duplikat_scan.py`:** rechnet Breitenprofil-d/σ **auf den
  gespeicherten Referenz-PNGs** — für den Altbestand (334/359 `image_path`
  NULL) nicht lauffähig; Skript liegt außerhalb des Pakets. Befund:
  Fassaden-Anbindung wäre ein eigener Vorgang → weggelassen (Auflage:
  „im Zweifel weglassen").
- **Frame-Quelle:** `CameraWorker.request_full_frame()` +
  `full_frame_ready(np.ndarray)` existieren (`camera_worker.py:41/58`);
  die Demo-Quelle bedient dasselbe Muster (MainWindow verbindet generisch,
  `main_window.py:365`) — der Segmentierungs-Test ist damit am Mac im
  Demo-Modus bedienbar.
- **`camera.probe_cameras` ÖFFNET echte Geräte** (Docstring: „nie im
  Testlauf"). Konsequenz: die Suche ist im Panel nur aktiv, wenn das
  Hauptfenster KEINE Kamera hält (sonst Hinweistext) — so bleiben
  Kamera-Alleinbesitz UND Spec Punkt 12 erfüllt. `focus_lock_supported()`
  und `capture_backend()` öffnen nichts.
- **Fortsetzen-Mechanik:** `EnrollDialog(cfg, ui, source, parent,
  fortsetzen=SessionInfo)` (`main_window.py:581`); Zustand ist
  `UiState.READY`. Verwerfen-Semantik: `discard_enroll_session` sichert
  nach `data/verworfen/`, `plan_discard_enroll_session` liefert die
  Gegenrichtungs-Tabelle für den Bestätigungsdialog.
- **Config-Herkunft:** `config.local_override(path)` liefert die lokale
  Schicht separat (genau dafür gebaut, Docstring nennt den
  Korpus-Wächter als Nutzer); Basis-YAML wird roh geladen, Herkunft je
  Key durch Deep-Walk.

## Global Constraints

- **Branch `feature/admin-panel-stufe4`**, Commit je Task, kein
  Merge/Push. Melden und stoppen NUR bei Spec-Änderung, Berührung
  bestehenden Codes über die unten genannten Punkte hinaus, oder wenn
  eine Session-Aktion nicht über die bestehende Fassade abbildbar ist.
- **Berührungspunkte bestehenden Codes (abschließend, spec-gedeckt):**
  1. `pipeline.py`: drei additive Lese-Fassaden (Task 1).
  2. `admin_window.py`: drei neue optionale Konstruktor-Parameter
     (Meldekanäle, Default None) + Seiten-Verdrahtung (Task 7).
  3. `main_window.py`: additive Methoden für die Spec-§4-Meldekanäle
     (Voll-Frame auf Anforderung, Kamera-Warntext) und die
     Fortsetzen-Delegation (Spec Punkt 13), plus deren Übergabe beim
     AdminWindow-Bau (Task 7).
  4. `articles_page.py`: additiver B1-Detailbereich (Task 6).
  5. Spec: B1/B2-Teilung + Stufe-4-Präzisierungen (Task 8).
- **Threads/Kamera:** Admin öffnet KEINE Kamera; alle Jobs seriell über
  PipelineWorker; kein zweiter QThread-Pfad. Kein Test öffnet eine
  Kamera (conftest-Stolperdraht bleibt der Wächter); Segmentierungs-Test
  mit gestellten Frames, `probe_cameras` in Tests nur gemockt.
- **Read-only am Bestand** überall AUSSER `discard_enroll_session`
  (einzige genehmigte Ausnahme; nur die bestehende Fassade, Tests nur
  gegen Temp-Bestand).
- TDD; Python-3.9-Floor; UI-Module einzeln je pytest-Aufruf; volle
  Suite + Korpus-Doppel-Check EINMAL am Ende gegen den Referenzpunkt.
- Am Ende: `grep -rn "docodetect.reporting\|docodetect.matcher\|
  docodetect.analysis\|docodetect.enrollment_sheet\|docodetect.cli"
  docodetect/ui_qt/` → leer.

---

### Task 1: Drei Lese-Fassaden in pipeline.py

**Files:** Modify `docodetect/pipeline.py` (nach `export_analysis_run`);
Test `tests/test_ui_facade.py` (ans Ende; Datei ohne
`from __future__` — keine PEP-604-Annotationen im Testcode).

**Interfaces:**
- `reference_statistics(cfg, article_number) -> EnrollmentStats | None` —
  öffnet die DB, `stats_for`, schließt; None ohne DB/ohne Stats. Die UI
  liest nur Attribute (kein features-Import nötig).
- `min_shots_floor() -> int` — lazy Re-Export von `floor_analysis.MIN_N`
  (Konstanten-Präzedenzfall NO_MATCH, aber ohne floor_analysis beim
  pipeline-Import zu laden).
- `config_with_origin(config_path: str | Path | None = None)
  -> list[tuple[str, str, str]]` — `(key_pfad, wert, herkunft)` je
  Blatt-Key der effektiven Config, Herkunft `"config.yaml"` |
  `"config.local.yaml"`; getrenntes Laden (Basis-YAML roh +
  `local_override`), Deep-Merge nur zur Anzeige. Kein Schreibpfad.

- [ ] Step 1: Fehlschlagende Tests (test_ui_facade.py, Auszug):

```python
# ---------- Stufe-4/B1-Fassaden (Freigabe 2026-08-11) ----------

from docodetect.pipeline import (config_with_origin,  # noqa: E402
                                 min_shots_floor, reference_statistics)


def test_reference_statistics_liest_stats(tmp_path):
    cfg = make_cfg(tmp_path)
    _seed_db(cfg, with_reference=True)
    st = reference_statistics(cfg, "T-270")
    assert st is not None and st.n_shots == 1
    assert "diameter_mm" in st.scalar_mean
    assert reference_statistics(cfg, "GIBTSNICHT") is None


def test_reference_statistics_ohne_db_ist_none(tmp_path):
    assert reference_statistics(make_cfg(tmp_path), "X") is None


def test_min_shots_floor_ist_floor_analysis_min_n():
    from docodetect.floor_analysis import MIN_N
    assert min_shots_floor() == MIN_N == 10


def test_config_with_origin_trennt_die_schichten(tmp_path):
    basis = tmp_path / "config.yaml"
    basis.write_text("camera:\n  index: 0\n  width: 1920\n"
                     "matching:\n  top_k: 3\n", encoding="utf-8")
    (tmp_path / "config.local.yaml").write_text(
        "camera:\n  index: 1\n", encoding="utf-8")
    eintraege = {k: (w, h) for k, w, h in config_with_origin(basis)}
    assert eintraege["camera.index"] == ("1", "config.local.yaml")
    assert eintraege["camera.width"] == ("1920", "config.yaml")
    assert eintraege["matching.top_k"] == ("3", "config.yaml")


def test_config_with_origin_ohne_local(tmp_path):
    basis = tmp_path / "config.yaml"
    basis.write_text("camera:\n  index: 0\n", encoding="utf-8")
    assert config_with_origin(basis) == [("camera.index", "0",
                                          "config.yaml")]
```

- [ ] Step 2: Fehlschlag = ImportError verifizieren.
- [ ] Step 3: Implementieren (vollständig):

```python
def reference_statistics(cfg: dict, article_number: str):
    """Enrollment-Statistik eines Artikels aus reference_stats (Stufe 3
    Teil B1): EnrollmentStats (n_shots, scalar_mean/std, proto_std) oder
    None. Die UI liest nur Attribute — kein features-Import in ui_qt."""
    if not resolve(cfg["paths"]["db_file"]).exists():
        return None
    db = Database(cfg)
    try:
        return db.stats_for(article_number)
    except Exception:
        return None
    finally:
        db.close()


def min_shots_floor() -> int:
    """MIN_N der Floor-Analyse (floor_analysis.py) für die Anzeige
    „n < MIN_N"-Marker — lazy, damit pipeline floor_analysis nicht beim
    Import zieht (Konstanten über pipeline, Zugriffsweg-Präzedenz)."""
    from .floor_analysis import MIN_N
    return int(MIN_N)


def config_with_origin(config_path: str | Path | None = None
                       ) -> list[tuple[str, str, str]]:
    """Effektive Config als (key_pfad, wert, herkunft) je Blatt-Key —
    Herkunft durch GETRENNTES Laden von Basis- und Lokal-Schicht
    (config.local_override), Merge nur auf Anzeige-Ebene. Read-only,
    kein Schreibpfad, kein Export (Spec Punkt 11)."""
    import yaml

    from .config import DEFAULT_CONFIG_PATH, local_override
    pfad = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    with open(pfad, "r", encoding="utf-8") as fh:
        basis = yaml.safe_load(fh) or {}
    lokal = local_override(pfad)

    def _blaetter(d: dict, prefix: str = ""):
        for k in sorted(d, key=str):
            v = d[k]
            key = f"{prefix}{k}"
            if isinstance(v, dict):
                yield from _blaetter(v, key + ".")
            else:
                yield key, v

    def _hat(d: dict, key_pfad: str) -> bool:
        teil = d
        for t in key_pfad.split("."):
            if not isinstance(teil, dict) or t not in teil:
                return False
            teil = teil[t]
        return True

    from .config import _deep_merge
    effektiv = _deep_merge(basis, lokal) if lokal else basis
    return [(key, str(wert),
             "config.local.yaml" if _hat(lokal, key) else "config.yaml")
            for key, wert in _blaetter(effektiv)]
```

- [ ] Step 4: `pytest tests/test_ui_facade.py` grün. Step 5: Commit
  `feat(pipeline): Stufe-4/B1-Lese-Fassaden (stats, MIN_N, Config-Herkunft)`.

---

### Task 2: Config-Ansicht (pages/config_page.py)

**Interfaces:** `ConfigPage(cfg, parent=None)` — QTreeWidget
(Spalten Key | Wert | Herkunft), Hinweiszeile „read-only — es gibt
keinen Schreibpfad", Refresh. Nutzt NUR `pipeline.config_with_origin()`
(echte Projekt-Config; die Seite zeigt, womit die App läuft).
Testhilfe `zeilen() -> list[tuple]`. Fehlende config.yaml → Fehlertext
(kein Crash). Test `tests/test_admin_diagnose.py` (neu): Seite gegen
tmp-Config via monkeypatch von `config_page.config_with_origin`
(Modul-Attribut) — die Seite selbst kennt keine Pfade.

- [ ] Tests → Fehlschlag → Implementierung → grün → Commit
  `feat(admin): Config-Ansicht read-only mit Herkunft je Key (Stufe 4)`.

---

### Task 3: Kamera-Diagnose (pages/camera_page.py)

**Interfaces:** `CameraPage(cfg, camera_status, kamera_warnung=None,
parent=None)` — zeigt: konfigurierter Index (`camera.index`), Backend
(`camera.capture_backend`-Name), `camera.focus_lock_supported()`,
Kamera-Zustand (Callable vom Hauptfenster), letzte Fokus-/
Readback-Warnung (optionales Callable; „—" ohne), festen Hinweis
„Readback-Warnung ist auf Mac/AVFoundation erwartbar und kein Fehler".
Knopf „Kameras suchen": NUR aktiv, wenn der Kamera-Zustand nicht
„verbunden" ist (Alleinbesitz, Befund oben — probe öffnet Geräte);
Suche läuft im PipelineWorker, Ergebnis als Tabelle (Index, ok,
Auflösung). camera.py ist per CLAUDE.md erlaubter UI-Import.
Tests: `probe_cameras` im Seitenmodul gemockt (der conftest-
Stolperdraht sichert, dass nie ein echtes Gerät aufgeht); Knopf-Gating
über camera_status-Fake („verbunden" → inaktiv + Hinweis).

- [ ] Tests → Fehlschlag → Implementierung → grün → Commit
  `feat(admin): Kamera-Diagnose mit gegateter Suche (Stufe 4)`.

---

### Task 4: Segmentierungs-Test (pages/segtest_page.py)

**Interfaces:** `SegTestPage(cfg, frame_anfordern=None, parent=None)`.
`frame_anfordern(cb) -> bool` ist der Spec-§4-Meldekanal „Voll-Frame auf
Anforderung" (False/None = keine Quelle → Seite deaktiviert mit
Hinweis). Ablauf: Knopf „Testaufnahme" → Frame-Callback → Job im
PipelineWorker: `pipeline.measure_shot(frame, cfg)` (kein
DB-Schreibzugriff) → Anzeige Maske (uint8), Kontur-Overlay
(cv2.drawContours auf Kopie, `qimage.bgr_to_qimage` +
`downscale_width`), Messwerte-Tabelle (Ø, äquiv. Ø, Fläche,
Zirkularität, Seitenverhältnis, Randberührung). `SegmentationError` →
Fehlertext („warum erkennt er nichts") statt Crash.
Tests mit GESTELLTEN Frames (np.ndarray aus dem Test) und gemocktem
`segtest_page.measure_shot` (Fake-Features + SegmentationResult mit
synthetischer Maske/Kontur); Fehlerpfad mit werfendem Fake. Der echte
Messpfad bleibt durch seine eigenen Tests gedeckt.

- [ ] Tests → Fehlschlag → Implementierung → grün → Commit
  `feat(admin): Segmentierungs-Test ueber die Hauptfenster-Frame-Quelle (Stufe 4)`.

---

### Task 5: Einlern-Sessions — Anzeige + Verwerfen + Fortsetzen

**Files:** Create `pages/sessions_page.py`, Test
`tests/test_admin_sessions.py` (Session-Fixture nach dem Muster der
bestehenden `test_enroll_session*.py`, alles unter tmp_path).

**Interfaces:** `SessionsPage(cfg, fortsetzen_pruefen=None,
fortsetzen=None, parent=None)`:
- Tabelle aus `pipeline.list_enroll_sessions`: Artikel | angelegt |
  Shots (n/target) | Zustand | Fingerprint | Alter. Leerzustand mit Text.
- **Verwerfen:** Knopf nur mit Auswahl. Bestätigungsdialog zeigt die
  BETROFFENEN PFADE (Session-Ordner, Ziel `data/verworfen/…`, n Dateien
  der Gegenrichtungs-Tabelle aus `pipeline.plan_discard_enroll_session`)
  — erst nach Bestätigung läuft `pipeline.discard_enroll_session` im
  PipelineWorker (Dateibewegungen); Ergebnis „gesichert unter <pfad>"
  bzw. Fehlertext; danach reload. KEIN eigener Ablauf: die Seite ruft
  exakt die zwei bestehenden Fassaden, sonst nichts (Dialog-Naht
  `_bestaetigen(text) -> bool` als monkeypatch-Punkt).
- **Fortsetzen:** `fortsetzen_pruefen() -> str | None` (None = READY):
  bei Hinweistext wird STATT des Knopfs der Text gezeigt (Spec Punkt
  13); sonst delegiert der Knopf an `fortsetzen(session_info)` — die
  MainWindow-Implementierung öffnet den BESTEHENDEN EnrollDialog mit
  `fortsetzen=SessionInfo` (kein neuer Ablauf).
- Tests: (a) Anzeige gegen echte Temp-Session (Fixture), (b) Verwerfen
  End-to-End gegen Temp-Bestand: Ordner landet unter
  `<tmp>/data/verworfen/<artikel>/<ts>/`, DB/Referenzen wie von der
  Fassade hinterlassen, (c) Spy-Test: gemockte pipeline-Fassaden im
  Seitenmodul zeichnen Aufrufe auf → NUR `plan_discard_enroll_session`
  + `discard_enroll_session` werden gerufen (Nachweis für die
  Abschlussmeldung), (d) Bestätigung „Nein" → nichts passiert,
  (e) Fortsetzen-Gating: Hinweistext vs. Delegations-Aufruf.

- [ ] Tests → Fehlschlag → Implementierung → grün → Commit
  `feat(admin): Einlern-Sessions — Anzeige, Verwerfen, Fortsetzen (Stufe 4)`.

---

### Task 6: Stufe 3 Teil B1 — Referenz-Kennzahlen auf der Artikelseite

**Files:** Modify `pages/articles_page.py` (additiver Detailbereich),
Test in `tests/test_admin_articles.py`.

**Interfaces:** Auswahl einer Zeile → Detailbereich unter der Tabelle:
- Kopf: „<artikel> — n_shots Shots"; **Marker** `n < MIN_N` (über
  `pipeline.min_shots_floor()`): „n=9 < 10 — Floor-Schätzung unsicher".
- Skalare-Tabelle: Merkmal | Mittel | σ_enroll (scalar_mean/scalar_std,
  Dezimalkomma); Distanzkanäle: Kanal | proto_std. Zusatz-Marker
  „σ=0 bei n>1 — verdächtig" je betroffenem Merkmal.
- Ohne Stats (nie eingelernt): „keine Enrollment-Statistik".
- Daten NUR über `pipeline.reference_statistics`. KEINE Bilder (B2).

- [ ] Tests (Temp-DB mit `add_reference`-Bestand, wie `_seed_db`) →
  Fehlschlag → Implementierung → grün → Commit
  `feat(admin): Referenz-Kennzahlen je Artikel (Stufe 3 Teil B1)`.

---

### Task 7: Verdrahtung AdminWindow + MainWindow

**Files:** Modify `admin_window.py`, `main_window.py`; Tests in
`tests/test_admin_ui.py`.

- `AdminWindow(cfg, camera_status, frame_anfordern=None,
  kamera_warnung=None, fortsetzen_pruefen=None, fortsetzen=None)` —
  neue Parameter optional (bestehende Aufrufer/Tests unverändert
  gültig); Diagnose-Platzhalter wird durch eine Diagnose-Sektion mit
  Tabs (Segmentierungs-Test | Config | Kamera) ersetzt; Sessions als
  eigene Seite? NEIN — Sidebar bleibt bei fünf Einträgen (Spec §4):
  Sessions wird ein Tab der Artikel-Sektion? Auch nein — Spec nennt
  „Artikel & Sessions" als EINE Stufe, die Sidebar-Sektion „Artikel"
  erhält zwei Tabs „Artikelliste" | „Einlern-Sessions" (Tab-Präzedenz:
  Reports-Sektion 1b, Analyse-Sektion Stufe 2).
- `main_window.py` additiv: `_frame_fuer_admin(cb) -> bool` (verbindet
  einmalig `source.full_frame_ready` → cb, ruft
  `source.request_full_frame()`; False ohne Quelle),
  `_kamera_warnungs_text() -> str` (letzte focus_warning-Meldung,
  bereits im Fenster vorhanden), `_fortsetzen_pruefen() -> str | None`
  (None bei `UiState.READY`, sonst Hinweistext),
  `_fortsetzen_aus_admin(info)` (öffnet EnrollDialog mit
  `fortsetzen=info` — exakt der bestehende Weg). Übergabe beim Bau in
  `_open_admin_panel`.
- Tests: Fensterbau mit/ohne neue Callables; Seiten-Typen; Sidebar
  weiter 5 Einträge.

- [ ] Tests → Fehlschlag → Implementierung → grün → Commit
  `feat(admin): Stufe-4-Seiten und Meldekanaele verdrahtet`.

---

### Task 8: Spec-Revision

B1/B2-Teilung in Stufe 3 eintragen (B1 = Referenz-Kennzahlen ohne
Bilder, jetzt; B2 = Bilder/Diagnoseblätter nach Neu-Enrollment,
Vorbedingungen unverändert); Stufe-4-Präzisierungen: probe-Gating
(Alleinbesitz vs. Punkt 12), Sessions als Tab der Artikel-Sektion,
Fortsetzen-Delegation über `fortsetzen=SessionInfo`. Commit
`docs(spec): Stufe-3-Teilung B1/B2 + Stufe-4-Praezisierungen`.

---

### Task 9: Abschluss-Regime

- Subagent-Review des Diffs gegen die Auflagen (wie beim Export).
- Auswahl-Testläufe (UI einzeln, inkl. der drei neuen Testdateien),
  Qt-freier Block; Vollausgaben nach `~/Documents/tmp/`.
- Volle Suite (Erwartung 861 + n) + Korpus-Doppel-Check, Vergleich
  gegen den Referenzpunkt.
- Abnahme-Stichprobe: Panel-Werte offscreen gegen echte Config
  (READ-ONLY — die Session-Aktionen werden NICHT gegen den echten
  Bestand ausgeführt, nur gegen Temp in Tests): Config-Herkunft gegen
  rohes YAML/`grep`, Kamera-Statik gegen cfg + `focus_lock_supported`,
  B1-Kennzahlen gegen sqlite-ro `stats_json` (jq), Sessions-Liste gegen
  Dateisystem. Windows-Verifikationsliste für alles Kamera-abhängige.
- Abschlussmeldung, dann STOPP.
