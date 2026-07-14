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
python -m docodetect.cli capture-background      # leere Box fotografieren
python -m docodetect.cli calibrate               # Marker liegt in der Box

# 3. Artikel einlernen (Referenzmerkmale, mehrere Rotationen)
python -m docodetect.cli enroll TELLER-27-WEISS --shots 8

# 4. Identifizieren
python -m docodetect.cli identify                # Live-Aufnahme
python -m docodetect.cli identify --image foto.jpg

# 5. Genauigkeit messen (Ordner mit gelabelten Testbildern)
python -m docodetect.cli evaluate data/testset/
```

## Test-UI (Streamlit)

Browser-Oberfläche für denselben Workflow (Hintergrund, Kalibrieren,
Identifizieren, Einlernen) mit Live-Kamera-Vorschau – praktisch zum Testen,
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

## Repo-Struktur

```
docodetect/
  camera.py        Kamera-Capture (4K, MJPG, Autofokus-Lock)
  calibration.py   ArUco-Kalibrierung px→mm, Hintergrund-Referenz
  segmentation.py  Hintergrund-Differenz → Objektkontur + Randprüfung
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
