"""Admin-Panel Stufe 2: Analyse-Lauf-Seite (Worker, Historie, Betrachter).

Qt offscreen, alles gegen tmp_path — nie gegen reports/analysis/ des
Repos. Der Worker-Test nutzt eine monkeypatchte Fassade (schnell,
deterministisch) und wartet per processEvents-Schleife — kein sleep,
kein zweiter Thread-Pfad. Läuft im Test-Regime als EIGENER pytest-Aufruf
in der UI-Schleife (Segfault-Regel)."""

from __future__ import annotations

import os
import sys
import time
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


# 1x1-PNG (Standard-Bytes) — reicht dem Betrachter.
_PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00"
        b"\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx"
        b"\x9cc\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01\x87\xa1N\xe8\x00"
        b"\x00\x00\x00IEND\xaeB`\x82")


def _lauf(base, run_id, pngs=(), gueltig=True, inhalt="# Bericht\nZeile 2"):
    d = Path(base) / run_id
    d.mkdir(parents=True)
    (d / "report.md").write_text(inhalt, encoding="utf-8")
    if gueltig:
        (d / "metrics.json").write_text("{}", encoding="utf-8")
    for name in pngs:
        (d / name).write_bytes(_PNG)
    return d


def test_historie_gueltig_und_ungueltig(qapp, tmp_path):
    from docodetect.ui_qt.admin.pages.analysis_page import LaufTab
    cfg = _cfg(tmp_path)
    _lauf(cfg["analysis"]["output_dir"], "lauf-a", pngs=("b.png", "a.png"))
    _lauf(cfg["analysis"]["output_dir"], "kaputt", gueltig=False)
    (Path(cfg["analysis"]["output_dir"]) / "leer").mkdir()
    tab = LaufTab(cfg)
    w = tab.werte()
    assert w["historie"] == ["lauf-a"]
    assert "ungültig, 2 Stück" in w["ungueltig"]


def test_historie_leerzustand(qapp, tmp_path):
    from docodetect.ui_qt.admin.pages.analysis_page import LaufTab
    tab = LaufTab(_cfg(tmp_path))
    w = tab.werte()
    assert w["historie"] == []
    assert w["ungueltig"] == ""
    assert "Noch keine Analyse-Läufe" in w["status"]


def test_betrachter_zeigt_report_und_blaettert(qapp, tmp_path):
    from docodetect.ui_qt.admin.pages.analysis_page import LaufTab
    cfg = _cfg(tmp_path)
    _lauf(cfg["analysis"]["output_dir"], "lauf-a", pngs=("b.png", "a.png"))
    tab = LaufTab(cfg)
    tab.historie.setCurrentRow(0)
    w = tab.werte()
    assert w["report_erste_zeile"] == "# Bericht"
    assert w["png"] == "a.png"            # alphabetisch, erstes zuerst
    tab.blaettern(1)
    assert tab.werte()["png"] == "b.png"
    tab.blaettern(1)                       # klemmt am Ende, kein Wrap
    assert tab.werte()["png"] == "b.png"
    tab.blaettern(-1)
    assert tab.werte()["png"] == "a.png"


def test_lauf_im_worker_aktualisiert_historie(qapp, tmp_path, monkeypatch):
    from docodetect.ui_qt.admin.pages import analysis_page as mod
    cfg = _cfg(tmp_path)

    def fake_run(cfg_, reports_dir=None, run_id=None):
        return _lauf(cfg_["analysis"]["output_dir"], run_id or "neu",
                     pngs=("x.png",))

    monkeypatch.setattr(mod, "run_report_analysis", fake_run)
    tab = mod.LaufTab(cfg)
    tab.run_id_feld.setText("wlauf")
    tab.starte_lauf()
    assert not tab.start_button.isEnabled()      # seriell: gesperrt
    ende = time.monotonic() + 10.0
    while tab._worker is not None and time.monotonic() < ende:
        qapp.processEvents()
    assert tab._worker is None, "Worker nicht fertig geworden"
    w = tab.werte()
    assert "wlauf" in w["status"]
    assert w["historie"] == ["wlauf"]
    assert tab.start_button.isEnabled()


def test_lauf_fehler_zeigt_text_statt_crash(qapp, tmp_path):
    from docodetect.ui_qt.admin.pages.analysis_page import LaufTab
    tab = LaufTab(_cfg(tmp_path))
    tab._lauf_fehler("kein Plattenplatz")
    w = tab.werte()
    assert "Analyse-Lauf fehlgeschlagen" in w["status"]
    assert "kein Plattenplatz" in w["status"]
    assert tab.start_button.isEnabled()


# ---------- Bewertungs-Übersicht (Spec Stufe 2, Punkt 7) ----------

def _rep(decision, verdict=None, artikel=None):
    from docodetect.matcher import CandidateReport
    from docodetect.pipeline import MatchReport
    cands = []
    if artikel:
        cands = [CandidateReport(
            article_number=artikel, name=artikel, nominal_size_mm=180.0,
            height_mm=0.0, corrected_diameter_mm=181.0,
            geometry_error_mm=1.0, has_references=True, n_shots=9,
            features=[], log_score=-0.4, posterior=0.9, max_abs_z=1.0)]
    return MatchReport(decision=decision, message="", verdict=verdict,
                       candidates=cands)


def test_bewertungsuebersicht_zaehlt_je_artikel(qapp, tmp_path):
    from docodetect.ui_qt.admin.pages.analysis_page import BewertungsTab
    cfg = _cfg(tmp_path)
    caps = Path(cfg["paths"]["captures_dir"])
    caps.mkdir(parents=True)
    daten = [("a.json", _rep("accept", "correct", "A-1")),
             ("b.json", _rep("accept", "wrong", "A-1")),
             ("c.json", _rep("ambiguous", None, "B-2")),
             ("d.json", _rep("reject", "correct", None))]   # NO_MATCH
    for name, rep in daten:
        (caps / name).write_text(rep.to_json(), encoding="utf-8")
    tab = BewertungsTab(cfg)
    zeilen = {z["artikel"]: z for z in tab.zeilen()}
    assert zeilen["A-1"] == {"artikel": "A-1", "richtig": 1, "falsch": 1,
                             "unbewertet": 0, "quote": "50 %"}
    assert zeilen["B-2"]["unbewertet"] == 1
    assert zeilen["B-2"]["quote"] == "–"
    assert "— kein Kandidat" in zeilen          # NIE als Artikelnummer
    assert "NO_MATCH" not in zeilen
    assert "2 von 3 richtig" in tab.gesamt_text()


def test_bewertungsuebersicht_leerzustand(qapp, tmp_path):
    from docodetect.ui_qt.admin.pages.analysis_page import BewertungsTab
    tab = BewertungsTab(_cfg(tmp_path))
    assert tab.zeilen() == []
    assert "Keine Reports" in tab.gesamt_text()


def test_analysis_page_hat_beide_tabs(qapp, tmp_path):
    from docodetect.ui_qt.admin.pages.analysis_page import AnalysisPage
    page = AnalysisPage(_cfg(tmp_path))
    assert page.tabs.count() == 2
    assert page.tabs.tabText(0) == "Analyse-Lauf"
    assert page.tabs.tabText(1) == "Bewertungs-Übersicht"


# ---------- Export (Freigabe 2026-08-11) ----------

def test_export_knoepfe_erst_mit_auswahl_aktiv(qapp, tmp_path):
    from docodetect.ui_qt.admin.pages.analysis_page import LaufTab
    cfg = _cfg(tmp_path)
    _lauf(cfg["analysis"]["output_dir"], "lauf-a")
    tab = LaufTab(cfg)
    assert not tab.export_ordner_button.isEnabled()
    assert not tab.export_zip_button.isEnabled()
    tab.historie.setCurrentRow(0)
    assert tab.export_ordner_button.isEnabled()
    assert tab.export_zip_button.isEnabled()


def test_export_ordner_und_zip_ueber_dialognaht(qapp, tmp_path, monkeypatch):
    import zipfile

    from docodetect.ui_qt.admin.pages.analysis_page import LaufTab
    cfg = _cfg(tmp_path)
    _lauf(cfg["analysis"]["output_dir"], "lauf-a", pngs=("x.png",))
    tab = LaufTab(cfg)
    tab.historie.setCurrentRow(0)
    ziel_eltern = tmp_path / "raus"
    ziel_eltern.mkdir()
    monkeypatch.setattr(tab, "_frage_ordner_ziel",
                        lambda: str(ziel_eltern / "lauf-a"))
    tab._export(als_zip=False)
    assert "Export fertig" in tab.werte()["status"]
    assert sorted(p.name for p in (ziel_eltern / "lauf-a").iterdir()) == [
        "metrics.json", "report.md", "x.png"]
    monkeypatch.setattr(tab, "_frage_zip_ziel",
                        lambda vorschlag: str(ziel_eltern / "lauf-a.zip"))
    tab._export(als_zip=True)
    assert "Export fertig" in tab.werte()["status"]
    with zipfile.ZipFile(ziel_eltern / "lauf-a.zip") as z:
        # run_id als oberste Ebene (Review 2026-08-11, wie Fassaden-Test)
        dateien = sorted(n for n in z.namelist() if not n.endswith("/"))
        assert dateien == ["lauf-a/metrics.json", "lauf-a/report.md",
                           "lauf-a/x.png"]


def test_export_projekt_root_wird_abgelehnt_mit_text(qapp, tmp_path,
                                                     monkeypatch):
    from docodetect.config import project_root
    from docodetect.ui_qt.admin.pages.analysis_page import LaufTab
    cfg = _cfg(tmp_path)
    _lauf(cfg["analysis"]["output_dir"], "lauf-a")
    tab = LaufTab(cfg)
    tab.historie.setCurrentRow(0)
    verboten = str(Path(project_root()) / "reports" / "export-test")
    monkeypatch.setattr(tab, "_frage_ordner_ziel", lambda: verboten)
    tab._export(als_zip=False)
    w = tab.werte()
    assert "Export fehlgeschlagen" in w["status"]
    assert "Projektverzeichnis" in w["status"]
    assert not Path(verboten).exists()


def test_export_abbruch_im_dialog_aendert_nichts(qapp, tmp_path,
                                                 monkeypatch):
    from docodetect.ui_qt.admin.pages.analysis_page import LaufTab
    cfg = _cfg(tmp_path)
    _lauf(cfg["analysis"]["output_dir"], "lauf-a")
    tab = LaufTab(cfg)
    tab.historie.setCurrentRow(0)
    vorher = tab.werte()["status"]
    monkeypatch.setattr(tab, "_frage_ordner_ziel", lambda: "")
    tab._export(als_zip=False)
    assert tab.werte()["status"] == vorher


def test_export_knoepfe_nach_reload_wieder_inaktiv(qapp, tmp_path):
    """Review 2026-08-11: reload_historie() nimmt die Auswahl weg —
    die Knoepfe muessen mit zurueckfallen (blockSignals unterdrueckt
    das currentRowChanged aus clear())."""
    from docodetect.ui_qt.admin.pages.analysis_page import LaufTab
    cfg = _cfg(tmp_path)
    _lauf(cfg["analysis"]["output_dir"], "lauf-a")
    tab = LaufTab(cfg)
    tab.historie.setCurrentRow(0)
    assert tab.export_ordner_button.isEnabled()
    tab.reload_historie()
    assert not tab.export_ordner_button.isEnabled()
    assert not tab.export_zip_button.isEnabled()


def test_export_zip_abbruch_im_dialog_aendert_nichts(qapp, tmp_path,
                                                     monkeypatch):
    from docodetect.ui_qt.admin.pages.analysis_page import LaufTab
    cfg = _cfg(tmp_path)
    _lauf(cfg["analysis"]["output_dir"], "lauf-a")
    tab = LaufTab(cfg)
    tab.historie.setCurrentRow(0)
    vorher = tab.werte()["status"]
    monkeypatch.setattr(tab, "_frage_zip_ziel", lambda vorschlag: "")
    tab._export(als_zip=True)
    assert tab.werte()["status"] == vorher


def test_export_verschwundener_lauf_meldet_und_raeumt_historie(
        qapp, tmp_path, monkeypatch):
    """Review 2026-08-11 (7d): verschwindet der Lauf zwischen Auswahl
    und Export, zeigt die Seite den Fehler UND aktualisiert die
    Historie — kein toter Eintrag mit aktivem Knopf."""
    import shutil as sh
    from docodetect.ui_qt.admin.pages.analysis_page import LaufTab
    cfg = _cfg(tmp_path)
    d = _lauf(cfg["analysis"]["output_dir"], "lauf-a")
    tab = LaufTab(cfg)
    tab.historie.setCurrentRow(0)
    sh.rmtree(d)
    monkeypatch.setattr(tab, "_frage_ordner_ziel",
                        lambda: str(tmp_path / "raus" / "lauf-a"))
    tab._export(als_zip=False)
    w = tab.werte()
    assert "Export fehlgeschlagen" in w["status"]
    assert w["historie"] == []
    assert not tab.export_ordner_button.isEnabled()
