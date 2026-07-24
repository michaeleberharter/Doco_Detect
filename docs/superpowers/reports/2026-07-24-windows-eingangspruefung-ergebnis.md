# Windows-Eingangsprüfung + SQLite-Portabilität — Ergebnisdokument

Stand 2026-07-24 · Repo `main @ 622e95c` (gepullt) · Fix auf Branch
`fix/sqlite-portabilitaet` · Maschine: Windows-11-Pro (10.0.26200), AMD64.

> **Für eine Sitzung ohne Vorkontext.** Dies ist der erste Lauf der Pipeline
> auf einer zweiten Maschine (bisher nur Mac/arm64). Auftrag war ein Gate vor
> dem Toleranz-Sweep: Umgebung aufsetzen, Transfer verifizieren, volle Suite,
> Null-Replay gegen die Mac-Baseline. Ergebnis: **echte Plattform-Drift
> gefunden — Sweep bleibt gesperrt**; unterwegs ein Portabilitäts-Bug (SQLite)
> gefixt.

---

## 0. Was an einem Satz hängen bleibt

Die Windows-Maschine ist sauber aufgesetzt und deckungsgleich zur Mac-Baseline
(`code_fingerprint` byte-identisch), der Google-Drive-Transfer ist
fingerprint-genau verifiziert — aber der Null-Replay zeigt **reale
Plattform-Drift** (arm64 → x86-64), messbar allein in der H-S-Histogramm-
Distanz, **entscheidungs-neutral** (Quoten identisch). Ein dabei gefundener
SQLite-Portabilitäts-Bug (`unixepoch()` erst ab SQLite 3.38, Windows-3.9.6
bündelt 3.35.5) ist im Code gefixt, messneutral bewiesen. **Sweep bleibt
gesperrt**; nächster Schritt ist die Plattform-Attribution der H-S-Drift.

## 1. Transfer- & Bestandsprüfung — SAUBER

Code-unabhängig verifiziert (stdlib, kein `docodetect`-Import):

- **Manifest-shas:** 173/173 Korpus-Bilder byte-identisch zu `corpus/manifest.json`;
  0 fehlend, 0 abweichend, 0 fehlende Golden-Reports. (176 PNG auf Platte =
  173 + 3 Bündel-`background.png`.)
- **Produktions-DB:** `PRAGMA integrity_check = ok`, 41 Artikel, `LOEFFEL-4
  max(w,d) = 186,49` (Post-Sync-Fingerprint bestätigt), sha256
  `6ef5f64b…`.
- **Pre-Sync-DB:** `backups/doco_detect_2026-07-24_pre-sync.sqlite3` sha256
  `92950f65…` — wie dokumentiert. Bündel-Backups (`2026-07-24_pre-sync-refresh`,
  `2026-07-24_phase-b_original-16er`) vorhanden.

## 2. Alt-Stand-Sicherung (vor dem Aufsetzen)

Der Arbeitsbaum war **nicht** 622e95c: 13 Dateien (config.py, die vier
Messpfad-Module, config.yaml, requirements.txt, …) lagen auf **`4588fdc`
(2026-07-14 01:56:51)** — eine eigene Session vor dem Mac-Zyklus (passend zur
alten 16.07-DB), byte-genau über `config.py`-Identität nachgewiesen; nichts im
Baum war neuer als 622e95c. Vor dem Restore gesichert:

- Patch `backups/2026-07-24_windows-worktree-altstand.patch` (232 KB, vollständiger Alt-Stand-Diff).
- `git stash@{0}` „windows-altstand vor 622e95c-restore" (liegt, nicht gedroppt).

Dann `core.autocrlf=false` + LF-Neucheckout → **622e95c, `git status` leer, CR-Bytes = 0**.
`code_fingerprint`/`config_fingerprint` **byte-identisch zur Mac-Baseline**
(`5f4e90b6…` / `df1a1190…`) → die CRLF-Mine ist ausgeschlossen, jede Drift ist
Plattform, nicht Zeilenende/Code.

## 3. Umgebung + env-Fingerprint

Frisches venv, **Python 3.9.6** (python.org, MD5 `ac25cf79…` gegen
Release-Seite verifiziert, per-user installiert — es war kein 3.9 vorhanden,
nur 3.14.5). Bibliotheken **exakt nach `requirements.lock`**: numpy 2.0.2 ·
opencv 5.0.0.93 (cv2 5.0.0) · scipy 1.13.1 · PyYAML 6.0.3 · matplotlib 3.9.4 ·
pytest 8.4.2. UI-Test-Deps (streamlit/pandas/plotly, PySide6/qtawesome) unter
Lock-Constraint installiert — Messstack unberührt. `config/config.local.yaml`
mit NUR `paths` (db_file, corpus_dir), Override-Wächter grün.

**env-Block der `metrics.json` (erster Windows-Fingerprint):**
```json
{ "python":"3.9.6", "platform":"Windows-10-10.0.26200-SP0", "machine":"AMD64",
  "sqlite_version":"3.35.5", "numpy":"2.0.2", "cv2":"5.0.0", "scipy":"1.13.1",
  "python_impl":"CPython" }
```
Einzige Abweichung zur Mac-Referenz: die Plattform selbst (macOS-15.6/arm64) —
das Prüfobjekt. (`sqlite_version` ist ab diesem Auftrag neu im env-Block, s. §4.)

## 4. SQLite-Portabilitäts-Befund + Fix (Option B)

**Befund:** Volle Suite scheiterte zunächst mit 63 Failures, alle mit
`sqlite3.OperationalError: unknown function: unixepoch()`. `unixepoch()` gibt es
erst ab **SQLite 3.38** (2022); das Windows-Python-3.9.6 bündelt **3.35.5**
(Floor 3.9.0 = 3.33.0). Der Mac verdeckte das nur, weil sein `sqlite3` gegen die
neuere **System**-libsqlite (≥3.38) linkt. **Die gebündelte SQLite-Version ist
damit Teil der Zielumgebung** — der Bug gehört in den Code, nicht in einen
DLL-Tausch (unsichtbarer Maschinenzustand, in keinem Fingerprint).

**Klassen-Scan:** `unixepoch()` ist das einzige Konstrukt neuer als der 3.9-Floor
(kein RETURNING/STRICT/DROP COLUMN/JSON-Operatoren/Generated Columns; UPSERT ist
3.24, sicher). Drei Fundstellen, alle in `database.py`: zwei Schema-Defaults
(`created_unix`/`updated_unix`), ein Touch-Update in `_recompute_stats`.

**Fix (Option B, freigegeben):** eine Modul-Konstante
`_SQL_UNIX_NOW = "CAST(strftime('%s','now') AS INT)"` an allen drei Stellen
interpoliert — plus die beiden Schreibpfade (`add_reference`,
`_recompute_stats`) setzen den Zeitstempel ab jetzt **explizit** in der INSERT-
Spaltenliste. Damit deckt der Fix die **2×2-Matrix Bestands-/Neu-DB ×
SQLite 3.35/≥3.38** vollständig ab:

| | SQLite 3.35 (Windows) | SQLite ≥3.38 (Mac) |
|---|---|---|
| **Neu-DB** | Default = `strftime` ✓ | ✓ |
| **Bestands-DB** | expliziter Schreibwert umgeht den schlafenden `unixepoch`-Default ✓ | ✓ |

`strftime('%s','now')` liefert denselben ganzzahligen UTC-Sekundenwert; die
REAL-Spalte speichert ihn per Typ-Affinität identisch zu vorher (`1784…0`).
**Bestands-DBs werden NICHT migriert** — ihr gespeicherter `unixepoch`-Default
bleibt bewusst stehen und wird nie mehr ausgewertet (dokumentiert am
Schema-String). Zwei neue Tests (`tests/test_sqlite_portability.py`): beide
Upsert-Zweige mit ganzzahligem Zeitstempel; kein `unixepoch` im Schema einer
frischen DB; `sqlite_version` im env-Block. `sqlite_version` wandert neu in den
env-Block der `metrics.json` — die Version war der unsichtbare Unterschied
zwischen den Maschinen.

## 5. Volle Suite — festgeschriebenes Tripel bestätigt

**530 collected / 525 passed / 2 skipped / 3 failed** (Skips = 2× camera-hardware).
Der SQLite-Fix behob 60 der 63 Failures (57 direkt `unixepoch` + 3
seed-downstream Demo-Tests). Die 3 verbliebenen sind **keine SQLite-Sache**:

1. `test_corpus_tier1_full_reproduces` — assert null Tier-1-Drift → **die H-S-Drift**.
2. `test_corpus_smoke_subset_reproduces` — dito auf dem 20-Bilder-Subset.
3. `test_camera_worker_without_camera_goes_no_camera` — Windows-Qt-Reconnect-Timing
   („Reconnect meldet wiederholt statt leise"), keine Messung, **kein** `xfail` —
   bleibt rot, eigener Triage-Auftrag (Qt-Timing vs. echtes Verhalten der
   Kamera-Schicht, relevant weil die Anlage Windows wird).

## 6. Suite-Grün ≡ Baseline-Maschine (strukturell)

**Suite-Grün und Drift-Freiheit sind auf dieser Codebasis nicht unabhängig — die
Korpus-Reproduktionstests sind Teil der Suite. Ein grünes Tripel ist ab jetzt
eine Aussage über die Baseline-Maschine, nicht über die Codebasis. Auf jeder
Nicht-Baseline-Maschine ist das erwartete Tripel um die Korpus-Tests reduziert;
das ist Absicht und kein Defekt.** Konsequenz: sobald die Windows-Baseline
existiert (eigener Auftrag nach der H-S-Attribution), ist das Tripel dort wieder
0 failed — und der Mac ist dann die Nicht-Baseline-Maschine.

## 7. Drift-Signatur (Null-Replay, beide Tiers)

`corpus-run --check` meldet REGRESSION — die Harness-Etikettierung
„auf gepinnter Umgebung code-verursacht" gilt hier **nicht**: `code_fingerprint`
== Mac (vor dem Fix), also **Umgebung, nicht Code**.

**Tier 1 (mm-Ebene, 173 Bilder):** 8 PASS / 163 DRIFT / 2 FAIL, Delta-Median
**1,0e-4**. Verteilung je Merkmal:

| Merkmal | Bilder | median \|Δ\| | max \|Δ\| |
|---|---|---|---|
| `hs_hist_rim` (Bhattacharyya) | 165 | 7,4e-5 | 5,4e-4 |
| `hs_hist_center` | 99 | 6,9e-5 | 1,6e-3 |
| `lab_center` (L\*) | 9 | 0,010 | 0,036 |
| `mean_saturation`/`mean_hsv` | 6 | 0,010 | 0,010 |
| `lab_rim` | 2 | 0,004 | 0,007 |
| **`circle_diameter_mm`** | **1** | **0,010 mm** | **0,010 mm** |

→ **Geometrie ist plattform-stabil** (Ø/Fläche/Umfang/Circularity/Solidity/
Zentroide/Seg-Fläche reproduzieren die Goldens exakt; genau 1 Bild driftet um
0,01 mm). Die Drift sitzt fast vollständig in der **H-S-Histogramm-Distanz**
(Float-Rundung von `sqrt`-Summen über 128 Bins; x86-FMA/SIMD ≠ arm64). Die 2
harten FAILs sind `hs_hist_center`-Ausreißer (~1,0–1,6e-3) auf GABEL-4/GABEL-1
(phase-c2); `5bf6b431` (GABEL-1-Rückenlage-Wächter) bleibt korrekt REJECT.

**Tier 2 (Entscheidungen, 104 Bilder):** 66 PASS / 38 DRIFT / **0 FAIL**. Drift
nur in `llr_margin` (med 1e-4, max 1,5e-3) und `max_z_winner` (med 1e-4, max
6,8e-3). **Null kategoriale Änderungen.** Quoten **identisch zur Baseline**:

| Kennzahl | Ist = Soll |
|---|---|
| accuracy_top1 | 95/104 |
| accuracy_top3 | 101/104 |
| auto_accept_rate | 44/104 |
| false_accept_rate | 0/44 |
| accuracy_top1_verdict | 83/104 |
| decisions | ambiguous 56 / accept 44 / reject 4 |

## 8. Beleg: der DB-Fix berührt den Messpfad nicht

Zweistufige Null-Replay-Verifikation Post-Fix gegen Pre-Fix (dieselbe Maschine,
einzige Änderung `database.py`):

- **PRIMÄR (Bit-Vergleich):** Tier 1 **165/165** Fehler-JSONs byte-identisch;
  Tier 2 **38/38** identisch bis auf das Wall-Clock-`timestamp`-Feld des Reports
  (Messwerte/Entscheidungen unverändert). Band-Zahlen identisch (8/163/2 bzw.
  66/38/0).
- **SEKUNDÄR (`--check` gegen Mac-Baseline):** REGRESSION mit exakt derselben
  Drift-Signatur wie oben. Baseline bleibt Mac-Stand, **kein `--accept-drift`,
  kein `--update-baseline`**.
- **`code_fingerprint`:** wie vorab benannt **geändert** (`5f4e90b6…` →
  `03a009d6…`) — `database.py` ist Teil des gehashten Umfangs. Der Beleg der
  Messneutralität ist also **nicht** der Fingerprint (der ändert sich), sondern
  die bit-gleiche Drift-Signatur.

## 9. Sweep-Sperre + Folgeaufträge

- **Sweep GESPERRT** — kein Sweep auf driftendem Messboden. Schwellen/Toleranzen
  unangetastet (`diameter_tolerance_mm` bleibt 6,0).
- **Folgeauftrag 1 (nächster):** Plattform-Attribution der H-S-Drift (arm64 ↔
  x86 Float-Verhalten in cv2/numpy) — Größenordnung 1e-4, entscheidungs-neutral.
- **Folgeauftrag 2:** Triage `test_camera_worker_…` (Qt-Timing vs.
  Kamera-Schicht).
- **Folgeauftrag 3:** Windows-Baseline anlegen (nach 1), dann ist das Tripel
  dort wieder 0 failed.

## 10. Läufe & Artefakte (externer Korpus, `runs/`)

`win-block4-tier1` / `win-block4-tier2` (Pre-Fix-Referenz), `win-postfix-tier1` /
`win-postfix-tier2` (Post-Fix, Bit-Vergleich). Der Probe-Lauf `win-sqlite-probe`
liegt in `runs/_invalid/`. Repo-Änderungen: `docodetect/database.py`,
`docodetect/corpus/report.py`, `tests/test_sqlite_portability.py` (Branch
`fix/sqlite-portabilitaet`).
