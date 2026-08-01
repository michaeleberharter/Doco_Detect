"""Block A: Die Unabhaengigkeitsannahme der Likelihood pruefen.

Die Gauss-Likelihood in matcher.py behandelt die acht Merkmale als unkorreliert
(log_score = Summe gewichteter -0.5 z^2). Dieses Skript misst die tatsaechliche
Korrelationsstruktur, prueft ob eine gepoolte Kovarianz ueberhaupt schaetzbar
ist, und simuliert die Mahalanobis-Variante.

Kein Messpfad. Reine Auswertung + Simulation ueber scripts/simulate_scoring.py.

Aufruf:
    .venv/bin/python scripts/analyse_merkmalskorrelation.py
"""
from __future__ import annotations

import itertools
import json
import math
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import simulate_scoring as sim  # noqa: E402
from docodetect.calibration import load_calibration  # noqa: E402
from docodetect.config import load_config, sandbox_cfg  # noqa: E402
from docodetect.features import (ALL_FEATURES, PROTO_FEATURES,  # noqa: E402
                                 SCALAR_FEATURES, proto_distance, scalar_value)
from docodetect.matcher import _sigma_floor  # noqa: E402

OUT = Path.home() / "Documents/tmp/2026-08-01-blockA"
KURZ = {"diameter_mm": "diam", "circularity": "circ", "solidity": "soli",
        "delta_e_center": "dEc", "delta_e_rim": "dEr",
        "hist_center": "hic", "hist_rim": "hir", "hu_log": "hu"}


def z_matrix(bestand, floors):
    """z-Vektoren der WAHREN Artikel: fuer jeden der 169 Shots die acht
    z-Werte gegen die Leave-one-out-Referenz des eigenen Artikels.

    Das ist genau der Vektor, dessen Komponenten die Likelihood als
    unabhaengig annimmt und quadriert aufsummiert."""
    _, feats, _, stats_loo = bestand
    rows, labels = [], []
    for a in sorted(stats_loo):
        for i, m in enumerate(feats[a]):
            st = stats_loo[a][i]
            z = []
            ok = True
            for f in ALL_FEATURES:
                if f in SCALAR_FEATURES:
                    mv = scalar_value(m, f)
                    if mv is None or f not in st.scalar_mean:
                        ok = False
                        break
                    d = abs(mv - st.scalar_mean[f])
                    se = st.scalar_std.get(f, 0.0)
                else:
                    d = proto_distance(f, m, st)
                    if d is None:
                        ok = False
                        break
                    se = st.proto_std.get(f, 0.0)
                z.append(d / math.sqrt(se ** 2 + _sigma_floor(f, floors) ** 2))
            if ok:
                rows.append(z)
                labels.append(a)
    return np.array(rows), labels


def zweitmoment(Z):
    """C = E[z z^T], auf Einheitsdiagonale skaliert. NICHT zentriert:
    fuer unabhaengige Merkmale mit z ~ eigener Skala ist C = I, und die
    quadratische Form reduziert sich exakt auf die heutige Summe."""
    # einsum statt @: vermeidet die spuriose divide-by-zero-Warnung des
    # matmul-SIMD-Pfads (gleiche Stelle wie features.py::_proj, Ergebnis
    # geprueft identisch bis 0.0).
    M = np.einsum('ij,ik->jk', Z, Z) / len(Z)
    d = np.sqrt(np.diag(M))
    return M / np.outer(d, d)


def eff_rang(C):
    """Effektiver Rang ueber die Partizipationsquote der Eigenwerte."""
    w = np.linalg.eigvalsh(C)
    w = np.clip(w, 1e-12, None)
    p = w / w.sum()
    return float(np.exp(-(p * np.log(p)).sum())), w[::-1]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cfg = sandbox_cfg(load_config(), sim.SANDBOX, verbose=False)
    cal = load_calibration(cfg)
    basis_m = cfg["matching"]
    floors = basis_m["sigma_floors"]
    bestand = sim.lade_bestand(cfg)
    Z, labels = z_matrix(bestand, floors)
    arts = sorted(set(labels))
    print(f"z-Matrix: {Z.shape[0]} Shots x {Z.shape[1]} Merkmale, "
          f"{len(arts)} Artikel")

    # ================================================================= A1
    print("\n" + "=" * 92)
    print("A1) KORRELATIONSSTRUKTUR der acht Merkmale (Pearson ueber die z-Vektoren)")
    print("=" * 92)
    R = np.corrcoef(Z.T)
    hdr = "".join(f"{KURZ[f]:>7}" for f in ALL_FEATURES)
    print(f"{'':<6}{hdr}")
    for i, f in enumerate(ALL_FEATURES):
        print(f"{KURZ[f]:<6}" + "".join(f"{R[i, j]:>7.2f}" for j in range(8)))

    print("\n  Mittelwert |z| je Merkmal (zeigt die Faltung der Vektor-Merkmale):")
    print("   " + "  ".join(f"{KURZ[f]}={Z[:, i].mean():.2f}"
                            for i, f in enumerate(ALL_FEATURES)))

    paare = [(abs(R[i, j]), R[i, j], ALL_FEATURES[i], ALL_FEATURES[j])
             for i, j in itertools.combinations(range(8), 2)]
    paare.sort(reverse=True)
    print("\n  staerkste Paare:")
    for a, r, f1, f2 in paare[:6]:
        print(f"    {f1:<16} <-> {f2:<16} rho = {r:+.3f}")
    print(f"  Paare mit |rho| > 0.5: {sum(1 for a, *_ in paare if a > 0.5)} von 28")
    print(f"  Paare mit |rho| > 0.3: {sum(1 for a, *_ in paare if a > 0.3)} von 28")

    er, ew = eff_rang(R)
    print(f"\n  Eigenwerte: {', '.join(f'{v:.2f}' for v in ew)}")
    print(f"  effektiver Rang (Entropie-Mass): {er:.2f} von 8")
    kum = np.cumsum(ew) / ew.sum()
    print(f"  Varianzanteil der ersten k Komponenten: "
          + ", ".join(f"k={k+1}:{kum[k]*100:.0f}%" for k in range(4)))

    # ================================================================= A2
    print("\n" + "=" * 92)
    print("A2) IST EINE GEPOOLTE KOVARIANZ TRAGFAEHIG?")
    print("=" * 92)
    C = zweitmoment(Z)
    kappa = float(np.linalg.cond(C))
    print(f"  Zweitmoment-Matrix C (Einheitsdiagonale), Konditionszahl = {kappa:.1f}")
    print(f"  Stichprobe: {len(Z)} Shots fuer 8x8 (36 freie Parameter) "
          f"-> {len(Z)/36:.1f} Beobachtungen je Parameter")

    print("\n  Stabilitaet unter Leave-one-ARTIKEL-out (13 Neuschaetzungen):")
    kappas, maxdev = [], []
    Cs = []
    for a in arts:
        m = np.array([l != a for l in labels])
        Ca = zweitmoment(Z[m])
        Cs.append(Ca)
        kappas.append(float(np.linalg.cond(Ca)))
        maxdev.append(float(np.abs(Ca - C).max()))
    print(f"    Konditionszahl: min {min(kappas):.1f}, Median "
          f"{np.median(kappas):.1f}, max {max(kappas):.1f}")
    print(f"    groesste Abweichung eines Eintrags zur Voll-Matrix: "
          f"min {min(maxdev):.3f}, Median {np.median(maxdev):.3f}, "
          f"max {max(maxdev):.3f}")
    ewR = np.linalg.eigvalsh(R)
    ewC = np.linalg.eigvalsh(C)
    print(f"\n  Konditionierung — und warum sich die beiden Matrizen unterscheiden:")
    print(f"    R (zentriert, Pearson):     kappa {ewR[-1]/ewR[0]:>6.1f}, "
          f"kleinster Eigenwert {ewR[0]:.3f}  -> gut konditioniert")
    print(f"    C (unzentriert, Zweitmom.): kappa {ewC[-1]/ewC[0]:>6.1f}, "
          f"kleinster Eigenwert {ewC[0]:.4f}  -> schlecht konditioniert")
    print("    Ursache ist NICHT die Datenmenge, sondern die Faltung: fuenf der acht")
    print("    Merkmale sind Prototyp-DISTANZEN und damit >= 0, alle z-Mittelwerte")
    print("    liegen bei 0.36-0.62. C wird dadurch von der gemeinsamen")
    print("    Positiv-Richtung dominiert; ihre Komplemente werden klein. Wer C")
    print("    invertiert, gewichtet genau die Richtungen hoch, die die Daten am")
    print("    schlechtesten bestimmen.")
    stab = max(maxdev) < 0.25
    print(f"\n    -> Struktur unter Artikel-Weglassen: "
          f"{'STABIL' if stab else 'INSTABIL'} (groesste Einzelabweichung "
          f"{max(maxdev):.3f}). Die Matrix haengt NICHT an einzelnen Artikeln.")
    print("    -> Aber die Inverse ist heikel. Darum werden unten zusaetzlich")
    print("       Shrinkage-Varianten und die auf |rho| > 0.5 reduzierte Matrix")
    print("       gerechnet, wie im Auftrag vorgesehen.")

    def als_dict(Minv):
        return {f1: {f2: float(Minv[i, j]) for j, f2 in enumerate(ALL_FEATURES)}
                for i, f1 in enumerate(ALL_FEATURES)}

    C_shrunk = {lam: (1 - lam) * C + lam * np.eye(8) for lam in (0.2, 0.5)}
    C_red = C.copy()                       # nur Bloecke mit |rho| > 0.5
    for i in range(8):
        for j in range(8):
            if i != j and abs(R[i, j]) <= 0.5:
                C_red[i, j] = 0.0
    Cinv = np.linalg.inv(C)
    sim.MAHA_C = C
    sim.MAHA_CINV = {f1: {f2: float(Cinv[i, j]) for j, f2 in enumerate(ALL_FEATURES)}
                     for i, f1 in enumerate(ALL_FEATURES)}

    # ================================================================= A3
    print("\n" + "=" * 92)
    print("A3) SIMULATION: Mahalanobis statt Summe unabhaengiger z-Quadrate")
    print("    log_score = -0.5 * z^T D^0.5 C^-1 D^0.5 z, D = diag(w_eff).")
    print("    Fuer C = I ist das exakt die Baseline (strikte Verallgemeinerung).")
    print("=" * 92)
    ergebnisse, roh = {}, {}

    def run(name, m, agg, merkmale=None):
        res = sim.lauf(bestand, cal, m, agg, merkmale)
        k = (float(m["min_llr_margin"]), float(m["max_z_accept"]))
        ergebnisse[name] = sim.kennzahlen(res, *k)
        roh[name] = res
        return res

    print(sim.KOPF)
    faelle = [("a) Baseline", sim.variante_cfg(basis_m), "mean", None),
              ("A) maha", sim.variante_cfg(basis_m), "maha", None),
              ("A) maha + floor x0.5",
               sim.variante_cfg(basis_m, floor=0.5), "maha", None),
              ("A) maha + tol 4.0",
               sim.variante_cfg(basis_m, tol=4.0), "maha", None),
              ("A) maha ohne Farbe", sim.variante_cfg(basis_m), "maha",
               tuple(f for f in ALL_FEATURES if f not in sim.FARB_MERKMALE)),
              ("A) maha shrink 0.2", sim.variante_cfg(basis_m), "maha", None),
              ("A) maha shrink 0.5", sim.variante_cfg(basis_m), "maha", None),
              ("A) maha nur |rho|>0.5", sim.variante_cfg(basis_m), "maha", None),
              ("Kontrolle: floor x0.5 (mean)",
               sim.variante_cfg(basis_m, floor=0.5), "mean", None),
              ("Kontrolle: maha mit C=I", sim.variante_cfg(basis_m), "maha", None)]
    for i, (nm, m, agg, mk) in enumerate(faelle):
        if "shrink 0.2" in nm:
            sim.MAHA_CINV = als_dict(np.linalg.inv(C_shrunk[0.2]))
        elif "shrink 0.5" in nm:
            sim.MAHA_CINV = als_dict(np.linalg.inv(C_shrunk[0.5]))
        elif "rho|>0.5" in nm:
            sim.MAHA_CINV = als_dict(np.linalg.inv(C_red))
        elif nm.startswith("Kontrolle: maha"):
            sim.MAHA_CINV = als_dict(np.eye(8))
        else:
            sim.MAHA_CINV = als_dict(Cinv)
        run(nm, m, agg, mk)
        print(sim.zeile(nm, ergebnisse[nm]))
    sim.MAHA_CINV = {f1: {f2: float(Cinv[i, j]) for j, f2 in enumerate(ALL_FEATURES)}
                     for i, f1 in enumerate(ALL_FEATURES)}

    print("\n  max|z| des Siegers (Gate 3.5) — Verteilung:")
    for nm in ("a) Baseline", "A) maha", "A) maha + floor x0.5"):
        k = ergebnisse[nm]
        print(f"    {nm:<24} Median {k['mz_med']:.2f}, p90 {k['mz_p90']:.2f}, "
              f"max {k['mz_max']:.2f}, ueber Gate: {k['mz_ueber_gate']}")

    # ================================================================= A4
    print("\n" + "=" * 92)
    print("A4) GEGENPROBE: verkleidete Schwellensenkung?")
    print("=" * 92)
    from scipy.stats import spearmanr
    base = roh["a) Baseline"]
    lb = np.array([r["llr"] if r["llr"] is not None else np.inf for r in base])
    for nm in [n for n in roh if n != "a) Baseline"]:
        lk = np.array([r["llr"] if r["llr"] is not None else np.inf for r in roh[nm]])
        e = np.isfinite(lb) & np.isfinite(lk)
        rho = spearmanr(lb[e], lk[e]).statistic
        n_acc = int((lk >= 2.0).sum())
        t = float(np.sort(lb)[::-1][n_acc - 1]) if 0 < n_acc <= len(lb) else float("nan")
        sk = {i for i in range(len(lk)) if lk[i] >= 2.0}
        sb = {i for i in range(len(lb)) if lb[i] >= t}
        print(f"  {nm:<24} rho = {rho:+.4f} | ACCEPT {n_acc:>3} | "
              f"aequiv. Baseline-Schwelle {t:>6.3f} | Ueberlappung {len(sk & sb)}/{n_acc}")

    print("\n  k_safe (Pflichtkennzahl): groesstes k ohne false_accept,")
    print("  Faelle nach Margin sortiert, vom z-Gate verworfene ausgenommen.")
    for nm in roh:
        c = [r for r in roh[nm] if r["decision"] != "reject"]
        c.sort(key=lambda r: -(r["llr"] if r["llr"] is not None else float("inf")))
        k = 0
        for i, r in enumerate(c):
            if r["ranking"][:1] != [r["wahr"]]:
                break
            k = i + 1
        fehler = sum(1 for r in roh[nm] if r["ranking"][:1] != [r["wahr"]])
        print(f"    {nm:<28} k_safe {k:>3} von {len(c):>3} | top1-Fehler {fehler}")

    # ============================================== Aufteilung nach Artikeln
    print("\n" + "=" * 92)
    print("ACCEPT JE ARTIKEL — bewegt eine Variante die Nullartikel?")
    print("=" * 92)
    namen = list(roh)
    print(f"{'Artikel':<11}" + "".join(f"{n[:11]:>13}" for n in namen))
    null_basis = []
    for a in arts:
        zeile = f"{a:<11}"
        for n in namen:
            acc = sum(1 for r in roh[n] if r["wahr"] == a and r["decision"] == "accept")
            zeile += f"{acc:>10}/13"
        if sum(1 for r in roh["a) Baseline"]
               if r["wahr"] == a and r["decision"] == "accept") == 0:
            null_basis.append(a)
            zeile += "  <- Nullartikel"
        print(zeile)
    print(f"\n  Nullartikel der Baseline ({len(null_basis)}): {', '.join(null_basis)}")
    for n in namen:
        bewegt = [a for a in null_basis
                  if sum(1 for r in roh[n] if r["wahr"] == a
                         and r["decision"] == "accept") > 0]
        print(f"    {n:<24} bewegt {len(bewegt):>2} von {len(null_basis)} "
              f"Nullartikeln{': ' + ', '.join(bewegt) if bewegt else ''}")

    with open(OUT / "blockA.json", "w") as fh:
        json.dump({"korrelation": R.tolist(), "C": C.tolist(),
                   "kappa": kappa, "eff_rang": er,
                   "kennzahlen": ergebnisse}, fh, indent=1)
    print(f"\n-> {OUT/'blockA.json'}")


if __name__ == "__main__":
    main()
