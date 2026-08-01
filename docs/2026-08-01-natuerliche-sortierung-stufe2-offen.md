# Natürliche Sortierung: Stufe 1 umgesetzt, Stufe 2 bewusst offen

**Datum:** 2026-08-01 · **Art:** Offener Punkt mit fertiger Analyse.
**Entscheidung:** Mike, 2026-08-01 — Stufe 2 wird **nicht** umgesetzt.

Artikelnummern wurden überall lexikografisch sortiert: `LOEFFEL-1`,
`LOEFFEL-11`, `LOEFFEL-12`, …, `LOEFFEL-15`, `LOEFFEL-2`. Bei 40 Artikeln ist
das mühsam zu lesen.

---

## Stufe 1 — umgesetzt

`display.natuerlicher_schluessel()` (Zahlengruppen numerisch, Rest
alphabetisch, wirft nie) an genau **zwei** Anzeigestellen:

| Stelle | Wirkung |
|---|---|
| `pipeline.list_articles()` | Artikel-Combo des Qt-Einlerndialogs **und** der Korrekturdialog — beide ohne eigene Sortierung, damit ohne UI-Änderung miterledigt |
| `cli.cmd_list_articles()` | die Artikeltabelle |

## Die Abgrenzung, auf die es ankommt

**`Database.all_articles()` (`ORDER BY article_number`) bleibt lexikografisch
— für immer.** Das war der naheliegende Einzeiler und wäre der Fehler
gewesen:

`matcher.match()` baut die Kandidatenliste in genau dieser Reihenfolge auf
(`matcher.py`, Schleife über `db.all_articles()`), und die spätere
`candidates.sort(key=log_score, reverse=True)` ist **stabil**. Bei gleichem
`log_score` entscheidet also die DB-Reihenfolge, wer Top-1 wird — und
`log_score` wird vor dem Sortieren auf **vier Nachkommastellen gerundet**.
Exakte Gleichstände sind bei baugleichen Artikeln damit nicht theoretisch;
dieser Bestand hatte mit MESSER-2/-5/-6 sogar dreimal dasselbe physische
Objekt.

Eine „kosmetische" Sortierung in der DB-Schicht hätte also Entscheidungen
kippen können — sichtbar erst in der Tier-2-Entscheidungs-Reproduktion des
Korpus, und `scripts/simulate_scoring.py` (reproduziert `matcher.match()`
bit-identisch) hätte es mitgetragen.

`tests/test_natuerliche_sortierung.py` prüft das **positiv**: die DB-Schicht
liefert weiter lexikografisch, und ein Matcher-Lauf mit zwei baugleichen
Artikeln belegt, dass die Kandidatenreihenfolge bei echtem Gleichstand der
DB folgt und nicht der Anzeige.

---

## Stufe 2 — analysiert, nicht umgesetzt

Diese Stellen sortieren ebenfalls Artikelnummern für Menschen, bleiben aber
lexikografisch:

| Datei | Zeilen | Was |
|---|---|---|
| `analysis.py` | 198–199 | Achsen der Verwechslungsmatrix |
| `analysis.py` | 785, 823, 926 | Zeilenreihenfolge von `true_rank.csv` und zwei weiteren CSVs |
| `analysis.py` | 1117, 1165–1167 | Paar-Etiketten der Trennschärfe-Matrix (`A / B`) |
| `corpus/review.py` | 790–791, 811–812 | dieselben Konfusionsachsen im Korpus-Review |

**Grund für das Aufschieben:** `analyze --publish` kopiert die Artefakte nach
`analysis.publish_dir` (`reports/archive/`), und das ist **versioniert** —
`.gitignore` nimmt `reports/archive/` ausdrücklich von `reports/*` aus. Eine
geänderte Zeilenreihenfolge erzeugt dort bei jedem künftigen Lauf einen Diff,
der nichts mit den Zahlen zu tun hat. Rauschen in versionierten Artefakten
kostet mehr, als die bequemere Leserichtung in einer CSV einbringt.

**Wer es später doch will:** die Analyse ist gemacht, die Tabelle oben ist
die vollständige Fundstellenliste. Der Eingriff ist je Stelle ein
`key=natuerlicher_schluessel` am vorhandenen `sorted(...)`. Zusätzlich zu
prüfen wäre dann nur, ob `tests/test_analysis.py` und
`tests/test_corpus_report.py` auf Zeilenreihenfolge zusichern.

## Nicht betroffen (geprüft, damit die Liste nicht erneut durchgegangen wird)

- **Korpus-Reihenfolgen** — `corpus/manifest.py` (Sessions; Bilder nach `sha`)
  und `corpus/runner.py` (nach `session, sha`): persistierte bzw.
  Verarbeitungsreihenfolge, das Manifest ist versioniert.
- **`cli.py` `evaluate`** — `sorted(class_dir)` ist die Verarbeitungsreihenfolge
  über das Testset.
- **`reporting.py`** — Reports nach `st_mtime`, absichtlich nicht nach Namen.
- **Nach Kennzahl sortierte Listen** in `analysis.py` und `stammdaten.py` —
  sortieren nach Zahlen, nicht nach Namen.
- **`enrollment_sheet.py`, `analysis.py:142`** — sortieren ganzzahlige
  Indizes, keine Artikelnummern.
