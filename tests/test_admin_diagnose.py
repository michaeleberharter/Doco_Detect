"""Admin-Panel Stufe 4: Diagnose-Seiten (Config-Ansicht, Kamera-Diagnose,
Segmentierungs-Test).

Qt offscreen, alles gegen tmp_path bzw. gemockte Fassaden. Kein Test
öffnet eine Kamera (conftest-Stolperdraht bleibt der Wächter); Frames
werden gestellt. Läuft im Test-Regime als EIGENER pytest-Aufruf."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(scope="module")
def qapp():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from docodetect.ui_qt.app import make_app
    return make_app()


def _cfg(tmp_path):
    return {
        "camera": {"index": 1, "width": 1920, "height": 1080},
        "calibration": {
            "file": str(tmp_path / "calibration.json"),
            "background_file": str(tmp_path / "background.png"),
        },
        "paths": {"db_file": str(tmp_path / "db.sqlite3"),
                  "captures_dir": str(tmp_path / "captures")},
        "analysis": {"output_dir": str(tmp_path / "runs")},
        "matching": {"diameter_tolerance_mm": 6.0, "top_k": 3},
        "stage2": {"enabled": False},
    }


# ---------- Config-Ansicht (Spec Punkt 11) ----------

def test_config_ansicht_zeigt_herkunft(qapp, tmp_path, monkeypatch):
    from docodetect.ui_qt.admin.pages import config_page as mod
    daten = [("camera.index", "1", "config.local.yaml"),
             ("camera.width", "1920", "config.yaml"),
             ("matching.top_k", "3", "config.yaml")]
    monkeypatch.setattr(mod, "config_with_origin", lambda: daten)
    seite = mod.ConfigPage(_cfg(tmp_path))
    zeilen = seite.zeilen()
    # YAML-Zeilen unverändert vorn; dahinter ALLE Dialog-Keys ohne
    # config-Zeile als Werksvorgabe (seit 2026-08-12) — die Ansicht
    # zeigt die effektiven Werte VOLLSTÄNDIG (hier hat die gestellte
    # config gar keinen ui-Abschnitt, also erscheinen alle sieben).
    assert zeilen[:3] == daten
    zusatz = {k: (w, h) for k, w, h in zeilen[3:]}
    assert set(zusatz) == {"ui.theme", "ui.scale_percent",
                           "ui.result_overlay_secs", "ui.confirm_sound",
                           "ui.verdict_buttons_visible",
                           "ui.preview_pause_minutes", "ui.touch_mode"}
    assert all(h == "Werksvorgabe (Code)" for _, h in zusatz.values())
    assert zusatz["ui.theme"][0] == "dark"          # app._UI_DEFAULTS
    assert "read-only" in seite.hinweis_text()
    assert "keinen Schreibpfad" in seite.hinweis_text()


def test_config_ansicht_zeigt_qsettings_ebene(qapp, tmp_path, monkeypatch):
    """Seit dem Einstellungsdialog überdeckt QSettings die YAML-Schichten
    im ui-Abschnitt — ohne dieses Overlay zeigte die Seite nicht mehr die
    effektiven Werte. QSettings sind per conftest auf tmp isoliert."""
    from docodetect.ui_qt import settings as st
    from docodetect.ui_qt.admin.pages import config_page as mod
    daten = [("ui.theme", "dark", "config.yaml"),
             ("ui.confirm_sound", "True", "config.yaml")]
    monkeypatch.setattr(mod, "config_with_origin", lambda: daten)
    st.setze(st.KEY_THEME, "light")
    st.setze(st.KEY_TOUCH, True)
    seite = mod.ConfigPage(_cfg(tmp_path))
    z = {k: (w, h) for k, w, h in seite.zeilen()}
    assert z["ui.theme"] == ("light", "QSettings (Benutzer)")
    assert z["ui.confirm_sound"][1] == "config.yaml"        # nicht gesetzt
    assert z["ui.touch_mode"] == ("True", "QSettings (Benutzer)")
    assert "QSettings" in seite.hinweis_text()


def test_config_ansicht_fehler_statt_crash(qapp, tmp_path, monkeypatch):
    from docodetect.ui_qt.admin.pages import config_page as mod

    def kaputt():
        raise FileNotFoundError("config.yaml fehlt")

    monkeypatch.setattr(mod, "config_with_origin", kaputt)
    seite = mod.ConfigPage(_cfg(tmp_path))
    assert seite.zeilen() == []
    assert "Config nicht lesbar" in seite.hinweis_text()
    assert "config.yaml fehlt" in seite.hinweis_text()


# ---------- Kamera-Diagnose (Spec Punkt 12) ----------

def test_kamera_diagnose_statik_und_mac_hinweis(qapp, tmp_path):
    from docodetect.ui_qt.admin.pages.camera_page import CameraPage
    seite = CameraPage(_cfg(tmp_path), camera_status=lambda: "verbunden",
                       kamera_warnung=lambda: "Readback weicht ab")
    w = seite.werte()
    assert w["index"] == "1"
    assert w["zustand"] == "verbunden"
    assert w["warnung"] == "Readback weicht ab"
    assert "AVFoundation" in w["hinweis"]
    assert "erwartbar" in w["hinweis"]


def test_kamera_suche_nur_mit_kamera_frei_kanal(qapp, tmp_path):
    """Review 2026-08-11: „getrennt" heisst NICHT „haelt keine Kamera" —
    der CameraWorker reconnectet alle 3 s. Gating deshalb ueber den
    expliziten kamera_frei-Kanal des Hauptfensters; ohne Kanal oder bei
    kamera_frei=False bleibt die Suche gesperrt (probe oeffnet Geraete)."""
    from docodetect.ui_qt.admin.pages.camera_page import CameraPage
    ohne_kanal = CameraPage(_cfg(tmp_path),
                            camera_status=lambda: "getrennt")
    assert not ohne_kanal.suche_button.isEnabled()
    belegt = CameraPage(_cfg(tmp_path), camera_status=lambda: "getrennt",
                        kamera_frei=lambda: False)
    assert not belegt.suche_button.isEnabled()
    assert "kollidieren" in belegt.werte()["suche_hinweis"]
    frei = CameraPage(_cfg(tmp_path), camera_status=lambda: "Demo",
                      kamera_frei=lambda: True)
    assert frei.suche_button.isEnabled()


def test_kamera_suche_zeigt_gefundene(qapp, tmp_path, monkeypatch):
    import time

    from docodetect.ui_qt.admin.pages import camera_page as mod
    monkeypatch.setattr(mod, "probe_cameras",
                        lambda camera_cfg=None, max_index=3: [
                            (0, True, 1920, 1080), (1, False, 0, 0)])
    seite = mod.CameraPage(_cfg(tmp_path),
                           camera_status=lambda: "getrennt",
                           kamera_frei=lambda: True)
    seite.suche_starten()
    ende = time.monotonic() + 10.0
    while seite._worker is not None and time.monotonic() < ende:
        qapp.processEvents()
    assert seite._worker is None
    zeilen = seite.suche_zeilen()
    assert zeilen[0] == {"index": 0, "ok": True, "aufloesung": "1920×1080"}
    assert zeilen[1]["ok"] is False


# ---------- Segmentierungs-Test (Spec Punkt 10) ----------

def _fake_messung():
    """Gestelltes Messergebnis: Features + SegmentationResult-Attrappe
    mit synthetischer Maske/Kontur (kein Messpfad im UI-Test)."""
    import numpy as np

    class FakeFeatures:
        circle_diameter_mm = 270.34
        equiv_diameter_mm = 268.1
        area_mm2 = 57255.0
        circularity = 0.95
        aspect_ratio = 1.02

    class FakeSeg:
        mask = np.zeros((60, 80), dtype=np.uint8)
        contour = np.array([[[10, 10]], [[10, 40]], [[60, 40]],
                            [[60, 10]]], dtype=np.int32)
        touches_border = False

    FakeSeg.mask[10:40, 10:60] = 255
    return FakeFeatures(), FakeSeg()


def _frame():
    import numpy as np
    return np.zeros((60, 80, 3), dtype=np.uint8)


def test_segtest_ohne_quelle_deaktiviert_mit_hinweis(qapp, tmp_path):
    from docodetect.ui_qt.admin.pages.segtest_page import SegTestPage
    seite = SegTestPage(_cfg(tmp_path), frame_anfordern=None)
    assert not seite.aufnahme_button.isEnabled()
    assert "keine Kamera" in seite.werte()["status"]


def test_segtest_misst_gestellten_frame(qapp, tmp_path, monkeypatch):
    import time

    from docodetect.ui_qt.admin.pages import segtest_page as mod
    monkeypatch.setattr(mod, "measure_shot",
                        lambda frame, cfg: _fake_messung())

    def frame_anfordern(cb):
        cb(_frame())
        return True

    seite = mod.SegTestPage(_cfg(tmp_path), frame_anfordern=frame_anfordern)
    assert seite.aufnahme_button.isEnabled()
    seite.testaufnahme()
    ende = time.monotonic() + 10.0
    while seite._worker is not None and time.monotonic() < ende:
        qapp.processEvents()
    assert seite._worker is None
    w = seite.werte()
    assert w["messwerte"]["Ø (minEnclosingCircle) [mm]"] == "270,34"
    assert w["messwerte"]["Randberührung"] == "nein"
    assert w["maske_gesetzt"] and w["overlay_gesetzt"]
    assert "Messung fertig" in w["status"]


def test_segtest_timeout_entsperrt_und_bleibt_ausloesbar(qapp, tmp_path,
                                                         monkeypatch):
    """Vormerkliste 27: Frame bleibt aus -> Timeout greift -> Meldung steht
    -> Knopf wieder frei -> erneut ausloesbar, ohne die Seite zu verlassen.
    Der Frame-Kanal ist dabei unberuehrt: die Anforderung kommt an
    (ok=True), nur der Frame bleibt aus; ein verspaeteter Frame nach dem
    Timeout faellt ins Warte-Flag."""
    import time

    from docodetect.ui_qt.admin.pages import segtest_page as mod

    monkeypatch.setattr(mod, "_FRAME_TIMEOUT_MS", 60)
    anforderungen = []

    def frame_anfordern(cb):
        anforderungen.append(cb)
        return True                # Kanal ok — es kommt nur nie ein Frame

    seite = mod.SegTestPage(_cfg(tmp_path), frame_anfordern=frame_anfordern)
    seite.testaufnahme()
    assert len(anforderungen) == 1
    assert not seite.aufnahme_button.isEnabled()
    assert "Warte auf Frame" in seite.werte()["status"]

    ende = time.monotonic() + 5.0
    while seite._warte_auf_frame and time.monotonic() < ende:
        qapp.processEvents()
    assert seite._warte_auf_frame is False, "der Timer beendet das Warten"
    assert "erneut versuchen" in seite.werte()["status"].lower()
    assert seite.aufnahme_button.isEnabled(), "Knopf wieder frei"

    anforderungen[0](_frame())     # verspaeteter Frame: verworfen, kein Worker
    assert seite._worker is None
    assert "erneut versuchen" in seite.werte()["status"].lower()

    seite.testaufnahme()
    assert len(anforderungen) == 2, "erneutes Ausloesen ohne Seitenwechsel"
    assert "Warte auf Frame" in seite.werte()["status"]


def test_segtest_segmentierungsfehler_als_text(qapp, tmp_path, monkeypatch):
    import time

    from docodetect.ui_qt.admin.pages import segtest_page as mod
    from docodetect.pipeline import SegmentationError

    def wirft(frame, cfg):
        raise SegmentationError("Kein Objekt gefunden (Bild zu dunkel).")

    monkeypatch.setattr(mod, "measure_shot", wirft)
    seite = mod.SegTestPage(_cfg(tmp_path),
                            frame_anfordern=lambda cb: (cb(_frame()), True)[1])
    seite.testaufnahme()
    ende = time.monotonic() + 10.0
    while seite._worker is not None and time.monotonic() < ende:
        qapp.processEvents()
    w = seite.werte()
    assert "Nicht messbar" in w["status"]
    assert "zu dunkel" in w["status"]


def test_kamera_suche_fehlertext_ueberlebt_refresh(qapp, tmp_path,
                                                   monkeypatch):
    """Review 2026-08-11: _worker_beendet -> refresh() darf den
    Fehlertext der Suche nicht ueberschreiben."""
    import time

    from docodetect.ui_qt.admin.pages import camera_page as mod

    def kaputt(camera_cfg=None, max_index=3):
        raise RuntimeError("Backend nicht verfuegbar")

    monkeypatch.setattr(mod, "probe_cameras", kaputt)
    seite = mod.CameraPage(_cfg(tmp_path),
                           camera_status=lambda: "getrennt",
                           kamera_frei=lambda: True)
    seite.suche_starten()
    ende = time.monotonic() + 10.0
    while seite._worker is not None and time.monotonic() < ende:
        qapp.processEvents()
    assert "Suche fehlgeschlagen" in seite.werte()["suche_hinweis"]
    assert "Backend nicht verfuegbar" in seite.werte()["suche_hinweis"]
