# Block D: `sigma_eff` als Stellgröße — zwei Varianten halten, fünf nicht

**Datum:** 2026-08-01 · **Art:** Negativbefund mit Entscheidung, plus zwei
haltbare Varianten, die nicht gebaut werden.
**Ergebnis: keine Änderung.** Kein Produktivcode, keine Config.
**Datenbasis:** 169 Leave-one-out-Fälle über 13 echte Artikel,
`scripts/analyse_sigma_eff.py`, `scripts/analyse_gewichte_wprofil.py`.

Anders als die Blöcke davor greift D nicht die Aggregation, die Gewichte oder
die Schwellen an, sondern die Konstruktion von `sigma_eff` selbst. Auslöser ist
der Mechanik-Befund
([2026-08-01-enrollment-streuung-bedraenger.md](2026-08-01-enrollment-streuung-bedraenger.md)):
ein Kandidat mit weiter Enrollment-Verteilung ist strukturell schwer
auszuschließen und drückt die Margin seiner Nachbarn.

---

## Übersicht

| Variante | top1 | ACCEPT | **k_safe** | FA | Urteil |
|---|---|---|---|---|---|
| Baseline | 168/169 | 41 | 165 | 0 | — |
| D0 robust Median/MAD | 163/169 | 40 | **154** | 0 | verworfen |
| **D1 Deckel 1,5× Median** | **169/169** | 42 | **168** | 0 | **hält** |
| **D1 Deckel 2× Median** | **169/169** | 41 | **168** | 0 | **hält** |
| D2 symmetrisiert (median) | 164/169 | 47 | 161 | 0 | verworfen |
| **D3 cap 1× Floor** | 168/169 | 41 | **166** | 0 | **hält** |
| D3 cap 0,5× Floor | 165/169 | 46 | 160 | 0 | verworfen |
| D4 Merkmal abschalten (1×) | 166/169 | 41 | **130** | 0 | verworfen |
| D5 D3(1×) + B2 | 165/169 | 66 | 162 | 0 | verworfen |

Harte Bedingung war: `false_accept = 0` **und** `k_safe` darf nicht fallen.
`false_accept` bleibt überall 0 — entschieden hat durchweg `k_safe`.

---

## D0 — robuste σ-Schätzung: verworfen, und die Erwartung trifft nicht zu

Median statt Mittelwert, MAD·1,4826 statt Standardabweichung. Für die fünf
Prototyp-Merkmale ist der robuste Gegenpart nicht der MAD der Distanzen (der
misst Streuung *um* den Median, nicht die Skala der Distanz), sondern
1,4826·median(d) — unter dem gefalteten Normalmodell, das die Likelihood für
diese Merkmale ohnehin unterstellt, gilt median(d) = 0,6745·σ.

**Erwartet:** die sieben ausreißergetriebenen Floor-Überschreitungen verschwinden,
die sechs gleichmäßig breiten bleiben. **Beides falsch.**

| Artikel | Merkmal | klassisch | robust | vorheriges Urteil |
|---|---|---|---|---|
| MESSER-7 | hu_log | 2,21 | **0,94** | „gleichmäßig breit" → weg |
| GABEL-10 | hu_log | 1,51 | **0,13** | „gleichmäßig breit" → weg |
| LOEFFEL-1 | hu_log | 1,54 | **0,19** | „gleichmäßig breit" → weg |
| GABEL-9 | delta_e_center | 1,91 | **2,11** | „gleichmäßig breit" → schlimmer |

MAD entschärft **9 von 13** Überschreitungen — darunter fünf der sechs
„gleichmäßig breiten" — und **erzeugt 10 neue** (sechsmal `circularity`).
Netto 13 → 14.

### Die Schwerschwanz-Korrektur

**Das korrigiert die Jackknife-Deutung aus dem Enrollment-Dokument.** Jackknife
(σ ohne die ein bzw. zwei äußersten Shots) und MAD widersprechen sich — und der
Widerspruch ist selbst der Befund:

Bei `hu_log` ist die Distanzverteilung **schwerschwänzig**. Der Spann wird von
etwa drei bis fünf Shots getragen — nicht von einem oder zwei (dann hülfe der
Jackknife) und nicht gleichmäßig (dann hülfe der Median nicht). **Die
Zweiteilung „Ausreißer oder Artikeleigenschaft" war zu grob.**

Praktisch heißt das: Weder Wiederholen noch ein robuster Schätzer löst diese
Fälle zuverlässig. Sie brauchen eine Behandlung auf der σ-Seite — was D1/D3
tun.

### Der Preis des robusten Schätzers

σ_robust / σ_klassisch über 97 (Artikel × Merkmal) ohne bekannten Ausreißer:

| Median | p10 | p90 | min | max | IQR/Median |
|---|---|---|---|---|---|
| **1,122** | 0,671 | 1,426 | 0,088 | 1,585 | **0,357** |

Bei n = 13 ist der MAD stark verrauscht und um 12 % nach oben verzerrt. Artikel
**ohne** Ausreißer bekommen dadurch ein schlechteres σ — genau der befürchtete
Effekt, und er ist groß.

Scoring: top1 168 → **163**, k_safe 165 → **154**, REJECT 1 → 3. Das Einzige,
was D0 erreicht: die Sonden-Asymmetrie MESSER-5/MESSER-7 fällt von 6,5× auf
**1,0×** (0,398 gegen 0,405) — perfekte Symmetrie, teuer erkauft.

### Korpus-Wirkung (D0 ist der einzige Messpfad-Eingriff in Block D)

`features.py` steht in `CODE_DATEIEN`
([corpus/runner.py](../docodetect/corpus/runner.py)) → der `code_fingerprint`
ändert sich, `--changed-only` rechnet alles neu.

Die **Ergebnisse** blieben unverändert: die Korpus-Bundles frieren
`db.sqlite3` mit fertig gerechneten `reference_stats` ein, und `stats_for()`
liest nur ([database.py:300](../docodetect/database.py)). Ausnahme:
`init_schema` ruft `recompute_all_stats` — wer ein Bundle neu aufsetzt, bekäme
die neuen Werte und damit andere Tier-2-Entscheidungen.

---

## D1 und D3 — halten, wirken aufs Ranking statt auf ACCEPT

**D1** deckelt σ_enroll bei einem Vielfachen des Medians über alle Artikel im
selben Merkmal, **D3** bei einem Vielfachen des `sigma_floor`.

| Variante | top1 | ACCEPT | k_safe | Überlappung | berührte Überschreitungen |
|---|---|---|---|---|---|
| D1 1,5× Median | **169/169** | 42 | **168** | 41/42 (98 %) | 11 von 13 (alle 9 Artikel) |
| D1 2× Median | **169/169** | 41 | **168** | 41/41 (100 %) | 5 von 13 |
| D1 3× / 5× Median | 168/169 | 41 | 165 | 100 % | 1 bzw. 0 — wirkungslos |
| D3 cap 1× Floor | 168/169 | 41 | **166** | 41/41 (100 %) | 13 von 13 |
| D3 cap 2× Floor | 168/169 | 41 | 165 | 100 % | 1 (nur MESSER-7) |

**Das ist eine andere Art von Ergebnis als alles bisher.** Die Gegenprobe zeigt
98–100 % Überlappung — die ACCEPT-Menge ist praktisch dieselbe. Der Gewinn liegt
nicht dort, sondern im **Ranking**: top1 168 → 169 und k_safe 165 → 168. D1
repariert den einen Rangfehler des Bestands (GABEL-12 shot 12) und macht die
Margin-Sortierung robuster.

### Der Preis des Deckels

Ein Deckel behandelt die Referenz als präziser, als sie gemessen wurde. Das hebt
z für **alle** Messungen dieses Artikels, auch die richtigen. Gemessen an max|z|
des Siegers, nur bei korrektem Top-1:

| Variante | Median | p90 | p99 | max | > 3,5 | gestiegen | Median-Anstieg |
|---|---|---|---|---|---|---|---|
| Baseline | 0,89 | 1,40 | 2,98 | 4,60 | 1 | — | — |
| D1 1,5× Median | 0,95 | 1,54 | 3,04 | 4,60 | **1** | 67 | 0,000 |
| D3 cap 1× Floor | 0,95 | 1,71 | 2,99 | 4,60 | **1** | 75 | 0,000 |
| D3 cap 0,5× Floor | 1,11 | 2,05 | 3,51 | 4,84 | **2** | 158 | 0,207 |
| D2 sym median | 1,10 | 2,21 | 3,29 | 4,35 | 2 | 147 | 0,209 |

Bei D1 1,5× und D3 1× ist der Preis vernachlässigbar: p99 steigt um 0,06, die
Zahl der Fälle über dem Gate bleibt 1. Erst wenn der Deckel scharf greift
(D3 0,5×), kostet er — 158 Fälle steigen, ein zusätzlicher Fall über dem Gate.

**Entscheidung: nicht gebaut.** Der Gewinn ist ein Rangfehler und drei k_safe-
Fälle bei n ≈ 13 Artikeln. Aber D1/D3 sind **haltbar** und stehen neben B2 und
D8 auf der Wiederaufnahme-Liste.

---

## D2 und D4 — verworfen

**D2 (symmetrisiertes σ):** alle Kandidaten eines Sets teilen dasselbe σ je
Merkmal (Median, gepoolt oder Maximum). Damit hängt der Abstand nicht mehr davon
ab, wessen Referenz breiter ist — die Sonden-Asymmetrie fällt auf 1,1–2,3×.

**Was dabei verloren geht:** Das ist **keine gültige Likelihood mehr.** Der
Nenner von z stammt dann nicht mehr aus dem Modell des jeweiligen Kandidaten,
sondern aus einer Eigenschaft des zufällig zusammengesetzten Kandidatensets.
Derselbe Kandidat bekommt in verschiedenen Sets verschiedene σ; `log_score` ist
nicht mehr als Log-Wahrscheinlichkeit interpretierbar, `max|z|` nicht mehr als
Abweichung in Einheiten der eigenen Streuung. Das Gate `max_z_accept = 3.5`
verliert damit seine Bedeutung als absolutes Kriterium.

Numerisch: top1 164–167, k_safe 153–162 — durchweg unter der Baseline.

**D4 (Merkmal je Kandidat abschalten):** überschreitet σ_enroll den Floor um
mehr als k, geht das Merkmal für **diesen** Kandidaten gar nicht ein.

| Variante | Merkmale je Kandidat | top1 | **k_safe** |
|---|---|---|---|
| D4 aus ab 1× Floor | **5–8** | 166/169 | **130** |
| D4 aus ab 2× Floor | 7–8 | 167/169 | 160 |

**Das bestätigt die Vergleichbarkeitssorge empirisch.** `log_contrib = −0,5 z²`
ist immer ≤ 0; ein Kandidat mit weniger Merkmalen sammelt weniger Strafpunkte
und wird dadurch bevorzugt — genau der Mechanismus, der für den
Produktivbestand bei einer unnormierten Summe vorhergesagt wurde
([2026-08-01-scoring-simulation-widerlegte-thesen.md](2026-08-01-scoring-simulation-widerlegte-thesen.md),
Abschnitt 2). k_safe bricht auf 130 ein. **Sauber lösen lässt es sich nicht:**
jede Renormierung, die die Vergleichbarkeit wiederherstellt, hebt die Wirkung
der Abschaltung wieder auf.

Zusätzlich macht D4 die Sonden-Asymmetrie **schlechter** (7,8× bzw. 10,2×
gegen 6,5× in der Baseline).

---

## D5 — Kombinationen kippen, auch ohne false_accept

| Kombination | ACCEPT | k_safe | top1 |
|---|---|---|---|
| B2 allein (aus Block B) | 60 | **167** | 168/169 |
| D3(1×) allein | 41 | **166** | 168/169 |
| **D3(1×) + B2** | 66 | **162** | 165/169 |
| D0 + B2 | 62 | **101** | 160/169 |

Beide Bestandteile sind einzeln unschädlich, kombiniert fällt k_safe unter die
Baseline. Kein false_accept, aber die harte Bedingung ist verletzt. Das ist —
nach `alpha=32 + S2` und `sum_unweighted + tol 4,0` — der dritte dokumentierte
Kombinationseffekt dieser Art.

---

## D7 — w(s) mit hohem Gewicht: die Lücke im Negativbefund

Der w(s)-Negativbefund prüfte Gewichte bis 0,25. Nachgerechnet bei floor 0,50:

| Gewicht | Ø-Anteil | top1 | ACCEPT | k_safe | Überlappung |
|---|---|---|---|---|---|
| 0,10 | 0,455 | 169/169 | 58 | 168 | 50/58 |
| 0,25 | 0,400 | 169/169 | 92 | 168 | 64/92 |
| 0,60 | 0,312 | 169/169 | 113 | 168 | 89/114 |
| 1,00 | 0,250 | 169/169 | 122 | 168 | 97/123 |

**Die Erwartung, ein hohes w(s)-Gewicht ziehe `diameter_mm` herunter und schade
dem Ranking, bestätigt sich nicht:** top1 bleibt 169/169 und k_safe 168 bei
jedem Gewicht, auch wenn Ø von 0,50 auf 0,25 Anteil fällt. Der Gewinn sättigt
(58 → 92 → 101 → 113 → 122), kehrt sich aber nicht um.

Floor-Sweep als Kontrolle:

| Gewicht | floor 0,50 | floor 1,00 | floor 1,50 |
|---|---|---|---|
| 0,25 | 92 | 46 | **41 = Baseline** |
| 0,60 | 113 | **72** | **41 = Baseline** |

Ab floor 1,50 ist der Gewinn vollständig weg. Bei floor 1,00 und Gewicht 0,60
bleibt er — und dieser Bereich wurde im Negativbefund nie gerechnet. Der
geschätzte Betriebs-Floor (0,5–0,9 mm) liegt vollständig darin.

Vollständige Einordnung und die Kontrolle, dass Leave-one-out und die
Testaufnahme-Konstruktion **nicht** auseinanderlaufen:
[2026-08-01-wprofil-negativbefund.md](2026-08-01-wprofil-negativbefund.md),
Nachtrag 11.

---

## Einschränkungen — für Block D besonders

- **Die Fixpunkt-Referenzen haben keine Positionsstreuung.** Im Betrieb wäre
  σ_enroll bei allen Artikeln größer und **möglicherweise gleichmäßiger**. Dann
  hätten Deckel und Symmetrisierung weniger zu tun — und die hier gemessene
  Streuungs-Asymmetrie, an der der ganze Block hängt, könnte gar nicht bestehen
  bleiben. Das begrenzt die Übertragbarkeit von D erheblich.
- n ≈ 13 Artikel, 169 nicht-unabhängige Fälle, Leave-one-out statt unabhängiger
  Testaufnahmen.
- Der Gewinn von D1 (ein Rangfehler, drei k_safe-Fälle) liegt in derselben
  Größenordnung wie das Rauschen dieser Basis.

---

## Verwandte Dokumente

- [2026-08-01-enrollment-streuung-bedraenger.md](2026-08-01-enrollment-streuung-bedraenger.md) — der Mechanik-Befund, der Block D ausgelöst hat.
- [2026-08-01-blockD6-gewichtsschema.md](2026-08-01-blockD6-gewichtsschema.md) — D6, eigenes Dokument.
- [2026-08-01-blockD8-tiebreaker.md](2026-08-01-blockD8-tiebreaker.md) — D8.
- [2026-08-01-abschluss-scoring-runde.md](2026-08-01-abschluss-scoring-runde.md) — Gesamtbilanz der Runde.
