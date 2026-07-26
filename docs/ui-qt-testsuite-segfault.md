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
