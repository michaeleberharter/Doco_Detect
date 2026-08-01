# Block D8: Tiebreaker bei AMBIGUOUS — Mechanismus nachgewiesen, Wirkung nicht

**Datum:** 2026-08-01 · **Art:** Negativbefund mit Entscheidung.
**Ergebnis: D8 wird nicht gebaut.** Kein Produktivcode, keine Config.
**Datenbasis:** 169 Leave-one-out-Fälle über 13 echte Artikel,
`scripts/analyse_tiebreaker.py`.

> **Zwei Aussagen, gleichrangig:**
> 1. Der strukturelle Vorteil ist **bestätigt**. Im Tiebreak kann kein Dritter
>    nachrücken; die Sonde MESSER-5/MESSER-7 löst sich **symmetrisch 13/13 in
>    beiden Richtungen**; die 12,47 σ des Breitenprofils werden hier tatsächlich
>    in eine Entscheidung umgesetzt. **Das ist der einzige Ansatz der ganzen
>    Runde, bei dem das gelungen ist.**
> 2. Auf diesen Daten ist D8 **nicht von „Margin-Gate abschaffen"
>    unterscheidbar** — der Vorsprung gegenüber dem Nullmodell beträgt einen
>    einzigen Fall.

---

## Idee

Meldet das Scoring AMBIGUOUS, wird zwischen Platz 1 und Platz 2 separat
entschieden — nicht durch Umgewichtung aller Merkmale (das war Block B und ist
erledigt), sondern durch **Reduktion auf das eine Merkmal, das dieses konkrete
Paar am besten trennt**. Fisher-Ratio auf dem Paar, aber als *Selektion* statt
als Gewichtung. Kein Mittel, keine Aggregation, keine Posterior-Masse von
Dritten.

### Methodische Korrektur während der Auswertung

Die erste Umsetzung wählte das Tiebreaker-Merkmal über die
**messungsabhängigen** Distanzen (|d_a − d_b| der aktuellen Messung) und
entschied dann mit demselben Merkmal. **Das ist Selektion auf dem Ergebnis** —
der Tiebreaker sucht sich das Merkmal aus, das ihm gerade recht gibt, und sieht
dadurch immer gut aus.

Korrigiert auf messungsunabhängige Selektion: die Trennschärfe wird aus den
beiden **Enrollment-Referenzen** gebildet (|Lage_a − Lage_b| / σ_eff bzw.
Prototyp-Distanz), entschieden wird danach über die z-Werte der Messung. Die
Ergebnisse änderten sich dadurch nur wenig — die Zahlen der ersten Fassung waren
trotzdem nicht gültig.

---

## Die Obergrenze — günstiger als erwartet

Eine Kaskade ist unheilbar: was in der ersten Stufe nicht unter die ersten zwei
kommt, kann die zweite Stufe nicht mehr retten.

| | Anzahl |
|---|---|
| AMBIGUOUS gesamt | 127 |
| wahrer Artikel auf Platz 1 | **126** |
| wahrer Artikel auf Platz 2 | 1 |
| **wahrer Artikel nicht unter den ersten zwei** | **0** |

Obergrenze für D8: **127 von 127**. Die Kaskade verliert auf diesem Bestand
nichts.

---

## Ergebnisse

| Variante | Schwelle | gelöst | korrekt | **FALSCH** | ACCEPT ges. | Sonde M5 / M7 |
|---|---|---|---|---|---|---|
| Baseline | — | 0 | 0 | 0 | 41 | 0/13 · 0/13 |
| 1 Merkmal | 0,0 | 127 | 122 | **5** | 163 | 13/13 · 13/13 |
| 1 Merkmal | 1,0 | 92 | 89 | **3** | 130 | 0/13 · 7/13 |
| 1 Merkmal | 2,0 | 54 | 54 | 0 | 95 | 0/13 · 7/13 |
| 3 Merkmale | 0,5 | 125 | 125 | **0** | 166 | 13/13 · 12/13 |
| 3 Merkmale | 1,0 | 116 | 116 | 0 | 157 | 11/13 · 9/13 |
| **1 Merkmal + w(s)** | **0,0–1,0** | **127** | **127** | **0** | **168** | **13/13 · 13/13** |
| 3 Merkmale + w(s) | 0,0–2,0 | 127 | 127 | **0** | 168 | 13/13 · 13/13 |
| 3 Merkmale + w(s) | 5,0 | 104 | 104 | 0 | 145 | 13/13 · 13/13 |

**Ohne w(s) erzeugt ein einzelnes Merkmal fünf Fehlentscheidungen** — nach der
harten Bedingung sofort verworfen. Erst drei Merkmale ab Schwelle 0,5 sind
fehlerfrei, lösen dafür 125 statt 127.

**Mit w(s) im Pool ist jede Variante fehlerfrei**, bei jeder Schwelle. Das
Gewicht ist hier irrelevant — es geht um Selektion, nicht um Aggregation. Damit
umgeht D8 das Gewichtungsproblem aus D7 vollständig.

---

## Der strukturelle Vorteil — bestätigt

In der Baseline ist MESSER-7 in **13 von 13** Fällen der Zweitplatzierte von
MESSER-5 und umgekehrt. Ein perfekt symmetrisches Paar.

In der **Aggregation** (w(s)-Negativbefund, Abschnitt 3b) verdrängte w(s) den
Bedränger aus Platz 2 — und ein anderer Kandidat rückte nach. Der Gewinn
neutralisierte sich, die Margin bewegte sich kaum.

Im **Tiebreak** kann das nicht passieren: es gibt per Konstruktion nur zwei
Kandidaten. Kein Dritter kann Platz 2 übernehmen und keine Posterior-Masse
ziehen. Ergebnis: **13/13 in beiden Richtungen**, symmetrisch, bei jeder
Schwelle bis 5,0.

Auch die Asymmetrie aus dem Enrollment-Befund (MESSER-5 0/13 gegen MESSER-7
7/13 unter dem B2-Nachschlag) verschwindet — allerdings nur mit w(s) im Pool.
Ohne w(s) bleibt sie bestehen (bei Schwelle 1,0: 0/13 gegen 7/13).

**Das ist der einzige Ansatz der gesamten Runde, bei dem die Trennschärfe eines
Merkmals in eine Entscheidung umgesetzt wird, statt in der Aggregation zu
verdampfen.** Der Mechanismus funktioniert.

---

## Die Nullmodell-Kontrolle — und was sie entwertet

Die entscheidende Frage: was leistet D8 gegenüber „bei AMBIGUOUS ungeprüft
Platz 1 nehmen"? Das entspricht exakt `min_llr_margin = 0`.

| | gelöst | korrekt | **falsch** | ACCEPT |
|---|---|---|---|---|
| **Nullmodell** (Gate abschaffen) | 127 | **126** | **1** | 168 |
| D8, 1 Merkmal + w(s), Schwelle 0 | 127 | 127 | 0 | 168 |

**Der Mehrwert von D8 gegenüber dem Nullmodell ist genau ein Fall:**
GABEL-12 shot 12, wo GABEL-11 mit einer Margin von 0,048 auf Platz 1 stand.
D8 dreht diesen einen Fall richtig herum.

Das ist dieselbe Gegenprobe wie in allen Blöcken zuvor, nur in anderer Gestalt.
D8 mit Schwelle 0 **ist** die Abschaffung des Margin-Gates plus eine
Ein-Fall-Korrektur. Die 41 → 168 ACCEPT sind zu 127/128 das Nullmodell.

Bei höheren Schwellen wird D8 selektiver und ist dann wieder eine Schwelle —
und die Frage lautet, ob sie besser sortiert als `min_llr_margin`. Auf diesen
Daten: ja, aber mit einem Ereignis Unterschied.

---

## Die strukturelle Warnung: Kopplung an die Top-2-Rangfehlerrate

Der Tiebreaker entscheidet zwischen zwei Kandidaten, von denen einer falsch ist.
**Seine false-accept-Rate ist damit nach unten begrenzt durch die Rate, mit der
der falsche Kandidat auf Platz 1 steht.**

Hier ist diese Rate 1/127 ≈ 0,8 %, und D8 fängt genau diesen einen Fall. Das ist
kein Verdienst des Verfahrens, sondern eine Eigenschaft des Bestands: 13 Artikel,
Fixpunkt ohne Positionsstreuung, Leave-one-out. **Mit mehr Artikeln und echter
Positionsstreuung wird die Top-2-Rangfehlerrate steigen — und D8 wandelt sie
dann direkt in Fehlbuchungen um, wo vorher AMBIGUOUS stand.**

Genau das ist der Unterschied zwischen AMBIGUOUS und ACCEPT: AMBIGUOUS gibt den
Fall an den Menschen, ACCEPT bucht. Ein Verfahren, das AMBIGUOUS abschafft,
übernimmt jeden Rangfehler als Fehlbuchung.

Rule of Three über Artikel (0 Fehler bei n ≈ 13): Fehlerrate < 21 %. Die
gemessene 0 belegt nichts.

---

## Entscheidung

**D8 wird nicht gebaut.** Ein Fall Vorsprung gegenüber dem Nullmodell, und die
Fehlerrate ist strukturell an die Top-2-Rangfehlerrate gekoppelt, die auf dieser
Basis nur zufällig null ist.

**Wiederaufnahme:** D8 ist neben B2 und D1/D3 der dritte Kandidat für die Zeit
nach der Windows-Box — und der **aussichtsreichste**, weil sein Mechanismus
nachgewiesen ist und nur die Datenbasis fehlt. Was zu messen wäre:

1. die Top-2-Rangfehlerrate auf unabhängigen Testaufnahmen mit echter
   Positionsstreuung — sie ist die Obergrenze für die false-accept-Rate;
2. ob w(s) seine Trennschärfe bei realem Betriebs-Floor behält (dieselbe offene
   Größe wie im Negativbefund);
3. ob D8 mit einer Schwelle > 0 einen messbaren Vorsprung vor dem Nullmodell
   behält, wenn die Rangfehlerrate nicht mehr bei 1/127 liegt.

---

## Einschränkungen

- n ≈ 13 Artikel, 169 nicht-unabhängige Fälle, Fixpunkt-Referenzen ohne
  Positionsstreuung, Leave-one-out statt unabhängiger Testaufnahmen.
- w(s) im Tiebreak-Pool nutzt dieselbe Leave-one-out-Konstruktion und einen
  fest verdrahteten floor von 0,50 mm wie D7. Ohne w(s) fällt D8 auf das Niveau
  der übrigen Ansätze zurück (fünf Fehlentscheidungen bei einem Merkmal).
- Der Unterschied zum Nullmodell ist ein Ereignis. Jede Aussage darüber, ob D8
  „besser sortiert", ist auf dieser Basis nicht belastbar.

---

## Verwandte Dokumente

- [2026-08-01-blockB-paarweises-scoring.md](2026-08-01-blockB-paarweises-scoring.md) — Block B, den D8 ablöst.
- [2026-08-01-wprofil-negativbefund.md](2026-08-01-wprofil-negativbefund.md) — die 12,47 σ und der offene Betriebs-Floor.
- [2026-08-01-abschluss-scoring-runde.md](2026-08-01-abschluss-scoring-runde.md) — Gesamtbilanz.
