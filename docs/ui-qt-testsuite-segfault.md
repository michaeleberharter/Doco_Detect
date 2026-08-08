# Notiz: UI-Qt-Testsuite segfaultet am Stück (vorbestehend)

Status: **Befund, nicht behoben.** Bewusst NICHT Teil des High-DPI-Icon-Commits
(a66bde2). Zum späteren Terminieren durch Mike.

## Symptom

Werden **zwei oder mehr** UI-Testmodule in **einem** `pytest`-Aufruf gesammelt,
crasht der Interpreter nativ (Segfault) beim/nach dem Modulübergang, z.B.:

    QT_QPA_PLATFORM=offscreen pytest tests/test_ui_layout.py tests/test_ui_theme.py \
        tests/test_ui_dialogs.py tests/test_ui_result_states.py \
        tests/test_ui_history.py tests/test_ui_state.py

Beim vollen Smoke-Lauf zusätzlich beobachtet:
`QThread: Destroyed while thread '' is still running`.

## Was gesichert ist

- **Vorbestehend**, nicht durch den Icon-Commit verursacht: reproduziert auf
  sauberem `main` (per `git stash` der geänderten Dateien) — auch ohne die neue
  `tests/test_icon_hidpi.py`.
- **Jedes Modul einzeln ist grün** (test_ui_layout 13, test_ui_theme 18,
  test_ui_dialogs 8, test_ui_result_states 15, test_ui_history 10,
  test_ui_state 6, test_ui_qt_smoke 20, test_icon_hidpi 10).
- Folge: die UI-Suite läuft in der Praxis nie am Stück — CI/lokal müssen die
  Module einzeln aufgerufen werden, sonst maskiert der Crash echte Fehler.

## Datenpunkt 2026-07-31

Ein vollständiger serieller Lauf (`pytest -q -rs`, 641 gesammelt, alle
UI-Module in einem Aufruf, Mac/Python 3.9/PySide6) lief **ohne Segfault**
durch: 639 passed, 2 skipped, Exit 0, vollständige Zusammenfassung. Die
Teardown-Meldung war vorhanden — `QThread: Destroyed while thread '' is still
running`, davor `Error calling Python override of QThread::run(): KeyError:
'index'` (`camera_worker.py:73` → `camera.py:93`), beides nach dem Summary.
Einzeln reproduzierbar mit `pytest tests/test_ui_qt_smoke.py -k
status_bar_calibrated`, das `MainWindow(cfg)` mit `demo=False` und einer
Test-Config ohne `camera.index` baut.

## Vermutete Ursache

Jedes UI-Modul bringt sein **eigenes `qapp`-Fixture** mit (kein gemeinsames
conftest-Fixture), das über `docodetect.ui_qt.app.make_app()` das
QApplication-**Singleton** wiederverwendet (`QApplication.instance() or
QApplication(...)`). Dabei:

- **gemischte Fixture-Scopes**: `test_ui_layout`/`test_ui_theme` u.a. sind
  function-scoped, `test_ui_qt_smoke` ist module-scoped;
- **kein Teardown schließt Top-Level-Fenster** oder ruft `deleteLater()`;
- **QThreads überleben ihre Owner**: `camera_worker`/`pipeline_worker` starten
  QThreads; werden `MainWindow`-Instanzen eines früheren Moduls erst später
  (GC / Interpreter-Shutdown) unter der App eines anderen Moduls finalisiert,
  passt „Destroyed while thread still running" ins Bild.

Die Kombination — persistentes Singleton + nicht abgeräumte Widgets/QThreads
über Modulgrenzen — ist die wahrscheinliche Crash-Quelle.

## Kandidaten-Fix (zu prüfen, nicht umgesetzt)

1. **Ein einziges session-scoped `qapp`-Fixture in `tests/conftest.py`** statt
   pro Modul; die Modul-Fixtures darauf umstellen. Teardown, der vor GC
   deterministisch aufräumt: offene Top-Level-Fenster `close()` +
   `deleteLater()`, laufende Kamera-/Pipeline-QThreads stoppen und **joinen**,
   danach `processEvents()`.
2. Alternativ **pytest-qt** einführen (`qapp`/`qtbot`): liefert genau dieses
   session-scoped, aufräumende App-Management out of the box — wäre aber eine
   neue Test-Abhängigkeit (Rückfrage nötig).

Empfehlung: erst (1) versuchen (keine neue Abhängigkeit); die QThread-Stops im
Teardown sind vermutlich der eigentliche Hebel gegen den Segfault.

## Datenpunkte 2026-08-06/07 — dreimal **Exit 134** nach grünem Summary

Drei datierte Vorkommen an **zwei Tagen**, alle in einem **vollen**
Suite-Lauf (`pytest tests/`, alle Module in einem Aufruf, Mac/Python 3.9.6/
PySide6, `QT_QPA_PLATFORM=offscreen`). Reine Beobachtung — **kein Fix, keine
Arbeit am Ursachenpfad.**

| Datum | Lauf | Ergebnis laut pytest | Prozess-Exit |
|---|---|---|---|
| 2026-08-06 | 739 gesammelt | **737 passed, 2 skipped, 0 failed** | **134** (SIGABRT) |
| 2026-08-07 | 765 gesammelt | **763 passed, 2 skipped, 0 failed** | **134** (SIGABRT) |
| 2026-08-07 | 772 gesammelt | **770 passed, 2 skipped, 0 failed** | **134** (SIGABRT) |

In beiden Fällen erschien **nach** der Summary-Zeile
`QThread: Destroyed while thread '' is still running`, danach brach der
Interpreter ab. **Alle Tests waren zu diesem Zeitpunkt bereits grün** — belegt
unabhängig durch `--junitxml`, das pro Test geschrieben wird und den Abbruch
deshalb überlebt: `failures=0 errors=0 skipped=2` in beiden Läufen.

**Warum das zählt, über die Kuriosität hinaus:** ein CI liest **Exit 134 als
Fehlschlag**, egal wie das Summary lautet. Solange der Teardown-Abbruch
auftritt, ist der Prozess-Rückgabecode kein verlässliches Freigabesignal — die
Aussage steckt dann nur noch im XML. Wer das Gate baut, muss das wissen.

**Nicht deterministisch:** dieselbe Codebasis lief in derselben Sitzung
mehrfach mit **Exit 0** durch. Die Abbrüche traten unabhängig davon auf, welcher
Schritt gerade gebaut wurde.

### 2026-08-08 — Exit 134 im EINZELLAUF eines Moduls

**Das widerspricht der Beschreibung oben.** Die Notiz führt den Abbruch bisher
auf die Konstellation „zwei oder mehr UI-Testmodule in EINEM pytest-Aufruf"
zurück, mit dem persistenten QApplication-Singleton über Modulgrenzen als
vermuteter Ursache. Am 2026-08-08 endete

    QT_QPA_PLATFORM=offscreen pytest tests/test_ui_qt_smoke.py

— **ein einzelnes Modul, ein einziger Aufruf** — mit **Exit 134**, bei
`23 passed`, ohne einen einzigen Fehlschlag.

**Was das für die vermutete Ursache heißt:** „gemischte Fixture-Scopes über
Modulgrenzen" kann die alleinige Erklärung nicht mehr sein. Innerhalb von
`test_ui_qt_smoke` gibt es allerdings ein **modul-scoped** `qapp`-Fixture und
mehrere `MainWindow`-Instanzen mit je eigenen QThreads — die Kombination
„persistentes Singleton + nicht abgeräumte Widgets/QThreads" ist also auch
**innerhalb eines Moduls** herstellbar. Der Kandidaten-Fix (deterministisches
Teardown mit QThread-Join) bleibt damit plausibel; die Modulgrenze ist nur
nicht die Bedingung, für die sie gehalten wurde.

**Gegenprobe, damit es niemand dem Session-Paket zurechnet:** derselbe
Einzellauf wurde gegen den Commit **`092be2d`** gefahren, also OHNE die
Qt-Arbeit von Schritt 7 — auch dort **Exit 134**. Zum Vergleich mit Schritt 7
zweimal Exit 134. Der Abbruch ist vorbestehend und **nicht** von dieser Arbeit
verursacht.

**Nicht immer:** früher am selben Tag lief dasselbe Modul einzeln mit Exit 0
durch. Nichtdeterministisch wie die Abbrüche im vollen Lauf.

**Vorbestehend.** Die Session-Arbeit dieser Sitzung fasst keinen QThread an;
sie fügt nur Tests hinzu, die ohne Qt laufen. Der Fix bleibt der oben
beschriebene Kandidat und ist nicht Teil dieser Arbeit.
