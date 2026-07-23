# Arbeitsplan ab 2026-07-24 — Mac-first, Windows wenn verfügbar

> **Für eine Sitzung ohne Vorkontext:** Stand nach Abschluss des
> Schritt-7-Auftrags (phase-c, Metrik-Fix, mehrklassige Baseline) —
> siehe `docs/superpowers/reports/2026-07-23-phase-c-ergebnis.md` und
> die dort verlinkten Vorgänger. Korpus: 3 Phasen, ~170 Bilder,
> mehrklassig. Baseline ehrlich (top1 roh gegen Label). Backstop: 19
> versionierte Goldens, skip→fail. Suite ~520 Tests. False Accepts
> die ganze Woche: 0.

## Leitplanken (unverändert gültig)

- Keine Schwellenänderung ohne Daten; `min_llr_margin=2.0` und
  `max_z_accept=3.5` stehen. Der Sweep (unten) ist der einzige
  legitime Weg, daran zu drehen.
- Messpfad gesperrt; Änderungen nur als eigener Auftrag mit
  Harness-Verifikation.
- Jede DB-/Config-Änderung, die Entscheidungen beeinflusst, läuft
  über den Drift-Zyklus (Review → Delta → Baseline).
- Melde-Punkte sind blockierend. Zahlen werden belegt, nicht erzählt.

---

## Block 1 — Reste des Mac-Zyklus (Mac-Rig, ~1 h, zuerst)

Voraussetzung: Schritt-7-Push ist durch. Box steht noch.

1. **GABEL-1: erledigt, KEIN Re-Enrollment.** Die Session-Mix-Hypothese
   ist widerlegt (E1 im phase-c-Ergebnisdokument, Abschnitt 5): alle 9
   Shots stammen aus einer Session, die zwei Gate-Rejects sind
   **Rückenlage** (Out-of-Distribution-Pose), das z-Gate arbeitet korrekt.
   Produktentscheidung steht: Rückenlage ist nicht buchbar, Bedienregel
   „Vorderseite nach oben". Die zwei Reject-Goldens bleiben als
   Rückenlage-Wächter im Korpus (Manifest-`notiz`). **Offen bleibt allein
   die Betriebsablauf-Frage** (unten unter „An DO&CO"): soll die
   Rückenlage buchbar sein? Falls ja = Schema-Arbeit (Pose als eigene
   Dimension), nicht heute.
2. **stammdaten.py-Fix + `sync-stammdaten --apply` — eigener priorisierter
   Auftrag, NICHT heute Nacht.** E2 hat einen echten Defekt gefunden, nicht
   nur eine Empfehlung: `stammdaten.compute_sync` rechnet den Nominalwert
   als `hypot(width, depth)`, der Vorfilter nutzt seit dem 2026-07-21
   `max(width, depth)`. Das Vorzeichen des mittleren Abstands kippt dadurch
   (−0,86 mm gemeldet vs. +1,15 mm echt), ein `--apply` zöge die Stammdaten
   in die **falsche** Richtung. **Dritte Fundstelle der Diagonal-vs-Länge-
   Klasse** (nach Vorfilter und Flächen-Check). Auftrag:
   (a) `stammdaten.py` auf dieselbe Nominalfunktion wie der Matcher
   umstellen (`hypot`→`max` für längliche Artikel; idealerweise beide auf
   `matcher._nominal_size_mm` zusammenführen, damit es keine vierte
   Fundstelle gibt), mit Test;
   (b) danach `sync-stammdaten --apply` MIT vollem Drift-Zyklus (Vorfilter-
   Fenster verschieben sich → erwarteter Tier-2-Drift, Review, Delta,
   Baseline). **Datenbegründung:** der korrekte Sync hätte den einzigen
   Vorfilter-Kill des Tages verhindert (LOEFFEL-4, 7,21 mm → 3,93 mm bei
   6,0 mm Toleranz). Bis dahin bleibt `--apply` gesperrt (so auch in
   CLAUDE.md notiert).
3. **Korpus-Kopie ziehen** (USB/Cloud) — jetzt, wo er konsistent
   ist (173 Bilder, 3 Sessions, beide Gates grün). Manifest-Verifikation
   dokumentieren. Das ist die Windows-Vorbereitung, egal wann Windows kommt.
4. Danach darf die Box abgebaut werden — alles Weitere ist
   hardwarefrei bis zur nächsten Enrollment-Session (Servierlöffel/Glas/
   Rückenlagen-Serie = eigene Session mit eigenem Snapshot).

**An DO&CO (Betriebsablauf-Entscheidung, kein Code):** Soll die Rückenlage
buchbar sein? Heutiger Stand: nein, Bedienregel „Vorderseite nach oben".
Wird sie im Ablauf gebraucht, ist das Schema-Arbeit (Pose als eigene
Dimension neben dem Artikel) — die Referenzen dürfen NICHT einfach um
Rückenlagen-Shots ergänzt werden, das machte sie bimodal und verwässerte
die Zwillingstrennung (der Effekt, den Abschnitt 4.4 des Ergebnisdokuments
an den vier 213-mm-Messern zeigt).

## Block 2 — Der Schwellen-Sweep (Schreibtisch, Mac, ~1 Tag CC-Arbeit)

**Das wichtigste offene Implementierungsstück.** Alle Voraussetzungen
existieren seit dieser Woche: mehrklassiger Korpus, gemessene Floors,
lauf-scoped Replay-Verzeichnisse, corpus-report --compare.

Auftrag an Claude Code (Kurzform; Detail-Prompt bei Bedarf):
- Report-only-Replay-Modus: Korpus unter systematisch variierten
  matching-Werten nachspielen (min_llr_margin, max_z_accept,
  optional Gewichte, softmax_temperature) — im Speicher variiert,
  config.yaml unangetastet, KEIN Gate, KEINE Baseline.
- Output je Betriebspunkt: auto_accept_rate, false_accept_rate,
  top1/top3 — als Betriebskurven-Artefakt (Viz v2: auto_accept vs.
  false_accept, Pareto-Front markiert).
- Sicherheits-Invariante hart codiert: Betriebspunkte mit
  false_accept > 0 werden ausgewiesen, aber nie empfohlen.
- Abnahme: der aktuelle Betriebspunkt (2.0/3.5) muss exakt die
  Baseline-Quoten reproduzieren (Konsistenz-Anker).
- ERGEBNIS IST EIN BERICHT. Ob Schwellen geändert werden, ist eine
  separate Entscheidung mit eigenem Drift-Zyklus — Vorsicht:
  besteck-only-Korpus; Schwellen, die hier optimal sind, sind es
  nach den Tellern (Windows) womöglich nicht mehr. Deshalb:
  Sweep-Infrastruktur JETZT bauen und verstehen, Schwellen-
  ENTSCHEIDUNG erst nach Teller-Erweiterung.

## Block 3 — Breite als Scoring-Merkmal: Analyse-Vorstufe (Mac, ~2 h)

Die Messer↔Löffel-Trennung lief über Rundheit/Hu — sie hat gehalten,
aber ohne Marge-Reserve-Beleg. Die minAreaRect-Breite wird mit
<2 mm Rauschen gemessen und nirgends gescort (bekannter Befund).

Vorstufe OHNE Messpfad-Eingriff:
- Aus den phase-c-Reports (measured-Blöcke) die Breiten-Verteilung
  je Artikel extrahieren; Trennschärfe-Analyse (Fisher-Ratio) Breite
  vs. bestehende Merkmale für die realen Verwechslungspaare.
- Bericht: würde ein width_mm-Merkmal die Zwillings-Margins heben?
  (Erwartung: Löffel↔Löffel kaum — gleiche Breite; Klassen-Trennung
  ja, aber die ist schon perfekt. Ehrliches Ergebnis kann sein:
  lohnt SICH NICHT. Dann ist der Punkt datenbegründet geschlossen.)
- Nur wenn die Analyse klar positiv: Implementierungs-Auftrag als
  eigener Schritt (ein sigma_floor, ein Gewicht, Drift-Zyklus).

## Block 4 — Kleinkram-Sammelauftrag (Schreibtisch, ~2 h CC)

Aufgelaufene offene Punkte, keiner eilig, zusammen ein Auftrag:
- **Session-Artefakte archivieren statt überschreiben** (aus Schritt 7):
  `capture-background` und die Kalibrierung müssen den bestehenden Stand
  vor dem Schreiben mit Zeitstempel wegsichern (`background-<ts>.png`),
  statt ihn zu ersetzen. Dritter Überschreiben-statt-Verschieben-Vorfall;
  er hat die 18 Bilder der LOEFFEL-14-Messreihe korpus-unfähig gemacht
  (phase-c-Ergebnisdokument, Abschnitt 3.2). Die CLAUDE.md-Regel
  „Destruktives immer als Verschieben nach `backups/`" muss auch für die
  Pipeline selbst gelten, nicht nur für Mensch und Ad-hoc-Skript.
- **Ära-Kennzahl ersetzen** (aus Schritt 7): `adopt_goldens.py::era_median`
  (Median-|diff| gegen Schranke 6) ist bei schwarzer Box strukturell
  blind — die leere Fläche dominiert den Median. Gemessen: 0 bzw. 1 bei
  real 18/18 nicht reproduzierbaren Messungen. Kandidaten: hohes Perzentil
  (P99) statt Median, oder maskierte Differenz um die Objektregion. Bis zum
  Fix gilt: ihr grünes Licht ist kein Beweis, der Beweis ist ein
  Tier-1-Lauf gegen die Session-Goldens.
- runs/-Hygiene entscheiden (tmp_path vs. Selbst-Aufräumen vs.
  _test-Präfix) und umsetzen — drei Waisen/Abend sind genug Beweis.
- Auflösungs-Wächter: Live-Auflösung gegen image_width/height aus
  calibration.json beim Capture hart prüfen (Fixture liegt in
  data/quarantine/ — der 1080p-Vorfall vom 22.).
- camera.py: verhandelte Auflösung IMMER loggen, nicht nur warnen.
- Unmarkierter Skip test_floor_analysis.py:219 → Marker + Grund.
- accuracy_top1_verdict: prüfen ob als Zusatzfeld sinnvoll oder weg.
- CLAUDE.md-Konsolidierung: die Wochen-Regeln (Melde-Punkte,
  Tripel-Vergleich, which-python, Verschieben-statt-Löschen) sind
  über mehrere Commits verstreut — einmal zusammenziehen.

## Block 5 — Windows-Tag (sobald PC verfügbar; ~halber Tag)

Reihenfolge bindend:
1. **Umgebungs-Vergleich VOR allem:** Python/numpy/cv2/scipy gegen
   die Mac-Pins aus metrics.json/requirements.lock. Abweichungen
   erst angleichen oder bewusst dokumentieren — sonst ist
   Plattform-Drift nicht von Versions-Drift trennbar.
2. **Eingangsprüfung:** pullen, Korpus-Kopie einspielen, Manifest
   verifizieren, beide --check-Läufe. Erwartung: Tier-1-DRIFT
   möglich (Float-Verhalten), Tier 2 folgt daraus. Dokumentierter
   Ablauf: Review → ggf. Plattform-Delta → Entscheidung kanonische
   Baseline-Maschine (vermutlich Windows, da Produktionsnähe).
3. **Geometrie-Entscheidung (P1):** Kamerahöhe erhöhen / 4:3 /
   Weitwinkel — Ziel: größter DO&CO-Teller passt vollständig.
   REIHENFOLGE-MINE: erst camera_height_mm in config.yaml setzen,
   DANN kalibrieren. MARKER-MINE: realen Marker mit Messschieber
   messen (Bestand: 72,5 mm real vs. 136,0 in config!) und
   marker_size_mm exakt setzen.
4. **Neue Ära Windows:** Hintergrund, Kalibrierung, Kamera-Locks
   (DSHOW — hier funktionieren sie), Exposure-Sweep. Dann
   Messreihe 15–20× → analyze-floors → Floors-Drift-Zyklus (die
   Mac-Floors gelten NICHT — anderes Rig).
5. **Golden-Backstop Windows-Ära:** Klären, ob die 19 Mac-Goldens
   als plattformübergreifende Fixtures reichen (erwartbar ja — sie
   prüfen Code, nicht Rig) oder ob eine Windows-Ära dazukommt.
6. **Teller-Enrollment** (endlich): create-article --height-mm mit
   Messschieber-Werten, 8 Shots, Cross-Tests, phase-d-Korpusbau.
7. Danach: Sweep-ENTSCHEIDUNG (Block 2) mit Teller-Daten neu
   bewerten; Stufe-2-Frage stellt sich erst, wenn die
   Konfusionsmatrix nach phase-d echte Klassen-Cluster zeigt.

## Explizit NICHT jetzt

- Stufe 2 (DINOv2): Kriterium unverändert — persistente
  AMBIGUOUS-Cluster, die klassische Merkmale nicht trennen. Die
  einzigen Cluster sind Löffel-Zwillinge; das löst auch Stufe 2
  auf Spiegelstahl kaum. Warten auf echten DO&CO-Katalog.
- Schwellen ändern vor Teller-Daten (siehe Block 2).
- Python-Upgrade (3.9 EOL): eigener Auftrag mit vollem
  Tier-1-Drift-Zyklus, frühestens nach dem Windows-Tag — nie
  nebenbei.
- UI-Ausbau, Projekthandbuch-Fertigstellung, Callgraph-Diagramm:
  wertvoll, aber hinter allem Obigen.
