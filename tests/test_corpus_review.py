"""Tests der Auswertungsschicht `corpus/review.py`.

Alles hier laeuft auf SYNTHETISCHEN Runner-Ergebnissen in tmp_path: ein
Korpusbaum aus Goldens, Replay-Reports, failures/ und metrics.json, wie ihn
`corpus/report.write_run` schreibt. Nie der echte Korpus, nie die Pipeline —
die Review-Schicht rechnet ohnehin nichts nach, und genau das pruefen die
Konsistenz-Tests: was im CSV steht, muss aus metrics.json stammen.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from docodetect.corpus import review
from docodetect.corpus.manifest import ImageEntry, Manifest
from docodetect.corpus.report import tier2_quotas
from docodetect.matcher import CandidateReport, FeatureScore, MatchReport


# --------------------------------------------------------------------------
# Synthetischer Korpus
# --------------------------------------------------------------------------

def _cand(nr, *, z=1.0, margin=None):
    return CandidateReport(
        article_number=nr, name=nr, nominal_size_mm=200.0, height_mm=0.0,
        corrected_diameter_mm=200.0, geometry_error_mm=0.0,
        has_references=True, n_shots=2,
        features=[FeatureScore(feature="hu_log", measured=1.0, reference=1.0,
                               distance=0.0, sigma_enroll=1.0, sigma_eff=1.0,
                               z=z, log_contrib=0.0, w_eff=1.0, weighted=0.0),
                  FeatureScore(feature="circularity", measured=1.0,
                               reference=1.0, distance=0.0, sigma_enroll=1.0,
                               sigma_eff=1.0, z=z / 2.0, log_contrib=0.0,
                               w_eff=1.0, weighted=0.0)],
        margin_to_next=margin)


def _report(*, decision="accept", label=None, verdict=None, top1="A-1",
            margin=3.0, max_z=1.5, zweiter="A-2"):
    cands = [_cand(top1, z=max_z)]
    if zweiter:
        cands.append(_cand(zweiter, z=max_z + 1.0))
    return MatchReport(decision=decision, message="", candidates=cands,
                       label=label, verdict=verdict, llr_margin=margin,
                       max_z_winner=max_z, measured={})


def _schreibe(p: Path, rep: MatchReport) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(rep.to_json(), encoding="utf-8")


def _korpus(tmp_path: Path, goldens: dict) -> tuple[Path, Manifest]:
    """Goldens unter phase-a/reports/<sha8>.json + passendes Manifest."""
    root = tmp_path / "corpus"
    eintraege = []
    for sha8, rep in goldens.items():
        sha = sha8 + "0" * (64 - len(sha8))
        rel = f"phase-a/reports/{sha8}.json"
        _schreibe(root / rel, rep)
        eintraege.append(ImageEntry(
            sha=sha, session="s1", article=rep.label or "_unbewertet",
            image_rel=f"phase-a/images/{sha8}.png", report_rel=rel,
            label=rep.label, verdict=rep.verdict, tier=2))
    return root, Manifest(images=eintraege)


def _lauf(root: Path, run_id: str, replay: dict, *, tier=2,
          failures: dict | None = None, metrics: dict | None = None) -> Path:
    """Einen Lauf schreiben, wie `report.write_run` es tut.

    metrics.json entsteht aus denselben `tier2_quotas` ueber dieselben
    Reports, die der Runner benutzt — damit ist der Konsistenz-Test ein
    echter Test und keine Tautologie ueber handgeschriebene Zahlen.
    """
    d = root / "runs" / run_id
    for sha8, rep in replay.items():
        _schreibe(d / "replay" / f"{sha8}.json", rep)
    for sha8, payload in (failures or {}).items():
        p = d / "failures" / f"{sha8}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload), encoding="utf-8")
    if metrics is None:
        metrics = {"run_id": run_id, "tier": tier, "n": len(replay),
                   "baender": {"pass": len(replay)},
                   "quotas": tier2_quotas(list(replay.values()))}
    (d / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    return d


def _csv(p: Path) -> list[dict]:
    with open(p, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture
def korpus(tmp_path):
    """Vier Bilder: eins unveraendert, eins mit Score-Drift, eins mit
    Rang-1-Wechsel, eins mit Entscheidungswechsel."""
    goldens = {
        "aaaaaaaa": _report(label="A-1", top1="A-1", margin=4.0, max_z=1.0,
                            verdict="correct"),
        "bbbbbbbb": _report(label="B-1", top1="B-1", margin=3.0, max_z=1.2,
                            verdict="correct"),
        "cccccccc": _report(label="C-1", top1="C-1", margin=2.5, max_z=1.4,
                            verdict="correct"),
        "dddddddd": _report(label="D-1", top1="D-1", margin=2.2, max_z=3.0,
                            decision="accept", verdict="correct"),
    }
    root, manifest = _korpus(tmp_path, goldens)
    replay = {
        "aaaaaaaa": _report(label="A-1", top1="A-1", margin=4.0, max_z=1.0,
                            verdict="correct"),
        "bbbbbbbb": _report(label="B-1", top1="B-1", margin=3.4, max_z=1.1,
                            verdict="correct"),
        "cccccccc": _report(label="C-1", top1="C-9", margin=2.1, max_z=1.9,
                            verdict="wrong"),
        "dddddddd": _report(label="D-1", top1="D-1", margin=1.4, max_z=3.9,
                            decision="ambiguous", verdict="correct"),
    }
    _lauf(root, "20260722-lauf", replay,
          failures={"cccccccc": {"band": "fail", "diffs": [
                        {"field": "hu_log", "band": "fail", "delta": 0.4}]},
                    "dddddddd": {"band": "drift", "diffs": [
                        {"field": "circularity", "band": "drift",
                         "delta": 0.02}]}})
    return root, manifest


@pytest.fixture
def cfg(korpus):
    root, _ = korpus
    return {"paths": {"corpus_dir": str(root)},
            "matching": {"min_llr_margin": 2.0, "max_z_accept": 3.5}}


# --------------------------------------------------------------------------
# Neue v1-Regel: ein Lauf ohne metrics.json ist unvollstaendig
# --------------------------------------------------------------------------

def test_lauf_ohne_metrics_wird_als_seite_abgelehnt(korpus):
    """Der Runner schreibt metrics.json zuletzt. Fehlt sie, wurde der Lauf
    abgebrochen und traegt einen Torso-Replay — als Vergleichsseite waere er
    stillschweigend irrefuehrend (fehlende Bilder saehen aus wie
    'nicht betroffen'). Anlass: 20260722-170558/-173247 am 2026-07-22."""
    root, _ = korpus
    d = root / "runs" / "abgebrochen"
    _schreibe(d / "replay" / "aaaaaaaa.json", _report(label="A-1"))

    with pytest.raises(review.UnvollstaendigerLauf) as exc:
        review.load_run_side(root, "abgebrochen")

    meldung = str(exc.value)
    assert "abgebrochen" in meldung
    assert "metrics.json" in meldung
    # Die Meldung muss handlungsfaehig machen: was fehlt, wie viel Torso da
    # ist und welche Laeufe stattdessen gehen.
    assert "1 Replay-Report" in meldung
    assert "20260722-lauf" in meldung


def test_unvollstaendiger_lauf_ist_ein_filenotfounderror(korpus):
    """`corpus-run --report` faengt (RuntimeError, FileNotFoundError) ab,
    damit die Review den Exit-Code von --check nie beeinflusst. Die neue
    Ausnahme muss unter diesen Schirm fallen."""
    root, _ = korpus
    (root / "runs" / "torso").mkdir(parents=True)
    with pytest.raises(FileNotFoundError):
        review.load_run_side(root, "torso")


def test_letzte_ueberspringt_unvollstaendige_laeufe(korpus):
    """`--run letzte` darf nie auf einem Torso landen, auch wenn er der
    juengste Ordner ist."""
    root, _ = korpus
    d = root / "runs" / "zzzz-neuer-torso"
    _schreibe(d / "replay" / "aaaaaaaa.json", _report(label="A-1"))

    assert "zzzz-neuer-torso" not in review.list_runs(root)
    assert review.latest_run_id(root) == "20260722-lauf"
    assert review.latest_run_id(root, tier=2) == "20260722-lauf"


def test_quarantaene_ordner_wird_uebergangen(korpus):
    """runs/_invalid/ ist die Ablage fuer aussortierte Laeufe — ein Lauf
    darin darf nie wieder als Seite auftauchen."""
    root, _ = korpus
    d = root / "runs" / "_invalid" / "20260722-173247"
    _schreibe(d / "replay" / "aaaaaaaa.json", _report(label="A-1"))
    (d / "metrics.json").write_text(json.dumps({"tier": 2, "quotas": {}}),
                                    encoding="utf-8")

    assert review.list_runs(root) == ["20260722-lauf"]


def test_unbekannte_lauf_id_nennt_den_pfad(korpus):
    root, _ = korpus
    with pytest.raises(FileNotFoundError, match="gibt.s nicht|existiert nicht"):
        review.load_run_side(root, "gibt-es-nicht")


# --------------------------------------------------------------------------
# Artefakte entstehen
# --------------------------------------------------------------------------

ERWARTETE_ARTEFAKTE = [
    "index.html",
    "drift_review.csv", "drift_scatter.png",
    "decision_matrix.png", "decision_matrix.csv", "top1_wechsel.csv",
    "baseline_verlauf.csv",
    "verteilungen.csv", "verteilungen.png",
    "quoten.csv", "quoten.png",
    "confusion_matrix.csv", "confusion_matrix.png",
]


def test_run_review_erzeugt_alle_artefakte(korpus, cfg, tmp_path):
    _, manifest = korpus
    out = review.run_review(cfg, run="20260722-lauf", manifest=manifest,
                            accepted={}, out_dir=tmp_path / "out")
    fehlend = [n for n in ERWARTETE_ARTEFAKTE if not (out / n).exists()]
    assert not fehlend, f"fehlende Artefakte: {fehlend}"
    assert (out / "index.html").read_text(encoding="utf-8").startswith("<!doctype")


def test_compare_modus_erzeugt_eigenen_ordner(korpus, cfg, tmp_path):
    """Lauf gegen Lauf — die formalisierte hu_log-Rekonstruktion."""
    root, manifest = korpus
    _lauf(root, "20260722-zweiter",
          {"aaaaaaaa": _report(label="A-1", top1="A-1", margin=4.2, max_z=1.0),
           "bbbbbbbb": _report(label="B-1", top1="B-1", margin=3.9, max_z=1.0)})

    out = review.run_review(cfg, compare=("20260722-lauf", "20260722-zweiter"),
                            manifest=manifest, accepted={},
                            out_dir=tmp_path / "cmp")
    zeilen = _csv(out / "drift_review.csv")
    # Nur die Bilder, die BEIDE Seiten fuehren.
    assert {z["sha8"] for z in zeilen} == {"aaaaaaaa", "bbbbbbbb"}


def test_review_id_unterscheidet_die_beiden_modi():
    assert review.review_id_for(review.GOLDEN, "lauf-x") == "lauf-x"
    assert review.review_id_for("a", "b") == "compare-a-vs-b"


def test_compare_verlangt_zwei_konkrete_ids(cfg):
    with pytest.raises(ValueError, match="zwei konkrete"):
        review.run_review(cfg, compare=("letzte", "x"))


def test_seiten_ohne_gemeinsames_bild_brechen_ab(korpus, cfg, tmp_path):
    root, manifest = korpus
    _lauf(root, "fremd", {"99999999": _report(label="Z-1")})
    with pytest.raises(RuntimeError, match="kein Bild gemeinsam"):
        review.run_review(cfg, run="fremd", manifest=manifest, accepted={},
                          out_dir=tmp_path / "leer")


# --------------------------------------------------------------------------
# Konsistenz: CSV == Runner-Output (Schutz gegen Erzaehl-Drift)
# --------------------------------------------------------------------------

def test_quoten_csv_uebernimmt_die_zahlen_aus_metrics_json(korpus, cfg, tmp_path):
    """Der maschinelle Konsistenz-Check: jede Kennzahl der Laufseite im CSV
    muss ZIFFERNGLEICH in runs/<id>/metrics.json stehen. Weicht sie ab, hat
    die Auswertungsschicht selbst gerechnet — genau das darf sie nicht."""
    root, manifest = korpus
    metrics = json.loads((root / "runs" / "20260722-lauf" / "metrics.json"
                          ).read_text(encoding="utf-8"))

    out = review.run_review(cfg, run="20260722-lauf", manifest=manifest,
                            accepted={}, out_dir=tmp_path / "out")

    aus_csv = {z["kennzahl"]: z for z in _csv(out / "quoten.csv")
               if z["seite"] == "20260722-lauf"}
    geprueft = 0
    for name, q in metrics["quotas"].items():
        if not isinstance(q, dict) or "p" not in q:
            continue
        assert name in aus_csv, f"{name} fehlt im CSV"
        z = aus_csv[name]
        assert int(z["k"]) == q["k"]
        assert int(z["n"]) == q["n"]
        assert float(z["p"]) == pytest.approx(q["p"])
        assert float(z["wilson_lo"]) == pytest.approx(q["wilson_lo"])
        assert float(z["wilson_hi"]) == pytest.approx(q["wilson_hi"])
        assert "metrics.json" in z["quelle"]
        geprueft += 1
    assert geprueft >= 4, "zu wenige Kennzahlen geprueft"


def test_abweichende_metrics_werden_als_befund_gemeldet_nicht_ueberschrieben(
        korpus, cfg, tmp_path):
    """Steht in metrics.json etwas anderes, als tier2_quotas ueber den
    Replay ergibt, gewinnt metrics.json (das ist die Zahl, die --check
    bewertet hat) — und die Abweichung wird als Befund sichtbar, statt
    still unterzugehen."""
    root, manifest = korpus
    mp = root / "runs" / "20260722-lauf" / "metrics.json"
    metrics = json.loads(mp.read_text(encoding="utf-8"))
    metrics["quotas"]["accuracy_top1"] = {
        "k": 99, "n": 99, "p": 1.0, "wilson_lo": 1.0, "wilson_hi": 1.0}
    mp.write_text(json.dumps(metrics), encoding="utf-8")

    out = review.run_review(cfg, run="20260722-lauf", manifest=manifest,
                            accepted={}, out_dir=tmp_path / "out")

    zeile = next(z for z in _csv(out / "quoten.csv")
                 if z["seite"] == "20260722-lauf"
                 and z["kennzahl"] == "accuracy_top1")
    assert (int(zeile["k"]), int(zeile["n"])) == (99, 99)
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "Konsistenz-Befund" in html
    assert "99/99" in html


def test_baender_kommen_aus_failures_nicht_aus_nachrechnung(korpus, cfg,
                                                            tmp_path):
    """PASS/DRIFT/FAIL stammen ausschliesslich aus failures/ bzw. dessen
    Abwesenheit — die Review faellt nie ein eigenes Band-Urteil."""
    _, manifest = korpus
    out = review.run_review(cfg, run="20260722-lauf", manifest=manifest,
                            accepted={}, out_dir=tmp_path / "out")
    baender = {z["sha8"]: z["band"] for z in _csv(out / "drift_review.csv")}
    assert baender == {"aaaaaaaa": "pass", "bbbbbbbb": "pass",
                       "cccccccc": "fail", "dddddddd": "drift"}


def test_decision_matrix_csv_summiert_auf_die_zeilenzahl(korpus, cfg, tmp_path):
    _, manifest = korpus
    out = review.run_review(cfg, run="20260722-lauf", manifest=manifest,
                            accepted={}, out_dir=tmp_path / "out")
    n_zeilen = len(_csv(out / "drift_review.csv"))
    summe = 0
    for z in _csv(out / "decision_matrix.csv"):
        summe += sum(int(v) for k, v in z.items() if k != "alt\\neu")
    assert summe == n_zeilen


# --------------------------------------------------------------------------
# Ablesungen (beschreibend, keine Urteile)
# --------------------------------------------------------------------------

def test_change_kind_stuft_nach_tragweite():
    basis = _report(top1="A-1", margin=3.0, max_z=1.0)
    assert review.change_kind(basis, basis) == "identisch"
    assert review.change_kind(
        basis, _report(top1="A-1", margin=3.5, max_z=1.0)) == "score"
    assert review.change_kind(
        basis, _report(top1="A-9", margin=3.0, max_z=1.0)) == "top1"
    assert review.change_kind(
        basis, _report(top1="A-1", margin=3.0, max_z=1.0,
                       decision="reject")) == "entscheidung"


def test_change_kind_erkennt_das_kandidatenset():
    a = _report(top1="A-1", zweiter="A-2")
    b = _report(top1="A-1", zweiter="A-3")
    assert review.change_kind(a, b) == "kandidatenset"


def test_driving_feature_liest_das_groesste_z_des_siegers():
    rep = _report(top1="A-1", max_z=2.5)
    feld, z = review.driving_feature(rep)
    assert feld == "hu_log"          # z=2.5 gegen circularity z=1.25
    assert z == pytest.approx(2.5)


def test_driving_feature_vertraegt_einen_report_ohne_kandidaten():
    leer = MatchReport(decision="reject", message="", candidates=[])
    assert review.driving_feature(leer) == ("", None)


def test_top1_wechsel_bilanziert_die_richtung(korpus, cfg, tmp_path):
    _, manifest = korpus
    out = review.run_review(cfg, run="20260722-lauf", manifest=manifest,
                            accepted={}, out_dir=tmp_path / "out")
    wechsel = {z["richtung"]: int(z["anzahl"])
               for z in _csv(out / "top1_wechsel.csv")}
    # Nur cccccccc wechselt Rang 1, und zwar von richtig auf falsch.
    assert wechsel["richtig->falsch"] == 1
    assert sum(wechsel.values()) == 1


def test_delta_status_kommt_aus_accepted_deltas(korpus, cfg, tmp_path):
    _, manifest = korpus
    accepted = {"cccccccc": {"kategorie": "hu_log-floor",
                             "_source": "corpus/accepted_deltas/x.json",
                             "_fix_commit": "abcdef1234567890"}}
    out = review.run_review(cfg, run="20260722-lauf", manifest=manifest,
                            accepted=accepted, out_dir=tmp_path / "out")
    zeilen = {z["sha8"]: z for z in _csv(out / "drift_review.csv")}
    assert zeilen["cccccccc"]["delta_status"] == "akzeptiert"
    assert zeilen["cccccccc"]["delta_kategorie"] == "hu_log-floor"
    assert zeilen["cccccccc"]["delta_fix_commit"] == "abcdef12"
    assert zeilen["aaaaaaaa"]["delta_status"] == "-"


# --------------------------------------------------------------------------
# Tier-1-Drift je Merkmal
# --------------------------------------------------------------------------

def test_tier1_drift_aggregiert_die_failure_diffs(korpus):
    root, _ = korpus
    side = review.load_run_side(root, "20260722-lauf")
    zeilen = {z["feld"]: z for z in review.tier1_drift_je_merkmal(side)}
    assert zeilen["hu_log"]["fail"] == 1
    assert zeilen["hu_log"]["bilder"] == 1
    assert zeilen["circularity"]["drift"] == 1
    assert zeilen["hu_log"]["delta_max"] == pytest.approx(0.4)
    # FAIL sortiert vor DRIFT.
    assert review.tier1_drift_je_merkmal(side)[0]["feld"] == "hu_log"


def test_tier1_drift_ist_leer_ohne_failures(korpus):
    root, _ = korpus
    _lauf(root, "sauber", {"aaaaaaaa": _report(label="A-1")}, tier=1)
    side = review.load_run_side(root, "sauber")
    assert review.tier1_drift_je_merkmal(side) == []


# --------------------------------------------------------------------------
# Baseline-Verlauf
# --------------------------------------------------------------------------

def test_baseline_history_liest_die_git_historie(tmp_path):
    """Je Commit wird die damalige baseline.json mit `git show` geholt und
    genau so gelesen wie heute — kein neues Schema."""
    import subprocess

    repo = tmp_path / "repo"
    (repo / "corpus").mkdir(parents=True)
    def git(*args):
        subprocess.run(["git", "-C", str(repo), *args], check=True,
                       capture_output=True)
    git("init", "-q")
    git("config", "user.email", "t@t")
    git("config", "user.name", "T")

    p = repo / "corpus" / "baseline.json"
    for i, (k, betreff) in enumerate(((40, "erste Baseline"),
                                      (46, "nach sigma_floors"))):
        p.write_text(json.dumps({
            "run_id": f"lauf-{i}", "n": 60,
            "quotas": {"accuracy_top1": {"k": k, "n": 60, "p": k / 60},
                       "false_accept_rate": {"k": 0, "n": 27, "p": 0.0}}}),
            encoding="utf-8")
        git("add", "corpus/baseline.json")
        git("commit", "-q", "-m", betreff)

    punkte = review.baseline_history(pfad=p, repo=repo)
    assert [x["betreff"] for x in punkte] == ["erste Baseline",
                                              "nach sigma_floors"]
    assert punkte[0]["accuracy_top1_k"] == 40
    assert punkte[1]["accuracy_top1_k"] == 46
    assert punkte[1]["false_accept_rate_n"] == 27
    assert all(len(x["commit"]) == 8 for x in punkte)


def test_baseline_history_ohne_git_ist_leer_statt_fehler(tmp_path):
    """Die Ansicht ist eine Zugabe: ohne Repo bleibt sie leer, sie darf den
    Rest der Review nie mitreissen."""
    assert review.baseline_history(pfad=tmp_path / "x.json",
                                   repo=tmp_path) == []


# --------------------------------------------------------------------------
# publish
# --------------------------------------------------------------------------

def test_publish_kopiert_und_ueberschreibt_nie(korpus, cfg, tmp_path):
    _, manifest = korpus
    out = review.run_review(cfg, run="20260722-lauf", manifest=manifest,
                            accepted={}, out_dir=tmp_path / "out")
    cfg2 = dict(cfg, analysis={"publish_dir": str(tmp_path / "archiv")})

    ziel = review.publish_review(cfg2, out)
    assert ziel.name == "corpus-out"
    assert (ziel / "index.html").exists()

    with pytest.raises(FileExistsError):
        review.publish_review(cfg2, out)


# --------------------------------------------------------------------------
# Neue Fehlbuchungen (Befund der Abnahme 2026-07-22)
# --------------------------------------------------------------------------

def test_neue_fehlbuchung_ohne_rang1_wechsel(korpus, cfg, tmp_path):
    """Der Fall 46f9b1b3 bei hu_log-Floor 0.069: Rang 1 war schon im Golden
    falsch, nur die Entscheidung kippte auf accept. `top1_wechsel` sieht das
    NICHT (Rang 1 bewegt sich ja nicht) — es ist trotzdem eine neue
    Fehlbuchung, und zwar die teuerste Klasse von Abweichung."""
    root, manifest = korpus
    _lauf(root, "kippt-auf-accept", {
        # Golden fuer cccccccc: label C-1, top1 C-1 (richtig), ambiguous waere
        # harmlos — hier bleibt Rang 1 falsch UND wird gebucht.
        "cccccccc": _report(label="C-1", top1="C-9", decision="accept",
                            margin=3.0, max_z=1.0)})

    out = review.run_review(cfg, run="kippt-auf-accept", manifest=manifest,
                            accepted={}, out_dir=tmp_path / "out")

    fehl = _csv(out / "neue_fehlbuchungen.csv")
    assert [z["sha8"] for z in fehl] == ["cccccccc"]
    assert fehl[0]["top1_neu"] == "C-9" and fehl[0]["label"] == "C-1"

    html = (out / "index.html").read_text(encoding="utf-8")
    assert "Neue Fehlbuchungen: 1" in html


def test_bereits_vorher_falsch_gebucht_ist_keine_neue_fehlbuchung():
    """Buchte schon die alte Seite denselben Fehler, ist er nicht neu —
    sonst meldete jede Review dieselbe Altlast erneut."""
    zeilen = [{"sha8": "x", "label": "A-1", "decision_alt": "accept",
               "decision_neu": "accept", "top1_korrekt_alt": "nein",
               "top1_korrekt_neu": "nein"}]
    assert review.neue_fehlbuchungen(zeilen) == []


def test_richtig_gebucht_ist_keine_fehlbuchung():
    zeilen = [{"sha8": "x", "label": "A-1", "decision_alt": "ambiguous",
               "decision_neu": "accept", "top1_korrekt_alt": "ja",
               "top1_korrekt_neu": "ja"}]
    assert review.neue_fehlbuchungen(zeilen) == []


def test_ohne_label_keine_fehlbuchung():
    """Ohne wahres Label ist 'falsch' nicht entscheidbar."""
    zeilen = [{"sha8": "x", "label": "", "decision_alt": "ambiguous",
               "decision_neu": "accept", "top1_korrekt_alt": "nein",
               "top1_korrekt_neu": "nein"}]
    assert review.neue_fehlbuchungen(zeilen) == []


def test_standardlauf_meldet_seine_eine_fehlbuchung(korpus, cfg, tmp_path):
    """Im Fixture bucht `cccccccc` per accept den falschen Artikel (C-9 statt
    C-1) — das MUSS als Fehlbuchung erscheinen, obwohl es zugleich ein
    Rang-1-Wechsel ist."""
    _, manifest = korpus
    out = review.run_review(cfg, run="20260722-lauf", manifest=manifest,
                            accepted={}, out_dir=tmp_path / "out")
    assert [z["sha8"] for z in _csv(out / "neue_fehlbuchungen.csv")] == \
        ["cccccccc"]


def test_lauf_ohne_fehlbuchung_meldet_null(korpus, cfg, tmp_path):
    root, manifest = korpus
    _lauf(root, "sauberer-lauf",
          {"aaaaaaaa": _report(label="A-1", top1="A-1", decision="accept"),
           "bbbbbbbb": _report(label="B-1", top1="B-1", decision="ambiguous")})
    out = review.run_review(cfg, run="sauberer-lauf", manifest=manifest,
                            accepted={}, out_dir=tmp_path / "out")
    assert _csv(out / "neue_fehlbuchungen.csv") == []
    assert "Neue Fehlbuchungen: 0" in (out / "index.html").read_text(
        encoding="utf-8")
