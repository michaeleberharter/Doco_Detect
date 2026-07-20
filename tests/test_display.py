"""Tests der zentralen Anzeige-Helfer (docodetect/display.py) — beide UIs
nutzen exakt diese Strings; Format hier festgeschrieben (Dezimalkomma)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.matcher import CandidateReport, FeatureScore  # noqa: E402
from docodetect.pipeline import (channel_percentages, format_delta,  # noqa: E402
                                 format_diameter, format_measured,
                                 format_rank_line, headline)


def cand(corrected=141.0, h=60.0, err=2.4, posterior=0.61, name="Teller 20",
         features=None):
    return CandidateReport(
        article_number="X", name=name, nominal_size_mm=140.0, height_mm=h,
        corrected_diameter_mm=corrected, geometry_error_mm=err,
        has_references=True, n_shots=3, features=features or [],
        log_score=0.0, posterior=posterior, max_abs_z=0.0)


def fs(feature, weighted):
    return FeatureScore(feature=feature, measured=None, reference=None,
                        distance=0.0, sigma_enroll=0.0, sigma_eff=1.0,
                        z=0.0, log_contrib=weighted, w_eff=0.1,
                        weighted=weighted)


CFG = {"matching": {"diameter_tolerance_mm": 6.0}}


def test_format_diameter_with_height():
    assert format_diameter(cand()) == "Ø 141,0 mm (höhenkorrigiert, h = 60 mm)"


def test_format_diameter_floor_plane():
    assert format_diameter(cand(corrected=180.0, h=0.0)) == "Ø 180,0 mm (Bodenebene)"


def test_format_delta():
    assert format_delta(cand(), CFG) == "Δ 2,4 mm von ±6,0"


def test_format_rank_line():
    assert format_rank_line(cand(), 2) == "2. Teller 20 · 61 %"


def test_headline_mapping():
    assert headline("accept", "Teller 20") == ("✓ Automatisch übernommen: Teller 20", "accept")
    assert headline("accept") == ("✓ Automatisch übernommen", "accept")
    assert headline("ambiguous") == ("Bitte bestätigen", "confirm")
    assert headline("reject") == ("Kein Treffer", "reject")


def test_channel_percentages_perfect_match_is_one():
    c = cand(features=[fs("diameter_mm", 0.0), fs("delta_e_center", 0.0),
                       fs("hu_log", 0.0)])
    pct = channel_percentages(c)
    assert pct["geometry"] == pytest.approx(1.0)
    assert pct["color"] == pytest.approx(1.0)
    assert pct["shape"] == pytest.approx(1.0)


def test_format_measured():
    measured = {"circle_diameter_mm": 123.4, "circularity": 0.91,
                "area_mm2": 11958.0}
    assert format_measured(measured) == (
        "Gemessen: Ø 123,4 mm (Bodenebene) · Rundheit 0,91 · Fläche 120 cm²")


def test_format_measured_missing_keys_defaults_to_zero():
    assert format_measured({}) == (
        "Gemessen: Ø 0,0 mm (Bodenebene) · Rundheit 0,00 · Fläche 0 cm²")


def test_channel_percentages_geometry_only_has_none_channels():
    """Geometry-only-Kandidat: Farbe/Form ohne Merkmale -> None (UI graut
    die Balken aus, statt faelschlich 100 % zu zeigen)."""
    c = cand(features=[fs("diameter_mm", -0.5)])
    pct = channel_percentages(c)
    assert 0.0 < pct["geometry"] < 1.0
    assert pct["color"] is None and pct["shape"] is None
