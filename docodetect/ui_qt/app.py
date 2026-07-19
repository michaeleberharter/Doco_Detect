"""QApplication-Setup: Fusion-Style, dunkle Palette, QSS, High-DPI.

Fusion sieht auf Windows und macOS gleich aus – gewollt: die App soll auf
beiden Systemen identisch bedienbar sein. Qt 6 skaliert High-DPI automatisch.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

_UI_DEFAULTS = {
    "preview_max_width": 960,
    "preview_fps": 15,
    "result_overlay_secs": 4,
    "confirm_sound": True,
    "window_min_width": 1280,
    "window_min_height": 800,
}


def ui_cfg(cfg: dict) -> dict:
    """ui:-Sektion mit Code-Fallbacks – fehlende Keys sind ok (z.B. alte
    config.yaml), neue Keys gehören trotzdem in die config dokumentiert."""
    out = dict(_UI_DEFAULTS)
    out.update(cfg.get("ui") or {})
    return out


def _dark_palette() -> QPalette:
    """Dunkle Fusion-Palette – Feinschliff (Buttons, Karten) macht style.qss.
    Sehr dunkles Grau statt reinem Schwarz; die Vorschau ist der Star."""
    p = QPalette()
    bg = QColor(30, 32, 34)        # Fensterfläche
    base = QColor(22, 24, 26)      # Eingabe-/Listenflächen
    text = QColor(228, 230, 232)
    dim = QColor(150, 155, 160)
    accent = QColor(46, 125, 220)  # einzige Akzentfarbe (Primär-Button)
    p.setColor(QPalette.Window, bg)
    p.setColor(QPalette.WindowText, text)
    p.setColor(QPalette.Base, base)
    p.setColor(QPalette.AlternateBase, bg)
    p.setColor(QPalette.Text, text)
    p.setColor(QPalette.PlaceholderText, dim)
    p.setColor(QPalette.Button, bg)
    p.setColor(QPalette.ButtonText, text)
    p.setColor(QPalette.ToolTipBase, base)
    p.setColor(QPalette.ToolTipText, text)
    p.setColor(QPalette.Highlight, accent)
    p.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, dim)
    p.setColor(QPalette.Disabled, QPalette.Text, dim)
    p.setColor(QPalette.Disabled, QPalette.WindowText, dim)
    return p


def make_app(argv: list | None = None) -> QApplication:
    """QApplication mit Fusion + dunkler Palette + QSS. Wiederverwendet eine
    bestehende Instanz (Tests/offscreen), setzt aber Style/QSS immer."""
    app = QApplication.instance() or QApplication(argv or [])
    app.setApplicationName("Doco Detect")
    app.setStyle("Fusion")
    app.setPalette(_dark_palette())
    qss = Path(__file__).with_name("style.qss")
    if qss.exists():
        app.setStyleSheet(qss.read_text(encoding="utf-8"))
    return app


def run(cfg: dict, demo: bool = False) -> int:
    app = make_app()
    from .main_window import MainWindow
    win = MainWindow(cfg, demo=demo)
    win.show()
    return app.exec()
