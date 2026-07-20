"""Tests für docodetect/analysis.py: Wilson-Intervalle, Kanal-Attribution,
End-to-End-Artefakte, Rückwärtskompatibilität mit alten Report-JSONs.

Run: pytest tests/test_analysis.py -v
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.analysis import (attribution_case, channel_scores,  # noqa: E402
                                 rule_of_three, run_analysis, wilson_interval)
from docodetect.database import Article, Database  # noqa: E402
from docodetect.matcher import (CandidateReport, FeatureScore,  # noqa: E402
                                MatchReport)

MATCHING = {"diameter_tolerance_mm": 6.0, "area_tolerance_pct": 12.0,
            "max_z_accept": 3.5, "min_llr_margin": 2.0, "top_k": 3}


def _cand(nr, log_score, posterior=0.5, feats=None):
    fs = [FeatureScore(feature=f, measured=None, reference=None, distance=0.0,
                       sigma_enroll=0.0, sigma_eff=1.0, z=0.0, log_contrib=w,
                       w_eff=0.1, weighted=w)
          for f, w in (feats or {}).items()]
    return CandidateReport(article_number=nr, name=nr, nominal_size_mm=200.0,
                           height_mm=0.0, corrected_diameter_mm=200.0,
                           geometry_error_mm=0.0, has_references=True,
                           n_shots=2, features=fs, log_score=log_score,
                           posterior=posterior, max_abs_z=1.0)


def _rep(decision="accept", label=None, verdict=None, cands=(), margin=None,
         max_z=1.0, centroid=None, measured=None, ts="2026-07-17T10:00:00"):
    return MatchReport(decision=decision, message="", candidates=list(cands),
                       llr_margin=margin, max_z_winner=max_z,
                       gate_passed=decision != "reject",
                       thresholds=dict(MATCHING), measured=measured or {},
                       timestamp=ts, label=label, verdict=verdict,
                       centroid_px=centroid,
                       image_size=[1920, 1080] if centroid else None)


def test_wilson_closed_form():
    p, lo, hi = wilson_interval(8, 10)
    assert p == pytest.approx(0.8)
    assert lo == pytest.approx(0.4902, abs=1e-3)   # bekannter Wert für 8/10
    assert hi == pytest.approx(0.9433, abs=1e-3)
    assert wilson_interval(0, 0) == (0.0, 0.0, 1.0)
    _, lo0, _ = wilson_interval(0, 20)
    assert lo0 == 0.0


def test_rule_of_three():
    assert "n=30" in rule_of_three(30) and "10.0%" in rule_of_three(30)


def test_channel_scores_aggregates_weighted_contributions():
    c = _cand("A", -1.0, feats={"diameter_mm": -0.1, "delta_e_center": -0.2,
                                "hist_rim": -0.3, "hu_log": -0.05,
                                "circularity": -0.01})
    ch = channel_scores(c)
    assert ch["geometry"] == pytest.approx(-0.1)
    assert ch["color"] == pytest.approx(-0.5)
    assert ch["shape"] == pytest.approx(-0.06)


def test_attribution_case_trennt_die_vier_nicht_attribuierbaren_faelle():
    """Regression: frueher landeten 'Top-1 war korrekt', 'keine Kandidaten'
    und der echte Vorfilter-Kill in EINEM Zaehler, der als Vorfilter-Kill
    gemeldet wurde – daher die unmoegliche Kombination '13 Kills bei 59/60
    Top-3' (Phase A, 1-Shot-Referenzen: sigma_enroll=0 sprengt das z-Gate,
    der richtige Artikel gewinnt trotzdem)."""
    feats = {"diameter_mm": -0.1}

    # richtiger Artikel gewinnt, Entscheidung trotzdem reject -> KEIN Kill
    top1_ok = _rep(decision="reject", label="A", verdict="wrong",
                   cands=[_cand("A", -4.0, 1.0, feats)])
    assert attribution_case(top1_ok)[0] == "top1_korrekt"

    # wahrer Artikel gar nicht im Kandidatenset -> echter Vorfilter-Kill
    kill = _rep(decision="ambiguous", label="A", verdict="wrong",
                cands=[_cand("B", -0.5, 0.6, feats),
                       _cand("C", -0.9, 0.4, feats)])
    assert attribution_case(kill)[0] == "vorfilter_kill"

    # gar kein Kandidat (Segmentierung abgelehnt) -> nicht berechenbar
    leer = _rep(decision="reject", label="A", verdict="wrong", cands=[])
    assert attribution_case(leer)[0] == "keine_kandidaten"

    # Kandidaten ohne Merkmals-Scores (Alt-Report) -> nicht berechenbar
    ohne = _rep(decision="ambiguous", label="A", verdict="wrong",
                cands=[_cand("B", -0.5, 0.6), _cand("A", -0.9, 0.4)])
    assert attribution_case(ohne)[0] == "keine_merkmalsscores"

    # echte Fehlidentifikation -> attribuierbar
    echt = _rep(decision="ambiguous", label="A", verdict="wrong",
                cands=[_cand("B", -0.5, 0.6, feats), _cand("A", -0.9, 0.4, feats)])
    case, wrong, right = attribution_case(echt)
    assert case == "attribuierbar"
    assert wrong.article_number == "B" and right.article_number == "A"


def test_attribution_meldet_top1_korrekt_nicht_als_vorfilter_kill(tmp_path,
                                                                  monkeypatch):
    """Der Bug im Zusammenspiel: ein Lauf, in dem JEDER Fehler ein
    'Top-1 war korrekt'-Fall ist, darf 0 Vorfilter-Kills melden."""
    import docodetect.config as cfgmod
    monkeypatch.setattr(cfgmod, "project_root", lambda: tmp_path)
    reports_dir = tmp_path / "caps"
    reports_dir.mkdir()
    feats = {"diameter_mm": -0.1}
    for i in range(3):
        _write(reports_dir, f"r{i}", _rep(
            decision="reject", label="A", verdict="wrong",
            cands=[_cand("A", -4.0, 1.0, feats)],
            measured={"circle_diameter_mm": 200.0}))

    cfg = {"matching": dict(MATCHING),
           "analysis": {"output_dir": "reports/analysis", "near_miss_factor": 1.5},
           "geometry": {"camera_height_mm": 300.0},
           "paths": {"db_file": str(tmp_path / "t.sqlite3")}}
    out = run_analysis(cfg, reports_dir, run_id="attrib")
    md = (out / "report.md").read_text(encoding="utf-8")
    assert "3× der richtige Artikel stand auf Platz 1" in md
    assert "Geometrie-Vorfilter nicht überlebt" not in md

    # die unattribuierten Faelle sind einzeln nachvollziehbar abgelegt
    csv_lines = (out / "error_attribution_unattributed.csv").read_text(
        encoding="utf-8").splitlines()
    assert len(csv_lines) == 4 and all("top1_korrekt" in ln for ln in csv_lines[1:])


def _write(reports_dir: Path, name: str, rep: MatchReport):
    (reports_dir / f"{name}.json").write_text(rep.to_json(), encoding="utf-8")


EXPECTED_FILES = [
    "confusion_matrix.png", "confusion_matrix.csv",
    "confusion_matrix_accept.png", "confusion_matrix_accept.csv",
    "score_distributions.png", "score_distributions.csv",
    "near_misses.png", "near_misses.csv",
    "error_attribution.png", "error_attribution.csv",
    "position_errors.png", "position_errors.csv",
    "metrics.png", "metrics.json", "report.md",
]


def test_run_analysis_end_to_end(tmp_path, monkeypatch):
    import docodetect.config as cfgmod
    monkeypatch.setattr(cfgmod, "project_root", lambda: tmp_path)
    reports_dir = tmp_path / "caps"
    reports_dir.mkdir()

    feats_good = {"diameter_mm": -0.05, "delta_e_center": -0.02, "hu_log": -0.01}
    feats_bad_color = {"diameter_mm": -0.05, "delta_e_center": -2.5, "hu_log": -0.01}

    # 3 korrekte Accepts (einer davon Near-Miss: margin 1.0 < 2.0*1.5)
    _write(reports_dir, "a1", _rep(label="A", verdict="correct", margin=5.0,
                                   cands=[_cand("A", -0.1, 0.95, feats_good),
                                          _cand("B", -5.1, 0.05, feats_bad_color)],
                                   centroid=[400.0, 300.0],
                                   measured={"circle_diameter_mm": 201.0}))
    _write(reports_dir, "a2", _rep(label="A", verdict="correct", margin=1.0,
                                   cands=[_cand("A", -0.2, 0.7, feats_good),
                                          _cand("B", -1.2, 0.3, feats_bad_color)],
                                   centroid=[1500.0, 800.0],
                                   measured={"circle_diameter_mm": 198.5}))
    _write(reports_dir, "b1", _rep(label="B", verdict="correct", margin=4.0,
                                   cands=[_cand("B", -0.3, 0.9, feats_good)],
                                   centroid=[960.0, 540.0],
                                   measured={"circle_diameter_mm": 199.0}))
    # 1 Fehl-Accept: Wahrheit B, erkannt A; Farbe beguenstigt den Falschen
    _write(reports_dir, "err", _rep(
        label="B", verdict="wrong", margin=0.5,
        cands=[_cand("A", -0.4, 0.6, {"diameter_mm": -0.05,
                                      "delta_e_center": -0.1, "hu_log": -0.2}),
               _cand("B", -0.9, 0.4, {"diameter_mm": -0.04,
                                      "delta_e_center": -0.8, "hu_log": -0.06})],
        centroid=[300.0, 900.0], measured={"circle_diameter_mm": 205.0}))
    # 1 unbewertet + 1 Alt-Format ohne neue Felder (darf nichts crashen)
    _write(reports_dir, "unrated", _rep(cands=[_cand("A", -0.2)]))
    legacy = _rep(label="A", cands=[_cand("A", -0.2)]).to_dict()
    for k in ("verdict", "report_path", "centroid_px", "image_size"):
        legacy.pop(k)
    (reports_dir / "legacy.json").write_text(json.dumps(legacy), encoding="utf-8")

    cfg = {"matching": dict(MATCHING),
           "analysis": {"output_dir": "reports/analysis", "near_miss_factor": 1.5},
           "geometry": {"camera_height_mm": 300.0},
           "paths": {"db_file": str(tmp_path / "t.sqlite3")}}
    db = Database(cfg)
    db.init_schema()
    for nr in ("A", "B"):
        db.create_article(Article(article_number=nr, name=nr, category=None,
                                  diameter_mm=200.0, width_mm=None, depth_mm=None,
                                  height_mm=None, color_desc=None, notes=None))
    db.close()

    out = run_analysis(cfg, reports_dir, run_id="testrun")
    assert out == tmp_path / "reports" / "analysis" / "testrun"
    for f in EXPECTED_FILES:
        assert (out / f).exists(), f"Artefakt fehlt: {f}"

    metrics = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
    q = metrics["quotas"]
    # bewertet: a1,a2,b1 (verdict) + err (verdict) + legacy (Label-Vergleich)
    assert q["accuracy_top1"]["k"] == 4 and q["accuracy_top1"]["n"] == 5
    assert q["auto_accept_rate"]["n"] == 6                 # alle Reports
    assert q["false_accept_rate"]["k"] == 1
    assert metrics["per_article"]["B"]["p"] == pytest.approx(0.5)

    # Near-Miss: genau der margin-1.0-Fall
    near = (out / "near_misses.csv").read_text(encoding="utf-8").splitlines()
    assert len(near) == 2 and near[1].startswith("1.0,")

    # Attribution: Verursacher ist der Farbkanal
    attr = (out / "error_attribution.csv").read_text(encoding="utf-8").splitlines()
    assert len(attr) == 2 and attr[1].endswith("color")
    assert "B -> A" in attr[1]

    # report.md bindet Grafiken ein
    md = (out / "report.md").read_text(encoding="utf-8")
    assert "![confusion_matrix]" in md and "metrics.json" in md


def test_run_analysis_archive_moves_jsons_but_keeps_images(tmp_path, monkeypatch):
    """archive=True: ausgewertete Report-JSONs wandern in den Lauf-Ordner
    (naechste Testrunde startet leer); Bilder bleiben in captures liegen
    (Golden-PNGs der Segmentierungs-Regressionssuite!)."""
    import docodetect.config as cfgmod
    monkeypatch.setattr(cfgmod, "project_root", lambda: tmp_path)
    reports_dir = tmp_path / "caps"
    reports_dir.mkdir()
    _write(reports_dir, "a1", _rep(label="A", verdict="correct",
                                   cands=[_cand("A", -0.1)]))
    _write(reports_dir, "a2", _rep(label="A", verdict="correct",
                                   cands=[_cand("A", -0.2)]))
    (reports_dir / "1234.png").write_bytes(b"fake-golden")   # bleibt liegen
    cfg = {"matching": dict(MATCHING), "analysis": {"output_dir": "r"},
           "geometry": {"camera_height_mm": 300.0},
           "paths": {"db_file": str(tmp_path / "t.sqlite3")}}
    out = run_analysis(cfg, reports_dir, run_id="arch", archive=True)
    assert list(reports_dir.glob("*.json")) == []            # Runde ist leer
    assert (reports_dir / "1234.png").exists()               # Bild unberuehrt
    archived = sorted(p.name for p in (out / "reports").glob("*.json"))
    assert archived == ["a1.json", "a2.json"]
    assert "archiviert" in (out / "report.md").read_text(encoding="utf-8")


def test_publish_copies_artifacts_without_raw_jsons(tmp_path, monkeypatch):
    """--publish: nur die aggregierten Artefakte (6x PNG+CSV, metrics,
    report.md) wandern ins versionierte Archiv – die per --archive in den
    Lauf-Ordner verschobenen rohen Report-JSONs bleiben draußen. Ein
    vorhandener Archiv-Eintrag wird nie überschrieben."""
    import docodetect.config as cfgmod
    from docodetect.analysis import publish_run
    monkeypatch.setattr(cfgmod, "project_root", lambda: tmp_path)
    reports_dir = tmp_path / "caps"
    reports_dir.mkdir()
    _write(reports_dir, "a1", _rep(label="A", verdict="correct",
                                   cands=[_cand("A", -0.1)]))
    cfg = {"matching": dict(MATCHING),
           "analysis": {"output_dir": "r", "publish_dir": "archive"},
           "geometry": {"camera_height_mm": 300.0},
           "paths": {"db_file": str(tmp_path / "t.sqlite3")}}
    out = run_analysis(cfg, reports_dir, run_id="pub", archive=True)
    assert (out / "reports" / "a1.json").exists()      # roh archiviert im Lauf

    dest = publish_run(cfg, out)
    assert dest == tmp_path / "archive" / "pub"
    # Kontrakt: ALLE Top-Level-Artefakte des Laufs, NICHTS aus Unterordnern
    # (welche Plots entstehen, hängt vom Report-Material ab)
    src_files = sorted(p.name for p in out.iterdir() if p.is_file())
    copied = sorted(p.name for p in dest.iterdir())
    assert copied == src_files
    assert "report.md" in copied and "metrics.json" in copied
    assert not (dest / "reports").exists()             # rohe JSONs NICHT kopiert
    assert "a1.json" not in copied
    with pytest.raises(FileExistsError):
        publish_run(cfg, out)                          # nie überschreiben


def test_run_analysis_survives_unlabeled_only(tmp_path, monkeypatch):
    """Nur unbewertete Reports: Auswertungen werden uebersprungen statt zu
    crashen, metrics.json + report.md entstehen trotzdem."""
    import docodetect.config as cfgmod
    monkeypatch.setattr(cfgmod, "project_root", lambda: tmp_path)
    reports_dir = tmp_path / "caps"
    reports_dir.mkdir()
    _write(reports_dir, "u1", _rep(cands=[_cand("A", -0.2)]))
    cfg = {"matching": dict(MATCHING), "analysis": {"output_dir": "r"},
           "geometry": {"camera_height_mm": 300.0},
           "paths": {"db_file": str(tmp_path / "t.sqlite3")}}
    out = run_analysis(cfg, reports_dir, run_id="empty")
    md = (out / "report.md").read_text(encoding="utf-8")
    assert "Übersprungen" in md
    metrics = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["quotas"]["accuracy_top1"]["n"] == 0
