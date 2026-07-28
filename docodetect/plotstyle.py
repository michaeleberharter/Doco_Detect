"""Zentraler Plot-Stil fuer alle PNG-Artefakte (analysis.py und
enrollment_sheet.py) – damit Diagnoseblatt und Auswertungs-Grafiken als EINE
Familie lesen.

Stil nach Vorbild wissenschaftlicher Artikel: duenne Achsen, top/right-Spines
aus, serifenlos 7-9 pt, rahmenlose Legenden im Panel, Colorbars rechts
beschriftet, >= 200 dpi, Panel-Labels ausserhalb der Achsen.

Farben: PALETTE ist die validierte kategoriale Referenzpalette der dataviz-
Regeln (colorblind-sicher; kategoriale Farben in FESTER Reihenfolge, NIE
zyklisch – ab der 9. Serie in "Andere" falten oder Small Multiples; fuer
Streudiagramme sind nur die ersten DREI Slots all-pairs-sicher). Sequenziell =
viridis (Index/Ordnung/Magnitude), divergierend = RdBu_r (signierte z mit
Neutralmitte). Keine Regenbogen-Skalen.

Nur Darstellung – keine Kennzahl, keine Schwelle wird hier berechnet.
"""

from __future__ import annotations

import matplotlib
from cycler import cycler

# Validierte kategoriale Referenzpalette (dataviz references/palette.md, light).
# Die REIHENFOLGE ist der CVD-Sicherheitsmechanismus, nicht kosmetisch – nicht
# umsortieren. Streudiagramme/all-pairs: nur die ersten drei Slots sind
# all-pairs-sicher, darueber falten/faceten.
PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100",
           "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
SEQ = "viridis"          # sequenziell: Index/Ordnung/Magnitude
DIV = "RdBu_r"           # divergierend: signierte z (Neutralmitte)
OUTLIER = "#d62728"      # kontrastierendes Rot fuer den EINEN markierten Ausreisser

_RC = {
    "font.family": "sans-serif",
    "font.size": 8,
    "axes.titlesize": 8,
    "axes.labelsize": 8,
    "axes.linewidth": 0.6,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": False,
    "grid.linewidth": 0.4,
    "grid.color": "0.85",
    "grid.alpha": 0.7,
    "xtick.labelsize": 7,
    "ytick.labelsize": 7,
    "xtick.major.size": 2.5,
    "ytick.major.size": 2.5,
    "xtick.major.width": 0.6,
    "ytick.major.width": 0.6,
    "legend.fontsize": 7,
    "legend.frameon": False,
    "figure.dpi": 110,
    "savefig.dpi": 200,
}


def _params() -> dict:
    return {**_RC, "axes.prop_cycle": cycler(color=PALETTE)}


def apply_style() -> None:
    """rcParams global setzen – fuer CLI-Laeufe (analyze), die viele Figuren
    hintereinander erzeugen."""
    matplotlib.rcParams.update(_params())


def style_context():
    """Scoped-Variante: `with plotstyle.style_context(): ...`. Aendert den
    globalen rcParams-Zustand nicht dauerhaft (fuer Aufrufer wie den
    Qt-Dialog, die im selben Prozess weiterlaufen)."""
    import matplotlib.pyplot as plt
    return plt.rc_context(_params())


def panel_label(ax, letter: str) -> None:
    """Fettes Panel-Label oben links, ausserhalb der Achsen (Punkt-Offset,
    robust gegen Panelbreite)."""
    ax.annotate(letter, xy=(0, 1), xycoords="axes fraction",
                xytext=(-22, 9), textcoords="offset points",
                fontsize=11, fontweight="bold", va="bottom", ha="left")
