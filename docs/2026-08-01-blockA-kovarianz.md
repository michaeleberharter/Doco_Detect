# Block A: Die Unabhängigkeitsannahme der Likelihood — keine Kovarianz-Korrektur

**Datum:** 2026-08-01 · **Art:** Negativbefund mit Entscheidung.
**Ergebnis: keine Kovarianz-Korrektur.** Kein Produktivcode, keine Config.
**Datenbasis:** 169 Leave-one-out-Fälle über 13 echte Artikel (Sandbox
`neuenroll-2026-08`), Simulation über `scripts/simulate_scoring.py` +
`scripts/analyse_merkmalskorrelation.py`.

---

## 0. Die Prämissen-Korrektur, die hier am wichtigsten ist

> **Rauschkorrelation innerhalb eines Artikels ≠ z-Korrelation über alle
> Kandidaten.** Wer die Unabhängigkeitsannahme der Likelihood prüfen will, muss
> die erste Größe messen. Die zweite sieht ähnlich aus, misst aber etwas anderes
> und ist erheblich größer.

Auslöser für Block A war die Zahl **circularity ↔ delta_e_rim = +0,73** aus dem
w(s)-Negativbefund (Abschnitt 5b). Sie wurde über die z-Werte **aller
(Report × Kandidat)-Zeilen** gerechnet — also einschließlich der *falschen*
Kandidaten. Diese Population mischt zwei Dinge:

- **Messrauschen** eines Artikels um seine eigene Referenz (das, was die
  Likelihood als unabhängig annimmt), und
- **Zwischen-Artikel-Struktur** — wie weit ein falscher Kandidat in jedem
  Merkmal danebenliegt. Artikel, die in einem Merkmal weit weg sind, sind es oft
  auch im anderen; das erzeugt Korrelation, die mit der Modellannahme nichts
  zu tun hat.

Über die richtige Population — je Shot die acht z-Werte gegen die
Leave-one-out-Referenz des **eigenen** Artikels — beträgt dieselbe Korrelation
**−0,15**. Die Motivation für Block A trug also nicht.

**Merkregel:** Bei jeder Korrelations-, Streuungs- oder Trennschärfeaussage
zuerst benennen, über welche Grundgesamtheit gerechnet wurde. Derselbe
Merkmalsname liefert je nach Population völlig verschiedene Zahlen. Dieselbe
Fehlerklasse trat schon einmal auf: „Farbe ist bei 2 von 105 Paaren das beste
Merkmal" maß Dominanz, nicht Grenzbeitrag — und führte zur falschen Vermutung,
Farbe sei toter Ballast
([2026-08-01-scoring-simulation-widerlegte-thesen.md](2026-08-01-scoring-simulation-widerlegte-thesen.md),
Abschnitt 4).

---

## 1. Die tatsächliche Korrelationsstruktur

Pearson über die z-Vektoren der wahren Artikel, 169 Shots × 8 Merkmale:

|  | diam | circ | soli | dEc | dEr | hic | hir | hu |
|---|---|---|---|---|---|---|---|---|
| **diam** | 1,00 | −0,01 | −0,04 | 0,21 | 0,29 | 0,34 | 0,35 | 0,01 |
| **circ** | | 1,00 | −0,05 | −0,08 | −0,15 | −0,14 | −0,02 | −0,01 |
| **soli** | | | 1,00 | 0,08 | 0,03 | −0,01 | 0,03 | −0,04 |
| **dEc** | | | | 1,00 | 0,32 | **0,53** | 0,24 | −0,01 |
| **dEr** | | | | | 1,00 | 0,45 | 0,29 | 0,21 |
| **hic** | | | | | | 1,00 | **0,53** | 0,00 |
| **hir** | | | | | | | 1,00 | −0,09 |

- **Ein Block**, und zwar der Farbblock: dEc↔hic 0,53, hic↔hir 0,53, dEr↔hic
  0,45, dazu schwache Ankopplung an den Ø (0,34/0,35).
- `circularity`, `solidity`, `hu_log` sind von allem unabhängig (|ρ| ≤ 0,21).
- Nur **2 von 28** Paaren über 0,5, 6 von 28 über 0,3.
- Eigenwerte 2,47 / 1,13 / 1,08 / 0,94 / 0,81 / 0,66 / 0,57 / 0,34 →
  **effektiver Rang 6,83 von 8**. Also etwa eine Dimension Redundanz.

Die Unabhängigkeitsannahme ist verletzt — aber schwach und lokal.

---

## 2. Schätzbar ja, invertierbar heikel

169 Shots für 36 freie Parameter = 4,7 Beobachtungen je Parameter. Dünn, aber
brauchbar. Entscheidend ist die Stabilität:

- **Leave-one-ARTIKEL-out** (13 Neuschätzungen): größte Abweichung eines
  Matrixeintrags **0,106**, Konditionszahl-Bereich 146,6–169,8. → Die Struktur
  hängt **nicht** an einzelnen Artikeln.
- Aber: κ(R, zentriert) = **7,2** gegen κ(C, unzentriert) = **153,5**,
  λ_min = 0,038.

Die schlechte Konditionierung von C ist **kein Datenmengen-Problem, sondern eine
Folge der Faltung**: fünf der acht Merkmale sind Prototyp-*Distanzen* und damit
≥ 0, alle z-Mittelwerte liegen bei 0,36–0,62. Die unzentrierte Zweitmoment-Matrix
wird von der gemeinsamen Positiv-Richtung dominiert, ihre Komplemente werden
klein. Wer C invertiert, gewichtet genau die Richtungen hoch, die die Daten am
schlechtesten bestimmen.

---

## 3. Simulation: Mahalanobis statt Summe unabhängiger z²

Formulierung als strikte Verallgemeinerung:
`log_score = −0,5 · zᵀ D^½ C⁻¹ D^½ z` mit `D = diag(w_eff)`. Für **C = I** ist
das exakt die heutige Baseline.

| Variante | top1 | ACCEPT | **k_safe** | ρ zur Baseline | äquiv. Schwelle | Überlappung |
|---|---|---|---|---|---|---|
| a) Baseline | 168/169 | 41 | 165 | — | — | — |
| **Kontrolle C = I** | 168/169 | **41** | **165** | **+1,0000** | 2,020 | **41/41** |
| maha (volles C) | **163**/169 | 61 | **135** | +0,9416 | 1,297 | 57/61 |
| maha shrink 0,2 | 162/169 | 40 | 139 | +0,9626 | 2,223 | 39/40 |
| maha shrink 0,5 | 167/169 | 35 | 141 | +0,9764 | 2,577 | 34/35 |
| maha nur \|ρ\| > 0,5 | 168/169 | 38 | **167** | +0,9794 | 2,427 | 37/38 |

**Die Kontrolle mit C = I ist bit-identisch zur Baseline** — die Implementierung
ist damit als Verallgemeinerung validiert, nicht als anderes Verfahren.

Der scheinbare Gewinn des vollen Mahalanobis (ACCEPT 41 → 61) kostet **5
zusätzliche Ranking-Fehler und 30 Fälle k_safe**. Und er verschwindet
vollständig, sobald man regularisiert: Shrinkage und die auf |ρ| > 0,5
reduzierte Matrix landen *unter* der Baseline-ACCEPT-Zahl. **Der Gewinn steckt
genau in den schlecht bestimmten Richtungen — er ist Rauschverstärkung, keine
Information.**

`max|z|` des Siegers bleibt praktisch unverändert (Median 0,89 → 0,90, max 4,60
in beiden, 1 Fall über dem Gate). Die Dekorrelation hebt oder senkt z nicht
nennenswert.

Gegenprobe wie bei allen bisherigen Varianten: ρ = 0,9416 und Überlappung 57/61
→ rund **93 % des Gewinns sind eine Schwellenverschiebung** (äquivalent zu
`min_llr_margin` = 1,297).

---

## 4. Die Nullartikel — der schärfste Filter

Acht der dreizehn Artikel erreichen in der Baseline **kein einziges** ACCEPT:
GABEL-10, GABEL-11, GABEL-12, GABEL-14, LOEFFEL-2, LOEFFEL-5, MESSER-5, MESSER-7.

| Variante | bewegt von 8 Nullartikeln |
|---|---|
| maha (volles C) | 2 (GABEL-10, LOEFFEL-5) — bei 5 neuen Ranking-Fehlern |
| maha shrink 0,2 / 0,5 / reduziert | **0** |
| maha + floor ×0,5 | 7 — **aber floor ×0,5 allein bewegt bereits 6** |

**Keine Variante aus Block A bewegt die Nullartikel aus eigener Kraft.** Was sie
bewegt, ist die Floor-Senkung — und die war bereits verworfen (k_safe fällt,
AMBIGUOUS wird gegen REJECT getauscht).

**MESSER-5 bleibt in jeder einzelnen Variante 0/13.**

---

## 5. Entscheidung

**Keine Kovarianz-Korrektur.** Entweder Rauschverstärkung (volles C: −5 top1,
−30 k_safe) oder wirkungslos (regularisiert: 0 Nullartikel, weniger ACCEPT als
die Baseline). Dazu 93 % Schwellenverschiebung. Nach den harten Bedingungen
scheitert jede Variante an k_safe, auch wenn false_accept überall 0 bleibt.

---

## 6. Einschränkungen

- n ≈ 13 Artikel, 4,7 Beobachtungen je Kovarianz-Parameter. Die Aussage
  „Korrelationskorrektur hilft nicht" ist eine **Richtungsaussage**, kein
  Ausschluss für einen Bestand mit anderer Merkmalsstruktur.
- Fixpunkt-Referenzen ohne Positionsstreuung; Leave-one-out auf
  Enrollment-Shots statt unabhängiger Testaufnahmen.
- Die Faltung der fünf Prototyp-Distanzen ist ein **Modellierungsproblem, das
  bestehen bleibt**: die Likelihood behandelt nicht-negative Distanzen wie
  Gauß-Residuen. Block A hat das sichtbar gemacht, aber nicht behoben. Ob eine
  Modellierung als Halbnormal- oder χ-Verteilung etwas bringt, ist offen und
  wurde hier nicht geprüft.

---

## Verwandte Dokumente

- [2026-08-01-scoring-simulation-widerlegte-thesen.md](2026-08-01-scoring-simulation-widerlegte-thesen.md) —
  Vorrunde, Herkunft der 0,73, und die Voraussetzungen für jede Änderung.
- [2026-08-01-wprofil-negativbefund.md](2026-08-01-wprofil-negativbefund.md) —
  Abschnitt 5b, wo die falsch interpretierte Korrelation steht.
