"""IBM Plex Sans/Mono aus assets/fonts/ laden – mit System-Fallback.

Die Schriften liegen als statische OFL-TTFs im Repo (assets/fonts/, Lizenz
daneben). Bewusst STATISCHE Schnitte statt der Variable Fonts von Google
Fonts: Qt wählt aus einer Variable-Font-Datei nicht zuverlässig das
gewünschte Gewicht, statische Dateien tun das immer.

Gebündelt sind nur die vom Entwurf benötigten Schnitte:
    Sans Regular/Medium/SemiBold/Bold (400/500/600/700)
    Mono Regular/SemiBold            (400/600, alle Zahlen und Codes)

ABWEICHUNG vom Entwurf: dieser nennt Gewicht 800 für das große
„Identifizieren" und den Messwert im Nicht-gefunden-Zustand. IBM Plex Sans
hat kein 800 – die Familie endet bei Bold 700; dort steht deshalb 700.

Schlägt das Laden fehl (Datei fehlt, Qt ohne Font-Backend), liefert
`families()` die System-Stacks zurück: die App startet dann normal, nur mit
anderer Schrift.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QFontDatabase

# Fallback-Stacks, falls die gebündelten Dateien nicht geladen werden können.
FALLBACK_UI = "Segoe UI, SF Pro Text, Helvetica Neue, Arial, sans-serif"
FALLBACK_MONO = "Menlo, Consolas, DejaVu Sans Mono, monospace"

UI_FAMILY = "IBM Plex Sans"
MONO_FAMILY = "IBM Plex Mono"

_FILES = (
    "IBMPlexSans-Regular.ttf",
    "IBMPlexSans-Medium.ttf",
    "IBMPlexSans-SemiBold.ttf",
    "IBMPlexSans-Bold.ttf",
    "IBMPlexMono-Regular.ttf",
    "IBMPlexMono-SemiBold.ttf",
)

_loaded: dict | None = None      # Ergebnis-Cache (einmal je Prozess)


def assets_dir() -> Path:
    """<projekt>/assets/fonts – ui_qt liegt in docodetect/, also zwei hoch."""
    return Path(__file__).resolve().parents[2] / "assets" / "fonts"


def load_fonts() -> dict:
    """Alle gebündelten Schnitte registrieren.

    -> {"ui": Familienname, "mono": Familienname, "loaded": n, "missing": [...]}
    Mehrfachaufrufe sind billig (Cache) – wichtig, weil `make_app()` in Tests
    oft läuft."""
    global _loaded
    if _loaded is not None:
        return _loaded

    d = assets_dir()
    families: set = set()
    missing: list = []
    n = 0
    for name in _FILES:
        p = d / name
        if not p.exists():
            missing.append(name)
            continue
        fid = QFontDatabase.addApplicationFont(str(p))
        if fid == -1:
            missing.append(name)
            continue
        n += 1
        families.update(QFontDatabase.applicationFontFamilies(fid))

    _loaded = {
        "ui": UI_FAMILY if UI_FAMILY in families else FALLBACK_UI,
        "mono": MONO_FAMILY if MONO_FAMILY in families else FALLBACK_MONO,
        "loaded": n,
        "missing": missing,
    }
    if missing:
        print(f"[ui] {len(missing)} Schriftschnitt(e) nicht geladen "
              f"({', '.join(missing)}) – System-Schrift wird verwendet.")
    return _loaded


def families() -> dict:
    """{"ui": ..., "mono": ...} für die QSS-Platzhalter $fontUi/$fontMono."""
    f = load_fonts()
    return {"ui": f["ui"], "mono": f["mono"]}


def reset_cache() -> None:
    """Nur für Tests: nächster `load_fonts()` misst wieder echt."""
    global _loaded
    _loaded = None
