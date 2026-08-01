# NEGATIVBEFUND: Das Breitenprofil w(s) wird NICHT als Scoring-Merkmal gebaut

**Datum:** 2026-08-01 · **Art:** Negativbefund mit Entscheidung. Kein Code, keine
Config, keine Baseline geändert.
**Datenbasis:** Sandbox `neuenroll-2026-08`, Run `20260801-140818` — 15 Artikel ×
13 Referenz-Shots (195/195 segmentiert), 16 zusätzliche Ein-Shot-Kandidaten,
15 gelabelte Testaufnahmen.

> **Diese Frage ist entschieden und beantwortet. Wer sie erneut aufmacht, muss
> zuerst die Floor-Abschätzung in Abschnitt 6 widerlegen — nicht die
> Trennschärfe-Zahlen.** Die Trennschärfe ist unstrittig gut; sie ist nicht der
> Grund für die Absage.
>
> **PRÄZISIERUNG 2026-08-01 (Abschnitt 11):** Der Riegel gilt **für Gewichte bis
> 0,25 und für σ_floor ≥ 1,50 mm**. Für den Bereich **Gewicht 0,60 bei floor
> 0,5–1,0** ist die Absage **nicht belegt** — dort wurde nie gerechnet. Wer die
> Frage in diesem Bereich aufmacht, macht sie zu Recht auf.
>
> **ZWEITE PRÄZISIERUNG 2026-08-01 (Ende Abschnitt 11), betrifft Abschnitt 6:**
> Die Floor-Abschätzung „0,50–0,89 mm" ist im Wert richtig, aber falsch
> beschriftet — die 8,56 mm Drift stehen über **64 %** der Feldhöhe, nicht über
> die halbe. Als Rate gerechnet spannt der plausible Betriebs-Floor
> **0,40–1,41 mm**, je nachdem, wie weit die Auflage im Betrieb streut, und
> umspannt damit die Entscheidungsgrenze von 1,0 mm. **Die Absage bleibt, ihre
> Begründung ist ausgetauscht:** nicht „der Floor liegt zu hoch", sondern „der
> Floor ist unbekannt". Messung:
> [2026-08-01-positionsdrift-messung.md](2026-08-01-positionsdrift-messung.md).

---

## Auslöser

Der Fixpunkt-Test ([2026-08-01-fixpunkt-test-scoring.md](2026-08-01-fixpunkt-test-scoring.md))
lieferte 15/15 Top-1 korrekt bei nur 3 ACCEPT: das Ranking stimmt, die
LLR-Margin bricht bei großen Kandidatensets ein. `contour-band` zeigte auf zwei
Bedränger-Paaren deutliche Formunterschiede im Breitenprofil w(s), die keines der
acht Scoring-Merkmale sieht — bei MESSER-5/MESSER-7 ein Doppelmaximum gegen ein
einfaches, Differenzen ~3 mm bei ~0,5 mm Shot-Streuung.

Frage: Würde w(s) als zusätzliches Merkmal die 12 AMBIGUOUS-Fälle retten?

**Antwort: nein.** Im günstigsten geprüften Setting 4 von 12, ab einem
σ_floor von 1,0 mm keiner — und der Betriebs-Floor liegt nach eigener
Abschätzung genau in diesem Band.

---

## 1. Ausgangslage w(s)

Berechnet in `enrollment_sheet._shot_geometry`
([docodetect/enrollment_sheet.py:88-146](../docodetect/enrollment_sheet.py)); die
Primitive (`_densify`, `_pca_axes`, `_proj`, `_pctl`) liegen im Messpfad
(features.py) und werden importiert.

**Nirgends persistiert.** `ShotGeom` ist transient und wird nur ins
Diagnoseblatt (Feld 2) bzw. `contour_band` (Panel b) gerendert. Nicht in
`Features`, nicht in `features_json`, nicht in `reference_stats`, nicht im
Report-JSON.

- Referenzseite: **nicht** aus `reference_features` rekonstruierbar — features_json
  enthält kein Profil, `lat_p98_mm` ist ein einzelner Skalar. Neuberechnung nur
  aus den PNGs über `pipeline.analyze`, ~3–5 s je 4K-Bild.
- Messseite: **rekonstruierbar ohne Neusegmentierung** — `MatchReport.contour`
  enthält die Kontur in px. w(s) einer Testaufnahme ist allein aus dem
  Report-JSON berechenbar.

---

## 2. Die Trennschärfe ist gut — daran liegt es nicht

Distanzmaß: Profile auf 101 Stützstellen über u = s/L resampelt, L2 = RMS der
mm-Differenz. σ-Konvention wie `features._proto_stats` bzw. `analysis.py`.

Trennschärfe-Matrix über die 105 Paare der 15 Artikel, Median:

| Merkmal | Median | Paare < 2 σ |
|---|---|---|
| solidity | 25,87 | 7 |
| **w(s) L2** | **16,13** | **3** |
| diameter_mm | 12,88 | 18 |
| circularity | 7,86 | 16 |
| hu_log | 1,81 | 59 |
| delta_e_rim / hist_center | 1,72 | 59 / 63 |
| hist_rim | 1,48 | 77 |
| delta_e_center | 1,26 | 73 |

Auf den beiden Bedränger-Paaren:

| Paar | bestes der 8 Merkmale | w(s) | absolut |
|---|---|---|---|
| MESSER-5 / MESSER-7 | 1,43 (hu_log) | **12,47** | 3,49 mm |
| GABEL-11 / GABEL-14 | 2,19 (delta_e_rim) | **3,44** | 1,63 mm |

Die Extraktion reproduziert die contour-band-Beobachtung: MESSER-5
18,5 / Tal 7,8 / 16,9 (beobachtet 18,2 / 7,8 / 17,0), MESSER-7 20,6 / 10,7 / 15,6
(beobachtet 21,1 / 10,6 / 15,5).

---

## 3. Warum es trotzdem nicht trägt

Matcher-Arithmetik aus den Report-JSONs rekonstruiert (distance, sigma_enroll,
reference stehen je Kandidat und Merkmal drin), inklusive Fisher-adaptiver
Gewichte. Reproduktion geprüft: **14/15 Reports auf ≤ 0,009** in `llr_margin`
und `max|z|`. Der 15. (GABEL-9, 333,71 vs 331,08) weicht ab, weil der Report
`sigma_enroll` auf 4 Nachkommastellen rundet und der **Verlierer** MESSER-8 bei
solidity σ_enroll = 0,0021 mit z = 65 hat — z² verstärkt die Rundung.
Entscheidungsirrelevant.

| Gewicht w(s) | σ_floor | LLR-Faktor Median | max | ACCEPT | Top-1 | neue REJECT |
|---|---|---|---|---|---|---|
| 0,10 | 0,25 | 1,5× | 33,9× | 3 → 6 | 15/15 | 0 |
| 0,10 | 0,50 | 1,2× | 14,7× | 3 → 5 | 15/15 | 0 |
| 0,15 | 0,50 | 1,4× | 20,7× | 3 → 6 | 15/15 | 0 |
| 0,25 | 0,50 | 1,5× | 31,3× | 3 → 7 | 15/15 | 0 |
| 0,10 | 1,00 | 1,1× | 5,0× | 3 → 3 | 15/15 | 0 |
| 0,10 | 1,50 | 1,0× | 2,8× | 3 → 3 | 15/15 | 0 |

(Gewichte roh vor Normierung; Ø hat 0,50.)

Zwei Ursachen:

### 3a Die Score-Aggregation, nicht der Merkmalsraum

`log_score` ist ein gewichtetes **Mittel**, je Kandidat renormiert
([matcher.py:336-351](../docodetect/matcher.py)). Ein Merkmal mit ~9 %
Gewichtsmasse kann eine Margin von 0,11 nicht auf 2,0 heben — dafür bräuchte es
Faktor 18. Nur MESSER-7 erreicht das.

**Das ist der wichtigste Übertrag aus dieser Analyse:** das Problem sitzt in der
Aggregation, nicht im Merkmalsraum. Ein zusätzliches Merkmal wird durch die
Mittelung genau so weit verdünnt, wie es Gewicht bekommt.

### 3b MESSER-2/5/6 sind auch im Profil entartet

Innerhalb des Trios beträgt d_w(s) nur **0,25–0,56 mm** bei einer Shot-Streuung
von 0,27–0,35 mm. MESSER-7 liegt **3,4–3,5 mm** von allen dreien entfernt.

Folge: w(s) verdrängt MESSER-7 aus Platz 2 der Reports von MESSER-2/5/6, neuer
Platz 2 wird ein anderes Mitglied desselben Trios — die Margin bewegt sich kaum,
MESSER-2 **sinkt** sogar von 0,54 auf 0,50. Nur MESSER-7s eigener Report gewinnt
14,7×, weil sein Bedränger MESSER-5 jetzt 3,45 mm entfernt ist.

Das GABEL-Cluster (10/11/12/14) liegt dazwischen: 1,3–2,1 mm bei 0,3–0,55 mm
Streuung → 1,2–3,2×, weiterhin unter 2,0.

**Für MESSER-2/5/6 ist der klassische Merkmalsraum erschöpft.** Weder die acht
Merkmale noch das Profil trennen sie. Das Trio ist ein Kandidat für Stufe 2
(DINOv2 + FAISS, `docodetect/embeddings.py`), nicht für weitere Merkmalsarbeit.

---

## 4. z-Gate: kein Risiko, aber auch kein Argument

AMBIGUOUS gegen REJECT zu tauschen wäre kein Fortschritt gewesen — passiert aber
nicht:

- Sieger heute: max|z| min 0,52, **Median 0,77**, max 2,06 (GABEL-12, getrieben
  von delta_e_center). Kopffreiheit bis zum Gate 3,5 überall **≥ 1,44 σ**.
- Profil-z des wahren Artikels bei Floor 0,5: **0,15–0,98** — nie das Maximum.
  In der Gegenrechnung ändert sich max|z| des Siegers in genau einem Fall
  (LOEFFEL-1, 0,77 → 0,98).
- **0 von 15 überschreiten 3,5; 0 neue REJECT in allen sechs Settings.**
- Strukturell ausgeschlossen: z_w = d_test / √(σ_enroll² + floor²). Größtes
  d_test 0,787 mm (LOEFFEL-1) bei σ_enroll 0,598 → z ≤ 1,32 selbst bei Floor 0.

---

## 5. Zwei Prämissen-Korrekturen (unabhängig von w(s) gültig)

### 5a Das Profil trägt die Länge NICHT ein zweites Mal

Die Vermutung war, w(s) müsse auf die Objektlänge normiert werden, weil es sonst
die Längeninformation dupliziert und damit Ø doppelt zählt. **Trifft nicht zu:**

| Beziehung | r | R² |
|---|---|---|
| \|Δ Länge\| ↔ Profildistanz unnormiert | +0,180 | 3,3 % |
| \|Δ Länge\| ↔ Profildistanz normiert | +0,196 | 3,8 % |
| \|Δ ext_full\| ↔ Profildistanz form-only | +0,113 | **1,3 %** |
| \|Δ lat_p98\| ↔ Profildistanz voll | **+0,847** | **71,8 %** |

Die tatsächliche Dopplung ist die **Breite**: `lat_p98` erklärt 72 % der
Profil-Distanz. `lat_p98` ist heute Diagnose, kein Scoring-Merkmal — w(s)
dupliziert also nichts Gescortes. Aber: „w(s) aufnehmen" und „lat_p98 aufnehmen"
sind weitgehend derselbe Schritt; form-only bleiben 42 % eigenständige Varianz.

Amplituden- gegen Formanteil: die mittlere Breitendifferenz macht im Median nur
13,6 % von d² aus — **86 % der Profildistanz ist echte Form.**

Normieren wäre trotzdem richtig gewesen, nur aus einem anderen Grund:
Vergleichbarkeit von Shots verschiedener Messlänge, plus Streuungsgewinn
(siehe 5c).

### 5b `area_mm2` und `aspect_ratio` sind KEINE Scoring-Merkmale

Die acht Scoring-Merkmale sind: `diameter_mm`, `circularity`, `solidity`,
`delta_e_center`, `delta_e_rim`, `hist_center`, `hist_rim`, `hu_log`.

`area_mm2` ist per config.yaml ausdrücklich ausgeschlossen („Fläche geht NICHT
ins Scoring – korreliert voll mit Ø"), `aspect_ratio` war es nie. Beide gehen nur
in den Vorfilter bzw. die Artikel-Klassifikation.

Die starken strukturellen Redundanzen liegen genau bei den ausgeschlossenen
Größen: equiv_diameter ↔ area 1,00, circularity ↔ area 0,95, aspect_ratio ↔
lat_p98 0,95. **Operativ** (Pearson über die z-Werte von 101 Kandidatenzeilen)
gibt es unter den acht nur **ein** Paar ≥ 0,7 — circularity ↔ delta_e_rim +0,73,
Artefakt dieses Artikelsatzes. Alles übrige 0,04–0,68. Keine schwere Redundanz
im Betrieb.

Gewichtsmasse zum Vergleich:

| Gruppe | global | effektiv (Fisher, Mittel über 15 Reports) |
|---|---|---|
| Ø (diameter_mm) | 50,0 % | 46,1 % |
| Form (circ + solid + hu) | 20,0 % | 27,3 % |
| Farbe (4 Merkmale) | 30,0 % | **26,6 %** |

Trennschärfstes Merkmal je Paar über 105 Paare: solidity 67×, diameter 30×,
circularity 5×, delta_e_rim 1×, hist_rim 1×, hu_log 1×, delta_e_center 0×,
hist_center 0×. → **26,6 % effektive Gewichtsmasse liegen auf vier Farbmerkmalen,
die bei 2 von 105 Paaren das beste Merkmal sind.** Zahl ohne Empfehlung; eine
Gewichtsänderung braucht Datengrundlage UND expliziten Auftrag.

### 5c Nebenbefund zur Ausrichtung (falls das Thema je zurückkommt)

Der heutige Nullpunkt (s = 0 am Breitenmaximum) zittert stark: sd(s_wmax) bis
**4,47 mm**, Spanne bis **17,6 mm** (MESSER-2) — bei ~3 mm Signal.

Ursache ist **nicht** ein Buckelsprung: 13/13 Shots je Artikel liegen im selben
Buckel, 0/195 Orientierungswidersprüche, Flip-Reserve 8–10 σ. Ursache ist ein
**Plateau**: der Bereich <0,3 mm unter dem Maximum ist bei MESSER-2 32,2 mm breit.
Ein argmax auf einem 30-mm-Plateau ist Rauschen, kein Ort.

Rest-Streuung der 13 Profile je Ausrichtung (mm RMS, Mittel über 15 Artikel):
argmax (heute) 0,500 · **Längen-Normierung u = s/L 0,404** · Schwerpunkt-Anker
0,442 · Kreuzkorrelation 0,242 (mit freiem Parameter je Shot gefittet, nach unten
verzerrt).

Der Flächenschwerpunkt hat über alle 15 Artikel sd 0,0012–0,0028 und **0
Seitenwechsel** — zwei Größenordnungen stabiler als der argmax, weil Integral
statt Punktschätzung.

---

## 6. Die Größe, die den Ausschlag gibt: der Betriebs-Floor

Aus den Fixpunkt-Daten ergibt sich **σ_floor = 0,000 mm**: die Testaufnahme liegt
mit RMS 0,357 mm **näher** am Prototyp als der mittlere Enrollment-Shot
(0,441 mm). Auch die Alt-Referenz aus früherer Session liegt mit 0,321 mm unter
der Intra-Session-Streuung (0,473 mm).

**Das ist ein Fixpunkt-Artefakt, kein Merkmalswert.** Enrollment und Test teilen
die Auflage; die Positionsstreuung ist per Konstruktion aus den Daten entfernt.

Abschätzung des echten Floors: ein globaler Maßstabsfehler von k % erzeugt eine
Profildistanz von k · RMS(w(s)); RMS(w) liegt bei 12,6–22,2 mm. Mit der
dokumentierten ext_full-Drift von **8,6 mm über die halbe Bildhöhe** bei MESSER-2
(L = 215 mm → 4,0 %) ergibt das **0,50–0,89 mm** — das **1,4–2,3-fache** der
heutigen σ_enroll.

Floor-Empfindlichkeit der Trennschärfe:

| σ_floor | Median sep | Paare < 2 σ | MESSER-5/7 |
|---|---|---|---|
| 0,00 | 16,13 | 3 | 12,47 |
| 0,50 | 13,64 | 3 | 6,98 |
| 1,00 | 7,39 | 13 | 3,49 |
| 1,50 | 4,92 | 19 | 2,33 |
| 2,00 | 3,69 | 28 | 1,74 |

**Der geschätzte Betriebs-Floor (0,5–0,9 mm) liegt genau dort, wo der Gewinn von
4 zurückgewonnenen ACCEPT auf 0 fällt.** Hoher Aufwand — Persistenz des Profils,
Enrollment-Format, Matcher-Merkmal, Korpus-Re-Baselining — für einen Gewinn, der
bei realistischer Positionsstreuung verschwindet.

> **→ Diese Herleitung ist am 2026-08-01 korrigiert worden (Ende Abschnitt 11).**
> Der Text hier bleibt unverändert, aber wer nur diesen Abschnitt liest, bekommt
> eine zu schmale Zahl: die 8,56 mm Drift stehen über **64 %** der Feldhöhe,
> nicht über die halbe. Als Rate gerechnet spannt der Floor **0,40–1,41 mm** je
> nach unterstellter Auflage-Streuung — er umspannt die Entscheidungsgrenze von
> 1,0 mm, statt darüber zu liegen. Der Effekt selbst ist inzwischen aus den
> Rohdaten belegt (r = −0,997):
> [2026-08-01-positionsdrift-messung.md](2026-08-01-positionsdrift-messung.md).

---

## 7. Entscheidung

**w(s) wird NICHT als Scoring-Merkmal gebaut.** Begründung: 4 von 12 im
günstigsten Setting, 0 ab Floor 1,0 mm, und der Betriebs-Floor liegt in diesem
Band.

Mitgenommen:

1. **Das Problem sitzt in der Score-Aggregation, nicht im Merkmalsraum.** Das
   gewichtete Mittel ist der Verdächtige. Weiterverfolgt in der
   Leave-one-out-Simulation über die 195 Shots, dort mit Priorität auf
   „Summe statt gewichtetem Mittel". w(s) fällt dort als Variante raus.
2. **MESSER-2/5/6 sind auch im Profil entartet** → Kandidat für Stufe 2, nicht
   für weitere Merkmalsarbeit.
3. Die zwei Prämissen-Korrekturen aus Abschnitt 5 gelten unabhängig von dieser
   Entscheidung.

---

## 8. Einschränkungen der Analyse

- **Fixpunkt-Referenzen ohne Positionsstreuung.** σ_floor = 0,000 mm ist kein
  Betriebswert; alle Trennschärfen und LLR-Faktoren sind ohne Floor optimistisch.
  Deshalb die Sweeps in Abschnitt 3 und 6.
- n = 13 je Artikel, 15 Artikel, **eine** Testaufnahme je Artikel. Die
  LLR-Faktoren beruhen auf 15 Einzelmessungen; ein Konfidenzintervall je Artikel
  gibt die Basis nicht her. Die 105 Paar-Trennschärfen sind Punktschätzer ohne
  Fehlerband.
- Die 13 Shots sind **1 Alt-Shot + 12 einer Session** — `reference_stats` kennt
  keinen Session-Begriff ([2026-07-31-reference-stats-keine-sessions.md](2026-07-31-reference-stats-keine-sessions.md)).
  σ_enroll mischt Innerhalb- und Zwischen-Session.
- Die Profil-Entartung von MESSER-2/5/6 stützt sich auf 3 Artikel; ob sie über
  5 Messer hinaus generalisiert, ist offen.
- **Nicht geprüft:** ob ein amplituden-normiertes (dimensionsloses) Profil
  positionsrobuster wäre. Das wäre der einzige Ansatz, der die Floor-Abschätzung
  aus Abschnitt 6 aushebeln könnte — wer die Frage wieder aufmacht, fängt dort an.

---

## 9. NACHTRAG 2026-08-01 (nach Erstfassung): MESSER-2 und MESSER-5 sind dasselbe Objekt

**Der Originaltext oben bleibt unverändert stehen.** Dieser Nachtrag korrigiert
eine Aussage daraus.

Am 2026-08-01 wurde **am physischen Objekt** festgestellt: MESSER-2 und MESSER-5
sind dasselbe Besteckteil, beim Sammeln doppelt erfasst. Nicht aus den Daten
geschlossen, sondern am Objekt geprüft.

### Was dadurch hinfällig wird

Abschnitt 3b sagt: „MESSER-2/5/6 sind auch im Profil entartet … Für dieses Trio
ist der klassische Merkmalsraum erschöpft." **Für das Paar MESSER-2/MESSER-5
ist das falsch begründet.** Dort war nichts entartet — zwei Datenbankeinträge
beschrieben dasselbe Objekt. Kein Merkmal der Welt trennt einen Gegenstand von
sich selbst. Das war ein **Datenfehler, kein Merkmalsversagen.**

Der Beleg deckt sich mit den Zahlen aus Abschnitt 3b: Profildistanz 0,25 mm bei
einer Shot-Streuung von 0,278 mm, also **d/σ = 0,92** — unterhalb der eigenen
Messstreuung. Dazu identischer Doppelbuckel, deckungsgleicher Umriss,
Registrier-Restfehler beide 0,71 mm.

### Was bestehen bleibt

**MESSER-6 ist ein echter Nachbar von MESSER-5**, kein Duplikat:

| Paar | d | σ_eff | d/σ | Einordnung |
|---|---|---|---|---|
| MESSER-2 / MESSER-5 | 0,25 mm | 0,278 | **0,92** | dasselbe Objekt |
| MESSER-5 / MESSER-6 | 0,38 mm | 0,316 | 1,20 | echter, sehr enger Nachbar |
| MESSER-2 / MESSER-6 | 0,48 mm | 0,313 | 1,53 | dito (= 5/6, andere Erfassung) |
| nächstes Paar (MESSER-10/MESSER-4) | 1,01 mm | — | 2,18 | deutlich getrennt |

Aus dem Trio wird also ein **Paar**: MESSER-5 und MESSER-6 liegen 1,20 σ
auseinander. Das ist trennbar, aber sehr eng — die Aussage „Kandidat für Stufe 2"
gilt für dieses Paar unverändert, nur eben für zwei statt drei Artikel.

### Kernaussage des Negativbefunds: NICHT berührt

Nachgerechnet, beide Male über dieselbe Gegenrechnung wie in Abschnitt 3:

| | n | ACCEPT (w=0,10 / floor 0,50) | ACCEPT (w=0,15) | LLR-Faktor Median | max |
|---|---|---|---|---|---|
| mit MESSER-2 | 15 | 3 → 5 | 3 → 6 | 1,25× | 14,7× |
| **ohne MESSER-2** | 14 | **3 → 5** | **3 → 6** | **1,25×** | 14,7× |

Identisch. Die Erwartung, dass die Kernaussage nicht betroffen ist, trifft zu —
und zwar aus einem strukturellen Grund: die Absage hängt am **gewichteten
Mittel** (Abschnitt 3a) und am **Betriebs-Floor** (Abschnitt 6). Beide sind von
der Zusammensetzung des Artikelbestands unabhängig. MESSER-2 war in keinem
einzigen Report der Zweitplatzierte, und die LLR-Margin ist eine
Platz-1-gegen-Platz-2-Größe — der Duplikateintrag hat sie nie berührt.

**Die Entscheidung „w(s) wird nicht gebaut" bleibt unverändert gültig.**

### Duplikat-Scan über den gesamten Bestand

Gleiche Methode auf alle 40 Artikel angewandt (780 Paare; für die 25
1-Shot-Artikel ersatzweise die gepoolte Shot-Streuung 0,463 mm, da ihre eigene
unbekannt ist):

- **d/σ ≤ 1,0: genau ein Paar** — MESSER-2 / MESSER-5 (0,92).
- d/σ ≤ 2,0: zusätzlich nur MESSER-5/MESSER-6 (1,20) und MESSER-2/MESSER-6 (1,53).
- Danach klarer Abstand: das nächste Paar liegt bei 2,18.

Kein weiterer Duplikatverdacht im Bestand. Einschränkung: für die 25
1-Shot-Artikel ist das ein schwächerer Test, weil ihr σ geschätzt ist.

Details und Auswirkung auf den Testlauf:
[2026-08-01-fixpunkt-test-scoring.md](2026-08-01-fixpunkt-test-scoring.md),
Nachtrag.

---

## 10. ZWEITER NACHTRAG 2026-08-01: MESSER-6 ist ebenfalls ein Duplikat

**Abschnitte 1–9 bleiben unverändert stehen.** Dieser Nachtrag korrigiert eine
Aussage aus Abschnitt 9.

Nach der physischen Prüfung von MESSER-6 (angestoßen durch den Scan in
Abschnitt 9): **MESSER-2, MESSER-5 und MESSER-6 sind drei Datenbankeinträge
desselben Besteckteils.** Aus 15 vermeintlichen Artikeln werden 13 echte.

### Was dadurch hinfällig wird

Abschnitt 9 sagt: „MESSER-6 ist ein echter Nachbar von MESSER-5, kein Duplikat"
und „Aus dem Trio wird ein Paar … MESSER-5 und MESSER-6 liegen 1,20 σ
auseinander". **Beides ist falsch.** Es gibt in diesem Bestand **kein entartetes
Paar mehr** — der gesamte vermeintliche Dreier-Cluster war ein Datenfehler.

Damit entfällt auch die Einordnung aus Abschnitt 3b, dieses Cluster sei ein
„Kandidat für Stufe 2". Es gibt hier nichts, was Stufe 2 lösen müsste; es gab
nur dreimal dasselbe Messer.

### Der Scan hatte recht — die Lücke war das Signal

Der Duplikat-Scan aus Abschnitt 9 hat **beide** Duplikate korrekt als Cluster
ausgewiesen:

| Paar | d | d/σ |
|---|---|---|
| MESSER-2 / MESSER-5 | 0,25 mm | **0,92** |
| MESSER-5 / MESSER-6 | 0,38 mm | **1,20** |
| MESSER-2 / MESSER-6 | 0,48 mm | **1,53** |
| — Lücke — | | |
| MESSER-10 / MESSER-4 (nächstes Paar) | 1,01 mm | 2,18 |

Der Fehler lag nicht im Scan, sondern in meiner Schwelle: ich hatte nur
d/σ ≤ 1,0 als „Duplikatverdacht" gewertet und 1,20 / 1,53 als „echte Nachbarn"
eingeordnet. Richtig gewesen wäre, die **Lücke** zu lesen: drei Paare unter 1,6,
dann nichts bis 2,18. Verdächtig ist alles unter **d/σ < 2,0**. Ausführlich:
[2026-08-01-duplikatpruefung-methode.md](2026-08-01-duplikatpruefung-methode.md).

### Kernaussage weiterhin NICHT berührt

Die Absage an w(s) hängt am gewichteten Mittel (Abschnitt 3a) und am
Betriebs-Floor (Abschnitt 6). Beide sind von der Bestandszusammensetzung
unabhängig. Die Neurechnung der Simulation mit 13 Artikeln bestätigt das
Gesamtbild unverändert: **127 von 169 Fällen bleiben AMBIGUOUS**, ACCEPT bleibt
bei 41, neun der dreizehn Artikel erreichen kein einziges ACCEPT [KORREKTUR
2026-08-01: **acht**, nicht neun — LOEFFEL-1 hat 1/13]
([2026-08-01-scoring-simulation-widerlegte-thesen.md](2026-08-01-scoring-simulation-widerlegte-thesen.md)).

**Die Entscheidung „w(s) wird nicht gebaut" bleibt unverändert gültig.**

---

## Verwandte Dokumente

- [2026-08-01-fixpunkt-test-scoring.md](2026-08-01-fixpunkt-test-scoring.md) — der
  Testlauf, der diese Frage ausgelöst hat.
- [2026-08-01-analysis-floor-key-befund.md](2026-08-01-analysis-floor-key-befund.md) —
  bei dieser Analyse gefundener Fehler in der Auswertungsschicht; die
  `discriminability`-Zahlen des Runs `20260801-140818` sind für die Farbmerkmale
  unbrauchbar.
- [2026-07-28-messpfad-aufgeschoben.md](2026-07-28-messpfad-aufgeschoben.md) —
  `lat_p98` als Kontext zu Abschnitt 5a.


---

## 11. NACHTRAG 2026-08-01: die Absage war unvollständig geprüft

**Abschnitte 1–10 bleiben unverändert.** Dieser Nachtrag korrigiert den
Geltungsbereich, nicht das Ergebnis.

Abschnitt 3 prüfte Gewichte von 0,10 bis 0,25. In Block D7 wurden 0,40, 0,60 und
1,00 nachgerechnet — und dort verschwindet der Gewinn bei floor 1,00 **nicht**.

### Was tatsächlich gilt

| Gewicht w(s) | σ_floor 0,50 | σ_floor 1,00 | σ_floor 1,50 |
|---|---|---|---|
| 0,10 | Gewinn | **kein Gewinn** | kein Gewinn |
| 0,25 | Gewinn | ~kein Gewinn | **kein Gewinn** |
| **0,60** | Gewinn | **GEWINN — nie geprüft** | **kein Gewinn** |

Bei Gewicht 0,60 und floor 1,00 liegt die ACCEPT-Rate bei 38 % (Testaufnahme-
Konstruktion) bzw. 43 % (Leave-one-out) gegen eine Baseline von 23 % / 24 %.
~~Der geschätzte Betriebs-Floor war 0,5–0,9 mm (Abschnitt 6) — dieser Bereich
liegt vollständig innerhalb der Zone, in der ein hohes Gewicht noch wirkt.~~

> **Durchgestrichen am 2026-08-01 nach der Positionsmessung.** Der Bereich
> liegt **nicht** vollständig in der Wirkzone — er umspannt deren Grenze. Siehe
> die Präzisierung am Ende dieses Abschnitts.

Ab floor 1,50 ist der Gewinn in beiden Konstruktionen und bei jedem geprüften
Gewicht vollständig weg. Die Absage gilt dort unverändert.

### Es sind nicht zwei Verfahren, die sich widersprechen

Der naheliegende Verdacht war, dass Leave-one-out (Messung stammt aus derselben
Enrollment-Serie wie der Prototyp) systematisch günstiger rechnet als die
Testaufnahme-Konstruktion aus Abschnitt 3. **Nachgerechnet — der Verdacht
bestätigt sich nicht:**

| Gewicht / floor | Testaufnahme (n=13) | Leave-one-out (n=169) |
|---|---|---|
| Baseline | 23 % | 24 % |
| 0,10 / 0,50 | 38 % | 34 % |
| 0,25 / 0,50 | 62 % | 54 % |
| 0,60 / 0,50 | 62 % | 67 % |
| 0,25 / 1,00 | 23 % | 27 % |
| 0,60 / 1,00 | 38 % | 43 % |
| 0,60 / 1,50 | 23 % | 24 % |

Die beiden Konstruktionen liegen überall innerhalb weniger Prozentpunkte und
zeigen keine systematische Richtung. **Mein Vorbehalt, LOO sei die günstigere
Konstruktion, ist damit gegenstandslos und wird zurückgezogen.** Der Unterschied
zwischen Abschnitt 3 und Block D7 ist kein Methodenunterschied — es ist eine
Lücke im geprüften Parameterbereich.

### Was der Nachtrag NICHT ändert

- Die Trennschärfe von w(s) war nie strittig (Abschnitt 2).
- Der Aufwand ist unverändert: Persistenz des Profils, Enrollment-Format,
  Matcher-Merkmal, Korpus-Re-Baselining.
- Die statistische Basis trägt weiterhin keine Entscheidung: n ≈ 13 Artikel,
  Fixpunkt-Referenzen ohne Positionsstreuung, und der Betriebs-Floor ist
  **geschätzt**, nicht gemessen. Ob er bei 0,5, 0,9 oder 1,5 liegt, entscheidet
  über das ganze Ergebnis — und genau das ist offen.
- top1 und k_safe bleiben bei jedem Gewicht bis 1,00 unverändert (169/169 bzw.
  168). Die Befürchtung, ein hohes w(s)-Gewicht ziehe `diameter_mm` herunter und
  schade dem Ranking, bestätigt sich nicht.

### PRÄZISIERUNG 2026-08-01: die Floor-Herleitung aus Abschnitt 6 war falsch beschriftet

Die Positionsmessung, auf der Abschnitt 6 beruht, ist inzwischen aus den
Rohdaten ausgewertet
([2026-08-01-positionsdrift-messung.md](2026-08-01-positionsdrift-messung.md)).
Sie **bestätigt den Effekt deutlicher als zuvor** (r = −0,997 über eine
Positionsleiter von 109 mm) und korrigiert zugleich die Herleitung:

**Die 8,56 mm stehen über 64 % der Feldhöhe, nicht über die halbe.** Abschnitt 6
hat die *beobachtete Spanne* verwendet und sie „halbe Bildhöhe" genannt. Als
Rate gerechnet (−0,0374 % je mm Verschiebung) hängt der Floor daran, wie weit
die Auflage im Betrieb streut:

| unterstellte Auflage-Streuung | Drift | relativ | → Floor |
|---|---|---|---|
| halbe Feldhöhe (85 mm) | 6,73 mm | 3,18 % | **0,40–0,71 mm** |
| beobachtete Leiter (109 mm) | 8,66 mm | 4,09 % | 0,52–0,91 mm |
| volle Feldhöhe (170 mm) | 13,47 mm | 6,36 % | **0,80–1,41 mm** |

Die dokumentierten 0,50–0,89 mm entsprechen der mittleren Zeile — der **Wert**
stimmt, die **Begründung** war ungenau.

**Das tauscht die Begründung der Absage aus.** Bisher stand hier: der Gewinn
verschwindet, weil der Betriebs-Floor in der Zone liegt, in der w(s) nicht mehr
wirkt. Richtig ist:

> Der plausible Bereich des Betriebs-Floors ist **0,40–1,41 mm** und umspannt
> damit die Entscheidungsgrenze von **1,0 mm** auf beiden Seiten. Der Faktor
> zwischen den Extremen ist **3,5**, und er hängt nicht an der Messung, sondern
> an einer **unbeobachteten Betriebsannahme** — wie weit die Objekte in der Box
> tatsächlich streuen. Diese Streuung ist nicht gemessen.

Die Absage bleibt, aber ihr Grund ist schmaler als bisher beschrieben: **nicht
„der Floor liegt zu hoch", sondern „der Floor ist unbekannt, und sein
plausibler Bereich umspannt die Entscheidungsgrenze".** Wer w(s) wieder
aufmacht, muss deshalb nicht die Trennschärfe und nicht die Floor-Abschätzung
angreifen — er muss den Floor **messen**.

**Praktische Folge, die nichts kostet:** eine engere Auflage-Zone verkleinert
den Floor. Wer die Objekte auf ein mittiges Feld beschränkt statt über die volle
Feldhöhe zu streuen, drückt den Beitrag dieses Effekts in Richtung der ersten
Tabellenzeile — und damit unter die Entscheidungsgrenze. Das ist eine
Bedienregel wie „mittig auflegen", keine Codeänderung. Sie steht im Konflikt
mit der Enrollment-Forderung nach *breiter* Positionsstreuung
([Ablaufzettel](2026-07-31-ablauf-enrollment-session.md), Schritt 3): das
Enrollment muss die Streuung sehen, der Betrieb sollte sie klein halten. Beides
zusammen ist kein Widerspruch, aber es gehört bewusst entschieden.

**Handlungsfolge:** unverändert nicht bauen. Sobald die Windows-Box einen
**gemessenen** Floor liefert — die Rasterfahrt aus
[positionsdrift-messung, Abschnitt 7](2026-08-01-positionsdrift-messung.md)
liefert ihn nebenbei —, ist die Frage neu zu stellen. Fällt er unter 1,0 mm,
ist w(s) mit hohem Gewicht ein ernsthafter Kandidat.
