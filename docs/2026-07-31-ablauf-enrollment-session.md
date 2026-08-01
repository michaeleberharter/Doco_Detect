# Ablaufzettel: Enrollment-Session in der Sandbox

**Stand:** 2026-07-31 · Zum Ausdrucken. Kommandos sind ausgeschrieben.

Sandbox-Name in diesem Zettel: **`neuenroll-2026-08`**. Er steht in jedem
Kommando; wer einen anderen nimmt, muss ihn überall gleich ersetzen — ein
abweichender Name ist ein zweiter, leerer Bestand.

Alle Kommandos aus dem Projektverzeichnis `~/Documents/Doco_Detect`.
Statt `docodetect` ggf. `.venv/bin/python -m docodetect.cli` schreiben.

---

## Grundregeln für den ganzen Ablauf

**Die Kamera kann immer nur EIN Programm halten.** Das Qt-Fenster belegt sie
durchgehend, solange es offen ist. Während Qt läuft, scheitert jedes
CLI-Kommando, das die Kamera braucht, mit einem Kamera-Fehler. Deshalb:
**erst alle Artikel anlegen (CLI), Qt schließen, dann einlernen (Qt).**
Nicht in zwei Fenstern parallel.

**Kalibrierung und Hintergrund sind geteilt, nicht Teil der Sandbox.**
`calibrate` und `capture-background` brechen unter `--sandbox` mit Exit 1 ab,
und die beiden Knöpfe sind im Qt-Fenster ausgegraut. Beides gehört vor den
Durchlauf — siehe Schritt 0.

**Nichts von alledem berührt den Produktivbestand.** DB, Referenzbilder,
Verworfene, Captures und Berichte liegen unter `data/sandbox/neuenroll-2026-08/`.
Die produktive `doco_detect.sqlite3` und `data/reference/` bleiben unangetastet.

---

## Schritt 0 — Einrichtung prüfen (OHNE `--sandbox`)

Nur nötig, wenn die Box seit der letzten Kalibrierung bewegt wurde oder die
Beleuchtung sich geändert hat. Sonst überspringen.

```
docodetect capture-background
docodetect calibrate
```

*Kamera:* öffnet und schließt **pro Kommando einmal**, je eine Aufnahme.
Vor `capture-background` die Box **leeren**, vor `calibrate` den ArUco-Marker
hineinlegen.

**Achten auf:**
- `[calibration] background reference saved to …`
- `[calibration] mm_per_px = 0.17…  -> saved to …` — der Wert muss zur
  bisherigen Größenordnung passen. Ein Sprung heißt: Marker falsch erkannt.
- Ein alter Stand wird automatisch archiviert, nicht überschrieben.

---

## Schritt 1 — Sandbox anlegen

```
docodetect --sandbox neuenroll-2026-08 init-db
```

*Kamera:* wird **nicht** geöffnet.

**Achten auf** die Startzeile — sie nennt alle fünf Pfade. Alle müssen
`data/sandbox/neuenroll-2026-08/` enthalten:

```
[sandbox] 'neuenroll-2026-08' aktiv — db=… · referenzen=… · verworfen=… · captures=… · berichte=…
[db] schema ready at …/data/sandbox/neuenroll-2026-08/doco_detect.sqlite3
```

Steht dort irgendwo `data/reference` oder die DB im Projektstamm: **abbrechen**,
der Schalter hat nicht gegriffen.

---

## Schritt 2 — Artikel anlegen, einer nach dem anderen

Je Kommando: Objekt mittig in die Box legen, Kommando starten, Vorschau prüfen.

*Kamera:* öffnet, wärmt **10 Frames** auf (~0,5 s), macht **eine** Aufnahme,
schließt sofort wieder. Pro Artikel ein vollständiger Zyklus — das Klacken
zwischen den Artikeln ist normal.

**Bei jedem Artikel auf drei Dinge achten:**

1. **Die Maßzeile.** `'Löffel 1' angelegt als LOEFFEL-1 (194.4 × 40.9 mm, …)`
   — Länge und Breite müssen zum Objekt passen. Ein Löffel mit 274 mm ist eine
   Fehlmessung, kein langer Löffel.
2. **Rund oder länglich.** Steht dort `Ø 167.8 mm` statt `194.4 × 40.9 mm`,
   wurde das Objekt als **rund** klassifiziert. Bei Besteck ist das immer
   falsch und bleibt dauerhaft falsch: die Klassifikation entscheidet, ob
   später der Ø oder die Länge als Nominal verglichen wird. Dann Artikel
   löschen und neu anlegen (`docodetect --sandbox neuenroll-2026-08
   delete-article LOEFFEL-1`).
3. **`Farbe:`** muss plausibel sein. „schwarz" bei blankem Besteck heißt,
   dass die Segmentierung den Schatten statt das Objekt erwischt hat.

`--height-mm 0` ist bei flach aufliegendem Besteck **richtig**, nicht nur
bequem: die vermessene Kontur liegt auf dem Boden. Nur bei Tellern,
Schüsseln und Tassen ist ein Wert > 0 einzutragen — dann die Höhe der
**vermessenen Kontur** über dem Boden, nicht die Gesamthöhe des Objekts.

### Löffel

```
docodetect --sandbox neuenroll-2026-08 create-article "Löffel 1"  --article-number LOEFFEL-1  --height-mm 0 --category Loeffel
docodetect --sandbox neuenroll-2026-08 create-article "Löffel 2"  --article-number LOEFFEL-2  --height-mm 0 --category Loeffel
docodetect --sandbox neuenroll-2026-08 create-article "Löffel 3"  --article-number LOEFFEL-3  --height-mm 0 --category Loeffel
docodetect --sandbox neuenroll-2026-08 create-article "Löffel 4"  --article-number LOEFFEL-4  --height-mm 0 --category Loeffel
docodetect --sandbox neuenroll-2026-08 create-article "Löffel 5"  --article-number LOEFFEL-5  --height-mm 0 --category Loeffel
docodetect --sandbox neuenroll-2026-08 create-article "Löffel 6"  --article-number LOEFFEL-6  --height-mm 0 --category Loeffel
docodetect --sandbox neuenroll-2026-08 create-article "Löffel 7"  --article-number LOEFFEL-7  --height-mm 0 --category Loeffel
docodetect --sandbox neuenroll-2026-08 create-article "Löffel 8"  --article-number LOEFFEL-8  --height-mm 0 --category Loeffel
docodetect --sandbox neuenroll-2026-08 create-article "Löffel 9"  --article-number LOEFFEL-9  --height-mm 0 --category Loeffel
docodetect --sandbox neuenroll-2026-08 create-article "Löffel 10" --article-number LOEFFEL-10 --height-mm 0 --category Loeffel
docodetect --sandbox neuenroll-2026-08 create-article "Löffel 11" --article-number LOEFFEL-11 --height-mm 0 --category Loeffel
docodetect --sandbox neuenroll-2026-08 create-article "Löffel 12" --article-number LOEFFEL-12 --height-mm 0 --category Loeffel
docodetect --sandbox neuenroll-2026-08 create-article "Löffel 13" --article-number LOEFFEL-13 --height-mm 0 --category Loeffel
docodetect --sandbox neuenroll-2026-08 create-article "Löffel 14" --article-number LOEFFEL-14 --height-mm 0 --category Loeffel
docodetect --sandbox neuenroll-2026-08 create-article "Löffel 15" --article-number LOEFFEL-15 --height-mm 0 --category Loeffel
```

### Gabeln

```
docodetect --sandbox neuenroll-2026-08 create-article "Gabel 1"  --article-number GABEL-1  --height-mm 0 --category Gabel
docodetect --sandbox neuenroll-2026-08 create-article "Gabel 2"  --article-number GABEL-2  --height-mm 0 --category Gabel
docodetect --sandbox neuenroll-2026-08 create-article "Gabel 3"  --article-number GABEL-3  --height-mm 0 --category Gabel
docodetect --sandbox neuenroll-2026-08 create-article "Gabel 4"  --article-number GABEL-4  --height-mm 0 --category Gabel
docodetect --sandbox neuenroll-2026-08 create-article "Gabel 5"  --article-number GABEL-5  --height-mm 0 --category Gabel
docodetect --sandbox neuenroll-2026-08 create-article "Gabel 6"  --article-number GABEL-6  --height-mm 0 --category Gabel
docodetect --sandbox neuenroll-2026-08 create-article "Gabel 7"  --article-number GABEL-7  --height-mm 0 --category Gabel
docodetect --sandbox neuenroll-2026-08 create-article "Gabel 8"  --article-number GABEL-8  --height-mm 0 --category Gabel
docodetect --sandbox neuenroll-2026-08 create-article "Gabel 9"  --article-number GABEL-9  --height-mm 0 --category Gabel
docodetect --sandbox neuenroll-2026-08 create-article "Gabel 10" --article-number GABEL-10 --height-mm 0 --category Gabel
docodetect --sandbox neuenroll-2026-08 create-article "Gabel 11" --article-number GABEL-11 --height-mm 0 --category Gabel
docodetect --sandbox neuenroll-2026-08 create-article "Gabel 12" --article-number GABEL-12 --height-mm 0 --category Gabel
docodetect --sandbox neuenroll-2026-08 create-article "Gabel 13" --article-number GABEL-13 --height-mm 0 --category Gabel
docodetect --sandbox neuenroll-2026-08 create-article "Gabel 14" --article-number GABEL-14 --height-mm 0 --category Gabel
```

### Messer

```
docodetect --sandbox neuenroll-2026-08 create-article "Messer 1"  --article-number MESSER-1  --height-mm 0 --category Messer
docodetect --sandbox neuenroll-2026-08 create-article "Messer 2"  --article-number MESSER-2  --height-mm 0 --category Messer
docodetect --sandbox neuenroll-2026-08 create-article "Messer 3"  --article-number MESSER-3  --height-mm 0 --category Messer
docodetect --sandbox neuenroll-2026-08 create-article "Messer 4"  --article-number MESSER-4  --height-mm 0 --category Messer
docodetect --sandbox neuenroll-2026-08 create-article "Messer 5"  --article-number MESSER-5  --height-mm 0 --category Messer
docodetect --sandbox neuenroll-2026-08 create-article "Messer 6"  --article-number MESSER-6  --height-mm 0 --category Messer
docodetect --sandbox neuenroll-2026-08 create-article "Messer 7"  --article-number MESSER-7  --height-mm 0 --category Messer
docodetect --sandbox neuenroll-2026-08 create-article "Messer 8"  --article-number MESSER-8  --height-mm 0 --category Messer
docodetect --sandbox neuenroll-2026-08 create-article "Messer 9"  --article-number MESSER-9  --height-mm 0 --category Messer
docodetect --sandbox neuenroll-2026-08 create-article "Messer 10" --article-number MESSER-10 --height-mm 0 --category Messer
docodetect --sandbox neuenroll-2026-08 create-article "Messer 11" --article-number MESSER-11 --height-mm 0 --category Messer
```

### Zwischenkontrolle

```
sqlite3 data/sandbox/neuenroll-2026-08/doco_detect.sqlite3 "select count(*), sum(diameter_mm is not null) from articles;"
```

Erwartet: `40|0` — 40 Artikel, **keiner** davon rund. Steht rechts etwas
anderes als 0, wurde mindestens ein Besteckteil als rund klassifiziert.

---

## Schritt 3 — Einlernen im Qt-Fenster

```
python -m docodetect.ui_qt --sandbox neuenroll-2026-08
```

*Kamera:* wird beim Start geöffnet und bleibt **die ganze Sitzung über offen**.
Sie schließt erst beim Beenden des Fensters. Bricht die Verbindung ab, versucht
das Programm alle paar Sekunden selbst einen Reconnect.

**Beim Start achten auf:**
- dieselbe `[sandbox]`-Zeile mit den fünf Pfaden wie in Schritt 1
- Statusleiste: `40 Artikel (0 eingelernt)`
- „Hintergrund aufnehmen" und „Kalibrieren" sind **ausgegraut** — so soll es
  sein, der Tooltip nennt den Grund
- Am Mac erscheint eine **Fokus-Warnung**. Das ist erwartbar (AVFoundation
  lässt die Kamera-Properties nicht setzen) und kein Fehler.

**Je Artikel:**

1. „Artikel einlernen…" drücken.
2. Im Dropdown den Artikel wählen — tippen filtert. **Ein frei eingetippter
   Name legt keinen Artikel an**; steht dort „Keinen Artikel gewählt", ist
   nichts ausgewählt.
3. „Aufnahmen" steht auf **12**. So lassen.
4. Objekt auflegen, „Aufnehmen". **Zwischen den Aufnahmen das Objekt drehen
   und verschieben** — die Streuung über die 12 Shots ist genau das, was
   später `sigma_eff` bestimmt. Zwölfmal dieselbe Lage ergibt ein zu kleines
   σ und damit ein zu scharfes Gate.
5. Nach jeder Aufnahme erscheint ein Thumbnail mit Ø. **Ausreißer sofort
   erkennen:** ein Thumbnail, dessen Ø deutlich abweicht, per Klick auswählen
   und mit „Aufnehmen" wiederholen.
6. Nach 12 Aufnahmen „Speichern".
7. Es erscheint **erst das Diagnoseblatt**, noch ist nichts in der DB
   (Rendern dauert ~1 s je Aufnahme).

**Auf dem Diagnoseblatt prüfen, bevor „Übernehmen":**

- **Feld c (Messwert je Shot):** eine sichtbare Drift über die Shots — Werte,
  die von S1 nach S12 wandern statt zu streuen — heißt, dass sich etwas
  verändert hat (Beleuchtung, Position, Objekt verbogen). Dann verwerfen.
- **Streuungstabelle:** σ(Ø) im Bereich **0,4–0,9 mm** ist sauber. Deutlich
  darüber ist ein Warnsignal. **LOEFFEL-3 ist ein bekannt harter Fall** —
  aus dem Altbestand mit σ(Ø) = 1,87 mm gemessen. Dort besonders hinsehen.
- **Konturband:** die 12 Konturen sollen als schmales Band übereinanderliegen.
  Eine Kontur, die ausbricht, ist die, die man wiederholen sollte.

**„Übernehmen"** schreibt die 12 Referenzen in die Sandbox-DB und legt das
Blatt unter `data/sandbox/neuenroll-2026-08/reports/enrollment/<nr>.png` ab.

**„Verwerfen"** schreibt **nichts** in die DB, sichert aber Aufnahmen und Blatt
nach `data/sandbox/neuenroll-2026-08/verworfen/<nr>/<zeitstempel>/`. Das ist
Absicht: verworfenes Material beantwortet später die Frage, warum es verworfen
wurde. Danach kann derselbe Artikel sofort neu aufgenommen werden.

**Nicht zweimal denselben Artikel „übernehmen".** `reference_stats` kennt
keinen Session-Begriff — zwei Sessions verschmelzen still zu **einem** σ. In
einer frischen Sandbox-DB ist das kein Thema, solange jeder Artikel genau
einmal übernommen wird. Passiert es doch: Artikel löschen und komplett neu.

---

## Schritt 4 — Stichprobe

Qt geöffnet lassen. Ein bereits eingelerntes Teil auflegen, **Leertaste**.

**Achten auf:** ACCEPT mit dem richtigen Artikel. Bei AMBIGUOUS zeigt die
Karte die Kandidaten — bei baugleichem Besteck ist das erwartbar und kein
Fehler. Jede Identifikation schreibt Bild + Report nach
`data/sandbox/neuenroll-2026-08/captures/`, nicht in den Produktivbestand.

Für einen Blick auf die Streuung eines Artikels nach dem Einlernen, mit
geschlossenem Qt-Fenster:

```
docodetect --sandbox neuenroll-2026-08 enrollment-sheet LOEFFEL-3
docodetect --sandbox neuenroll-2026-08 contour-band LOEFFEL-3
```

*Kamera:* wird bei beiden **nicht** geöffnet — sie rechnen auf den
gespeicherten Bildern.

---

## Schritt 5 — Danach

Der Produktivbestand ist unverändert. Die Sandbox lässt sich als Ganzes
beurteilen, behalten oder wegräumen (verschieben, nicht löschen):

```
mv data/sandbox/neuenroll-2026-08 backups/2026-08-XX-enrollment-sandbox/
```

Ob und wie der Sandbox-Stand produktiv wird, ist eine eigene Entscheidung —
dieser Zettel endet hier.

---

## Was in der Sandbox gesperrt ist

| Kommando | Warum |
|---|---|
| `calibrate`, `capture-background` | Kalibrierung/Hintergrund sind geteilt |
| Qt-Knöpfe „Kalibrieren", „Hintergrund aufnehmen" | dieselben Schreibpfade |
| `make-smoke-testset` | verschiebt Kalibrierung und DB beiseite |
| `analyze --publish` | `reports/archive` ist versioniert |
| `corpus-build`, `corpus-run`, `corpus-diff`, `corpus-report`, `corpus-triage` | Korpus ist das Regressionsgate |
| `--sandbox` zusammen mit `--demo` | zwei kollidierende Umlenkungen |

Alle brechen mit Exit 1 und Klartext ab. Details:
[2026-07-31-sandbox-isolierter-db-stand.md](2026-07-31-sandbox-isolierter-db-stand.md).
