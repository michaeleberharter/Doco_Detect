# stammdaten-Diagonal-Fix + sync-stammdaten --apply — Ergebnisdokument

Stand 2026-07-24 · Branch `fix/stammdaten-diagonal` von `main` (b931435) ·
Auftrag: `docs/arbeitsplan-2026-07-24.md`, Block 1.2.

> **Für eine Sitzung ohne Vorkontext.** Vorgänger: der Vorfilter-Fix vom
> 2026-07-21 (`2026-07-21-vorfilter-laengliche-artikel-ergebnis.md`, Option A:
> `hypot`→`max` im Matcher) und die phase-c-Bilanz vom 2026-07-23
> (`2026-07-23-phase-c-ergebnis.md`, Abschnitt 6: der sync-stammdaten-Defekt
> als **dritte** Fundstelle derselben Diagonal-vs-Länge-Fehlerklasse). Dieses
> Dokument schließt genau diese offene Stelle.

---

## 0. Was an einem Satz hängen bleibt

Die dritte und letzte Fundstelle der Diagonal-vs-Länge-Fehlerklasse ist
gefixt, `sync-stammdaten --apply` ist gelaufen, und der eigentliche Ziel-Kill
(LOEFFEL-4, 190,42 mm) löst sich. Der Preis ist **eine bewusst akzeptierte,
fail-safe Regression** an einem breitschaufeligen Servierlöffel — und die
Residual-Analyse erklärt sie: der Sync macht die Nominale *wahrer*, aber
phase-b hat einen ~2,4 mm Session-Offset, den die 6-mm-Festtoleranz nicht
mehr abfängt. **Fehlbuchungsrate bleibt 0.**

## 1. Fundstellen (Schritt 1, Analyse vor jeder Änderung)

Repo-weite Suche nach `hypot` / `sqrt(w²+d²)` auf `width_mm`/`depth_mm`. Genau
**eine** verbliebene Fundstelle der Fehlerklasse — keine vierte:

| Datei | Was | Fließt wohin |
|---|---|---|
| `docodetect/stammdaten.py:73` | `alt = math.hypot(w, d)` als Bezug für den Skalierungsfaktor `f = mean/alt` | `apply_sync()` → `articles.width_mm/depth_mm` (**schreibt**) |
| `stammdaten.py` Docstring + CLI-Ausgabetext | „…gegen `hypot(width, depth)`" | Doku, seit 2026-07-21 sachlich falsch — mitgezogen |

Ausgeschlossen (geprüft): `matcher._nominal_size_mm` (bereits `max`, verbleibende
`hypot`-Nennung ist Docstring-Historie); der Flächen-Vorfilter (`if art.diameter_mm`,
für längliche Artikel inaktiv); `segmentation.py`/`corpus/triage.py` (Pixel-Geometrie);
`analysis.py`/`corpus/report.py` (Wilson-`sqrt`, Statistik); UI (zeigt `w × d` nur an).

## 2. Fix (Schritt 2)

`docodetect/stammdaten.py`: `hypot(w,d)` → `max(w,d)` — dieselbe Größe wie
`matcher._nominal_size_mm` (Option A, Stadion-Form). Docstring + CLI-Text auf
`max`/„Länge, nicht Diagonale" umgestellt, inkl. Tablett-Caveat (scharfkantig
rechteckige Artikel hätten den Umkreis an der Diagonale — hier bewusst nicht
gelöst). `import math` entfernt (ungenutzt).

**Unit-Tests** (`tests/test_stammdaten.py`): der Löffel-Bestandstest pinnt jetzt
`max()` statt `hypot()`; neu `test_laenglicher_artikel_wird_gegen_laenge_
synchronisiert_nicht_diagonale` mit den echten LOEFFEL-4-Werten (w=183,21,
d=37,18, mean=186,49) und der vollen Zahlenkette 190,42 / 183,21 / 186,49 →
7,21 / 3,93; Gegenprobe, dass `nominal_alt` **nicht** die Diagonale (186,94)
ist; der runde Zweig ist mit Kommentar als „unberührt vom hypot/max-Code"
gepinnt. Gezielter Lauf `test_stammdaten.py` + `test_matching_decisions.py`:
**25 passed**.

## 3. Erwartung vs. Ist (Schritt 3, Dry-Run nach Fix)

`sync-stammdaten` ohne `--apply` gegen die echte Produktions-DB, programmatisch
gegen eine unabhängige `max`-Parallelrechnung geprüft: **0 Abweichungen bei 40
Artikeln.** Nur längliche Artikel betroffen (0 Zeilen über den `diameter_mm`-Zweig;
`CD-REFERENZ` rund/1 Shot bleibt übersprungen). Aggregat wie in phase-c-Abschnitt 6:

| Klasse | n | Diff `hypot` (alt) | Diff `max` (Fix) |
|---|---|---|---|
| MESSER | 11 | — | Mittel −0,50 (−1,84…+0,33) |
| GABEL | 14 | — | Mittel +0,69 (−2,58…+1,90) |
| LOEFFEL | 15 | — | Mittel +2,79 (+0,68…+6,02) |
| **gesamt** | **40** | **−0,86 (−4,13…+3,17)** | **+1,15 (−2,58…+6,02)** |

## 3.5 Bündel-Äquivalenz (vor jedem Apply)

Inhalts-Diff (articles + reference_stats) der Bündel-DBs gegen die Produktions-DB:
**phase-b** (16 Art., prä-Gabel/Messer) und **phase-c2** (41 Art.) je **0
Abweichungen** auf überlappenden Artikeln. phase-c1 existiert im Korpus nicht
(nur `backups/`), phase-a hat `has_db:false`. → Refresh isoliert den Sync-Diff sauber.

## 3.6 Null-Replay (Code-Fix allein ist replay-neutral)

Gefixter Code, unveränderte Bündel, kein Apply: `corpus-run --tier 2 --check`
= **104/104 PASS, 0 DRIFT**, Quoten byte-identisch zur alten Baseline, sogar
`code_fingerprint` identisch (`stammdaten.py` ist nicht Teil des gehashten
Messpfads). Jeder spätere Drift ist damit eindeutig der DB-Änderung zuzuordnen.

## 4. Der Weg über den Drift-Zyklus (Schritt 4)

Weil `corpus-build` phase-b nicht mehr auffrischt (bewusst aus `SOURCES`
genommen) und die Report-Quellordner im Worktree fehlen, lief der Bündel-Refresh
als **chirurgischer DB-Tausch mit `copy_db_readonly`** — demselben Helfer, den
`build.py:234` intern nutzt; der Tausch ist mechanisch identisch mit dem
Build-Pfad. „Bündel-Refresh" := (1) Backup-Move der alten Bündel-DB, (2)
verifizierte inhaltsgleiche Kopie via `copy_db_readonly`, (3) Provenienz in
`session.json`. Das versionierte `corpus/manifest.json` hasht die Bündel-DBs
**nicht** → Provenienz genügt, kein Manifest-Update.

**Zweistufig, um Ära von Sync zu trennen:**

- **4a** Produktions-DB → `backups/doco_detect_2026-07-24_pre-sync.sqlite3`
  (byte-identisch).
- **4b** phase-b 16→41 migriert (Original-16er → `backups/bundles/
  2026-07-24_phase-b_original-16er/`), 41er-**Alt-Nominal**-Stand eingespielt.
  Ära-Replay `20260724-4b-aera-16auf41`.
- **4c** `sync-stammdaten --apply` — Schema-Hash **unverändert**, Werte = Dry-Run,
  LOEFFEL-4 183,21→186,49.
- **4d** beide Bündel-DBs → `backups/bundles/2026-07-24_pre-sync-refresh/`,
  Post-Sync-DB eingespielt, je verifiziert (0 Diffs, `db_match_ratio` 1.0).
  Sync-Replay `20260724-4d-post-sync`.

### Zwei-Schichten-Attribution

**Schicht Ära (4b vs. Baseline, nur phase-b):** 35 Bilder bewegt, **ausnahmslos
`cand_added`** (Gabeln/Messer treten in den Längen-Vorfilter ein) + Margin-Drift.
**Keine** Decision-, Top-1- oder `cand_removed`-Änderung. phase-c2: 0/44. Quoten
identisch zur Baseline. Alle 4b-STOPP-Bedingungen grün. Die Klassentrennung
leistet vollständig das Scoring — 0 Klassenverwechslungen trotz gewachsenem Set.

**Schicht Sync (4d vs. 4b):** vier korrektheitsrelevante Bilder:

| Bild | Session | Artikel | measured Ø | Nominal alt→neu (Fehler) | Effekt |
|---|---|---|---|---|---|
| **51695897** | phase-c2 | LOEFFEL-4 | 190,42 | 183,21 (7,21✗)→186,49 (**3,93✓**) | **Top-1 LOEFFEL-1→LOEFFEL-4** — der Ziel-Kill löst sich (Decision bleibt ambiguous, Zwillings-Margin) |
| **8dc74a45** | phase-b | LOEFFEL-7 | 267,92 | 268,58 (0,66✓)→274,60 (**6,68✗**) | **Accept→Reject** (akzeptierte fail-safe-Regression) |
| 4587d1a8 | phase-b | LOEFFEL-3 | 188,83 | 193,09 (4,26✓)→196,55 (7,72✗) | wahres Label verlässt Top-3; Top-1 (schon vorher falsch) unverändert |
| cc1f627e | phase-b | LOEFFEL-6 | 190,13 | 193,65 (3,52✓)→197,67 (7,54✗) | wahres Label verlässt candset (war nicht in Top-3) → keine Metrik-Änderung |

Alle anderen phase-b-Bilder: benigner Zwillings-Reshuffle ohne Decision/Top-1-
Effekt. Belege (Bild + Report-JSON) je Fall: `docs/assets/2026-07-24-stammdaten-sync/`.

### Neue Baseline

| Kennzahl | Baseline alt | **neu** | Δ |
|---|---|---|---|
| accuracy_top1 | 95/104 | **95/104** | 0 (L4 +1 hebt L7 −1 auf) |
| accuracy_top3 | 102/104 | **101/104** | −1 |
| auto_accept_rate | 45/104 | **44/104** | −1 |
| false_accept_rate | 0/45 | **0/44** | 0 (Nenner 45→44, weil ein Accept zu Reject wurde) |
| accuracy_top1_verdict | 83/104 | 83/104 | 0 |
| reject | 3 | **4** | +1 |

**Harte Checks alle erfüllt:** false_accept **0/44** · top1 **95/104 ≥ 95** ·
GABEL-1-Rückenlage-Wächter (152de077, 5bf6b431) beide **REJECT**.

`corpus/baseline.json`: `run_id` `20260724-baseline-post-sync`, `config_fingerprint`
**unverändert** (keine Schwellen-/Config-Änderung; `diameter_tolerance_mm` bleibt
6,0), `code_fingerprint` neu (accepted_deltas sind Teil des Fingerprints).
`corpus-run --tier 2 --check` gegen die neue Baseline: **OK (104/104)**.
Provenienz: Bündel = post-sync 2026-07-24; **die alte Baseline (95/102/45/0/83)
bleibt reproduzierbar** über die Backups:
`backups/bundles/2026-07-24_pre-sync-refresh/phase-{b,c2}_db_*.sqlite3` (Bündel-Stand)
und `backups/doco_detect_2026-07-24_pre-sync.sqlite3` (Produktions-DB).

### Accepted-Deltas (nach Schicht getrennt)

- `corpus/accepted_deltas/2026-07-24-stammdaten-sync.json` — die 4 oben, einzeln;
  8dc74a45 explizit als „bekannte, akzeptierte Regression (fail-safe)".
- `corpus/accepted_deltas/2026-07-24-stammdaten-aera-16auf41.json` — 59 Bilder
  (Ära-Cross-Class-Eintritte + benigner post-sync Reshuffle), Sammel-Begründung.
- Zusammen decken sie exakt die 63 fail-Band-Bilder; `--check` grün verifiziert.

## 5. Fallstudie LOEFFEL-7: der Sync macht die Nominale wahrer, die Metrik lokal schlechter

8dc74a45 (phase-b, LOEFFEL-7, breitschaufeliger Servierlöffel — Bild in
`docs/assets/…`) war vor dem Sync ein korrekter Auto-Accept (measured 267,92 vs.
Nominal 268,58, Fehler 0,66). Der Sync zieht das Nominal korrekt auf das
Enrollment-Mittel des Umkreis-Ø (274,60 — die breite Laffe hebt den Umkreis über
die Länge, exakt der in phase-c-Abschnitt 6 vorhergesagte Effekt). Genau dieser
Golden-Shot liegt aber 6,68 mm darunter → knapp außerhalb 6,0 mm → LOEFFEL-7 aus
dem eigenen Set gekillt → **Reject statt Accept**. Kein Fehlbuchungsrisiko (Reject
ist der sichere Ausgang); Kosten −1 top3, −1 auto_accept. **Die neue Baseline
bildet ab jetzt die Wahrheit ab** — der alte Wert war nicht „zufällig nahe",
sondern **Ära-kohärent**: das alte Ein-Shot-Nominal aus `create-article` stammte
aus derselben Mess-Ära wie der phase-b-Golden und trug denselben Ära-Skalen-Offset
(Abschnitt 6b), passte darum lokal. Der Sync hat den Ära-Wechsel **sichtbar
gemacht**, nicht Pech erzeugt.

## 6. Residual-Analyse (report-only, keine Eingriffe)

Pro Bild: `residual = measured.circle_diameter_mm − nominal_neu(wahrer Artikel)`,
`nominal_neu = max(w,d)` aus der Post-Sync-DB. Alle Cutlery height=0 → keine
Höhenkorrektur. Drei Sessions als Zeitachse. Artefakte:
`reports/archive/residual-groessenmerkmal-2026-07-24/` (CSV + Verteilungsplot).

| Session | n | Mittel | Std | Min…Max | \|res\|>6 mm |
|---|---|---|---|---|---|
| phase-a | 60 | −1,41 | 1,60 | −6,53…+1,34 | 1/60 |
| **phase-b** | 60 | **−2,39** | 1,82 | −7,72…+0,24 | 3/60 |
| **phase-c2** (Kontrolle) | 44 | **−0,09** | 1,85 | −5,52…+3,93 | 0/44 |

**Befund: Session-Offset, kein zufälliges Zentrum bei 0.**

1. **phase-c2 zentriert bei −0,09 mm** — die Kontrolle. phase-c2 wurde in derselben
   Ära wie das Enrollment gemessen; der gemessene Umkreis-Ø entspricht im Mittel
   exakt dem Enrollment-Mittel (= `nominal_neu`). **Das beweist, dass der Sync-Wert
   korrekt ist.**
2. **phase-b zentriert bei −2,39 mm** (phase-a bei −1,41). Diese Sessions (Messung
   2026-07-20) liegen systematisch ~2,4 mm unter dem post-sync Nominal — ein echter
   Geometrie-Offset zwischen Mess- und Enrollment-Ära. Die drei phase-b-Kills
   (LOEFFEL-7/3/6) sind die Extrem-Ausreißer dieses Offsets (−6,68 / −7,72 / −7,54),
   verschärft bei den breitschaufeligen Löffeln (größte |Mittel| **und** größte Std:
   LOEFFEL-7/12/3/6 bei −3,4…−4,1 mm, Std 1,4…3,2).

Der Sync ist also nicht schuld: er hebt das Nominal korrekt aufs Enrollment-Mittel.
Die Regression entsteht aus dem **Zusammenspiel von korrektem Sync + realem
Ära-Skalen-Offset + fester 6-mm-Toleranz** bei den Artikeln mit der größten
Shot-zu-Shot-Streuung. Der Mechanismus des Offsets — Kalibrierung oder Physik —
ist in Abschnitt 6b aufgeschlüsselt: **es ist die Kalibrier-Reproduzierbarkeit
(Zweig K)**, nicht ein additiver Segmentierungs-Bias.

## 6b. Mechanismus des Offsets: Kalibrierung vs. Physik (report-only)

Frage: ist der Ära-Offset ein **Skalen**-Effekt (multiplikativ, `residual ∝
Größe`, Achsenabschnitt ≈ 0) oder ein **additiver** Kanten-/Segmentierungs-Bias
(`slope ≈ 0`, konstanter mm-Offset)? Drei Auswertungen, alle nur aus vorhandenen
Snapshots/CSV:

**Tabelle 1 — Kalibrier-Kenndaten je Ära.** Die gebündelten `calibration.json`
(phase-a/b/c2) **und** die aktuelle sind **byte-identisch**: `mm_per_px`
0,07876574, `marker_size_mm` 72,5, `camera_height_mm` 300,0, **derselbe**
`created_unix` (1784555426). Die aus den Reports rückgerechneten effektiven
Skalen unterscheiden sich um **< 0,03 %** (phase-b −0,026 % vs. phase-c2). Die
*gespeicherte* Skala ist über alle Ären konstant — sie stammt aus **einem
einzigen** Marker-Kalibrierereignis und wurde nie je Session nachgemessen.

**Tabelle 2 — phase-c2-Residuen nach Enrollment-Ära der Klasse.** LOEFFEL
(enrolled 21./22.) Mittel **+0,27** (Std 2,53, n=9); GABEL/MESSER (enrolled 23.)
Mittel **−0,18** (Std 1,66, n=35). **Beide ≈ 0** → das Enrollment-Fenster
21.→23. ist stabil, kein diskreter Sprung innerhalb der Enrollment-Ära.

**Check 3 — Regression `residual ~ Größe` innerhalb phase-b (bzw. a):**

| Session | Fit | R² | Deutung |
|---|---|---|---|
| phase-b | `residual = −0,03 + (−0,01337)·Größe` | 0,10 | **Steigung ≈ −1,34 %, Achsenabschnitt ≈ 0** |
| phase-a | `residual = +0,65 + (−0,01170)·Größe` | 0,10 | Steigung ≈ −1,17 %, Achsenabschnitt ≈ 0 |
| phase-c2 | `residual = −1,00 + (+0,00448)·Größe` | 0,00 | Steigung ≈ 0 (Kontrolle, flach) |

Die Steigung −1,34 % / −1,17 % deckt sich mit dem mittleren Offset (−2,39 mm auf
~190 mm = −1,26 %) bei **Achsenabschnitt ≈ 0** — die Signatur eines
**multiplikativen Skalen**-Effekts. Ein rein additiver Kanten-Bias hätte
Steigung ≈ 0 und Achsenabschnitt ≈ −2,4 gegeben; das ist **nicht** der Fall.
(Das niedrige R² ≈ 0,10 heißt nur, dass die Shot-zu-Shot-Streuung ~1,8 mm den
systematischen ~1,3 %-Anteil pro Einzelmessung überlagert — der Trend selbst ist
die Skala.)

**Auflösung — Zweig K (Kalibrier-Reproduzierbarkeit), nicht Zweig P.** Der
scheinbare Widerspruch (gespeicherte Skala identisch, effektive Skala −1,3 %)
löst sich so: die Kalibrierung ist aus **einem** Marker-Shot eingefroren
(`created_unix` über alle Ären gleich) und kann eine **reale** physische
Skalen-Drift von ~1,3 % zwischen der 07-20-Aufnahme-Ära und der 07-21+-Enrollment-
Ära nicht nachführen. Die Drift ist echt (Rig/Optik/Fokus über die Tage), aber
**unsichtbar für die Pipeline**, weil die Skala nicht je Session neu gemessen
wird. phase-a ≠ phase-b (−1,41 vs. −2,39) zeigt zudem **Je-Session-Varianz** —
es ist kein einzelnes sauberes Ereignis (a==b), sondern eine über die Sessions
schwankende Skala.

**Konsequenz (Roadmap unten präzisiert): Re-Enrollment oder Toleranz-Aufweitung
wären die falsche Medizin** — sie behandelten das Symptom einer nicht
reproduzierten Kalibrierung. Die Baustelle ist die **Kalibrier-Reproduzierbarkeit**.

## 7. Roadmap (Kandidaten, NICHT in diesem Auftrag umgesetzt)

1. **Kalibrier-Reproduzierbarkeit (die eigentliche Ursache, Zweig K).** Der
   Ära-Offset ist eine nicht nachgeführte ~1,3 %-Skalen-Drift (Abschnitt 6b), kein
   additiver Bias und kein Sync-Fehler. Baustelle: **Marker-Nachmess-Protokoll**
   (Marker mit Messschieber je Session verifizieren — Bestand ohnehin offen:
   marker_size_mm 72,5 vs. früher 136,0 in config), **Doppel-Kalibrierung als
   Gegenprobe** (zwei Marker-Shots pro Session, Skalen-Spread als Qualitätsmaß),
   und die **Ära-Kennzahl (Block 4) konkret = Skalenfaktor je Session
   versionieren** statt nur `created_unix`. **Re-Enrollment und Toleranz-Aufweitung
   sind hier die falsche Medizin.**
2. **Vorfilter-Toleranz pro Artikel** (Symptom-Behandlung, nachrangig zu 1): Floor
   6 mm, Erweiterung ~`k·sigma_enroll` des Größenmerkmals. KANDIDAT, bedingt auf den
   Streuungs-Befund; Entscheidung **nur datengetrieben via Block-2-Sweep**. Keine
   Schwellen-/Config-Änderung ohne Sweep — `diameter_tolerance_mm` bleibt 6,0. Ohne
   die Kalibrier-Baustelle (1) würde eine weitere Toleranz nur die Drift kaschieren.
3. **Wiederholbarkeits-Test + CD-Positions-Block priorisieren** — misst die
   Je-Session-Skalen-Varianz (phase-a ≠ phase-b in 6b) direkt und macht 1 prüfbar.
4. **Block 4:** (a) fehlender Wächter — `has_db:true` bei fehlender Bündel-Datei
   muss laut scheitern; das phase-b-Bündel ist ab jetzt „nur manuell gepflegt"
   (in `session.json` vermerkt, da nicht in `build.SOURCES`). (b) `BUNDLE_QUELLEN`
   führt `phase-c1`, das im Korpus nicht existiert — toter Eintrag, Hygiene.

## 8. Korpus-Semantik + Verfahren

- **phase-b-Migration 16→41 ist eine bewusste Korpus-Semantik-Änderung.** Die
  Golden-Reports entstanden vor dem Gabel/Messer-Enrollment; ab jetzt läuft phase-b
  gegen den vollen 41-Artikel-Kandidatenraum (härtere, ehrlichere Probe). Der alte
  16er-Stand bleibt in `backups/bundles/2026-07-24_phase-b_original-16er/`.
- **Schritt-0-Suite-Tripel = 527 collected / 525 passed / 2 skipped / 0 failed**
  (Skips = 2× camera-hardware). Es gilt zugleich als **Nachdokumentation des
  Merge-Commits b931435** (Push-Freigabe-Bedingung vom 2026-07-23 rückwirkend erfüllt).

## 9. Läufe (im externen Korpus, `runs/`)

`20260724-null-replay-nach-fix` (Baseline-Reprod.), `…-4b-aera-16auf41` (Ära),
`…-4d-post-sync` (Sync), `…-4e-verify-deltas` (Deltas grün), `…-baseline-post-sync`
(neue Baseline), `…-4e-final-check` (final grün). Test-Waisen dieses Laufs nach
`runs/_invalid/` (siehe Abschluss-Commit).
