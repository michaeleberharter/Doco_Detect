"""Tests des Einstellungsdialogs (widgets/settings_dialog.py, 2026-08-12).

Sofortwirkung (Theme), Persistenz nach QSettings (nie config), Seiten-
Reset, Skalierungs-Angebot gegen den simulierten Zielschirm (Auflage 1),
Neustart-Hinweis beim Schließen (Auflage 3) und die Sichtbarkeits-
Schaltung der Bewertungsleiste (nur Sichtbarkeit, Verdrahtung bleibt).

QSettings sind über die conftest-Fixture isolate_qsettings auf eine Ini
unter tmp_path umgelenkt — der Dialog läuft hier wie produktiv über die
Modul-Factory, ohne den Benutzer-Scope zu berühren.

Läuft im Test-Regime als EIGENER pytest-Aufruf (Segfault-Doku).

Run: pytest tests/test_ui_settings_dialog.py -v
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from docodetect.matcher import CandidateReport, MatchReport  # noqa: E402
from docodetect.ui_qt import settings as st  # noqa: E402
from docodetect.ui_qt import theme as theme_mod  # noqa: E402
from docodetect.ui_qt import touch  # noqa: E402
from docodetect.ui_qt.app import apply_theme, current_theme, make_app  # noqa: E402
from docodetect.ui_qt.widgets.settings_dialog import SettingsDialog  # noqa: E402


@pytest.fixture
def qapp():
    app = make_app(theme="dark")            # Theme-Pinnung: nie "system"
    yield app
    touch.anwenden(app, False)
    apply_theme(app, theme_mod.DEFAULT_THEME)


@pytest.fixture
def kein_neustart_hinweis(monkeypatch):
    """QMessageBox.information ist modal (exec) und würde offscreen den
    Lauf blockieren — aufzeichnen statt anzeigen."""
    from PySide6.QtWidgets import QMessageBox
    hinweise = []
    monkeypatch.setattr(QMessageBox, "information",
                        lambda *a, **k: hinweise.append(a[2]))
    return hinweise


CFG = {"ui": {"theme": "dark", "confirm_sound": True,
              "result_overlay_secs": 4,
              "window_min_width": 1280, "window_min_height": 800}}


@pytest.fixture
def dlg(qapp, kein_neustart_hinweis):
    d = SettingsDialog(dict(CFG))
    yield d
    d.done(0)
    d.deleteLater()


# ---------- Aufbau ----------

def test_drei_kategorien_und_seitenwechsel(dlg):
    texte = [dlg.kategorien.item(i).text()
             for i in range(dlg.kategorien.count())]
    assert texte == ["Darstellung", "Rückmeldung", "Bedienung"]
    dlg.kategorien.setCurrentRow(2)
    assert dlg.stack.currentIndex() == 2


def test_theme_combo_kennt_system(dlg):
    """Versionsbefund 1 (Qt 6.10 >= 6.5): „System" ist die dritte Wahl."""
    daten = [dlg.theme_box.itemData(i) for i in range(dlg.theme_box.count())]
    assert daten == ["light", "dark", "system"]


# ---------- Sofortwirkung + Persistenz ----------

def test_theme_wechsel_wirkt_sofort_und_geht_nach_qsettings(dlg, qapp):
    assert current_theme().name == "dark"
    dlg.theme_box.setCurrentIndex(dlg.theme_box.findData("light"))
    assert current_theme().name == "light"          # sofort, ohne Neustart
    assert st.gesetzte_ui_keys() == {"theme": "light"}


def test_werte_schreiben_nur_nach_qsettings_nie_in_die_config(dlg):
    """Die wichtigste Regel des Vorgangs: cfg (und damit config.yaml)
    bleibt in jedem Fall unangetastet."""
    vorher = dict(CFG["ui"])
    dlg.overlay_spin.setValue(7)
    dlg.sound_check.setChecked(False)
    dlg.verdict_check.setChecked(False)
    dlg.pause_spin.setValue(3)
    assert dlg.cfg["ui"] == vorher
    gesetzt = st.gesetzte_ui_keys()
    assert gesetzt["result_overlay_secs"] == 7
    assert gesetzt["confirm_sound"] is False
    assert gesetzt["verdict_buttons_visible"] is False
    assert gesetzt["preview_pause_minutes"] == 3


def test_reset_seite_loescht_nur_ihre_keys(dlg, qapp):
    dlg.theme_box.setCurrentIndex(dlg.theme_box.findData("light"))
    dlg.overlay_spin.setValue(9)
    dlg.sound_check.setChecked(False)               # andere Seite
    dlg.stack.widget(0)._reset()                    # Darstellung
    gesetzt = st.gesetzte_ui_keys()
    assert "theme" not in gesetzt and "result_overlay_secs" not in gesetzt
    assert gesetzt["confirm_sound"] is False        # bleibt
    assert current_theme().name == "dark"           # Werksvorgabe wieder aktiv
    assert dlg.overlay_spin.value() == 4


# ---------- Skalierung (Auflage 1) ----------

def test_scale_bietet_auf_1080p_kein_150_an(qapp, kein_neustart_hinweis,
                                            monkeypatch):
    """Simulierter kleiner Screen: kein anbietbarer Wert überschreitet mit
    der Mindestfenstergröße die verfügbare Geometrie."""
    monkeypatch.setattr(SettingsDialog, "_basis_geometrie",
                        lambda self: (1920, 1080))
    d = SettingsDialog(dict(CFG))
    daten = [d.scale_box.itemData(i) for i in range(d.scale_box.count())]
    assert daten == [100, 125]
    d.done(0)


def test_scale_winziger_screen_nur_100(qapp, kein_neustart_hinweis,
                                       monkeypatch):
    monkeypatch.setattr(SettingsDialog, "_basis_geometrie",
                        lambda self: (1000, 700))
    d = SettingsDialog(dict(CFG))
    assert [d.scale_box.itemData(i)
            for i in range(d.scale_box.count())] == [100]
    d.done(0)


def test_zu_grosser_gespeicherter_wert_wird_benannt_nicht_angeboten(
        qapp, kein_neustart_hinweis, monkeypatch):
    """Screen ist geschrumpft (anderer Monitor): der gespeicherte Wert
    bleibt gespeichert, wird aber nicht angeboten — mit Klartext-Hinweis
    statt stillschweigender Korrektur."""
    st.setze(st.KEY_SCALE, 200)
    monkeypatch.setattr(SettingsDialog, "_basis_geometrie",
                        lambda self: (1920, 1080))
    d = SettingsDialog(dict(CFG))
    assert [d.scale_box.itemData(i)
            for i in range(d.scale_box.count())] == [100, 125]
    assert d.scale_hinweis.isVisibleTo(d)
    assert "200" in d.scale_hinweis.text()
    assert st.gesetzte_ui_keys()["scale_percent"] == 200   # nichts geschrieben
    d.done(0)


# ---------- Neustart-Hinweis (Auflage 3) ----------

def test_neustart_hinweis_bei_skalierung(qapp, kein_neustart_hinweis,
                                         monkeypatch):
    monkeypatch.setattr(SettingsDialog, "_basis_geometrie",
                        lambda self: (3840, 2160))
    d = SettingsDialog(dict(CFG))
    d.scale_box.setCurrentIndex(d.scale_box.findData(150))
    d.done(0)
    assert len(kein_neustart_hinweis) == 1
    assert "Neustart" in kein_neustart_hinweis[0] \
        or "150" in kein_neustart_hinweis[0]


def test_neustart_hinweis_bei_touch_nur_fuer_die_tastatur(dlg, qapp,
                                                          kein_neustart_hinweis):
    dlg.touch_check.setChecked(True)
    assert touch.ist_aktiv(qapp)                    # Layout wirkt SOFORT
    dlg.done(0)
    assert len(kein_neustart_hinweis) == 1
    assert "Bildschirmtastatur" in kein_neustart_hinweis[0]


def test_kein_hinweis_ohne_neustart_relevante_aenderung(dlg,
                                                        kein_neustart_hinweis):
    dlg.sound_check.setChecked(False)
    dlg.done(0)
    assert kein_neustart_hinweis == []


# ---------- Wirkung im Hauptfenster ----------

def make_win_cfg(tmp_path):
    return {
        "camera": {"width": 1920, "height": 1080},
        "calibration": {
            "file": str(tmp_path / "calibration.json"),
            "background_file": str(tmp_path / "background.png"),
            "aruco_dict": "DICT_4X4_50", "marker_id": 0,
            "marker_size_mm": 72.5,
        },
        "geometry": {"camera_height_mm": 300.0},
        "matching": {"diameter_tolerance_mm": 6.0, "top_k": 3},
        "paths": {"db_file": str(tmp_path / "db.sqlite3")},
        "ui": {"preview_fps": 5, "confirm_sound": False},
        "stage2": {"enabled": False},
    }


def _accept_report():
    c = CandidateReport(
        article_number="ART-1", name="Teller 18", nominal_size_mm=180.0,
        height_mm=0.0, corrected_diameter_mm=181.0, geometry_error_mm=1.0,
        has_references=True, n_shots=5, posterior=0.92, log_score=-0.1,
        max_abs_z=0.5)
    return MatchReport(decision="accept", message="Testreport",
                       candidates=[c], measured={}, touches_border=False,
                       contour=None, image_size=None)


def test_bewertungsleiste_nur_sichtbarkeit(qapp, tmp_path,
                                           kein_neustart_hinweis):
    """Einstellung aus -> Leiste unsichtbar, aber VORHANDEN und verdrahtet
    (die Rückschreibung ins Report-JSON bleibt unangetastet); live wieder
    einschaltbar ohne neues Rendern."""
    from docodetect.ui_qt.main_window import MainWindow

    st.setze(st.KEY_VERDICT, False)
    w = MainWindow(make_win_cfg(tmp_path))
    try:
        w._show_report(_accept_report())
        assert w._verdict_bar is not None            # existiert weiter
        assert not w._verdict_bar.isVisibleTo(w)     # nur unsichtbar
        # Verdrahtung intakt: das Signal erreicht den echten Speicherweg
        # (der ohne report_path sauber ablehnt — genau diese Meldung).
        w._verdict_bar.correct.emit()
        assert "Bewertung nicht gespeichert" in w.headline_text()

        st.setze(st.KEY_VERDICT, True)
        w._settings_geaendert()
        assert w._verdict_bar.isVisibleTo(w)
    finally:
        w.close()
        w.deleteLater()


def test_dialog_aenderung_erreicht_das_hauptfenster(qapp, tmp_path,
                                                    kein_neustart_hinweis):
    """geaendert-Signal -> MainWindow liest effective_ui neu (self.ui)."""
    from docodetect.ui_qt.main_window import MainWindow

    w = MainWindow(make_win_cfg(tmp_path))
    try:
        d = SettingsDialog(w.cfg, w)
        d.geaendert.connect(w._settings_geaendert)
        d.overlay_spin.setValue(11)
        assert w.ui["result_overlay_secs"] == 11
        d.done(0)
        d.deleteLater()
    finally:
        w.close()
        w.deleteLater()
