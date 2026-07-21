"""Floor-Auswertung: `matching.sigma_floors` aus einer Messreihe bestimmen
(README: "ein Artikel 15-20x neu auflegen") statt von Hand durch
`reference_stats`/Report-JSONs zu blättern.

CLI: python -m docodetect.cli analyze-floors [reports_dir] [--label ART-NR]
     [--since ISO] [--until ISO] [--limit N]

Liest MatchReport-JSONs (deren `measured`-Block), rekonstruiert daraus
`Features` und nutzt DIESELBE Statistik wie das Einlernen
(`docodetect.features.compute_enrollment_stats`) — die Floor-Kandidaten
sind damit exakt das, was `matcher.py` als `sigma_enroll` für einen frisch
eingelernten Artikel berechnen würde:

- Skalar-Merkmale (Ø, Rundheit, Solidity): Floor = Stichproben-Std der
  Rohwerte über die Messreihe (deckt sich mit dem config.yaml-Kommentar
  "die Standardabweichung je Merkmal ist der Floor").
- Prototyp-Merkmale (ΔE, Histogramm, Hu-Momente): jedes Merkmal wird im
  Scoring nur als DISTANZ zu einem Prototyp verwendet, nie als Rohwert —
  der Floor ist darum der RMS der Distanzen jeder Aufnahme zum Prototyp
  DIESER Messreihe (identische Formel wie `features._proto_stats`).
- `delta_e_center`/`delta_e_rim` teilen sich einen Floor (`delta_e`),
  ebenso `hist_center`/`hist_rim` (`hist_bhattacharyya`) — für diese wird
  über beide Distanzlisten gepoolt (verkettet), nicht das arithmetische
  Mittel zweier RMS-Werte gebildet.

Kein Eingriff in den Messpfad: reine Auswertung über bereits gespeicherte
Reports, schreibt nichts zurück.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .features import (PROTO_FEATURES, SCALAR_FEATURES, Features,
                       compute_enrollment_stats, proto_distance, scalar_value)
from .matcher import MatchReport
from .reporting import load_reports

# Score-Feature -> Key in matching.sigma_floors. Muss deckungsgleich mit
# matcher._FLOOR_KEY bleiben (tests/test_floor_analysis.py prüft das).
FLOOR_KEY = {
    "diameter_mm": "diameter_mm",
    "circularity": "circularity",
    "solidity": "solidity",
    "delta_e_center": "delta_e",
    "delta_e_rim": "delta_e",
    "hist_center": "hist_bhattacharyya",
    "hist_rim": "hist_bhattacharyya",
    "hu_log": "hu_log",
}

# Reihenfolge des sigma_floors-YAML-Blocks in config/config.yaml.
FLOOR_ORDER = ("diameter_mm", "circularity", "solidity", "delta_e",
              "hist_bhattacharyya", "hu_log")

MIN_N = 10       # unter dieser Stichprobengroesse: Warnung
OUTLIER_Z = 3.0  # |x - mean| > OUTLIER_Z * std -> Ausreisser


@dataclass
class Outlier:
    feature: str          # Score-Feature, das den Ausreisser meldet
    report_path: str
    value: float
    z: float


@dataclass
class FeatureFloor:
    floor_key: str
    n: int
    mean: float
    std: float           # Stichproben-Std der gepoolten Rohwerte/Distanzen
    floor: float          # empfohlener sigma_floors-Wert (Skalar: std, Proto: RMS)
    minimum: float
    maximum: float
    low_n_warning: bool
    outliers: list[Outlier] = field(default_factory=list)


@dataclass
class FloorReport:
    n_reports: int         # Anzahl Reports nach Filter/Limit, VOR measured-Check
    n_usable: int          # davon mit gesetztem measured-Block
    features: dict          # floor_key -> FeatureFloor, nur vorhandene Merkmale


def _filter_reports(reports: list, *, label: str | None,
                    since: str | None, until: str | None) -> list:
    out = []
    for p, r in reports:
        if label is not None and r.label != label:
            continue
        ts = r.timestamp or ""
        if since is not None and ts < since:
            continue
        if until is not None and ts > until:
            continue
        out.append((p, r))
    return out


def _feature_floor(floor_key: str, samples: list) -> FeatureFloor:
    """samples: Liste (report_path, value) - fuer Skalare der Rohwert, fuer
    Prototyp-Merkmale die Distanz zum Messreihen-Prototyp; bei zwei
    beitragenden Score-Features (delta_e, hist_bhattacharyya) bereits ueber
    beide gepoolt (verkettet)."""
    values = np.asarray([v for _, v in samples], dtype=np.float64)
    n = len(values)
    mean = float(values.mean())
    std = float(values.std(ddof=1)) if n > 1 else 0.0
    is_scalar = floor_key in SCALAR_FEATURES
    floor = std if is_scalar else float(np.sqrt(np.mean(np.square(values))))
    outliers = []
    if std > 0:
        for (path, v), z in zip(samples, np.abs(values - mean) / std):
            if z > OUTLIER_Z:
                outliers.append(Outlier(feature=floor_key, report_path=path,
                                        value=float(v), z=round(float(z), 2)))
    return FeatureFloor(
        floor_key=floor_key, n=n, mean=round(mean, 4), std=round(std, 4),
        floor=round(floor, 4), minimum=round(float(values.min()), 4),
        maximum=round(float(values.max()), 4), low_n_warning=n < MIN_N,
        outliers=outliers)


def analyze_floors(reports_dir: str | Path, *, label: str | None = None,
                   since: str | None = None, until: str | None = None,
                   limit: int | None = None) -> FloorReport:
    """Laedt Report-JSONs aus reports_dir (neueste zuerst, wie `analyze`),
    filtert optional nach Label/Zeitfenster, nimmt danach die letzten
    `limit` und wertet die Merkmalsstreuung ueber die verbleibende
    Messreihe aus."""
    raw = load_reports(reports_dir)
    filtered = _filter_reports(raw, label=label, since=since, until=until)
    if limit is not None:
        filtered = filtered[:limit]

    paths, feats_list = [], []
    for p, r in filtered:
        if not r.measured:
            continue
        feats_list.append(Features(**r.measured))
        paths.append(str(p))

    stats = compute_enrollment_stats(feats_list)

    # Rohwerte/Distanzen je Score-Feature sammeln, dann auf floor_key poolen.
    per_floor_key: dict[str, list] = {}
    for name in SCALAR_FEATURES:
        samples = [(p, v) for p, f in zip(paths, feats_list)
                  if (v := scalar_value(f, name)) is not None]
        per_floor_key.setdefault(FLOOR_KEY[name], []).extend(samples)
    for name in PROTO_FEATURES:
        samples = [(p, d) for p, f in zip(paths, feats_list)
                  if (d := proto_distance(name, f, stats)) is not None]
        per_floor_key.setdefault(FLOOR_KEY[name], []).extend(samples)

    features = {fk: _feature_floor(fk, samples)
               for fk, samples in per_floor_key.items() if samples}

    return FloorReport(n_reports=len(filtered), n_usable=len(feats_list),
                       features=features)


def format_table(report: FloorReport) -> str:
    header = f"{'Merkmal':<20} {'n':>4} {'mean':>10} {'std':>10} {'floor':>10} {'min':>10} {'max':>10}"
    lines = [header, "-" * len(header)]
    for fk in FLOOR_ORDER:
        ff = report.features.get(fk)
        if ff is None:
            lines.append(f"{fk:<20} {'—':>4} (keine Werte in der Messreihe)")
            continue
        warn = "  [n<10!]" if ff.low_n_warning else ""
        lines.append(f"{fk:<20} {ff.n:>4} {ff.mean:>10} {ff.std:>10} "
                     f"{ff.floor:>10} {ff.minimum:>10} {ff.maximum:>10}{warn}")
    return "\n".join(lines)


def format_yaml_block(report: FloorReport) -> str:
    lines = ["sigma_floors:"]
    for fk in FLOOR_ORDER:
        ff = report.features.get(fk)
        value = ff.floor if ff is not None else "?  # keine Werte in der Messreihe"
        lines.append(f"  {fk}: {value}")
    return "\n".join(lines)


def format_diameter_summary(report: FloorReport) -> str | None:
    """Explizite Ø-Streuung (min/max/std) - beantwortet, ob ein bekanntes
    Restresiduum (z.B. das ~3,16mm der Ex-Kills, siehe
    docs/superpowers/reports/2026-07-21-vorfilter-laengliche-artikel-
    ergebnis.md) im Bereich des reinen Auflage-Rauschens liegt oder darueber."""
    ff = report.features.get("diameter_mm")
    if ff is None:
        return None
    return (f"Ø-Streuung ueber {ff.n} Aufnahmen derselben Auflage: "
           f"min {ff.minimum} mm, max {ff.maximum} mm, "
           f"Spannweite {round(ff.maximum - ff.minimum, 4)} mm, "
           f"Std {ff.std} mm.")


def format_outliers(report: FloorReport) -> str | None:
    all_outliers = [o for ff in report.features.values() for o in ff.outliers]
    if not all_outliers:
        return None
    lines = [f"Ausreisser (|x-mean| > {OUTLIER_Z}*std):"]
    for o in all_outliers:
        lines.append(f"  {o.feature}: {o.report_path} = {o.value} (z={o.z})")
    return "\n".join(lines)


def format_warnings(report: FloorReport) -> list:
    out = []
    for fk, ff in report.features.items():
        if ff.low_n_warning:
            out.append(f"n={ff.n} < {MIN_N} fuer '{fk}' - Floor-Schaetzung "
                       f"unsicher, mehr Aufnahmen empfohlen.")
    return out
