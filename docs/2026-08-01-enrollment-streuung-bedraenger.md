# Die Enrollment-Streuung eines Artikels bestimmt die Margin seiner Nachbarn

**Datum:** 2026-08-01 · **Art:** Mechanik-Befund mit Handlungsfolge für das
Enrollment. Kein Code, keine Config geändert.
**Belegt an:** Sandbox `neuenroll-2026-08`, 13 echte Artikel, 169
Leave-one-out-Fälle.

> **Für das anstehende Komplett-Neu-Enrollment an der Windows-Box:**
> Nach jedem eingelernten Artikel prüfen, ob `sigma_enroll` bei einem Merkmal
> **über dem `sigma_floor`** liegt. Wenn ja, mit dem Jackknife-Test aus
> Abschnitt 4b unterscheiden: **Ausreißer-Shot → neu einlernen**;
> **gleichmäßig breit → Wiederholen hilft nicht**, der Artikel ist
> rotationsempfindlich. Etwa hälftig verteilt. Enrollment-Qualität ist an
> dieser Stelle ein Systemparameter, keine Kosmetik — aber sie ist nicht die
> ganze Antwort.

---

## 1. Herleitung aus der Formel

Der Matcher rechnet je Kandidat und Merkmal
([matcher.py:342-344](../docodetect/matcher.py)):

```
sigma_eff = sqrt(sigma_enroll² + sigma_floor²)
z         = d / sigma_eff
log_contrib = -0.5 * z²
```

`sigma_enroll` ist die Streuung **des jeweiligen Kandidaten** über seine eigenen
Enrollment-Shots. Sie steht also im Nenner des Strafterms, mit dem *dieser
Kandidat* bewertet wird — auch dann, wenn er der **falsche** ist.

Daraus folgt unmittelbar:

- Ein Artikel mit **enger** Referenz (kleines σ) wird für jede Abweichung hart
  bestraft. Er ist leicht auszuschließen — ein **schwacher** Konkurrent.
- Ein Artikel mit **weiter** Referenz (großes σ) wird kaum bestraft. Alles passt
  irgendwie in seine breite Verteilung. Er ist ein **klebriger** Konkurrent, der
  sich nicht abschütteln lässt.

Und weil die LLR-Margin die Differenz zwischen Platz 1 und Platz 2 ist, gilt:
**die Margin, die ein Artikel bekommt, hängt an der Enrollment-Qualität seines
Bedrängers, nicht nur an seiner eigenen.**

Formal ist das korrektes Likelihood-Verhalten — eine breite Referenzverteilung
hat für einen weiten Messbereich echte Wahrscheinlichkeitsmasse. Betrieblich ist
die Folge unerwünscht: **schlampiges Enrollment wird belohnt**, und es
verschlechtert die Nachbarn gleich mit.

---

## 2. Der Beleg: MESSER-5 gegen MESSER-7

Zwei echte Artikel (kein Duplikat), geometrisch 0,77 mm auseinander, in **26/26**
Leave-one-out-Fällen gegenseitige Bedränger. Ein symmetrisches Paar — und
trotzdem ein stark asymmetrisches Ergebnis:

| | Margin-Median | ACCEPT (Baseline) | ACCEPT (mit paarweisem Nachschlag α=8) |
|---|---|---|---|
| MESSER-5 | **0,069** | 0/13 | **0/13** |
| MESSER-7 | **0,452** | 0/13 | **7/13** |

Faktor 6,5 in der Margin. Die Kandidatensetgrößen sind identisch (4–5, Median 5)
— es ist nicht die Nachbarschaft.

### Der Unterschied steckt in genau einem Merkmal

Mittlerer Log-Beitrag je Merkmal, beide Richtungen (höher = besser für den
wahren Artikel):

| Merkmal | wahr = M5, Gegner M7 | wahr = M7, Gegner M5 |
|---|---|---|
| diameter_mm | −0,00 | −0,00 |
| circularity | +0,00 | +0,06 |
| solidity | −0,02 | +0,01 |
| delta_e_center | +0,04 | +0,14 |
| delta_e_rim | +0,21 | +0,21 |
| hist_center | +0,43 | +0,44 |
| hist_rim | +0,25 | +0,22 |
| **hu_log** | **+0,51** | **+5,17** |

Sieben Merkmale tragen in beiden Richtungen praktisch gleich bei. `hu_log` trägt
in der einen Richtung Faktor 10 mehr.

### Warum

| | MESSER-5 | MESSER-7 | Verhältnis |
|---|---|---|---|
| σ_enroll(hu_log) | **0,0338** | **0,8389** | **24,8** |
| σ_eff(hu_log) | 0,3815 | 0,9210 | 2,4 |

- **MESSER-7 gemessen:** die hu-Distanz trifft MESSER-5s enge Referenz →
  z 2,4× größer → z² 5,9× größer → der falsche Kandidat kassiert −5,66.
- **MESSER-5 gemessen:** dieselbe Distanz trifft MESSER-7s weite Referenz →
  der falsche Kandidat kassiert nur −0,51.

MESSER-7 profitiert also davon, dass sein Konkurrent sauber eingelernt ist.
MESSER-5 wird dafür bestraft, dass seiner es nicht ist.

---

## 3. Reichweite — ausdrücklich begrenzt

**Der Mechanismus ist aus der Formel hergeleitet, nicht statistisch
erschlossen.** Seine Existenz steht damit fest. Wie oft er im Betrieb beißt, ist
eine andere Frage — und die ist an diesen Daten **nicht** beantwortbar.

Über die sechs Bedränger-Paare des Bestands:

| Paar | σ-Verhältnis (hu_log) | Margins beide Richtungen | Effekt |
|---|---|---|---|
| MESSER-5 / MESSER-7 | 24,8 | 0,069 / 0,452 | **Faktor 6,5** |
| GABEL-11 / GABEL-14 | 12,3 | 0,549 / 0,460 | keiner |
| LOEFFEL-2 / LOEFFEL-5 | 23,9 | 0,931 / 0,927 | keiner |

`corr(σ_hu des Bedrängers, Margin-Median) = −0,29` bei n = 13 — **nicht
belastbar.**

Der Mechanismus braucht **zwei** Bedingungen gleichzeitig:

1. eine große σ-Asymmetrie zwischen den beiden Artikeln **und**
2. eine substanzielle Distanz zwischen ihnen **in genau diesem Merkmal**.

Bei GABEL-11/14 und LOEFFEL-2/5 ist die σ-Asymmetrie ähnlich groß, die
hu-Distanz aber klein — kein Effekt. In diesem Bestand treffen beide Bedingungen
bei **einem von sechs** Paaren zusammen.

**Was daraus NICHT folgt:** dass jeder Artikel mit weiter Streuung seine
Nachbarn spürbar schädigt. GABEL-9 hat `delta_e_center` bei 1,91× Floor und
erreicht trotzdem 13/13 ACCEPT — weil sein Kandidatenset nur zwei Einträge hat.
Das Kriterium markiert ein **Risiko**, das sich erst mit engen Nachbarn
realisiert.

---

## 4. Prüfkriterium: σ_enroll gegen σ_floor

Der `sigma_floor` ist der gemessene Mess-Rauschboden des Rigs
([config.yaml](../config/config.yaml), `matching.sigma_floors`, gemessen
2026-07-22). Streuen die Enrollment-Shots eines Artikels **stärker als dieser
Boden**, dann ist die Streuung nicht mehr Messrauschen, sondern Uneinigkeit der
eigenen Aufnahmen. Ob das ein behebbarer Enrollment-Mangel oder eine
Artikeleigenschaft ist, entscheidet der Jackknife-Test in Abschnitt 4b — die
Überschreitung allein sagt es nicht.

Verhältnis σ_enroll / σ_floor über die 13 Artikel (> 1 = über dem Boden):

| Artikel | diam | circ | soli | dEc | dEr | hic | hir | **hu** | max |
|---|---|---|---|---|---|---|---|---|---|
| GABEL-10 | 0,42 | 0,33 | 0,55 | 0,87 | 0,46 | 0,68 | 0,48 | **1,51** | 1,51 |
| GABEL-11 | 0,50 | 0,42 | **1,62** | 0,48 | 0,52 | 0,86 | 0,50 | **1,36** | 1,62 |
| GABEL-12 | 0,44 | 0,31 | 0,90 | **1,34** | 0,49 | 0,91 | 0,52 | 0,14 | 1,34 |
| GABEL-14 | 0,39 | 0,35 | 0,86 | **1,23** | 0,55 | **1,00** | 0,66 | 0,11 | 1,23 |
| GABEL-9 | 0,48 | 0,30 | 0,70 | **1,91** | 0,95 | **1,00** | 0,49 | 0,86 | 1,91 |
| LOEFFEL-1 | 0,52 | 0,82 | 0,53 | 0,42 | 0,53 | 0,66 | 0,52 | **1,54** | 1,54 |
| LOEFFEL-2 | 0,53 | 0,74 | 0,49 | 0,27 | 0,68 | 0,67 | 0,45 | **1,59** | 1,59 |
| LOEFFEL-3 | 0,57 | 0,99 | 0,70 | 0,43 | 0,25 | 0,57 | 0,44 | 0,16 | 0,99 |
| LOEFFEL-5 | 0,68 | 0,94 | 0,51 | 0,32 | 0,28 | 0,58 | 0,67 | 0,07 | 0,94 |
| LOEFFEL-6 | 0,62 | 0,88 | 0,35 | 0,33 | 0,67 | 0,62 | 0,55 | **1,34** | 1,34 |
| MESSER-5 | 0,31 | 0,86 | 0,39 | 0,66 | 0,45 | 0,73 | 0,45 | 0,09 | 0,86 |
| **MESSER-7** | 0,25 | **1,02** | 0,70 | **1,02** | 0,43 | 0,84 | 0,51 | **2,21** | **2,21** |
| MESSER-8 | 0,41 | 0,92 | 0,48 | 0,59 | 0,21 | 0,76 | 0,50 | 0,08 | 0,92 |
| **Artikel > 1** | 0 | 1 | 1 | 4 | 0 | 1 | 0 | **6** | — |

**Neun der dreizehn Artikel überschreiten den Floor in mindestens einem
Merkmal.** Nach Schwere:

```
MESSER-7   2,21x (hu_log)          LOEFFEL-1  1,54x (hu_log)
GABEL-9    1,91x (delta_e_center)  GABEL-10   1,51x (hu_log)
GABEL-11   1,62x (solidity)        LOEFFEL-6  1,34x (hu_log)
LOEFFEL-2  1,59x (hu_log)          GABEL-12   1,34x (delta_e_center)
                                   GABEL-14   1,23x (delta_e_center)
```

Auffällig ist die Verteilung über die Merkmale: `hu_log` (6×) und
`delta_e_center` (4×) tragen fast alle Überschreitungen. `diameter_mm`,
`delta_e_rim` und `hist_rim` überschreiten **nie** — bei ihnen sind die
Enrollment-Shots durchweg einig.

Die sechs hu_log-Überschreiter sind der Grund, warum die Diskussion überhaupt
mit hu_log begann. Der Mechanismus ist aber merkmalsunabhängig: er gilt für jedes
Merkmal, dessen σ_enroll über dem Floor liegt.

---

## 4b. EINWAND (2026-08-01, geprüft): weite Streuung ist nicht immer ein Enrollment-Mangel

Der Einwand: Beim Einlernen wurden **alle** Artikel gleich behandelt — gleiche
Shot-Zahl, gleiches Anheben und Drehen, gleiche Session, gleicher Fixpunkt. Die
Streuungsunterschiede können dann keine Enrollment-Qualität sein, sondern sind
eine **Artikeleigenschaft**: manche Formen reagieren empfindlicher auf Rotation
als andere. Faktor 25 bei `hu_log` lässt sich nicht durch sorgfältigeres
Hinlegen wegmachen.

**Der Einwand ist an den Daten teilweise entscheidbar.** Test: σ nach Weglassen
der ein bzw. zwei am weitesten vom Prototyp entfernten Shots neu rechnen. Fällt
σ dann unter den Floor, war es ein **Ausreißer-Shot** (Aufnahmeproblem, durch
Wiederholen behebbar). Bleibt es darüber, ist die Verteilung **gleichmäßig
breit** (Artikeleigenschaft, durch Wiederholen NICHT behebbar).

| Artikel | Merkmal | σ/Floor | ohne 1 | ohne 2 | Urteil |
|---|---|---|---|---|---|
| **MESSER-7** | **hu_log** | **2,21** | **2,17** | **2,15** | **gleichmäßig breit** |
| GABEL-9 | delta_e_center | 1,91 | 1,61 | 1,41 | gleichmäßig breit |
| LOEFFEL-1 | hu_log | 1,54 | 1,51 | 1,46 | gleichmäßig breit |
| GABEL-10 | hu_log | 1,51 | 1,40 | 1,23 | gleichmäßig breit |
| GABEL-11 | hu_log | 1,36 | 1,31 | 1,24 | gleichmäßig breit |
| LOEFFEL-6 | hu_log | 1,34 | 1,22 | 1,08 | gleichmäßig breit |
| GABEL-11 | solidity | 1,62 | 0,62 | 0,55 | Ausreißer (1 Shot) |
| LOEFFEL-2 | hu_log | 1,59 | 1,33 | 0,99 | Ausreißer (2 Shots) |
| GABEL-12 | delta_e_center | 1,34 | 0,77 | 0,64 | Ausreißer (1 Shot) |
| GABEL-14 | delta_e_center | 1,23 | 0,76 | 0,71 | Ausreißer (1 Shot) |
| MESSER-7 | circularity | 1,02 | 0,87 | 0,70 | Ausreißer (1 Shot) |
| MESSER-7 | delta_e_center | 1,02 | 0,61 | 0,58 | Ausreißer (1 Shot) |
| GABEL-9 | hist_center | 1,00 | 0,94 | 0,86 | Ausreißer (1 Shot) |

**Es sind zwei verschiedene Mechanismen, etwa hälftig verteilt** (6 gleichmäßig
breit, 7 ausreißergetrieben) — und sie brauchen verschiedene Antworten:

- **Ausreißergetrieben** (7 Fälle): ein einzelner Shot zieht σ über den Floor.
  Durch Wiederholen behebbar, und ebenso durch eine robuste σ-Schätzung
  (Median/MAD statt Standardabweichung) — Letzteres wäre allerdings ein Eingriff
  in `features.compute_enrollment_stats`, also in den Messpfad. Hier nur notiert.
- **Gleichmäßig breit** (6 Fälle): die Form reagiert wirklich empfindlich auf
  Rotation. **Nicht durch sorgfältigeres Einlernen behebbar.**

**Entscheidend:** Der Fall, der die ganze MESSER-5/MESSER-7-Asymmetrie treibt —
MESSER-7s `hu_log` — ist der **gleichmäßig breite**. σ/Floor fällt von 2,21 nur
auf 2,15, wenn man die zwei schlimmsten Shots streicht. Für genau den
motivierenden Fall gilt der Einwand also: **„sauberer einlernen" ist keine
hinreichende Antwort.**

Daraus folgt die allgemeinere Einschränkung: Ein System, das nur bei perfektem
Enrollment funktioniert, ist im Betrieb nicht haltbar — bei DO&CO wird nicht
jeder Artikel unter Laborbedingungen eingelernt. Die Konstruktion von `sigma_eff`
muss mit ungleichen Streuungen umgehen können. Das ist Gegenstand einer eigenen
Untersuchung (Block D) und **nicht** durch dieses Dokument beantwortet.

---

## 5. Was daraus für das Neu-Enrollment folgt

**Nach jedem eingelernten Artikel** — vor dem Übernehmen in die DB:

1. Für jedes der acht Scoring-Merkmale `sigma_enroll / sigma_floor` bilden.
2. Liegt ein Verhältnis **über 1,0**, streuen die eigenen Aufnahmen stärker als
   der Mess-Rauschboden. Das ist kein Rauschen mehr, sondern ein
   Aufnahme-Problem: verrutschte Auflage, wechselnde Ausrichtung, ein Ausreißer
   unter den Shots, unscharfe erste Aufnahme.
3. **Dann den Jackknife-Test aus Abschnitt 4b anwenden**, bevor entschieden wird:
   σ ohne die ein bzw. zwei äußersten Shots neu rechnen.
   - Fällt σ unter den Floor → **Ausreißer-Shot, neu einlernen statt
     übernehmen.** Der Qt-Einlerndialog hat den Pfad dafür bereits:
     „Verwerfen" sichert die Aufnahmen nach `data/verworfen/<artikel>/<ts>/`
     und schreibt nichts in die DB.
   - Bleibt σ über dem Floor → **gleichmäßig breit, Wiederholen hilft nicht.**
     Übernehmen, aber den Artikel als rotationsempfindlich vermerken. Er wird
     ein klebriger Bedränger bleiben; die Antwort darauf liegt nicht im
     Enrollment (siehe Abschnitt 4b und Block D).

Der Aufwand ist eine Wiederholung von zwölf Aufnahmen. Der Nutzen ist, dass der
Artikel kein klebriger Bedränger für seine Nachbarn wird — und dass er selbst
eine belastbare Referenz bekommt.

**Reihenfolge beachten:** Die Duplikatprüfung
([2026-08-01-duplikatpruefung-methode.md](2026-08-01-duplikatpruefung-methode.md))
kommt danach, über den fertigen Bestand. Beide Prüfungen zusammen:

```
create-article → Enrollment (N Shots)
       ↓
   sigma_enroll / sigma_floor je Merkmal   ← DIESES Dokument, je Artikel
       ↓  (> 1 -> verwerfen und neu einlernen)
   ... alle Artikel eingelernt ...
       ↓
   Duplikat-Scan d/sigma < 2,0             ← ueber den ganzen Bestand
       ↓
   Identifikationslauf / analyze / Simulation
```

---

## 6. OFFEN — und ausdrücklich nicht geprüft

**Ob ein Wiedereinlernen der neun Überschreiter die Margins ihrer Nachbarn
tatsächlich hebt, ist NICHT gemessen.** Das ist der direkte Test des ganzen
Befunds, und er braucht neue Aufnahmen — mit den vorhandenen Daten ist er nicht
zu machen, weil ein besseres Enrollment nicht simuliert werden kann.

Was sich vorhersagen lässt: MESSER-5 müsste davon profitieren, wenn MESSER-7
sauber neu eingelernt wird (σ_hu von 0,84 auf die Größenordnung der übrigen
Messer, also ~0,03). Der Strafterm für MESSER-7-als-falscher-Kandidat stiege
dann von −0,51 in Richtung −5, und MESSER-5s Margin sollte sich der 0,452 von
MESSER-7 annähern. **Das ist eine Vorhersage, keine Messung** — und sie ist an
der Windows-Box überprüfbar, wenn dort ohnehin neu eingelernt wird.

Ebenfalls offen: ob 0,452 überhaupt reicht. Auch der bessere der beiden Werte
liegt eine Größenordnung unter dem Gate von 2,0. Der Befund verbessert die
Ausgangslage, er löst das Margin-Problem nicht.

---

## 7. VORSCHLAG (nicht umgesetzt): das Diagnoseblatt zeigt es nicht

Geprüft: **`docodetect/enrollment_sheet.py` liest `sigma_floors` nirgends.**
Kein Treffer auf `sigma_floor`, `floors` oder `matching` in der ganzen Datei.

Die Streuungstabelle (Feld 4) zeigt je Merkmal `Mittel · Std · Min · Max ·
Spannw. · Extrem-Shot · z_klass · z_rob · Ref-σ`. Der Wert steht also da — aber:

- der **Floor kommt auf dem Blatt nicht vor**, weder als Spalte noch als Linie;
- die einzige farbliche Hervorhebung ist `|z_rob| ≥ 3,0` des Extrem-Shots, also
  ein **Ausreißer**-Kriterium, kein Streuungs-Kriterium;
- der Vergleichsmaßstab in der Überschrift ist die C-Serie-Bandbreite von
  `ext_full` (0,43–0,92 mm) — eine ganz andere Größe.

Wer beim Einlernen entscheiden soll, müsste die acht Floor-Werte auswendig
kennen und im Kopf dividieren. **Die Information ist vorhanden, aber nicht
handlungsfähig aufbereitet.**

Naheliegender Vorschlag, hier nur notiert:

- eine Spalte `σ/Floor` in der Streuungstabelle,
- Zeile rot, wenn das Verhältnis > 1,0,
- eine Kopfzeile „N Merkmale über dem Rauschboden" als Ampel für den
  Übernehmen/Verwerfen-Knopf.

Das wäre eine Änderung an `enrollment_sheet.py` — reine Konsumentenschicht, kein
Messpfad, aber ein Eingriff in ein Blatt, das im Einlern-Dialog vor dem
DB-Schreiben erscheint. **Nicht umgesetzt**, gehört als eigener Schritt
entschieden.

---

## Verwandte Dokumente

- [2026-08-01-blockB-paarweises-scoring.md](2026-08-01-blockB-paarweises-scoring.md) —
  wo der Befund aufgetaucht ist (Sonde MESSER-5/MESSER-7).
- [2026-08-01-duplikatpruefung-methode.md](2026-08-01-duplikatpruefung-methode.md) —
  die zweite Prüfung, die vor jede Auswertung gehört.
- [2026-07-31-reference-stats-keine-sessions.md](2026-07-31-reference-stats-keine-sessions.md) —
  warum zwei Einlern-Sessions still zu einem σ verschmelzen; verwandte Falle beim
  Neu-Einlernen.
