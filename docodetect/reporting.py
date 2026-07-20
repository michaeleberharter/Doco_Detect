"""Batch-Aggregation über MatchReport-JSONs.

EINE Implementierung für beide Konsumenten: der CLI-Befehl `evaluate` und
der Batch-Tab der Streamlit-Seite "Scoring-Analyse" rechnen exakt dieselben
Kennzahlen (Accuracy, Verwechslungspaare, Entscheidungsanteile, Posterior-
Verteilungen korrekt vs. falsch). Labels kommen aus `MatchReport.label`
(gesetzt von `evaluate` bzw. beim Identify mit bekannter Wahrheit).
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .matcher import MatchReport

NO_MATCH = "NO_MATCH"


def predicted_article(report: MatchReport) -> str:
    """Top-1-Vorhersage eines Reports; NO_MATCH wenn kein Kandidat übrig blieb."""
    return report.candidates[0].article_number if report.candidates else NO_MATCH


def judgement(report: MatchReport) -> bool | None:
    """War die Vorhersage richtig? True/False wenn beurteilbar, None wenn
    weder menschliches Feedback (verdict) noch ein Label vorliegt. Ein
    manuelles Urteil hat Vorrang vor dem Label-Vergleich."""
    if report.verdict == "correct":
        return True
    if report.verdict == "wrong":
        return False
    if report.label:
        return predicted_article(report) == report.label
    return None


def save_verdict(report: MatchReport, correct: bool,
                 true_article: str | None = None) -> Path:
    """Menschliches Feedback ("stimmt" / "stimmt nicht") in das gespeicherte
    Report-JSON zurückschreiben – Grundlage für Erfolgsrate und Fehlerliste
    im Batch-Tab. Bei "richtig" wird die Top-1-Vorhersage als Label
    übernommen; bei "falsch" der übergebene wahre Artikel (None = unbekannt,
    ein evtl. vorhandenes evaluate-Label bleibt dann stehen)."""
    if not report.report_path:
        raise ValueError("Report wurde nie gespeichert (paths.captures_dir "
                         "fehlte) – Bewertung kann nicht abgelegt werden.")
    report.verdict = "correct" if correct else "wrong"
    if correct:
        report.label = predicted_article(report)
    elif true_article:
        report.label = true_article
    p = Path(report.report_path)
    p.write_text(report.to_json(), encoding="utf-8")
    return p


@dataclass
class BatchSummary:
    total: int = 0
    labeled: int = 0
    correct: int = 0
    accuracy: float = 0.0                # correct/labeled; 0.0 wenn labeled == 0
    decision_counts: dict = field(default_factory=dict)
    confusion: list = field(default_factory=list)   # (truth, predicted, n), nur Fehler
    posteriors_correct: list = field(default_factory=list)
    posteriors_wrong: list = field(default_factory=list)
    per_class: dict = field(default_factory=dict)   # truth -> {predicted: n}


def summarize(reports: list[MatchReport]) -> BatchSummary:
    s = BatchSummary(total=len(reports))
    decisions: Counter = Counter()
    confusion: Counter = Counter()
    per_class: dict = defaultdict(Counter)
    for r in reports:
        decisions[r.decision] += 1
        pred = predicted_article(r)
        top_post = r.candidates[0].posterior if r.candidates else 0.0
        ok = judgement(r)
        if ok is None:
            continue                       # weder Feedback noch Label -> unbewertet
        s.labeled += 1
        if r.label:
            per_class[r.label][pred] += 1
        if ok:
            s.correct += 1
            s.posteriors_correct.append(top_post)
        else:
            # unbekannte Wahrheit (Feedback "falsch" ohne Artikelangabe) -> "?"
            confusion[(r.label or "?", pred)] += 1
            s.posteriors_wrong.append(top_post)
    s.accuracy = s.correct / s.labeled if s.labeled else 0.0
    s.decision_counts = dict(decisions)
    s.confusion = [(t, p, n) for (t, p), n in confusion.most_common()]
    s.per_class = {t: dict(c) for t, c in per_class.items()}
    return s


def load_reports(folder: str | Path,
                 limit: int | None = None) -> list[tuple[Path, MatchReport]]:
    """Alle Report-JSONs eines Ordners, nach mtime absteigend (neueste zuerst).
    Defekte/fremde JSONs werden übersprungen statt die Ansicht zu killen."""
    folder = Path(folder)
    if not folder.is_dir():
        return []
    out: list[tuple[Path, MatchReport]] = []
    for p in sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime,
                    reverse=True):
        try:
            rep = MatchReport.from_json(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, TypeError, KeyError):
            continue
        # tatsächlichen Ablageort setzen (überschreibt evtl. veraltete Pfade
        # von anderen Rechnern) -> save_verdict schreibt garantiert hierhin
        rep.report_path = str(p)
        out.append((p, rep))
        if limit is not None and len(out) >= limit:
            break
    return out


def top_k_accuracy(reports: list, k: int) -> tuple:
    """(Treffer, gewertete) – wie oft liegt der wahre Artikel unter den ersten
    k Kandidaten? Gewertet wird nur, was eine Wahrheit trägt (Label oder
    menschliches Verdict mit wahrem Artikel)."""
    hit = scored = 0
    for r in reports:
        truth = r.label
        if not truth:
            continue
        scored += 1
        if truth in [c.article_number for c in r.candidates[:k]]:
            hit += 1
    return hit, scored


def max_z_distribution(reports: list) -> dict:
    """Verteilung von max|z| des Siegers – die Größe, an der das Gate
    entscheidet. Ohne numpy/scipy: Median und Quartile aus der Sortierung."""
    values = sorted(r.max_z_winner for r in reports if r.max_z_winner is not None)
    if not values:
        return {}

    def q(frac):
        return values[min(len(values) - 1, int(frac * (len(values) - 1)))]

    return {"n": len(values), "min": values[0], "p25": q(0.25),
            "median": q(0.5), "p75": q(0.75), "max": values[-1]}


def compare_runs(reports_a: list, reports_b: list, k: int = 3,
                 label_a: str = "A", label_b: str = "B") -> str:
    """A/B-Vergleich zweier Testrunden (z.B. 1 Shot vs. 8 Shots eingelernt).
    Nutzt dieselbe Aggregation wie `evaluate`/das Dashboard (summarize), damit
    die Zahlen zwischen den Werkzeugen identisch sind."""
    sa, sb = summarize(reports_a), summarize(reports_b)
    lines = [f"=== A/B-Vergleich: {label_a} vs. {label_b} ===", ""]

    def row(name, a, b, fmt="{:.0f}"):
        va, vb = fmt.format(a), fmt.format(b)
        delta = ""
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            d = b - a
            delta = f"  ({d:+.1f})" if abs(d) >= 0.05 else "  (=)"
        lines.append(f"  {name:<26} {va:>10} {vb:>10}{delta}")

    lines.append(f"  {'':<26} {label_a:>10} {label_b:>10}")
    row("Reports gesamt", sa.total, sb.total)
    row("davon bewertet", sa.labeled, sb.labeled)
    row("Erfolgsrate %", sa.accuracy * 100, sb.accuracy * 100, "{:.1f}")

    ha, na = top_k_accuracy(reports_a, k)
    hb, nb = top_k_accuracy(reports_b, k)
    row(f"korrekt in Top-{k} %",
        100.0 * ha / na if na else 0.0, 100.0 * hb / nb if nb else 0.0, "{:.1f}")

    for decision in ("accept", "ambiguous", "reject"):
        pa = 100.0 * sa.decision_counts.get(decision, 0) / sa.total if sa.total else 0.0
        pb = 100.0 * sb.decision_counts.get(decision, 0) / sb.total if sb.total else 0.0
        row(f"{decision.upper()} %", pa, pb, "{:.1f}")

    za, zb = max_z_distribution(reports_a), max_z_distribution(reports_b)
    if za and zb:
        lines.append("")
        lines.append("  max|z| des Siegers (Gate-Größe):")
        for key in ("min", "p25", "median", "p75", "max"):
            row(f"  {key}", za[key], zb[key], "{:.2f}")

    for label, s in ((label_a, sa), (label_b, sb)):
        if s.confusion:
            lines.append("")
            lines.append(f"  Verwechslungen {label} (wahr -> erkannt):")
            for truth, pred, n in s.confusion[:8]:
                lines.append(f"    {truth} -> {pred}: {n}x")
    return "\n".join(lines)


def format_summary(s: BatchSummary) -> str:
    """CLI-Textblock für `evaluate` – gleiche Zahlen wie der Batch-Tab."""
    lines = [f"\n=== top-1 accuracy: {s.correct}/{s.labeled} "
             f"({100.0 * s.accuracy:.1f} %) ==="]
    if s.total:
        parts = ", ".join(f"{d}: {n} ({100.0 * n / s.total:.0f} %)"
                          for d, n in sorted(s.decision_counts.items()))
        lines.append(f"decisions: {parts}")
    if s.posteriors_correct:
        lines.append(f"posterior korrekt: mean "
                     f"{sum(s.posteriors_correct) / len(s.posteriors_correct):.2f}")
    if s.posteriors_wrong:
        lines.append(f"posterior falsch:  mean "
                     f"{sum(s.posteriors_wrong) / len(s.posteriors_wrong):.2f}")
    if s.confusion:
        lines.append("confusion pairs (truth -> predicted):")
        for t, p, n in s.confusion:
            lines.append(f"  {t} -> {p}: {n}x")
        lines.append("\nThese pairs are the shortlist for stage 2 (embeddings) "
                     "or for tightening tolerances/features.")
    return "\n".join(lines)
