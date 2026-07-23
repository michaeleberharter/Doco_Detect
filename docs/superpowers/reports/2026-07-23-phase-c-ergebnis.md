# Schritt 7 — Metrik-Fix, phase-c-Korpus, mehrklassige Baseline (2026-07-23)

> **Für eine Sitzung ohne Vorkontext.** Dieses Dokument steht für sich. Was
> vorher galt: `docs/2026-07-22-testtag-mac.md` (Ablauf des Testtags),
> `docs/superpowers/reports/2026-07-22-sigma-floors-ergebnis.md` (die
> gemessenen Floors, seither versioniert in `config.yaml`) und im README die
> Abschnitte „Scoring", „Regressions-Korpus" und „Welche Config repliziert
> Tier 2?".

## 0. Was an einem Satz hängen bleibt

Der Korpus ist zum ersten Mal **mehrklassig** (Löffel, Gabeln, Messer statt
nur Löffel), die Regressionskennzahl misst zum ersten Mal **den Matcher statt
das eingefrorene Menschenurteil**, und beide `--check`-Stufen sind grün. Die
teuerste Lehre des Tages ist keine Zahl, sondern ein verlorener Hintergrund.

## 1. Ausgangslage und Ergebnis

Der Korpus wuchs an diesem Abend in zwei Schritten: zuerst die 23
Cross-Tests (phase-c2), dann die **Verdichtung** — 21 weitere bewertete
Auflagen der Messer- und Gabel-Zwillinge (Abschnitt 4.4). Der Endstand:

| | vorher | Zwischenstand | **Endstand** |
|---|---|---|---|
| Korpus | 129, nur LOEFFEL | 152 | **173 Bilder, 3 Sessions, 6 Klassen** |
| Tier-2-Bilder | 60 | 83 | **104** |
| `accuracy_top1` | 46/60 (verdict) | 75/83 | **95/104 = 0,9135** (roh gegen Label) |
| `accuracy_top3` | 59/60 | 81/83 | **102/104 = 0,9808** |
| `auto_accept_rate` | 27/60 | 42/83 | **45/104 = 0,4327** |
| `false_accept_rate` | **0/27** | 0/42 | **0/45** |

Beide Gates grün auf dem Endstand: `corpus-run --tier 1 --check` (173
Bilder, Exit 0) und `--tier 2 --check` (104 Bilder, Exit 0). Finaler
Baseline-Lauf: `20260723-baseline-final`, Verifikation:
`20260723-verifikation-final`, generierte Review:
`reports/corpus/20260723-verifikation-final/index.html`. Abschluss-Batch
über alle 44 bewerteten Cross-Reports: `analyze --run-id cross-mac-final`
(`reports/archive/cross-mac-final/`), ersetzt cross_test_2 als Abschluss.

**Die Fehlbuchungsrate bleibt 0.** Das ist die Invariante, an der der Tag
gemessen wird, und sie hält auf 45 Annahmen bei dreifach größerem
Kandidatenraum — und über die Messer-Zwillinge hinweg, die vier fast
gleich langen Klingen (Abschnitt 4.4).

> **Anmerkung zur Verdichtung.** Der Auftrag nannte 14 Reports (je 2×);
> die Daten zeigen **21** (je 3×). Inhaltlich exakt die genannten Artikel
> (MESSER-2/5/6/7/11, GABEL-3/4), nur eine Auflage mehr je Artikel. Das
> Aufnahmekriterium — „alle bewerteten Reports nach 17:20:25" — ist
> eindeutig und liefert 21; alle tragen ein Verdict. Deshalb Endstand
> 173/104/44 statt der im Auftrag genannten 166/97/37.

## 2. Der Metrik-Semantikwechsel (Abschnitt A)

### 2.1 Was falsch war

`tier2_quotas.accuracy_top1` rechnete über `judgement()`, und das gibt dem
menschlichen `verdict` Vorrang vor dem Label-Vergleich. Ein verdict ist am
Tag der Aufnahme eingefroren: es bleibt „falsch", auch wenn eine spätere
Matcher-Änderung den richtigen Artikel auf Rang 1 hebt. **Als Regressions-Gate
war die Kennzahl blind** — sie konnte eine Verbesserung nicht sehen und eine
Verschlechterung nur dann, wenn sie zufällig mit dem alten Urteil kollidierte.

### 2.2 Was jetzt gilt

`accuracy_top1` und `accuracy_top3` rechnen **roh gegen das Label**, über
dieselbe Grundmenge (alle gelabelten Reports). Die alte Zählung läuft als
`accuracy_top1_verdict` weiter, ist aber **nicht Gate-relevant**
(`report.NUR_INFO`) — eine eingefrorene Zahl kann eine Regression weder
anzeigen noch ausschließen, und ein Gate darauf meldete Sicherheit, die es
nicht geprüft hat.

Nebenwirkung, die man wissen muss: top1 und top3 teilen jetzt einen Nenner.
Vorher war n(top1) die Menge der *beurteilbaren* und n(top3) die der
*gelabelten* Reports — zwei Grundmengen, deren Quoten man nicht nebeneinander
lesen durfte.

Jede geschriebene `baseline.json` trägt `quoten_semantik`. Fehlt die Marke
oder weicht sie ab, meldet `--check` das im Klartext, ohne den Exit-Code zu
drehen: die Bild-Vergleiche sind von der Definition unberührt, aber niemand
soll eine top1-Schranke aus der verdict-Ära für geprüft halten.

### 2.3 Der Beweis, dass es etwas ändert

Die Gegenprobe der phase-c2-Teilmenge (44 Bilder) gegen den `analyze`-Lauf
`cross-mac-final`:

| Kennzahl | Replay | cross-mac-final | |
|---|---|---|---|
| `accuracy_top3` | 43/44 | 43/44 | identisch |
| `auto_accept_rate` | 18/44 | 18/44 | identisch |
| `false_accept_rate` | 0/18 | 0/18 | identisch |
| `accuracy_top1_verdict` | **37/44** | **37/44** | identisch |
| `accuracy_top1` (roh) | **39/44** | — | +2 |

Die Differenz ist **exakt** die zwei GABEL-1-Aufnahmen, bei denen Rang 1
korrekt war und das z-Gate trotzdem verworfen hat. Die neue Kennzahl sieht,
was die alte verschluckte; die alte trifft weiterhin punktgenau die
`analyze`-Zahl (die über `judgement()` aggregiert). Beides zugleich ist genau
das Gewünschte — und es hält auf dem größeren Satz genauso wie auf den ersten
23 (dort war es 19/23 roh vs 17/23 verdict, dieselben zwei Rejects).

### 2.4 Das Ein-Bild-Rätsel der alten 60

Roh 47, verdict 46 — gesucht war das eine Bild mit `top1 == label` bei
Mensch-Urteil „falsch". Es ist **`dbb5f4ea`** (phase-b, LOEFFEL-9):

```
decision: reject   max|z| 3.735 > 3.5   posterior 1.0   Rang 1 = LOEFFEL-9
diameter 1.03  circularity 0.24  solidity 0.35  hu_log 0.27   <- Geometrie perfekt
delta_e_center 3.20  delta_e_rim 2.74  hist_center 2.95  hist_rim 3.74  <- Farbe reißt
```

Die Geometrie sitzt, **alle vier Farbmerkmale** sind hoch. Der Löffel liegt
am rechten Bildrand (Schwerpunkt x = 3359 von 3840). Nachgemessen über alle
47 Treffer: die Korrelation zwischen Randlage und maximalem Farb-z beträgt
**r = 0,71**; außen (>0,6 der halben Bildbreite) liegt der Median bei 2,62,
innen bei 1,07. Das Bild ist mit 0,749 die zweitäußerste Lage im Satz und
trägt den höchsten Farb-z-Wert überhaupt.

**Befund: die Farbmerkmale sind positionsabhängig** (Vignettierung/
Beleuchtungsabfall zum Rand). Das ist kein Scoring-Fehler, aber ein
Randeffekt, der ein korrektes Ergebnis am Gate scheitern lässt. Kein
Handlungsbedarf heute — festgehalten, weil es dieselbe Mechanik ist, die in
Abschnitt 5 wieder auftaucht.

## 3. Der Korpusbau (Abschnitt B)

### 3.1 phase-c2 — aufgenommen, voll Tier 2

23 bewertete Cross-Tests vom 2026-07-23, 17:11–17:20. Sie liefen bereits
gegen die heutige `config.yaml` und die heutige DB, Entstehungs- und
Replay-Zustand sind identisch — der Replay reproduziert sie exakt.
DB-Abgleich 100 %, Bündel mit heutigem Hintergrund, `calibration.json`
(seit 20.07. unverändert) und DB-Snapshot nach dem Gabel/Messer-Enrollment.

### 3.2 phase-c1 — gebaut, geprüft, verworfen

18 bewertete Reports der LOEFFEL-14-Messreihe vom 2026-07-22, geplant als
**Tier-1-only** (Begründung: ihre Entscheidungen entstanden unter den damals
*lokalen* sigma_floors; als Tier-2-Goldens wären sie nur Delta-Lärm gegen
eine Entscheidungsbasis, die es nie wieder gibt — ihr Wert ist die Mess-Serie,
und die ist reine Tier-1-Größe).

**Sie ist nicht korpusfähig.** Der Tier-1-Lauf war eindeutig:

| Session | Bilder | abweichend |
|---|---|---|
| phase-a | 67 | 0 |
| phase-b | 62 | 0 |
| **phase-c1** | **18** | **18** (12 FAIL, 6 DRIFT) |

Über fast alle Felder: `area_mm2`, `mean_hsv`, `hu_moments`, `circularity`,
`solidity`. Die Ursache ist **der Hintergrund vom 22.07., den es nicht mehr
gibt**: `calibration/background.png` wurde am 23.07. um 14:55 für die
Golden-Fixtures neu aufgenommen und hat ihn überschrieben. Ein Backup
existiert nicht.

phase-c1 liegt in `backups/2026-07-23-phase-c1-nicht-korpusfaehig/`, die
18 Reports bleiben als Analyse-Artefakt unter
`reports/analysis/messreihe_l14_2026-07-22/` auswertbar.

**Die Ära-Kennzahl hat das nicht gesehen.** `era_median` (Median-|diff| gegen
Schranke 6) meldete 0 bzw. 1 — grünes Licht bei real 18/18 nicht
reproduzierbaren Messungen. Bei schwarzer Box dominiert die leere Fläche den
Median; Objekt und Umfeld gehen darin unter. Die Kennzahl steht als offener
Punkt (Abschnitt 7).

### 3.3 Zwei Fallen, die beim Bauen aufgingen

**Eingefrorene Bündel wurden still überschrieben.** Die Quellpfade in
`BUNDLE_QUELLEN` zeigen auf *lebende* Dateien: `calibration/background.png`
wechselt bei jedem `capture-background`, `doco_detect.sqlite3` wächst mit
jedem Enrollment. Ein Build vom 23.07. hätte phase-a den heutigen Hintergrund
untergeschoben — die 67 alten Tier-1-Bilder lägen dann gegen eine andere
Segmentierungsgrundlage und der nächste `--check` meldete eine Code-Regression,
die keine ist. `build_corpus` schreibt Bündeldateien jetzt nur noch, wenn sie
fehlen, und meldet Abweichungen laut (`BUENDEL UNVERAENDERT: …`).

**phase-b sammelte weiter.** Seine Quelle war `data/captures` — der Ordner, in
den jede neue Identifikation schreibt. Solange dort nichts lag, fiel es nicht
auf; ab der nächsten Bewertungsrunde hätte der Build frische Reports in
phase-b einsortiert und ihnen dessen Bündel vom 20.07. gegeben. phase-b ist
jetzt geschlossen; neues Material bekommt eine neue Session mit eigenem
Snapshot.

Beides sind Varianten desselben Fehlers: **ein eingefrorener Zustand, der an
einem lebenden Pfad hängt.**

## 4. Cross-Test-Zahlen und Kernbefunde

**44 Identifikationen über zwei Blöcke, alle bewertet.** Der erste Block
(23, 17:11–17:20) war die Klassen-Stichprobe, der zweite (21, 18:19–18:28)
die Zwillings-Verdichtung. `analyze`-Lauf `cross-mac-final`
(veröffentlicht unter `reports/archive/cross-mac-final/`).

| Artikel | richtig/n | | Artikel | richtig/n |
|---|---|---|---|---|
| GABEL-2 | 5/5 | | MESSER-2 | 3/3 |
| MESSER-1 | 4/4 | | MESSER-5 | 2/3 |
| GABEL-1 | 3/5 | | MESSER-6 | 3/3 |
| LOEFFEL-2 | 2/3 | | MESSER-7 | 3/3 |
| LOEFFEL-4 | 2/3 | | MESSER-11 | 3/3 |
| LOEFFEL-14 | 1/3 | | GABEL-3 | 3/3 |
| | | | GABEL-4 | 3/3 |

### 4.1 Klassentrennung: der eigentliche Erfolg des Tages

**0 von 23 Klassenverwechslungen auf Rang 1.** Kein Löffel wurde als Gabel
oder Messer gebucht, in keiner Lage.

Das ist keine Selbstverständlichkeit, denn **15 der 23 Kandidatensets
enthalten klassenfremde Artikel**. Der Geometrie-Vorfilter kann Klassen nicht
trennen — er vergleicht nur die Länge, und ein 213-mm-Messer ist von einer
213-mm-Gabel darin nicht zu unterscheiden. Die Trennung leistet vollständig
das Scoring über Form und Farbe. Genau diese Frage stand im Testtagsplan
(„Wie gut trennt das Scoring längliche Artikel gleicher Länge?"), und die
Antwort ist: sauber.

### 4.2 Alle Fehler sind Zwillinge derselben Klasse

Die 6 Fehlschläge verteilen sich auf zwei Mechaniken, keine davon eine
Fehlbuchung:

- **2× GABEL-1**: Rang 1 korrekt, vom z-Gate verworfen (Abschnitt 5).
- **4× Löffel gegen Löffel**: LOEFFEL-14↔LOEFFEL-11, LOEFFEL-2↔LOEFFEL-6,
  LOEFFEL-4↔LOEFFEL-1 — alle mit Margin ≤ 1,05 und Entscheidung
  `ambiguous`. Kein einziger davon wurde gebucht.

**Die Fisher-Kompression ist sichtbar und arbeitet wie vorhergesagt:** bei
wachsendem Kandidatenset sinken die Margins, mehr Fälle landen auf
`ambiguous`. Das ist Design, nicht Verschlechterung — der Preis dafür, dass
nichts Falsches gebucht wird.

### 4.3 Der Zwei-Gate-Beleg

Die beiden Gates fangen **verschiedene** Fälle. Jedes allein hätte gebucht,
was das andere gestoppt hat:

| | Fall | Margin | max\|z\| | Ausgang |
|---|---|---|---|---|
| z-Gate fängt | GABEL-1, 17:12:14 | **95,03** (extrem eindeutig) | **4,25 > 3,5** | reject |
| Margin-Gate fängt | LOEFFEL-4, 17:20:25 | **1,05 < 2,0** | 2,87 (Gate offen) | ambiguous |

Der GABEL-1-Fall hätte mit der höchsten Margin des ganzen Satzes gebucht
werden können — das z-Gate hat ihn gestoppt. Beim LOEFFEL-4-Fall war das
z-Gate offen, und der wahre Artikel war **nicht einmal im Kandidatenset**
(Vorfilter-Kill); eine Buchung wäre eine Fehlbuchung gewesen — die Margin hat
sie verhindert.

*Korrektur einer Arbeitshypothese:* Der Fall mit hoher Margin und
max|z| ≈ 4,3 ist **nicht** der LOEFFEL-4-Kill, sondern der GABEL-1-Reject.
Der L4-Kill hat eine *niedrige* Margin (1,05). Die beiden Fälle sind
komplementär, nicht identisch.

### 4.4 Die Messer-Zwillinge: das Löffel-Muster auf härterer Stufe

Die Verdichtung (21 Auflagen, je 3× MESSER-2/5/6/7/11 und GABEL-3/4) war
gezielt auf die engste Zwillingsgruppe im Bestand gerichtet: vier fast gleich
lange Klingen (MESSER-2/5/6/7, alle ~213 mm). Ergebnis:

| Artikel | n | ambiguous | accept | Top-1 == Label | Label in Top-3 |
|---|---|---|---|---|---|
| MESSER-2 | 3 | 3 | 0 | 3 | 3 |
| MESSER-5 | 3 | 3 | 0 | 2 | 3 |
| MESSER-6 | 3 | 3 | 0 | 3 | 3 |
| MESSER-7 | 3 | 3 | 0 | 3 | 3 |
| **MESSER-11** | 3 | **0** | **3** | 3 | 3 |
| GABEL-3 | 3 | 3 | 0 | 3 | 3 |
| GABEL-4 | 3 | 3 | 0 | 3 | 3 |

**Das Muster ist exakt das der Löffel, nur enger:** Die vier
213-mm-Zwillinge landen zu 12/12 auf `ambiguous`, keiner wird gebucht, der
Top-1 ist 11/12 korrekt, das Label liegt 12/12 in den Top-3. Der Softmax
teilt sich unter ihnen auf ~0,33/0,32/0,29 — die Margins fallen gegen null.
Der eine „falsche" Fall (MESSER-5, 18:20:41) ist genau so ein Beinahe-
Gleichstand: Margin 0,033, MESSER-7 auf 0,335 vor MESSER-5 auf 0,324, das
wahre Label auf Rang 2. **Keine Fehlbuchung — ambiguous, nicht gebucht.**

**MESSER-11 ist die Kontrollprobe.** Mit ~209 mm ist es kürzer und fällt aus
der Zwillingsgruppe; es trennt sauber und wird 3/3 gebucht. Das zeigt, dass
die `ambiguous`-Häufung der anderen vier kein Kalibrierungsfehler ist,
sondern die ehrliche Antwort auf tatsächlich fast identische Objekte.

Das ist die härteste Bewährung des Scorings an diesem Tag, und der Ausgang ist
der gewünschte: **lieber ein Handgriff mehr (ambiguous) als eine Fehlbuchung.**
Die vier Zwillinge sind zugleich die stärksten Kandidaten für Stufe 2
(DINOv2/FAISS), falls die `ambiguous`-Rate im Betrieb stört — der Hook steht
(`TODO(stage-2)` in `matcher.py`).

## 5. Die GABEL-1-Rejects: Pose, nicht Enrollment

**Diagnose: die Gabel lag auf dem Rücken.** Beide Rejects zeigen die
Rückseite (Zinken nach oben gewölbt, kein Punzenzeichen, Kropf von unten);
alle drei Accepts zeigen die Vorderseite. Zum Vergleich: **alle fünf
GABEL-2-Aufnahmen sind Vorderseite — 5/5 accept.** Der Unterschied zwischen
den beiden Artikeln ist die Auflage, nicht die Qualität.

| Zeit | Entsch. | max\|z\| | Treiber | Ø gemessen |
|---|---|---|---|---|
| 17:11:26 | accept | 1,83 | — | 219,1 mm |
| 17:11:47 | accept | 1,79 | — | 219,5 mm |
| 17:11:58 | accept | 1,27 | — | 219,4 mm |
| 17:12:14 | **reject** | 4,25 | `delta_e_center` (22,3 statt 5–6,6) | 214,0 mm |
| 17:12:33 | **reject** | 4,49 | `solidity` | 216,7 mm |

Die Rückseite reflektiert anders, und die hochgebogenen Zinken verkürzen den
gemessenen Ø um ~5 mm. Echte Out-of-Distribution-Lage. **Das z-Gate hat
getan, wofür es da ist.**

Zwei Hypothesen sind damit widerlegt: es gibt **keine Session-Grenze im
Enrollment** von GABEL-1 (alle 9 Shots am 22.07., 17:26–17:31; GABEL-2
17:33–17:55 — nichts wurde später aufgefüllt), und es gibt **keinen
systematischen Farbversatz** (drei von fünf Auflagen haben Farb-z ≈ 1).

### Methodenlehre

Die Zahlenforensik traf die **Mechanik** — verschiedene Treiber pro Reject,
also kein gemeinsamer Modus, also kein Enrollment-Defekt. Die **Ursache**
fanden erst die Bilder. Aus der Merkmalstabelle allein wäre „delta_e hoch"
als Reflexionsproblem durchgegangen; dass die Gabel schlicht falsch herum
lag, sieht man nur beim Hinsehen. Kennzahlen grenzen ein, Bilder erklären.

### Produktentscheidung: Rückenlage ist nicht buchbar

Bedienregel **„Vorderseite nach oben"**, analog zu „mittig auflegen".
Begründung:

- **REJECT ist der sichere Ausgang.** Ein verworfenes Teil kostet einen
  Handgriff; ein falsch gebuchtes kostet Vertrauen in die Zahlen.
- **Posen-Mischung im Enrollment machte die Referenzen bimodal.** Vorder- und
  Rückseite in einen Merkmalssatz zu werfen bläht `sigma_enroll` auf und
  verwässert genau die Zwillingstrennung, die Abschnitt 4.2/4.4 gerade trägt
  (bei den vier 213-mm-Messern hätte eine bimodale Referenz die ohnehin
  hauchdünnen Margins vollends zerstört).
- **Saubere Pose-Unterstützung wäre Schema-Arbeit** (Pose als eigene
  Dimension neben dem Artikel), nicht ein zusätzlicher Enrollment-Durchgang.

Die finale Entscheidung liegt beim DO&CO-Betriebsablauf — als offener Punkt
dorthin (Abschnitt 7).

Die zwei Reject-Reports bleiben als bewertete Goldens im Korpus und sind im
Manifest als **Rückenlage-Wächter** gekennzeichnet (`notiz`-Feld,
`5bf6b431` und `152de077`): ihr REJECT ist das Soll-Verhalten. Ohne diese
Kennzeichnung liest ein späterer Betrachter sie als Fehlschläge und
„repariert" womöglich das Gate, das hier gerade richtig arbeitet.

## 6. sync-stammdaten: nicht anwenden — die dritte Fundstelle (Abschnitt E2)

**Dies ist die dritte Stelle derselben Fehlerklasse: Diagonale statt Länge
bei länglichen Artikeln.** Die Klasse ist bekannt und wurde zweimal gefunden:
im Vorfilter selbst (Fix vom 2026-07-21) und im Flächen-Check (damals geprüft
und korrekt). Der **Sync-Rechner wurde übersehen** — und er ist die
gefährlichste der drei, weil er als einziger *schreibt*.

**`sync-stammdaten` rechnet gegen eine Größe, die der Vorfilter nicht mehr
benutzt.** `stammdaten.compute_sync` bildet den Nominalwert als
`hypot(width, depth)`; `matcher._nominal_size_mm` nutzt seit dem
Vorfilter-Fix vom 2026-07-21 **`max(width, depth)`** (die Länge). Die
Spaltenüberschrift „was der Vorfilter heute vergleicht" ist damit falsch.

Die Folge ist nicht nur ein Anzeigefehler — **das Vorzeichen kippt**:

| Bezugsgröße | mittlerer Abstand Enroll-Mittel − Nominal |
|---|---|
| `hypot(w,d)` — was das Werkzeug meldet | **−0,86 mm** („Nominale schrumpfen") |
| `max(w,d)` — was der Vorfilter wirklich vergleicht | **+1,15 mm** („Nominale wachsen") |

Ein `--apply` würde die Stammdaten also in die **falsche Richtung** ziehen und
Vorfilter-Kills wahrscheinlicher machen statt seltener.

Nach Klassen, gegen die richtige Bezugsgröße:

| Klasse | n | Mittel | Spanne |
|---|---|---|---|
| MESSER | 11 | −0,50 mm | −1,84 … +0,33 |
| GABEL | 14 | +0,69 mm | −2,58 … +1,90 |
| **LOEFFEL** | 15 | **+2,79 mm** | +0,68 … **+6,02** |

Das ist selbst ein Befund: die „Stadion"-Annahme in `_nominal_size_mm` (bei
länglichem, rundendigem Umriss ist der minEnclosingCircle-Ø gleich der Länge)
hält für **Messer** sehr gut, für **Gabeln** gut und **bricht bei Löffeln** —
die breite Laffe an einem Ende hebt den umschließenden Kreis über die Länge.

Der Nachweis am konkreten Fall, dem LOEFFEL-4-Kill (gemessen 190,42 mm,
Toleranz 6,0 mm):

- Nominal heute 183,21 → Fehler **7,21 mm → KILL**
- nach *korrektem* Sync 186,49 → Fehler **3,93 mm → bleibt im Kandidatenset**

**Empfehlung: `--apply` bleibt gesperrt, bis `stammdaten.py` dieselbe
Nominalfunktion benutzt wie der Matcher.** Danach lohnt der Abgleich
tatsächlich — er hätte den einzigen Vorfilter-Kill des Tages verhindert. Die
Änderung berührt Vorfilter-Verhalten und erzeugt erwarteten Drift, gehört
also in einen eigenen Auftrag mit eigener Freigabe.

## 7. Offene Punkte

**Betriebsablauf DO&CO**
- [ ] **Rückenlage endgültig entscheiden.** Heute: nicht buchbar, Bedienregel
      „Vorderseite nach oben". Wird die Rückenlage im Betrieb gebraucht, ist
      das Schema-Arbeit (Pose als eigene Dimension), kein Enrollment-Nachschlag.

**Code, mit eigener Freigabe**
- [ ] **`stammdaten.py` auf `_nominal_size_mm` umstellen**, dann
      `sync-stammdaten` neu bewerten (Abschnitt 6). Erwarteter Drift.
- [ ] **Session-Artefakte archivieren statt überschreiben** —
      `capture-background` und Kalibrierung müssen den Vorstand mit
      Zeitstempel wegsichern. Dritter Vorfall dieser Art; er hat heute
      18 Bilder gekostet.
- [ ] **Ära-Kennzahl ersetzen** (`era_median`): bei schwarzer Box strukturell
      blind. Kandidaten: hohes Perzentil (P99) statt Median, oder maskierte
      Differenz um die Objektregion. Bis dahin gilt: ihr grünes Licht ist
      kein Beweis — der Beweis ist ein Tier-1-Lauf.

**Beobachten**
- [ ] **hu-Floor nachrechnen, sobald Windows-Sessions vorliegen.** Die
      aktuellen `sigma_floors` stammen aus einer Mac-Messreihe; `hu_log` ist
      der Wert mit der größten Spannweite zwischen den Sessions.
- [ ] **`runs/`-Hygiene.** Jeder volle Testlauf hinterlässt ein Verzeichnis
      ohne `metrics.json`, weil `test_corpus_tier2_decisions_reproduce`
      `run_corpus()` direkt aufruft und `write_run` nie erreicht. Solche
      Ordner gehören nach `runs/_invalid/`.
- [ ] **Farb-Randeffekt** (Abschnitt 2.4, r = 0,71 zwischen Randlage und
      Farb-z). Heute kein Handlungsbedarf; bei künftigen Rand-Rejects die
      erste Hypothese.

## 8. Umgebungs-Fingerprint (Abschnitt D)

Jede `runs/<id>/metrics.json` trägt jetzt einen `env`-Block (Python, numpy,
cv2, scipy, Plattform), und `corpus-report` zeigt ihn je Seite an — inklusive
Warnung, wenn zwei Vergleichsseiten aus verschiedenen Umgebungen stammen.
`requirements.lock` dokumentiert die Versionen der Baseline-Maschine.

Beides ist reine Vorbereitung für **Freitag, die Windows-Eingangsprüfung**:
DRIFT bricht per Default, weil auf gepinnter Umgebung jede Abweichung
code-verursacht ist. Beim Plattformwechsel gilt das nicht mehr, und dann ist
die erste Frage „Code oder Bibliothek?". Ab jetzt steht die Antwort im Lauf
selbst statt in einer nachträglichen Rekonstruktion.

Referenz dieser Baseline: Python 3.9.6, numpy 2.0.2, cv2 5.0.0, scipy 1.13.1,
macOS 15.6 arm64.
