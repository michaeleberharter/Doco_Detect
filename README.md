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
   leicht drehen/verschieben), z. B. per `enroll ART-NR --shots 20`.
2. Pro Merkmal die Standardabweichung über die Messreihe ablesen: die Skalar-
   Streuungen stehen nach dem Einlernen in `reference_stats` (`scalar_std`),
   die Streuung der Farb-/Formdistanzen als `proto_std`; alternativ die
   `measured`-Blöcke der Report-JSONs unter `data/captures/` auswerten.
3. Diese Std je Merkmal ist der Floor → in `matching.sigma_floors` eintragen.
   (Danach ggf. die Test-Referenzen wieder löschen: `delete-article` + neu
   anlegen, damit die 20 Messreihen-Shots nicht als Referenzen bleiben.)

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
