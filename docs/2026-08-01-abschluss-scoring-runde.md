# Abschluss der Scoring-Analyse-Runde 2026-08-01

**Datum:** 2026-08-01 · **Art:** Gesamtbilanz. **Keine einzige Änderung an
Produktivcode, Config oder Baseline.**
**Umfang:** sechs Architektur-Ansätze, über 250 simulierte Varianten, 169
Leave-one-out-Fälle über 13 echte Artikel.

> **Wer diese Runde in einem Satz braucht:** Nichts wurde gebaut, und das ist
> das Ergebnis. Sechs Ansätze zeigten dasselbe Muster — was wirkt, ist eine
> verkleidete Senkung von `min_llr_margin`; was keine ist, wirkt nicht. Das
> Werkzeug, das diese sechs Scheingewinne entlarvt hat, steht in Abschnitt 3 und
> ist das methodisch wertvollste Ergebnis der Runde.

---

## 1. Ausgangslage

Der Fixpunkt-Test
([2026-08-01-fixpunkt-test-scoring.md](2026-08-01-fixpunkt-test-scoring.md))
zeigte: das Ranking funktioniert (168/169 Top-1 korrekt), aber nur 41 von 169
Fällen erreichen ACCEPT. **127 bleiben AMBIGUOUS**, acht der dreizehn Artikel
erreichen kein einziges ACCEPT. Die 41 ACCEPT stammen fast vollständig aus drei
Artikeln mit kleinem Kandidatenset.

Gesucht war ein Weg, die Margin zu heben, ohne `false_accept` zu erzeugen.

---

## 2. Was geprüft und verworfen wurde

| Ansatz | Kern | Ergebnis |
|---|---|---|
| **w(s) als Merkmal** | Breitenprofil ins Scoring | Nicht gebaut. Trennschärfe hervorragend (16,1 σ Median), aber der Gewinn hängt am unbekannten Betriebs-Floor. [Nachtrag 11 präzisiert den Geltungsbereich.](2026-08-01-wprofil-negativbefund.md) |
| **Summe statt Mittel** | Aggregation | `log_score` IST bereits eine gewichtete Summe (wsum = 1). Die ungewichtete Summe ist zu 96 % Schwellensenkung. |
| **Vorfilter verschärfen** | Kandidatenset verkleinern | **Aktiv gefährlich.** k_safe 166 → 35. Der Vorfilter tötet den wahren Artikel; ein falscher gewinnt konkurrenzlos mit Riesen-Margin. |
| **Farbe abwerten** | Gewichte | Verschlechtert top1 und k_safe. Farbe bricht Gleichstände in genau den harten Fällen. |
| **`sigma_floors` senken** | Streuung | Tauscht AMBIGUOUS gegen REJECT. k_safe fällt. |
| **`softmax_temperature`** | Skala | Strukturell wirkungslos — kein Gate liest den Posterior. |
| **[Block A: Kovarianz](2026-08-01-blockA-kovarianz.md)** | Unabhängigkeitsannahme | Korrelation real, aber schwach (effektiver Rang 6,83/8). Mahalanobis: −5 top1, −30 k_safe. Regularisiert: wirkungslos. |
| **[Block B: paarweises Scoring](2026-08-01-blockB-paarweises-scoring.md)** | Fisher auf dem Spitzenpaar | Ändert die Reihenfolge nicht (Kontrolle B4 kennzahlengleich). Abstandsoperation. |
| **[Block D: `sigma_eff`](2026-08-01-blockD-sigma-eff.md)** | Konstruktion der Streuung | D0/D2/D4/D5 verworfen. D1/D3 halten, wirken aber aufs Ranking statt auf ACCEPT. |
| **[Block D6: Gewichtsschema](2026-08-01-blockD6-gewichtsschema.md)** | 5 Schemata × 4 α | Gleichverteilt dominiert das heutige Schema — aber Maximum aus 20 Zellen bei n ≈ 13. |
| **[Block D8: Tiebreaker](2026-08-01-blockD8-tiebreaker.md)** | Zweistufige Entscheidung | Mechanismus nachgewiesen, Wirkung ein Fall über dem Nullmodell. |

**Block C** (ist der Margin überhaupt die richtige Entscheidungsgröße?) wurde
**nicht mehr gerechnet**. Begründung: sechs Ansätze, sechsmal dasselbe Muster —
ein siebter auf derselben Datenbasis hätte es reproduziert. Block C bleibt als
**offene Frage** dokumentiert, nicht als offener Auftrag.

---

## 3. Das methodisch wertvollste Ergebnis: die Gegenprobe

Jede Variante, die die ACCEPT-Zahl hebt, muss sich derselben Frage stellen:

> **Wie viele ACCEPT bekäme man, wenn man einfach `min_llr_margin` so weit
> senkt, bis dieselbe Anzahl herauskommt — und sind es dieselben Fälle?**

Operativ in zwei Zahlen:

1. **Äquivalente Baseline-Schwelle:** der `min_llr_margin`-Wert, bei dem die
   Baseline gleich viele ACCEPT liefert wie die Variante.
2. **Mengenüberlappung:** wie viele der akzeptierten Fälle in beiden Mengen
   liegen. 100 % = die Variante ist eine reine Skalenoperation.

Dazu Spearman-ρ der Margin-Reihenfolge als Kontrolle.

### Was die Gegenprobe entlarvt hat

| Ansatz | ACCEPT | äquiv. Schwelle | Überlappung | Anteil Schwelle |
|---|---|---|---|---|
| `sum_unweighted` | 148 | 0,155 | 143/149 | **96 %** |
| Mahalanobis (volles C) | 61 | 1,297 | 57/61 | **93 %** |
| global α = 8 | 45 | 1,623 | 44/45 | **98 %** |
| D1 Deckel 1,5× | 42 | 1,847 | 41/42 | **98 %** |
| **B2 Nachschlag α=8** | 60 | 1,385 | 47/60 | **78 %** |
| D8 Tiebreak | 168 | 0 (Nullmodell) | 127/128 | **99 %** |

**Sechs von sechs Ansätzen waren überwiegend Schwellensenkung.** Ohne diese
Gegenprobe hätte jeder einzelne wie ein Durchbruch ausgesehen: `sum_unweighted`
mit 41 → 148 ACCEPT, D8 mit 41 → 168.

**Die Regel, die daraus folgt:** Eine ACCEPT-Zahl allein ist kein Ergebnis. Wer
das Gate senken will, soll das Gate senken und es so nennen — `min_llr_margin`
ist laut [CLAUDE.md](../CLAUDE.md) der einzige wirksame Schutz gegen
Fehlbuchungen bei baugleichen Artikeln.

### Zwei ergänzende Werkzeuge, die sich bewährt haben

- **`k_safe`** — wie viele Fälle man akzeptieren kann, bevor der erste falsche
  dabei ist (nach Margin sortiert, vom z-Gate Verworfene ausgenommen). Skalenfrei
  und damit über Varianten mit verschiedenen Margin-Größenordnungen vergleichbar.
  Hat mehr Varianten aussortiert als `false_accept` (das blieb fast überall 0).
- **Die Kontrolle mit dem neutralen Element** — Mahalanobis mit C = I, der
  Nachschlag mit fixierter Reihenfolge, das Nullmodell bei D8. Jedes Mal war
  das die Zahl, die den Befund entschieden hat, statt ihn plausibel zu machen.

### Nachtrag 2026-08-01: eine fehlerhafte Auswertungsschicht invertiert Empfehlungen, ohne rot zu werden

Der [Floor-Key-Fehler](2026-08-01-analysis-floor-key-befund.md) in
`analysis.py` hat nicht nur Zahlen überhöht. Er hat in den „Nächsten Schritten"
von [fixpunkt-test-scoring.md](2026-08-01-fixpunkt-test-scoring.md) eine
Empfehlung erzeugt, die **das Gegenteil des Richtigen** vorschlug — die
ΔE-Merkmale erschienen als die tragenden, tatsächlich sind sie die
schwächsten. Nirgends brach etwas ab, nirgends wurde etwas rot; die nächste
Runde hätte darauf aufgesetzt.

**Dass die Simulationen davon unberührt blieben, war Glück der Konstruktion,
nicht Vorsicht.** Sie importieren `matcher._sigma_floor` und rechnen deshalb
über `_FLOOR_KEY` — nicht, weil jemand diese Trennung geprüft hätte, sondern
weil sie ohnehin am Matcher entlang gebaut wurden.

**Die Regel, die daraus folgt:** Auswertungs-Artefakte und Simulationen müssen
**dieselbe Floor-Quelle** benutzen. Zwei Wege zu denselben Schwellen sind zwei
Wege, sich zu widersprechen — und der Widerspruch fällt nicht auf, weil beide
Seiten für sich plausible Zahlen liefern.

---

## 4. Was bleibt: drei Wiederaufnahme-Kandidaten

Nicht gebaut, aber nicht widerlegt — in der Reihenfolge ihrer Aussicht:

**1. [D8 Tiebreaker](2026-08-01-blockD8-tiebreaker.md) — der aussichtsreichste.**
Der einzige Ansatz, bei dem die Trennschärfe eines Merkmals in eine Entscheidung
umgesetzt wird, statt in der Aggregation zu verdampfen. Die Sonde
MESSER-5/MESSER-7 löst sich symmetrisch 13/13 in beiden Richtungen. Der
Mechanismus ist nachgewiesen; es fehlt nur die Datenbasis. Zu messen: die
Top-2-Rangfehlerrate, an die seine false-accept-Rate strukturell gekoppelt ist.

**2. [B2 Nachschlag](2026-08-01-blockB-paarweises-scoring.md) α = 8.**
Verschlechtert nichts (k_safe +2, top1 gleich, FA 0) und hat mit 78 % den
niedrigsten Schwellenanteil aller Ansätze. Nicht gebaut, weil 13 Fälle bei
n ≈ 13 Rauschen sind.

**3. [D1/D3 Deckel auf `sigma_enroll`](2026-08-01-blockD-sigma-eff.md).**
Die einzigen Varianten, die top1 auf 169/169 heben und k_safe von 165 auf 168.
Wirken aufs Ranking statt auf ACCEPT — eine andere Art von Gewinn als alles
übrige, und der einzige, der nicht als Schwellensenkung erklärbar ist.

Dazu zwei Befunde ohne Codeänderung, die sofort nutzbar sind:

- **[Duplikatprüfung vor jeder Analyse](2026-08-01-duplikatpruefung-methode.md)** —
  Profildistanz `d/σ < 2,0` markiert Verdacht. Hat zwei übersehene Duplikate
  gefunden, nachdem drei Analysen bereits auf ihnen aufgebaut hatten.
- **[Enrollment-Streuung des Bedrängers](2026-08-01-enrollment-streuung-bedraenger.md)** —
  σ_enroll gegen σ_floor prüfen, bevor ein Artikel übernommen wird. Relevant für
  das Windows-Neu-Enrollment.

---

## 5. Was die Datenbasis leisten müsste

**Die vorhandene Basis kann diese Fragen nicht entscheiden.** Das ist keine
Formalie — es ist der Grund, warum keine Änderung erfolgt.

| Problem | Wirkung | Was nötig wäre |
|---|---|---|
| **n ≈ 13 Artikel** | 169 Fälle sind 13 Aufnahmeserien. Rule of Three: Fehlerrate < 21 %. „false_accept = 0" belegt nichts. | **≥ 40 Artikel**, möglichst mit den engen Größenclustern des Produktivbestands |
| **Fixpunkt-Referenzen** | σ_enroll enthält keine Positionsstreuung. Absolute Margins sind optimistisch; die Streuungs-Asymmetrie, an der Block D hängt, könnte im Betrieb gar nicht bestehen. | **Enrollment mit echter Positionsstreuung** — Artikel bewusst verteilt statt am Fixpunkt |
| **Leave-one-out** | Messung stammt aus derselben Aufnahmeserie wie die Referenz. Keine unabhängige Prüfung. | **Getrennte Testaufnahmen**, mindestens n ≥ 5 je Artikel |
| **Betriebs-Floor geschätzt** | **0,40–1,41 mm** je nach unterstellter Auflage-Streuung, nicht gemessen — der Bereich umspannt die Entscheidungsgrenze von 1,0 mm (Korrektur 2026-08-01, siehe Fussnote). Entscheidet allein über w(s). | **Gemessener Floor** aus wiederholten Auflagen an realen Positionen — die Rasterfahrt liefert ihn nebenbei |
| **Kein Fokus-Lock (Mac)** | Kameraverbindung brach mehrfach ab, Fokus über die Session nicht garantiert. | **Windows-Box mit Fokus-Lock** |

Alle fünf laufen auf denselben Schritt hinaus: **das Komplett-Neu-Enrollment an
der Windows-Box**, mit verteilten statt fixierten Auflagen und getrennten
Testaufnahmen. Danach — und erst danach — sind die drei Wiederaufnahme-Kandidaten
entscheidbar.

> **Fussnote zum Betriebs-Floor (Korrektur 2026-08-01).** Die Runde führte hier
> „0,5–0,9 mm". Die zugrunde liegende Positionsmessung ist inzwischen aus den
> Rohdaten ausgewertet
> ([2026-08-01-positionsdrift-messung.md](2026-08-01-positionsdrift-messung.md)):
> der Effekt ist **deutlicher belegt als angenommen** (r = −0,997 über eine
> Positionsleiter von 109 mm), aber die Drift von 8,56 mm steht über **64 %**
> der Feldhöhe, nicht über die halbe. Als Rate gerechnet spannt der Floor
> **0,40–1,41 mm**, je nachdem wie weit die Auflage im Betrieb streut.
>
> Das verschiebt keine Entscheidung dieser Runde, aber es verschärft den
> Befund: die Größe, die allein über w(s) entscheidet, hängt nicht nur an einer
> fehlenden Messung, sondern an einer **unbeobachteten Betriebsannahme** mit
> Faktor 3,5 zwischen den Extremen — und die Entscheidungsgrenze von 1,0 mm
> liegt mittendrin. Die Rasterfahrt an der Windows-Box (5 × 3 Positionen, eine
> halbe Stunde) liefert beides: den gemessenen Floor und die Ursache des
> Gradienten.

Vorher ist der Simulator (`scripts/simulate_scoring.py`, reproduziert
`matcher.match()` bit-identisch) ein Werkzeug zum **Ausschließen** von Thesen,
nicht zum Begründen von Änderungen. Sechs Ausschlüsse in einer Runde ohne eine
einzige neue Aufnahme sind der Ertrag dieser Arbeit.

---

## 6. Nebenbefunde ohne Codeänderung

- **[`analysis.py` liest `sigma_floors` ohne `_FLOOR_KEY`](2026-08-01-analysis-floor-key-befund.md)** —
  die `discriminability`-Zahlen aus Run `20260801-140818` sind für die
  Farbmerkmale unbrauchbar. **Nachtrag: am 2026-08-01 gefixt**, Lauf neu
  gerechnet nach `20260801-140818-floorfix`. Die Sortierung der Matrix hatte
  die real schwierigen Paare verborgen; Aussagen dieser Runde beruhten bis auf
  einen Vorschlag in `fixpunkt-test-scoring.md` (dort korrigiert) nicht darauf.
- **Das Enrollment-Diagnoseblatt zeigt den `sigma_floor` nicht** (0 Treffer in
  `enrollment_sheet.py`). Wer beim Einlernen entscheiden soll, müsste acht
  Floor-Werte auswendig kennen. Vorschlag notiert, nicht umgesetzt.
- **`softmax_temperature` ist reine Anzeige** — kein Gate liest den Posterior.
- **α = 32 schadet in jedem Gewichtsschema** (k_safe 147–158 gegen 165).
- **Drei Kombinationseffekte dokumentiert**, bei denen einzeln unbedenkliche
  Änderungen zusammen schaden: `alpha=32 + S2` (historisch),
  `sum_unweighted + tol 4,0` (1 false_accept), `D3 + B2` (k_safe unter Baseline).
  Kombinationen sind kein Zusatz zur Prüfung, sie sind die Prüfung.

---

## 7. Offene Fragen, bewusst nicht beantwortet

- **Block C:** Ist die LLR-Margin überhaupt die richtige Entscheidungsgröße? Sie
  fällt systematisch mit der Kandidatensetgröße; ein festes Gate darauf ist
  möglicherweise falsch spezifiziert. Nicht gerechnet.
- **Die Faltung der Prototyp-Distanzen:** Die Likelihood behandelt
  nicht-negative Distanzen wie Gauß-Residuen. Block A hat das sichtbar gemacht,
  nicht behoben.
- **Ob Wiedereinlernen streuungsauffälliger Artikel die Nachbar-Margins hebt:**
  nicht messbar ohne neue Aufnahmen. Vorhersage steht im Enrollment-Dokument.
- **Stufe 2** (DINOv2 + FAISS) blieb in dieser Runde vollständig außen vor.

---

## Alle Dokumente dieser Runde

1. [Fixpunkt-Test](2026-08-01-fixpunkt-test-scoring.md) — Ausgangslage, zwei Duplikat-Nachträge
2. [w(s)-Negativbefund](2026-08-01-wprofil-negativbefund.md) — inkl. Nachtrag 11 zum Geltungsbereich
3. [Duplikatprüfung: Methode](2026-08-01-duplikatpruefung-methode.md)
4. [Drei widerlegte Thesen (Simulation a–f)](2026-08-01-scoring-simulation-widerlegte-thesen.md)
5. [Enrollment-Streuung des Bedrängers](2026-08-01-enrollment-streuung-bedraenger.md)
6. [Block A: Kovarianz](2026-08-01-blockA-kovarianz.md)
7. [Block B: paarweises Scoring](2026-08-01-blockB-paarweises-scoring.md)
8. [Block D: `sigma_eff`](2026-08-01-blockD-sigma-eff.md)
9. [Block D6: Gewichtsschema](2026-08-01-blockD6-gewichtsschema.md)
10. [Block D8: Tiebreaker](2026-08-01-blockD8-tiebreaker.md)
11. [`analysis.py` Floor-Key-Befund](2026-08-01-analysis-floor-key-befund.md)
