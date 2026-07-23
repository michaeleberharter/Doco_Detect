"""Drift-Review und Kennzahlen-Ansichten ueber FERTIGE Korpus-Laeufe.

REINE KONSUMENTENSCHICHT. Dieses Modul rechnet NIE Pipeline, Segmentierung
oder Matcher. Es liest ausschliesslich, was auf Platte liegt:

- Goldens        `phase-*/reports/<sha8>.json`     -> Seite "alt"
- Replay         `runs/<id>/replay/<sha8>.json`    -> Seite "neu" (nur Tier 2)
- Band-Urteile   `runs/<id>/metrics.json` + `runs/<id>/failures/*.json`
- Delta-Status   `corpus/accepted_deltas/*.json`
- Baseline       `corpus/baseline.json` (auch historisch, ueber git)

Die Vergleichslogik des Runners (`corpus/compare.py`) bleibt unangetastet:
JEDES Band-Urteil in diesen Artefakten stammt aus `failures/` bzw.
`metrics.json`, nie aus einer eigenen Nachrechnung. Was dieses Modul selbst
bildet, sind rein beschreibende Groessen (welches Feld unterscheidet sich,
welcher Artikel steht auf Rang 1, welches Merkmal traegt das groesste |z|) —
Ablesungen aus den Reports, keine Urteile.

Zwei Seiten, zwei Modi:

    corpus-report --run <id>                 Goldens vs. Lauf   (Drift-Review)
    corpus-report --compare <run_a> <run_b>  Lauf vs. Lauf      (Iterations-/
                                             Schwellen-Vergleich)

Artefakte landen unter `reports/corpus/<review-id>/`: PNG fuer den Menschen,
CSV fuer den maschinellen Abgleich, `index.html` als Uebersicht.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from html import escape
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless – nie ein Fenster oeffnen
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from ..analysis import _finish, _plot_confusion, _write_csv  # noqa: E402
from ..config import project_root, resolve  # noqa: E402
from ..matcher import MatchReport  # noqa: E402
from ..reporting import predicted_article  # noqa: E402
from .accepted import load_all as load_accepted  # noqa: E402
from .manifest import Manifest, corpus_root  # noqa: E402
from .report import BASELINE_PATH, tier2_quotas  # noqa: E402

GOLDEN = "golden-set"

# Entscheidungen in fester Reihenfolge — die Matrix soll zwischen zwei
# Laeufen dieselbe Achsenbelegung haben, auch wenn ein Wert diesmal fehlt.
DECISIONS = ("accept", "ambiguous", "reject")

# Aenderungsklassen, aufsteigend nach Tragweite. Rein beschreibend: sie sagen,
# WAS sich zwischen den beiden geladenen Reports unterscheidet, nicht ob es
# erlaubt ist. Das Urteil dazu steht in `band` (aus failures/metrics).
AENDERUNG = ("identisch", "score", "kandidatenset", "top1", "entscheidung")

_AENDERUNG_FARBE = {
    "identisch": "#b0b0b0",
    "score": "#4c72b0",
    "kandidatenset": "#b58900",
    "top1": "#d1701a",
    "entscheidung": "#b02a37",
}

_BAND_FARBE = {"pass": "#1a7f37", "drift": "#b58900", "fail": "#b02a37"}


# --------------------------------------------------------------------------
# Seiten laden
# --------------------------------------------------------------------------

@dataclass
class Side:
    """Eine Vergleichsseite: Reports plus — sofern es ein Lauf ist — die
    Band-Urteile und Kennzahlen, die der Runner dazu geschrieben hat."""

    name: str
    reports: dict = field(default_factory=dict)     # sha8 -> MatchReport
    bands: dict = field(default_factory=dict)       # sha8 -> "pass"|"drift"|"fail"
    diffs: dict = field(default_factory=dict)       # sha8 -> [FieldDiff-dicts]
    metrics: dict = field(default_factory=dict)     # runs/<id>/metrics.json
    quelle: str = ""                                # Herkunft fuer den Bericht

    @property
    def is_run(self) -> bool:
        return self.name != GOLDEN


def _load_report(path: Path) -> MatchReport | None:
    try:
        return MatchReport.from_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, KeyError):
        return None


def load_golden_side(root: Path, manifest: Manifest | None = None) -> Side:
    """Die Golden-Reports der Tier-2-faehigen Bilder, ueber das Manifest.

    Ueber das Manifest und nicht per Glob: nur so ist ausgeschlossen, dass
    Reports einer nicht Tier-2-faehigen Session mitlaufen und die Seite
    "alt" gegen etwas anderes als der Runner vergleicht.
    """
    side = Side(name=GOLDEN, quelle="corpus/manifest.json + phase-*/reports")
    for e in (manifest or Manifest.load()).images:
        if e.tier < 2:
            continue
        rep = _load_report(Path(root) / e.report_rel)
        if rep is not None:
            side.reports[e.sha[:8]] = rep
    return side


class UnvollstaendigerLauf(FileNotFoundError):
    """Ein Lauf ohne `metrics.json` — abgebrochen, nicht auswertbar."""


def load_run_side(root: Path, run_id: str) -> Side:
    """Replay-Reports, Band-Urteile und Kennzahlen EINES Laufs.

    Das Band je Bild steht nicht in metrics.json (dort nur die Summe),
    sondern implizit: `failures/<sha8>.json` existiert genau fuer die Bilder,
    die NICHT pass sind. Alles ohne Datei ist pass — das ist die Buchfuehrung
    von `report.write_run`, hier nur gelesen.

    `metrics.json` ist PFLICHT. Der Runner schreibt sie als LETZTES
    (`report.write_run`); ein Lauf ohne sie wurde mittendrin abgebrochen und
    traegt einen unvollstaendigen Replay-Stand. Als Vergleichsseite waere er
    stillschweigend irrefuehrend: die fehlenden Bilder saehen wie
    "nicht betroffen" aus statt wie "nie gefahren", und ohne die
    Runner-Kennzahlen muesste diese Schicht die Quoten selbst rechnen —
    genau das, was sie nicht tut. Darum Abbruch mit Klartext statt
    stiller Teilauswertung.
    """
    d = Path(root) / "runs" / run_id
    if not d.is_dir():
        raise FileNotFoundError(
            f"Lauf '{run_id}' existiert nicht ({d}). Vorhandene Laeufe: "
            f"'ls {Path(root) / 'runs'}'.")
    side = Side(name=run_id, quelle=f"runs/{run_id}")

    mp = d / "metrics.json"
    if not mp.exists():
        n_replay = len(list((d / "replay").glob("*.json"))) if (d / "replay").is_dir() else 0
        # Nur die juengsten nennen: die vollstaendige Liste ist nach ein paar
        # Wochen dreissig Zeilen lang und hilft niemandem.
        vollstaendig = list_runs(root)
        zuletzt = ", ".join(vollstaendig[-5:]) or "(keine)"
        raise UnvollstaendigerLauf(
            f"Lauf '{run_id}' ist unvollstaendig: {mp} fehlt. Der Runner "
            f"schreibt metrics.json zuletzt — dieser Lauf wurde abgebrochen "
            f"(gefunden: {n_replay} Replay-Report(s)). Ein abgebrochener Lauf "
            f"ist keine gueltige Vergleichsseite. Zuletzt vollstaendig "
            f"({len(vollstaendig)} insgesamt): {zuletzt}. Abgebrochene Laeufe "
            f"gehoeren nach runs/_invalid/.")
    side.metrics = json.loads(mp.read_text(encoding="utf-8"))

    for p in sorted((d / "replay").glob("*.json")) if (d / "replay").is_dir() else []:
        rep = _load_report(p)
        if rep is not None:
            side.reports[p.stem] = rep

    fd = d / "failures"
    if fd.is_dir():
        for p in sorted(fd.glob("*.json")):
            try:
                payload = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            side.bands[p.stem] = payload.get("band", "fail")
            side.diffs[p.stem] = payload.get("diffs") or []
    # Kein Eintrag unter failures/ = pass. Bewusst nur fuer Bilder, die der
    # Lauf ueberhaupt gefahren hat (Replay-Report vorhanden) — ein Bild ohne
    # beides duerfte nie stillschweigend als "pass" erscheinen.
    for sha8 in side.reports:
        side.bands.setdefault(sha8, "pass")
    return side


def load_side(root: Path, spec: str, manifest: Manifest | None = None) -> Side:
    return (load_golden_side(root, manifest) if spec == GOLDEN
            else load_run_side(root, spec))


def list_runs(root: Path) -> list:
    """Alle VOLLSTAENDIGEN Laeufe, aelteste zuerst.

    Vollstaendig heisst: `metrics.json` vorhanden. Abgebrochene Laeufe
    werden hier stillschweigend uebergangen — `--run letzte` soll nie auf
    einem Torso landen. Wer einen solchen Lauf ausdruecklich nennt, bekommt
    stattdessen den Klartext aus `load_run_side`.

    Ordner mit fuehrendem Unterstrich (Konvention: `runs/_invalid/` fuer
    aussortierte Laeufe) bleiben grundsaetzlich aussen vor.
    """
    rd = Path(root) / "runs"
    if not rd.is_dir():
        return []
    out = []
    for p in sorted(rd.iterdir()):
        if p.name.startswith("_"):
            continue
        mp = p / "metrics.json"
        if p.is_dir() and mp.exists():
            out.append((mp.stat().st_mtime, p.name))
    return [name for _, name in sorted(out)]


def latest_run_id(root: Path, tier: int | None = None) -> str:
    """Der zuletzt geschriebene Lauf (`--run letzte`), optional auf eine
    Stufe eingeschraenkt."""
    kandidaten = list_runs(root)
    if tier is not None:
        gefiltert = []
        for name in kandidaten:
            m = json.loads(((Path(root) / "runs" / name / "metrics.json")
                            ).read_text(encoding="utf-8"))
            if m.get("tier") == tier:
                gefiltert.append(name)
        kandidaten = gefiltert
    if not kandidaten:
        raise FileNotFoundError(
            f"Kein Lauf mit metrics.json unter {Path(root) / 'runs'}"
            + (f" (Tier {tier})" if tier is not None else "")
            + " — zuerst 'corpus-run' ausfuehren.")
    return kandidaten[-1]


# --------------------------------------------------------------------------
# Ablesungen aus einem Report (keine Neurechnung)
# --------------------------------------------------------------------------

def driving_feature(report: MatchReport) -> tuple:
    """(Merkmal, z) des Siegers mit dem groessten |z| — das Merkmal, an dem
    `max_z_winner` haengt und damit der Treiber des z-Gates.

    Reine Ablesung: `max_z_winner` wird NICHT nachgerechnet, es wird nur der
    Eintrag mit dem groessten |z| aus der bereits im Report gespeicherten
    Merkmalsliste des Rang-1-Kandidaten herausgesucht.
    """
    if not report.candidates or not report.candidates[0].features:
        return "", None
    f = max(report.candidates[0].features,
            key=lambda x: abs(x.z) if x.z is not None else -1.0)
    return f.feature, f.z


def change_kind(alt: MatchReport, neu: MatchReport) -> str:
    """Was unterscheidet die beiden Reports? Rein beschreibend, in der
    Reihenfolge ihrer Tragweite."""
    if alt.decision != neu.decision:
        return "entscheidung"
    if predicted_article(alt) != predicted_article(neu):
        return "top1"
    if ([c.article_number for c in alt.candidates]
            != [c.article_number for c in neu.candidates]):
        return "kandidatenset"
    for a, b in ((alt.llr_margin, neu.llr_margin),
                 (alt.max_z_winner, neu.max_z_winner)):
        if a != b:
            return "score"
    return "identisch"


def _num(x):
    return x if isinstance(x, (int, float)) else None


def _delta(a, b):
    a, b = _num(a), _num(b)
    return round(b - a, 4) if a is not None and b is not None else None


# --------------------------------------------------------------------------
# Zeilen der Drift-Review
# --------------------------------------------------------------------------

REVIEW_HEADER = [
    "sha8", "band", "aenderung", "label",
    "decision_alt", "decision_neu",
    "top1_alt", "top1_neu", "top1_korrekt_alt", "top1_korrekt_neu",
    "llr_margin_alt", "llr_margin_neu", "llr_margin_delta",
    "max_z_alt", "max_z_neu", "max_z_delta",
    "treiber_alt", "treiber_z_alt", "treiber_neu", "treiber_z_neu",
    "top3_neu", "label_in_top3_neu",
    "delta_status", "delta_kategorie", "delta_quelle", "delta_fix_commit",
]


def build_rows(alt: Side, neu: Side, accepted: dict | None = None) -> list:
    """Eine Zeile je Bild, das BEIDE Seiten fuehren.

    `band` kommt aus der neuen Seite (dem Runner-Urteil des Laufs). Bei
    Goldens-vs-Lauf ist das genau das Urteil, das `corpus-run --check`
    gefaellt hat; bei Lauf-vs-Lauf das des zweiten Laufs.
    """
    accepted = load_accepted() if accepted is None else accepted
    rows = []
    for sha8 in sorted(set(alt.reports) & set(neu.reports)):
        a, b = alt.reports[sha8], neu.reports[sha8]
        # Wahrheit aus der Seite "alt" (Goldens bzw. der aeltere Lauf); der
        # Replay uebernimmt sie ohnehin aus dem Manifest.
        label = a.label or b.label or ""
        top1_a, top1_b = predicted_article(a), predicted_article(b)
        top3_b = [c.article_number for c in b.candidates[:3]]
        ta, za = driving_feature(a)
        tb, zb = driving_feature(b)
        entry = accepted.get(sha8) or {}
        rows.append({
            "sha8": sha8,
            "band": neu.bands.get(sha8, "" if not neu.is_run else "pass"),
            "aenderung": change_kind(a, b),
            "label": label,
            "decision_alt": a.decision, "decision_neu": b.decision,
            "top1_alt": top1_a, "top1_neu": top1_b,
            "top1_korrekt_alt": "ja" if label and top1_a == label else "nein",
            "top1_korrekt_neu": "ja" if label and top1_b == label else "nein",
            "llr_margin_alt": _num(a.llr_margin),
            "llr_margin_neu": _num(b.llr_margin),
            "llr_margin_delta": _delta(a.llr_margin, b.llr_margin),
            "max_z_alt": _num(a.max_z_winner),
            "max_z_neu": _num(b.max_z_winner),
            "max_z_delta": _delta(a.max_z_winner, b.max_z_winner),
            "treiber_alt": ta, "treiber_z_alt": za,
            "treiber_neu": tb, "treiber_z_neu": zb,
            "top3_neu": " ".join(top3_b),
            "label_in_top3_neu": "ja" if label and label in top3_b else "nein",
            "delta_status": "akzeptiert" if entry else "-",
            "delta_kategorie": entry.get("kategorie", ""),
            "delta_quelle": entry.get("_source", ""),
            "delta_fix_commit": (entry.get("_fix_commit") or "")[:8],
        })
    return rows


def neue_fehlbuchungen(rows: list) -> list:
    """Bilder, die die NEUE Seite mit falschem Artikel akzeptiert, die alte
    aber nicht (sie buchte gar nicht oder buchte richtig).

    Das ist die teuerste Klasse von Abweichung und NICHT dieselbe Menge wie
    ein Rang-1-Wechsel: war Rang 1 schon vorher falsch und kippt nur die
    Entscheidung auf `accept`, entsteht eine neue Fehlbuchung, ohne dass sich
    Rang 1 bewegt. Genau so lag `46f9b1b3` bei hu_log-Floor 0.069 — die
    Richtungsbilanz `top1_wechsel` zeigte dort 1, tatsaechlich waren es 2
    (Abnahme des Ergebnisdokuments 2026-07-22, Abschnitt 3).
    """
    return [r for r in rows
            if r["decision_neu"] == "accept"
            and r["label"] and r["top1_korrekt_neu"] == "nein"
            and not (r["decision_alt"] == "accept"
                     and r["top1_korrekt_alt"] == "nein")]


def top1_wechsel(rows: list) -> dict:
    """Richtungsbilanz der Rang-1-Wechsel: falsch->richtig, richtig->falsch,
    falsch->falsch, richtig->richtig. Reine Auszaehlung ueber die Zeilen."""
    zaehler = {"falsch->richtig": 0, "richtig->falsch": 0,
               "falsch->falsch": 0, "richtig->richtig": 0}
    for r in rows:
        if r["top1_alt"] == r["top1_neu"] or not r["label"]:
            continue
        a = "richtig" if r["top1_korrekt_alt"] == "ja" else "falsch"
        b = "richtig" if r["top1_korrekt_neu"] == "ja" else "falsch"
        zaehler[f"{a}->{b}"] += 1
    return zaehler


# --------------------------------------------------------------------------
# Ansicht 1: Drift-Review
# --------------------------------------------------------------------------

def _scatter(ax, rows, key_a, key_b, gate, titel, achse):
    gruppen = {}
    for r in rows:
        x, y = r[key_a], r[key_b]
        if x is None or y is None:
            continue
        gruppen.setdefault(r["aenderung"], []).append((x, y, r["sha8"]))
    werte = [v for g in gruppen.values() for p in g for v in p[:2]]
    if not werte:
        ax.set_title(f"{titel}: keine Daten")
        ax.axis("off")
        return 0
    lo, hi = min(werte + [gate]), max(werte + [gate])
    rand = 0.05 * (hi - lo or 1.0)
    lo, hi = lo - rand, hi + rand
    ax.plot([lo, hi], [lo, hi], color="#888", linewidth=0.8, linestyle=":",
            zorder=1, label="unveraendert")
    ax.axvline(gate, color="black", linestyle="--", linewidth=1.0, zorder=2)
    ax.axhline(gate, color="black", linestyle="--", linewidth=1.0, zorder=2)
    n = 0
    for kind in AENDERUNG:
        pts = gruppen.get(kind)
        if not pts:
            continue
        n += len(pts)
        ax.scatter([p[0] for p in pts], [p[1] for p in pts],
                   s=46 if kind == "identisch" else 70,
                   color=_AENDERUNG_FARBE[kind],
                   alpha=0.5 if kind == "identisch" else 0.9,
                   edgecolors="black", linewidths=0.4, zorder=3,
                   label=f"{kind} (n={len(pts)})")
    # Nur die Bilder beschriften, die die Gate-Linie ueberqueren – alles
    # andere macht den Plot unlesbar, ohne Information zu tragen.
    for pts in gruppen.values():
        for x, y, sha in pts:
            if (x < gate) != (y < gate):
                ax.annotate(sha, (x, y), fontsize=6.5, xytext=(4, 3),
                            textcoords="offset points")
    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    ax.set_xlabel(f"{achse} alt")
    ax.set_ylabel(f"{achse} neu")
    ax.set_title(f"{titel} (n={n})", fontsize=10)
    ax.legend(fontsize=7, loc="best")
    ax.grid(alpha=0.25)
    return n


def _plot_decision_matrix(rows, path, run_id, titel):
    mat = np.zeros((len(DECISIONS), len(DECISIONS)), dtype=int)
    idx = {d: i for i, d in enumerate(DECISIONS)}
    sonstige = 0
    for r in rows:
        i, j = idx.get(r["decision_alt"]), idx.get(r["decision_neu"])
        if i is None or j is None:
            sonstige += 1
            continue
        mat[i, j] += 1
    fig, ax = plt.subplots(figsize=(5.6, 4.6))
    ax.imshow(mat, cmap="Blues")
    ax.set_xticks(range(len(DECISIONS)), DECISIONS)
    ax.set_yticks(range(len(DECISIONS)), DECISIONS)
    ax.set_xlabel("neu")
    ax.set_ylabel("alt")
    ax.set_title(titel, fontsize=10, wrap=True)
    vmax = mat.max() or 1
    for i in range(len(DECISIONS)):
        for j in range(len(DECISIONS)):
            if i == j:
                ax.add_patch(plt.Rectangle((j - 0.5, i - 0.5), 1, 1, fill=False,
                                           edgecolor="#1a7f37", linewidth=2.2))
            if mat[i, j]:
                ax.text(j, i, str(mat[i, j]), ha="center", va="center",
                        fontsize=10,
                        color="white" if mat[i, j] > 0.6 * vmax else "black")
    if sonstige:
        ax.set_xlabel(f"neu ({sonstige} Fall/Faelle mit unbekannter "
                      f"Entscheidung ausgelassen)")
    _finish(fig, path, run_id)
    return mat


def write_drift_review(out: Path, rows: list, alt: Side, neu: Side,
                       cfg: dict, review_id: str) -> dict:
    """CSV + Margin-Scatter + max|z|-Scatter + Entscheidungs-Matrix."""
    _write_csv(out / "drift_review.csv", REVIEW_HEADER,
               [[r[k] if r[k] is not None else "" for k in REVIEW_HEADER]
                for r in rows])

    m = cfg.get("matching", {})
    gate_margin = float(m.get("min_llr_margin", 2.0))
    gate_z = float(m.get("max_z_accept", 3.5))

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.8))
    _scatter(axes[0], rows, "llr_margin_alt", "llr_margin_neu", gate_margin,
             f"LLR-Margin – Gate min_llr_margin = {gate_margin:g}", "LLR-Margin")
    _scatter(axes[1], rows, "max_z_alt", "max_z_neu", gate_z,
             f"max |z| des Siegers – Gate max_z_accept = {gate_z:g}", "max |z|")
    fig.suptitle(f"Drift-Review {alt.name} → {neu.name}", fontsize=11)
    _finish(fig, out / "drift_scatter.png", review_id)

    mat = _plot_decision_matrix(
        rows, out / "decision_matrix.png", review_id,
        f"Entscheidung {alt.name} → {neu.name} (n={len(rows)})")
    _write_csv(out / "decision_matrix.csv", ["alt\\neu"] + list(DECISIONS),
               [[d] + list(mat[i]) for i, d in enumerate(DECISIONS)])

    wechsel = top1_wechsel(rows)
    _write_csv(out / "top1_wechsel.csv", ["richtung", "anzahl"],
               [[k, v] for k, v in wechsel.items()])

    fehl = neue_fehlbuchungen(rows)
    _write_csv(out / "neue_fehlbuchungen.csv",
               ["sha8", "label", "top1_neu", "decision_alt", "decision_neu",
                "llr_margin_neu", "max_z_neu", "treiber_neu", "delta_status"],
               [[r["sha8"], r["label"], r["top1_neu"], r["decision_alt"],
                 r["decision_neu"], r["llr_margin_neu"], r["max_z_neu"],
                 r["treiber_neu"], r["delta_status"]] for r in fehl])

    return {"top1_wechsel": wechsel,
            "neue_fehlbuchungen": fehl,
            "aenderungen": {k: sum(1 for r in rows if r["aenderung"] == k)
                            for k in AENDERUNG},
            "baender": {b: sum(1 for r in rows if r["band"] == b)
                        for b in ("pass", "drift", "fail")}}


# --------------------------------------------------------------------------
# Ansicht 2: Baseline-Verlauf aus der Git-Historie
# --------------------------------------------------------------------------

def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, check=True).stdout


def baseline_history(pfad: Path | None = None, repo: Path | None = None) -> list:
    """Quoten je Commit, der `corpus/baseline.json` angefasst hat — aeltester
    zuerst. Kein neues Schema: je Commit wird die damalige Datei mit
    `git show` geholt und genau so gelesen wie heute.
    """
    repo = Path(repo or project_root())
    p = Path(pfad or BASELINE_PATH)
    try:
        rel = p.relative_to(repo).as_posix()
    except ValueError:
        return []
    try:
        log = _git(repo, "log", "--reverse", "--format=%H%x09%ad%x09%s",
                   "--date=short", "--", rel)
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return []
    punkte = []
    for zeile in log.splitlines():
        teile = zeile.split("\t")
        if len(teile) < 3:
            continue
        sha, datum, betreff = teile[0], teile[1], "\t".join(teile[2:])
        try:
            payload = json.loads(_git(repo, "show", f"{sha}:{rel}"))
        except (subprocess.CalledProcessError, ValueError):
            continue
        quotas = payload.get("quotas") or {}
        eintrag = {"commit": sha[:8], "datum": datum, "betreff": betreff,
                   "run_id": payload.get("run_id", ""), "n": payload.get("n")}
        for name in ("accuracy_top1", "accuracy_top3", "auto_accept_rate",
                     "false_accept_rate"):
            q = quotas.get(name) or {}
            eintrag[name] = q.get("p")
            eintrag[f"{name}_k"] = q.get("k")
            eintrag[f"{name}_n"] = q.get("n")
        punkte.append(eintrag)
    return punkte


def write_baseline_history(out: Path, review_id: str, *, pfad: Path | None = None,
                           repo: Path | None = None) -> list:
    punkte = baseline_history(pfad, repo)
    header = ["commit", "datum", "betreff", "run_id", "n",
              "accuracy_top1", "accuracy_top3", "auto_accept_rate",
              "false_accept_rate", "false_accept_rate_k", "false_accept_rate_n"]
    _write_csv(out / "baseline_verlauf.csv", header,
               [[p.get(k, "") if p.get(k) is not None else "" for k in header]
                for p in punkte])
    if not punkte:
        return punkte

    x = list(range(len(punkte)))
    ticks = [f"{p['commit']}\n{p['datum']}" for p in punkte]
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.8))
    for name, farbe in (("accuracy_top1", "#4c72b0"),
                        ("accuracy_top3", "#55a868"),
                        ("auto_accept_rate", "#b58900")):
        ys = [p.get(name) for p in punkte]
        if all(v is None for v in ys):
            continue
        axes[0].plot(x, ys, marker="o", color=farbe, label=name)
        for xi, yi in zip(x, ys):
            if yi is not None:
                axes[0].annotate(f"{yi:.3f}", (xi, yi), fontsize=7,
                                 xytext=(0, 6), textcoords="offset points",
                                 ha="center")
    axes[0].set_xticks(x, ticks, fontsize=7)
    axes[0].set_ylim(-0.02, 1.05)
    axes[0].set_ylabel("Quote (Anteil, 0–1)")
    axes[0].set_title("Baseline-Quoten je Commit von corpus/baseline.json",
                      fontsize=10)
    axes[0].grid(alpha=0.3)
    axes[0].legend(fontsize=8)

    k = [p.get("false_accept_rate_k") or 0 for p in punkte]
    n = [p.get("false_accept_rate_n") or 0 for p in punkte]
    axes[1].bar(x, k, color="#b02a37")
    for xi, ki, ni in zip(x, k, n):
        axes[1].annotate(f"{ki}/{ni}", (xi, ki), fontsize=8, ha="center",
                         xytext=(0, 4), textcoords="offset points")
    axes[1].set_xticks(x, ticks, fontsize=7)
    axes[1].set_ylim(0, max(k + [1]) * 1.4)
    axes[1].set_ylabel("Fehlbuchungen (k von n accepts)")
    axes[1].set_title("false_accept – Zaehler, nicht Quote "
                      "(0 heisst nicht 0 %, siehe Wilson-Obergrenze)",
                      fontsize=9, wrap=True)
    axes[1].grid(axis="y", alpha=0.3)
    _finish(fig, out / "baseline_verlauf.png", review_id)
    return punkte


# --------------------------------------------------------------------------
# Ansicht 3: Verteilungen
# --------------------------------------------------------------------------

def write_distributions(out: Path, alt: Side, neu: Side, cfg: dict,
                        review_id: str) -> dict:
    """LLR-Margin und max|z| als Histogramme, getrennt korrekt vs. falsch.

    Wahres Label aus der Seite "alt" (den Goldens). Korrekt heisst hier
    `top1 == label` — bewusst NICHT `reporting.judgement()`: dessen
    Verdict-Vorrang macht die Groesse ueber den Korpus konstant (alle 60
    Bilder tragen ein eingefrorenes menschliches Urteil, siehe
    docs/superpowers/reports/2026-07-22-sigma-floors-ergebnis.md, 5.3).
    Fuer eine Schwellen-Diskussion braucht es die rohe Trefferlage.
    """
    m = cfg.get("matching", {})
    gates = {"llr_margin": float(m.get("min_llr_margin", 2.0)),
             "max_z_winner": float(m.get("max_z_accept", 3.5))}
    zeilen, daten = [], {"llr_margin": ([], []), "max_z_winner": ([], [])}
    for sha8 in sorted(set(alt.reports) & set(neu.reports)):
        a, b = alt.reports[sha8], neu.reports[sha8]
        label = a.label or b.label or ""
        if not label:
            continue
        ok = predicted_article(b) == label
        zeilen.append([sha8, label, predicted_article(b),
                       "ja" if ok else "nein", b.decision,
                       _num(b.llr_margin) if _num(b.llr_margin) is not None else "",
                       _num(b.max_z_winner) if _num(b.max_z_winner) is not None else ""])
        for key in daten:
            v = _num(getattr(b, key))
            if v is not None:
                daten[key][0 if ok else 1].append(v)
    _write_csv(out / "verteilungen.csv",
               ["sha8", "label", "top1", "top1_korrekt", "entscheidung",
                "llr_margin", "max_z_winner"], zeilen)

    fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.4))
    panels = (("llr_margin", "LLR-Margin (Platz 1 − Platz 2)",
               "min_llr_margin", axes[0]),
              ("max_z_winner", "max |z| des Siegers", "max_z_accept", axes[1]))
    for key, titel, gate_name, ax in panels:
        gut, schlecht = daten[key]
        alle = gut + schlecht
        if not alle:
            ax.set_title(f"{titel}: keine Daten")
            ax.axis("off")
            continue
        bins = np.linspace(min(alle), max(alle) or 1.0, 22)
        ax.hist(gut, bins=bins, alpha=0.6, color="#1a7f37",
                label=f"top1 == label (n={len(gut)})")
        ax.hist(schlecht, bins=bins, alpha=0.6, color="#b02a37",
                label=f"top1 != label (n={len(schlecht)})")
        ax.axvline(gates[key], color="black", linestyle="--",
                   label=f"{gate_name} = {gates[key]:g}")
        ax.set_title(f"{titel} – {neu.name} (n={len(alle)})", fontsize=10)
        ax.set_xlabel(f"{titel} [dimensionslos]")
        ax.set_ylabel("Anzahl Bilder")
        ax.legend(fontsize=8)
    _finish(fig, out / "verteilungen.png", review_id)
    return {k: {"korrekt": len(v[0]), "falsch": len(v[1])} for k, v in daten.items()}


# --------------------------------------------------------------------------
# Ansicht 4: Konfusionsmatrix + Quoten mit Wilson-CI
# --------------------------------------------------------------------------

QUOTEN_HEADER = ["kennzahl", "seite", "k", "n", "p", "wilson_lo", "wilson_hi",
                 "quelle"]


def _quota_rows(side: Side, alt: Side | None = None) -> tuple:
    """(Zeilen, Konsistenz-Befunde) fuer eine Seite.

    Die Kennzahlen einer LAUF-Seite werden aus `runs/<id>/metrics.json`
    UEBERNOMMEN, nicht neu gerechnet — das ist die Zahl, die der Runner
    gemeldet und `--check` bewertet hat. Zusaetzlich laeuft
    `report.tier2_quotas` (dieselbe Funktion, die der Runner benutzt) ueber
    die Replay-Reports und wird dagegen gehalten: weicht etwas ab, steht das
    als Befund im Bericht statt still unterzugehen.
    """
    zeilen, befunde = [], []
    nach = tier2_quotas(list(side.reports.values())) if side.reports else {}

    if side.is_run and side.metrics.get("quotas"):
        quelle_q = f"runs/{side.name}/metrics.json"
        quoten = side.metrics["quotas"]
    else:
        quelle_q = ("gerechnet: corpus.report.tier2_quotas() ueber "
                    + (f"runs/{side.name}/replay" if side.is_run
                       else "die Golden-Reports"))
        quoten = nach

    for name, q in quoten.items():
        if not isinstance(q, dict) or "p" not in q:
            continue
        zeilen.append([name, side.name, q["k"], q["n"], q["p"],
                       q["wilson_lo"], q["wilson_hi"], quelle_q])
        gegen = nach.get(name)
        if (side.is_run and side.metrics.get("quotas")
                and isinstance(gegen, dict) and "p" in gegen
                and (gegen["k"], gegen["n"]) != (q["k"], q["n"])):
            befunde.append(
                f"{side.name}/{name}: metrics.json meldet {q['k']}/{q['n']}, "
                f"tier2_quotas ueber runs/{side.name}/replay ergibt "
                f"{gegen['k']}/{gegen['n']} — die Artefakte zeigen den Wert "
                f"aus metrics.json.")

    # Rohe Top-1-Quote, unabhaengig nachgerechnet. Seit dem Semantikwechsel
    # vom 2026-07-23 rechnet accuracy_top1 selbst roh gegen das Label — diese
    # Zeile MUSS also mit ihr uebereinstimmen, solange die Laufseite aus der
    # neuen Aera stammt. Weicht sie ab, kommt die metrics.json der Laufseite
    # aus der verdict-Aera; die Zeile ist dann der Umrechnungsschluessel und
    # macht den Unterschied sichtbar, statt zwei Aeren stumm zu mischen.
    # Sie rechnet zusaetzlich ueber die Labels der REFERENZSEITE und ueber-
    # lebt damit Replay-Reports, die selbst kein Label tragen.
    if alt is not None or not side.is_run:
        wahrheit = alt or side
        k = n = 0
        for sha8, rep in side.reports.items():
            ref = wahrheit.reports.get(sha8)
            label = (ref.label if ref else None) or rep.label
            if not label:
                continue
            n += 1
            if predicted_article(rep) == label:
                k += 1
        if n:
            from .report import wilson
            p, lo, hi = wilson(k, n)
            zeilen.append(["roh_top1_gleich_label", side.name, k, n, p, lo, hi,
                           "gerechnet: top1 == label (KEINE Runner-Kennzahl; "
                           "muss accuracy_top1 entsprechen — Abweichung = "
                           "metrics.json aus der verdict-Aera)"])
    return zeilen, befunde


def write_quotas(out: Path, alt: Side, neu: Side, review_id: str) -> tuple:
    zeilen_a, befunde_a = _quota_rows(alt, alt)
    zeilen_b, befunde_b = _quota_rows(neu, alt)
    _write_csv(out / "quoten.csv", QUOTEN_HEADER, zeilen_a + zeilen_b)

    namen = [z[0] for z in zeilen_b]
    fig, ax = plt.subplots(figsize=(max(7, 1.7 * len(namen) + 2), 4.6))
    for versatz, (zeilen, seite, farbe) in enumerate(
            ((zeilen_a, alt.name, "#999999"), (zeilen_b, neu.name, "#4c72b0"))):
        nach_name = {z[0]: z for z in zeilen}
        xs, ps, lo, hi = [], [], [], []
        for i, name in enumerate(namen):
            z = nach_name.get(name)
            if not z:
                continue
            xs.append(i + (versatz - 0.5) * 0.16)
            ps.append(z[4])
            lo.append(z[4] - z[5])
            hi.append(z[6] - z[4])
        if xs:
            ax.errorbar(xs, ps, yerr=[lo, hi], fmt="o", capsize=4,
                        color=farbe, label=seite)
    ax.set_xticks(range(len(namen)),
                  [f"{n}\n(n={dict((z[0], z[3]) for z in zeilen_b).get(n)})"
                   for n in namen], fontsize=7.5)
    ax.set_ylim(-0.02, 1.05)
    ax.set_ylabel("Quote (Anteil, 0–1)")
    ax.set_title("Quoten mit 95%-Wilson-CI – Werte der Laufseiten aus "
                 "metrics.json uebernommen", fontsize=10, wrap=True)
    ax.grid(axis="y", alpha=0.3)
    ax.legend(fontsize=8)
    _finish(fig, out / "quoten.png", review_id)
    return zeilen_a + zeilen_b, befunde_a + befunde_b


def write_confusion(out: Path, alt: Side, neu: Side, review_id: str) -> int:
    """Konfusionsmatrix ueber den Replay-Stand der neuen Seite —
    Aufbaulogik identisch zu `analysis._analysis_confusion` (dieselbe
    Plot-Funktion, dieselbe Paar-Zaehlung)."""
    from collections import Counter
    paare = Counter()
    for sha8, rep in neu.reports.items():
        ref = alt.reports.get(sha8)
        label = (ref.label if ref else None) or rep.label
        if label:
            paare[(label, predicted_article(rep))] += 1
    if not paare:
        return 0
    gts = sorted({g for g, _ in paare})
    preds = sorted({p for _, p in paare})
    mat = np.array([[paare.get((g, p), 0) for p in preds] for g in gts],
                   dtype=int)
    _write_csv(out / "confusion_matrix.csv", ["ground_truth"] + preds,
               [[g] + list(zeile) for g, zeile in zip(gts, mat)])
    n = int(mat.sum())
    _plot_confusion(mat, gts, preds,
                    f"Konfusionsmatrix – {neu.name} (n={n}); "
                    f"ground truth aus {alt.name}",
                    out / "confusion_matrix.png", review_id)

    akzeptiert = Counter()
    for sha8, rep in neu.reports.items():
        if rep.decision != "accept":
            continue
        ref = alt.reports.get(sha8)
        label = (ref.label if ref else None) or rep.label
        if label:
            akzeptiert[(label, predicted_article(rep))] += 1
    if akzeptiert:
        gts_a = sorted({g for g, _ in akzeptiert})
        preds_a = sorted({p for _, p in akzeptiert})
        mat_a = np.array([[akzeptiert.get((g, p), 0) for p in preds_a]
                          for g in gts_a], dtype=int)
        _write_csv(out / "confusion_matrix_accept.csv", ["ground_truth"] + preds_a,
                   [[g] + list(zeile) for g, zeile in zip(gts_a, mat_a)])
        _plot_confusion(mat_a, gts_a, preds_a,
                        f"Konfusionsmatrix – nur ACCEPT (n={int(mat_a.sum())}) "
                        f"– Fehler hier sind Fehlbuchungen",
                        out / "confusion_matrix_accept.png", review_id)
    return n


# --------------------------------------------------------------------------
# Zusatzansicht: Tier-1-Drift je Merkmal
# --------------------------------------------------------------------------

def tier1_drift_je_merkmal(side: Side) -> list:
    """Aus den `failures/`-Diffs eines Tier-1-Laufs: je Merkmal, wie viele
    Bilder betroffen sind und wie gross die Abweichung ausfaellt.

    Erster Anwendungsfall ist die Plattform-Drift Mac->Windows. Solange kein
    Lauf Failures hat, bleibt die Ansicht leer — Messwerte werden fuer
    PASS-Bilder bewusst nicht persistiert (bekannte, akzeptierte Luecke).
    """
    je_feld: dict = {}
    for sha8, diffs in side.diffs.items():
        for d in diffs:
            feld = d.get("field", "?")
            eintrag = je_feld.setdefault(
                feld, {"feld": feld, "bilder": set(), "drift": 0, "fail": 0,
                       "deltas": []})
            eintrag["bilder"].add(sha8)
            band = d.get("band", "")
            if band in ("drift", "fail"):
                eintrag[band] += 1
            delta = d.get("delta")
            if isinstance(delta, (int, float)):
                eintrag["deltas"].append(abs(delta))
    zeilen = []
    for e in je_feld.values():
        ds = sorted(e["deltas"])
        zeilen.append({
            "feld": e["feld"], "bilder": len(e["bilder"]),
            "drift": e["drift"], "fail": e["fail"],
            "delta_median": round(ds[len(ds) // 2], 6) if ds else None,
            "delta_max": round(ds[-1], 6) if ds else None})
    zeilen.sort(key=lambda z: (-z["fail"], -z["drift"], -z["bilder"]))
    return zeilen


def write_tier1_drift(out: Path, side: Side, review_id: str) -> list:
    zeilen = tier1_drift_je_merkmal(side)
    header = ["feld", "bilder", "drift", "fail", "delta_median", "delta_max"]
    _write_csv(out / "tier1_drift.csv", header,
               [[z[k] if z[k] is not None else "" for k in header] for z in zeilen])
    if not zeilen:
        return zeilen
    fig, ax = plt.subplots(figsize=(9, max(3, 0.42 * len(zeilen) + 1.8)))
    felder = [z["feld"] for z in zeilen][::-1]
    drift = [z["drift"] for z in zeilen][::-1]
    fail = [z["fail"] for z in zeilen][::-1]
    ax.barh(felder, drift, color=_BAND_FARBE["drift"], label="DRIFT")
    ax.barh(felder, fail, left=drift, color=_BAND_FARBE["fail"], label="FAIL")
    ax.set_xlabel("Anzahl Befunde")
    ax.set_title(f"Tier-1-Drift je Merkmal – {side.name} "
                 f"(nur Bilder mit Befund; PASS speichert keine Messwerte)",
                 fontsize=10, wrap=True)
    ax.legend(fontsize=8)
    _finish(fig, out / "tier1_drift.png", review_id)
    return zeilen


# --------------------------------------------------------------------------
# HTML-Uebersicht
# --------------------------------------------------------------------------

_HTML_CSS = """
:root { color-scheme: light dark; }
body { font-family: -apple-system, "Segoe UI", system-ui, sans-serif;
       margin: 0 auto; max-width: 1180px; padding: 1.6rem 1.2rem 4rem;
       line-height: 1.55; }
h1 { font-size: 1.5rem; margin-bottom: .2rem; }
h2 { font-size: 1.15rem; margin-top: 2.2rem;
     border-bottom: 1px solid rgba(128,128,128,.35); padding-bottom: .25rem; }
.meta { font-size: .85rem; opacity: .75; }
img { max-width: 100%; height: auto; display: block; margin: .8rem 0;
      border: 1px solid rgba(128,128,128,.3); border-radius: 6px;
      background: #fff; }
table { border-collapse: collapse; font-size: .82rem; display: block;
        overflow-x: auto; max-width: 100%; }
th, td { border: 1px solid rgba(128,128,128,.35); padding: .25rem .5rem;
         text-align: left; white-space: nowrap; }
th { background: rgba(128,128,128,.14); }
code { font-size: .85em; }
.note { border-left: 3px solid #b58900; padding: .4rem .8rem; margin: .8rem 0;
        background: rgba(181,137,0,.08); font-size: .88rem; }
.files a { margin-right: 1rem; font-size: .85rem; }
.band-pass { color: #1a7f37; } .band-drift { color: #b58900; }
.band-fail { color: #b02a37; font-weight: 600; }
"""


def _html_table(header: list, rows: list, limit: int | None = None) -> str:
    teile = ["<table><thead><tr>"
             + "".join(f"<th>{escape(str(h))}</th>" for h in header)
             + "</tr></thead><tbody>"]
    for r in rows[:limit] if limit else rows:
        teile.append("<tr>" + "".join(
            f"<td>{escape('' if v is None else str(v))}</td>" for v in r)
            + "</tr>")
    teile.append("</tbody></table>")
    if limit and len(rows) > limit:
        teile.append(f"<p class='meta'>… {len(rows) - limit} weitere Zeilen "
                     f"in der CSV.</p>")
    return "\n".join(teile)


def _abschnitt(titel: str, *bloecke: str) -> str:
    return f"<h2>{escape(titel)}</h2>\n" + "\n".join(b for b in bloecke if b)


def _bild(out: Path, name: str, alt_text: str) -> str:
    return (f"<img src='{name}' alt='{escape(alt_text)}'>"
            if (out / name).exists() else "")


def _dateien(out: Path, *namen: str) -> str:
    vorhanden = [n for n in namen if (out / n).exists()]
    if not vorhanden:
        return ""
    return ("<p class='files'>Daten: "
            + " ".join(f"<a href='{n}'>{n}</a>" for n in vorhanden) + "</p>")


# --------------------------------------------------------------------------
# Einstiegspunkt
# --------------------------------------------------------------------------

def review_id_for(alt_spec: str, neu_spec: str) -> str:
    return neu_spec if alt_spec == GOLDEN else f"compare-{alt_spec}-vs-{neu_spec}"


def run_review(cfg: dict, *, run: str | None = None, compare: tuple | None = None,
               out_dir: Path | None = None, manifest: Manifest | None = None,
               accepted: dict | None = None) -> Path:
    """Die vier Ansichten ueber zwei Seiten erzeugen. Gibt den Artefaktordner
    zurueck (`reports/corpus/<review-id>/`).

    `manifest`/`accepted` sind Nahtstellen fuer Tests und fuer den Fall, dass
    ein anderer Korpus-Stand ausgewertet werden soll; Default ist der
    versionierte Stand des Repos.
    """
    root = corpus_root(cfg)
    if compare:
        alt_spec, neu_spec = compare
        if alt_spec == "letzte":
            raise ValueError("--compare braucht zwei konkrete Lauf-IDs.")
        neu_spec = latest_run_id(root) if neu_spec == "letzte" else neu_spec
    else:
        alt_spec = GOLDEN
        neu_spec = latest_run_id(root, tier=2) if (run in (None, "letzte")) else run

    alt = load_side(root, alt_spec, manifest)
    neu = load_side(root, neu_spec, manifest)
    gemeinsam = set(alt.reports) & set(neu.reports)
    if not gemeinsam:
        raise RuntimeError(
            f"'{alt_spec}' und '{neu_spec}' haben kein Bild gemeinsam "
            f"({len(alt.reports)} vs. {len(neu.reports)} Reports). Ein Lauf "
            f"ohne Replay-Reports ist meist Tier 1 — die Drift-Review "
            f"braucht auf beiden Seiten Tier-2-Reports.")

    review_id = review_id_for(alt_spec, neu_spec)
    out = Path(out_dir) if out_dir else (
        resolve(cfg.get("corpus_report", {}).get("output_dir", "reports/corpus"))
        / review_id)
    out.mkdir(parents=True, exist_ok=True)

    rows = build_rows(alt, neu, accepted)
    zusammenfassung = write_drift_review(out, rows, alt, neu, cfg, review_id)
    verlauf = write_baseline_history(out, review_id)
    verteilung = write_distributions(out, alt, neu, cfg, review_id)
    quoten, befunde = write_quotas(out, alt, neu, review_id)
    n_confusion = write_confusion(out, alt, neu, review_id)
    t1 = write_tier1_drift(out, neu, review_id) if neu.metrics.get("tier") == 1 else []

    _schreibe_html(out, cfg, review_id, alt, neu, rows, zusammenfassung,
                   verlauf, verteilung, quoten, befunde, n_confusion, t1)
    return out


def _schreibe_html(out, cfg, review_id, alt, neu, rows, zus, verlauf,
                   verteilung, quoten, befunde, n_confusion, t1) -> Path:
    m = cfg.get("matching", {})
    fehlend_alt = sorted(set(neu.reports) - set(alt.reports))
    fehlend_neu = sorted(set(alt.reports) - set(neu.reports))

    kopf = [
        f"<h1>Korpus-Review: {escape(alt.name)} → {escape(neu.name)}</h1>",
        f"<p class='meta'>erzeugt {datetime.now().isoformat(timespec='seconds')}"
        f" · {len(rows)} Bilder auf beiden Seiten"
        f" · Gates: min_llr_margin = {m.get('min_llr_margin')},"
        f" max_z_accept = {m.get('max_z_accept')}</p>",
        f"<p class='meta'>alt: <code>{escape(alt.quelle)}</code> · "
        f"neu: <code>{escape(neu.quelle)}</code></p>",
        "<div class='note'>Reine Konsumentenschicht: alle Band-Urteile "
        "(PASS/DRIFT/FAIL) stammen aus <code>metrics.json</code> bzw. "
        "<code>failures/</code> des Laufs, alle Quoten einer Laufseite aus "
        "dessen <code>metrics.json</code>. Nichts davon wird hier "
        "nachgerechnet.</div>",
    ]
    # Umgebungs-Fingerprint beider Seiten. Bei einem Plattformwechsel ist die
    # erste Frage nach jedem DRIFT "Code oder Bibliothek?" — hier steht die
    # Antwort, statt nachtraeglich rekonstruiert werden zu muessen.
    def _env_text(side):
        e = (side.metrics or {}).get("env") or {}
        if not e:
            return None
        return (f"{side.name}: Python {e.get('python', '?')} · "
                f"numpy {e.get('numpy', '?')} · cv2 {e.get('cv2', '?')} · "
                f"scipy {e.get('scipy', '?')} · {e.get('platform', '?')}")

    env_zeilen = [t for t in (_env_text(alt), _env_text(neu)) if t]
    if env_zeilen:
        env_alt = (alt.metrics or {}).get("env") or {}
        env_neu = (neu.metrics or {}).get("env") or {}
        gleich = (not env_alt or not env_neu
                  or all(env_alt.get(k) == env_neu.get(k)
                         for k in ("python", "numpy", "cv2", "scipy", "platform")))
        kopf.append(
            "<div class='note'><b>Umgebung:</b><ul>"
            + "".join(f"<li>{escape(t)}</li>" for t in env_zeilen)
            + "</ul>"
            + ("" if gleich else
               "<b>Die Seiten liefen auf verschiedenen Umgebungen</b> — DRIFT "
               "ist hier nicht ohne Weiteres code-verursacht.")
            + "</div>")

    if befunde:
        kopf.append("<div class='note'><b>Konsistenz-Befund:</b><ul>"
                    + "".join(f"<li>{escape(b)}</li>" for b in befunde)
                    + "</ul></div>")
    if fehlend_alt or fehlend_neu:
        kopf.append(
            f"<div class='note'>Nicht auf beiden Seiten: "
            f"{len(fehlend_alt)} nur in <code>{escape(neu.name)}</code>, "
            f"{len(fehlend_neu)} nur in <code>{escape(alt.name)}</code> — "
            f"diese Bilder fehlen in allen Vergleichsansichten.</div>")

    baender = " · ".join(
        f"<span class='band-{b}'>{b.upper()}: {n}</span>"
        for b, n in zus["baender"].items())
    aenderungen = " · ".join(f"{k}: {v}" for k, v in zus["aenderungen"].items() if v)
    wechsel = " · ".join(f"{k}: {v}" for k, v in zus["top1_wechsel"].items() if v)

    auffaellig = [r for r in rows if r["aenderung"] in ("entscheidung", "top1")]
    review_spalten = ["sha8", "band", "aenderung", "label", "decision_alt",
                      "decision_neu", "top1_alt", "top1_neu",
                      "llr_margin_alt", "llr_margin_neu", "max_z_alt",
                      "max_z_neu", "treiber_neu", "treiber_z_neu",
                      "delta_status", "delta_kategorie"]

    fehl = zus["neue_fehlbuchungen"]
    fehl_block = (
        "<div class='note' style='border-left-color:#b02a37;"
        "background:rgba(176,42,55,.09)'><b>Neue Fehlbuchungen: "
        f"{len(fehl)}</b> — von <code>{escape(neu.name)}</code> akzeptiert, "
        "obwohl Rang 1 nicht das wahre Label ist, und alt wurde so nicht "
        "gebucht.<ul>"
        + "".join(
            f"<li><code>{escape(r['sha8'])}</code>: {escape(r['label'])} "
            f"gebucht als <b>{escape(r['top1_neu'])}</b> "
            f"({escape(r['decision_alt'])} → {escape(r['decision_neu'])}, "
            f"Margin {r['llr_margin_neu']}, max|z| {r['max_z_neu']})</li>"
            for r in fehl)
        + "</ul></div>") if fehl else (
        "<p><b>Neue Fehlbuchungen: 0.</b></p>")

    teile = kopf + [
        _abschnitt(
            "1. Drift-Review",
            fehl_block,
            f"<p>Baender (Urteil des Laufs): {baender}</p>",
            f"<p>Aenderungen alt→neu: {escape(aenderungen)}</p>",
            "<p class='meta'>Je Bild zaehlt nur die SCHWERSTE Klasse: ein "
            "Bild, dessen Entscheidung UND Rang 1 sich aendern, steht unter "
            "„entscheidung“, nicht unter „top1“. Die Richtungsbilanz darunter "
            "zaehlt dagegen jeden Rang-1-Wechsel — beide Zahlen duerfen "
            "auseinanderlaufen.</p>",
            f"<p>Rang-1-Wechsel: {escape(wechsel) or 'keine'}</p>",
            "<p class='meta'>Rang-1-Wechsel und neue Fehlbuchungen sind "
            "verschiedene Mengen: war Rang 1 schon vorher falsch und kippt "
            "nur die Entscheidung auf accept, entsteht eine Fehlbuchung ohne "
            "Rang-1-Wechsel.</p>",
            _bild(out, "drift_scatter.png", "Margin- und max|z|-Scatter"),
            _bild(out, "decision_matrix.png", "Entscheidungsmatrix alt→neu"),
            f"<h3 style='font-size:1rem'>Bilder mit Entscheidungs- oder "
            f"Rang-1-Wechsel ({len(auffaellig)})</h3>",
            _html_table(review_spalten,
                        [[r[k] for k in review_spalten] for r in auffaellig], 60)
            if auffaellig else "<p>Keine.</p>",
            _dateien(out, "drift_review.csv", "decision_matrix.csv",
                     "top1_wechsel.csv", "neue_fehlbuchungen.csv")),
        _abschnitt(
            "2. Baseline-Verlauf",
            "<p class='meta'>Quoten je Commit, der corpus/baseline.json "
            "angefasst hat — direkt aus der Git-Historie gelesen.</p>",
            _bild(out, "baseline_verlauf.png", "Baseline-Quoten je Commit"),
            _html_table(["commit", "datum", "run_id", "n", "accuracy_top1",
                         "accuracy_top3", "auto_accept_rate",
                         "false_accept_rate", "betreff"],
                        [[p.get(k) for k in
                          ("commit", "datum", "run_id", "n", "accuracy_top1",
                           "accuracy_top3", "auto_accept_rate",
                           "false_accept_rate", "betreff")] for p in verlauf])
            if verlauf else "<p>Keine Historie lesbar (kein git oder Datei "
                            "nie versioniert).</p>",
            _dateien(out, "baseline_verlauf.csv")),
        _abschnitt(
            "3. Verteilungen",
            f"<p class='meta'>Wahres Label aus <code>{escape(alt.name)}</code>; "
            f"korrekt = top1 == label (roh, nicht verdict-basiert). "
            f"LLR-Margin: {verteilung['llr_margin']['korrekt']} korrekt / "
            f"{verteilung['llr_margin']['falsch']} falsch.</p>",
            _bild(out, "verteilungen.png", "Histogramme Margin und max|z|"),
            _dateien(out, "verteilungen.csv")),
        _abschnitt(
            "4. Konfusionsmatrix und Quoten",
            f"<p class='meta'>Konfusion ueber {n_confusion} gelabelte Bilder "
            f"des Replay-Stands <code>{escape(neu.name)}</code>.</p>",
            _bild(out, "confusion_matrix.png", "Konfusionsmatrix"),
            _bild(out, "confusion_matrix_accept.png",
                  "Konfusionsmatrix nur ACCEPT"),
            _bild(out, "quoten.png", "Quoten mit Wilson-CI"),
            _html_table(QUOTEN_HEADER, quoten),
            _dateien(out, "quoten.csv", "confusion_matrix.csv",
                     "confusion_matrix_accept.csv")),
    ]
    if t1:
        teile.append(_abschnitt(
            "5. Tier-1-Drift je Merkmal",
            _bild(out, "tier1_drift.png", "Tier-1-Drift je Merkmal"),
            _html_table(["feld", "bilder", "drift", "fail", "delta_median",
                         "delta_max"],
                        [[z[k] for k in ("feld", "bilder", "drift", "fail",
                                         "delta_median", "delta_max")]
                         for z in t1]),
            _dateien(out, "tier1_drift.csv")))

    html = (f"<!doctype html>\n<html lang='de'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width, "
            f"initial-scale=1'>"
            f"<title>Korpus-Review {escape(review_id)}</title>"
            f"<style>{_HTML_CSS}</style></head><body>\n"
            + "\n".join(teile) + "\n</body></html>\n")
    p = out / "index.html"
    p.write_text(html, encoding="utf-8")
    return p


def publish_review(cfg: dict, review_dir: str | Path) -> Path:
    """Artefakte zusaetzlich ins versionierte Archiv kopieren — analog
    `analysis.publish_run`, aber mit `corpus-`-Praefix, damit ein
    Korpus-Review nie mit einem `analyze`-Lauf gleichen Namens kollidiert."""
    review_dir = Path(review_dir)
    dest = (resolve(cfg.get("analysis", {}).get("publish_dir", "reports/archive"))
            / f"corpus-{review_dir.name}")
    if dest.exists():
        raise FileExistsError(
            f"Archiv-Eintrag existiert bereits: {dest}. Anderen Lauf waehlen "
            f"oder den Eintrag zuerst entfernen — publish ueberschreibt nie.")
    dest.mkdir(parents=True)
    n = 0
    for p in sorted(review_dir.iterdir()):
        if p.is_file():
            shutil.copy2(p, dest / p.name)
            n += 1
    print(f"[corpus-report] {n} Artefakte nach {dest} veroeffentlicht.")
    return dest
