"""Runner: Fingerprints, Filter, deterministische Reihenfolge, Cache."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.corpus.manifest import ImageEntry
from docodetect.corpus.runner import (auswahl, code_fingerprint,
                                      config_fingerprint)


def _e(sha, session="phase-b", article="LOEFFEL-1", tier=2):
    return ImageEntry(sha=sha, session=session, article=article,
                      image_rel=f"{session}/images/{article}/{sha[:8]}.png",
                      report_rel=f"{session}/reports/{sha[:8]}.json",
                      label=article, verdict="correct", tier=tier)


def test_code_fingerprint_is_stable_within_a_run():
    assert code_fingerprint() == code_fingerprint()
    assert len(code_fingerprint()) == 64


def test_config_fingerprint_reacts_to_a_threshold_change():
    a = {"matching": {"max_z_accept": 3.5}, "features": {}, "geometry": {}}
    b = {"matching": {"max_z_accept": 3.4}, "features": {}, "geometry": {}}
    assert config_fingerprint(a) != config_fingerprint(b)


def test_config_fingerprint_ignores_irrelevant_sections():
    a = {"matching": {"max_z_accept": 3.5}, "features": {}, "geometry": {},
         "camera": {"index": 0}}
    b = {"matching": {"max_z_accept": 3.5}, "features": {}, "geometry": {},
         "camera": {"index": 1}}
    assert config_fingerprint(a) == config_fingerprint(b)


def test_auswahl_is_deterministic_and_sorted():
    e = [_e("cc" * 32), _e("aa" * 32), _e("bb" * 32)]
    got = [x.sha for x in auswahl(e)]
    assert got == sorted(got)
    assert got == [x.sha for x in auswahl(list(reversed(e)))]


def test_auswahl_filters_by_session():
    e = [_e("aa" * 32, session="phase-a"), _e("bb" * 32, session="phase-b")]
    assert [x.session for x in auswahl(e, sessions=["phase-b"])] == ["phase-b"]


def test_auswahl_filters_by_article():
    e = [_e("aa" * 32, article="LOEFFEL-1"), _e("bb" * 32, article="LOEFFEL-5")]
    got = auswahl(e, articles=["LOEFFEL-5"])
    assert [x.article for x in got] == ["LOEFFEL-5"]


def test_auswahl_tier2_filter_drops_tier1_entries():
    e = [_e("aa" * 32, tier=1), _e("bb" * 32, tier=2)]
    assert [x.tier for x in auswahl(e, tier=2)] == [2]


def test_auswahl_tier1_filter_keeps_everything():
    """Tier 1 laeuft auf JEDEM Bild – auch auf den Tier-2-faehigen."""
    e = [_e("aa" * 32, tier=1), _e("bb" * 32, tier=2)]
    assert len(auswahl(e, tier=1)) == 2


def test_subset_takes_a_stable_prefix():
    e = [_e(f"{i:02x}" * 32) for i in range(10)]
    a = [x.sha for x in auswahl(e, subset=3)]
    b = [x.sha for x in auswahl(list(reversed(e)), subset=3)]
    assert a == b and len(a) == 3
