"""Design-Tokens des UI-Redesigns: EINE Quelle für QSS, QPalette und die
selbst gezeichneten Flächen (Vorschau-Overlay, Icons, Toleranzbalken).

Warum diese Datei existiert: Qt-Stylesheets kennen KEINE Variablen. Der
Entwurf (design/ui-redesign/) ist aber vollständig über `var(--token)` in
zwei Sätzen (dunkel/hell) aufgebaut. Deshalb liegen die Tokens hier als
Python-Dict und `style.qss` ist ein `string.Template` mit `$token`-Platz-
haltern, das beim Laden befüllt wird. Ein Theme-Wechsel ist damit ein
erneutes `setStyleSheet` – und das helle Theme kostet nur ein zweites Dict.

Halbtransparente Tokens des Entwurfs (`accentWeak` & Co., dort als `rgba()`)
werden hier auf ihren bekannten Untergrund GERECHNET und als deckendes Hex
ausgegeben: Qt behandelt `rgba()` in Stylesheets je nach Property
unterschiedlich zuverlässig, ein deckender Wert ist vorhersehbar. Wer eine
echte Transparenz braucht (Overlay über dem Live-Bild), nimmt `rgba()`.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

# Rohtokens exakt aus design/ui-redesign/README.md ("Design Tokens").
# Werte als (Farbe, Alpha, Untergrund-Token) sind im Entwurf rgba() und
# werden von resolve() auf den Untergrund gerechnet.
_DARK = {
    "bg": "#0f141b",
    "stage": "#05070b",
    "panel": "#161c25",
    "panel2": "#1b2431",
    "line": "#28303d",
    "text": "#e8edf3",
    "dim": "#8b97a8",
    "faint": "#5c6675",
    "accent": "#3d7dfb",
    "accentH": "#5b93ff",
    "accentWeak": ("#3d7dfb", 0.16, "bg"),
    "ok": "#31b46f",
    "okWeak": ("#31b46f", 0.15, "bg"),
    "warn": "#e0a63a",
    "warnWeak": ("#e0a63a", 0.15, "bg"),
    "bad": "#e2604a",
    "badWeak": ("#e2604a", 0.15, "bg"),
    "track": "#0e141c",
    "plate": "#c9ced6",
}

_LIGHT = {
    "bg": "#eef1f5",
    "stage": "#dfe4ea",
    "panel": "#ffffff",
    "panel2": "#f4f7fa",
    "line": "#e2e7ee",
    "text": "#141a22",
    "dim": "#5b6675",
    "faint": "#98a2b0",
    "accent": "#2f6fe0",
    "accentH": "#1f5fd0",
    "accentWeak": ("#2f6fe0", 0.12, "bg"),
    "ok": "#178a52",
    "okWeak": ("#178a52", 0.11, "bg"),
    "warn": "#b9781f",
    "warnWeak": ("#b9781f", 0.12, "bg"),
    "bad": "#c8472f",
    "badWeak": ("#c8472f", 0.12, "bg"),
    "track": "#eef1f5",
    "plate": "#cbd1d9",
}

_RAW = {"dark": _DARK, "light": _LIGHT}

DEFAULT_THEME = "dark"

# Erkanntes Objekt im Vorschau-Overlay – in beiden Themes gleich (Entwurf).
OBJECT_FILL = "#6fa8ef"
OBJECT_STROKE = "#3f7fd6"


def _rgb(hex_color: str) -> tuple:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def blend(fg: str, alpha: float, bg: str) -> str:
    """`fg` mit Deckkraft `alpha` über `bg` – ergibt ein deckendes Hex.
    Genau das, was der Browser beim rgba()-Token des Entwurfs zeigt."""
    f, b = _rgb(fg), _rgb(bg)
    m = [round(f[i] * alpha + b[i] * (1.0 - alpha)) for i in range(3)]
    return "#{:02x}{:02x}{:02x}".format(*m)


@lru_cache(maxsize=None)
def _resolved(name: str) -> dict:
    raw = _RAW.get(name) or _RAW[DEFAULT_THEME]
    out: dict = {k: v for k, v in raw.items() if isinstance(v, str)}
    for key, value in raw.items():
        if not isinstance(value, str):
            color, alpha, base = value
            out[key] = blend(color, alpha, out[base])
    return out


def resolve(name: str = DEFAULT_THEME) -> dict:
    """Token-Dict eines Themes, alle Werte als deckendes `#rrggbb`.

    Die Auflösung ist gecacht: `PreviewWidget.paintEvent` fragt das Theme bei
    JEDEM Frame ab (preview_fps), da darf kein Blenden pro Bild anfallen.
    Zurück kommt eine Kopie – wer sie verändert, beschädigt den Cache nicht."""
    return dict(_resolved(name))


def theme_names() -> list:
    return list(_RAW)


@dataclass(frozen=True)
class Theme:
    """Aufgelöstes Theme: Tokens + Zustandszuordnung.

    `tone_color` ist die einzige Stelle, an der die VIER Anzeigezustände auf
    Farben abgebildet werden (accept/ambiguous/reject/border) – Widgets
    fragen hier, statt Farben selbst zu kennen."""
    name: str
    tokens: dict

    def __getitem__(self, key: str) -> str:
        return self.tokens[key]

    @property
    def is_dark(self) -> bool:
        return self.name == "dark"

    def tone_color(self, tone: str) -> str:
        """accept -> ok, ambiguous/border -> warn, reject -> bad.

        `border` (Objekt berührt den Bildrand) teilt sich die Amber-Farbe mit
        `ambiguous`, ist aber ein eigener Zustand: kein Reject-Look, weil die
        Messung nicht falsch, sondern nur nicht durchführbar ist."""
        return self.tokens[_TONE_TOKEN.get(tone, "dim")]

    def tone_weak(self, tone: str) -> str:
        return self.tokens[_TONE_TOKEN.get(tone, "dim") + "Weak"]


# Zustand -> Farbtoken. 'border' bewusst amber wie 'ambiguous' (Auftrag
# 2026-07-20: eigener vierter Zustand, aber kein Reject-Rot).
_TONE_TOKEN = {
    "accept": "ok",
    "ambiguous": "warn",
    "border": "warn",
    "reject": "bad",
}

TONES = tuple(_TONE_TOKEN)


@lru_cache(maxsize=None)
def load(name: str = DEFAULT_THEME) -> Theme:
    """Aufgelöstes Theme (gecacht – siehe resolve())."""
    name = name if name in _RAW else DEFAULT_THEME
    return Theme(name=name, tokens=_resolved(name))
