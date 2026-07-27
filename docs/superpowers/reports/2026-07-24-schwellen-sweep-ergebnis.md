# Schwellen-Sweep — Betriebskurven (Block 2, Ergebnisdokument)

Stand 2026-07-24 · **report-only** · Branch `feature/schwellen-sweep` ·
Arbeitsplan `docs/arbeitsplan-2026-07-24.md`. Läuft auf Windows als
Rechenmaschine; Baseline bleibt Mac.

> **GRUNDSATZ:** Der Sweep erzeugt Kurven, er ändert **nichts**. `config.yaml`,
> `baseline.json`, `accepted_deltas`, alle Schwellen bleiben unangetastet
> (`min_llr_margin` 2,0 / `max_z_accept` 3,5 / `diameter_tolerance_mm` 6,0). Eine
> Schwellen-**Entscheidung** ist ausdrücklich NICHT Teil dieses Auftrags: der
> Korpus ist **besteck-only**, phase-a/b tragen einen Kalibrier-Offset (Je-Session-
> Varianz, s. HS-Drift-Dokument §10), n=104 ist eine kleine Stichprobe.

---

## 0. Was an einem Satz hängen bleibt

Die beiden Gates schützen **verschiedene** Fehler: `min_llr_margin`=2,0 sitzt
**0,0265 über** dem ersten false-accept (LOEFFEL-3 als LOEFFEL-4, ein
Poliertstahl-Zwilling) und schützt gegen **Zwillings-Verwechslung**;
`max_z_accept`=3,5 hat gegen false-accepts **unendlich Luft** in diesem Korpus,
erzwingt aber den **Rückenlage-REJECT**. `accuracy_top1` (95/104) ist
schwellen-invariant — keine Schwelle verbessert die Trefferquote, sie verschiebt
nur die Partition Accept/Ambiguous/Reject.

## 1. Mechanismus + Äquivalenz-Nachweis (Selbstvalidierung)

Die Entscheidung ist eine **reine Funktion gespeicherter Werte** (`matcher.match`
Z. 341–365): `max_z_winner`, `llr_margin`, `candidates[0].has_references`.
Kandidatenmenge und Ranking hängen **nicht** an den Gates → die Neu-Ableitung bei
anderen `(max_z_accept, min_llr_margin)` ist **exakt**, ohne Segmentierung/
Features/Matcher neu zu rechnen (Millisekunden je Rasterpunkt).

**Input = `runs/win-postfix-tier2/replay/` (104 Reports)** — die Reports, die die
Baseline DEFINIEREN. **Nicht** die Enrollment-Ära-Goldens: die liefern
**86/97/43** (falsche Grundlage, weil die Baseline der Post-Sync-Replay gegen die
aktuellen Bündel-DBs ist). Der **Pinning-Test** im Werkzeug sichert beides ab: er
schlägt fehl, wenn die Quelle bei den Produktionsschwellen nicht **exakt** die
Baseline reproduziert (0/104 Abweichungen; 95/101/44/0/83, decisions 56/44/4 —
über die Produktions-`tier2_quotas()`, kein Reimplementat). So kann kein späterer
Lauf still auf die falschen Reports zeigen.

## 2. Achsen

- **`max_z_accept`**: 2,0 … 6,0, Schritt 0,1 (Betrieb 3,5).
- **`min_llr_margin`**: 0,0 … 5,0, Schritt 0,1 (Betrieb 2,0). Um den Knick 0,01-
  nachverfeinert.
- 2D-Raster (2091 Punkte) + zwei 1D-Schnitte. Drift-neutral: die Windows-
  Plattform-Drift (≤6,8e-3 auf max_z, ≤1,5e-3 auf llr) ist «1 Rasterschritt.
- **`diameter_tolerance_mm` — GRENZE, nicht gesweept.** Aus Reports nicht
  ableitbar: **Lockern** braucht Kandidaten, die nie gescort wurden; **Straffen**
  ändert die adaptiven **Fisher-Gewichte** (hängen an der Kandidatenmenge) →
  Ranking/Scores wären neu, nicht abgeleitet. Das ist **Neurechnung**, nicht
  Ableitung, und würde die Exaktheitsgarantie des Werkzeugs aufweichen. Der
  **Matcher-Replay-Pfad** (aus gespeicherten Features + DB, ohne Segmentierung)
  ist ein **eigener künftiger Auftrag** — und die Voraussetzung für die
  **artikelweise Toleranz** aus der Sync-Roadmap (Stammdaten-Doc §7.2).

## 3. Was der Sweep NICHT kann

`accuracy_top1` (95/104) und `accuracy_top3` (101/104) sind **schwellen-invariant**
— sie messen das **Ranking**, das kein Gate berührt. Der Sweep verschiebt **nur**
die Partition Accept/Ambiguous/Reject. Konsequenz für jede spätere Präsentation
der Kurven: **keine Schwelle hebt die Trefferquote**; die Kurven sind eine
Aussage über *Automatisierungsgrad vs. Fehlbuchungsrisiko*, nicht über *Genauigkeit*.

## 4. Ergebnisse

**Z-Achse (max_z_accept lockern, M=2,0 fix): 0 false-accepts bei JEDEM Z.** Alle
top1-falschen Reports haben `llr` < 2,0 → das z-Gate allein macht nie eine
Fehlbuchung. Gelockert treten **3 rejects** als Accept ein — **alle top1-korrekt**
— bei Z = 3,81 (LOEFFEL-9), 4,25, 4,49. **Aber Z ≥ 4,25 hebt den
Rückenlage-Wächter `5bf6b431` auf** (GABEL-1 auf dem Rücken, OOD-Pose, label-
korrekt aber nicht buchbar). Max Accepts bei 0 false: **47/104** bei Z=4,5.

**M-Achse (min_llr_margin lockern, Z=3,5 fix): der Knick.** Erster false-accept bei
**min_llr_margin = 1,9735** — 0,01-Nachverfeinerung:

| min_llr_margin | Accepts | false-accepts |
|---|---|---|
| … 1,97 | 45 | **1** |
| 1,98 … 2,01 | 44 | 0 |
| 2,02 … | 43 | 0 |

Der Betriebspunkt **2,0 sitzt 0,0265 über dem Knick** = **18× die größte
beobachtete llr-Drift** (1,5e-3) → drift-sicher, aber der **Design-Abstand** zur
ersten Fehlbuchung ist bewusst knapp: die 2,0 ist auf genau diesen Zwilling
kalibriert. (Der engste *korrekte* Accept liegt bei llr ≈ 2,02 direkt darüber —
das Gate liegt in einer engen Zone zwischen richtig und falsch.)

**Betriebspunkt (3,5/2,0):** 44/104 Accepts (42,3 %, Wilson 33,3–51,9 %), **0/44
false**, 4 reject, 56 ambiguous.

## 5. Drei benannte Befunde (die Zwei-Gate-Architektur, empirisch)

**B1 — Gate-Asymmetrie: die zwei Gates schützen verschiedene Fehlerklassen.**
`max_z_accept` schützt gegen **Fremdobjekt/Pose** — über die *ganze* Z-Achse
(2,0 … 6,0) bleibt `false_accept` = **0/44**; kein z-Wert allein erzeugt je eine
Fehlbuchung. `min_llr_margin` schützt gegen **Verwechslung** — es ist der
**einzige** Kanal, über den in diesem Korpus überhaupt ein false-accept entsteht
(unterhalb 1,98, s. B2). Das ist der **empirische Beleg der
Zwei-Gate-Architektur**: nicht Redundanz, sondern zwei disjunkte Schutzaufgaben.

**B2 — `min_llr_margin`=2,0: bestätigt konservativ, aber KEIN Spielraum nach
unten.** Der Betriebspunkt 2,0 sitzt **0,0265 über** dem ersten false-accept
(Knick 1,9735) = **18× die größte beobachtete Windows-llr-Drift** (1,5e-3) →
drift-sicher. Zwischen „0 false" und „1 false" liegt aber **ein einziger**
polierter Löffel-Zwilling (§6). Lesart: **die Kurve bestätigt 2,0 als
konservativ** (0 false belegt) — sie liefert **keinen Spielraum nach unten**.
Jede künftige Diskussion über ein *Lockern* von `min_llr_margin` muss **zuerst die
Hue-Instabilität bei poliertem Besteck adressieren** (H-basierte Farbmerkmale
schwach bei achromatischem Material — Merkmals-Befund der HS-Drift-Attribution,
`docs/superpowers/reports/2026-07-24-hs-drift-attribution-ergebnis.md`). Ohne
diesen Merkmals-Fix ist Lockern nicht datenbelegt.

**B3 — `max_z_accept` ≤ ~4,25 ist an eine Betriebsregel gekoppelt.** Lockern des
z-Gates gewinnt 3 *korrekte* Accepts (Z 3,81/4,25/4,49), **aber Z ≥ 4,25 hebt den
Rückenlage-Wächter `5bf6b431` auf** (GABEL-1 auf dem Rücken: label-korrekt, aber
OOD-Pose, nicht buchbar). Damit hängt die **Pose-Sicherheit** — die
Produktentscheidung vom 23.07. „**Vorderseite oben**" — direkt an
`max_z_accept` ≤ ~4,25. Das verknüpft die Schwelle mit einer **Betriebsregel**,
nicht nur mit einer Messgröße, und gehört als solche dokumentiert: ein Lockern
von `max_z_accept` ist keine reine Genauigkeits-Abwägung, es kippt eine
Pose-Zusage.

## 6. Der Knick im Einzelnen (Erkenntnis, nicht nur Zahl)

`4587d1a8` · Bild `phase-b/images/LOEFFEL-3/4587d1a8.png` · wahres Label
**LOEFFEL-3**, akzeptiert würde **LOEFFEL-4** · `max_z` 1,506 · `llr` 1,9735.
Das Bild (angesehen): ein **polierter Edelstahl-Esslöffel**. LOEFFEL-3 und
LOEFFEL-4 sind ein **Größen-Zwilling** (~186 mm, der LOEFFEL-4-Sync-Zielwert),
und beide sind **achromatisch** — genau die **Hue-Instabilität aus der
HS-Drift-Attribution** (poliertes Besteck, H-basierte Farbmerkmale schwach). Die
Geometrie trennt sie nicht (Zwilling), die Farbe kann es materialbedingt nicht →
der `llr`-Vorsprung bleibt bei 1,97, knapp unter 2,0. **Das Margin-Gate 2,0 tut
also exakt seine Aufgabe: es verweigert die Auto-Buchung eines nicht sicher
trennbaren Löffel-Zwillings.** Kein Fehler der Kurve — eine bewusst gesetzte Kante.

## 7. Messer-Vierlinge — datengetriebene Herleitung + mit/ohne

Von 19 MESSER-tier2-Bildern bilden **MESSER-2, MESSER-5, MESSER-6, MESSER-7** einen
**mutuell verwechselten Cluster**: ihre top-3 liegen ausnahmslos innerhalb des
Clusters, `llr` winzig (0,03–1,2) → **alle ambiguous, nie Accept**. Das sind die
**12 physisch nicht trennbaren Bilder** (3 je Artikel). MESSER-1 und MESSER-11
sind sauber getrennt (`llr` 11–14, Accept) → **keine** Vierlinge.

| | mit Vierlingen (n=104) | ohne Vierlinge (n=92) |
|---|---|---|
| auto_accept @ (3,5/2,0) | 44/104 = **42,3 %** (33,3–51,9) | 44/92 = **47,8 %** (37,9–57,9) |
| false_accept | 0/44 | 0/44 |
| accuracy_top1 | 95/104 | 84/92 (Rate ~unverändert) |
| ambiguous | 56 | 44 |

Die 12 Bilder (je 3 aus **MESSER-2, MESSER-5, MESSER-6, MESSER-7**) sind reines
Nenner-Gewicht (akzeptieren nie, korrektes Top-1). **Würden sie auf
Stammdaten-Ebene als Alias-Gruppe gelöst, stiege der erreichbare
Automatisierungsgrad um ~5,5 Prozentpunkte — ohne jede Schwellen-Änderung.** Das
ist die operativ relevantere Antwort als jede Gate-Verschiebung.

**Das ist aber keine technische Empfehlung, sondern eine Frage an DO&CO:**
*Müssen MESSER-2/5/6/7 überhaupt getrennt gebucht werden?* Sind es aus
Buchungssicht dasselbe Artikel (nur unterschiedliche Stammdatennummern), löst eine
Alias-Gruppe das Problem sauber und ohne Risiko. Müssen sie getrennt bleiben,
dann sind sie mit der aktuellen Merkmalsbasis (Geometrie + Farbe) **physisch nicht
auto-trennbar** — dann ist ambiguous das korrekte Verhalten und kein Defekt. Die
Entscheidung ist eine Prozess-/Stammdatenfrage, keine Schwellenfrage.

## 8. Ehrliche Grenzen des Sweeps

- **Besteck-only:** der Korpus enthält kein Porzellan/Glas; die Kurven gelten für
  die Besteck-Mischung, nicht für den Betrieb.
- **Kalibrier-Offset** in phase-a/b (Je-Session-Varianz, HS-Drift-Doc §10) — die
  z-Werte tragen einen Ära-Offset, den ein Betriebspunkt nicht kennt.
- **n=104, kleine Stichprobe:** alle Raten mit **Wilson-Intervall** (oben je
  Zahl). false_accept 0/44 heißt Wilson-Obergrenze **8,0 %** — „0 gesehen" ist
  nicht „0 Risiko".
- **Keine Schwellen-Entscheidung** — Kurven, keine Wahl.

## 9. Artefakte

`scripts/schwellen_sweep.py` (report-only, Pinning-Test) ·
`tests/test_schwellen_sweep.py` (Always-on: pinnt `rederive()` gegen
synthetische MatchReports bei 3,5/2,0 + Off-Schwellen — korpus-unabhängig) ·
`reports/archive/schwellen-sweep-2026-07-24/`: `sweep_grid.csv` (4182 Punkte,
mit/ohne), `knee.json` (Knick + 8 top1-falsche Fälle + Z-Gewinne + 0,01-Verfeinerung),
`m_slice.png`, `z_slice.png`, `betriebskurve.png`. Baseline/Config/Schwellen
unverändert.
