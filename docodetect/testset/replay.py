"""testset-replay: alle Buendel durchrechnen, Ergebnis diffbar ablegen.

REIN BERICHTEND — kein Gate. Je Snapshot laeuft Pipeline.identify gegen
den eingefrorenen Zustand (snapshot_cfg: captures_dir=None, das Replay
schreibt nie Captures); verglichen wird gegen den gespeicherten
Original-Report der Aufnahme.

Plattform-Waechter (Spec: pruefen, nicht ausgleichen): weicht die
Plattform oder eine Messpfad-Bibliothek von der im Snapshot vermerkten
ab, wird das laut gemeldet und der Lauf als vergleichbar=false markiert
— Struktur- und Codepruefung bleiben moeglich, ein Zahlenvergleich gegen
andere Laeufe ist es nicht. Der dokumentierte H-S-Drift Mac<->Windows
ist der Grund; es gibt hier bewusst KEINE Toleranz dafuer.

Diffbarkeit: results.json und metrics.json tragen keine Zeitstempel und
sind stabil sortiert — zwei Laeufe auf gleichem Stand sind byteidentisch.
Laufspezifisches (Zeit, Dauer, Umgebung) steht getrennt in lauf.json.
"""

from __future__ import annotations

import json
import platform
import time
from pathlib import Path

import cv2
import numpy as np

from ..corpus.manifest import sha256_file
from ..matcher import MatchReport
from ..pipeline import Pipeline
from ..reporting import NO_MATCH, predicted_article
from .manifest import NO_MATCH_ARTIKEL, TestsetManifest, testset_root
from .snapshot import lade_zustand, pruefe_snapshot, snapshot_cfg

_LLR_TOL = 1e-3

# Umgebungs-Schluessel, deren Abweichung den Zahlenvergleich entwertet.
# python ist bewusst nur Meldung: ein Patch-Update aendert keine Messung,
# die Messpfad-Bibliotheken (cv2/numpy) und das OS dagegen nachweislich.
_VERGLEICHS_SCHLUESSEL = ("system", "opencv", "numpy")


def _umgebung_jetzt() -> dict:
    return {"system": platform.system(), "plattform": platform.platform(),
            "python": platform.python_version(), "opencv": cv2.__version__,
            "numpy": np.__version__}


def _vergleiche_report(golden: MatchReport, neu: MatchReport) -> list:
    """Abweichungsgruende Replay gegen Original. [] = identisch reproduziert."""
    gruende = []
    if neu.decision != golden.decision:
        gruende.append(f"decision {golden.decision}->{neu.decision}")
    g_top = golden.candidates[0].article_number if golden.candidates else None
    n_top = neu.candidates[0].article_number if neu.candidates else None
    if g_top != n_top:
        gruende.append(f"top1 {g_top}->{n_top}")
    if (golden.llr_margin is None) != (neu.llr_margin is None):
        gruende.append(f"llr {golden.llr_margin}->{neu.llr_margin}")
    elif golden.llr_margin is not None \
            and abs(neu.llr_margin - golden.llr_margin) >= _LLR_TOL:
        gruende.append(f"llr {golden.llr_margin}->{round(neu.llr_margin, 4)}")
    # Segmentierung ist deterministisch: auf identischen Pixeln muss der
    # measured-Block exakt stehen. Jede Abweichung wird je Feld benannt.
    for k in sorted(set(golden.measured or {}) | set(neu.measured or {})):
        a, b = (golden.measured or {}).get(k), (neu.measured or {}).get(k)
        if a != b:
            gruende.append(f"measured.{k}")
    return gruende


def replay_testset(cfg: dict, run_id: str | None = None) -> dict:
    root = testset_root(cfg)
    manifest = TestsetManifest.load()
    if not manifest.captures:
        raise RuntimeError(
            "Testset-Manifest ist leer — nichts zu replayen. Zuerst an der "
            "Box sammeln und 'testset-build' ausfuehren. 'Keine Aufnahmen' "
            "ist kein gruener Lauf.")
    if not root.exists():
        raise RuntimeError(
            f"Testset-Verzeichnis fehlt: {root}. paths.testset_dir pruefen "
            f"(config.local.yaml) oder Testset-Ordner uebernehmen.")

    run_id = run_id or time.strftime("%Y%m%d-%H%M%S")
    jetzt = _umgebung_jetzt()
    t0 = time.time()

    ergebnisse: list = []
    plattform_meldungen: list = []
    vergleichbar = True

    gruppen: dict = {}
    for e in manifest.captures:
        gruppen.setdefault(e.snapshot, []).append(e)

    for fp12 in sorted(gruppen):
        eintraege = sorted(gruppen[fp12], key=lambda e: e.sha)
        befunde = pruefe_snapshot(root, fp12)
        if befunde:
            # Unvollstaendiges/veraendertes Buendel: FEHLER fuer jede seiner
            # Aufnahmen — sichtbar im Ergebnis, nie ein stiller Teil-Lauf.
            for e in eintraege:
                ergebnisse.append({
                    "snapshot": fp12, "sha": e.sha, "artikel": e.artikel,
                    "band": "fehler",
                    "gruende": [f"Buendel: {b}" for b in befunde],
                    "decision": None, "top1": None, "llr_margin": None,
                    "treffer": None, "false_accept": None})
            continue

        z = lade_zustand(root, fp12)
        abweichend = [k for k in _VERGLEICHS_SCHLUESSEL
                      if z.get(k) != jetzt.get(k)]
        if abweichend:
            vergleichbar = False
            plattform_meldungen.append(
                f"Snapshot {fp12}: entstanden unter "
                + ", ".join(f"{k}={z.get(k)}" for k in abweichend)
                + " — jetzt "
                + ", ".join(f"{k}={jetzt.get(k)}" for k in abweichend)
                + ". Zahlen NICHT vergleichbar (H-S-Drift Mac<->Windows, "
                  "keine Toleranz).")

        pipe = Pipeline(snapshot_cfg(cfg, root, fp12))
        try:
            for e in eintraege:
                zeile = {"snapshot": fp12, "sha": e.sha, "artikel": e.artikel,
                         "band": "pass", "gruende": [], "decision": None,
                         "top1": None, "llr_margin": None,
                         "treffer": None, "false_accept": None}
                ergebnisse.append(zeile)
                bild_pfad = root / e.image_rel
                report_pfad = root / e.report_rel
                if not bild_pfad.is_file() or not report_pfad.is_file():
                    zeile["band"] = "fehler"
                    zeile["gruende"] = ["Capture oder Report fehlt im Testset"]
                    continue
                if sha256_file(bild_pfad) != e.sha:
                    zeile["band"] = "fehler"
                    zeile["gruende"] = ["Capture veraendert (SHA weicht vom "
                                        "Manifest ab)"]
                    continue
                golden = MatchReport.from_json(
                    report_pfad.read_text(encoding="utf-8"))
                img = cv2.imread(str(bild_pfad))
                if img is None:
                    zeile["band"] = "fehler"
                    zeile["gruende"] = ["Capture nicht lesbar"]
                    continue
                outcome = pipe.identify(img, source_path=str(bild_pfad),
                                        label=golden.label)
                rep = outcome.report
                gruende = _vergleiche_report(golden, rep)
                top1 = predicted_article(rep)
                zeile["decision"] = rep.decision
                zeile["top1"] = top1
                zeile["llr_margin"] = rep.llr_margin
                # Trefferquote top1-roh wie die Korpus-Quoten; fuer die
                # Wahrheit "nicht in der DB" zaehlt: kein Auto-Accept.
                if e.artikel == NO_MATCH_ARTIKEL:
                    zeile["treffer"] = (rep.decision != "accept"
                                        or top1 == NO_MATCH)
                else:
                    zeile["treffer"] = top1 == e.artikel
                zeile["false_accept"] = (rep.decision == "accept"
                                         and top1 != e.artikel)
                if gruende:
                    zeile["band"] = "abweichung"
                    zeile["gruende"] = gruende
        finally:
            pipe.close()

    dauer = time.time() - t0
    ergebnisse.sort(key=lambda r: (r["snapshot"], r["sha"]))

    gewertet = [r for r in ergebnisse if r["band"] != "fehler"]
    decisions: dict = {}
    for r in gewertet:
        decisions[r["decision"]] = decisions.get(r["decision"], 0) + 1
    metrics = {
        "n": len(ergebnisse),
        "gewertet": len(gewertet),
        "treffer": sum(1 for r in gewertet if r["treffer"]),
        "trefferquote": (round(sum(1 for r in gewertet if r["treffer"])
                               / len(gewertet), 4) if gewertet else None),
        "decisions": dict(sorted(decisions.items(), key=lambda x: str(x[0]))),
        "false_accept": sum(1 for r in gewertet if r["false_accept"]),
        "abweichungen": sum(1 for r in ergebnisse
                            if r["band"] == "abweichung"),
        "fehler": sum(1 for r in ergebnisse if r["band"] == "fehler"),
        "vergleichbar": vergleichbar,
    }

    lauf_dir = root / "runs" / run_id
    lauf_dir.mkdir(parents=True, exist_ok=True)
    (lauf_dir / "results.json").write_text(
        json.dumps(ergebnisse, indent=2, ensure_ascii=False,
                   sort_keys=True) + "\n", encoding="utf-8")
    (lauf_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False,
                   sort_keys=True) + "\n", encoding="utf-8")
    (lauf_dir / "lauf.json").write_text(
        json.dumps({"run_id": run_id, "dauer_s": round(dauer, 1),
                    "umgebung": jetzt, "vergleichbar": vergleichbar,
                    "plattform_meldungen": plattform_meldungen},
                   indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")

    return {"run_id": run_id, "lauf_dir": str(lauf_dir), "metrics": metrics,
            "plattform_meldungen": plattform_meldungen,
            "ergebnisse": ergebnisse}
