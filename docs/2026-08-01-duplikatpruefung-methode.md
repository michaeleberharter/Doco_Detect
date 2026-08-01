# Duplikatprüfung gehört VOR jede Analyse — Methode und Schwelle

**Datum:** 2026-08-01 · **Art:** Methodenempfehlung aus einem konkreten Vorfall.
Kein Code, keine Config geändert.

> **Kurzfassung:** Vor jeder Auswertung eines neu eingelernten Bestands den
> Profildistanz-Scan laufen lassen. **Alles unter d/σ < 2,0 ist verdächtig und
> gehört physisch geprüft**, bevor gerechnet wird. Zwei Duplikate blieben am
> 2026-08-01 unentdeckt, bis mehrere Analysen bereits auf ihnen aufgebaut hatten.

---

## Der Vorfall

Die Sandbox `neuenroll-2026-08` wurde mit 15 „verschiedenen" Artikeln eingelernt.
Tatsächlich waren es **13**: MESSER-2 und MESSER-6 sind beide dasselbe
Besteckteil wie MESSER-5, beim Sammeln dreifach erfasst.

Die Duplikate wurden erst gefunden, nachdem drei Analysen auf ihnen aufgebaut
hatten:

- Der Fixpunkt-Test meldete `accuracy_top1 = 15/15` über 13 Objekte.
- Der w(s)-Negativbefund erklärte das Trio MESSER-2/5/6 für „im Merkmalsraum
  erschöpft" und stufte es als Kandidat für Stufe 2 ein — für einen Gegenstand,
  der von sich selbst unterschieden werden sollte.
- Die Scoring-Simulation musste zweimal neu gerechnet werden.

Keine dieser Analysen war falsch gerechnet. Sie beantworteten nur teilweise eine
Frage, die es nicht gab.

---

## Die Methode, die beide gefunden hat

Für jeden Artikel wird aus seinen N Enrollment-Shots das Breitenprofil w(s)
berechnet, längennormiert auf ein festes Gitter (u = s/L, 101 Stützstellen), und
daraus ein Prototyp (Mittel über die Shots) gebildet.

Zwei Größen je Artikelpaar:

```
d(A,B)   = RMS über u von |w_A(u) − w_B(u)|          [mm]
sigma(A) = RMS über die Shots von d(w_i, Prototyp_A) [mm]
d/sigma  = d(A,B) / sqrt((sigma(A)² + sigma(B)²) / 2)
```

**Die Kennzahl ist `d/σ`, nicht `d`.** Ein absoluter Abstand sagt nichts, solange
man die eigene Messstreuung nicht kennt: 0,38 mm sind viel für ein Messer und
nichts für einen Löffel. `d/σ < 1` heißt wörtlich: *die beiden Artikel liegen
näher beieinander als zwei Aufnahmen desselben Artikels.* Das kann kein anderes
Objekt sein.

Rechenweg im Bestand: `pipeline.analyze` auf jedes Referenz-PNG (~3–5 s je
4K-Bild), dann `enrollment_sheet._shot_geometry` für die Kontur-Geometrie. Für
40 Artikel mit zusammen ~220 Aufnahmen etwa 15 Minuten — einmalig, ohne Kamera.

---

## Die Schwelle: d/σ < 2,0, und die Lücke lesen

Gemessene Verteilung über alle 780 Artikelpaare des Bestands:

| Paar | d | **d/σ** | tatsächlich |
|---|---|---|---|
| MESSER-2 / MESSER-5 | 0,25 mm | **0,92** | Duplikat |
| MESSER-5 / MESSER-6 | 0,38 mm | **1,20** | Duplikat |
| MESSER-2 / MESSER-6 | 0,48 mm | **1,53** | Duplikat |
| *— Lücke —* | | | |
| MESSER-10 / MESSER-4 | 1,01 mm | 2,18 | verschieden |
| GABEL-2 / GABEL-7 | 1,05 mm | 2,26 | verschieden |
| GABEL-9 / GABEL-13 | 1,16 mm | 2,28 | verschieden |
| LOEFFEL-1 / LOEFFEL-2 | 2,02 mm | 3,36 | verschieden |

**Mein Fehler beim ersten Durchgang:** Ich hatte d/σ ≤ 1,0 als Verdachtsschwelle
gesetzt und damit nur MESSER-2/MESSER-5 gemeldet. Die Paare bei 1,20 und 1,53
habe ich als „sehr nah, aber trennbar" bzw. „echter Nachbar" eingeordnet — und
darauf eine falsche Aussage im Negativbefund gestützt.

**Richtig ist, die Lücke zu lesen, nicht eine Zahl.** Drei Paare unter 1,6,
danach nichts bis 2,18: das ist eine bimodale Verteilung, kein Kontinuum. Die
drei unteren gehören zusammen und sind derselbe Gegenstand.

Als arbeitsfähige Regel:

- **d/σ < 2,0 → physisch prüfen.** Falschalarme kosten einen Blick auf den
  Gegenstand; ein übersehenes Duplikat kostet mehrere Analysen.
- **Zusätzlich immer die sortierte Liste ansehen.** Gibt es eine deutliche Lücke,
  liegt die Trennlinie dort — auch wenn sie über 2,0 fällt.
- **Duplikate treten in Clustern auf, nicht als Einzelpaare.** Sind A/B und B/C
  auffällig, ist A/C es auch. Drei auffällige Paare bedeuten drei Exemplare
  desselben Artikels, nicht drei ähnliche Artikel.

---

## Warum das Profil und nicht die Scoring-Merkmale

Die acht Scoring-Merkmale eignen sich schlecht für diese Prüfung: sie sind
global (Ø, Fläche, Circularity), und zwei verschiedene Besteckteile derselben
Serie unterscheiden sich dort kaum. Das Breitenprofil ist lokalisiert und war in
der Trennschärfe-Matrix mit Abstand das schärfste Maß (Median 16,1 σ gegen
1,3–1,8 σ der Farbmerkmale, siehe
[2026-08-01-wprofil-negativbefund.md](2026-08-01-wprofil-negativbefund.md),
Abschnitt 2).

Das ist die eigentliche Pointe: **w(s) taugt nicht als Scoring-Merkmal, aber
hervorragend als Duplikat-Detektor.** Der Grund ist derselbe in beide
Richtungen — es misst sehr fein, und was es misst, hängt stark von der
Objektposition ab. Für eine Betriebsentscheidung ist das zu wackelig; für den
Vergleich zweier Enrollment-Sätze, die unter identischen Bedingungen entstanden
sind, ist es genau richtig.

---

## Einordnung in den Ablauf

Der Scan gehört **nach dem Einlernen und vor die erste Auswertung**:

```
create-article → Enrollment (N Shots je Artikel)
       ↓
   DUPLIKAT-SCAN  ← hier
       ↓
   physische Prüfung aller Paare mit d/σ < 2,0
       ↓
   Identifikationslauf / analyze / Simulation
```

Er braucht keine Kamera und keine Testaufnahmen, nur die schon gespeicherten
Referenz-PNGs. Voraussetzung ist gesetztes `reference_features.image_path` —
im Qt- und CLI-Pfad gegeben, im Streamlit-Anlegepfad noch nicht.

Der Scan ist heute ein Ad-hoc-Skript. Ob er als CLI-Befehl fest eingebaut wird
(`corpus`-Muster: reine Konsumentenschicht, kein Messpfad), ist eine offene
Entscheidung und nicht Teil dieses Dokuments.

---

## Was das Duplikat tatsächlich gekostet hat

Bemerkenswert und für die Einordnung wichtig: **die Duplikate haben die
Scoring-Kennzahlen kaum verzerrt.**

- Im Fixpunkt-Test änderte das Entfernen von MESSER-2 **null** Entscheidungen;
  ACCEPT blieb 3/15. MESSER-2 war in fremden Reports nie Zweitplatzierter, und
  die LLR-Margin ist eine Platz-1-gegen-Platz-2-Größe.
- Die Simulation über 13 statt 15 Artikel ergibt dasselbe Bild: 127 von 169
  Fällen AMBIGUOUS, ACCEPT 41.

Der Schaden war **inhaltlich, nicht numerisch**: eine falsche Erklärung
(„Merkmalsraum erschöpft") für etwas, das gar kein Merkmalsproblem war, plus
zwei Neuberechnungen. Genau deshalb gehört die Prüfung nach vorn — nicht weil
die Zahlen sonst falsch werden, sondern weil man sonst die falsche Frage
beantwortet.

---

## Verwandte Dokumente

- [2026-08-01-fixpunkt-test-scoring.md](2026-08-01-fixpunkt-test-scoring.md) —
  beide Duplikat-Nachträge und ihre Wirkung auf die Kennzahlen.
- [2026-08-01-wprofil-negativbefund.md](2026-08-01-wprofil-negativbefund.md) —
  Abschnitt 2 (Trennschärfe des Profils), Nachträge 9 und 10.
- [2026-08-01-scoring-simulation-widerlegte-thesen.md](2026-08-01-scoring-simulation-widerlegte-thesen.md) —
  die auf 13 Artikel neu gerechnete Simulation.
