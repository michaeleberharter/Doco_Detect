"""Admin-Panel Stufe 4: Einlern-Sessions — Anzeige, Verwerfen, Fortsetzen.

Session-Fixture nach dem Muster von test_enroll_session.py (echte
begin/stage/append-Fassaden gegen Temp-Bestand). Verwerfen ist die
einzige bestandsverändernde Admin-Aktion: getestet wird End-to-End gegen
tmp_path UND per Spy, dass NUR die bestehenden Fassaden gerufen werden.
Läuft im Test-Regime als EIGENER pytest-Aufruf."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.calibration import Calibration  # noqa: E402
from docodetect.database import Article, Database  # noqa: E402
from docodetect.features import Features  # noqa: E402
from docodetect.pipeline import (append_shot, begin_enroll_session,  # noqa: E402
                                 stage_frame)

ARTIKEL = "T-270"


@pytest.fixture(scope="module")
def qapp():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from docodetect.ui_qt.app import make_app
    return make_app()


def _cfg(tmp_path):
    return {
        "calibration": {"file": str(tmp_path / "calibration.json"),
                        "background_file": str(tmp_path / "background.png")},
        "paths": {"db_file": str(tmp_path / "db.sqlite3"),
                  "reference_dir": str(tmp_path / "reference"),
                  "enroll_sessions_dir": str(tmp_path / "enroll_sessions"),
                  "backups_dir": str(tmp_path / "backups")},
        "features": {"ring_zones": {"center_max": 0.60, "rim_min": 0.75},
                     "hs_hist_bins": [16, 8]},
        "matching": {"sigma_floors": {"diameter_mm": 0.6}},
        "stage2": {"enabled": False},
    }


def _feats(d_mm=270.0):
    return Features(
        equiv_diameter_mm=d_mm, circle_diameter_mm=d_mm, area_mm2=57255.0,
        perimeter_mm=848.0, circularity=0.95, aspect_ratio=1.0,
        mean_hsv=[0.0, 0.0, 200.0], solidity=0.99, hu_moments=[1.0] * 7,
        lab_center=[80.0, 0.0, 0.0], lab_rim=[80.0, 0.0, 0.0],
        hs_hist_center=[1.0], hs_hist_rim=[1.0])


def _session_anlegen(cfg, n_shots=2):
    Calibration(mm_per_px=0.2, camera_height_mm=300.0, image_width=1920,
                image_height=1080, marker_size_mm=50.0,
                created_unix=0.0).save(cfg["calibration"]["file"])
    cv2.imwrite(cfg["calibration"]["background_file"],
                np.full((64, 96, 3), 200, dtype=np.uint8))
    db = Database(cfg)
    db.init_schema()
    db.create_article(Article(
        article_number=ARTIKEL, name="Teller flach 27", category="Teller",
        diameter_mm=270.0, width_mm=None, depth_mm=None, height_mm=25.0,
        color_desc=None, notes=None))
    db.close()
    s = begin_enroll_session(cfg, ARTIKEL, target_shots=9)
    for _ in range(n_shots):
        raw = stage_frame(cfg, s, np.full((64, 96, 3), 120, dtype=np.uint8))
        s = append_shot(cfg, s, raw, _feats())
    return s


def test_sessions_tabelle_und_leerzustand(qapp, tmp_path):
    from docodetect.ui_qt.admin.pages.sessions_page import SessionsPage
    leer = SessionsPage(_cfg(tmp_path))
    assert leer.zeilen() == []
    assert "Keine offenen Einlern-Sessions" in leer.hinweis_text()
    cfg = _cfg(tmp_path / "mit")
    _session_anlegen(cfg)
    seite = SessionsPage(cfg)
    zeilen = seite.zeilen()
    assert len(zeilen) == 1
    assert zeilen[0]["artikel"] == ARTIKEL
    assert zeilen[0]["shots"] == "2/9"
    assert zeilen[0]["zustand"] == "offen"


def test_verwerfen_end_to_end_gegen_temp_bestand(qapp, tmp_path,
                                                 monkeypatch):
    from docodetect.ui_qt.admin.pages.sessions_page import SessionsPage
    cfg = _cfg(tmp_path)
    s = _session_anlegen(cfg)
    sess_dir = s.info.path
    seite = SessionsPage(cfg)
    seite.tabelle.setCurrentCell(0, 0)
    gesehen = {}
    monkeypatch.setattr(seite, "_bestaetigen",
                        lambda text: gesehen.setdefault("text", text) or True)
    seite.verwerfen()
    ende = time.monotonic() + 15.0
    while seite._worker is not None and time.monotonic() < ende:
        qapp.processEvents()
    assert seite._worker is None
    assert str(sess_dir) in gesehen["text"]        # betroffene Pfade im Dialog
    assert "verworfen" in gesehen["text"]
    assert not sess_dir.exists()                    # Session-Ordner weg …
    verworfen = tmp_path / "verworfen" / ARTIKEL
    assert verworfen.is_dir()                       # … gesichert, nicht gelöscht
    assert any(verworfen.iterdir())
    assert "gesichert unter" in seite.hinweis_text()
    assert seite.zeilen() == []                     # Tabelle nachgeladen


def test_verwerfen_abgebrochen_bewegt_nichts(qapp, tmp_path, monkeypatch):
    from docodetect.ui_qt.admin.pages.sessions_page import SessionsPage
    cfg = _cfg(tmp_path)
    s = _session_anlegen(cfg)
    seite = SessionsPage(cfg)
    seite.tabelle.setCurrentCell(0, 0)
    monkeypatch.setattr(seite, "_bestaetigen", lambda text: False)
    seite.verwerfen()
    assert s.info.path.exists()
    assert seite.zeilen() and seite.zeilen()[0]["artikel"] == ARTIKEL


def test_verwerfen_ruft_nur_die_bestehenden_fassaden(qapp, tmp_path,
                                                     monkeypatch):
    """Nachweis für die Abschlussmeldung: kein zweiter Pfad zu einer
    bestandsverändernden Operation — exakt plan_discard + discard."""
    from docodetect.ui_qt.admin.pages import sessions_page as mod
    cfg = _cfg(tmp_path)
    _session_anlegen(cfg)
    aufrufe = []
    echt_load = mod.load_enroll_session
    monkeypatch.setattr(mod, "load_enroll_session",
                        lambda c, p: aufrufe.append("load") or echt_load(c, p))
    monkeypatch.setattr(mod, "plan_discard_enroll_session",
                        lambda c, s: aufrufe.append("plan") or
                        {"n": 2, "plan": [], "article_number": ARTIKEL,
                         "ts": s.info.ts})
    monkeypatch.setattr(mod, "discard_enroll_session",
                        lambda c, s: aufrufe.append("discard") or
                        Path(tmp_path / "verworfen-fake"))
    seite = mod.SessionsPage(cfg)
    seite.tabelle.setCurrentCell(0, 0)
    monkeypatch.setattr(seite, "_bestaetigen", lambda text: True)
    seite.verwerfen()
    ende = time.monotonic() + 10.0
    while seite._worker is not None and time.monotonic() < ende:
        qapp.processEvents()
    assert aufrufe.count("plan") == 1
    assert aufrufe.count("discard") == 1
    assert set(aufrufe) <= {"load", "plan", "discard"}


def test_fortsetzen_gating_und_delegation(qapp, tmp_path):
    from docodetect.ui_qt.admin.pages.sessions_page import SessionsPage
    cfg = _cfg(tmp_path)
    _session_anlegen(cfg)
    gesperrt = SessionsPage(
        cfg, fortsetzen_pruefen=lambda: "Kamera fehlt — erst verbinden.",
        fortsetzen=lambda info: pytest.fail("darf nicht delegieren"))
    gesperrt.tabelle.setCurrentCell(0, 0)
    assert not gesperrt.fortsetzen_button.isVisible()
    assert "Kamera fehlt" in gesperrt.fortsetzen_hinweis_text()
    empfangen = []
    frei = SessionsPage(cfg, fortsetzen_pruefen=lambda: None,
                        fortsetzen=lambda info: empfangen.append(info))
    frei.tabelle.setCurrentCell(0, 0)
    frei.fortsetzen()
    assert len(empfangen) == 1
    assert empfangen[0].article_number == ARTIKEL


def test_fortsetzen_ohne_anbindung_zeigt_hinweis(qapp, tmp_path):
    from docodetect.ui_qt.admin.pages.sessions_page import SessionsPage
    cfg = _cfg(tmp_path)
    _session_anlegen(cfg)
    seite = SessionsPage(cfg)                       # keine Callables
    assert not seite.fortsetzen_button.isVisible()
    assert "Hauptfenster" in seite.fortsetzen_hinweis_text()
