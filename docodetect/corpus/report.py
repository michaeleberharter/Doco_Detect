"""Lauf-Berichte, Baseline und Exit-Code-Logik."""

from __future__ import annotations

import json
import math
import statistics
from datetime import datetime
from pathlib import Path

from ..config import project_root
from ..reporting import NO_MATCH, judgement, summarize
from .compare import DRIFT, FAIL

BASELINE_PATH = project_root() / "corpus" / "baseline.json"

# Ab so vielen betroffenen Bildern UND so kleiner relativer Streuung gilt
# eine Drift als uniform (Bibliothek/Plattform) statt als Ausreisser (Code).
UNIFORM_MIN_ANTEIL = 0.5
UNIFORM_MAX_STREUUNG = 0.25


def wilson(k: int, n: int, z: float = 1.96) -> tuple:
    """Punktschaetzer plus Wilson-Score-Intervall. Wilson statt Normal-
    approximation, weil die Quoten hier oft nahe 0 oder 1 liegen (FAR!)."""
    if n <= 0:
        return 0.0, 0.0, 0.0
    p = k / n
    d = 1.0 + z * z / n
    mitte = (p + z * z / (2 * n)) / d
    rand = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return round(p, 4), round(max(0.0, mitte - rand), 4), round(min(1.0, mitte + rand), 4)


def tier2_quotas(reports: list) -> dict:
    """Kennzahlen ueber Replay-Reports. Nutzt dieselbe Aggregation wie
    `analyze`, damit die Zahlen zwischen den Werkzeugen identisch bleiben.

    accuracy_top1 rechnet ueber `judgement()`, nicht ueber `top_k_accuracy`:
    judgement() gibt dem menschlichen Urteil (report.verdict, schliesst das
    z-Gate ein) Vorrang vor dem reinen Label-Vergleich. Ein Report wie
    1784562586318.png (Rang-1-Kandidat == Label, aber vom Gate verworfen und
    darum verdict="wrong") ist in top_k_accuracy ein Treffer, im
    `analyze`-Befehl aber nicht — ohne diesen Wechsel weichen die
    Korpus-Zahlen vom bestehenden Werkzeug ab.
    """
    s = summarize(reports)
    judged = [(r, judgement(r)) for r in reports if judgement(r) is not None]
    labeled = [r for r in reports if r.label]
    h1, n1 = sum(1 for _, ok in judged if ok), len(judged)
    h3 = sum(1 for r in labeled
             if (r.label in [c.article_number for c in r.candidates[:3]]
                 or (not r.candidates and r.label == NO_MATCH)))
    n3 = len(labeled)
    akzeptiert = [r for r in reports if r.decision == "accept"]
    falsch_akzeptiert = sum(
        1 for r in akzeptiert
        if r.label and r.candidates and r.candidates[0].article_number != r.label)

    def q(k, n):
        p, lo, hi = wilson(k, n)
        return {"k": k, "n": n, "p": p, "wilson_lo": lo, "wilson_hi": hi}

    return {
        "accuracy_top1": q(h1, n1),
        "accuracy_top3": q(h3, n3),
        "auto_accept_rate": q(len(akzeptiert), len(reports)),
        "false_accept_rate": q(falsch_akzeptiert, len(akzeptiert)),
        "decisions": s.decision_counts,
    }


def classify_drift(results: list) -> dict:
    """Uniforme Drift (Bibliothek/Plattform) von Ausreissern (Code) trennen.

    Uniform = viele Bilder, alle ungefaehr gleich stark verschoben.
    Ausreisser = wenige Bilder, beliebige Groesse. Genau diese Trennung
    entscheidet, ob ein --accept-drift-Lauf gerechtfertigt ist.
    """
    betroffen = [r for r in results if r["band"] == DRIFT]
    if not betroffen:
        return {"muster": "keine", "betroffen": 0, "anteil": 0.0}
    deltas = []
    for r in betroffen:
        werte = [abs(d["delta"]) for d in r["diffs"]
                 if d["band"] == DRIFT and isinstance(d["delta"], (int, float))
                 and not math.isnan(d["delta"])]
        if werte:
            deltas.append(max(werte))
    anteil = len(betroffen) / max(1, len(results))
    streuung = 0.0
    if len(deltas) > 1 and statistics.mean(deltas) > 0:
        streuung = statistics.pstdev(deltas) / statistics.mean(deltas)
    uniform = anteil >= UNIFORM_MIN_ANTEIL and streuung <= UNIFORM_MAX_STREUUNG
    return {"muster": "uniform" if uniform else "ausreisser",
            "betroffen": len(betroffen), "anteil": round(anteil, 3),
            "delta_median": round(statistics.median(deltas), 6) if deltas else 0.0,
            "streuung": round(streuung, 3)}


def load_baseline() -> dict:
    if not BASELINE_PATH.exists():
        return {}
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def save_baseline(payload: dict) -> Path:
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return BASELINE_PATH


def check_against_baseline(run: dict, quotas: dict, baseline: dict, *,
                           accept_drift: bool) -> tuple:
    """Exit-Code plus Klartext-Meldungen.

    0 = in Ordnung, 1 = Regression. Per Default brechen DRIFT und FAIL
    beide: auf derselben Maschine mit denselben Bibliotheken ist jede
    Abweichung code-verursacht, und nur so bleibt --check bisect-tauglich.
    """
    meldungen, code = [], 0
    fails = [r for r in run["results"] if r["band"] == FAIL]
    drifts = [r for r in run["results"] if r["band"] == DRIFT]

    if fails:
        code = 1
        meldungen.append(f"FAIL: {len(fails)} Bild(er) ausserhalb der weichen Stufe")
    if drifts:
        if accept_drift:
            meldungen.append(f"DRIFT: {len(drifts)} Bild(er) – toleriert "
                             "(--accept-drift). Re-Baselining mit Begruendung faellig.")
        else:
            code = 1
            meldungen.append(f"DRIFT: {len(drifts)} Bild(er) ausserhalb des "
                             "Rundungsquantums – auf gepinnter Umgebung ist das "
                             "code-verursacht (--accept-drift zum Tolerieren)")

    for name, jetzt in (quotas or {}).items():
        alt = (baseline.get("quotas") or {}).get(name)
        if not alt or not isinstance(jetzt, dict) or "p" not in jetzt:
            continue
        if jetzt["p"] < alt.get("wilson_lo", 0.0):
            code = 1
            meldungen.append(
                f"{name}: {jetzt['p']:.4f} unter Baseline-Wilson-Untergrenze "
                f"{alt['wilson_lo']:.4f} (Baseline p={alt.get('p')})")
    return code, meldungen


def write_run(root: Path, run_id: str, run: dict, quotas: dict) -> Path:
    """runs/<run_id>/ mit summary.md, metrics.json und failures/."""
    out = root / "runs" / run_id
    (out / "failures").mkdir(parents=True, exist_ok=True)

    drift = classify_drift(run["results"])
    zaehler = {}
    for r in run["results"]:
        zaehler[r["band"]] = zaehler.get(r["band"], 0) + 1

    (out / "metrics.json").write_text(json.dumps(
        {"run_id": run_id, "generated": datetime.now().isoformat(timespec="seconds"),
         "tier": run["tier"], "n": run["n"], "dauer_s": run["dauer_s"],
         "bilder_pro_s": run["bilder_pro_s"], "baender": zaehler,
         "drift": drift, "quotas": quotas,
         "code_fingerprint": run["code_fingerprint"],
         "config_fingerprint": run["config_fingerprint"]},
        indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    for r in run["results"]:
        if r["band"] == "pass":
            continue
        (out / "failures" / f"{r['sha'][:8]}.json").write_text(
            json.dumps({**r, "image_rel": f"{r['session']}/images/"
                                          f"{r['article']}/{r['sha'][:8]}.png"},
                       indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    zeilen = [f"# Korpus-Lauf `{run_id}`", "",
              f"- Tier: {run['tier']}",
              f"- Bilder: {run['n']} (neu gerechnet: {run['neu_gerechnet']})",
              f"- Laufzeit: {run['dauer_s']} s"
              + (f" = {run['bilder_pro_s']} Bilder/s" if run["bilder_pro_s"] else ""),
              "", "## Baender", ""]
    for b in ("pass", "drift", "fail"):
        zeilen.append(f"- {b.upper()}: {zaehler.get(b, 0)}")
    zeilen += ["", "## Drift-Klassifikation", "",
               f"- Muster: **{drift['muster']}**",
               f"- betroffen: {drift['betroffen']} ({drift['anteil']:.1%})",
               f"- Delta-Median: {drift['delta_median']}",
               f"- relative Streuung: {drift['streuung']}", ""]
    if drift["muster"] == "uniform":
        zeilen.append("> Gleichmaessige Verschiebung ueber viele Bilder — Muster "
                      "Bibliothek/Plattform, nicht Code.")
    elif drift["muster"] == "ausreisser":
        zeilen.append("> Einzelne Bilder betroffen — Muster Code-Regression.")
    if quotas:
        zeilen += ["", "## Tier-2-Quoten", "",
                   "| Kennzahl | k/n | p | Wilson |", "|---|---|---|---|"]
        for name, q in quotas.items():
            if isinstance(q, dict) and "p" in q:
                zeilen.append(f"| {name} | {q['k']}/{q['n']} | {q['p']:.4f} | "
                              f"{q['wilson_lo']:.4f} … {q['wilson_hi']:.4f} |")
    (out / "summary.md").write_text("\n".join(zeilen) + "\n", encoding="utf-8")
    return out
