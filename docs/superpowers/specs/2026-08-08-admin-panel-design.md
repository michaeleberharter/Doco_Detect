# Admin-Panel für die Qt-UI — Design

**Datum:** 2026-08-08 · **Art:** freigegebenes Design (Brainstorm-Ergebnis).
**Revision:** 2026-08-08 nach Review (sechs Punkte + Gegenvorschlag
Zugriffsweg; Belege in Anhang A).
**Umsetzung:** vier Stufen; Stufe 1 hat zwei blockierende Melde-Punkte,
jede weitere Stufe einen. Implementierungsplan folgt separat.

---

## 1. Ziel

Ein passwortgeschützter Wartungsbereich in der Qt-App: Reports auswerten,
einzelne Fälle forensisch verstehen, Artikel und Einlern-Sessions einsehen,
Fehlerursachen eingrenzen — ohne CLI und ohne Dateibrowser. Das Panel ist
eine reine **Konsumentenschicht**: es rechnet nie Pipeline oder Matcher, es
ruft bestehende Fassaden und zeigt deren Ergebnis an. Es ist View, keine
vierte Auswertungswahrheit (siehe Abnahmekriterien, Abschnitt 8).

## 2. Nicht-Ziele (bewusst ausgeschlossen)

- **Kein Schreibweg für Parameter.** Keine Schwellen, Gewichte oder
  Config-Werte setzen oder speichern — das war der Fehlermodus, der zur
  Entfernung der Streamlit-UI führte
  ([2026-08-01-streamlit-config-tab-schreibt-config-yaml.md](../../2026-08-01-streamlit-config-tab-schreibt-config-yaml.md)).
  Parameter werden nur angezeigt (Stufe 4, strikt read-only).
- **Keine bestandsverändernden Eingriffe.** Löschen von Artikeln/Referenzen
  ist aus dem Vorhaben ausgegliedert (Abschnitt 7). Die einzigen
  bestandsberührenden Aktionen des Panels sind die Session-Aktionen in
  Stufe 4 — und die rufen exakt die bestehenden Fassaden.
- **Keine Korpus-Operationen** (`corpus-run`, Baseline, Triage) — das sind
  Entwicklerwerkzeuge mit Begründungspflicht im Commit, sie bleiben CLI.
- **Keine Benutzerverwaltung/Rollen.** Ein Admin-Passwort genügt (Zweck und
  Grenzen: Abschnitt 3).
- **Keine CLAUDE.md-Änderung.** Der Zugriff läuft vollständig über
  pipeline-Fassaden (Abschnitt 4, „Zugriffsweg"); die UI-Regel gilt
  unverändert weiter.

## 3. Zugang und Passwort

- **Einstieg:** Schloss-Symbol in der Icon-Schiene (`ToolRail`), unterhalb
  der vier Arbeitsschritte, oberhalb des Zahnrads. Immer aktiv — der
  Admin-Bereich muss gerade dann erreichbar sein, wenn die Kamera fehlt
  (Diagnose).
- **Was das Passwort ist — und was nicht:** Der Passwort-Hash ist
  **Fehlklick-Schutz gegen versehentliches Betreten, keine
  Sicherheitsgrenze.** DB, Config und Captures liegen unverschlüsselt
  direkt daneben; wer Dateisystem-Zugriff hat, braucht das Panel nicht.
- **Zusicherung:** Das Schloss gated **nichts, was während einer
  Box-Session gebraucht wird.** Identifizieren, Bewerten/Korrigieren,
  Einlernen, Hintergrund aufnehmen und Kalibrieren bleiben vollständig
  außerhalb des Admin-Bereichs.
- **Mechanik:** Das Passwort wird nie im Klartext gespeichert, nur als
  PBKDF2-HMAC-SHA256-Hash (stdlib `hashlib.pbkdf2_hmac`, 200 000
  Iterationen; Algo, Iterationszahl und Salt stehen mit in der Datei) in
  einer eigenen gitignorten Datei **`config/admin_auth.local.json`**.
  Bewusst PBKDF2 statt scrypt (Befund 2026-08-10): `hashlib.scrypt`
  fehlt bei LibreSSL-Builds (macOS-Systempython), und die Auth-Datei
  muss auf Mac UND Windows-Box mit demselben Verfahren prüfbar sein —
  ein Algorithmus auf beiden Plattformen. Bewusst NICHT in
  `config.local.yaml`: die müsste per YAML-Roundtrip neu geschrieben werden
  und verlöre Kommentare — dieselbe Klasse Nebenwirkung wie beim
  Streamlit-Befund.
- **Erster Start** (Datei fehlt): Dialog „Admin-Passwort festlegen"
  (zweimal eingeben), Datei wird angelegt.
- **Recovery bei vergessenem Passwort:** `config/admin_auth.local.json`
  löschen → beim nächsten Öffnen greift der Erster-Start-Dialog und das
  Passwort wird neu vergeben. Wird im README dokumentiert.
- **Falsches Passwort:** Fehlertext im Dialog, kein Lockout (Schutzzweck
  siehe oben).
- **Modul:** `docodetect/admin_auth.py`, Qt-frei
  (setzen/prüfen/ist-konfiguriert), damit ohne Fenster testbar.
- `.gitignore` bekommt `config/admin_auth.local.json`.

## 4. Architektur

- **Eigenes Fenster, eigenes Paket `docodetect/ui_qt/admin/`:**
  `admin_window.py` (Fenster-Gerüst) plus `pages/` mit einem Modul je
  Seite. Das Hauptfenster (947 Zeilen) bekommt nur den Schloss-Knopf und
  den Öffnen-Aufruf. Bedienoberfläche und Wartungsbereich teilen keinen
  Zustand — mit Ausnahme von genau zwei **einseitigen Meldungen
  Hauptfenster → Admin**: dem Kamera-Zustand (Signal) und einem
  Voll-Frame auf Anforderung (`request_full_frame`-Muster, Stufe 4).
  Kein Rückkanal, kein gemeinsames Objekt.
- **Navigation:** Sidebar links (Status / Reports / Analyse / Artikel /
  Diagnose), rechts ein `QStackedWidget` je Seite. Nicht-modal, ein Fenster
  zur Zeit (erneutes Öffnen fokussiert das bestehende).
- **Theme:** dieselbe Stylesheet-/`retheme()`-Mechanik wie das
  Hauptfenster; neues Schloss-Icon in `icons.py` (`_BUILDERS`).
- **Threads und Kamera — feste Regel:** Der Kamera-Alleinbesitz bleibt beim
  `CameraWorker` des Hauptfensters; das Admin-Fenster besitzt keine Kamera
  und öffnet keine. Alle Admin-Jobs laufen **seriell** über das vorhandene
  `PipelineWorker`-Muster (Pipeline-Objekte werden IM Job konstruiert,
  SQLite-Thread-Affinität) — **kein zweiter QThread-Pfad.** Der
  QThread-Komplex ist Timo-eigen und wird in diesem Vorhaben nicht
  angefasst. Für den Segmentierungs-Test (Stufe 4) nutzt das Panel die
  Frame-Quelle des Hauptfensters (`request_full_frame`-Muster); ohne
  Kamera ist die Seite deaktiviert mit Hinweis.
- **Sandbox:** Das Panel arbeitet auf der Config, mit der die App läuft —
  in der Sandbox also auf dem Sandbox-Stand. Bestandsberührende
  Session-Aktionen (Stufe 4) zeigen die betroffenen Pfade im
  Bestätigungsdialog an.

### Zugriffsweg (die UI-Regel bleibt unverändert)

Das Panel importiert ausschließlich die in CLAUDE.md erlaubten Module
(`pipeline.py` / `calibration.py` / `camera.py` / `database.py`) — **keine
CLAUDE.md-Änderung.**

- **Stufe 1** braucht dazu **drei additive Read-only-Fassaden in
  `pipeline.py`**, gebaut und getestet in **Melde-Punkt 1a**: Reports
  laden (löst `paths.captures_dir` selbst auf und ruft intern
  `reporting.load_reports`), Bewertung/Verdict lesen (intern
  `reporting.judgement`/`predicted_article`) und Optik-Fingerprint lesen
  (öffentlicher Wrapper um die bestehende Modulfunktion
  `pipeline._fingerabdruck`, siehe Status-Seite). Die Schreibseite
  existiert bereits genau nach diesem Muster: `confirm_result` /
  `confirm_no_match` / `reject_result` (`pipeline.py:1064–1090`) wrappen
  `reporting.save_verdict` mit ausdrücklichem Docstring „damit UIs
  reporting.py nie direkt importieren müssen". Die Leseseite fehlt heute
  (kein `load_reports`/`judgement` in `pipeline.py`, Befund 2026-08-08) —
  die drei Fassaden sind der einzige nötige Zusatz für Stufe 1.
- **Stufe 2/3:** `analysis.py` und `enrollment_sheet.py` konstruieren
  eigene Pfade aus der Config (Belege: Anhang A) und sind damit nicht
  direkt aus der UI rufbar. Ihre Anbindung (pipeline-Fassaden bzw.
  `out_dir`-Parameter; für Altbestands-Blätter ein Wrapper um
  `build_enrollment_sheet` analog `enrollment_sheet_for_shots` /
  `persist_enrollment_sheet`) ist ein **eigener, separat zu genehmigender
  Eingriff** — fällig erst, wenn die jeweilige Stufe entblockt ist.
- **Vorgemerkter Wortlaut** für eine etwaige spätere CLAUDE.md-Präzisierung
  (nur falls je nötig, nicht jetzt): *„UI-Schichten dürfen zusätzlich reine
  Konsumentenmodule rufen, sofern das Modul keine eigene Pfadkonstruktion
  aus der Config betreibt — Pfade ausschließlich als Argument, aufgelöst
  von pipeline.py."* Belege dazu: Anhang A.

## 5. Read-only-Definition

„Read-only" in den Stufen 1–3 heißt: **keinerlei Veränderung am Bestand** —
DB, Referenzen (`data/reference/`), Captures (`data/captures/`),
Einlern-Sessions. Neuschreibungen in **Ausgabebereiche** sind davon nicht
berührt: die Passwort-Datei (Stufe 1) und Analyse-Artefakte unter
`reports/analysis/<run_id>/` (Stufe 2) sind Neuanlagen außerhalb des
Bestands, kein Bestandseingriff.

## 6. Seiten je Stufe

### Stufe 1 — Zugang, Status, Report-Forensik (fünf Seiten, zwei Melde-Punkte)

**Melde-Punkt 1a** (enthält auch die drei pipeline-Lese-Fassaden samt
Tests, Abschnitt 4 — damit steht 1b auf bereits abgenommener Basis und
die Pakete sind gleich schwer):

1. **Gerüst + Zugang:** Schloss-Knopf, Passwortdialog (inkl. Festlegen beim
   ersten Mal), Fenster mit Sidebar und leeren Seiten-Slots.
2. **System-Status:** `pipeline.get_status(cfg)` (Hintergrund/Kalibrierung
   vorhanden + Alter), DB-Pfad und -Größe, Artikel-/Referenzzahl
   (`pipeline.list_articles`), Kamera-Zustand (vom Hauptfenster gemeldet),
   Sandbox-Marker, freier Plattenplatz der Datenpartition. Dazu der
   **Optik-Fingerprint** der aktuellen Konfiguration, read-only:
   `calibration_sha256`, `background_sha256`, `features_cfg_sha256`,
   `mm_per_px`, `camera_height_mm` — die bestehende, wiederverwendbare
   Modulfunktion `pipeline._fingerabdruck` (`pipeline.py:368–394`,
   ~0,5 ms laut Docstring) über den öffentlichen Wrapper aus Abschnitt 4.
   Das ist der Wert, der vor jeder Box-Session zählt. Fehlen Kalibrierung
   oder Hintergrund, zeigt das Feld den Leerzustand („nicht kalibriert")
   statt eines Fehlers.

**Melde-Punkt 1b:**

3. **Report-Browser:** lädt die Identifikationen über die neue
   pipeline-Fassade (Abschnitt 4) **synchron im GUI-Thread** — Revision
   2026-08-11, vorher „im Worker": gemessen 9 ms für den vollen Bestand
   (23 Reports), und ein Worker-Thread wäre neben dem offenen
   Qt-Teardown-Befund
   ([ui-qt-testsuite-segfault.md](../../ui-qt-testsuite-segfault.md))
   reine Teardown-Fläche ohne Nutzen. **Neu zu bewerten**, sobald
   Box-Bestände die 500er-Obergrenze überschreiten und der
   Zeitraum-Filter spürbar nachlädt. Tabelle mit Datum,
   Entscheidung (accept/ambiguous/reject/border), Top-1-Artikel, Bewertung
   (Richtig/Falsch/unbewertet). Filter: Entscheidung, Artikel, Bewertung,
   Zeitraum. Doppelklick öffnet die Einzelreport-Ansicht.
   **Default-Verhalten bei wachsendem Bestand:** geladen werden die
   neuesten 500 Report-JSONs (nach Datum); liegen mehr vor, weist der
   Browser „n ältere nicht geladen — Zeitraum-Filter setzen" aus, und der
   Zeitraum-Filter lädt gezielt nach. Befund 2026-08-10: aktuell 23
   Report-JSONs im echten Bestand, `load_reports` darüber 9,5 ms — die
   Grenze ist Zukunftsschutz für den Box-Betrieb, keine heutige Not.
4. **Einzelreport-Ansicht:** die acht Felder aus
   [2026-08-01-einzelreport-ansicht-nachbau.md](../../2026-08-01-einzelreport-ansicht-nachbau.md)
   (Entscheidungs-Badge, Gate-Ampel max|z|/LLR-Margin/Posterior, Aufnahme +
   Kontur-Overlay via `pipeline.render_report_overlay`, Kandidatentabelle,
   z je Merkmal, Rohmesswerte, Prefilter-Kills aus `prefiltered`,
   Verdict-Zeile). Quelle: Auswahl im Browser — die „letzte
   Live-Identifikation" ist nach „Aktualisieren" der oberste
   Browser-Eintrag, denn jede Identifikation liegt als Report-JSON in
   `captures_dir`; ein dritter Meldekanal Hauptfenster → Admin über die
   zwei aus Abschnitt 4 hinaus entfällt bewusst (Revision 2026-08-11).
   Maßgeblich sind DIESE acht Felder: die zusätzlichen Panels des
   Nachbau-Dokuments (Log-Beitrags-Chart, Top-1-vs-Top-2-Kontrast,
   Fisher-Panel) sind bewusst nicht Teil von 1b — die Tabellen
   beantworten die Forensik-Frage „warum diese Entscheidung", die
   Diagramme wären eigener Aufwand mit eigener Abnahme.
5. **Prefilter-Kill-Seite:** eigene Sicht über alle geladenen Reports —
   Tabelle mit Artikel, Kill-Grund (`diameter` | `area`) und gemessenem
   Abstand zur Toleranz („um x gerissen"); Datenquelle ist die
   `prefiltered`-Liste im Report-JSON (`matcher.py:260–285`, jeder Kill mit
   Grund + Abstand). Wo ein Verdict den wahren Artikel benennt, wird
   markiert, ob **der wahre Artikel** unter den Kills war — die Auswertung
   des Fixpunkt-Tests vom 2026-08-01 (Befund 5) als stehende Sicht. Laut
   C-Serie sitzt dort das gesamte False-Accept-Risiko.
   **Umsetzung (Revision 2026-08-11):** eigener Tab neben dem Browser in
   der Reports-Sektion — „eigene Sicht, kein Filter" bleibt erfüllt,
   ohne die Sidebar aus Abschnitt 4 zu erweitern. **Offener Punkt:** die
   Wahrer-Artikel-Markierung ist bisher nur per Test-Fixture belegt —
   kein realer Report trägt ein Label. Gegen echte Daten geprüft ist sie
   erst nach der nächsten Bewertungsrunde, und genau auf diese
   Markierung kommt es bei der False-Accept-Analyse an.

### Stufe 2 — Auswertung

**Vorbedingungen (blockierend):**

- **Listbarkeits-Kriterium implementiert:** Als Lauf-Historie gelten nur
  Ordner unter `reports/analysis/` mit `report.md` **und** `metrics.json`;
  alle anderen werden als „ungültig, n Stück" ausgewiesen, nie
  verschwiegen. Befund 2026-08-08: 22 Ordner, 15 gültig, 7 ohne beide
  Dateien (3× `enrollment*`-Blattausgaben, 4× `tail-*`-Skriptausgaben —
  andere Artefakt-Typen im selben Baum; ein `_invalid`-Analogon existiert
  dort nicht).
- **pipeline-Fassade für `run_analysis`** (Quell- UND Zielpfad als
  Argument) — separat zu genehmigender Eingriff, siehe Zugriffsweg und
  Anhang A.

Die Klärung der 19 Einträge in `runs/_invalid/` des **Korpus**-Baums
(Cross-Run-Effekte ja/nein) ist ein eigener offener Vorgang und blockiert
das Panel nicht — das Panel zeigt den Korpus-Baum nie an.

6. **Analyse-Lauf:** Ordnerwahl (Default `captures_dir`) + Run-ID, Lauf im
   Worker mit Fortschrittsanzeige; danach und für bestehende gültige Läufe:
   Artefakt-Betrachter (PNG-Blättern, `report.md` als Text). Kein
   `--publish` aus der UI — Archivieren bleibt bewusst CLI (versioniertes
   Verzeichnis).
7. **Bewertungs-Übersicht:** Aggregation der Verdicts aus den geladenen
   Reports (richtig/falsch/unbewertet je Artikel, Gesamtquote). Reine
   Zählung auf Anzeige-Ebene, keine Kennzahlen-Nachrechnung.

### Stufe 3 — Artikel & Sessions (rein anzeigend)

**Vorbedingungen (blockierend):**

- **Diagnoseblätter:** blockiert, solange `reference_features.image_path`
  überwiegend NULL ist — Stand 2026-08-08 auf der Produktiv-DB: **334 von
  359 Zeilen NULL**, die Blatt-Felder 1–3 wären für ~93 % des Bestands
  leer. Entblockt erst nach dem Neu-Einlernen mit Bildern (realistisch an
  der Windows-Box, ~ab Ende August 2026).
- **pipeline-Wrapper für Altbestands-Blätter** (`build_enrollment_sheet`)
  — separat zu genehmigender Eingriff, siehe Zugriffsweg.

8. **Artikelliste:** `pipeline.list_articles` mit Referenzzahl und
   Nominalmaßen; je Artikel das **Diagnoseblatt** (über pipeline-Fassaden
   gerendert, im Worker; Cache über den `persist_enrollment_sheet`-
   Bestand). Die LOEFFEL-3-Lehre („vor dem Vertrauen das Blatt prüfen")
   direkt im Panel — mit Bestands-Angabe.
9. **Einlern-Sessions (nur Anzeige):** `pipeline.list_enroll_sessions` mit
   Zustand und Shots. Verwerfen und Fortsetzen sind NICHT Teil dieser
   Stufe — sie liegen als Aktionen in Stufe 4.

### Stufe 4 — Diagnose & Session-Aktionen

10. **Segmentierungs-Test:** Testaufnahme über die Frame-Quelle des
    Hauptfensters, `pipeline.measure_shot` (kein DB-Schreibzugriff),
    Anzeige Maske/Kontur-Overlay + Messwerte. Beantwortet „warum erkennt
    er nichts?".
11. **Config-Ansicht (read-only):** effektive Config als Baum, je Key mit
    Herkunft (`config.yaml` / `config.local.yaml`), ermittelt durch
    getrenntes Laden beider Dateien auf Anzeige-Ebene. Es gibt keinerlei
    Schreibpfad — auch keinen „Export".
12. **Kamera-Diagnose:** `camera.py`-Fassade (gefundene Kameras,
    Profil-Readback) mit dem Hinweis, dass die Readback-Warnung auf
    Mac/AVFoundation erwartbar ist.
13. **Session-Aktionen:** Verwerfen ruft exakt
    `pipeline.discard_enroll_session` (bestehende Semantik: sichern nach
    `data/verworfen/`, kein Löschen); Fortsetzen delegiert an den
    bestehenden Einlern-Dialog des Hauptfensters und ist nur möglich, wenn
    dessen Zustand READY ist (Kamera + Kalibrierung), sonst Hinweistext
    statt Knopf. **Bedingung: kein neuer Ablauf, kein zweiter Pfad zu
    einer bestandsverändernden Operation.** Beide Aktionen werden bei der
    Abnahme einzeln geprüft.

## 7. Ausgegliedert (nicht Teil dieses Vorhabens)

- **Löschen mit Backup-Move** (Semantik von `delete-article` /
  `delete-references`): eigener, später zu genehmigender Vorgang mit
  eigenem Test. Er erfordert die Extraktion der Ablauflogik aus `cli.py`
  in eine `pipeline.py`-Fassade — ein Eingriff in den Datenpfad, kein
  UI-Bau. Die UI importiert nie `cli.py`.
- **Korpus-Klärung `runs/_invalid/`** (19 Einträge, Cross-Run-Effekte):
  eigener offener Vorgang, unabhängig vom Panel. **Befund 2026-08-10
  dazu:** der serielle Suite-Volllauf hinterließ `runs/20260810-193545`
  (leer, ohne `metrics.json`) im Korpus-Baum — die Testsuite schreibt
  also in den Korpus-Baum, und das ist die naheliegende Quelle der
  `_invalid`-Einträge (deckt sich mit dem CLAUDE.md-Hinweis auf
  `test_corpus_tier2_decisions_reproduce`, das `run_corpus()` direkt
  ruft und `write_run` nie erreicht). Nur Notiz, keine Untersuchung.

## 8. Abnahmekriterien

- **Prüfbarkeit gegen Quellen außerhalb des Panels (hart):** Jede Zahl
  aus dem **Mess-/Report-Pfad** ist gegen eine Quelle außerhalb des
  Panels prüfbar — ein CLI-Äquivalent (`analyze`, `list-articles`, …),
  das rohe Report-JSON (dokumentierter `jq`-/`grep`-Befehl) oder ein
  direkter Datei-Hash (`shasum -a 256`, für den Optik-Fingerprint).
  Für die Prefilter-Kill-Seite konkret: das Aggregat gegen das
  `analyze`-Artefakt `prefilter_funnel.csv` (`_analysis_prefilter`,
  `analysis.py:887–950`, liest `report.prefiltered`), die Detailzeilen
  gegen die `prefiltered`-Liste der Report-JSONs. Das Panel ist View,
  keine vierte Auswertungswahrheit neben `analyze`, `corpus-report` und
  den Report-JSONs.
- **Ausgenommen sind Umgebungsfakten** — freier Plattenplatz, DB-Größe,
  Datei-Alter, Kamera-Zustand: sie beschreiben die Maschine, nicht die
  Messung, und haben bewusst keine Panel-externe Prüfquelle.
- **Die Abnahme jedes Melde-Punkts enthält den Stichprobenvergleich mit
  dem konkret verwendeten Befehl** — der Befehl steht im Melde-Text,
  nicht nur die Zusage, dass verglichen wurde.
- **Streamlit-Ablösung:** Das Panel **schließt die Streamlit-Ablösung ab**
  (entfernt mit Commit `07586b5`, 2026-08-01): die Einzelreport-Ansicht
  war laut README-Funktionstabelle und Nachbau-Dokument das letzte
  fehlende Äquivalent. Mit Abnahme von Melde-Punkt 1b wird die
  „kein Ersatz"-Zeile der README-Tabelle im dafür vorgesehenen
  Doku-Vorgang aktualisiert.

## 9. Fehlerbehandlung

- Worker-Fehler erscheinen als Fehlertext auf der jeweiligen Seite
  (Muster des Hauptfensters: Kopfzeile + Abhilfe-Text), nie als Crash.
- Fehlende Verzeichnisse/leere Bestände sind Leerzustände mit
  Handlungsanleitung, keine Fehler.
- Reports mit unlesbarem JSON werden übersprungen und gezählt
  („n nicht lesbar"), nicht verschwiegen; ungültige Analyse-Ordner werden
  als „ungültig, n Stück" ausgewiesen (Listbarkeits-Kriterium, Stufe 2).

## 10. Tests

- `admin_auth.py`: reine Unit-Tests (Temp-Verzeichnis; setzen, prüfen,
  falsches Passwort, Datei fehlt, Datei defekt).
- Seiten: Qt-Tests im Stil der bestehenden ui_qt-Suite (offscreen), immer
  gegen Temp-DB/Temp-Captures (Projektregel; echte `doco_detect.sqlite3`
  und `data/` werden nie berührt). Report-Browser, Einzelreport-Ansicht
  und Prefilter-Kill-Seite gegen synthetische Report-JSONs (inkl.
  `prefiltered`-Einträgen beider Kill-Gründe).
- Die drei pipeline-Lese-Fassaden: eigene Tests gegen Temp-Captures bzw.
  Temp-Kalibrierdateien — Teil von Melde-Punkt 1a.
- Kein Test öffnet eine Kamera (`tests/conftest.py`-Autouse bleibt
  maßgeblich); der Segmentierungs-Test wird mit gestellten Frames
  getestet.
- **Test-Regime Stufe 1** — gilt für Stufe 1 (additiv; Bestehendes wird
  nur an zwei Stellen berührt: Hauptfenster Schloss-Knopf, `pipeline.py`
  Lese-Fassaden; Messpfad unberührt) und ist **für spätere Stufen vor
  Beginn neu zu bewerten**:
  - **Nach 1a und nach 1b: nur die betroffene Auswahl,** kein voller
    Lauf. Die ui_qt-Module laufen dabei EINZELN je pytest-Aufruf —
    dokumentierte Segfault-Vermeidung
    ([ui-qt-testsuite-segfault.md](../../ui-qt-testsuite-segfault.md):
    zwei oder mehr UI-Module in einem Aufruf können nativ crashen und
    echte Fehler maskieren. Auswahl (gemessen 2026-08-10, seriell:
    **213 s**, alles grün):

    ```
    for m in tests/test_ui_*.py tests/test_camera_worker.py \
             tests/test_demo_scenes.py tests/test_demo_seed_state.py \
             tests/test_icon_hidpi.py; do pytest "$m"; done
    pytest tests/test_pipeline_synthetic.py tests/test_enroll_session*.py
    ```

    Die neuen Tests reihen sich ein: Admin-Seiten-Tests (Qt) in die
    Einzelaufruf-Schleife, `admin_auth`- und Fassaden-Tests (Qt-frei) in
    den zweiten Aufruf.
  - **Bekannte Eigenheit:** `test_ui_qt_smoke.py` endet auch grün mit
    Exit 134 (vorbestehender Teardown-Abort, `QThread: Destroyed…`) —
    maßgeblich ist bei DIESEM Modul die pytest-Summary, nicht der
    Exit-Code.
  - **Volle Suite: einmal auf dem Merge-Commit** (seriell, kein xdist;
    Messung 2026-08-10: 20:28 min bei 789 passed, 2 skipped).
  - **Beide Korpus-Stufen** (`corpus-run --tier 1 --check` und
    `--tier 2 --check`): einmal vor dem Merge, nicht je Melde-Punkt —
    der Messpfad wird in Stufe 1 nicht angefasst. Erwartung: keine
    Abweichung.
  - Unverändert: vor jedem Folgelauf lastfailed-Stand und Vollausgabe in
    Datei sichern; kein `git stash` während Vergleichsläufen
    (git worktree).

## 11. Ablauf der Umsetzung

Stufe 1 hat **zwei blockierende Melde-Punkte**: (1a) die drei
pipeline-Lese-Fassaden, Gerüst, Zugang, System-Status; (1b)
Report-Browser, Einzelreport-Ansicht, Prefilter-Kill-Seite. Jede weitere
Stufe ist ein eigenes Paket auf einem Feature-Branch mit eigenem
blockierendem Melde-Punkt: das Ergebnis des Test-Regimes aus Abschnitt 10
melden (je Melde-Punkt die betroffene Auswahl; volle Suite und beide
Korpus-Stufen einmal zum Merge), auf Antwort warten, erst dann
committen/mergen (CLAUDE.md „Zusammenarbeit").
Die Session-Aktionen (Punkt 13) werden innerhalb von Stufe 4 als letztes
umgesetzt und einzeln abgenommen.

---

## Anhang A — Befund Pfadkonstruktion (2026-08-08, rohe Ausgaben)

Grundlage des Zugriffsweg-Abschnitts und des vorgemerkten Wortlauts.
Geprüft wurde, ob `reporting.py`, `analysis.py`, `enrollment_sheet.py`
eigene Pfade konstruieren (Kriterium: `Path(`-/Join-Konstruktion aus
Config-Schlüsseln oder Literalen — nicht das bloße Weiterreichen von
Argumenten).

**Grep A — `Path(` / `os.path.join` / `joinpath` / `mkdir` / `.parent`:**

```
docodetect/reporting.py:55:    p = Path(report.report_path)
docodetect/reporting.py:74:    p = Path(report.report_path)
docodetect/reporting.py:125:    folder = Path(folder)
docodetect/analysis.py:649:    return Path(r.report_path).stem if r.report_path else (r.timestamp or "")
docodetect/analysis.py:1046:               [[i, Path(r.report_path).stem if r.report_path else "", r.label,
docodetect/analysis.py:1319:    src = Path(reports_dir) if reports_dir else resolve(
docodetect/analysis.py:1323:    out.mkdir(parents=True, exist_ok=True)
docodetect/analysis.py:1355:        arch.mkdir(exist_ok=True)
docodetect/analysis.py:1392:    run_dir = Path(run_dir)
docodetect/analysis.py:1400:    dest.mkdir(parents=True)
docodetect/enrollment_sheet.py:714:        out_path = Path(out_path)
docodetect/enrollment_sheet.py:715:        out_path.parent.mkdir(parents=True, exist_ok=True)
docodetect/enrollment_sheet.py:729:    p = Path(src)
docodetect/enrollment_sheet.py:808:    return render_sheet(metrics, geoms, Path(out), title, subnote)
docodetect/enrollment_sheet.py:824:            meta = [(ip, f) for ip, f in meta if ip and session in Path(ip).name]
docodetect/enrollment_sheet.py:855:        out = Path(out)
docodetect/enrollment_sheet.py:856:        out.parent.mkdir(parents=True, exist_ok=True)
```

**Grep B — Pfad-Literale und Config-Pfadschlüssel (Codezeilen; weitere
Treffer waren Docstrings/Fehlermeldungs-Texte):**

```
docodetect/enrollment_sheet.py:731:        p = resolve(src)
docodetect/enrollment_sheet.py:806:        base = cfg.get("analysis", {}).get("output_dir", "reports/analysis")
docodetect/enrollment_sheet.py:807:        out = resolve(base) / "enrollment" / f"{article_number or 'session'}.png"
docodetect/enrollment_sheet.py:852:            base = cfg.get("analysis", {}).get("output_dir", "reports/analysis")
docodetect/enrollment_sheet.py:854:            out = resolve(base) / "contour_band" / f"{name}.png"
docodetect/analysis.py:1319:    src = Path(reports_dir) if reports_dir else resolve(
docodetect/analysis.py:1320:        cfg.get("paths", {}).get("captures_dir", "data/captures"))
docodetect/analysis.py:1322:    out = resolve(cfg.get("analysis", {}).get("output_dir", "reports/analysis")) / run_id
docodetect/analysis.py:1393:    dest = resolve(cfg.get("analysis", {}).get(
docodetect/analysis.py:1394:        "publish_dir", "reports/archive")) / run_dir.name
```

**Bewertung je Modul:**

- `reporting.py`: **keine eigene Pfadkonstruktion.** `Path(folder)` ist das
  Aufrufer-Argument; `Path(report.report_path)` liest ein Feld, das
  `pipeline.py` beim Speichern gesetzt hat. Zeilen 48/70 erwähnen
  `paths.captures_dir` nur im Fehlermeldungs-Text.
- `analysis.py`: **konstruiert eigene Pfade.** Quellpfad-Fallback aus
  `paths.captures_dir` (1319–1320), Zielpfad immer aus
  `analysis.output_dir` (1322, ohne Parameter übergehbar), `publish_run`
  aus `analysis.publish_dir` (1393–1394).
- `enrollment_sheet.py`: **konstruiert eigene Pfade.** Default-Ausgabepfade
  aus `analysis.output_dir` mit Literal-Fallback (806–807, 852–854; per
  explizitem `out` umgehbar) und `resolve(src)` für DB-gespeicherte
  Bildpfade (729–731; nicht umgehbar).

**Bestehende Wrapper in `pipeline.py`** (das Muster, das der Zugriffsweg
fortführt): Schreibseite `confirm_result`/`confirm_no_match`/
`reject_result` (1064–1090, Docstring „damit UIs reporting.py nie direkt
importieren müssen"); Blätter `enrollment_sheet_for_shots` (171) und
`persist_enrollment_sheet` (215). Eine Leseseite für Reports existiert
nicht — die zwei Stufe-1-Fassaden sind der einzige Zusatz.
