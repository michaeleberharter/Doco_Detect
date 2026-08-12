"""Touch-Modus: Mindest-Trefferflächen + kinetisches Scrollen (QScroller).

Explizite Einstellung (Stationseigenschaft), KEINE Auto-Erkennung — und
unabhängig von der UI-Skalierung schaltbar (Auftrag 2026-08-12). Der Modus
greift live in zwei Mechaniken:

1. QSS-Zusatzblock: wird von app.apply_theme ans Stylesheet angehängt
   (qss_zusatz liest die App-Property `docoTouch`). Nur Grössen, keine
   Farben — deshalb themefrei und ohne $token.
2. QScroller auf allen Scrollflächen (Report-Browser, Kandidaten-/Ergebnis-
   spalte, Tabellen, Thumbnail-Leiste): bestehende Widgets sofort, künftig
   erzeugte (Dialoge, Admin-Fenster) über einen App-EventFilter beim
   Polish. LeftMouseButtonGesture deckt Maus UND Touch ab; kurze Taps
   bleiben Klicks (QScroller-Distanzschwelle).

Die Bildschirmtastatur gehört NICHT hierher: QT_IM_MODULE muss vor der
QApplication-Erzeugung stehen (settings.env_vorbereiten) und wirkt darum
erst nach Neustart — der Dialog benennt das genau so.
"""

from __future__ import annotations

import weakref
from string import Template

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QAbstractScrollArea, QApplication, QScroller

# Die EINE Trefferflächen-Zahl (Auftrag: ~48 px) — auch dialog_shell liest
# sie (Close-Button hat setFixedSize, das gewinnt über jede QSS-Regel).
MIN_TREFFER_PX = 48

# Nur Geometrie: Trefferflächen, breitere Scrollbalken, höhere Zeilen in
# Listen/Tabellen/Bäumen. Der railButton (58 px fix) und die Aktionsleiste
# (72 px) erfüllen die Vorgabe bereits ohne Zusatz.
_TOUCH_QSS = Template("""
QPushButton { min-height: ${px}px; }
QToolButton { min-height: ${px}px; min-width: ${px}px; }
QComboBox, QSpinBox, QLineEdit { min-height: ${px}px; }
QCheckBox, QRadioButton { min-height: ${px}px; }
QCheckBox::indicator, QRadioButton::indicator { width: 28px; height: 28px; }
QScrollBar:vertical { width: 18px; }
QScrollBar:horizontal { height: 18px; }
QTableWidget::item, QListWidget::item, QTreeWidget::item {
    padding: 10px 6px; }
QTabBar::tab { min-height: ${px}px; padding: 6px 18px; }
""").substitute(px=MIN_TREFFER_PX)


def ist_aktiv(app: QApplication | None = None) -> bool:
    app = app or QApplication.instance()
    return bool(app.property("docoTouch")) if app is not None else False


def qss_zusatz(app: QApplication | None = None) -> str:
    """Von app.apply_theme angehängt — so überlebt der Block jeden
    Theme-Wechsel, ohne dass zwei Stellen Stylesheets verwalten."""
    return _TOUCH_QSS if ist_aktiv(app) else ""


# Buchführung der gegrabbten Viewports. Nötig, weil die QScroller-API den
# Aus-Zustand nicht abfragbar macht (hasScroller bleibt nach ungrabGesture
# True — es meldet nur die Existenz des Scroller-Objekts). Das WeakSet
# macht grab idempotent, ungrab vollständig und den Zustand testbar;
# zerstörte Widgets fallen von selbst heraus.
_gegrabbt: "weakref.WeakSet" = weakref.WeakSet()


def _grab(area: QAbstractScrollArea) -> None:
    vp = area.viewport()
    if vp not in _gegrabbt:
        QScroller.grabGesture(vp, QScroller.LeftMouseButtonGesture)
        _gegrabbt.add(vp)


def ist_gegrabbt(area: QAbstractScrollArea) -> bool:
    """Testsonde: scrollt diese Fläche kinetisch?"""
    return area.viewport() in _gegrabbt


class _ScrollerFilter(QObject):
    """Rüstet Scrollflächen nach, die NACH dem Einschalten entstehen
    (Einstellungs-/Einlern-Dialog, Admin-Fenster). Polish feuert genau
    einmal pro Widget nach der Erzeugung."""

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt-API)
        if event.type() == QEvent.Polish and isinstance(obj,
                                                        QAbstractScrollArea):
            _grab(obj)
        return False


def anwenden(app: QApplication, on: bool) -> None:
    """Touch-Modus live schalten: Property + Stylesheet (über apply_theme)
    + QScroller auf allen bestehenden Scrollflächen, Filter für künftige.

    Der Filter hängt als KIND an der App (findChild), nicht an einem
    Modul-Global: ein Global überlebte die QApplication und zeigte nach
    deren Zerstörung auf ein totes C++-Objekt — auf einer Folge-App wäre
    die Nachrüstung dann stumm tot (Review-Befund W1, 2026-08-12)."""
    app.setProperty("docoTouch", bool(on))
    if on:
        for w in app.allWidgets():
            if isinstance(w, QAbstractScrollArea):
                _grab(w)
    else:
        for vp in list(_gegrabbt):
            QScroller.ungrabGesture(vp)
        _gegrabbt.clear()
    flt = app.findChild(_ScrollerFilter)
    if on and flt is None:
        app.installEventFilter(_ScrollerFilter(app))
    elif not on and flt is not None:
        app.removeEventFilter(flt)
        flt.setParent(None)
        flt.deleteLater()
    # Stylesheet mit/ohne Zusatzblock neu setzen (inkl. Repolish).
    from .app import apply_theme
    choice = app.property("docoThemeChoice")
    from . import theme as theme_mod
    apply_theme(app, choice or theme_mod.DEFAULT_THEME)
