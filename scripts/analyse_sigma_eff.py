"""Block D: sigma_eff selbst als Stellgroesse.

sigma_eff wird pro Kandidat aus dessen eigener Enrollment-Streuung gebildet.
Formal die korrekte Likelihood — betrieblich macht es einen Kandidaten mit
weiter Verteilung strukturell schwer ausschliessbar. D greift nicht die
Aggregation, die Gewichte oder die Schwellen an, sondern die Konstruktion von
sigma_eff.

D0  robuste sigma-Schaetzung (Median/MAD statt Mittel/Std)   [Messpfad!]
D1  Deckel relativ zum Median ueber alle Artikel
D2  symmetrisiertes sigma ueber das Kandidatenset            [keine Likelihood]
D3  Deckel relativ zum sigma_floor
D4  Merkmal je Kandidat abschalten statt kappen
D5  Kombinationen mit dem B2-Nachschlag

Kein Produktivcode. Aufruf:
    .venv/bin/python scripts/analyse_sigma_eff.py
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import simulate_scoring as sim  # noqa: E402
from docodetect.calibration import load_calibration  # noqa: E402
from docodetect.config import load_config, sandbox_cfg  # noqa: E402
from docodetect.features import (ALL_FEATURES, PROTO_FEATURES,  # noqa: E402
                                 SCALAR_FEATURES, EnrollmentStats, _PROTO_SRC,
                                 compute_enrollment_stats, scalar_value)
from docodetect.matcher import _sigma_floor  # noqa: E402

OUT = Path.home() / "Documents/tmp/2026-08-01-blockD"
SONDE = ("MESSER-5", "MESSER-7")
MAD_K = 1.4826


def robuste_stats(feats_list) -> EnrollmentStats:
    """D0: Median statt Mittelwert, MAD*1.4826 statt Standardabweichung.

    Fuer die fuenf Prototyp-Merkmale ist der robuste Gegenpart nicht der MAD
    der Distanzen (die messen Streuung UM den Median, nicht die Skala der
    Distanz), sondern 1.4826 * median(d): unter dem gefalteten Normalmodell,
    das die Likelihood fuer diese Merkmale ohnehin unterstellt, gilt
    median(d) = 0.6745 * sigma, also sigma = 1.4826 * median(d)."""
    st = EnrollmentStats(n_shots=len(feats_list))
    for name in SCALAR_FEATURES:
        vals = [v for f in feats_list if (v := scalar_value(f, name)) is not None]
        if not vals:
            continue
        x = np.asarray(vals, dtype=float)
        med = float(np.median(x))
        st.scalar_mean[name] = med
        st.scalar_std[name] = (MAD_K * float(np.median(np.abs(x - med)))
                               if len(x) > 1 else 0.0)
    for key, (attr, dist_fn) in _PROTO_SRC.items():
        vecs = [v for f in feats_list if (v := getattr(f, attr, None))]
        if not vecs or len({len(v) for v in vecs}) != 1:
            continue
        arr = np.asarray(vecs, dtype=float)
        proto = np.median(arr, axis=0)
        st.proto[key] = proto.tolist()
        if len(vecs) < 2:
            st.proto_std[key] = 0.0
            continue
        d = [dist_fn(v, st.proto[key]) for v in vecs]
        st.proto_std[key] = MAD_K * float(np.median(d))
    for key in ("hist_center", "hist_rim"):
        if key in st.proto:
            ssum = sum(st.proto[key])
            if ssum > 0:
                st.proto[key] = [v / ssum for v in st.proto[key]]
    return st


def bestand_mit(cfg, schaetzer):
    """lade_bestand, aber mit frei waehlbarem Statistik-Schaetzer."""
    from docodetect.database import Database
    db = Database(cfg)
    try:
        arts = [a for a in db.all_articles()
                if a.article_number not in sim.AUSGESCHLOSSEN]
        feats = {a.article_number: db.references_for(a.article_number) for a in arts}
    finally:
        db.close()
    voll = {a: schaetzer(f) for a, f in feats.items() if f}
    loo = {a: [schaetzer([x for j, x in enumerate(f) if j != i])
               for i in range(len(f))]
           for a, f in feats.items() if len(f) >= 13}
    return arts, feats, voll, loo


def sig_of(st, f):
    return (st.scalar_std.get(f, 0.0) if f in SCALAR_FEATURES
            else st.proto_std.get(f, 0.0))


def k_safe(res):
    c = [r for r in res if r["decision"] != "reject"]
    c.sort(key=lambda r: -(r["llr"] if r["llr"] is not None else float("inf")))
    k = 0
    for i, r in enumerate(c):
        if r["ranking"][:1] != [r["wahr"]]:
            break
        k = i + 1
    return k


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cfg = sandbox_cfg(load_config(), sim.SANDBOX, verbose=False)
    cal = load_calibration(cfg)
    m0 = cfg["matching"]
    floors = m0["sigma_floors"]

    b_klass = sim.lade_bestand(cfg)
    b_rob = bestand_mit(cfg, robuste_stats)
    A = sorted(b_klass[3])

    # ============================================================ D0 vorab
    print("=" * 100)
    print("D0-VORPRUEFUNG: was macht Median/MAD mit den Streuungen?")
    print("=" * 100)
    ueber_k = [(a, f) for a in A for f in ALL_FEATURES
               if sig_of(b_klass[2][a], f) / _sigma_floor(f, floors) > 1.0]
    ueber_r = [(a, f) for a in A for f in ALL_FEATURES
               if sig_of(b_rob[2][a], f) / _sigma_floor(f, floors) > 1.0]
    print(f"  Floor-Ueberschreitungen klassisch: {len(ueber_k)}   robust: {len(ueber_r)}")
    print(f"  {'Artikel':<11}{'Merkmal':<16}{'klassisch':>11}{'robust':>9}   Jackknife-Urteil")
    jack = {("GABEL-11", "solidity"): "Ausreisser", ("GABEL-12", "delta_e_center"): "Ausreisser",
            ("GABEL-14", "delta_e_center"): "Ausreisser", ("GABEL-9", "hist_center"): "Ausreisser",
            ("LOEFFEL-2", "hu_log"): "Ausreisser", ("MESSER-7", "circularity"): "Ausreisser",
            ("MESSER-7", "delta_e_center"): "Ausreisser"}
    for a, f in ueber_k:
        fl = _sigma_floor(f, floors)
        k = sig_of(b_klass[2][a], f) / fl
        r = sig_of(b_rob[2][a], f) / fl
        u = jack.get((a, f), "gleichmaessig breit")
        weg = " -> WEG" if r <= 1.0 else ""
        print(f"  {a:<11}{f:<16}{k:>11.2f}{r:>9.2f}   {u}{weg}")

    print("\n  PREIS: was macht Median/MAD bei Artikeln OHNE Ausreisser?")
    q = [sig_of(b_rob[2][a], f) / sig_of(b_klass[2][a], f)
         for a in A for f in ALL_FEATURES
         if (a, f) not in jack and sig_of(b_klass[2][a], f) > 0]
    q = np.array(q)
    print(f"    Verhaeltnis sigma_robust / sigma_klassisch ueber {len(q)} "
          f"(Artikel x Merkmal) ohne bekannten Ausreisser:")
    print(f"    Median {np.median(q):.3f} | p10 {np.percentile(q,10):.3f} | "
          f"p90 {np.percentile(q,90):.3f} | min {q.min():.3f} | max {q.max():.3f}")
    print(f"    Streuung des Schaetzers selbst (IQR/Median): "
          f"{(np.percentile(q,75)-np.percentile(q,25))/np.median(q):.3f}")

    # ============================================================ Laeufe
    med_klass = {f: float(np.median([sig_of(b_klass[2][a], f) for a in A]))
                 for f in ALL_FEATURES}
    NS = {"alpha": 8.0, "reihenfolge": True}
    faelle = [
        ("a) Baseline", b_klass, None, None),
        ("D0) robust Median/MAD", b_rob, None, None),
        ("D1) Deckel 1.5x Median", b_klass, {"art": "cap_median", "faktor": 1.5, "median": med_klass}, None),
        ("D1) Deckel 2x Median", b_klass, {"art": "cap_median", "faktor": 2.0, "median": med_klass}, None),
        ("D1) Deckel 3x Median", b_klass, {"art": "cap_median", "faktor": 3.0, "median": med_klass}, None),
        ("D1) Deckel 5x Median", b_klass, {"art": "cap_median", "faktor": 5.0, "median": med_klass}, None),
        ("D2) sym median", b_klass, {"art": "sym", "modus": "median"}, None),
        ("D2) sym pooled", b_klass, {"art": "sym", "modus": "pool"}, None),
        ("D2) sym max", b_klass, {"art": "sym", "modus": "max"}, None),
        ("D3) cap 0.5x Floor", b_klass, {"art": "cap_floor", "k": 0.5}, None),
        ("D3) cap 1x Floor", b_klass, {"art": "cap_floor", "k": 1.0}, None),
        ("D3) cap 2x Floor", b_klass, {"art": "cap_floor", "k": 2.0}, None),
        ("D4) aus ab 1x Floor", b_klass, {"art": "aus", "k": 1.0}, None),
        ("D4) aus ab 2x Floor", b_klass, {"art": "aus", "k": 2.0}, None),
        ("D5) D0 + D3(1x)", b_rob, {"art": "cap_floor", "k": 1.0}, None),
        ("D5) D0 + B2", b_rob, None, NS),
        ("D5) D3(1x) + B2", b_klass, {"art": "cap_floor", "k": 1.0}, NS),
        ("D5) D0 + D3(1x) + B2", b_rob, {"art": "cap_floor", "k": 1.0}, NS),
    ]

    roh, kenn = {}, {}
    print("\n" + "=" * 100)
    print("D) KENNZAHLEN")
    print("=" * 100)
    print(sim.KOPF)
    for nm, best, regel, ns in faelle:
        res = sim.lauf(best, cal, sim.variante_cfg(m0), "mean", None, ns, regel)
        roh[nm] = res
        kenn[nm] = sim.kennzahlen(res, float(m0["min_llr_margin"]),
                                  float(m0["max_z_accept"]))
        print(sim.zeile(nm, kenn[nm]))

    print(f"\n  {'Variante':<26}{'k_safe':>8}{'top1-Fehler':>13}{'Merkmale/Kand.':>16}")
    for nm in roh:
        nf = [n for r in roh[nm] for n in r.get("n_feats", [])]
        fehl = sum(1 for r in roh[nm] if r["ranking"][:1] != [r["wahr"]])
        spanne = f"{min(nf)}-{max(nf)}" if nf else "-"
        print(f"  {nm:<26}{k_safe(roh[nm]):>8}{fehl:>13}{spanne:>16}")

    # ==================================================== Preis des Deckels
    print("\n" + "=" * 100)
    print("PREIS DES DECKELS: rutschen korrekte Identifikationen Richtung z-Gate?")
    print("  max|z| des Siegers, nur Faelle mit KORREKTEM Top-1.")
    print("=" * 100)
    base_z = {(r["wahr"], r["shot"]): r["max_z"] for r in roh["a) Baseline"]
              if r["ranking"][:1] == [r["wahr"]] and r["max_z"] is not None}
    print(f"  {'Variante':<26}{'Median':>8}{'p90':>8}{'p99':>8}{'max':>8}"
          f"{'> 3.5':>7}{'gestiegen':>11}{'Median-Anstieg':>15}")
    for nm in roh:
        zs = {(r["wahr"], r["shot"]): r["max_z"] for r in roh[nm]
              if r["ranking"][:1] == [r["wahr"]] and r["max_z"] is not None}
        gem = [k for k in zs if k in base_z]
        v = np.array([zs[k] for k in gem])
        d = np.array([zs[k] - base_z[k] for k in gem])
        print(f"  {nm:<26}{np.median(v):>8.2f}{np.percentile(v,90):>8.2f}"
              f"{np.percentile(v,99):>8.2f}{v.max():>8.2f}{int((v>3.5).sum()):>7}"
              f"{int((d>1e-9).sum()):>11}{np.median(d):>15.3f}")

    # =========================================================== Gegenprobe
    print("\n" + "=" * 100)
    print("GEGENPROBE auf JEDE Variante: verkleidete Schwellensenkung?")
    print("=" * 100)
    from scipy.stats import spearmanr
    lb = np.array([r["llr"] if r["llr"] is not None else np.inf
                   for r in roh["a) Baseline"]])
    for nm in roh:
        if nm == "a) Baseline":
            continue
        lk = np.array([r["llr"] if r["llr"] is not None else np.inf for r in roh[nm]])
        e = np.isfinite(lb) & np.isfinite(lk)
        rho = spearmanr(lb[e], lk[e]).statistic
        n_acc = int((lk >= 2.0).sum())
        t = float(np.sort(lb)[::-1][n_acc - 1]) if 0 < n_acc <= len(lb) else float("nan")
        sk = {i for i in range(len(lk)) if lk[i] >= 2.0}
        sb = {i for i in range(len(lb)) if lb[i] >= t}
        ueb = len(sk & sb)
        anteil = f"{ueb/n_acc*100:.0f} %" if n_acc else "-"
        print(f"  {nm:<26} rho {rho:+.4f} | ACCEPT {n_acc:>3} | "
              f"aequiv. Schwelle {t:>6.3f} | Ueberlappung {ueb}/{n_acc} ({anteil})")

    # ================================================ Sonde + Nullartikel
    print("\n" + "=" * 100)
    print("SONDE MESSER-5 / MESSER-7 — Symmetrie ist das Erfolgskriterium")
    print("=" * 100)
    print(f"  {'Variante':<26}{'M5 ACC':>8}{'M7 ACC':>8}{'M5 Margin':>11}"
          f"{'M7 Margin':>11}{'Asymmetrie':>12}")
    for nm in roh:
        z = {}
        for a in SONDE:
            rs = [r for r in roh[nm] if r["wahr"] == a]
            z[a] = (sum(1 for r in rs if r["decision"] == "accept"),
                    float(np.median([r["llr"] for r in rs if r["llr"] is not None])))
        m5, m7 = z[SONDE[0]], z[SONDE[1]]
        asym = max(m5[1], m7[1]) / min(m5[1], m7[1]) if min(m5[1], m7[1]) > 0 else float("inf")
        print(f"  {nm:<26}{m5[0]:>7}/13{m7[0]:>7}/13{m5[1]:>11.3f}{m7[1]:>11.3f}"
              f"{asym:>11.1f}x")

    print("\n" + "=" * 100)
    print("NULLARTIKEL (8) und beruehrte Floor-Ueberschreiter (9 Artikel)")
    print("=" * 100)
    null = [a for a in A if sum(1 for r in roh["a) Baseline"]
                                if r["wahr"] == a and r["decision"] == "accept") == 0]
    ueber_art = sorted({a for a, f in ueber_k})
    for nm in roh:
        bewegt = [a for a in null if sum(1 for r in roh[nm] if r["wahr"] == a
                                         and r["decision"] == "accept") > 0]
        print(f"  {nm:<26} Nullartikel bewegt {len(bewegt)}/{len(null)}"
              f"{': ' + ', '.join(bewegt) if bewegt else ''}")
    print(f"\n  Floor-Ueberschreiter ({len(ueber_art)}): {', '.join(ueber_art)}")

    with open(OUT / "blockD.json", "w") as fh:
        json.dump(kenn, fh, indent=1)
    print(f"\n-> {OUT/'blockD.json'}")


if __name__ == "__main__":
    main()
