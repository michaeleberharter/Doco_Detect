"""Tests für die dünne UI-Fassade in pipeline.py (get_status/list_articles).

Die Qt-UI (und jede weitere UI) ruft ausschließlich docodetect.pipeline auf.
get_status() muss auch VOR der Einrichtung funktionieren (keine Kalibrierung,
kein Hintergrund, keine DB) – daraus speist sich der NOT_READY-Zustand.
Keine Kamera, kein Qt nötig.
"""

import sys
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.calibration import Calibration  # noqa: E402
from docodetect.database import Database  # noqa: E402
from docodetect.pipeline import get_status, list_articles  # noqa: E402


def make_cfg(tmp_path):
    """Minimal-Config mit allen Pfaden unter tmp_path – nichts existiert."""
    return {
        "calibration": {
            "file": str(tmp_path / "calibration.json"),
            "background_file": str(tmp_path / "background.png"),
        },
        "paths": {"db_file": str(tmp_path / "db.sqlite3")},
        "stage2": {"enabled": False},
    }


def _seed_db(cfg, with_reference=False):
    """DB mit einem Artikel (und optional einer Referenz) anlegen."""
    from docodetect.features import Features

    db = Database(cfg)
    db.init_schema()
    from docodetect.database import Article
    db.create_article(Article(
        article_number="T-270", name="Teller flach 27", category="Teller",
        diameter_mm=270.0, width_mm=None, depth_mm=None, height_mm=25.0,
        color_desc=None, notes=None))
    if with_reference:
        feats = Features(
            equiv_diameter_mm=270.0, circle_diameter_mm=270.0, area_mm2=57255.0,
            perimeter_mm=848.0, circularity=0.95, aspect_ratio=1.0,
            mean_hsv=[0.0, 0.0, 200.0], solidity=0.99,
            hu_moments=[1.0] * 7,
            lab_center=[80.0, 0.0, 0.0], lab_rim=[80.0, 0.0, 0.0],
            hs_hist_center=[1.0], hs_hist_rim=[1.0])
        db.add_reference("T-270", feats)
    db.close()


# ---------- get_status: vor der Einrichtung ----------

def test_status_unconfigured(tmp_path):
    st = get_status(make_cfg(tmp_path))
    assert st.calibrated is False
    assert st.mm_per_px is None
    assert st.background_present is False
    assert st.article_count == 0
    assert st.articles_with_references == 0
    assert st.stage2_enabled is False
    assert st.ready is False


def test_status_does_not_create_files(tmp_path):
    """Eine Status-Abfrage darf keine Dateien anlegen (kein leeres sqlite)."""
    cfg = make_cfg(tmp_path)
    get_status(cfg)
    assert list(tmp_path.iterdir()) == []


# ---------- get_status: nach der Einrichtung ----------

def test_status_configured(tmp_path):
    cfg = make_cfg(tmp_path)
    Calibration(mm_per_px=0.171, camera_height_mm=300.0, image_width=1920,
                image_height=1080, marker_size_mm=136.0,
                created_unix=time.time()).save(cfg["calibration"]["file"])
    cv2.imwrite(cfg["calibration"]["background_file"],
                np.full((10, 10, 3), 200, dtype=np.uint8))
    _seed_db(cfg, with_reference=True)

    st = get_status(cfg)
    assert st.calibrated is True
    assert st.mm_per_px == pytest.approx(0.171)
    assert st.calibrated_unix is not None
    assert st.background_present is True
    assert st.article_count == 1
    assert st.articles_with_references == 1
    assert st.ready is True


def test_status_stage2_flag(tmp_path):
    cfg = make_cfg(tmp_path)
    cfg["stage2"] = {"enabled": True}
    assert get_status(cfg).stage2_enabled is True


def test_status_corrupt_calibration_is_not_calibrated(tmp_path):
    """Kaputte calibration.json => calibrated False, kein Crash."""
    cfg = make_cfg(tmp_path)
    Path(cfg["calibration"]["file"]).write_text("{kaputt", encoding="utf-8")
    st = get_status(cfg)
    assert st.calibrated is False
    assert st.ready is False


# ---------- list_articles ----------

def test_list_articles_empty_without_db(tmp_path):
    assert list_articles(make_cfg(tmp_path)) == []


def test_list_articles_with_reference_counts(tmp_path):
    cfg = make_cfg(tmp_path)
    _seed_db(cfg, with_reference=True)
    arts = list_articles(cfg)
    assert len(arts) == 1
    a = arts[0]
    assert a.article_number == "T-270"
    assert a.name == "Teller flach 27"
    assert a.diameter_mm == 270.0
    assert a.n_references == 1


# ---------- Einzelbild-Fassaden: capture_background / calibrate ----------

def _marker_cfg(tmp_path):
    cfg = make_cfg(tmp_path)
    cfg["camera"] = {"width": 1920, "height": 1080}
    cfg["calibration"].update(aruco_dict="DICT_4X4_50", marker_id=0,
                              marker_size_mm=136.0)
    cfg["geometry"] = {"camera_height_mm": 300.0}
    cfg["paths"]["reference_dir"] = str(tmp_path / "reference")
    # Einlern-Sessions und ihr Archiv unter tmp_path: sonst schriebe der Test
    # in den echten Projektbaum (resolve() loest relative Pfade gegen
    # project_root() auf).
    cfg["paths"]["enroll_sessions_dir"] = str(tmp_path / "enroll_sessions")
    cfg["paths"]["backups_dir"] = str(tmp_path / "backups")
    return cfg


def test_capture_background_then_status(tmp_path):
    from docodetect.pipeline import capture_background

    cfg = _marker_cfg(tmp_path)
    img = np.full((1080, 1920, 3), 200, dtype=np.uint8)
    capture_background(img, cfg)
    assert get_status(cfg).background_present is True


def test_calibrate_from_marker_scene(tmp_path):
    from docodetect.pipeline import calibrate
    from docodetect.ui_qt.demo_scenes import DEMO_MM_PER_PX, build_scene

    cfg = _marker_cfg(tmp_path)
    cal = calibrate(build_scene(cfg, "Marker"), cfg)
    assert cal.mm_per_px == pytest.approx(DEMO_MM_PER_PX, rel=0.02)
    st = get_status(cfg)
    assert st.calibrated is True
    assert st.mm_per_px == pytest.approx(DEMO_MM_PER_PX, rel=0.02)


def test_calibrate_without_marker_raises_actionable_error(tmp_path):
    from docodetect.pipeline import calibrate

    cfg = _marker_cfg(tmp_path)
    img = np.full((1080, 1920, 3), 200, dtype=np.uint8)
    with pytest.raises(RuntimeError):
        calibrate(img, cfg)
    assert get_status(cfg).calibrated is False


# ---------- annotiertes Ergebnisbild ----------

def test_render_report_overlay_draws_contour_and_diameter(tmp_path):
    from docodetect.matcher import MatchReport
    from docodetect.pipeline import render_report_overlay

    img = np.full((200, 300, 3), 50, dtype=np.uint8)
    contour = [[100, 40], [200, 40], [200, 160], [100, 160]]
    report = MatchReport(decision="accept", message="ok", contour=contour,
                         touches_border=False,
                         measured={"circle_diameter_mm": 186.3})
    out = render_report_overlay(img, report)
    assert out.shape == img.shape
    assert not np.array_equal(out, img)      # es wurde gezeichnet
    assert np.array_equal(img, np.full((200, 300, 3), 50, dtype=np.uint8))


def test_render_report_overlay_border_case_red(tmp_path):
    from docodetect.matcher import MatchReport
    from docodetect.pipeline import render_report_overlay

    img = np.zeros((100, 100, 3), dtype=np.uint8)
    report = MatchReport(decision="reject", message="Rand",
                         contour=[[0, 10], [50, 10], [50, 90], [0, 90]],
                         touches_border=True, measured={})
    out = render_report_overlay(img, report)
    # Rot (BGR: Kanal 2) dominiert auf der Kontur, kein Grün
    assert out[10, 20, 2] > 150 and out[10, 20, 1] < 100


def test_render_report_overlay_without_contour_is_noop(tmp_path):
    from docodetect.matcher import MatchReport
    from docodetect.pipeline import render_report_overlay

    img = np.zeros((50, 50, 3), dtype=np.uint8)
    report = MatchReport(decision="reject", message="nichts", measured={})
    assert np.array_equal(render_report_overlay(img, report), img)


# ---------- Einlernen: measure_shot + save_enrollment (Zwei-Schritt) ----------

def test_measure_shot_and_save_enrollment_roundtrip(tmp_path):
    """Der Einlern-Dialog misst erst (ohne DB-Schreiben – Wiederholen
    möglich) und persistiert dann alle Shots auf einmal."""
    from docodetect.pipeline import (get_status, list_articles, measure_shot,
                                     save_enrollment)
    from docodetect.ui_qt.demo_scenes import build_scene

    cfg = _marker_cfg(tmp_path)
    from docodetect.pipeline import calibrate, capture_background
    capture_background(build_scene(cfg, "Hintergrund"), cfg)
    calibrate(build_scene(cfg, "Marker"), cfg)
    _seed_db(cfg, with_reference=False)

    shots = []
    for v in (1, 2):
        img = build_scene(cfg, "Teller 18", v)
        feats, seg = measure_shot(img, cfg)
        assert feats.circle_diameter_mm == pytest.approx(186.2, abs=3.0)
        assert seg.contour is not None
        shots.append((img, feats))
    assert get_status(cfg).articles_with_references == 0  # noch nichts gespeichert

    n = save_enrollment(cfg, "T-270", shots)
    assert n == 2
    arts = {a.article_number: a for a in list_articles(cfg)}
    assert arts["T-270"].n_references == 2
    ref_dir = Path(cfg["paths"]["reference_dir"]) / "T-270"
    assert len(list(ref_dir.glob("*.png"))) == 2  # verlustlose Referenzfotos wie CLI


def test_measure_shot_border_raises(tmp_path):
    from docodetect.pipeline import calibrate, capture_background, measure_shot
    from docodetect.segmentation import SegmentationError
    from docodetect.ui_qt.demo_scenes import build_scene

    cfg = _marker_cfg(tmp_path)
    capture_background(build_scene(cfg, "Hintergrund"), cfg)
    calibrate(build_scene(cfg, "Marker"), cfg)
    with pytest.raises(SegmentationError):
        measure_shot(build_scene(cfg, "Randbild"), cfg)


# ---------- manuelle Bestätigung (AMBIGUOUS-Karten) ----------

def _ambiguous_report(tmp_path):
    from docodetect.matcher import CandidateReport, MatchReport

    report = MatchReport(
        decision="ambiguous", message="2 Kandidaten",
        candidates=[
            CandidateReport(article_number="A", name="Teller A",
                            nominal_size_mm=180, height_mm=0,
                            corrected_diameter_mm=180, geometry_error_mm=0,
                            has_references=True, n_shots=5),
            CandidateReport(article_number="B", name="Teller B",
                            nominal_size_mm=182, height_mm=0,
                            corrected_diameter_mm=180, geometry_error_mm=2,
                            has_references=True, n_shots=5),
        ])
    p = tmp_path / "report.json"
    p.write_text(report.to_json(), encoding="utf-8")
    report.report_path = str(p)
    return report, p


def test_confirm_no_match_setzt_label_auf_no_match(tmp_path):
    """„Zu Recht abgelehnt" darf NIE als „Artikel X war richtig" im Report
    landen. Der Report hier hat Kandidaten (Vorfilter lieferte welche, das
    z-Gate kippte) – genau der Fall, in dem save_verdict(correct=True) das
    Label auf die Top-1-Vorhersage setzen und das Urteil verdrehen würde.
    Solche verdrehten Urteile haben am 2026-07-20 die Fehlerattribution der
    Auswertung verfälscht."""
    import json

    from docodetect.pipeline import confirm_no_match
    from docodetect.reporting import NO_MATCH

    report, p = _ambiguous_report(tmp_path)
    report.decision = "reject"
    confirm_no_match(report)
    saved = json.loads(p.read_text(encoding="utf-8"))
    assert saved["verdict"] == "correct"
    assert saved["label"] == NO_MATCH
    assert saved["label"] != "A", "Top-1 faelschlich als Wahrheit vermerkt"


def test_confirm_no_match_ohne_gespeicherten_report_meldet_sich(tmp_path):
    from docodetect.pipeline import confirm_no_match

    report, _ = _ambiguous_report(tmp_path)
    report.report_path = None
    with pytest.raises(ValueError, match="captures_dir"):
        confirm_no_match(report)


def test_confirm_result_top1_marks_correct(tmp_path):
    import json

    from docodetect.pipeline import confirm_result

    report, p = _ambiguous_report(tmp_path)
    confirm_result(report, "A")
    saved = json.loads(p.read_text(encoding="utf-8"))
    assert saved["verdict"] == "correct"
    assert saved["label"] == "A"


def test_confirm_result_other_candidate_marks_wrong_with_truth(tmp_path):
    import json

    from docodetect.pipeline import confirm_result

    report, p = _ambiguous_report(tmp_path)
    confirm_result(report, "B")
    saved = json.loads(p.read_text(encoding="utf-8"))
    assert saved["verdict"] == "wrong"
    assert saved["label"] == "B"


# ---------- manuelle Korrektur „Keiner davon" (reject_result) ----------

def test_reject_result_with_article_marks_wrong_with_truth(tmp_path):
    import json

    from docodetect.pipeline import reject_result

    report, p = _ambiguous_report(tmp_path)
    reject_result(report, "A")
    saved = json.loads(p.read_text(encoding="utf-8"))
    assert saved["verdict"] == "wrong"
    assert saved["label"] == "A"


def test_reject_result_without_article_marks_wrong_no_label(tmp_path):
    """Unbekannt-Option (kein wahrer Artikel): verdict=wrong, label bleibt
    unbelegt (kein evaluate-Label vorhanden, das stehen bleiben könnte)."""
    import json

    from docodetect.pipeline import reject_result

    report, p = _ambiguous_report(tmp_path)
    reject_result(report)
    saved = json.loads(p.read_text(encoding="utf-8"))
    assert saved["verdict"] == "wrong"
    assert saved.get("label") is None


# ---------- (D) Enrollment-Blatt-Autosave beim „Übernehmen" ----------

def test_persist_enrollment_sheet_copies_to_analysis_dir(tmp_path):
    from docodetect.pipeline import persist_enrollment_sheet

    src = tmp_path / "tmp_sheet.png"
    src.write_bytes(b"\x89PNG\r\n\x1a\n fake sheet")
    cfg = {"analysis": {"output_dir": str(tmp_path / "reports")}}
    dest = persist_enrollment_sheet(cfg, "LOEFFEL-3", src)
    assert dest == tmp_path / "reports" / "enrollment" / "LOEFFEL-3.png"
    assert dest.is_file()
    assert dest.read_bytes() == src.read_bytes()


def test_persist_enrollment_sheet_missing_source_raises(tmp_path):
    from docodetect.pipeline import persist_enrollment_sheet

    cfg = {"analysis": {"output_dir": str(tmp_path / "reports")}}
    with pytest.raises(FileNotFoundError):
        persist_enrollment_sheet(cfg, "X-1", tmp_path / "does_not_exist.png")


def _enroll_session(cfg):
    """Eine Einlern-Session mit zwei Aufnahmen AUF DER PLATTE + eingerichtete
    cfg (bg + Kalibrierung).

    Seit dem Session-Umbau nimmt _job_commit eine EnrollSession statt einer
    Liste von In-Memory-Shots — die Aussage der beiden Tests darunter bleibt
    unveraendert (Blatt-Kopieren ist best-effort und darf das Buchen nie
    blockieren), nur der Weg dorthin fuehrt jetzt ueber das Journal."""
    from docodetect.pipeline import (append_shot, begin_enroll_session,
                                     calibrate, capture_background,
                                     measure_shot, stage_frame)
    from docodetect.ui_qt.demo_scenes import build_scene

    capture_background(build_scene(cfg, "Hintergrund"), cfg)
    calibrate(build_scene(cfg, "Marker"), cfg)
    _seed_db(cfg, with_reference=False)
    s = begin_enroll_session(cfg, "T-270", target_shots=2)
    for v in (1, 2):
        img = build_scene(cfg, "Teller 18", v)
        feats, _ = measure_shot(img, cfg)
        s = append_shot(cfg, s, stage_frame(cfg, s, img), feats)
    return s


def test_job_commit_copies_sheet_on_uebernehmen(tmp_path):
    from docodetect.ui_qt.widgets.enroll_dialog import _job_commit

    cfg = _marker_cfg(tmp_path)
    cfg["analysis"] = {"output_dir": str(tmp_path / "reports")}
    session = _enroll_session(cfg)
    sheet = tmp_path / "tmp_sheet.png"
    sheet.write_bytes(b"\x89PNG fake sheet")

    result = _job_commit(cfg, session, str(sheet))
    assert result["n"] == 2
    assert result["warn"] is None
    dest = Path(cfg["analysis"]["output_dir"]) / "enrollment" / "T-270.png"
    assert dest.is_file()
    assert result["sheet_dest"] == str(dest)


def test_job_commit_copy_failure_does_not_block_db_write(tmp_path):
    """Schlägt das Blatt-Kopieren fehl, wird trotzdem in die DB geschrieben
    (n korrekt, Referenzen da) und nur gewarnt — kein Abbruch."""
    from docodetect.ui_qt.widgets.enroll_dialog import _job_commit

    cfg = _marker_cfg(tmp_path)
    cfg["analysis"] = {"output_dir": str(tmp_path / "reports")}
    session = _enroll_session(cfg)

    result = _job_commit(cfg, session, str(tmp_path / "gibt_es_nicht.png"))
    assert result["n"] == 2                               # DB-Schreiben NICHT blockiert
    assert result["sheet_dest"] is None
    assert result["warn"] and "nicht gesichert" in result["warn"]
    assert get_status(cfg).articles_with_references == 1  # Referenzen sind da


# ---------- Lese-Fassaden (Admin-Panel 1a) ----------

from docodetect.matcher import MatchReport  # noqa: E402
from docodetect.pipeline import (load_saved_reports,  # noqa: E402
                                 optics_fingerprint, report_judgement,
                                 report_predicted_article)


def _schreibe_report(pfad, decision, verdict=None):
    # Ohne Typ-Annotationen: die Datei hat kein `from __future__ import
    # annotations`, und unter Python 3.9 wäre `str | None` ein TypeError.
    rep = MatchReport(decision=decision, message="Test", verdict=verdict)
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(rep.to_json(), encoding="utf-8")


def test_load_saved_reports_neueste_zuerst_limit_und_defekte(tmp_path):
    cfg = make_cfg(tmp_path)
    caps = tmp_path / "captures"
    cfg["paths"]["captures_dir"] = str(caps)
    # Die Fassade sortiert nach DATEINAME (absteigend) — Capture-Namen
    # sind ms-Zeitstempel. Kein sleep nötig, mtime ist egal.
    _schreibe_report(caps / "a.json", "reject")
    _schreibe_report(caps / "b.json", "accept")
    (caps / "kaputt.json").write_text("{nix", encoding="utf-8")
    alle = load_saved_reports(cfg)
    assert [p.name for p, _ in alle] == ["b.json", "a.json"]
    assert alle[0][1].report_path == str(caps / "b.json")
    nur_eins = load_saved_reports(cfg, limit=1)
    assert [p.name for p, _ in nur_eins] == ["b.json"]


def test_load_saved_reports_bewertung_aendert_reihenfolge_nicht(tmp_path):
    """Befund 2026-08-10: save_verdict schreibt das Report-JSON neu. Mit
    mtime-Sortierung springt ein nachträglich bewerteter alter Report in
    „neueste zuerst" nach vorn — genau die bewerteten Reports sind aber
    die, die man im Browser sucht. Maßgeblich ist der Dateiname
    (ms-Zeitstempel), nicht der Schreibzeitpunkt."""
    cfg = make_cfg(tmp_path)
    caps = tmp_path / "captures"
    cfg["paths"]["captures_dir"] = str(caps)
    _schreibe_report(caps / "20260810-100000-000.json", "reject")
    _schreibe_report(caps / "20260810-110000-000.json", "accept")
    # Nachträgliche Bewertung: die ÄLTERE Datei wird neu geschrieben,
    # ihr mtime ist jetzt der jüngste im Ordner.
    _schreibe_report(caps / "20260810-100000-000.json", "reject",
                     verdict="wrong")
    alle = load_saved_reports(cfg)
    assert [p.name for p, _ in alle] == ["20260810-110000-000.json",
                                         "20260810-100000-000.json"]


def test_load_saved_reports_ohne_captures_key_ist_leer(tmp_path):
    """Konsistent mit dem Schreibpfad: ohne paths.captures_dir speichert
    _save_capture_and_report nichts — die Lesefassade liefert dann []
    statt KeyError (Befund 2026-08-11, Integration Admin-Panel 1b)."""
    assert load_saved_reports(make_cfg(tmp_path)) == []


def test_load_saved_reports_ohne_ordner_ist_leer(tmp_path):
    cfg = make_cfg(tmp_path)
    cfg["paths"]["captures_dir"] = str(tmp_path / "gibtsnicht")
    assert load_saved_reports(cfg) == []


def test_load_saved_reports_fremddateien_crashen_nicht(tmp_path):
    """Dateien ohne Zeitstempel-Muster im Namen: kein Crash, deterministische
    Einsortierung (lexikografisch — 'z…' steht absteigend vor den
    Ziffern-Zeitstempeln, unabhängig vom Schreibzeitpunkt)."""
    cfg = make_cfg(tmp_path)
    caps = tmp_path / "captures"
    cfg["paths"]["captures_dir"] = str(caps)
    _schreibe_report(caps / "zzz-fremd.json", "reject")   # zuerst geschrieben
    _schreibe_report(caps / "20260810-120000-000.json", "accept")
    alle = load_saved_reports(cfg)
    assert [p.name for p, _ in alle] == ["zzz-fremd.json",
                                         "20260810-120000-000.json"]


def test_load_reports_unbekannter_sortierschluessel(tmp_path):
    """Der additive sort_by-Parameter kennt genau 'mtime' und 'name' —
    alles andere ist ein klarer Fehler, kein stilles Fallback."""
    from docodetect.reporting import load_reports
    with pytest.raises(ValueError):
        load_reports(tmp_path, sort_by="quatsch")


def test_report_judgement_und_prediction_delegieren():
    rep = MatchReport(decision="accept", message="", verdict="correct")
    assert report_judgement(rep) is True
    assert report_predicted_article(rep) == "NO_MATCH"  # keine Kandidaten
    assert report_judgement(MatchReport(decision="reject", message="")) is None


def test_optics_fingerprint_none_ohne_einrichtung(tmp_path):
    assert optics_fingerprint(make_cfg(tmp_path)) is None


def test_optics_fingerprint_liefert_hashes(tmp_path):
    import hashlib

    cfg = make_cfg(tmp_path)
    cfg["features"] = {"ring_zones": 3, "hs_hist_bins": [8, 8]}
    Calibration(mm_per_px=0.5, camera_height_mm=300.0, image_width=1920,
                image_height=1080, marker_size_mm=72.5,
                created_unix=time.time()).save(cfg["calibration"]["file"])
    cv2.imwrite(cfg["calibration"]["background_file"],
                np.zeros((8, 8, 3), dtype=np.uint8))
    fp = optics_fingerprint(cfg)
    assert fp is not None
    assert fp["mm_per_px"] == 0.5
    erwartet = hashlib.sha256(
        Path(cfg["calibration"]["background_file"]).read_bytes()).hexdigest()
    assert fp["background_sha256"] == erwartet
    assert set(fp) == {"calibration_sha256", "background_sha256",
                       "features_cfg_sha256", "mm_per_px",
                       "camera_height_mm"}


# ---------- Stufe-2/3A-Fassaden (Admin-Panel, Freigabe 2026-08-11) ----------

import math  # noqa: E402

from docodetect.pipeline import (AnalysisRunInfo, ArticleInfo,  # noqa: E402
                                 NO_MATCH, list_analysis_runs,
                                 nominal_size_mm, run_report_analysis)


def test_no_match_ist_ueber_pipeline_beziehbar():
    assert NO_MATCH == "NO_MATCH"


def test_run_report_analysis_loest_quelle_und_ziel_auf(tmp_path, monkeypatch):
    import docodetect.config as cfgmod
    monkeypatch.setattr(cfgmod, "project_root", lambda: tmp_path)
    caps = tmp_path / "captures"
    caps.mkdir()
    cfg = make_cfg(tmp_path)
    cfg["paths"]["captures_dir"] = str(caps)
    out = run_report_analysis(cfg, run_id="fassade")
    assert out == tmp_path / "reports" / "analysis" / "fassade"
    md = (out / "report.md").read_text(encoding="utf-8")
    assert str(caps) in md                 # Quelle = captures_dir-Default


def test_run_report_analysis_expliziter_quellordner(tmp_path, monkeypatch):
    import docodetect.config as cfgmod
    monkeypatch.setattr(cfgmod, "project_root", lambda: tmp_path)
    quelle = tmp_path / "eigene"
    quelle.mkdir()
    cfg = make_cfg(tmp_path)
    cfg["analysis"] = {"output_dir": str(tmp_path / "ziel")}
    out = run_report_analysis(cfg, reports_dir=quelle, run_id="expl")
    assert out == tmp_path / "ziel" / "expl"
    assert str(quelle) in (out / "report.md").read_text(encoding="utf-8")


def test_list_analysis_runs_kriterium_und_zaehlung(tmp_path):
    import os
    base = tmp_path / "runs"
    cfg = make_cfg(tmp_path)
    cfg["analysis"] = {"output_dir": str(base)}
    for name, dateien in (("gut1", ("report.md", "metrics.json")),
                          ("gut2", ("report.md", "metrics.json")),
                          ("nur-md", ("report.md",)),
                          ("leer", ())):
        (base / name).mkdir(parents=True)
        for f in dateien:
            (base / name / f).write_text("x", encoding="utf-8")
    (base / "notiz.txt").write_text("x", encoding="utf-8")  # kein Ordner
    os.utime(base / "gut2" / "report.md", (1000, 1000))     # aelter machen
    laeufe, ungueltig = list_analysis_runs(cfg)
    assert [r.run_id for r in laeufe] == ["gut1", "gut2"]   # Dateizeit absteigend
    assert ungueltig == 2                                   # nur-md + leer
    assert laeufe[0].path == base / "gut1"
    assert isinstance(laeufe[0], AnalysisRunInfo)


def test_list_analysis_runs_ohne_verzeichnis(tmp_path):
    cfg = make_cfg(tmp_path)
    cfg["analysis"] = {"output_dir": str(tmp_path / "gibtsnicht")}
    assert list_analysis_runs(cfg) == ([], 0)


def test_nominal_size_mm_max_nicht_hypot():
    """Die max/hypot-Regel lebt in matcher._nominal_size_mm und wird von
    der Fassade nur durchgereicht — der hypot-Fehler vom 2026-07-21 darf
    nicht als Zweitimplementierung in einer UI wiederkehren."""
    laenglich = ArticleInfo(article_number="L-1", name="Loeffel",
                            category=None, diameter_mm=None, height_mm=None,
                            n_references=0, width_mm=186.9, depth_mm=45.0)
    assert nominal_size_mm(laenglich) == 186.9
    assert nominal_size_mm(laenglich) != pytest.approx(
        math.hypot(186.9, 45.0))
    rund = ArticleInfo(article_number="T-1", name="Teller", category=None,
                       diameter_mm=270.0, height_mm=None, n_references=0)
    assert nominal_size_mm(rund) == 270.0
    ohne = ArticleInfo(article_number="X-1", name="Ohne", category=None,
                       diameter_mm=None, height_mm=None, n_references=0)
    assert nominal_size_mm(ohne) is None


def test_list_articles_liefert_breite_und_tiefe(tmp_path):
    from docodetect.database import Article
    cfg = make_cfg(tmp_path)
    db = Database(cfg)
    db.init_schema()
    db.create_article(Article(article_number="L-1", name="Loeffel",
                              category=None, diameter_mm=None,
                              width_mm=186.9, depth_mm=45.0, height_mm=20.0,
                              color_desc=None, notes=None))
    db.close()
    infos = list_articles(cfg)
    assert infos[0].width_mm == 186.9
    assert infos[0].depth_mm == 45.0


# ---------- Export von Analyse-Läufen (Freigabe 2026-08-11) ----------

import os  # noqa: E402
import zipfile  # noqa: E402

from docodetect.pipeline import export_analysis_run  # noqa: E402


def _mini_lauf(tmp_path, name="lauf"):
    d = tmp_path / name
    d.mkdir(parents=True)
    (d / "report.md").write_text("# Bericht", encoding="utf-8")
    (d / "metrics.json").write_text("{}", encoding="utf-8")
    (d / "a.png").write_bytes(b"png-a")
    (d / "b.csv").write_text("x;y", encoding="utf-8")
    return d


def test_export_ordner_kopiert_komplett(tmp_path):
    src = _mini_lauf(tmp_path)
    ziel = export_analysis_run(src, tmp_path / "raus" / "kopie")
    assert sorted(p.name for p in ziel.iterdir()) == [
        "a.png", "b.csv", "metrics.json", "report.md"]
    assert (ziel / "a.png").read_bytes() == b"png-a"


def test_export_zip_enthaelt_alles_und_ergaenzt_endung(tmp_path):
    """Das Archiv traegt die run_id als oberste Ebene (Review 2026-08-11:
    symmetrisch zum Ordner-Export; Entpacken kippt nichts ins CWD)."""
    src = _mini_lauf(tmp_path)
    ziel = export_analysis_run(src, tmp_path / "raus" / "archiv",
                               als_zip=True)
    assert ziel.name == "archiv.zip"
    with zipfile.ZipFile(ziel) as z:
        dateien = sorted(n for n in z.namelist() if not n.endswith("/"))
        assert dateien == ["lauf/a.png", "lauf/b.csv",
                           "lauf/metrics.json", "lauf/report.md"]


def test_export_zip_grossschreibung_und_bestehendes_zip(tmp_path):
    """Review-Befund 2026-08-11: '.ZIP' wird auf '.zip' normalisiert
    (vorher prueften exists() und make_archive VERSCHIEDENE Pfade);
    'x' bei existierendem 'x.zip' wird abgelehnt."""
    src = _mini_lauf(tmp_path)
    ziel = export_analysis_run(src, tmp_path / "raus" / "archiv.ZIP",
                               als_zip=True)
    assert ziel.name == "archiv.zip"
    with pytest.raises(ValueError, match="existiert bereits"):
        export_analysis_run(src, tmp_path / "raus" / "archiv",
                            als_zip=True)


def test_export_root_selbst_und_geschwister_praefix(tmp_path, monkeypatch):
    """Der Root selbst ist gesperrt; ein GESCHWISTER-Ordner mit gleichem
    Namens-Praefix (Doco_Detect_corpus neben Doco_Detect) muss durch —
    Schutz gegen einen Rueckfall auf String-Praefix-Vergleich."""
    import docodetect.config as cfgmod
    projekt = tmp_path / "projekt"
    projekt.mkdir()
    monkeypatch.setattr(cfgmod, "project_root", lambda: projekt)
    src = _mini_lauf(tmp_path)
    with pytest.raises(ValueError, match="Projektverzeichnis"):
        export_analysis_run(src, projekt)
    ziel = export_analysis_run(src, tmp_path / "projekt_corpus" / "kopie")
    assert (ziel / "report.md").is_file()


def test_export_case_variante_des_projektpfads(tmp_path, monkeypatch):
    """macOS/APFS ist case-insensitiv, resolve() kanonisiert die
    Schreibweise nicht — ein Ziel unter 'PROJEKT/' landet real im
    Projekt. Der Inode-Vergleich faengt das (Review 2026-08-11).
    Auf case-sensitivem FS existiert der Pfad nicht: Skip."""
    import docodetect.config as cfgmod
    projekt = tmp_path / "projekt"
    projekt.mkdir()
    if not (tmp_path / "PROJEKT").exists():
        pytest.skip("Dateisystem ist case-sensitiv")
    monkeypatch.setattr(cfgmod, "project_root", lambda: projekt)
    src = _mini_lauf(tmp_path)
    with pytest.raises(ValueError, match="Projektverzeichnis"):
        export_analysis_run(src, tmp_path / "PROJEKT" / "kopie")


def test_export_ziel_im_projekt_wird_abgelehnt(tmp_path, monkeypatch):
    import docodetect.config as cfgmod
    projekt = tmp_path / "projekt"
    projekt.mkdir()
    monkeypatch.setattr(cfgmod, "project_root", lambda: projekt)
    src = _mini_lauf(tmp_path)
    with pytest.raises(ValueError, match="Projektverzeichnis"):
        export_analysis_run(src, projekt / "reports" / "kopie")


def test_export_symlink_ins_projekt_wird_abgelehnt(tmp_path, monkeypatch):
    import docodetect.config as cfgmod
    projekt = tmp_path / "projekt"
    (projekt / "unter").mkdir(parents=True)
    monkeypatch.setattr(cfgmod, "project_root", lambda: projekt)
    link = tmp_path / "harmlos"
    link.symlink_to(projekt / "unter")
    src = _mini_lauf(tmp_path)
    with pytest.raises(ValueError, match="Projektverzeichnis"):
        export_analysis_run(src, link / "kopie")


def test_export_ziel_existiert_nie_ueberschreiben(tmp_path):
    src = _mini_lauf(tmp_path)
    ziel = tmp_path / "raus" / "kopie"
    ziel.mkdir(parents=True)
    with pytest.raises(ValueError, match="existiert bereits"):
        export_analysis_run(src, ziel)


def test_export_quelle_ungueltig_oder_verschwunden(tmp_path):
    kaputt = tmp_path / "kaputt"
    kaputt.mkdir()
    (kaputt / "report.md").write_text("x", encoding="utf-8")  # ohne metrics
    with pytest.raises(ValueError, match="gültiger Analyse-Lauf"):
        export_analysis_run(kaputt, tmp_path / "raus1")
    with pytest.raises(ValueError, match="gültiger Analyse-Lauf"):
        export_analysis_run(tmp_path / "wegga", tmp_path / "raus2")


def test_export_ziel_nicht_beschreibbar(tmp_path):
    src = _mini_lauf(tmp_path)
    gesperrt = tmp_path / "gesperrt"
    gesperrt.mkdir()
    os.chmod(gesperrt, 0o500)
    try:
        with pytest.raises(OSError):
            export_analysis_run(src, gesperrt / "kopie")
    finally:
        os.chmod(gesperrt, 0o700)
