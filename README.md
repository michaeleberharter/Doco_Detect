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
- [ ] Toleranzen in config.yaml anhand echter Messreihen justieren
- [ ] Stufe 2 aktivieren, falls Stufe-1-Confusion-Matrix Mehrdeutigkeiten zeigt
