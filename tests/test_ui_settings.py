"""Tests der QSettings-Ebene (docodetect/ui_qt/settings.py, 2026-08-12).

Präzedenz config.yaml -> config.local.yaml -> QSettings, Typkonvertierung
aus Ini-Strings, Seiten-Reset, Skalierungsgrenzen (Auflage 1: kein Wert
anbietbar, mit dem das Mindestfenster den Schirm sprengt) und die
Start-Umgebung (QT_SCALE_FACTOR / QT_IM_MODULE).

Alle Tests laufen gegen eine QSettings-Ini unter tmp_path — der echte
Benutzer-Scope wird nie berührt (zusätzlich abgesichert durch die
autouse-Fixture isolate_qsettings in conftest.py).

Run: pytest tests/test_ui_settings.py -v
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings  # noqa: E402

from docodetect.ui_qt import settings as st  # noqa: E402

CFG = {"ui": {"theme": "dark", "confirm_sound": True,
              "result_overlay_secs": 4}}


@pytest.fixture
def ini(tmp_path):
    return QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)


# ---------- Präzedenz ----------

def test_ohne_qsettings_gilt_die_config_kette(ini):
    """config.local.yaml kommt bereits gemergt als cfg an (Deep-Merge in
    config.py) — hier zählt: config-Wert vor Code-Vorgabe."""
    eff = st.effective_ui({"ui": {"theme": "light"}}, ini)
    assert eff["theme"] == "light"
    assert eff["scale_percent"] == 100          # Code-Vorgabe (kein config-Key)
    assert eff["verdict_buttons_visible"] is True
    assert eff["preview_pause_minutes"] == 0
    assert eff["touch_mode"] is False


def test_qsettings_ueberdeckt_die_config(ini):
    st.setze(st.KEY_THEME, "light", ini)
    st.setze(st.KEY_CONFIRM_SOUND, False, ini)
    eff = st.effective_ui(CFG, ini)
    assert eff["theme"] == "light"
    assert eff["confirm_sound"] is False
    # Nicht gesetzte Keys bleiben auf der config-Kette.
    assert eff["result_overlay_secs"] == 4


def test_reset_faellt_auf_die_werksvorgabe_zurueck(ini):
    """„Auf Werksvorgabe zurücksetzen" = Key löschen, NICHT Wert
    überschreiben — die config-Kette gilt wieder."""
    st.setze(st.KEY_THEME, "light", ini)
    st.setze(st.KEY_PAUSE_MIN, 9, ini)
    st.zuruecksetzen([st.KEY_THEME, st.KEY_PAUSE_MIN], ini)
    eff = st.effective_ui(CFG, ini)
    assert eff["theme"] == "dark"
    assert eff["preview_pause_minutes"] == 0
    assert not st.ist_gesetzt(st.KEY_THEME, ini)


def test_typkonvertierung_aus_ini_strings(ini):
    """QSettings-Ini liefert Strings — 'false' muss False werden, nicht
    truthy bleiben (der klassische QSettings-Fallstrick)."""
    ini.setValue(st.KEY_CONFIRM_SOUND, "false")
    ini.setValue(st.KEY_TOUCH, "true")
    ini.setValue(st.KEY_PAUSE_MIN, "7")
    ini.setValue(st.KEY_SCALE, "125")
    eff = st.effective_ui(CFG, ini)
    assert eff["confirm_sound"] is False
    assert eff["touch_mode"] is True
    assert eff["preview_pause_minutes"] == 7
    assert eff["scale_percent"] == 125


def test_unsinnige_werte_fallen_auf_die_vorgabe(ini):
    ini.setValue(st.KEY_THEME, "neon")           # kein gültiges Theme
    ini.setValue(st.KEY_PAUSE_MIN, "viel")       # kein int
    eff = st.effective_ui(CFG, ini)
    assert eff["theme"] == "dark"
    assert eff["preview_pause_minutes"] == 0


def test_gesetzte_ui_keys_nur_die_gesetzten(ini):
    assert st.gesetzte_ui_keys(ini) == {}
    st.setze(st.KEY_THEME, "system", ini)
    st.setze(st.KEY_VERDICT, False, ini)
    assert st.gesetzte_ui_keys(ini) == {
        "theme": "system", "verdict_buttons_visible": False}


# ---------- Skalierungsgrenzen (Auflage 1) ----------

def test_1080p_bietet_150_prozent_nicht_an():
    """Der Fall aus der Freigabe: 1280x800-Mindestfenster mal 1,5 =
    1920x1200 — passt nicht auf ein 1080p-Panel, die Aktionsleiste wäre
    unerreichbar. 150 darf also gar nicht erst wählbar sein."""
    assert st.erlaubte_skalierungen(1280, 800, 1920, 1080) == [100, 125]


def test_kleiner_screen_bietet_nur_100():
    """Kein anbietbarer Wert, mit dem die Mindestgröße die verfügbare
    Geometrie überschreitet; 100 bleibt als unskalierter Ist-Zustand."""
    assert st.erlaubte_skalierungen(1280, 800, 1000, 700) == [100]


def test_grosser_screen_bietet_alle_stufen():
    assert st.erlaubte_skalierungen(1280, 800, 3840, 2160) == \
        [100, 125, 150, 175, 200]


def test_grenzwert_exakt_passend_ist_erlaubt():
    # 1280*1.25 = 1600, 800*1.25 = 1000 — exakt der Schirm: passt.
    assert 125 in st.erlaubte_skalierungen(1280, 800, 1600, 1000)


# ---------- Start-Umgebung ----------

def test_env_vorbereiten_setzt_beide_variablen(ini, monkeypatch):
    monkeypatch.delenv("QT_SCALE_FACTOR", raising=False)
    monkeypatch.delenv("QT_IM_MODULE", raising=False)
    info = st.env_vorbereiten({"scale_percent": 150, "touch_mode": True}, ini)
    assert os.environ["QT_SCALE_FACTOR"] == "1.5"
    assert os.environ["QT_IM_MODULE"] == "qtvirtualkeyboard"
    assert set(info["gesetzt"]) == {"QT_SCALE_FACTOR", "QT_IM_MODULE"}
    assert info["scale_angewendet"] == info["scale_gespeichert"] == 150


def test_env_vorbereiten_respektiert_externe_werte(ini, monkeypatch):
    """Von aussen gesetzte Variablen (Entwickler, Deployment) werden nie
    überschrieben."""
    monkeypatch.setenv("QT_SCALE_FACTOR", "2")
    monkeypatch.setenv("QT_IM_MODULE", "anderswert")
    info = st.env_vorbereiten({"scale_percent": 150, "touch_mode": True}, ini)
    assert info["gesetzt"] == []
    assert os.environ["QT_SCALE_FACTOR"] == "2"
    assert os.environ["QT_IM_MODULE"] == "anderswert"


def test_env_vorbereiten_neutral_bei_werksvorgaben(ini, monkeypatch):
    monkeypatch.delenv("QT_SCALE_FACTOR", raising=False)
    monkeypatch.delenv("QT_IM_MODULE", raising=False)
    info = st.env_vorbereiten({"scale_percent": 100, "touch_mode": False}, ini)
    assert info["gesetzt"] == []
    assert "QT_SCALE_FACTOR" not in os.environ
    assert "QT_IM_MODULE" not in os.environ


# ---------- Start-Deckel gegen die gespeicherte Schirm-Basis ----------

def test_schirm_basis_roundtrip(ini):
    assert st.lese_schirm_basis(ini) is None
    st.speichere_schirm_basis(1920.0, 1080.0, ini)
    assert st.lese_schirm_basis(ini) == (1920, 1080)
    ini.setValue(st.KEY_SCHIRM_BASIS, "kaputt")
    assert st.lese_schirm_basis(ini) is None


def test_start_deckelt_zu_grosse_stufe_gegen_die_schirm_basis(
        ini, monkeypatch):
    """Der Fall aus Checkpoint 2: Station hängt am 1080p-Monitor,
    gespeichert sind 150 %. ANGEWENDET wird die grösste passende Stufe
    (125), der GESPEICHERTE Wert bleibt unangetastet — am grossen Schirm
    gilt er wieder. Sichtbar gemacht wird das von
    app._skalierungs_kontrolle (Info-Box), nie still verschluckt."""
    monkeypatch.delenv("QT_SCALE_FACTOR", raising=False)
    st.setze(st.KEY_SCALE, 150, ini)
    st.speichere_schirm_basis(1920, 1080, ini)
    ui = st.effective_ui({"ui": {"window_min_width": 1280,
                                 "window_min_height": 800}}, ini)
    info = st.env_vorbereiten(ui, ini)
    assert os.environ["QT_SCALE_FACTOR"] == "1.25"
    assert info["scale_angewendet"] == 125
    assert info["scale_gespeichert"] == 150
    # Der gespeicherte Wert wurde NICHT überschrieben:
    assert st.gesetzte_ui_keys(ini)["scale_percent"] == 150
    monkeypatch.delenv("QT_SCALE_FACTOR", raising=False)


def test_start_ohne_basis_wendet_die_stufe_unveraendert_an(ini, monkeypatch):
    """Noch nie gelaufen (kein Cache): keine Basis, kein Deckel — die
    gültige Stufe gilt; die Basis entsteht beim ersten Lauf."""
    monkeypatch.delenv("QT_SCALE_FACTOR", raising=False)
    info = st.env_vorbereiten({"scale_percent": 150, "touch_mode": False,
                               "window_min_width": 1280,
                               "window_min_height": 800}, ini)
    assert os.environ["QT_SCALE_FACTOR"] == "1.5"
    assert info["scale_angewendet"] == 150
    monkeypatch.delenv("QT_SCALE_FACTOR", raising=False)


def test_beste_schirm_basis_nimmt_den_schirm_mit_der_groessten_stufe():
    """Mehrschirm-Entscheidung 2026-08-12: Basis vom verbundenen Schirm,
    der die grösste Skalierung erlaubt — nicht vom Startschirm."""
    laptop, extern = (1512, 950), (2560, 1415)
    assert st.beste_schirm_basis([laptop, extern], 1280, 800) == extern
    assert st.beste_schirm_basis([extern, laptop], 1280, 800) == extern
    assert st.beste_schirm_basis([laptop], 1280, 800) == laptop


def test_beste_schirm_basis_setzt_keine_achsen_zusammen():
    """Hoch- + Querformat: es zählt der real beste EINZELSCHIRM (beide
    Limits gemeinsam), nie ein unabhängiges Achsen-Maximum (1920x1920
    hat kein Schirm)."""
    quer, hoch = (1920, 1080), (1080, 1920)
    # quer: min(1920/1280, 1080/800) = 1.35 > hoch: min(0.84, 2.4) = 0.84
    assert st.beste_schirm_basis([quer, hoch], 1280, 800) == quer


def test_start_deckelt_winzige_basis_auf_100(ini, monkeypatch):
    monkeypatch.delenv("QT_SCALE_FACTOR", raising=False)
    st.speichere_schirm_basis(1300, 820, ini)
    info = st.env_vorbereiten({"scale_percent": 200, "touch_mode": False,
                               "window_min_width": 1280,
                               "window_min_height": 800}, ini)
    assert info["scale_angewendet"] == 100
    assert "QT_SCALE_FACTOR" not in os.environ


def test_aktueller_scale_faktor(monkeypatch):
    monkeypatch.delenv("QT_SCALE_FACTOR", raising=False)
    assert st.aktueller_scale_faktor() == 1.0
    monkeypatch.setenv("QT_SCALE_FACTOR", "1.5")
    assert st.aktueller_scale_faktor() == 1.5
    monkeypatch.setenv("QT_SCALE_FACTOR", "unsinn")
    assert st.aktueller_scale_faktor() == 1.0
