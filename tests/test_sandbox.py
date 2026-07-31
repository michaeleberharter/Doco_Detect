"""Tests für den isolierten Testbestand (--sandbox NAME).

Zweck der Sandbox: ein komplettes Test-Enrollment samt Prüflauf fahren, ohne
produktive Referenzen, DB, Captures oder Berichte anzufassen. Fünf Pfade
werden umgelenkt, ZWEI bewusst NICHT — calibration.file und
background_file bleiben geteilt, weil ein Test-Enrollment gegen eine andere
Skala nichts misst. Genau daraus folgen die Sperren: was die geteilten
Dateien schreibt, darf aus einer Sandbox heraus nicht laufen.

Die Sperren sind hier EINZELN geprüft. Eine Sammelprüfung („irgendeine
Sperre greift") würde nicht auffallen, wenn eine davon still wegfällt.
"""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect import cli  # noqa: E402
from docodetect.config import (SANDBOX_ROOT, project_root,  # noqa: E402
                               resolve, sandbox_cfg, validate_sandbox_name)


def _cfg():
    """Config-Ausschnitt, wie ihn load_config liefert (nur was zählt)."""
    return {
        "camera": {"index": 0, "width": 3840},
        "geometry": {"camera_height_mm": 300.0},
        "calibration": {"file": "calibration/calibration.json",
                        "background_file": "calibration/background.png",
                        "marker_size_mm": 136.0},
        "matching": {"max_z_accept": 3.5, "min_llr_margin": 2.0,
                     "sigma_floors": {"diameter_mm": 0.6}},
        "features": {"weights": {"diameter_mm": 1.0}},
        "paths": {"db_file": "doco_detect.sqlite3",
                  "reference_dir": "data/reference",
                  "captures_dir": "data/captures"},
        "analysis": {"output_dir": "reports/analysis",
                     "publish_dir": "reports/archive"},
    }


# ---------- Umlenkung: die fünf Pfade ----------

def test_sandbox_lenkt_die_fuenf_schreibpfade_um():
    out = sandbox_cfg(_cfg(), "testlauf1", verbose=False)
    root = f"{SANDBOX_ROOT}/testlauf1"
    assert out["paths"]["db_file"] == f"{root}/doco_detect.sqlite3"
    assert out["paths"]["reference_dir"] == f"{root}/reference"
    assert out["paths"]["captures_dir"] == f"{root}/captures"
    assert out["analysis"]["output_dir"] == f"{root}/reports"
    assert out["sandbox"] == "testlauf1"


def test_verworfen_folgt_dem_reference_dir():
    """discard_enrollment leitet das Ziel aus reference_dir.parent ab – der
    fünfte Pfad entsteht ohne eigenen Config-Key. Wird reference_dir einmal
    NICHT mehr umgelenkt, landen verworfene Aufnahmen wieder produktiv."""
    out = sandbox_cfg(_cfg(), "testlauf1", verbose=False)
    verworfen = resolve(out["paths"]["reference_dir"]).parent / "verworfen"
    assert verworfen == project_root() / SANDBOX_ROOT / "testlauf1" / "verworfen"
    assert verworfen != project_root() / "data" / "verworfen"


def test_kalibrierung_und_hintergrund_sind_NICHT_umgelenkt():
    """Positiv geprüft, nicht nur über die Sperren: beide Pfade müssen
    unverändert auf den geteilten Produktivstand zeigen. Ein Test-Enrollment
    gegen eine eigene Kalibrierung wäre wertlos – und würde still andere
    Millimeter liefern als der Produktivbetrieb."""
    src = _cfg()
    out = sandbox_cfg(src, "testlauf1", verbose=False)
    assert out["calibration"]["file"] == src["calibration"]["file"]
    assert out["calibration"]["background_file"] == \
        src["calibration"]["background_file"]
    assert resolve(out["calibration"]["file"]) == \
        project_root() / "calibration" / "calibration.json"
    assert SANDBOX_ROOT not in out["calibration"]["file"]
    assert SANDBOX_ROOT not in out["calibration"]["background_file"]


def test_messparameter_bleiben_unangetastet():
    """matching/features/geometry/camera gehen in den config_fingerprint bzw.
    direkt in die Messung. Eine Sandbox darf NUR Ablageorte verschieben."""
    src = _cfg()
    out = sandbox_cfg(src, "testlauf1", verbose=False)
    for abschnitt in ("matching", "features", "geometry", "camera"):
        assert out[abschnitt] == src[abschnitt]


def test_original_cfg_bleibt_unberuehrt():
    src = _cfg()
    sandbox_cfg(src, "testlauf1", verbose=False)
    assert src["paths"]["db_file"] == "doco_detect.sqlite3"
    assert src["paths"]["reference_dir"] == "data/reference"
    assert src["paths"]["captures_dir"] == "data/captures"
    assert src["analysis"]["output_dir"] == "reports/analysis"
    assert "sandbox" not in src


def test_publish_dir_wird_nicht_umgelenkt():
    """reports/archive ist versioniert und bleibt stehen – geschützt wird es
    über die Sperre von `analyze --publish`, nicht über eine Umlenkung."""
    out = sandbox_cfg(_cfg(), "testlauf1", verbose=False)
    assert out["analysis"]["publish_dir"] == "reports/archive"


def test_startzeile_nennt_alle_fuenf_pfade(capsys):
    sandbox_cfg(_cfg(), "testlauf1")
    zeile = capsys.readouterr().out
    assert "[sandbox] 'testlauf1' aktiv" in zeile
    for teil in ("db=", "referenzen=", "verworfen=", "captures=", "berichte="):
        assert teil in zeile
    assert str(project_root() / SANDBOX_ROOT / "testlauf1") in zeile


# ---------- Namensvalidierung ----------

@pytest.mark.parametrize("name", ["a", "testlauf1", "test-1", "test_1",
                                  "v1.2", "ABC-123_x.y"])
def test_gueltige_namen(name):
    assert validate_sandbox_name(name) == name


@pytest.mark.parametrize("name", [
    "", ".", "..", "../produktiv", "a/b", "a\\b", "/abs", "a b", "a;rm",
    "ä", "a\nb", "..\\..\\x",
])
def test_ungueltige_namen_werfen(name):
    with pytest.raises(ValueError):
        validate_sandbox_name(name)


def test_traversal_erreicht_das_projektwurzel_verzeichnis_nicht():
    """Doppelte Absicherung: selbst wenn die Regex einmal aufweicht, darf
    kein Name aus data/sandbox/ herausführen."""
    for name in ("..", "../..", "a/../.."):
        with pytest.raises(ValueError):
            sandbox_cfg(_cfg(), name, verbose=False)


def test_ungueltiger_name_bricht_die_cli_mit_exit_1_ab():
    with pytest.raises(SystemExit) as e:
        cli.main(["--sandbox", "../produktiv", "init-db"])
    assert e.value.code != 0


# ---------- Sperren: jede einzeln ----------

@pytest.mark.parametrize("cmd", [
    "calibrate", "capture-background", "make-smoke-testset",
    "corpus-build", "corpus-run", "corpus-diff", "corpus-report",
    "corpus-triage",
])
def test_gesperrter_befehl_bricht_mit_exit_1_ab(cmd, capsys):
    with pytest.raises(SystemExit) as e:
        cli.pruefe_sandbox_sperre(cmd, object())
    assert e.value.code != 0
    meldung = str(e.value)
    assert "[sandbox]" in meldung and cmd in meldung


def test_analyze_publish_gesperrt():
    class Args:
        publish = True
    with pytest.raises(SystemExit) as e:
        cli.pruefe_sandbox_sperre("analyze", Args())
    assert "publish_dir" in str(e.value)


def test_analyze_ohne_publish_erlaubt():
    class Args:
        publish = False
    cli.pruefe_sandbox_sperre("analyze", Args())   # darf nicht werfen


@pytest.mark.parametrize("cmd", [
    "init-db", "import-articles", "create-article", "batch-create", "enroll",
    "batch-enroll", "delete-article", "enrollment-sheet", "contour-band",
    "sync-stammdaten", "analyze-floors", "identify", "evaluate", "ab-report",
    "list-cameras",
])
def test_erlaubte_befehle_laufen_durch(cmd):
    cli.pruefe_sandbox_sperre(cmd, object())       # darf nicht werfen


def test_jeder_gesperrte_befehl_existiert_als_subcommand():
    """Wächter gegen eine Sperre, die einen Befehl schützt, den es nicht mehr
    gibt – die sähe grün aus und schützte nichts."""
    hilfe = subprocess.run(
        [sys.executable, "-m", "docodetect.cli", "--help"],
        capture_output=True, text=True, cwd=project_root()).stdout
    for cmd in cli.SANDBOX_GESPERRT:
        assert cmd in hilfe, f"{cmd} ist gesperrt, existiert aber nicht (mehr)"


# ---------- Qt-Einstieg ----------

def test_sandbox_und_demo_schliessen_sich_aus():
    from docodetect.ui_qt.__main__ import main as qt_main
    assert qt_main(["--demo", "--sandbox", "testlauf1"]) == 1


def test_qt_ungueltiger_name_exit_1():
    from docodetect.ui_qt.__main__ import main as qt_main
    assert qt_main(["--sandbox", "../weg"]) == 1
