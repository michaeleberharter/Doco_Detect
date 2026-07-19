# Plan: Native Desktop-UI mit PySide6 (`docodetect/ui_qt/`)

Umsetzungsplan für Claude Code. Ziel: eine native Desktop-App (Windows + macOS) als
Bedienoberfläche für Doco_Detect — Ersatz bzw. Ergänzung der Streamlit-UI. Die App
ist das, was der Bediener an der Fotobox sieht: Live-Vorschau, ein großer
„Identifizieren"-Button, klares Ergebnis.

**Arbeitsweise:** Der gesamte Plan darf in einer Session umgesetzt werden —
aber die Phasen bleiben strikt **sequenziell**, denn sie bauen aufeinander auf
und fassen dieselben Dateien an (`main_window.py`, `pipeline.py`). Keine
parallelen Subagents auf verschiedenen Phasen. Nach jeder Phase führt Claude
Code die Abnahmekriterien **selbst** aus (Demo-Modus, Smoke-Tests, für die
Kamera Phase 0), statt auf manuelle Abnahme zu warten; erst bei Grün beginnt
die nächste Phase. Bei Unklarheiten über bestehende Signaturen in
`pipeline.py`: erst Code lesen, dann minimal erweitern — nicht raten.

---

## 1. Architektur-Invarianten (nicht verhandelbar)

1. **Die UI ruft ausschließlich `pipeline.py` auf.** Keine direkten Imports von
   `database.py`, `matcher.py`, `segmentation.py`, `camera.py` in UI-Code. Fehlt
   der UI eine Funktion (z. B. Artikelliste, Kalibrierstatus), wird sie als dünne
   Fassade in `pipeline.py` ergänzt (siehe Abschnitt 5).
2. **Alle Parameter kommen aus `config/config.yaml`** — auch UI-Parameter (neue
   `ui:`-Sektion, Abschnitt 8). Keine Magic Numbers im UI-Code.
3. **Alle Längen in mm.** Die UI zeigt mm an, rechnet aber nie selbst — Messwerte
   kommen fertig aus der Pipeline (inkl. Höhenkompensation).
4. **Kein Training, keine neuen Modelle.** Die UI ändert nichts an Stufe 1/2.
5. **Kein Streamlit-Code kopieren.** Die Streamlit-UI bleibt unangetastet und
   funktionsfähig; beide UIs teilen sich dieselbe Pipeline-Fassade.

---

## 2. Neue Dateien

```
docodetect/ui_qt/
  __init__.py
  __main__.py          # Entry: python -m docodetect.ui_qt  [--demo] [--config PFAD]
  app.py               # QApplication-Setup, Fusion-Style, QSS laden, High-DPI
  main_window.py       # Hauptfenster, Layout, Zustandsmaschine (siehe 6.4)
  camera_worker.py     # QThread: einziger Kamera-Besitzer, Frames per Signal
  pipeline_worker.py   # QThread/QRunnable: identify/enroll/calibrate im Hintergrund
  demo_source.py       # Bildquelle aus Testbildern statt Kamera (--demo)
  widgets/
    __init__.py
    preview.py         # Live-Vorschau (QLabel-basiert), Overlays, Rand-Warnung
    result_card.py     # Kandidaten-Karte (Name, Nr., Ø gemessen vs. DB, Score-Balken)
    status_bar.py      # Kalibrierstatus, Kamera/FPS, Artikelanzahl, Stufe-2-Status
    enroll_dialog.py   # Einlern-Assistent (Artikelwahl + n Aufnahmen mit Fortschritt)
  style.qss            # Dark Theme (siehe 7)
  assets/              # App-Icon (icon.ico, icon.icns, icon.png), ggf. Sounds
requirements-ui.txt    # PySide6, qtawesome  (analog zu requirements-stage2.txt)
```

Installation (in bestehende venv):

```powershell
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
python -m pip install -r requirements-ui.txt
```
```bash
# macOS:
source .venv/bin/activate
python -m pip install -r requirements-ui.txt
```

---

## 3. Kritischster Punkt: Kamera-Ownership

Es darf **genau ein** Kamera-Handle geben. Aktuell öffnet `camera.py` die Kamera
pro Pipeline-Aufruf — das kollidiert mit einer Live-Vorschau (zwei `VideoCapture`
auf dasselbe Gerät schlagen fehl oder liefern Müll).

**Lösung:** Der `CameraWorker` der UI ist der alleinige Kamera-Besitzer und hält
das Gerät dauerhaft offen (4K, MJPG, Autofokus-Lock — dieselbe Initialisierung
wie `camera.py`, idealerweise durch Wiederverwendung der Setup-Funktion aus
`camera.py`, nicht durch Kopie). Alle Pipeline-Aktionen (identify, enroll,
calibrate, capture-background) erhalten **das Bild als Argument** statt selbst
zu capturen. Der CLI-Pfad `identify --image foto.jpg` zeigt, dass ein
bildbasierter Weg existiert — falls `pipeline.py` bisher nur Dateipfade nimmt,
auf `np.ndarray` erweitern (Pfad-Variante als Wrapper behalten, CLI bleibt
kompatibel).

---

## 4. Threading-Modell

Der GUI-Thread darf **nie** blockieren (kein `VideoCapture.read()`, kein
Pipeline-Aufruf, kein DINOv2 im Main-Thread).

**`CameraWorker` (QThread):**
- Öffnet die Kamera einmal (Backend siehe Abschnitt 9), verwirft
  `warmup_frames`, läuft dann in einer Grab-Schleife.
- Preview: Frame per `cv2.resize` auf `ui.preview_max_width` verkleinern,
  Signal `frame_ready(QImage)` mit ca. `ui.preview_fps` (überzählige Frames per
  `cap.grab()` verwerfen, damit der Puffer nicht altert — sonst zeigt die
  Vorschau die Vergangenheit).
- Voll-Auflösung auf Anfrage: Slot `request_full_frame()` → nächster kompletter
  4K-Frame → Signal `full_frame_ready(np.ndarray)` (BGR, unverändert — das ist
  das Bild für die Pipeline).
- Fehlerpfad: Kamera nicht gefunden / Verbindung verloren → Signal
  `camera_error(str)`, UI zeigt Zustand „Keine Kamera" (siehe 6.4) statt zu
  crashen. Reconnect-Versuch alle paar Sekunden.

**`PipelineWorker`:**
- Führt genau eine Pipeline-Aktion aus (identify/enroll_shot/calibrate/
  capture_background) und stirbt. Signale: `finished(object)` mit dem
  Result-Objekt, `failed(str)` mit verständlicher Meldung.
- Während ein Worker läuft: Aktions-Buttons deaktiviert, dezenter
  Busy-Indikator über der Vorschau. Kein zweiter paralleler Lauf möglich.
- Stufe 2 (DINOv2) kann Sekunden dauern — genau deshalb Worker-Thread.

**Frame → Anzeige (Klassiker, bitte exakt so):**

```python
rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
h, w, _ = rgb.shape
qimg = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()
```

Das `.copy()` ist Pflicht — `QImage` referenziert sonst den numpy-Puffer, der im
Worker sofort überschrieben wird (führt zu Bildmüll/Abstürzen). `3 * w` als
bytesPerLine explizit setzen (Stride).

Signale zwischen Threads laufen automatisch als QueuedConnection — keine
eigenen Locks für die UI-Kommunikation bauen.

---

## 5. Minimale Fassaden-Erweiterungen in `pipeline.py`

Erst prüfen, was schon existiert; nur ergänzen, was fehlt. Zielbild:

- `identify(image: np.ndarray) -> IdentifyResult` — Result enthält: Liste der
  Top-k-Kandidaten (Artikel-ID, Name, Score, Ø_gemessen_mm, Ø_db_mm,
  height_mm), Entscheidung (`auto_accept` / `ambiguous` / `no_match` /
  `object_clipped` / `not_calibrated`), sowie ein **annotiertes Bild**
  (Kontur + Maßlinien eingezeichnet) für die Ergebnisanzeige. Falls es noch
  kein annotiertes Debug-Bild gibt: als optionales Feld ergänzen.
- `capture_background(image) `, `calibrate(image)`, `enroll_shot(article_id,
  image, shot_index)` — Einzelbild-APIs. Wichtig für den Einlern-Dialog: die
  CLI-Schleife (`--shots 8`) wird in der UI durch n einzelne
  `enroll_shot`-Aufrufe mit Nutzer-Interaktion dazwischen ersetzt
  („Teller drehen, dann weiter").
- `list_articles() -> list[ArticleInfo]` — für das Einlern-Dropdown
  (Weiterleitung an `database.py`, damit die UI-Regel hält).
- `get_status() -> Status` — Kalibrierung vorhanden? (px/mm-Faktor, Datum aus
  `calibration.json`), Hintergrund vorhanden?, Artikel in DB, Referenzen pro
  Artikel, Stufe 2 aktiv?

Alle Erweiterungen müssen von der bestehenden Streamlit-UI und CLI mitbenutzt
werden können (reine Ergänzung, keine Signatur-Brüche).

---

## 6. UI-Design

Zielgruppe: Bediener an der Spülstraße/Sortierstation, kurze Blickzeiten,
evtl. nasse Hände am Touchscreen. Daraus folgt: **große Flächen, wenige
Elemente, eindeutige Sprache, hoher Kontrast.** Das Signatur-Element der App
ist die große Live-Vorschau mit Mess-Overlay — alles andere bleibt ruhig.

### 6.1 Layout (Hauptfenster, min. 1280×800)

```
┌────────────────────────────────────────────┬──────────────────────────┐
│                                            │  DOCO DETECT             │
│                                            │                          │
│         LIVE-VORSCHAU                      │  [   IDENTIFIZIEREN   ]  │  ← groß, Leertaste
│         (füllt Platz, hält 16:9,           │                          │
│          Fadenkreuz-Mitte,                 │  Ergebnis                │
│          Rand-Warnrahmen)                  │  ┌────────────────────┐  │
│                                            │  │ ResultCard #1      │  │
│                                            │  │ ResultCard #2      │  │
│                                            │  │ ResultCard #3      │  │
│                                            │  └────────────────────┘  │
│                                            │                          │
│                                            │  Hintergrund aufnehmen   │  ← sekundär,
│                                            │  Kalibrieren             │    kleiner
│                                            │  Artikel einlernen…      │
├────────────────────────────────────────────┴──────────────────────────┤
│ ● Kamera 15 fps · Kalibriert 12.07. (0,171 mm/px) · 214 Artikel · S2 aus │
└───────────────────────────────────────────────────────────────────────┘
```

### 6.2 Live-Vorschau (`widgets/preview.py`)

- Skaliert mit dem Fenster, hält Seitenverhältnis (letterboxing, kein
  Verzerren).
- Dezentes Fadenkreuz + Mittelpunktmarke zum Ausrichten des Geschirrs.
- Nach einer Identifikation: für einige Sekunden das **annotierte Bild**
  (Kontur + Ø-Maßlinie in mm) einblenden, dann zurück zur Live-Ansicht.
  Umschalten auch per Klick auf die Vorschau.
- Rand-Warnung: Meldet die Pipeline `object_clipped`, färbt sich der
  Vorschau-Rahmen rot mit Meldung im Bild: **„Objekt berührt den Bildrand —
  weiter zur Mitte legen."** (Kein Popup — der Bediener schaut auf die
  Vorschau.)

### 6.3 Ergebnis-Panel (`widgets/result_card.py`)

Pro Kandidat eine Karte:

- **Artikelname** groß, Artikelnummer klein darunter.
- „Ø gemessen 268,4 mm · Datenbank 270 mm (±6)" — die Zahl, die Vertrauen
  schafft.
- Score als horizontaler Balken + Prozentwert.
- Farbcodierung konsistent mit `config.matching`: Grün wenn
  `score ≥ auto_accept_score` **und** Abstand zum Zweitplatzierten ≥
  `auto_accept_margin` (= die Pipeline hat auto-akzeptiert), Gelb für „bitte
  bestätigen", neutral/grau für die übrigen Vorschläge.
- Bei `auto_accept`: Karte #1 erscheint mit deutlichem grünem Zustand
  „✓ Erkannt: <Name>"; optional kurzer Bestätigungston
  (`ui.confirm_sound`).
- Bei `ambiguous`: Überschrift „Bitte bestätigen" — Karten sind klickbar,
  Klick = manuelle Bestätigung (vorerst nur visuell quittieren + im Log
  vermerken; Buchungs-Anbindung ist nicht Teil dieses Plans).
- Bei `no_match`: „Kein Artikel passt. Prüfen: richtig gelegt? Artikel
  eingelernt?" mit Direkt-Button „Artikel einlernen…".

Interface-Sprache durchgängig: aktive Verben, ein Begriff pro Aktion
(Button „Identifizieren" → Ergebnis „Erkannt", nie mal „Scannen", mal
„Analysieren"). Fehlertexte sagen immer, **was zu tun ist**, nicht nur was
schiefging.

### 6.4 Zustandsmaschine des Hauptfensters

Zustände explizit modellieren (ein Enum, ein `set_state()`):

1. **NO_CAMERA** — Vorschau zeigt Platzhalter „Keine Kamera gefunden —
   Verbindung wird gesucht…"; nur „Einstellungen/Demo" aktiv.
2. **NOT_READY** — Kamera läuft, aber Hintergrund/Kalibrierung fehlen
   (aus `get_status()`). Vorschau live, aber „Identifizieren" deaktiviert mit
   Tooltip; stattdessen geführter Hinweis im Ergebnis-Panel: „Einrichtung:
   1. Box leeren → Hintergrund aufnehmen. 2. Marker einlegen → Kalibrieren."
   Erledigte Schritte abgehakt.
3. **READY** — Normalbetrieb.
4. **BUSY** — Pipeline läuft; Aktionen deaktiviert, Busy-Overlay.

Der Empty State ist damit eine Handlungsanleitung, kein toter Bildschirm.

### 6.5 Einlern-Dialog (`widgets/enroll_dialog.py`)

- Artikel-Auswahl: durchsuchbares Dropdown (QComboBox + Completer) aus
  `list_articles()`; Anzeige, wie viele Referenzen der Artikel schon hat.
- Ablauf: „Aufnahme 3 von 8 — Artikel etwas drehen, dann ‚Aufnehmen'."
  Nach jedem Shot Thumbnail-Leiste der bisherigen Aufnahmen; einzelne
  wiederholbar. Shots-Anzahl aus Config-Default, im Dialog änderbar.
- Nutzt denselben `full_frame_ready`-Weg + `enroll_shot()` pro Bild.

### 6.6 Shortcuts

- **Leertaste = Identifizieren** (der eine, wichtige Shortcut — muss auch mit
  Fokus irgendwo im Fenster funktionieren, also als QAction mit
  `WindowShortcut`).
- Esc schließt Dialoge. Mehr nicht — keine Shortcut-Sammlung erfinden.

---

## 7. Styling (`style.qss`)

- Basis: `QApplication.setStyle("Fusion")` + dunkle QPalette + QSS obendrauf.
  (Fusion sieht auf Windows und macOS gleich aus — gewollt, die App soll auf
  beiden Systemen identisch bedienbar sein.)
- Dunkles, ruhiges Theme: sehr dunkles Grau als Fläche (kein reines Schwarz),
  eine einzige Akzentfarbe für den Primär-Button und Zustands-Grün/-Gelb/-Rot
  für Ergebnisse — sonst keine Farben. Die Vorschau ist der Star; das Chrome
  drumherum tritt zurück.
- Typografie: Systemschrift (`Segoe UI` / `SF Pro` via QFont-Default),
  klare Größenhierarchie: Artikelname ~20 pt, Messwerte ~14 pt tabellarisch
  (`font-variant-numeric` gibt's in QSS nicht — Zahlen ggf. mit fester Breite
  formatieren), Statusleiste klein.
- Primär-Button „Identifizieren": mindestens 64 px hoch, volle Panelbreite.
- Icons sparsam über `qtawesome` (z. B. Kamera-, Ziel-, Häkchen-Icon).
- High-DPI: Qt 6 skaliert automatisch; nichts in Pixeln „festnageln", Layouts
  statt fixer Geometrien.
- Alle Farb-/Größenwerte am Kopf der QSS-Datei als kommentierte Palette, damit
  Anpassung an DO&CO-CI später ein Fünf-Minuten-Job ist.

---

## 8. `config/config.yaml` — neue Sektion

```yaml
ui:
  preview_max_width: 960     # px, Downscale für Live-Vorschau
  preview_fps: 15            # Ziel-FPS der Vorschau (4K-MJPG-Decode ist teuer)
  result_overlay_secs: 4     # wie lange das annotierte Ergebnisbild steht
  confirm_sound: true        # Ton bei auto_accept
  window_min_width: 1280
  window_min_height: 800
```

`--demo` bleibt bewusst ein CLI-Flag (kein Config-Eintrag): Demo ist ein
Entwicklungsmodus, kein Betriebsparameter.

---

## 9. Plattform-Handling (Mac ⇄ Windows)

Der Python-Code ist auf beiden Systemen identisch lauffähig; genau drei
Stellen sind plattformabhängig und gehören **nach `camera.py`** (nicht in die
UI):

1. **Capture-Backend:**

   ```python
   if sys.platform == "win32":
       backend = cv2.CAP_DSHOW        # nötig für MJPG-4K + UVC-Properties
   elif sys.platform == "darwin":
       backend = cv2.CAP_AVFOUNDATION
   else:
       backend = cv2.CAP_V4L2
   cap = cv2.VideoCapture(index, backend)
   ```

   Optional per `camera.backend`-Eintrag in der Config überschreibbar.

2. **Fokus-Lock:** `CAP_PROP_AUTOFOCUS=0` / `CAP_PROP_FOCUS=<wert>`
   funktioniert unter Windows (DSHOW) zuverlässig, unter macOS/AVFoundation
   häufig **nicht**. Verhalten: Rückgabewert prüfen; wenn Setzen fehlschlägt →
   Warnung in Statusleiste „Fokus-Lock nicht verfügbar — Messbetrieb nur unter
   Windows verlässlich", kein Crash. (Mess-/Produktivbetrieb läuft am
   Windows-PC an der Box; der Mac ist Entwicklungsumgebung.)
3. **Pfade:** ausschließlich `pathlib.Path`, alle Pfade relativ zum
   Projekt-/Config-Ort auflösen. Keine Backslash-Literale.

macOS fragt beim ersten Kamerazugriff nach Berechtigung — normal, einmal
erlauben. (Für ein späteres `.app`-Bundle braucht es
`NSCameraUsageDescription`, siehe Phase 6.)

---

## 10. Demo-Modus (`--demo`) — zuerst bauen, dann Kamera

Solange die physische Kamera/Box nicht angeschlossen ist, muss die komplette
UI trotzdem end-to-end testbar sein:

- `demo_source.py` implementiert dieselbe Schnittstelle wie der CameraWorker
  (gleiche Signale), liefert aber Bilder aus einem Ordner (Default:
  das synthetische Testkit / `data/testset`).
- In der Vorschau erscheint eine schmale Demo-Leiste: Bildauswahl-Dropdown
  (Hintergrund, Marker, Teller 27, Teller 25, Schüssel, Randbild) — damit
  lassen sich Kalibrieren → Identifizieren → Randfehler komplett ohne
  Hardware durchspielen.
- `full_frame_ready` liefert das gewählte Bild in Originalauflösung — die
  Pipeline merkt keinen Unterschied.

---

## 11. Umsetzungsphasen mit Abnahme

**Phase 0 — Hardware-Smoke-Test (Kamera ist angeschlossen — zuerst machen).**
Kleines Skript `scripts/camera_check.py` (kein Qt, ~30 Zeilen): Kamera mit
plattformrichtigem Backend (Abschnitt 9) öffnen, verifizieren und ausgeben:
tatsächliche Auflösung == 3840×2160, FOURCC == MJPG, `CAP_PROP_AUTOFOCUS=0`
setzen und **zurücklesen**, `CAP_PROP_FOCUS=config.focus_value` setzen und
zurücklesen, `warmup_frames` verwerfen, einen Frame nach
`data/captures/camera_check.jpg` speichern, gemessene Grab-FPS über 3 Sekunden
ausgeben. *Abnahme:* Skript meldet auf dem Windows-PC mit der UGREEN-Kamera
alle Prüfungen OK. Damit ist das größte Risiko (Backend, 4K-MJPG, Fokus-Lock)
geklärt, **bevor** UI-Code entsteht — schlägt hier etwas fehl, erst das lösen.

**Phase 1 — Skeleton.**
Paketstruktur, `__main__.py`, Fenster mit Layout-Platzhaltern, Fusion + QSS,
Statusleiste zeigt echte Werte aus `get_status()` (Fassade dafür zuerst).
*Abnahme:* `python -m docodetect.ui_qt` öffnet das Fenster auf Mac und
Windows; Streamlit-UI und CLI unverändert lauffähig.

**Phase 2 — Demo-Quelle + Vorschau.**
`demo_source.py`, Preview-Widget mit Skalierung/Fadenkreuz, Zustandsmaschine
NO_CAMERA/NOT_READY/READY.
*Abnahme:* `--demo` zeigt die Testbilder live umschaltbar; Fenster-Resize
verzerrt nichts; CPU-Last im Leerlauf gering.

**Phase 3 — Pipeline-Anbindung (der Kern).**
Fassaden-Erweiterungen aus Abschnitt 5, `PipelineWorker`, Identifizieren per
Button/Leertaste, ResultCards, annotiertes Ergebnisbild, Randfehler-Anzeige.
*Abnahme im Demo-Modus:* Hintergrundbild → „Hintergrund aufnehmen", Marker →
„Kalibrieren", dann 27-cm-Teller → korrekter Artikel grün mit plausiblem Ø;
25-cm-Teller → korrekt; Randbild → rote Rand-Warnung statt Messwert. GUI
bleibt während allem bedienbar (nichts friert ein).

**Phase 4 — CameraWorker (echte Kamera).**
Kamera-Ownership gemäß Abschnitt 3, Backend-Wahl gemäß Abschnitt 9,
Reconnect-Logik, FPS-Anzeige.
*Abnahme:* Mit angeschlossener UVC-Webcam (notfalls interner Mac-Kamera als
Platzhalter): Live-Bild stabil, `request_full_frame` liefert volle Auflösung,
Kamera abziehen → Zustand NO_CAMERA → wieder anstecken → erholt sich.
Fokus-Lock-Warnung erscheint auf macOS, nicht auf Windows.

**Phase 5 — Einlern-Dialog + Polish.**
`enroll_dialog.py` mit Einzel-Shot-Ablauf, Busy-Overlay, Bestätigungston,
Tooltips/Fehlertexte gemäß 6.3, finaler QSS-Durchgang.
*Abnahme:* Kompletter Einlern-Durchlauf (Demo oder Kamera) legt Referenzen an,
die anschließend beim Identifizieren wirken; alle Fehlerzustände zeigen
handlungsleitende Texte.

**Phase 6 — optional, erst nach stabiler UI: Packaging.**
Zwei PyInstaller-Specs (`packaging/doco_detect_win.spec`,
`packaging/doco_detect_mac.spec`), `--windowed`. Wichtig:

- `config/`, `calibration/`, `data/`, die SQLite-DB **nicht einbetten**,
  sondern neben der Exe erwarten (portables Layout). Pfadauflösung: wenn
  `getattr(sys, "frozen", False)` → Basisverzeichnis =
  `Path(sys.executable).parent`, sonst wie bisher.
- macOS-Spec: `info_plist={"NSCameraUsageDescription": "…"}`; unsignierte App
  beim ersten Start per Rechtsklick → Öffnen.
- Builds sind plattformgebunden: `.exe` auf dem Windows-PC bauen, `.app` am
  Mac — jeweils aus demselben Code-Stand.

---

## 12. Fallstricke-Checkliste (vor jedem Commit gegenlesen)

- [ ] Kein zweites `VideoCapture` irgendwo (auch nicht „kurz" in einem Dialog).
- [ ] Kein Pipeline-/Kamera-Aufruf im GUI-Thread.
- [ ] `QImage(...).copy()` bei jeder numpy→Qt-Konvertierung, Stride gesetzt.
- [ ] UI importiert nur `docodetect.pipeline` (+ Qt, cv2 fürs Konvertieren).
- [ ] Neue Parameter in `config.yaml`, dokumentiert, mit Default im Code-Fallback.
- [ ] Fehlertexte nennen die Abhilfe („weiter zur Mitte legen"), nie nur den Fehler.
- [ ] Streamlit-UI und CLI nach jeder Phase unverändert funktionsfähig.
- [ ] Läuft auf Mac **und** Windows aus dem Repo (`python -m docodetect.ui_qt`).
