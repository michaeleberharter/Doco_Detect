# Die `feature_weights` sind eine ungeprüfte Setzung — und gleichverteilt ist besser

**Datum:** 2026-08-01 · **Art:** Befund. Keine Änderung an `config.yaml`.
**Datenbasis:** 169 Leave-one-out-Fälle über 13 echte Artikel, volle Matrix aus
5 Gewichtsschemata × 4 α-Werten, `scripts/analyse_gewichte_wprofil.py`.

> **Zwei Aussagen, gleichrangig:**
> 1. Gleichverteilte Gewichte dominieren das heutige Schema in **allen drei**
>    harten Kennzahlen gleichzeitig — top1, ACCEPT und k_safe.
> 2. Das ist das Maximum aus 20 Zellen bei n ≈ 13 Artikeln, und der Unterschied
>    beträgt neun Fälle. Genau die Konstruktion, die überanpasst.
>
> Keine der beiden Aussagen relativiert die andere weg. Beide gelten.

---

## Ausgangslage

Die Gewichte in [config/config.yaml](../config/config.yaml) stammen aus der
Anfangszeit des Projekts:

```yaml
diameter_mm: 0.50      # "Ø ist bewusst schwer - er ist das
circularity: 0.07      #  verlaesslichste Merkmal in der Box"
solidity: 0.06
delta_e_center: 0.08 · delta_e_rim: 0.08
hist_center: 0.07 · hist_rim: 0.07 · hu_log: 0.07
```

Die Begründung im Kommentar ist plausibel, aber es ist eine **Setzung, kein
Optimierungsergebnis**. Gegen Daten geprüft wurde sie nie. Dieses Dokument holt
das nach — als Messung, nicht als Änderungsvorschlag.

---

## Ergebnis: volle Matrix Schema × α

| Schema | α | top1 | ACCEPT | **k_safe** | FA | Überlappung |
|---|---|---|---|---|---|---|
| **S0 heute** | 0 | 168/169 | 33 | 158 | 0 | 31/33 |
| **S0 heute** | **2** | **168/169** | **41** | **165** | 0 | — |
| S0 heute | 8 | 168/169 | 45 | 167 | 0 | 44/45 |
| S0 heute | 32 | 166/169 | 45 | 158 | 0 | 44/45 |
| **S1 gleichverteilt** | 0 | **169/169** | 45 | **168** | 0 | 43/45 |
| **S1 gleichverteilt** | **2** | **169/169** | **50** | **168** | 0 | **43/50 (86 %)** |
| S1 gleichverteilt | 8 | 168/169 | 54 | 167 | 0 | 44/54 |
| S1 gleichverteilt | 32 | 165/169 | 56 | **148** | 0 | 46/56 |
| **S2 Form** (Ø 0,25) | 2 | **169/169** | 49 | **168** | 0 | 43/49 |
| S2 Form | 32 | 163/169 | 53 | **147** | 0 | 45/53 |
| S3 Farbe abgewertet | 0 | **169/169** | 42 | **168** | 0 | 41/42 |
| S3 Farbe abgewertet | 32 | 163/169 | 47 | **149** | 0 | 44/47 |
| S4 Ø stark (0,70) | 2 | 167/169 | 36 | 164 | 0 | 35/36 |

Schemata: **S1** alle acht auf 0,125 · **S2** Ø 0,25, Form (circ/sol/hu) je 0,15,
Farbe je 0,075 · **S3** Ø 0,50, Form 0,12/0,12/0,11, Farbe je 0,0375 ·
**S4** Ø 0,70, Rest gleichmäßig.

### Drei Befunde

**1. Gleichverteilt dominiert.** S1 mit α = 2 ist dem heutigen S0 in allen drei
harten Kennzahlen überlegen: top1 169 statt 168, ACCEPT 50 statt 41, k_safe 168
statt 165. Kein Trade-off, keine Gegenrechnung nötig.

**2. Ø höher zu gewichten schadet.** S4 (Ø = 0,70) liegt in jeder Kennzahl unter
S0. Die Begründung „Ø ist das verlässlichste Merkmal" trägt also nicht bis zur
Gewichtung durch — sie war ein Argument für ein hohes Gewicht, aber die Daten
zeigen, dass das heutige 0,50 bereits über dem Optimum liegt.

**3. α = 32 schadet in JEDEM Schema.** k_safe fällt auf 147–158, top1 auf
163–166. Über alle Schemata ist α = 0–2 am besten; α = 8 hebt ACCEPT bei
leichtem k_safe-Verlust. Die Fisher-Adaption ist also nützlich, aber nur in
schwacher Dosierung.

**Kein false_accept in allen 20 Zellen.** Der historische Fall
`alpha=32 + Schema S2`, der seinerzeit kombiniert einen false_accept bei 2,01
ergab, reproduziert sich auf diesem Bestand nicht — die volle Matrix wurde
gerechnet, nicht nur die Diagonale.

---

## Der Vorbehalt, gleichrangig

**Das ist ein Maximum aus 20 Zellen.** Bei n ≈ 13 Artikeln und 169
nicht-unabhängigen Fällen ist die Auswahl des besten Ergebnisses aus einer
Parametermatrix genau die Konstruktion, die überanpasst.

Konkret:

- Der ACCEPT-Vorsprung von S1/α=2 gegenüber S0/α=2 sind **neun Fälle**
  (50 gegen 41). Bei 13 Artikeln sind das im Mittel weniger als ein Fall je
  Artikel.
- Der top1-Vorsprung ist **ein einziger Fall** (GABEL-12 shot 12).
- Der k_safe-Vorsprung sind **drei Fälle**.
- Die Gegenprobe zeigt 86 % Überlappung mit der äquivalenten Baseline-Schwelle:
  von den 50 ACCEPT sind 43 auch dann erreichbar, wenn man einfach
  `min_llr_margin` auf 1,55 senkt. Echt neu sind **sieben Fälle**.

Ein zweiter, unabhängiger Datensatz kann diese Rangfolge umdrehen, ohne dass
irgendetwas an der Analyse falsch wäre.

---

## Was daraus folgt

**Keine Änderung an `config.yaml`.** Weder ist die Datenbasis tragfähig, noch
ist eine Gewichtsänderung ohne Datenbegründung und expliziten Auftrag zulässig
([CLAUDE.md](../CLAUDE.md)).

**Was dokumentiert sein soll:** Die heutigen `feature_weights` sind eine
ungeprüfte Setzung. Der erste Test, dem sie unterzogen wurden, spricht gegen
sie — und zwar in eine Richtung, die der ursprünglichen Begründung
widerspricht (nicht „Ø noch schwerer", sondern „Ø leichter"). Wer das Schema
später anfasst, fängt nicht bei null an.

**Der belastbare Teil des Befunds ist nicht die Rangfolge der Schemata, sondern
die Beobachtung, dass mehrere naheliegende Alternativen das heutige Schema
erreichen oder schlagen** — S1, S2 und S3 liegen alle bei top1 169/169 und
k_safe 168. Vier von fünf geprüften Schemata sind mindestens so gut wie das
gesetzte. Das spricht weniger für ein bestimmtes Schema als dafür, dass die
genaue Wahl innerhalb eines weiten Bereichs kaum zählt — und dass gerade das
heutige eher am ungünstigen Rand liegt.

---

## Einschränkungen

- n ≈ 13 Artikel, Fixpunkt-Referenzen ohne Positionsstreuung, Leave-one-out
  statt unabhängiger Testaufnahmen.
- Fünf Schemata sind eine grobe Abtastung eines 8-dimensionalen Raums. Ein
  systematisches Optimum wurde nicht gesucht — und dürfte auf dieser Basis
  auch nicht gesucht werden.
- Die Kennzahlen ACCEPT und k_safe hängen beide an `min_llr_margin = 2,0`.
  Ein anderes Gate verschiebt die Rangfolge möglicherweise.

---

## Verwandte Dokumente

- [2026-08-01-blockD-sigma-eff.md](2026-08-01-blockD-sigma-eff.md) — Block D, aus dem D6 stammt.
- [2026-08-01-abschluss-scoring-runde.md](2026-08-01-abschluss-scoring-runde.md) — Gesamtbilanz.
