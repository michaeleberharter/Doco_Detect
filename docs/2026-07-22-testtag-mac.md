# Testtag Mac — Ablaufplan (2026-07-22)

> **Für eine Sitzung ohne Vorkontext:** Zuerst lesen —
> `docs/superpowers/reports/2026-07-21-vorfilter-laengliche-artikel-ergebnis.md`
> (Vorfilter-Fix Option A + Akzeptanz-Schicht) und den Übergabebericht des
> Regressions-Korpus (`2026-07-20-corpus-harness-abschluss.md`). Im README:
> Abschnitte „Scoring", „Testphase" und „Welche Config repliziert Tier 2?".

## Lage

Der Vorfilter-Fix (Länge statt Diagonale für längliche Artikel) ist gemerged;
Tier-2-Baseline: 46/60 top1, 56/60 top3, 24/60 auto_accept, **0/24
false_accept**. Der Harness ist grün: Tier 1 129/129 (Messwerte), Tier 2
60/60 (Entscheidungen, via Golden + Akzeptanz-Schicht
`corpus/accepted_deltas/`). Neu: `analyze-floors` (CLI) wertet Messreihen aus
und liefert den fertigen `sigma_floors:`-YAML-Block; geklärt ist, dass Tier 2
mit der **aktuellen** `config.yaml` rechnet — ein Floor-Eintrag erzeugt also
erwarteten DRIFT auf voraussichtlich allen 60 historischen Bildern. Dieser
Mac ist die Baseline-Maschine (Harness hier gebaut) — heute gibt es keinen
Plattform-Drift; die Windows-Eingangsprüfung folgt am Freitag.

## Bereits erledigt (vor diesem Plan)

Die **Löffel sind am Mac frisch eingelernt** — damit stehen Session-Setup
(Hintergrund, Kalibrierung) und Kamera-Konfiguration, und die frühere Frage
„Halten die Windows-Farbreferenzen am Mac?" ist gegenstandslos: alle
Referenzen der heutigen Cross-Tests stammen aus derselben Mac-Session. Der
frühere Sanity-Check entfällt.

**Direkte Konsequenz:** Der Kamera-Zustand, unter dem eingelernt wurde, ist
ab jetzt **eingefroren** — `lock_exposure`, `lock_white_balance`,
`exposure`, `focus_value`, `camera.index`, Auflösung: nichts davon heute
noch ändern. Jede Änderung der Kamera-Antwort würde die frischen
Farb-Referenzen sofort wieder invalidieren und das Einlernen von vorn
erzwingen.

## Invarianten (gelten den ganzen Tag)

- **false_accept bleibt 0.** Kein Review darf einen neuen automatischen
  Fehlbucher akzeptieren — ein solcher Fall stoppt den Tag.
- **Kamera-Settings und Aufbau sind eingefroren** (siehe oben). Box und
  Kamera nicht bewegen; falls doch unvermeidlich: Hintergrund + Kalibrierung
  neu, und die Farb-Referenzen kritisch prüfen.
- Original-Goldens werden **nie** verändert; der Korpus ist append-only.
  Heute entsteht **phase-c** mit vollem Session-Snapshot.
- Keine Schwellen anfassen (`max_z_accept`, `min_llr_margin`, Gewichte,
  `top_k`) — heute werden ausschließlich die `sigma_floors` durch gemessene
  Werte ersetzt.
- Beleuchtung während der gesamten Session nicht verändern.

## Ablauf

1. **Messreihe:** EIN Löffel, 15–20 Auflagen (jedes Mal anheben, drehen,
   leicht versetzen), jeweils identifizieren. Die Entscheidungen sind
   egal — nur die `measured`-Blöcke zählen, und die sind
   referenz-unabhängig. Bonus dieser Konstellation: Enrollment und
   Messreihe liegen in **derselben Session** — die Streuung der Messwerte
   um den Enrollment-Mittelwert (`reference_stats`) ist damit direkt und
   unverfälscht ablesbar, genau der ursprüngliche Wiederholbarkeits-Gedanke.
2. **Floors bestimmen und eintragen:** `analyze-floors` über die
   Messreihe, YAML-Block in `config.yaml` übernehmen. Dabei die
   Ø-Streuung prüfen: ~2–3 mm Std bestätigt die Auflage-Rauschen-Erklärung
   des −3,16-mm-Residuums der Ex-Kills (Vorbefund aus phase-b: 3,19 mm
   Spannweite bei nur n=4 — nicht überinterpretiert, heute kommt die
   belastbare Zahl).
3. **Korpus-Lauf nach dem Floor-Eintrag:** voller Tier-2-Lauf (der
   Config-Fingerprint invalidiert den Cache), erwarteter DRIFT auf bis zu
   60 Bildern. Review mit zwei Checks: (a) **kein neuer False-Accept**;
   (b) jeden **neuen** Auto-Accept einzeln gegen das wahre Label prüfen —
   weitere Floors bedeuten kleinere z-Werte, die Gates öffnen sich.
   Danach Delta-Datei (`corpus/accepted_deltas/2026-07-22-floors.json`,
   mit Begründung je Bild) + neue Tier-2-Baseline.
4. **FOV-Test:** größten Teller einlegen — die Kontur darf den Bildrand
   nicht berühren; bei Clipping den 4:3-Modus **nur ansehen, nicht
   umstellen** (Auflösungswechsel wäre ein Kamera-Eingriff und würde die
   heutigen Referenzen invalidieren — 4:3 ist eine Entscheidung für die
   finale Windows-Konfiguration). Nur Teller, die im aktuellen Modus
   vollständig ins Bild passen, kommen heute in die DB. Fahnenhöhe der
   Teller mit dem Messschieber messen (`height_mm` — echte Messwerte,
   keine Schätzung).
5. **Einlernen:** Gabel, Messer, FOV-taugliche Teller — `create-article`
   (längliche Artikel: kurz prüfen, dass width/depth statt diameter
   gesetzt wird), danach je 8 Enroll-Shots mit Rotationen (Reflex-Streuung
   des Stahls muss in sigma_enroll landen). Falls beim Löffel-Einlernen
   nur eine Teilmenge der ~15 Alt-Löffel erneuert wurde: vor den
   Cross-Tests entscheiden, was mit den übrigen passiert (aus der Live-DB
   nehmen oder ihre bekannte Verzerrung beim Bewerten einpreisen).
6. **Cross-Tests:** jeden Artikel ~5× in wechselnden Lagen
   identifizieren, **jedes** Ergebnis bewerten (bei „Falsch" den wahren
   Artikel angeben — das ist das Futter für den Korpus). Erwartungen:
   sinkende Margins / mehr AMBIGUOUS sind Design (Fisher-Kompression bei
   wachsendem Kandidatenset, Empfehlung b im Ergebnisdokument); der wahre
   Artikel kann im Kandidatenset, aber wegen `top_k=3` in der UI
   unsichtbar sein — dann zählt „Falsch + wahren Artikel angeben".
   Spannend: Löffel↔Gabel↔Messer gleicher Länge (der Vorfilter nutzt nur
   die Länge — die Trennung muss das Scoring leisten) und die
   Ø-Trennung der Teller.
7. **Abschluss:** Korpus-Builder über die bewerteten Reports (phase-c
   inkl. Hintergrund, Kalibrierung, DB-Stand, Config als Snapshot), neue
   Tier-2-Baseline auf dem mehrklassigen Stand, alles committen und
   pushen.

## Fragen, die heute Antworten bekommen

- Ist das −3,16-mm-Residuum Auflage-Rauschen? (Schritte 1–2)
- Passt der größte Teller ins FOV — und welche Teller kommen heute in die
  DB? (Schritt 4)
- Wie gut trennt das Scoring längliche Artikel gleicher Länge?
  (Schritt 6)

## Danach (nicht heute)

Freitag: Windows-Eingangsprüfung (pullen, Korpus kopieren, Manifest
verifizieren, beide `--check`-Läufe; DRIFT dort ist plattformbedingt) und
Entscheidung, welcher Rechner ab dann die kanonische Baseline-Maschine ist —
inklusive der 4:3-Frage aus Schritt 4, falls der größte Teller im 16:9-Modus
clippt. Nächste Woche: Schwellen-Sweep als eigener Auftrag
(Report-only-Replay über Config-Varianten), danach ggf. Breite als
Scoring-Merkmal für längliche Artikel.
