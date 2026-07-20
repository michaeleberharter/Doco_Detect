# Real-Capture-Regressions-Harness (Korpus) — Design

Datum: 2026-07-20 · Branch: `feature/corpus-harness` · Status: freigegeben

Ein Regressions-Harness, das jede Änderung am Messpfad gegen ~143 echte,
bewertete Aufnahmen prüft. Die Original-MatchReports **sind** die Goldens: sie
enthalten Label, Verdict und die damals gemessenen Werte.

---

## 1. Bestandsaufnahme (Ergebnis, read-only ermittelt)

176 Report-JSONs, 134 mit Label + Verdict. Das Report-Schema trägt alles
Nötige: `measured` (15 Felder), `contour`, `centroid_px`, `image_size`,
`thresholds`, `w_global`, `alpha` und pro Kandidat `sigma_enroll`,
`sigma_eff`, `z`, `reference`, `n_shots`.

### 1.1 Session-Identifikation ohne Fingerprint im Report

Reports tragen kein Session-Feld (das Einbetten berührt `pipeline.py` und ist
laut Auftrag aufgeschoben). Die Zuordnung geht trotzdem ohne Zeitstempel-Raterei
über drei **aus den Reports rekonstruierbare** Fingerprints:

| Fingerprint | Herleitung | Trennt |
|---|---|---|
| `mm_per_px` | `circle_diameter_mm` ÷ minEnclosingCircle(`contour`) | Kalibrier-Epochen |
| `sigma_floors` | `sqrt(sigma_eff² − sigma_enroll²)` je Merkmal | Config-Epochen |
| DB-Identität | `candidates[].features[].reference` + `n_shots` gegen `reference_stats.scalar_mean` | **exakter** DB-Abgleich |

Der DB-Abgleich ist kein Indiz, sondern ein Gleichheitstest auf
Fliesskomma-Ebene. Alle drei Fingerprints stimmen mit den Zeitstempeln überein.

### 1.2 Provenienz-Tabelle

| Session | Zeit (2026-07-20) | Reports / bewertet | mm_per_px | floors | DB-Snapshot | Bilder | Tier |
|---|---|---|---|---|---|---|---|
| `erster_test_loeffel` | 14:01–14:06 | 19 / 3 | 0,078879 | alt | `vor-ab-test` 95 % | backups | **ausgeschlossen** |
| `test_2_loeffel` | 14:52–15:31 | 14 / 11 | 0,078886 | neu | `neue-position` **100 %** | vorhanden | 1 + 2 |
| `phase-a` (`test_n_60_loeffel`) | 16:08–16:39 | 67 / 60 | 0,078784 | neu | **keiner** (0 %) | vorhanden | **nur 1** |
| `phase-b` (`data/captures`) | 17:31–17:52 | 62 / 60 | 0,078788 | neu | Live-DB **100 %** | vorhanden | 1 + 2 |
| `smoke-v2-uiqt` | 07-19 23:35 | 14 / 0 | 0,2 | alt | keiner | **fehlen** | **ausgeschlossen** |

**Korpus-Umfang (Entscheidung):** nur die drei sauberen Sessions —
143 Reports, 131 bewertet. `erster_test_loeffel` fällt raus (nur 3 bewertet,
gemischt 1080p/4K, alte `sigma_floors`), `smoke-v2-uiqt` ebenfalls
(synthetisch, `mm_per_px` 0,2, Bilder nicht auffindbar).

**Belege für die beiden kritischen Zeilen:** `reference_stats.updated_unix` der
Live-DB reicht bis 16:56 — nach Phase A, vor Phase B. Sie passt deshalb zu
191/191 Phase-B-Kandidatenwerten und zu null aus Phase A. Ihr mtime (17:27)
liegt vor Phase-B-Beginn und blieb während der Session unverändert.

**Hintergründe:** `calibration/background.png` und
`backups/2026-07-20-vor-ab-test/background-alt.png` unterscheiden sich mit
mean-absdiff 0,43 praktisch nicht — eine Beleuchtungs-Ära, ein Bündel-
Hintergrund genügt für alle drei Sessions.

### 1.3 Reproduzierbarkeit (Spike-Ergebnis)

Der aktuelle Code reproduziert die Phase-B-Messwerte **bit-exakt**: über
10 Bilder und alle 8 Skalare `max|Δ| = 0,00000`. Die Segmentierung ist
vollständig deterministisch. Damit sind die Original-Reports belastbare
Goldens, und die Toleranzen können auf das Rundungsquantum gehen.

**Ungeprüft:** ob Tier 2 (Entscheidung) ebenso exakt reproduziert. Der Spike
deckte nur Segmentierung und Merkmale ab. Eine Abweichung beim Erstlauf ist
ein **Befund**, kein Anlass, die Baseline anzupassen.

---

## 2. Ablage und Konfiguration

Neuer Config-Key `paths.corpus_dir`, Default `../Doco_Detect_corpus` —
ausserhalb des Repos, damit die PNGs nie in git landen. Versioniert wird
ausschliesslich `corpus/manifest.json` **im Repo**; alle Pfade darin sind
relativ zu `corpus_dir`. Das Manifest existiert damit genau einmal.

```
<corpus_dir>/<session>/
  bundle/
    session.json        Fingerprints, Provenienz, effektive Matching-Config
    background.png
    calibration.json
    db.sqlite3          optional — fehlt er, ist die Session Tier-1-only
  images/<wahrer Artikel>/<sha8>.png
  images/_unbewertet/<sha8>.png
  reports/<sha8>.json   Golden
```

Umzug Mac → Windows: Ordner kopieren, `paths.corpus_dir` in
`config.local.yaml` setzen. Das Manifest kommt aus git.

Unbewertete Reports (kein Label / kein Verdict) landen unter
`images/_unbewertet/` und laufen **nur in Tier 1**. Konkret betrifft das in
Phase B die zwei Randberührungs-Reports — sie sind genau die zwei unbewerteten
der 62 und bleiben als Segmentierungs-Regressionsfälle wertvoll.

### 2.1 DB-Snapshots

Read-only. `corpus-build` kopiert über die sqlite3-Backup-API aus einer
`mode=ro`-Verbindung und **verifiziert danach** den Referenz-Abgleich gegen die
Reports der Session. Weniger als 100 % Übereinstimmung ⇒ Session fällt
automatisch auf Tier-1-only zurück, mit Vermerk im Manifest. Genau dieser
Mechanismus hat Phase A korrekt aussortiert.

Die Live-`doco_detect.sqlite3` wird nur gelesen, nie geschrieben und nie im
Schema angefasst (bestätigt durch den Auftraggeber, entgegen der
Default-Regel in CLAUDE.md — dort als Ausnahme zu dokumentieren).

---

## 3. Tier 1 — Reproduktion (jedes Bild, ohne DB)

Replay von Segmentierung + Merkmalen gegen den Golden desselben Bildes.

**Verglichen wird:**
- die 8 Skalare aus `measured`
- die Vektor-Merkmale (`hue_hist`, `hu_moments`, `lab_center`/`_rim`,
  `hs_hist_center`/`_rim`, `mean_hsv`) über max-abs-Differenz
- als Segmentierungs-Signale: `touches_border`, Konturfläche, Schwerpunkt

**Drei Bänder je Merkmal:**

| Band | Bedingung |
|---|---|
| PASS | Δ ≤ Rundungsquantum (Ø ±0,005 mm; Rundheit/Solidity ±0,00005) |
| DRIFT | Quantum < Δ ≤ weiche Stufe (Ø ±0,2 mm; Rundheit/Solidity ±0,01) |
| FAIL | Δ > weiche Stufe |

Das Rundungsquantum wird je Feld **aus der im Report gespeicherten
Nachkommastelle abgeleitet**, nicht hart kodiert.

---

## 4. Tier 2 — Entscheidung (nur mit DB-Snapshot)

Der Runner baut eine Bündel-Config (`paths.db_file`,
`calibration.background_file`, `calibration.file` zeigen ins Bündel;
`paths.captures_dir: null`) und ruft `Pipeline.identify()`. Weil
`_save_capture_and_report` bei fehlendem `captures_dir` sofort zurückkehrt,
schreibt der Replay nichts — `pipeline.py` bleibt unverändert.

**Vergleichslogik, zweigeteilt:**

| Grösse | Vergleich |
|---|---|
| `decision` | **exakt** |
| Top-k-Reihenfolge | **exakt** (Artikelnummern in Reihenfolge) |
| `gate_passed` | **exakt** |
| `llr_margin` | Drei-Band (Quantum aus Nachkommastelle, weiche Stufe ±0,05) |
| `max_z_winner` | Drei-Band (Quantum aus Nachkommastelle, weiche Stufe ±0,05) |

Ohne die Drei-Band-Logik auf den beiden Gleitkomma-Grössen wäre Tier 2
implizit bit-exakt und würde beim ersten Bibliotheks-Update flächendeckend
kippen, ohne zwischen Drift und Regression zu unterscheiden.

**Aggregation** über `reporting.summarize()` und `reporting.top_k_accuracy()`
— dieselbe Implementierung wie `analyze`, damit die Zahlen zwischen den
Werkzeugen identisch bleiben. Kennzahlen: Top-1, Top-3, Auto-Accept-Rate,
False-Accept-Rate, je mit Wilson-Intervall.

---

## 5. Runner (`corpus-run`)

ProcessPool aus der stdlib. Default `--workers 8` — gemessenes Optimum,
10 Worker bringen nichts. Aufgaben nach `(session, sha)` sortiert
(deterministisch); Bündel-Kontext pro Worker in einem Modul-Dict gecacht, also
einmal pro Worker und Session geladen.

**Filter:** `--session`, `--article`, `--tier`, `--subset N` (deterministisch
die ersten N der SHA-Sortierung, damit ein Subset stabil bleibt).

**`--changed-only`:** Ergebnis-Cache, Schlüssel = Bild-SHA + Code-Fingerprint
(SHA-256 über `segmentation.py`, `features.py`, `matcher.py`, `pipeline.py`,
`calibration.py`, `database.py`) + Fingerprint der matching-relevanten
Config-Teilbäume (`matching.*`, `features.*`, `geometry.*`). Jede Code- oder
Schwellenänderung invalidiert den Cache automatisch.

**Ausgabe** je Lauf nach `<corpus_dir>/runs/<run_id>/` — Laufartefakte sind
flüchtig und gehören nicht ins Repo (nur `manifest.json` und `baseline.json`
sind versioniert):
- `summary.md` — Kennzahlen, Laufzeit, Bilder/s, Drift-Klassifikation
- `metrics.json` — maschinenlesbar
- `failures/<sha8>.json` — je Fehler ein Diff: Golden vs. Jetzt pro Merkmal,
  z-Werte, Gate-Status, Pfad zum PNG

**`--check`:** vergleicht gegen `baseline.json`, Exit 0 (ok) / 1 (Regression),
bisect-tauglich. **DRIFT und FAIL brechen beide** — auf gepinnter Umgebung ist
jede Abweichung code-verursacht. `--accept-drift` lässt nur FAIL brechen, für
die zwei legitimen Ereignisse: bewusstes Bibliotheks-Update und
Plattformwechsel Mac → Windows. Danach ist ein begründetes Re-Baselining
Pflicht.

**Drift-Klassifikation im Summary** (Vorlage für `corpus-triage`):
- „N Bilder mit uniformer Drift ≤ X" ⇒ Muster Bibliothek/Plattform
- „Ausreisser-Drift auf einzelnen Bildern" ⇒ Muster Code-Regression

### 5.1 Performance — gemessen, nicht geschätzt

| Konfiguration | Durchsatz | 1000 Bilder |
|---|---|---|
| 1 Prozess | 0,33 Bilder/s | 50 min |
| 8 Worker, `cv2.setNumThreads(1)` | 0,48 Bilder/s | 34,5 min |
| 10 Worker | 0,48 Bilder/s | 34,5 min |
| 8 Worker, cv2 auto | **0,52 Bilder/s** | **32 min** |

Kostenverteilung je Bild: `segment` 2,83 s (95 %), `extract` 0,115 s (4 %),
`imread` 0,04 s (1 %).

**Das ursprüngliche Ziel „1000 Bilder < 10 min" ist auf diesem Mac nicht
erreichbar.** Zehn Kerne bringen nur Faktor 1,5: die Segmentierung ist
speicherbandbreiten-gebunden (4K-Vollbild-Durchläufe), nicht rechengebunden.
Die Ursache liegt in `segmentation.py` und ist als Messpfad ohne expliziten
Auftrag unantastbar.

**Neues, dokumentiertes Ziel:** voller Korpus (143 Bilder) < 6 min,
`--changed-only`-Lauf < 30 s. Die 32-min-Messung steht als belegte Tatsache in
README und Summary.

---

## 6. Baseline

`corpus/baseline.json`, versioniert. Erzeugt aus dem ersten vollen Lauf:
Tier-2-Quoten mit Wilson-Intervallen, Tier-1-Bandverteilung, Anzahl Bilder je
Session. Regression, wenn eine neue Quote unter die Wilson-Untergrenze der
Baseline fällt.

Änderung ausschliesslich über explizites `corpus-run --update-baseline`, mit
Begründungspflicht im Commit.

---

## 7. Diff und Triage

**`corpus-diff <runA> <runB>`** — neu kaputt / repariert / weiterhin kaputt,
plus Metrik-Deltas.

**`corpus-triage <run>`** clustert Failures in Kategorien:

| Kategorie | Signatur |
|---|---|
| Messwert-Drift | Skalare ausserhalb Quantum, Kontur stabil |
| Segmentierungs-Änderung | Konturfläche/`touches_border` verändert |
| Vorfilter-Kill | wahrer Artikel fehlt in der Kandidatenliste |
| Gate-Kipp | `gate_passed` gekippt, Messwerte stabil |
| Label-Verdacht | hohe Konfidenz gegen das Label |

Ausgabe `findings.md` mit Hypothesen und PNG-Links. **Triage erzeugt nur
Befunde — niemals Code-, Schwellen- oder Baseline-Änderungen.**

### 7.1 Die fünf Vorfilter-Kills aus Phase B (Definition und Datenlage)

**„Kill" ≠ REJECT.** Ein Kill liegt vor, wenn der *wahre* Artikel den
Geometrie-Vorfilter nicht überlebt hat und ein falscher gewonnen hat. Die
Entscheidungs-Spalte ist dafür der falsche Schlüssel; das Kriterium lautet
„bewertet falsch **und** wahrer Artikel fehlt in der Kandidatenliste".
Maschinenlesbar in
`reports/analysis/phase-b-korrigiert/error_attribution_unattributed.csv`.

Verglichen wird gegen die **Vorfilter-Basis des wahren Artikels**, also
`hypot(articles.width_mm, articles.depth_mm)` — nicht gegen
`top1_nominal_mm` aus der CSV, das ist das Nominalmass des *Siegers*.

| Capture | wahr → Sieger | Ø gemessen | Vorfilter-Basis wahr | Δ |
|---|---|---|---|---|
| `1784561499560.png` | L1 → L5 | 190,50 | 197,47 | **−6,97** |
| `1784562390997.png` | L1 → L5 | 191,45 | 197,47 | **−6,02** |
| `1784562412154.png` | L2 → L5 | 187,66 | 195,03 | **−7,37** |
| `1784562435798.png` | L3 → L4 | 188,83 | 197,24 | **−8,41** |
| `1784562504239.png` | L6 → L5 | 190,13 | 197,91 | **−7,78** |

Alle fünf messen zu kurz und überschreiten `diameter_tolerance_mm = 6,0` —
das ist der Kill-Mechanismus. Die beiden Härtefälle sind `1784562435798.png`
(−8,41) und `1784562504239.png` (−7,78).

Der sechste unattribuierte Fall `1784562586318.png` ist **kein Kill**, sondern
„Top-1 korrekt, aber z-Gate-Reject" — nicht mitzählen.

**Zwei Abweichungen zur mündlichen Beschreibung, aus den Daten belegt:**

1. **Alle fünf Kills sind AMBIGUOUS, keiner ist REJECT.** Sowohl die CSV als
   auch die unabhängige Rekonstruktion zeigen fünfmal `ambiguous`. Das einzige
   `reject` in der Datei ist der ausgeschlossene sechste Fall.
2. **Die Kills liegen nicht am Rand, sondern zentral.** Abstand zur Bildmitte
   (1920 / 1080): Kills median **102 px** (44 … 350), übrige 57 Phase-B-
   Aufnahmen median **463 px** (12 … 1519). Die beiden Härtefälle sind die
   beiden zentralsten Aufnahmen überhaupt (44 px, 102 px). Zum Vergleich: die
   Phase-A-z-Gate-Rejects lagen tatsächlich weit rechts (x = 2500 … 3490).

**Zwei Hypothesen für die Triage, beide unbestätigt und additiv:**

1. **Positionsabhängige Projektion.** Ein Objekt genau unter der Kamera wird
   senkrecht projiziert und misst seine wahre Grösse; ausserhalb der Mitte
   projiziert die Oberseite eines Objekts mit Höhe nach aussen und misst zu
   gross. Wurden die Referenzen überwiegend ausserhalb der Mitte eingelernt,
   sind die Stammdaten systematisch aufgebläht — die „zu kurzen" Kills wären
   dann die korrekt vermessenen Aufnahmen. Zu prüfen gegen die
   Einlern-Positionen.
2. **Bekannter Grössen-Versatz.** `articles.width_mm/depth_mm` sind die Seiten
   des minAreaRect, `circle_diameter_mm` ist der minEnclosingCircle-Ø (siehe
   CLAUDE.md, „Messgrössen — bekannte Fallstricke"). Der Vorfilter vergleicht
   `hypot(width, depth)` gegen den Kreis-Ø; für einen Löffel sind das zwei
   verwandte, aber nicht identische Grössen. Ein Teil der −6 … −8,4 mm kann
   dieser dokumentierte Versatz sein.

Die Triage trennt beide Anteile, ändert aber nichts — weder Schwellen noch
Stammdaten.

**PNG-Sichtung, verpflichtend im Erstlauf-Bericht** für `1784562435798.png`
und `1784562504239.png`: Ist die Stielspitze vollständig segmentiert, oder
frisst der Bildrand Kontur? Wie liegt der Löffel relativ zur Bildmitte?

---

## 8. Tests

`tests/test_corpus.py`, zwei Marker in `tests/conftest.py` registriert:

- `corpus` — voller Lauf
- `corpus_smoke` — festes 20-Bilder-Subset für den Alltag

Beide skippen mit klarer Meldung, wenn der Korpus lokal fehlt — Muster wie die
bestehenden Goldens in `tests/test_real_captures.py`. **Bestehende Tests
bleiben unberührt.**

---

## 9. Modulaufbau

Neues Paket `docodetect/corpus/` statt einer Einzeldatei:

| Modul | Aufgabe |
|---|---|
| `manifest.py` | Manifest lesen/schreiben, SHA-256, Dedup |
| `bundle.py` | Session-Bündel bauen und verifizieren, Fingerprints |
| `runner.py` | ProcessPool, Tier 1 + Tier 2, Cache |
| `compare.py` | Drei-Band-Logik, Diff-Erzeugung |
| `triage.py` | Failure-Clustering, `findings.md` |
| `cli.py` | die vier `corpus-*`-Befehle, eingehängt in `docodetect/cli.py` |

Die vier Befehle: `corpus-build`, `corpus-run`, `corpus-diff`, `corpus-triage`.

---

## 10. Invarianten

- **Messpfad read-only.** `pipeline.py`, `segmentation.py`, `features.py`,
  `matcher.py` werden nicht angefasst. Der Runner nutzt ausschliesslich
  `pipeline.measure_shot()` und `Pipeline.identify()`.
- **Keine neuen Pflicht-Dependencies.** `multiprocessing` aus der stdlib.
- **Keine Schwellen-/Gewichtsänderungen.** Der Harness misst, er justiert nicht.
- **Destruktives immer als Verschieben** nach `backups/<datum>-<zweck>/`.
- Kompletter Testlauf am Ende. `git commit`/`push` erst nach Rückfrage.

---

## 11. Ausdrücklich aufgeschoben

Das Einbetten eines Session-Fingerprints in neue MatchReports berührt
`pipeline.py` und kommt als eigener Mini-Auftrag, sobald der UI-Branch gemergt
ist. Bis dahin läuft die Session-Zuordnung über die Rekonstruktions-Logik aus
Abschnitt 1.1.
