# CLAUDE.md

Projekt-Dauerregeln für Claude Code. Architektur-Details:
[docs/architektur.md](docs/architektur.md). Ablauf/Setup: [README.md](README.md).

## Architektur-Invarianten

- Zweistufige Pipeline, **kein Modelltraining**. Alle Maße in mm.
- Alle Parameter zentral in `config/config.yaml`. Maschinen-Spezifisches
  (`camera.index`, `geometry.camera_height_mm` des Rigs) gehört NUR in
  `config/config.local.yaml` (Deep-Merge, gitignored) — nie in die geteilte
  `config.yaml`.
- **`matching` und `features` NIE in `config.local.yaml`** — auch nicht
  rig-spezifisch gemessene `sigma_floors`. Beide Abschnitte gehen in den
  `config_fingerprint` des Korpus; lokal überschrieben rechnet die
  Tier-2-Baseline gegen unversionierte Werte und misst nichts mehr (so
  geschehen am 2026-07-21). `corpus-run` bricht deshalb ab, wenn es sie
  dort findet (`corpus/runner.py::pruefe_lokale_overrides`).
- Ausnahme by design: `segmentation.py` hat **keine** Config-Keys, sie
  selbstkalibriert auf dem Bildpaar. Keine Segmentierungs-Knöpfe hinzufügen.
- UI-Schichten (`docodetect/ui_qt`) und CLI-Helfer rufen nur `pipeline.py` /
  `calibration.py` / `camera.py` / `database.py` — Messlogik wird nirgends
  dupliziert. (Die zweite UI, Streamlit `app.py`/`pages/`, ist am 2026-08-01
  entfernt worden, Commit `07586b5` — Begründung und Ersatzwege im README.)
- Messpfad = `pipeline.py`, `segmentation.py`, `features.py`, `matcher.py`:
  Änderungen nur bei explizitem Auftrag, nie beiläufig „mitverbessern".
- Schwellen/Gewichte (`max_z_accept`, `min_llr_margin`, `feature_weights`,
  `sigma_floors`-Defaults) nur mit Datenbegründung UND explizitem Auftrag.
  **Stand 2026-07-20: Die LLR-Margin ist der einzige wirksame Schutz gegen
  Fehlbuchungen bei baugleichen Artikeln — nicht lockern.**

## Daten & Tests

- Echte `doco_detect.sqlite3`, `data/reference/` und `calibration/` NIE aus
  Tests oder Ad-hoc-Skripten anfassen; Tests nur gegen Temp-DBs/Temp-Verzeichnisse.
- Destruktives immer als Verschieben nach `backups/<datum>-<zweck>/`
  (gitignored), nie löschen. Fallbeispiel für die Kosten: beim Rig-Umbau am
  2026-07-20 wurde der alte Capture-Bestand gelöscht statt verschoben —
  damit sind die 15 Fixtures von `test_real_captures.py` unwiederbringlich
  weg und der Segmentierungs-Backstop seither tot (Details und Auflösung:
  README, „Tests und Hardware").
- `tests/conftest.py` blockt echte Kamerazugriffe (autouse); Hardware-Tests
  tragen Marker `hardware`, laufen nur mit `DOCODETECT_HW_TESTS=1`. Kein Code
  darf am Fixture vorbei `cv2.VideoCapture` öffnen.
- `tests/test_real_captures.py` (Goldens) liest AUSSCHLIESSLICH aus dem
  versionierten Satz `tests/fixtures/golden_captures/` (Szenen +
  zugehöriger Hintergrund + `goldens.json`) — nie mehr aus `data/captures/`.
  **Fehlt der Satz, schlägt der Test fehl; er skippt nicht.** Ein fehlender
  Backstop ist ein Befund, kein Umstand. Der Wächter
  `test_golden_fixtures_vollstaendig` ist bewusst NICHT parametrisiert:
  eine Parametrisierung über ein leeres Manifest sammelt null Tests ein
  („got empty parameter set" = SKIP) und verschwindet lautlos.
- `PFLICHT_SZENEN` in derselben Datei ist die verbindliche Szenenliste.
  Eine Szene aufzugeben ist erlaubt, aber nur als bewusste Code-Änderung
  mit Begründung im Commit — nicht als Nebeneffekt eines Hardware-Tags.
- Neue Goldens nur über `scripts/adopt_goldens.py`, und nur nach
  Sichtabnahme jeder Maske (`--dry-run --overlay-dir …` zuerst). Ein
  unbesehen übernommenes Golden zementiert genau den Fehler, den es messen
  soll.
- Nach jedem Paket kompletter Testlauf; `git commit`/`push` erst nach Rückfrage.

## Regressions-Korpus

- **Vor jedem Merge BEIDE Stufen: `corpus-run --tier 1 --check` UND
  `corpus-run --tier 2 --check`.** Exit 1 = Regression. Tier 1 allein
  genügt nicht: dort ist `quotas` leer, die Baseline-Quoten werden nie
  ausgewertet und die Entscheidungs-Reproduktion läuft gar nicht.
  Die Suite lässt die beiden Korpus-Reproduktionstests per Default aus
  (`DOCODETECT_CORPUS_REPRO=1` holt sie zurück) — der Doppel-Check ist
  damit keine Redundanz, sondern die einzige Korpus-Prüfung vor dem
  Merge und deckt den Deselect ausdrücklich mit ab (Nachweis
  2026-08-11: der CLI-Check prüft strikt mehr, inkl. DRIFT und Quoten).
  DRIFT bricht per Default mit — auf gepinnter Umgebung ist jede
  Abweichung code-verursacht. `--accept-drift` nur bei bewusstem
  Bibliotheks-Update oder Plattformwechsel Mac↔Windows, danach
  Re-Baselining mit Begründung.
- `--check` gilt nur ungefiltert: `--subset`/`--session`/`--article`
  enden bewusst mit Exit 1. Ein Teil-Lauf ist keine Freigabe.
- Alltag: `pytest -m corpus_smoke` (20 Bilder). Vollständig:
  `pytest -m corpus`. Beide skippen sauber ohne lokalen Korpus.
- Der Korpus liegt AUSSERHALB des Repos (`paths.corpus_dir`, Default
  `../Doco_Detect_corpus`). Versioniert sind nur `corpus/manifest.json`
  und `corpus/baseline.json`.
- **Baseline-Änderung nur über `corpus-run --tier 2 --update-baseline`
  MIT Begründung im Commit.** Eine Baseline, die man ohne Erklärung
  nachzieht, misst nichts mehr. Ohne `--tier 2` bricht der Befehl mit
  Exit 2 ab — eine Baseline mit leeren Quoten würde jede Kennzahl
  dauerhaft abschalten.
- `corpus-triage` erzeugt NUR Befunde — nie Code-, Schwellen- oder
  Baseline-Änderungen.
- `corpus-report` (`corpus/review.py`) ist eine reine **Konsumentenschicht**:
  liest Goldens, `runs/<id>/`, `accepted_deltas/`, `baseline.json` und
  schreibt PNG/CSV/HTML nach `reports/corpus/`. Sie rechnet NIE Pipeline
  oder Matcher; jedes Band-Urteil kommt aus `failures/`/`metrics.json`,
  jede Quote einer Laufseite aus deren `metrics.json`. Abweichungen zur
  Nachrechnung werden als Befund gemeldet, nicht stillschweigend ersetzt.
- Ein Lauf ohne `metrics.json` ist keine gültige Vergleichsseite
  (Klartext-Abbruch), `--run letzte` überspringt ihn. Aussortiertes nach
  `runs/_invalid/`. Häufigste Quelle solcher Ordner ist NICHT ein Abbruch,
  sondern `tests/test_corpus.py::test_corpus_tier2_decisions_reproduce`:
  es ruft `run_corpus()` direkt auf und erreicht `write_run` nie. Jeder
  volle Testlauf hinterlässt so ein Verzeichnis.

## Zusammenarbeit

- **Definiert eine Freigabe eine Sequenz mit Melde-Punkten, ist JEDER
  Melde-Punkt blockierend.** Nach dem Melden wird gestoppt und auf Antwort
  gewartet — auch wenn das Ergebnis grün ist und der nächste Schritt
  offensichtlich scheint. Ein Bericht, den der Mensch erst nach der
  ausgeführten Folgeaktion liest, ist kein Freigabe-Punkt (so geschehen
  2026-07-22: Suite-Tripel gemeldet und im selben Zug committet UND
  gemergt). Nachträglich nachreichen heilt das nicht.
- **Nebenausgaben (Analyse-Berichte, PNGs, Scratch — alles, was NICHT ins
  Repo gehört) immer nach `~/Documents/tmp/`, NIE nach `/tmp`.** `/tmp` ist
  auf dem Mac im Finder ausgeblendet und wird beim Neustart geleert (User hat
  Dateien dort mehrfach nicht gefunden). `~/Documents/tmp/` liegt neben dem
  Projekt (außerhalb des Repos, `git status` bleibt sauber), ist dauerhaft und
  im Finder sichtbar. Verlangt eine Aufgabe explizit `/tmp/x`, zusätzlich
  dorthin kopieren.

## Worktrees

- `config/config.local.yaml` mit absoluten `paths` reicht NICHT, um einen
  Worktree voll testfähig zu machen. Sie wirkt nur auf Code, der
  `cfg["paths"][...]` liest. `config.resolve()` löst IMMER gegen
  `project_root()` auf — Aufrufer, die Literale übergeben, umgehen die
  Config komplett.
- Deshalb im Worktree zusätzlich symlinken (beide gitignored):
  `data/captures -> ../../Doco_Detect/data/captures` und
  `calibration/background.png -> ../../Doco_Detect/calibration/background.png`.
  Das stellt Gleichstand zum Hauptverzeichnis her — mehr nicht.
  **Für `test_real_captures.py` ist das seit dem Fixture-Umbau nicht mehr
  nötig:** der Test liest nur noch aus `tests/fixtures/golden_captures/`,
  und das ist versioniert, also im Worktree ohnehin vorhanden. Genau darin
  liegt der Gewinn — ein Worktree ist für den Segmentierungs-Backstop jetzt
  ohne Sonderbehandlung gleichwertig.
- Ein Worktree-Testlauf ist erst dann gleichwertig, wenn seine Skip-Liste
  die des Hauptverzeichnisses ist — **Zusammensetzung, nicht nur Anzahl**.
  Beide meldeten am 2026-07-22 „17 skipped", aber aus verschiedenen
  Gründen (`no captures` vs. `capture … not present`). Gleiche Zahl,
  verschiedene Ursache: Skip-Gründe immer mit `-rs` ausgeben und
  vergleichen, nie nur die Passed-Zahl.

## Umgebungen

- Entwicklung aktuell: **MacBook, OpenCV/AVFoundation** — Kamera-Props sind per
  `cv2` NICHT setzbar (Profil kommt aus CameraController); die Read-back-Warnung
  aus `camera.py` ist auf dem Mac erwartbar und kein Fehler.
- Produktionsziel: **Windows/DSHOW** an der Fotobox. Windows-venv-Eigenheiten:
  `.venv\Scripts\Activate.ps1`, `python -m pip` (defekter Launcher).
- Windows-Verhalten darf durch Mac-Arbeiten nie unbemerkt kippen.
- **Commit-Messages auf Windows über Datei, nicht inline:**
  `git commit -F <datei>` statt `git commit -m "…"`. Das PowerShell-/Bash-
  Tool-Quoting hat einen mehrzeiligen Here-String schon zu einem nackten
  `@` verstümmelt (Subject leer). Nachricht in eine Temp-Datei schreiben
  (Write-Tool), dann `-F` — so ist das Subject reproduzierbar korrekt.

## Auswertung

- Jede Identifikation: Capture + MatchReport-JSON unter `data/captures/`.
- `analyze <ordner> --run-id X` aggregiert nach `reports/analysis/<run_id>/`;
  archivierte Reports sind reanalysierbar.
- Bewertungen (Richtig/Falsch + wahrer Artikel) kommen aus der UI und stehen
  in den Report-JSONs.

## Messgrößen — bekannte Fallstricke (2026-07-20)

- `articles.width_mm/depth_mm` (aus `create-article`) sind die Seiten des
  **minAreaRect**; `reference_stats.scalar_mean["diameter_mm"]` (aus `enroll`)
  ist der **minEnclosingCircle**-Ø. Zwei verschiedene Größen — `width_mm`
  direkt gegen den Enrollment-Mittelwert zu vergleichen erzeugt einen
  Scheinversatz von ~2,8 mm. Der Vorfilter vergleicht seit dem Fix vom
  2026-07-21 **`max(width, depth)`** (die Länge), nicht mehr
  `hypot(width, depth)` — maßgeblich ist `matcher._nominal_size_mm`.
  Der 2026-07-23-Vorbehalt („`stammdaten.py` rechnet noch mit `hypot`,
  `sync-stammdaten --apply` deshalb gesperrt") ist **erledigt**: der
  hypot→max-Fix landete am 2026-07-24, `stammdaten.py` und
  `matcher._nominal_size_mm` vergleichen jetzt beide `max(width, depth)`, und
  **`sync-stammdaten --apply` wurde am 2026-07-24 ausgeführt** — Live-DB und
  Bundle-DBs sind seither post-sync (Nominal == Enrollment-Ø-Mittel). Wirkung
  am 2026-07-27 aus Snapshots gemessen (docs/2026-07-27-scoring-analyse.md,
  Nachtrag): **0 neue Falschakzepte**, aber −1 korrekter Auto-Accept und
  Vorfilter-Kills 1→3 (die Messausreißer LOEFFEL-3/-6/-7).
- Der Geometrie-Vorfilter nutzt **immer** die `articles`-Stammdaten, nie
  `reference_stats` — die Basis wechselt auch nach dem Einlernen nicht.

## Enrollment-Diagnose (2026-07-28)

- `enrollment-sheet <artikelnummer> [--out]` (`docodetect/enrollment_sheet.py`)
  rendert aus den N Shots eines Artikels ein PNG mit fünf Feldern (Konturband,
  Breitenprofil, Messwert/Shot, Streuungstabelle über ALLE Scoring-Merkmale mit
  klassischem UND robustem Leave-one-out-z, Shot×Merkmal-Heatmap). Reine
  **Konsumentenschicht** wie `analysis.py`, KEIN Messpfad; die Geometrie
  (`ext_full`/`lat_p98`/`w(s)`) ist 1:1 aus den eingefrorenen C-Skripten
  (`scripts/tail_*_check.py`) kopiert. Felder 1–3 brauchen die Kontur (also
  gesetztes `reference_features.image_path`); 4–5 laufen rein auf features_json,
  also auch für Altbestand.
- Im Qt-Einlerndialog erscheint das Blatt VOR dem DB-Schreiben mit
  Übernehmen/Verwerfen. **Verwerfen sichert** die Aufnahmen (+ Blatt) nach
  `data/verworfen/<artikel>/<ts>/` (gitignored) statt sie zu löschen — kein
  DB-/reference_dir-Eintrag, da pre-commit. Das ist das „warum verworfen"-
  Material, das der C-Serie fehlte.
- **Beim Neu-Einlernen beachten — gilt für die PRODUKTIV-DB:** dort ist
  LOEFFEL-3 ein harter Fall (schon in der C-Serie: Messausreißer
  LOEFFEL-3/-6/-7). Am 2026-07-28 aus den 9 **Altbestands**-Shots der
  Produktiv-DB gemessen: **σ(Ø) = 1,87 mm**, ~2–4× die saubere
  C-Serie-Bandbreite (0,43–0,92 mm), mit sichtbarer Drift über die Shots
  (Diagnoseblatt Feld c/e: auffällig S9/S1/S8). Vor dem Vertrauen auf LOEFFEL-3
  das Blatt prüfen.
  **Nicht auf andere Bestände übertragen:** Artikelnummern sind je Bestand
  neu vergeben. In der Sandbox `neuenroll-2026-08` (2026-08-01) ist LOEFFEL-3
  im Gegenteil unauffällig — kein Merkmal über dem Floor (max σ_enroll/σ_floor
  = 0,99) und einer von nur drei Artikeln mit ACCEPT. Wer eine
  Artikel-Warnung zitiert, nennt den Bestand dazu.

## Messpfad-Runde (2026-07-28) — ERLEDIGT am 2026-07-29

> **Erledigt mit Commit `59edc46` (2026-07-29).** Alle drei unten genannten
> Änderungen sind im Messpfad: `matcher.py` schreibt `prefiltered` (jeder Kill
> mit Grund und Abstand zur Toleranz) und `timestamp` mit µs-Auflösung,
> `features.py` liefert `lat_p98_mm`. **Der Satz „die risikotragende Größe ist
> derzeit nicht messbar" ist damit falsch** — Prefilter-Kills stehen seither im
> Report-JSON, und der Fixpunkt-Test vom 2026-08-01 hat sie ausgewertet
> (Befund 5: kein Kill des wahren Artikels in 15 Aufnahmen). Der Text unten
> bleibt als Herleitung stehen, ist aber kein offener Auftrag mehr.

- **Prefilter-Kills sind aus den Report-JSONs nicht rekonstruierbar** (nur die
  überlebenden Kandidaten stehen drin). Laut C-Serie sitzt das
  Falschakzept-Risiko konzentriert **genau dort** — kein Falschakzept war je ein
  Nicht-Kill-Fall. Damit ist die risikotragende Größe **derzeit nicht messbar**;
  der Vorfilter-Trichter der Analyse zeigt ehrlich „nicht im Kandidatenset".
- Fix = Prefilter-Liste ins Report-JSON — Messpfad-Eingriff, bewusst
  aufgeschoben. Gebündelt mit **lat_p98** (echte Breite statt Ø·aspect_ratio-
  Proxy) und **µs-Auflösung im `timestamp`** (heute nur Sekunden, Analyse keyt
  auf den ms-Basename des `report_path`). Drei Dinge am selben Ort → **eine**
  Messpfad-Runde, nicht einzeln (je Runde ein Korpus-Re-Baselining). Details:
  [docs/2026-07-28-messpfad-aufgeschoben.md](docs/2026-07-28-messpfad-aufgeschoben.md).

## Korpus tier1 — nichtdeterministisches Flackern (2026-07-28, offen)

- **Korpus tier1 flackert nichtdeterministisch** (`corpus-run --tier 1 --check`
  auf `workers=8`): am 2026-07-28 einmal `FAIL` mit **1 Bild** (`a8d8c8d7…`,
  Session phase-b, Artikel **LOEFFEL-3**), `error: "RuntimeError: vector"` —
  ein Replay-**Absturz** (kein `raise` im Code, Delta-Median 0.0, keine Drift),
  Re-Lauf sofort grün. Nicht code-verursacht: `corpus/runner.py` importiert
  weder analysis/review/plotstyle noch ändert der Messpfad sich. **Vorgabe bei
  Wiederkehr:** ist es DASSELBE Bild (`a8d8c8d7`/LOEFFEL-3) → bekanntes Grenzbild
  eines harten Artikels, so dokumentieren; jedes Mal ein ANDERES → Harness-
  Nichtdeterminismus, dann taugt der Korpus so nicht als Regressionsgate
  (eigenes Thema). Erster dokumentierter sha: `a8d8c8d7` (der frühere Einzelfall
  ging durch `| tail` verloren).
