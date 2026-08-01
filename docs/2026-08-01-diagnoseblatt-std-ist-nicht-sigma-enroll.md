# Die `Std`-Spalte des Diagnoseblatts ist bei fünf von acht Merkmalen NICHT `sigma_enroll`

**Datum:** 2026-08-01 · **Art:** Befund. Nichts geändert, kein Code angefasst.
**Betrifft:** die Diagnoseschicht (`enrollment_sheet.py`), **nicht** den
Messpfad. Keine Entscheidung, kein Report-JSON, keine Baseline ist betroffen.

> **Praktische Folge, die auffindbar sein muss:** Wer beim Einlernen die Spalte
> `Std` des Diagnoseblatts gegen `matching.sigma_floors` hält, bekommt für
> `delta_e_center`, `delta_e_rim`, `hist_center`, `hist_rim` und `hu_log` ein
> **um Faktor 2–4 zu kleines** Verhältnis. Ein Artikel, der deutlich über dem
> Floor streut, sieht dort sauber aus. Der Fehler zeigt in die gefährliche
> Richtung: er gibt Entwarnung.

---

## Befund

Zwei Stellen rechnen eine Streuung über dieselben Enrollment-Shots, und für die
fünf Prototyp-Merkmale rechnen sie **verschiedene Größen**.

**Der Matcher** ([features.py:349-355](../docodetect/features.py)) —
`_proto_stats`, dessen Ergebnis als `reference_stats.proto_std` gespeichert und
im Matcher zu `sigma_eff = sqrt(sigma_enroll² + sigma_floor²)` wird:

```python
proto = arr.mean(axis=0)                       # Prototyp über ALLE Shots
d = [dist_fn(v, proto.tolist()) for v in vectors]
return proto.tolist(), float(np.sqrt(np.mean(np.square(d))))   # RMS der Distanzen
```

**Das Diagnoseblatt** ([enrollment_sheet.py:340-368](../docodetect/enrollment_sheet.py))
— Feld 4, Spalte `Std`:

```python
others = [arr[j] for j in idx if j != i]
proto = np.mean(others, axis=0).tolist()       # Leave-one-out-Prototyp
d[k] = dist_fn(arr[i].tolist(), proto)
...
std=float(d.std(ddof=1))                       # Streuung UM den Mittelwert
```

Zwei Unterschiede, die sich überlagern:

1. **RMS gegen Standardabweichung.** Der Matcher misst die *Höhe* der Distanzen
   (`sqrt(mean(d²))`, enthält den Mittelwert), das Blatt ihre *Streuung*
   (`std`, der Mittelwert ist herausgerechnet). Prototyp-Distanzen sind
   nicht-negativ und liegen im Normalfall deutlich über null — der Mittelwert
   ist hier der grösste Anteil, und genau den wirft die Standardabweichung weg.
2. **Voller gegen Leave-one-out-Prototyp.** Das Blatt vergleicht jeden Shot
   gegen das Mittel der *übrigen* Shots. Diese Distanzen sind systematisch
   grösser — das wirkt dem ersten Punkt entgegen, hebt ihn aber nicht auf.

Für die drei **skalaren** Merkmale gibt es das Problem nicht: beide Seiten
rechnen `np.std(vals, ddof=1)` ([features.py:375](../docodetect/features.py)
gegen [enrollment_sheet.py:312](../docodetect/enrollment_sheet.py)), die Zahlen
sind identisch.

| Zeile im Blatt | `Std` zeigt | Matcher benutzt | gleich? |
|---|---|---|---|
| Ø (circle) | `std(ddof=1)` der Werte | `std(ddof=1)` der Werte | **ja** |
| circularity | dito | dito | **ja** |
| solidity | dito | dito | **ja** |
| ΔE center | `std` der LOO-Distanzen | **RMS** der Prototyp-Distanzen | **nein** |
| ΔE rim | dito | dito | **nein** |
| hist center | dito | dito | **nein** |
| hist rim | dito | dito | **nein** |
| hu_log | dito | dito | **nein** |

`aspect_ratio`, `area`, `ext_full` und `lat_p98` stehen ebenfalls in der
Tabelle, sind aber keine Scoring-Merkmale — für sie gibt es keinen Floor und
nichts zu vergleichen.

---

## Wie gross ist der Unterschied?

Gemessen mit den echten Funktionen (`features._proto_stats` gegen die
Blatt-Rechnung) über synthetische Shot-Sätze, 13 Shots je Fall:

| Szenario | `sigma_enroll` (Matcher) | `Std` (Blatt) | Faktor |
|---|---|---|---|
| Lab-Vektoren, enge Shots (±0,5) | 0,6885 | 0,2546 | **2,7×** |
| Lab-Vektoren, mittel (±2) | 2,8286 | 1,1238 | **2,5×** |
| Lab-Vektoren, weit (±5) | 6,9990 | 3,1439 | **2,2×** |
| hu_log, eng (MESSER-5-artig) | 0,0074 | 0,0019 | **3,8×** |
| hu_log, weit (MESSER-7-artig) | 0,2364 | 0,0757 | **3,1×** |

**Faktor 2,2–3,8, und immer in dieselbe Richtung: die Blatt-Spalte ist zu
klein.** Das ist kein Rundungsunterschied, und es ist kein Zufall der Beispiele
— es folgt aus Punkt 1 oben: die Standardabweichung lässt genau den Anteil weg,
der bei nicht-negativen Distanzen den Wert ausmacht.

Zur Einordnung an echten Zahlen: die neun Floor-Überschreitungen der
Fixpunkt-Session liegen zwischen **1,23× und 2,21×** Floor
([2026-08-01-enrollment-streuung-bedraenger.md](2026-08-01-enrollment-streuung-bedraenger.md),
Abschnitt 4). Ein Fehler von Faktor 2–4 nach unten drückt **jede einzelne davon
unter den Floor**. Die Prüfung würde also nicht ungenau, sondern wirkungslos.

---

## Warum das jetzt zählt

Zwei laufende Vorhaben würden den Fehler übernehmen:

1. **Der Vorschlag „Spalte `σ/Floor` ins Blatt"**
   ([enrollment-streuung, Abschnitt 7](2026-08-01-enrollment-streuung-bedraenger.md)):
   eine Spalte `σ/Floor`, Zeile rot ab > 1,0, plus eine Kopfzeile „N Merkmale
   über dem Rauschboden" als Ampel für den Übernehmen-Knopf. Baut man das auf
   der vorhandenen `Std`-Spalte, zeigt die Ampel **für fünf von acht Merkmalen
   ein falsches Verhältnis** — und zwar zu grün. Der Vorschlag ist richtig, die
   naheliegende Umsetzung wäre falsch.
2. **Der Ablaufzettel**
   ([2026-07-31-ablauf-enrollment-session.md](2026-07-31-ablauf-enrollment-session.md)):
   dort steht die σ-gegen-Floor-Prüfung seit dem 2026-08-01 als Pflichtschritt.
   Er trennt die beiden Fälle bereits und nennt für die fünf Merkmale die
   Näherung `sqrt(Mittel² + Std²)` aus der Distanzzeile — brauchbar, weil beide
   Momente auf dem Blatt stehen, und konservativ (eher zu gross).

---

## Was zu tun wäre (nicht umgesetzt)

- **Die Diagnoseschicht soll dieselbe Funktion benutzen wie der Messpfad.**
  `enrollment_sheet` importiert aus `features.py` ohnehin schon die privaten
  Geometrie-Primitive; `_proto_stats` liesse sich genauso importieren und je
  Vektor-Merkmal einmal über alle Shots aufrufen. Dann steht auf dem Blatt
  dieselbe Zahl, die später in `reference_stats` landet — und die Spalte
  `σ/Floor` wäre unmittelbar richtig.
- **Die heutige `Std`-Spalte deshalb nicht ersetzen, sondern ergänzen.** Sie
  beantwortet eine andere, ebenfalls nützliche Frage: *streuen die Shots
  ungleichmässig?* Genau darauf beruhen `z_klass`/`z_rob` und die Markierung
  des Extrem-Shots, und die sind korrekt. Zwei Spalten, zwei Fragen.
- **Beim Umsetzen die Spaltenüberschriften benennen**, sonst entsteht derselbe
  Fehler in neuer Form: `Std(Shots)` gegen `σ_enroll`.

Das ist eine Änderung an `enrollment_sheet.py` — reine Konsumentenschicht, kein
Messpfad, aber ein Eingriff in ein Blatt, das im Einlern-Dialog vor dem
DB-Schreiben erscheint. Gehört als eigener, benannter Schritt gemacht.

---

## Was NICHT betroffen ist

- **Der Messpfad.** `matcher.py` liest `reference_stats.proto_std`, also den
  RMS aus `_proto_stats`. Alle `sigma_eff`, `z` und `log_contrib` in den
  Report-JSONs sind richtig gerechnet.
- **Entscheidungen, Korpus, Baseline.** Das Blatt ist Anzeige.
- **Die Spalte `Ref-σ`** desselben Blatts: sie kommt aus
  `stored_stats.proto_std` bzw. `scalar_std` und **ist** das `sigma_enroll` des
  Matchers. Sie ist allerdings erst nach dem Übernehmen gefüllt — vor dem
  DB-Schreiben gibt es für einen frischen Artikel keine `reference_stats`.
- **Die Ausreisser-Erkennung** (`z_klass`, `z_rob`, Extrem-Shot, Feld e): sie
  misst bewusst die Streuung *um* den Mittelwert und ist für ihre Frage richtig.

---

## Verwandte Dokumente

- [2026-08-01-enrollment-streuung-bedraenger.md](2026-08-01-enrollment-streuung-bedraenger.md) —
  warum σ_enroll gegen σ_floor überhaupt geprüft wird, und der Vorschlag, den
  dieser Befund korrigiert.
- [2026-07-31-ablauf-enrollment-session.md](2026-07-31-ablauf-enrollment-session.md) —
  der Ablaufzettel, der die Unterscheidung bereits umsetzt.
- [2026-08-01-analysis-floor-key-befund.md](2026-08-01-analysis-floor-key-befund.md) —
  dieselbe Klasse: eine Nebenschicht rechnet eine Schwellen-nahe Grösse anders
  als der Messpfad, ohne dass irgendwo etwas rot wird.
