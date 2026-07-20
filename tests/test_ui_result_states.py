"""Tests der vier Anzeigezustände (Phase 3 des UI-Redesigns):
accept, ambiguous, border, reject – dazu Toleranzbalken, Erkennungsrahmen
und die Richtig/Falsch-Bewertung.

Offscreen wie die übrigen Qt-Tests.

Run: pytest tests/test_ui_result_states.py -v
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from docodetect.matcher import CandidateReport, MatchReport  # noqa: E402
from docodetect.ui_qt import theme as theme_mod  # noqa: E402
from docodetect.ui_qt.app import apply_theme, make_app  # noqa: E402

TOL = 6.0


@pytest.fixture
def qapp():
    app = make_app()
    yield app
    apply_theme(app, theme_mod.DEFAULT_THEME)


def make_cfg(tmp_path):
    return {
        "camera": {"width": 1920, "height": 1080},
        "calibration": {
            "file": str(tmp_path / "calibration.json"),
            "background_file": str(tmp_path / "background.png"),
            "aruco_dict": "DICT_4X4_50", "marker_id": 0, "marker_size_mm": 72.5,
        },
        "geometry": {"camera_height_mm": 300.0},
        "matching": {"diameter_tolerance_mm": TOL, "top_k": 3},
        "paths": {"db_file": str(tmp_path / "db.sqlite3")},
        "ui": {"preview_fps": 5, "confirm_sound": False},
        "stage2": {"enabled": False},
    }


@pytest.fixture
def win(qapp, tmp_path):
    from docodetect.ui_qt.main_window import MainWindow
    w = MainWindow(make_cfg(tmp_path))
    yield w
    w.close()


def cand(nr="ART-1", name="Teller 18", nominal=180.0, measured=181.0,
         posterior=0.92, err=1.0):
    return CandidateReport(
        article_number=nr, name=name, nominal_size_mm=nominal, height_mm=0.0,
        corrected_diameter_mm=measured, geometry_error_mm=err,
        has_references=True, n_shots=5, posterior=posterior,
        log_score=-0.1, max_abs_z=0.5)


def report(decision, candidates=(), measured=None, touches=False,
           contour=None, size=None):
    return MatchReport(decision=decision, message="Testreport",
                       candidates=list(candidates), measured=measured or {},
                       touches_border=touches, contour=contour,
                       image_size=size)


# ---------- Zustandszuordnung ----------

def test_vier_zustaende_und_border_schlaegt_reject(win):
    t = win.report_tone
    assert t(report("accept", [cand()])) == "accept"
    assert t(report("ambiguous", [cand()])) == "ambiguous"
    assert t(report("reject")) == "reject"
    # Randberuehrung kommt als reject aus der Pipeline, ist aber ein
    # EIGENER Anzeigezustand – sonst saehe eine Platzierungsfrage aus wie
    # eine Ablehnung.
    assert t(report("reject", touches=True)) == "border"


def test_border_ist_amber_und_nie_rot(win):
    t = theme_mod.load("dark")
    assert t.tone_color("border") == t["warn"]
    assert t.tone_color("border") != t.tone_color("reject")


# ---------- ACCEPT ----------

def test_accept_zeigt_karte_toleranzbalken_und_bewertung(win):
    win._show_report(report("accept", [cand(), cand("ART-2", "Teller 20",
                                                    posterior=0.06)]))
    assert "Automatisch übernommen" in win.headline_text()
    assert win.result_header.value.text() == "92 %"

    from docodetect.ui_qt.widgets.result_card import ResultCard
    cards = win.cards_box.findChildren(ResultCard)
    assert len(cards) == 1
    assert cards[0].property("tone") == "accept"
    assert cards[0].gauge.in_tolerance

    assert win._verdict_bar is not None, "Bewertung fehlt bei ACCEPT"
    assert win.rank_lines_count() == 1                  # Platz 2


def test_accept_karte_zeigt_weiter_die_zentralen_helferstrings(win):
    """Architekturregel: Qt und Streamlit zeigen denselben mm-Text."""
    from docodetect.pipeline import format_delta, format_diameter
    from docodetect.ui_qt.widgets.result_card import ResultCard

    c = cand()
    win._show_report(report("accept", [c]))
    texts = win.cards_box.findChildren(ResultCard)[0].all_text()
    assert format_diameter(c) in texts
    assert format_delta(c, win.cfg) in texts


def test_teilscores_sind_eingeklappt_aber_nicht_verschwunden(win):
    from docodetect.ui_qt.widgets.result_card import ResultCard

    win._show_report(report("accept", [cand()]))
    card = win.cards_box.findChildren(ResultCard)[0]
    assert not card.details_box.isVisible(), "Details sollen zu starten"
    card.details_toggle.setChecked(True)
    assert card.details_box.isVisibleTo(card)
    assert set(card.channel_bars()) == {"geometry", "color", "shape"}


# ---------- AMBIGUOUS ----------

def test_ambiguous_ist_amber_mit_anklickbaren_kandidaten(win):
    from docodetect.ui_qt.widgets.result_card import CandidateRow, MessageCard

    win._show_report(report("ambiguous", [cand(), cand("ART-2", "Teller 20",
                                                       posterior=0.4)]))
    assert "Bitte bestätigen" in win.headline_text()
    card = win.cards_box.findChildren(MessageCard)[0]
    assert card.property("tone") == "ambiguous"
    assert "wählen" in card.title_label.text()

    rows = win.candidates_box.findChildren(CandidateRow)
    assert len(rows) == 2
    assert all(r._clickable for r in rows), "Kandidaten müssen wählbar sein"
    assert win.none_of_these_button() is not None


# ---------- REJECT ----------

def test_reject_zeigt_messwert_einlern_taste_und_bewertung(win):
    from docodetect.ui_qt.widgets.result_card import MessageCard

    win._show_report(report("reject", measured={"circle_diameter_mm": 123.4,
                                                "circularity": 0.91,
                                                "area_mm2": 11958.0}))
    assert "Kein Treffer" in win.headline_text()
    card = win.cards_box.findChildren(MessageCard)[0]
    assert card.property("tone") == "reject"
    assert "123,4" in card.all_text()
    assert card.action_button.text() == "Als neuen Artikel einlernen"
    assert win._verdict_bar is not None, "Bewertung fehlt bei REJECT"
    assert "123,4" in win.diagnose_text()


def test_reject_richtig_vermerkt_kein_treffer_statt_top1(win, tmp_path):
    """Der Knackpunkt: „Ablehnung war richtig" darf nicht als „Artikel X war
    richtig" im Report landen, auch wenn Kandidaten vorhanden sind."""
    import json

    from docodetect.reporting import NO_MATCH

    rep = report("reject", [cand()], measured={"circle_diameter_mm": 123.4})
    p = tmp_path / "r.json"
    p.write_text(rep.to_json(), encoding="utf-8")
    rep.report_path = str(p)

    win._show_report(rep)
    win._verdict_bar.correct_button.click()

    saved = json.loads(p.read_text(encoding="utf-8"))
    assert saved["verdict"] == "correct"
    assert saved["label"] == NO_MATCH != "ART-1"
    assert not win._verdict_bar.correct_button.isEnabled()


# ---------- BORDER ----------

def test_border_zustand_ohne_bewertung_aber_mit_hinweis(win):
    from docodetect.ui_qt.widgets.result_card import MessageCard

    win._show_report(report("reject", touches=True,
                            measured={"circle_diameter_mm": 300.0}))
    assert "Bildrand" in win.headline_text()
    card = win.cards_box.findChildren(MessageCard)[0]
    assert card.property("tone") == "border"
    # Kein Urteil: hier gibt es kein Ergebnis zu bewerten, nur eine
    # Platzierung zu korrigieren.
    assert win._verdict_bar is None
    # Im Bild muss es trotzdem stehen – dort schaut der Bediener hin.
    assert win.preview._warn_text and "Bildrand" in win.preview._warn_text


# ---------- Toleranzbalken ----------

def test_gauge_erkennt_innerhalb_und_ausserhalb(qapp):
    from docodetect.ui_qt.widgets.gauge import ToleranceGauge

    inside = ToleranceGauge(180.0, 183.0, TOL)
    assert inside.in_tolerance and "im Toleranzbereich" in inside.status_text()

    outside = ToleranceGauge(180.0, 190.0, TOL)
    assert not outside.in_tolerance
    assert "ausserhalb" in outside.status_text()


def test_gauge_bildet_das_toleranzband_auf_25_bis_75_prozent_ab(qapp):
    """Damit ein Messwert AUSSERHALB der Toleranz darstellbar bleibt, ist
    die Spur doppelt so breit wie das Band."""
    from docodetect.ui_qt.widgets.gauge import ToleranceGauge

    assert ToleranceGauge(180.0, 180.0, TOL)._fraction() == pytest.approx(0.5)
    assert ToleranceGauge(180.0, 180.0 - TOL, TOL)._fraction() == pytest.approx(0.25)
    assert ToleranceGauge(180.0, 180.0 + TOL, TOL)._fraction() == pytest.approx(0.75)
    # weit daneben -> geklemmt, nicht ausserhalb der Spur gezeichnet
    assert ToleranceGauge(180.0, 400.0, TOL)._fraction() == 1.0


# ---------- Erkennungsrahmen im Bild ----------

def test_erkennungsrahmen_wird_auf_die_bildgroesse_normiert(win):
    rep = report("accept", [cand()],
                 contour=[[400, 200], [800, 200], [800, 600], [400, 600]],
                 size=[1600, 1200])
    det = win._detection_for(rep)
    x, y, w, h = det.bbox
    assert 0.2 < x < 0.26 and 0.15 < y < 0.18       # 400/1600, 200/1200 (+Luft)
    assert 0.24 < w < 0.28 and 0.32 < h < 0.36
    assert det.tone == "accept"
    assert det.chips[0].startswith("Ø 181,0")
    assert det.chips[1] == "92 %"


def test_erkennungsrahmen_ohne_kandidat_zeigt_fragezeichen(win):
    rep = report("reject", measured={"circle_diameter_mm": 123.4},
                 contour=[[10, 10], [20, 20]], size=[100, 100])
    det = win._detection_for(rep)
    assert det.tone == "reject"
    assert det.chips[-1] == "?"


def test_ohne_kontur_kein_rahmen(win):
    assert win._detection_for(report("reject")) is None


def test_warnrahmen_faerbt_das_bild_nicht_flaechig_ein(qapp):
    """Regression: der Erkennungsrahmen setzt für seine Chips einen
    Füllpinsel. Blieb der stehen, füllte der anschliessende Warnrahmen das
    GESAMTE Bild in Amber – im Randberührungs-Zustand war vom Objekt nichts
    mehr zu sehen."""
    from PySide6.QtGui import QColor, QImage
    from docodetect.ui_qt.widgets.preview import Detection, PreviewWidget

    white = QImage(200, 200, QImage.Format_RGB32)
    white.fill(QColor("#ffffff"))

    w = PreviewWidget()
    w.resize(200, 200)
    w.set_overlay(white, 5.0,
                  Detection(bbox=(0.1, 0.1, 0.3, 0.3), tone="border",
                            chips=["Ø 300,0 mm", "?"]))
    w.set_warning("Objekt berührt den Bildrand")

    shot = w.grab().toImage()
    warn = QColor(theme_mod.load(theme_mod.DEFAULT_THEME)["warn"])
    centre = shot.pixelColor(shot.width() // 2, int(shot.height() * 0.75))
    assert centre.red() != warn.red() or centre.green() != warn.green(), \
        "Bildfläche ist flächig in der Warnfarbe eingefärbt"
