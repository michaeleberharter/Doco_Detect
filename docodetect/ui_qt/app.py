"""QApplication-Setup: Fusion-Style, Theme (dunkel/hell), Schrift, QSS.

Fusion sieht auf Windows und macOS gleich aus – gewollt: die App soll auf
beiden Systemen identisch bedienbar sein. Qt 6 skaliert High-DPI automatisch.

Die Farbwelt kommt aus theme.py, die Schrift aus fonts.py; `style.qss` ist
ein Template mit `$token`-Platzhaltern (Qt-QSS kennt keine Variablen). Ein
Theme-Wechsel ist deshalb ein erneutes `apply_theme()` – ohne Neustart.
"""

from __future__ import annotations

from pathlib import Path
from string import Template

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

from . import fonts, theme as theme_mod

_UI_DEFAULTS = {
    "preview_max_width": 960,
    "preview_fps": 15,
    "result_overlay_secs": 4,
    "confirm_sound": True,
    "window_min_width": 1280,
    "window_min_height": 800,
    "enroll_shots": 8,
    "theme": theme_mod.DEFAULT_THEME,     # "dark" | "light"
}


def ui_cfg(cfg: dict) -> dict:
    """ui:-Sektion mit Code-Fallbacks – fehlende Keys sind ok (z.B. alte
    config.yaml), neue Keys gehören trotzdem in die config dokumentiert."""
    out = dict(_UI_DEFAULTS)
    out.update(cfg.get("ui") or {})
    return out


def palette_for(t: theme_mod.Theme) -> QPalette:
    """QPalette aus denselben Tokens wie die QSS.

    Nötig, weil Fusion viele Details (Fokusrahmen, Auswahl, deaktivierte
    Texte, native Dialoge) aus der Palette zieht und nicht aus dem
    Stylesheet – ohne das bliebe die App im alten Grau."""
    c = QColor
    p = QPalette()
    p.setColor(QPalette.Window, c(t["bg"]))
    p.setColor(QPalette.WindowText, c(t["text"]))
    p.setColor(QPalette.Base, c(t["panel2"]))
    p.setColor(QPalette.AlternateBase, c(t["panel"]))
    p.setColor(QPalette.Text, c(t["text"]))
    p.setColor(QPalette.PlaceholderText, c(t["faint"]))
    p.setColor(QPalette.Button, c(t["panel2"]))
    p.setColor(QPalette.ButtonText, c(t["text"]))
    p.setColor(QPalette.ToolTipBase, c(t["panel"]))
    p.setColor(QPalette.ToolTipText, c(t["text"]))
    p.setColor(QPalette.Highlight, c(t["accent"]))
    p.setColor(QPalette.HighlightedText, c("#ffffff"))
    p.setColor(QPalette.Link, c(t["accent"]))
    for role in (QPalette.ButtonText, QPalette.Text, QPalette.WindowText):
        p.setColor(QPalette.Disabled, role, c(t["faint"]))
    return p


def stylesheet(t: theme_mod.Theme) -> str:
    """style.qss mit den Tokens des Themes befüllen.

    `safe_substitute` statt `substitute`: ein vergessener Platzhalter soll
    die App nicht am Start hindern, sondern sichtbar im Stylesheet stehen
    bleiben (und im Test auffallen)."""
    qss = Path(__file__).with_name("style.qss")
    if not qss.exists():
        return ""
    values = dict(t.tokens)
    families = fonts.families()
    values["fontUi"] = families["ui"]
    values["fontMono"] = families["mono"]
    return Template(qss.read_text(encoding="utf-8")).safe_substitute(values)


def apply_theme(app: QApplication, name: str) -> theme_mod.Theme:
    """Theme setzen (Palette + Stylesheet) und zurückgeben. Läuft auch zur
    Laufzeit – der Umschalter in der Icon-Schiene ruft genau das."""
    t = theme_mod.load(name)
    app.setPalette(palette_for(t))
    app.setStyleSheet(stylesheet(t))
    app.setProperty("docoTheme", t.name)
    return t


def current_theme(app: QApplication | None = None) -> theme_mod.Theme:
    """Aktuell gesetztes Theme – Widgets fragen hier nach Farben für ihre
    selbst gezeichneten Flächen (Vorschau, Icons, Balken)."""
    app = app or QApplication.instance()
    name = app.property("docoTheme") if app is not None else None
    return theme_mod.load(name or theme_mod.DEFAULT_THEME)


def make_app(argv: list | None = None, theme: str | None = None) -> QApplication:
    """QApplication mit Fusion + Theme + Schrift. Wiederverwendet eine
    bestehende Instanz (Tests/offscreen), setzt aber Style/Theme immer."""
    app = QApplication.instance() or QApplication(argv or [])
    app.setApplicationName("Doco Detect")
    app.setStyle("Fusion")
    # Basisschrift auch als QFont setzen, nicht nur per QSS: native Dialoge
    # (Datei-/Meldungsdialoge) lesen die Anwendungsschrift, kein Stylesheet.
    loaded = fonts.load_fonts()
    if loaded["loaded"]:
        app.setFont(QFont(loaded["ui"], 12))
    apply_theme(app, theme or theme_mod.DEFAULT_THEME)
    return app


def run(cfg: dict, demo: bool = False) -> int:
    ui = ui_cfg(cfg)
    app = make_app(theme=ui["theme"])
    from .main_window import MainWindow
    win = MainWindow(cfg, demo=demo)
    win.show()
    return app.exec()
