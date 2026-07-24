"""Lauf-Berichte, Baseline und Exit-Code-Logik."""

from __future__ import annotations

import json
import math
import statistics
from datetime import datetime
from pathlib import Path

from ..config import project_root
from ..reporting import NO_MATCH, judgement, predicted_article, summarize
from .compare import DRIFT, FAIL

BASELINE_PATH = project_root() / "corpus" / "baseline.json"

# Ab so vielen betroffenen Bildern UND so kleiner relativer Streuung gilt
# eine Drift als uniform (Bibliothek/Plattform) statt als Ausreisser (Code).
UNIFORM_MIN_ANTEIL = 0.5
UNIFORM_MAX_STREUUNG = 0.25

# Kennzahlen, bei denen GROESSER = SCHLECHTER ist. Sie regressieren nach
# oben und muessen deshalb gegen die Wilson-OBERgrenze geprueft werden.
# Die Untergrenzen-Pruefung ist bei ihnen wirkungslos: false_accept_rate
# steht bei 0/25 mit wilson_lo 0.0, und p < 0.0 kann nie eintreten — eine
# Fehlbuchungsrate von 0 auf 20 % liefe damit als "OK" durch.
FEHLERRATEN = ("false_accept_rate",)

# Kennzahlen, die MITLAUFEN, aber NICHT gaten. accuracy_top1_verdict ist die
# alte, verdict-basierte Zaehlung: sie friert das menschliche Urteil vom Tag
# der Aufnahme ein und bewegt sich durch keine Matcher-Aenderung — als Gate
# misst sie darum nichts. Sie bleibt als Zusatzfeld erhalten, weil sie die
# Bruecke zu den `analyze`-Zahlen und zur alten Baseline schlaegt.
NUR_INFO = ("accuracy_top1_verdict",)

# Semantik-Marke der Quoten. Steht in jeder geschriebenen baseline.json und
# wird von check_against_baseline gegen die eigene geprueft: eine Baseline
# aus der verdict-Aera traegt sie NICHT, und ihre top1-Schranke beschreibt
# eine andere Groesse als die heute gerechnete. Ohne diese Marke haette der
# Wechsel den Vergleich still verschoben — die Zahl haette sich bewegt und
# niemand haette gewusst, ob Matcher oder Definition sich geaendert hat.
QUOTEN_SEMANTIK = "top1-roh-gegen-label/2026-07-23"


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

    SEMANTIK seit 2026-07-23 (Semantikwechsel, siehe baseline.json/
    "semantik" und docs/superpowers/reports/2026-07-23-phase-c-ergebnis.md):

    accuracy_top1 und accuracy_top3 rechnen **roh gegen das wahre Label** —
    Rang-1 bzw. Rang-1..3 gegen `report.label`, ueber dieselbe Grundmenge
    (alle gelabelten Reports). Das ist die einzige Groesse, die sich bewegt,
    wenn der Matcher sich aendert, und damit die einzige, die als Gate etwas
    misst.

    Vorher rechnete accuracy_top1 ueber `judgement()`, das dem menschlichen
    `verdict` Vorrang vor dem Label-Vergleich gibt. Ein verdict ist am Tag der
    Aufnahme eingefroren: es bleibt "wrong", auch wenn eine spaetere
    Matcher-Aenderung den Artikel korrekt auf Rang 1 hebt. Als Regressions-
    Gate war die Kennzahl damit blind. Sie laeuft als `accuracy_top1_verdict`
    weiter (Zusatzfeld, NICHT Gate-relevant — siehe NUR_INFO), weil sie die
    Bruecke zu den `analyze`-Zahlen schlaegt, die weiter ueber judgement()
    aggregieren.

    Nebenwirkung des Wechsels: top1 und top3 teilen jetzt denselben Nenner.
    Vorher war n(top1) = beurteilbare (verdict ODER label), n(top3) =
    gelabelte — zwei verschiedene Grundmengen, deren Quoten man nicht
    nebeneinander lesen durfte.
    """
    s = summarize(reports)
    labeled = [r for r in reports if r.label]
    h1 = sum(1 for r in labeled if predicted_article(r) == r.label)
    n1 = len(labeled)
    h3 = sum(1 for r in labeled
             if (r.label in [c.article_number for c in r.candidates[:3]]
                 or (not r.candidates and r.label == NO_MATCH)))
    n3 = len(labeled)
    judged = [ok for r in reports if (ok := judgement(r)) is not None]
    hv, nv = sum(1 for ok in judged if ok), len(judged)
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
        "accuracy_top1_verdict": q(hv, nv),
        "decisions": s.decision_counts,
    }


def umgebung() -> dict:
    """Versionen der vier Pakete des Messpfads plus Plattform.

    Zweck ist die Attribution beim Plattformwechsel Mac<->Windows: DRIFT
    bricht per Default, und die Frage ist dann immer dieselbe — Code oder
    Umgebung? Ohne diesen Block steht die Antwort nirgends und muss
    nachtraeglich rekonstruiert werden, wenn die Umgebung sich laengst
    weitergedreht hat.

    Die Importe sind bewusst lokal und einzeln abgesichert: eine fehlende
    Bibliothek darf einen fertigen Lauf nicht um seine metrics.json bringen.
    """
    import platform
    import sqlite3
    import sys

    werte = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        # Die SQLite-Version war der unsichtbare Plattform-Unterschied
        # Mac<->Windows (unixepoch() braucht >=3.38; Windows-3.9.6 = 3.35.5).
        # Ab jetzt Teil des Fingerprint-Umfelds.
        "sqlite_version": sqlite3.sqlite_version,
    }
    for name, modul in (("numpy", "numpy"), ("cv2", "cv2"), ("scipy", "scipy")):
        try:
            werte[name] = __import__(modul).__version__
        except Exception as exc:                       # noqa: BLE001
            werte[name] = f"<nicht ermittelbar: {type(exc).__name__}>"
    werte["python_impl"] = platform.python_implementation()
    werte["executable"] = sys.executable
    return werte


def classify_drift(results: list) -> dict:
    """Uniforme Drift (Bibliothek/Plattform) von Ausreissern (Code) trennen.

    Uniform = viele Bilder, alle ungefaehr gleich stark verschoben.
    Ausreisser = wenige Bilder, beliebige Groesse. Genau diese Trennung
    entscheidet, ob ein --accept-drift-Lauf gerechtfertigt ist.
    """
    betroffen = [r for r in results if r["band"] == DRIFT]
    if not betroffen:
        return {"muster": "keine", "betroffen": 0, "anteil": 0.0,
                "delta_median": 0.0, "streuung": 0.0}
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

    # Semantik-Abgleich VOR den Kennzahlen: sonst liest sich ein gruener
    # Lauf wie eine bestaetigte Quote, obwohl die Baseline-Schranke fuer
    # top1 eine andere Groesse beschreibt (verdict statt Label). Kein
    # Exit-Code — die Bild-Vergleiche sind von der Definition unberuehrt,
    # und ein hartes Fail wuerde jeden Lauf bis zum Re-Baselining blockieren.
    # Aber laut genug, dass niemand die Zahl fuer geprueft haelt.
    if baseline and baseline.get("quoten_semantik") != QUOTEN_SEMANTIK:
        meldungen.append(
            f"HINWEIS: Baseline-Semantik "
            f"'{baseline.get('quoten_semantik', '<keine>')}' != "
            f"'{QUOTEN_SEMANTIK}'. accuracy_top1/top3 werden jetzt roh gegen "
            f"das Label gerechnet, die Baseline-Schranken stammen aus der "
            f"verdict-Aera — die beiden top1-Zahlen sind NICHT vergleichbar. "
            f"Re-Baselining faellig: corpus-run --tier 2 --update-baseline")

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
        if name in NUR_INFO:
            # Bewusst kein Gate: die verdict-Zaehlung ist eingefroren und
            # kann eine Regression weder anzeigen noch ausschliessen. Sie
            # hier mitzupruefen hiesse, Sicherheit zu melden, die nicht
            # geprueft wurde.
            continue
        alt = (baseline.get("quotas") or {}).get(name)
        # Kein Baseline-Eintrag: die Kennzahl ist neu, es gibt nichts zu
        # vergleichen. `decisions` traegt kein "p" und faellt hier ebenfalls
        # heraus — es ist eine Zaehlung, keine Quote.
        if not alt or not isinstance(jetzt, dict) or "p" not in jetzt:
            continue
        grenze = "wilson_hi" if name in FEHLERRATEN else "wilson_lo"
        schranke = alt.get(grenze) if isinstance(alt, dict) else None
        if not isinstance(schranke, (int, float)):
            # Eine fehlende Grenze ist ein Fehler, keine Erlaubnis: mit
            # .get(..., 0.0) waere der Vergleich still ausgeschaltet und das
            # Gate meldete Sicherheit, die es nicht geprueft hat.
            code = 1
            meldungen.append(
                f"{name}: Baseline-Eintrag ohne {grenze} — Kennzahl nicht "
                f"pruefbar. Baseline mit 'corpus-run --tier 2 "
                f"--update-baseline' neu erzeugen.")
            continue
        if name in FEHLERRATEN:
            if jetzt["p"] > schranke:
                code = 1
                meldungen.append(
                    f"{name}: {jetzt['p']:.4f} ueber Baseline-Wilson-"
                    f"Obergrenze {schranke:.4f} (Baseline p={alt.get('p')}) — "
                    f"Fehlerrate gestiegen")
        elif jetzt["p"] < schranke:
            code = 1
            meldungen.append(
                f"{name}: {jetzt['p']:.4f} unter Baseline-Wilson-Untergrenze "
                f"{schranke:.4f} (Baseline p={alt.get('p')})")
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
         "quoten_semantik": QUOTEN_SEMANTIK,
         "env": umgebung(),
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
