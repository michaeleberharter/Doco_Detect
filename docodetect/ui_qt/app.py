"""QApplication-Setup: Fusion-Style, Theme (dunkel/hell/System), Schrift, QSS.

Fusion sieht auf Windows und macOS gleich aus – gewollt: die App soll auf
beiden Systemen identisch bedienbar sein. Qt 6 skaliert High-DPI automatisch.

Die Farbwelt kommt aus theme.py, die Schrift aus fonts.py; `style.qss` ist
ein Template mit `$token`-Platzhaltern (Qt-QSS kennt keine Variablen). Ein
Theme-Wechsel ist deshalb ein erneutes `apply_theme()` – ohne Neustart.

„system" ist KEIN drittes Token-Set: es löst über QStyleHints.colorScheme
(Qt >= 6.5, Versionsbefund 2026-08-12) auf dark/light auf und zieht bei
colorSchemeChanged live nach. Die App-Properties trennen deshalb WAHL
(`docoThemeChoice`: dark|light|system) und WIRKUNG (`docoTheme`: dark|light)
– Widgets fragen weiterhin nur current_theme(), das die Wirkung liefert.
"""

from __future__ import annotations

from pathlib import Path
from string import Template

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication, QWidget

from . import fonts, theme as theme_mod

_UI_DEFAULTS = {
    "preview_max_width": 960,
    "preview_fps": 15,
    "result_overlay_secs": 4,
    "confirm_sound": True,
    "window_min_width": 1280,
    "window_min_height": 800,
    "enroll_shots": 12,
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


def system_scheme(app: QApplication | None = None) -> str:
    """OS-Farbschema als Theme-Name. Unknown -> dark (Boxen-Umgebung ist
    dunkel, und dark ist die Werksvorgabe der config)."""
    app = app or QApplication.instance()
    hints = app.styleHints() if app is not None else None
    if hints is None or not hasattr(hints, "colorScheme"):
        return theme_mod.DEFAULT_THEME
    return "light" if hints.colorScheme() == Qt.ColorScheme.Light else "dark"


def resolve_theme_choice(choice: str, app: QApplication | None = None) -> str:
    """Wahl (dark|light|system) -> wirksames Theme (dark|light)."""
    return system_scheme(app) if choice == "system" else choice


def apply_theme(app: QApplication, name: str) -> theme_mod.Theme:
    """Theme setzen (Palette + Stylesheet) und zurückgeben. Läuft auch zur
    Laufzeit – der Einstellungsdialog ruft genau das.

    `name` darf auch „system" sein (Auflösung siehe resolve_theme_choice).
    Nach dem Setzen werden ALLE Widgets unpolish/polish-t und `retheme()`
    der Top-Level-Fenster gerufen: property-basierte QSS-Selektoren und
    selbst gezeichnete Icons/Pixmaps ziehen sonst nicht nach (Auftrag
    2026-08-12 — kein Neustart nötig)."""
    effektiv = resolve_theme_choice(name, app)
    t = theme_mod.load(effektiv)
    app.setPalette(palette_for(t))
    qss = stylesheet(t)
    from . import touch
    qss += touch.qss_zusatz(app)
    app.setStyleSheet(qss)
    app.setProperty("docoThemeChoice", name)
    app.setProperty("docoTheme", t.name)
    _repolish_all(app)
    return t


def _repolish_all(app: QApplication) -> None:
    """unpolish/polish über alle Widgets + retheme() der Fenster, die eines
    haben. Idempotent — MainWindow.retheme läuft ggf. zusätzlich über sein
    PaletteChange-Event, das ist unschädlich (nur Neuzeichnen)."""
    for top in app.topLevelWidgets():
        for w in [top] + top.findChildren(QWidget):
            w.style().unpolish(w)
            w.style().polish(w)
        retheme = getattr(top, "retheme", None)
        if callable(retheme):
            retheme()


def _system_nachziehen(app: QApplication) -> None:
    """colorSchemeChanged: nur bei Wahl „system" das wirksame Theme
    nachziehen — eine explizite dark/light-Wahl bleibt stehen."""
    if app.property("docoThemeChoice") == "system":
        apply_theme(app, "system")


def current_theme(app: QApplication | None = None) -> theme_mod.Theme:
    """Aktuell gesetztes Theme – Widgets fragen hier nach Farben für ihre
    selbst gezeichneten Flächen (Vorschau, Icons, Balken)."""
    app = app or QApplication.instance()
    name = app.property("docoTheme") if app is not None else None
    return theme_mod.load(name or theme_mod.DEFAULT_THEME)


def make_app(argv: list | None = None, theme: str | None = None) -> QApplication:
    """QApplication mit Fusion + Theme + Schrift. Wiederverwendet eine
    bestehende Instanz (Tests/offscreen), setzt aber Style/Theme immer.

    `theme` bleibt EXPLIZIT (kein QSettings-Zugriff hier): Tests pinnen
    dark/light und berühren den Benutzer-Scope nie; die Settings-Ebene
    liest allein run()."""
    app = QApplication.instance() or QApplication(argv or [])
    app.setOrganizationName("DocoDetect")   # == settings.ORG (QSettings-Pfad)
    app.setApplicationName("Doco Detect")   # == settings.APP
    app.setStyle("Fusion")
    # Basisschrift auch als QFont setzen, nicht nur per QSS: native Dialoge
    # (Datei-/Meldungsdialoge) lesen die Anwendungsschrift, kein Stylesheet.
    loaded = fonts.load_fonts()
    if loaded["loaded"]:
        app.setFont(QFont(loaded["ui"], 12))
    # Live-Nachführung bei OS-Themewechsel — einmal je App-Instanz (das
    # Singleton überlebt in Tests viele make_app-Aufrufe).
    if not app.property("docoSchemeHooked") and hasattr(app.styleHints(),
                                                        "colorSchemeChanged"):
        app.styleHints().colorSchemeChanged.connect(
            lambda *_: _system_nachziehen(app))
        app.setProperty("docoSchemeHooked", True)
    apply_theme(app, theme or theme_mod.DEFAULT_THEME)
    return app


def run(cfg: dict, demo: bool = False) -> int:
    # Lokaler Import: settings importiert ui_cfg aus diesem Modul.
    from . import settings, touch
    ui = settings.effective_ui(cfg)
    # QT_SCALE_FACTOR / QT_IM_MODULE wirken nur VOR der QApplication-
    # Erzeugung — deshalb hier und nirgendwo später.
    start = settings.env_vorbereiten(ui)
    if start["gesetzt"]:
        print(f"[ui] Start-Umgebung aus Einstellungen: "
              f"{', '.join(start['gesetzt'])}")
    app = make_app(theme=ui["theme"])
    # Aus ist der Grundzustand — anwenden(False) liefe nur ein zweites
    # Mal Stylesheet+Repolish über alle Widgets (Review-Befund M3).
    if ui["touch_mode"]:
        touch.anwenden(app, True)
    from .main_window import MainWindow
    win = MainWindow(cfg, demo=demo)
    win.show()
    _skalierungs_kontrolle(app, win, ui, start)
    return app.exec()


def _skalierungs_kontrolle(app: QApplication, win, ui: dict,
                           start: dict) -> None:
    """Schirm-Basis für den Start-Deckel des NÄCHSTEN Laufs speichern und
    den Operator SICHTBAR informieren, wenn die Skalierung begrenzt wurde
    oder das Fenster nicht auf den Schirm passt (Station an kleinerem
    Monitor; der Deckel greift dann erst beim nächsten Start, weil die
    gespeicherte Basis noch vom alten Schirm stammt).

    Die Box ist bewusst NICHT modal (ein Kiosk-Autostart darf nicht auf
    einen OK-Klick warten) und ersetzt keine gespeicherte Einstellung —
    der QSettings-Wert bleibt stehen und gilt am grossen Schirm wieder."""
    from . import settings
    from PySide6.QtWidgets import QMessageBox

    screen = win.screen() or app.primaryScreen()
    if screen is None:                       # offscreen-Extremfall
        return
    avail = screen.availableGeometry()
    f = settings.aktueller_scale_faktor()
    settings.speichere_schirm_basis(avail.width() * f, avail.height() * f)

    meldung = None
    if start["scale_angewendet"] != start["scale_gespeichert"]:
        meldung = (
            f"Gespeichert sind {start['scale_gespeichert']} % UI-Skalierung; "
            f"für diesen Bildschirm werden {start['scale_angewendet']} % "
            "angewendet, damit das Fenster vollständig sichtbar bleibt.\n\n"
            "Die gespeicherte Einstellung bleibt unverändert und gilt "
            "wieder, sobald die Station an einem grösseren Bildschirm "
            "hängt.")
    elif (int(ui["window_min_width"]) > avail.width()
          or int(ui["window_min_height"]) > avail.height()):
        meldung = (
            "Der Bildschirm ist kleiner als das Fenster bei der aktuellen "
            "UI-Skalierung — vermutlich hängt die Station jetzt an einem "
            "kleineren Monitor. Beim nächsten Start wird die Skalierung "
            "automatisch begrenzt; alternativ jetzt im Einstellungsdialog "
            "(Zahnrad) eine kleinere Stufe wählen und neu starten.")
    if meldung:
        print(f"[ui] Skalierungs-Hinweis: {meldung.splitlines()[0]}")
        box = QMessageBox(win)
        box.setIcon(QMessageBox.Information)
        box.setWindowTitle("UI-Skalierung")
        box.setText(meldung)
        box.setModal(False)
        box.setAttribute(Qt.WA_DeleteOnClose, True)
        box.show()
