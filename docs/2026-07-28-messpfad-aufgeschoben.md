# Aufgeschobene Messpfad-Änderungen — nächste Runde (Stand 2026-07-28)

> ## NACHTRAG 2026-08-01: ERLEDIGT am 2026-07-29 — dieses Dokument ist kein offener Auftrag mehr
>
> Alle drei Änderungen sind mit Commit **`59edc46`** („Messpfad-Runde:
> Prefilter-Liste, lat_p98, µs-timestamp im Report", 2026-07-29) umgesetzt:
>
> | Punkt | Stand heute |
> |---|---|
> | 1. Prefilter-Liste | `matcher.py` führt `prefiltered` als Feld des Reports und protokolliert **jeden** Kill mit Grund (`diameter`/`area`) und Abstand zur Toleranz |
> | 2. `lat_p98` | `features.py` berechnet und speichert `lat_p98_mm`; `0.0` markiert Referenzen von vor der Einführung |
> | 3. µs-`timestamp` | `matcher.py` schreibt `isoformat(timespec="microseconds")` |
>
> **Der Satz „Damit ist die risikotragende Größe derzeit nicht messbar" gilt
> nicht mehr.** Der Fixpunkt-Test vom 2026-08-01 hat die Prefilter-Kills
> ausgewertet — Befund 5: bei allen 15 Aufnahmen steht der wahre Artikel im
> Kandidatenset, kein einziger Kill des korrekten Artikels
> ([2026-08-01-fixpunkt-test-scoring.md](2026-08-01-fixpunkt-test-scoring.md)).
> Und die Simulation vom selben Tag hat die Gegenrichtung gemessen: ein
> **engerer** Vorfilter tötet den wahren Artikel und lässt einen falschen
> konkurrenzlos gewinnen (`k_safe` 166 → 35 bei `diameter_tolerance_mm` 4,0,
> [2026-08-01-scoring-simulation-widerlegte-thesen.md](2026-08-01-scoring-simulation-widerlegte-thesen.md),
> Abschnitt 3).
>
> **Die Vorhersage aus „Warum gebündelt" hat gehalten:** es war ein
> Cache-Recompute, kein Baseline-Update. Beide `--check`-Läufe am 2026-07-31
> waren Exit 0, alle Tier-2-Quoten deckten sich exakt mit der unveränderten
> Baseline ([2026-07-31-baseline-code-fingerprint.md](2026-07-31-baseline-code-fingerprint.md)).
> Offen blieb allein die dort beschriebene Cache-Folge: die Baseline trägt noch
> den `code_fingerprint` von **vor** dieser Runde, `--changed-only` rechnet
> deshalb mehr neu als nötig.
>
> Der Text unten bleibt unverändert als Herleitung stehen.

Drei Änderungen hängen am selben Ort (was in die Messung bzw. ins Report-JSON
geschrieben wird) und lohnen sich **gebündelt**, nicht einzeln. Alle drei sind
Messpfad-Eingriffe und wurden bewusst aufgeschoben — der Diagnose-Ausbau vom
2026-07-28 (Analyse-Grafiken STUFE B) lief bildfrei und messpfad-frei.

## 1. Prefilter-Liste ins Report-JSON  ← die risikotragende

Prefilter-Kills sind aus den heutigen Report-JSONs **nicht rekonstruierbar**:
die Reports listen nur die *überlebenden* Kandidaten. Ob ein Artikel durch den
Geometrie-Vorfilter fiel oder nur unter Top-k scorte, ist nicht unterscheidbar.
Der Vorfilter-Trichter (`analysis._analysis_prefilter`) zeigt deshalb die
ehrliche dritte Kategorie **„nicht im Kandidatenset"**, nicht „prefilter-killed".

**Warum das zählt:** Laut C-Serie sitzt das **Falschakzept-Risiko konzentriert
genau dort** — kein einziges Falschakzept war je ein Nicht-Kill-Fall. Die
risikotragende Größe ist damit derzeit **nicht messbar**.

Fix: beim Matchen die prefilter-verworfenen Artikelnummern (+ `geometry_error_mm`)
in den Report schreiben (z. B. `prefiltered: [...]`). Berührt `matcher.py` +
`reporting.py`.

## 2. lat_p98 (echte Breite) in Messung + Report

Diagnoseblatt und Drift-Grafik (9) brauchen eine echte Breite; der Report hat
nur `circle_diameter_mm` + `aspect_ratio`, also nutzt (9) den Proxy
`Ø·aspect_ratio`. `lat_p98` (kontur-abgeleitet, C-Serie) wäre die saubere Größe,
müsste aber in der Messung berechnet und im Report abgelegt werden. Berührt
`features.py`/`pipeline.py` + `reporting.py`.

## 3. Mikrosekunden im timestamp-Feld

`matcher.py:228` schreibt `datetime.now().isoformat(timespec="seconds")` →
Sekunden-Auflösung. Aufnahmen derselben Sekunde sind über das `timestamp`-Feld
nicht ordenbar; die Analyse keyt darum auf den ms-Basename des `report_path`.
`isoformat()` (µs) machte das Feld selbst ordnungstragend. Ein-Zeilen-Änderung
in `matcher.py`.

## Warum gebündelt

Alle drei berühren den Messpfad (`matcher.py`/`features.py`, beide in
`corpus/runner.py::CODE_DATEIEN`). Eine Byte-Änderung dort ändert den
`code_fingerprint` und damit den Cache-Key — der Regressions-Korpus rechnet
**einmal komplett neu** (kalter Cache).

Das ist ein **Cache-Recompute, kein Baseline-Update** (frühere Fassung sagte
hier „Re-Baselining" — ungenau): die drei Zusätze (`prefiltered`-Feld,
`lat_p98_mm`, µs-`timestamp`) liegen alle NEBEN der Vergleichsfläche von
`corpus/compare.py` (Tier-1-Allowlist `_TIER1_SKALARE`/`_TIER1_VEKTOREN`; Tier-2:
`decision`/`top_k`/`gate_passed`/`llr_margin`/`max_z_winner`), und
`config_fingerprint` bleibt unberührt (kein `features`/`matching`-Config-Eintrag
ändert sich). `--check` läuft deshalb gegen die **unveränderte** `baseline.json`
und muss grün bleiben — `--update-baseline` wäre hier falsch. Gebündelt lohnt es
sich trotzdem: der einmalige Voll-Recompute fällt so nur einmal an, nicht dreimal.
