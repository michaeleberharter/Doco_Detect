"""Tests der Dialoge (Phase 4 des UI-Redesigns): Kalibrieren und Einlernen.

Schwerpunkt sind die zwei verbindlichen Korrekturen gegenüber dem Entwurf:
der Kalibrier-Dialog fährt den ECHTEN ArUco-Ablauf (kein Eingabefeld für ein
bekanntes Maß), und die Toleranz im Einlern-Dialog ist eine globale
Konfigurationsgröße, kein Artikelattribut.

Run: pytest tests/test_ui_dialogs.py -v
"""

import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QLineEdit, QSpinBox  # noqa: E402

from docodetect.ui_qt import theme as theme_mod  # noqa: E402
from docodetect.ui_qt.app import apply_theme, make_app  # noqa: E402


@pytest.fixture
def qapp():
    app = make_app()
    yield app
    apply_theme(app, theme_mod.DEFAULT_THEME)


def _wait(qapp, cond, timeout=90.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        qapp.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def demo_cfg(tmp_path):
    """Echte Konfiguration, aber alle Schreibpfade in tmp_path."""
    from docodetect.config import load_config

    cfg = load_config()
    cfg["calibration"] = dict(cfg["calibration"])
    cfg["calibration"]["file"] = str(tmp_path / "calibration.json")
    cfg["calibration"]["background_file"] = str(tmp_path / "background.png")
    cfg["paths"] = {"db_file": str(tmp_path / "demo.sqlite3"),
                    "captures_dir": str(tmp_path / "captures"),
                    "reference_dir": str(tmp_path / "reference")}
    return cfg


@pytest.fixture
def source(qapp, demo_cfg):
    from docodetect.ui_qt.demo_source import DemoSource

    src = DemoSource(demo_cfg)
    src.start()
    yield src
    src.stop()


# ---------- Kalibrieren ----------

def test_kalibrieren_hat_kein_feld_fuer_ein_handmass(qapp, demo_cfg, source):
    """Verbindliche Korrektur 1: der Maßstab kommt aus dem ArUco-Marker.
    Ein Eingabefeld „bekannter Durchmesser" waere eine zweite, konkurrierende
    Quelle fuer dieselbe Groesse."""
    from docodetect.ui_qt.widgets.calibrate_dialog import CalibrateDialog

    dlg = CalibrateDialog(demo_cfg, source)
    assert dlg.findChildren(QLineEdit) == []
    assert dlg.findChildren(QSpinBox) == []


def test_kalibrieren_zeigt_die_markerparameter_aus_der_config(qapp, demo_cfg,
                                                              source):
    from docodetect.ui_qt.widgets.calibrate_dialog import CalibrateDialog

    demo_cfg["calibration"]["marker_size_mm"] = 72.5
    dlg = CalibrateDialog(demo_cfg, source)
    texts = " ".join(lbl.text() for lbl in dlg.findChildren(type(dlg.status)))
    assert demo_cfg["calibration"]["aruco_dict"] in texts
    assert "72,5 mm" in texts
    assert f"ID {demo_cfg['calibration']['marker_id']}" in texts


def test_kalibrieren_mahnt_den_fehlenden_hintergrund_an(qapp, demo_cfg, source):
    """Auftrag: der Hinweis „erst Hintergrund, dann Kalibrieren" gehoert in
    den Dialog – nicht erst spaeter beim Identifizieren."""
    from docodetect.pipeline import capture_background
    from docodetect.ui_qt.demo_scenes import build_scene
    from docodetect.ui_qt.widgets.calibrate_dialog import CalibrateDialog

    dlg = CalibrateDialog(demo_cfg, source)
    assert dlg.hint.isVisibleTo(dlg)
    assert "Hintergrund" in dlg.hint.text()

    capture_background(build_scene(demo_cfg, "Hintergrund"), demo_cfg)
    dlg2 = CalibrateDialog(demo_cfg, source)
    assert not dlg2.hint.isVisibleTo(dlg2)


def test_kalibrieren_misst_und_zeigt_massstab_und_datum(qapp, demo_cfg, source):
    from docodetect.ui_qt.widgets.calibrate_dialog import CalibrateDialog

    source.set_scene("Marker")
    dlg = CalibrateDialog(demo_cfg, source)
    assert dlg.scale_value.text() == "–"

    dlg.primary_button.click()
    assert _wait(qapp, lambda: dlg.calibrated), "Kalibrierung lief nicht"
    assert "mm/px" in dlg.scale_value.text()
    assert "px" in dlg.edge_value.text()
    assert dlg.date_value.text() != "–"
    # Nach Erfolg wird die Hauptaktion zum Schliessen, nicht zum Neumessen.
    assert dlg.primary_button.text() == "Fertig"
    assert Path(demo_cfg["calibration"]["file"]).exists()


def test_kalibrieren_ohne_marker_nennt_die_abhilfe(qapp, demo_cfg, source):
    from docodetect.ui_qt.widgets.calibrate_dialog import CalibrateDialog

    source.set_scene("Teller 18")            # kein Marker im Bild
    dlg = CalibrateDialog(demo_cfg, source)
    dlg.primary_button.click()
    assert _wait(qapp, lambda: dlg.status.text() != "")
    assert not dlg.calibrated
    assert "marker" in dlg.status.text().lower()
    assert dlg.primary_button.isEnabled(), "Wiederholen muss moeglich bleiben"


# ---------- Einlernen ----------

def test_toleranz_ist_nur_information_und_nicht_editierbar(qapp, demo_cfg,
                                                           source, tmp_path):
    """Verbindliche Korrektur 2: die Toleranz ist global
    (matching.diameter_tolerance_mm) und KEIN Artikelattribut. Ein
    Eingabefeld wuerde ein DB-Feld vortaeuschen, das es nicht gibt."""
    from docodetect.database import Database
    from docodetect.ui_qt.app import ui_cfg
    from docodetect.ui_qt.widgets.enroll_dialog import EnrollDialog

    Database(demo_cfg).init_schema()
    dlg = EnrollDialog(demo_cfg, ui_cfg(demo_cfg), source)

    tol_text = f"{float(demo_cfg['matching']['diameter_tolerance_mm']):.1f} mm"
    tol_text = tol_text.replace(".", ",")

    # Die Toleranz steht in einem ANZEIGE-Feld (read_only aus dialog_shell).
    values = [lbl for lbl in dlg.findChildren(type(dlg.ref_label))
              if lbl.objectName() == "fieldValue"]
    assert any(v.text() == tol_text for v in values), \
        "Toleranz wird nicht als Anzeigefeld gezeigt"
    labels = " ".join(lbl.text() for lbl in dlg.findChildren(type(dlg.ref_label)))
    assert "global" in labels.lower(), "Herkunft der Toleranz nicht benannt"

    # ... und nirgends editierbar. Die vorhandenen Eingabefelder gehoeren
    # ausschliesslich zur Artikelwahl und zur Aufnahmenzahl.
    assert dlg.findChildren(QSpinBox) == [dlg.shots_spin]
    editable = [e.text() for e in dlg.findChildren(QLineEdit)]
    assert tol_text not in editable
    assert all(e.parent() in (dlg.article_box, dlg.shots_spin)
               for e in dlg.findChildren(QLineEdit)), \
        "Unerwartetes Eingabefeld im Einlern-Dialog"


# ---------- Hülle ----------

def test_dialoghuelle_bricht_ueber_abbrechen_und_kreuz_ab(qapp, demo_cfg,
                                                          source):
    from PySide6.QtWidgets import QDialog

    from docodetect.ui_qt.widgets.calibrate_dialog import CalibrateDialog

    dlg = CalibrateDialog(demo_cfg, source)
    dlg.cancel_button.click()
    assert dlg.result() == QDialog.Rejected

    dlg2 = CalibrateDialog(demo_cfg, source)
    dlg2.header.close_button.click()
    assert dlg2.result() == QDialog.Rejected
    assert not dlg2.calibrated


def test_dialoge_folgen_dem_theme(qapp, demo_cfg, source):
    """Das Badge im Kopf ist ein gezeichnetes Icon – es muss beim
    Themewechsel mitziehen wie die uebrigen."""
    from docodetect.ui_qt.widgets.calibrate_dialog import CalibrateDialog

    apply_theme(qapp, "dark")
    dlg = CalibrateDialog(demo_cfg, source)
    before = dlg.header.badge.pixmap().toImage()
    apply_theme(qapp, "light")
    dlg.header.retheme()
    assert dlg.header.badge.pixmap().toImage() != before
