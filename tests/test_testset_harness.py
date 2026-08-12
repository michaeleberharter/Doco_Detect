"""Trockenlauf des Real-Capture-Testset-Harness (docodetect/testset).

Am Mac gibt es keine echten Daten — ein gruener Test beweist hier nur,
dass der Code laeuft. Deshalb prueft dieser Trockenlauf mit GESTELLTEN
Aufnahmen (smoke_testset-Generator), dass die Harness eine Veraenderung
auch MERKT (Abnahmekriterien der Spec):

  1. identischer Replay      -> identisches Ergebnis (byteidentische Dateien)
  2. veraendertes Capture    -> Abweichung wird gemeldet (SHA-Waechter UND
                                Pipeline-Ebene, beide einzeln belegt)
  3. veraenderter Zustand    -> Abweichung wird gemeldet (Buendel-Integritaet)
  4. unvollstaendiges Buendel-> sauberer Fehler, kein stiller Teil-Lauf

Dazu die Builder-Regeln: ueberspringen und zaehlen statt raten,
Widersprueche melden statt aufloesen, Fidelity-Pflichttest, Dedup.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import cv2
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.config import load_config  # noqa: E402
from docodetect.pipeline import Pipeline  # noqa: E402
from docodetect.reporting import (NO_MATCH, save_no_match_verdict,  # noqa: E402
                                  save_verdict)
from docodetect.smoke_testset import draw_plate, generate, make_background  # noqa: E402
from docodetect.testset import manifest as ts_manifest  # noqa: E402
from docodetect.testset.builder import build_testset  # noqa: E402
from docodetect.testset.manifest import (NO_MATCH_ARTIKEL,  # noqa: E402
                                         TestsetManifest)
from docodetect.testset.replay import replay_testset  # noqa: E402
from docodetect.testset.snapshot import pruefe_snapshot, snapshot_dir  # noqa: E402


def _cfg(basis: Path) -> dict:
    d = basis / "env"
    return {
        "camera": {"width": 1920, "height": 1080},
        "calibration": {
            "file": str(d / "calibration" / "calibration.json"),
            "background_file": str(d / "calibration" / "background.png"),
            "aruco_dict": "DICT_4X4_50", "marker_id": 0,
            "marker_size_mm": 136.0,
        },
        "geometry": {"camera_height_mm": 300.0},
        "features": {},
        "matching": json.loads(json.dumps(load_config()["matching"])),
        "paths": {"db_file": str(d / "doco_detect.sqlite3"),
                  "reference_dir": str(d / "reference"),
                  "captures_dir": str(d / "captures"),
                  "testset_dir": str(basis / "testset_root")},
    }


@pytest.fixture(scope="module")
def umgebung(tmp_path_factory):
    """Einmal je Modul: smoke-Umgebung + 7 Identifikationen + Bewertungen +
    Build + Erst-Replay. Mutations-Tests kopieren sich das Testset weg,
    statt den geteilten Stand zu veraendern."""
    mp = pytest.MonkeyPatch()
    basis = tmp_path_factory.mktemp("harness")
    cfg = _cfg(basis)
    out = basis / "testset-smoke"
    generate(cfg, out)
    mp.setattr(ts_manifest, "MANIFEST_PATH",
               basis / "repo" / "manifest.json")

    bg = make_background()
    pipe = Pipeline(cfg)
    reports = {}
    try:
        def ident(name, img_path=None, img=None):
            frame = cv2.imread(str(img_path)) if img_path is not None else img
            reports[name] = pipe.identify(frame).report
            return reports[name]

        ident("t160", sorted((out / "TELLER-160").glob("*.png"))[0])
        ident("loeffel", sorted((out / "LOEFFEL").glob("*.png"))[0])
        ident("trap", sorted((out / "TELLER-180-HOCH").glob("*.png"))[0])
        ident("unbewertet", sorted((out / "TELLER-180").glob("*.png"))[1])
        ident("ohne_artikel", sorted((out / "TELLER-DEKOR-200").glob("*.png"))[0])
        # nicht in der DB: 120-mm-Teller -> Vorfilter killt alles, NO_MATCH
        ident("fremd", img=draw_plate(bg, 120.0, 2))
        # Randberuehrung: Segmentierungs-Reject, measured bleibt leer
        ident("rand", img=draw_plate(bg, 200.0, 2, center=(300, 540)))
    finally:
        pipe.close()

    save_verdict(reports["t160"], correct=True)
    save_verdict(reports["loeffel"], correct=True)
    save_verdict(reports["trap"], correct=False,
                 true_article="TELLER-180-HOCH")
    save_verdict(reports["ohne_artikel"], correct=False, true_article=None)
    save_no_match_verdict(reports["fremd"])
    save_no_match_verdict(reports["rand"])

    stat = build_testset(cfg)
    lauf_a = replay_testset(cfg, run_id="lauf-a")
    yield {"cfg": cfg, "basis": basis, "stat": stat, "lauf_a": lauf_a,
           "reports": reports, "bg": bg}
    mp.undo()


def _testset_kopie(umgebung, tmp_path, mp) -> dict:
    """Eigene Kopie von Testset-Ordner + Manifest fuer Mutations-Tests."""
    quelle = Path(umgebung["cfg"]["paths"]["testset_dir"])
    ziel = tmp_path / "testset_root"
    shutil.copytree(quelle, ziel)
    mani_ziel = tmp_path / "manifest.json"
    shutil.copy2(umgebung["basis"] / "repo" / "manifest.json", mani_ziel)
    mp.setattr(ts_manifest, "MANIFEST_PATH", mani_ziel)
    cfg = json.loads(json.dumps(umgebung["cfg"]))
    cfg["paths"]["testset_dir"] = str(ziel)
    return cfg


# ---------- Builder ----------

def test_builder_nimmt_bewertete_und_zaehlt_rest(umgebung):
    stat = umgebung["stat"]
    assert stat["aufgenommen"] == 5
    assert stat["uebersprungen"] == {"unbewertet": 1, "falsch_ohne_artikel": 1}
    assert len(stat["snapshots_neu"]) == 1          # eine Session, EIN Snapshot
    m = TestsetManifest.load()
    assert len(m.captures) == 5
    herkuenfte = {e.artikel: e.label_herkunft for e in m.captures}
    assert herkuenfte["TELLER-160"] == "verdict-richtig"
    assert herkuenfte["TELLER-180-HOCH"] == "verdict-falsch+artikel"
    assert herkuenfte[NO_MATCH_ARTIKEL] == "verdict-richtig"
    # Ablage unter dem WAHREN Artikel, nie der Vorhersage
    root = Path(umgebung["cfg"]["paths"]["testset_dir"])
    assert (root / "captures" / "TELLER-180-HOCH").is_dir()
    fp12 = stat["snapshots_neu"][0]
    assert pruefe_snapshot(root, fp12) == []
    assert m.snapshots[fp12]["system"]              # Plattform im Manifest


def test_builder_zweiter_lauf_nur_dubletten(umgebung):
    stat2 = build_testset(umgebung["cfg"])
    assert stat2["aufgenommen"] == 0
    assert stat2["uebersprungen"]["dublette"] == 5


def test_builder_meldet_widerspruch_statt_aufloesen(umgebung, tmp_path):
    cfg = umgebung["cfg"]
    caps = Path(cfg["paths"]["captures_dir"])
    alt = json.loads(Path(umgebung["reports"]["t160"].report_path).read_text())
    # dasselbe Bild (gleicher SHA), aber als anderer Artikel bewertet
    neu_bild = caps / "99990101-000000-000.png"
    shutil.copy2(alt["image_path"], neu_bild)
    alt["image_path"] = str(neu_bild)
    alt["label"] = "TELLER-180"
    (caps / "99990101-000000-000.json").write_text(
        json.dumps(alt), encoding="utf-8")
    try:
        stat = build_testset(cfg)
        assert stat["uebersprungen"]["widerspruch_label"] == 1
        assert any("Widerspruch" in b for b in stat["befunde"])
        assert stat["aufgenommen"] == 0             # nicht aufgeloest
    finally:
        (caps / "99990101-000000-000.json").unlink()
        neu_bild.unlink()


def test_builder_ueberspringt_ohne_zustand_und_jpg(umgebung, tmp_path):
    cfg = umgebung["cfg"]
    caps = Path(cfg["paths"]["captures_dir"])
    basis = json.loads(Path(umgebung["reports"]["loeffel"].report_path).read_text())
    angelegt = []
    try:
        # a) Report ohne zustand-Block (Altbestand)
        alt = dict(basis)
        del alt["zustand"]
        p = caps / "99990101-000001-000.json"
        p.write_text(json.dumps(alt), encoding="utf-8")
        angelegt.append(p)
        # b) JPG-Capture (verlustbehaftet)
        jpg = caps / "99990101-000002-000.jpg"
        cv2.imwrite(str(jpg), cv2.imread(basis["image_path"]))
        angelegt.append(jpg)
        mit_jpg = dict(basis)
        mit_jpg["image_path"] = str(jpg)
        p2 = caps / "99990101-000002-000.json"
        p2.write_text(json.dumps(mit_jpg), encoding="utf-8")
        angelegt.append(p2)
        # c) Zustand, den es nicht mehr gibt (fremder Fingerprint)
        weg = dict(basis)
        weg["zustand"] = dict(basis["zustand"])
        weg["zustand"]["fingerprint"] = "f" * 64
        weg["zustand"]["db_zustand_sha256"] = "f" * 64
        p3 = caps / "99990101-000003-000.json"
        p3.write_text(json.dumps(weg), encoding="utf-8")
        angelegt.append(p3)

        stat = build_testset(cfg)
        assert stat["uebersprungen"]["ohne_zustand"] == 1
        assert stat["uebersprungen"]["kein_png"] == 1
        assert stat["uebersprungen"]["zustand_nicht_mehr_vorhanden"] == 1
        assert any("existiert nicht mehr" in b for b in stat["befunde"])
        assert stat["aufgenommen"] == 0
    finally:
        for p in angelegt:
            p.unlink()


def test_builder_meldet_label_ohne_db_artikel(umgebung):
    cfg = umgebung["cfg"]
    caps = Path(cfg["paths"]["captures_dir"])
    basis = json.loads(Path(umgebung["reports"]["loeffel"].report_path).read_text())
    # frisches Bild (ein Pixel anders -> neuer SHA), sonst griffe der
    # Dubletten-/Widerspruchs-Waechter VOR der Stammdaten-Pruefung
    img = cv2.imread(basis["image_path"])
    img[0, 0] = (1, 2, 3)
    neu_bild = caps / "99990101-000004-000.png"
    cv2.imwrite(str(neu_bild), img)
    fehl = dict(basis)
    fehl["image_path"] = str(neu_bild)
    fehl["verdict"] = "wrong"
    fehl["label"] = "PHANTOM-99"
    p = caps / "99990101-000004-000.json"
    p.write_text(json.dumps(fehl), encoding="utf-8")
    try:
        stat = build_testset(cfg)
        assert stat["uebersprungen"]["label_unbekannt_in_db"] == 1
        assert any("PHANTOM-99" in b for b in stat["befunde"])
    finally:
        p.unlink()
        neu_bild.unlink()


# ---------- Replay: Abnahmekriterien ----------

def test_replay_reproduziert_alle_buendel(umgebung):
    m = umgebung["lauf_a"]["metrics"]
    assert m["n"] == m["gewertet"] == 5
    assert m["abweichungen"] == 0 and m["fehler"] == 0
    assert m["vergleichbar"] is True
    # Erwartung aus den GOLDENS abgeleitet, nicht hart verdrahtet: die
    # Hoehenkompensations-Falle des smoke-Sets liefert designgemaess einen
    # falschen Accept — genau den muss die false_accept-Zaehlung sehen.
    golden_fa = sum(
        1 for e in TestsetManifest.load().captures
        for rep in [json.loads((Path(umgebung["cfg"]["paths"]["testset_dir"])
                                / e.report_rel).read_text())]
        if rep["decision"] == "accept"
        and rep["candidates"][0]["article_number"] != e.artikel)
    assert m["false_accept"] == golden_fa
    # NO_MATCH-Wahrheiten (Fremdobjekt + Randberuehrung) zaehlen als Treffer,
    # weil kein Auto-Accept passierte
    no_match = [r for r in umgebung["lauf_a"]["ergebnisse"]
                if r["artikel"] == NO_MATCH_ARTIKEL]
    assert len(no_match) == 2 and all(r["treffer"] for r in no_match)


def test_replay_identisch_bei_identischem_stand(umgebung):
    lauf_b = replay_testset(umgebung["cfg"], run_id="lauf-b")
    root = Path(umgebung["cfg"]["paths"]["testset_dir"])
    for datei in ("results.json", "metrics.json"):
        a = (root / "runs" / "lauf-a" / datei).read_bytes()
        b = (root / "runs" / "lauf-b" / datei).read_bytes()
        assert a == b, f"{datei} weicht zwischen identischen Laeufen ab"
    assert lauf_b["metrics"] == umgebung["lauf_a"]["metrics"]


def test_replay_meldet_veraendertes_capture_sha(umgebung, tmp_path,
                                                monkeypatch):
    cfg = _testset_kopie(umgebung, tmp_path, monkeypatch)
    root = Path(cfg["paths"]["testset_dir"])
    ziel = sorted((root / "captures" / "TELLER-160").glob("*.png"))[0]
    img = cv2.imread(str(ziel))
    cv2.circle(img, (400, 400), 40, (0, 0, 255), -1)
    cv2.imwrite(str(ziel), img)
    out = replay_testset(cfg, run_id="mut-sha")
    betroffen = [r for r in out["ergebnisse"] if r["artikel"] == "TELLER-160"]
    assert betroffen[0]["band"] == "fehler"
    assert any("veraendert" in g for g in betroffen[0]["gruende"])


def test_replay_merkt_veraendertes_capture_in_der_messung(umgebung, tmp_path,
                                                          monkeypatch):
    """Pipeline-Ebene, nicht nur SHA-Waechter: Manifest-SHA wird auf das
    manipulierte Bild nachgezogen — die Abweichung muss aus der MESSUNG
    kommen. Eine Harness, die das nicht merkt, ist wertlos."""
    cfg = _testset_kopie(umgebung, tmp_path, monkeypatch)
    root = Path(cfg["paths"]["testset_dir"])
    ziel = sorted((root / "captures" / "TELLER-160").glob("*.png"))[0]
    img = cv2.imread(str(ziel))
    # den Teller selbst vergroessern (430 px Radius ~ 172 mm statt 160):
    # die Messung MUSS kippen, nicht bloss ein Pixelrauschen entstehen
    cv2.circle(img, (960, 540), 430, (250, 250, 250), -1)
    cv2.circle(img, (960, 540), 430, (150, 150, 150), 3)
    cv2.imwrite(str(ziel), img)
    from docodetect.corpus.manifest import sha256_file
    m = TestsetManifest.load()
    for e in m.captures:
        if e.artikel == "TELLER-160":
            e.sha = sha256_file(ziel)
    m.save()
    out = replay_testset(cfg, run_id="mut-messung")
    betroffen = [r for r in out["ergebnisse"] if r["artikel"] == "TELLER-160"]
    assert betroffen[0]["band"] == "abweichung"
    assert any(g.startswith("measured.") or g.startswith("decision")
               or g.startswith("top1") or g.startswith("llr")
               for g in betroffen[0]["gruende"])


def test_replay_meldet_veraenderten_zustand_im_buendel(umgebung, tmp_path,
                                                       monkeypatch):
    cfg = _testset_kopie(umgebung, tmp_path, monkeypatch)
    root = Path(cfg["paths"]["testset_dir"])
    fp12 = umgebung["stat"]["snapshots_neu"][0]
    anderes_bg = make_background().copy()
    cv2.rectangle(anderes_bg, (0, 0), (200, 200), (0, 0, 0), -1)
    cv2.imwrite(str(snapshot_dir(root, fp12) / "background.png"), anderes_bg)
    out = replay_testset(cfg, run_id="mut-zustand")
    assert out["metrics"]["fehler"] == out["metrics"]["n"] == 5
    assert all("background.png" in " ".join(r["gruende"])
               for r in out["ergebnisse"])


def test_replay_unvollstaendiges_buendel_ist_fehler_kein_teillauf(
        umgebung, tmp_path, monkeypatch):
    cfg = _testset_kopie(umgebung, tmp_path, monkeypatch)
    root = Path(cfg["paths"]["testset_dir"])
    fp12 = umgebung["stat"]["snapshots_neu"][0]
    (snapshot_dir(root, fp12) / "db.sqlite3").unlink()
    out = replay_testset(cfg, run_id="mut-unvollstaendig")
    # JEDE Aufnahme des Buendels ist FEHLER — nichts laeuft still weiter
    assert out["metrics"]["fehler"] == out["metrics"]["n"] == 5
    assert all(r["band"] == "fehler" and
               any("unvollstaendig" in g for g in r["gruende"])
               for r in out["ergebnisse"])


def test_replay_plattform_waechter_meldet_nicht_vergleichbar(
        umgebung, tmp_path, monkeypatch):
    cfg = _testset_kopie(umgebung, tmp_path, monkeypatch)
    root = Path(cfg["paths"]["testset_dir"])
    fp12 = umgebung["stat"]["snapshots_neu"][0]
    z_pfad = snapshot_dir(root, fp12) / "zustand.json"
    z = json.loads(z_pfad.read_text(encoding="utf-8"))
    z["system"] = "Windows"            # kein Fingerprint-Bestandteil:
    z_pfad.write_text(json.dumps(z, indent=2, sort_keys=True),
                      encoding="utf-8")   # Integritaet bleibt intakt
    out = replay_testset(cfg, run_id="mut-plattform")
    assert out["metrics"]["vergleichbar"] is False
    assert any("NICHT vergleichbar" in m for m in out["plattform_meldungen"])
    # gerechnet wird trotzdem — Struktur-/Codepruefung bleibt moeglich
    assert out["metrics"]["fehler"] == 0


def test_replay_leeres_manifest_ist_kein_gruener_lauf(umgebung, tmp_path,
                                                      monkeypatch):
    monkeypatch.setattr(ts_manifest, "MANIFEST_PATH", tmp_path / "leer.json")
    with pytest.raises(RuntimeError, match="kein gruener Lauf"):
        replay_testset(umgebung["cfg"], run_id="leer")


def test_testset_cli_unter_sandbox_gesperrt():
    from docodetect.cli import main
    with pytest.raises(SystemExit) as e:
        main(["--sandbox", "probe", "testset-build"])
    assert "gesperrt" in str(e.value)
