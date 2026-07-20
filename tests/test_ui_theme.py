"""Tests für das Theme-Fundament der Qt-UI (Phase 1 des UI-Redesigns):
Design-Tokens, Alpha-Auflösung, QSS-Template, Schriftladen, Icons.

Offscreen wie die übrigen Qt-Tests; PySide6 ist optional (Skip statt Fehler).

Run: pytest tests/test_ui_theme.py -v
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from docodetect.ui_qt import theme as theme_mod  # noqa: E402


@pytest.fixture
def qapp():
    """QApplication (offscreen). Setzt das Theme danach auf den Default
    zurueck – die QApplication ist ein Singleton und wird von den anderen
    Qt-Testmodulen mitbenutzt."""
    from docodetect.ui_qt.app import apply_theme, make_app
    app = make_app()
    yield app
    apply_theme(app, theme_mod.DEFAULT_THEME)


# ---------- Tokens (Qt-frei) ----------

def test_beide_themes_haben_denselben_tokensatz():
    dark, light = theme_mod.resolve("dark"), theme_mod.resolve("light")
    assert set(dark) == set(light), "Ein Theme hätte sonst leere QSS-Platzhalter"
    assert theme_mod.theme_names() == ["dark", "light"]


def test_alle_tokens_sind_deckendes_hex():
    """QSS bekommt nie rgba(): die halbtransparenten Tokens des Entwurfs
    werden auf ihren Untergrund gerechnet."""
    for name in theme_mod.theme_names():
        for key, value in theme_mod.resolve(name).items():
            assert isinstance(value, str), f"{name}.{key}"
            assert len(value) == 7 and value.startswith("#"), f"{name}.{key}={value}"
            int(value[1:], 16)          # wirft bei Unsinn


def test_blend_rechnet_alpha_auf_den_untergrund():
    assert theme_mod.blend("#ffffff", 0.0, "#000000") == "#000000"
    assert theme_mod.blend("#ffffff", 1.0, "#000000") == "#ffffff"
    assert theme_mod.blend("#ffffff", 0.5, "#000000") == "#808080"


def test_weak_token_liegt_zwischen_farbe_und_untergrund():
    """okWeak ist der grüne Kartenhintergrund – deutlich dunkler als ok,
    aber unterscheidbar vom Fensterhintergrund."""
    t = theme_mod.resolve("dark")
    assert t["okWeak"] not in (t["ok"], t["bg"])
    assert theme_mod.blend(t["ok"], 0.15, t["bg"]) == t["okWeak"]


def test_unbekanntes_theme_faellt_auf_dark_zurueck():
    assert theme_mod.load("gibtsnicht").name == "dark"
    assert theme_mod.load("light").name == "light"


def test_vier_anzeigezustaende_haben_farben():
    """accept/ambiguous/border/reject – 'border' (Objekt am Bildrand) ist ein
    EIGENER Zustand, teilt sich aber bewusst das Amber mit 'ambiguous' und
    darf nie wie 'reject' aussehen."""
    t = theme_mod.load("dark")
    assert set(theme_mod.TONES) == {"accept", "ambiguous", "border", "reject"}
    assert t.tone_color("accept") == t["ok"]
    assert t.tone_color("reject") == t["bad"]
    assert t.tone_color("border") == t["warn"] == t.tone_color("ambiguous")
    assert t.tone_color("border") != t.tone_color("reject")
    assert t.tone_weak("accept") == t["okWeak"]


# ---------- QSS-Template ----------

def test_stylesheet_hat_keine_offenen_platzhalter(qapp):
    """Jeder $token in style.qss muss aus theme.py bedient werden – ein
    Rest-$ hieße: Regel wirkungslos, Farbe fehlt."""
    from docodetect.ui_qt.app import stylesheet
    for name in theme_mod.theme_names():
        qss = stylesheet(theme_mod.load(name))
        assert qss, "style.qss nicht gefunden"
        assert "$" not in qss, f"offener Platzhalter im Theme '{name}'"


def test_stylesheet_traegt_die_themefarben(qapp):
    from docodetect.ui_qt.app import stylesheet
    dark = theme_mod.load("dark")
    light = theme_mod.load("light")
    qss_dark = stylesheet(dark)
    assert dark["accent"] in qss_dark and dark["bg"] in qss_dark
    assert stylesheet(light) != qss_dark


def test_qss_deckt_alle_vier_zustaende_ab(qapp):
    from docodetect.ui_qt.app import stylesheet
    qss = stylesheet(theme_mod.load("dark"))
    for tone in theme_mod.TONES:
        assert f'[tone="{tone}"]' in qss, f"Zustand '{tone}' ohne QSS-Regel"


def test_apply_theme_wechselt_zur_laufzeit(qapp):
    """Der Umschalter in der Icon-Schiene braucht genau das: neues Theme
    ohne Neustart, Palette und Stylesheet gemeinsam."""
    from docodetect.ui_qt.app import apply_theme, current_theme

    apply_theme(qapp, "light")
    assert current_theme(qapp).name == "light"
    light_bg = qapp.palette().window().color().name()

    apply_theme(qapp, "dark")
    assert current_theme(qapp).name == "dark"
    assert qapp.palette().window().color().name() != light_bg
    assert qapp.palette().window().color().name() == theme_mod.load("dark")["bg"]


def test_ui_cfg_kennt_theme_mit_fallback():
    from docodetect.ui_qt.app import ui_cfg
    assert ui_cfg({})["theme"] == "dark"
    assert ui_cfg({"ui": {"theme": "light"}})["theme"] == "light"


# ---------- Schriften ----------

def test_gebuendelte_schriften_liegen_im_repo():
    """Die OFL-TTFs sind Teil des Repos (keine Netz-Abhängigkeit zur
    Laufzeit) – inklusive Lizenz."""
    from docodetect.ui_qt import fonts
    d = fonts.assets_dir()
    assert (d / "LICENSE.txt").exists(), "OFL-Lizenz fehlt neben den Schriften"
    for f in ("IBMPlexSans-Regular.ttf", "IBMPlexSans-SemiBold.ttf",
              "IBMPlexSans-Bold.ttf", "IBMPlexMono-Regular.ttf"):
        assert (d / f).exists(), f"Schriftschnitt fehlt: {f}"


def test_schriften_werden_geladen(qapp):
    from docodetect.ui_qt import fonts
    fonts.reset_cache()
    info = fonts.load_fonts()
    assert info["loaded"] == 6 and not info["missing"]
    assert info["ui"] == fonts.UI_FAMILY and info["mono"] == fonts.MONO_FAMILY


def test_fehlende_schriften_fallen_auf_system_zurueck(qapp, monkeypatch, tmp_path):
    """Kein Absturz, wenn assets/fonts/ fehlt – nur andere Schrift."""
    from docodetect.ui_qt import fonts
    monkeypatch.setattr(fonts, "assets_dir", lambda: tmp_path / "weg")
    fonts.reset_cache()
    info = fonts.load_fonts()
    assert info["loaded"] == 0
    assert info["ui"] == fonts.FALLBACK_UI and info["mono"] == fonts.FALLBACK_MONO
    fonts.reset_cache()


# ---------- Icons ----------

def test_icons_zeichnen_sichtbare_pixel_in_der_gewuenschten_farbe(qapp):
    """Jedes Icon der Schiene muss tatsächlich etwas malen (ein leeres
    QPixmap fiele optisch erst spät auf) und die übergebene Farbe tragen."""
    from PySide6.QtGui import QColor
    from docodetect.ui_qt import icons

    for name in icons.NAMES:
        px = icons.pixmap(name, 24, "#ff0000")
        img = px.toImage()
        opaque = [(x, y) for y in range(img.height()) for x in range(img.width())
                  if img.pixelColor(x, y).alpha() > 200]
        assert opaque, f"Icon '{name}' zeichnet nichts"
        r, g, b = QColor(img.pixelColor(*opaque[0])).getRgb()[:3]
        assert r > 200 and g < 60 and b < 60, f"Icon '{name}' ignoriert die Farbe"


def test_vorschau_zeichnet_in_themefarben(qapp):
    """Die Vorschau hatte ihre Farben hartkodiert – im hellen Theme blieben
    die Letterbox-Balken schwarz. Sie kommen jetzt aus dem Theme."""
    from docodetect.ui_qt.app import apply_theme
    from docodetect.ui_qt.widgets import preview as preview_mod

    for name in ("dark", "light"):
        apply_theme(qapp, name)
        t = theme_mod.load(name)
        c = preview_mod._colors()
        assert c["bg"].name() == t["stage"]
        assert c["msg"].name() == t["dim"]


def test_randberuehrung_ist_amber_und_nicht_rot(qapp):
    """Vierter Anzeigezustand: die Randwarnung der Vorschau darf nicht wie
    ein REJECT aussehen (Auftrag 2026-07-20)."""
    from docodetect.ui_qt.app import apply_theme
    from docodetect.ui_qt.widgets import preview as preview_mod

    apply_theme(qapp, "dark")
    t = theme_mod.load("dark")
    c = preview_mod._colors()
    assert c["warn"].name() == t["warn"] == t.tone_color("border")
    assert c["warn"].name() != t["bad"]


def test_unbekanntes_icon_meldet_sich_deutlich(qapp):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QPainter, QPixmap
    from docodetect.ui_qt import icons

    px = QPixmap(24, 24)
    p = QPainter(px)
    with pytest.raises(KeyError, match="scan"):     # Fehlertext nennt die Auswahl
        icons.paint(p, "gibtsnicht", QRectF(0, 0, 24, 24), "#ffffff")
    p.end()
