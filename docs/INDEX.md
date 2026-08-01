# Doku-Chronik

Landkarte für Sitzungen ohne Vorkontext: die Ergebnis- und Ablaufdokumente
in zeitlicher Reihenfolge, je ein Satz Inhalt. **Ersetzt kein Dokument** —
für die eigentliche Begründung immer das verlinkte Dokument lesen. Dauerregeln
stehen in [../CLAUDE.md](../CLAUDE.md), Architektur in
[architektur.md](architektur.md), Setup/Ablauf im [../README.md](../README.md).

## Ergebnis- & Ablaufdokumente (chronologisch)

- **2026-07-20** — [Regressions-Korpus Übergabebericht](superpowers/reports/2026-07-20-corpus-harness-abschluss.md):
  Aufbau der zweistufigen Korpus-Harness (Tier 1 Messung, Tier 2 Entscheidung),
  Fingerprints/Baseline/Drift-Zyklus.
- **2026-07-21** — [Vorfilter-Vergleichsfehler für längliche Artikel](superpowers/reports/2026-07-21-vorfilter-laengliche-artikel-ergebnis.md):
  Der Geometrie-Vorfilter vergleicht seither `max(width, depth)` statt
  `hypot` (Diagonal-vs-Länge-Fehler), plus Akzeptanz-Schicht.
- **2026-07-22** — [Testtag Mac — Ablaufplan](2026-07-22-testtag-mac.md):
  Ablauf der Mac-Messreihe (Vorbereitung für sigma_floors und Enrollment).
- **2026-07-22** — [sigma_floors aus einer echten Messreihe](superpowers/reports/2026-07-22-sigma-floors-ergebnis.md):
  Gemessene, versionierte sigma_floors in `config.yaml` (Ablösung der lokalen
  Werte, gegen die die alte Baseline fälschlich rechnete).
- **2026-07-23** — [Golden-Backstop](2026-07-23-golden-backstop.md):
  Schnittstelle zum Hardware-Block — welche Szenen an der Box aufzunehmen
  sind und wie sie als versionierte Segmentierungs-Goldens ins Repo kommen.
- **2026-07-23** — [Schritt 7: Metrik-Fix, phase-c-Korpus, mehrklassige Baseline](superpowers/reports/2026-07-23-phase-c-ergebnis.md):
  top1 rechnet roh gegen Label (Semantikwechsel), mehrklassiger Korpus,
  ehrliche Baseline; Rückenlage-Wächter.
- **2026-07-24** — [Windows-Eingangsprüfung + SQLite-Portabilität](superpowers/reports/2026-07-24-windows-eingangspruefung-ergebnis.md):
  Erster Windows-Lauf; SQLite-Versions-Unterschied gefixt, Tier-1-Drift
  gefunden, Schwellen-Sweep gesperrt.
- **2026-07-24** — [H-S-Drift-Attribution (arm64 ↔ x86-64)](superpowers/reports/2026-07-24-hs-drift-attribution-ergebnis.md):
  report-only — Zuordnung der Tier-1-Drift zum Plattformwechsel statt zu Code.
- **2026-07-24** — [Schwellen-Sweep — Betriebskurven (Block 2)](superpowers/reports/2026-07-24-schwellen-sweep-ergebnis.md):
  report-only — Betriebskurven (auto_accept vs. false_accept) aus
  Replay-Reports; Schwellen-ENTSCHEIDUNG erst nach Teller-Daten.
- **2026-07-24** — [stammdaten-Diagonal-Fix + sync-stammdaten](superpowers/reports/2026-07-24-stammdaten-sync-ergebnis.md):
  dritte und letzte Fundstelle der Diagonal-vs-Länge-Klasse **gefixt**
  (`stammdaten.py` rechnet seither `max(width, depth)` wie der Matcher), und
  **`sync-stammdaten --apply` ist am 2026-07-24 gelaufen** — Live-DB und
  Bundle-DBs sind post-sync. Preis: eine bewusst akzeptierte fail-safe-
  Regression (LOEFFEL-7 accept→reject), Fehlbuchungsrate bleibt 0. Enthält die
  Residual-Analyse, die den Ära-Offset der **Kalibrier-Reproduzierbarkeit**
  zuordnet (~1,3 % Skalen-Drift, Zweig K), nicht dem Sync.
  *(Korrigiert 2026-08-01: dieser Eintrag beschrieb bis dahin den Zustand VOR
  dem Dokument, auf das er zeigt — „`--apply` bleibt gesperrt".)*
- **2026-07-24** — [Arbeitsplan ab 2026-07-24](arbeitsplan-2026-07-24.md):
  aktueller Plan (Mac-first, Windows-Tag, Blöcke 1–5) — der lebende Fahrplan.
- **2026-07-31** — [`reference_stats` kennt keinen Session-Begriff](2026-07-31-reference-stats-keine-sessions.md):
  zwei Einlern-Sessions desselben Artikels verschmelzen still zu einem σ
  (Basis für `sigma_eff`) — vor dem Neu-Einlernen ALLE Altreferenzen löschen.
- **2026-07-31** — [Ablaufzettel: Enrollment-Session in der Sandbox](2026-07-31-ablauf-enrollment-session.md):
  ausgeschriebene Befehlsfolge (init-db → 40× create-article → Qt-Einlernen),
  je Schritt Bildschirm-Kontrolle und Kamera-Öffnen/-Schließen. Zum Ausdrucken.
- **2026-07-31** — [Baseline trägt `code_fingerprint` von vor der Messpfad-Runde](2026-07-31-baseline-code-fingerprint.md):
  Befund — ohne Wirkung auf `--check`, aber `--changed-only` rechnet mehr neu
  als nötig. Nichts geändert, kein Re-Baselining.
- **2026-07-31** — [Isolierter Testbestand `--sandbox NAME`](2026-07-31-sandbox-isolierter-db-stand.md):
  fünf Schreibpfade nach `data/sandbox/<name>/`, Kalibrierung bleibt geteilt
  (daher Sperren); enthält die bekannte Einschränkung `corpus/build.py:117`.
- **2026-08-01** — [Fixpunkt-Test: trennt das Scoring ohne Positionseffekt?](2026-08-01-fixpunkt-test-scoring.md):
  15/15 Top-1 korrekt, aber nur 3 ACCEPT — der Margin bricht mit der
  Kandidatensetgröße ein, nicht mit der Artikelähnlichkeit.
  **Zwei Nachträge:** MESSER-2 UND MESSER-6 sind Duplikate von MESSER-5
  (physisch geprüft) — der Bestand hatte **13 statt 15** Objekte; die Duplikate
  kosteten aber keinen einzigen ACCEPT. Befund 2 („Hebel ist der Vorfilter")
  ist **widerlegt** — siehe Simulation vom selben Tag.
- **2026-08-01** — [NEGATIVBEFUND: Breitenprofil w(s) wird NICHT gebaut](2026-08-01-wprofil-negativbefund.md):
  w(s) trennt hervorragend (Median 16,1 σ gegen 1,3–1,8 σ der Farbmerkmale),
  rettet aber nur 4 der 12 AMBIGUOUS — und 0 ab σ_floor 1,0 mm, wo der
  Betriebs-Floor geschätzt liegt. **Frage entschieden, nicht neu aufmachen.**
  Enthält zwei Prämissen-Korrekturen (keine Längendopplung im Profil;
  `area_mm2`/`aspect_ratio` sind keine Scoring-Merkmale) und den Übertrag:
  das Problem sitzt in der Score-Aggregation. **Zwei Nachträge:** MESSER-2,
  MESSER-5 und MESSER-6 sind DASSELBE Objekt — die „Entartung des Trios" war
  vollständig ein Datenfehler, es bleibt kein entartetes Paar. Kernaussage
  unberührt.
- **2026-08-01** — [Drei widerlegte Thesen zum Scoring (Simulation)](2026-08-01-scoring-simulation-widerlegte-thesen.md):
  169 Leave-one-out-Fälle über 13 echte Artikel, 103 Varianten. **Keine
  Scoring-Änderung.**
  `log_score` IST bereits eine gewichtete Summe, solange alle Kandidaten alle
  Merkmale tragen (im Produktivbestand mit Altreferenzen gilt das NICHT, und
  eine unnormierte Summe bevorzugt dort Kandidaten mit LÜCKEN). Vorfilter-
  Verschärfung tötet den wahren Artikel und erzeugt konkurrenzlose
  Falschsieger (k_safe 166 → 35). Farbe ist kein toter Ballast. Ergebnis der
  Runde ist `scripts/simulate_scoring.py` — reproduziert `matcher.match()`
  bit-identisch. Offen bleibt der Kern: 127 von 169 Fällen AMBIGUOUS, acht von
  dreizehn Artikeln ohne ein einziges ACCEPT (Korrektur 2026-08-01, im
  Dokument als Nachtrag vermerkt).
- **2026-08-01** — [Duplikatprüfung gehört VOR jede Analyse](2026-08-01-duplikatpruefung-methode.md):
  Methodenempfehlung nach zwei übersehenen Duplikaten. Profildistanz-Scan über
  w(s), Kennzahl `d/σ` (nicht `d`), **Schwelle d/σ < 2,0 = physisch prüfen** —
  und die Lücke in der sortierten Liste lesen, nicht nur die Zahl. w(s) taugt
  nicht als Scoring-Merkmal, aber hervorragend als Duplikat-Detektor.
- **2026-08-01** — [Block A: Unabhängigkeitsannahme / Kovarianz](2026-08-01-blockA-kovarianz.md):
  **Keine Kovarianz-Korrektur.** Korrelation existiert, aber schwach und nur im
  Farbblock (effektiver Rang 6,83/8). Mahalanobis kostet 5 top1 und 30 k_safe;
  regularisiert bewegt es 0 Nullartikel. Enthält die Merkregel
  **Rauschkorrelation innerhalb eines Artikels ≠ z über alle Kandidaten** — die
  motivierende 0,73 war über die falsche Grundgesamtheit gerechnet (richtig: −0,15).
- **2026-08-01** — [Block B: Paarweises Scoring](2026-08-01-blockB-paarweises-scoring.md):
  **Nicht gebaut, aber nicht widerlegt.** Der Nachschlag ändert die Reihenfolge
  nicht (Kontrolle B4 mit fixierter Reihenfolge ist kennzahlengleich) — reine
  Abstandsoperation. Einziger Ansatz bisher, der nichts verschlechtert
  (k_safe +2, 78 % statt 93–98 % Schwellenanteil); nicht gebaut, weil 13 Fälle
  bei n≈13 Rauschen sind. Erster Wiederaufnahme-Kandidat nach der Windows-Box.
  Enthält den Mechanik-Befund: **die Enrollment-Streuung des BEDRÄNGERS bestimmt
  die Margin** (σ_hu 0,03 gegen 0,84 erklärt MESSER-5 0/13 gegen MESSER-7 7/13).
- **2026-08-01** — [Enrollment-Streuung bestimmt die Margin der Nachbarn](2026-08-01-enrollment-streuung-bedraenger.md):
  **Für das Windows-Neu-Enrollment relevant.** Aus der Formel hergeleitet:
  `z = d/sigma_eff` benutzt die Streuung des jeweiligen KANDIDATEN, also ist ein
  weit eingelernter Artikel ein klebriger Bedränger und drückt die Margin seiner
  Nachbarn. Prüfkriterium **σ_enroll > σ_floor → neu einlernen statt übernehmen**;
  9 von 13 Artikeln überschreiten (hu_log 6×, delta_e_center 4×). Reichweite
  bewusst offen (1 von 6 Paaren betroffen, n=13). Das Diagnoseblatt zeigt den
  Floor NICHT — Vorschlag notiert, nicht umgesetzt.
- **2026-08-01** — [Block D: `sigma_eff` als Stellgröße](2026-08-01-blockD-sigma-eff.md):
  **Keine Änderung.** D0 (robust Median/MAD) verworfen — entschärft 9 von 13
  Floor-Überschreitungen, erzeugt 10 neue, k_safe 165→154; enthält die
  **Schwerschwanz-Korrektur** zur früheren Zweiteilung „Ausreißer oder
  Artikeleigenschaft". D2/D4/D5 verworfen (D4 bestätigt die
  Vergleichbarkeitssorge: k_safe 130). **D1/D3 halten** — top1 169/169,
  k_safe 168, wirken aufs Ranking statt auf ACCEPT. D7 schließt die
  w(s)-Gewichtslücke.
- **2026-08-01** — [Block D6: die `feature_weights` sind ungeprüft](2026-08-01-blockD6-gewichtsschema.md):
  Gleichverteilte Gewichte dominieren das heutige Schema in top1, ACCEPT UND
  k_safe gleichzeitig; Ø höher zu gewichten schadet; α=32 schadet in jedem
  Schema. **Gleichrangig daneben:** Maximum aus 20 Zellen bei n≈13, neun Fälle
  Unterschied, Überanpassungsgefahr. Keine Config-Änderung.
- **2026-08-01** — [Block D8: Tiebreaker bei AMBIGUOUS](2026-08-01-blockD8-tiebreaker.md):
  **Nicht gebaut.** Struktureller Vorteil BESTÄTIGT — im Tiebreak kann kein
  Dritter nachrücken, die Sonde löst sich symmetrisch 13/13, die 12,47 σ werden
  umgesetzt. Und: nicht unterscheidbar von „Margin-Gate abschaffen" (ein Fall
  Vorsprung gegenüber dem Nullmodell). Fehlerrate strukturell an die
  Top-2-Rangfehlerrate gekoppelt.
- **2026-08-01** — [ABSCHLUSS der Scoring-Runde](2026-08-01-abschluss-scoring-runde.md):
  **Hier anfangen, wer die Runde nachvollziehen will.** Sechs Ansätze, über 250
  Varianten, keine einzige Änderung. Das methodisch wertvollste Ergebnis ist die
  Gegenprobe **äquivalente Schwelle + Mengenüberlappung** — sie hat sechs von
  sechs Scheingewinnen als verkleidete Schwellensenkung entlarvt. Enthält die
  drei Wiederaufnahme-Kandidaten (D8, B2, D1/D3) und was die Datenbasis leisten
  müsste, damit die Fragen entscheidbar werden.
- **2026-08-01** — [`analysis.py` liest `sigma_floors` ohne `_FLOOR_KEY`](2026-08-01-analysis-floor-key-befund.md):
  **gefixt am 2026-08-01.** Die vier Farbmerkmale bekamen in
  `_analysis_discriminability` Floor 0,0 → Trennschärfen überhöht, bei
  1-Shot-Artikeln Werte um 10¹⁰. Folge war nicht nur eine falsche Zahl: die
  nach Zeilenmaximum sortierte Matrix zeigte oben die Artefaktzeilen und
  verbarg unten die real schwierigen Paare (`MESSER-5/7`, `GABEL-10/14`,
  `LOEFFEL-2/5`). Lauf `20260801-140818` ist neu gerechnet nach
  `20260801-140818-floorfix`; die alte Fassung bleibt als Beleg stehen.
  Messpfad, Entscheidungen und Korpus waren nie betroffen, die Analyse-Skripte
  auch nicht (sie nutzen `matcher._sigma_floor`).

## Referenz (nicht chronologisch)

- [architektur.md](architektur.md) — zweistufige Pipeline, Modulgrenzen, Messpfad.
- Pläne/Specs: [superpowers/plans/](superpowers/plans/), [superpowers/specs/](superpowers/specs/).
