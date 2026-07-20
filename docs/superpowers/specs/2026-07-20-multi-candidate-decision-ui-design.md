# Spec: Mehrkandidaten-Entscheidungspfad sichtbar machen (beide UIs)

Datum: 2026-07-20 · Status: vom User freigegeben (Design-Gespräch)

## Kontext und Grundsatzentscheidungen

Die ursprüngliche Anforderung („bisher nur Ein-Treffer-Pfad") wurde gegen
einen veralteten Repo-Stand geschrieben. Seit dem Statistik-Scoring-Umbau
(15.07., `docs/superpowers/plans/2026-07-15-statistical-scoring.md`)
existieren dreiwertige Entscheidung, gerankte Kandidaten mit
kandidatenspezifischer Höhenkorrektur, Margin und Feature-Breakdown
bereits in `matcher.py`. Diese Spec baut ausschließlich die echten
Lücken: Sichtbarkeit in beiden UIs, zentrale Format-Helfer, den
„Keiner davon"-Pfad, knappe Demo-Szenarien und Schwellen-Randfall-Tests.

**Entschieden (User, 2026-07-20):**

1. **Das statistische Gate bleibt.** Keine Rückkehr zu
   `auto_accept_score`/`auto_accept_margin` (die wurden am 15.07. bewusst
   ersetzt, siehe `config/config.yaml` Kommentar bei `max_z_accept`).
   Anzeige-Mapping statt Logik-Umbau:

   | Anzeige (Spec-Begriff) | Wire-Name (`MatchReport.decision`) | Bedingung (unverändert) |
   |---|---|---|
   | AUTO_ACCEPT | `accept` | max\|z\| ≤ `max_z_accept` **und** LLR-Margin ≥ `min_llr_margin` **und** Referenzen vorhanden |
   | CONFIRM | `ambiguous` | Gate ok, aber Margin verfehlt **oder** keine Enrollment-Referenzen |
   | NO_MATCH | `reject` | Geometriefilter leer **oder** Gate verfehlt (max\|z\| > Schwelle) **oder** Segmentierungsfehler (Rand) |

   Die JSON-Wire-Namen bleiben unverändert (Golden-Reports, Baseline,
   Analyse hängen daran); die Spec-Begriffe existieren nur in der Anzeige.
2. **„Keiner davon" = Artikel-Picker + Verdict:** durchsuchbare
   Artikelliste + Option „Unbekannt"; Auswahl schreibt `verdict=wrong`
   (+ wahren Artikel als `label`) über `reporting.save_verdict` ins
   Report-JSON → füttert die Verwechslungsmatrix der Batch-Auswertung.
3. **Zwei dokumentierte Spec-Abweichungen:**
   - Verwechsler-Paar ist **TELLER-19/TELLER-20 mit Zwischenbild 195 mm**
     statt „Teller 25/26": ein 255-mm-Objekt sprengt die Demo-FOV bei
     1080p-Config (216 mm sichtbare Höhe) und endet als Randfall.
     19/20-bei-195 liegt in jeder Config-Auflösung im Bild und erfüllt
     dieselbe Absicht (beide Kandidaten im Toleranzfenster ±6 mm).
   - „confirm_wegen_score" existiert in der Statistik-Semantik nicht:
     „bester Kandidat unter der Güte-Schwelle" ist Gate-Fail und damit
     **NO_MATCH** („vermutlich nicht in der Datenbank", niemals
     automatisch buchen) — wird genau so getestet, nicht als CONFIRM.

## A. Matcher (additiv, kein Logik-Umbau)

- `CandidateReport` bekommt `margin_to_next: float | None = None`:
  eigener `log_score` minus der des Nächstplatzierten; letzter Kandidat
  und Einzelkandidat: `None`. Wird in `match()` nach der Sortierung
  befüllt.
- `CHANNELS` + `channel_scores()` ziehen von `analysis.py` nach
  `matcher.py` um (dort lebt `CandidateReport`; vermeidet den
  Matplotlib-Import in UI-Prozessen). `analysis.py` importiert sie von
  dort re-exportierend — kein API-Bruch für Bestandscode.
- Kompatibilität: `MatchReport.from_dict` toleriert alte JSONs ohne das
  neue Feld (Dataclass-Default). Entscheidungslogik unangetastet →
  **die Smoke-Baseline 11/14 bleibt gültig**; nach Umsetzung per
  `evaluate data/testset-smoke` verifizieren (gleiche drei Abweichungen).

## B. Zentrale Anzeige-Helfer (`docodetect/display.py`)

Neues Modul ohne Qt-/Streamlit-Abhängigkeit; `pipeline.py` re-exportiert
die Funktionen, damit die Regel „UIs importieren nur pipeline" formal
hält. Deutsch formatiert (Dezimalkomma). Funktionen:

- `format_diameter(c: CandidateReport) -> str` —
  „Ø 141,0 mm (höhenkorrigiert, h = 60 mm)"; bei `height_mm == 0`:
  „Ø 180,0 mm (Bodenebene)".
- `format_delta(c, cfg) -> str` — „Δ 2,4 mm von ±6,0"
  (`geometry_error_mm` gegen `matching.diameter_tolerance_mm`).
- `format_rank_line(c) -> str` — „2. Teller 20 · 61 %" (Posterior).
- `channel_percentages(c) -> dict` — `{"geometry": 0..1, "color": 0..1,
  "shape": 0..1}` als `exp(Kanal-Log-Beitragssumme)` (1,0 = perfekte
  Übereinstimmung; ehrliche Likelihood-Darstellung, keine erfundene
  Skala). Basis: `channel_scores()` aus A.
- `headline(decision, best_name=None) -> tuple[str, str]` — Text +
  Statusklasse: („✓ Automatisch übernommen: <Name>", "accept") /
  („Bitte bestätigen", "confirm") / („Kein Treffer", "reject").

## C. Qt-App (`docodetect/ui_qt/`)

- Headline-Wortlaut über `headline()`-Helfer; accept-Text wird
  „✓ Automatisch übernommen: <Name>" (statt „Erkannt:").
  **Farbdoppelung auflösen:** Statusfarbe nur in der Headline,
  Kartenrahmen neutral.
- `ResultCard`: Ø-Zeile aus `format_diameter`, Δ-Zeile aus
  `format_delta`, Gesamtscore-Balken (Posterior, wie bisher) + drei
  kleine Teilscore-Balken (Geometrie/Farbe/Form aus
  `channel_percentages`).
- ACCEPT: Siegerkarte + Plätze 2–3 als kompakte Textzeilen
  (`format_rank_line`) — macht die Margin sichtbar.
- CONFIRM: 2–3 klickbare Karten (bestehender Bestätigungsweg) **plus**
  Button „Keiner davon / manuell korrigieren" → Dialog mit
  durchsuchbarer Artikelliste (QComboBox + Completer, Muster aus dem
  Einlern-Dialog, Daten aus `list_articles()`) + Option „Unbekannt";
  Ergebnis via `save_verdict` (Entscheidung 2).
- NO_MATCH: Headline rot + Diagnosezeile mit Rohmesswerten aus
  `report.measured` (Ø Bodenebene, Rundheit, Fläche).

## D. Streamlit (`app.py`)

Gleiche Pfade, gleiche Helfer, Bordmittel — kein optisches
1:1-Matching:

- Statusheadline via `headline()` → `st.success`/`st.warning`/`st.error`.
- Pro Kandidat dieselben Strings + drei `st.progress` für die
  Teilscores; unter dem Sieger Plätze 2–3 kompakt (`format_rank_line`).
- CONFIRM: Kandidaten anklickbar/auswählbar + „Keiner davon" mit
  Artikel-Selectbox → derselbe `save_verdict`-Weg.
- Kein Demo-Dropdown (die Streamlit-UI bietet keine Demo-Bilder an;
  die „falls"-Bedingung der Anforderung greift nicht).

## E. Demo-Szenarien (nur Demo-Kit; Smoke-Testset unberührt)

- Neuer Demo-Artikel **TELLER-19** (Ø 190, h 0) im Demo-Seed
  (3 Referenz-Shots wie die übrigen).
- Neues Demo-Bild **„Teller 19/20 (knapp)"**: Teller in 195 mm
  gezeichnet, Farbe/Form identisch zu TELLER-19/20 → beide Kandidaten
  innerhalb ±6 mm, LLR-Margin < 2 → zuverlässig CONFIRM.
- Neues Demo-Bild **„Unbekanntes Objekt"**: Teller Ø 120 mm → kein
  Artikel in Toleranz → NO_MATCH.
- Beide Bilder ins Demo-Dropdown der Qt-App; bestehende Demo-Artikel
  und deren Erwartungen bleiben unverändert (Ø-Abstände 19↔18/20 sind
  10 mm > 6 mm — keine Wechselwirkung mit den Alt-Szenarien).
- E2E-Demo-Tests: Knapp-Bild → `ambiguous` mit 2 Kandidaten;
  Unbekannt-Bild → `reject` ohne Kandidaten.

## F. Tests (`tests/test_matching_decisions.py`)

Synthetische Features direkt gegen `match()`, ohne Kamera. Schwellen
aus `load_config()` als Fixture injiziert, nie dupliziert. Fälle:

1. `auto_accept`: klarer Sieger, beide Bedingungen erfüllt.
2. `confirm_wegen_margin`: zwei nahe Kandidaten, Gate ok, LLR < Schwelle.
3. `confirm_ohne_referenzen`: geometry-only-Sieger kann nie accepten.
4. `no_match_gate`: Ø passt, Farbe völlig fremd → max|z| > Schwelle →
   reject (das ehrliche Mapping von „score zu niedrig", Entscheidung 3).
5. `no_match_leerer_vorfilter`: kein Artikel in Geometrie-Toleranz.
6. **Randfälle exakt auf der Schwelle** (Verhalten festschreiben):
   max|z| **==** `max_z_accept` → Gate besteht (`<=`); LLR-Margin **==**
   `min_llr_margin` → accept (`>=`). Konstruktion über `sigma_enroll=0`
   → `sigma_eff == sigma_floor` → Distanz = z·floor exakt setzbar.
7. Höhenkompensation: gleicher Pixelkreis, zwei Kandidaten mit
   h=0 und h=60 → `corrected_diameter_mm` beider Kandidaten exakt
   `measured · (Z − h) / Z` mit Z aus `geometry.camera_height_mm`.
8. `border_clipped`: `identify()` mit angeschnittenem Objekt → reject,
   `candidates == []`, kein Match-Ergebnis.
9. `margin_to_next`: befüllt/None korrekt über die Rangfolge.
10. Format-Helfer (`display.py`): Zahlenformate (Komma), h-Angabe,
    Δ-String, `headline()`-Mapping, `channel_percentages`-Wertebereich.

## Nicht-Ziele

- Keine Änderung an Schwellen, Toleranzen oder Scoring-Formeln.
- Keine Umbenennung der Wire-Decision-Namen.
- Kein Buchungs-Backend hinter der Bestätigung (nur Verdict-Log).
- Kein Streamlit-Demo-Modus, kein Packaging.

## Erfolgskriterien

1. Volle Suite grün inkl. neuer Tests (`pytest tests/`).
2. `evaluate data/testset-smoke` liefert unverändert 11/14 mit
   denselben drei Abweichungen (Baseline-Schutz).
3. Qt-Demo: „Teller 19/20 (knapp)" → gelbe CONFIRM-Ansicht mit zwei
   Karten + „Keiner davon"; „Unbekanntes Objekt" → rote NO_MATCH-Ansicht
   mit Rohmesswerten; TELLER-18 weiterhin grün „Automatisch übernommen".
4. Streamlit zeigt für dieselben Reports inhaltlich identische Strings
   (gleiche Helfer, keine Duplikate).
