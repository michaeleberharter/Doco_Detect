# Doco_Detect

Geschirr-Identifikation für DO&CO mittels Fotobox + UGREEN FineCam Lite 4K.

Zweistufige Pipeline:

1. **Stufe 1 (klassisch, deterministisch):** Hintergrund-Segmentierung → geometrische
   Vermessung in mm (Durchmesser, Fläche, Rundheit, Formmerkmale) + Farbanalyse →
   Kandidatenfilter gegen die Artikel-Datenbank.
2. **Stufe 2 (optional, nur bei Mehrdeutigkeit):** DINOv2-Embeddings + FAISS
   Nearest-Neighbor gegen eingelernte Referenzfotos. Kein Training nötig.

## Hardware-Setup

- Fotobox 40 × 30 × 30 cm, Kamera mittig an der Decke, Blick senkrecht nach unten
- Kamera: UGREEN FineCam Lite 4K (3840×2160, 70° diagonales FOV, Autofokus)
- Kamerahöhe über Boxboden: **300 mm** (in `config/config.yaml` hinterlegt)

### ⚠️ Wichtige Geometrie-Einschränkung

Bei 70° diagonalem FOV und 300 mm Abstand sieht die Kamera am Boxboden nur
**ca. 37 × 21 cm** (16:9). Das heißt:

- Teller mit Ø > ~19–20 cm passen **nicht vollständig** ins Bild (kurze Bildseite!).
- Die Pipeline erkennt das (Kontur berührt Bildrand) und meldet einen Fehler statt
  falsch zu messen.
- Lösungen: Kamera höher montieren (Box-Deckel erhöhen), Weitwinkel-Kamera, oder
  4:3-Modus der Kamera nutzen (geringere Auflösung, aber mehr vertikales FOV).
  **Das solltet ihr vor dem Bau der finalen Box mit eurem größten Teller testen.**

### Autofokus deaktivieren

Für reproduzierbare Messungen muss der Autofokus **aus** sein (fester Fokuswert,
wird beim Kalibrieren mitgespeichert). Der Code setzt das über UVC-Properties;
unter Linux ggf. zusätzlich `v4l2-ctl -d /dev/video0 -c focus_automatic_continuous=0`.

### Höhenkompensation

Die Pixel→mm-Kalibrierung gilt für die Bodenebene. Ein Tellerrand liegt aber z. B.
25 mm höher → erscheint ~9 % größer. Der Matcher korrigiert das **pro Kandidat**
mit dessen Höhe aus der Datenbank: `wahre_Größe = gemessene_Größe · (Z − h) / Z`.
Darum ist die Spalte `height_mm` in der Artikeldatenbank wichtig.

## Scoring (Stufe 1, statistisch)

Nach dem harten Geometrie-Vorfilter (höhenkompensiert, `diameter_tolerance_mm` /
`area_tolerance_pct`) wird jedes Merkmal f als Gauß-Messung modelliert:

Der Vorfilter vergleicht den gemessenen minEnclosingCircle-Durchmesser gegen
eine artikelabhängige Nominalgröße: bei runden Artikeln (`diameter_mm`)
direkt gegen den Durchmesser; bei länglichen Artikeln (Löffel, Gabel,
Messer – `width_mm`/`depth_mm`) gegen die LÄNGE (`max(width_mm, depth_mm)`),
nicht gegen die Diagonale des minAreaRect. Grund: Besteck ist eine
„Stadion"-Form (Schaft + abgerundete Enden), keine scharfkantige
Rechteckkontur – für eine solche Form entspricht der
minEnclosingCircle-Durchmesser exakt der Länge, für jedes Breite/Länge-
Verhältnis (siehe `docs/superpowers/reports/2026-07-21-vorfilter-laengliche-
artikel-ergebnis.md`).

    sigma_eff(f) = sqrt(sigma_enroll(f)² + sigma_floor(f)²)
    z(f)    = d(f) / sigma_eff(f)          d = Distanz Messung ↔ Enrollment-Referenz
    logL(f) = −0.5 · z(f)²                 (Log-Likelihood bis auf Konstante)

`sigma_enroll` kommt aus den Enrollment-Shots (Mittelwert/Std je Artikel,
Tabelle `reference_stats` – wird bei jedem Einlernen automatisch neu berechnet),
`sigma_floor` aus `matching.sigma_floors` (Mess-Rauschboden, verhindert
Division durch ~0 bei wenigen Shots). Der Gesamt-Log-Score eines Kandidaten
ist das gewichtete Mittel der logL über seine verfügbaren Merkmale; der
Posterior ist ein Softmax der Log-Scores (`softmax_temperature`).

**Merkmale:** Ø (mm), Rundheit 4πA/P², Solidity, ΔE-CIE76 + H-S-Histogramm
getrennt für Zentrum (r < 0.6) und Rand/Fahne (r > 0.75, `features.ring_zones`;
die Übergangszone wird ignoriert), log-Hu-Momente (rotationsinvariant –
Draufsicht macht Tellerrotation irrelevant). Die Fläche ist nur Vorfilter
(korreliert voll mit dem Durchmesser). Kandidaten mit Enrollment-Statistiken
werden Floor-Ebene gegen Floor-Ebene verglichen (keine doppelte Höhenkorrektur);
Artikel ohne Referenzen laufen geometry-only und können nie automatisch buchen.

**Adaptive Gewichte (Fisher-Ratio):** pro Merkmal über das Kandidatenset

    D_f = Var(Kandidaten-Lagen von f) / Mittel(sigma_eff(f)²)

– trennt ein Merkmal die aktuellen Kandidaten gut, bekommt es mehr Gewicht:
`w_eff = w_global · (1 + α · D_norm)`, danach normiert;
α = `matching.adaptive_weight_alpha` (0 = aus). Bei nur einem Kandidaten
entfällt die Adaption.

**Entscheidung (drei Ausgänge):**

- **ACCEPT:** max |z| des Siegers ≤ `max_z_accept` UND Log-Score-Vorsprung zu
  Platz 2 ≥ `min_llr_margin` (2.0 ≈ e² ≈ 7,4× wahrscheinlicher) UND der Sieger
  hat eingelernte Referenzen.
- **AMBIGUOUS:** Gate bestanden, Margin nicht → Top-k zur manuellen Auswahl
  (genau hier übernimmt später Stufe 2 / DINOv2).
- **REJECT:** Gate verfehlt → „Objekt vermutlich nicht in der Datenbank",
  wird niemals automatisch gebucht.

Jede Identifikation legt Capture + `MatchReport`-JSON (alle Zwischengrößen:
pro Kandidat und Merkmal Distanz, sigma, z, Log-Beitrag; Fisher-D, Gewichte,
Posterior, Gate-Status) unter `data/captures/` ab. Unter jedem Ergebnis
(Identify-Tab und Einzel-Report) kann per **Richtig/Falsch** bewertet werden,
bei „Falsch" optional mit dem wahren Artikel — das Urteil wird ins Report-JSON
zurückgeschrieben und fließt in Erfolgsrate, Fehlerliste und
Verwechslungsmatrix des Batch-Tabs ein. Die Streamlit-Seite
**📊 Scoring-Analyse** schlüsselt jeden Report auf (Kandidatentabelle,
Log-Beitrags-Chart, Top-1-vs-Top-2-Kontrast) und aggregiert ganze Ordner zu
Genauigkeit/Verwechslungsmatrix – dieselbe Logik wie `evaluate`
(`docodetect/reporting.py`).

### sigma_floors aus einer echten Messreihe bestimmen

1. Einen Artikel wählen und 15–20× neu in die Box legen (jedes Mal anheben,
   leicht drehen/verschieben). Über `identify` (bzw. UI, ohne den Artikel
   vorher enrollen zu müssen) landet jede Aufnahme als `MatchReport`-JSON
   unter `data/captures/`.
2. Pro Merkmal die Standardabweichung über die Messreihe auswerten:
   ```bash
   python -m docodetect.cli analyze-floors --limit 20
   ```
   Zeigt Tabelle (n/mean/std/floor/min/max je Merkmal), einen fertigen
   `sigma_floors:`-YAML-Block zum Copy-Paste, die explizite Ø-Streuung
   (min/max/Std — hilft z. B. einzuordnen, ob ein beobachtetes Restresiduum
   im Bereich des reinen Auflage-Rauschens liegt), eine Warnung bei
   `n < 10` und benennt Ausreißer (`|x−mean| > 3·Std`). Filter: `--label
   ART-NR` (nur Reports mit diesem Urteil), `--since`/`--until` (ISO-
   Zeitstempel), `--limit N` (nur die letzten N). Alternative ohne
   `identify`: `enroll ART-NR --shots 20` und danach `reference_stats`
   (`scalar_std`/`proto_std`) auswerten — `analyze-floors` deckt nur den
   `data/captures/`-Weg ab.
3. Der `floor`-Wert je Merkmal aus Schritt 2 kommt in `matching.sigma_floors`
   — in `config/config.yaml`, **nicht** in `config.local.yaml` (siehe unten).
   (Danach ggf. Test-Captures/-Referenzen aufräumen, damit die
   Messreihen-Shots nicht versehentlich als echte Referenzen/Captures
   liegen bleiben.)

**Die Floors gehören versioniert in `config/config.yaml` — auch wenn sie
rig-spezifisch gemessen sind.** Das ist bewusst kein Widerspruch: die Floors
sind zwar am Rig gemessen, aber der Regressions-Korpus rechnet gegen sie und
die Tier-2-Baseline hält ihren `config_fingerprint` fest. Stünden sie in der
unversionierten `config.local.yaml`, verglichen `corpus-run --check` und die
Baseline gegen Werte, die kein anderer Rechner und kein Reviewer je zu sehen
bekommt — die Kennzahl misst dann nichts mehr. Genau so entstand die
Tier-2-Baseline vom 2026-07-21. `corpus-run` bricht deshalb ab, sobald eine
`config.local.yaml` einen fingerprinteten Abschnitt (`matching`, `features`)
überschreibt; in die lokale Datei gehört nur Maschinen-Spezifisches wie
`camera.index`. Wechselt das Rig (Mac → Windows-Box), wird neu gemessen und
der Wert in `config.yaml` ersetzt — nicht lokal überlagert.

**Eine Messreihe misst nur einen Tag.** `analyze-floors` erfasst die
Streuung *einer* Auflage-Serie an *einem* Rig an *einem* Tag. Merkmale mit
zusätzlicher Streuung über Sessions hinweg (Beleuchtung, Kamera-Profil,
Neu-Enrollment) brauchen mehr Boden, als eine Serie zeigt. Konkret am
2026-07-22: `hu_log` maß 0.069, über die Korpus-Sessions läuft die
hu-Distanz eines Artikels zu seiner *eigenen* Referenz aber bis 1.37
(Median 0.18) — mit 0.069 hätte das z-Gate historisch korrekte Auflagen
verworfen (z bis 13.9) und zwei Fehlbuchungen erzeugt. Der Wert steht
darum auf 0.38, dem kleinsten Floor, bei dem kein korrekter Korpus-Fall am
Gate scheitert. Prüfregel: **nach jeder Floor-Änderung `corpus-run --tier 2
--check`** und die neuen REJECTs korrekter Artikel auf ihr treibendes
Merkmal ansehen — ein Merkmal, das dort allein z > 3.5 erzeugt, hat einen
zu engen Floor und wird angehoben, nicht wegbaseliniert.

### Testphase: Validieren statt Schwellen raten

Einzelne gute (oder schlechte) Ergebnisse sind keine Basis für Tuning.
Bevor an `max_z_accept` / `min_llr_margin` / Gewichten gedreht wird, in
dieser Reihenfolge vorgehen:

1. **sigma_floors aus einer echten Messreihe bestimmen** (Anleitung oben).
   Das ist der einzige noch geschätzte Wert, und die gesamte z-Skala hängt
   daran — erst die Floors festnageln, dann über Schwellen reden.
2. **Beim Einlernen Rotationen abdecken:** pro Artikel ~8 Shots, zwischen
   den Shots anheben, drehen, leicht verschieben. Gerade bei poliertem
   Stahl leben die Farb-/Textur-Merkmale von den Reflexionen — die Streuung
   über Rotationen muss in sigma_enroll enthalten sein, sonst wirkt ein
   anders gedrehter Löffel künstlich „falsch".
3. **Batch-Daten sammeln statt raten:** entweder ein gelabeltes Testset
   anlegen (`data/testset/<artikelnummer>/*.jpg`, pro Artikel 10–20 Aufnahmen
   in verschiedenen Rotationen) und `evaluate` laufen lassen — oder einfach
   beim Live-Testen jedes Ergebnis mit den **Richtig/Falsch**-Buttons
   bewerten. Beides landet in denselben Report-JSONs; der Batch-Tab der
   **Scoring-Analyse** zeigt daraus Erfolgsrate, Fehlerliste und die
   Posterior-Verteilung korrekt vs. falsch. Erst wenn sich die beiden
   Verteilungen überlappen, lohnt sich Tuning an `min_llr_margin` oder
   `max_z_accept`.

Leitplanken beim Lesen der Ergebnisse:

- Gesund sieht so aus: korrekte Artikel bei max |z| ≈ 1–2, falsche bei 5+.
  Dazwischen viel Luft → nichts anfassen.
- Enden **korrekte** Artikel gelegentlich als REJECT (max |z| knapp über
  3.5), sind die `sigma_floors` zu eng geschätzt → **Floors anheben**
  (Schritt 1 wiederholen), NICHT das Gate aufweichen.
- Häufen sich AMBIGUOUS-Fälle, ist das kein Fehler, sondern die Vorlage für
  Stufe 2 (DINOv2) — der Übergabepunkt ist in `matcher.py` als
  `TODO(stage-2)` markiert.

## Installation

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # Stufe 1
pip install -r requirements-stage2.txt   # optional: Stufe 2 (torch, faiss)
pip install -r requirements-ui.txt       # optional: Streamlit-Test-UI
pip install -r requirements-ui-qt.txt    # optional: native Qt-Bedien-UI
```

### Rechnerlokale Einstellungen (`config/config.local.yaml`)

Liegt neben `config/config.yaml` eine `config.local.yaml`, wird sie beim
Laden per Deep-Merge darübergelegt — dort gesetzte Keys gewinnen, alles
andere bleibt wie in der geteilten Config. Die Datei ist nicht versioniert
(`.gitignore`) und dafür da, rechnerabhängige Werte aus der geteilten
Config herauszuhalten. Typischer Fall ist der Kamera-Index: am Windows-PC
an der Box ist die UGREEN Index 0, am Entwicklungs-Mac liegt dort die
interne FaceTime-Kamera und die UGREEN meist auf 1.

```yaml
# config/config.local.yaml
camera:
  index: 1
```

**Was hier NICHT hingehört:** `matching` und `features`. Beide gehen in den
`config_fingerprint` des Regressions-Korpus ein; lokal überschrieben würde
die Tier-2-Baseline gegen unversionierte Werte gerechnet. `corpus-run`
bricht darum mit einer Fehlermeldung ab, wenn es einen dieser Abschnitte in
der lokalen Datei findet. Auch rig-spezifisch gemessene `sigma_floors`
gehören nach `config/config.yaml` (siehe „sigma_floors aus einer echten
Messreihe bestimmen"). `geometry.camera_height_mm` bleibt dagegen zulässig:
der Wert wird nur beim Kalibrieren gelesen, das Replay lädt die eingefrorene
`calibration.json` aus dem Bündel.

Passenden Index ermitteln:

```bash
python -m docodetect.cli list-cameras     # probiert Index 0..3 durch
```

### Tests und Hardware

`pytest tests/` läuft komplett ohne Kamera: `tests/conftest.py` sperrt jeden
Zugriff auf echte Aufnahmegeräte (sonst öffnet der Testlauf unter macOS die
FaceTime-Kamera und löst den Berechtigungsdialog aus). Tests, die zwingend
eine angeschlossene Kamera brauchen, tragen den Marker `hardware` und werden
standardmäßig übersprungen:

```bash
python -m pytest tests/ -v                              # ohne Hardware
DOCODETECT_HW_TESTS=1 python -m pytest tests/ -v -m hardware -s   # mit Kamera
```

## Workflow

```bash
# 1. Datenbank anlegen und Artikel importieren (CSV: siehe data/articles_example.csv)
python -m docodetect.cli init-db
python -m docodetect.cli import-articles data/articles_example.csv

# 2. Kalibrieren (ArUco-Marker DICT_4X4_50, ID 0, 50 mm, flach auf Boxboden)
#    Empfohlen VORHER: in config/config.yaml camera.lock_exposure/lock_white_balance
#    = true setzen (feste Kamera-Antwort). Danach IMMER den Hintergrund neu aufnehmen.
python -m docodetect.cli capture-background      # leere Box fotografieren
python -m docodetect.cli calibrate               # Marker liegt in der Box

# 2b. Neuen Artikel direkt per Kamera anlegen (ohne CSV): Objekt in die Box
#     legen, Namen angeben - Maße werden gemessen, das Foto wird sofort als
#     erste Referenz gespeichert. --height-mm nur für erhöhte Teile (Tasse).
python -m docodetect.cli create-article "Suppenloeffel"
python -m docodetect.cli create-article "Kaffeetasse weiss" --height-mm 80
python -m docodetect.cli delete-article SUPPENLOEFFEL   # falsch vermessen? Löschen + neu anlegen

# 3. Artikel einlernen (weitere Referenzmerkmale, mehrere Rotationen)
python -m docodetect.cli enroll TELLER-27-WEISS --shots 8

# 4. Identifizieren
python -m docodetect.cli identify                # Live-Aufnahme
python -m docodetect.cli identify --image foto.jpg
#    -> legt Capture + Scoring-Report (JSON) unter data/captures/ ab

# 5. Genauigkeit messen (Ordner mit gelabelten Testbildern)
python -m docodetect.cli evaluate data/testset/
```

## Test-UI (Streamlit)

Browser-Oberfläche für denselben Workflow (Hintergrund, Kalibrieren,
Identifizieren, Neuer Artikel, Einlernen) mit Live-Kamera-Vorschau – praktisch zum Testen,
ohne jeden Schritt über die CLI einzutippen. Nutzt intern ausschließlich
`docodetect/pipeline.py`, `calibration.py`, `camera.py` und `database.py`
(kein Bild-Upload, keine synthetischen Testbilder – jede Aktion löst die
echte `BoxCamera` aus).

```bash
pip install -r requirements-ui.txt   # einmalig: streamlit, pandas
streamlit run app.py
```

Öffnet auf http://localhost:8501. Die Kamera wird nur geöffnet, während die
Live-Vorschau läuft oder eine Aufnahme passiert, und danach wieder
freigegeben (Sidebar-Button "🔌 Kamera freigeben" schließt sie auch manuell) –
so blockiert die UI das Kamera-Device nicht dauerhaft für die CLI.

## Segmentierung: EIN globaler Graph-Cut, KEINE Konfiguration

Die Segmentierung löst das Problem so wie ein Mensch: nicht Pixel für Pixel
klassifizieren, sondern **die geschlossene Region finden, deren Rand auf den
sichtbaren Kanten liegt** – als globale Optimierung (Min-Cut, scipy).
**Es gibt keine Stellschrauben**: jede Schwelle wird pro Bild selbst
kalibriert (Boden-Rauschdecke per Sigma-Clipping, Objekt-Anker = obere
Hälfte des Evidenzbereichs jedes Teils, Kantenmaß am Referenzboden).

1. **Evidenz** je Pixel: Differenz + Textur gegenüber dem leeren-Box-
   Referenzbild (Textur zählt nur, wo das Pixel selbst messbar vom Boden
   abweicht – sonst würden schmale Gabelschlitze Textur der Zinken erben).
2. **Graph-Cut**: der Datenterm beansprucht nur Sicheres (Boden unter der
   Rauschdecke, Anker auf dem Objekt) – alles dazwischen ist neutral, und
   die Grenze legt sich zwingend auf die stärkste sichtbare Kante. Der
   Glüh-Saum (Bloom) um helles Metall hat keine Außenkante und fällt so
   von selbst an den Boden.
3. **Amodale Vervollständigung**: von Kanten umschlossene Spiegelzonen
   gehören zum Objekt; getrennte Teile (Spiegel-Hals einer vertikalen
   Gabel) werden über die Distanz-Linse gebrückt, wenn der Korridor
   Nicht-Boden-Material trägt; Einbuchtungen mit unsichtbarer Grenze und
   Evidenz-Inhalt werden gefüllt. Gabelschlitze münden kantenfrei nach
   außen und bleiben offen – ihre Grenze ist sichtbar.
4. **Kontur-Snap** auf die stärksten Bildkanten; Punkte ganz ohne Kante
   suchen nur nach außen die verpasste Kontur ("keine Grenze ohne Kante").

Validiert und gepinnt an echten Aufnahmen (`data/captures/` +
`tests/test_real_captures.py`, 12 Goldens); ~0,7–1,5 s pro Bild, rein CPU
(opencv+scipy). Der frühere MobileSAM-Pfad ist stillgelegt
(`docodetect/neural_seg.py` bleibt nur für Experimente).

## Ältere Hinweise (Beleuchtung/Untergrund)

Spiegelnder Edelstahl reflektiert den dunklen Untergrund und hebt sich dann
farblich/hell kaum ab – reine Hintergrund-Differenz übersieht ihn. Zwei Dinge
adressieren das:

1. **Belichtung/Weißabgleich fixieren** (`camera.lock_exposure` /
   `lock_white_balance` in `config/config.yaml`). Ohne Lock regelt die
   Kamera-Automatik bei leerer (dunkler) Box anders als mit glänzendem Objekt →
   Hintergrund- und Objektbild unterscheiden sich global und die Differenz misst
   die Kamera-Regelung statt des Objekts. **Nach dem Aktivieren/Ändern den
   Hintergrund neu aufnehmen.** `exposure` ist kameraspezifisch (per Sweep im
   Config-Tab ermitteln); manche UVC-Kameras ignorieren die Props – `camera.py`
   liest die Ist-Werte zurück und warnt.

2. **Textur-Evidenz + Graph-Cut** in `segmentation.py`: zusätzlich zur
   Kanal-Differenz misst die Evidenz die lokale Textur (Reflex-Schlieren
   gegen den matten Grund), und der Graph-Cut behandelt Spiegelzonen als
   neutral – die sichtbaren Kanten entscheiden. Es gibt **keine
   Stellschrauben** (alles selbstkalibrierend); stimmt eine Segmentierung
   nicht, ist die automatisch gespeicherte Aufnahme in `data/captures/`
   der Testfall für eine Regel-Verbesserung. Zusätzlich verwirft die
   Objektauswahl randklebende Rausch-Blobs (Score aus Fläche/Solidität/
   Zentrierung/Randkontakt).

**Untergrund: SCHWARZ (matt) ist die richtige Wahl.** Ein grauer Untergrund
wurde real getestet (2026-07-16) und ist messbar schlechter: Spiegel-Stahl
reflektiert dann die graue Box-Umgebung und trifft die Boden-Helligkeit
großflächig (halbe Laffen "verschwinden"), und an den Tangential-Flächen
verschwindet sogar die Umriss-Kante selbst – dort kann keine Vervollständigung
mehr greifen. Auf Schwarz sind die Spiegel-Zonen von sichtbaren Glanz-Kanten
umschlossen und werden amodal ergänzt; zudem wirft Schwarz keine sichtbaren
Schatten. Der komplette Golden-Bestand ist auf schwarzem Boden validiert.

### Stillgelegt: KI-Silhouette (MobileSAM)

Der frühere neuronale Pfad ist **nicht mehr in die Pipeline eingebunden** –
der globale Graph-Cut hat ihn ersetzt (SAM versiegelte z. B. schmale
Gabelschlitze). `docodetect/neural_seg.py` und
`requirements-seg-neural.txt` bleiben nur für Experimente im Repo; es gibt
keinen `segmentation.neural`-Config-Block und keinen UI-Schalter mehr.

## Regressions-Korpus (echte Aufnahmen)

Der Korpus hält 129 echte, bewertete Aufnahmen aus zwei Sessions
(`phase-a`, `phase-b`) und prüft jede Messpfad-Änderung dagegen. Die
Original-MatchReports SIND die Goldens: sie enthalten Label, Urteil und
die damals gemessenen Werte. Drei weitere Sessions sind bewusst
ausgeschlossen, weil ihr damaliger Session-Zustand nicht mehr
rekonstruierbar ist: `test_2_loeffel` (Hintergrund der Session existiert
nicht mehr), `erster_test_loeffel` (nur 3 bewertete Reports, gemischte
Auflösung) und `smoke-v2-uiqt` (synthetisch, Bilder fehlen).

### Aufbau

```bash
python -m docodetect.cli corpus-build      # idempotent, dedupliziert per SHA-256
python -m docodetect.cli corpus-run --tier 1 --check
python -m docodetect.cli corpus-run --tier 2 --check
```

Vor einem Merge laufen **beide** `--check`-Zeilen. Tier 1 allein prüft nur
die Messwerte: dort ist `quotas` leer, die Baseline-Quoten werden nicht
ausgewertet und die Entscheidungs-Reproduktion läuft nicht. `--check`
verlangt einen ungefilterten Lauf — `--subset`, `--session` und
`--article` enden mit Exit 1, weil ein Ausschnitt keine Freigabe ist.

Der Korpus liegt unter `paths.corpus_dir` (Default `../Doco_Detect_corpus`),
bewusst ausserhalb des Repos — er enthält die 129 4K-PNGs. Versioniert
sind nur `corpus/manifest.json` und `corpus/baseline.json`.

### Zwei Stufen

**Tier 1 (jedes Bild, ohne DB)** replayt Segmentierung und Merkmale gegen
den Golden desselben Bildes. Der aktuelle Code reproduziert die
Messwerte bit-exakt, deshalb liegt die PASS-Schwelle beim
Rundungsquantum (Ø ±0,005 mm, Rundheit/Solidity ±0,00005).

**Tier 2 (nur mit verifiziertem DB-Snapshot)** replayt die komplette
Pipeline und vergleicht Entscheidung, Top-k-Reihenfolge und Gate exakt;
`llr_margin` und `max_z_winner` laufen über dieselbe Drei-Band-Logik. Ob
ein Snapshot passt, stellt `corpus-build` selbst fest — über einen
exakten Abgleich der im Report gespeicherten Referenzwerte gegen die
`reference_stats` des Snapshots; nur bei 100 % Übereinstimmung läuft die
Session in Tier 2. `phase-a` (67 Bilder) hat keinen passenden Snapshot
und läuft deshalb nur in Tier 1; von `phase-b` (62 Bilder) qualifizieren
60 für Tier 2.

Bänder: **PASS** (Abweichung innerhalb des Rundungsquantums der
gespeicherten Werte, z. B. Durchmesser ±0,005 mm, Rundheit/Solidity
±0,00005) · **DRIFT** (darüber, aber innerhalb der weichen Stufe, z. B.
Durchmesser ±0,2 mm) · **FAIL** (darüber). `--check` bricht per Default
bei DRIFT *und* FAIL, weil auf gepinnter Umgebung jede Abweichung
code-verursacht ist. `--accept-drift` lässt nur FAIL brechen und ist für
genau zwei Fälle gedacht: bewusstes Bibliotheks-Update und
Plattformwechsel Mac → Windows — danach ist ein begründetes
Re-Baselining Pflicht.

Stand 2026-07-21: Tier 1 129/129 PASS, Tier 2 60/60 PASS, je 0 DRIFT und
0 FAIL. Die Tier-2-Quoten reproduzieren die früher veröffentlichten
Zahlen aus `reports/analysis/phase-b-korrigiert/metrics.json` exakt:
`accuracy_top1` 46/60, `accuracy_top3` 54/60, `false_accept_rate` 0/25.

### Sync Mac ↔ Windows

Der Korpus zieht als Ordner um; alle Manifest-Pfade sind relativ.

1. `<corpus_dir>` auf den Zielrechner kopieren (rsync, Stick, Netzlaufwerk)
2. dort in `config/config.local.yaml`:
   ```yaml
   paths:
     corpus_dir: D:/Doco_Detect_corpus
   ```
3. `python -m docodetect.cli corpus-run --tier 1` — das Manifest kommt aus git

Der erste Lauf auf Windows wird sehr wahrscheinlich DRIFT melden (andere
OpenCV-Build-Optionen) — das ist der dokumentierte Anwendungsfall für
`--accept-drift` plus anschliessendes Re-Baselining auf dieser Plattform.

### Welche Config repliziert Tier 2?

**Die AKTUELLE `config/config.yaml`/`config.local.yaml`, nicht ein
Session-Snapshot.** `docodetect/corpus/bundle.py::bundle_cfg()` kopiert die
beim Aufruf geladene Live-Config und biegt darin NUR `paths.db_file`,
`paths.captures_dir`, `calibration.file` und `calibration.background_file`
auf das eingefrorene Bündel um — `matching` und `features` (also
`sigma_floors`, `feature_weights`, `diameter_tolerance_mm`, `max_z_accept`,
`min_llr_margin` usw.) kommen unverändert aus dem Live-Zustand.
`geometry.camera_height_mm` wird dagegen NIE live gelesen: es fließt nur
einmalig beim Kalibrieren in `calibration.json` ein, und der Replay lädt
ausschließlich das eingefrorene Bündel (`load_calibration` liest nie die
Live-Config). Ein `session.json` führt zwar zur Provenienz ein
rekonstruiertes `sigma_floors` (siehe `corpus/build.py`,
`recover_sigma_floors`), das ist aber reine Dokumentation für Menschen —
der Replay liest es nie zurück.

**Konsequenz:** Ändert sich `matching.sigma_floors` (oder eine andere
Schwelle) in `config.yaml`, repliziert der NÄCHSTE `corpus-run --tier 2`
JEDE historische Session mit den NEUEN Werten — nicht mit den Werten, die
zum Aufnahmezeitpunkt galten. Das erzeugt erwarteten Tier-2-DRIFT/FAIL,
kein Bug. Ablauf dafür (etabliert 2026-07-21, siehe
[Ergebnisdokument Vorfilter-Fix](docs/superpowers/reports/2026-07-21-vorfilter-laengliche-artikel-ergebnis.md),
Abschnitt 6): Lauf ohne `--check` fahren, `corpus-diff` gegen den letzten
grünen Lauf ziehen, jede Abweichung einzeln prüfen und akzeptieren, dann
als versioniertes Delta unter `corpus/accepted_deltas/*.json` ablegen
(`docodetect/corpus/accepted.py`) — die Original-Goldens bleiben dabei
unverändert. Erst danach `corpus-run --tier 2 --update-baseline`.

**Cache-Fingerprint deckt das ab.** `docodetect/corpus/runner.py::
config_fingerprint(cfg, tier)` hasht `features` (Tier 1) bzw. `features`
+ `matching` (Tier 2) tier-gerecht in den `--changed-only`-Cache-Schlüssel
ein (`geometry` bewusst NICHT, siehe oben — es wäre eine Attrappe, kein
zusätzlicher Schutz). Eine Config-Änderung invalidiert den betroffenen
Cache-Eintrag also automatisch: der DRIFT/FAIL aus der Konsequenz oben
erscheint garantiert beim nächsten Lauf, auch unter `--changed-only`, nicht
erst nach manuellem Löschen von `corpus/.cache/results.json`.

### Baseline-Regel

`corpus/baseline.json` ändert sich NUR über
`corpus-run --tier 2 --update-baseline`, und der Commit muss begründen,
warum die alten Zahlen nicht mehr gelten. Ohne diese Regel misst die
Baseline irgendwann nur noch den Status quo.

Ohne `--tier 2` bricht der Befehl mit Exit 2 ab: nur ein Tier-2-Lauf
erzeugt die Quoten, und eine ersetzend geschriebene Baseline mit leeren
`quotas` würde jede Kennzahl dauerhaft aus dem Vergleich nehmen.
Fehlerraten (`false_accept_rate`) prüft `--check` gegen die Wilson-
**Ober**grenze, alle übrigen Kennzahlen gegen die Untergrenze; fehlt
einer vorhandenen Kennzahl ihre Grenze, ist das ein Fehler und keine
Erlaubnis.

### Auswertung: `corpus-report`

Die Zahlen eines Laufs sichtbar machen, ohne irgendetwas neu zu rechnen.
`corpus-report` (`docodetect/corpus/review.py`) ist eine reine
Konsumentenschicht: sie liest Goldens, `runs/<id>/replay/`, `failures/`,
`metrics.json`, `corpus/accepted_deltas/` und `corpus/baseline.json` und
legt PNG + CSV + `index.html` unter `reports/corpus/<review-id>/` ab.

```bash
python -m docodetect.cli corpus-report --run letzte        # Goldens vs. Lauf
python -m docodetect.cli corpus-report --run 20260722-floors-final
python -m docodetect.cli corpus-report --compare RUN_A RUN_B   # Lauf vs. Lauf
python -m docodetect.cli corpus-run --tier 2 --report      # Review nach dem Lauf
```

Vier Ansichten: **Drift-Review** (Tabelle je Bild mit Entscheidung/Top-1/
Margin/max|z| alt→neu, treibendem Merkmal und Delta-Status, dazu die
Scatter gegen die Gate-Linien und die Entscheidungsmatrix),
**Baseline-Verlauf** (Quoten je Commit von `corpus/baseline.json`, direkt
aus der Git-Historie), **Verteilungen** (Margin und max|z| als Histogramme,
getrennt korrekt vs. falsch — die Ansicht für jede Schwellen-Diskussion)
und **Konfusionsmatrix + Quoten mit Wilson-CI**. Bei einem Tier-1-Lauf mit
Befunden kommt „Tier-1-Drift je Merkmal" aus den `failures/`-Diffs dazu
(erster Anwendungsfall: Plattform-Drift Mac↔Windows).

Die Drift-Review führt **neue Fehlbuchungen** getrennt: Bilder, die der
neue Stand mit falschem Artikel akzeptiert, ohne dass die alte Seite so
gebucht hätte (`neue_fehlbuchungen.csv`). Das ist bewusst **nicht** dieselbe
Menge wie die Rang-1-Wechsel — war Rang 1 schon vorher falsch und kippt nur
die Entscheidung auf `accept`, entsteht eine Fehlbuchung, ohne dass sich
Rang 1 bewegt. Genau so lag `46f9b1b3` bei `hu_log`-Floor 0.069; die
Richtungsbilanz allein zeigte dort 1 statt 2 (Abnahme 2026-07-22).

**Kein Urteil entsteht hier.** Jedes PASS/DRIFT/FAIL stammt aus
`failures/` bzw. dessen Abwesenheit, jede Quote einer Laufseite aus deren
`metrics.json`. Zusätzlich rechnet die Schicht `report.tier2_quotas` — die
Funktion, die auch der Runner benutzt — über die Replay-Reports und hält
sie dagegen; weicht etwas ab, steht das als **Konsistenz-Befund** im
Bericht, und angezeigt wird weiterhin der Wert aus `metrics.json`, weil das
die Zahl ist, die `--check` bewertet hat.

Zwei Kennzahlen sehen ähnlich aus und sind es nicht: `accuracy_top1` ist
über den Korpus verdict-eingefroren (jedes Bild trägt ein menschliches
Urteil) und bewegt sich durch keine Matcher-Änderung; `roh_top1_gleich_label`
ist der rohe Label-Vergleich und als Zusatz gekennzeichnet. Für eine
Schwellen-Diskussion zählt die rohe Größe.

Ein Lauf **ohne `metrics.json`** ist abgebrochen und gilt als
unvollständig: `corpus-report` lehnt ihn als Vergleichsseite mit Klartext
ab (Exit 1), und `--run letzte` überspringt ihn. Der Runner schreibt
`metrics.json` zuletzt — fehlt sie, ist der Replay-Stand ein Torso, und
die fehlenden Bilder sähen in jeder Ansicht wie „nicht betroffen" aus
statt wie „nie gefahren". Aussortierte Läufe gehören nach
`runs/_invalid/`; Ordner mit führendem Unterstrich übergeht die
Auswertung grundsätzlich.

`reports/` ist Arbeitsordner und gitignored. `--publish` kopiert eine
Review zusätzlich nach `reports/archive/corpus-<review-id>/` (Präfix, damit
sie nie mit einem `analyze`-Lauf gleichen Namens kollidiert) und
überschreibt dabei nie.

Die Streamlit-Seite **Korpus** (`pages/2_Korpus.py`) zeigt dieselben
Artefakte an und erzeugt keine — neue Reviews entstehen nur über die CLI.

> **Offener Punkt — Hygiene von `runs/`.** Jeder Tier-2-Lauf legt rund 60
> Reports (~1 MB) unter `runs/<id>/replay/` ab; nach einem Arbeitstag mit
> Iterationen stehen dort schnell 30+ Läufe. Aufgeräumt wird derzeit
> **nichts automatisch**, und das ist Absicht: alte Läufe sind die
> Datengrundlage jedes `--compare` und damit aktuell wertvoll (die
> `hu_log`-Iteration vom 2026-07-22 ließ sich nur deshalb rekonstruieren).
> Eine Aufräum-Strategie — etwa „behalte Baseline-Läufe, benannte Läufe und
> die letzten N, verwirf den Rest" — steht noch aus.
>
> Dazu gehört ein zweiter, verwandter Befund (2026-07-22): **jeder volle
> Testlauf hinterlässt selbst ein solches Verzeichnis.**
> `tests/test_corpus.py::test_corpus_tier2_decisions_reproduce` ruft
> `run_corpus()` direkt auf — das schreibt die 60 Replay-Reports, ruft aber
> nie `report.write_run`, also entsteht nie eine `metrics.json`. Das
> Ergebnis ist ein zeitgestempelter Ordner, der wie ein abgebrochener Lauf
> aussieht, obwohl der Test sauber durchlief. `corpus-report` lehnt ihn
> korrekt ab; verwechselt wird er trotzdem leicht. Kandidaten für ein
> künftiges Aufräumen sind daher auch die fünf unvollständigen Läufe vom
> 2026-07-21 (`20260721-020439`, `-024424`, `-182655`, `-192204`,
> `-193004`) — vermutlich derselben Herkunft. Sie bleiben vorerst
> unangetastet.

### Laufzeit (gemessen auf dem MacBook, 10 Kerne, 8 Worker)

| Lauf | Dauer |
|---|---|
| Voller Tier-1-Lauf (129 Bilder) | 241,9 s (4,0 min), 0,53 Bilder/s |
| Voller Tier-2-Lauf (60 Bilder) | 126,4 s, 0,47 Bilder/s |
| `corpus-run --check --changed-only` ohne Änderung | 0,0 s (Volltreffer im Cache) |

Die Segmentierung kostet 2,83 s je 4K-Bild und ist
speicherbandbreiten-gebunden, nicht rechengebunden: acht Worker bringen
Faktor 1,5, mehr Worker bringen nichts. Hochgerechnet auf 1000 Bilder
sind das rund 31 min — das ursprüngliche Ziel „1000 Bilder unter 10 min"
ist auf dieser Maschine nicht erreichbar. Das dokumentierte Ziel ist
stattdessen „voller Korpus unter 6 min".

## Repo-Struktur

```
docodetect/
  camera.py        Kamera-Capture (4K, MJPG, Autofokus-Lock)
  calibration.py   ArUco-Kalibrierung px→mm, Hintergrund-Referenz
  segmentation.py  Globaler Graph-Cut (Evidenz → Min-Cut → Kanten-Abschluss → Snap)
  features.py      Geometrie (mm-korrekt) + Farbe + Formmerkmale
  database.py      SQLite: Artikelstammdaten + Referenzmerkmale
  matcher.py       Stufe 1: Kandidatenfilter + Scoring + Confidence
  embeddings.py    Stufe 2: DINOv2 + FAISS (optional, lazy imports)
  pipeline.py      Orchestrierung Capture → Segment → Features → Match
  cli.py           Kommandozeilen-Interface
config/config.yaml Alle Parameter (Toleranzen, Schwellen, Pfade)
calibration/       Erzeugte Kalibrierdaten (calibration.json, background.png)
data/reference/    Eingelernte Referenzfotos pro Artikel
```

## Nächste Schritte (offen)

- [ ] FOV-Test mit größtem Teller → ggf. Kamerahöhe/Box anpassen
- [ ] Echte Artikelliste aus DO&CO-Datenbank exportieren (Mapping auf CSV-Schema)
- [ ] Beleuchtung finalisieren (diffus, konstant — Voraussetzung für Farbmerkmale)
- [ ] sigma_floors aus 15–20er-Messreihe bestimmen (siehe „Testphase" im
      Scoring-Abschnitt) — davor keine Schwellen anfassen
- [ ] Gelabeltes Testset aufbauen + `evaluate`/Batch-Tab: Posterior-Verteilung
      korrekt vs. falsch prüfen, erst bei Überlappung Schwellen justieren
- [ ] Stufe 2 aktivieren, falls Batch-Auswertung/Verwechslungsmatrix
      AMBIGUOUS-Häufungen zeigt (Hook: `TODO(stage-2)` in matcher.py)
- [ ] Smoke-Testset gegen Produktions-Config immunisieren: der Generator
      (`make-smoke-testset`, docodetect/smoke_testset.py) rendert aktuell in
      `camera.width/height` und misst gegen `matching`-Schwellen der
      geteilten config.yaml — eigene, gepinnte Auflösung/Schwellen für die
      Baseline, damit Produktions-Änderungen (z. B. 1080p→4K) die
      Regressionszahlen nicht verschieben (Baseline-Bilder auf Platte sind
      davon unberührt, nur eine NEU-Generierung wiche ab)
