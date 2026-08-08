# Plan: Crash-sichere Einlern-Session

**Datum:** 2026-08-05 · **Status:** freigegeben, **nicht begonnen** ·
**Design:** [../specs/2026-08-05-crashsichere-einlern-session-design.md](../specs/2026-08-05-crashsichere-einlern-session-design.md)

Umsetzungsplan zum gleichnamigen Design. **Das Design ist maßgeblich** — dieser
Plan sagt nur, in welcher Reihenfolge es entsteht und wo angehalten wird. Bei
Widerspruch gilt das Design.

---

## Arbeitsregeln für dieses Paket

- **Branch:** `feature/crashsichere-einlern-session`, abgezweigt von
  **`ef86abf`** (Spitze von `feature/cli-und-analyse-fixes`). Bewusst **nicht**
  von `main`: dort fehlten die Streamlit-Entfernung und `pyproject.toml`. Der
  Merge von `feature/cli-und-analyse-fixes` nach `main` bleibt eine **eigene,
  davon getrennte Entscheidung** — dieses Paket wird nicht mit 16 fremden
  Commits in eine Merge-Entscheidung gebündelt.
- **Ein Commit je Schritt**, jeweils **nach** dem zugehörigen Melde-Punkt und
  **erst auf ausdrückliche Freigabe**. Kein `git add .`.
- **Kein Push ohne separate Anweisung.**
- **Der volle Testlauf muss auf dem Merge-Commit grün sein**, nicht nur auf den
  Einzelschritten.
- **Kein Schritt fasst den Messpfad an** (`segmentation.py`, `features.py`,
  `matcher.py`, `pipeline.analyze`, `measure_shot`).

### Melde-Punkte sind blockierend

Nach jedem 🛑 wird **gestoppt und auf Antwort gewartet** — auch wenn das
Ergebnis grün ist und der nächste Schritt offensichtlich scheint. Ein Bericht,
den der Mensch erst nach der ausgeführten Folgeaktion liest, ist kein
Freigabe-Punkt. Nachträglich nachreichen heilt das nicht.

### Wenn ein Schritt ohne Hardware nicht abschließbar ist

Die Windows-Box ist mehrere Wochen weg; alles bis Melde-Punkt 5 läuft gegen
Sandbox, Temp-Verzeichnisse und Attrappen. **Das ist so geplant.** Fällt
während der Umsetzung auf, dass ein Schritt ohne echtes Gerät nicht sinnvoll
abschließbar ist, wird das **an seinem Melde-Punkt gemeldet**, statt ihn mit
einem Attrappentest grün zu schreiben. Die sieben ungeprüften Zeilen stehen in
Abschnitt 8 des Designs.

---

## Fingerabdruck: eine setzende, drei prüfende Stellen

Damit keine zwischen zwei Schritten durchfällt — hier die vollständige
Zuordnung. Implementierung ist **einmal** `_pruefe_fingerabdruck` bzw.
`_schreibe_fingerabdruck`, aufgerufen an vier Stellen:

| # | Stelle | Rolle | Schritt | Test dort |
|---|---|---|---|---|
| 1 | `begin_enroll_session` | **SETZT** — schreibt die drei Hashes in `session.json`. Kann nichts prüfen, es gibt keinen Vergleichswert. | **2** | `session.json` enthält `calibration_sha256`, `background_sha256`, `features_cfg_sha256` mit den korrekten Werten; kanonisiertes `features`-JSON (Umformatierung ohne Wertänderung ändert den Hash nicht) |
| 2 | `stage_frame` | **PRÜFT** — jede einzelne Aufnahme, auch in fortgesetzten Sessions | **2** | `calibration.json` zwischen zwei Aufnahmen ändern → `kind='fingerprint'`; **und** `raw_<NNN>.png` existiert trotzdem, ohne Journalzeile |
| 3 | `remeasure_session` | **PRÜFT** — vor dem Neuvermessen | **3** | Abdruck ändern → `kind='fingerprint'`, kein Shot neu vermessen |
| 4 | `commit_enroll_session` | **PRÜFT** — unmittelbar vor der Transaktion, der kritische Moment (hier entsteht `sigma_enroll`) | **3** | Abdruck ändern → `kind='fingerprint'`, **keine Datei bewegt**, DB unverändert |

Zusätzlich prüft Stelle 2 den `features`-Block, nicht nur die beiden
Optikdateien: `ring_zones`/`hs_hist_bins` ändern zwischen zwei Aufnahmen →
`kind='fingerprint'`.

---

## Schritt 1 — Config und DB-Schicht ⏱ ~1 h

**Dateien:** `config/config.yaml`, `docodetect/config.py`,
`docodetect/database.py`, `tests/test_sandbox.py` (erweitern),
`tests/test_scoring.py` (erweitern)

- `paths.enroll_sessions_dir: data/enroll_sessions` in `config.yaml`
- `sandbox_cfg` (config.py:134) um das **fünfte** umgelenkte Ziel erweitern,
  `sandbox_pfade` (config.py:174) entsprechend (Startbanner)
- `database.add_references(article_number, items) -> int` mit `with self.conn:`

**Tests:** Sandbox lenkt `enroll_sessions_dir` um und zeigt ihn im Banner ·
`add_references([])` gibt 0 zurück, ohne Transaktion und ohne
`_recompute_stats` · N Zeilen + `reference_stats` in **einer** Transaktion ·
Exception mittendrin rollt **alles** zurück (keine Zeile, keine Statistik) ·
`_recompute_stats` läuft genau einmal und liefert dasselbe wie N Einzelaufrufe.

---

## Schritt 2 — Session-Fassaden ⏱ ~4 h

**Dateien:** `docodetect/pipeline.py`, `tests/test_enroll_session.py` (neu)

- `EnrollSessionError` mit `.kind`/`.detail`
- `SessionShot`, `SessionInfo`, `EnrollSession`
- `begin_enroll_session`, `stage_frame`, `append_shot`,
  `list_enroll_sessions`, `load_enroll_session`
- interne Prüfer: `_pruefe_mount`, `_pruefe_fingerabdruck`, `_pruefe_luecken`

**Tests (ohne Qt, Temp-Verzeichnisse/-DBs):**
Journal ist append-only, `flush`+`fsync` je Zeile · **N = distinkte `i`**
(`i` = 0,1,1,2 → `n_shots == 3`, letzte Zeile je `i` gewinnt) · Retake schreibt
`raw_002.png` und lässt `raw_001.png` liegen · `append_shot` weist
`<session>/optik/background.png` mit `ValueError` ab (Namensprüfung, nicht nur
Enthaltensein) · abgeschnittene **letzte** Journalzeile wird stillschweigend
verworfen, kaputte Zeile **in der Mitte** wirft `ValueError` ·
Fingerabdruck-Stellen **1 und 2** (Tabelle oben) · `_pruefe_mount` mit
gepatchtem `os.stat` → `kind='mount'` beim Anlegen · mehrere Sessions je
Artikel werden alle gelistet, neueste zuerst · Session entsteht mit
`optik/`-Kopien.

> **🛑 MELDE-PUNKT 1 — Fundament**
> Layout und schreibende Fassaden stehen, Tests grün. **Billigster
> Umkehrpunkt**, falls das Layout in der Praxis anders greift als entworfen.
> Vorzulegen: Testergebnis, ein realer Session-Ordner als Baumausgabe, die
> ersten Journalzeilen.

---

## Schritt 3 — Umzug, Buchen, Verwerfen ⏱ ~4 h

**Dateien:** `docodetect/pipeline.py`, `tests/test_enroll_session.py`

- `_zeilen_je_pfad` (abfragend) und `_pruefe_buchungsstand` (werfend)
- `_move_session_files` und `_reverse_move` (**beide intern**, nicht öffentlich)
- `commit_enroll_session`, `discard_enroll_session`, `remeasure_session`

**Tests:**
**U1** — `add_references` per monkeypatch werfen lassen → alle N Dateien im
Ziel, DB leer, zweites `commit` vollendet · **Vier Fälle vorwärts**, jeder
Zustand einzeln konstruiert · **Vier Fälle rückwärts** inkl. „Zeile zeigt auf
Ziel → nicht anfassen" · Lückenlosigkeit (`i` = 0,1,3 → `kind='luecke'`;
`N = 0` → `kind='luecke'`) · **`k<N`-Assertion** (k Zeilen direkt einfügen →
`kind='invariante'`, **keine Datei bewegt**) · **Zustand 3** (alle N Zeilen +
Dateien im Ziel → nur Aufräumen, keine Doppelbuchung) ·
**`remeasure_session` schreibt nicht** — Journal-Bytes vor/nach **identisch**,
und ein anschließendes `commit` bucht die **ursprünglichen** Werte ·
Abweichungstoleranz `0,1 × sigma_floor` über **`matcher._sigma_floor`**
(inklusive `_FLOOR_KEY`-Zuordnung für die vier Farbmerkmale) ·
Fingerabdruck-Stellen **3 und 4** · Rückumzug rührt eine Datei mit DB-Zeile
nicht an.

---

## Schritt 4 — Absturzsimulation ⏱ ~3 h

**Dateien:** `tests/test_enroll_session_crash.py` (neu)

`SIGKILL`-Harness: Kindprozess fährt die Session über die Fassaden und meldet
Fortschritt über eine Markerdatei; der Elternprozess schießt ihn an einem
definierten Punkt ab (kein Handler, kein `finally`) und prüft **ausschließlich,
was auf der Platte liegt**.

| Abschuss nach | Erwarteter Befund | Erwartete Rettung |
|---|---|---|
| PNG geschrieben, **vor** Journalzeile | Waisen-PNG, `n_shots` unverändert | Session offen, fortsetzbar |
| k Journalzeilen | `n_shots == k` | fortsetzbar, weitere Aufnahmen möglich |
| k von N Renames | „Umzug unterbrochen" | `commit` führt zu Ende und bucht |
| alle Renames, **vor** Transaktion | „Umzug vollständig, DB leer" | `commit` bucht, keine Datei bewegt |
| Transaktion durch, **vor** `backups/` | Zustand 3 | `commit` räumt nur auf |

Jeder Punkt prüft zusätzlich: **keine DB-Zeile zeigt ins Leere**, **keine Datei
ist verschwunden**.

**Grenze, die im Bericht stehen muss:** `SIGKILL` beendet den Prozess, lässt
aber den Page-Cache intakt. Das prüft **Prozessabsturz**, nicht
**Stromausfall** — die `fsync`-Reihenfolge aus Design 3.7 bleibt **entworfen,
aber unverifiziert**. Kein Test wird so beschriftet, als deckte er das ab.

> **🛑 MELDE-PUNKT 2 — der Beweis des Pakets**
> Vorher ist alles Behauptung. Vorzulegen: die **fünf Abschusspunkte einzeln**
> mit Befund und Rettung, plus die ausdrückliche Feststellung, dass
> Stromausfall nicht geprüft ist.

---

## Schritt 5 — CLI ⏱ ~2 h

**Dateien:** `docodetect/cli.py`, `tests/test_corpus_cli.py`-Muster folgend in
`tests/test_enroll_session_cli.py` (neu)

```
list-enroll-sessions      [--article NR] [--json]
show-enroll-session       <artikel> [--ts TS]
commit-enroll-session     <artikel> [--ts TS] [--dry-run]
discard-enroll-session    <artikel> [--ts TS] [--dry-run]
```

**Tests:** `--ts` ist Pflicht, sobald mehr als eine offene Session für den
Artikel existiert (kein Raten) · `--dry-run` bei `commit` führt alle vier
Prüfungen aus und bewegt **nichts** · `--dry-run` bei `discard` zeigt die
vollständige Gegenrichtungs-Tabelle je `i` und schreibt **kein** `info.json` ·
kein Befehl ist unter `--sandbox` gesperrt.

> **🛑 MELDE-PUNKT 3 — Rettungspfad ohne GUI vollständig**
> Ab hier ist eine unterbrochene Session vom Terminal aus zu Ende zu bringen,
> **selbst wenn Qt gar nicht startet**. Vorzulegen: ein durchgespielter
> Rettungsfall (Session anlegen → SIGKILL → `list` → `show` → `commit
> --dry-run` → `commit`) als Konsolenmitschnitt.

---

## Schritt 6 — Kamera-Fixes ⏱ ~2 h

**Dateien:** `docodetect/ui_qt/camera_worker.py`,
`tests/test_camera_worker.py` (neu)

- **Befund 2:** zweiter `except`-Zweig für alles, was nicht `CameraError` ist —
  Meldung mit Typnamen, **kein Reconnect** (nicht-transient), `return`
- **Befund 3:** zwei getrennte Zähler (`grab_fails`, `retrieve_fails`), jeder
  auf seinem eigenen Erfolg zurückgesetzt, beide gegen `_MAX_GRAB_FAILS`

**Tests ohne QApplication:** `_grab_loop` wird mit einer `cap`-Attrappe
**direkt aufgerufen**, der Thread nie gestartet. Attrappe „grabt, liefert aber
nie" → Fehlermeldung nach `_MAX_GRAB_FAILS` statt Endlosschleife · Config ohne
`camera.index` → `camera_error` wird **emittiert** und der Thread endet, statt
den `KeyError` aus `run()` entkommen zu lassen · überzählige Frames (grab ohne
retrieve) erhöhen `retrieve_fails` nicht.

**Beschriftung:** beide firmieren als **Robustheitsverbesserung**, nicht als
Behebung des Absturzes vom 2026-08-01 — die Aktenlage verortet jenen „beim
Speichern", also im `PipelineWorker`, nicht im `CameraWorker` (Design 6.0).

---

## Schritt 7 — Qt ⏱ ~5 h

**Dateien:** `docodetect/ui_qt/pipeline_worker.py`,
`docodetect/ui_qt/widgets/enroll_dialog.py`,
`docodetect/ui_qt/widgets/open_sessions_dialog.py` (neu),
`docodetect/ui_qt/main_window.py`,
`tests/test_ui_enroll_session.py` (neu)

- `PipelineWorker`: `progress = Signal(int, int)` + explizites
  `with_progress`-Flag (kein `inspect.signature`-Raten)
- `EnrollDialog`: Session statt `self._shots` als Wahrheit; `_job_capture` mit
  den drei Schritten `stage_frame` → `measure_shot` → `append_shot`;
  Combo-Sperre ab der ersten Journalzeile; Abbrechen-Rückfrage mit
  **Vorbelegung „Verwerfen"**; Schließschutz mit „Trotzdem schließen" nach
  30 s; **6-s-Timer** (= 2 × `_RECONNECT_SECS`) gegen das stumme Warten auf
  einen Frame, als **Zustandsmeldung, nicht als Fehler**
- `open_sessions_dialog.py`: Liste aus Design 5.1
- `main_window.py`: vor `EnrollDialog` auf offene Sessions prüfen

> **Ausdrücklich: `pipeline.save_enrollment` und `pipeline.save_reference`
> werden NICHT entfernt und ihre Tests NICHT angepasst.**
> Mit der Umstellung des Dialogs verliert `save_enrollment` seinen
> Produktivaufrufer und `save_reference` seinen einzigen Aufrufer überhaupt.
> Beide bleiben mit datiertem Kommentar stehen (Design 4.2 / Vormerkliste 16).
> Die drei Testaufrufer — **`test_enrollment_sheet.py:91`,
> `test_enrollment_sheet.py:217`, `test_ui_facade.py:239`** — bleiben
> **unverändert** und müssen weiter grün sein. Sie sind ab dann die **einzige**
> Absicherung dieser Fassaden. Wer sie „der neuen Welt anpasst", entfernt genau
> die Absicherung, die wir bewusst behalten haben.

**Qt-Tests (`QT_QPA_PLATFORM=offscreen`, Module einzeln aufrufen):** Dialog für
offene Sessions (Auswahl, mehrere je Artikel, abgeblendetes „Fortsetzen" bei
abweichendem Abdruck) · gesperrte Combo mit Hinweistext · Abbrechen-Rückfrage,
Vorbelegung „Verwerfen" hat den Fokus · Schließschutz blockt, „Trotzdem
schließen" erscheint nach 30 s und lässt die Session offen · Fortschrittsanzeige
während `remeasure_session` · 6-s-Timer entsperrt und meldet **Zustand**, nicht
Fehler.

> **🛑 MELDE-PUNKT 4 — UI**
> Vorzulegen: Qt-Module **einzeln** aufgerufen mit getrennten Ergebnissen, plus
> die Skip-Listen mit `-rs` **verglichen nach Zusammensetzung**, nicht nur nach
> Anzahl.

---

## Schritt 8 — Doku und Gesamtlauf ⏱ ~2 h

**Dateien:** `docs/architektur.md`, `README.md`, `docodetect/pipeline.py`
(Kommentare)

- `architektur.md`: Session-Ablage und die neuen Fassaden
- `README.md`: die vier Rettungsbefehle
- datierte Kommentare an `save_reference` (pipeline.py:408) und
  `save_enrollment` (pipeline.py:125): seit diesem Paket ohne
  Produktivaufrufer, warum sie trotzdem bleiben, Verweis auf Vormerkliste 16

**Gesamtlauf, Erwartungen VOR dem Lauf registriert:**

- Ausgangsstand **680 Tests** (gemessen auf `ef86abf`)
- erwartet: 680 + neue, **0 failed**, Skip-Liste **unverändert in
  Zusammensetzung** (`-rs`, vergleichen — nicht nur die Zahl)
- Laufprofil ~20 min, davon 7–8 min scheinbarer Stillstand im Korpus-Block bei
  Test 72/73 — **kein Hänger, nicht abbrechen**
- `corpus-run --tier 1 --check` → Exit 0, kein DRIFT
- `corpus-run --tier 2 --check` → Exit 0, kein DRIFT, `false_accept`
  unverändert
- beide **ungefiltert** (`--subset`/`--session`/`--article` enden bewusst mit
  Exit 1 und wären keine Freigabe)

**Kein Re-Baselining erwartet:** `config_fingerprint` speist sich aus
`("features",)` bzw. `("features","matching")` (`corpus/runner.py:57-58`) —
`paths` geht nicht ein, der neue Key ändert keinen Fingerprint.

**Erwartbare Störungen, die keine Regression dieses Pakets sind:** das
dokumentierte Tier-1-Flackern (`RuntimeError: vector`, erster Fall
`a8d8c8d7`/LOEFFEL-3 — bei Wiederkehr die Regel aus CLAUDE.md anwenden) und das
von `test_corpus_tier2_decisions_reproduce` bei jedem vollen Lauf hinterlassene
`runs/_invalid/`.

> **🛑 MELDE-PUNKT 5 — vor jedem Commit**
> Vorzulegen: Testzahlen **gegen die registrierte Erwartung**, beide
> `corpus-run --check`, und die **offene Verifikationsliste als das, was sie
> ist** — sieben ungeprüfte Zeilen (Design Abschnitt 8), **nicht grün**.
> „Suite grün" bedeutet bis dahin **nicht** „an der Box geprüft".

---

## Aufwand

**~23 h geschätzt, nicht gemessen.** Die Schätzung enthält keine Reserve für
Befunde, die während der Umsetzung auftauchen — solche werden am nächsten
Melde-Punkt gemeldet, nicht stillschweigend eingearbeitet.
