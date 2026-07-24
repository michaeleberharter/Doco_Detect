# H-S-Drift-Attribution (arm64 ↔ x86-64) — Ergebnisdokument

Stand 2026-07-24 · report-only · Branch `analysis/hs-drift-attribution` ·
Vorgänger: `2026-07-24-windows-eingangspruefung-ergebnis.md` (dort wurde die
Drift gefunden und der Sweep gesperrt).

> **Für eine Sitzung ohne Vorkontext.** Beim ersten Pipeline-Lauf auf Windows
> (x86-64) gegen die Mac-Baseline (arm64) driftet der Null-Replay — bei
> byte-identischem `code_fingerprint`, also Plattform, nicht Code. Dieser
> Auftrag lokalisiert die Drift in der Rechenkette, charakterisiert sie und
> gibt ein Verdikt + eine Sweep-Empfehlung. **Kein Fix** (Umsetzung wäre
> eigener Auftrag); der endgültige K1/K2-Schnitt braucht den Mac-Gegencheck.

---

## 0. Was an einem Satz hängen bleibt

Die Drift ist **unvermeidbares Plattform-Float-Rauschen in cv2-Ops** (K1 mit
K3-Beigeschmack), verortet in der **zonen-abgeleiteten Farbe** (H-S-Histogramm,
Lab-Zonenmittel, S-Mittel) — Geometrie und Voll-Masken-H sind byte-identisch;
sie ist auf Windows in sich **deterministisch** (5 Läufe bit-gleich), liegt
**~2 Größenordnungen unter der knappsten kippenden Entscheidung** (69× am
engsten Gate, 0 kategoriale Änderungen) und ist damit **sweep-unkritisch**.
Empfehlung: eine reine Plattform-Toleranz im Harness (Vorschlag, nicht
umgesetzt), Baseline bleibt Mac.

## 1. Messboden identisch — die Drift ist Plattform

`code_fingerprint`/`config_fingerprint` Windows == Mac (`5f4e90b6…`/`df1a1190…`,
vor dem SQLite-Fix), Zeilenenden LF wie Mac. Die Segmentmaske ist plattform-
identisch (`seg_area_px`, `centroid_x/y` = 0 Drift über alle 173). Beleg-Basis:
`scripts/hs_drift_export.py` repliziert die `extract()`-cv2-Aufrufe und ist je
Bild **byte-gleich zum Messpfad geprüft — 165/165 valid** (Selbstvalidierung
vor jeder Auswertung; sonst wären die Zwischenwerte wertlos).

## 2. Die Rechenkette + was ausgeschlossen ist

Pixel → HSV (`cvtColor`) → Distanztransform (`distanceTransform` DIST_L2/5,
float32) → normierter Radius `r=1−dist/dmax` → Zonen-Maske (Schwelle) →
2D-Histogramm (`calcHist [16,8]`) → Normierung (`/total`) → `round(·,6)` →
Bhattacharyya (Matcher). **Ausgeschlossen** durch je 0 Drift über 165 Bilder:

| Byte-identisch Mac↔Win | Schluss |
|---|---|
| `seg_area_px`, `centroid` | Segmentierung (scipy-Min-Cut) exakt |
| **`hue_hist` (Voll-Masken-H)** | **`cvtColor`-H-Kanal + `calcHist`-Zählung stabil** |

Die Drift sitzt ausschließlich in **zonen-abgeleiteter Farbe**: `hs_hist_rim`
(165/165), `hs_hist_center` (99/165), `lab_center` (9), `lab_rim` (2) — plus
das **Voll-Masken-S-Mittel** `mean_saturation` (6). Verbleibende Quellen:
`distanceTransform` (Zonengrenze) und/oder S-Kanal-Float-Verhalten.

## 3. Zwei widerlegte Vorab-Erwartungen (ausdrücklich)

**(a) „Δ ∝ 1/N" (Zonen-Randkippen) — WIDERLEGT.** Der max-Bin-Delta korreliert
mit **nichts** stark: vs 1/N ≈ 0 (−0,06/+0,11), vs Peak-Bin-Höhe +0,15, vs
#nichtleere-Bins +0,39 (alle |r|<0,4). Kein sauberes Gesetz → **verteiltes
Float-Rauschen**, kein struktureller Mechanismus. (Die robuste Aggregatgröße
ist die Bhattacharyya-Distanz, §7.)

**(b) „GABEL fällt wegen kleiner/dünner Zonen" — WIDERLEGT.** GABEL-4/-1 haben
**Median-Zonen** (obj_px pct 44/50, center_px pct 34/47); die kleinsten Zonen
gehören LOEFFEL-10. Der FAIL ist ein Grenzgang auf der strengen
max-Einzel-Bin-SOFT-Schwelle (1e-3): GABEL-1 1,56e-3, GABEL-4 1,00e-3 — beide
direkt an der Linie, 2 von 165.

**Eigenständiger Befund — Hue-Instabilität bei poliertem Stahl.** Das Bild von
GABEL-1 zeigt spiegelpolierten Stahl: **achromatisch → Hue numerisch instabil**
(1 LSB RGB kippt H). Die Masse liegt in der Niedrig-S-Zeile, über viele
H-Spalten verschmiert (GABEL-1: 75 nichtleere Bins). Deshalb sind gerade
Besteck-Bilder auf dem H-abhängigen Merkmal am empfindlichsten. **Notiz für die
spätere Merkmals-Diskussion (unabhängig von der Plattformfrage):** H-basierte
Farbmerkmale sind bei poliertem Besteck generell schwach — ein Argument für
**Breite als Merkmal** und für das **Stage-2-Timing** (DINOv2 dort, wo Stufe 1
farbschwach ist). Kandidat, hier nur dokumentiert.

## 4. (c) Determinismus — Windows in sich exakt

**5 unabhängige, cache-gelöschte Voll-Tier-1-Läufe: byte-identisch (165/165
Fehler-JSONs)** — die 3 neuen (det-1/2/3, jetzt in `runs/_invalid/`) plus die 2
bereits bit-gleichen Pre-/Post-Fix-Läufe (`win-block4-tier1`,
`win-postfix-tier1`, verschiedene `code_fingerprint` → beide von Grund auf neu
gerechnet). Kein Intra-Maschinen-Rauschen → die Drift ist eine **deterministische
Mac↔Windows-Differenz**, kein Thread-Reihenfolge-Artefakt. Die vorregistrierte
`cv2.setNumThreads(1)`-Kontingenz war nicht nötig.

## 5. (d) Vorzeichen + Schärfungen

- **Vorzeichen überwiegend symmetrisch:** am argmax +35/−64 (center), +68/−97
  (rim), Mittel signed ~−1e-5 — schwacher negativer Hang, **kein systematischer
  additiver Bias** → konsistent mit Rundung, nicht mit einem Kanten-Offset.
- **K2 klein (Schärfung 1):** `mean_S` driftet auf **6** Bildern (alle
  überlappen hs-Drift), max **0,006**. Da H byte-gleich ist, ist das entweder
  S-Wert-Differenz **oder** `cv2.mean`-Akkumulationsreihenfolge — der
  `hsv_masked_sha`-Mac-Vergleich entscheidet. **Verdikt: K1-dominant + K2-klein.**
- **dmax-Verstärker (Schärfung 2):** `dmax` als exakte Float-Bits (hex) +
  `dist_sha` exportiert. „dmax gleich / dist-sha verschieden" (lokales
  Randkippen) vs „dmax verschieden" (globale Iso-Verschiebung, da
  `r=1−dist/dmax`) sind zwei verschiedene K1-Geschichten — Mac-seitig zu trennen.

## 6. (e) Robustheit — die Sweep-Zahl (beide Ebenen)

- **(i) Feature-Ebene:** Bhattacharyya(Windows, Golden) desselben Bildes
  **≤ 6,4e-3**; **0** Bilder über dem `hist_bhattacharyya`-`sigma_floor`
  **0,05** → **Faktor 8×**.
- **(ii) Entscheidungs-Ebene:** knappster Accept **0,649** unter dem z-Gate
  (max Accept-max|z| 2,851 < 3,5), **0,104** über dem Margin-Gate
  (min Accept-llr 2,104 > 2,0); knappster Reject 0,754 über dem z-Gate. Gegen die
  beobachtete Tier-2-Drift (max_z **6,8e-3**, llr **1,5e-3**):
  - **z-Gate: 0,649 / 6,8e-3 ≈ 95×**
  - **Margin-Gate: 0,104 / 1,5e-3 ≈ 69×**
  - empirisch: **0 kategoriale Änderungen**, false_accept **0/44**, der
    GABEL-1-Rückenlage-Wächter bleibt REJECT.

## 7. Verdikt — Klasse K1 (mit K3-Beigeschmack), nicht K2

- **K1 (unvermeidbare Float-Differenz):** verteiltes, richtungsloses,
  sub-schwelliges Rauschen; Windows in sich deterministisch. Die natürliche
  Signatur von float32-Arithmetik über verschiedene ISA (FMA/SIMD).
- **K3-Beigeschmack:** der Ort ist die **cv2-Bibliothek** (approximativer
  `distanceTransform` DIST_L2/5, `cvtColor`-S, `cv2.mean`), nicht eigener Code.
- **Warum nicht K2:** `features.py` selbst akkumuliert **nichts**
  reihenfolge-abhängig (nur `hist/total`-Division und `round`). Es gibt in
  unserem Code nichts umzusortieren; eine deterministische Reihenfolge ließe
  sich nur INNERHALB von cv2 erzwingen. cv2 ist bereits versionsgepinnt
  (5.0.0.93) — ein anderer Build oder eine Neuimplementierung der Ops wäre für
  einen 1e-4-Effekt bei 69× Reserve unverhältnismäßig.

## 8. Toleranz-Vorschlag (NUR VORSCHLAG — Umsetzung eigener Auftrag)

Bewusst **nicht in diesem Auftrag** und bewusst **erst nach dem Mac-Gegencheck**:
eine Toleranz vor dem endgültigen K1/K2-Schnitt könnte genau den Effekt
zudecken, den der Gegencheck noch belegen soll.

- **Schwelle:** eine „Plattform-Band"-Toleranz auf den Farb-/Histogramm-Feldern
  von **1e-2** (Bhattacharyya-äquivalent), **abgeleitet aus der Reserve, nicht
  aus der beobachteten Drift**: = `sigma_floor` 0,05 / 5. Damit bleibt (i) eine
  echte Regression in `sigma_floor`-Größenordnung (≥ 0,05) weiterhin FAIL, (ii)
  die Entscheidungsreserve über ~**40×** (1e-2 → ~2,3e-3 llr-Drift vs 0,104
  Margin), (iii) heutige Plattform-Drift (6,4e-3) klar darunter. Bewusst NICHT
  auf 6,4e-3 geeicht — sonst wäre die Toleranz auf den heutigen Zufall kalibriert.
- **Wirkungsbereich:** gilt **nur auf Nicht-Baseline-Maschinen** und **nur** für
  die benannten Farbmerkmale (`hist_center/rim`, `delta_e_*`, `lab_*`,
  `mean_hsv`/`mean_saturation`). **Geometrie bleibt exakt** (Quantum unverändert).
- **Sichtbarkeit:** sub-schwellige Drift wird als **PASS gewertet, aber weiter
  gezählt und im Report ausgewiesen** (eigenes „Plattform-Band"). Eine Toleranz,
  die Drift unsichtbar macht, ist eine abgeschaltete Sicherung.
- **Gegenargument / ab wann falsch:** Die Toleranz ist gerechtfertigt, **solange
  die Entscheidungsreserve ≥ ~10×** bleibt. Sie wird falsch, wenn eine künftige
  Änderung (neue Plattform, neue cv2-Version, Merkmals-/Zonen-Änderung) die
  beobachtete Drift so anhebt, dass 69× unter ~10× fällt — dann ist die richtige
  Antwort **neu messen**, nicht die Toleranz aufweiten. Deshalb: Plattform-Band
  je Maschine/cv2 neu gegen die Reserve prüfen, nicht einmal fest verdrahten.

## 9. Offene Mac-Seite — was der Gegencheck entscheidet

Alles im Archiv (`reports/archive/hs-drift-attribution-2026-07-24/`): der Mac
lässt `scripts/hs_drift_export.py` **identisch** laufen und stellt gegen
`windows_export.json`:

| Vergleich | Ergebnis → Klasse |
|---|---|
| **`hsv_masked_sha`** (HSV im Objekt) | gleich → HSV-Werte identisch, **alle** hs-Drift ist Zone (K1); verschieden → S-Wert-Anteil (K2) |
| **`center_px`/`rim_px`, `center/rim_mask_sha`** | verschieden → Zonengrenze verschoben (K1 bestätigt) |
| **`dmax_hex`** | gleich + `dist_sha` verschieden → lokales Randkippen; verschieden → globale Iso-Verschiebung |
| **Voll-`[16,8]`-Zählmatrix (`fullhs_sha`)** | gleich → S-Binning stabil (stützt reine Zone); verschieden → S-Wert-Anteil |
| **Kreuz-Zonen** (`windows_zone_masks.npz`: 2 FAILs + 3 Kontrollen) | Mac-Merkmale mit **importierten Windows-Zonen** == Windows-Ergebnis → **Differenz war die Zone (K1)**; bleibt verschieden → Wertdifferenz (K2/K4) |

Die Masken **müssen von Windows stammen** (im npz) — Neuerzeugung auf dem Mac
hätte genau die Eigenschaft (mac-eigene Zonen), die geprüft wird. Der Mac-Teil
gehört in den Opener der nächsten Mac-Session (neben SQLite-Gegencheck).

## 10. Beifang — Je-Session-Varianz (Residual-Analyse §6b)

`residual ~ measured` je Session, aus
`reports/archive/residual-groessenmerkmal-2026-07-24/residuals.csv`:

| Session | n | Steigung | Achsenabschnitt | Mittel-Residual |
|---|---|---|---|---|
| phase-a | 60 | −1,05 % | +0,43 | −1,42 |
| phase-b | 60 | −1,18 % | −0,33 | −2,39 |
| phase-c2 (Kontrolle) | 44 | +1,34 % (R² 0,02, flach) | −2,83 | −0,09 |

**Steigungen nicht trennbar** (−1,05 % vs −1,18 %, bei R²≈0,08/n=60), aber die
**Offsets trennen** (Mittel-Residual ~1 mm auseinander, Achsenabschnitte kippen
das Vorzeichen), und die Kontrolle phase-c2 hat umgekehrtes Vorzeichen → **reale
Je-Session-Varianz, kein Einzelereignis** an der 20./21.-Grenze. Konsequenzen:

1. **Skalen-Gate am Session-Start ist Voraussetzung, nicht Option.**
2. **Skalenfaktor je Session versionieren** — konkretisiert die Ära-Kennzahl aus
   Block 4 (statt nur `created_unix`).
3. **NEU: Enrollment-Referenzen tragen den Offset ihrer eigenen Session.**
   Empfehlung: Enrollments **nur innerhalb einer verifizierten Ära mischen**; bei
   Ära-Wechsel Referenzen als **ära-behaftet kennzeichnen**. Kandidat,
   **nicht umzusetzen** — hat Konsequenzen für die Stammdaten-Ebene.

Siehe Residual-Dokument (`2026-07-24-stammdaten-sync-ergebnis.md`, §6b) für den
Kalibrier-Reproduzierbarkeits-Mechanismus (Zweig K).

## 11. Sweep-Freigabe

**Bestätigt** (nach Abnahme dieses Dokuments): Die Drift ist unvermeidbar,
sub-schwellig, deterministisch und **69× unter dem engsten Entscheidungs-Gate**.
Betriebskurven auf Windows sind rechenbar. Baseline bleibt Mac; die Drift wird
**dokumentiert, nicht akzeptiert** (kein `--accept-drift`, kein
`--update-baseline`) bis das Plattform-Band (eigener Auftrag, nach Mac-Gegencheck)
steht.

## 12. Artefakte

- `scripts/hs_drift_export.py` (Harness, self-validating), `scripts/hs_drift_masks.py`.
- `reports/archive/hs-drift-attribution-2026-07-24/windows_export.json` (165
  Bilder, Zwischenwerte + Golden-Vergleich), `windows_zone_masks.npz` (Windows-Zonen
  der 5 Kontroll-Bilder). Archiv gesamt ~0,6 MB.
- Determinismus-Läufe: `runs/_invalid/det-1..3`; Referenz `runs/win-block4-tier1`,
  `runs/win-postfix-tier1`.
