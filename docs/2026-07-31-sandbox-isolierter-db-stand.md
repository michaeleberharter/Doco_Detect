# Isolierter Testbestand: `--sandbox NAME`

**Datum:** 2026-07-31 · **Art:** Feature + bekannte Einschränkung

Ein komplettes Test-Enrollment samt Prüflauf fahren, ohne produktive
Referenzen, DB, Captures oder Berichte anzufassen.

```bash
docodetect --sandbox testlauf1 init-db
docodetect --sandbox testlauf1 create-article "Löffel 1" --height-mm 3
docodetect --sandbox testlauf1 enroll LOEFFEL-1 --shots 12
docodetect --sandbox testlauf1 identify

python -m docodetect.ui_qt --sandbox testlauf1     # Qt-Einlerndialog + Blatt
```

Jeder Lauf meldet beim Start seine fünf aufgelösten Pfade in einer Zeile.

## Was umgelenkt wird

| Config-Key | Ziel |
|---|---|
| `paths.db_file` | `data/sandbox/<name>/doco_detect.sqlite3` |
| `paths.reference_dir` | `data/sandbox/<name>/reference` |
| `paths.captures_dir` | `data/sandbox/<name>/captures` |
| `analysis.output_dir` | `data/sandbox/<name>/reports` |
| — (abgeleitet) | `data/sandbox/<name>/verworfen` |

Der Verworfenen-Ordner hat **keinen eigenen Config-Key**:
`pipeline.discard_enrollment` leitet ihn aus `reference_dir.parent` ab. Er
folgt der Umlenkung damit automatisch — und würde ihr genauso automatisch
nicht mehr folgen, wenn `reference_dir` einmal aus der Liste fiele. Dafür gibt
es einen eigenen Test.

`data/sandbox` ist gitignored.

## Was bewusst geteilt bleibt — und warum daraus Sperren folgen

`calibration.file` und `calibration.background_file` werden **nicht**
umgelenkt. Ein Test-Enrollment, das gegen eine eigene Kalibrierung misst,
liefert andere Millimeter als der Produktivbetrieb und ist damit wertlos.

Weil beide Dateien somit produktiver Zustand bleiben, ist alles gesperrt, was
sie schreibt. `run_calibration` und `save_background` speichern **immer** und
rotieren den alten Stand vorher weg — ein Sandbox-Lauf hätte also nicht nur
überschrieben, sondern die produktive Kalibrierung verschoben.

| gesperrt unter `--sandbox` | Grund |
|---|---|
| `calibrate`, `capture-background` | schreiben die geteilte Kalibrierung/Hintergrund |
| **Qt: „Kalibrieren", „Hintergrund aufnehmen"** | dieselben Schreibpfade über die UI |
| `make-smoke-testset` | verschiebt `calibration.file`, `background_file` **und** `db_file` beiseite |
| `analyze --publish` | `analysis.publish_dir` (`reports/archive`) ist **versioniert** — ein Sandbox-Lauf landete im Commit |
| `corpus-build/run/diff/report/triage` | Korpus liest/schreibt ausserhalb (`paths.corpus_dir`, `corpus/baseline.json`, `reports/corpus/`); aus einem Testbestand gebaut ist er kein Gate mehr |
| `--sandbox` **zusammen mit** `--demo` | zwei einander überschreibende Umlenkungen; die Demo lenkt Kalibrierung mit um, die Sandbox nicht |

Alle Sperren enden mit **Exit 1** und Klartext. In der Qt-UI sind die beiden
Knöpfe ausgegraut **und** die Aktionen brechen selbst ab — die Icon-Schiene
löst dieselben Aktionen aus, ein ausgegrauter Knopf allein wäre kein Schutz.

Unangetastet bleiben ausserdem `matching`, `features`, `geometry`, `camera`:
eine Sandbox verschiebt **nur Ablageorte**, nie Messparameter.

## Erlaubt

`init-db`, `import-articles`, `create-article`, `batch-create`, `enroll`,
`batch-enroll`, `delete-article`, `enrollment-sheet`, `contour-band`,
`sync-stammdaten`, `analyze` (ohne `--publish`), `analyze-floors`, `identify`,
`evaluate`, `ab-report`, `list-cameras` · Qt: Einlerndialog, Identifizieren,
Korrekturdialog.

`sync-stammdaten --apply` schreibt ausschliesslich `articles` in die
Sandbox-DB — der Nominal-Abgleich lässt sich damit üben, ohne die Live-
Stammdaten anzufassen.

## Namensregel

Der Name ist **Pflicht und hat keinen Default**. Erlaubt sind nur
`[A-Za-z0-9._-]`; `.` und `..` sind zusätzlich ausgeschlossen.

Der fehlende Default ist Absicht, kein Versäumnis: ein Sammelordner lüde dazu
ein, zwei Testläufe still in denselben Stand zu schreiben. `reference_stats`
kennt **keinen Session-Begriff** — zwei Einlern-Sessions desselben Artikels
verschmelzen dort zu einem Mittelwert und einem σ, der Basis für `sigma_eff`
im Matcher, ohne Warnung und ohne Spur. Siehe
[2026-07-31-reference-stats-keine-sessions.md](2026-07-31-reference-stats-keine-sessions.md).

Ein vertippter Name erzeugt still einen zweiten leeren Stand (`sqlite3.connect`
legt die Datei an). Die Startzeile mit den fünf Pfaden ist auch dagegen die
Absicherung — sie ist zu lesen, nicht zu überblättern.

---

## BEKANNTE EINSCHRÄNKUNG: `corpus/build.py` ignoriert die Config

**Fundstelle:** [docodetect/corpus/build.py:117](../docodetect/corpus/build.py)
(`BILD_POOLS`), ebenso die Session-Quellen in `BUNDLE_QUELLEN` darüber.

`corpus-build` führt `data/captures` als **festverdrahtetes
Projekt-Root-Literal** (`_P / "data/captures"`), statt `paths.captures_dir` aus
der Config zu lesen. Das ist ein eigenständiger Fehler, und er ist **grösser
als die Sandbox**: er hebelt **jede** Config-Umlenkung von `captures_dir` aus,
nicht nur diese — auch `--config` mit abweichenden Pfaden.

**Konsequenz, die man kennen muss:** Solange das Literal steht, schützt die
Sandbox-Umlenkung von `captures_dir` den Regressions-Korpus **nur deshalb,
weil die Sandbox woanders hinschreibt — nicht, weil `build.py` die Umlenkung
respektiert.** Der Schutz ist ein Nebeneffekt, keine Zusage. Wer künftig
`captures_dir` auf anderem Weg umlenkt und annimmt, `corpus-build` folge dem,
irrt: es liest weiter `data/captures`.

**Bewusst nicht in diesem Auftrag repariert.** `corpus/` ist das
Regressionsgate und gemeinsamer Code; die Änderung gehört in einen eigenen
Vorgang mit eigenem Re-Baselining. Hier nur festgehalten.
