"""QSettings-Ebene der Bediener-Einstellungen (Einstellungsdialog).

Präzedenz: config.yaml -> config.local.yaml -> QSettings. Die App schreibt
NIE in eine der YAML-Dateien — der ui:-Block dort ist Werksvorgabe, und
„Auf Werksvorgabe zurücksetzen" heisst schlicht: QSettings-Key löschen,
der Wert fällt auf die config-Kette (app.ui_cfg) zurück.

Nur die Keys des Dialogs haben eine QSettings-Ebene. `preview_fps`,
`preview_max_width`, `window_min_*` und `enroll_shots` bleiben bewusst
reine config-Werte — CameraWorker und DemoSource lesen weiter app.ui_cfg.

Testbarkeit: Tests ersetzen `_factory` (bzw. rufen alle Funktionen mit
explizitem `settings`-Objekt) durch eine QSettings-Ini unter tmp_path.
Der echte Benutzer-Scope (Registry/plist) wird von Tests nie berührt —
dieselbe Regel wie „echte DB nie aus Tests anfassen".
"""

from __future__ import annotations

import os

from PySide6.QtCore import QSettings

from .app import ui_cfg

ORG = "DocoDetect"
APP = "Doco Detect"          # identisch zu app.make_app (setApplicationName)

# Dialog-Keys. Die drei mit config-Werksvorgabe tragen denselben Namen wie
# ihr ui:-Key; die vier neuen existieren nur hier (Code-Vorgabe).
KEY_THEME = "ui/theme"                        # str: dark | light | system
KEY_SCALE = "ui/scale_percent"                # int, 100 = keine Skalierung
KEY_OVERLAY_SECS = "ui/result_overlay_secs"   # int, Sekunden
KEY_CONFIRM_SOUND = "ui/confirm_sound"        # bool
KEY_VERDICT = "ui/verdict_buttons_visible"    # bool
KEY_PAUSE_MIN = "ui/preview_pause_minutes"    # int, 0 = nie
KEY_TOUCH = "ui/touch_mode"                   # bool

# Werksvorgaben der Keys OHNE config-Gegenstück (Feldname im effektiven
# ui-Dict = Key-Name ohne "ui/"-Präfix).
CODE_VORGABEN = {
    KEY_SCALE: 100,
    KEY_VERDICT: True,
    KEY_PAUSE_MIN: 0,
    KEY_TOUCH: False,
}

_BOOL_KEYS = (KEY_CONFIRM_SOUND, KEY_VERDICT, KEY_TOUCH)
_INT_KEYS = (KEY_SCALE, KEY_OVERLAY_SECS, KEY_PAUSE_MIN)
ALLE_KEYS = (KEY_THEME, KEY_SCALE, KEY_OVERLAY_SECS, KEY_CONFIRM_SOUND,
             KEY_VERDICT, KEY_PAUSE_MIN, KEY_TOUCH)

# Angebotene Skalierungsstufen; was davon anbietbar ist, entscheidet
# erlaubte_skalierungen() gegen den Zielschirm.
SCALE_STUFEN = (100, 125, 150, 175, 200)

THEMES = ("dark", "light", "system")


def _make_qsettings() -> QSettings:
    """Expliziter Konstruktor statt QSettings(): unabhängig davon, ob und
    wann QCoreApplication-Namen gesetzt wurden (Reihenfolge-robust)."""
    return QSettings(ORG, APP)


# Tests ersetzen diese Factory (oder übergeben `settings` direkt).
_factory = _make_qsettings


def qsettings() -> QSettings:
    return _factory()


# ---------- Typkonvertierung ----------
# QSettings liefert aus Ini-Dateien (Test-Injektion, Linux) Strings zurück,
# aus der Registry/plist teils native Typen — beides robust normieren.

def _als_bool(v, fallback: bool) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, int):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes", "ja")
    return fallback


def _als_int(v, fallback: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return fallback


def _konvertiert(key: str, roh, fallback):
    if key in _BOOL_KEYS:
        return _als_bool(roh, fallback)
    if key in _INT_KEYS:
        return _als_int(roh, fallback)
    if key == KEY_THEME:
        wert = str(roh)
        return wert if wert in THEMES else fallback
    return roh


# ---------- Lesen ----------

def effective_ui(cfg: dict, settings: QSettings | None = None) -> dict:
    """ui-Dict mit voller Präzedenz: ui_cfg (config-Kette) + Code-Vorgaben
    der neuen Keys + Overlay der GESETZTEN QSettings-Keys."""
    s = settings or qsettings()
    out = ui_cfg(cfg)
    for key, vorgabe in CODE_VORGABEN.items():
        out.setdefault(_feldname(key), vorgabe)
    for key in ALLE_KEYS:
        if s.contains(key):
            feld = _feldname(key)
            out[feld] = _konvertiert(key, s.value(key), out.get(feld))
    return out


def _feldname(key: str) -> str:
    return key.split("/", 1)[1]


def werksvorgabe(key: str):
    """Werksvorgabe eines Dialog-Keys OHNE QSettings-Ebene: Code-Vorgabe
    der neuen Keys bzw. der app-Fallback der config-Keys. Konsumiert von
    der Admin-Config-Ansicht, damit sie die effektiven Werte auch dann
    vollständig zeigt, wenn ein ui:-Key aus der config fällt."""
    if key in CODE_VORGABEN:
        return CODE_VORGABEN[key]
    return ui_cfg({}).get(_feldname(key))


def ist_gesetzt(key: str, settings: QSettings | None = None) -> bool:
    return (settings or qsettings()).contains(key)


def gesetzte_ui_keys(settings: QSettings | None = None) -> dict:
    """{feldname: normierter Wert} NUR für gesetzte Keys — die
    Anzeige-Ebene der Admin-Config-Seite (Herkunft „QSettings")."""
    s = settings or qsettings()
    out = {}
    for key in ALLE_KEYS:
        if s.contains(key):
            out[_feldname(key)] = _konvertiert(key, s.value(key), None)
    return out


# ---------- Schreiben ----------

def setze(key: str, value, settings: QSettings | None = None) -> None:
    s = settings or qsettings()
    s.setValue(key, value)
    s.sync()


def entferne(key: str, settings: QSettings | None = None) -> None:
    s = settings or qsettings()
    s.remove(key)
    s.sync()


def zuruecksetzen(keys, settings: QSettings | None = None) -> None:
    """Seiten-Reset: Keys löschen -> Werte fallen auf die config-Kette
    bzw. die Code-Vorgabe zurück."""
    s = settings or qsettings()
    for key in keys:
        s.remove(key)
    s.sync()


# ---------- Skalierung ----------

def erlaubte_skalierungen(min_w: int, min_h: int,
                          basis_avail_w: float, basis_avail_h: float,
                          stufen=SCALE_STUFEN) -> list:
    """Anbietbare Stufen für den Zielschirm.

    `basis_avail_*` ist die verfügbare Bildschirmgeometrie BEI FAKTOR 100 %
    (also availableGeometry des Screens multipliziert mit dem aktuell
    wirksamen QT_SCALE_FACTOR — der Aufrufer rechnet das um, siehe
    aktueller_scale_faktor()). Eine Stufe s ist anbietbar, wenn das
    skalierte Mindestfenster (min_w*s, min_h*s) hineinpasst.

    100 ist IMMER dabei: es ist der unskalierte Ist-Zustand — ohne diesen
    Eintrag gäbe es auf einem Schirm unterhalb der Mindestfenstergröße
    gar keine Auswahl, und anbieten würde er trotzdem nichts Neues."""
    out = [100]
    for s in stufen:
        if s == 100:
            continue
        if min_w * s <= basis_avail_w * 100 and min_h * s <= basis_avail_h * 100:
            out.append(s)
    return out


def beste_schirm_basis(geometrien, min_w: int, min_h: int):
    """Aus den verfügbaren Geometrien ALLER verbundenen Schirme die des
    Schirms, der die grösste Skalierungsstufe erlaubt (Breiten- UND
    Höhenlimit zählen — deshalb kein unabhängiges max je Achse, das aus
    einem Hoch- und einem Querformat eine Geometrie zusammensetzte, die
    kein realer Schirm hat).

    Entscheidung 2026-08-12 (Mehrschirm-Klärung): Basis je Lauf vom
    grössten verbundenen Schirm statt vom Startschirm des Fensters —
    am Entwicklungs-Mac (Laptop + externer Monitor) pendelt die
    angewendete Skalierung damit nicht mehr zwischen den Läufen; nach
    dauerhaftem Umzug an einen kleineren Monitor (allein verbunden)
    greift der Deckel weiterhin ab dem Folgestart."""
    def _kapazitaet(g):
        return min(g[0] / max(1, min_w), g[1] / max(1, min_h))
    return max(geometrien, key=_kapazitaet)


def aktueller_scale_faktor() -> float:
    """Der beim Start wirksam gewordene QT_SCALE_FACTOR (1.0 wenn keiner).
    Nötig, um availableGeometry (in bereits skalierten Einheiten) auf die
    100-%-Basis zurückzurechnen."""
    try:
        return float(os.environ.get("QT_SCALE_FACTOR", "") or 1.0)
    except ValueError:
        return 1.0


# ---------- Schirm-Basis-Cache (für den Start-Deckel) ----------
# Interner Cache, KEIN Dialog-Key (nicht in ALLE_KEYS, erscheint nicht in
# der Admin-Config-Ansicht): die beim letzten Lauf gemessene verfügbare
# Schirm-Geometrie auf 100-%-Basis. Nötig, weil QT_SCALE_FACTOR VOR der
# QApplication stehen muss, QScreen aber erst danach existiert — ohne
# Cache könnte der Start nicht gegen den Schirm deckeln.

KEY_SCHIRM_BASIS = "ui_intern/schirm_basis_100"


def speichere_schirm_basis(w: float, h: float,
                           settings: QSettings | None = None) -> None:
    s = settings or qsettings()
    s.setValue(KEY_SCHIRM_BASIS, f"{int(w)}x{int(h)}")
    s.sync()


def lese_schirm_basis(settings: QSettings | None = None):
    """-> (w, h) auf 100-%-Basis oder None (noch nie gelaufen/defekt)."""
    s = settings or qsettings()
    roh = s.value(KEY_SCHIRM_BASIS)
    if not roh:
        return None
    try:
        w, h = str(roh).lower().split("x", 1)
        return (int(float(w)), int(float(h)))
    except (ValueError, TypeError):
        return None


# ---------- Start-Umgebung (VOR QApplication-Erzeugung) ----------

def env_vorbereiten(ui: dict, settings: QSettings | None = None) -> dict:
    """Setzt QT_SCALE_FACTOR und QT_IM_MODULE aus den effektiven Werten —
    muss VOR der QApplication-Erzeugung laufen (app.run tut das). Eine von
    aussen gesetzte Variable wird respektiert, nie überschrieben.

    Skalierungs-Deckel (Auflage Checkpoint 2): ANGEWENDET wird die grösste
    Stufe <= dem gespeicherten Wert, mit der das Mindestfenster in die beim
    letzten Lauf gemessene Schirm-Basis passt. Der GESPEICHERTE Wert bleibt
    unangetastet — hängt die Station wieder am grossen Schirm, gilt er
    wieder. Der Operator erfährt von der Begrenzung sichtbar
    (app._skalierungs_kontrolle zeigt eine Info-Box), nie still.

    -> {"gesetzt": [Variablennamen], "scale_gespeichert": int,
        "scale_angewendet": int}"""
    gesetzt = []
    gespeichert = int(ui.get("scale_percent") or 100)
    scale = gespeichert
    if scale not in SCALE_STUFEN:
        # Nur validierte Stufen erreichen den Faktor: ein von Hand in
        # Registry/plist editierter Unsinnswert (z.B. 1000) machte die UI
        # beim Start unbenutzbar — und die Einstellung läge dann NUR in
        # der unbenutzbaren UI (Review-Befund W4, 2026-08-12).
        scale = 100
    basis = lese_schirm_basis(settings)
    if scale != 100 and basis is not None:
        erlaubt = erlaubte_skalierungen(
            int(ui.get("window_min_width") or 1280),
            int(ui.get("window_min_height") or 800), basis[0], basis[1])
        if scale not in erlaubt:
            scale = max(s for s in erlaubt if s <= scale)   # 100 ist immer da
    if scale != 100 and "QT_SCALE_FACTOR" not in os.environ:
        os.environ["QT_SCALE_FACTOR"] = f"{scale / 100.0:g}"
        gesetzt.append("QT_SCALE_FACTOR")
    if ui.get("touch_mode") and "QT_IM_MODULE" not in os.environ:
        # Bildschirmtastatur (Qt Virtual Keyboard, im PySide6-Wheel als
        # Plattform-Input-Context-Plugin enthalten). Nur mit Touch-Modus —
        # und prinzipbedingt erst ab dem nächsten Start wirksam.
        os.environ["QT_IM_MODULE"] = "qtvirtualkeyboard"
        gesetzt.append("QT_IM_MODULE")
    return {"gesetzt": gesetzt, "scale_gespeichert": gespeichert,
            "scale_angewendet": scale}
