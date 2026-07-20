"""Auswertungs-Artefakte über gespeicherte MatchReport-JSONs.

Einstieg: run_analysis(cfg, reports_dir=None, run_id=None) -> Ausgabeordner
CLI:      python -m docodetect.cli analyze [reports_dir] [--run-id X]

Sechs Auswertungen (A-F, siehe die _analysis_*-Funktionen). Jede erzeugt
IMMER zwei Artefakte: eine Grafik (PNG, matplotlib) für den Menschen und die
zugrundeliegenden Zahlen (CSV bzw. JSON) für Vergleiche zwischen Testläufen.
Alles landet unter <analysis.output_dir>/<run_id>/ plus einem report.md, das
die Grafiken einbindet und übersprungene Auswertungen begründet.

Feld-Mapping auf das statistische Scoring (die klassischen Größen der
Vorgänger-Version existieren so nicht mehr):
- "Gesamtscore"            -> log_score (gewichtete Log-Likelihood, 0 = perfekt)
- "Teilscores geo/color/shape" -> Summe der gewichteten Log-Beiträge der
  Merkmale je Kanal (CHANNELS unten)
- "auto_accept_score"      -> ersetzt durch das max|z|-Gate (max_z_accept)
- "margin"                 -> LLR-Margin (log_score_1 - log_score_2),
  Schwelle min_llr_margin
- "entscheidung"           -> accept | ambiguous | reject
- ground_truth             -> report.label (Feedback-Buttons oder evaluate)

Rückwärtskompatibilität: alte Report-JSONs ohne neuere Felder (label,
verdict, centroid_px, ...) crashen nichts – betroffene Auswertungen werden
übersprungen bzw. die Fälle ausgelassen, mit Hinweis im report.md.
"""

from __future__ import annotations

import csv
import json
import math
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless – nie ein Fenster öffnen
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from .config import resolve  # noqa: E402
from .database import Database  # noqa: E402
from .features import height_corrected_scale  # noqa: E402
from .matcher import CHANNELS, CandidateReport, MatchReport, channel_scores  # noqa: E402, F401
from .reporting import NO_MATCH, judgement, load_reports, predicted_article  # noqa: E402


def wilson_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    """(Punktschätzer, untere, obere Grenze) des 95%-Wilson-Intervalls.
    Geschlossene Form – bewusst ohne scipy."""
    if n == 0:
        return 0.0, 0.0, 1.0
    p = k / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return p, max(0.0, center - half), min(1.0, center + half)


def rule_of_three(n: int) -> str:
    """0 beobachtete Fehler heißt nicht 0% Fehlerrate – Faustregel 3/n."""
    return f"0 Fehler bei n={n} -> Fehlerrate < {3 / n:.1%} (95%)" if n else ""


# ---------- kleine Helfer ----------

def _write_csv(path: Path, header: list, rows: list) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def _finish(fig, path: Path, run_id: str) -> None:
    fig.text(0.99, 0.005, f"run: {run_id}", ha="right", va="bottom",
             fontsize=7, color="gray")
    fig.tight_layout(rect=(0, 0.02, 1, 1))
    fig.savefig(path, dpi=130)
    plt.close(fig)


def _top1(report: MatchReport) -> CandidateReport | None:
    return report.candidates[0] if report.candidates else None


class _Section:
    """Ein Abschnitt des report.md: Titel, Hinweise, erzeugte Artefakte."""

    def __init__(self, title: str):
        self.title = title
        self.notes: list = []
        self.artifacts: list = []
        self.skipped: str | None = None

    def to_md(self) -> str:
        lines = [f"## {self.title}", ""]
        if self.skipped:
            lines += [f"**Übersprungen:** {self.skipped}", ""]
        for n in self.notes:
            lines += [f"- {n}"]
        if self.notes:
            lines.append("")
        for a in self.artifacts:
            if a.suffix == ".png":
                lines += [f"![{a.stem}]({a.name})", ""]
            else:
                lines += [f"Daten: [`{a.name}`]({a.name})", ""]
        return "\n".join(lines)


# ---------- A) Confusion Matrix ----------

def _plot_confusion(mat: np.ndarray, gts: list, preds: list, title: str,
                    path: Path, run_id: str) -> None:
    fig, ax = plt.subplots(figsize=(max(7, 0.6 * len(preds) + 3),
                                    max(4.5, 0.5 * len(gts) + 2)))
    ax.imshow(mat, cmap="Blues")
    ax.set_xticks(range(len(preds)), preds, rotation=45, ha="right", fontsize=8)
    ax.set_yticks(range(len(gts)), gts, fontsize=8)
    ax.set_xlabel("erkannt (Top-1)")
    ax.set_ylabel("ground truth")
    ax.set_title(title, fontsize=10, wrap=True)
    vmax = mat.max() if mat.size else 1
    for i, gt in enumerate(gts):
        for j, pr in enumerate(preds):
            v = int(mat[i, j])
            if gt == pr:  # Diagonale (korrekt) visuell absetzen
                ax.add_patch(plt.Rectangle((j - 0.5, i - 0.5), 1, 1, fill=False,
                                           edgecolor="#1a7f37", linewidth=2.2))
            if v:
                ax.text(j, i, str(v), ha="center", va="center", fontsize=8,
                        color="white" if v > 0.6 * vmax else "black")
    _finish(fig, path, run_id)


def _analysis_confusion(reports: list, out: Path, run_id: str, cfg: dict) -> _Section:
    sec = _Section("A) Confusion Matrix")
    labeled = [r for r in reports if r.label]
    if not labeled:
        sec.skipped = ("keine Reports mit ground truth (Label) – per "
                       "Richtig/Falsch-Feedback oder `evaluate` labeln.")
        return sec

    def build(rs):
        pairs = Counter((r.label, predicted_article(r)) for r in rs)
        gts = sorted({g for g, _ in pairs})
        preds = sorted({p for _, p in pairs})
        mat = np.array([[pairs.get((g, p), 0) for p in preds] for g in gts],
                       dtype=int)
        return mat, gts, preds

    mat, gts, preds = build(labeled)
    _write_csv(out / "confusion_matrix.csv", ["ground_truth"] + preds,
               [[g] + list(row) for g, row in zip(gts, mat)])
    _plot_confusion(mat, gts, preds,
                    f"Confusion Matrix – alle Entscheidungen (n={len(labeled)})",
                    out / "confusion_matrix.png", run_id)
    sec.artifacts += [out / "confusion_matrix.png", out / "confusion_matrix.csv"]

    accepted = [r for r in labeled if r.decision == "accept"]
    if accepted:
        mat_a, gts_a, preds_a = build(accepted)
        _write_csv(out / "confusion_matrix_accept.csv", ["ground_truth"] + preds_a,
                   [[g] + list(row) for g, row in zip(gts_a, mat_a)])
        _plot_confusion(mat_a, gts_a, preds_a,
                        f"Confusion Matrix – nur ACCEPT (n={len(accepted)}) "
                        "– Fehler hier = Fehlbuchungen",
                        out / "confusion_matrix_accept.png", run_id)
        sec.artifacts += [out / "confusion_matrix_accept.png",
                          out / "confusion_matrix_accept.csv"]
    else:
        sec.notes.append("Keine ACCEPT-Fälle mit Label – Fehlbuchungs-Matrix entfällt.")
    return sec


# ---------- B) Score-Verteilungen ----------

def _analysis_scores(reports: list, out: Path, run_id: str, cfg: dict) -> _Section:
    sec = _Section("B) Score-Verteilungen (korrekt vs. falsch)")
    sec.notes.append(
        "Mapping: das frühere auto_accept_score existiert im statistischen "
        "Scoring nicht mehr – entscheidungsrelevant sind max|z| des Siegers "
        "(Gate `max_z_accept`) und die LLR-Margin (`min_llr_margin`).")
    rows = []
    for r in reports:
        ok = judgement(r)
        top = _top1(r)
        rows.append([r.timestamp, "" if ok is None else ("ja" if ok else "nein"),
                     r.decision,
                     top.log_score if top else "", top.posterior if top else "",
                     r.max_z_winner if r.max_z_winner is not None else "",
                     r.llr_margin if r.llr_margin is not None else ""])
    _write_csv(out / "score_distributions.csv",
               ["timestamp", "korrekt", "entscheidung", "log_score",
                "posterior", "max_abs_z", "llr_margin"], rows)
    sec.artifacts.append(out / "score_distributions.csv")

    judged = [(r, judgement(r)) for r in reports if judgement(r) is not None]
    if not judged:
        sec.skipped = "keine bewerteten Fälle – Histogramme entfallen (CSV liegt vor)."
        return sec
    m = cfg.get("matching", {})
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    panels = [
        ("max |z| des Siegers", "max_z_accept",
         lambda r: r.max_z_winner, axes[0]),
        ("LLR-Margin (Platz 1 − Platz 2)", "min_llr_margin",
         lambda r: r.llr_margin, axes[1]),
    ]
    for name, thr_key, getter, ax in panels:
        good = [getter(r) for r, ok in judged if ok and getter(r) is not None]
        bad = [getter(r) for r, ok in judged if not ok and getter(r) is not None]
        allv = good + bad
        if not allv:
            ax.set_title(f"{name}: keine Daten")
            continue
        bins = np.linspace(min(allv), max(allv) or 1.0, 20)
        ax.hist(good, bins=bins, alpha=0.55, label=f"korrekt (n={len(good)})",
                color="#1a7f37")
        ax.hist(bad, bins=bins, alpha=0.55, label=f"falsch (n={len(bad)})",
                color="#b02a37")
        thr = m.get(thr_key)
        if thr is not None:
            ax.axvline(float(thr), color="black", linestyle="--",
                       label=f"{thr_key} = {thr}")
        ax.set_title(f"{name} (n={len(allv)})")
        ax.set_xlabel(name + " [dimensionslos]")
        ax.set_ylabel("Anzahl Identifikationen")
        ax.legend(fontsize=8)
    _finish(fig, out / "score_distributions.png", run_id)
    sec.artifacts.insert(0, out / "score_distributions.png")
    return sec


# ---------- C) Near-Miss-Liste ----------

def _analysis_near_miss(reports: list, out: Path, run_id: str, cfg: dict) -> _Section:
    factor = float(cfg.get("analysis", {}).get("near_miss_factor", 1.5))
    min_llr = float(cfg.get("matching", {}).get("min_llr_margin", 2.0))
    limit = min_llr * factor
    sec = _Section(f"C) Near-Miss-Liste (korrekt, aber Margin < "
                   f"{min_llr} × {factor} = {limit:g})")
    rows = []
    for r in reports:
        if judgement(r) is not True or r.llr_margin is None or len(r.candidates) < 2:
            continue
        if r.llr_margin >= limit:
            continue
        c1, c2 = r.candidates[0], r.candidates[1]
        ch1, ch2 = channel_scores(c1), channel_scores(c2)
        rows.append([round(r.llr_margin, 4), r.timestamp, r.label,
                     c2.article_number, c1.log_score, c2.log_score,
                     round(ch1["geometry"] - ch2["geometry"], 4),
                     round(ch1["color"] - ch2["color"], 4),
                     round(ch1["shape"] - ch2["shape"], 4),
                     r.image_path or ""])
    rows.sort(key=lambda row: row[0])
    _write_csv(out / "near_misses.csv",
               ["margin", "timestamp", "ground_truth", "bedraenger",
                "log_score_top1", "log_score_top2", "diff_geometry",
                "diff_color", "diff_shape", "bilddatei"], rows)
    sec.artifacts.append(out / "near_misses.csv")
    if not rows:
        sec.notes.append("Keine Near-Misses gefunden – kein knapper korrekter Sieg.")
        return sec

    pairs = Counter(f"{row[2]}  <-  {row[3]}" for row in rows)
    top = pairs.most_common(12)
    fig, ax = plt.subplots(figsize=(8, max(3, 0.45 * len(top) + 1.5)))
    names = [p for p, _ in top][::-1]
    counts = [c for _, c in top][::-1]
    ax.barh(names, counts, color="#b58900")
    ax.set_xlabel("Anzahl Near-Misses")
    ax.set_title(f"Häufigste Bedränger-Paare (ground truth <- Bedränger, "
                 f"n={len(rows)})")
    _finish(fig, out / "near_misses.png", run_id)
    sec.artifacts.insert(0, out / "near_misses.png")
    return sec


# ---------- D) Teilscore-Attribution bei Fehlern ----------

def attribution_case(report: MatchReport) -> tuple[str, object, object]:
    """Warum ist ein als falsch bewerteter Report (nicht) attribuierbar?

    -> (Fall, Top-1-Kandidat, Kandidat des wahren Artikels)

    Die vier Nicht-Attribuierbar-Fälle haben GRUNDVERSCHIEDENE Ursachen und
    dürfen nicht in einen Topf – insbesondere ist `top1_korrekt` gar keine
    Fehlidentifikation: der richtige Artikel gewann, nur die Entscheidung war
    reject/ambiguous (bei 1-Shot-Referenzen der Normalfall, weil sigma_enroll
    = 0 das max|z|-Gate sprengt). Diese Fälle als 'Vorfilter-Kill' zu melden
    war der Bug hinter dem Widerspruch '13 Kills bei 59/60 Top-3'.
    """
    top = _top1(report)
    if top is None:
        return "keine_kandidaten", None, None
    right = next((c for c in report.candidates
                  if c.article_number == report.label), None)
    if right is None:
        return "vorfilter_kill", top, None
    if right is top:
        return "top1_korrekt", top, right
    if not top.features or not right.features:
        return "keine_merkmalsscores", top, right
    return "attribuierbar", top, right


# Fall -> ehrliche Meldung im report.md (keine Sammelkategorie mehr)
_ATTRIB_NOTES = {
    "vorfilter_kill":
        "der richtige Artikel hat den Geometrie-Vorfilter nicht überlebt "
        "(Toleranz bzw. Stammdaten prüfen – siehe `sync-stammdaten`)",
    "top1_korrekt":
        "der richtige Artikel stand auf Platz 1, die Entscheidung lautete aber "
        "reject/ambiguous – KEINE Fehlidentifikation, sondern eine Gate-/"
        "Margin-Frage; eine Teilscore-Attribution ist hier nicht anwendbar",
    "keine_kandidaten":
        "kein einziger Kandidat im Report (Segmentierung abgelehnt oder "
        "Vorfilter leer) – Attribution nicht berechenbar",
    "keine_merkmalsscores":
        "Attribution nicht berechenbar: dem Report fehlen die Merkmals-Scores "
        "(alte Report-Version)",
}


def _analysis_attribution(reports: list, out: Path, run_id: str, cfg: dict) -> _Section:
    sec = _Section("D) Teilscore-Attribution bei Fehlern")
    errors = [r for r in reports
              if judgement(r) is False and r.label and r.label != NO_MATCH]
    rows: list = []
    cases: Counter = Counter()
    unattributed: list = []
    for r in errors:
        case, wrong, right = attribution_case(r)
        cases[case] += 1
        if case != "attribuierbar":
            rang = next((i + 1 for i, c in enumerate(r.candidates)
                         if c.article_number == r.label), None)
            unattributed.append([
                case, r.timestamp, r.label,
                wrong.article_number if wrong else "", r.decision,
                len(r.candidates), rang if rang is not None else "",
                (r.measured or {}).get("circle_diameter_mm", ""),
                wrong.corrected_diameter_mm if wrong else "",
                wrong.nominal_size_mm if wrong else "",
                r.image_path or ""])
            continue
        chw, chr_ = channel_scores(wrong), channel_scores(right)
        diffs = {ch: round(chw[ch] - chr_[ch], 4) for ch in CHANNELS}
        verursacher = max(diffs, key=diffs.get)
        row = [f"{r.label} -> {wrong.article_number}", r.timestamp]
        for ch in CHANNELS:
            row += [chw[ch], chr_[ch], diffs[ch]]
        rows.append(row + [verursacher])
    header = ["pair", "timestamp"]
    for ch in CHANNELS:
        header += [f"{ch}_score_falsch", f"{ch}_score_richtig", f"{ch}_differenz"]
    _write_csv(out / "error_attribution.csv", rows=rows,
               header=header + ["verursacher"])
    sec.artifacts.append(out / "error_attribution.csv")

    sec.notes.append(f"{len(errors)} als falsch bewertete Identifikationen, "
                     f"davon {len(rows)} attribuierbar.")
    for case, note in _ATTRIB_NOTES.items():
        if cases.get(case):
            sec.notes.append(f"{cases[case]}× {note}.")
    if unattributed:
        _write_csv(out / "error_attribution_unattributed.csv",
                   ["fall", "timestamp", "wahr", "top1", "entscheidung",
                    "n_kandidaten", "rang_wahr", "gemessen_kreis_mm",
                    "top1_korrigiert_mm", "top1_nominal_mm", "bilddatei"],
                   sorted(unattributed))
        sec.artifacts.append(out / "error_attribution_unattributed.csv")

    if not rows:
        sec.notes.append("Keine attribuierbaren Fehlidentifikationen – gut so.")
        return sec

    colors = {"geometry": "#4c72b0", "color": "#b02a37", "shape": "#55a868"}
    pair_causes: dict = {}
    for row in rows:
        pair, verursacher = row[0], row[-1]
        pair_causes.setdefault(pair, Counter())[verursacher] += 1
    fig, axes = plt.subplots(1, 2, figsize=(12, max(4, 0.5 * len(pair_causes) + 2)))
    pairs_sorted = sorted(pair_causes, key=lambda p: -sum(pair_causes[p].values()))
    bottom = np.zeros(len(pairs_sorted))
    for ch in CHANNELS:
        vals = np.array([pair_causes[p].get(ch, 0) for p in pairs_sorted], float)
        axes[0].barh(pairs_sorted, vals, left=bottom, color=colors[ch], label=ch)
        bottom += vals
    axes[0].set_xlabel("Anzahl Fehler")
    axes[0].set_title(f"Verursacher-Kanal je Verwechslungspaar (n={len(rows)})")
    axes[0].legend(fontsize=8)
    axes[0].invert_yaxis()

    idx = {ch: header.index(f"{ch}_differenz") for ch in CHANNELS}
    data = [[row[idx[ch]] for row in rows] for ch in CHANNELS]
    axes[1].boxplot(data, tick_labels=list(CHANNELS))
    axes[1].axhline(0, color="gray", linewidth=0.8)
    axes[1].set_ylabel("Teilscore-Differenz falsch − richtig [Log-Beitrag]")
    axes[1].set_title("Differenzen je Kanal (>0 = Kanal begünstigt den falschen)")
    _finish(fig, out / "error_attribution.png", run_id)
    sec.artifacts.insert(0, out / "error_attribution.png")
    return sec


# ---------- E) Positionsplot ----------

def _analysis_position(reports: list, out: Path, run_id: str, cfg: dict) -> _Section:
    sec = _Section("E) Positionsplot (Ø-Messfehler über die Bildposition)")
    with_pos = [r for r in reports if r.centroid_px and r.label
                and r.label != NO_MATCH and r.measured]
    if not with_pos:
        sec.skipped = ("keine Reports mit Schwerpunkt + Label – "
                       "centroid_px wird erst seit dieser Version geloggt; "
                       "alte Logs können hier nicht ausgewertet werden.")
        return sec
    z_mm = float(cfg.get("geometry", {}).get("camera_height_mm", 300.0))
    rows = []
    try:
        db = Database(cfg)
        for r in with_pos:
            try:
                art = db.get_article(r.label)
            except Exception:
                art = None
            if art is None or not art.diameter_mm:
                continue  # nur Artikel mit Soll-Ø in der DB
            measured = r.measured.get("circle_diameter_mm")
            if measured is None:
                continue
            corrected = height_corrected_scale(measured, float(art.height_mm or 0.0), z_mm)
            rows.append([r.centroid_px[0], r.centroid_px[1], r.label,
                         float(art.diameter_mm), round(corrected, 2),
                         round(corrected - float(art.diameter_mm), 2)])
    finally:
        try:
            db.close()
        except Exception:
            pass
    _write_csv(out / "position_errors.csv",
               ["x_px", "y_px", "artikel", "soll_mm", "gemessen_mm", "fehler_mm"],
               rows)
    sec.artifacts.append(out / "position_errors.csv")
    if not rows:
        sec.notes.append("Kein gelabelter Fall mit Soll-Ø in der Datenbank.")
        return sec

    xs = [row[0] for row in rows]
    ys = [row[1] for row in rows]
    errs = [row[5] for row in rows]
    m = max(0.5, max(abs(e) for e in errs))
    fig, ax = plt.subplots(figsize=(9, 5.5))
    size = next((r.image_size for r in with_pos if r.image_size), None)
    if size:
        ax.add_patch(plt.Rectangle((0, 0), size[0], size[1], fill=False,
                                   edgecolor="gray", linestyle="--", linewidth=1))
        ax.set_xlim(-40, size[0] + 40)
        ax.set_ylim(size[1] + 40, -40)          # Bildkoordinaten: y nach unten
    else:
        ax.invert_yaxis()
    sc = ax.scatter(xs, ys, c=errs, cmap="RdBu_r", vmin=-m, vmax=m,
                    edgecolors="black", linewidths=0.4, s=60)
    fig.colorbar(sc, ax=ax, label="Ø-Messfehler (mm), 0 = weiß")
    ax.set_xlabel("Schwerpunkt x (px)")
    ax.set_ylabel("Schwerpunkt y (px)")
    ax.set_title(f"Messfehler über die Bildposition (n={len(rows)}) – "
                 "Muster am Rand = Objektiv-/Kalibrierproblem")
    _finish(fig, out / "position_errors.png", run_id)
    sec.artifacts.insert(0, out / "position_errors.png")
    return sec


# ---------- F) Quoten mit Wilson-Konfidenzintervallen ----------

def _quota(k: int, n: int, is_error_rate: bool = False) -> dict:
    p, lo, hi = wilson_interval(k, n)
    q = {"k": k, "n": n, "p": round(p, 4),
         "wilson_lo": round(lo, 4), "wilson_hi": round(hi, 4)}
    if is_error_rate and n > 0 and k == 0:
        q["rule_of_three"] = rule_of_three(n)
    return q


def _analysis_metrics(reports: list, out: Path, run_id: str, cfg: dict,
                      source: str) -> _Section:
    sec = _Section("F) Quoten mit Wilson-Konfidenzintervallen")
    judged = [(r, judgement(r)) for r in reports if judgement(r) is not None]
    labeled = [r for r in reports if r.label]
    accepts = [r for r in reports if r.decision == "accept"]
    accepts_judged = [(r, ok) for r, ok in judged if r.decision == "accept"]

    top3_hits = sum(
        1 for r in labeled
        if (r.label in [c.article_number for c in r.candidates[:3]]
            or (not r.candidates and r.label == NO_MATCH)))
    metrics = {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "run_id": run_id,
        "source": source,
        "n_reports": len(reports),
        "n_judged": len(judged),
        "quotas": {
            "accuracy_top1": _quota(sum(1 for _, ok in judged if ok), len(judged)),
            "accuracy_top3": _quota(top3_hits, len(labeled)),
            "auto_accept_rate": _quota(len(accepts), len(reports)),
            "false_accept_rate": _quota(
                sum(1 for _, ok in accepts_judged if not ok),
                len(accepts_judged), is_error_rate=True),
        },
        "per_article": {},
    }
    err_top1 = metrics["quotas"]["accuracy_top1"]
    if err_top1["n"] > 0 and err_top1["k"] == err_top1["n"]:
        err_top1["rule_of_three"] = rule_of_three(err_top1["n"])

    per_article: dict = {}
    for r, ok in judged:
        if not r.label:
            continue
        k_n = per_article.setdefault(r.label, [0, 0])
        k_n[1] += 1
        if ok:
            k_n[0] += 1
    metrics["per_article"] = {a: _quota(k, n) for a, (k, n) in per_article.items()}

    (out / "metrics.json").write_text(
        json.dumps(metrics, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8")
    sec.artifacts.append(out / "metrics.json")
    if not judged:
        sec.notes.append("Keine bewerteten Fälle – alle Quoten mit n=0 bzw. "
                         "nur auto_accept_rate aussagekräftig.")

    fig, axes = plt.subplots(1, 2, figsize=(12, max(4, 0.4 * len(per_article) + 2)))
    names, ps, lows, highs = [], [], [], []
    for name, q in metrics["quotas"].items():
        names.append(f"{name}\n(n={q['n']})")
        ps.append(q["p"])
        lows.append(q["p"] - q["wilson_lo"])
        highs.append(q["wilson_hi"] - q["p"])
    axes[0].errorbar(range(len(names)), ps, yerr=[lows, highs], fmt="o",
                     capsize=4, color="#4c72b0")
    axes[0].set_xticks(range(len(names)), names, fontsize=8)
    axes[0].set_ylim(-0.02, 1.02)
    axes[0].set_ylabel("Quote (Anteil, 0–1)")
    axes[0].set_title(f"Quoten mit 95%-Wilson-CI (n={len(reports)} Reports)")
    axes[0].grid(axis="y", alpha=0.3)

    if per_article:
        arts = sorted(metrics["per_article"],
                      key=lambda a: metrics["per_article"][a]["p"])
        ps_a = [metrics["per_article"][a]["p"] for a in arts]
        lo_a = [metrics["per_article"][a]["p"] - metrics["per_article"][a]["wilson_lo"]
                for a in arts]
        hi_a = [metrics["per_article"][a]["wilson_hi"] - metrics["per_article"][a]["p"]
                for a in arts]
        labels_a = [f"{a} (n={metrics['per_article'][a]['n']})" for a in arts]
        axes[1].barh(labels_a, ps_a, xerr=[lo_a, hi_a], capsize=3,
                     color="#55a868")
        axes[1].set_xlim(0, 1.02)
        axes[1].set_xlabel("Accuracy (Anteil korrekt, 0–1)")
        axes[1].set_title("Accuracy pro Artikel – schlechteste zuerst")
    else:
        axes[1].set_title("Accuracy pro Artikel: keine gelabelten Fälle")
        axes[1].axis("off")
    _finish(fig, out / "metrics.png", run_id)
    sec.artifacts.insert(0, out / "metrics.png")
    return sec


# ---------- Einstiegspunkt ----------

def run_analysis(cfg: dict, reports_dir: str | Path | None = None,
                 run_id: str | None = None, archive: bool = False) -> Path:
    """Alle sechs Auswertungen über einen Ordner voller Report-JSONs fahren.
    Gibt den Artefakt-Ordner <analysis.output_dir>/<run_id>/ zurück.

    archive=True: die ausgewerteten Report-JSONs werden anschließend nach
    <run_id>/reports/ verschoben – jede Testrunde bleibt komplett beisammen
    und die nächste startet bei 0. Bilder (Roh-PNGs/JPGs) bleiben im
    Quellordner: die PNGs sind die Golden-Testfälle der Segmentierungs-
    Regressionssuite und werden von den Reports weiter referenziert."""
    src = Path(reports_dir) if reports_dir else resolve(
        cfg.get("paths", {}).get("captures_dir", "data/captures"))
    run_id = run_id or datetime.now().strftime("%Y%m%d-%H%M%S")
    out = resolve(cfg.get("analysis", {}).get("output_dir", "reports/analysis")) / run_id
    out.mkdir(parents=True, exist_ok=True)

    loaded = load_reports(src)
    reports = [r for _, r in loaded]
    sections = []
    if not reports:
        sections.append(_Section("Keine Reports"))
        sections[-1].skipped = f"keine Report-JSONs in {src} gefunden."
    else:
        sections.append(_analysis_confusion(reports, out, run_id, cfg))
        sections.append(_analysis_scores(reports, out, run_id, cfg))
        sections.append(_analysis_near_miss(reports, out, run_id, cfg))
        sections.append(_analysis_attribution(reports, out, run_id, cfg))
        sections.append(_analysis_position(reports, out, run_id, cfg))
        sections.append(_analysis_metrics(reports, out, run_id, cfg, str(src)))

    archived_note = ""
    if archive and loaded:
        arch = out / "reports"
        arch.mkdir(exist_ok=True)
        for p, _ in loaded:
            shutil.move(str(p), str(arch / p.name))
        archived_note = (f"- Reports: {len(loaded)} JSONs nach `{arch}` "
                         "archiviert – der Quellordner ist bereit für die "
                         "nächste Testrunde (Bilder bleiben dort liegen).")

    judged_n = sum(1 for r in reports if judgement(r) is not None)
    head = [
        "# Scoring-Analyse – Auswertungslauf", "",
        f"- run_id: `{run_id}`",
        f"- erzeugt: {datetime.now().isoformat(timespec='seconds')}",
        f"- Quelle: `{src}`",
        f"- Reports: {len(reports)} (davon bewertet/gelabelt: {judged_n})",
    ]
    if archived_note:
        head.append(archived_note)
    head += [
        "",
        "Grafiken (PNG) für den Menschen, CSV/JSON für Diffs zwischen "
        "Testläufen. Bewertungen kommen aus den Richtig/Falsch-Buttons "
        "bzw. `evaluate`-Labels.", "",
    ]
    (out / "report.md").write_text(
        "\n".join(head + [s.to_md() for s in sections]), encoding="utf-8")
    return out


def publish_run(cfg: dict, run_dir: str | Path) -> Path:
    """Lauf-Artefakte zusätzlich ins VERSIONIERTE Archiv kopieren
    (analysis.publish_dir, Default reports/archive – .gitignore-Ausnahme).

    Kopiert nur die aggregierten Artefakte (Top-Level-Dateien des Laufs:
    sechs Auswertungen als PNG+CSV, metrics.png/json, report.md). Der
    Unterordner reports/ mit den per --archive verschobenen rohen
    Report-JSONs bleibt bewusst draußen – ins Git-Archiv gehören nur
    Aggregate. Überschreibt nie einen vorhandenen Archiv-Eintrag."""
    run_dir = Path(run_dir)
    dest = resolve(cfg.get("analysis", {}).get(
        "publish_dir", "reports/archive")) / run_dir.name
    if dest.exists():
        raise FileExistsError(
            f"Archiv-Eintrag existiert bereits: {dest}. Anderen --run-id "
            "wählen oder den Eintrag zuerst entfernen – publish "
            "überschreibt nie.")
    dest.mkdir(parents=True)
    n = 0
    for p in sorted(run_dir.iterdir()):
        if p.is_file():
            shutil.copy2(p, dest / p.name)
            n += 1
    print(f"[analyze] {n} Artefakte nach {dest} veröffentlicht "
          "(ohne rohe Report-JSONs).")
    return dest
