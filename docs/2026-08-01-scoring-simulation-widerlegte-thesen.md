# Drei widerlegte Thesen zum Scoring — Leave-one-out-Simulation

**Datum:** 2026-08-01 · **Art:** Negativbefund mit Entscheidung.
**Ergebnis: keine Scoring-Änderung.** Kein Produktivcode, keine Config, keine
Baseline geändert.
**Datenbasis:** Sandbox `neuenroll-2026-08`, **13 voll eingelernte Artikel ×
13 Shots = 169 Leave-one-out-Identifikationen**, 25 Ein-Shot-Artikel als Störer.
MESSER-2 **und** MESSER-6 sind ausgeschlossen — beide sind physisch geprüfte
Duplikate von MESSER-5
([2026-08-01-fixpunkt-test-scoring.md](2026-08-01-fixpunkt-test-scoring.md),
Nachträge). Methodik der Duplikatprüfung:
[2026-08-01-duplikatpruefung-methode.md](2026-08-01-duplikatpruefung-methode.md).

> **Vor jeder künftigen Scoring-Änderung zuerst Abschnitt 6 lesen.** Die
> statistische Basis (effektiv n ≈ 13 Artikel) trägt keine Entscheidung. Sie
> taugt, um Thesen zu WIDERLEGEN — nicht, um eine Änderung zu begründen.

---

## 1. Das eigentliche Ergebnis: der Simulator

`scripts/simulate_scoring.py` rechnet Scoring-Varianten offline auf dem
vorhandenen Bestand durch — **ohne Kamera, ohne neue Aufnahmen**. Damit sind
Fragen dieser Art künftig in Minuten statt in einem Testtag beantwortbar.

Zwei Eigenschaften machen ihn belastbar:

1. **Er reproduziert `matcher.match()` bit-identisch.** Auf allen 169 Fällen:
   Ranking identisch, `max |Δ llr_margin| = 0.00e+00`, `max |Δ max_z| = 0.00e+00`.
   Dazu gehört, die **Rundung auf 4 Nachkommastellen nachzubilden**, die
   `matcher.match` vor dem Summieren anwendet (`weighted=round(...)`,
   `log_score=sum(gerundete)`, `max_abs_z` aus dem gerundeten z). Diese Rundung
   ist nicht kosmetisch: ohne sie weicht der Simulator um bis zu 3·10⁻⁴ ab, bei
   Verlierern mit sehr kleinem σ_enroll deutlich mehr.
2. **Er dupliziert keine Messlogik.** Vorfilter und Merkmalszeilen kommen über
   die privaten Helfer aus `matcher.py` (`_nominal_size_mm`, `_feature_rows`,
   `_sigma_floor`) — dasselbe Muster, mit dem `enrollment_sheet.py` aus
   `features.py` importiert.

Vorab geprüft: `features.compute_enrollment_stats` reproduziert den
gespeicherten `reference_stats`-Cache **bit-identisch** (größte Abweichung
0,000e+00). Die Leave-one-out-Statistiken sind also sauber neu gerechnet und
nicht aus dem Cache genommen. Alle 169 LOO-Zuschnitte behalten alle acht
Merkmale.

Referenz-Baseline (heutiges Scoring, unverändert):

| top1 | top3 | ACCEPT | AMBIGUOUS | REJECT | false_accept | llr p25/Median/p75 | Setgröße | k_safe |
|---|---|---|---|---|---|---|---|---|
| 168/169 | 169 | 41 | **127** | 1 | 0 | 0,49 / 0,99 / 1,80 | 6,40 | 166 |

Die 41 ACCEPT verteilen sich auf nur drei Artikel mit kleinem Kandidatenset
(GABEL-9 13/13, MESSER-8 13/13, LOEFFEL-3 10/13) plus Reste bei LOEFFEL-6 (4/13)
und LOEFFEL-1 (1/13). **Neun der dreizehn Artikel erreichen kein einziges
ACCEPT.**

---

## 2. These 1 WIDERLEGT: „Summe statt gewichtetem Mittel bringt Trennschärfe"

Herkunft: der w(s)-Negativbefund
([2026-08-01-wprofil-negativbefund.md](2026-08-01-wprofil-negativbefund.md),
Abschnitt 3a) zeigte, dass ein Merkmal mit ~9 % Gewichtsmasse eine Margin von
0,11 nicht auf 2,0 hebt, weil `log_score` ein gewichtetes **Mittel** ist. Nahe
lag: dann eben eine Summe.

### `log_score` IST bereits eine gewichtete Summe

**Das ist der kontraintuitive Kern und der Grund, warum die These nicht trägt.**

`matcher.match` rechnet ([matcher.py:336-351](../docodetect/matcher.py)):

```python
wsum = sum(w_eff[f] for f in rows)
...  weighted = w_eff[f] * log_contrib / wsum
log_score = sum(s.weighted for s in scores)
```

`w_eff` ist über **alle acht** Merkmale auf Summe 1 normiert. Trägt jeder
Kandidat alle acht Merkmale, ist `wsum = 1.0` — und die Division durch `wsum`
ist wirkungslos. `log_score` ist dann exakt Σ w·(−0,5 z²), also eine gewichtete
Summe mit Gesamtgewicht 1. **Zwischen „Mittel" und „gewichteter Summe" gibt es
in diesem Bestand keinen Unterschied.**

Gemessen, nicht argumentiert:

| Variante | top1 | ACCEPT | llr Median | Spearman ρ zur Baseline | Mengenüberlappung |
|---|---|---|---|---|---|
| a) Baseline (Mittel) | 168/169 | 41 | 0,99 | — | — |
| **b) sum_weighted** | 168/169 | **41** | **0,99** | **+1,0000** | **41/41** |

Bit-identisch. Die Config-Gewichte summieren sich ohnehin auf exakt 1,000000.

### Wirksam ist nur die ungewichtete Summe — und die ist zu 96 % eine Schwelle

`sum_unweighted` (jedes Merkmal Gewicht 1) ändert tatsächlich etwas, weil es den
**Gewichtsvektor** ändert (Ø verliert seine Dominanz 0,50), nicht die Normierung:

| Variante | top1 | ACCEPT | llr Median | k_safe |
|---|---|---|---|---|
| a) Baseline | 168/169 | 41 | 0,99 | 166 |
| b) sum_unweighted | **169/169** | **148** | 8,35 | **169** |

Sieht nach einem Durchbruch aus. Ist aber überwiegend eine Skalenverschiebung:

- Spearman ρ der LLR-Margins zur Baseline: **+0,9119**
- Die Baseline-Schwelle, die dieselbe ACCEPT-Zahl ergibt, ist **0,155**
- Dort liefert die Baseline **148 ACCEPT bei 0 false_accept**, Mengenüberlappung
  **143/149**

Schwellenkurve der Baseline (nur `min_llr_margin` gesenkt, sonst nichts):

| min_llr_margin | 2,0 | 1,0 | 0,5 | 0,25 | **0,155** | 0,05 | 0,0 |
|---|---|---|---|---|---|---|---|
| ACCEPT | 41 | 84 | 125 | 145 | **148** | 165 | 168 |
| false_accept | 0 | 0 | 0 | 0 | **0** | 0 | 1 |

**Rund 96 % des Gewinns von `sum_unweighted` sind eine verkleidete Senkung von
`min_llr_margin` von 2,0 auf 0,155.** Echt bleibt nur ein kleiner Rest:
top1 168 → 169 und k_safe 166 → 169, also eine geringfügig bessere Sortierung.

Wer das Gate senken will, soll das Gate senken und es so nennen.
`min_llr_margin` ist laut [CLAUDE.md](../CLAUDE.md) der einzige wirksame Schutz
gegen Fehlbuchungen bei baugleichen Artikeln.

### Was im PRODUKTIVBESTAND anders wäre — und gefährlich

Dass `wsum = 1.0` gilt, ist eine **Eigenschaft dieses Bestands**, keine
Eigenschaft des Codes: hier haben alle Artikel mindestens eine Referenz aus
aktuellem Code, alle Kandidaten tragen 8/8 Merkmale, es gibt 0
geometry-only-Fälle.

Im Produktivbestand ist das nicht garantiert. `_feature_rows` lässt Merkmale
aus, wenn die Referenz sie nicht hat — `solidity` fehlt in Referenz-JSONs von
vor dessen Einführung, die vier Ring-Zonen-Merkmale in Referenzen von vor den
Zonen, und Kandidaten ganz ohne `reference_stats` laufen geometry-only mit einem
einzigen Merkmal. Dann ist `wsum < 1` und Mittel ≠ Summe.

**Und dann kippt die Richtung ins Gefährliche:** `log_contrib = −0,5 z²` ist
immer ≤ 0. Eine **unnormierte** Summe über weniger Merkmale ist damit
systematisch **weniger negativ**, also besser. Ein Artikel mit lückenhaften
Referenzen würde einen vollständig eingelernten schlagen — allein weil er
weniger Gelegenheit hatte, Strafpunkte zu sammeln. Die Division durch `wsum`,
die hier wirkungslos aussieht, ist genau der Schutz dagegen.

Wer die Aggregation je anfasst, muss zuerst die Merkmalszahl je Kandidat im
Produktivbestand messen. In dieser Sandbox ist die Frage unsichtbar.

---

## 3. These 2 WIDERLEGT: „Der Vorfilter ist der Hebel"

Herkunft: der Fixpunkt-Test
([2026-08-01-fixpunkt-test-scoring.md](2026-08-01-fixpunkt-test-scoring.md),
Befund 2) zeigte, dass der Margin mit der Kandidatensetgröße einbricht, und
schloss: `diameter_tolerance_mm` verschärfen ist der Hebel, nicht
`min_llr_margin` senken. **Die Simulation widerlegt das.**

| `diameter_tolerance_mm` | top1 | ACCEPT | REJECT | Setgröße | **k_safe** |
|---|---|---|---|---|---|
| 6,0 (heute) | 168/169 | 41 | 1 | 6,40 | **166** |
| 5,0 | 168/169 | 43 | 1 | 5,64 | — |
| 4,0 | 166/169 | 45 | 2 | 4,85 | **35** |
| 3,0 | 158/169 | 44 | 7 | 4,09 | — |

`k_safe` = wie viele Fälle man akzeptieren kann, bevor der erste falsche dabei
ist (Fälle nach Margin sortiert, vom z-Gate verworfene ausgenommen). Das ist die
skalenfreie Kennzahl: sie vergleicht Varianten unabhängig davon, wie groß ihre
Margins ausfallen.

**Der Einbruch von 166 auf 35 ist der Befund.** Die ACCEPT-Zahl steigt kaum
(41 → 45), top1 fällt, REJECT steigt — und die Sortierung nach Margin wird
unbrauchbar.

### Der Mechanismus: der Vorfilter tötet den wahren Artikel

Ein engerer Vorfilter verkleinert das Kandidatenset nicht gleichmäßig. Er
entfernt zuerst Kandidaten, deren gemessener Ø weit vom Nominal liegt — und das
ist bei einem Messausreißer **der wahre Artikel selbst**. Bleibt der wahre
Artikel draußen, gewinnt ein falscher **konkurrenzlos**, mit riesiger Margin:

| Variante | Fall | Margin | max\|z\| | Entscheidung |
|---|---|---|---|---|
| tol 4,0 | LOEFFEL-3 shot 12 → **LOEFFEL-6** | **25,46** | 6,89 | reject (nur durchs Gate) |
| tol 4,0 | LOEFFEL-5 shot 7 → LOEFFEL-2 | 0,91 | 1,72 | ambiguous |
| tol 4,0 | GABEL-12 shot 12 → GABEL-11 | 0,05 | 2,73 | ambiguous |

Die Margin ist im ersten Fall **kein Vertrauenssignal mehr, sondern ein
Alarmsignal**: sie ist groß, *weil* die Konkurrenz fehlt. Das Einzige, was
diesen Fall von einer Fehlbuchung trennt, ist das absolute z-Gate
(`max_z_accept = 3.5`). Bei tol 3,0 gibt es 11 Top-1-Fehler, von denen das Gate
6 abfängt.

### Alle false_accepts der ganzen Runde enthalten die Verschärfung

Über **103 geprüfte Varianten**: 30 mit false_accept > 0, davon **0 ohne
Vorfilter-Verschärfung**.

Und der bekannte Kombinationsfall reproduziert sich exakt:

| Variante | false_accept |
|---|---|
| `sum_unweighted` allein | **0** |
| `tol 4,0` allein | **0** |
| **beides kombiniert** | **1** |
| `sum_unweighted` + `tol 3,0` | **4** |
| `mean` + `floor ×0,5` + `tol 4,0` | **1** |

Zwei einzeln unbedenkliche Änderungen ergeben kombiniert eine Fehlbuchung —
dasselbe Muster wie seinerzeit `alpha=32` mit Gewichtsschema S2. Kombinationen
sind kein Zusatz zur Prüfung, sie sind die Prüfung.

---

## 4. These 3 WIDERLEGT: „Farbe ist toter Ballast"

Herkunft: aus dem w(s)-Negativbefund (Abschnitt 5b) stammt die Zahl **26,6 %
effektive Gewichtsmasse auf vier Farbmerkmalen, die bei 2 von 105 Paaren das
beste Merkmal sind**. Daraus las sich: Farbe kann weg.

**Diese Zahl misst Dominanz, nicht Grenzbeitrag** — eine Fehldeutung meiner
eigenen Statistik. Ein Merkmal, das nie das beste ist, kann trotzdem
Gleichstände brechen.

| Variante | top1 | ACCEPT | **k_safe** |
|---|---|---|---|
| a) Baseline | 168/169 | 41 | **166** |
| Farbgewicht ×0,5 | 168/169 | 43 | — |
| Farbgewicht ×0,25 | 167/169 | 43 | — |
| Farbe ganz weggelassen | **165/169** | 43 | **151** |

ACCEPT steigt kaum (41 → 43), aber top1 fällt um drei und k_safe bricht um 15
Fälle ein. Farbe trägt zwischen poliertem Stahl derselben Serie wenig — aber das
Wenige entscheidet dort, wo sonst nichts mehr entscheidet.

Hinweis: die Trennschärfe-Zahlen der Farbmerkmale aus Lauf `20260801-140818`
sind wegen des Floor-Key-Fehlers überhöht
([2026-08-01-analysis-floor-key-befund.md](2026-08-01-analysis-floor-key-befund.md)).
Diese Simulation benutzt die korrekten Floors über `matcher._FLOOR_KEY`.

---

## 5. Nebenbefunde

### `sigma_floors` senken tauscht AMBIGUOUS gegen REJECT

| Floor-Faktor | top1 | ACCEPT | AMBIGUOUS | REJECT | k_safe |
|---|---|---|---|---|---|
| ×1,0 | 168/169 | 41 | 127 | 1 | 166 |
| ×0,75 | 167/169 | 59 | 107 | 3 | — |
| ×0,5 | 167/169 | 102 | 63 | 4 | 152 |
| ×0,25 | 166/169 | 126 | 38 | 5 | 154 |
| ×0,125 | 166/169 | 141 | 23 | 5 | 155 |

Die ACCEPT-Zahl steigt stark, aber: REJECT steigt mit (1 → 5), top1 fällt, und
k_safe verschlechtert sich um 11–14 Fälle. Kleinere Floors blähen alle z² auf,
also alle Margins — wieder überwiegend Skala. AMBIGUOUS gegen REJECT zu tauschen
ist kein Fortschritt.

`floor ×0,0` ist **strukturell ungültig** und wird nicht ausgewertet: 25 der 38
Artikel haben genau eine Referenz, dort ist σ_enroll = 0 für jedes Merkmal. Mit
Floor 0 wäre σ_eff = 0 und z undefiniert. Der Simulator bricht dort hart ab —
absichtlich, denn ein stillschweigendes z = 0 macht einen Ein-Shot-Störer zum
perfekten Treffer (in einem früheren Zwischenstand genau so passiert: 3
false_accepts aus reinem Artefakt).

### `softmax_temperature` ist wirkungslos

0,5 / 1,0 / 2,0 / 5,0 liefern **identische** Werte in jeder Kennzahl. Das ist
kein Messergebnis, sondern Struktur: die Temperatur skaliert ausschließlich den
Posterior ([matcher.py:369-373](../docodetect/matcher.py)), und **kein Gate liest
den Posterior**. Entschieden wird über `max_abs_z` und die rohe
`log_score`-Differenz. Der Parameter ist reine Anzeige.

---

## 6. VORAUSSETZUNG für jede künftige Scoring-Änderung

**Die statistische Basis dieser Runde trägt keine Entscheidung.**

- 169 Fälle sind **nicht** 169 unabhängige Messungen. 13 Shots eines Artikels
  stammen aus einer Aufnahmeserie; effektiv ist **n ≈ 13** (die Artikel). Über
  Artikel gerechnet erlaubt die Rule of Three bei 0 Fehlern nur „Fehlerrate
  < 21 %". Ein „false_accept = 0" auf dieser Basis widerspricht nichts, es
  belegt nichts.
- **Leave-one-out auf Enrollment-Shots ist keine unabhängige Testaufnahme.**
  Alle Shots stammen aus derselben Session, mit derselben Optik, demselben
  Hintergrund und derselben Auflage.
- **Fixpunkt-Referenzen enthalten keine Positionsstreuung.** σ_enroll ist
  kleiner als im Betrieb, absolute Margins sind optimistisch. Belastbar sind
  ausschließlich die **relativen** Unterschiede zwischen Varianten.
- Die Session hatte Kamera-Unterbrechungen mit Hintergrund-Neuaufnahme; ohne
  Fokus-Lock am Mac ist der Fokus über die Session nicht garantiert identisch.
- Der Bestand enthielt **zwei Duplikate** (MESSER-2 und MESSER-6 als Kopien von
  MESSER-5), die erst nachträglich auffielen. Aus 15 vermeintlichen Artikeln
  wurden 13 echte.

**Bevor hier irgendetwas geändert wird, braucht es:**

1. **Unabhängige Testaufnahmen** — getrennt von den Enrollment-Shots.
2. **Referenzen mit echter Positionsstreuung** — also nicht am Fixpunkt.
3. Beides an der **Windows-Box mit Fokus-Lock**.

Bis dahin ist der Simulator ein Werkzeug zum Ausschließen von Thesen, nicht zum
Begründen von Änderungen.

---

## 7. Entscheidung

**Keine Scoring-Änderung.** Begründung:

| Variante | Warum verworfen |
|---|---|
| b) Summe statt Mittel | `sum_weighted` ist bit-identisch — der Unterschied existiert nicht. `sum_unweighted` ist zu 96 % eine verkleidete Senkung von `min_llr_margin`. |
| c) Farbe abwerten/entfernen | verschlechtert top1 (168 → 165) und k_safe (166 → 151). |
| d) `sigma_floors` senken | tauscht AMBIGUOUS gegen REJECT, k_safe fällt. |
| e) `diameter_tolerance_mm` verschärfen | aktiv gefährlich: k_safe 166 → 35; alle 30 false_accept-Varianten enthalten sie. |
| f) `softmax_temperature` | strukturell wirkungslos. |

Was bleibt, ist der Simulator.

**Und der offene Kern:** 127 der 169 Fälle bleiben AMBIGUOUS, neun der dreizehn
Artikel erreichen kein einziges ACCEPT — auch nachdem beide Duplikate entfernt
sind. Das Problem ist also weder ein Datenfehler noch ein Parameterproblem
innerhalb dieser Architektur.

---

## Verwandte Dokumente

- [2026-08-01-fixpunkt-test-scoring.md](2026-08-01-fixpunkt-test-scoring.md) —
  der Testlauf, dessen Befund 2 hier widerlegt wird; enthält beide
  Duplikat-Nachträge.
- [2026-08-01-duplikatpruefung-methode.md](2026-08-01-duplikatpruefung-methode.md) —
  wie die Duplikate gefunden wurden und warum die Prüfung VOR die Analyse gehört.
- [2026-08-01-wprofil-negativbefund.md](2026-08-01-wprofil-negativbefund.md) —
  Herkunft der Thesen 1 und 3.
- [2026-08-01-analysis-floor-key-befund.md](2026-08-01-analysis-floor-key-befund.md) —
  warum die Farb-Trennschärfen aus `20260801-140818` nicht zitierfähig sind.
