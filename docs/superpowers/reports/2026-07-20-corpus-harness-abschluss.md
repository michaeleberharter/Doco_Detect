# Regressions-Korpus — Übergabebericht

Stand 2026-07-21 · Branch `feature/corpus-harness` · Projekt `/Users/mikeeberharter/Documents/Doco_Detect`

Dieser Bericht ist für eine Sitzung ohne Vorkontext geschrieben. Fachbegriffe
werden bei ihrer ersten Nennung erklärt.

---

## 1. PLAN WAR

Doco_Detect identifiziert Besteck und Geschirr in einer Fotobox: eine Kamera
über einem Boden, ein Objekt darunter, eine zweistufige Pipeline aus
Segmentierung, Merkmalsextraktion und statistischem Abgleich gegen eine
Artikel-Datenbank. Es gibt kein Modelltraining; alle Schwellen stehen in
`config/config.yaml`.

Der Auftrag war, ein **Regressions-Harness** zu bauen: rund 120 bereits
bewertete echte Aufnahmen liegen als Bilder plus JSON-Reports vor, und jeder
Report enthält sowohl das menschliche Urteil als auch die damals gemessenen
Werte. Damit sind die alten Reports zugleich die **Goldens** — die
Soll-Ergebnisse, gegen die ein erneuter Lauf verglichen wird. Ziel: jede
künftige Änderung am Messpfad automatisch gegen diesen Bestand prüfen.

Zwei Prüfstufen waren gefordert:

- **Tier 1 „Reproduktion"** — jedes Bild, ohne Datenbank: Segmentierung und
  Merkmale neu messen und gegen den Golden desselben Bildes vergleichen.
- **Tier 2 „Entscheidung"** — nur Bilder mit passendem Datenbank-Snapshot:
  die komplette Pipeline replayen und Entscheidung plus Kandidatenliste
  vergleichen.

Umgesetzt wurde das in dreizehn Tasks: Manifest-Grundlage (1),
Session-Fingerprints (2), Drei-Band-Vergleich (3), `corpus-build` (4),
paralleler Runner (5), Auswertung und Baseline (6), `corpus-run` (7),
`corpus-diff` (8), `corpus-triage` (9), Pytest-Marker (10), Erstlauf mit
Baseline (11), Dokumentation (12), dieser Bericht (13).

---

## 2. GEÄNDERT WURDE

### Neues Paket `docodetect/corpus/`

| Datei | Aufgabe |
|---|---|
| `manifest.py` | Manifest lesen/schreiben, SHA-256-Hashing, Pfadauflösung |
| `bundle.py` | Session-Fingerprints, Bündel-Verifikation, Replay-Config |
| `compare.py` | Drei-Band-Vergleich für Tier 1 und Tier 2 |
| `build.py` | Korpus aufbauen, dedupliziert per Inhalts-Hash |
| `runner.py` | Paralleler Replay über einen ProcessPool, Ergebnis-Cache |
| `report.py` | Wilson-Intervalle, Quoten, Drift-Klassifikation, Baseline |
| `diff.py` | Zwei Läufe gegeneinanderstellen |
| `triage.py` | Failures clustern, Befunde schreiben |

**„Bündel"** heisst der eingefrorene Zustand einer Aufnahme-Session:
Hintergrundbild, Kalibrierung und Datenbank-Snapshot, so wie sie zum
Aufnahmezeitpunkt waren. Der Replay läuft immer gegen das Bündel seiner
Session, nie gegen den heutigen Live-Zustand.

**„Drei-Band"** ist die Bewertung jeder einzelnen Abweichung zwischen Golden
und Replay: **PASS** innerhalb des Rundungsquantums der gespeicherten Werte
(Durchmesser ±0,005 mm, Rundheit und Solidity ±0,00005 — abgeleitet aus den
`round()`-Aufrufen in `docodetect/features.py`), **DRIFT** darüber aber
innerhalb der weichen Stufe (Durchmesser ±0,2 mm), **FAIL** darüber.

### Vier CLI-Befehle

Registriert in `docodetect/cli.py` neben den 16 bestehenden Befehlen:

- **`corpus-build`** — baut den Korpus aus Live-Captures, archivierten
  Report-Ordnern und Datenbank-Backups auf. Idempotent, dedupliziert per
  SHA-256 des Bildinhalts.
- **`corpus-run`** — fährt den Replay (`--tier 1` oder `--tier 2`), schreibt
  Bericht und Fehlerdateien; mit `--check` liefert er den Exit-Code fürs
  Merge-Gate.
- **`corpus-diff <lauf-a> <lauf-b>`** — zeigt, was zwischen zwei Läufen neu
  kaputt ist, was repariert wurde und was weiterhin kaputt ist.
- **`corpus-triage <lauf>`** — clustert Fehlschläge in Kategorien und
  schreibt `findings.md`. Erzeugt ausschliesslich Befunde.

### Neue Config-Keys

Genau einer, in `config/config.yaml` unter `paths`:

```yaml
corpus_dir: ../Doco_Detect_corpus
```

Der Korpus liegt bewusst **ausserhalb** des Repos — er enthält 129
4K-PNGs. Versioniert sind nur `corpus/manifest.json` und
`corpus/baseline.json`. Zusätzlich in `.gitignore`: `corpus/runs/`.

### Tests

Neun neue Testdateien mit zusammen **151 Tests**, plus `tests/test_corpus.py`
mit den Markern `corpus` (voller Lauf) und `corpus_smoke` (20-Bilder-Subset).
`tests/conftest.py` wurde rein additiv um die zwei Marker-Registrierungen
ergänzt.

### Dokumentation

`CLAUDE.md` bekam einen Abschnitt „Regressions-Korpus" mit den Dauerregeln,
`README.md` einen ausführlichen Abschnitt mit Aufbau, den zwei Stufen, dem
Sync Mac↔Windows und der Baseline-Regel.

### Commits

26 Commits auf `feature/corpus-harness`, 8443 Zeilen hinzugefügt, **0 Zeilen
gelöscht**. Von `1574781` (Design-Spec) bis `216edca` (Dokumentation).

### Was ausdrücklich NICHT angefasst wurde

- **Der Messpfad.** `docodetect/pipeline.py`, `segmentation.py`,
  `features.py`, `matcher.py`, `calibration.py`, `database.py` sind
  unverändert. Der Runner ruft ausschliesslich die vorhandenen Fassaden
  `pipeline.measure_shot()` und `Pipeline.identify()`. Das funktioniert, weil
  die Bündel-Config `paths.captures_dir` auf `None` setzt und
  `pipeline._save_capture_and_report` bei fehlendem `captures_dir` sofort
  zurückkehrt — der Replay schreibt dadurch nichts nach `data/captures`.
- **Die echte `doco_detect.sqlite3`.** Nur gelesen. Der Snapshot ins Bündel
  entsteht über die sqlite3-Backup-API auf einer `mode=ro`-Verbindung.
- **Schwellen und Gewichte.** `max_z_accept`, `min_llr_margin`,
  `feature_weights`, `sigma_floors` sind unverändert. Der Harness misst, er
  justiert nicht.
- **`docodetect/reporting.py` und `analysis.py`.** Nur importiert, damit die
  Korpus-Zahlen mit denen des bestehenden `analyze`-Befehls identisch sind.

---

## 3. ABWEICHUNGEN VOM PLAN

**Die vier `corpus-*`-Befehle hängen in `docodetect/cli.py`**, nicht in einem
paket-eigenen CLI-Einstieg wie ursprünglich skizziert. Begründung: alle 16
bestehenden Befehle sind dort registriert; ein zweiter Einstiegspunkt wäre ein
abweichendes Muster ohne Gewinn.

**`report.py` und `diff.py` kamen als eigene Module dazu.** Die ursprüngliche
Modulliste hatte Auswertung und Diff nicht getrennt; beide sind gross genug
für eigene Dateien.

**`run_one` legt Replay-Reports unter `runs/<lauf-id>/replay/` ab.** In der
Plan-Selbstprüfung fiel auf, dass die Tier-2-Quoten aus einem Verzeichnis
gelesen wurden, das niemand füllte — der Replay-Report existiert nur im
Worker-Prozess, weil `captures_dir` im Bündel `None` ist.

**Der Cache-Schlüssel wurde erweitert.** Ursprünglich Bild-Hash plus Code- und
Config-Fingerprint. Ein Review zeigte, dass `docodetect/corpus/compare.py`
fehlte — dessen Schwellen-Tabellen erzeugen unmittelbar den gecachten
Bandwert, eine geänderte weiche Stufe hätte alte Ergebnisse als gültig
durchgehen lassen. Ergänzt wurden `compare.py`, der Hash des Golden-Reports
und ein Bündel-Fingerprint je Session.

**`accuracy_top1` rechnet über `reporting.judgement()`, nicht über
`top_k_accuracy()`.** Die Spec behauptete, `top_k_accuracy` liefere dieselbe
Zahl wie der `analyze`-Befehl. Das war falsch: `analysis.py` gibt dem
menschlichen Urteil Vorrang (und schliesst damit das z-Gate ein), während
`top_k_accuracy` nur Label gegen Kandidatenliste vergleicht. Auf den echten
Daten ergab das 46/60 gegen 47/60. Das eine abweichende Bild ist
`1784562586318.png`: der richtige Artikel stand auf Platz 1, aber das z-Gate
verwarf die Identifikation — das System lieferte also kein Ergebnis.

**`compare_tier1` behandelt fehlende Segmentierungs-Signale symmetrisch.**
Ursprünglich wurde der Vergleich still übersprungen, wenn nur die
Golden-Seite keine Kontur hatte. Genau das ist aber der aussagekräftige Fall
„die Segmentierung findet jetzt ein Objekt, wo früher keines war".

**`seg_area_px` vergleicht ausgedünnt gegen ausgedünnt.** Der erste echte
Lauf war rot (88 von 143 FAIL). Ursache war kein Regressionsbefund, sondern
ein Fehler im Vergleich: der Golden speichert nur die auf ~400 Punkte
**ausgedünnte** Kontur (`pipeline._thin_contour`), verglichen wurde sie aber
gegen die Fläche der vollen Replay-Kontur. Nach der Korrektur reproduzierten
alle Bilder der beiden verbliebenen Sessions bit-exakt.

**`test_2_loeffel` wurde aus dem Korpus ausgeschlossen.** Der Plan sah drei
Sessions vor. Der Erstlauf zeigte, dass der Session-Zustand dieser Runde
(14:52–15:31) nicht mehr rekonstruierbar ist: die einzige vorhandene
`calibration/background.png` stammt von 15:45, also von *nach* der Session,
und `background-alt.png` aus den Backups liefert dasselbe Ergebnis. Dort
fielen Farb-, Form- **und** Pixelgrössen durch — ein echter
Segmentierungsunterschied, keine blosse mm-Skalierung. Die Session teilt
damit das Schicksal von `erster_test_loeffel` und `smoke-v2-uiqt`.

**Der ursprüngliche Diskriminator-Test war nicht durchführbar.** Geplant war,
die Einlern-Aufnahmen der betroffenen Artikel erneut zu vermessen und ihre
Schwerpunkt-Position gegen die der Fehlaufnahmen zu stellen. Alle 135
`reference_features`-Zeilen der Löffel-Artikel haben aber `image_path = NULL`
— die Einlern-Bilder wurden nie als Dateien abgelegt. Ersetzt wurde der Test
durch dieselbe Korrelation über alle Korpus-Aufnahmen mit Bündel-Datenbank.

**Zwei Tests schrieben in den echten Korpus-Ordner.** Ein Review fand, dass
die `--check`-Tests nur `BASELINE_PATH` und `MANIFEST_PATH` mockten, nicht
aber den Korpus-Pfad; `cli.main()` lud die echte Config. Real entstanden
sechs Lauf-Verzeichnisse mit Fixture-Daten (nach
`backups/2026-07-21-testmuell-korpus/` verschoben). Behoben durch Isolierung
plus einen Test, der die Invariante an der Wurzel prüft, die der Befehl
tatsächlich benutzt.

**`--tier 2 --changed-only` schaltete die Prüfung still ab.** Replay-Reports
schrieb nur der frisch gerechnete Teil; kam alles aus dem Cache, waren die
Quoten leer und der Baseline-Vergleich übersprang Tier 2 wortlos mit Exit 0.
Behoben: der Replay-Report wandert in den Cache-Eintrag und wird bei
Cache-Treffern im aktuellen Lauf materialisiert; zusätzlich bricht `--check`
bei unvollständigen Quoten mit Exit 1 ab.

**Das Merge-Gate konnte sich selbst entwaffnen.** Das Final-Review fand, dass
`corpus-run --update-baseline` mit dem Default `--tier 1` leere Quoten in die
Baseline schrieb — danach übersprang der Baseline-Vergleich jede Kennzahl
dauerhaft und lautlos. Erschwerend nannte `CLAUDE.md` als Dauerregel
ausgerechnet die Tier-1-Variante. Behoben: `--update-baseline` verweigert den
Vorgang bei leeren Quoten mit Exit 2, und die Dauerregel nennt jetzt beide
Stufen.

**Die Prüfung der Falsch-Akzeptanz-Rate war richtungsverkehrt.** Der
Baseline-Vergleich prüfte durchgehend gegen die *Untergrenze* des
Wilson-Intervalls. Für eine Fehlerrate ist das wirkungslos: sie regressiert
nach oben, und bei einer Baseline von 0/25 mit Untergrenze 0,0 konnte die
Bedingung nie greifen. Belegt: 0/25 → 5/25 lieferte Exit 0. Fehlerraten werden
jetzt gegen die Obergrenze geprüft — relevant, weil `CLAUDE.md` den Schutz vor
Fehlbuchungen als zentrale Eigenschaft des Systems benennt.

**Ein Teil-Lauf sah aus wie eine Freigabe.** `--check` liess sich mit
`--subset`, `--session` und `--article` kombinieren und endete bei sauberem
Ausschnitt mit Exit 0. Jetzt verweigert jeder gefilterte `--check`-Lauf die
Freigabe mit Exit 1 und nennt den gesetzten Filter.

**Zwei Kritische im Runner, gefunden vor dem ersten Lauf.** Erstens galt ein
Segmentierungs-Abbruch als „reproduziert", wenn der Golden `decision ==
"reject"` trug. Das ist untauglich: der Geometrie-Vorfilter verwirft auch
nach vollständig gelungener Messung — im echten Bestand betraf das 15 von 25
Reject-Reports, die bei einem Totalausfall der Segmentierung PASS gemeldet
hätten. Diskriminator ist jetzt, ob `golden.measured` leer ist. Zweitens legte
der Tier-1-Replay eine leere `db.sqlite3` im eingefrorenen Bündel an, weil
`Pipeline.__init__` eine Datenbankverbindung öffnet und `sqlite3.connect`
fehlende Dateien anlegt — genau die Datei, die `corpus-build` dort entfernt.

---

## 4. ZIEL ERREICHT?

### Ja, mit belegten Zahlen

**Testlauf.** Vollständige Suite: **389 passed, 17 skipped**, keine
Fehlschläge. Davon 151 Tests in den neun neuen Korpus-Testdateien. Die 17
übersprungenen sind die Hardware-Tests, die eine angeschlossene Kamera
brauchen (`DOCODETECT_HW_TESTS=1`). `pytest -m corpus_smoke` läuft in 46,6 s.

**Korpus.** 129 Bilder aus zwei Sessions: `phase-a` (67 Bilder, Tier 1) und
`phase-b` (62 Bilder, davon 60 Tier 2). Beide Phasen mit je 15 Artikeln × 4
Aufnahmen. Dass `phase-a` nur Tier 1 fährt, hat der Build selbst festgestellt:
sein Abgleich der in den Reports gespeicherten Referenzwerte gegen
`reference_stats` des Snapshots ergab 0 % Übereinstimmung, für `phase-b`
dagegen 100 %.

**Reproduktion.** Tier 1: **129/129 PASS**, 0 DRIFT, 0 FAIL. Tier 2:
**60/60 PASS**, 0 DRIFT, 0 FAIL.

**Tier 2 reproduziert die Historie exakt** — das war zu Projektbeginn
ausdrücklich ungeprüft. Gegenprobe gegen
`reports/analysis/phase-b-korrigiert/metrics.json`:

| Kennzahl | Korpus | veröffentlicht |
|---|---|---|
| accuracy_top1 | 46/60 | 46/60 ✓ |
| accuracy_top3 | 54/60 | 54/60 ✓ |
| false_accept_rate | 0/25 | 0/25 ✓ |
| auto_accept_rate | 25/**60** | 25/**62** |

Der abweichende Nenner ist erklärt und korrekt: der Korpus führt die zwei
unbewerteten Randberührungs-Aufnahmen als Tier-1-only, die Altauswertung
zählte alle 62 Reports. Der Zähler ist identisch.

**Baseline** (`corpus/baseline.json`): die vier Quoten oben mit ihren
Wilson-Intervallen, plus Code- und Config-Fingerprint des erzeugenden Laufs.

**Laufzeit, gemessen auf einem MacBook mit 10 Kernen, 8 Worker:**

| Lauf | Zeit | Durchsatz |
|---|---|---|
| Tier 1, 129 Bilder | 241,9 s (4,0 min) | 0,53 Bilder/s |
| Tier 2, 60 Bilder | 126,4 s | 0,47 Bilder/s |
| `--check --changed-only` | 0,0 s | Volltreffer im Cache |

Hochrechnung auf 1000 Bilder: **rund 31 min**.

### Nein, an einer Stelle

**Das ursprüngliche Performance-Ziel „1000 Bilder unter 10 min" ist nicht
erreicht und auf dieser Maschine nicht erreichbar.** Die Segmentierung kostet
2,83 s je 4K-Bild und ist speicherbandbreiten-gebunden, nicht rechengebunden:
acht Worker bringen Faktor 1,5, mehr Worker bringen nichts. Die Ursache liegt
in `segmentation.py` und damit im Messpfad, der ohne expliziten Auftrag
unantastbar ist. Das dokumentierte Ziel wurde stattdessen auf die reale
Korpusgrösse umgeschrieben — „voller Korpus unter 6 min", gehalten mit
4,0 min.

### Triage-Ergebnis: die fünf Vorfilter-Kills sind erklärt

Ein **Vorfilter-Kill** heisst: der wahre Artikel hat den Geometrie-Vorfilter
nicht überlebt und fehlt in der Kandidatenliste, ein falscher hat gewonnen.
Fünf solche Fälle aus `phase-b` waren zu klären.

**Diskriminator-Test: negativ.** Über 71 Punkte ergab die Korrelation
zwischen Messfehler und Abstand zur Bildmitte **r = 0,1367** — keine
Positionsabhängigkeit. Die Hypothese, ausserhalb der Bildmitte eingelernte
Referenzen hätten die Stammdaten aufgebläht, ist damit widerlegt; der auf
fünf Punkten gemessene Wert von r = +0,823 war Kleinstichproben-Rauschen.

**Sichtprüfung der zwei Härtefälle: Segmentierung einwandfrei.** Bei
`1784562435798.png` und `1784562504239.png` ist die Laffe geschlossen, der
Stiel bis zur Spitze erfasst, kein Randbeschnitt (98 bzw. 216 px Abstand zum
nächsten Bildrand).

**Die verbleibende Erklärung rechnet sich auf.** Der Vorfilter vergleicht den
gemessenen **minEnclosingCircle-Durchmesser** (bei einem länglichen Löffel
praktisch seine Länge) gegen `hypot(width_mm, depth_mm)` der Stammdaten —
also die Diagonale des **minAreaRect**, näherungsweise √(Länge² + Breite²).
Bei rund 40 mm Löffelbreite ist das systematisch **+4,15 mm** grösser. Zieht
man diesen Versatz ab, bleiben im Mittel −3,16 mm — **innerhalb der
Vorfilter-Toleranz von 6,0 mm**. Hätte der Vorfilter Gleiches mit Gleichem
verglichen, wäre keiner der fünf Kills passiert.

Das ist der in `CLAUDE.md` unter „Messgrössen — bekannte Fallstricke"
dokumentierte Effekt, aber grösser als die dort notierten ~2,8 mm, weil er
mit der Objektbreite skaliert. **Es wurde nichts daran geändert.**

### Offene Punkte

1. **Der Vorfilter vergleicht zwei verschiedene Grössen.** Siehe oben: der
   Versatz erklärt die fünf bekannten Fehlbuchungen vollständig. Eine
   Korrektur berührt `matcher.py` und die Schwellen und braucht einen
   eigenen Auftrag mit Datenbegründung.
2. **`analysis.py` widerspricht sich selbst.** In
   `reports/analysis/phase-b-korrigiert/` zeigt `confusion_matrix.csv` eine
   Diagonale von 47, `metrics.json` nennt `accuracy_top1` = 46. Ursache ist
   dieselbe Definitionslücke: die Matrix vergleicht Vorhersage gegen Label,
   die Quote nutzt das menschliche Urteil. Nicht behoben, weil `analysis.py`
   ausserhalb dieses Auftrags lag.
3. **Session-Fingerprint in neuen MatchReports.** Ausdrücklich aufgeschoben,
   weil es `pipeline.py` berühren würde. Bis dahin läuft die Zuordnung über
   die Rekonstruktions-Logik in `docodetect/corpus/bundle.py`.
4. **Windows ist ungeprüft.** Der erste Lauf dort wird sehr wahrscheinlich
   DRIFT melden (andere OpenCV-Build-Optionen). Das ist der dokumentierte
   Anwendungsfall für `corpus-run --check --accept-drift` plus
   anschliessendes Re-Baselining auf der Plattform.
5. **`phase-a` hat keinen Datenbank-Snapshot** und wird deshalb nie Tier 2
   fahren. Seine 60 bewerteten Aufnahmen prüfen nur Messwerte.
6. **Der Bündel-Fingerprint nutzt Datei-mtime.** Ein erneuter `corpus-build`
   kopiert die Bündel-Dateien neu und invalidiert den Cache dadurch
   konservativ zu oft. Kein Fehler, aber der Grund, wenn ein
   `--changed-only`-Lauf nach einem Build länger dauert als erwartet.
7. **Die Baseline führt `n` ohne Stufentrennung.** Die neue
   Vollständigkeitsschranke vergleicht die Bildzahl des Laufs gegen dieses
   Feld. Heute geht das auf (Tier 1: 129, Tier 2: 60, Baseline `n` = 60),
   und eine Tier-1-Baseline ist ohnehin verboten. Eine nach Stufe getrennte
   `n`-Führung wäre robuster.
8. **`--changed-only` ist beim Arbeiten am Runner wirkungslos.**
   `CODE_DATEIEN` enthält jetzt `corpus/runner.py` und `corpus/bundle.py`,
   damit eine Änderung an der Falsch-Grün-Logik den Cache invalidiert. Die
   Kehrseite: wer am Runner arbeitet, rechnet jedes Mal alles neu. Das ist
   die gewollte, konservative Richtung.
9. **Der volle Testlauf legt Lauf-Verzeichnisse im echten Korpus an.** Die
   Marker `corpus`/`corpus_smoke` werden nicht deselektiert, laufen also im
   normalen `pytest` mit; `test_corpus_tier2_decisions_reproduce` erzeugt
   dabei jedes Mal ein neues `runs/<zeitstempel>/replay/`. By design, aber
   unbegrenzt wachsend — gelegentlich aufräumen.
10. **Kleinere Beobachtungen aus den Reviews**, nicht blockierend: Der
    Replay-Report landet über `write_run` auch in den Failure-Dateien und
    bläht sie auf; der Tier-2-Cache wächst dadurch spürbar;
    `cmd_corpus_run`/`cmd_corpus_diff` lassen rohe Tracebacks durch, während
    der Rest von `cli.py` `sys.exit()` mit Meldung nutzt; `classify_drift`
    hat keine Mindestbildzahl, wodurch bei sehr kleinen Läufen ein Einzelfall
    als „uniform" gelten kann; eine Pipeline-Instanz wird pro Bild statt pro
    Worker gebaut (bewusst zurückgestellt, Gewinn wäre rund 2 %); das
    `corpus_smoke`-Subset liegt durch die Sortierung vollständig in
    `phase-a` und berührt damit weder `phase-b` noch Tier 2.
