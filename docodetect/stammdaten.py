"""Geometrische Stammdaten an die Enrollment-Mittelwerte angleichen.

Hintergrund: `create-article` leitet die Stammdaten aus EINEM Shot ab,
`enroll` mittelt über n Shots. Beide messen über denselben Weg
(`Pipeline.analyze`), speichern aber VERSCHIEDENE Größen:

    create-article, rund     -> articles.diameter_mm  = minEnclosingCircle-Ø
    create-article, länglich -> articles.width/depth  = minAreaRect-Seiten
    enroll (beide)           -> reference_stats.scalar_mean["diameter_mm"]
                                = minEnclosingCircle-Ø, über n Shots gemittelt

Der Geometrie-Vorfilter in `matcher.py` vergleicht den gemessenen
minEnclosingCircle-Ø gegen `_nominal_size_mm(article)`, also gegen
`diameter_mm` bzw. `hypot(width_mm, depth_mm)`. GENAU diese Größe wird hier
auf den Enrollment-Mittelwert gezogen – bei länglichen Artikeln über einen
gemeinsamen Faktor auf width und depth, damit das Seitenverhältnis aus dem
minAreaRect (echte Information) erhalten bleibt.

Nur lesend, solange `apply_sync` nicht gerufen wird.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .database import Database

# Ein einzelner Shot ist kein Mittelwert – dagegen zu synchronisieren
# verschiebt die Stammdaten ohne Gewinn an Genauigkeit.
DEFAULT_MIN_SHOTS = 2


@dataclass
class SyncRow:
    """Eine Artikel-Zeile der Diff-Tabelle."""
    article_number: str
    name: str
    n_shots: int
    nominal_alt: float               # was der Vorfilter heute vergleicht
    nominal_neu: float               # Enrollment-Mittel (minEnclosingCircle-Ø)
    felder: dict = field(default_factory=dict)   # Spalte -> (alt, neu)

    @property
    def diff_mm(self) -> float:
        return self.nominal_neu - self.nominal_alt


def compute_sync(db: Database, min_shots: int = DEFAULT_MIN_SHOTS) -> tuple[list, list]:
    """(Zeilen mit Änderungsbedarf, Hinweise zu übersprungenen Artikeln).

    Rein lesend – schreibt nichts."""
    rows: list = []
    skipped: list = []
    for art in db.all_articles():
        stats = db.stats_for(art.article_number)
        if stats is None:
            continue                     # nie eingelernt – nichts abzugleichen
        mean = stats.scalar_mean.get("diameter_mm")
        if mean is None:
            skipped.append(f"{art.article_number}: Referenzen ohne Ø-Statistik")
            continue
        if stats.n_shots < min_shots:
            skipped.append(f"{art.article_number}: nur {stats.n_shots} Shot(s) "
                           f"< {min_shots}")
            continue

        if art.diameter_mm:
            alt = float(art.diameter_mm)
            felder = {"diameter_mm": (alt, round(mean, 2))}
        elif art.width_mm and art.depth_mm:
            w, d = float(art.width_mm), float(art.depth_mm)
            alt = math.hypot(w, d)
            f = mean / alt if alt > 0 else 1.0
            felder = {"width_mm": (w, round(w * f, 2)),
                      "depth_mm": (d, round(d * f, 2))}
        elif art.width_mm:
            alt = float(art.width_mm)
            felder = {"width_mm": (alt, round(mean, 2))}
        else:
            skipped.append(f"{art.article_number}: keine Maße in den Stammdaten")
            continue

        rows.append(SyncRow(article_number=art.article_number, name=art.name,
                            n_shots=stats.n_shots, nominal_alt=round(alt, 2),
                            nominal_neu=round(mean, 2), felder=felder))
    rows.sort(key=lambda r: -abs(r.diff_mm))
    return rows, skipped


def apply_sync(db: Database, rows: list) -> int:
    """Die berechneten Stammdaten wirklich schreiben. Gibt die Zahl der
    geänderten Artikel zurück."""
    for r in rows:
        db.update_geometry(r.article_number,
                           **{k: neu for k, (_, neu) in r.felder.items()})
    return len(rows)


def format_table(rows: list, skipped: list, min_shots: int,
                 applied: bool = False) -> str:
    """Diff-Tabelle für die CLI – dieselbe Darstellung vor und nach --apply."""
    head = "geschrieben" if applied else "Vorschau (nichts geschrieben)"
    out = [f"\n=== sync-stammdaten – {head} ===", ""]
    if not rows:
        out.append("  Keine Artikel mit Enrollment-Statistik (>= "
                   f"{min_shots} Shots) gefunden – nichts zu tun.")
    else:
        out.append(f"  {'Artikel':<14} {'n':>3} {'Vorfilter-Nominal':>18} "
                   f"{'Enroll-Mittel':>14} {'Diff':>8}   Felder")
        out.append("  " + "-" * 92)
        for r in rows:
            felder = ", ".join(f"{k} {alt:.1f}->{neu:.1f}"
                               for k, (alt, neu) in r.felder.items())
            out.append(f"  {r.article_number:<14} {r.n_shots:>3} "
                       f"{r.nominal_alt:>18.2f} {r.nominal_neu:>14.2f} "
                       f"{r.diff_mm:>+8.2f}   {felder}")
        diffs = [r.diff_mm for r in rows]
        out.append("  " + "-" * 92)
        out.append(f"  {len(rows)} Artikel, Diff Mittel "
                   f"{sum(diffs) / len(diffs):+.2f} mm, "
                   f"min {min(diffs):+.2f}, max {max(diffs):+.2f}")
    for s in skipped:
        out.append(f"  [übersprungen] {s}")
    out.append("")
    out.append("  Angeglichen wird die Größe, die der Vorfilter vergleicht "
               "(diameter_mm bzw. hypot(width, depth)).")
    out.append("  Bei länglichen Artikeln skalieren width und depth mit "
               "gemeinsamem Faktor – das Seitenverhältnis bleibt erhalten.")
    if not applied and rows:
        out.append("  Schreiben: denselben Befehl mit --apply wiederholen.")
    return "\n".join(out)
