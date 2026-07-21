# Vorfilter-Vergleichsfehler für längliche Artikel — Ergebnisdokument

Stand 2026-07-21 · Branch `main` · Bezug: [Plan](../plans/2026-07-21-vorfilter-laengliche-artikel.md),
[Übergabebericht Regressions-Korpus](2026-07-20-corpus-harness-abschluss.md)
(Abschnitt „Offene Punkte", Punkt 1).

Dieses Dokument ist für eine Sitzung ohne Vorkontext geschrieben.

---

## 1. Auftrag und Befund

Der Geometrie-Vorfilter (`docodetect/matcher.py::_nominal_size_mm`) verglich
für längliche Artikel (Löffel/Gabel/Messer — `width_mm`/`depth_mm` gesetzt,
`diameter_mm` leer) den gemessenen `circle_diameter_mm`
(minEnclosingCircle-Durchmesser) gegen `hypot(width_mm, depth_mm)` — die
Diagonale des `minAreaRect`. Das ist ein Äpfel-Birnen-Vergleich: bei einem
länglichen, konvex abgerundeten Objekt (Besteck) entspricht der
minEnclosingCircle-Durchmesser der LÄNGE, nicht der Rechteck-Diagonale.
Fünf Löffel-Bilder aus dem Regressions-Korpus (`phase-b`) waren dadurch
bekannte „Vorfilter-Kills": der wahre Artikel überstand den Vorfilter nicht,
ein falscher gewann.

## 2. Optionsanalyse (datenbasiert, alle 60 Löffel-Bilder aus `phase-b`)

Drei Optionen wurden gegen den vollständigen Korpus (nicht nur die 5
bekannten Kills) ausgewertet:

| Option | Vergleichsbasis | mean\|err\| | median | max\|err\| | n>6mm (Kills) |
|---|---|---|---|---|---|
| Aktuell (verworfen) | `hypot(width,depth)` (Diagonale) | 2.82 mm | 2.43 mm | 8.41 mm | **5** |
| **A — gewählt** | `max(width,depth)` (Länge) | 1.51 mm | 1.48 mm | 4.26 mm | **0** |
| B — Länge-Teilconstraint | gemessene minAreaRect-Länge (aus Report-Kontur) | 1.41 mm | 1.25 mm | 4.36 mm | 0 |
| B — Breite-Teilconstraint | gemessene minAreaRect-Breite (aus Report-Kontur) | 0.63 mm | 0.59 mm | 1.93 mm | 0 |

**Gewählt: Option A** — `_nominal_size_mm` gibt für den länglichen Zweig
`max(width_mm, depth_mm)` statt `hypot(width_mm, depth_mm)` zurück.

**Begründung:**

1. Löst alle 5 bekannten Kills; über alle 60 Bilder bleibt der maximale
   Restfehler bei 4.26 mm — deutlich innerhalb der 6-mm-Toleranz, kein
   Ausreißer nahe der Grenze.
2. Kein neuer Messwert nötig: `measured.circle_diameter_mm` (bereits in
   `Features` vorhanden) wird weiterhin verglichen, nur die DB-Seite ändert
   sich. Keine neue Abhängigkeit von der (bereits auf ~400 Punkte
   ausgedünnten) Report-Kontur.
3. Option B (zwei Constraints aus dem gemessenen minAreaRect auf der
   ausgedünnten Kontur) bringt keinen Genauigkeitsgewinn (Breite-Residuen
   sind ohnehin klein, < 2 mm) und erzeugt beim tatsächlichen
   Kandidatenset-Vergleich MEHR Änderungen als Option A (36 von 60 Bildern
   gegenüber 32 bei A, Simulation vor der Implementierung) — mehr
   Komplexität, mehr Fehlerflächen, kein Nutzen.
4. **Geometrischer Beweis für den Randfall `width ≈ depth`:** Cutlery-Objekte
   sind keine scharfkantigen Rechtecke, sondern eine „Stadion"-Form (Schaft +
   abgerundete Enden). Für eine Stadion-Kontur der Länge L und Breite W ≤ L
   ist der minEnclosingCircle-Durchmesser **exakt** L, unabhängig von W —
   analytisch hergeleitet und gegen rasterisierte Konturen verifiziert:

   | L | W | minEnclosingCircle (gemessen) |
   |---|---|---|
   | 190 | 40 | 190.00 |
   | 100 | 90 | 100.00 |
   | 100 | 100 (entartet zum Kreis) | 100.00 |
   | 100 | 10 | 100.00 |

   Die Diagonale wäre nur für ein scharfkantiges Rechteck korrekt — das ist
   bei keinem Cutlery-Artikel der Fall. Option A ist damit über den GESAMTEN
   Breite/Länge-Bereich physikalisch exakt, nicht nur eine Näherung für sehr
   längliche Objekte.

**Flächen-Vorfilter (`area_tolerance_pct`) — Prüfbefund, kein Fix (Auftrag
verlangte nur Bericht):** Der Flächencheck in `matcher.py` läuft NUR
`if art.diameter_mm` (runder Zweig) — für längliche Artikel ist er komplett
inaktiv, trägt also nicht dieselbe Inkonsistenzklasse (er greift schlicht
nie). Für runde Artikel vergleicht er `measured.area_mm2` (Polygonfläche)
gegen `pi*(nominal/2)^2`, wobei `nominal` selbst aus `circle_diameter_mm`
abgeleitet wurde — ein leichteres Echo desselben Effekts (Umkreis- vs.
Flächenmaß), aber unbelegt als Fehlerquelle in der Praxis (keine
gemeldeten Kills bei runden Artikeln). Empfehlung, nicht umgesetzt.

## 3. Implementierung

**Geändert:** `docodetect/matcher.py::_nominal_size_mm` (Zeile 162–176),
eine Zeile: `np.hypot(width_mm, depth_mm)` → `max(width_mm, depth_mm)`,
Docstring um die Stadion-Form-Begründung ergänzt.

**Unit-Tests** (`tests/test_matching_decisions.py`, 5 neue, alle nutzen die
echten Schwellen aus `config/config.yaml`):

| Test | Prüft |
|---|---|
| `test_laenglicher_artikel_vergleicht_gegen_laenge_nicht_diagonale` | Kernfix: 187 mm Messung, Löffel 190×40 mm — Diagonale (194.15) hätte gekillt, Länge (190) überlebt |
| `test_laenglicher_artikel_ausserhalb_laengen_toleranz_wird_gekillt` | Gegenprobe: auch von der Länge > 6 mm entfernt → weiterhin REJECT (kein pauschales Aufweichen) |
| `test_rundes_produkt_unveraendert_ueber_diameter_mm` | Runder Zweig (`diameter_mm`) unberührt |
| `test_laenglich_width_gleich_depth_randfall` | Randfall `width == depth` (50/50 mm): Länge (50) und Diagonale (70.7) fallen weit auseinander — Fix vergleicht weiterhin gegen die Länge |
| `test_laenglich_hoehenkompensation_bleibt_pro_kandidat_wirksam` | `corrected_diameter_mm`-Formel bleibt unverändert wirksam (Formel ist von der Nominal-Wahl unabhängig) |

Vor dem Fix: 3 von 5 schlugen fehl (die zwei übrigen testen bereits
unveränderte Pfade). Nach dem Fix: alle 19 Tests in der Datei grün.

## 4. Harness-Ergebnis: Tier 1 und Tier 2

### Tier 1 — unverändert (wie erwartet)

129/129 PASS, 0 DRIFT, 0 FAIL, vor UND nach dem Fix identisch (nur der
Code-Fingerprint ändert sich — beweist, dass der Fix den Harness erreicht,
aber Tier 1 ruft `matcher.match()` nie auf).

### Tier 2 — 32 von 60 Bildern ändern sich (nicht nur die 5 bekannten Kills)

**Die Schritt-3-Erwartung war zu eng formuliert.** Angenommen war: „nur die
5 bekannten Kills ändern sich, sonst bleibt jedes Kandidatenset identisch".
Tatsächlich ändern sich 32 von 60 Bildern. Grund: der Diagonal-Offset
verschob das Vorfilter-Toleranzfenster für JEDEN länglichen Kandidaten in
JEDEM Bild simultan (nicht nur für den jeweils wahren Artikel) — bei
mehreren Löffeln nahezu identischer Länge im Korpus (Cluster ~188–194 mm:
LOEFFEL-1/2/3/5/6/12; Cluster ~124–141 mm: LOEFFEL-9/11/13/14/15) kippen
dadurch auch Grenzfälle außerhalb der 5 Kills. Das ist eine physikalisch
zwingende Konsequenz der Korrektur, keine Nebenwirkung, die man hätte
vermeiden können.

**Vollständige Klassifikation aller 32 (Rechenschaft, siehe Konversation für
Details):**

| Kategorie | n | Kriterium |
|---|---|---|
| a — bekannte Vorfilter-Kills | 5 | Label war vorher nicht im Kandidatenset |
| b — reine Kandidatenset-Verschiebung | 26 | Sieger (Top-1) UND Entscheidung beide unverändert |
| c — Entscheidungswechsel außerhalb der 5 | 1 | Entscheidung ändert sich, Top-1 bleibt aber gleich |
| d — alles andere | **0** | — |

**Kritischer Check (Regressions-Stopp-Kriterium): fällt in irgendeinem Bild
der WAHRE Artikel neu aus dem Kandidatenset?** Geprüft über alle 32
geänderten Bilder (jede mögliche Verschlechterung müsste dort auftauchen,
da unveränderte Kandidatensets per Definition nichts verlieren können).
**Ergebnis: 0 von 32.** Das Toleranzfenster verschiebt sich zwar in beide
Richtungen, aber empirisch verliert niemand seinen wahren Artikel.

**Kategorie a — die 5 bekannten Kills.** Entscheidung bleibt in allen 5
Fällen `ambiguous` (war es vorher auch); der bisherige, falsche Top-1
bleibt (Farb-/Formmerkmale entscheiden hier, nicht die Geometrie). Neu: das
wahre Label erscheint jetzt im Kandidatenset und ist für den Menschen in
der AMBIGUOUS-Auswahl wählbar — vorher war es dort gar nicht vertreten.
Zwei der fünf (`1784561499560.png`, `1784562390997.png`, Label LOEFFEL-1)
landen dabei auf Rang 2 (das erklärt die accuracy_top3-Verbesserung, siehe
unten); die anderen drei auf Rang 4–5 von 6–7 (siehe Empfehlung 5a).

**Kategorie c — das eine Ausnahme-Bild, einzeln begründet.**
`1784562127960.png`, Label LOEFFEL-4: Decision `accept → ambiguous`, Top-1
bleibt korrekt `LOEFFEL-4 → LOEFFEL-4`. Ursache: zwei neue geometrische
Nachbarn (LOEFFEL-5, LOEFFEL-2) treten neu ins Kandidatenset ein; das
vergrößerte Set verschiebt die Fisher-adaptive Gewichtung
(`matching.adaptive_weight_alpha=2.0`, `w_eff = w_global · (1 + α·D_norm)`)
über ALLE Kandidaten, wodurch `llr_margin` von 5.8807 auf 1.7029 sinkt
(< `min_llr_margin`=2.0). Ergebnis: statt Auto-Buchung jetzt eine
Bestätigung durch den Menschen nötig — der richtige Artikel bleibt vorne,
kein Fehlbuchungsrisiko. Das ist die LLR-Margin-Schutzfunktion
(CLAUDE.md: „einziger wirksamer Schutz gegen Fehlbuchungen bei baugleichen
Artikeln") bei einem größer gewordenen Kandidatenset — Design, keine
Regression (siehe Empfehlung 5b).

**Kategorie b (26) — vollständige Liste:**

| Bild | Label | Kat. | Decision alt→neu | llr_margin alt→neu | Kandidaten +/− |
|---|---|---|---|---|---|
| 1784561563735.png | LOEFFEL-4 | b | accept→accept | –→2.095 | +LOEFFEL-5 |
| 1784561713592.png | LOEFFEL-12 | b | accept→accept | 2.5519→2.5914 | +LOEFFEL-3,1,6 / −LOEFFEL-4 |
| 1784562262497.png | LOEFFEL-11 | b | ambiguous→ambiguous | 0.087→0.1493 | −LOEFFEL-15 |
| 1784562009379.png | LOEFFEL-13 | b | ambiguous→ambiguous | 0.2146→0.266 | +LOEFFEL-14 / −LOEFFEL-15 |
| 1784562043071.png | LOEFFEL-15 | b | accept→accept | 4.3497→6.1453 | +LOEFFEL-13 / −LOEFFEL-9 |
| 1784561987654.png | LOEFFEL-12 | b | accept→accept | 2.3587→2.594 | +LOEFFEL-6 / −LOEFFEL-4 |
| 1784561845932.png | LOEFFEL-4 | b | accept→accept | –→2.7482 | +LOEFFEL-5 |
| 1784561693698.png | LOEFFEL-11 | b | ambiguous→ambiguous | 0.0509→0.0099 | −LOEFFEL-15 |
| 1784561731029.png | LOEFFEL-13 | b | ambiguous→ambiguous | 0.1908→0.2285 | −LOEFFEL-15 |
| 1784561862597.png | LOEFFEL-5 | b | ambiguous→ambiguous | 1.2276→1.0163 | +LOEFFEL-1,6,3 / −LOEFFEL-4 |
| 1784562063348.png | LOEFFEL-1 | b | ambiguous→ambiguous | 0.2955→0.3418 | +LOEFFEL-6 / −LOEFFEL-4 |
| 1784562282473.png | LOEFFEL-12 | b | accept→accept | 2.1038→2.3079 | −LOEFFEL-4 |
| 1784562632885.png | LOEFFEL-11 | b | ambiguous→ambiguous | 0.0061→0.0594 | −LOEFFEL-15 |
| 1784562370595.png | LOEFFEL-15 | b | accept→accept | –→4.0342 | +LOEFFEL-11,13 |
| 1784562660953.png | LOEFFEL-12 | b | ambiguous→ambiguous | 0.5547→0.3324 | +LOEFFEL-1,3,6 |
| 1784561883389.png | LOEFFEL-6 | b | ambiguous→ambiguous | 0.0323→0.0425 | −LOEFFEL-5 |
| 1784562105164.png | LOEFFEL-3 | b | ambiguous→ambiguous | 0.2709→0.2745 | −LOEFFEL-5 |
| 1784562325397.png | LOEFFEL-13 | b | ambiguous→ambiguous | 0.1158→0.115 | +LOEFFEL-14 |
| 1784562482368.png | LOEFFEL-5 | b | ambiguous→ambiguous | 0.0411→0.0394 | +LOEFFEL-2 |
| 1784561542515.png | LOEFFEL-3 | b | ambiguous→ambiguous | 0.0794→0.1173 | −LOEFFEL-4 |
| 1784561581163.png | LOEFFEL-5 | b | ambiguous→ambiguous | 0.3221→0.35 | +LOEFFEL-2,3 |
| 1784561524646.png | LOEFFEL-2 | b | ambiguous→ambiguous | 0.3628→0.3748 | −LOEFFEL-4 |
| 1784562166780.png | LOEFFEL-6 | b | ambiguous→ambiguous | 0.1734→0.1575 | −LOEFFEL-5 |
| 1784562683113.png | LOEFFEL-13 | b | ambiguous→ambiguous | 0.156→0.1553 | −LOEFFEL-15 |
| 1784561600355.png | LOEFFEL-6 | b | ambiguous→ambiguous | 0.0907→0.0984 | −LOEFFEL-5 |
| 1784562145801.png | LOEFFEL-5 | b | ambiguous→ambiguous | 0.7237→0.7055 | +LOEFFEL-1,6,3 / −LOEFFEL-4 |

**Kategorie a — vollständig (zur Vollständigkeit hier nochmal mit
Kandidaten-Diff):**

| Bild | Label | Decision alt→neu | llr_margin alt→neu | Kandidaten +/− |
|---|---|---|---|---|
| 1784562435798.png | LOEFFEL-3 | ambiguous→ambiguous | 0.4378→0.381 | +LOEFFEL-1,2,3,6 |
| 1784561499560.png | LOEFFEL-1 | ambiguous→ambiguous | 0.659→0.2361 | +LOEFFEL-1,6,3 / −LOEFFEL-4 |
| 1784562390997.png | LOEFFEL-1 | ambiguous→ambiguous | 0.4626→0.0731 | +LOEFFEL-1,6 / −LOEFFEL-4 |
| 1784562412154.png | LOEFFEL-2 | ambiguous→ambiguous | 0.0831→0.0367 | +LOEFFEL-1,2,6,3 |
| 1784562504239.png | LOEFFEL-6 | ambiguous→ambiguous | 0.7423→0.6187 | +LOEFFEL-1,6,3 / −LOEFFEL-4 |

### Quoten-Diff (Tier 2, gegen die alte Baseline 46/60, 54/60, 25/60, 0/25)

| Kennzahl | alt | neu | Δ | Erklärung |
|---|---|---|---|---|
| accuracy_top1 | 46/60 (0.7667) | 46/60 (0.7667) | 0 | unverändert |
| accuracy_top3 | 54/60 (0.9000) | 56/60 (0.9333) | **+2** | die 2 Kategorie-a-Fälle, in denen das Label neu auf Rang 2 landet |
| auto_accept_rate | 25/60 (0.4167) | 24/60 (0.4000) | −1 | exakt das eine Kategorie-c-Bild |
| false_accept_rate | 0/25 (0.0) | 0/24 (0.0) | 0 | weiterhin keine einzige Fehlbuchung; Nenner sinkt nur, weil ein Accept zu Ambiguous wurde |

## 5. Empfehlungen (nicht umgesetzt, nur dokumentiert)

**a) `top_k=3` vs. Rang 4–5 bei drei der fünf Ex-Kills.** Die UI zeigt bei
AMBIGUOUS nur `matching.top_k` (=3) Vorschläge. Drei der fünf ehemaligen
Kills (LOEFFEL-2, LOEFFEL-3, LOEFFEL-6 — siehe Tabelle Kategorie a) landen
nach dem Fix auf Rang 4 oder 5 von 6–7 Kandidaten: der wahre Artikel ist
zwar jetzt im Kandidatenset (`rep.candidates`, vollständig), aber in der
UI mit `top_k=3` weiterhin unsichtbar. Nur die zwei auf Rang 2 gelandeten
Fälle sind für den Menschen tatsächlich sichtbar auswählbar. Eine
Diskussion, ob `top_k` für längliche Artikel mit vielen geometrischen
Nachbarn erhöht werden sollte, ist eine begründete Empfehlung — keine
Schwellenänderung in diesem Auftrag.

**b) Fisher-adaptive Gewichtung komprimiert Margins mit wachsendem
Kandidatenset — dokumentierte Erwartung fürs DB-Wachstum.** Kategorie c
zeigt den Mechanismus konkret: mehr geometrische Nachbarn im Kandidatenset
→ kleinere `llr_margin` für alle Kandidaten (durch die Fisher-Ratio-
Neuberechnung über das größere Set) → `auto_accept_rate` sinkt tendenziell,
je mehr Artikel eingelernt sind. Beim geplanten Einlernen von Gabeln und
Messern (weitere längliche Artikel, weitere geometrische Nachbarn) ist ein
weiterer Rückgang der Auto-Accept-Quote zu erwarten. Das ist Design (die
LLR-Margin schützt genau davor, bei mehrdeutiger Geometrie automatisch zu
buchen), keine Regression — aber sollte nicht überraschen, wenn es beim
nächsten Korpus-Lauf erneut auftritt.

**c) Eigene, weniger strenge Toleranz für längliche Artikel?** Nicht
umgesetzt (explizit gesperrt in diesem Auftrag). Datenlage: mit Option A
liegt der maximale Restfehler über alle 60 Löffel-Bilder bei 4.26 mm, die
6-mm-Toleranz hat also spürbare Reserve. Aktuell kein Bedarf erkennbar.

**d) Flächen-Vorfilter für runde Artikel** — siehe Abschnitt 2, Prüfbefund
ohne Fix.

**e) Option A gilt exakt nur für konvexe Stadion-Formen (Besteck) — vor dem
Einlernen scharfkantig rechteckiger Artikel prüfen.** Der geometrische
Beweis in Abschnitt 2 gilt für eine konvexe Kontur aus Schaft + abgerundeten
Enden. Ein scharfkantig RECHTECKIGER länglicher Artikel (Tablett,
rechteckige Platte, GN-Behälter) hat seinen minEnclosingCircle-Durchmesser
dagegen an der DIAGONALE, nicht an der Länge — der Vergleich gegen die
Länge würde dort den gespiegelten Fehler dieses Fixes erzeugen: der
Geometriefehler liefe systematisch zu groß in die andere Richtung (Messwert
≈ Diagonale, Nominal = Länge) und könnte den Vorfilter für boxige statt für
längliche Formen wieder falsch killen. Vor dem Einlernen eines solchen
Artikels ist diese Annahme zu prüfen; im Zweifel eine
Formklassen-Unterscheidung (rund / Stadion / scharfkantiges Rechteck) als
eigener Auftrag mit Datenbegründung. Hinweis dazu steht auch im Docstring
von `_nominal_size_mm` (`docodetect/matcher.py`).

## 6. Harness-Erweiterung: Akzeptanz-Schicht für Golden-Deltas

Während der Umsetzung zeigte sich: `corpus-run --tier 2 --check` vergleicht
pro Bild direkt gegen den eingefrorenen Golden-Report (historisches
Mess-/Bewertungsprotokoll, außerhalb des Repos, NIE verändert) — unabhängig
von `corpus/baseline.json` (das nur Aggregat-Quoten führt). Ohne weitere
Maßnahme hätte JEDE der 32 Änderungen `--check` auf Dauer FAIL gemeldet,
selbst nach explizitem Review und Freigabe.

Gebaut wurde eine neue, versionierte Akzeptanz-Schicht (Harness-Änderung,
NICHT der Messpfad — die Sperrliste des Auftrags bleibt unberührt):

- `docodetect/corpus/accepted.py` (neu): lädt `corpus/accepted_deltas/*.json`
  und vergleicht einen Replay bei einer FAIL-Abweichung vom Original-Golden
  zusätzlich gegen einen dort hinterlegten, akzeptierten Delta-Eintrag.
  Reproduziert der Replay das Delta exakt → PASS. Erklärt das Delta die
  Abweichung nur teilweise (eine weitere, nicht akzeptierte Änderung obendrauf)
  → bleibt FAIL. Ohne Delta-Eintrag: Verhalten unverändert (nur gegen Golden).
- `docodetect/corpus/runner.py`: `resolve_diffs()` nach `compare_tier2()`
  eingehängt; `corpus/accepted.py` und der Inhalt von
  `corpus/accepted_deltas/*.json` sind jetzt Teil des Code-Fingerprints
  (ein neues/geändertes Delta invalidiert den `--changed-only`-Cache wie
  eine geänderte `compare.py`-Schwelle).
- `corpus/accepted_deltas/2026-07-21-vorfilter-fix.json` (neu, versioniert):
  die 32 akzeptierten Bilder mit den erwarteten neuen Matcher-Ausgabefeldern
  (`decision`, `candidates`, `gate_passed`, `llr_margin`, `max_z_winner`),
  Kategorie (a/b/c) und Begründung je Bild — beim Kategorie-c-Bild die
  volle Fisher-Gewichtungs-Erklärung (Margin 5.88→1.70), nicht nur die
  neuen Felder. `fix_commit` ist als `null` mit einem Hinweisfeld
  hinterlegt und muss nach Freigabe des Commits mit dem echten Hash
  befüllt werden (`git log -1 --format=%H`).
- 9 neue Unit-Tests: `tests/test_corpus_accepted.py` (Laden/Mergen mehrerer
  Delta-Dateien, exakte Übereinstimmung → PASS, teilweise erklärte
  Abweichung → weiterhin FAIL, sha8-Kürzung).

Die Original-Golden-Reports in `phase-b/reports/*.json` sind dabei
byte-identisch geblieben (nicht angefasst, keine Backup-Kopie nötig).

## 7. Testergebnisse

- `pytest tests/test_matching_decisions.py` (19 Tests, davon 5 neu): PASS.
- `pytest tests/test_corpus_accepted.py` (9 neue Tests): PASS.
- Volle Suite ohne Korpus-Marker: 410 passed, 17 skipped, 0 failed.
- Volle Suite unfiltered (`pytest`, inkl. `corpus`/`corpus_smoke`-Marker):
  **414 passed, 17 skipped, 0 failed** (14:10 min). Vorher (Stand
  Übergabebericht) 400 passed — die Differenz sind die 14 neuen Tests (5 in
  `test_matching_decisions.py`, 9 in `test_corpus_accepted.py`).
  `test_corpus.py::test_corpus_tier2_decisions_reproduce` — vor der
  Akzeptanz-Schicht die einzige rote Stelle im vollen Lauf — ist jetzt
  ebenfalls grün.
- `corpus-run --tier 1 --check`: **OK** (129/129, unverändert vor/nach Fix).
- `corpus-run --tier 2 --check`: **OK** (60/60 über Golden + Akzeptanz-
  Schicht, gegen die neue Baseline).
- `corpus-run --tier 1 --update-baseline`: verweigert korrekt mit Exit 2
  („ABBRUCH: --update-baseline ohne Quoten") — die bekannte Falle greift
  nicht mehr, `corpus/baseline.json` bleibt dabei unangetastet (verifiziert
  per `git diff`).
- `corpus-run --tier 2 --update-baseline`: Baseline aktualisiert mit vollen
  Quoten (siehe Abschnitt 4).

## 8. Zusammenfassung Auftrags-Deliverables

- ✅ Optionsanalyse A/B/C mit Verteilungszahlen über alle 60 Löffel-Bilder
  (Abschnitt 2).
- ✅ Gewählte Option (A) mit Begründung, inkl. geometrischem Beweis für den
  Randfall `width ≈ depth` (Abschnitt 2).
- ✅ Erwartung vor Implementierung schriftlich festgelegt (Plan-Dokument),
  Abweichung von der ursprünglichen „nur 5 Fälle"-Annahme erklärt
  (Abschnitt 4).
- ✅ Unit-Tests: länglich (Kernfix), länglich außerhalb Toleranz (Gegenprobe),
  rund (Regressionsschutz), `width ≈ depth` (Randfall), Höhenkompensation
  (Abschnitt 3).
- ✅ Flächen-Vorfilter geprüft und berichtet, nicht gefixt (Abschnitt 2).
- ✅ Tier 1: 129/129, unverändert (Abschnitt 4).
- ✅ Tier 2: alle 32 Abweichungen einzeln klassifiziert und erklärt,
  kritischer Regressions-Check (wahres Label neu verworfen?) mit Ergebnis 0
  (Abschnitt 4).
- ✅ Beide Tiers explizit re-baselinet, bekannte `--update-baseline`-Falle
  verifiziert (Abschnitt 6/7).
- ✅ Diameter-Toleranz unverändert (6.0 mm) — nur als Empfehlung
  dokumentiert (Abschnitt 5c).
