# Scoring-Analyse – Auswertungslauf

- run_id: `smoke-v2-uiqt-2026-07-19`
- erzeugt: 2026-07-19T23:36:18
- Quelle: `/Users/mikeeberharter/Documents/Doco_Detect/data/captures`
- Reports: 14 (davon bewertet/gelabelt: 14)
- Reports: 14 JSONs nach `/Users/mikeeberharter/Documents/Doco_Detect/reports/analysis/smoke-v2-uiqt-2026-07-19/reports` archiviert – der Quellordner ist bereit für die nächste Testrunde (Bilder bleiben dort liegen).

Grafiken (PNG) für den Menschen, CSV/JSON für Diffs zwischen Testläufen. Bewertungen kommen aus den Richtig/Falsch-Buttons bzw. `evaluate`-Labels.

## A) Confusion Matrix

![confusion_matrix](confusion_matrix.png)

Daten: [`confusion_matrix.csv`](confusion_matrix.csv)

![confusion_matrix_accept](confusion_matrix_accept.png)

Daten: [`confusion_matrix_accept.csv`](confusion_matrix_accept.csv)

## B) Score-Verteilungen (korrekt vs. falsch)

- Mapping: das frühere auto_accept_score existiert im statistischen Scoring nicht mehr – entscheidungsrelevant sind max|z| des Siegers (Gate `max_z_accept`) und die LLR-Margin (`min_llr_margin`).

![score_distributions](score_distributions.png)

Daten: [`score_distributions.csv`](score_distributions.csv)

## C) Near-Miss-Liste (korrekt, aber Margin < 2.0 × 1.5 = 3)

- Keine Near-Misses gefunden – kein knapper korrekter Sieg.

Daten: [`near_misses.csv`](near_misses.csv)

## D) Teilscore-Attribution bei Fehlern

- 3 Fehler ohne Attribution: der richtige Artikel hat den Geometrie-Vorfilter nicht überlebt (dort hilft nur Toleranz/Stammdaten prüfen).
- Keine attribuierbaren Fehlidentifikationen – gut so.

Daten: [`error_attribution.csv`](error_attribution.csv)

## E) Positionsplot (Ø-Messfehler über die Bildposition)

![position_errors](position_errors.png)

Daten: [`position_errors.csv`](position_errors.csv)

## F) Quoten mit Wilson-Konfidenzintervallen

![metrics](metrics.png)

Daten: [`metrics.json`](metrics.json)
