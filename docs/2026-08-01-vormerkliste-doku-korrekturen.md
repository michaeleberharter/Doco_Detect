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

**Nachtrag 2026-08-11 — Datenpunkt aus der 1a-Abnahme des Admin-Panels:**
Produktivbestand laut Status-Seite und `list-articles`: **41 Artikel, 40
eingelernt, 359 Referenzen** — im Schnitt unter 9 Shots je Artikel und damit
unter dem MIN_N=10-Guardrail von `analyze-floors`
(`floor_analysis.py:59`, „unter dieser Stichprobengroesse: Warnung"). Der
Altbestand trägt also im Mittel zu wenige Shots je Artikel für belastbare
Floor-Schätzungen. Stützt die geplante Re-Enrollment-Sequenz mit 12 Shots
(`ui.enroll_shots: 12`). Artikelnummern beziehen sich auf den
Produktivbestand.

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

---

# Nachtrag 2026-08-05 — aus dem Design „Crash-sichere Einlern-Session"

Die folgenden drei Punkte sind beim Entwurf von
[2026-08-05-crashsichere-einlern-session-design.md](superpowers/specs/2026-08-05-crashsichere-einlern-session-design.md)
entstanden und **bewusst aus dessen Umfang herausgehalten** worden. Sie setzen
voraus, dass das Design umgesetzt ist — vorher greifen sie ins Leere.

## 16. Zwei aufruferlose Fassaden nach dem Session-Umbau

**Fundstellen:** `pipeline.save_reference`, `pipeline.save_enrollment` ·
**Aufwand:** ~30 min

Nach der Umstellung des Einlerndialogs auf `commit_enroll_session` hat
**`save_reference` keinen Aufrufer mehr** (heute genau einen:
`save_enrollment`), und **`save_enrollment` keinen Produktivaufrufer** — es
behält Testaufrufer (`test_enrollment_sheet.py:91` und `:217`,
`test_ui_facade.py:239`).

Beide bleiben bewusst stehen, mit datiertem Kommentar an der Definition:
`save_reference` ist die dokumentierte zweite Hälfte der Zwei-Schritt-Fassade
(`pipeline.py:403`), und ein UI, das einzelne Referenzen nachträgt, wäre ein
legitimer künftiger Aufrufer.

**Zusammenlegen oder entfernen ist ein eigener Schritt** — ausdrücklich nicht
im selben Paket, das den Einlernpfad umbaut: das vergrößerte dessen Testfläche
ohne Not. Wer den Punkt aufgreift, prüft zuerst, ob die Testaufrufer auf die
Session-Fassaden umgezogen werden können.

## 17. Doppelte Segmentierung beim Fortsetzen-und-Speichern

**Fundstellen:** `pipeline.remeasure_session`,
`enrollment_sheet.build_enrollment_sheet` · **Aufwand:** ~1–2 h

`remeasure_session` segmentiert beim Fortsetzen alle N Aufnahmen neu (~1 s je
Shot), `build_enrollment_sheet` unmittelbar danach beim Speichern **noch
einmal**. Wer eine unterbrochene Session fortsetzt und direkt speichert, wartet
bei zwölf Shots **rund 24 s statt 12**.

Zusammenlegen hieße, `build_enrollment_sheet` fertige Segmentierungen
entgegennehmen zu lassen — ein Eingriff in eine Konsumentenschicht, bewusst aus
dem Absicherungspaket herausgehalten. Als bekannte Kosten im Design benannt
(Abschnitt 5.2), nicht als Defekt.

## 18. `optik/`-Kopien sind teilweise redundant zum `calibration/`-Archiv

**Fundstellen:** `calibration/` (21 × `background-<ts>.png`, 3 ×
`calibration-<ts>.json` am 2026-08-05), Design Abschnitt 3.2 ·
**Aufwand:** ~20 min Prüfung, danach Entscheidung

Jede Session legt Kopien von `calibration.json` und `background.png` unter
`<session>/optik/` ab, damit der Ausweg „alte Kalibrierung zurückholen" ohne
Suche funktioniert. `capture-background` und `calibrate` **archivieren die
Vorgängerstände aber ohnehin schon** mit Zeitstempel im selben Verzeichnis —
über den gespeicherten Hash wäre der passende Archivstand auffindbar.

Die Kopien sind also nicht die einzige Rettung, sondern die bequeme. Bei
gemessenen 1,26 MB je Session (~52 MB über 40 Artikel) ist der Preis niedrig
und die Entscheidung fiel für die Kopie — **aber die Redundanz ist nie geprüft
worden**: ob das Archiv lückenlos ist, ob es je aufgeräumt wird, und ob eine
Hash-Suche darin verlässlich zum richtigen Stand führt. Wer das prüft, kann die
Kopien danach begründet behalten oder streichen.

## 19. Der Korpus sammelt Zustand über wiederholte Suite-Läufe an

**Fundstellen:** `<corpus_dir>/runs/` (am 2026-08-06: **93 Laufordner**, davon 7
aus einer einzigen Sitzung), `<corpus_dir>/runs/_invalid/` (**19 Einträge**),
`tests/test_corpus.py::test_corpus_tier2_decisions_reproduce` ·
**Aufwand:** offen, zuerst ~30 min Beobachtung

Jeder volle Suite-Lauf legt einen Laufordner an, und
`test_corpus_tier2_decisions_reproduce` hinterlässt zusätzlich einen Eintrag
unter `runs/_invalid/` — es ruft `run_corpus()` direkt auf und erreicht
`write_run` nie (in CLAUDE.md dokumentiert). Über Monate summiert sich das:
93 Ordner, 443 MB.

**Warum es notiert wird:** am 2026-08-06 zeigte ein voller Suite-Lauf **5
Ausfälle**, während dieselbe Codebasis in drei Folgeläufen grün war — beide
Teilmengen einzeln (mit und ohne Korpus-Block) und der vollständige Lauf. Die
Namen der fünf sind verloren (erst durch ein `tail -8` in der Erfassung, dann
durch einen fehlerfreien Diagnoselauf, der `.pytest_cache/.../lastfailed`
leerte). Angesammelter Korpus-Zustand ist ein **plausibler, ungeprüfter**
Kandidat für solche Reihenfolge-Effekte — der andere ist der dokumentierte
Qt-Teardown ([ui-qt-testsuite-segfault.md](ui-qt-testsuite-segfault.md)), der im
selben Zeitraum einen Lauf mit **SIGABRT (Exit 134)** beendete, nachdem alle
737 Tests grün gemeldet waren.

**Nicht verfolgt, bewusst.** Wer es aufgreift: zuerst klären, ob ein Lauf gegen
einen frisch aufgeräumten `runs/`-Stand anders ausgeht als gegen den
gewachsenen. Aufräumen heißt hier **verschieben**, nicht löschen — der Korpus
liegt außerhalb des Repos und ist nicht wiederherstellbar.

**Nachtrag 2026-08-11 (aus dem Entdopplungs-Nachweis):** Der Mechanismus ist
jetzt zeilengenau belegt — `test_corpus_tier2_decisions_reproduce` →
`run_corpus` (auto-`run_id`, `runner.py:405`) → `run_one` schreibt je Bild
ein Replay-JSON nach `runs/<id>/replay/` (`runner.py:306–312`, als
Quoten-Datenquelle gewollt), `write_run` läuft aber nur im CLI-Pfad
(`cli.py:883`). Der Suite-Ordner vom 2026-08-10 enthält entsprechend
`replay/` mit 104 JSONs, ihm fehlt nur `metrics.json` (frühere Meldung
„leer" war falsch). Der Tier-1-Test schreibt keinen Laufordner. Seit der
Korpus-Entdopplung (Deselect per Default, `DOCODETECT_CORPUS_REPRO=1` holt
zurück) entstehen solche Ordner im Normallauf nicht mehr — der Bestand
(19 `_invalid` + die aufgelaufenen metrics-losen) bleibt Gegenstand dieses
Punkts.

**Regel für die nächste Untersuchung, teuer gelernt:** bei einem nicht
reproduzierbaren Suite-Fehler zuerst `.pytest_cache/v/cache/lastfailed`
sichern und die volle Ausgabe in eine Datei schreiben — **bevor** irgendein
weiterer Lauf startet. Ein erfolgreicher Diagnoselauf löscht die Namen, die er
finden soll.

## 21. Test-Configs lenken `paths` um — aber nicht jeden Schlüssel, der einen Pfad enthält

**Fundstellen (vier, in vier Wochen):** `_raeume_nach_backups` gegen
`project_root()` statt `paths.backups_dir` (Schritt 3), `_marker_cfg` in
`test_ui_facade.py` und die fünf `paths`-Blöcke in `test_ui_qt_smoke.py` ohne
`enroll_sessions_dir`/`backups_dir` (Schritt 7), `analysis.output_dir` in
denselben fünf Blöcken (Schritt 7, Punkt 20) · **Aufwand:** ~1 h für einen
Wächter, offen für die Methode

**Das ist ein Muster, kein Einzelfall.** Vier Mal dieselbe Klasse: eine
Test-Config überschreibt `paths.*` unter `tmp_path`, übersieht aber einen
Schlüssel, der ebenfalls einen Pfad trägt — und der Test schreibt in den echten
Projektbaum. Gefunden wurde es jedes Mal **zufällig**, weil etwas auffiel; zwei
der vier Fundstellen sind gitignored (`backups/`, `reports/*`), `git status`
bleibt also sauber und niemand merkt es.

**Warum es zählt:** ein Test, der in den Produktivbaum schreibt, kann bei
ungünstiger Reihenfolge auch Produktivzustand *lesen* — und dann misst er etwas
anderes, als er behauptet. Beim Session-Paket war das jedes Mal harmlos
(Artefakte, keine Überschreibungen), aber das ist Glück, keine Eigenschaft.

**Kandidaten für die nächste Runde**, absteigend nach Nutzen:

1. **Ein autouse-Wächter in `tests/conftest.py`**, der vor und nach jedem Test
   den Projektbaum auf neue Dateien vergleicht und bei einer Abweichung
   fehlschlägt. Findet die Klasse vollständig statt stichprobenartig. Kosten:
   Laufzeit je Test, und die bekannten Ausnahmen (Korpus-Tests schreiben
   absichtlich in `runs/`) müssen erlaubt werden.
2. **Eine gemeinsame `test_cfg(tmp_path)`-Fabrik** statt sechs handgepflegter
   `make_cfg`/`_marker_cfg`/inline-Blöcke. Dann existiert die Umlenkung an
   einer Stelle — dieselbe Begründung wie für `sandbox_cfg` im Produktivcode.
3. Minimal: eine Liste aller Config-Schlüssel, die einen Pfad tragen, plus ein
   Test, der prüft, dass jede Test-Config sie vollständig umlenkt.

**Nicht jetzt verfolgen, nur festhalten** — die nächste Fundstelle findet sich
sonst wieder erst, wenn etwas im Projektbaum landet.

---

## 22. Drei Verfahrensregeln aus Beinahe-Ereignissen — an einer Stelle

**Herkunft:** alle drei aus der Sitzung vom 2026-08-08 (Session-Paket und
Merge-Sequenz) · **Aufwand:** ~15 min, wenn sie nach CLAUDE.md sollen

**Warum überhaupt notiert:** diese drei Regeln stehen sonst verstreut — eine im
Fließtext von Punkt 19, eine in einer Chat-Antwort zu Schritt 7, eine in einer
Meldung von heute. Regeln, die nur dort stehen, wo sie entstanden sind, gelten
genau so lange, wie sich jemand erinnert. Alle drei stammen aus
**Beinahe-Ereignissen**: keines hat Schaden angerichtet, und genau deshalb ist
die Versuchung groß, sie als „ging ja gut" abzuhaken.

**1. Beweise sichern, BEVOR der nächste Lauf startet.** Bei einem nicht
reproduzierbaren Suite-Fehler zuerst `.pytest_cache/v/cache/lastfailed` sichern
und die volle Ausgabe in eine Datei schreiben. Ein erfolgreicher Diagnoselauf
löscht die Namen, die er finden soll. Ausführlich in Punkt 19 — dort steht auch
der Preis: fünf Fehlschlagnamen am 2026-08-06 zweimal verloren, erst durch ein
`tail -8`, dann durch einen grünen Diagnoselauf. Am 2026-08-08 zum ersten Mal
angewandt und sofort wirksam: der Name
`test_variants_jitter_but_measure_same` stand nach dem Fehlschlag fest, statt
geraten werden zu müssen.

**2. Kein `git stash` während laufender Vergleichsläufe.** Wird ein Vergleich
gegen einen anderen Stand gebraucht, gehört er in ein separates Worktree oder
einen Clone. Anlass: bei der Gegenprobe zum Qt-Segfault (Schritt 7 des
Session-Pakets) lag die Arbeit kurzzeitig im Stash, und ein
10-Minuten-Timeout des Vergleichslaufs hätte sie dort unbemerkt liegen lassen.
Sie war wiederherstellbar — Glück, keine Eigenschaft. Ein Worktree kostet
Sekunden und hat kein solches Fenster.

**3. Die Botschaftsdatei schreiben, BEVOR die Botschaft in die Nachricht geht.**
Die Hausregel „Nachricht in eine Temp-Datei, dann `git commit -F`" (CLAUDE.md,
„Umgebungen") gilt sinngemäß für Merges. Am 2026-08-08 wurde der Text einer
Merge-Botschaft in die Chat-Nachricht geschrieben und anschließend eine Datei
referenziert, die nie existierte. **Dass daraus kein Schaden wurde, verdankt
sich `git merge -F`, das bei fehlender Datei abbricht — nicht dem Verfahren.**
Die Korrektur dreht die Reihenfolge um, statt Aufmerksamkeit zu versprechen:
erst die Datei, dann der Text in die Nachricht.

**Der gemeinsame Nenner** ist keine Nachlässigkeit, sondern eine Bauform: alle
drei Regeln schützen einen Zustand, der zwischen zwei Schritten kurz nur an
EINER Stelle existiert — die Fehlschlagnamen im Cache, die Arbeit im Stash, die
Botschaft im Kopf. Wer eine vierte Regel dieser Art findet, gehört hierher.

**Wenn sie nach CLAUDE.md wandern** (eigener Schritt, nicht Teil dieses
Pakets): Regel 1 und 2 zu „Daten & Tests", Regel 3 zu „Umgebungen" neben die
bestehende `-F`-Regel. Ausdrücklich NICHT als vierter Abschnitt „Regeln aus
Fehlern" — verstreute Regeln waren ja das Problem, ein eigener Abschnitt dafür
wäre dasselbe in neu.

---

## 20. ✅ ERLEDIGT 2026-08-08 — Ein Qt-Test schrieb in den echten Projektbaum

> **Behoben in Schritt 7 des Session-Pakets.** Ursache war präziser als hier
> beschrieben: `test_enroll_dialog_demo_flow` lädt die **echte `config.yaml`**
> (`load_config()`) und überschrieb danach nur `paths` und `calibration` —
> `analysis.output_dir` blieb auf dem Produktivwert `reports/analysis`, und
> `persist_enrollment_sheet` schrieb folgerichtig dorthin. Fix: dieselbe
> Umlenkung unter `tmp_path` wie für die Pfade, an allen fünf Stellen im
> Modul. Verifiziert durch Beiseitelegen der Datei und erneuten Lauf: sie
> entsteht nicht wieder.
>
> Die beiden Altbestände (`DEMO-T18.png` von 2026-08-06 und 2026-08-08) liegen
> **verschoben, nicht gelöscht** unter `~/Documents/tmp/`. Der Text unten
> bleibt als Herleitung stehen.

---

### (ursprünglicher Eintrag)

**Fundstelle:** `reports/analysis/enrollment/DEMO-T18.png` (am 2026-08-06 um
20:26 während eines Suite-Laufs entstanden), `pipeline.persist_enrollment_sheet`
→ `analysis.output_dir/enrollment/<artikel>.png` · **Aufwand:** ~20 min

`DEMO-T18` ist ein Demo-Artikel aus `ui_qt/demo_scenes.py` und kommt nur in den
Qt-Tests vor. Ein Smoke-Test fährt den Einlernpfad durch, und
`persist_enrollment_sheet` schreibt gegen ein **nicht umgelenktes**
`analysis.output_dir` — also in den echten Projektbaum. Dort liegt das
Testartefakt seither neben Produktivmaterial:

```
DEMO-T18.png    337 KB   2026-08-06   <- Test
MESSER-2.png    712 KB   2026-07-28   <- echtes Enrollment
LOEFFEL-3.png   628 KB   2026-07-28   <- echtes Enrollment
GABEL-1.png     334 KB   2026-07-28   <- echtes Enrollment
```

**Warum es niemandem auffällt:** `reports/*` ist gitignored (`.gitignore:24`),
`git status` bleibt sauber.

**Vorbestehend, nicht durch das Session-Paket verursacht** — gefunden beim
Nachweis für `paths.backups_dir`, das dieselbe Fehlerklasse im neuen Code
beseitigt hat. Der Fix ist derselbe: die Qt-Test-Config muss
`analysis.output_dir` unter `tmp_path` legen. **Nicht aufgeräumt** — wer es
angeht, entscheidet zuerst, ob `DEMO-T18.png` verschoben oder gelöscht wird
(Dauerregel: verschieben).

---

## 23. Windows-Verifikation Admin-Panel Stufe 4 (Nachtrag 2026-08-12)

**Fundstelle:** Abschlussmeldung Stufe 4 + Teil B1 (Merge `51d7e53`),
Abschnitt „Windows-Verifikationsliste" · **Aufwand:** ~20 min an der Box
· **Gehört auf die Windows-Tagesordnung** (wie Punkt 0).

Stufe 4 ist vollständig gebaut und getestet, aber vier Wege sind am Mac
prinzipbedingt nur mit gestellten Frames/Demo-Quelle prüfbar gewesen:

1. **Segmentierungs-Test mit echtem CameraWorker — WICHTIGSTER PUNKT:**
   der Frame-Kanal (`MainWindow._frame_fuer_admin` →
   `SegTestPage._frame_erhalten`) liefert Frames aus dem
   CameraWorker-Thread; die Zustellung in den GUI-Thread hängt an der
   QueuedConnection auf die gebundene QObject-Methode. Am Mac lief nur
   die GUI-Thread-DemoSource — der Cross-Thread-Weg ist UNGEPRÜFT.
   An der Box: Testaufnahme mit aufgelegtem Objekt, Maske/Overlay/
   Messwerte plausibel, kein Freeze/Crash.
2. **Kamera-Diagnose am DSHOW-Backend:** Backend-Anzeige, Focus-Lock
   „verfügbar", Readback ohne die Mac-Warnung; Geräte-Suche im wirklich
   kamerafreien Zustand (App ohne Kamera gestartet).
3. **Fortsetzen-Delegation im echten READY-Zustand** (Kamera +
   Kalibrierung): Admin → Sessions-Tab → Fortsetzen öffnet den
   Einlern-Dialog auf der gewählten Session. Am Mac nur per
   Fake-Callables belegt.
4. **Verwerfen gegen einen echten Session-Bestand** (Bestätigungsdialog
   mit Pfaden, Sicherung nach `data/verworfen/`). Am Mac nur gegen
   Temp-Bestand getestet.

---

## 24. Drei Zustandstöne ACCEPT / AMBIGUOUS / REJECT (Nachtrag 2026-08-12)

**Fundstelle:** Analysegespräch zum Einstellungsdialog, Entscheidung
2026-08-12 · **Aufwand:** ~halber Tag, davon der grössere Teil Auswahl
und Gegenhören der Töne · **Vorbedingung:** feature/ui-einstellungen
gemergt.

Der Operator schaut aufs Objekt und auf seine Hände, nicht auf den
Schirm. Akustisch unterscheidbare Zustände sparen pro Teil einen
Blickwechsel. REJECT verlangt Handlung und ist selten — der darf
auffallen; ACCEPT ist der häufigste Fall und muss am unauffälligsten
sein.

**Bewusst ausgeklammert aus feature/ui-einstellungen:** der dort
geplante Key `ui/state_sounds` wurde ersatzlos gestrichen und kommt
mit diesem Punkt zurück. Der Schalter gehört auf die bestehende
Dialogseite „Rückmeldung", neben `confirm_sound`.

**Umsetzung:** drei kurze WAVs als gebündelte Assets, gleiche Logik wie
die Plex-OFL-Fonts, Wiedergabe über `QSoundEffect` (QtMultimedia ist im
Wheel, verifiziert 2026-08-12). KEINE zur Laufzeit generierten
Sinustöne — der Nutzen liegt in der Gestaltung, nicht im Code; genau
das war der Grund für die Vertagung.

**Gestaltung (der eigentliche Aufwand):** Unterscheidbarkeit über die
KONTUR, nicht die Tonhöhe — ACCEPT kurzer aufsteigender Zweiklang,
AMBIGUOUS einzelner neutraler Ton, REJECT tiefer absteigend. Wer den
Unterschied nach dem dritten Teil nicht hört, hört ihn auch nach dem
hundertsten nicht. Der Feind ist Nerverei, nicht Unklarheit: bei ein
paar hundert Teilen pro Schicht wird alles leicht Schrille nach zwei
Stunden abgedreht, dann ist das Feature tot. Unter 200 ms, weicher
Einsatz, eher leise.

**Lizenz:** pro Datei prüfen und im Repo notieren. CC0 — CC-BY reicht
nicht ohne Namensnennung.

**Test:** stummer Pfad in CI und Qt-Tests ist Pflicht, sonst hängt oder
rauscht die Suite ohne Audiogerät. Die Suite hat bereits
Teardown-Probleme (`docs/ui-qt-testsuite-segfault.md`) — nicht
draufsatteln.

**Nebennutzen:** beim Testen wird die Zustandsverteilung hörbar. Häuft
sich der AMBIGUOUS-Ton, merkst du das schneller als über jede
Auswertung.

---

## 25. Windows-Verifikation Bildschirmtastatur UND UI-Skalierung (Nachtrag 2026-08-12)

**Fundstelle:** Versionsbefund 2 + Skalierungs-Deckel des Vorgangs
feature/ui-einstellungen (Checkpoints 1/2, 2026-08-12) · **Aufwand:**
~20 min an der Box · **Gehört auf die Windows-Tagesordnung** (wie
Punkt 0 und 23). Beide Prüfungen in DERSELBEN Sitzung.

Der Touch-Modus koppelt die Bildschirmtastatur über
`QT_IM_MODULE=qtvirtualkeyboard` (gesetzt vor der QApplication-Erzeugung,
`settings.env_vorbereiten`). Verifiziert ist das nur am **Mac-Wheel**
(PySide6 6.10.3: `libqtvirtualkeyboardplugin.dylib` lädt, Plugin-Log
geprüft). An der Box prüfen:

1. Windows-Wheel enthält das Plugin
   (`PySide6\plugins\platforminputcontexts\qtvirtualkeyboardplugin.dll`).
2. Mit aktivem Touch-Modus und Neustart: Tastatur erscheint beim Fokus
   auf Artikelname (Einlern-Dialog) und Admin-Passwort, Eingabe kommt an.
3. Ohne Touch-Modus: keine Tastatur, kein Plugin-Fehler im Log.

Fehlt das Plugin im Windows-Wheel: NICHT selbst eine Tastatur bauen
(Auftrag 2026-08-12) — Einschränkung dokumentieren, Touch-Modus bleibt
ohne Tastatur ausgeliefert.

**UI-Skalierung am Windows-Wheel:** per-Monitor-DPI-Awareness und
System-DPI (z.B. 125 %) multiplizieren sich mit `QT_SCALE_FACTOR`; der
Deckel (`settings.env_vorbereiten` gegen die gespeicherte
availableGeometry-Basis) ist am Mac gerechnet und verifiziert. An der
Box zu prüfen: Stufen 100/125/150 bei System-DPI != 100 % — Fenster
passt vollständig auf den Schirm, untere Aktionsleiste erreichbar,
Start-Hinweisbox erscheint bei begrenzter Stufe. Kippt das
Zusammenspiel (doppelte Skalierung), Befund dokumentieren und den
Deckel gegen die dann effektive Basis nachziehen.

---

## 26. Weisser Text auf Zustands-Vollflächen unterschreitet den Kontrast (Nachtrag 2026-08-12)

**Fundstelle:** Kontrastmessung im Zuge von feature/ui-einstellungen
· **Aufwand:** ~2 h · **Bestand aus dem UI-Redesign (Juli), NICHT aus
diesem Vorgang** — preview.py und result_card.py waren dort unangetastet.

Drei Stellen zeichnen Text/Strich hartkodiert in #ffffff auf eine
Zustands-Vollfläche, in beiden Themes identisch: Mess-Chips im
Vorschau-Overlay (preview.py:211-215), Randberührungs-Banner
(preview.py:247-251), Badge-Häkchen (result_card.py:270-276).

Gemessene WCAG-Kontraste, weisser Text auf Vollfläche:
  hell:   ok 4.38 | warn 3.64 | bad 4.77
  dunkel: ok 2.66 | warn 2.17 | bad 3.50
Schwelle: 4.5:1 für normalen Text, 3:1 für grossen/fetten Text und
UI-Elemente. Der dunkle Default ist der schlechteste Fall.

**Lösungsrichtung: Textfarbe pro Theme, NICHT die Token ändern.** Dunkler
Text auf den hellen, gesättigten Dunkel-Theme-Tönen ergibt 7.89 / 9.69 /
6.01, ohne dass ein einziger Farbwert im Token-Set aus design/ui-redesign/
angefasst wird. Im hellen Theme bleibt Weiss richtig; dort ist nur warn
(3.64) knapp — entweder Chip-Text fetten bzw. eine Stufe grösser (dann
gilt die 3:1-Schwelle und es passt), oder den warn-Ton absenken.

**Relevanz:** der Operator unterscheidet drei Zustände über die Farbe,
und es ist der Screen, den er am häufigsten sieht — unter Hallenlicht,
nicht am Schreibtisch.

---

## 27. ✅ ERLEDIGT 2026-08-13 — Zwei Frame-Wartepfade ohne Timeout (Nachtrag 2026-08-12)

> **Umgesetzt auf feature/frame-timeout:** beide Wartestellen
> (`calibrate_dialog.py`, `segtest_page.py`) haben jetzt das
> `_frame_ausgeblieben`-Muster des Einlern-Dialogs samt dessen
> Zeitgrenze (`_FRAME_TIMEOUT_MS`, wiederverwendet statt dupliziert) —
> nach Ablauf Zustandsmeldung, Knopf wieder frei, erneut auslösbar;
> die Hilfetexte (admin-diagnose.md, einrichtung.md) beschreiben das
> neue Verhalten. Der Text unten bleibt als Herleitung stehen.

**Fundstelle:** Sichtung im Zuge von feature/ui-hilfe · **Aufwand:**
klein · eigener Vorgang.

`calibrate_dialog.py:152-158` und `segtest_page.py:106` warten ohne
Timeout auf einen Frame. Stirbt die Kamera nach dem Klick, bleibt der
Zustand („Messe…" / „Warte auf Frame …") stehen; einziger Ausweg ist
Abbrechen. Der Einlern-Dialog löst denselben Fall bereits sauber über
`_frame_ausgeblieben` (`enroll_dialog.py:396-412`) — dort ist das
Muster, das übertragen werden kann. Bis dahin benennt die Hilfe den
Ausweg.

---

## 28. Autostart der Box-Station (Nachtrag 2026-08-12)

**Fundstelle:** Hilfe-Vorgang, Entscheidung Mike 2026-08-12 ·
**Windows-Thema** · eigener Vorgang, gehört zur Windows-Sitzung.

Heute wird die App an der Box von Hand gestartet. Gewünscht ist ein
automatischer Start. Ein Autostart ist erst dann brauchbar, wenn er
auch nach Absturz und Stromausfall ohne Terminal wieder hochkommt —
zu klären sind daher: Aufgabenplanung oder Dienst, Neustart bei
Absturz, Startprotokoll für den Fall, dass die App gar nicht kommt,
und ob der Rechner ohne Anmeldung in die App booten soll (sonst hilft
der Autostart genau im Stromausfall nicht). Erst danach lässt sich
app-startet-nicht.md sinnvoll füllen; bis dahin steht dort die
Von-Hand-Variante.

---

## 29. Einlernen generell hinter das Schloss? (Nachtrag 2026-08-12)

**Fundstelle:** Befund im Hilfe-Vorgang · **offener Entscheid, nicht
vor dem Echtbetrieb.**

Die Abkürzung auf der Kein-Treffer-Karte ist entfernt (28d8d06), der
reguläre Einlern-Knopf in Aktionsleiste und Schiene bleibt offen
erreichbar. Solange nur das Projektteam an der Box steht, ist das
gewollt — ein Passwort bei jedem Testeinlernen wäre teurer als der
Schutz wert. Vor dem Betrieb durch DO&CO-Personal neu entscheiden:
Einlernen ist die Aktion, die den Referenzbestand verändert, und die
Hilfe ordnet sie durchgehend als Technik-Arbeit ein.
