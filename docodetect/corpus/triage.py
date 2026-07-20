"""corpus-triage: Failures clustern und Hypothesen aufschreiben.

Erzeugt AUSSCHLIESSLICH Befunde. Keine Code-, Schwellen- oder
Baseline-Aenderung — das ist die Trennlinie, die diesen Befehl
vertrauenswuerdig macht.
"""

from __future__ import annotations

import json
import math
import sqlite3
import statistics
from datetime import datetime
from pathlib import Path

from ..matcher import MatchReport
from .manifest import Manifest

KATEGORIEN = ("segmentierungs_aenderung", "vorfilter_kill", "gate_kipp",
              "messwert_drift", "label_verdacht", "unklar")

_SEG_FELDER = {"seg_area_px", "centroid_x", "centroid_y"}


def _pearson(xs: list, ys: list) -> float:
    if len(xs) < 2:
        return 0.0
    mx, my = statistics.mean(xs), statistics.mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
    return round(num / den, 4) if den else 0.0


def categorize(failure: dict, golden) -> str:
    felder = {d["field"] for d in failure.get("diffs", [])}

    # Kill zuerst pruefen: er ist eine Aussage ueber die Kandidatenliste,
    # nicht ueber die Entscheidung (Spec 7.1).
    if golden is not None and golden.label:
        kandidaten = [c.article_number for c in golden.candidates]
        if golden.label not in kandidaten:
            if felder & {"top_k", "decision"} or not felder:
                if golden.candidates and golden.gate_passed \
                        and golden.candidates[0].posterior >= 0.95:
                    return "label_verdacht"
                return "vorfilter_kill"

    if felder & _SEG_FELDER:
        return "segmentierungs_aenderung"
    if "gate_passed" in felder:
        return "gate_kipp"
    if felder:
        return "messwert_drift"
    return "unklar"


def position_correlation(cfg: dict, root: Path, manifest: Manifest) -> dict:
    """Diskriminator-Test aus Spec 7.1: haengt der Messfehler vom Abstand
    zur Bildmitte ab?

    Je Capture: circle_diameter_mm minus Enrollment-Mittel des WAHREN
    Artikels, gegen den Schwerpunkt-Abstand zur Bildmitte. Ersetzt den
    nicht durchfuehrbaren Einlern-Shot-Vergleich (image_path ist NULL).
    """
    punkte = []
    for session in sorted({e.session for e in manifest.images}):
        db = root / session / "bundle" / "db.sqlite3"
        if not db.exists():
            continue
        mittel = {}
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            for art, sj in con.execute(
                    "SELECT article_number, stats_json FROM reference_stats"):
                m = json.loads(sj).get("scalar_mean", {}).get("diameter_mm")
                if m:
                    mittel[art] = m
        finally:
            con.close()

        for e in manifest.images:
            if e.session != session or not e.label or e.label not in mittel:
                continue
            rp = root / e.report_rel
            if not rp.exists():
                continue
            r = MatchReport.from_json(rp.read_text(encoding="utf-8"))
            d_mm = (r.measured or {}).get("circle_diameter_mm")
            if not d_mm or not r.centroid_px or not r.image_size:
                continue
            cx, cy = r.image_size[0] / 2.0, r.image_size[1] / 2.0
            dist = math.hypot(r.centroid_px[0] - cx, r.centroid_px[1] - cy)
            punkte.append({"sha": e.sha, "article": e.label, "dist": dist,
                           "delta": d_mm - mittel[e.label]})

    xs = [p["dist"] for p in punkte]
    ys = [p["delta"] for p in punkte]
    r = _pearson(xs, ys)
    if not punkte:
        deutung = "keine auswertbaren Punkte (kein Buendel-DB-Snapshot?)"
    elif abs(r) < 0.3:
        deutung = ("Ausgang B: keine Positionsabhaengigkeit. Hypothese (i) "
                   "faellt; es bleiben minAreaRect/minEnclosingCircle-Versatz "
                   "und/oder Segmentierung.")
    else:
        deutung = ("Ausgang A: Positionsabhaengigkeit bestaetigt. Der Messfehler "
                   "haengt vom Abstand zur Bildmitte ab — positionsabhaengige "
                   "Projektion blaeht die Stammdaten auf.")
    return {"n": len(punkte), "pearson_r": r, "deutung": deutung,
            "punkte": punkte}


def triage_run(cfg: dict, root: Path, run_id: str) -> Path:
    lauf = root / "runs" / run_id
    fd = lauf / "failures"
    if not fd.is_dir():
        raise FileNotFoundError(f"Lauf '{run_id}' hat keinen failures-Ordner")

    manifest = Manifest.load()
    per_sha = manifest.by_sha()
    cluster: dict = {k: [] for k in KATEGORIEN}
    for p in sorted(fd.glob("*.json")):
        fail = json.loads(p.read_text(encoding="utf-8"))
        eintrag = next((e for s, e in per_sha.items() if s.startswith(fail["sha"][:8])),
                       None)
        golden = None
        if eintrag:
            rp = root / eintrag.report_rel
            if rp.exists():
                golden = MatchReport.from_json(rp.read_text(encoding="utf-8"))
        kat = categorize(fail, golden)
        cluster[kat].append({**fail, "image_rel":
                             eintrag.image_rel if eintrag else None})

    korr = position_correlation(cfg, root, manifest)

    z = [f"# Triage-Befunde `{run_id}`", "",
         f"Erzeugt {datetime.now().isoformat(timespec='seconds')}.", "",
         "> Dieser Bericht enthaelt **nur Befunde**. Keine Code-, Schwellen- "
         "oder Baseline-Aenderung wurde vorgenommen.", "",
         "## Kategorien", ""]
    for kat in KATEGORIEN:
        eintraege = cluster[kat]
        if not eintraege:
            continue
        z.append(f"### {kat} ({len(eintraege)})")
        z.append("")
        for f in eintraege[:25]:
            felder = ", ".join(sorted({d["field"] for d in f.get("diffs", [])})) or "–"
            z.append(f"- `{f['sha'][:8]}` · {f['session']}/{f['article']} · "
                     f"Felder: {felder}"
                     + (f" · [PNG]({f['image_rel']})" if f.get("image_rel") else ""))
        if len(eintraege) > 25:
            z.append(f"- … und {len(eintraege) - 25} weitere")
        z.append("")

    z += ["## Diskriminator: Position gegen Messfehler", "",
          f"- Punkte: {korr['n']}",
          f"- Pearson r: {korr['pearson_r']}",
          f"- Deutung: {korr['deutung']}", ""]

    out = lauf / "findings.md"
    out.write_text("\n".join(z) + "\n", encoding="utf-8")
    (lauf / "position_correlation.json").write_text(
        json.dumps(korr, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out
