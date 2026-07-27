#!/usr/bin/env python3
"""Korpus-Fidelitaets-Eingangstest.

Prueft, ob der HEUTIGE Stand (DB + config.yaml) die gespeicherten
Korpus-Reports reproduziert. Rechnet je Report `matcher.match` auf dem
gespeicherten `measured`-Block neu (Segmentierung ist deterministisch und
reproduziert `measured` exakt, siehe G3 – daher genuegt der measured-Block)
und vergleicht Entscheidung, Top-1 und llr_margin gegen den gespeicherten
Report.

READ-ONLY: oeffnet die DB nur lesend (match ruft ausschliesslich
all_articles/stats_for). Schreibt nichts, veraendert weder Reports noch
Quellbilder noch Goldens. NICHT Teil der Pipeline – reines Analyse-Werkzeug.

Ausgabe: exakt/abweichend, Delta-llr median/p90/max, Liste der abweichenden
Dateien. Exit 0 wenn alle exakt, sonst 1.

Aufruf:  python scripts/corpus_fidelity_check.py [--corpus DIR] [--tier N]
"""
from __future__ import annotations
import argparse, json, os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from docodetect.config import load_config, resolve
from docodetect.database import Database
from docodetect.calibration import Calibration
from docodetect.features import Features
from docodetect import matcher


def _pct(vals, f):
    v = sorted(vals)
    return v[min(len(v) - 1, int(f * (len(v) - 1)))] if v else float("nan")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=None, help="Korpus-Verzeichnis (Default: paths.corpus_dir)")
    ap.add_argument("--tier", type=int, default=2, help="nur diese Tier-Stufe (Default 2)")
    args = ap.parse_args()

    cfg = load_config()
    corpus_dir = Path(args.corpus) if args.corpus else resolve(
        cfg.get("paths", {}).get("corpus_dir", "../Doco_Detect_corpus"))
    manifest = json.loads((Path(__file__).resolve().parent.parent /
                           "corpus" / "manifest.json").read_text())

    db = Database(cfg)
    cal = Calibration.load(resolve(cfg["calibration"]["file"]))

    total = comparable = exact = 0
    deltas: list[float] = []
    divergent: list[tuple[str, str]] = []
    for img in manifest["images"]:
        if args.tier is not None and img.get("tier") != args.tier:
            continue
        rp = corpus_dir / img["report_rel"]
        if not rp.exists():
            continue
        stored = json.loads(rp.read_text())
        if not stored.get("measured"):
            continue
        total += 1
        measured = Features(**stored["measured"])
        rep = matcher.match(measured, db, cal, cfg, label=img.get("label"))
        s_dec, n_dec = stored.get("decision"), rep.decision
        s_top = stored["candidates"][0]["article_number"] if stored.get("candidates") else None
        n_top = rep.candidates[0].article_number if rep.candidates else None
        s_llr, n_llr = stored.get("llr_margin"), rep.llr_margin
        # llr comparison
        if s_llr is not None and n_llr is not None:
            comparable += 1
            d = abs(n_llr - s_llr)
            deltas.append(d)
            llr_ok = d < 1e-3
        else:
            llr_ok = (s_llr is None) == (n_llr is None)
        ok = llr_ok and s_dec == n_dec and s_top == n_top
        if ok:
            exact += 1
        else:
            reason = []
            if s_dec != n_dec: reason.append(f"decision {s_dec}->{n_dec}")
            if s_top != n_top: reason.append(f"top1 {s_top}->{n_top}")
            if s_llr is not None and n_llr is not None and abs(n_llr - s_llr) >= 1e-3:
                reason.append(f"llr {s_llr}->{round(n_llr,4)}")
            elif (s_llr is None) != (n_llr is None):
                reason.append(f"llr {s_llr}->{n_llr}")
            divergent.append((os.path.basename(stored.get("image_path", rp.name)), "; ".join(reason)))
    db.conn.close()

    print(f"[fidelity] Korpus: {corpus_dir}")
    print(f"[fidelity] geprueft {total} Reports | exakt {exact} | abweichend {total - exact}")
    if deltas:
        print(f"[fidelity] Delta llr_margin (n={comparable}): "
              f"median {_pct(deltas,0.5):.4f} | p90 {_pct(deltas,0.9):.4f} | max {max(deltas):.4f}")
    if divergent:
        print(f"[fidelity] abweichende Dateien ({len(divergent)}):")
        for name, why in sorted(divergent):
            print(f"    {name}: {why}")
    return 0 if exact == total else 1


if __name__ == "__main__":
    sys.exit(main())
