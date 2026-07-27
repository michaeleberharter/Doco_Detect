# Scoring-Analyse Besteck-Verwechslung (2026-07-27)

Analyseserie zur Frage, warum baugleiche Löffel/Messer in Stufe 1 nicht
sauber getrennt werden. Ergebnis vorweg, damit niemand dieselben
Stellschrauben erneut durchprobiert: **Die Konfiguration bleibt unverändert.**
Kein sigma_floor, kein Gewicht, kein alpha, keine Toleranz und kein
zusätzliches Gate verbessert die Trennung, ohne an anderer Stelle einen
Falschakzept oder mehr verlorene korrekte Buchungen zu erzeugen. Die Ursache
liegt **außerhalb des Scorings**: der wahre Artikel wird in den Fehlfällen
systematisch zu klein gemessen, und 14 von 17 kritischen Artikelpaaren sind im
vorhandenen Merkmalsraum überhaupt nicht trennbar. Diese Datei hält fest, was
mit welchen Zahlen geprüft und warum es verworfen wurde.

Alle Zahlen entstammen einer rein rechnerischen Auswertung der gespeicherten
MatchReport-JSONs (kein Eingriff in Messpfad, Config, Reports oder Goldens).
Die Rohtabellen lagen zum Analysezeitpunkt unter `/tmp/` (flüchtig); die hier
wichtigen sind unten eingebettet.

---

## 1. Ausgangsfrage und Ergebnis

Warum landen ähnliche Löffel in AMBIGUOUS statt getrennt zu werden, und
lässt sich das über die Stufe-1-Parameter beheben? Antwort: nein. Jede
einzelne Stellschraube ist einzeln plausibel und scheitert an den Zahlen —
entweder erzeugt sie einen Falschakzept, oder sie kostet mehr korrekte
Accepts als sie gewinnt. Das Falschakzept-Risiko sitzt konzentriert bei den
Fällen, in denen der Vorfilter den wahren Artikel vorher aus dem
Kandidatenset entfernt hat; dort misst die LLR-Margin nur noch, wie klar ein
falscher Kandidat gegen einen anderen falschen gewinnt. Die Konfiguration
bleibt, die Arbeit muss an Messung/Vorfilter/Merkmalsraum ansetzen.

---

## 2. Datenbasis

Ausgewertet wurde der Tier-2-Korpus (Sessions **phase-b** und **phase-c2**),
dedupliziert **105 Reports** (die 18 doppelten `data/captures`-AMBIGUOUS sind
namensgleich zu Tier-2). Verteilung: **58 AMBIGUOUS, 43 ACCEPT, 4 REJECT**;
104 Reports tragen einen eingelernten Artikel. Von den **21 Reports mit
verdict=wrong** sind:

- **12 echte Rang-Fehler** (wahrer Artikel im Kandidatenset, aber nicht Rang 1),
- **6 Vorfilter-Kills** (wahrer Artikel gar nicht im Set, an der Ø-Toleranz
  ausgesiebt),
- **3 REJECTs** mit top1==label (am z-Gate abgelehnt, kein Ranking-Fehler).

Alle 58 AMBIGUOUS sind Besteck-gegen-Besteck. Alle 43 ACCEPT tragen
verdict=correct — es gibt im Bestand **keinen** realen Falschakzept; die
LLR-Margin (min_llr_margin = 2.0) hält sie draußen.

**Stammdaten-Drift (Vorbehalt).** Die report-zeitlichen Nominalwerte
(`nominal_size_mm` aus den Kandidaten) driften zwischen den Sessions um ~4 mm
(z. B. LOEFFEL-4: phase-b 186.94, phase-c2 183.21), und die heute
ausgelieferten Bundle-DBs sind **post-sync** (`sync-stammdaten --apply`,
hypot→max-Fix, 2026-07-24) und reproduzieren die Report-Kandidatensets
**nicht** mehr. Betroffen waren die Vorfilter-Analysen (welche Artikel im Set
sind, warum der wahre Artikel fehlt): jede DB-basierte Reproduktion führt in
die Irre, es müssen die **report-zeitlichen** Nominale aus den Kandidaten-
Vorkommen derselben Session verwendet werden. Die Scoring-Analysen (llr,
max_z, Merkmals-z) sind nicht betroffen — sie rechnen aus den im Report
gespeicherten Werten, und die Rekonstruktion reproduziert den Ist-Zustand
exakt (Kontrolle S0/α=2 bitgenau).

---

## 3. Geprüft und abgelehnt — je Stellschraube ein Absatz

**sigma_floors senken (C3).** Setzt man jeden Floor auf den empirischen
Median der n=9-Enrollment-Serien (Verhältnis 0.39–0.85 der aktuellen Werte),
steigt die AMBIGUOUS-Margin-Median von 0.23 auf 0.80 und drei AMBIGUOUS
überschreiten 2.0 als **wrong** — und zwar exakt drei Vorfilter-Kill-Fälle
(1784562435798 LOEFFEL-3→LOEFFEL-4, 1784820020752 LOEFFEL-4→LOEFFEL-1,
1784562412154 LOEFFEL-2→LOEFFEL-5), die mit passiertem z-Gate auto-gebucht
würden. Gleichzeitig verlieren vier korrekte ACCEPTs ihren Status am z-Gate
(kleinerer Floor → größeres z > 3.5). Umgekehrt kostet ein Anheben auf 200 %
sieben korrekte ACCEPTs an der Margin. Die Config sitzt zwischen zwei
Kipppunkten. Abgelehnt: jede Richtung erzeugt Falschakzepte oder Verluste.

**Globalgewichte umverteilen (D; S1: Ø 0.5→0.25, solidity 0.06→0.25; S2: Ø
0.20, solidity 0.30, circularity 0.10).** Beide Szenarien erzeugen **0
Falschakzepte** (harte Randbedingung bestanden), gewinnen aber netto nur +3
bzw. +4 korrekte Accepts und verlieren dabei 1 bzw. 2 andere korrekte Accepts
an der Margin. Von den 17 kritischen Paaren lösen nur **zwei** auf
(LOEFFEL-12/LOEFFEL-4, MESSER-6/MESSER-7, beide solidity-separierbar), während
drei sich **verschlechtern** (LOEFFEL-15/LOEFFEL-9, MESSER-5/MESSER-7,
LOEFFEL-2/LOEFFEL-5), weil sie über Ø/hu trennen, die heruntergewichtet
werden. Es ist ein Nullsummenspiel zwischen Paartypen. Das dritte Szenario
S3 (aspect_ratio als gescortes Merkmal, Gewicht 0.15) ist **nicht
simulierbar**: aspect_ratio ist in `reference_stats` nicht als Skalar geführt
(kein sigma_enroll) und hat keinen sigma_floor — es wurde nicht geschätzt.

**Fisher-alpha erhöhen (E; α ∈ {0,1,2,4,8,16,32}).** Kein einzelnes α ist
disqualifiziert (0 Falschakzepte über den ganzen Sweep). α hoch gewinnt bis
+5 korrekte AMBIGUOUS (α=32: netto +4), α=0 (keine Adaption) verlöre dagegen
8 korrekte ACCEPTs — die Adaption ist tragend, α=2 bleibt sinnvoll. Der Preis
höherer α ist Instabilität: die w_eff-Streuung zwischen Reports desselben
Paars wächst monoton, und ein Leave-one-out (schwächsten Kandidaten
entfernen, Fisher neu) verschiebt die Margin bei α≥16 im Maximum um bis zu
~1.25 — die Entscheidung hängt dann spürbar vom zufälligen Kandidatenset ab.
Abgelehnt: höhere α kaufen wenige Gewinne mit wachsender Zufallsabhängigkeit.

**alpha und Gewichte kombiniert (E5).** Das beste nicht-disqualifizierte α
(32) mit den S2-Gewichten kombiniert erzeugt **einen** Falschakzept, den
keine der beiden Änderungen allein hatte: Fall 1784562412154, wahr LOEFFEL-2,
akzeptiert LOEFFEL-5 bei llr 2.01 (S2 allein 1.33, α=32 allein 0.30). Die
Effekte verstärken sich; **Kombinationen sind nicht additiv sicher**. Abgelehnt.

**Vorfilter-Toleranz weiten (C5/F).** Die sechs Kill-Fälle bräuchten eine
Ø-Toleranz von 6.02–8.41 mm statt 6.0. Weitet man so weit, holt man die
wahren Artikel zwar ins Set — aber genau diese Fälle tauchen dann eine Stufe
später als Falschakzepte wieder auf (siehe C3/E5, es sind dieselben Kill-
Lookalikes). Korpusweit bleibt der Median-Zuwachs an Kandidaten bis T≈8 bei
+0; die sync-Simulation vergrößert die Sets im Mittel um +1.49. Abgelehnt:
verlagert das Problem, löst es nicht.

**Schattenkandidaten-Gate (F2/F3).** Ein Gate, das einen ACCEPT herabstuft,
sobald ein Artikel knapp außerhalb der Toleranz (im „Schattenband" 6.0 < geo
≤ B) liegt, erfasst alle sechs Kills erst bei **B = 8.5** — kostet dort aber
**21 der 43 correct-ACCEPT** einen Schattenkandidaten und damit den
Auto-Buchungsstatus (schon die reine Baseline mit Gate verliert 21). Das Gate
ist indiskriminant, weil bei baugleichem Besteck praktisch immer ein anderes
Exemplar im Band liegt. Es neutralisiert zwar formal den α32/S2-Falschakzept,
zu einem Netto von −22. Abgelehnt.

---

## 4. Der strukturelle Befund

Das Falschakzept-Risiko sitzt **konzentriert bei den Vorfilter-Kill-Fällen.**
Fehlt der wahre Artikel im Set, misst die Margin nur noch, wie klar ein
falscher Kandidat A gegen einen falschen B gewinnt — jede Scoring-„Verbesserung"
(kleinere Floors, mehr Gewicht auf trennende Merkmale, höheres α) macht das
Votum dort *sicherer falsch*. Über alle Simulationen hinweg gab es **keinen
einzigen Falschakzept, der kein Kill-Fall war.** Das ist der Kernbefund:
Scoring-Parameter können das Fehlbuchungsrisiko nicht senken, weil es nicht im
Scoring entsteht, sondern im Vorfilter/der Messung davor.

Das Oberschranken-Experiment (H3) trennt Messung von Scoring sauber: setzt man
in den 12 Rang-Fehlern das gemessene circle_diameter_mm rechnerisch auf das
Enrollment-Mittel des **wahren** Artikels (Annahme: perfekt gemessen), landen
**11 von 12** wieder auf Rang 1 — aber **0 von 12** erreichen die 2.0-Margin,
und in der Kontrollrechnung fallen dabei **3 korrekte ACCEPTs unter 2.0**
(das Experiment ist also nicht neutral, die „perfekte" Messung kann Margins
auch senken). Lesart: der Messfehler erklärt die **Rangfolge**, nicht die
**Margin**. Selbst mit korrekter Größe blieben diese Fälle AMBIGUOUS.

Daraus folgt der begrenzende Befund: **14 von 17 kritischen Paaren** lösen in
**keinem** Szenario auf (nur LOEFFEL-12/LOEFFEL-4, LOEFFEL-15/LOEFFEL-9,
MESSER-6/MESSER-7 lösen bei irgendeinem α/Gewicht auf). Kein Gewichtsschema
kann fördern, was der Merkmalsraum nicht misst; die schwersten Paare
(MESSER-5/-7, LOEFFEL-1/-5, LOEFFEL-1/-6) liegen in allen vier
Trennschärfe-Achsen (Ø, solidity, hu, aspect) unter ~1 σ.

Zur Einordnung der 12 Rang-Fehler die zentralen Zahlen:

| Kennzahl | Wert |
|---|---|
| median z_eigen(wahr) der 12 | **−1.76** |
| median z_eigen über ALLE Reports | −0.92 |
| median z_eigen über correct-ACCEPT | −0.77 |
| Fehl-Top-1 nominal kürzer als wahr | 8 / 12 |
| kontrafaktisch (perfekter Ø) wieder Rang 1 | 11 / 12 |
| davon erreichen llr ≥ 2.0 | 0 / 12 |

Der wahre Artikel ist in den Fehlern also fast doppelt so stark unterschätzt
wie im Schnitt, und in 8 von 12 Fällen ist der fälschlich gewählte Artikel
tatsächlich kürzer — die zu kleine Messung passt besser zum kleineren
Nachbarn. (Gegenbeleg: die übrigen 4 sind quasi gleich große Paare, bei denen
der Ø nicht trennt und andere Merkmale den Fehlsieger bestimmen.)

---

## 5. Zwei getrennte Messeffekte

Die Messung zeigt zwei überlagerte, sauber getrennte Auffälligkeiten.

**Bulk-Versatz (isotrop, session-spezifisch).** Über alle 104 Reports ist
`z_eigen` (gemessener Ø minus eigenes Enrollment-Mittel, in Enrollment-Std)
systematisch **negativ**: median −0.94, 80 % negativ. Session-aufgelöst misst
**phase-b alle Artikel bei ~0.987** (1.3 % zu klein), **phase-c2 bei ~1.000**.
`s_len ≈ s_wid ≈ 0.993` (Länge und Breite gleich reduziert) — der Bulk-Versatz
ist **isotrop**, also skalenartig. Rechnerisch äquivalent zu einem
Kalibriermarker, der ~4.05 mm über dem Boxboden liegt (`h = Z·(1−f) =
300·(1−0.9865)`; erhöhter Marker → kleineres mm_per_px → Untermaß). Ob das
zutrifft, ist **mit den Snapshots nicht entscheidbar**: `calibration.json` und
`session.json` speichern keine Marker-Höhe/Unterlage/Aufbau. Als **Gegenbeleg**
gegen eine feste Rig-Geometrie: phase-c2 zeigt den Versatz nicht — wäre es
permanente Geometrie, müsste sie beide Sessions treffen. Der Offset ist
phase-b-spezifisch (session-spezifische Auflage oder Licht-/Segmentierungs-
Unterschied), Ursache offen.

**Tail-Effekt (anisotrop).** Acht Reports haben |z_eigen| > 3 (sieben negativ,
einer positiv). Dort ist die Anisotropie stark: `s_wid/s_len ≈ 1.040`, d. h.
die Länge fällt ~4 %, die Breite bleibt erhalten. In 6 der 8 Fälle folgt das
diesem Muster; Ausnahmen sind LOEFFEL-12 (verliert Breite statt Länge) und
LOEFFEL-4 in 1784820020752 (übermaßig, +z). Die Konturen sind laut Overlay
**vollständig** — keine Amputation, sondern eine Verformung an einem
Objektende (bei LOEFFEL-3 an der Laffe, bei LOEFFEL-6 am Stiel; die genaue
Ende-Zuordnung ist registrierungs-sensitiv). Die Ursache ist offen; siehe die
Orientierungsprüfung in Abschnitt 9.

**Ausdrücklich widerlegte Hypothesen** (der wertvollste Teil):

- *Parallaxen-Scherung / randnahe Verzeichnung.* Widerlegt. Die beiden am
  genauesten untersuchten Ausreißer sind die **am stärksten zentrierten**
  Aufnahmen (radialer centroid-Abstand 3.4 bzw. 8.0 mm gegen Artikel-Median
  40.6 bzw. 27.7 mm). Und über alle 104 Reports korreliert s_len **nicht** mit
  der Endposition (r = −0.09), Orientierung (−0.17) oder Schwerpunktlage
  (−0.16) — kein Fit trägt (Abschnitt 9).
- *End-Trunkierung als durchgehender Mechanismus.* Widerlegt. Über den ganzen
  Bestand ist der Versatz **isotrop** (median s_len ≈ median s_wid ≈ 0.993),
  und s_len < s_wid trifft nur auf 49 % der Reports zu — es gibt kein
  durchgehendes „kürzer bei erhaltener Breite". Der anisotrope Effekt ist ein
  **Tail-Phänomen** unterschiedlicher Stärke, kein Grundmechanismus.
- *Kontamination der Formmerkmale durch fehlende Endabschnitte.* Widerlegt.
  s_len korreliert nur schwach mit solidity (+0.13), circularity (−0.08),
  hu-Distanz (−0.16) und aspect (−0.27, konstruktiv gekoppelt). Die in der
  Paartrennung stärksten Merkmale (solidity, hu_log) tragen Artikeltyp-, nicht
  Trunkierungs-Information.

---

## 6. Methodische Lehren

Die **Stammdaten-Drift (~4 mm)** hat drei Analysen zunächst verfälscht: eine
DB-basierte Reproduktion des Vorfilters „bewies" falsche Ursachen (der
Flächenfilter schien den wahren Artikel zu killen), bis klar wurde, dass die
heutige DB nicht mehr dem Report-Zustand entspricht. Lehre: für alles
Vorfilter-Bezogene ausschließlich **report-zeitliche Nominale** verwenden,
nie die aktuelle DB.

Die **Enrollment-Shots werden verrechnet, aber nicht als Bild gespeichert**
(`reference_features.image_path = None`, `data/reference/` enthält nur
CD-REFERENZ). Dadurch war kein Vergleich „Ausreißer-Kontur gegen
Enrollment-Shot-Kontur" möglich — die visuelle Forensik musste auf
„Testbild gegen normalen Testbild-Report desselben Artikels" ausweichen. Das
reicht für die Anisotropie-Diagnose, nicht für eine echte Enrollment-Referenz.

**Simulation vor Änderung hat funktioniert.** Jede Stellschraube war einzeln
plausibel und ist erst an den Zahlen gescheitert — mehrfach an einem einzigen
Falschakzept, der ohne Simulation erst im Betrieb aufgefallen wäre. Die
Kontrollrechnung (S0/α=2 reproduziert den Ist-Zustand exakt) hat jede
Simulation abgesichert; das sollte Standard bleiben.

---

## 7. Offen / nächste Schritte

Nicht als Empfehlung, sondern als Liste dessen, was die Daten nahelegen zu
prüfen: `sync-stammdaten` vor `--apply` **simulieren** (vergrößert die
Kandidatensets im Mittel um +1.49, das ist ein Preis); die **Marker-Auflage**
am Rig physisch prüfen (die 4.05-mm-Hypothese ist mit den Snapshots weder zu
stützen noch auszuschließen); eine **Intrinsic-Kalibrierung** gegen radiale
Verzeichnung erwägen; ein **Auflagefeld** / definierte Objektposition beim
Enrollment und Identify; ein separater **CD-Positions-/Wiederholbarkeits-Test**
(mehrfach dieselbe Auflage, um den Rauschboden zu messen). Eine elastische
**Konturmetrik** (SRVF o. Ä.) bleibt zurückgestellt, bis der Rauschboden der
Messung bekannt ist — sonst misst sie Segmentierungsrauschen statt Form.

---

## 8. Anhang

Die vollständigen Zwischentabellen und Streudiagramme lagen zum
Analysezeitpunkt unter `/tmp/` (`ambiguous_analyse.md`,
`ambiguous_verifikation.md`, `floors_und_achsen.md`, `gewichte_simulation.md`,
`alpha_simulation.md`, `vorfilter_gate.md`, `ausreisser.md`,
`trunkierung.md`, `orientierung.md`, plus PNGs). **Diese Pfade sind flüchtig**
— die für spätere Arbeit relevanten Tabellen (Abschnitte 4 und 5) sind
deshalb hier eingebettet und nicht verlinkt. Wer tiefer einsteigt, reproduziert
die Zahlen aus den Report-JSONs; die Rekonstruktion ist deterministisch und
reproduziert den Ist-Zustand bitgenau.

---

## 9. Orientierungs-Test (Teil I, 2026-07-27)

Nachgereichte Prüfung der einzigen zum Redaktionsschluss offenen Frage aus
Abschnitt 5: ist der anisotrope **Tail**-Effekt Aufnahmegeometrie
(Scherung/radiale Verzeichnung) oder etwas anderes?

Geprüft wurde über alle 104 Reports der Zusammenhang von s_len (und dem
Anisotropiemaß s_wid/s_len) mit der Aufnahmegeometrie aus der Kontur:
Hauptachsenwinkel theta, radialer Abstand der Objektenden (r_end_max), der
Querausdehnung (r_quer_max) und der Schwerpunktlage. **Kein einziger Fit
trägt** — alle |Pearson r| ≤ 0.29:

| Fit | r |
|---|---|
| s_len ~ r_end_max | −0.09 |
| s_len ~ theta | −0.17 |
| s_len ~ r_centroid | −0.16 |
| s_wid ~ r_quer_max | −0.07 |
| (s_wid/s_len) ~ r_end_max | +0.02 |
| (s_wid/s_len) ~ theta | +0.29 |

Eine radiale Verzeichnung/Scherung müsste drei Dinge erzeugen; geprüft
einzeln: (1) s_len fällt monoton mit r_end_max → **nein** (r = −0.09, die
niedrigen s_len streuen über den ganzen Radiusbereich); (2) s_wid unabhängig
von r_end_max → ja, aber trivial, weil nichts von r_end_max abhängt; (3)
orientierungsabhängig über theta → **nicht entscheidbar** (r ≤ 0.29). Die
**definierende** Vorhersage (1) ist widerlegt.

Der Bulk-Fit s_len ~ r_end_max ist flach (r = +0.02); die acht Tail-Fälle
liegen als eigener Residuen-Cluster (−0.018 bis −0.033) **abseits** dieser
Linie, unabhängig von ihrer Position — ein **eigener Mechanismus**, kein
positionsverstärkter Bulk-Effekt. Ergebnis: **Aufnahmegeometrie als Ursache
des Tail-Effekts ist ausgeschlossen** (damit auch Parallaxe/Scherung erneut,
vgl. Abschnitt 5). Da Bildgeometrie ausscheidet und die Konturen vollständig
sind, bleiben auflage- oder segmentierungsseitige Ursachen — mit den
vorhandenen Daten (kein Enrollment-Bild) nicht weiter auflösbar.
