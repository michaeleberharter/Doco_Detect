"""corpus-diff: zwei Laeufe gegeneinander stellen."""

from __future__ import annotations

import json
from pathlib import Path


def _lade(root: Path, run_id: str) -> tuple:
    d = root / "runs" / run_id
    mp = d / "metrics.json"
    if not mp.exists():
        raise FileNotFoundError(f"Lauf '{run_id}' hat keine metrics.json ({mp})")
    metrics = json.loads(mp.read_text(encoding="utf-8"))
    kaputt = set()
    fd = d / "failures"
    if fd.is_dir():
        kaputt = {p.stem for p in fd.glob("*.json")}
    return metrics, kaputt


def diff_runs(root: Path, run_a: str, run_b: str) -> dict:
    ma, ka = _lade(root, run_a)
    mb, kb = _lade(root, run_b)
    deltas = {}
    qa, qb = ma.get("quotas") or {}, mb.get("quotas") or {}
    for name in sorted(set(qa) & set(qb)):
        a, b = qa[name], qb[name]
        if isinstance(a, dict) and isinstance(b, dict) and "p" in a and "p" in b:
            deltas[name] = {"a": a["p"], "b": b["p"],
                            "delta": round(b["p"] - a["p"], 4)}
    return {"run_a": run_a, "run_b": run_b,
            "neu_kaputt": sorted(kb - ka),
            "repariert": sorted(ka - kb),
            "weiterhin_kaputt": sorted(ka & kb),
            "metrik_deltas": deltas}


def format_diff(d: dict) -> str:
    z = [f"=== corpus-diff: {d['run_a']} -> {d['run_b']} ===", ""]
    for titel, key in (("neu kaputt", "neu_kaputt"),
                       ("repariert", "repariert"),
                       ("weiterhin kaputt", "weiterhin_kaputt")):
        z.append(f"{titel}: {len(d[key])}")
        for sha in d[key][:20]:
            z.append(f"    {sha}")
        if len(d[key]) > 20:
            z.append(f"    … und {len(d[key]) - 20} weitere")
        z.append("")
    if d["metrik_deltas"]:
        z.append("Metrik-Deltas:")
        for name, v in d["metrik_deltas"].items():
            z.append(f"    {name:22} {v['a']:.4f} -> {v['b']:.4f}  ({v['delta']:+.4f})")
    return "\n".join(z)
