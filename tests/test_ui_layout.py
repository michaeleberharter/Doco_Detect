"""Tests für das Hauptscreen-Layout (Phase 2 des UI-Redesigns):
Icon-Schiene, Aktionsleiste, Live-Anzeige, Ergebnisspalte, Theme-Umschalter.

Offscreen wie die übrigen Qt-Tests.

Run: pytest tests/test_ui_layout.py -v
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from docodetect.ui_qt import theme as theme_mod  # noqa: E402
from docodetect.ui_qt.app import apply_theme, make_app  # noqa: E402


@pytest.fixture
def qapp():
    app = make_app()
    yield app
    apply_theme(app, theme_mod.DEFAULT_THEME)


def make_cfg(tmp_path):
    """Minimale Konfiguration ohne Einrichtung -> Fenster steht in
    NO_CAMERA/NOT_READY, was für Layout-Tests genügt."""
    return {
        "camera": {"width": 1920, "height": 1080},
        "calibration": {
            "file": str(tmp_path / "calibration.json"),
            "background_file": str(tmp_path / "background.png"),
            "aruco_dict": "DICT_4X4_50", "marker_id": 0,
            "marker_size_mm": 72.5,
        },
        "geometry": {"camera_height_mm": 300.0},
        "matching": {"diameter_tolerance_mm": 6.0, "area_tolerance_pct": 12.0,
                     "top_k": 3, "max_z_accept": 3.5, "min_llr_margin": 2.0,
                     "sigma_floors": {}, "feature_weights": {}},
        "paths": {"db_file": str(tmp_path / "t.sqlite3")},
        "ui": {"preview_fps": 5},
        "stage2": {"enabled": False},
    }


@pytest.fixture
def win(qapp, tmp_path):
    from docodetect.ui_qt.main_window import MainWindow
    w = MainWindow(make_cfg(tmp_path))
    yield w
    w.close()


# ---------- Icon-Schiene ----------

def test_schiene_loest_dieselben_aktionen_aus_wie_die_leiste(win):
    """Der Entwurf zeigt die Aktionen doppelt (Schiene + untere Leiste).
    Beide müssen an derselben Stelle landen, sonst driften sie auseinander."""
    from docodetect.ui_qt.state import UiState

    win.set_state(UiState.READY)          # sonst sind die Buttons gesperrt
    seen = []
    win._rail_actions = {k: (lambda k=k: seen.append(k))
                         for k in ("identify", "background", "calibrate", "enroll")}
    for key in ("identify", "background", "calibrate", "enroll"):
        win.tool_rail.button(key).click()
    assert seen == ["identify", "background", "calibrate", "enroll"]


def test_nur_scan_rastet_ein(win):
    """„Scan" markiert den aktiven Bereich. Die drei anderen sind Aktionen –
    blieben sie eingerastet, sähe „Kalibrieren" dauerhaft aktiv aus."""
    from docodetect.ui_qt.state import UiState

    win.set_state(UiState.READY)
    # Aktionen stillegen: der echte „Lernen"-Klick öffnet einen modalen
    # Dialog und würde den Testlauf blockieren.
    win._rail_actions = {k: (lambda: None) for k in win._rail_actions}
    assert win.tool_rail.button("identify").isChecked()
    for key in ("background", "calibrate", "enroll"):
        b = win.tool_rail.button(key)
        assert not b.isCheckable()
        b.click()
        assert not b.isChecked(), f"'{key}' bleibt nach dem Klick eingerastet"


def test_schiene_spiegelt_die_freigabe_der_leiste(win):
    """Ohne Einrichtung ist Identifizieren gesperrt – in BEIDEN Bedien-
    wegen, sonst führt die Schiene an der Zustandsmaschine vorbei."""
    from docodetect.ui_qt.state import UiState

    win.set_state(UiState.NOT_READY)
    assert not win.identify_button.isEnabled()
    assert not win.tool_rail.button("identify").isEnabled()
    assert win.background_button.isEnabled()
    assert win.tool_rail.button("background").isEnabled()

    win.set_state(UiState.READY)
    assert win.identify_button.isEnabled()
    assert win.tool_rail.button("identify").isEnabled()


def test_icons_folgen_dem_theme_ohne_zusaetzlichen_aufruf(win, qapp):
    """Ein Themewechsel muss die gezeichneten Icons mitnehmen, ohne dass der
    Aufrufer `retheme()` nachschiebt – sonst blieben sie in der alten Farbe
    stehen und wären im hellen Theme praktisch unsichtbar."""
    rail_before = win.tool_rail.button("identify").icon().pixmap(20, 20).toImage()
    bar_before = win.action_bar.calibrate_button._icon.pixmap().toImage()

    apply_theme(qapp, "light")
    qapp.processEvents()

    assert win.tool_rail.button("identify").icon().pixmap(20, 20).toImage() \
        != rail_before, "Schienen-Icon behält die Farbe des alten Themes"
    assert win.action_bar.calibrate_button._icon.pixmap().toImage() != bar_before, \
        "Leisten-Icon behält die Farbe des alten Themes"


# ---------- Aktionsleiste ----------

def test_leiste_traegt_die_vier_aktionen_mit_beschriftung(win):
    bar = win.action_bar
    assert bar.identify_button.title.text() == "Identifizieren"
    assert "Leertaste" in bar.identify_button.kbd.text()
    assert "Hintergrund" in bar.background_button.label_text()
    assert "Kalibrieren" in bar.calibrate_button.label_text()
    assert "einlernen" in bar.enroll_button.label_text()


def test_beschriftung_wird_beim_sperren_mit_ausgegraut(win):
    """Qt vererbt den Disabled-Zustand nicht an Kindlabels – ohne die
    Eigenschaft `off` bliebe die Schrift eines gesperrten Buttons hell."""
    b = win.action_bar.identify_button
    b.setEnabled(False)
    assert b.title.property("off") == "yes"
    assert b.kbd.property("off") == "yes"
    b.setEnabled(True)
    assert b.title.property("off") == "no"


def test_klick_auf_die_beschriftung_loest_den_button_aus(win, qapp):
    """Die Labels im Button dürfen den Klick nicht schlucken."""
    from PySide6.QtCore import Qt
    b = win.action_bar.identify_button
    for child in (b.title, b.subtitle, b.kbd):
        assert child.testAttribute(Qt.WA_TransparentForMouseEvents)


# ---------- Live-Anzeige ----------

def test_live_anzeige_folgt_dem_kamerazustand(win):
    from docodetect.ui_qt.state import UiState

    win.set_state(UiState.READY)
    assert win.live_indicator.label_text() == "Live"

    win.set_state(UiState.NO_CAMERA)
    assert win.live_indicator.label_text() != "Live"
    assert not win.live_indicator._dot.is_running(), \
        "Puls läuft ohne Kamera weiter und kostet Bildrate"


# ---------- Ergebnisspalte / Demo-Leiste ----------

def test_demoleiste_ist_ohne_demo_modus_unsichtbar(win):
    """Die Szenenauswahl ist ein Entwicklerwerkzeug, kein Produktfeature."""
    assert not win.demo_bar.isVisibleTo(win)


def test_abschnittslabels_sind_gross_und_gesperrt(win):
    """QSS kann weder text-transform noch letter-spacing – beides kommt
    aus dem Code (widgets/common.py)."""
    from PySide6.QtGui import QFont

    lbl = win.candidates_label
    assert lbl.text() == "WEITERE KANDIDATEN"
    assert lbl.font().letterSpacingType() == QFont.PercentageSpacing
    assert lbl.font().letterSpacing() > 100


def test_ergebnisspalte_hat_die_entwurfsbreite(win):
    assert win.width() >= 0            # Fenster existiert
    assert win.findChild(type(win.cards_box), None) is not None
    panel = win.cards_box.parent()
    while panel is not None and panel.objectName() != "resultColumn":
        panel = panel.parent()
    assert panel is not None, "Ergebnisspalte nicht gefunden"
    assert panel.width() == 372        # Entwurf


# ---------- Theme-Umschalter ----------

def test_zahnrad_schaltet_das_theme_um(win, qapp):
    from docodetect.ui_qt.app import current_theme

    start = current_theme().name
    win.toggle_theme()
    assert current_theme().name != start
    win.toggle_theme()
    assert current_theme().name == start


def test_theme_wechsel_schreibt_nicht_in_die_config(win):
    """Das Erscheinungsbild der Fotobox gehört in config.local.yaml und darf
    nicht von der laufenden App überschrieben werden."""
    before = dict(win.cfg.get("ui") or {})
    win.toggle_theme()
    assert dict(win.cfg.get("ui") or {}) == before
