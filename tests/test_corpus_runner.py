"""Runner: Fingerprints, Filter, deterministische Reihenfolge, Cache."""

import json
import math
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import docodetect.config
from docodetect.corpus import runner
from docodetect.corpus.bundle import bundle_cfg
from docodetect.corpus.compare import FAIL, PASS
from docodetect.corpus.manifest import ImageEntry, Manifest
from docodetect.corpus.runner import (auswahl, bundle_fingerprint,
                                      code_fingerprint, config_fingerprint,
                                      golden_fingerprint, run_corpus, run_one)
from docodetect.matcher import MatchReport


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
    assert config_fingerprint(a, tier=2) != config_fingerprint(b, tier=2)


def test_config_fingerprint_ignores_irrelevant_sections():
    a = {"matching": {"max_z_accept": 3.5}, "features": {}, "geometry": {},
         "camera": {"index": 0}}
    b = {"matching": {"max_z_accept": 3.5}, "features": {}, "geometry": {},
         "camera": {"index": 1}}
    assert config_fingerprint(a, tier=2) == config_fingerprint(b, tier=2)


# ---------- Tier-gerechte Fingerprints ----------
# Tier 1 (measure_shot: segment()+extract()) ruft matcher.py nie auf -
# ein reiner matching-Wert (z.B. ein sigma_floor) darf den Tier-1-Cache
# NICHT invalidieren, sonst rechnet --changed-only nach jeder Schwellen-
# Aenderung 129 Bilder unnoetig neu. Tier 2 (Pipeline.identify()) durchlaeuft
# zusaetzlich match() und muss auf jede matching-Aenderung reagieren - siehe
# README "Welche Config repliziert Tier 2?".

def test_matching_aenderung_invalidiert_nur_tier2_cache():
    a = {"matching": {"sigma_floors": {"diameter_mm": 1.5}}, "features": {},
        "geometry": {}}
    b = {"matching": {"sigma_floors": {"diameter_mm": 2.0}}, "features": {},
        "geometry": {}}
    assert config_fingerprint(a, tier=1) == config_fingerprint(b, tier=1)
    assert config_fingerprint(a, tier=2) != config_fingerprint(b, tier=2)


def test_features_aenderung_invalidiert_beide_tiers():
    a = {"matching": {}, "features": {"ring_zones": {"center_max": 0.60}},
        "geometry": {}}
    b = {"matching": {}, "features": {"ring_zones": {"center_max": 0.65}},
        "geometry": {}}
    assert config_fingerprint(a, tier=1) != config_fingerprint(b, tier=1)
    assert config_fingerprint(a, tier=2) != config_fingerprint(b, tier=2)


def test_geometry_aenderung_invalidiert_keinen_cache():
    """geometry.camera_height_mm wird nur einmalig beim Kalibrieren gelesen
    (calibration.calibrate_from_image) und landet in calibration.json -
    load_calibration() liest beim Replay NIE die Live-Config, sondern das
    eingefrorene Buendel (bereits ueber bundle_fingerprint() erfasst)."""
    a = {"matching": {}, "features": {}, "geometry": {"camera_height_mm": 300.0}}
    b = {"matching": {}, "features": {}, "geometry": {"camera_height_mm": 250.0}}
    assert config_fingerprint(a, tier=1) == config_fingerprint(b, tier=1)
    assert config_fingerprint(a, tier=2) == config_fingerprint(b, tier=2)


def test_reine_paths_aenderung_invalidiert_keinen_cache():
    a = {"matching": {}, "features": {}, "geometry": {},
        "paths": {"corpus_dir": "../a"}}
    b = {"matching": {}, "features": {}, "geometry": {},
        "paths": {"corpus_dir": "../b"}}
    assert config_fingerprint(a, tier=1) == config_fingerprint(b, tier=1)
    assert config_fingerprint(a, tier=2) == config_fingerprint(b, tier=2)


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


# --- M1: subset=0 ---------------------------------------------------------

def test_subset_null_liefert_nichts():
    """subset=0 heisst 'kein Bild', nicht 'alle Bilder'."""
    e = [_e(f"{i:02x}" * 32) for i in range(4)]
    assert auswahl(e, subset=0) == []
    assert len(auswahl(e, subset=None)) == 4


# --- Testkorpus im tmp_path ----------------------------------------------

def _schreibe_korpus(root: Path, entry: ImageEntry, golden: MatchReport,
                     *, mit_bundle: bool = True) -> None:
    """Minimaler Korpus: ein Bild, ein Golden-Report, optional ein Buendel."""
    import cv2
    import numpy as np

    img_p = root / entry.image_rel
    img_p.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(img_p), np.zeros((8, 8, 3), dtype=np.uint8))
    rep_p = root / entry.report_rel
    rep_p.parent.mkdir(parents=True, exist_ok=True)
    rep_p.write_text(golden.to_json(), encoding="utf-8")
    if mit_bundle:
        (root / entry.session / "bundle").mkdir(parents=True, exist_ok=True)


def _ctx(root: Path) -> None:
    runner._CTX.clear()
    runner._CTX.update({"cfg": {}, "root": Path(root), "bundles": {}})


@pytest.fixture(autouse=True)
def _ctx_sauber():
    yield
    runner._CTX.pop("bundles", None)
    runner._CTX.pop("root", None)
    runner._CTX.pop("cfg", None)


# --- C1: Falsch-Gruen bei Segmentierungsausfall ---------------------------

def _seg_boom(monkeypatch):
    from docodetect.segmentation import SegmentationError

    def boom(img, cfg):
        raise SegmentationError("Randberuehrung")

    monkeypatch.setattr("docodetect.pipeline.measure_shot", boom)


def test_segfehler_mit_leerem_measured_ist_reproduziert(tmp_path, monkeypatch):
    """Golden ohne measured -> auch dort brach die Segmentierung ab -> PASS."""
    e = _e("aa" * 32, tier=1)
    golden = MatchReport(decision="reject", message="", measured={},
                         touches_border=True)
    _schreibe_korpus(tmp_path, e, golden)
    _ctx(tmp_path)
    _seg_boom(monkeypatch)
    r = run_one(asdict(e), 1, "testlauf")
    assert r["band"] == PASS, r
    assert r["error"] is None


def test_segfehler_bei_messbarem_golden_ist_fail(tmp_path, monkeypatch):
    """decision == 'reject' taugt NICHT als Diskriminator: der Golden hat
    ein gefuelltes measured, die Messung gelang damals also."""
    e = _e("bb" * 32, tier=1)
    golden = MatchReport(decision="reject", message="",
                         measured={"equiv_diameter_mm": 42.0},
                         touches_border=False)
    _schreibe_korpus(tmp_path, e, golden)
    _ctx(tmp_path)
    _seg_boom(monkeypatch)
    r = run_one(asdict(e), 1, "testlauf")
    assert r["band"] == FAIL, r
    assert "messbar" in (r["error"] or "")


# --- C2: Tier 1 darf nicht ins Buendel schreiben --------------------------

def test_tier1_cfg_zeigt_nicht_ins_buendel(tmp_path):
    bdir = tmp_path / "phase-b" / "bundle"
    bcfg = bundle_cfg({}, bdir)
    t1 = runner._tier1_cfg(bcfg)
    assert Path(t1["paths"]["db_file"]).parent != bdir
    assert str(bdir) not in t1["paths"]["db_file"]
    # Buendel-Config bleibt unveraendert (Tier 2 braucht die echte DB).
    assert bcfg["paths"]["db_file"] == str(bdir / "db.sqlite3")


def test_tier1_replay_bekommt_keine_buendel_db(tmp_path, monkeypatch):
    """Die Config, die measure_shot im Tier-1-Zweig erhaelt, darf ihre
    db_file nicht im eingefrorenen Buendel haben."""
    e = _e("cc" * 32, tier=1)
    golden = MatchReport(decision="accept", message="", measured={})
    _schreibe_korpus(tmp_path, e, golden)
    _ctx(tmp_path)
    gesehen = {}

    def fake_measure(img, cfg):
        gesehen["db_file"] = cfg["paths"]["db_file"]
        raise RuntimeError("stopp")

    monkeypatch.setattr("docodetect.pipeline.measure_shot", fake_measure)
    run_one(asdict(e), 1, "testlauf")
    bdir = tmp_path / e.session / "bundle"
    assert gesehen, "measure_shot wurde nicht aufgerufen"
    assert str(bdir) not in gesehen["db_file"]
    assert not (bdir / "db.sqlite3").exists()


# --- I1: Cache-Schluessel --------------------------------------------------

def _fake_quellbaum(root: Path) -> None:
    (root / "docodetect" / "corpus").mkdir(parents=True, exist_ok=True)
    for name in runner.CODE_DATEIEN:
        p = root / "docodetect" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"# {name}\n", encoding="utf-8")


def test_code_fingerprint_umfasst_corpus_compare(tmp_path, monkeypatch):
    """Die QUANTUM/SOFT-Tabellen aus compare.py erzeugen den gecachten
    Bandwert – eine Aenderung dort muss den Cache invalidieren."""
    assert "corpus/compare.py" in runner.CODE_DATEIEN
    _fake_quellbaum(tmp_path)
    monkeypatch.setattr(runner, "project_root", lambda: tmp_path)
    vorher = code_fingerprint()
    (tmp_path / "docodetect" / "corpus" / "compare.py").write_text(
        "SOFT = {'area_mm2': 99.0}\n", encoding="utf-8")
    assert code_fingerprint() != vorher


def test_code_fingerprint_umfasst_runner_und_bundle(tmp_path, monkeypatch):
    """runner.py haelt den Diskriminator fuer Segmentierungs-Abbrueche und
    _tier1_cfg, bundle.py baut ueber bundle_cfg die Replay-Config. Beide
    entscheiden mit ueber jeden gecachten Bandwert."""
    assert "corpus/runner.py" in runner.CODE_DATEIEN
    assert "corpus/bundle.py" in runner.CODE_DATEIEN
    _fake_quellbaum(tmp_path)
    monkeypatch.setattr(runner, "project_root", lambda: tmp_path)
    for name in ("corpus/runner.py", "corpus/bundle.py"):
        vorher = code_fingerprint()
        (tmp_path / "docodetect").joinpath(*name.split("/")).write_text(
            f"# abgeschwaecht {name}\n", encoding="utf-8")
        assert code_fingerprint() != vorher, f"{name} invalidiert den Cache nicht"


def test_code_fingerprint_meldet_fehlenden_bestandteil(tmp_path, monkeypatch):
    """Ein still uebergangener Bestandteil waere schlimmer als keiner."""
    _fake_quellbaum(tmp_path)
    (tmp_path / "docodetect" / "corpus" / "compare.py").unlink()
    monkeypatch.setattr(runner, "project_root", lambda: tmp_path)
    with pytest.raises(FileNotFoundError):
        code_fingerprint()


def test_golden_fingerprint_reagiert_auf_korrigiertes_golden(tmp_path):
    e = _e("dd" * 32)
    _schreibe_korpus(tmp_path, e, MatchReport(decision="accept", message=""))
    vorher = golden_fingerprint(tmp_path, e)
    (tmp_path / e.report_rel).write_text(
        MatchReport(decision="reject", message="").to_json(), encoding="utf-8")
    assert golden_fingerprint(tmp_path, e) != vorher


def test_bundle_fingerprint_reagiert_auf_neuen_db_snapshot(tmp_path):
    bdir = tmp_path / "phase-b" / "bundle"
    bdir.mkdir(parents=True)
    (bdir / "db.sqlite3").write_bytes(b"alt")
    vorher = bundle_fingerprint(tmp_path, "phase-b")
    (bdir / "db.sqlite3").write_bytes(b"neuer snapshot mit anderer laenge")
    assert bundle_fingerprint(tmp_path, "phase-b") != vorher


def test_cache_key_haengt_an_golden_und_buendel():
    basis = dict(sha="aa", tier=1, code_fp="c" * 64, cfg_fp="d" * 64)
    k1 = runner._cache_key(**basis, golden_fp="1" * 64, bundle_fp="2" * 64)
    k2 = runner._cache_key(**basis, golden_fp="9" * 64, bundle_fp="2" * 64)
    k3 = runner._cache_key(**basis, golden_fp="1" * 64, bundle_fp="9" * 64)
    assert len({k1, k2, k3}) == 3


# --- Orchestrierung mit Stub-Executor -------------------------------------

class _FakeExecutor:
    def __init__(self, *a, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def map(self, fn, *iterables, **kw):
        return list(map(fn, *iterables))


def _stub_run_one(entry_dict, tier, run_id):
    return {"sha": entry_dict["sha"], "session": entry_dict["session"],
            "article": entry_dict["article"], "tier": tier,
            "tier_capability": entry_dict["tier"], "band": PASS,
            "diffs": [], "error": None, "run_id": run_id}


def _prep(monkeypatch, tmp_path, entries, stub=_stub_run_one):
    m = Manifest(images=list(entries))
    monkeypatch.setattr(runner, "corpus_root", lambda cfg: tmp_path)
    monkeypatch.setattr(runner.Manifest, "load", staticmethod(lambda: m))
    monkeypatch.setattr(runner, "ProcessPoolExecutor", _FakeExecutor)
    monkeypatch.setattr(runner, "run_one", stub)
    # Der Waechter liest sonst die ECHTE config.local.yaml dieses Rechners —
    # dann haengen saemtliche Orchestrierungs-Tests an einer unversionierten
    # Datei. Er hat eigene Tests weiter unten.
    monkeypatch.setattr(docodetect.config, "local_override", lambda p=None: {})


# --- I2: Cache mergen statt ueberschreiben --------------------------------

def test_teillauf_wirft_den_cache_des_vollen_laufs_nicht_weg(tmp_path,
                                                             monkeypatch):
    entries = [_e(f"{i:02x}" * 32, tier=1) for i in range(4)]
    _prep(monkeypatch, tmp_path, entries)
    run_corpus({}, tier=1, workers=1)          # voller Lauf fuellt den Cache
    voll = json.loads(runner._cache_path(tmp_path).read_text(encoding="utf-8"))
    assert len(voll) == 4
    run_corpus({}, tier=1, workers=1, subset=1)   # Teillauf
    danach = json.loads(runner._cache_path(tmp_path).read_text(encoding="utf-8"))
    assert len(danach) == 4, "Teillauf hat den Cache des vollen Laufs geleert"


# --- I4: gefahrene Stufe vs. Faehigkeit -----------------------------------

def test_tier_haelt_die_gefahrene_stufe(tmp_path, monkeypatch):
    e = _e("ee" * 32, tier=2)                      # Tier-2-faehiges Bild
    golden = MatchReport(decision="accept", message="", measured={})
    _schreibe_korpus(tmp_path, e, golden)
    _ctx(tmp_path)
    _seg_boom(monkeypatch)
    r = run_one(asdict(e), 1, "testlauf")          # aber Tier-1-Lauf
    assert r["tier"] == 1
    assert r["tier_capability"] == 2


# --- I5: Replay-Reports je Lauf -------------------------------------------

def test_run_corpus_liefert_und_reicht_run_id_durch(tmp_path, monkeypatch):
    entries = [_e("ff" * 32, tier=1)]
    gesehen = []

    def stub(entry_dict, tier, run_id):
        gesehen.append(run_id)
        return _stub_run_one(entry_dict, tier, run_id)

    _prep(monkeypatch, tmp_path, entries, stub)
    out = run_corpus({}, tier=1, workers=1, run_id="lauf-42")
    assert out["run_id"] == "lauf-42"
    assert gesehen == ["lauf-42"]


def test_run_corpus_erzeugt_run_id_ohne_vorgabe(tmp_path, monkeypatch):
    _prep(monkeypatch, tmp_path, [_e("ab" * 32, tier=1)])
    out = run_corpus({}, tier=1, workers=1)
    assert out["run_id"] and out["run_id"] != "_replay"


def test_replay_pfad_haengt_am_run_id(tmp_path):
    a = runner._replay_dir(tmp_path, "lauf-a")
    b = runner._replay_dir(tmp_path, "lauf-b")
    assert a != b
    assert a == tmp_path / "runs" / "lauf-a" / "replay"


# --- I6: eine Exception darf den Lauf nicht abreissen ---------------------

def test_kaputter_manifest_eintrag_erzeugt_fail_statt_abbruch(tmp_path):
    _ctx(tmp_path)
    kaputt = asdict(_e("ba" * 32, tier=1))
    kaputt["unbekanntes_feld"] = 1
    r = run_one(kaputt, 1, "testlauf")
    assert r["band"] == FAIL
    assert r["error"]


def test_fehlendes_buendel_erzeugt_fail_statt_abbruch(tmp_path, monkeypatch):
    e = _e("bc" * 32, tier=1)
    _ctx(tmp_path)

    def kein_buendel(cfg, bundle_dir):
        raise FileNotFoundError(f"Buendel fehlt: {bundle_dir}")

    monkeypatch.setattr(runner, "bundle_cfg", kein_buendel)
    r = run_one(asdict(e), 1, "testlauf")
    assert r["band"] == FAIL
    assert "Buendel" in (r["error"] or "") or r["error"]


def test_tier2_ohne_buendel_db_ist_fail_und_legt_nichts_an(tmp_path):
    """build_corpus loescht die Buendel-DB, sobald eine Session den Abgleich
    nicht mehr besteht, revidiert aber bestehende ImageEntry.tier-Werte nie.
    sqlite3.connect wuerde dann eine 0-Byte-Datei in den fingerprint-
    verifizierten Session-Zustand schreiben und der Lauf liefe weiter."""
    e = _e("cd" * 32, tier=2)
    golden = MatchReport(decision="accept", message="", measured={})
    _schreibe_korpus(tmp_path, e, golden)
    _ctx(tmp_path)
    db = tmp_path / e.session / "bundle" / "db.sqlite3"
    assert not db.exists()

    r = run_one(asdict(e), 2, "testlauf")
    assert r["band"] == FAIL, r
    assert "db.sqlite3" in (r["error"] or "") or "Buendel-DB" in (r["error"] or "")
    assert not db.exists(), "Tier-2-Replay hat eine leere Buendel-DB angelegt"


# --- M2: Zentroid kommt aus pipeline --------------------------------------

def test_zentroid_wird_aus_pipeline_importiert():
    from docodetect.pipeline import _centroid_px
    assert runner._centroid_px is _centroid_px


# --- Waechter: keine fingerprinteten Abschnitte in der lokalen Config -----
# Hintergrund: die Tier-2-Baseline vom 2026-07-21 wurde gegen sigma_floors
# aus einer unversionierten config.local.yaml gerechnet. Der Vergleich lief
# damit gegen Werte, die im Repo nirgends stehen.

def _lokale_config(tmp_path, text: str) -> Path:
    """Legt config.local.yaml neben eine (nicht benoetigte) config.yaml und
    gibt den Pfad der Haupt-Config zurueck — genau das, was der Waechter
    als config_path bekommt."""
    (tmp_path / "config.local.yaml").write_text(text, encoding="utf-8")
    return tmp_path / "config.yaml"


def test_waechter_laesst_maschinen_spezifisches_durch(tmp_path):
    haupt = _lokale_config(tmp_path, "camera:\n  index: 1\n"
                                     "geometry:\n  camera_height_mm: 412.0\n")
    runner.pruefe_lokale_overrides(haupt)      # wirft nicht


def test_waechter_ohne_lokale_config(tmp_path):
    runner.pruefe_lokale_overrides(tmp_path / "config.yaml")   # wirft nicht


@pytest.mark.parametrize("abschnitt", ["matching", "features"])
def test_waechter_bricht_bei_fingerprintetem_abschnitt_ab(tmp_path, abschnitt):
    haupt = _lokale_config(
        tmp_path, f"camera:\n  index: 1\n{abschnitt}:\n"
                  f"  sigma_floors:\n    hu_log: 0.35\n")
    with pytest.raises(RuntimeError) as exc:
        runner.pruefe_lokale_overrides(haupt)
    assert abschnitt in str(exc.value)
    assert "config.yaml" in str(exc.value), "Meldung nennt den richtigen Ort nicht"


def test_waechter_deckt_alle_fingerprint_abschnitte_ab():
    """Kommt spaeter ein Abschnitt in CONFIG_TEILE_* dazu, muss ihn der
    Waechter automatisch mitnehmen — sonst entsteht genau dieselbe Luecke
    an anderer Stelle neu."""
    assert set(runner.FINGERPRINT_ABSCHNITTE) == (
        set(runner.CONFIG_TEILE_TIER1) | set(runner.CONFIG_TEILE_TIER2))


def test_waechter_greift_vor_dem_rechnen(tmp_path, monkeypatch):
    """Der Abbruch muss VOR dem ersten Bild kommen: ein Lauf, der erst
    rechnet und dann meckert, schreibt bereits Cache-Eintraege gegen die
    unversionierten Werte."""
    gerechnet = []

    def stub(entry_dict, tier, run_id):
        gerechnet.append(entry_dict["sha"])
        return _stub_run_one(entry_dict, tier, run_id)

    _prep(monkeypatch, tmp_path, [_e("da" * 32, tier=1)], stub)
    # _prep neutralisiert den Waechter - hier wird er absichtlich zurueckgeholt.
    monkeypatch.setattr(docodetect.config, "local_override",
                        lambda p=None: {"matching": {"sigma_floors": {}}})
    with pytest.raises(RuntimeError, match="matching"):
        run_corpus({}, tier=1, workers=1)
    assert gerechnet == [], "Waechter hat erst nach dem Rechnen gegriffen"
    assert not runner._cache_path(tmp_path).exists(), "Cache trotz Abbruch geschrieben"


# --- M5: NaN im Cache-JSON ------------------------------------------------

def test_nan_deltas_werden_als_null_serialisiert():
    roh = {"band": FAIL, "diffs": [{"field": "decision", "delta": float("nan")}],
           "tief": [{"x": float("inf")}]}
    safe = runner._json_safe(roh)
    assert safe["diffs"][0]["delta"] is None
    assert safe["tief"][0]["x"] is None
    json.dumps(safe, allow_nan=False)      # wirft nicht


def test_cache_datei_ist_striktes_json(tmp_path, monkeypatch):
    def stub(entry_dict, tier, run_id):
        r = _stub_run_one(entry_dict, tier, run_id)
        r["diffs"] = [{"field": "decision", "golden": "a", "actual": "b",
                       "delta": float("nan"), "band": FAIL}]
        return runner._json_safe(r)

    _prep(monkeypatch, tmp_path, [_e("bd" * 32, tier=1)], stub)
    run_corpus({}, tier=1, workers=1)
    roh = runner._cache_path(tmp_path).read_text(encoding="utf-8")
    json.loads(roh, parse_constant=lambda c: (_ for _ in ()).throw(
        AssertionError(f"kein striktes JSON: {c}")))


# --- Befund 2: Cache-Treffer muessen den Replay-Report mitbringen ----------

def test_cache_treffer_materialisiert_replay_report(tmp_path, monkeypatch):
    """Ein --changed-only-Lauf muss runs/<run_id>/replay/ vollstaendig
    fuellen, sonst rechnet cmd_corpus_run die Tier-2-Quoten nur ueber die
    frisch gerechnete Teilmenge."""
    e = _e("c1" * 32, tier=2)

    def stub(entry_dict, tier, run_id):
        r = _stub_run_one(entry_dict, tier, run_id)
        # run_one legt den Report ab UND reicht ihn im Ergebnis mit.
        replay = runner._replay_dir(tmp_path, run_id)
        replay.mkdir(parents=True, exist_ok=True)
        text = MatchReport(decision="accept", message="", measured={}).to_json()
        (replay / f"{entry_dict['sha'][:8]}.json").write_text(text,
                                                              encoding="utf-8")
        r["replay_json"] = text
        return r

    _prep(monkeypatch, tmp_path, [e], stub)
    run_corpus({}, tier=2, workers=1, run_id="lauf-1")   # fuellt den Cache
    assert (runner._replay_dir(tmp_path, "lauf-1") / f"{e.sha[:8]}.json").exists()

    out = run_corpus({}, tier=2, workers=1, changed_only=True,
                     run_id="lauf-2")
    assert out["neu_gerechnet"] == 0, "Lauf 2 kam nicht aus dem Cache"
    ziel = runner._replay_dir(tmp_path, "lauf-2") / f"{e.sha[:8]}.json"
    assert ziel.exists(), "Cache-Treffer hat keinen Replay-Report im neuen Lauf"
    assert MatchReport.from_json(ziel.read_text(encoding="utf-8")).decision \
        == "accept"


def test_tier1_ergebnis_traegt_keinen_replay_report(tmp_path, monkeypatch):
    """Tier 1 kennt keine Entscheidung — replay_json bleibt None und es
    entsteht kein Replay-Verzeichnis."""
    _prep(monkeypatch, tmp_path, [_e("c2" * 32, tier=1)])
    run_corpus({}, tier=1, workers=1, run_id="lauf-t1")
    assert not runner._replay_dir(tmp_path, "lauf-t1").exists()


def test_materialisiere_replay_ueberschreibt_frische_reports_nicht(tmp_path):
    frisch = runner._replay_dir(tmp_path, "lauf-x")
    frisch.mkdir(parents=True, exist_ok=True)
    (frisch / "aaaaaaaa.json").write_text("frisch", encoding="utf-8")
    runner._materialisiere_replay(
        tmp_path, "lauf-x", [{"sha": "aaaaaaaa" + "0" * 56,
                              "replay_json": "aus-cache"}])
    assert (frisch / "aaaaaaaa.json").read_text(encoding="utf-8") == "frisch"


# --- M6: leerer Korpus ist kein Erfolg ------------------------------------

def test_leeres_manifest_wirft(tmp_path, monkeypatch):
    _prep(monkeypatch, tmp_path, [])
    with pytest.raises(RuntimeError, match="corpus-build"):
        run_corpus({}, tier=1, workers=1)


def test_fehlendes_korpus_verzeichnis_wirft(tmp_path, monkeypatch):
    fehlt = tmp_path / "gibtsnicht"
    _prep(monkeypatch, fehlt, [_e("be" * 32, tier=1)])
    with pytest.raises(RuntimeError, match="corpus-build"):
        run_corpus({}, tier=1, workers=1)


def test_leere_auswahl_wirft(tmp_path, monkeypatch):
    _prep(monkeypatch, tmp_path, [_e("bf" * 32, session="phase-a", tier=1)])
    with pytest.raises(RuntimeError):
        run_corpus({}, tier=1, workers=1, sessions=["gibtsnicht"])
