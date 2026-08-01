"""Block B: Paarweises Scoring statt globalem.

Bei zwoelf Kandidaten lautet die Entscheidungsfrage nicht "wer passt am besten",
sondern "Platz 1 oder Platz 2". Die Fisher-Adaption laeuft heute ueber das ganze
Kandidatenset; hier wird sie auf genau das Spitzenpaar angewandt.

Geprueft werden drei Dinge, in dieser Reihenfolge:
  1. Aendert der Nachschlag die REIHENFOLGE oder nur den ABSTAND?
  2. Wenn er die Reihenfolge aendert: in welche Richtung (korrekt <-> falsch)?
  3. Ist der Gewinn eine verkleidete Schwellensenkung? (aequivalente
     Baseline-Schwelle + Mengenueberlappung, auf JEDE Variante angewandt)

Sonde: MESSER-5 gegen MESSER-7 — zwei echte Artikel, geometrisch 0,77 mm
auseinander, im Profil 12,47 sigma getrennt. MESSER-5 erreicht in der Baseline
0/13 ACCEPT. Wenn paarweises Scoring irgendwo wirkt, dann hier.

Kein Messpfad. Aufruf:
    .venv/bin/python scripts/analyse_paarweises_scoring.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import simulate_scoring as sim  # noqa: E402
from docodetect.calibration import load_calibration  # noqa: E402
from docodetect.config import load_config, sandbox_cfg  # noqa: E402

OUT = Path.home() / "Documents/tmp/2026-08-01-blockB"
SONDE = ("MESSER-5", "MESSER-7")


def k_safe(res):
    c = [r for r in res if r["decision"] != "reject"]
    c.sort(key=lambda r: -(r["llr"] if r["llr"] is not None else float("inf")))
    k = 0
    for i, r in enumerate(c):
        if r["ranking"][:1] != [r["wahr"]]:
            break
        k = i + 1
    return k, len(c)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cfg = sandbox_cfg(load_config(), sim.SANDBOX, verbose=False)
    cal = load_calibration(cfg)
    basis_m = cfg["matching"]
    bestand = sim.lade_bestand(cfg)
    print(f"Bestand: {len(bestand[0])} Artikel, "
          f"{sum(len(v) for v in bestand[3].values())} LOO-Faelle")

    def m_alpha(a):
        m = sim.variante_cfg(basis_m)
        m["adaptive_weight_alpha"] = float(a)
        return m

    faelle = [
        ("a) Baseline", sim.variante_cfg(basis_m), None),
        ("B1) Nachschlag a=2", sim.variante_cfg(basis_m),
         {"alpha": 2.0, "reihenfolge": True}),
        ("B2) Nachschlag a=8", sim.variante_cfg(basis_m),
         {"alpha": 8.0, "reihenfolge": True}),
        ("B3) Nachschlag a=32", sim.variante_cfg(basis_m),
         {"alpha": 32.0, "reihenfolge": True}),
        ("B4) Nachschlag a=8, Reihenfolge FIX", sim.variante_cfg(basis_m),
         {"alpha": 8.0, "reihenfolge": False}),
        ("B5) global alpha=8", m_alpha(8), None),
        ("B6) global alpha=32", m_alpha(32), None),
        ("B7) Nachschlag a=8 + floor x0.5",
         sim.variante_cfg(basis_m, floor=0.5), {"alpha": 8.0, "reihenfolge": True}),
    ]

    roh, kenn = {}, {}
    print("\n" + "=" * 100)
    print("B) KENNZAHLEN")
    print("=" * 100)
    print(sim.KOPF)
    for nm, m, ns in faelle:
        res = sim.lauf(bestand, cal, m, "mean", None, ns)
        roh[nm] = res
        kenn[nm] = sim.kennzahlen(res, float(m["min_llr_margin"]),
                                  float(m["max_z_accept"]))
        print(sim.zeile(nm, kenn[nm]))

    print("\n  k_safe (Pflichtkennzahl):")
    for nm in roh:
        k, n = k_safe(roh[nm])
        fehler = sum(1 for r in roh[nm] if r["ranking"][:1] != [r["wahr"]])
        print(f"    {nm:<36} k_safe {k:>3} von {n:>3} | top1-Fehler {fehler}")

    # ---------------------------------------------------------------- B2/B3
    print("\n" + "=" * 100)
    print("B-Kernfrage: aendert der Nachschlag die REIHENFOLGE oder nur den ABSTAND?")
    print("=" * 100)
    base = {(r["wahr"], r["shot"]): r for r in roh["a) Baseline"]}
    for nm in roh:
        if nm == "a) Baseline":
            continue
        tausch = [r for r in roh[nm] if r.get("getauscht")]
        k_f, f_k = 0, 0
        for r in tausch:
            b = base[(r["wahr"], r["shot"])]
            vorher_ok = b["ranking"][:1] == [b["wahr"]]
            nachher_ok = r["ranking"][:1] == [r["wahr"]]
            if vorher_ok and not nachher_ok:
                k_f += 1
            elif nachher_ok and not vorher_ok:
                f_k += 1
        print(f"  {nm:<36} Reihenfolge getauscht: {len(tausch):>3}/169  "
              f"(korrekt->falsch {k_f}, falsch->korrekt {f_k})")

    # ------------------------------------------------------------------ B4
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
        print(f"  {nm:<36} rho {rho:+.4f} | ACCEPT {n_acc:>3} | "
              f"aequiv. Schwelle {t:>6.3f} | Ueberlappung {ueb}/{n_acc}"
              f"{'  (= reine Skala)' if n_acc and ueb == n_acc else ''}")

    # --------------------------------------------------------------- Sonde
    print("\n" + "=" * 100)
    print(f"SONDE {SONDE[0]} gegen {SONDE[1]} — 26 Faelle, beide in der Baseline 0/13")
    print("=" * 100)
    print(f"{'Variante':<36} " + " ".join(f"{a:>10} ACC" for a in SONDE)
          + "   Margin-Median   Bedraenger ist der jeweils andere")
    for nm in roh:
        zeile = f"{nm:<36} "
        med = []
        for a in SONDE:
            rs = [r for r in roh[nm] if r["wahr"] == a]
            acc = sum(1 for r in rs if r["decision"] == "accept")
            zeile += f"{acc:>11}/13 "
            med += [r["llr"] for r in rs if r["llr"] is not None]
        gegen = sum(1 for a, b in (SONDE, SONDE[::-1])
                    for r in roh[nm] if r["wahr"] == a
                    and len(r["ranking"]) > 1 and r["ranking"][1] == b)
        print(zeile + f"  {np.median(med):>13.3f}   {gegen:>2}/26")

    # -------------------------------------------------------- Nullartikel
    print("\n" + "=" * 100)
    print("NULLARTIKEL: bewegt eine Variante die acht Artikel mit 0 ACCEPT?")
    print("=" * 100)
    arts = sorted({r["wahr"] for r in roh["a) Baseline"]})
    null = [a for a in arts
            if sum(1 for r in roh["a) Baseline"]
                   if r["wahr"] == a and r["decision"] == "accept") == 0]
    print(f"  Nullartikel der Baseline ({len(null)}): {', '.join(null)}")
    for nm in roh:
        bewegt = [a for a in null
                  if sum(1 for r in roh[nm] if r["wahr"] == a
                         and r["decision"] == "accept") > 0]
        print(f"    {nm:<36} bewegt {len(bewegt)}/{len(null)}"
              f"{': ' + ', '.join(bewegt) if bewegt else ''}")

    with open(OUT / "blockB.json", "w") as fh:
        json.dump({nm: kenn[nm] for nm in kenn}, fh, indent=1)
    print(f"\n-> {OUT/'blockB.json'}")


if __name__ == "__main__":
    main()
