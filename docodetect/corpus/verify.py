"""Konsistenz-Waechter fuer einen gebauten Korpus.

Laeuft VOR einem Replay (aus cmd_corpus_run), rechnet NICHTS neu und
aendert nichts — er stellt nur sicher, dass der eingefrorene
Session-Zustand nicht seiner eigenen Provenienz widerspricht.

Bewusst ausserhalb von runner.py/bundle.py: diese Datei geht NICHT in den
code_fingerprint ein, ein Wächter-Umbau invalidiert den Replay-Cache also
nicht.
"""

from __future__ import annotations

import json
from pathlib import Path


def pruefe_bundle_db_konsistenz(root: str | Path) -> None:
    """Abbruch, wenn eine `session.json` `has_db: true` behauptet, im Buendel
    aber keine `db.sqlite3` liegt.

    Warum LAUT statt still: faellt eine Session-DB weg (geloescht, Buendel
    ohne DB kopiert, Build gegen eine andere DB), sinkt die Session beim
    naechsten `corpus-build` auf Tier 1 — ihre Bilder verschwinden dann
    aus `auswahl(tier=2)`, und ein `corpus-run --tier 2 --check` prueft
    stillschweigend WENIGER Bilder und endet trotzdem mit Exit 0. Genau
    dieser leisere, engere Lauf sieht aus wie „alles gruen". Der Wächter
    macht die Inkonsistenz sichtbar, bevor der Lauf beginnt.

    `session.json` selbst wird zur Laufzeit sonst NICHT gelesen (der
    Runner liest die Tier-Stufe aus dem Manifest). Die Datei ist die
    dokumentierte Zusage der Session; dieser Wächter ist die einzige
    Stelle, die sie gegen die Wirklichkeit auf der Platte prueft.
    """
    root = Path(root)
    runs_dir = root / "runs"
    verletzt = []
    for sj in sorted(root.glob("*/bundle/session.json")):
        # runs/<id>/... enthaelt keine Session-Buendel; nicht mitpruefen.
        try:
            sj.relative_to(runs_dir)
            continue
        except ValueError:
            pass
        try:
            daten = json.loads(sj.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            verletzt.append(f"{sj}: nicht lesbar ({type(exc).__name__})")
            continue
        if daten.get("has_db") and not (sj.parent / "db.sqlite3").is_file():
            name = daten.get("name", sj.parent.parent.name)
            verletzt.append(
                f"{name}: session.json meldet has_db:true, aber "
                f"{sj.parent / 'db.sqlite3'} fehlt")
    if verletzt:
        raise RuntimeError(
            "Korpus inkonsistent — eine als Tier-2-faehig ausgewiesene "
            "Session hat keine Buendel-DB. Ein Tier-2-Lauf prueft sonst "
            "stillschweigend weniger Bilder und endet trotzdem gruen:\n  - "
            + "\n  - ".join(verletzt)
            + "\nBehebung: 'corpus-build' erneut ausfuehren (stellt die DB "
            "wieder her) ODER die Session bewusst nach backups/ verschieben "
            "und neu bauen.")
