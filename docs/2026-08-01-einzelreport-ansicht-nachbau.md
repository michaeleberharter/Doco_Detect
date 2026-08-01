# Einzelreport-Ansicht: was mit Streamlit wegfiel und wie sie nachzubauen wäre

**Datum:** 2026-08-01 · **Art:** Offener Nachbau-Kandidat, nicht beauftragt.
**Anlass:** Die Streamlit-UI wurde vollständig entfernt (Commit **`07586b5`**).
Alle ihre Funktionen haben ein Äquivalent in Qt oder CLI — **außer dieser
einen.**

> **Warum dieses Dokument existiert:** „seit Wochen nicht benutzt" heißt nicht
> „brauche ich nie wieder". Wenn die Windows-Daten da sind und einzelne Fälle
> forensisch angesehen werden sollen, ist genau das die fehlende Ansicht.
> Dieses Dokument ist so geschrieben, dass der Nachbau möglich ist, **ohne den
> alten Code zu lesen**.
>
> Wer ihn doch lesen will:
> `git show 07586b5^:pages/1_Scoring_Analyse.py`

---

## 1. Was die Ansicht konnte — acht Felder

Alle acht rendern **einen** `MatchReport`, live nach einem `identify` oder aus
einer Report-JSON unter `data/captures/`.

### a) Entscheidungs-Badge
Farbige Zeile `ACCEPT` / `AMBIGUOUS` / `REJECT` mit der Klartext-Begründung
aus dem Report.

### b) Gate-Ampel — drei Kennzahlen nebeneinander
| Kachel | Wert | Vergleichswert daneben |
|---|---|---|
| max \|z\| Sieger | `max_z_winner` | Gate `≤ max_z_accept` |
| LLR-Margin (1. vs 2.) | `llr_margin`, „∞ (1 Kandidat)" bei `None` | Schwelle `≥ min_llr_margin` |
| Posterior Top-1 | `candidates[0].posterior` | — |

Die direkte Antwort auf „warum ACCEPT/AMBIGUOUS/REJECT?".

### c) Aufnahme + Kontur-Overlay
Zwei Bilder nebeneinander: Original und dieselbe Aufnahme mit der im Report
gespeicherten Kontur, Bildunterschrift mit dem Randberührungs-Status.

### d) Gemessene Merkmale (Floor-Ebene)
Eine Zeile mit Ø Kreis, Ø äquivalent, Fläche (cm²), Rundheit, Solidity,
Lab Zentrum, Lab Rand. Darunter die **höhenkompensierte** Tabelle pro
Kandidat: Höhe, Ø korrigiert, Nominal, Δ Geometrie — also der Vorfilter,
nachvollziehbar gemacht.

### e) Kandidatentabelle — die Merkmals-Aufschlüsselung
Je Kandidat ein aufklappbarer Block (die ersten `top_k` offen), Kopfzeile
`#n  ARTIKEL — Name · log-Score X · Posterior Y%`, bei fehlendem Enrollment
der Zusatz „keine Referenzen (nur Geometrie)". Darin eine Zeile pro Merkmal
mit **zehn** Spalten:

`Merkmal · Messwert · Referenz · Distanz · σ_enroll · σ_eff · z · logL ·
w_eff · gewichtet`

plus eine Summenzeile `Σ log-Score / Posterior`. Die `z`-Spalte war
eingefärbt (Betragsskala) — dadurch springt das disqualifizierende Merkmal
sofort ins Auge.

### f) Log-Beitrags-Chart
Gruppiertes Balkendiagramm über die Top-k-Kandidaten: x = Merkmal,
y = gewichteter Log-Beitrag, Farbe = Artikel. Bildunterschrift: *weniger
negativ = besser; ein einzelner stark negativer Balken zeigt das Merkmal,
das den Kandidaten disqualifiziert.*

### g) Top-1-vs-Top-2-Kontrast
Die direkte Antwort auf „warum A statt B?". Eine Zeile je Merkmal:
`z` von Top-1, `z` von Top-2, `Δ gewichtet (1−2)` und die Spalte **Vorteil**
mit der Artikelnummer, die bei diesem Merkmal vorn liegt.

### h) Diskriminanz-Panel (Fisher-Adaption)
Balkendiagramm der normierten Fisher-Diskriminanz `D_f` je Merkmal, dazu ein
zweites mit `w_global` gegen `w_eff` (Gewichte vor/nach Adaption, α im Titel).
Entfiel die Adaption, stand dort der Grund: nur 1 Kandidat, α = 0, oder alle
D_f = 0.

---

## 2. Datenlage: alles im Report-JSON, nichts nachzurechnen

**Deine Vermutung stimmt — der Nachbau ist reine Darstellung.** Feld für Feld
geprüft gegen `matcher.MatchReport` / `matcher.CandidateReport`:

| Feld | Quelle im JSON |
|---|---|
| a) Badge | `decision`, `message` |
| b) Gate | `max_z_winner`, `llr_margin`, `thresholds`, `candidates[0].posterior` |
| c) Bild | `image_path`, `contour`, `touches_border` |
| d) Messwerte | `measured` (= `asdict(Features)`), je Kandidat `height_mm`, `corrected_diameter_mm`, `nominal_size_mm`, `geometry_error_mm` |
| e) Tabelle | `candidates[].features[]` mit `feature`, `measured`, `reference`, `distance`, `sigma_enroll`, `sigma_eff`, `z`, `log_contrib`, `w_eff`, `weighted`; dazu `log_score`, `posterior`, `has_references` |
| f) Chart | dieselben `weighted`-Werte, `thresholds["top_k"]` |
| g) Kontrast | `candidates[0]`, `candidates[1]`, `feature_names` |
| h) Fisher | `fisher_d_norm`, `w_global`, `w_eff`, `alpha`, `feature_names` |

**Kein Panel ruft Pipeline oder Matcher.** Der Nachbau wäre eine reine
Konsumentenschicht wie `analysis.py` — dieselbe Regel, dieselbe Prüfung.

Zwei Einschränkungen:

1. **Das Bild ist kein JSON.** `image_path` zeigt auf eine Datei, die noch da
   sein muss. Das Overlay selbst zeichnet `pipeline.render_report_overlay()`
   (existiert weiter, wird mit der CLI geteilt).
2. **Altbestand.** Reports von vor der Messpfad-Runde tragen kein
   `prefiltered` und kein `lat_p98_mm`; die Ansicht braucht beides nicht,
   aber ein Vorfilter-Feld wäre aus alten Reports nicht füllbar.

---

## 3. Aufwandsschätzung: Qt-Dialog

**Zwei Ausbaustufen, weil sie sich stark unterscheiden.**

### Minimal — nur Tabellen, keine Diagramme: **1,5–2 Personentage**

| Posten | Aufwand | Warum so |
|---|---|---|
| Dialograhmen + Report-Auswahl | 0,5 T | `widgets/dialog_shell.py` und `reporting.load_reports()` gibt es; nötig ist eine Liste über `data/captures/*.json` |
| Badge + Gate-Ampel (b, a) | 0,25 T | `verdict_bar.py` und die Kachel-Optik aus `result_card.py` sind da |
| Kandidatentabelle (e) mit z-Einfärbung | 0,5 T | `QTableWidget`, 10 Spalten, Farbskala über `plotstyle` |
| Top-1-vs-Top-2 (g) + Messwerte (d) | 0,5 T | zwei weitere Tabellen, dieselbe Machart |

Damit hätte man die forensisch wichtigsten Felder: **b, e, g** beantworten
„warum diese Entscheidung" und „warum A statt B".

### Vollständig — mit den drei Diagrammen: **+2–2,5 Tage, also 4–5 gesamt**

| Posten | Aufwand | Warum so |
|---|---|---|
| Log-Beitrags-Chart (f) | 1 T | Qt hat kein Diagramm-Modul. **matplotlib ist bereits Projekt-Abhängigkeit** (`analysis.py`, `plotstyle.py`) — Figure rendern und als `QPixmap` einbetten ist der billigste Weg und hält die Optik konsistent zu den `analyze`-Artefakten. Kosten stecken im Theming (hell/dunkel) und im Neuzeichnen bei Größenänderung |
| Fisher-Panel (h), zwei Diagramme | 0,5 T | dieselbe Machart, sobald der erste Weg steht |
| Bild + Overlay (c) | 0,25 T | `render_report_overlay()` + `qimage.py` vorhanden |
| Tests | 0,75 T | das Projekt testet Qt-Dialoge (`test_ui_dialogs.py`, `test_ui_qt_smoke.py`); der Dialog braucht ein eigenes Modul, weil die Suite UI-Module einzeln laufen lässt |
| Einbindung ins Hauptfenster + Theming | 0,25 T | Tool-Rail hat vier Aktionen; eine fünfte oder ein Menüeintrag, dazu `theme.py`-Durchlauf |

**Der Kostentreiber ist ausschließlich die Diagramm-Darstellung**, nicht die
Logik. Wer nur die Forensik braucht, bekommt sie in der Minimalstufe für gut
ein Drittel des Aufwands.

### Nicht eingerechnet

Eine Wiederbelebung als Web-Ansicht (statisches HTML aus `analyze` heraus,
je Report eine Seite) wäre eine dritte Variante — vermutlich billiger als der
Qt-Dialog, weil `analysis.py` bereits Artefakte schreibt und HTML kein
Theming-Problem hat. Nicht geschätzt, aber vor einem Qt-Dialog erwägenswert.

---

## Verwandt

- [2026-08-01-streamlit-config-tab-schreibt-config-yaml.md](2026-08-01-streamlit-config-tab-schreibt-config-yaml.md)
  — der Fund, der die Entfernung ausgelöst hat.
- README, Abschnitt „Die Streamlit-Test-UI wurde entfernt" — die Tabelle
  aller Ersatzwege.
