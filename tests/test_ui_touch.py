"""Tests des Touch-Modus (docodetect/ui_qt/touch.py, 2026-08-12).

Mindest-Trefferflächen (~48 px) über den QSS-Zusatzblock, kinetisches
Scrollen per QScroller (bestehende UND nachträglich erzeugte
Scrollflächen), Theme-Wechsel erhält den Zusatzblock, Close-Button der
Dialog-Hülle. Explizite Einstellung — es gibt bewusst keine
Auto-Erkennung, die getestet werden könnte.

Läuft im Test-Regime als EIGENER pytest-Aufruf.

Run: pytest tests/test_ui_touch.py -v
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import (QPushButton, QScrollArea, QScroller,  # noqa: E402
                               QTableWidget)

from docodetect.ui_qt import theme as theme_mod  # noqa: E402
from docodetect.ui_qt import touch  # noqa: E402
from docodetect.ui_qt.app import apply_theme, make_app  # noqa: E402


@pytest.fixture
def qapp():
    app = make_app(theme="dark")            # Theme-Pinnung: nie "system"
    yield app
    touch.anwenden(app, False)
    apply_theme(app, theme_mod.DEFAULT_THEME)


def test_qss_zusatz_haengt_am_touch_zustand(qapp):
    assert not touch.ist_aktiv(qapp)
    assert "min-height: 48px" not in qapp.styleSheet()
    touch.anwenden(qapp, True)
    assert touch.ist_aktiv(qapp)
    assert "min-height: 48px" in qapp.styleSheet()
    touch.anwenden(qapp, False)
    assert "min-height: 48px" not in qapp.styleSheet()


def test_theme_wechsel_erhaelt_den_touch_block(qapp):
    """apply_theme setzt das Stylesheet komplett neu — der Zusatzblock
    muss den Wechsel überleben (qss_zusatz wird dort angehängt)."""
    touch.anwenden(qapp, True)
    apply_theme(qapp, "light")
    assert "min-height: 48px" in qapp.styleSheet()
    apply_theme(qapp, "dark")
    assert "min-height: 48px" in qapp.styleSheet()


def test_buttons_erreichen_48px_im_touch_modus(qapp):
    b = QPushButton("Leeren")
    try:
        b.ensurePolished()
        normal = b.sizeHint().height()
        touch.anwenden(qapp, True)
        b.ensurePolished()
        assert b.sizeHint().height() >= 48, (
            f"Trefferfläche {b.sizeHint().height()} px < 48 px")
        assert b.sizeHint().height() >= normal
    finally:
        b.deleteLater()


def test_scroller_greift_bestehende_flaechen(qapp):
    """Ein/Aus über die touch-Buchführung: die QScroller-API selbst macht
    den Aus-Zustand nicht abfragbar (hasScroller bleibt nach ungrab True),
    das WeakSet in touch.py treibt die echten grab/ungrab-Aufrufe."""
    area = QTableWidget(3, 2)
    try:
        assert not touch.ist_gegrabbt(area)
        assert not QScroller.hasScroller(area.viewport())
        touch.anwenden(qapp, True)
        assert touch.ist_gegrabbt(area)
        assert QScroller.hasScroller(area.viewport())   # wirklich gegrabbt
        touch.anwenden(qapp, False)
        assert not touch.ist_gegrabbt(area)
    finally:
        area.deleteLater()


def test_scroller_greift_nachtraeglich_erzeugte_flaechen(qapp):
    """Dialoge und Admin-Fenster entstehen NACH dem Einschalten — der
    Polish-Filter muss sie ohne Zutun der Erzeugungsstellen nachrüsten."""
    touch.anwenden(qapp, True)
    area = QScrollArea()
    try:
        area.ensurePolished()
        assert touch.ist_gegrabbt(area)
    finally:
        area.deleteLater()
        touch.anwenden(qapp, False)


def test_dialog_close_button_waechst_im_touch_modus(qapp):
    from docodetect.ui_qt.widgets.dialog_shell import DialogShell

    d = DialogShell("gear", "Test", "Ok")
    try:
        assert d.header.close_button.width() == 30
    finally:
        d.deleteLater()

    touch.anwenden(qapp, True)
    d2 = DialogShell("gear", "Test", "Ok")
    try:
        assert d2.header.close_button.width() == 48
    finally:
        d2.deleteLater()


def test_railbuttons_erfuellen_48px_bereits(qapp):
    """Die Icon-Schiene (58 px fix) braucht keinen Zusatz — Regression
    dagegen, dass jemand die Buttons unter die Trefferfläche schrumpft."""
    from docodetect.ui_qt.widgets.tool_rail import ToolRail

    rail = ToolRail()
    try:
        for key in ("identify", "background", "calibrate", "enroll"):
            b = rail.button(key)
            assert b.width() >= 48 and b.height() >= 48
    finally:
        rail.deleteLater()
