# Ablaufzettel: Enrollment-Session in der Sandbox

**Stand:** 2026-08-01 (Erstfassung 2026-07-31) · Zum Ausdrucken. Kommandos sind
ausgeschrieben.

> **Was sich am 2026-08-01 geändert hat** — vier Punkte, alle aus der
> Auswertung der ersten Session nach diesem Zettel:
>
> 1. **Verteilte Auflage ist Pflicht** (Schritt 3). Die erste Session lernte am
>    Fixpunkt ein; die Referenzen waren dadurch unbrauchbar für den
>    Produktivbestand und liessen drei Scoring-Fragen unentscheidbar.
> 2. **σ gegen Floor je Merkmal** statt „σ(Ø) 0,4–0,9 mm" (Schritt 3) — das
>    alte Kriterium prüfte das einzige Merkmal, das nie auffällig wird. Die
>    acht Floor-Werte stehen jetzt im Zettel.
> 3. **Zwei neue Pflichtschritte:** σ-Endkontrolle je Artikel (Schritt 4) und
>    Duplikat-Scan über den fertigen Bestand (Schritt 5). Ohne den zweiten
>    waren drei von fünfzehn „Artikeln" dasselbe Messer.
> 4. Schritt 1 nennt das `init-db`-Verhalten bei fehlenden Verzeichnissen.
> 5. **Nachtrag am selben Tag: die Rasterfahrt als Schritt 0a**, vor der
>    Kalibrierung. Der Positionseffekt ist inzwischen aus den Rohdaten belegt
>    (r = −0,997); steckt eine mechanische Ursache dahinter, werden sonst alle
>    Artikel gegen ein schiefes Feld eingelernt.
>
> Ablauf jetzt: **0a Rasterfahrt** · 0b Hintergrund/Kalibrierung · 1 Sandbox ·
> 2 Artikel anlegen · 3 Einlernen · **4 σ/Floor** · **5 Duplikat-Scan** ·
> 6 Stichprobe · 7 Danach.

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

## Schritt 0 — Rig vorbereiten (OHNE `--sandbox`)

### 0a — PFLICHT am neuen Rig: Rasterfahrt, VOR der Kalibrierung

**Einmalig je Rig, und nach jeder mechanischen Änderung.** Nicht je Session.

Dasselbe Objekt an **5 × 3 Positionen** über das Feld legen, je 2–3 Aufnahmen,
Positionen notieren. Auswertung mit `scripts/positionsdrift_check.py` als
Vorlage (das Skript rechnet heute auf einer Serie aus `data/reference/`).

**Warum das vor allem anderen steht:** Am Mac-Rig wurde am 2026-07-28 gemessen,
dass die **gemessene Länge von der Position im Bild abhängt** — 8,56 mm über
109 mm Weg, r = −0,997
([2026-08-01-positionsdrift-messung.md](2026-08-01-positionsdrift-messung.md)).
Steckt dahinter eine mechanische Ursache (schief stehende Kamera), dann werden
**alle** danach eingelernten Artikel gegen ein schiefes Feld gemessen. Vierzig
Artikel neu einzulernen und den Fehler danach zu finden, ist der teuerste
denkbare Ablauf.

Die halbe Stunde beantwortet drei Fragen auf einmal:

1. **Ist der Gradient mechanisch behebbar?** Linear über das Feld = Kamera
   steht schief (richten). Radialsymmetrisch = Objektivverzeichnung
   (Intrinsic-Kalibrierung). Keins von beidem = weitersuchen. **Eine Linie kann
   das nicht trennen, ein Raster sofort.**
2. **Wie groß ist der Betriebs-Floor wirklich?** Er entscheidet allein über
   w(s), und an derselben Zahl hängen D7 und D8. Heute ist er *geschätzt* und
   sein plausibler Bereich (0,40–1,41 mm) umspannt die Entscheidungsgrenze von
   1,0 mm. Drei offene Scoring-Fragen hängen an einer halben Stunde Messung.
3. **Warum fällt die Breite schneller als die Länge?** `lat_p98` reagiert
   **2,66× stärker** auf Position als `ext_full`, monoton über alle zwölf
   Shots. Eine reine Vergrößerungsänderung würde beide gleich skalieren — sie
   tut es nicht, und niemand weiß warum. Das ist nicht bloß Neugier:
   `lat_p98` erklärt 72 % der Profildistanz von w(s), die Floor-Abschätzung
   stammt aber aus der **Länge**. Ist die Breite dreimal empfindlicher, ist die
   Abschätzung womöglich nach unten verzerrt — in genau die Richtung, die die
   w(s)-Absage stützt.

**Ergebnis vor der Kalibrierung auswerten.** Ist eine mechanische Ursache
erkennbar, erst richten, dann kalibrieren — sonst friert die Kalibrierung den
schiefen Zustand ein.

### 0b — Hintergrund und Kalibrierung

Nur nötig, wenn die Box seit der letzten Kalibrierung bewegt wurde oder die
Beleuchtung sich geändert hat. Nach einer Rasterfahrt mit Korrektur (0a) ist es
**immer** nötig.

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

Die fünf Verzeichnisse legt `init-db` selbst an. Bricht der Befehl mit
`sqlite3.OperationalError: unable to open database file` ab, ist der Stand
älter als der Fix vom 2026-08-01 — dann einmalig
`mkdir -p data/sandbox/neuenroll-2026-08/{reference,captures,verworfen,reports}`
und den Befehl wiederholen.

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
   UND an eine andere Stelle der Box legen.** Beides ist Pflicht, nicht
   Empfehlung — siehe den Kasten unten.
5. Nach jeder Aufnahme erscheint ein Thumbnail mit Ø. **Ausreißer sofort
   erkennen:** ein Thumbnail, dessen Ø deutlich abweicht, per Klick auswählen
   und mit „Aufnehmen" wiederholen.
6. Nach 12 Aufnahmen „Speichern".
7. Es erscheint **erst das Diagnoseblatt**, noch ist nichts in der DB
   (Rendern dauert ~1 s je Aufnahme).

> ### PFLICHT: die Aufnahmen müssen über die Box verteilt sein
>
> Zwölfmal dieselbe Stelle ergibt eine **Wegwerf-Referenz**. Der Grund ist
> gemessen, nicht vermutet: die Fixpunkt-Session vom 2026-08-01 hat alle Shots
> an derselben markierten Stelle aufgenommen, und `sigma_enroll` enthält
> dadurch **keine Positionsstreuung**. Alle Margins dieser Session sind
> optimistisch, die Referenzen durften nicht in den Produktivbestand, und die
> drei offenen Scoring-Fragen (D8, B2, D1/D3) blieben **unentscheidbar** —
> nicht weil die Analyse zu schwach war, sondern weil die Daten die Frage nicht
> beantworten können
> ([2026-08-01-abschluss-scoring-runde.md](2026-08-01-abschluss-scoring-runde.md),
> Abschnitt 5).
>
> Der Positionseffekt ist die grösste bekannte Messfehlerquelle: über die halbe
> Bildhöhe driftet die gemessene Länge um **~8,6 mm** (MESSER-2, 2026-07-28).
> Was das Enrollment nicht sieht, taucht im Betrieb als Fehler auf.
>
> **Also je Shot: anheben, drehen UND versetzen** — über die ganze nutzbare
> Fläche, nicht nur ein paar Millimeter. Nur die Randberührung vermeiden.

**Auf dem Diagnoseblatt prüfen, bevor „Übernehmen":**

- **Feld c (Messwert je Shot):** eine sichtbare Drift über die Shots — Werte,
  die von S1 nach S12 wandern statt zu streuen — heißt, dass sich etwas
  verändert hat (Beleuchtung, Fokus, Objekt verbogen). Dann verwerfen.
- **Konturband:** die 12 Konturen sollen als schmales Band übereinanderliegen.
  Eine Kontur, die ausbricht, ist die, die man wiederholen sollte.
- **Streuungstabelle: die Spalte `Std` gegen den Floor des Merkmals halten**
  (Tabelle unten). Über dem Floor streuen die eigenen Aufnahmen stärker als der
  Mess-Rauschboden des Rigs — das ist kein Rauschen mehr, sondern Uneinigkeit
  der Shots.

**Warum nicht mehr „σ(Ø) 0,4–0,9 mm":** Dieses Kriterium stand bis 2026-08-01
hier und schaut auf das einzige Merkmal, das nie auffällig wird. Über die 13
Artikel der Fixpunkt-Session überschreitet `diameter_mm` den Floor **kein
einziges Mal**; die Überschreitungen sitzen fast vollständig bei `hu_log` (6
von 13 Artikeln) und `delta_e_center` (4 von 13)
([2026-08-01-enrollment-streuung-bedraenger.md](2026-08-01-enrollment-streuung-bedraenger.md),
Abschnitt 4). Wer nur den Ø prüft, prüft nichts.

### Die acht Floor-Werte (aus `config/config.yaml`, `matching.sigma_floors`)

Zum Danebenlegen — sie stehen **nicht** auf dem Diagnoseblatt.

| Zeile im Blatt | Floor | Config-Key |
|---|---|---|
| Ø (circle) | **1,63** mm | `diameter_mm` |
| circularity | **0,0063** | `circularity` |
| solidity | **0,0043** | `solidity` |
| ΔE center | **3,40** | `delta_e` ⟵ geteilt |
| ΔE rim | **3,40** | `delta_e` ⟵ geteilt |
| hist center | **0,146** | `hist_bhattacharyya` ⟵ geteilt |
| hist rim | **0,146** | `hist_bhattacharyya` ⟵ geteilt |
| hu_log | **0,38** | `hu_log` |

Zwei Keys bedienen je zwei Merkmale (Zentrum- und Randzone teilen sich einen
Floor). `aspect_ratio`, `area`, `ext_full` und `lat_p98` stehen zwar in der
Tabelle, sind aber **keine Scoring-Merkmale** — für sie gibt es keinen Floor
und nichts zu entscheiden.

**Genauigkeit der Spalten, damit niemand das Falsche vergleicht:**

- **Ø, circularity, solidity:** die Spalte `Std` **ist** exakt das spätere
  `sigma_enroll` (beide `std(ddof=1)` über die Shots). Direkt gegen den Floor
  halten.
- **ΔE center/rim, hist center/rim, hu_log:** hier ist `Std` die Streuung der
  Leave-one-out-Distanzen, das spätere `sigma_enroll` dagegen der **RMS** der
  Distanzen zum Prototyp (`features._proto_stats`). Nicht dieselbe Zahl.
  Brauchbare Näherung aus dem Blatt: `sqrt(Mittel² + Std²)` der Distanzzeile.
  Sie fällt eher zu gross aus — der Fehler zeigt also in Richtung „nochmal
  hinsehen", und das ist die richtige Richtung.

**Wenn ein Merkmal über dem Floor liegt — nicht sofort verwerfen, erst
unterscheiden** ([enrollment-streuung](2026-08-01-enrollment-streuung-bedraenger.md),
Abschnitt 4b): σ ohne den einen bzw. die zwei äussersten Shots neu ansehen
(Feld e zeigt, welche das sind).

- Fällt σ dann unter den Floor → **Ausreisser-Shot: verwerfen und neu
  einlernen.** „Verwerfen" sichert die Aufnahmen, es geht nichts verloren.
- Bleibt σ darüber → **gleichmässig breit, Wiederholen hilft nicht.** Der
  Artikel reagiert empfindlich auf Rotation. Übernehmen, aber notieren: er wird
  ein *klebriger Bedränger* und drückt die Margin seiner Nachbarn, weil
  `z = d/sigma_eff` die Streuung des jeweiligen Kandidaten benutzt — auch wenn
  er der falsche ist.

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

## Schritt 4 — PFLICHT: σ gegen Floor, endgültig (Qt geschlossen)

Der Blatt-Check in Schritt 3 arbeitet mit einer Näherung, weil vor dem
DB-Schreiben noch keine `reference_stats` existieren. Sobald ein Artikel
übernommen ist, steht der **echte** Wert in der Spalte `Ref-σ`
(`stored_stats.proto_std` bzw. `scalar_std` — genau das `sigma_enroll` des
Matchers). Deshalb nach dem Einlernen einmal je Artikel:

```
docodetect --sandbox neuenroll-2026-08 enrollment-sheet LOEFFEL-1
```

*Kamera:* wird **nicht** geöffnet.

`Ref-σ` gegen die Floor-Tabelle aus Schritt 3 halten. Über dem Floor →
Jackknife-Unterscheidung wie dort. Soll der Artikel neu eingelernt werden,
**erst die Altreferenzen entfernen**:

```
docodetect --sandbox neuenroll-2026-08 delete-references LOEFFEL-1
```

Nicht einfach ein zweites Mal einlernen: `reference_stats` kennt keinen
Session-Begriff, zwei Sessions verschmelzen still zu **einem** σ
([2026-07-31-reference-stats-keine-sessions.md](2026-07-31-reference-stats-keine-sessions.md)).

---

## Schritt 5 — PFLICHT: Duplikat-Scan über den FERTIGEN Bestand

Erst wenn **alle** Artikel eingelernt sind — der Scan vergleicht Artikel
gegeneinander, ein Teil-Bestand kann den Partner nicht sehen.

```
.venv/bin/python scripts/duplikat_scan.py --sandbox neuenroll-2026-08
```

*Kamera:* wird **nicht** geöffnet. Dauer ~15 min bei 40 Artikeln (die
Segmentierung läuft je Referenzbild neu). Das Skript ist **rein lesend** und
ändert nichts.

**Warum das nicht optional ist:** Am 2026-08-01 waren drei von fünfzehn
„Artikeln" dasselbe Messer (MESSER-2 = MESSER-5 = MESSER-6). Es fiel erst auf,
nachdem drei Analysen darauf aufgebaut hatten — eine davon erklärte das Trio
für „im Merkmalsraum erschöpft" und schlug Stufe 2 vor, für einen Gegenstand,
der von sich selbst unterschieden werden sollte. Die Zahlen waren nicht falsch
gerechnet; sie beantworteten eine Frage, die es nicht gab.

**Ausgabe lesen — die Lücke, nicht nur die Schwelle:**

- Alles unter **d/σ < 2,0** → die Gegenstände nebeneinanderlegen und ansehen.
- Zusätzlich die Liste „Kandidaten für die Trennlinie": ein Sprung mit
  **wenigen** Paaren darunter trennt „dasselbe Objekt" von „verschiedene
  Objekte". Liegt so ein Sprung **über** der Schwelle, meldet das Skript die
  Paare dazwischen ausdrücklich — sie gehören mit geprüft. Genau daran ist der
  erste Durchgang gescheitert: mit d/σ ≤ 1,0 wurde nur eines von drei
  Duplikatpaaren gemeldet.
- Steht bei einem Paar eine deutlich **verschiedene Länge**, ist es eher eine
  Formfamilie als ein Duplikat — die Profilnormierung blendet die Länge aus.
- Meldet das Skript **„SCAN NICHT FAHRBAR"**, ist der Bestand *nicht* geprüft.
  Das ist ein Befund, kein leeres Ergebnis. Häufigster Grund: fehlende
  `reference_features.image_path` (im Produktivbestand 334 von 359 Zeilen).

**Erst nach vollständigem Enrollment hat der Scan seine volle Stärke.** Ein
Artikel mit nur einer Aufnahme hat kein eigenes σ; das Skript setzt dort die
über alle Artikel gepoolte Shot-Streuung ein und markiert das Paar mit `*`.
Diese Schätzung ist gröber als das echte σ — zwischen zwei solchen Artikeln
tritt ein Duplikat weniger deutlich hervor. Im Lauf vom 2026-08-01 betraf das
**25 von 40 Artikeln** (die Anlege-Shots) und 9 der 15 engsten Paare. Der
Windows-Durchgang lernt alle Artikel voll ein, dort entfällt die Einschränkung.
Wer den Scan dazwischen auf einem halb eingelernten Bestand fährt, bekommt ein
schwächeres Ergebnis, als die Ausgabe vermuten lässt — die Sternchen in der
Tabelle sind der Hinweis darauf.

Bestätigt sich ein Duplikat: den überzähligen Eintrag **entfernen** und die
Auswertung neu rechnen — **nicht umetikettieren.** Eine Umetikettierung trägt
Top-1-Fehler in jede spätere Auswertung
([2026-08-01-duplikatpruefung-methode.md](2026-08-01-duplikatpruefung-methode.md)).

---

## Schritt 6 — Stichprobe

Qt geöffnet lassen. Ein bereits eingelerntes Teil auflegen, **Leertaste**.

**Achten auf:** ACCEPT mit dem richtigen Artikel. Bei AMBIGUOUS zeigt die
Karte die Kandidaten — bei baugleichem Besteck ist das erwartbar und kein
Fehler. Jede Identifikation schreibt Bild + Report nach
`data/sandbox/neuenroll-2026-08/captures/`, nicht in den Produktivbestand.

Für einen genaueren Blick auf einen einzelnen Artikel, mit geschlossenem
Qt-Fenster:

```
docodetect --sandbox neuenroll-2026-08 enrollment-sheet LOEFFEL-3
docodetect --sandbox neuenroll-2026-08 contour-band LOEFFEL-3
```

*Kamera:* wird bei beiden **nicht** geöffnet — sie rechnen auf den
gespeicherten Bildern.

---

## Schritt 7 — Danach

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
