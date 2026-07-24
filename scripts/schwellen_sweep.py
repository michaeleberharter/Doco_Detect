"""Schwellen-Sweep — report-only Betriebskurven (Block 2).

Leitet die Entscheidungen aus den vorhandenen Tier-2-REPLAY-Reports NEU AB
(kein Segmentierungs-/Feature-/Matcher-Lauf). Sweept die beiden Gates
max_z_accept und min_llr_margin; Kandidatenmenge und Ranking haengen NICHT an
den Gates, darum ist die Neu-Ableitung exakt.

INPUT: runs/win-postfix-tier2/replay/ — die Replay-Reports, die die Baseline
DEFINIEREN. NICHT die Enrollment-Aera-Goldens (die liefern 86/97/43, falsche
Grundlage). Der Pinning-Test sichert diese Wahl ab.

Aendert NICHTS: keine Config-/Baseline-/accepted_deltas-Schreibpfade.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.matcher import MatchReport  # noqa: E402
from docodetect.corpus.report import tier2_quotas  # noqa: E402

REPLAY = Path(r"C:/Users/Mike/Desktop/Doco_Detect_corpus/runs/win-postfix-tier2/replay")
OUT = (Path(__file__).resolve().parent.parent / "reports" / "archive"
       / "schwellen-sweep-2026-07-24")
PROD_Z, PROD_M = 3.5, 2.0
LLR_DRIFT = 1.5e-3   # groesste beobachtete Tier-2-llr-Drift (Block-2-Attribution)
BASELINE = {"accuracy_top1": (95, 104), "accuracy_top3": (101, 104),
            "auto_accept_rate": (44, 104), "false_accept_rate": (0, 44),
            "decisions": {"ambiguous": 56, "accept": 44, "reject": 4}}
VIERLINGE = {"MESSER-2", "MESSER-5", "MESSER-6", "MESSER-7"}  # datengetrieben, s. Bericht


def load_reports():
    return [(p.stem, MatchReport.from_json(p.read_text(encoding="utf-8")))
            for p in sorted(REPLAY.glob("*.json"))]


def rederive(r, z, m) -> str:
    if not r.candidates:
        return "reject"
    if r.max_z_winner is None or r.max_z_winner > z:
        return "reject"
    if (r.llr_margin is None or r.llr_margin >= m) and r.candidates[0].has_references:
        return "accept"
    return "ambiguous"


def quotas_at(reps, z, m) -> dict:
    for r in reps:
        r.decision = rederive(r, z, m)
    return tier2_quotas(reps)


def pinning_check(reps):
    stored = [r.decision for r in reps]
    q = quotas_at(reps, PROD_Z, PROD_M)
    assert stored == [r.decision for r in reps], "Neu-Ableitung != gespeicherte Entscheidung"
    for k, expect in BASELINE.items():
        if k == "decisions":
            assert q["decisions"] == expect, f"decisions {q['decisions']} != {expect}"
        else:
            assert (q[k]["k"], q[k]["n"]) == expect, f"{k} {q[k]['k']}/{q[k]['n']} != {expect}"
    print(f"[pinning] OK: {REPLAY.name}, {len(reps)} Reports, reproduziert die Baseline "
          f"bei ({PROD_Z}/{PROD_M}).")


def frange(a, b, step):
    return [round(a + i * step, 4) for i in range(round((b - a) / step) + 1)]


def sweep(reps, zs, ms, label):
    rows = []
    for z in zs:
        for m in ms:
            q = quotas_at(reps, z, m)
            aa, fa, d = q["auto_accept_rate"], q["false_accept_rate"], q["decisions"]
            rows.append(dict(variant=label, max_z_accept=z, min_llr_margin=m,
                             accept_k=aa["k"], accept_n=aa["n"], accept_p=aa["p"],
                             accept_lo=aa["wilson_lo"], accept_hi=aa["wilson_hi"],
                             false_k=fa["k"], false_n=fa["n"], false_p=fa["p"],
                             false_lo=fa["wilson_lo"], false_hi=fa["wilson_hi"],
                             reject=d.get("reject", 0), ambiguous=d.get("ambiguous", 0),
                             top1_k=q["accuracy_top1"]["k"], top1_n=q["accuracy_top1"]["n"]))
    return rows


def knee(reps):
    wrong = [(sha, r) for sha, r in reps
             if r.label and r.candidates and r.candidates[0].article_number != r.label
             and r.candidates[0].has_references]
    cases = [dict(sha8=sha, label=r.label, accepted=r.candidates[0].article_number,
                  max_z_winner=r.max_z_winner, llr_margin=r.llr_margin) for sha, r in wrong]
    # M-Knick bei Z=prod: hoechste llr unter den top1-falschen mit max_z<=PROD_Z
    at_prodZ = [c for c in cases if c["max_z_winner"] <= PROD_Z and c["llr_margin"] is not None]
    at_prodZ.sort(key=lambda c: -c["llr_margin"])
    m_knee = at_prodZ[0] if at_prodZ else None
    # Z-Achse bei M=prod: rejects-mit-Kandidaten, die zu Accept wuerden
    z_gains = []
    for sha, r in reps:
        if r.candidates and r.max_z_winner is not None and r.max_z_winner > PROD_Z \
                and (r.llr_margin is None or r.llr_margin >= PROD_M) and r.candidates[0].has_references:
            z_gains.append(dict(sha8=sha, label=r.label, top1=r.candidates[0].article_number,
                                correct=r.candidates[0].article_number == r.label,
                                enters_at_z=r.max_z_winner, llr=r.llr_margin))
    z_gains.sort(key=lambda c: c["enters_at_z"])
    return cases, m_knee, z_gains


def plots(rows_mit, rows_ohne, m_knee, outdir):
    def slice_at(rows, key_fix, val_fix, key_var):
        pts = [r for r in rows if abs(r[key_fix] - val_fix) < 1e-9]
        pts.sort(key=lambda r: r[key_var])
        return pts

    # M-Schnitt bei Z=prod
    fig, ax = plt.subplots(figsize=(7, 4.2))
    for rows, lbl, c in ((rows_mit, "mit Vierlingen (n=104)", "C0"),
                         (rows_ohne, "ohne Vierlinge (n=92)", "C1")):
        s = slice_at(rows, "max_z_accept", PROD_Z, "min_llr_margin")
        ax.plot([r["min_llr_margin"] for r in s], [r["accept_p"] for r in s], c + "-", label=f"auto_accept · {lbl}")
        ax.plot([r["min_llr_margin"] for r in s], [r["false_p"] for r in s], c + "--", label=f"false_accept · {lbl}")
    ax.axvline(PROD_M, color="k", ls=":", lw=1); ax.text(PROD_M, 0.9, " Betrieb 2,0", fontsize=8)
    if m_knee:
        ax.axvline(m_knee["llr_margin"], color="r", ls=":", lw=1)
        ax.text(m_knee["llr_margin"], 0.05, f" Knick {m_knee['llr_margin']:.3f}\n {m_knee['label']}→{m_knee['accepted']}", fontsize=7, color="r")
    ax.set_xlabel("min_llr_margin (Z=3,5 fix)"); ax.set_ylabel("Rate"); ax.set_ylim(0, 1)
    ax.set_title("M-Schnitt: Accept-/False-Rate über min_llr_margin"); ax.legend(fontsize=7); ax.grid(alpha=.3)
    fig.tight_layout(); fig.savefig(outdir / "m_slice.png", dpi=130); plt.close(fig)

    # Z-Schnitt bei M=prod
    fig, ax = plt.subplots(figsize=(7, 4.2))
    for rows, lbl, c in ((rows_mit, "mit Vierlingen", "C0"), (rows_ohne, "ohne Vierlinge", "C1")):
        s = slice_at(rows, "min_llr_margin", PROD_M, "max_z_accept")
        ax.plot([r["max_z_accept"] for r in s], [r["accept_p"] for r in s], c + "-", label=f"auto_accept · {lbl}")
        ax.plot([r["max_z_accept"] for r in s], [r["false_p"] for r in s], c + "--", label=f"false_accept · {lbl}")
    ax.axvline(PROD_Z, color="k", ls=":", lw=1); ax.text(PROD_Z, 0.9, " Betrieb 3,5", fontsize=8)
    ax.set_xlabel("max_z_accept (M=2,0 fix)"); ax.set_ylabel("Rate"); ax.set_ylim(0, 1)
    ax.set_title("Z-Schnitt: Accept-/False-Rate über max_z_accept (false bleibt 0)")
    ax.legend(fontsize=7); ax.grid(alpha=.3)
    fig.tight_layout(); fig.savefig(outdir / "z_slice.png", dpi=130); plt.close(fig)

    # Betriebskurve auto vs false (über M bei mehreren Z), mit Vierlingen
    fig, ax = plt.subplots(figsize=(6.4, 4.6))
    for z, c in ((3.5, "C0"), (4.5, "C2"), (5.5, "C3")):
        s = slice_at(rows_mit, "max_z_accept", z, "min_llr_margin")
        ax.plot([r["false_p"] for r in s], [r["accept_p"] for r in s], c + "-o", ms=2, label=f"Z={z}")
    op = [r for r in rows_mit if abs(r["max_z_accept"]-PROD_Z)<1e-9 and abs(r["min_llr_margin"]-PROD_M)<1e-9][0]
    ax.plot(op["false_p"], op["accept_p"], "k*", ms=14, label="Betrieb 3,5/2,0")
    ax.set_xlabel("false_accept_rate"); ax.set_ylabel("auto_accept_rate")
    ax.set_title("Betriebskurve (über min_llr_margin, je Z)"); ax.legend(fontsize=8); ax.grid(alpha=.3)
    fig.tight_layout(); fig.savefig(outdir / "betriebskurve.png", dpi=130); plt.close(fig)
    print(f"[plots] m_slice.png, z_slice.png, betriebskurve.png -> {outdir}")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")   # Windows-Konsole cp1252 -> utf-8
    except Exception:
        pass
    ap = argparse.ArgumentParser(); ap.add_argument("--out", default=str(OUT))
    outdir = Path(ap.parse_args().out); outdir.mkdir(parents=True, exist_ok=True)

    reps = load_reports()
    pinning_check([r for _, r in reps])
    zs, ms = frange(2.0, 6.0, 0.1), frange(0.0, 5.0, 0.1)
    mit = [(s, r) for s, r in reps]
    ohne = [(s, r) for s, r in reps if (r.label or "") not in VIERLINGE]
    print(f"[sweep] mit n={len(mit)}, ohne Vierlinge n={len(ohne)} (−{len(mit)-len(ohne)}: {sorted(VIERLINGE)})")

    rows_mit = sweep([r for _, r in mit], zs, ms, "mit_vierlinge")
    rows_ohne = sweep([r for _, r in ohne], zs, ms, "ohne_vierlinge")
    with open(outdir / "sweep_grid.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows_mit[0].keys())); w.writeheader()
        w.writerows(rows_mit + rows_ohne)
    print(f"[sweep] {len(rows_mit)+len(rows_ohne)} Rasterpunkte -> sweep_grid.csv")

    cases, m_knee, z_gains = knee(mit)
    # 0,01-Nachverfeinerung um den M-Knick (Z=3,5)
    fine = []
    for m in frange(1.90, 2.05, 0.01):
        q = quotas_at([r for _, r in mit], PROD_Z, m)
        fine.append(dict(min_llr_margin=m, accept=q["auto_accept_rate"]["k"],
                         false=q["false_accept_rate"]["k"], false_n=q["false_accept_rate"]["n"]))
    knee_out = dict(m_knee=m_knee, dist_to_operating=(PROD_M - m_knee["llr_margin"]) if m_knee else None,
                    drift_reserve_x=((PROD_M - m_knee["llr_margin"]) / LLR_DRIFT) if m_knee else None,
                    n_top1_wrong=len(cases), cases=cases, z_gains=z_gains, fine_m_at_Z3p5=fine)
    (outdir / "knee.json").write_text(json.dumps(knee_out, indent=2), encoding="utf-8")
    print(f"[knick] M-Knick bei min_llr_margin={m_knee['llr_margin']} "
          f"({m_knee['label']}→{m_knee['accepted']}, sha {m_knee['sha8']}), "
          f"Abstand zum Betrieb {PROD_M - m_knee['llr_margin']:.4f} = "
          f"{(PROD_M - m_knee['llr_margin'])/LLR_DRIFT:.0f}× die llr-Drift")
    print(f"[knick] Z-Achse bei M=2,0: {len(z_gains)} rejects werden Accept (alle top1-korrekt: "
          f"{all(g['correct'] for g in z_gains)}); Eintritts-Z {[g['enters_at_z'] for g in z_gains]}")
    print("[fine] M @ Z=3,5:  " + "  ".join(f"{r['min_llr_margin']}:{r['accept']}A/{r['false']}F" for r in fine))

    plots(rows_mit, rows_ohne, m_knee, outdir)


if __name__ == "__main__":
    main()
