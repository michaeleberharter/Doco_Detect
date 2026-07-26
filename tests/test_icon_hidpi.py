"""High-DPI-Regression für die Strichicons (docodetect/ui_qt/icons.py).

Nagelt die Fehlerklasse fest, bei der ``icons.pixmap()`` das Icon bei dpr > 1
nur zum linken oberen Viertel rendert (doppelte dpr-Skalierung: Backing UND
Ziel-Rect mit dpr multipliziert). Zwei Wächter:

1. Ein bei dpr=2 gerendertes Icon, auf die dpr=1-Größe herunterskaliert, ist
   deckungsgleich mit dem direkt bei dpr=1 gerenderten (Alpha-Kanal, Toleranz
   für Antialiasing). Beim Bug zeigt das dpr=2-Icon nur ein Viertel → nach dem
   Herunterskalieren grob abweichend → harter Fehlschlag.
2. Die Ink-Bounding-Box stößt nicht an Rechts-/Unterkante an: der Bug schiebt
   die überzeichnete Grafik über den Rand, sodass sie dort abgeschnitten wird.

Offscreen wie die übrigen Qt-Tests; PySide6 ist optional (Skip statt Fehler).
"""
import math
import os
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import QSize, Qt        # noqa: E402
from PySide6.QtGui import QIcon, QImage     # noqa: E402

from docodetect.ui_qt import icons          # noqa: E402

# Windows skaliert auf 125 %/175 %: 18*1.25=22.5, 18*1.75=31.5 sind nicht
# ganzzahlig – der ceil-Fall, den macOS-dprs {1,1.5,2,2.5,3} nie treffen.
_WINDOWS_DPRS = (1.25, 1.75)


@pytest.fixture
def qapp():
    from docodetect.ui_qt.app import make_app
    return make_app()


def _alpha(img: QImage) -> np.ndarray:
    """Alpha-Kanal einer QImage als (h, w)-int16-Array."""
    img = img.convertToFormat(QImage.Format_ARGB32)
    w, h = img.width(), img.height()
    buf = img.constBits()
    arr = np.frombuffer(buf, np.uint8).reshape(h, img.bytesPerLine())
    return arr[:, : w * 4].reshape(h, w, 4)[:, :, 3].astype(np.int16)


def test_hidpi_pixmap_has_physical_backing(qapp):
    """dpr skaliert den Backing-Store, nicht die logische Größe."""
    px1 = icons.pixmap("scan", 24, "#ff0000", 1.0)
    px2 = icons.pixmap("scan", 24, "#ff0000", 2.0)
    assert (px1.width(), px1.height()) == (24, 24)
    assert (px2.width(), px2.height()) == (48, 48)
    assert px2.devicePixelRatio() == pytest.approx(2.0)


def test_hidpi_matches_lowdpi(qapp):
    """Herunterskaliertes dpr=2-Icon ~ direktes dpr=1-Icon (jedes Icon)."""
    for name in icons.NAMES:
        px1 = icons.pixmap(name, 24, "#ff0000", 1.0)
        px2 = icons.pixmap(name, 24, "#ff0000", 2.0)

        img2 = px2.toImage()
        img2.setDevicePixelRatio(1.0)          # rohe Pixel, nicht logisch
        down = img2.scaled(24, 24, Qt.IgnoreAspectRatio,
                           Qt.SmoothTransformation)

        a1 = _alpha(px1.toImage())
        a2 = _alpha(down)
        mad = float(np.mean(np.abs(a1 - a2)))
        assert mad < 12.0, (
            f"{name}: dpr=2 weicht vom dpr=1-Icon ab (MAD {mad:.1f}) – "
            f"Verdacht auf Viertel-Crop / Doppel-Skalierung")


def test_ink_not_clipped_at_edge(qapp):
    """Ink stößt nicht an Rechts-/Unterkante an – sonst wäre sie angeschnitten.

    'scan' hat korrekt gerendert Rand auf allen Seiten; beim Doppel-Skalier-Bug
    läuft die vergrößerte Grafik über die untere/rechte Kante und wird dort
    abgeschnitten (Ink genau bis zur letzten Pixelreihe)."""
    a = _alpha(icons.pixmap("scan", 24, "#ff0000", 2.0).toImage())  # 48x48
    ys, xs = np.where(a > 24)
    assert xs.size, "kein Icon gezeichnet"
    h, w = a.shape
    assert xs.max() <= w - 2, "Ink stößt an die rechte Kante (Anschnitt)"
    assert ys.max() <= h - 2, "Ink stößt an die untere Kante (Anschnitt)"


@pytest.mark.parametrize("dpr", _WINDOWS_DPRS)
@pytest.mark.parametrize("size", (18, 20, 24))
def test_fractional_dpr_backing_and_margin(qapp, size, dpr):
    """Windows-Skalen (krummes size*dpr): ceil rundet den Backing AUF, nie ab.

    Der Slack (Backing - size*dpr) bleibt < 1 physischem Pixel, die logische
    Größe (Backing/dpr) weicht damit nur sub-pixelweit von `size` ab und die
    Ink wird nirgends abgeschnitten. Wir behalten dpr (Option A): würde man
    stattdessen setDevicePixelRatio(Backing/size) setzen, entspräche die
    Pixmap-dpr nicht mehr der Screen-dpr und Qt würde beim Compositing neu
    skalieren (2 % Resample-Unschärfe) – genau der Defekt, den wir beheben."""
    px = icons.pixmap("camera", size, "#000000", dpr)
    backing = math.ceil(size * dpr)
    assert px.width() == backing and px.height() == backing
    assert px.devicePixelRatio() == pytest.approx(dpr)

    slack = backing - size * dpr            # transparenter Rand rechts/unten
    assert 0 <= slack < 1.0, f"ceil-Slack {slack} px außerhalb [0,1)"
    logical = backing / dpr
    assert abs(logical - size) < 1.0, f"logische Größe {logical} weit von {size}"

    a = _alpha(px.toImage())
    ys, xs = np.where(a > 24)
    assert xs.size, "kein Icon gezeichnet"
    assert xs.max() <= backing - 2 and ys.max() <= backing - 2, "Ink angeschnitten"


def test_icon_engine_renders_at_target_dpr(qapp):
    """icon() -> QIconEngine muss bei dpr=2 physisch 2× rastern, nicht eine
    dpr=1-Pixmap hochskalieren – das war die Schienen-Unschärfe.

    Alte Implementierung (QIcon aus fester dpr=1-Pixmap): pixmap(QSize(20,20),
    2.0) liefert 20×20 @dpr=1 → dieser Test fällt hart (Dimension UND dpr)."""
    got = icons.icon("target", 20, "#ff0000").pixmap(QSize(20, 20), 2.0)
    assert (got.width(), got.height()) == (40, 40), \
        "Engine liefert keine physisch verdoppelte Pixmap (hochskalierte dpr=1?)"
    assert got.devicePixelRatio() == pytest.approx(2.0)

    # scharf? deckungsgleich mit dem direkt bei dpr=2 gemalten 40px-Icon.
    ref = icons.pixmap("target", 20, "#ff0000", 2.0)
    mad = float(np.mean(np.abs(_alpha(got.toImage()) - _alpha(ref.toImage()))))
    assert mad < 6.0, f"Engine-Pixmap nicht deckungsgleich mit Direktrender (MAD {mad:.1f})"
