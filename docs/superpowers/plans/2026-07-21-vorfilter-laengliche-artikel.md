# Vorfilter-Vergleichsfehler für längliche Artikel — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Vergleichsbasis des geometrischen Vorfilters für längliche Artikel
(width_mm/depth_mm gesetzt) korrigieren, damit Messgröße und DB-Referenz
dieselbe physikalische Größe beschreiben — belegt durch Korpusdaten.

**Architektur:** Ein-Zeilen-Fix in `matcher.py::_nominal_size_mm()`: für den
länglichen Zweig `max(width_mm, depth_mm)` (Länge) statt
`hypot(width_mm, depth_mm)` (Diagonale des minAreaRect) zurückgeben. Kein
neuer Messwert, keine neue Abhängigkeit, keine Schwellenänderung.

**Tech Stack:** Python, pytest, `docodetect.corpus` Regressions-Harness.

## Global Constraints

- NUR `docodetect/matcher.py` wird angefasst. `features.py`, `segmentation.py`,
  `pipeline.py`, `camera.py`, `calibration.py` bleiben unberührt.
- Keine Schema-Änderung, keine Änderung an `create-article`.
- `matching.diameter_tolerance_mm` bleibt `6.0` (config/config.yaml, NICHT ändern).
- Höhenkompensation (`height_corrected_scale`) bleibt pro Kandidat wirksam,
  unabhängig von der Nominal-Formel.
- Tier 1 Corpus-Check MUSS 129/129 PASS bleiben (Matcher wird von Tier 1 gar
  nicht aufgerufen — reine Bestätigung, kein Risiko).
- Tier 2 Corpus-Check wird sich ändern (siehe Analyse unten) — das ist
  erwartet und muss Bild für Bild erklärt werden, nicht stillschweigend
  rebaselined.
- Kein `git commit`/`push` ohne explizite Bestätigung des Nutzers.

## Vorab-Analyse (bereits durchgeführt, Ergebnis dieser Plan-Grundlage)

**Ausgangszustand bestätigt:** `corpus-run --tier 1 --check` → 129/129 OK.
`corpus-run --tier 2 --check` → 60/60 OK (beide vor jeder Änderung grün).

**Optionsvergleich am Korpus** (alle 60 gelabelten Löffel-Bilder aus
`phase-b`, nicht nur die 5 bekannten Kills; Skript:
`analyze_prefilter.py`/`analyze_candidate_sets.py`/`analyze_option_b_sets.py`
im Scratchpad, Ergebnis unten übernommen):

| Option | Vergleichsbasis | mean\|err\| | median | max\|err\| | n>6mm (Kills) |
|---|---|---|---|---|---|
| Aktuell (Diagonale) | `hypot(width,depth)` | 2.82 mm | 2.43 mm | 8.41 mm | **5** |
| **A (gewählt)** | `max(width,depth)` = Länge | 1.51 mm | 1.48 mm | 4.26 mm | **0** |
| B Länge-Teil | gemessene minAreaRect-Länge | 1.41 mm | 1.25 mm | 4.36 mm | 0 |
| B Breite-Teil | gemessene minAreaRect-Breite | 0.63 mm | 0.59 mm | 1.93 mm | 0 |

**Entscheidung: Option A.** Begründung:
1. Löst alle 5 bekannten Kills UND bleibt bei allen 60 Bildern unter der
   6-mm-Toleranz (kein Ausreißer nahe der Grenze).
2. Braucht keinen neuen Messwert: `measured.circle_diameter_mm` (bereits
   vorhanden) wird weiterhin verglichen, nur die DB-Seite ändert sich.
3. Option B (zwei Constraints aus gemessenem minAreaRect auf der bereits
   ausgedünnten Report-Kontur) liefert KEINE bessere Trennschärfe im Korpus
   (Breite-Residuen sind ohnehin klein, <2mm) und erzeugt sogar MEHR
   Kandidatenset-Änderungen (36 von 60 Bildern vs. 32 bei A) durch eine
   zusätzliche, unabhängige Messquelle (cv2.minAreaRect auf der
   400-Punkte-Kontur statt der bereits in `Features` vorhandenen
   `circle_diameter_mm`). Mehr Komplexität, mehr Abhängigkeit von
   `contour is not None`, kein Genauigkeitsgewinn — abgelehnt.
4. Geometrische Begründung für den Randfall `width ≈ depth`: Cutlery-Artikel
   (Löffel, künftig Gabel/Messer) sind keine scharfkantigen Rechtecke,
   sondern "Stadion"-Form (Schaft + abgerundete Enden). Für eine
   Stadion-Kontur ist der minEnclosingCircle-Durchmesser **exakt gleich der
   Länge L, für jede Breite W ≤ L** (verifiziert per Rasterkontur:
   L=190/W=40 → 190.00; L=100/W=100 (Breite=Länge, entartet zum Kreis) →
   100.00; L=100/W=10 → 100.00). Die Diagonale wäre nur für ein
   scharfkantiges Rechteck korrekt — das ist bei keinem Cutlery-Artikel der
   Fall. Option A ist damit nicht nur für sehr längliche, sondern über den
   GESAMTEN Breite/Länge-Bereich physikalisch exakt.

**Erwartung vor der Implementierung (Schritt 3 des Auftrags):**
- Die 5 bekannten Kills (IDs unten) überstehen den Vorfilter.
- ABWEICHEND von der ursprünglichen Annahme "alle übrigen Bilder
  unverändert": die Simulation zeigt, dass **32 von 60** Löffel-Bildern ein
  geändertes Kandidatenset bekommen (nicht nur 5). Grund: mehrere Löffel im
  Korpus haben nahezu identische Längen (Cluster ~188–194 mm:
  LOEFFEL-1/2/3/5/6/12; Cluster ~124–141 mm: LOEFFEL-9/11/13/14/15). Die
  Diagonale hat diese Artikel bisher — durch einen physikalisch nicht
  begründeten Zufalls-Offset, der mit der Objektbreite skaliert — teils aus
  dem Kandidatenset jedes anderen herausgehalten. Nach der Korrektur werden
  einige dieser Nachbarn zusätzlich (korrekt!) zu Geometrie-Kandidaten, die
  dann von Score/Farbe/Form unterschieden werden müssen. Das ist erwartetes,
  Bild-für-Bild zu erklärendes Tier-2-DRIFT/FAIL, kein Fehler — siehe Task 2.
- Was aus den 5 Kills im Scoring wird (ACCEPT/AMBIGUOUS), ist Ergebnis des
  echten Harness-Laufs, nicht vorgegeben.

**Die fünf bekannten Kill-Fälle** (aus dem Übergabebericht, phase-b,
`Doco_Detect_corpus/phase-b/reports/`):

| Bild | Report | Label | err_diag (alt) | err_A (neu) |
|---|---|---|---|---|
| `1784562435798.png` | `4587d1a8.json` | LOEFFEL-3 | −8.41 mm | −4.26 mm |
| `1784561499560.png` | `4f08405b.json` | LOEFFEL-1 | −6.97 mm | −2.75 mm |
| `1784562390997.png` | `a2883cb7.json` | LOEFFEL-1 | −6.02 mm | −1.80 mm |
| `1784562412154.png` | `b26a6160.json` | LOEFFEL-2 | −7.37 mm | −3.80 mm |
| `1784562504239.png` | `cc1f627e.json` | LOEFFEL-6 | −7.78 mm | −3.52 mm |

**Flächen-Vorfilter (`area_tolerance_pct`) — nur Berichtspflicht, kein Fix:**
Der Flächencheck in `matcher.py` läuft NUR `if art.diameter_mm` (runder
Zweig). Für längliche Artikel (`diameter_mm is None`) wird er komplett
übersprungen — trägt für sie also NICHT dieselbe Inkonsistenzklasse (er
greift schlicht nie). Für runde Artikel vergleicht er `measured.area_mm2`
(Polygonfläche) gegen `pi*(nominal/2)^2`, wobei `nominal` selbst aus
`circle_diameter_mm` beim Anlegen abgeleitet wurde — ein leichteres Echo
desselben Effekts (Umkreis- vs. Flächen-Maß), aber unbelegt als
Fehlerquelle in der Praxis. Empfehlung ins Ergebnisdokument, nicht fixen.

## Task 1: `_nominal_size_mm` korrigieren, mit Unit-Tests (TDD)

**Files:**
- Modify: `docodetect/matcher.py:162-172` (`_nominal_size_mm`)
- Test: `tests/test_matching_decisions.py` (Tests anhängen, gleiche Fixtures
  `cfg`/`cal`/`fake()` wie im Rest der Datei)

**Interfaces:**
- Konsumiert: `Article.width_mm`, `Article.depth_mm`, `Article.diameter_mm`
  (alle `float | None`, `docodetect/database.py:72-81`).
- Produziert: `_nominal_size_mm(article) -> float | None`, unverändert in
  Signatur — wird intern in `match()` als `nominal` weiterverwendet
  (Zeile 219 `nominal = _nominal_size_mm(art)`), kein Caller ändert sich.

- [ ] **Step 1: Failing Tests schreiben** — an `tests/test_matching_decisions.py`
  anhängen (nutzt vorhandene `cfg`, `cal`, `fake()` Fixtures/Helper aus
  derselben Datei; `make_db` unterstützt nur `diameter_mm`, für längliche
  Artikel wird `db.create_article` direkt mit `Article(...)` aufgerufen):

```python
def test_laenglicher_artikel_vergleicht_gegen_laenge_nicht_diagonale(cfg, cal, tmp_path):
    """Kern des Fixes: Ø-Vergleich fuer laengliche Artikel (width/depth
    gesetzt) muss gegen die LAENGE (max(width,depth)) gehen, nicht gegen
    die Diagonale (hypot). Ein Loeffel mit Laenge 190mm/Breite 40mm hat
    Diagonale ~194.15mm - eine Messung von 187mm liegt 7.15mm von der
    Diagonale entfernt (> 6mm Toleranz, waere ALT gekillt) aber nur 3mm
    von der Laenge entfernt (<= 6mm, UEBERLEBT den Vorfilter)."""
    db = Database(cfg)
    db.init_schema()
    db.create_article(Article(
        article_number="LOEFFEL", name="Loeffel", category=None,
        diameter_mm=None, width_mm=190.0, depth_mm=40.0, height_mm=None,
        color_desc=None, notes=None))
    db.add_reference("LOEFFEL", fake(190.0))
    try:
        rep = match(fake(187.0), db, cal, cfg)
        assert [c.article_number for c in rep.candidates] == ["LOEFFEL"]
        assert rep.candidates[0].nominal_size_mm == pytest.approx(190.0)
    finally:
        db.close()


def test_laenglicher_artikel_ausserhalb_laengen_toleranz_wird_gekillt(cfg, cal, tmp_path):
    """Gegenprobe: liegt die Messung auch von der LAENGE weiter als 6mm weg,
    bleibt der Artikel zu Recht draussen (kein pauschales Aufweichen)."""
    db = Database(cfg)
    db.init_schema()
    db.create_article(Article(
        article_number="LOEFFEL", name="Loeffel", category=None,
        diameter_mm=None, width_mm=190.0, depth_mm=40.0, height_mm=None,
        color_desc=None, notes=None))
    db.add_reference("LOEFFEL", fake(190.0))
    try:
        rep = match(fake(180.0), db, cal, cfg)  # 10mm von der Laenge weg
        assert rep.candidates == []
        assert rep.decision == "reject"
    finally:
        db.close()


def test_rundes_produkt_unveraendert_ueber_diameter_mm(cfg, cal, tmp_path):
    """Runde Artikel (diameter_mm gesetzt) durchlaufen weiterhin den
    Diameter-Zweig von _nominal_size_mm - der Fix darf diesen Pfad nicht
    beruehren."""
    db = make_db(cfg, [("TELLER", 200.0, 0.0, [fake(200.0)])])
    try:
        rep = match(fake(200.0), db, cal, cfg)
        assert rep.candidates[0].nominal_size_mm == pytest.approx(200.0)
    finally:
        db.close()


def test_laenglich_width_gleich_depth_randfall(cfg, cal, tmp_path):
    """Randfall width==depth (entartete 'Stadion'-Form == Kreis): die
    Laenge (max(width,depth)) UND die Diagonale (hypot) faerben hier
    auseinander (50 vs. 70.7mm) - der Fix muss weiterhin gegen die Laenge
    vergleichen, nicht gegen die (hier besonders grosse) Diagonale."""
    db = Database(cfg)
    db.init_schema()
    db.create_article(Article(
        article_number="QUADRAT", name="Quadrat", category=None,
        diameter_mm=None, width_mm=50.0, depth_mm=50.0, height_mm=None,
        color_desc=None, notes=None))
    db.add_reference("QUADRAT", fake(50.0))
    try:
        rep = match(fake(52.0), db, cal, cfg)  # 2mm von der Laenge (50) weg
        assert [c.article_number for c in rep.candidates] == ["QUADRAT"]
        assert rep.candidates[0].nominal_size_mm == pytest.approx(50.0)
    finally:
        db.close()


def test_laenglich_hoehenkompensation_bleibt_pro_kandidat_wirksam(cfg, cal, tmp_path):
    """Die Formel fuer corrected_diameter_mm (Hoehenkompensation) ist von
    der Nominal-Wahl unabhaengig - muss fuer laengliche Artikel mit
    height_mm > 0 weiterhin greifen (wie bei runden Artikeln)."""
    from docodetect.features import height_corrected_scale
    db = Database(cfg)
    db.init_schema()
    db.create_article(Article(
        article_number="LOEFFEL_HOCH", name="Loeffel", category=None,
        diameter_mm=None, width_mm=190.0, depth_mm=40.0, height_mm=15.0,
        color_desc=None, notes=None))
    db.add_reference("LOEFFEL_HOCH", fake(190.0))
    try:
        measured_circle = 195.0
        rep = match(fake(measured_circle), db, cal, cfg)
        expected = height_corrected_scale(measured_circle, 15.0, cal.camera_height_mm)
        assert rep.candidates[0].corrected_diameter_mm == pytest.approx(
            round(expected, 2))
    finally:
        db.close()
```

- [ ] **Step 2: Tests laufen lassen, Fehlschlag bestätigen**

Run: `pytest tests/test_matching_decisions.py -v -k "laenglich or rundes_produkt"`
Expected: `test_laenglicher_artikel_vergleicht_gegen_laenge_nicht_diagonale` und
`test_laenglich_width_gleich_depth_randfall` FAIL (Kandidat fehlt, weil der
alte Code gegen die Diagonale vergleicht). Die anderen drei können bereits
PASS sein (sie prüfen unveränderte oder bereits korrekte Pfade) — das ist
für TDD in Ordnung, sie dienen als Regressionsschutz für Nachbarverhalten.

- [ ] **Step 3: Minimale Implementierung**

`docodetect/matcher.py:162-172`, aktueller Code:

```python
def _nominal_size_mm(article: Article) -> float | None:
    """Nominal footprint size to compare against the measured circle diameter.
    Round items: diameter. Non-round: the diagonal-ish max of width/depth,
    since min-enclosing-circle of a rectangle equals its diagonal."""
    if article.diameter_mm:
        return float(article.diameter_mm)
    if article.width_mm and article.depth_mm:
        return float(np.hypot(article.width_mm, article.depth_mm))
    if article.width_mm:
        return float(article.width_mm)
    return None
```

wird zu:

```python
def _nominal_size_mm(article: Article) -> float | None:
    """Nominal footprint size to compare against the measured circle diameter
    (docodetect.features.extract: cv2.minEnclosingCircle). Round items:
    diameter. Non-round (spoon/fork/knife): the LONGER side of the
    minAreaRect, not the diagonal. Cutlery footprints are a "stadium" shape
    (shaft + rounded ends), not a sharp-cornered rectangle: for a stadium
    of length L and width W <= L, the min-enclosing-circle diameter equals
    L exactly, independent of W (verified analytically and against
    rasterized contours down to W == L). The diagonal hypot(W, L) is only
    correct for a sharp-cornered rectangle, which no enrolled article is."""
    if article.diameter_mm:
        return float(article.diameter_mm)
    if article.width_mm and article.depth_mm:
        return float(max(article.width_mm, article.depth_mm))
    if article.width_mm:
        return float(article.width_mm)
    return None
```

(`np` bleibt in `matcher.py` für andere Stellen importiert — nicht entfernen,
nur die eine `np.hypot`-Zeile ändert sich zu `max`.)

- [ ] **Step 4: Tests laufen lassen, PASS bestätigen**

Run: `pytest tests/test_matching_decisions.py -v`
Expected: alle PASS, inkl. der 5 neuen Tests aus Step 1.

- [ ] **Step 5: Commit** (erst nach Rückfrage beim Nutzer — NICHT automatisch)

```bash
git add docodetect/matcher.py tests/test_matching_decisions.py
git commit -m "fix(matcher): Vorfilter fuer laengliche Artikel vergleicht Laenge statt Diagonale"
```

## Task 2: Volle Testsuite, Harness (Tier 1 + Tier 2), Re-Baseline, Doku

**Files:**
- Read/Run only: `corpus-run` CLI (`docodetect/cli.py`), `corpus-diff` CLI
- Modify: `README.md` (Abschnitt Vorfilter/Scoring), `corpus/baseline.json`
  (via `--update-baseline`, NICHT von Hand editieren)
- Modify: `docs/superpowers/reports/2026-07-20-corpus-harness-abschluss.md`
  (offenen Punkt 1 als erledigt markieren, Verweis auf das neue
  Ergebnisdokument)
- Create: `docs/superpowers/reports/2026-07-21-vorfilter-laengliche-artikel-ergebnis.md`
  (Ergebnisdokument: Option + Begründung + Verteilungszahlen + Diff-Liste +
  neue Baseline-Quoten + offene Empfehlungen)

**Interfaces:**
- Konsumiert: Task 1's Fix in `matcher.py`, keine neuen Schnittstellen.
- Produziert: aktualisierte `corpus/baseline.json` (beide Tiers mit vollen
  Quoten), aktualisiertes README/Übergabebericht, neues Ergebnisdokument.

- [ ] **Step 1: Volle Testsuite**

Run: `pytest`
Expected: alle PASS/SKIPPED wie vor der Änderung (400 passed, 17 skipped
laut Übergabebericht — Hardware-Tests bleiben skip), keine neuen Failures.

- [ ] **Step 2: Tier 1 Harness — MUSS unverändert grün bleiben**

Run: `python -m docodetect.cli corpus-run --tier 1 --check`
Expected: Exit 0, 129/129 wie vor der Änderung (Tier 1 ruft `matcher.match()`
nicht auf — reine Bestätigung, dass nichts außerhalb des Matchers
angefasst wurde). Bei JEDER Abweichung: stoppen, NICHT baselinen, Ursache
im Diff (`corpus-diff`) suchen — lt. Auftrag ist das ein Fehler in diesem
Fix.

- [ ] **Step 3: Tier 2 Harness — Lauf ohne --check, dann Diff**

Run: `python -m docodetect.cli corpus-run --tier 2` (OHNE `--check`, um erst
zu sehen was sich ändert, bevor irgendetwas gegen die Baseline geprüft wird)

Dann: `python -m docodetect.cli corpus-diff <alter-lauf> <neuer-lauf>` gegen
den letzten grünen Tier-2-Lauf aus der Bestätigung in Task 1 Step 0, um eine
vollständige Liste aller geänderten Bilder zu bekommen (Entscheidung,
Kandidatenliste, gate_passed, llr_margin/max_z_winner-Drift).

Für JEDES geänderte Bild: in die Diff-Liste im Ergebnisdokument aufnehmen
mit einer Zeile Erklärung (Kandidat X neu wegen Längen-Nachbarschaft zu Y,
oder: einer der 5 bekannten Kills, jetzt ACCEPT/AMBIGUOUS mit Begründung).
Ungeklärte Änderungen (Bild wo die Ursache nicht auf die Nominal-Formel
zurückzuführen ist) sind ein Stop-Signal — nicht baselinen, erst
analysieren.

- [ ] **Step 4: Re-Baseline BEIDER Tiers mit vollen Quoten**

Bekannte Falle aus dem Übergabebericht (Abschnitt 3, "Das Merge-Gate konnte
sich selbst entwaffnen"): `--update-baseline` mit Default `--tier 1`
schreibt LEERE Quoten und schaltet das Gate lautlos ab. Das Kommando
verweigert das inzwischen bei leeren Quoten mit Exit 2 — trotzdem explizit
BEIDE Tiers einzeln aufrufen und je das Ergebnis prüfen:

```bash
python -m docodetect.cli corpus-run --tier 1 --update-baseline
python -m docodetect.cli corpus-run --tier 2 --update-baseline
```

Danach verifizieren: `corpus/baseline.json` enthält für Tier 2 NICHT-leere
`quotas` (accuracy_top1, accuracy_top3, false_accept_rate,
auto_accept_rate, je mit Wilson-Intervall) und für beide Tiers Code-/
Config-Fingerprint des erzeugenden Laufs. Dann:

```bash
python -m docodetect.cli corpus-run --tier 1 --check
python -m docodetect.cli corpus-run --tier 2 --check
```

Expected: beide Exit 0 gegen die NEUE Baseline.

- [ ] **Step 5: Ergebnisdokument schreiben**

`docs/superpowers/reports/2026-07-21-vorfilter-laengliche-artikel-ergebnis.md`:
gewählte Option + Begründung (aus diesem Plan übernehmen), Verteilungszahlen
vorher/nachher (Tabelle aus diesem Plan), vollständige Diff-Liste aus Step 3
mit Erklärung je Bild, neue Baseline-Quoten (Zahlen aus Step 4), offene
Empfehlungen: (a) längliche Artikel könnten eine eigene, weniger strenge
`diameter_tolerance_mm` vertragen als runde — NICHT umgesetzt, nur
Empfehlung mit den Verteilungszahlen als Beleg; (b) Flächen-Vorfilter für
runde Artikel vergleicht Umkreis-abgeleitetes Nominal gegen Polygonfläche —
leichteres Echo derselben Inkonsistenzklasse, unbelegt als Praxisproblem,
nur Empfehlung.

- [ ] **Step 6: README aktualisieren**

Im Abschnitt, der den Vorfilter/das Scoring beschreibt (Suche nach
"Vorfilter" oder "diameter_tolerance_mm" in `README.md`): den Vergleich für
längliche Artikel von "Diagonale des minAreaRect" auf "Länge (längere Seite
des minAreaRect)" richtigstellen, mit einem Satz zur Stadion-Form-Begründung.

- [ ] **Step 7: Übergabebericht — offenen Punkt abhaken**

In `docs/superpowers/reports/2026-07-20-corpus-harness-abschluss.md`,
Abschnitt "Offene Punkte", Punkt 1 ("Der Vorfilter vergleicht zwei
verschiedene Grössen"): als erledigt markieren, mit Verweis auf das neue
Ergebnisdokument aus Step 5.

- [ ] **Step 8: Commit** (erst nach Rückfrage beim Nutzer)

```bash
git add corpus/baseline.json README.md \
  docs/superpowers/reports/2026-07-20-corpus-harness-abschluss.md \
  docs/superpowers/reports/2026-07-21-vorfilter-laengliche-artikel-ergebnis.md
git commit -m "docs(corpus): Re-Baseline nach Vorfilter-Fix (laengliche Artikel), Ergebnisdokument"
```

## Self-Review

- Spec-Abdeckung: Optionsanalyse (Vorab-Analyse-Abschnitt), Erwartung vor
  Implementierung (dito), Implementierung + Tests (Task 1), Harness Tier 1+2
  + Re-Baseline + Doku (Task 2) — alle Punkte aus dem Auftrag haben eine
  Aufgabe.
- Platzhalter-Scan: keine "TODO"/"später"/"ähnlich wie" — jeder Testcode ist
  vollständig ausgeschrieben.
- Typkonsistenz: `_nominal_size_mm(article: Article) -> float | None`
  Signatur unverändert; `Article.width_mm`/`depth_mm`/`diameter_mm` alle
  `float | None` wie in `database.py:72-81`.
