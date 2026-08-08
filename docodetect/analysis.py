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
from .plotstyle import (DIV, OUTLIER, PALETTE, SEQ, apply_style,  # noqa: E402,F401
                        panel_label)
from .database import Database  # noqa: E402
from .features import height_corrected_scale  # noqa: E402
from .matcher import (CHANNELS, CandidateReport, MatchReport,  # noqa: E402, F401
                      _FLOOR_KEY, channel_scores)
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
    fig.savefig(path, dpi=200)   # >= 200 dpi (plotstyle-Vorgabe)
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

def _confusion_focus(mat: np.ndarray, gts: list, preds: list):
    """Auf den Fehler-Fokus reduzieren: nur gt-Zeilen, die NICHT restlos korrekt
    sind (Verwechslung, Reject oder Diagonale=0), plus die beteiligten
    pred-Spalten und die Diagonalen dieser Zeilen. Bei 41 Artikeln waere die
    volle Matrix eine >90 % leere Flaeche – die Fehler gingen darin unter.
    Gibt (mat2, gts2, preds2, zero_gt) zurueck oder None, wenn alles sauber.
    `zero_gt` = gt-Artikel mit Diagonale 0 (NIE korrekt getroffen – der Fall,
    der sonst unsichtbar bliebe: Reject ohne Fehlbuchung)."""
    pred_idx = {p: j for j, p in enumerate(preds)}
    keep_g, zero_gt = [], set()
    for i, g in enumerate(gts):
        diag = mat[i, pred_idx[g]] if g in pred_idx else 0
        if diag < mat[i].sum():                 # mind. eine Fehlbuchung/Reject
            keep_g.append(i)
            if diag == 0:
                zero_gt.add(g)
    if not keep_g:
        return None
    keep_p = set()
    for i in keep_g:
        keep_p.update(int(j) for j in np.nonzero(mat[i])[0])
        if gts[i] in pred_idx:                  # Diagonale zum Kontext behalten
            keep_p.add(pred_idx[gts[i]])
    keep_p = sorted(keep_p)
    return (mat[np.ix_(keep_g, keep_p)], [gts[i] for i in keep_g],
            [preds[j] for j in keep_p], zero_gt)


def _render_confusion(mat: np.ndarray, gts: list, preds: list, title: str,
                      path: Path, run_id: str, n_ident: int) -> None:
    """Fehler-Fokus-Confusion. Ohne Fehler eine Textzeile statt leerer Matrix.
    Die VOLLE Matrix liegt als CSV daneben."""
    focus = _confusion_focus(mat, gts, preds)
    if focus is None:
        fig, ax = plt.subplots(figsize=(7, 1.8))
        ax.set_axis_off()
        ax.text(0.5, 0.55, f"keine Verwechslungen bei n={n_ident} Identifikationen",
                ha="center", va="center", fontsize=10)
        ax.set_title(title, wrap=True)
        _finish(fig, path, run_id)
        return
    mat, gts, preds, zero_gt = focus
    fig, ax = plt.subplots(figsize=(max(6, 0.6 * len(preds) + 3),
                                    max(3.5, 0.55 * len(gts) + 2)))
    ax.imshow(mat, cmap="Blues")
    ax.set_xticks(range(len(preds)), preds, rotation=45, ha="right")
    ax.set_yticks(range(len(gts)), gts)
    # gt ohne jeden Treffer rot+fett markieren (Reject/Verwechslung), damit man
    # sie von "hat auch Treffer, aber Fehler" unterscheidet.
    for tick, g in zip(ax.get_yticklabels(), gts):
        if g in zero_gt:
            tick.set_color(OUTLIER)
            tick.set_fontweight("bold")
    ax.set_xlabel("erkannt (Top-1)")
    ax.set_ylabel("ground truth")
    ax.set_title(title + "  ·  nur Fehler-Zeilen/-Spalten", wrap=True)
    vmax = mat.max() if mat.size else 1
    for i in range(len(gts)):
        for j in range(len(preds)):
            v = int(mat[i, j])
            if v:
                ax.text(j, i, str(v), ha="center", va="center", fontsize=7,
                        color="white" if v > 0.6 * vmax else "black")
    if zero_gt:
        fig.text(0.5, 0.005, "rot = nie korrekt getroffen (Reject/Verwechslung, "
                 "Diagonale 0)", ha="center", va="bottom", fontsize=7, color=OUTLIER)
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
    _render_confusion(mat, gts, preds,
                      f"Confusion Matrix – alle Entscheidungen (n={len(labeled)})",
                      out / "confusion_matrix.png", run_id, len(labeled))
    sec.artifacts += [out / "confusion_matrix.png", out / "confusion_matrix.csv"]

    accepted = [r for r in labeled if r.decision == "accept"]
    if accepted:
        mat_a, gts_a, preds_a = build(accepted)
        _write_csv(out / "confusion_matrix_accept.csv", ["ground_truth"] + preds_a,
                   [[g] + list(row) for g, row in zip(gts_a, mat_a)])
        _render_confusion(mat_a, gts_a, preds_a,
                          f"Confusion Matrix – nur ACCEPT (n={len(accepted)}) "
                          "– Fehler hier = Fehlbuchungen",
                          out / "confusion_matrix_accept.png", run_id, len(accepted))
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
        ax.set_xlabel(name)   # dimensionslos: keine Einheit, Titel nennt die Groesse
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

# ============================================================ STUFE B: Grafiken
# Alle bildfrei (nur Report-JSONs + DB). Farbe traegt NIE die Artikelidentitaet
# (41 Artikel sprengen jede kategoriale Palette) – Artikel stehen ueber die
# Position (sortierte Balken/Punkte). Farbe kodiert nur wenige Zustaende
# (korrekt/falsch, accept/ambiguous/reject, Rangklasse).

_C_OK = "#1a7f37"        # korrekt (bestehende Score-Grafik nutzt dieselben)
_C_BAD = "#b02a37"       # falsch
_DECISION_COLORS = {"accept": "#1baf7a", "ambiguous": "#eda100", "reject": "#e34948"}
_RANK_COLORS = {"1": "#1baf7a", "2": "#7bc47f", "3": "#eda100",
                ">3": "#eb6834", "nicht im Set": "#e34948"}
_RANK_ORDER = ["1", "2", "3", ">3", "nicht im Set"]
_TOL_MM = 6.0            # +/- Toleranzband Ø gegen Nominal


def _order_key(r: MatchReport) -> str:
    """Aufnahmereihenfolge = Millisekunden-Basename des report_path
    (YYYYMMDD-HHMMSS-fff, festbreit -> lexikalisch == chronologisch). BEWUSST
    NICHT das timestamp-Feld: das hat nur Sekunden-Aufloesung, Aufnahmen
    derselben Sekunde waeren nicht unterscheidbar (matcher.py:228). Wer hier
    kuenftig aufs naheliegende timestamp-Feld greift, verliert die Ordnung
    innerhalb einer Sekunde. Fallback nur, wenn kein report_path da ist."""
    return Path(r.report_path).stem if r.report_path else (r.timestamp or "")


def _true_rank(r: MatchReport) -> int | None:
    """1-basierter Rang von r.label in den Kandidaten; None = nicht im Set."""
    if not r.label:
        return None
    for i, c in enumerate(r.candidates):
        if c.article_number == r.label:
            return i + 1
    return None


def _analysis_margin(reports, out: Path, run_id: str, cfg: dict) -> _Section:
    """(2) LLR-Margin Platz1-vs-Platz2, korrekt vs. falsch, Gate-Linie."""
    sec = _Section("D) LLR-Margin-Verteilung (korrekt vs. falsch)")
    gate = float(cfg.get("matching", {}).get("min_llr_margin", 2.0))
    judged = [(r.llr_margin, judgement(r)) for r in reports
              if r.llr_margin is not None and judgement(r) is not None]
    _write_csv(out / "margin_distribution.csv", ["llr_margin", "korrekt"],
               [[mg, "ja" if j else "nein"] for mg, j in judged])
    sec.artifacts.append(out / "margin_distribution.csv")
    if not judged:
        sec.skipped = "keine bewerteten Fälle mit Margin."
        return sec
    good = [mg for mg, j in judged if j]
    bad = [mg for mg, j in judged if not j]
    fig, ax = plt.subplots(figsize=(7, 4))
    bins = np.linspace(0, max([mg for mg, _ in judged] + [gate]) * 1.05, 22)
    ax.hist(good, bins=bins, color=_C_OK, alpha=0.6, label=f"korrekt (n={len(good)})")
    ax.hist(bad, bins=bins, color=_C_BAD, alpha=0.6, label=f"falsch (n={len(bad)})")
    ax.axvline(gate, color="black", ls="--", label=f"min_llr_margin = {gate}")
    ax.set_xlabel("LLR-Margin (Platz 1 − Platz 2)")
    ax.set_ylabel("Anzahl Identifikationen")
    ax.set_title(f"LLR-Margin – korrekt vs. falsch (n={len(judged)})")
    ax.legend()
    _finish(fig, out / "margin_distribution.png", run_id)
    sec.artifacts.insert(0, out / "margin_distribution.png")
    return sec


def _analysis_margin_vs_setsize(reports, out: Path, run_id: str, cfg: dict) -> _Section:
    """(5) Margin gegen Kandidatensetgroesse, Median je Groesse, Gate-Linie."""
    sec = _Section("E) Margin gegen Kandidatensetgröße")
    gate = float(cfg.get("matching", {}).get("min_llr_margin", 2.0))
    pts = [(len(r.candidates), r.llr_margin, judgement(r)) for r in reports
           if r.llr_margin is not None and r.candidates]
    _write_csv(out / "margin_vs_setsize.csv", ["set_size", "llr_margin", "korrekt"],
               [[s, mg, "" if j is None else ("ja" if j else "nein")]
                for s, mg, j in pts])
    sec.artifacts.append(out / "margin_vs_setsize.csv")
    if not pts:
        sec.skipped = "keine Fälle mit Margin und Kandidaten."
        return sec
    rng = np.random.default_rng(0)          # deterministischer Jitter (reproduzierbar)
    jit = rng.uniform(-0.12, 0.12, len(pts))
    fig, ax = plt.subplots(figsize=(7, 4))
    for (s, mg, j), dx in zip(pts, jit):
        col = _C_OK if j else (_C_BAD if j is False else "0.6")
        ax.scatter(s + dx, mg, s=26, color=col, alpha=0.8,
                   edgecolors="white", linewidths=0.4, zorder=3)
    bysize: dict = {}
    for s, mg, _ in pts:
        bysize.setdefault(s, []).append(mg)
    xs = sorted(bysize)
    ax.plot(xs, [float(np.median(bysize[s])) for s in xs], color="0.25", lw=1,
            marker="o", ms=4, zorder=4, label="Median je Setgröße")
    ax.axhline(gate, color="black", ls="--", label=f"Gate {gate}")
    ax.set_xlabel("Kandidatensetgröße")
    ax.set_ylabel("LLR-Margin")
    ax.set_xticks(xs)
    ax.set_title(f"Margin vs. Kandidatensetgröße (n={len(pts)})")
    ax.legend()
    _finish(fig, out / "margin_vs_setsize.png", run_id)
    sec.artifacts.insert(0, out / "margin_vs_setsize.png")
    return sec


def _analysis_diameter_vs_nominal(reports, out: Path, run_id: str, cfg: dict) -> _Section:
    """(6) Ø gemessen gegen DB-Nominal je Artikel, +/-6 mm Band, Messstreuung."""
    sec = _Section("F) Ø gemessen gegen DB-Nominal")
    meas: dict = {}
    nominal: dict = {}
    for r in reports:
        d = (r.measured or {}).get("circle_diameter_mm")
        if not r.label or d is None:
            continue
        meas.setdefault(r.label, []).append(d)
        for c in r.candidates:
            if c.article_number == r.label:
                nominal[r.label] = c.nominal_size_mm
                break
    arts = [a for a in meas if a in nominal]
    _write_csv(out / "diameter_vs_nominal.csv", ["article", "nominal_mm", "messungen_mm"],
               [[a, nominal[a], ";".join(f"{v:.2f}" for v in meas[a])] for a in arts])
    sec.artifacts.append(out / "diameter_vs_nominal.csv")
    if not arts:
        sec.skipped = "keine gelabelten Messungen mit Nominal im Kandidaten."
        return sec
    arts.sort(key=lambda a: nominal[a])
    fig, ax = plt.subplots(figsize=(max(7, 0.5 * len(arts) + 2), 4.5))
    x = np.arange(len(arts))
    noms = np.array([nominal[a] for a in arts])
    ax.fill_between(x, noms - _TOL_MM, noms + _TOL_MM, color="0.85",
                    label=f"±{_TOL_MM:.0f} mm")
    ax.plot(x, noms, "s", color="0.25", ms=5, label="DB-Nominal")
    for xi, a in zip(x, arts):
        vs = meas[a]
        ax.scatter([xi] * len(vs), vs, s=18, color=PALETTE[0], alpha=0.7,
                   edgecolors="white", linewidths=0.3, zorder=3)
    ax.set_xticks(x, arts, rotation=45, ha="right")
    ax.set_ylabel("Ø / Nominal [mm]")
    ax.set_title(f"Ø gemessen vs. DB-Nominal (n={len(arts)} Artikel)")
    ax.legend()
    _finish(fig, out / "diameter_vs_nominal.png", run_id)
    sec.artifacts.insert(0, out / "diameter_vs_nominal.png")
    return sec


def _analysis_true_rank(reports, out: Path, run_id: str, cfg: dict) -> _Section:
    """(7) Rang des wahren Artikels: 1/2/3/>3/nicht im Set, gesamt und je Artikel."""
    sec = _Section("G) Rang des wahren Artikels")
    labeled = [r for r in reports if r.label]
    if not labeled:
        sec.skipped = "keine Reports mit Label."
        return sec

    def bucket(r):
        rk = _true_rank(r)
        return "nicht im Set" if rk is None else ({1: "1", 2: "2", 3: "3"}.get(rk, ">3"))

    per: dict = {}
    for r in labeled:
        per.setdefault(r.label, Counter())[bucket(r)] += 1
    total = Counter(bucket(r) for r in labeled)
    _write_csv(out / "true_rank.csv", ["article"] + _RANK_ORDER,
               [[a] + [per[a].get(k, 0) for k in _RANK_ORDER] for a in sorted(per)])
    sec.artifacts.append(out / "true_rank.csv")

    arts = sorted(per, key=lambda a: (-per[a].get("1", 0) / max(1, sum(per[a].values()))))
    fig, axes = plt.subplots(1, 2, figsize=(max(9, 0.5 * len(arts) + 4), 4.2),
                             gridspec_kw={"width_ratios": [1, max(2, len(arts) * 0.4)]})
    axes[0].bar(range(len(_RANK_ORDER)), [total.get(k, 0) for k in _RANK_ORDER],
                color=[_RANK_COLORS[k] for k in _RANK_ORDER])
    axes[0].set_xticks(range(len(_RANK_ORDER)), _RANK_ORDER, rotation=45, ha="right")
    axes[0].set_ylabel("Anzahl")
    axes[0].set_title(f"gesamt (n={len(labeled)})")
    x = np.arange(len(arts))
    bottom = np.zeros(len(arts))
    for k in _RANK_ORDER:
        h = np.array([per[a].get(k, 0) for a in arts])
        axes[1].bar(x, h, bottom=bottom, color=_RANK_COLORS[k], label=k, width=0.8)
        bottom += h
    axes[1].set_xticks(x, arts, rotation=45, ha="right")
    axes[1].set_ylabel("Anzahl")
    axes[1].set_title("je Artikel – bester Rang-1-Anteil zuerst")
    axes[1].legend(title="Rang", ncol=len(_RANK_ORDER))
    _finish(fig, out / "true_rank.png", run_id)
    sec.artifacts.insert(0, out / "true_rank.png")
    return sec


def _analysis_decision_per_article(reports, out: Path, run_id: str, cfg: dict) -> _Section:
    """(8) Entscheidung je Artikel: accept/ambiguous/reject, nach Accept-Anteil."""
    sec = _Section("H) Entscheidung je Artikel")
    labeled = [r for r in reports if r.label]
    if not labeled:
        sec.skipped = "keine Reports mit Label."
        return sec
    per: dict = {}
    for r in labeled:
        per.setdefault(r.label, Counter())[r.decision] += 1
    order = ["accept", "ambiguous", "reject"]
    _write_csv(out / "decision_per_article.csv", ["article"] + order,
               [[a] + [per[a].get(k, 0) for k in order] for a in sorted(per)])
    sec.artifacts.append(out / "decision_per_article.csv")
    arts = sorted(per, key=lambda a: -per[a].get("accept", 0) / max(1, sum(per[a].values())))
    fig, ax = plt.subplots(figsize=(max(7, 0.5 * len(arts) + 2), 4.5))
    x = np.arange(len(arts))
    bottom = np.zeros(len(arts))
    for k in order:
        h = np.array([per[a].get(k, 0) for a in arts])
        ax.bar(x, h, bottom=bottom, color=_DECISION_COLORS[k], label=k, width=0.8)
        bottom += h
    ax.set_xticks(x, arts, rotation=45, ha="right")
    ax.set_ylabel("Anzahl Identifikationen")
    ax.set_title(f"Entscheidung je Artikel – höchster Accept-Anteil zuerst (n={len(arts)})")
    ax.legend()
    _finish(fig, out / "decision_per_article.png", run_id)
    sec.artifacts.insert(0, out / "decision_per_article.png")
    return sec


def _analysis_z_per_feature(reports, out: Path, run_id: str, cfg: dict) -> _Section:
    """(3) |z| des Siegers je Merkmal, korrekt vs. falsch, Linie = max_z_accept."""
    sec = _Section("I) |z| des Siegers je Merkmal")
    zcap = float(cfg.get("matching", {}).get("max_z_accept", 3.5))
    data: dict = {}
    for r in reports:
        j = judgement(r)
        top = _top1(r)
        if j is None or not top:
            continue
        for fs in top.features:
            d = data.setdefault(fs.feature, {"ok": [], "bad": []})
            (d["ok"] if j else d["bad"]).append(abs(fs.z))
    if not data:
        sec.skipped = "keine bewerteten Sieger mit Merkmals-z."
        return sec
    feats = list(data)
    _write_csv(out / "z_per_feature.csv", ["feature", "korrekt", "abs_z"],
               [[f, k, v] for f in feats for k, key in [("ja", "ok"), ("nein", "bad")]
                for v in data[f][key]])
    sec.artifacts.append(out / "z_per_feature.csv")
    ncol = 4
    nrow = math.ceil(len(feats) / ncol)
    fig, axes = plt.subplots(nrow, ncol, figsize=(3.0 * ncol, 2.3 * nrow),
                             squeeze=False)
    for idx, f in enumerate(feats):
        ax = axes[idx // ncol][idx % ncol]
        ok, bad = data[f]["ok"], data[f]["bad"]
        bins = np.linspace(0, max(ok + bad + [zcap]) * 1.05, 14)
        ax.hist(ok, bins=bins, color=_C_OK, alpha=0.6)
        if bad:
            ax.hist(bad, bins=bins, color=_C_BAD, alpha=0.6)
        ax.axvline(zcap, color="black", ls="--", lw=0.8)
        ax.set_title(f, fontsize=8)
        if idx % ncol == 0:
            ax.set_ylabel("Anzahl")
    for idx in range(len(feats), nrow * ncol):
        axes[idx // ncol][idx % ncol].set_axis_off()
    fig.suptitle(f"|z| des Siegers je Merkmal – korrekt (grün) vs. falsch (rot), "
                 f"gestrichelt = max_z_accept {zcap}", fontsize=9)
    _finish(fig, out / "z_per_feature.png", run_id)
    sec.artifacts.insert(0, out / "z_per_feature.png")
    return sec


def _analysis_prefilter(reports, out: Path, run_id: str, cfg: dict) -> _Section:
    """(4) Vorfilter-Trichter je Artikel: wo landet der WAHRE Artikel?
    Rang 1 / im Set (schlechter) / vom Vorfilter gekillt (Durchmesser knapp
    bzw. weit über der Toleranz / Fläche) / nicht im Set. Die Kill-Gründe
    kommen aus report.prefiltered (Messpfad-Runde 2026-07-29); Reports ohne das
    Feld (Altbestand) zeigen Kills als „nicht im Set", weil der Grund fehlt."""
    sec = _Section("K) Vorfilter-Trichter (wahrer Artikel im Kandidatenset?)")
    labeled = [r for r in reports if r.label]
    if not labeled:
        sec.skipped = "keine Reports mit Label."
        return sec
    cats = ["Rang 1", "im Set (schlechter)", "Kill Ø (knapp)", "Kill Ø (weit)",
            "Kill Fläche", "nicht im Set"]
    colors = {"Rang 1": "#1baf7a", "im Set (schlechter)": "#eda100",
              "Kill Ø (knapp)": "#e34948",     # rot: knapp = riskant (fast Kandidat)
              "Kill Ø (weit)": "#f4a9a6",      # blass: weit = klar anderer Artikel
              "Kill Fläche": "#8c6d31", "nicht im Set": "#9aa0a6"}

    def cat(r):
        rk = _true_rank(r)
        if rk == 1:
            return "Rang 1"
        if rk is not None:
            return "im Set (schlechter)"
        # Nicht unter den Kandidaten: Kill-Grund aus prefiltered nachschlagen.
        kill = next((e for e in (r.prefiltered or [])
                     if e.get("article_number") == r.label), None)
        if kill is None:
            return "nicht im Set"        # Altbestand ohne Feld o. Sondersize
        if kill.get("reason") == "area":
            return "Kill Fläche"
        over = kill.get("over_tolerance_mm") or 0.0
        tol = kill.get("tolerance_mm") or 0.0
        return "Kill Ø (knapp)" if over <= tol else "Kill Ø (weit)"

    per: dict = {}
    for r in labeled:
        per.setdefault(r.label, Counter())[cat(r)] += 1
    _write_csv(out / "prefilter_funnel.csv", ["article"] + cats,
               [[a] + [per[a].get(k, 0) for k in cats] for a in sorted(per)])
    sec.artifacts.append(out / "prefilter_funnel.csv")
    sec.notes.append(
        "Kill-Gründe (Durchmesser knapp/weit, Fläche) stammen aus "
        "report.prefiltered; „knapp\" = over_tolerance_mm ≤ Toleranz (fast noch "
        "Kandidat, risikonah). Reports ohne das Feld (Altbestand) zählen Kills "
        "als „nicht im Set\".")
    arts = sorted(per, key=lambda a: -per[a].get("Rang 1", 0) / max(1, sum(per[a].values())))
    fig, ax = plt.subplots(figsize=(max(7, 0.5 * len(arts) + 2), 4.8))
    x = np.arange(len(arts))
    bottom = np.zeros(len(arts))
    for k in cats:
        h = np.array([per[a].get(k, 0) for a in arts])
        ax.bar(x, h, bottom=bottom, color=colors[k], label=k, width=0.8)
        bottom += h
    ax.set_xticks(x, arts, rotation=45, ha="right")
    ax.set_ylabel("Anzahl Identifikationen")
    ax.set_title(f"Vorfilter-Trichter je Artikel (n={len(arts)})")
    ax.legend(fontsize=7, ncol=2)
    fig.text(0.5, 0.005, "Kill-Gründe aus report.prefiltered: Durchmesser knapp "
             "(over ≤ Toleranz, risikonah) vs. weit, oder Fläche.  „nicht im "
             "Set\" = kein Kandidat und kein Kill-Eintrag (u.a. Altbestand vor "
             "dem Feld).", ha="center", va="bottom", fontsize=7, color="0.3")
    _finish(fig, out / "prefilter_funnel.png", run_id)
    sec.artifacts.insert(0, out / "prefilter_funnel.png")
    return sec


def _analysis_test_vs_enroll(reports, out: Path, run_id: str, cfg: dict) -> _Section:
    """(10) Std der Testmessungen (Ø) gegen sigma_enroll je Artikel, Diagonale.
    Punkte oberhalb = Enrollment-Streuung war zu optimistisch."""
    sec = _Section("L) Teststreuung gegen Enrollment-Streuung")
    meas: dict = {}
    sig: dict = {}
    for r in reports:
        d = (r.measured or {}).get("circle_diameter_mm")
        if not r.label or d is None:
            continue
        meas.setdefault(r.label, []).append(d)
        if r.label not in sig:
            for c in r.candidates:
                if c.article_number == r.label:
                    for f in c.features:
                        if f.feature == "diameter_mm":
                            sig[r.label] = f.sigma_enroll
                    break
    arts = [a for a in meas if a in sig and len(meas[a]) >= 2]
    _write_csv(out / "test_vs_enroll.csv", ["article", "sigma_enroll", "test_std", "n"],
               [[a, round(sig[a], 4), round(float(np.std(meas[a], ddof=1)), 4),
                 len(meas[a])] for a in arts])
    sec.artifacts.append(out / "test_vs_enroll.csv")
    if not arts:
        sec.skipped = "keine Artikel mit >=2 Messungen und sigma_enroll."
        return sec
    xs = np.array([sig[a] for a in arts])
    ys = np.array([float(np.std(meas[a], ddof=1)) for a in arts])
    fig, ax = plt.subplots(figsize=(6, 6))
    hi = float(max(xs.max(), ys.max())) * 1.15 + 0.1
    ax.plot([0, hi], [0, hi], color="0.5", ls="--", lw=1, label="Diagonale (gleich)")
    ax.scatter(xs, ys, s=30, color=PALETTE[0], edgecolors="white", linewidths=0.4,
               zorder=3)
    for a, xv, yv in zip(arts, xs, ys):
        ax.annotate(a, (xv, yv), fontsize=6.5, xytext=(3, 3),
                    textcoords="offset points")
    ax.set_xlim(0, hi)
    ax.set_ylim(0, hi)
    ax.set_aspect("equal")
    ax.set_xlabel("σ_enroll (Ø) [mm]")
    ax.set_ylabel("Std der Testmessungen (Ø) [mm]")
    ax.set_title("Teststreuung vs. Enrollment-Streuung – oberhalb = zu optimistisch")
    ax.legend()
    _finish(fig, out / "test_vs_enroll.png", run_id)
    sec.artifacts.insert(0, out / "test_vs_enroll.png")
    return sec


def _drift_breite(m: dict) -> tuple:
    """(Breite_mm, gemessen?): lat_p98 wenn im Report vorhanden und > 0
    (echte Nebenachsen-Messung), sonst der Ø·aspect_ratio-Proxy (an Ø
    gekoppelt, keine unabhängige Messung → abgeleitet)."""
    lat = m.get("lat_p98_mm") or 0.0
    if lat > 0:
        return float(lat), True
    return float(m["circle_diameter_mm"]) * (m.get("aspect_ratio") or 0.0), False


def _analysis_drift(reports, out: Path, run_id: str, cfg: dict) -> _Section:
    """(9) Drift ueber die Session: zwei gestapelte Panels (Ø, Breite) mit
    GEMEINSAMER x-Achse (Identifikationsreihenfolge), keine zweite y-Achse.
    Auffaellige Artikel (hohe Ø-Streuung) farbig, Rest grau. Breite = lat_p98
    (gemessen, gefuellte Marker) wo im Report vorhanden, sonst Ø·aspect_ratio-
    Proxy (abgeleitet, hohle Marker)."""
    sec = _Section("M) Drift über die Testsession")
    rows = sorted([r for r in reports
                   if r.label and (r.measured or {}).get("circle_diameter_mm") is not None],
                  key=_order_key)
    if len(rows) < 2:
        sec.skipped = "zu wenige Messungen für einen Drift-Verlauf."
        return sec
    per: dict = {}
    points: list = []               # je Zeile (i, dia, wid, gemessen?), fuer die CSV
    n_measured = 0
    for i, r in enumerate(rows):
        m = r.measured
        dia = m["circle_diameter_mm"]
        wid, is_meas = _drift_breite(m)
        n_measured += is_meas
        points.append((i, dia, wid, is_meas))
        per.setdefault(r.label, []).append((i, dia, wid, is_meas))
    n_derived = len(rows) - n_measured
    stds = {a: float(np.std([p[1] for p in v], ddof=1)) if len(v) >= 2 else 0.0
            for a, v in per.items()}
    pos = [s for s in stds.values() if s > 0]
    med = float(np.median(pos)) if pos else 0.0
    conspic = sorted([a for a in per if stds[a] > max(1.0, 2 * med)],
                     key=lambda a: -stds[a])[:4]
    cmap = {a: PALETTE[i] for i, a in enumerate(conspic)}
    _write_csv(out / "drift.csv",
               ["order", "report", "article", "diameter_mm", "breite_mm",
                "breite_quelle"],
               [[i, Path(r.report_path).stem if r.report_path else "", r.label,
                 round(dia, 2), round(wid, 2), "lat_p98" if meas else "proxy"]
                for (i, dia, wid, meas), r in zip(points, rows)])
    sec.artifacts.append(out / "drift.csv")
    sec.notes.append(
        f"Breite Panel b: lat_p98 gemessen (gefüllte Marker, N={n_measured}) wo "
        f"im Report vorhanden, sonst Ø·aspect_ratio-Proxy (abgeleitet, hohle "
        f"Marker, N={n_derived}). Reports vor dem lat_p98-Feld sind Proxy.")
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(max(8, len(rows) * 0.22 + 3), 7),
                                   sharex=True)
    for a, v in per.items():
        v = sorted(v)
        xs = [p[0] for p in v]
        dias = [p[1] for p in v]
        wids = [p[2] for p in v]
        meas = [p[3] for p in v]
        colored = a in cmap
        color = cmap[a] if colored else "0.7"
        ms = 4 if colored else 3
        alpha = 1.0 if colored else 0.6
        # Panel a (Ø): wie gehabt – farbige mit Linie, graue nur Marker.
        if colored:
            ax1.plot(xs, dias, "-o", color=color, ms=ms, lw=1, label=a)
        else:
            ax1.plot(xs, dias, "o", color=color, ms=ms, alpha=alpha)
        # Panel b (Breite): Linie nur fuer farbige; Marker gefuellt=gemessen
        # (lat_p98), hohl=abgeleitet (Proxy).
        if colored:
            ax2.plot(xs, wids, "-", color=color, lw=1)
        mkw = {"ms": ms} if colored else {"ms": ms, "alpha": alpha}
        fx = [x for x, mm in zip(xs, meas) if mm]
        fw = [w for w, mm in zip(wids, meas) if mm]
        hx = [x for x, mm in zip(xs, meas) if not mm]
        hw = [w for w, mm in zip(wids, meas) if not mm]
        if fx:
            ax2.plot(fx, fw, "o", color=color, **mkw)
        if hx:
            ax2.plot(hx, hw, "o", mfc="none", mec=color, **mkw)
    ax1.set_ylabel("Ø [mm]")
    ax2.set_ylabel("Breite [mm]")
    ax2.set_xlabel("Identifikation in Aufnahmereihenfolge")
    ax1.set_title(f"Drift über die Testsession (n={len(rows)}) – "
                  "auffällige Artikel farbig, Rest grau")
    if conspic:
        ax1.legend(title="auffällig (hohe Ø-Streuung)", fontsize=6.5,
                   ncol=min(4, len(conspic)))
    panel_label(ax1, "a")
    panel_label(ax2, "b")
    fig.text(0.5, 0.02, "x = Identifikationsreihenfolge (report_path-ms), NICHT "
             "Auslösezeitpunkt.  Breite Panel b: lat_p98 gemessen (gefüllt) / "
             "Ø·aspect_ratio-Proxy abgeleitet (hohl).",
             ha="center", va="bottom", fontsize=7, color="0.3")
    _finish(fig, out / "drift.png", run_id)
    sec.artifacts.insert(0, out / "drift.png")
    return sec


def _analysis_discriminability(reports, out: Path, run_id: str, cfg: dict) -> _Section:
    """(1) Trennschärfe je Merkmal fuer alle Artikelpaare, die je gemeinsam im
    Kandidatenset waren: |Lagendifferenz| / sigma_eff (Skalare) bzw.
    Prototyp-Distanz / sigma_eff (Vektoren), aus der DB (reference_stats).
    Zeilen nach Maximum sortiert (oben trennbar, unten hoffnungslos)."""
    from itertools import combinations

    from .database import Database
    from .features import PROTO_FEATURES, SCALAR_FEATURES, _PROTO_SRC

    sec = _Section("N) Trennschärfe-Matrix (Artikelpaare × Merkmale)")
    pairs: set = set()
    involved: set = set()
    for r in reports:
        arts = sorted({c.article_number for c in r.candidates if c.has_references})
        for a, b in combinations(arts, 2):
            pairs.add((a, b))
            involved.update((a, b))
    if not pairs:
        sec.skipped = "keine Artikelpaare in gemeinsamen Kandidatensets."
        return sec
    db = Database(cfg)
    try:
        stats = {a: db.stats_for(a) for a in involved}
    finally:
        db.close()
    floors = cfg.get("matching", {}).get("sigma_floors", {})
    feats = list(SCALAR_FEATURES) + list(PROTO_FEATURES)

    def sep(a, b, f):
        sa, sb = stats.get(a), stats.get(b)
        if not sa or not sb:
            return np.nan
        # ueber _FLOOR_KEY, nicht ueber den Merkmalsnamen: zwei Zonen teilen
        # sich einen Floor (delta_e_center/-_rim -> delta_e, hist_* ->
        # hist_bhattacharyya). Direkt nachgeschlagen liefern genau diese vier
        # Farbmerkmale 0.0 und erscheinen dadurch 1,3-2,3x trennschaerfer als
        # sie sind (docs/2026-08-01-analysis-floor-key-befund.md).
        floor = float(floors.get(_FLOOR_KEY.get(f, f), 0.0))
        if f in SCALAR_FEATURES:
            ma, mb = sa.scalar_mean.get(f), sb.scalar_mean.get(f)
            if ma is None or mb is None:
                return np.nan
            va, vb = sa.scalar_std.get(f, 0.0), sb.scalar_std.get(f, 0.0)
            loc = abs(ma - mb)
        else:
            pa, pb = sa.proto.get(f), sb.proto.get(f)
            if not pa or not pb or len(pa) != len(pb):
                return np.nan
            loc = _PROTO_SRC[f][1](pa, pb)      # Prototyp-Distanz
            va, vb = sa.proto_std.get(f, 0.0), sb.proto_std.get(f, 0.0)
        seff = math.sqrt((max(va, floor) ** 2 + max(vb, floor) ** 2) / 2)
        if seff <= 0:
            # Kein Floor UND beidseitig keine Streuung (z.B. 1-Shot-Artikel:
            # _proto_stats gibt bei <2 Vektoren 0 zurueck). Das ist keine
            # sinnvolle Vergleichsseite. Frueher zog hier ein `or 1e-9` und
            # erzeugte Trennschaerfen der Groessenordnung 1e10, die zusaetzlich
            # Sortierung und Farbskala der Matrix bestimmten. NaN ist ehrlich
            # und wird von cmap.set_bad bereits maskiert.
            return np.nan
        return loc / seff

    mat = np.array([[sep(a, b, f) for f in feats] for a, b in sorted(pairs)],
                   dtype=float)
    labels = [f"{a} / {b}" for a, b in sorted(pairs)]
    maxcol = np.nanmax(np.where(np.isnan(mat), -np.inf, mat), axis=1)
    order = np.argsort(-np.where(np.isfinite(maxcol), maxcol, -np.inf))
    mat, labels, maxcol = mat[order], [labels[i] for i in order], maxcol[order]
    _write_csv(out / "discriminability.csv", ["pair"] + feats + ["max"],
               [[labels[i]] + [round(v, 3) if np.isfinite(v) else "" for v in mat[i]]
                + [round(maxcol[i], 3) if np.isfinite(maxcol[i]) else ""]
                for i in range(len(labels))])
    sec.artifacts.append(out / "discriminability.csv")
    show = np.column_stack([mat, maxcol])
    cols = feats + ["max"]
    fig, ax = plt.subplots(figsize=(max(7, 0.55 * len(cols) + 3),
                                    max(3.5, 0.4 * len(labels) + 2)))
    cmap = plt.get_cmap(SEQ).copy()
    cmap.set_bad("0.85")
    im = ax.imshow(np.ma.masked_invalid(show), cmap=cmap, aspect="auto", vmin=0)
    ax.set_xticks(range(len(cols)), cols, rotation=45, ha="right")
    ax.set_yticks(range(len(labels)), labels)
    ax.axvline(len(feats) - 0.5, color="white", lw=2)     # "max"-Spalte absetzen
    ax.set_title("Trennschärfe |Δ| / σ_eff je Merkmal – oben trennbar, unten hoffnungslos")
    cb = fig.colorbar(im, ax=ax, fraction=0.05, pad=0.02)
    cb.set_label("Trennschärfe (σ_eff-Einheiten)", fontsize=7)
    _finish(fig, out / "discriminability.png", run_id)
    sec.artifacts.insert(0, out / "discriminability.png")
    return sec


def _analysis_querschnitt(reports, out: Path, run_id: str, cfg: dict) -> _Section:
    """Querschnitt: (2),(4),(7),(8),(9) als Panels a-e auf einem PNG – die Seite,
    die man nach einem Testtag zuerst anschaut. Kompakte Neu-Zeichnungen ueber
    dieselben Daten-Helfer (keine Messlogik dupliziert)."""
    sec = _Section("O) Querschnitt (Testtag-Übersicht)")
    labeled = [r for r in reports if r.label]
    if not labeled:
        sec.skipped = "keine Reports mit Label."
        return sec
    m = cfg.get("matching", {})
    gate = float(m.get("min_llr_margin", 2.0))
    fig = plt.figure(figsize=(13, 12))
    gs = fig.add_gridspec(3, 2, height_ratios=[1, 1, 1.1], hspace=0.55, wspace=0.22)

    # a: (2) Margin korrekt/falsch
    ax = fig.add_subplot(gs[0, 0])
    panel_label(ax, "a")
    judged = [(r.llr_margin, judgement(r)) for r in reports
              if r.llr_margin is not None and judgement(r) is not None]
    if judged:
        good = [mg for mg, j in judged if j]
        bad = [mg for mg, j in judged if not j]
        bins = np.linspace(0, max([mg for mg, _ in judged] + [gate]) * 1.05, 20)
        ax.hist(good, bins=bins, color=_C_OK, alpha=0.6, label=f"korrekt ({len(good)})")
        ax.hist(bad, bins=bins, color=_C_BAD, alpha=0.6, label=f"falsch ({len(bad)})")
        ax.axvline(gate, color="black", ls="--")
        ax.legend()
    ax.set_title("LLR-Margin korrekt vs. falsch")
    ax.set_xlabel("LLR-Margin")

    # b: (4) Vorfilter-Trichter
    ax = fig.add_subplot(gs[0, 1])
    panel_label(ax, "b")
    cats = ["Rang 1", "im Set (schlechter)", "nicht im Set"]
    cc = {"Rang 1": "#1baf7a", "im Set (schlechter)": "#eda100", "nicht im Set": "#e34948"}
    per: dict = {}
    for r in labeled:
        rk = _true_rank(r)
        k = "nicht im Set" if rk is None else ("Rang 1" if rk == 1 else "im Set (schlechter)")
        per.setdefault(r.label, Counter())[k] += 1
    arts = sorted(per, key=lambda a: -per[a].get("Rang 1", 0) / max(1, sum(per[a].values())))
    x = np.arange(len(arts))
    bottom = np.zeros(len(arts))
    for k in cats:
        h = np.array([per[a].get(k, 0) for a in arts])
        ax.bar(x, h, bottom=bottom, color=cc[k], label=k, width=0.85)
        bottom += h
    ax.set_xticks(x, arts, rotation=45, ha="right", fontsize=6)
    ax.set_title("Vorfilter-Trichter je Artikel")
    ax.legend(fontsize=6)

    # c: (7) Rang gesamt
    ax = fig.add_subplot(gs[1, 0])
    panel_label(ax, "c")
    total = Counter("nicht im Set" if _true_rank(r) is None
                    else {1: "1", 2: "2", 3: "3"}.get(_true_rank(r), ">3") for r in labeled)
    ax.bar(range(len(_RANK_ORDER)), [total.get(k, 0) for k in _RANK_ORDER],
           color=[_RANK_COLORS[k] for k in _RANK_ORDER])
    ax.set_xticks(range(len(_RANK_ORDER)), _RANK_ORDER, rotation=45, ha="right")
    ax.set_title(f"Rang des wahren Artikels (gesamt, n={len(labeled)})")

    # d: (8) Entscheidung je Artikel
    ax = fig.add_subplot(gs[1, 1])
    panel_label(ax, "d")
    dper: dict = {}
    for r in labeled:
        dper.setdefault(r.label, Counter())[r.decision] += 1
    darts = sorted(dper, key=lambda a: -dper[a].get("accept", 0) / max(1, sum(dper[a].values())))
    x = np.arange(len(darts))
    bottom = np.zeros(len(darts))
    for k in ["accept", "ambiguous", "reject"]:
        h = np.array([dper[a].get(k, 0) for a in darts])
        ax.bar(x, h, bottom=bottom, color=_DECISION_COLORS[k], label=k, width=0.85)
        bottom += h
    ax.set_xticks(x, darts, rotation=45, ha="right", fontsize=6)
    ax.set_title("Entscheidung je Artikel")
    ax.legend(fontsize=6)

    # e: (9) Drift Ø (kompakt, einauflösung)
    ax = fig.add_subplot(gs[2, :])
    panel_label(ax, "e")
    rows = sorted([r for r in labeled
                   if (r.measured or {}).get("circle_diameter_mm") is not None],
                  key=_order_key)
    dper2: dict = {}
    for i, r in enumerate(rows):
        dper2.setdefault(r.label, []).append((i, r.measured["circle_diameter_mm"]))
    stds = {a: float(np.std([p[1] for p in v], ddof=1)) if len(v) >= 2 else 0.0
            for a, v in dper2.items()}
    pos = [s for s in stds.values() if s > 0]
    medst = float(np.median(pos)) if pos else 0.0
    conspic = sorted([a for a in dper2 if stds[a] > max(1.0, 2 * medst)],
                     key=lambda a: -stds[a])[:4]
    cmap = {a: PALETTE[i] for i, a in enumerate(conspic)}
    for a, v in dper2.items():
        v = sorted(v)
        xs, ys = [p[0] for p in v], [p[1] for p in v]
        if a in cmap:
            ax.plot(xs, ys, "-o", color=cmap[a], ms=4, lw=1, label=a)
        else:
            ax.plot(xs, ys, "o", color="0.7", ms=3, alpha=0.6)
    if conspic:
        ax.legend(title="auffällig", fontsize=6, ncol=min(4, len(conspic)))
    ax.set_title("Drift Ø über die Session (Reihenfolge = report_path-ms)")
    ax.set_xlabel("Identifikation in Aufnahmereihenfolge")
    ax.set_ylabel("Ø [mm]")

    fig.suptitle(f"Querschnitt Testtag – {run_id} (n={len(labeled)} gelabelte Identifikationen)",
                 fontsize=12, fontweight="bold", y=0.995)
    fig.savefig(out / "querschnitt.png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    sec.artifacts.insert(0, out / "querschnitt.png")
    return sec


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
    apply_style()   # zentraler Plot-Stil (plotstyle) fuer alle 6 Artefakte

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
        # STUFE B
        sections.append(_analysis_margin(reports, out, run_id, cfg))
        sections.append(_analysis_margin_vs_setsize(reports, out, run_id, cfg))
        sections.append(_analysis_diameter_vs_nominal(reports, out, run_id, cfg))
        sections.append(_analysis_true_rank(reports, out, run_id, cfg))
        sections.append(_analysis_decision_per_article(reports, out, run_id, cfg))
        sections.append(_analysis_z_per_feature(reports, out, run_id, cfg))
        sections.append(_analysis_prefilter(reports, out, run_id, cfg))
        sections.append(_analysis_test_vs_enroll(reports, out, run_id, cfg))
        sections.append(_analysis_drift(reports, out, run_id, cfg))
        sections.append(_analysis_discriminability(reports, out, run_id, cfg))
        sections.append(_analysis_querschnitt(reports, out, run_id, cfg))

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
