"""Admin-Panel 1b: Report-Browser, Einzelreport-Ansicht, Prefilter-Kill-Sicht.

Alle Tests gegen synthetische Report-JSONs unter tmp_path (Spec Abschnitt
10), inkl. prefiltered-Einträgen BEIDER Kill-Gründe. Läuft im Test-Regime
als eigener pytest-Aufruf in der UI-Schleife."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.matcher import (CandidateReport, FeatureScore,  # noqa: E402
                                MatchReport)


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
        "matching": {"top_k": 3},
        "stage2": {"enabled": False},
    }


def _fs(name, z, w_eff=0.2):
    return FeatureScore(feature=name, measured=1.0, reference=1.1,
                        distance=0.1, sigma_enroll=0.05, sigma_eff=0.08,
                        z=z, log_contrib=-0.5 * z * z, w_eff=w_eff,
                        weighted=-0.5 * z * z * w_eff)


def _kandidat(nr, name, posterior, rang_features=None, margin=None):
    return CandidateReport(
        article_number=nr, name=name, nominal_size_mm=180.0, height_mm=20.0,
        corrected_diameter_mm=181.0, geometry_error_mm=1.0,
        has_references=True, n_shots=9,
        features=rang_features or [], log_score=-0.4, posterior=posterior,
        max_abs_z=max((abs(f.z) for f in (rang_features or [])), default=0.0),
        margin_to_next=margin)


def _kill(nr, reason, over_mm, area_pct=None):
    """Kill-Eintrag exakt im matcher._prefilter_kill-Format."""
    return {"article_number": nr, "name": f"Artikel {nr}", "reason": reason,
            "geometry_error_mm": 6.0 + over_mm, "tolerance_mm": 6.0,
            "over_tolerance_mm": over_mm, "area_error_pct": area_pct}


def _schreibe(caps, name, rep):
    caps.mkdir(parents=True, exist_ok=True)
    (caps / name).write_text(rep.to_json(), encoding="utf-8")


def _bestand(tmp_path):
    """Drei Reports: ACCEPT mit Kills+Verdict, REJECT ohne Kandidaten
    (NO_MATCH-Fall), AMBIGUOUS unbewertet."""
    caps = Path(tmp_path) / "captures"
    accept = MatchReport(
        decision="accept", message="klar", verdict="correct",
        label="T-270", max_z_winner=1.2, llr_margin=2.5, gate_passed=True,
        thresholds={"max_z_accept": 3.0, "min_llr_margin": 2.0, "top_k": 3},
        measured={"circle_diameter_mm": 270.3},
        timestamp="2026-08-10T12:00:00.000001",
        candidates=[_kandidat("T-270", "Teller 27", 0.9,
                              [_fs("diameter_mm", 1.2), _fs("delta_e", 0.4)],
                              margin=2.5),
                    _kandidat("T-250", "Teller 25", 0.1)],
        prefiltered=[_kill("LOEFFEL-1", "diameter", 3.2),
                     _kill("GABEL-2", "area", -1.0, area_pct=12.0)])
    _schreibe(caps, "20260810-120000-000.json", accept)
    reject = MatchReport(decision="reject", message="nichts passt",
                         verdict="wrong", label="MESSER-5",
                         measured={"circle_diameter_mm": 99.9},
                         prefiltered=[_kill("MESSER-5", "diameter", 0.4)])
    _schreibe(caps, "20260810-110000-000.json", reject)
    ambiguous = MatchReport(decision="ambiguous", message="knapp",
                            llr_margin=0.5, max_z_winner=2.0,
                            candidates=[_kandidat("T-270", "Teller 27", 0.5),
                                        _kandidat("T-250", "Teller 25", 0.45)])
    _schreibe(caps, "20260810-100000-000.json", ambiguous)
    return _cfg(tmp_path)


# ---------- Report-Browser ----------

def test_browser_neueste_zuerst_und_no_match_als_zustand(qapp, tmp_path):
    from docodetect.ui_qt.admin.pages.reports_page import ReportsPage
    seite = ReportsPage(_bestand(tmp_path))
    zeilen = seite.browser.zeilen()
    assert [z["entscheidung"] for z in zeilen] == ["accept", "reject",
                                                  "ambiguous"]
    # NO_MATCH ist ein Sonderwert, kein Artikel (Festlegung 2026-08-10):
    assert zeilen[1]["artikel"] == "— kein Kandidat"
    assert zeilen[0]["artikel"] == "T-270"
    assert [z["bewertung"] for z in zeilen] == ["Richtig", "Falsch",
                                               "unbewertet"]


def test_browser_filter_entscheidung_bewertung_artikel(qapp, tmp_path):
    from docodetect.ui_qt.admin.pages.reports_page import ReportsPage
    seite = ReportsPage(_bestand(tmp_path))
    seite.browser.set_filter(entscheidung="accept")
    assert len(seite.browser.zeilen()) == 1
    seite.browser.set_filter(bewertung="unbewertet")
    assert [z["entscheidung"] for z in seite.browser.zeilen()] == ["ambiguous"]
    seite.browser.set_filter(artikel="T-2")
    assert len(seite.browser.zeilen()) == 2   # accept + ambiguous (Top-1)


def test_browser_zeitraum_filter(qapp, tmp_path):
    from docodetect.ui_qt.admin.pages.reports_page import ReportsPage
    seite = ReportsPage(_bestand(tmp_path))
    seite.browser.set_filter(von="20260810-113000", bis="20260810-235959")
    assert [z["entscheidung"] for z in seite.browser.zeilen()] == ["accept"]


def test_browser_limit_hinweis(qapp, tmp_path, monkeypatch):
    from docodetect.ui_qt.admin.pages import reports_page as rp
    monkeypatch.setattr(rp, "_LIMIT", 2)
    seite = rp.ReportsPage(_bestand(tmp_path))
    assert len(seite.browser.zeilen()) == 2
    assert "Zeitraum-Filter" in seite.browser.hinweis_text()
    # Zeitraum gesetzt -> lädt gezielt nach (alle im Zeitraum, ohne Limit)
    seite.browser.set_filter(von="20260810-000000", bis="20260810-235959")
    assert len(seite.browser.zeilen()) == 3


# ---------- Einzelreport-Ansicht ----------

def test_detail_badge_gate_messwerte_verdict(qapp, tmp_path):
    from docodetect.ui_qt.admin.pages.reports_page import ReportsPage
    seite = ReportsPage(_bestand(tmp_path))
    seite.zeige_detail_fuer_zeile(0)          # accept-Report
    w = seite.detail.werte()
    assert w["badge"].startswith("ACCEPT")
    assert w["gate_max_z"] == "1,20 (Gate ≤ 3,00)"
    assert w["gate_margin"] == "2,50 (≥ 2,00)"
    assert w["gate_posterior"] == "90 %"
    assert "270,3" in w["messwerte"]
    assert w["verdict"] == "Richtig · Artikel: T-270"
    assert w["bild"] == "Bild nicht verfügbar."
    assert seite.aktueller_index() == 1       # Detail-Ansicht aktiv
    seite.zurueck()
    assert seite.aktueller_index() == 0


def test_detail_margin_unendlich_bei_einem_kandidaten(qapp, tmp_path):
    from docodetect.ui_qt.admin.pages.report_detail import ReportDetailView
    rep = MatchReport(decision="accept", message="solo",
                      max_z_winner=1.0, llr_margin=None,
                      thresholds={"max_z_accept": 3.0,
                                  "min_llr_margin": 2.0},
                      candidates=[_kandidat("T-270", "Teller 27", 1.0)])
    view = ReportDetailView()
    view.set_report(None, rep)
    assert view.werte()["gate_margin"] == "∞ (1 Kandidat)"


def test_detail_kandidaten_und_merkmalstabelle(qapp, tmp_path):
    from docodetect.ui_qt.admin.pages.reports_page import ReportsPage
    seite = ReportsPage(_bestand(tmp_path))
    seite.zeige_detail_fuer_zeile(0)
    w = seite.detail.werte()
    assert w["kandidaten"][0]["artikel"] == "T-270"
    assert w["kandidaten"][1]["artikel"] == "T-250"
    merkmale = w["merkmale"]                  # z je Merkmal des Siegers
    assert [m["merkmal"] for m in merkmale] == ["diameter_mm", "delta_e"]
    assert merkmale[0]["z"] == "1,20"
    assert set(merkmale[0]) >= {"merkmal", "messwert", "referenz",
                                "distanz", "sigma_enroll", "sigma_eff",
                                "z", "log_contrib", "w_eff", "gewichtet"}


def test_detail_kills_und_altbestand(qapp, tmp_path):
    from docodetect.ui_qt.admin.pages.reports_page import ReportsPage
    seite = ReportsPage(_bestand(tmp_path))
    seite.zeige_detail_fuer_zeile(0)
    kills = seite.detail.werte()["kills"]
    assert len(kills) == 2
    assert kills[0]["artikel"] == "LOEFFEL-1"
    assert "+3,20 mm" in kills[0]["abstand"]
    assert "12,0 %" in kills[1]["abstand"]
    seite.zeige_detail_fuer_zeile(2)          # ambiguous: keine Kills
    assert seite.detail.werte()["kills"] == "keine protokolliert"


# ---------- Prefilter-Kill-Sicht ----------

def test_kill_sicht_beide_gruende_und_wahrer_artikel(qapp, tmp_path):
    from docodetect.ui_qt.admin.pages.reports_page import ReportsPage
    seite = ReportsPage(_bestand(tmp_path))
    zeilen = seite.kills.zeilen()
    assert len(zeilen) == 3                   # 2 aus accept + 1 aus reject
    gruende = {z["grund"] for z in zeilen}
    assert gruende == {"diameter", "area"}
    # Der laut Verdict wahre Artikel (MESSER-5) war unter den Kills:
    wahre = [z for z in zeilen if z["wahrer_artikel"]]
    assert [z["artikel"] for z in wahre] == ["MESSER-5"]
    assert "3 Prefilter-Kills" in seite.kills.kopf_text()


def test_kill_sicht_leerzustand(qapp, tmp_path):
    from docodetect.ui_qt.admin.pages.reports_page import ReportsPage
    caps = Path(tmp_path) / "captures"
    _schreibe(caps, "20260810-100000-000.json",
              MatchReport(decision="accept", message="ohne Kills"))
    seite = ReportsPage(_cfg(tmp_path))
    assert seite.kills.zeilen() == []
    assert "Keine Prefilter-Kills" in seite.kills.kopf_text()


# ---------- Einbindung ins Admin-Fenster ----------

def test_admin_window_reports_sektion_traegt_die_seite(qapp, tmp_path):
    from docodetect.ui_qt.admin.admin_window import AdminWindow
    from docodetect.ui_qt.admin.pages.reports_page import ReportsPage
    win = AdminWindow(_bestand(tmp_path), camera_status=lambda: "Demo")
    assert win.sidebar.count() == 5           # Sidebar bleibt wie Spec §4
    win.sidebar.setCurrentRow(1)              # "Reports"
    assert isinstance(win.stack.currentWidget(), ReportsPage)
    tabs = win.stack.currentWidget().tabs
    assert [tabs.tabText(i) for i in range(tabs.count())] == [
        "Browser", "Prefilter-Kills"]
    win.close()
