"""Block D8: Tiebreaker bei AMBIGUOUS.

Meldet das Scoring AMBIGUOUS, wird zwischen Platz 1 und Platz 2 separat
entschieden — nicht durch Umgewichtung aller Merkmale (das war Block B), sondern
durch Reduktion auf das EINE Merkmal, das dieses konkrete Paar am besten trennt.
Fisher-Ratio auf dem Paar, aber als SELEKTION statt als Gewichtung.

Der strukturelle Vorteil, der zu pruefen ist: bei nur zwei Kandidaten kann kein
Dritter nachruecken. Der Effekt, der w(s) in der Aggregation neutralisiert hat
(Bedraenger verdraengt, neuer rueckt nach), kann hier nicht auftreten.

Die Obergrenze fuer alles, was D8 leisten kann: wie oft ist der wahre Artikel
gar nicht unter den ersten beiden? Eine Kaskade ist unheilbar.

Kein Produktivcode. Aufruf:
    .venv/bin/python scripts/analyse_tiebreaker.py
"""
from __future__ import annotations

import math
import pickle
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import simulate_scoring as sim  # noqa: E402
from docodetect.calibration import load_calibration  # noqa: E402
from docodetect.config import load_config, sandbox_cfg  # noqa: E402
from docodetect.features import (ALL_FEATURES, SCALAR_FEATURES,  # noqa: E402
                                 height_corrected_scale)
from docodetect.matcher import (_feature_rows, _nominal_size_mm,  # noqa: E402
                                _sigma_floor)

WP = Path.home() / "Documents/tmp/2026-08-01-wprofil/profiles.pkl"
K = 101
SONDE = ("MESSER-5", "MESSER-7")


def resample_u(w):
    n = len(w)
    return np.interp(np.linspace(0, 1, K), (np.arange(n) + 0.5) / n, np.asarray(w, float))


def d_full(a, b):
    return float(np.sqrt(np.mean((a - b) ** 2)))


def profil_tabelle(arts, A, U):
    """(wahr, shot) -> {kandidat: (d, sigma)} fuer w(s), leave-one-out."""
    pv = {a: U[a].mean(axis=0) for a in U}
    sv = {a: float(np.sqrt(np.mean([d_full(u, pv[a]) ** 2 for u in U[a]]))) for a in U}
    tab = {}
    for a in A:
        if a not in U or len(U[a]) < 13:
            continue
        for i in range(len(U[a])):
            rest = np.delete(U[a], i, axis=0)
            p = rest.mean(axis=0)
            s = float(np.sqrt(np.mean([d_full(u, p) ** 2 for u in rest])))
            wm = U[a][i]
            tab[(a, i)] = {x: ((d_full(wm, p), s) if x == a
                               else (d_full(wm, pv[x]), sv[x]))
                           for x in (art.article_number for art in arts)
                           if x == a or x in pv}
    return tab


def rows_fuer(measured, arts, stats, cal, m, namen):
    """Merkmalszeilen der genannten Kandidaten (dieselbe Logik wie der Matcher)."""
    out = {}
    for art in arts:
        if art.article_number not in namen:
            continue
        nom = _nominal_size_mm(art)
        if nom is None:
            continue
        h = float(art.height_mm or 0.0)
        cd = height_corrected_scale(measured.circle_diameter_mm, h, cal.camera_height_mm)
        out[art.article_number] = _feature_rows(measured, stats.get(art.article_number),
                                                cd, abs(cd - nom), nom)
    return out


def tiebreak(rows2, namen, floors, n_merkmale, stats, w_proto=None, w_extra=None):
    """Selektion des Tiebreaker-Merkmals ueber die Trennschaerfe des PAARES —
    also aus den beiden Referenzen, NICHT aus der Messung.

    Wichtig: die Auswahl muss messungsunabhaengig sein. Wuerde man das Merkmal
    ueber |d_a - d_b| der aktuellen Messung waehlen und mit demselben Merkmal
    entscheiden, waere das Selektion auf dem Ergebnis — der Tiebreaker saehe
    immer gut aus, weil er sich das Merkmal aussucht, das ihm gerade recht gibt.
    Hier: Trennschaerfe = |Lage_a - Lage_b| / sigma_eff aus den Enrollment-
    Statistiken, entschieden wird danach ueber die z-Werte der Messung."""
    from docodetect.features import PROTO_FEATURES, _PROTO_SRC
    a, b = namen
    sa_st, sb_st = stats.get(a), stats.get(b)
    if sa_st is None or sb_st is None:
        return None, 0.0, []
    kand = []
    for f in list(ALL_FEATURES) + (["w_profile"] if w_extra else []):
        ra = rows2[a].get(f) if f != "w_profile" else w_extra.get(a)
        rb = rows2[b].get(f) if f != "w_profile" else w_extra.get(b)
        if ra is None or rb is None:
            continue
        if f == "w_profile":
            da, sa = ra
            db, sb = rb
            fl = 0.50
            if w_proto is None or a not in w_proto or b not in w_proto:
                continue
            trennung = d_full(w_proto[a], w_proto[b])       # Referenz gegen Referenz
        else:
            da, sa = ra[0], ra[1]
            db, sb = rb[0], rb[1]
            fl = _sigma_floor(f, floors)
            if f in SCALAR_FEATURES:
                ma, mb = sa_st.scalar_mean.get(f), sb_st.scalar_mean.get(f)
                if ma is None or mb is None:
                    continue
                trennung = abs(ma - mb)
            else:
                pa, pb = sa_st.proto.get(f), sb_st.proto.get(f)
                if not pa or not pb or len(pa) != len(pb):
                    continue
                trennung = _PROTO_SRC[f][1](pa, pb)          # Prototyp gegen Prototyp
        sea = math.sqrt(sa ** 2 + fl ** 2)
        seb = math.sqrt(sb ** 2 + fl ** 2)
        trenn = trennung / math.sqrt((sea ** 2 + seb ** 2) / 2)
        za, zb = da / sea, db / seb
        kand.append((trenn, f, -0.5 * za * za, -0.5 * zb * zb))
    if not kand:
        return None, 0.0, []
    kand.sort(key=lambda t: -t[0])
    top = kand[:n_merkmale]
    sa_ = sum(t[2] for t in top)
    sb_ = sum(t[3] for t in top)
    sieger = a if sa_ >= sb_ else b
    return sieger, abs(sa_ - sb_), [t[1] for t in top]


def main():
    cfg = sandbox_cfg(load_config(), sim.SANDBOX, verbose=False)
    cal = load_calibration(cfg)
    m0 = cfg["matching"]
    floors = m0["sigma_floors"]
    bestand = sim.lade_bestand(cfg)
    arts, feats, voll, loo = bestand
    A = sorted(loo)

    data = pickle.load(open(WP, "rb"))
    shots = data["shots"]
    U = {a: np.array([resample_u(x["w_mm"]) for x in shots[a] if x["w_mm"] is not None])
         for a in shots if any(x["w_mm"] is not None for x in shots[a])}
    ptab = profil_tabelle(arts, A, U)
    w_proto = {a: U[a].mean(axis=0) for a in U}

    varianten = {
        "Baseline (kein Tiebreak)": None,
        "D8 1 Merkmal": dict(n=1, w=False),
        "D8 2 Merkmale": dict(n=2, w=False),
        "D8 3 Merkmale": dict(n=3, w=False),
        "D8 1 Merkmal + w(s)": dict(n=1, w=True),
        "D8 2 Merkmale + w(s)": dict(n=2, w=True),
        "D8 3 Merkmale + w(s)": dict(n=3, w=True),
    }

    # Grundlauf einmal, danach nur noch die AMBIGUOUS-Faelle nachbehandeln
    base = sim.lauf(bestand, cal, sim.variante_cfg(m0), "mean")
    idx = {(r["wahr"], r["shot"]): r for r in base}

    print("=" * 100)
    print("OBERGRENZE: wie oft ist der wahre Artikel gar nicht unter den ersten zwei?")
    print("=" * 100)
    amb = [r for r in base if r["decision"] == "ambiguous"]
    nicht_top2 = [r for r in amb if r["wahr"] not in r["ranking"][:2]]
    top1 = [r for r in amb if r["ranking"][:1] == [r["wahr"]]]
    top2 = [r for r in amb if len(r["ranking"]) > 1 and r["ranking"][1] == r["wahr"]]
    print(f"  AMBIGUOUS gesamt: {len(amb)}")
    print(f"    wahrer Artikel auf Platz 1: {len(top1)}")
    print(f"    wahrer Artikel auf Platz 2: {len(top2)}")
    print(f"    wahrer Artikel NICHT unter den ersten zwei: {len(nicht_top2)}"
          f"  <- unheilbar fuer jede Kaskade")
    print(f"  -> Obergrenze fuer D8: {len(amb) - len(nicht_top2)} von {len(amb)} "
          f"AMBIGUOUS ({(len(amb)-len(nicht_top2))/len(amb)*100:.0f} %)")

    print("\n" + "=" * 100)
    print("D8) TIEBREAKER — Aufloesung der AMBIGUOUS-Faelle")
    print("=" * 100)
    print(f"{'Variante':<24}{'Schwelle':>9}{'geloest':>9}{'korrekt':>9}"
          f"{'FALSCH':>8}{'offen':>7}{'ACCEPT ges.':>12}{'Sonde M5/M7':>13}")
    for nm, cfgv in varianten.items():
        if cfgv is None:
            print(f"{nm:<24}{'—':>9}{0:>9}{0:>9}{0:>8}{len(amb):>7}"
                  f"{sum(1 for r in base if r['decision']=='accept'):>12}"
                  f"{'0/13 0/13':>13}")
            continue
        for schwelle in (0.0, 0.5, 1.0, 2.0, 5.0):
            ok = falsch = offen = 0
            sonde = {SONDE[0]: 0, SONDE[1]: 0}
            for r in amb:
                a, i = r["wahr"], r["shot"]
                namen = tuple(r["ranking"][:2])
                stats = {**voll, a: loo[a][i]}
                r2 = rows_fuer(feats[a][i], arts, stats, cal, m0, set(namen))
                if len(r2) < 2:
                    offen += 1
                    continue
                we = None
                if cfgv["w"]:
                    t = ptab.get((a, i), {})
                    we = {n: t[n] for n in namen if n in t}
                    if len(we) < 2:
                        we = None
                sieger, marge, _ = tiebreak(r2, namen, floors, cfgv["n"],
                                            stats, w_proto, we)
                if sieger is None or marge < schwelle:
                    offen += 1
                elif sieger == a:
                    ok += 1
                    if a in sonde:
                        sonde[a] += 1
                else:
                    falsch += 1
            acc_ges = sum(1 for r in base if r["decision"] == "accept") + ok
            flag = "  <== FALSCH" if falsch else ""
            print(f"{nm:<24}{schwelle:>9.1f}{ok+falsch:>9}{ok:>9}{falsch:>8}{offen:>7}"
                  f"{acc_ges:>12}{f'{sonde[SONDE[0]]}/13 {sonde[SONDE[1]]}/13':>13}{flag}")

    print("\n" + "=" * 100)
    print("STRUKTURELLER VORTEIL: kann ein Dritter nachruecken?")
    print("=" * 100)
    print("  Der Tiebreak sieht per Konstruktion nur zwei Kandidaten. Ein dritter")
    print("  Artikel kann weder Platz 2 uebernehmen noch Posterior-Masse ziehen.")
    print("  Gegenprobe an der Sonde: in der Aggregation verdraengte w(s) den")
    print("  Bedraenger MESSER-7 aus Platz 2 und ein anderer rueckte nach.")
    for a in SONDE:
        rs = [r for r in base if r["wahr"] == a]
        p2 = {}
        for r in rs:
            if len(r["ranking"]) > 1:
                p2[r["ranking"][1]] = p2.get(r["ranking"][1], 0) + 1
        print(f"    {a}: Platz 2 in der Baseline = {p2}")


if __name__ == "__main__":
    main()
