"""Block D6/D7: Gewichtsschemata x alpha, und w(s) mit hohem Gewicht.

D6  Die feature_weights sind eine Setzung aus der Anfangszeit, nie gegen Daten
    geprueft. Volle Matrix Schema x alpha (nicht nur die Diagonale), weil
    alpha=32 mit Schema S2 seinerzeit kombiniert einen false_accept ergab.
D7  Der w(s)-Negativbefund prueft nur Gewichte bis 0,25. Hier 0,40 und 0,60,
    plus die Frage, was passiert, wenn diameter_mm dadurch an Gewicht verliert.

Kein Produktivcode. Aufruf:
    .venv/bin/python scripts/analyse_gewichte_wprofil.py
"""
from __future__ import annotations

import itertools
import json
import pickle
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import simulate_scoring as sim  # noqa: E402
from docodetect.calibration import load_calibration  # noqa: E402
from docodetect.config import load_config, sandbox_cfg  # noqa: E402
from docodetect.features import ALL_FEATURES  # noqa: E402

WP = Path.home() / "Documents/tmp/2026-08-01-wprofil/profiles.pkl"
OUT = Path.home() / "Documents/tmp/2026-08-01-blockD"
K = 101
FARBE = ("delta_e_center", "delta_e_rim", "hist_center", "hist_rim")

SCHEMATA = {
    "S0 heute": {"diameter_mm": .50, "circularity": .07, "solidity": .06,
                 "delta_e_center": .08, "delta_e_rim": .08,
                 "hist_center": .07, "hist_rim": .07, "hu_log": .07},
    "S1 gleich": {f: 0.125 for f in ALL_FEATURES},
    "S2 Form": {"diameter_mm": .25, "circularity": .15, "solidity": .15,
                "delta_e_center": .075, "delta_e_rim": .075,
                "hist_center": .075, "hist_rim": .075, "hu_log": .15},
    "S3 Farbe ab": {"diameter_mm": .50, "circularity": .12, "solidity": .12,
                    "delta_e_center": .0375, "delta_e_rim": .0375,
                    "hist_center": .0375, "hist_rim": .0375, "hu_log": .11},
    "S4 Oe stark": {"diameter_mm": .70, "circularity": .05, "solidity": .05,
                    "delta_e_center": .0375, "delta_e_rim": .0375,
                    "hist_center": .0375, "hist_rim": .0375, "hu_log": .05},
}


def resample_u(w):
    n = len(w)
    return np.interp(np.linspace(0, 1, K), (np.arange(n) + 0.5) / n, np.asarray(w, float))


def d_full(a, b):
    return float(np.sqrt(np.mean((a - b) ** 2)))


def k_safe(res):
    c = [r for r in res if r["decision"] != "reject"]
    c.sort(key=lambda r: -(r["llr"] if r["llr"] is not None else float("inf")))
    k = 0
    for i, r in enumerate(c):
        if r["ranking"][:1] != [r["wahr"]]:
            break
        k = i + 1
    return k


def gegenprobe(base, res):
    from scipy.stats import spearmanr
    lb = np.array([r["llr"] if r["llr"] is not None else np.inf for r in base])
    lk = np.array([r["llr"] if r["llr"] is not None else np.inf for r in res])
    e = np.isfinite(lb) & np.isfinite(lk)
    rho = spearmanr(lb[e], lk[e]).statistic
    n = int((lk >= 2.0).sum())
    t = float(np.sort(lb)[::-1][n - 1]) if 0 < n <= len(lb) else float("nan")
    sk = {i for i in range(len(lk)) if lk[i] >= 2.0}
    sb = {i for i in range(len(lb)) if lb[i] >= t}
    return rho, n, t, len(sk & sb)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cfg = sandbox_cfg(load_config(), sim.SANDBOX, verbose=False)
    cal = load_calibration(cfg)
    m0 = cfg["matching"]
    bestand = sim.lade_bestand(cfg)
    arts, feats, voll, loo = bestand
    A = sorted(loo)
    base = sim.lauf(bestand, cal, sim.variante_cfg(m0), "mean")

    def m_mit(schema, alpha):
        m = sim.variante_cfg(m0)
        m["feature_weights"] = dict(schema)
        m["adaptive_weight_alpha"] = float(alpha)
        return m

    # ==================================================================== D6
    print("=" * 104)
    print("D6) GEWICHTSSCHEMA x ALPHA — volle Matrix, nicht nur die Diagonale")
    print("=" * 104)
    print(f"{'Schema':<13}{'alpha':>6}" + sim.KOPF[34:] + f"{'k_safe':>8}{'Ueberl.':>9}")
    d6 = {}
    for nm, schema in SCHEMATA.items():
        for al in (0.0, 2.0, 8.0, 32.0):
            res = sim.lauf(bestand, cal, m_mit(schema, al), "mean")
            k = sim.kennzahlen(res, 2.0, 3.5)
            rho, nacc, t, ueb = gegenprobe(base, res)
            d6[(nm, al)] = k
            flag = "  <== false_accept" if k["false_accept"] else ""
            print(f"{nm:<13}{al:>6.0f}" + sim.zeile("", k)[34:]
                  + f"{k_safe(res):>8}{ueb}/{nacc:<5}{flag}")

    # ==================================================================== D7
    print()
    print("=" * 104)
    print("D7) w(s) MIT HOHEM GEWICHT — was passiert, wenn Ø an Gewicht verliert?")
    print("=" * 104)
    if not WP.exists():
        print(f"  Profil-Cache fehlt ({WP}) — D7 uebersprungen.")
        return
    data = pickle.load(open(WP, "rb"))
    shots = data["shots"]
    U = {a: np.array([resample_u(x["w_mm"]) for x in shots[a]
                      if x["w_mm"] is not None])
         for a in shots if any(x["w_mm"] is not None for x in shots[a])}
    proto_voll = {a: U[a].mean(axis=0) for a in U}
    sig_voll = {a: float(np.sqrt(np.mean([d_full(u, proto_voll[a]) ** 2 for u in U[a]])))
                for a in U}
    # Leave-one-out-Prototypen fuer die 13 eingelernten Artikel
    proto_loo, sig_loo = {}, {}
    for a in A:
        if a not in U or len(U[a]) < 13:
            continue
        proto_loo[a], sig_loo[a] = [], []
        for i in range(len(U[a])):
            rest = np.delete(U[a], i, axis=0)
            p = rest.mean(axis=0)
            proto_loo[a].append(p)
            sig_loo[a].append(float(np.sqrt(np.mean([d_full(u, p) ** 2 for u in rest]))))
    fehlt = [a for a in A if a not in proto_loo]
    if fehlt:
        print(f"  ohne Profil, w(s) faellt dort aus: {fehlt}")

    # Tabelle je (wahrer Artikel, Shot) -> {Kandidat: (d, sigma)}
    tab = {}
    for a in A:
        if a not in proto_loo:
            continue
        for i in range(len(U[a])):
            wm = U[a][i]
            eintrag = {}
            for x in (art.article_number for art in arts):
                if x == a:
                    eintrag[x] = (d_full(wm, proto_loo[a][i]), sig_loo[a][i])
                elif x in proto_voll:
                    eintrag[x] = (d_full(wm, proto_voll[x]), sig_voll[x])
            tab[(a, i)] = eintrag

    print(f"  Tabelle: {len(tab)} Messungen x bis zu {len(arts)} Kandidaten")
    print(f"\n{'Gewicht w(s)':<14}{'Ø-Anteil':>10}" + sim.KOPF[34:]
          + f"{'k_safe':>8}{'Ueberl.':>9}")
    for g in (0.0, 0.10, 0.25, 0.40, 0.60, 1.00):
        meta = {"name": "w_profile", "gewicht": g, "floor": 0.50}
        if g == 0.0:
            res, anteil = base, 0.50
        else:
            res = sim.lauf(bestand, cal, sim.variante_cfg(m0), "mean",
                           zusatz_tab=tab, zusatz_meta=meta)
            anteil = 0.50 / (1.0 + g)
        k = sim.kennzahlen(res, 2.0, 3.5)
        rho, nacc, t, ueb = gegenprobe(base, res)
        print(f"{g:<14.2f}{anteil:>10.3f}" + sim.zeile("", k)[34:]
              + f"{k_safe(res):>8}{ueb}/{nacc:<5}")

    with open(OUT / "blockD67.json", "w") as fh:
        json.dump({f"{a}|{b}": v for (a, b), v in d6.items()}, fh, indent=1)
    print(f"\n-> {OUT/'blockD67.json'}")


if __name__ == "__main__":
    main()
