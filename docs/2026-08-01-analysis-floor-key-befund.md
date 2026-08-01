# `analysis.py` liest `sigma_floors` mit dem Merkmalsnamen statt über `_FLOOR_KEY`

**Datum:** 2026-08-01 · **Art:** Befund. Nicht gefixt, nichts geändert.
**Betrifft:** Auswertungsschicht (`analysis.py`), **nicht** den Messpfad.
Keine Entscheidung, kein Report-JSON, keine Baseline ist betroffen.

> **Praktische Folge, die auffindbar sein muss:** Die
> `discriminability`-Zahlen des Laufs **`20260801-140818`** sind für die vier
> **Farbmerkmale** unbrauchbar. Wer sie zitiert, zitiert überhöhte Werte.

---

## Befund

[docodetect/analysis.py:1135](../docodetect/analysis.py) in
`_analysis_discriminability`:

```python
floor = float(floors.get(f, 0.0))
```

`f` läuft über `SCALAR_FEATURES + PROTO_FEATURES`, also über die
**Merkmalsnamen**. `matching.sigma_floors` in `config/config.yaml` ist aber nach
**Floor-Gruppe** verschlüsselt — zwei Zonen teilen sich einen Floor:

| Merkmal | Key in `sigma_floors` | `floors.get(f, 0.0)` liefert |
|---|---|---|
| `diameter_mm` | `diameter_mm` | 1.63 ✓ |
| `circularity` | `circularity` | 0.0063 ✓ |
| `solidity` | `solidity` | 0.0043 ✓ |
| `hu_log` | `hu_log` | 0.38 ✓ |
| `delta_e_center` | `delta_e` | **0.0** ✗ |
| `delta_e_rim` | `delta_e` | **0.0** ✗ |
| `hist_center` | `hist_bhattacharyya` | **0.0** ✗ |
| `hist_rim` | `hist_bhattacharyya` | **0.0** ✗ |

Der Matcher macht es richtig: `matcher._FLOOR_KEY`
([docodetect/matcher.py:59-66](../docodetect/matcher.py)) bildet genau diese
Zuordnung ab und wird von `_sigma_floor()` benutzt. `analysis.py` importiert
`_FLOOR_KEY` nicht.

---

## Wirkung

### 1. Sinnlose Zahlen bei Paaren mit 1-Shot-Artikeln

Für einen Artikel mit einer einzigen Referenz ist `proto_std = 0.0`
(`features._proto_stats` gibt bei `len(vectors) < 2` die Streuung 0 zurück). Mit
Floor 0.0 wird in

```python
seff = math.sqrt((max(va, floor) ** 2 + max(vb, floor) ** 2) / 2) or 1e-9
```

der `or 1e-9`-Zweig gezogen. Ergebnis: Trennschärfen in der Größenordnung
**10¹⁰**.

Genau das steht in `discriminability.csv` des Laufs `20260801-140818` — die
obersten Zeilen:

```
GABEL-3 / GABEL-7,1.055,1.032,3.93,21884117025.825,...
GABEL-3 / LOEFFEL-4,5.571,25.206,6.837,19055769546.256,...
```

Diese Werte sind numerisch bedeutungslos. Sie bestimmen zusätzlich **Sortierung
und Farbskala** des `discriminability.png`: die Matrix ist nach dem
Zeilenmaximum sortiert, also stehen die Artefakt-Zeilen oben und die real
schwierigen Paare unten.

### 2. Auch bei voll eingelernten Artikeln überhöht

Bei den 15 Artikeln mit 13 Shots greift der `1e-9`-Zweig nicht (`proto_std > 0`),
aber der fehlende Floor bleibt. Nachgerechnet über die 105 Paare dieser
15 Artikel, Median der Trennschärfe:

| Merkmal | wie in `analysis.py` | mit `_FLOOR_KEY` | Faktor |
|---|---|---|---|
| `delta_e_rim` | 3,99 | 1,72 | **2,3×** |
| `hist_rim` | 2,76 | 1,48 | **1,9×** |
| `delta_e_center` | 1,92 | 1,26 | 1,5× |
| `hist_center` | 2,29 | 1,72 | 1,3× |
| `diameter_mm` | 12,88 | 12,88 | 1,0× |
| `circularity` | 7,86 | 7,86 | 1,0× |
| `solidity` | 25,87 | 25,87 | 1,0× |
| `hu_log` | 1,81 | 1,81 | 1,0× |

Die vier Farbmerkmale erscheinen um 1,3–2,3× trennschärfer als sie sind. Das ist
die Richtung, die am meisten stört: Farbe ist zwischen zwei polierten
Stahl-Bestecken derselben Serie ohnehin das schwächste Signal (korrigierte
Mediane 1,26–1,72 σ), und der Fehler lässt sie besser aussehen.

---

## Was NICHT betroffen ist

- **Der Messpfad.** `matcher.py` nutzt `_FLOOR_KEY` korrekt; alle `sigma_eff`,
  `z`, `log_contrib` in den Report-JSONs sind richtig gerechnet.
- **Entscheidungen.** ACCEPT/AMBIGUOUS/REJECT hängen nicht an `analysis.py`.
- **Korpus und Baseline.** `corpus/runner.py` importiert `analysis.py` nicht.
- Alle übrigen Abschnitte von `analyze` — der Fehler sitzt allein in
  `_analysis_discriminability`.

---

## Status

Nicht gefixt. `analysis.py` ist reine Konsumentenschicht; ein Fix ändert weder
Messung noch Entscheidung, erzeugt aber andere Zahlen in allen künftigen
`discriminability`-Artefakten. Er gehört als eigener, benannter Schritt gemacht —
nicht beiläufig in einer anderen Runde.

Beim Fix mit zu bedenken:

1. `_FLOOR_KEY` aus `matcher.py` importieren statt die Zuordnung zu duplizieren.
2. Der `or 1e-9`-Zweig bleibt auch nach dem Fix erreichbar, wenn ein Merkmal
   ohne Floor-Eintrag dazukommt. Ein Paar mit `proto_std = 0` auf beiden Seiten
   ist keine sinnvolle Vergleichsseite — sauberer wäre `np.nan` (die Matrix
   maskiert NaN bereits über `cmap.set_bad`) als eine Zahl mit 10 Stellen.
3. Bereits geschriebene Läufe werden nicht rückwirkend korrigiert; für
   `20260801-140818` gilt dieser Befund.
