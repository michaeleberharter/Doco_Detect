# Fixpunkt-Test: Trennt das Scoring, wenn der Positionseffekt eliminiert ist?

**Datum:** 2026-08-01
**Sandbox:** `neuenroll-2026-08`
**Run:** `20260801-140818`
**Plattform:** Mac (AVFoundation, kein Fokus-Lock)

---

## Fragestellung

Die Schreibtisch-Analyse vom 2026-07-27 kam zu dem Schluss, 14 von 17 kritischen
Artikelpaaren seien im aktuellen Merkmalsraum strukturell untrennbar. Parallel
dazu zeigte das kontrollierte Positionsexperiment mit MESSER-2 einen
positionsabhängigen Messeffekt von ~8,6 mm über die halbe Bildhöhe.

Offen blieb: Ist die schlechte Trennung Folge der Positionsverzerrung, oder liegt
sie am Merkmalsraum selbst?

Der Test eliminiert den Positionsanteil, indem Enrollment und Identifikation am
selben markierten Fixpunkt stattfinden. Was dann noch an Verwechslung übrig
bleibt, geht auf den Merkmalsraum zurück.

---

## Aufbau

- Kalibrierung neu nach Setup-Änderung: `mm_per_px = 0.07974` (+1,67 % gegen den
  Vorlauf), Hintergrund neu aufgenommen
- 40 Artikel in der Sandbox angelegt (15 Löffel, 14 Gabeln, 11 Messer), alle
  länglich klassifiziert (`diameter_mm IS NULL` bei allen 40)
- 15 davon voll eingelernt mit je 12 Shots: **LOEFFEL-1, -2, -3, -5, -6 ·
  GABEL-9, -10, -11, -12, -14 · MESSER-2, -5, -6, -7, -8**
- Auswahl nach engen Größenclustern, nicht zufällig — die vier Messer liegen
  innerhalb von 1,0 mm, die vier kleinen Gabeln innerhalb von 3,6 mm
- Die übrigen 25 Artikel bleiben mit je einem Referenzfoto in der DB und wirken
  als geometry-only-Störer im Kandidatenset
- Zwischen den Enrollment-Shots wurde angehoben und gedreht, die Position blieb
  am Fixpunkt
- Identifikation: je ein Shot pro Artikel am selben Fixpunkt, in Qt bewertet

Kontrollobjekt MESSER-1: 222,0 mm zu Sessionbeginn (2026-07-31), 223,7 mm bei
Sessionende (2026-08-01). Versatz 1,5 mm / 0,7 % über die beiden Sessions.

---

## Ergebnis

| Kennzahl | Wert |
|---|---|
| `accuracy_top1` | 15/15 · 1.00 (Wilson-lo 0.796) |
| `accuracy_top3` | 15/15 · 1.00 |
| `auto_accept_rate` | 5/20 · 0.25 |
| `false_accept_rate` | 0/3 · 0.0 |
| Entscheidungen (n=15) | 3 ACCEPT, 12 AMBIGUOUS, 0 REJECT |

ACCEPT nur bei **MESSER-8, GABEL-9, LOEFFEL-3**.

---

## Befunde

### 1. Das Ranking funktioniert vollständig

Bei allen 15 Artikeln steht der richtige auf Platz 1. Kein einziger Fehlgriff,
auch nicht innerhalb der engsten Cluster. Der Merkmalsraum enthält also die
Information, um die Artikel zu unterscheiden.

Das relativiert die Formulierung „strukturell untrennbar" aus der Analyse vom
2026-07-27. Die Paare sind trennbar genug für ein korrektes Ranking — nur nicht
genug für ein LLR-Margin von 2,0 bei großem Kandidatenset. Das ist ein
Unterschied, der bei der weiteren Arbeit auseinandergehalten werden sollte.

### 2. Der Margin hängt an der Kandidatensetgröße, nicht an der Artikelähnlichkeit

Das ist der zentrale Befund. `margin_vs_setsize` zeigt einen scharfen Abfall:

| Setgröße | Median-Margin |
|---|---|
| 2 | ~309 |
| 4 | ~0 |
| 5 | ~21 |
| 6–13 | ~0–2 |

Die drei ACCEPT-Fälle sind genau die drei mit kleinem Kandidatenset. MESSER-8
(178,7 mm) und GABEL-9 (178,9 mm) bilden ein Zweier-Set; LOEFFEL-3 ebenso. Ihre
Margins liegen bei 285 und 333 — drei Größenordnungen über der Schwelle.

Sobald der Vorfilter mehr als vier Kandidaten durchlässt, fällt der Margin auf
die Gate-Linie. Die Wahrscheinlichkeitsmasse verteilt sich über das Set; der
Abstand zwischen Platz 1 und Platz 2 schrumpft, obwohl Platz 1 unverändert
korrekt bleibt.

**Konsequenz:** Der begrenzende Faktor ist der Vorfilter, nicht das Scoring.
`diameter_tolerance_mm = 6.0` erzeugt bei Artikeln, die 1 mm auseinanderliegen,
Kandidatensets von 12–13. Eine Verschärfung des Vorfilters ist der Hebel, den
dieser Test freilegt — nicht eine Absenkung von `min_llr_margin`. Letzteres wäre
der einzige Schutz gegen `false_accept` und bleibt unangetastet.

### 3. Die Bedränger sind durchweg Größennachbarn

Aus `near_misses`: MESSER-7 → MESSER-5, MESSER-5 → MESSER-7, MESSER-2 → MESSER-7,
MESSER-6 → MESSER-7, GABEL-12 → GABEL-11, GABEL-11 → GABEL-14, GABEL-14 → GABEL-11,
GABEL-10 → GABEL-14, LOEFFEL-1 → LOEFFEL-5, LOEFFEL-2 → LOEFFEL-5,
LOEFFEL-5 → LOEFFEL-2, LOEFFEL-6 → LOEFFEL-1.

Kein einziges gruppenübergreifendes Paar unter den Bedrängern — obwohl MESSER-8
und GABEL-9 nur 0,2 mm auseinanderliegen und MESSER-9/GABEL-8 nur 0,2 mm. Form-
und Farbmerkmale trennen Messer von Gabeln also zuverlässig; sie trennen nur
nicht innerhalb einer Besteckart.

### 4. Kein Drift über die Testsession

`drift` zeigt keinen Trend über die 15 Identifikationen. Die Streuung entspricht
den Artikelgrößen, nicht einer Zeitabhängigkeit.

### 5. Vorfilter tötet keinen richtigen Kandidaten

`prefilter_funnel`: bei allen 15 steht der wahre Artikel auf Rang 1 im Set.
Keine Kills des korrekten Artikels, weder knapp noch weit. Der Vorfilter ist also
zu weit, nicht zu eng.

---

## Einschränkungen

- **n = 1 pro Artikel.** Die Wilson-Untergrenze für `accuracy_top1` liegt bei
  0.796; die Rule-of-Three erlaubt bei 0 Fehlern aus 15 nur die Aussage
  „Fehlerrate < 20 %". Für eine Richtungsaussage reicht das, für eine
  Schwellenentscheidung nicht.
- **`false_accept_rate` auf n=3.** Wilson-Obergrenze 0.56. Die Zahl belegt
  nichts, sie widerspricht nur nichts.
- **Kein Fokus-Lock (Mac).** Die Kameraverbindung brach während der Session
  mehrfach ab; Setup und Hintergrund mussten zwischendurch wiederhergestellt
  werden. Der Fokus ist danach nicht garantiert identisch. Effekt: zusätzliches
  Rauschen, das den Test pessimistischer macht, nicht optimistischer — die
  Befunde 1 und 2 werden dadurch nicht in Frage gestellt.
- **Fixpunkt-Referenzen sind Wegwerf-Referenzen.** `sigma_enroll` enthält keine
  Positionsstreuung. Diese Sandbox darf nicht in den Produktivbestand übernommen
  werden.
- Die Skala dieser Session (`0.07974`) ist mit früheren Sessions nicht direkt
  vergleichbar (+1,67 % nach Setup-Änderung).

---

## Was der Test nicht beantwortet

Systematische Fehler kürzen sich heraus, weil Enrollment und Test dieselbe Optik
benutzen: der ~1,3-%-Skalenversatz, die Markererhöhung, ein Kalibrierfehler.
Der Test ist blind für genau die Fehlerklasse, die in der Optik-Finalisierung
untersucht wird.

Die Gegenrunde — dieselben 15 Artikel bewusst verteilt statt am Fixpunkt — steht
noch aus. Die Differenz beider Runden wäre der quantifizierte Positionsbeitrag.

---

## Nächste Schritte

1. **Gegenrunde verteilt** auf derselben Enrollment-Basis, um den Positionsanteil
   zu beziffern
2. **Wiederholung mit n ≥ 5 pro Artikel**, damit die Quoten belastbar werden
3. **Vorfilter-Analyse:** Wie verhält sich die Setgröße bei
   `diameter_tolerance_mm` von 6,0 / 4,0 / 3,0 — und um wieviel steigt dabei das
   Risiko, den korrekten Artikel zu killen? Nur als Simulation, keine
   Config-Änderung ohne Datengrundlage.
4. **Beitrag der Nicht-Ø-Merkmale prüfen:** ~~`discriminability` legt nahe, dass
   außer Ø und den ΔE-Werten kaum ein Merkmal zur Trennung beiträgt.~~ Falls das
   Bestand hat, ist die Gewichtung neu zu betrachten — mit Simulation vor jeder
   Änderung.

   > **Korrektur 2026-08-01 (nach dem Floor-Key-Fix):** Die durchgestrichene
   > Prämisse beruhte auf der fehlerhaften `discriminability`-Matrix und ist
   > **umgekehrt** richtig. Mit korrektem Floor sind die ΔE-Merkmale die
   > **schwächsten** (Median 1,25–1,59 σ), die Formmerkmale die stärksten. Das
   > deckt sich mit der unabhängig gerechneten Tabelle in
   > [2026-08-01-wprofil-negativbefund.md](2026-08-01-wprofil-negativbefund.md),
   > Abschnitt 2 (solidity 25,87 · diameter 12,88 · circularity 7,86 gegen
   > 1,26–1,72 der Farbmerkmale). Die absoluten Werte unterscheiden sich je nach
   > Grundgesamtheit — die Rangfolge Form ≫ Farbe nicht. Die Frage selbst bleibt
   > offen, nur mit umgekehrtem Vorzeichen: zu prüfen ist der Beitrag der
   > **Farbmerkmale**, nicht der der Nicht-Ø-Merkmale. Siehe
   > [2026-08-01-analysis-floor-key-befund.md](2026-08-01-analysis-floor-key-befund.md).
5. **Wiederholung auf der Windows-Box** mit Fokus-Lock, sobald verfügbar.

---

## NACHTRAG 2026-08-01: MESSER-2 ist ein Duplikat von MESSER-5

**Der Text oben bleibt unverändert.** Dieser Nachtrag korrigiert die
Datengrundlage.

Am 2026-08-01 **am physischen Objekt** festgestellt: MESSER-2 und MESSER-5 sind
dasselbe Besteckteil, beim Sammeln doppelt erfasst. Der Bestand enthielt damit
nicht 15, sondern **14 verschiedene Objekte** — und `accuracy_top1 = 15/15`
zählte einen Artikel doppelt.

Beleg über das Breitenprofil: Prototypen-Abstand 0,25 mm bei 0,278 mm
Shot-Streuung (**d/σ = 0,92**, also unterhalb der eigenen Messstreuung),
identischer Doppelbuckel, Registrier-Restfehler beide 0,71 mm. Der Scan über
alle 780 Artikelpaare findet **kein weiteres** Paar unter d/σ = 1,0 (Details:
[2026-08-01-wprofil-negativbefund.md](2026-08-01-wprofil-negativbefund.md),
Nachtrag Abschnitt 9).

### Wirkung auf die 12 AMBIGUOUS — geringer als erwartet

Nachgerechnet mit `matcher.match()` auf denselben Messwerten, einmal mit 40 und
einmal mit 39 Artikeln (Messwert aus `report.measured`, kein Nachrechnen von
Hand):

| Report | Rang von MESSER-2 | Posterior MESSER-2 | LLR mit | LLR ohne | Entscheidung |
|---|---|---|---|---|---|
| MESSER-2 | 1 (= wahr) | 0,460 | 0,54 | 0,02 | ambiguous → ambiguous |
| MESSER-5 | 3 | 0,254 | 0,14 | 0,14 | ambiguous → ambiguous |
| MESSER-7 | 3 | 0,227 | 0,11 | 0,11 | ambiguous → ambiguous |
| MESSER-6 | 4 | 0,023 | 0,96 | 0,95 | ambiguous → ambiguous |

**Entscheidungswechsel: 0. ACCEPT bleibt 3/15.**

Das Duplikat hat also durchaus Posterior-Masse gezogen (bis 0,254 in einem
fremden Report), aber **keinen einzigen AMBIGUOUS-Fall verursacht.** Grund: die
LLR-Margin ist eine Platz-1-gegen-Platz-2-Größe. MESSER-2 stand in keinem
fremden Report auf Platz 2 — die Bedränger waren dort MESSER-7 bzw. MESSER-5.
Ein Kandidat auf Platz 3 oder 4 verschiebt den Posterior, aber nicht die Margin.

Die Erwartung, zwei der zwölf AMBIGUOUS gingen auf das Duplikat zurück und
kippten ohne es auf ACCEPT, **bestätigt sich nicht.** Die 12 AMBIGUOUS bleiben
in vollem Umfang ein Problem der Score-Aggregation und der engen Größencluster.

### Der Zwilling wird nicht wiedergefunden

Wird die Aufnahme mit Label MESSER-2 gegen die DB ohne MESSER-2 gescort, steht
**nicht** MESSER-5 auf Platz 1:

| Rang | Artikel | log_score | Posterior |
|---|---|---|---|
| 1 | MESSER-7 | −0,5754 | 0,495 |
| 2 | **MESSER-5** (der physische Zwilling) | −0,5916 | 0,487 |
| 3 | MESSER-6 | −3,8704 | 0,018 |

Abstand 0,016 — praktisch ein Gleichstand, aber die falsche Reihenfolge. Das ist
ein eigenständiger Befund: Im Messer-Cluster trennt das Scoring auch dann nicht,
wenn man den Duplikateintrag entfernt. Für die Simulation folgt daraus, dass die
13 Aufnahmen von MESSER-2 **ausgeschlossen** und nicht auf MESSER-5 umetikettiert
werden — eine Umetikettierung würde 13 Top-1-Fehler in die Auswertung tragen.

### Was das für die Kennzahlen oben heißt

- `accuracy_top1 = 15/15` beruht auf 15 Labels über 14 Objekte. Die Aussage
  „Ranking funktioniert" bleibt bestehen (der Duplikateintrag war für seine
  eigene Aufnahme auf Platz 1), aber n ist effektiv 14.
- Befund 2 („Margin hängt an der Kandidatensetgröße") ist **nicht** betroffen —
  die Zweier-Sets von MESSER-8/GABEL-9 und LOEFFEL-3 enthalten kein MESSER-2.
- Befund 3 (Bedränger sind Größennachbarn) bleibt; MESSER-2 → MESSER-7 war
  ohnehin kein Duplikat-Paar.

---

## ZWEITER NACHTRAG 2026-08-01: MESSER-6 ist ebenfalls ein Duplikat

**Der Text oben, einschließlich des ersten Nachtrags, bleibt unverändert.**

Nach physischer Prüfung auch von MESSER-6: **MESSER-2, MESSER-5 und MESSER-6
sind drei Einträge desselben Besteckteils.** Der Bestand dieses Testtags enthielt
damit **13 verschiedene Objekte, nicht 15**.

Der Duplikat-Scan hatte alle drei korrekt als Cluster ausgewiesen (d/σ 0,92 /
1,20 / 1,53), klar abgesetzt vom nächsten Paar bei 2,18. Meine Einordnung von
1,20 und 1,53 als „echte Nachbarn" im ersten Nachtrag war zu eng gewählt; die
Lücke im Histogramm war das eigentliche Signal. Methodik und die Schwelle, die
funktioniert hätte (**d/σ < 2,0**):
[2026-08-01-duplikatpruefung-methode.md](2026-08-01-duplikatpruefung-methode.md).

### Wirkung auf die Kennzahlen dieses Testtags

- `accuracy_top1 = 15/15` beruht auf 15 Labels über **13** Objekte.
- Von den drei ACCEPT betrifft keiner ein Duplikat (MESSER-8, GABEL-9,
  LOEFFEL-3) — die ACCEPT-Quote 3/15 ist unverändert gültig, nur der Nenner
  zählt zwei Objekte doppelt.
- **Befund 2 („Der Hebel ist der Vorfilter") ist widerlegt**, unabhängig von den
  Duplikaten: `k_safe` bricht bei `diameter_tolerance_mm = 4,0` von 166 auf 35
  ein, weil der engere Vorfilter den *wahren* Artikel entfernt und ein falscher
  konkurrenzlos mit Riesen-Margin gewinnt. Siehe
  [2026-08-01-scoring-simulation-widerlegte-thesen.md](2026-08-01-scoring-simulation-widerlegte-thesen.md),
  Abschnitt 3.
- Befund 3 (Bedränger sind Größennachbarn) bleibt bestehen. MESSER-5 ↔ MESSER-7
  ist nach Entfernen beider Duplikate weiterhin das enge Messer-Paar; beide
  Artikel erreichen in der Neurechnung 0 von 13 ACCEPT.

### Das eigentliche Problem bleibt

Die Simulation mit den bereinigten 13 Artikeln ergibt **127 von 169 Fällen
AMBIGUOUS** und ACCEPT unverändert 41. Neun der dreizehn Artikel erreichen kein
einziges ACCEPT. [KORREKTUR 2026-08-01: **acht**, nicht neun — LOEFFEL-1 hat
1/13.] Der künstliche Dreier-Cluster war also **nicht** die Ursache
der AMBIGUOUS-Quote — er hat sie nur mit erklärt.

---

## Offene Punkte am Code, aus dieser Session

- `sandbox_cfg` legt die Zielverzeichnisse nicht an; ein neuer Sandbox-Name
  scheitert an `sqlite3.OperationalError: unable to open database file`.
  Workaround: `mkdir -p` von Hand.
- Kein CLI-Befehl zum Löschen nur der Referenzen eines Artikels. `delete-article`
  entfernt den Artikel mit. Für das anstehende Komplett-Neu-Enrollment wäre
  `delete-references <ARTIKEL>` nötig.
- Der QThread-Segfault (`docs/ui-qt-testsuite-segfault.md`) ist erstmals **im
  Betrieb** aufgetreten, nicht nur in der Testsuite: beim Speichern des
  Enrollments von LOEFFEL-15. Die 12 Shots waren danach nicht in der DB.
- Erste Aufnahme nach Kamerastart ist unscharf und misst dadurch ~1,7 % zu groß
  (isotrop in Länge und Breite). Betraf hier den ersten Anlege-Shot. Eine
  Wartezeit oder Schärfeprüfung vor dem ersten Shot wäre sinnvoll.
- `reference_features.image_path` wird von CLI und Qt inzwischen befüllt; der
  Streamlit-Create-Pfad noch nicht (Phase 2 offen).
