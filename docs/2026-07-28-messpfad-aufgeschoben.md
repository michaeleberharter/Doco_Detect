# Aufgeschobene Messpfad-Änderungen — nächste Runde (Stand 2026-07-28)

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

Alle drei berühren den Messpfad (matcher/reporting/features) und würden zusammen
ein Re-Baselining des Regressions-Korpus auslösen (`config_fingerprint` bzw.
`code_fingerprint`). Darum in **einer** Messpfad-Runde mit Datenbegründung,
nicht einzeln — jede einzelne Runde zahlt die Re-Baselining-Kosten erneut.
