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

> **Erledigt am 2026-08-01** (Branch `feature/cli-und-analyse-fixes`). Beide
> unten genannten Punkte umgesetzt: `_FLOOR_KEY` wird aus `matcher.py`
> importiert, der `or 1e-9`-Zweig ist durch `np.nan` ersetzt. Zwei Tests in
> `tests/test_analysis.py` (`test_discriminability_nutzt_die_floor_gruppe_…`,
> `…_ohne_floor_und_ohne_streuung_ist_leer_statt_1e10`) fallen ohne den Fix um.
>
> Der Lauf `20260801-140818` wurde **neu gerechnet nach
> `20260801-140818-floorfix`** (danebengelegt, die alte Fassung bleibt als
> Beleg stehen). Ergebnis über die 79 normal auswertbaren Paare:
> `delta_e_center` 3,82 → 1,25 · `delta_e_rim` 4,58 → 1,59 · `hist_center`
> 3,91 → 1,78 · `hist_rim` 3,81 → 1,48; die vier Formmerkmale bitgleich.
> Die korrigierten Mediane reproduzieren die oben unabhängig nachgerechneten
> Werte.
>
> ### Die eigentliche Auswirkung: die Matrix zeigte die falschen Paare
>
> Wichtiger als die Faktoren ist, **was ein Mensch auf dem
> `discriminability.png` gesehen hat**. Die Matrix ist nach dem Zeilenmaximum
> sortiert. Oben standen deshalb die Artefaktzeilen der 1-Shot-Artikel:
>
> | Rang | alt (fehlerhaft) | neu (korrigiert) |
> |---|---|---|
> | 1 | `GABEL-3 / GABEL-7` (max 2,2·10¹⁰) | `LOEFFEL-8 / MESSER-1` (87,0) |
> | 2 | `GABEL-3 / LOEFFEL-4` (1,9·10¹⁰) | `GABEL-1 / MESSER-11` (72,4) |
> | 3 | `GABEL-3 / GABEL-8` (1,6·10¹⁰) | `LOEFFEL-8 / MESSER-10` (72,3) |
>
> Und **unten**, wo die schwierigen Paare stehen sollen, standen sie nicht.
> Erst nach dem Fix erscheinen dort die drei Paare, um die es in dieser
> Analyse-Runde tatsächlich ging:
>
> | Paar | max (korrigiert) |
> |---|---|
> | `MESSER-5 / MESSER-7` | **1,43** |
> | `GABEL-10 / GABEL-14` | **1,83** |
> | `LOEFFEL-2 / LOEFFEL-5` | **1,93** |
>
> Sie waren unter den Artefakten begraben. Wer die Matrix zur Orientierung
> angeschaut hat, hat die falschen Paare gesehen — nicht bloss überhöhte
> Zahlen bei den richtigen. Das ist der Schaden, den der Fehler angerichtet
> hat, und der Grund, warum ein Sortierkriterium nie auf ungeprüften
> Extremwerten beruhen darf.
>
> ### Geprüft: welche Aussagen der Runde beruhten darauf?
>
> Vollständig durchgesehen (2026-08-01), Ergebnis: **eine**.
>
> - **Alle Analyse-Skripte sind sauber.** `scripts/simulate_scoring.py`,
>   `analyse_tiebreaker.py`, `analyse_sigma_eff.py`,
>   `analyse_merkmalskorrelation.py` importieren `matcher._sigma_floor` und
>   rechnen damit über `_FLOOR_KEY`. Kein Skript importiert `analysis.py`
>   oder liest `discriminability.csv`.
> - **Die Trennschärfe-Tabelle in
>   [wprofil-negativbefund](2026-08-01-wprofil-negativbefund.md) Abschnitt 2
>   ist korrekt** (1,26–1,72 für die Farbmerkmale) — unabhängig gerechnet,
>   nicht aus der Matrix übernommen. `duplikatpruefung-methode.md` zitiert
>   diese Tabelle, nicht die Matrix.
> - **Betroffen: [fixpunkt-test-scoring.md](2026-08-01-fixpunkt-test-scoring.md),
>   „Nächste Schritte" Punkt 4.** Dort stand, `discriminability` lege nahe,
>   dass ausser Ø und den ΔE-Werten kaum ein Merkmal zur Trennung beitrage.
>   Das ist **umgekehrt** richtig: die ΔE-Merkmale sind die schwächsten.
>   Kein Ergebnis und keine Änderung hing daran — es war ein Vorschlag für
>   die nächste Runde, der sie in die falsche Richtung geschickt hätte.
>   Dort als Korrektur vermerkt.
>
> **Ein Detail, das die Erwartung oben präzisiert:** die 40 Artefaktzeilen
> wurden NICHT zu NaN, sondern zu endlichen Werten (6,5–25,2). Mit korrektem
> Floor ist `sigma_eff` auch bei `proto_std = 0` grösser null — der Floor-Fix
> allein räumt sie ab. Der `np.nan`-Zweig hat auf diesen Daten **null Zellen**
> verändert; er ist Vorsorge für ein künftiges Merkmal ohne Floor-Eintrag,
> nicht die Ursache der besseren Zahlen.

Ursprünglicher Status (2026-08-01, vor dem Fix): Nicht gefixt.
`analysis.py` ist reine Konsumentenschicht; ein Fix ändert weder
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
