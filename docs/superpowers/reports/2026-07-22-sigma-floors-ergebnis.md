# sigma_floors aus einer echten Messreihe — Ergebnisdokument

Stand 2026-07-22 · Branch `main` · Bezug: [Testtag-Plan](../../2026-07-22-testtag-mac.md),
[Vorfilter-Ergebnisdokument](2026-07-21-vorfilter-laengliche-artikel-ergebnis.md),
[Übergabebericht Regressions-Korpus](2026-07-20-corpus-harness-abschluss.md).

Dieses Dokument ist für eine Sitzung ohne Vorkontext geschrieben.

---

## 1. Auftrag

`matching.sigma_floors` (Mess-Rauschboden je Merkmal, geht als
`sigma_eff = sqrt(sigma_enroll² + sigma_floor²)` in **jedes** z und damit in
jeden Score ein) stand seit Projektbeginn auf geschätzten Startwerten. Am
2026-07-22 lag erstmals eine echte Messreihe vor. Aufgabe: die gemessenen
Werte in die versionierte Config übernehmen, den daraus folgenden Korpus-DRIFT
nach Protokoll abwickeln und die dabei entdeckte Fehlerklasse „Baseline auf
unversionierten Werten" dauerhaft verhindern.

## 2. Die Messreihe

LOEFFEL-14, 18 Identify-Auflagen, Mac-Rig (Session-Kalibrierung vom 2026-07-20,
Kamera-Profil rekonstruiert). Ausgewertet mit
`python -m docodetect.cli analyze-floors data/captures --since 2026-07-22`:

| Merkmal | n | mean | std | **floor (RMS)** | min | max |
|---|---|---|---|---|---|---|
| diameter_mm | 18 | 145.1733 | 1.6308 | **1.6308** | 142.16 | 147.65 |
| circularity | 18 | 0.2105 | 0.0063 | **0.0063** | 0.2035 | 0.2231 |
| solidity | 18 | 0.6195 | 0.0043 | **0.0043** | 0.6119 | 0.6255 |
| delta_e | 36 | 2.8579 | 1.8625 | **3.3971** | 0.28 | 6.7493 |
| hist_bhattacharyya | 36 | 0.1377 | 0.0497 | **0.1462** | 0.06 | 0.2927 |
| hu_log | 18 | 0.0601 | 0.0355 | **0.0693** | 0.0126 | 0.1347 |

Ø-Streuung über die 18 Auflagen: Spannweite 5.49 mm, Std 1.6308 mm. Ein
Ausreißer (`hist_bhattacharyya` = 0.2927, z=3.12, `20260722-135101-853.json`)
— im Floor über den RMS enthalten, nicht entfernt.

## 3. hu_log: warum 0.38 und nicht der Messwert 0.069

**Fünf der sechs Floors wurden unverändert übernommen. `hu_log` nicht.**

Eine `analyze-floors`-Messreihe erfasst die Streuung **einer** Auflage-Serie an
**einem** Rig an **einem** Tag. Sie enthält damit das Auflage-Rauschen, aber
nicht die Streuung über Sessions hinweg (Beleuchtung, Kamera-Profil,
Neu-Enrollment). Für `hu_log` ist dieser Unterschied dramatisch: über die
Sessions des Regressions-Korpus läuft die hu-Distanz eines Artikels zu seiner
**eigenen** Referenz bis **1.3677**, bei einem Median von 0.179 —
zwanzigfach über dem, was die Tagesserie zeigt.

hu-Distanz am Sieger über alle 60 Tier-2-Bilder:

| min | median | p90 | p95 | max |
|---|---|---|---|---|
| 0.0114 | 0.1790 | 1.0947 | 1.1357 | 1.3677 |

Mit Floor 0.069 ist `sigma_eff` für `hu_log` faktisch `sigma_enroll`, und die
großen Distanzen schlagen ungedämpft ins z durch. Das z-Gate
(`max_z_accept = 3.5`) verwarf daraufhin **historisch korrekte** Auflagen, und
die überharte hu-Strafe drückte in zwei weiteren Bildern den korrekten Artikel
aus Rang 1 — also **neue Fehlbuchungen**.

Die Korrektur lief iterativ, weil sich mit dem Floor die Sieger ändern und
damit die bindende Anforderung wandert. Bedingung je Bild:
`floor >= sqrt(distance²/max_z_accept² − sigma_enroll²)` (`distance` und
`sigma_enroll` sind floor-unabhängig).

| Runde | `hu_log` | neue Fehlbuchungen | neue REJECTs korrekter Artikel | bindende Anforderung |
|---|---|---|---|---|
| Messwert | 0.069 | **2** — 46f9b1b3 (LOEFFEL-14→11), daeefc7e (LOEFFEL-15→9) | **4** — 1ea08720 (z 9.94), 9482d13a (z 9.48), a8d29a32 (z 11.88), bef4cba8 (z 13.89); treibendes Merkmal jeweils allein `hu_log` | 0.3207 (bef4cba8/LOEFFEL-7) |
| 2 | 0.33 | 0 | **2** — a8d8c8d7 (z 3.92), f649d598 (z 3.55), beide `hu_log` | 0.3740 (a8d8c8d7/LOEFFEL-3) |
| **final** | **0.38** | **0** | **0** | erfüllt, dort z = 3.44 |

Die Runde-2-Rejects entstanden erst durch die Korrektur selbst: bei 0.069 war
in beiden Bildern ein **falscher** Artikel Sieger, bei 0.33 gewann der
korrekte — und scheiterte dann am Gate.

Bindender Fall: a8d8c8d7 / LOEFFEL-3, hu-Distanz 1.3677, `sigma_enroll`
0.1132 → Floor ≥ 0.3740. **0.38** ist der kleinste Zwei-Nachkommastellen-Wert
darüber.

Neue REJECTs mit den Treibern `solidity` (a8d8c8d7, z 4.28) und `circularity`
(f649d598, z 3.61) aus Runde 1 wurden **nicht** zum Anlass einer
Floor-Anhebung genommen: dort war Rang 1 jeweils der *falsche* Artikel — das
Gate arbeitete korrekt.

## 4. Finale Floors (`config/config.yaml`)

```yaml
sigma_floors:
  diameter_mm: 1.63         # gemessen 1.6308
  circularity: 0.0063
  solidity: 0.0043
  delta_e: 3.40             # gemessen 3.3971
  hist_bhattacharyya: 0.146 # gemessen 0.1462
  hu_log: 0.38              # NICHT der Messwert 0.069 — siehe Abschnitt 3
```

## 5. Belegte Ergebniszahlen

### 5.1 Top-1-Wechsel — alle in dieselbe Richtung

Vergleich Replay gegen die Golden-Reports, 9 Bilder mit verändertem Rang 1:

| Richtung | Anzahl |
|---|---|
| falsch → richtig | **9** |
| richtig → falsch | **0** |
| falsch → falsch | **0** |

| sha8 | Label | alt | neu | Entscheidung | Top-3 neu | Label in Top-3 |
|---|---|---|---|---|---|---|
| 46f9b1b3 | LOEFFEL-14 | LOEFFEL-11 | LOEFFEL-14 | ambiguous | 14, 11, 13 | ja |
| 4f08405b | LOEFFEL-1 | LOEFFEL-5 | LOEFFEL-1 | ambiguous | 1, 5, 6 | ja |
| 53a17205 | LOEFFEL-11 | LOEFFEL-13 | LOEFFEL-11 | ambiguous | 11, 13, 14 | ja |
| a2883cb7 | LOEFFEL-1 | LOEFFEL-5 | LOEFFEL-1 | ambiguous | 1, 5, 2 | ja |
| a8cf4d7a | LOEFFEL-5 | LOEFFEL-4 | LOEFFEL-5 | **accept** | 5, 4, 2 | ja |
| a8d8c8d7 | LOEFFEL-3 | LOEFFEL-1 | LOEFFEL-3 | ambiguous | 3, 1, 6 | ja |
| b22df805 | LOEFFEL-5 | LOEFFEL-4 | LOEFFEL-5 | ambiguous | 5, 4, 2 | ja |
| e24cb7e5 | LOEFFEL-6 | LOEFFEL-1 | LOEFFEL-6 | ambiguous | 6, 1, 2 | ja |
| f649d598 | LOEFFEL-14 | LOEFFEL-11 | LOEFFEL-14 | ambiguous | 14, 11, 13 | ja |

### 5.2 Accept-Bilanz — drei Bezugspunkte, deshalb drei Zahlen

Die Zahlen 25 / 24 / 27 widersprechen sich nicht, sie zählen gegen
verschiedene Referenzen:

| Bezug | accepts | Bemerkung |
|---|---|---|
| Golden-Reports (historisch) | 25 | Vergleichsmaßstab des Replays |
| Baseline-Lauf 2026-07-21 | 24 | mit den **lokalen** Floors gerechnet (siehe Abschnitt 6) |
| **Finaler Lauf** | **27** | — |

- **Neu gegenüber den Goldens: 2** — `957a3f77` (LOEFFEL-12) und `a8cf4d7a`
  (LOEFFEL-5), beide Rang 1 == wahres Label, beide korrekt.
- **Neu gegenüber dem alten Baseline-Lauf: 3** — zusätzlich `2c88e15a`
  (LOEFFEL-4), Rang 1 == wahres Label, korrekt. Dieses Bild ist im Golden
  `accept`; die lokalen Floors hatten es auf `ambiguous` gedrückt, die
  gemessenen stellen das Golden-Verhalten wieder her.

**Alle 27 accept-Bilder wurden einzeln gegen ihr wahres Label geprüft: 27×
richtig, 0× falsch.** Das ist die direkte Auszählung hinter
`false_accept_rate = 0/27`.

### 5.3 Quoten

| Kennzahl | Baseline 2026-07-21 | final 2026-07-22 |
|---|---|---|
| accuracy_top1 | 46/60 | 46/60 |
| accuracy_top3 | 56/60 | **59/60** |
| auto_accept_rate | 24/60 | **27/60** |
| false_accept_rate | 0/24 | **0/27** |
| decisions | ambiguous 35, accept 24, reject 1 | ambiguous 32, accept 27, reject 1 |

**`accuracy_top1` ist als Regressionskennzahl derzeit blind** — das ist beim
Abgleich der obigen Zahlen aufgefallen und gehört als Befund festgehalten:
`tier2_quotas` rechnet sie über `reporting.judgement()`, und das gibt
`report.verdict` (dem eingefrorenen menschlichen Urteil aus der Historie)
Vorrang vor dem Label-Vergleich. Alle 60 Korpus-Bilder **haben** einen Verdict
(46 `correct`, 14 `wrong`), also ist die Kennzahl eine Konstante: sie kann
sich durch keine Matcher-Änderung bewegen, weder nach oben noch nach unten.

Die tatsächliche Top-1-Trefferquote (roh, `top1 == label`) zeigt die
Verbesserung, die `accuracy_top1` verschweigt:

| | roh top1 == label |
|---|---|
| Golden-Reports | 47/60 |
| finaler Lauf | **56/60** |

+9 — exakt die 9 Bilder aus 5.1. Richtungstabelle und Quotentabelle sind
damit konsistent; sie messen nur Verschiedenes.

## 6. Der `config.local.yaml`-Vorfall und der neue Wächter

Die Tier-2-Baseline vom 2026-07-21 wurde gegen `sigma_floors` gerechnet, die
in der **unversionierten** `config/config.local.yaml` standen
(`hist_bhattacharyya: 0.15`, `hu_log: 0.35` statt der Repo-Werte 0.05/0.15).
Damit verglichen `corpus-run --check` und die Baseline gegen Werte, die kein
anderer Rechner und kein Reviewer je zu sehen bekommt — die Kennzahl misst
in diesem Zustand nichts mehr. Der heutige DRIFT bemaß sich folglich gegen
diese lokalen Werte, nicht gegen die alten Repo-Werte.

Gegenmaßnahme in `docodetect/corpus/runner.py`:

- `FINGERPRINT_ABSCHNITTE` = Vereinigung von `CONFIG_TEILE_TIER1` und
  `CONFIG_TEILE_TIER2`, also `features` + `matching`.
- `pruefe_lokale_overrides()` läuft als erste Anweisung in `run_corpus()` und
  bricht mit `RuntimeError` ab, sobald die lokale Config einen dieser
  Abschnitte überschreibt. Bewusst **tier-unabhängig**: `matching` beeinflusst
  nur Tier 2, aber ein Rechner in diesem Zustand erzeugt beim nächsten
  Tier-2-Lauf still eine unversionierte Baseline.
- `docodetect/config.py::local_override()` liest die lokale Datei getrennt
  aus (nach dem Deep-Merge ist nicht mehr erkennbar, welcher Wert von wo kam);
  `load_config()` benutzt dieselbe Funktion.
- 6 neue Tests in `tests/test_corpus_runner.py`, darunter einer, der
  sicherstellt, dass der Abbruch **vor** dem ersten gerechneten Bild kommt
  (sonst stünden bereits Cache-Einträge gegen die unversionierten Werte).

`CLAUDE.md` sagte bisher das Gegenteil — gemessene `sigma_floors` gehörten
„NUR in `config/config.local.yaml`". Genau diese Regel hat den Vorfall
erzeugt und ist korrigiert: `matching` und `features` sind dort jetzt
ausdrücklich verboten, `camera.index` und `geometry.camera_height_mm` bleiben
zulässig. `geometry.camera_height_mm` ist unkritisch, weil es nur beim
Kalibrieren gelesen wird und das Replay die eingefrorene `calibration.json`
aus dem Bündel lädt.

## 7. Verifikation

- `corpus-run --tier 1 --check`: **OK, 129/129**. Bewusst ohne Cache gefahren
  (420 s), weil die Cache-Buchführung nach der Wächter-Änderung nicht
  eindeutig zu lesen war.
- `corpus-run --tier 2 --check`: **OK** — vor und nach `--update-baseline`,
  und erneut nach jeder Änderung an der Delta-Datei (sie geht in
  `code_fingerprint` ein, jede Änderung erzwingt eine Neurechnung).
- Alle 60 Tier-2-Bilder haben einen Eintrag in
  `corpus/accepted_deltas/2026-07-22-floors.json` mit Einzelbegründung
  (2× Entscheidungswechsel, 8× reiner Top-1-Wechsel, 50× reine
  Score-Verschiebung). Dass **alle** Bilder betroffen sind, ist erwartbar:
  jeder Floor geht über `sigma_eff` in jedes z ein.
- Testlauf: **439 passed, 17 skipped** (456 collected).

  Abgleich gegen den Vorstand `d984882`, gemessen statt geschätzt:

  | Stand | collected | passed | skipped |
  |---|---|---|---|
  | `d984882` (Repo, Korpus vorhanden) | 450 | 433 | 17 |
  | HEAD | 456 | **439** | 17 |

  Differenz +6 collected / +6 passed = exakt die sechs Wächter-Tests.
  Gemessen wurde `d984882` in einem `git worktree`, dort ergaben sich
  **428 passed / 22 skipped**: in einem Worktree löst `paths.corpus_dir`
  relativ zur Worktree-Wurzel auf, der Korpus fehlt also. Genau fünf Tests
  skippen deshalb zusätzlich — vier in `tests/test_corpus.py` (Marker
  `corpus`) und einer in `tests/test_floor_analysis.py:219`, der **keinen**
  Marker trägt und deshalb bei `-m "corpus or corpus_smoke"` nicht
  mitgezählt wird. 428 + 5 = 433.

  Randbefund: die Commit-Message von `d984882` nennt „429 passed, 17
  skipped" = 446, ihr eigener Baum sammelt aber 450 Tests ein. Diese Zahl
  war schon beim Schreiben um 4 inkonsistent; der gemessene Wert ist 433.

## 8. Offene Punkte

1. **Der hu_log-Floor 0.38 absorbiert Session-Effekte, nicht nur
   Auflage-Rauschen.** Er ist damit ehrlich hergeleitet, aber konservativ: er
   dämpft ein Merkmal, das über Sessions hinweg stark streut, für *alle*
   Vergleiche. Nach den phase-c- bzw. Windows-Sessions prüfen, ob die
   Session-Streuung dort kleiner ist (stabilere Beleuchtung in der Box) und
   der Floor wieder enger gefasst werden kann. Vorgehen wie hier: Floor
   senken, `corpus-run --tier 2 --check`, neue REJECTs korrekter Artikel auf
   das treibende Merkmal ansehen.
2. **Auflösungs-Wächter steht aus.** Die Live-Auflösung wird nicht gegen
   `image_width`/`image_height` aus `calibration.json` geprüft; am 2026-07-22
   lief das Rig zeitweise auf 1080p gegen eine Kalibrierung anderer Auflösung.
   Test-Fixture dafür liegt unversioniert in `data/quarantine/` (zwei
   Reports des Vorfalls plus Bilder) — bewusst nicht ins Repo, aber auch
   nicht gelöscht.
3. **`accuracy_top1` ist verdict-eingefroren** (Abschnitt 5.3) und taugt in
   der jetzigen Form nicht als Regressionskennzahl. Entweder eine rohe
   Top-1-Quote danebenstellen oder `tier2_quotas` so ändern, dass für
   Korpus-Replays der Label-Vergleich gilt und der Verdict nur dort
   einspringt, wo kein Label existiert. Nicht in diesem Auftrag geändert —
   das ist eine Kennzahlen-Definition, die eine eigene Entscheidung braucht.
