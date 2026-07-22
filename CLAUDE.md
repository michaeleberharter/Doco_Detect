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
- UI-Schichten (Streamlit `app.py`, `docodetect/ui_qt`) und CLI-Helfer rufen
  nur `pipeline.py` / `calibration.py` / `camera.py` / `database.py` —
  Messlogik wird nirgends dupliziert.
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
  (gitignored), nie löschen.
- `tests/conftest.py` blockt echte Kamerazugriffe (autouse); Hardware-Tests
  tragen Marker `hardware`, laufen nur mit `DOCODETECT_HW_TESTS=1`. Kein Code
  darf am Fixture vorbei `cv2.VideoCapture` öffnen.
- `tests/test_real_captures.py` (Goldens) läuft rein auf gespeicherten Bildern.
- Nach jedem Paket kompletter Testlauf; `git commit`/`push` erst nach Rückfrage.

## Regressions-Korpus

- **Vor jedem Merge BEIDE Stufen: `corpus-run --tier 1 --check` UND
  `corpus-run --tier 2 --check`.** Exit 1 = Regression. Tier 1 allein
  genügt nicht: dort ist `quotas` leer, die Baseline-Quoten werden nie
  ausgewertet und die Entscheidungs-Reproduktion läuft gar nicht.
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
- Ein Lauf ohne `metrics.json` ist abgebrochen: keine gültige
  Vergleichsseite (Klartext-Abbruch), `--run letzte` überspringt ihn.
  Aussortiertes nach `runs/_invalid/`.

## Umgebungen

- Entwicklung aktuell: **MacBook, OpenCV/AVFoundation** — Kamera-Props sind per
  `cv2` NICHT setzbar (Profil kommt aus CameraController); die Read-back-Warnung
  aus `camera.py` ist auf dem Mac erwartbar und kein Fehler.
- Produktionsziel: **Windows/DSHOW** an der Fotobox. Windows-venv-Eigenheiten:
  `.venv\Scripts\Activate.ps1`, `python -m pip` (defekter Launcher).
- Windows-Verhalten darf durch Mac-Arbeiten nie unbemerkt kippen.

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
  Scheinversatz von ~2,8 mm. Der Vorfilter vergleicht `hypot(width, depth)`.
- Der Geometrie-Vorfilter nutzt **immer** die `articles`-Stammdaten, nie
  `reference_stats` — die Basis wechselt auch nach dem Einlernen nicht.
