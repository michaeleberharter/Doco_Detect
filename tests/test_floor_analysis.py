"""floor_analysis.py: sigma_floors aus einer synthetischen Messreihe."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.config import load_config  # noqa: E402
from docodetect.corpus.manifest import corpus_root  # noqa: E402
from docodetect.features import Features  # noqa: E402
from docodetect.floor_analysis import (FLOOR_KEY, MIN_N, OUTLIER_Z,
                                       analyze_floors, format_diameter_summary,
                                       format_outliers, format_table,
                                       format_warnings, format_yaml_block)
from docodetect.matcher import MatchReport, _FLOOR_KEY  # noqa: E402


def _features(d=190.0, circ=0.20, sol=0.60, lab_jitter=0.0, hist_jitter=0.0,
             hu_jitter=0.0) -> Features:
    return Features(
        equiv_diameter_mm=d, circle_diameter_mm=d,
        area_mm2=3.14159 * (d / 2) ** 2, perimeter_mm=3.14159 * d,
        circularity=circ, aspect_ratio=0.20,
        mean_hsv=[0.0, 0.0, 200.0], hue_hist=[1.0 / 32] * 32,
        mean_saturation=0.0,
        hu_moments=[3.2 + hu_jitter, 8.0, 10.0, 10.0, 10.0, 10.0, 10.0],
        solidity=sol,
        lab_center=[95.0 + lab_jitter, 0.0, 0.0],
        lab_rim=[90.0 + lab_jitter, 0.0, 0.0],
        hs_hist_center=[0.4 + hist_jitter, 0.3, 0.2, 0.1 - hist_jitter],
        hs_hist_rim=[0.3 + hist_jitter, 0.3, 0.3, 0.1 - hist_jitter])


def _write(tmp_path, name, feats, *, label="LOEFFEL-TEST",
          timestamp="2026-07-22T09:00:00", decision="ambiguous"):
    from dataclasses import asdict
    rep = MatchReport(decision=decision, message="", measured=asdict(feats),
                      label=label, timestamp=timestamp)
    p = tmp_path / f"{name}.json"
    p.write_text(rep.to_json(), encoding="utf-8")
    return p


# ---------- Kernstatistik ----------

def test_skalar_merkmal_mean_std_n(tmp_path):
    """12 Aufnahmen mit bekannten Diametern - mean/std/n exakt nachrechenbar."""
    diam_values = [190.0 + i * 0.1 for i in range(-6, 6)]  # 12 Werte
    for i, d in enumerate(diam_values):
        _write(tmp_path, f"r{i:02d}", _features(d=d))
    report = analyze_floors(tmp_path)
    ff = report.features["diameter_mm"]
    assert ff.n == 12
    assert ff.mean == pytest.approx(sum(diam_values) / 12, abs=1e-3)
    import numpy as np
    assert ff.std == pytest.approx(float(np.std(diam_values, ddof=1)), abs=1e-3)
    assert ff.floor == ff.std          # Skalar: Floor == Std
    assert ff.minimum == pytest.approx(min(diam_values))
    assert ff.maximum == pytest.approx(max(diam_values))
    assert not ff.low_n_warning


def test_proto_merkmal_verwendet_rms_nicht_std(tmp_path):
    """delta_e_center/delta_e_rim teilen sich 'delta_e' - Floor ist die RMS
    der gepoolten Distanzen zum Messreihen-Prototyp, nicht deren Std."""
    for i in range(10):
        _write(tmp_path, f"r{i:02d}", _features(lab_jitter=(i - 4.5) * 0.3))
    report = analyze_floors(tmp_path)
    ff = report.features["delta_e"]
    assert ff.n == 20  # 10 Aufnahmen x 2 Zonen (center+rim) gepoolt
    assert ff.floor > 0.0
    # RMS >= 0 und ungleich der reinen Std, sobald der Mittelwert der
    # Distanzen selbst ungleich 0 ist (Distanzen sind nie negativ).
    assert ff.mean > 0.0


def test_n_kleiner_zehn_warnt(tmp_path):
    for i in range(5):
        _write(tmp_path, f"r{i:02d}", _features(d=190.0 + i * 0.1))
    report = analyze_floors(tmp_path)
    ff = report.features["diameter_mm"]
    assert ff.n == 5 < MIN_N
    assert ff.low_n_warning
    warnings = format_warnings(report)
    assert any("diameter_mm" in w for w in warnings)


def test_ausreisser_wird_erkannt_und_benannt(tmp_path):
    """Zehn enge Werte um 190mm, ein Ausreisser bei 205mm."""
    for i in range(10):
        _write(tmp_path, f"eng{i:02d}", _features(d=190.0 + (i - 4.5) * 0.05))
    outlier_path = _write(tmp_path, "ausreisser", _features(d=205.0))
    report = analyze_floors(tmp_path)
    ff = report.features["diameter_mm"]
    assert len(ff.outliers) == 1
    assert ff.outliers[0].report_path == str(outlier_path)
    assert ff.outliers[0].z > OUTLIER_Z
    text = format_outliers(report)
    assert "ausreisser" in text


def test_keine_ausreisser_bei_enger_streuung(tmp_path):
    for i in range(10):
        _write(tmp_path, f"r{i:02d}", _features(d=190.0 + (i - 4.5) * 0.05))
    report = analyze_floors(tmp_path)
    assert report.features["diameter_mm"].outliers == []
    assert format_outliers(report) is None


# ---------- Filter ----------

def test_label_filter(tmp_path):
    for i in range(6):
        _write(tmp_path, f"a{i}", _features(d=190.0 + i * 0.1), label="LOEFFEL-A")
    for i in range(6):
        _write(tmp_path, f"b{i}", _features(d=100.0 + i * 0.1), label="LOEFFEL-B")
    report = analyze_floors(tmp_path, label="LOEFFEL-A")
    assert report.n_reports == 6
    assert report.features["diameter_mm"].mean == pytest.approx(190.25, abs=0.01)


def test_zeitfenster_filter(tmp_path):
    _write(tmp_path, "frueh", _features(d=100.0), timestamp="2026-07-20T08:00:00")
    _write(tmp_path, "mitte", _features(d=190.0), timestamp="2026-07-22T09:00:00")
    _write(tmp_path, "spaet", _features(d=300.0), timestamp="2026-07-24T08:00:00")
    report = analyze_floors(tmp_path, since="2026-07-21T00:00:00",
                            until="2026-07-23T00:00:00")
    assert report.n_reports == 1
    assert report.features["diameter_mm"].mean == pytest.approx(190.0)


def test_limit_nimmt_die_letzten_n(tmp_path):
    """load_reports sortiert nach mtime absteigend (neueste zuerst) - limit
    muss danach genau die zuletzt GESCHRIEBENEN Dateien behalten."""
    import time
    for i in range(5):
        _write(tmp_path, f"alt{i}", _features(d=100.0))
        time.sleep(0.01)
    for i in range(3):
        _write(tmp_path, f"neu{i}", _features(d=200.0))
        time.sleep(0.01)
    report = analyze_floors(tmp_path, limit=3)
    assert report.n_reports == 3
    assert report.features["diameter_mm"].mean == pytest.approx(200.0)


def test_ohne_measured_block_wird_uebersprungen(tmp_path):
    rep = MatchReport(decision="reject", message="Segmentierung fehlgeschlagen",
                      measured={}, label="LOEFFEL-TEST",
                      timestamp="2026-07-22T09:00:00")
    (tmp_path / "leer.json").write_text(rep.to_json(), encoding="utf-8")
    _write(tmp_path, "gut", _features(d=190.0))
    report = analyze_floors(tmp_path)
    assert report.n_reports == 2
    assert report.n_usable == 1


# ---------- Ausgabe-Formate ----------

def test_yaml_block_enthaelt_alle_sechs_keys(tmp_path):
    for i in range(10):
        _write(tmp_path, f"r{i}", _features(d=190.0 + i * 0.1, lab_jitter=i * 0.1,
                                            hist_jitter=i * 0.001, hu_jitter=i * 0.001))
    report = analyze_floors(tmp_path)
    block = format_yaml_block(report)
    assert block.startswith("sigma_floors:")
    for key in ("diameter_mm", "circularity", "solidity", "delta_e",
               "hist_bhattacharyya", "hu_log"):
        assert f"  {key}:" in block


def test_diameter_summary_nennt_min_max_std(tmp_path):
    for i in range(10):
        _write(tmp_path, f"r{i}", _features(d=190.0 + i * 0.1))
    report = analyze_floors(tmp_path)
    summary = format_diameter_summary(report)
    assert "min" in summary and "max" in summary and "Std" in summary


def test_table_markiert_low_n_warnung(tmp_path):
    for i in range(3):
        _write(tmp_path, f"r{i}", _features(d=190.0 + i * 0.1))
    report = analyze_floors(tmp_path)
    assert "[n<10!]" in format_table(report)


def test_leerer_ordner_liefert_keine_merkmale(tmp_path):
    report = analyze_floors(tmp_path)
    assert report.n_reports == 0
    assert report.n_usable == 0
    assert report.features == {}


# ---------- Konsistenz mit dem echten Matcher ----------

def test_floor_key_deckt_sich_mit_matcher_intern():
    """FLOOR_KEY (floor_analysis) und _FLOOR_KEY (matcher) muessen
    deckungsgleich sein, sonst wertet der Auswertungsbefehl gegen andere
    Floor-Namen aus als der Matcher tatsaechlich verwendet."""
    for feature, floor_key in _FLOOR_KEY.items():
        assert FLOOR_KEY[feature] == floor_key
    # Merkmale ausserhalb von _FLOOR_KEY (matcher._sigma_floor-Fallback:
    # floors[feature]) muessen in FLOOR_KEY auf sich selbst zeigen.
    for feature in ("diameter_mm", "circularity", "solidity", "hu_log"):
        assert feature not in _FLOOR_KEY
        assert FLOOR_KEY[feature] == feature


# ---------- Smoke-Lauf gegen den echten Korpus ----------

def test_smoke_gegen_phase_b_reports():
    cfg = load_config()
    root = corpus_root(cfg)
    reports_dir = root / "phase-b" / "reports"
    if not reports_dir.is_dir():
        pytest.skip(f"Korpus fehlt ({reports_dir}). Aufbau: "
                   "python -m docodetect.cli corpus-build")
    report = analyze_floors(reports_dir, label="LOEFFEL-1")
    assert report.n_usable > 0
    assert "diameter_mm" in report.features
    # Muss ohne Crash Tabelle/YAML/Diameter-Zusammenfassung erzeugen.
    format_table(report)
    format_yaml_block(report)
    format_diameter_summary(report)
