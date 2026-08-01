# Vormerkliste: offene Doku-Korrekturen aus der Bestandsaufnahme

**Datum:** 2026-08-01 · **Art:** Arbeitsliste. Nichts davon ist umgesetzt.

Ergebnis der Bestandsaufnahme aller `docs/`-Dokumente vom 2026-08-01. Die
dringenden Punkte (falsche Aussagen in CLAUDE.md und INDEX, der Ablaufzettel,
der Positionsbefund) sind erledigt und committet. Was hier steht, ist bewusst
**aufgeschoben**, nicht vergessen — jeder Punkt mit Fundstelle, Grund und
Aufwand, damit er ohne erneute Analyse ausführbar ist.

> **Reihenfolge-Hinweis:** Punkt 1 und 2 sind die einzigen, bei denen ein
> Zuwarten Schaden anrichten kann — sie stehen in Dateien, die jede Sitzung
> ungefragt liest bzw. die als Auftragsliste gelesen werden.
>
> **Punkt 0 ist keine Doku-Arbeit, sondern die wertvollste halbe Stunde auf
> dieser Liste** und gehört auf die Windows-Tagesordnung, nicht hierher in die
> Reihenfolge.

---

## 0. PRIORITÄT — Rasterfahrt an der Windows-Box (30 min, beantwortet drei offene Fragen)

**Fundstelle:** [2026-08-01-positionsdrift-messung.md](2026-08-01-positionsdrift-messung.md),
Abschnitte 4 und 7 · **Aufwand:** ~30 min an der Box, plus ~15 min Auswertung
· **Werkzeug existiert:** `scripts/positionsdrift_check.py`

Dasselbe Objekt an **5 × 3 Positionen** über das Feld, je 2–3 Aufnahmen. Eine
halbe Stunde, die gleichzeitig drei Dinge liefert, die heute alle offen sind:

**1. Den gemessenen Betriebs-Floor.** Er entscheidet allein über w(s) — und
sein plausibler Bereich ist heute **0,40–1,41 mm**, umspannt also die
Entscheidungsgrenze von 1,0 mm mit Faktor 3,5 zwischen den Extremen. An
derselben Zahl hängen D7 und D8 (ohne w(s) im Pool fällt D8 auf fünf
Fehlentscheidungen zurück). **Drei der offenen Scoring-Fragen hängen an einer
Größe, die eine halbe Stunde Messung kostet.**

**2. Die Ursache des Gradienten.** Ist er linear (Keystone/Kameraneigung),
radialsymmetrisch (Verzeichnung) oder keins von beidem? Eine Linie kann das
nicht trennen, ein Raster sofort. Davon hängt ab, ob eine Intrinsic-Kalibrierung
oder eine mechanische Korrektur die richtige Antwort ist.

**3. Den unerklärten `lat_p98`-Befund — und der ist neu.** Über die
Positionsleiter fällt die **Breite relativ 2,66× schneller als die Länge**
(−0,0996 gegen −0,0374 % je mm), monoton über alle zwölf Shots, also kein
Rauschen:

| Größe | relative Steigung | über die Leiter |
|---|---|---|
| `ext_full` (Länge) | −0,0374 % je mm | −3,97 % |
| `lat_p98` (Breite) | **−0,0996 % je mm** | **−10,31 %** |

**Eine reine Vergrößerungsänderung würde beide gleich skalieren.** Sie tut es
nicht — der Effekt ist also kein reiner Maßstabsfehler, und keine der
vorliegenden Erklärungen (Keystone, schräge Sicht auf ein Objekt mit Höhe,
positionsabhängige Kantenlage der Segmentierung) ist damit belegt oder
ausgeschlossen.

**Warum das über die Neugier hinausgeht:** `lat_p98` ist heute Diagnose, kein
Scoring-Merkmal — aber es erklärt **72 % der Profildistanz** von w(s)
([w(s)-Negativbefund §5a](2026-08-01-wprofil-negativbefund.md)). Wenn die
Breite dreimal so positionsempfindlich ist wie die Länge, dann ist die
Positionsempfindlichkeit von w(s) **größer als die aus `ext_full` abgeleitete
Floor-Abschätzung unterstellt** — und die ist genau die Zahl, an der die
Absage hängt. Die heutige Abschätzung könnte also nach unten verzerrt sein.
Das ist mit einer Achse nicht entscheidbar.

**Reihenfolge:** vor dem Komplett-Neu-Enrollment, nicht danach. Ergibt das
Raster eine mechanische Ursache, will man sie beheben, bevor 40 Artikel gegen
das schiefe Feld eingelernt werden.

---

## 1. Methodik der Scoring-Runde gehört in CLAUDE.md

**Fundstelle:** [2026-08-01-abschluss-scoring-runde.md](2026-08-01-abschluss-scoring-runde.md),
Abschnitt 3 · **Aufwand:** ~20 min

Drei Werkzeuge haben in einer Runde sechs Scheingewinne entlarvt und stehen
nur in einem Ergebnisdokument, das man erst finden muss:

- **Die Gegenprobe:** äquivalente Baseline-Schwelle + Mengenüberlappung. „Eine
  ACCEPT-Zahl allein ist kein Ergebnis." Sechs von sechs Ansätzen waren
  überwiegend eine verkleidete Senkung von `min_llr_margin`.
- **`k_safe`** statt `false_accept` als entscheidende Kennzahl — FA blieb bei
  n ≈ 13 fast überall 0 und belegt nichts, `k_safe` hat mehr Varianten
  aussortiert als jede andere Zahl.
- **Die Kontrolle mit dem neutralen Element** (C = I, fixierte Reihenfolge,
  Nullmodell). „Jedes Mal war das die Zahl, die den Befund entschieden hat,
  statt ihn plausibel zu machen."

Dazu zwei Merkregeln aus derselben Runde:

- **Auswertungsschicht und Simulation müssen dieselbe Floor-Quelle benutzen**
  ([Floor-Key-Befund](2026-08-01-analysis-floor-key-befund.md)).
- **Bei jeder Korrelations-, Streuungs- oder Trennschärfeaussage zuerst die
  Grundgesamtheit benennen** ([Block A, Abschnitt 0](2026-08-01-blockA-kovarianz.md)).

**Warum es zählt:** Ohne diese Regeln sieht die nächste Runde wieder aus wie
ein Durchbruch. `sum_unweighted` hob ACCEPT von 41 auf 148 — und war zu 96 %
eine Schwellensenkung.

---

## 2. Der Duplikat-Scan gehört als Pflichtschritt in CLAUDE.md

**Fundstellen:** [duplikatpruefung-methode](2026-08-01-duplikatpruefung-methode.md),
[Ablaufzettel Schritt 5](2026-07-31-ablauf-enrollment-session.md),
`scripts/duplikat_scan.py` · **Aufwand:** ~10 min

Im Ablaufzettel steht er, in den Dauerregeln nicht. Ein Bestand, der ohne ihn
ausgewertet wird, beantwortet möglicherweise eine Frage, die es nicht gibt —
am 2026-08-01 waren drei von fünfzehn „Artikeln" dasselbe Messer. Dazu gehört
der zweite Pflichtschritt: **σ_enroll gegen σ_floor je Merkmal** nach jedem
eingelernten Artikel.

---

## 3. `sigma_floors` ist nach Floor-GRUPPE verschlüsselt — das steht nirgends

**Fundstellen:** [architektur.md:132-141](architektur.md) (erklärt `sigma_eff`
ohne die Zuordnung), [sigma-floors-Ergebnis §4](superpowers/reports/2026-07-22-sigma-floors-ergebnis.md)
(listet den YAML-Block ohne Hinweis) · **Aufwand:** ~15 min

`delta_e` bedient `delta_e_center` **und** `delta_e_rim`, `hist_bhattacharyya`
bedient beide Zonen-Histogramme. Die Zuordnung lebt allein in
`matcher._FLOOR_KEY`. Genau diese Lücke hat den Floor-Key-Fehler erzeugt.

**Vorsicht:** `architektur.md` wird derzeit von der Streamlit-Entfernung
angefasst — erst danach.

---

## 4. „14 von 17 Paaren strukturell untrennbar" ist überholt

**Fundstelle:** [2026-07-27-scoring-analyse.md:10-11](2026-07-27-scoring-analyse.md)
und Abschnitt 4 · **Aufwand:** ~20 min

Der Historisch-Vorbehalt oben entwertet ausdrücklich nur die **Zahlen** und
lässt die „strukturellen Befunde" gelten — dieser gehört dazu. Der
Fixpunkt-Test zeigt 168/169 Top-1 korrekt: die Paare sind trennbar genug für
ein korrektes Ranking, nur nicht für ein Margin von 2,0 bei großem
Kandidatenset. Das ist ein anderer Befund an anderer Stelle (Aggregation und
Gate statt Merkmalsraum).

Dazu gehört, dass mindestens ein Teil der damals „untrennbaren" Paare
(MESSER-2/5/6 untereinander) **nie ein Merkmalsproblem** war, sondern ein
Duplikat — siehe Punkt 5.

---

## 5. Die Messer-Vierlinge waren vermutlich zwei Objekte

**Fundstellen:** [phase-c-Ergebnis §4.4](superpowers/reports/2026-07-23-phase-c-ergebnis.md)
(„die vier Zwillinge sind die stärksten Kandidaten für Stufe 2"),
[Schwellen-Sweep §7](superpowers/reports/2026-07-24-schwellen-sweep-ergebnis.md)
(„Alias-Gruppe würde ~5,5 Prozentpunkte bringen · Frage an DO&CO") ·
**Aufwand:** ~30 min, aber siehe Vorbehalt

Im Sandbox-Bestand sind MESSER-2, -5 und -6 physisch geprüft **ein** Messer.
Die Stammdaten sprechen dafür, dass es dieselben DB-Einträge sind: die
Sandbox-Längen (214,2 / 213,6 / 213,4 / 214,4 mm plus MESSER-11 bei 208,8)
reproduzieren das phase-c-Bild (~213-mm-Vierling + ~209-mm-Kontrollprobe)
exakt.

**Vorbehalt, der die Sache offen hält:** Ob die Produktiv-Einträge dieselben
physischen Objekte sind, ist **nicht geprüft** — und mit dem Altbestand auch
nicht prüfbar (Punkt 6). Solange das offen ist, kann der Eintrag nur als
begründeter Verdacht markiert werden, nicht als Korrektur. Die
Stufe-2-Empfehlung und die DO&CO-Frage sollten aber **nicht weiter zitiert
werden**, ohne den Verdacht danebenzustellen.

---

## 6. Der Duplikat-Scan ist auf dem Produktivbestand nicht fahrbar

**Fundstelle:** [reference-stats-Dokument](2026-07-31-reference-stats-keine-sessions.md)
(334 von 359 `reference_features`-Zeilen mit `image_path IS NULL`) ·
**Aufwand:** entfällt — es ist ein Befund, keine Korrektur

Der Scan braucht die gespeicherten Referenz-PNGs. Damit ist die naheliegendste
Folgefrage aus Punkt 5 — *trägt der Produktivbestand dieselben Duplikate?* —
mit vorhandenen Mitteln **nicht beantwortbar**. Das Skript meldet den Zustand
als „SCAN NICHT FAHRBAR".

**Das ist ein Argument mehr für das Komplett-Neu-Enrollment**, und es gehört
dort notiert, wo über dessen Umfang entschieden wird.

---

## 7. Artikelnummern-Namensraum ist nirgends festgehalten

**Aufwand:** ~15 min

Kein Dokument sagt, ob `MESSER-5` in der Sandbox `neuenroll-2026-08` derselbe
Gegenstand ist wie `MESSER-5` in der Produktiv-DB. Jede dokumentübergreifende
Aussage unterstellt es stillschweigend. Ein Satz je Dokument — „Artikelnummern
beziehen sich auf Bestand X" — kostet nichts und verhindert die nächste
Fehlzuordnung. In CLAUDE.md ist die Regel seit heute für LOEFFEL-3 notiert;
die Dokumente selbst tragen sie noch nicht.

---

## 8. Widerlegte Aussagen stehen unmarkiert im Fließtext

**Aufwand:** ~20 min

Die Methode „Originaltext bleibt stehen, Korrektur im Nachtrag" ist richtig,
erzeugt aber Stellen, an denen der Fließtext das Gegenteil des Ergebnisses
sagt. Wer über Suche oder INDEX dorthin springt, liest die widerlegte Fassung.
Ein Ein-Zeilen-Marker am Absatz („→ korrigiert in Nachtrag X") schließt das,
ohne die Historie zu zerstören:

| Fundstelle | Aussage | widerlegt in |
|---|---|---|
| [w(s) §3b](2026-08-01-wprofil-negativbefund.md) | „MESSER-2/5/6 sind auch im Profil entartet … Kandidat für Stufe 2" | Nachtrag §10 |
| [w(s) §9](2026-08-01-wprofil-negativbefund.md) | „MESSER-6 ist ein echter Nachbar, kein Duplikat" | Nachtrag §10 |
| [w(s) §7](2026-08-01-wprofil-negativbefund.md) | „0 ab Floor 1,0 mm" als Begründung | Nachtrag §11 |
| [Fixpunkt Befund 2](2026-08-01-fixpunkt-test-scoring.md) | „Der Hebel ist der Vorfilter" | 2. Nachtrag + Simulation §3 |

---

## 9. Der hu_log-Floor: „prüfen, ob er enger gefasst werden kann" ist negativ beantwortet

**Fundstelle:** [sigma-floors-Ergebnis §8, Offener Punkt 1](superpowers/reports/2026-07-22-sigma-floors-ergebnis.md)
· **Aufwand:** ~10 min

Dort steht als Auftrag: nach den phase-c-/Windows-Sessions prüfen, ob der Floor
0,38 wieder enger gefasst werden kann. Drei heutige Befunde sprechen dagegen —
Floors senken tauscht AMBIGUOUS gegen REJECT und kostet `k_safe`
([Simulation §5](2026-08-01-scoring-simulation-widerlegte-thesen.md)); bei
`hu_log` überschreiten 6 von 13 Artikeln den Floor mit ihrer eigenen
Enrollment-Streuung ([enrollment-streuung §4](2026-08-01-enrollment-streuung-bedraenger.md));
die Distanzverteilung ist schwerschwänzig ([Block D, D0](2026-08-01-blockD-sigma-eff.md)).

Als **auf dieser Datenbasis negativ beantwortet** markieren, sonst greift ihn
die nächste Sitzung als offenen Auftrag auf.

---

## 10. Der QThread-Segfault ist im Betrieb aufgetreten

**Fundstelle:** [ui-qt-testsuite-segfault.md](ui-qt-testsuite-segfault.md) ·
**Aufwand:** ~10 min für den Nachtrag

Das Dokument endet mit „Datenpunkt 2026-07-31" (voller Lauf ohne Segfault) und
behandelt das Thema als Testsuite-Eigenheit. Am 2026-08-01 ist es **im
Betrieb** aufgetreten: beim Speichern des Enrollments von LOEFFEL-15, und
**die 12 Shots waren danach nicht in der DB**
([Fixpunkt, offene Punkte](2026-08-01-fixpunkt-test-scoring.md)). Datenverlust
beim Einlernen gehört in das Dokument, das den Titel trägt.

---

## 11. Der Arbeitsplan ist kein Fahrplan mehr

**Fundstellen:** [arbeitsplan-2026-07-24.md](arbeitsplan-2026-07-24.md),
[INDEX](INDEX.md) („der lebende Fahrplan") · **Aufwand:** ~15 min

Block 1.2 erledigt, Block 2 erledigt, Block 3 („würde ein width_mm-Merkmal die
Zwillings-Margins heben?") durch den w(s)-Negativbefund und D7 beantwortet,
Block 4 teilweise erledigt. Live ist allein Block 5 (Windows-Tag). Dazu ist das
Stufe-2-Kriterium unter „Explizit NICHT jetzt" von beiden Seiten überholt: das
Messer-Cluster war ein Duplikat, dafür stehen heute 127/169 AMBIGUOUS und acht
von dreizehn Artikeln ohne ein einziges ACCEPT.

Entweder als historisch markieren und Block 5 herausziehen, oder neu schreiben.

---

## 12. INDEX-Umbau: Status-Achse statt reiner Chronologie

**Aufwand:** ~1–2 h

Zwölf Einträge an einem Tag aus **einer** Runde, inhaltlich aneinanderhängend
und mit stark verschiedenem Status (Entscheidung / Methode / Befund / gefixter
Bug), lesen sich chronologisch wie zwölf gleichrangige Tagesereignisse. Der
wichtigste Einstiegspunkt (der Abschlussbericht) steht an vorletzter Stelle.

Vorgeschlagene Gliederung, Chronik bleibt als Rohliste darunter:

```
## Gültige Regeln und Methoden
## Entschiedene Fragen — nicht neu aufmachen   (je: Frage, Antwort, Bedingung für Wiederaufnahme)
## Offen / Wiederaufnahme nach der Windows-Box
## Befunde am Code (Status: offen / gefixt am …)
## Chronik (je eine Zeile)
```

Zwei Regeln, die den Zerfall verhindern: **ein Eintrag = eine Zeile** (die
heutigen Fünfzeiler veralten getrennt vom Dokument — genau so entstand die
falsche sync-stammdaten-Zeile), und **jeder Eintrag trägt einen Status**.

**Beim Umbau mit aufnehmen:**
[2026-07-28-messpfad-aufgeschoben.md](2026-07-28-messpfad-aufgeschoben.md)
steht in **keinem** INDEX-Eintrag — es ist nur aus CLAUDE.md verlinkt.

---

## 13. Streamlit-Restpunkte — nach Abschluss der Entfernung aufgestellt

**Stand:** Entfernung abgeschlossen (`07586b5`, `70ca30c`, Suite grün).
**Aufwand gesamt:** ~30 min

**Die Entfernung selbst ist sauber.** `app.py`, `pages/`, `ui_common.py` und
`requirements-ui.txt` sind weg; `README.md` hat einen Abschnitt „Die
Streamlit-Test-UI wurde entfernt" mit Ersatzpfaden; `architektur.md` beschreibt
jetzt die Qt-UI und markiert Streamlit als entfernt; die beiden 08-01-Dokumente
([duplikatpruefung](2026-08-01-duplikatpruefung-methode.md),
[Fixpunkt](2026-08-01-fixpunkt-test-scoring.md)) haben datierte Nachträge. Die
verbliebenen Erwähnungen in `cli.py`, `display.py` und `neural_seg.py` sind
historische Kommentare und richtig so.

Es blieben vier Kleinigkeiten. **Drei davon sind am 2026-08-01 erledigt:**

- ✅ **a)** `docs/architektur.md` trug die Überschrift `# CLAUDE.md` — ein Rest
  aus der Zeit, als die Datei dort herausgelöst wurde. Jetzt „Architektur", mit
  Abgrenzung zu CLAUDE.md und README und einer Notiz, woher die alte
  Überschrift kam.
- ✅ **b)** `PLAN_UI_QT.md` beschrieb Streamlit als lebend **und als
  Randbedingung** („bleibt unangetastet", „unverändert lauffähig", „Kein
  Streamlit-Code kopieren"). Datierter Kopf-Marker gesetzt, Inhalt unangetastet
  — historische Dokumente rückwirkend zu ändern macht sie unzuverlässig.
- ✅ **c)** [Plan](superpowers/plans/2026-07-20-multi-candidate-decision-ui.md)
  und [Spec](superpowers/specs/2026-07-20-multi-candidate-decision-ui-design.md)
  zur Streamlit-Entscheidungs-UI: datierte Marker, Inhalt unangetastet. Bei der
  Spec mit dem ausdrücklichen Zusatz, dass ihre Layout-Entscheidungen Beleg
  einer Abwägung sind, keine geltende Vorgabe.

**Offen — d) `--shots 8` gegen den Default 12** (`fc656ba`,
`config.yaml: enroll_shots: 12`): in `docs/architektur.md` **korrigiert**, in
**`README.md`** (Zeile ~382, Beispielblock) **noch nicht**. Grund: die Datei
trug beim Bearbeiten uncommittete Fremdarbeit (Konsolen-Entrypoints, die auf
ein noch nicht committetes `pyproject.toml` verweisen). Ein Commit hätte diese
Änderung mitgenommen und damit ein Feature dokumentiert, dessen Code nicht im
Repo ist. Nachzuziehen, sobald `README.md` frei ist. *(~2 min)*

---

## 14. — verschoben nach Punkt 0

Die Rasterfahrt stand hier zunächst als Nebenpunkt. Sie steht jetzt als
**Punkt 0** ganz oben: eine halbe Stunde, die den gemessenen Betriebs-Floor,
die Ursache des Gradienten und den offenen `lat_p98`-Befund zugleich
beantwortet.

---

## 15. Drei Skalenabweichungen gleicher Größe, nie zusammengeführt

**Aufwand:** ~30 min Analyse, kein Doku-Punkt

| Zahl | Fundstelle | Deutung dort |
|---|---|---|
| ~1,3 % Ära-Drift zwischen Sessions | [stammdaten-sync §6b](superpowers/reports/2026-07-24-stammdaten-sync-ergebnis.md) | nicht nachgeführte Kalibrierung (Zweig K) |
| +1,67 % nach Setup-Änderung | [Fixpunkt, Aufbau](2026-08-01-fixpunkt-test-scoring.md) | nur als Vergleichbarkeits-Vorbehalt notiert |
| ~1,7 % erste Aufnahme nach Kamerastart (unscharf) | [Fixpunkt, offene Punkte](2026-08-01-fixpunkt-test-scoring.md) | Einzeiler |
| ~4 % über die Positionsleiter | [Positionsdrift](2026-08-01-positionsdrift-messung.md) | gemessen |

Vier isotrope Skalenfehler ähnlicher Größenordnung in vier Dokumenten. Der
dritte betrifft den **Anlege-Shot** — also genau den Wert, der als
`articles.width_mm` das Vorfilter-Nominal wird. Ob sie denselben Ursprung
haben, hat niemand geprüft.
