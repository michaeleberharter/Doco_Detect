"""Offline-Simulation von Scoring-Varianten per Leave-one-out (Phase 1).

Kein Messpfad. Das Skript liest ausschliesslich die Sandbox-DB und rechnet
Entscheidungen nach; es schreibt weder DB noch Config noch Korpus. Die
Messlogik wird NICHT dupliziert: der Vorfilter und die Merkmalszeilen kommen
ueber die privaten Helfer aus `matcher.py` (`_nominal_size_mm`,
`_feature_rows`, `_sigma_floor`) — dasselbe Muster, mit dem
`enrollment_sheet.py` aus `features.py` importiert.

Verfahren: jeder der 195 Referenz-Shots der 15 voll eingelernten Artikel wird
einmal als Testmessung gegen Enrollment-Statistiken aus den uebrigen 12 Shots
desselben Artikels und die vollen Statistiken aller anderen Artikel gescort.
Der gespeicherte `reference_stats`-Cache wird dabei nie benutzt; alle
Statistiken werden ueber `features.compute_enrollment_stats` neu gerechnet
(geprueft: bit-identisch zum Cache, wenn ueber alle 13 Shots gerechnet).

Aufruf:
    .venv/bin/python scripts/simulate_scoring.py [--out DIR]
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.calibration import load_calibration  # noqa: E402
from docodetect.config import load_config, sandbox_cfg
from docodetect.database import Database
from docodetect.features import ALL_FEATURES, SCALAR_FEATURES, compute_enrollment_stats
from docodetect.matcher import (DECISION_ACCEPT, DECISION_AMBIGUOUS,
                                DECISION_REJECT, _feature_rows,
                                _nominal_size_mm, _sigma_floor)
from docodetect.features import height_corrected_scale

SANDBOX = "neuenroll-2026-08"

# MESSER-2 UND MESSER-6 sind DUPLIKATE von MESSER-5 — am 2026-08-01 am
# physischen Objekt festgestellt (zwei getrennte Pruefungen). Die drei
# Datenbankeintraege beschreiben dasselbe Besteckteil; der Profil-Scan hatte
# sie mit d/sigma 0.92 / 1.20 / 1.53 als Cluster ausgewiesen, klar abgesetzt
# vom naechsten Paar bei 2.18.
# Beide werden komplett ausgeschlossen, MESSER-5 bleibt als der eine echte
# Artikel. Umetikettieren waere falsch: die MESSER-2-Aufnahme ordnet sich auch
# ohne MESSER-2 nicht MESSER-5 zu, sondern MESSER-7.
# Siehe docs/2026-08-01-fixpunkt-test-scoring.md, Nachtraege.
AUSGESCHLOSSEN = ("MESSER-2", "MESSER-6")

# Nach Wegfall BEIDER Duplikate gibt es in diesem Bestand kein entartetes Paar
# mehr — der vermeintliche Dreier-Cluster war vollstaendig ein Datenfehler.
ENTARTET = ()

# --- Aggregationsformen ------------------------------------------------------
# mean              log_score = Sum w_eff*L / Sum w_eff        (heutiger Code)
# sum_weighted      log_score = Sum w_eff*L                    (ohne /wsum)
# sum_unweighted    log_score = Sum L                          (jedes Merkmal 1)
# sum_fisher        log_score = Sum w_roh*L, w_roh NICHT renormiert nach der
#                   Fisher-Adaption — die Skala waechst, wenn das Kandidatenset
#                   trennscharfe Merkmale hat.
AGGREGATIONEN = ("mean", "sum_weighted", "sum_unweighted", "sum_fisher")

# Block A: Mahalanobis. MAHA_C ist die 8x8-Korrelationsmatrix der z-Vektoren
# (Modulglobale, von scripts/analyse_merkmalskorrelation.py gesetzt). Die
# Aggregation "maha" rechnet  log_score = -0.5 * z^T D^0.5 C^-1 D^0.5 z  mit
# D = diag(w_eff). Fuer C = Identitaet ist das EXAKT die heutige Baseline —
# die Variante ist eine strikte Verallgemeinerung, kein anderes Verfahren.
MAHA_C = None          # dict {(f_i, f_j): rho} oder None
MAHA_CINV = None       # vorberechnete Inverse als dict-of-dict


def lade_bestand(cfg):
    """-> (artikel, feats_je_artikel, stats_voll, stats_loo)"""
    db = Database(cfg)
    try:
        arts = [a for a in db.all_articles()
                if a.article_number not in AUSGESCHLOSSEN]
        feats = {a.article_number: db.references_for(a.article_number) for a in arts}
    finally:
        db.close()
    stats_voll = {a: compute_enrollment_stats(f) for a, f in feats.items() if f}
    stats_loo = {}
    for a, f in feats.items():
        if len(f) >= 13:
            stats_loo[a] = [compute_enrollment_stats([x for j, x in enumerate(f) if j != i])
                            for i in range(len(f))]
    return arts, feats, stats_voll, stats_loo


FARB_MERKMALE = ("delta_e_center", "delta_e_rim", "hist_center", "hist_rim")


def score_einmal(measured, arts, stats, cal, m, aggregation, merkmale=None,
                 nachschlag=None, sigma_regel=None, zusatz=None):
    """Eine Identifikation. `stats` = {artikelnummer: EnrollmentStats}.
    `m` = cfg['matching'] (bereits variantenspezifisch veraendert).
    `merkmale` = aktive Merkmalsliste (None = alle acht). Das Weglassen von
    Merkmalen ist NICHT dasselbe wie Gewicht 0: bei `sum_unweighted` gibt es
    keine Gewichte, dort wirkt nur das Weglassen.

    `sigma_regel` (Block D) = None | dict, greift in die Konstruktion von
    sigma_enroll ein, BEVOR sigma_eff gebildet wird:
      {"art": "cap_median", "faktor": f, "median": {merkmal: wert}}
          kein Kandidat breiter als f * Median ueber alle Artikel
      {"art": "cap_floor", "k": k}      sigma_enroll <= k * sigma_floor
      {"art": "sym", "modus": "median"|"pool"|"max"}
          alle Kandidaten eines Sets teilen dasselbe sigma je Merkmal
      {"art": "aus", "k": k}
          Merkmal faellt fuer DIESEN Kandidaten aus, wenn sigma > k * floor
          (aendert die Merkmalszahl je Kandidat — siehe Bericht)

    `zusatz` (Block D7) = None | {"name", "gewicht", "floor",
    "tabelle": {kandidat: (distanz, sigma_enroll)}} — haengt EIN zusaetzliches
    Merkmal an, fuer die Kandidaten, die in der Tabelle stehen.

    `nachschlag` (Block B) = None | {"alpha": float, "reihenfolge": bool}.
    Gesetzt, werden nach dem globalen Durchgang Platz 1 und 2 mit Gewichten aus
    der Fisher-Ratio ueber GENAU DIESES PAAR neu bewertet. `reihenfolge=False`
    laesst die Reihenfolge des globalen Durchgangs unangetastet und aendert nur
    den Abstand — damit ist die Variante per Konstruktion eine reine
    Skalenoperation und muss sich an der Schwellen-Gegenprobe messen."""
    aktiv = tuple(merkmale) if merkmale else ALL_FEATURES
    tol_mm = float(m["diameter_tolerance_mm"])
    area_tol = float(m["area_tolerance_pct"]) / 100.0
    floors = m["sigma_floors"]
    alpha = float(m.get("adaptive_weight_alpha", 2.0))
    max_z_accept = float(m.get("max_z_accept", 3.5))
    min_llr = float(m.get("min_llr_margin", 2.0))

    w_cfg = dict(m["feature_weights"])
    if zusatz is not None:
        aktiv = tuple(aktiv) + (zusatz["name"],)
        w_cfg[zusatz["name"]] = float(zusatz["gewicht"])
    w_sum = sum(float(w_cfg.get(f, 0.0)) for f in aktiv)
    w_global = {f: float(w_cfg.get(f, 0.0)) / w_sum for f in aktiv}

    def _floor(f):
        return (float(zusatz["floor"]) if zusatz is not None and f == zusatz["name"]
                else _sigma_floor(f, floors))

    # ---- Vorfilter (Logik 1:1 wie matcher.match) ----
    prelim = []
    for art in arts:
        nominal = _nominal_size_mm(art)
        if nominal is None:
            continue
        h = float(art.height_mm or 0.0)
        corrected_d = height_corrected_scale(measured.circle_diameter_mm, h,
                                             cal.camera_height_mm)
        geo_err = abs(corrected_d - nominal)
        if geo_err > tol_mm:
            continue
        corr = (cal.camera_height_mm - min(h, 0.8 * cal.camera_height_mm)) / cal.camera_height_mm
        corrected_area = measured.area_mm2 * corr * corr
        nominal_area = np.pi * (nominal / 2.0) ** 2
        area_rel = abs(corrected_area - nominal_area) / nominal_area
        if art.diameter_mm and area_rel > area_tol * 2:
            continue
        st = stats.get(art.article_number)
        rows = _feature_rows(measured, st, corrected_d, geo_err, nominal)
        rows = {k: v for k, v in rows.items() if k in aktiv}
        if zusatz is not None and st is not None:
            zt = zusatz["tabelle"].get(art.article_number)
            if zt is not None:
                rows[zusatz["name"]] = (zt[0], zt[1], None, None)
        if sigma_regel is not None:
            art_ = sigma_regel["art"]
            neu = {}
            for f, (d, se, mv, ref) in rows.items():
                fl = _sigma_floor(f, floors)
                if art_ == "cap_median":
                    se = min(se, sigma_regel["faktor"] * sigma_regel["median"][f])
                elif art_ == "cap_floor":
                    se = min(se, sigma_regel["k"] * fl)
                elif art_ == "aus" and se > sigma_regel["k"] * fl:
                    continue          # Merkmal faellt fuer diesen Kandidaten aus
                neu[f] = (d, se, mv, ref)
            rows = neu
        prelim.append((art, st, rows))

    if not prelim:
        return {"decision": DECISION_REJECT, "ranking": [], "llr": None,
                "max_z": None, "n_cand": 0, "n_feats": [], "getauscht": False}

    # D2: symmetrisiertes sigma — erst moeglich, wenn das Kandidatenset steht.
    # Das ist KEINE gueltige Likelihood mehr (siehe Bericht): der Nenner haengt
    # dann nicht mehr am Modell des jeweiligen Kandidaten.
    if sigma_regel is not None and sigma_regel["art"] == "sym":
        modus = sigma_regel.get("modus", "median")
        for f in aktiv:
            ses = [rows[f][1] for (_, _, rows) in prelim if f in rows]
            if not ses:
                continue
            g = (float(np.median(ses)) if modus == "median"
                 else float(np.sqrt(np.mean(np.square(ses)))) if modus == "pool"
                 else float(max(ses)))
            for (_, _, rows) in prelim:
                if f in rows:
                    d, _se, mv, ref = rows[f]
                    rows[f] = (d, g, mv, ref)

    # ---- Fisher-adaptive Gewichte (1:1 wie matcher.match) ----
    w_eff = dict(w_global)
    w_roh = dict(w_global)
    if len(prelim) >= 2 and alpha > 0:
        fisher = {}
        for f in aktiv:
            locs, sig2 = [], []
            for (_, _, rows) in prelim:
                row = rows.get(f)
                if row is None:
                    continue
                dist, s_en, _, ref = row
                locs.append(ref if f in SCALAR_FEATURES and ref is not None else dist)
                sig2.append(s_en ** 2 + _floor(f) ** 2)
            if len(locs) >= 2 and np.mean(sig2) > 0:
                fisher[f] = float(np.var(locs) / np.mean(sig2))
        total = sum(fisher.values())
        if total > 0:
            dn = {f: v / total for f, v in fisher.items()}
            w_roh = {f: w_global[f] * (1.0 + alpha * dn.get(f, 0.0)) for f in w_global}
            s = sum(w_roh.values())
            w_eff = {f: v / s for f, v in w_roh.items()}

    # ---- Scoring ----
    # Die Rundung auf 4 Stellen ist NICHT kosmetisch: matcher.match rundet
    # `weighted` je Merkmal und summiert die gerundeten Werte zum log_score,
    # und max_abs_z entsteht aus dem gerundeten z. Beides wird hier
    # nachgebildet, sonst ist der Abgleich in pruefe_gegen_matcher nicht exakt.
    cands = []
    for (art, st, rows) in prelim:
        wsum = sum(w_eff[f] for f in rows if f in w_eff)
        beitraege, zs = [], []
        for f in aktiv:
            row = rows.get(f)
            if row is None:
                continue
            dist, s_en, _, _ = row
            sigma_eff = math.sqrt(s_en ** 2 + _floor(f) ** 2)
            if sigma_eff <= 0:
                raise ZeroDivisionError(
                    f"sigma_eff=0 bei {f} ({art.article_number}): "
                    "sigma_enroll=0 UND sigma_floor=0. Das Merkmal traegt "
                    "keine Information; z=0 zu setzen wuerde einen "
                    "1-Shot-Stoerer zum perfekten Treffer machen.")
            z = dist / sigma_eff
            L = -0.5 * z * z
            if aggregation == "mean":
                b = (w_eff[f] * L / wsum) if wsum > 0 else 0.0
            elif aggregation == "sum_weighted":
                b = w_eff[f] * L
            elif aggregation == "sum_unweighted":
                b = L
            elif aggregation == "sum_fisher":
                b = w_roh[f] * L
            elif aggregation == "maha":
                b = 0.0        # unten geschlossen ueber den ganzen Vektor
            else:
                raise ValueError(aggregation)
            beitraege.append(round(b, 4))
            zs.append(round(z, 4))
        if aggregation == "maha":
            import numpy as _np
            fs = [f for f in aktiv if rows.get(f) is not None]
            zv = _np.array([zs[i] for i in range(len(fs))], dtype=float)
            d = _np.sqrt(_np.array([w_eff[f] for f in fs], dtype=float))
            cinv = _np.array([[MAHA_CINV[a_][b_] for b_ in fs] for a_ in fs])
            q = float(zv @ (_np.outer(d, d) * cinv) @ zv)
            beitraege = [round(-0.5 * q, 4)]
        cands.append({"article": art.article_number,
                      "log_score": round(sum(beitraege), 4),
                      "max_abs_z": round(max((abs(z) for z in zs), default=0.0), 4),
                      "has_refs": st is not None, "n_feats": len(rows)})

    cands.sort(key=lambda c: -c["log_score"])
    best = cands[0]
    llr = (round(cands[0]["log_score"] - cands[1]["log_score"], 4)
           if len(cands) > 1 else None)
    if best["max_abs_z"] > max_z_accept:
        dec = DECISION_REJECT
    elif (llr is None or llr >= min_llr) and best["has_refs"]:
        dec = DECISION_ACCEPT
    else:
        dec = DECISION_AMBIGUOUS
    getauscht = False
    if nachschlag is not None and len(cands) >= 2:
        a_alt = cands[0]["article"]
        top = [c for c in cands[:2]]
        namen = [c["article"] for c in top]
        rows_top = {art.article_number: rows for (art, _st, rows) in prelim
                    if art.article_number in namen}
        al = float(nachschlag.get("alpha", alpha))
        fisher2 = {}
        for f in aktiv:
            locs, sig2 = [], []
            for n_ in namen:
                row = rows_top[n_].get(f)
                if row is None:
                    continue
                dist, s_en, _, ref = row
                locs.append(ref if f in SCALAR_FEATURES and ref is not None else dist)
                sig2.append(s_en ** 2 + _floor(f) ** 2)
            if len(locs) >= 2 and np.mean(sig2) > 0:
                fisher2[f] = float(np.var(locs) / np.mean(sig2))
        tot2 = sum(fisher2.values())
        if tot2 > 0:
            dn2 = {f: v / tot2 for f, v in fisher2.items()}
            w2 = {f: w_global[f] * (1.0 + al * dn2.get(f, 0.0)) for f in w_global}
            sw = sum(w2.values())
            w2 = {f: v / sw for f, v in w2.items()}
            neu = []
            for c in top:
                rows = rows_top[c["article"]]
                wsum2 = sum(w2[f] for f in rows if f in w2)
                b2 = []
                for f in aktiv:
                    row = rows.get(f)
                    if row is None:
                        continue
                    dist, s_en, _, _ = row
                    se = math.sqrt(s_en ** 2 + _floor(f) ** 2)
                    z = dist / se
                    L = -0.5 * z * z
                    b2.append(round((w2[f] * L / wsum2) if wsum2 > 0 else 0.0, 4))
                neu.append(dict(c, log_score=round(sum(b2), 4)))
            if nachschlag.get("reihenfolge", True):
                neu.sort(key=lambda c: -c["log_score"])
            cands = neu + cands[2:]
            best = cands[0]
            llr = round(cands[0]["log_score"] - cands[1]["log_score"], 4)
            getauscht = cands[0]["article"] != a_alt
            if best["max_abs_z"] > max_z_accept:
                dec = DECISION_REJECT
            elif (llr is None or llr >= min_llr) and best["has_refs"]:
                dec = DECISION_ACCEPT
            else:
                dec = DECISION_AMBIGUOUS

    return {"decision": dec, "ranking": [c["article"] for c in cands],
            "llr": llr, "max_z": best["max_abs_z"], "n_cand": len(cands),
            "n_feats": [c["n_feats"] for c in cands], "getauscht": getauscht}


def lauf(bestand, cal, m, aggregation, merkmale=None, nachschlag=None,
         sigma_regel=None, zusatz_tab=None, zusatz_meta=None):
    """195 Leave-one-out-Identifikationen -> Liste von Ergebnissen."""
    arts, feats, stats_voll, stats_loo = bestand
    out = []
    for a in sorted(stats_loo):
        for i, measured in enumerate(feats[a]):
            stats = dict(stats_voll)
            stats[a] = stats_loo[a][i]          # nur der wahre Artikel wird ersetzt
            zu = None
            if zusatz_tab is not None:
                zu = dict(zusatz_meta, tabelle=zusatz_tab[(a, i)])
            r = score_einmal(measured, arts, stats, cal, m, aggregation,
                             merkmale, nachschlag, sigma_regel, zu)
            r["wahr"] = a
            r["shot"] = i
            out.append(r)
    return out


def kennzahlen(res, min_llr=2.0, max_z_accept=3.5):
    n = len(res)
    top1 = sum(r["ranking"][:1] == [r["wahr"]] for r in res)
    top3 = sum(r["wahr"] in r["ranking"][:3] for r in res)
    dec = {d: sum(r["decision"] == d for r in res)
           for d in (DECISION_ACCEPT, DECISION_AMBIGUOUS, DECISION_REJECT)}
    fa = sum(r["decision"] == DECISION_ACCEPT and r["ranking"][:1] != [r["wahr"]]
             for r in res)
    llr = np.array([r["llr"] for r in res if r["llr"] is not None], float)
    mz = np.array([r["max_z"] for r in res if r["max_z"] is not None], float)
    q = lambda a, p: float(np.percentile(a, p)) if len(a) else float("nan")
    return {
        "n": n, "top1": top1, "top3": top3,
        "accept": dec[DECISION_ACCEPT], "ambiguous": dec[DECISION_AMBIGUOUS],
        "reject": dec[DECISION_REJECT], "false_accept": fa,
        "llr_min": float(llr.min()) if len(llr) else float("nan"),
        "llr_p10": q(llr, 10), "llr_p25": q(llr, 25), "llr_med": q(llr, 50),
        "llr_p75": q(llr, 75), "llr_p90": q(llr, 90),
        "llr_max": float(llr.max()) if len(llr) else float("nan"),
        "llr_ge_min": int((llr >= min_llr).sum()),
        "mz_med": q(mz, 50), "mz_p90": q(mz, 90), "mz_p99": q(mz, 99),
        "mz_max": float(mz.max()) if len(mz) else float("nan"),
        "mz_ueber_gate": int((mz > max_z_accept).sum()),
        "setgroesse": float(np.mean([r["n_cand"] for r in res])),
    }


def variante_cfg(basis_m, *, farbe=1.0, floor=1.0, tol=None, temp=None):
    """Kopie von cfg['matching'] mit den Variantenknoepfen."""
    m = json.loads(json.dumps(basis_m))
    for f in ("delta_e_center", "delta_e_rim", "hist_center", "hist_rim"):
        m["feature_weights"][f] = float(basis_m["feature_weights"][f]) * farbe
    if sum(float(v) for v in m["feature_weights"].values()) <= 0:
        raise ValueError("alle Gewichte 0")
    for k in m["sigma_floors"]:
        m["sigma_floors"][k] = float(basis_m["sigma_floors"][k]) * floor
    if tol is not None:
        m["diameter_tolerance_mm"] = float(tol)
    if temp is not None:
        m["softmax_temperature"] = float(temp)
    return m


def zeile(name, k):
    return (f"{name:<34} {k['top1']:>3}/{k['n']:<3} {k['top3']:>3} "
            f"{k['accept']:>4} {k['ambiguous']:>5} {k['reject']:>4} "
            f"{k['false_accept']:>3} "
            f"{k['llr_p25']:>7.2f} {k['llr_med']:>7.2f} {k['llr_p75']:>8.2f} "
            f"{k['llr_ge_min']:>5} "
            f"{k['mz_med']:>6.2f} {k['mz_max']:>7.2f} {k['mz_ueber_gate']:>4} "
            f"{k['setgroesse']:>6.2f}")


KOPF = (f"{'Variante':<34} {'top1':>7} {'top3':>3} {'ACC':>4} {'AMBI':>5} "
        f"{'REJ':>4} {'FA':>3} {'llr25':>7} {'llrMed':>7} {'llr75':>8} "
        f"{'>=2.0':>5} {'zMed':>6} {'zMax':>7} {'z>G':>4} {'Set':>6}")


def pruefe_gegen_matcher(bestand, cal, cfg):
    """Der Simulator muss in der Aggregation 'mean' EXAKT das liefern, was
    matcher.match() liefert. Sonst ist keine Variante belastbar."""
    from docodetect.matcher import match

    arts, feats, stats_voll, stats_loo = bestand

    class _ShimDB:
        """Nur die zwei Methoden, die matcher.match() benutzt."""
        def __init__(self, arts, stats):
            self._arts, self._stats = arts, stats

        def all_articles(self):
            return self._arts

        def stats_for(self, article_number):
            return self._stats.get(article_number)

    worst_llr = worst_ls = 0.0
    n = 0
    for a in sorted(stats_loo):
        for i, measured in enumerate(feats[a]):
            stats = dict(stats_voll)
            stats[a] = stats_loo[a][i]
            echt = match(measured, _ShimDB(arts, stats), cal, cfg)
            sim = score_einmal(measured, arts, stats, cal, cfg["matching"], "mean")
            n += 1
            assert [c.article_number for c in echt.candidates] == sim["ranking"], \
                f"Ranking weicht ab: {a} shot {i}"
            if echt.llr_margin is not None and sim["llr"] is not None:
                worst_llr = max(worst_llr, abs(echt.llr_margin - sim["llr"]))
            worst_ls = max(worst_ls, abs(echt.max_z_winner - sim["max_z"]))
    return n, worst_llr, worst_ls


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path.home() / "Documents/tmp/2026-08-01-simulation"))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    cfg = sandbox_cfg(load_config(), SANDBOX, verbose=False)
    cal = load_calibration(cfg)
    basis_m = cfg["matching"]
    bestand = lade_bestand(cfg)
    print(f"Bestand: {len(bestand[0])} Artikel, "
          f"{sum(len(v) for v in bestand[3].values())} LOO-Zuschnitte")

    print("\n=== 0) Simulator gegen matcher.match() ===")
    n, dl, dz = pruefe_gegen_matcher(bestand, cal, cfg)
    print(f"  {n} Faelle, Ranking identisch, max |d llr| = {dl:.2e}, "
          f"max |d maxz| = {dz:.2e}")
    if max(dl, dz) > 1e-9:
        raise SystemExit("Simulator weicht ab — Abbruch, keine Variante belastbar.")
    print("  -> deckungsgleich; alle Varianten laufen auf dieser Basis.")

    ergebnisse = {}
    roh = {}
    OHNE_FARBE = tuple(f for f in ALL_FEATURES if f not in FARB_MERKMALE)

    def run(name, m, agg, merkmale=None):
        res = lauf(bestand, cal, m, agg, merkmale)
        args_k = (float(m["min_llr_margin"]), float(m["max_z_accept"]))
        ergebnisse[name] = {
            "agg": agg, "merkmale": list(merkmale or ALL_FEATURES),
            "gesamt": kennzahlen(res, *args_k),
            "entartet": (kennzahlen([r for r in res if r["wahr"] in ENTARTET], *args_k)
                         if ENTARTET else None),
            "rest": kennzahlen([r for r in res if r["wahr"] not in ENTARTET], *args_k),
        }
        roh[name] = res
        return res

    def block(titel, faelle):
        print(f"\n=== {titel} ===")
        print(KOPF)
        for nm, m, agg, mk in faelle:
            run(nm, m, agg, mk)
            print(zeile(nm, ergebnisse[nm]["gesamt"]))

    # ---------------------------------------------------------------- a) + b)
    block("a) Baseline und b) Aggregationsformen",
          [("a) Baseline" if agg == "mean" else f"b) {agg}",
            variante_cfg(basis_m), agg, None) for agg in AGGREGATIONEN])

    # ------------------------------------------------------------------- c)
    # Zwei Mechanismen, die NICHT dasselbe sind: Gewicht herunterziehen wirkt
    # nur auf gewichtete Aggregationen, Merkmal weglassen wirkt auf alle.
    block("c) Farbmerkmale abgewertet (Gewicht) bzw. entfernt (Merkmalssatz)",
          [(f"c) farbe-gewicht x{fa}", variante_cfg(basis_m, farbe=fa), "mean", None)
           for fa in (1.0, 0.5, 0.25, 0.0)]
          + [("c) farbe WEGGELASSEN", variante_cfg(basis_m), "mean", OHNE_FARBE)])

    # ------------------------------------------------------------------- d)
    # floor x0.0 ist strukturell ungueltig: 25 der 40 Artikel haben genau eine
    # Referenz, dort ist sigma_enroll = 0 fuer JEDES Merkmal. Mit Floor 0 waere
    # sigma_eff = 0 und z undefiniert; score_einmal bricht darum hart ab.
    block("d) sigma_floors skaliert (x0.0 ist ungueltig, siehe Kommentar)",
          [(f"d) floor x{fl}", variante_cfg(basis_m, floor=fl), "mean", None)
           for fl in (1.0, 0.75, 0.5, 0.25, 0.125)])

    block("e) diameter_tolerance_mm gesweept",
          [(f"e) tol {t}", variante_cfg(basis_m, tol=t), "mean", None)
           for t in (6.0, 5.0, 4.0, 3.0)])

    block("f) softmax_temperature gesweept",
          [(f"f) temp {t}", variante_cfg(basis_m, temp=t), "mean", None)
           for t in (0.5, 1.0, 2.0, 5.0)])

    # --------------------------------------------- b) ist es eine Schwelle?
    print("\n=== b-Kontrolle: ist sum_unweighted nur eine verschobene Schwelle? ===")
    base = roh["a) Baseline"]
    for kand in ("b) sum_weighted", "b) sum_unweighted", "b) sum_fisher"):
        lb = np.array([r["llr"] if r["llr"] is not None else np.inf for r in base])
        lk = np.array([r["llr"] if r["llr"] is not None else np.inf for r in roh[kand]])
        endlich = np.isfinite(lb) & np.isfinite(lk)
        from scipy.stats import spearmanr  # noqa: E402
        rho = spearmanr(lb[endlich], lk[endlich]).statistic
        n_acc = int((lk >= 2.0).sum())
        # Schwelle, die in der Baseline dieselbe ACCEPT-Zahl ergibt
        t_aequiv = float(np.sort(lb)[::-1][n_acc - 1]) if 0 < n_acc <= len(lb) else float("nan")
        set_k = {i for i in range(len(lk)) if lk[i] >= 2.0}
        set_b = {i for i in range(len(lb)) if lb[i] >= t_aequiv}
        gleich = len(set_k & set_b)
        print(f"  {kand:<18} Spearman rho(llr) = {rho:+.4f} | ACCEPT {n_acc:>3} | "
              f"aequivalente Baseline-Schwelle {t_aequiv:>6.3f} | "
              f"Mengen-Ueberlappung {gleich}/{n_acc}")

    # ------------------------------------------------------- Kombinationen
    print("\n=== KOMBINATIONEN (Pflicht) ===")
    print(KOPF)
    basis_acc = ergebnisse["a) Baseline"]["gesamt"]["accept"]
    kombis = itertools.product(("sum_unweighted", "sum_fisher", "mean"),
                               ((1.0, None), (0.25, None), (0.0, OHNE_FARBE)),
                               (1.0, 0.5, 0.25), (6.0, 4.0, 3.0))
    for agg, (farbe, mk), fl, tol in kombis:
        nm = f"{agg[:9]}|{'oF' if mk else f'F{farbe}'}|fl{fl}|t{tol}"
        run(nm, variante_cfg(basis_m, farbe=farbe, floor=fl, tol=tol), agg, mk)
        k = ergebnisse[nm]["gesamt"]
        if k["false_accept"] > 0 or k["accept"] > basis_acc:
            print(zeile(nm, k))
    print("  (nur Zeilen mit false_accept > 0 ODER mehr ACCEPT als die Baseline)")

    # ------------------------------------------------- entartetes Trio separat
    if not ENTARTET:
        print("\n=== Kein entarteter Artikel mehr im Bestand (beide Duplikate raus) ===")
    else:
        print("\n=== Entartete Artikel getrennt ausgewiesen ===")
    print(f"{'Variante':<34} {'ACC ent':>8} {'AMBI ent':>9} {'FA ent':>7} "
          f"{'llrMed ent':>11} | {'ACC rest':>9} {'AMBI rest':>10} {'FA rest':>8} "
          f"{'llrMed rest':>12}")
    for nm in ("a) Baseline", "b) sum_unweighted", "b) sum_fisher",
               "c) farbe WEGGELASSEN", "d) floor x0.5", "d) floor x0.25",
               "e) tol 4.0", "sum_unwei|F1.0|fl0.5|t6.0"):
        if nm not in ergebnisse or not ENTARTET:
            continue
        e, r = ergebnisse[nm]["entartet"], ergebnisse[nm]["rest"]
        print(f"{nm:<34} {e['accept']:>8} {e['ambiguous']:>9} {e['false_accept']:>7} "
              f"{e['llr_med']:>11.2f} | {r['accept']:>9} {r['ambiguous']:>10} "
              f"{r['false_accept']:>8} {r['llr_med']:>12.2f}")

    # --------------------------------------------------------- Betriebskurve
    # Aggregationen haben verschiedene Skalen; ein Vergleich bei fester
    # Schwelle 2.0 misst deshalb teils nur die Skala. Skalenfrei ist die Frage:
    # wie viele Faelle kann man akzeptieren, BEVOR der erste falsche dabei ist?
    print("\n=== BETRIEBSKURVE: maximale ACCEPT-Zahl ohne false_accept ===")
    print("    Faelle nach LLR-Margin absteigend sortiert; k = Anzahl akzeptierter")
    print("    Faelle. k_safe = groesstes k, bei dem noch kein falscher dabei ist.")
    print(f"{'Variante':<34} {'k_safe':>7} {'Anteil':>8} {'top1-Fehler':>12} "
          f"{'ACC@2.0':>8} {'FA@2.0':>7}")
    for nm in ("a) Baseline", "b) sum_weighted", "b) sum_fisher", "b) sum_unweighted",
               "c) farbe WEGGELASSEN", "d) floor x0.5", "d) floor x0.25",
               "d) floor x0.125", "e) tol 4.0",
               "sum_unwei|F1.0|fl0.5|t6.0", "sum_unwei|oF|fl0.5|t6.0"):
        if nm not in roh:
            continue
        res = roh[nm]
        paare = sorted(((r["llr"] if r["llr"] is not None else float("inf"),
                         r["ranking"][:1] == [r["wahr"]]) for r in res),
                       key=lambda t: -t[0])
        k_safe = 0
        for i, (_, ok) in enumerate(paare):
            if not ok:
                break
            k_safe = i + 1
        k = ergebnisse[nm]["gesamt"]
        print(f"{nm:<34} {k_safe:>7} {k_safe/len(res)*100:>7.1f}% "
              f"{len(res)-k['top1']:>12} {k['accept']:>8} {k['false_accept']:>7}")

    with open(out / "ergebnisse.json", "w") as fh:
        json.dump(ergebnisse, fh, indent=1)
    with open(out / "faelle.json", "w") as fh:
        json.dump({nm: [{"wahr": r["wahr"], "shot": r["shot"], "llr": r["llr"],
                         "max_z": r["max_z"], "n_cand": r["n_cand"],
                         "top1": r["ranking"][0] if r["ranking"] else None,
                         "decision": r["decision"]} for r in res]
                   for nm, res in roh.items()}, fh)
    print(f"\n-> {out/'ergebnisse.json'} ({len(ergebnisse)} Varianten)")
    print(f"-> {out/'faelle.json'} (Einzelfaelle je Variante)")


if __name__ == "__main__":
    main()
