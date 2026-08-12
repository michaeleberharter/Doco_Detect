"""Pflichttests des Hilfe-Systems — Fenster und Ebene-1-Links (offscreen).

Geprüft wird die Mechanik: Fenster lädt Themen und springt an Anker,
die ToolRail hat den Hilfe-Knopf, das Hauptfenster setzt den Link je
Zustand, Ergebnis-Karten tragen ihre eigenen Links, und der Kontextsprung
öffnet das Fenster am richtigen Thema. Kein Pixel-Vergleich.

QSettings: wie test_ui_settings wird die Factory auf eine Ini unter
tmp_path gebogen — der Benutzer-Scope wird nie berührt.
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings  # noqa: E402

from docodetect.matcher import CandidateReport, MatchReport  # noqa: E402
from docodetect.ui_qt.app import make_app  # noqa: E402
from docodetect.ui_qt.hilfe import anker  # noqa: E402
from docodetect.ui_qt.hilfe import fenster as fenster_mod  # noqa: E402
from docodetect.ui_qt.hilfe.fenster import (HilfeFenster,  # noqa: E402
                                            HilfeLink, oeffne_hilfe)


@pytest.fixture(scope="module")
def qapp():
    return make_app()


@pytest.fixture(autouse=True)
def _qsettings_ini(tmp_path, monkeypatch):
    """Nie den Benutzer-Scope anfassen (Regel wie test_ui_settings)."""
    from docodetect.ui_qt import settings as settings_mod
    monkeypatch.setattr(
        settings_mod, "_factory",
        lambda: QSettings(str(tmp_path / "ui.ini"), QSettings.IniFormat))


@pytest.fixture(autouse=True)
def _singleton_aufraeumen(qapp):
    yield
    if fenster_mod._fenster is not None:
        fenster_mod._fenster.close()
        qapp.processEvents()
        fenster_mod._fenster = None


def make_cfg(tmp_path):
    return {
        "camera": {"index": 0, "width": 1920, "height": 1080},
        "calibration": {
            "file": str(tmp_path / "calibration.json"),
            "background_file": str(tmp_path / "background.png"),
            "aruco_dict": "DICT_4X4_50", "marker_id": 0,
            "marker_size_mm": 72.5,
        },
        "geometry": {"camera_height_mm": 300.0},
        "matching": {"diameter_tolerance_mm": 6.0,
                     "area_tolerance_pct": 12.0, "top_k": 3},
        "paths": {"db_file": str(tmp_path / "db.sqlite3"),
                  "captures_dir": str(tmp_path / "captures"),
                  "enroll_sessions_dir": str(tmp_path / "sessions")},
        "ui": {"preview_fps": 5, "confirm_sound": False},
        "stage2": {"enabled": False},
    }


def cand(nr="ART-1", name="Teller 18"):
    return CandidateReport(
        article_number=nr, name=name, nominal_size_mm=180.0, height_mm=0.0,
        corrected_diameter_mm=181.0, geometry_error_mm=1.0,
        has_references=True, n_shots=5, posterior=0.4,
        log_score=-0.1, max_abs_z=0.5)


def report(decision, candidates=(), touches=False):
    return MatchReport(decision=decision, message="Testreport",
                       candidates=list(candidates),
                       measured={"circle_diameter_mm": 181.0},
                       touches_border=touches, contour=None, image_size=None)


# ---------- Fenster ----------

def test_fenster_laedt_alle_themen(qapp, tmp_path):
    f = HilfeFenster(make_cfg(tmp_path))
    for thema in anker.ALLE_THEMEN:
        f.zeige_thema(thema)
        assert f.aktuelles_thema() == thema
        assert f.browser.toPlainText().strip(), thema
    f.close()


def test_zustandssprung_landet_am_anker(qapp, tmp_path):
    f = HilfeFenster(make_cfg(tmp_path))
    f.zeige_zustand(anker.EINLERNEN_KEIN_BILD)
    assert f.aktuelles_thema() == "einlernen-haengt"
    assert "Kein Bild" in f.browser.toPlainText()
    f.close()


def test_platzhalter_im_gerenderten_text_aufgeloest(qapp, tmp_path):
    f = HilfeFenster(make_cfg(tmp_path))
    f.zeige_thema("fragt-nach")
    text = f.browser.toPlainText()
    assert "{{config:" not in text
    assert "3" in text          # matching.top_k aus make_cfg
    f.close()


def test_querverweis_wechselt_thema(qapp, tmp_path):
    from PySide6.QtCore import QUrl
    f = HilfeFenster(make_cfg(tmp_path))
    f.zeige_thema("vorschau-dunkel")
    f._link_geklickt(QUrl("hilfe:keine-kamera#konfiguration"))
    assert f.aktuelles_thema() == "keine-kamera"
    f.close()


def test_unbekannter_zustand_faellt_sofort(qapp, tmp_path):
    with pytest.raises(KeyError):
        HilfeLink(make_cfg(tmp_path), "gibts-nicht")
    f = HilfeFenster(make_cfg(tmp_path))
    with pytest.raises(KeyError):
        f.zeige_zustand("gibts-nicht")
    f.close()


def test_oeffne_hilfe_ist_singleton(qapp, tmp_path):
    cfg = make_cfg(tmp_path)
    f1 = oeffne_hilfe(cfg, anker.ERGEBNIS_REJECT)
    f2 = oeffne_hilfe(cfg, anker.ERGEBNIS_AMBIGUOUS)
    assert f1 is f2
    assert f2.aktuelles_thema() == "fragt-nach"


# ---------- ToolRail / Statuszeile ----------

def test_toolrail_hat_hilfe_knopf(qapp):
    from docodetect.ui_qt.widgets.tool_rail import ToolRail
    rail = ToolRail()
    gefeuert = []
    rail.hilfe_requested.connect(lambda: gefeuert.append(True))
    rail._hilfe.click()
    assert gefeuert == [True]


def test_statuszeile_warnlink_folgt_der_warnung(qapp):
    from docodetect.ui_qt.widgets.status_bar import StatusBarContent
    inhalt = StatusBarContent()
    assert not inhalt.warn_hilfe.isVisibleTo(inhalt)
    inhalt.set_warning("Fokus-Lock nicht verfügbar")
    assert inhalt.warn_hilfe.isVisibleTo(inhalt)
    inhalt.set_warning("")
    assert not inhalt.warn_hilfe.isVisibleTo(inhalt)


# ---------- Hauptfenster: Ebene-1-Zustände ----------

@pytest.fixture()
def win(qapp, tmp_path):
    from docodetect.ui_qt.main_window import MainWindow
    w = MainWindow(make_cfg(tmp_path), demo=True)
    yield w
    w.close()


def test_not_ready_zeigt_einrichtungs_link(win):
    from docodetect.ui_qt.state import UiState
    assert win.state is UiState.NOT_READY
    assert win.hilfe_link.isVisibleTo(win)
    assert win.hilfe_link.zustand() == anker.EINRICHTUNG_NOETIG


def test_no_camera_zeigt_kamera_link(qapp, tmp_path):
    from docodetect.ui_qt.main_window import MainWindow
    from docodetect.ui_qt.state import UiState
    w = MainWindow(make_cfg(tmp_path))          # ohne Quelle -> NO_CAMERA
    assert w.state is UiState.NO_CAMERA
    assert w.hilfe_link.zustand() == anker.KEINE_KAMERA
    w.close()


def test_ergebnis_karten_tragen_eigene_links(win, qapp):
    from PySide6.QtCore import QCoreApplication, QEvent

    def karten_links():
        # deleteLater der Vorgänger-Karten erst ausführen — processEvents
        # allein stellt DeferredDelete nicht zu.
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        return win.cards_box.findChildren(HilfeLink)

    erwartet = {
        "reject": anker.ERGEBNIS_REJECT,
        "ambiguous": anker.ERGEBNIS_AMBIGUOUS,
    }
    for decision, zustand in erwartet.items():
        win._show_report(report(decision, [cand()]))
        assert [l.zustand() for l in karten_links()] == [zustand], decision
        assert not win.hilfe_link.isVisibleTo(win)
    win._show_report(report("reject", [cand()], touches=True))
    assert ([l.zustand() for l in karten_links()]
            == [anker.ERGEBNIS_BORDER])


def test_accept_hat_bewusst_keinen_link(win):
    win._show_report(report("accept", [cand()]))
    assert win.cards_box.findChildren(HilfeLink) == []
    assert not win.hilfe_link.isVisibleTo(win)


def test_job_failed_setzt_link(win):
    win._on_job_failed("No usable object found")
    assert win.hilfe_link.zustand() == anker.AKTION_FEHLGESCHLAGEN


def test_kontextsprung_aus_fehlerzustand(win, qapp):
    """Ebene 1 komplett: Reject-Karte -> Klick auf „Was tun?" -> Fenster
    steht auf dem Thema des Ankers."""
    win._show_report(report("reject", [cand()]))
    link = win.cards_box.findChildren(HilfeLink)[0]
    link.click()
    f = fenster_mod._fenster
    assert f is not None
    assert f.aktuelles_thema() == "nicht-gefunden"


# ---------- Dialog-Kindschaft (Modalität) ----------

def test_hilfe_als_kind_eines_modalen_dialogs(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication, QDialog
    dlg = QDialog()
    dlg.setModal(True)
    monkeypatch.setattr(QApplication, "activeModalWidget",
                        staticmethod(lambda: dlg))
    f = oeffne_hilfe(make_cfg(tmp_path), anker.EINLERNEN_KEIN_BILD)
    assert f.parent() is dlg
    assert fenster_mod._fenster is None      # kein Singleton im Modal-Fall
    dlg.deleteLater()
