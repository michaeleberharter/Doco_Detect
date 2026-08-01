# Block B: Paarweises Scoring — nicht gebaut, aber nicht widerlegt

**Datum:** 2026-08-01 · **Art:** Negativbefund mit Entscheidung, plus ein
Mechanik-Befund.
**Ergebnis: paarweises Scoring wird nicht gebaut.** Kein Produktivcode, keine
Config.
**Datenbasis:** 169 Leave-one-out-Fälle über 13 echte Artikel,
`scripts/analyse_paarweises_scoring.py`.

---

## 1. Die Frage und die Kontrolle, die sie beantwortet

Bei zwölf Kandidaten lautet die Entscheidungsfrage nicht „wer passt am besten",
sondern „Platz 1 oder Platz 2". Die Fisher-Adaption läuft heute über das ganze
Kandidatenset; auf das Spitzenpaar angewandt wäre sie schärfer.

Die Kernfrage war: **ändert ein paarweiser Nachschlag die Reihenfolge, oder nur
den Abstand?** Beantwortet nicht durch Argument, sondern durch eine Kontrolle:

**B4** = derselbe Nachschlag wie B2, aber mit **erzwungen unveränderter
Reihenfolge**. Wenn B4 identische Kennzahlen liefert, hat der
Ordnungsmechanismus nichts beigetragen.

| Variante | top1 | ACCEPT | k_safe | ρ | äquiv. Schwelle | Überlappung |
|---|---|---|---|---|---|---|
| a) Baseline | 168/169 | 41 | 165 | — | — | — |
| B2) Nachschlag α=8 | 168/169 | 60 | 167 | +0,9367 | 1,385 | 47/60 |
| **B4) α=8, Reihenfolge FIX** | **168/169** | **60** | **167** | **+0,9367** | **1,385** | **47/60** |

**Identisch in jeder Kennzahl.** Der Nachschlag ist eine Abstandsoperation.

Direkt gezählt bestätigt das dasselbe:

| Variante | Reihenfolge getauscht | korrekt→falsch | falsch→korrekt |
|---|---|---|---|
| B1 α=2 | 0/169 | 0 | 0 |
| B2 α=8 | 0/169 | 0 | 0 |
| B3 α=32 | 1/169 | **0** | 1 |
| B5/B6 global α=8/32 | 0/169 | 0 | 0 |

Das befürchtete Risiko — ein Nachschlag dreht die Reihenfolge zugunsten des
falschen Artikels — **tritt nicht ein**. Kein einziger korrekt→falsch-Tausch.
Aber ein Ereignis in 169 Fällen trägt keine Ratenaussage; ein Verfahren, das die
Reihenfolge prinzipiell ändern kann, bräuchte für eine Risikoaussage deutlich
mehr Fälle.

### Präzisierung: „nur der Abstand" ≠ „monotone Transformation"

Zwei verschiedene Dinge, die nicht verwechselt werden dürfen:

- Reihenfolge der **Kandidaten innerhalb eines Falls**: unverändert (0 Tausche).
- Reihenfolge der **Fälle nach Margin**: verändert (ρ = 0,9367, Überlappung
  47/60).

Nur die erste ist „keine Umsortierung". Die zweite entscheidet, ob eine feste
Schwelle eine andere Menge auswählt — und die ändert sich sehr wohl.

---

## 2. Die Sonde: MESSER-5 gegen MESSER-7

Zwei echte Artikel (kein Duplikat), geometrisch 0,77 mm auseinander, im Profil
12,47 σ getrennt, in **26/26** Fällen gegenseitige Bedränger, beide in der
Baseline 0/13 ACCEPT. Wenn paarweises Scoring irgendwo wirkt, dann hier.

| Variante | MESSER-5 | MESSER-7 | Margin-Median des Paares |
|---|---|---|---|
| Baseline | 0/13 | 0/13 | 0,123 |
| B2 α=8 | **0/13** | 7/13 | 0,234 |
| B3 α=32 | **0/13** | 7/13 | 0,324 |

Der Margin steigt um Faktor 1,9 auf 0,234 — **eine Größenordnung unter dem Gate
von 2,0**, obwohl die Fisher-Adaption hier auf genau zwei Kandidaten losgelassen
wird. Und die Bewegung ist einseitig: MESSER-7 kommt auf 7/13, MESSER-5 bleibt in
jeder Variante bei 0/13.

Die Asymmetrie ist ein eigener Befund, siehe Abschnitt 4.

---

## 3. Entscheidung — und was ausdrücklich offen bleibt

**Paarweises Scoring wird nicht gebaut.** Es ist eine Abstandsoperation, und die
Sonde bewegt sich um Faktor 1,9 gegen ein Gate, das Faktor 16 verlangt.

Der globale α-Weg (der kleinere Eingriff ohne zweiten Durchgang) ist schlechter:

| Variante | ACCEPT | k_safe | top1 | Überlappung |
|---|---|---|---|---|
| B5 global α=8 | 45 | 167 | 168/169 | 44/45 (98 % Schwelle) |
| B6 global α=32 | 45 | **158** | **166**/169 | 44/45 |

### B2 ist „nicht gebaut, aber nicht widerlegt"

Festzuhalten, weil es zum ersten Mal auftritt: **B2 verschlechtert nichts.**

- k_safe **165 → 167** (die erste Variante überhaupt, die k_safe nicht senkt)
- top1 unverändert 168/169, false_accept 0, z-über-Gate unverändert 1
- Schwellenanteil **78 %** — der niedrigste aller bisher geprüften Ansätze:

| Ansatz | Überlappung | Anteil Schwelle |
|---|---|---|
| sum_unweighted | 143/149 | 96 % |
| Mahalanobis (volles C) | 57/61 | 93 % |
| global α=8 | 44/45 | 98 % |
| **B2 Nachschlag α=8** | **47/60** | **78 %** |

**Warum trotzdem nicht gebaut:** 22 % von 60 Fällen sind 13 Fälle bei effektiv
n ≈ 13 Artikeln. Das ist Rauschen, keine Evidenz. Der Aufwand (zweiter
Scoring-Durchgang im Messpfad, Korpus-Re-Baselining) steht dazu in keinem
Verhältnis.

**Wiederaufnahme:** Sobald die Windows-Box unabhängige Testaufnahmen und
Referenzen mit echter Positionsstreuung liefert, ist B2 der **erste Kandidat**
zum erneuten Prüfen. Die Kennzahl, an der es sich messen lassen muss, ist die
Mengenüberlappung gegen die äquivalente Baseline-Schwelle — nicht die
ACCEPT-Zahl.

---

## 4. MECHANIK-BEFUND: Die Streuung des Bedrängers bestimmt die Margin

Die Asymmetrie MESSER-5 (0/13) gegen MESSER-7 (7/13) bei einem symmetrischen
Paar ist **keine Artikeleigenschaft im harmlosen Sinn, sondern Scoring-Mechanik.**

### Ursache: ein einziges Merkmal

Zerlegung des Log-Beitrags je Merkmal, beide Richtungen (höher = besser):

| Merkmal | wahr=M5, Gegner M7 | wahr=M7, Gegner M5 |
|---|---|---|
| delta_e_rim | +0,21 | +0,21 |
| hist_center | +0,43 | +0,44 |
| hist_rim | +0,25 | +0,22 |
| **hu_log** | **+0,51** | **+5,17** |

Alle anderen Merkmale tragen in beiden Richtungen praktisch gleich bei. Der
Unterschied steckt vollständig in `hu_log`, Faktor 10.

### Warum

| | MESSER-5 | MESSER-7 | Verhältnis |
|---|---|---|---|
| σ_enroll(hu_log) | **0,0338** | **0,8389** | **24,8** |
| σ_eff(hu_log) | 0,3815 | 0,9210 | 2,4 |

`z = d / σ_eff` benutzt die Streuung **des jeweiligen Kandidaten**:

- Wird MESSER-7 gemessen, trifft die hu-Distanz auf MESSER-5s **enge** Referenz
  → z 2,4× größer → z² 5,9× größer → der falsche Kandidat wird hart bestraft
  (−5,66). Margin-Median **0,452**.
- Wird MESSER-5 gemessen, trifft dieselbe Distanz auf MESSER-7s **weite**
  Referenz → kaum Strafe (−0,51). Margin-Median **0,069**.

Die Kandidatensetgrößen sind identisch (4–5, Median 5) — es ist nicht die
Nachbarschaft.

**Die Konsequenz, allgemein formuliert:** Ein Artikel mit weiter
Enrollment-Streuung ist ein *klebriger* Bedränger — schwer auszuschließen, weil
alles in seine breite Verteilung passt. Ein Artikel mit enger Streuung ist leicht
auszuschließen. **Die Margin, die man bekommt, hängt an der Enrollment-Qualität
des Konkurrenten, nicht nur an der eigenen.** Ein schlampig eingelernter Artikel
verschlechtert die Margin aller seiner Nachbarn.

Formal ist das korrektes Likelihood-Verhalten — eine breite Referenzverteilung
hat für einen weiten Messbereich echte Wahrscheinlichkeitsmasse. Betrieblich ist
die Folge unerwünscht: schlechtes Enrollment wird belohnt.

### Wie weit trägt der Befund?

**Nicht als allgemeines Gesetz.** Über die sechs Bedränger-Paare des Bestands:

| Paar | σ-Verhältnis hu | Margins beide Richtungen | Effekt |
|---|---|---|---|
| MESSER-5 / MESSER-7 | 24,8 | 0,069 / 0,452 | **Faktor 6,5** |
| GABEL-11 / GABEL-14 | 12,3 | 0,549 / 0,460 | keiner |
| LOEFFEL-2 / LOEFFEL-5 | 23,9 | 0,931 / 0,927 | keiner |

`corr(σ_hu des Bedrängers, Margin-Median) = −0,29` bei n=13 — nicht belastbar.

Der Mechanismus braucht **zwei** Bedingungen gleichzeitig: eine große
σ-Asymmetrie **und** eine substanzielle Distanz in genau diesem Merkmal. Bei
GABEL-11/14 und LOEFFEL-2/5 ist die σ-Asymmetrie ähnlich groß, die hu-Distanz
aber klein — kein Effekt. In diesem Bestand trifft beides bei **einem von sechs**
Paaren zusammen.

### Diagnostischer Nebenertrag

σ_enroll(hu_log) über die 13 Artikel, gegen den Floor 0,38:

```
MESSER-7  0,8389   LOEFFEL-2 0,6036   LOEFFEL-1 0,5849   GABEL-10  0,5729
GABEL-11  0,5170   LOEFFEL-6 0,5097   GABEL-9   0,3283   LOEFFEL-3 0,0604
GABEL-12  0,0549   GABEL-14  0,0420   MESSER-5  0,0338   MESSER-8  0,0289
LOEFFEL-5 0,0253
```

**Sechs von dreizehn Artikeln liegen über dem Floor**, MESSER-7 um mehr als das
Doppelte. Ein σ_enroll(hu_log) deutlich über 0,38 heißt: die eigenen
Enrollment-Shots sind sich in den Hu-Momenten uneinig. Das ist ein
Qualitätssignal des Einlernens und im Enrollment-Diagnoseblatt bereits sichtbar —
bisher wurde es nicht als Kriterium benutzt.

**Nicht geprüft** und offen: ob ein Wiedereinlernen der sechs Artikel mit hohem
σ_hu die Margins ihrer Nachbarn hebt. Das wäre der direkte Test, braucht aber
neue Aufnahmen.

---

## 5. Einschränkungen

- n ≈ 13 Artikel, 169 nicht-unabhängige Fälle. Fixpunkt-Referenzen ohne
  Positionsstreuung, Leave-one-out statt unabhängiger Testaufnahmen.
- Die Tauschrate 0–1/169 lässt keine Risikoaussage über die Reihenfolge zu.
- Der Mechanik-Befund aus Abschnitt 4 ist an **einem** Paar sauber belegt und an
  zwei weiteren widerlegt. Er ist ein erklärter Mechanismus, keine gemessene
  Regelmäßigkeit.

---

## Verwandte Dokumente

- [2026-08-01-blockA-kovarianz.md](2026-08-01-blockA-kovarianz.md) — Vorblock,
  enthält die Unterscheidung „Rauschkorrelation vs. z über alle Kandidaten".
- [2026-08-01-scoring-simulation-widerlegte-thesen.md](2026-08-01-scoring-simulation-widerlegte-thesen.md) —
  der Simulator und die Voraussetzungen für jede Änderung.
