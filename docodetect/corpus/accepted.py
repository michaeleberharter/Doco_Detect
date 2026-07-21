"""Akzeptierte, versionierte Abweichungen einzelner Korpus-Bilder von ihrem
urspruenglichen Golden-Report.

Hintergrund: die Golden-Reports (`phase-b/reports/*.json` im externen
Korpus) sind das historische Mess- und Bewertungsprotokoll echter Aufnahmen
und werden NIE veraendert - auch nicht nach einem bewusst reviewten,
korrekten Matcher-Fix. Ohne diese Schicht wuerde `corpus-run --tier 2
--check` nach jeder Verhaltensaenderung dauerhaft FAIL melden, selbst wenn
die neue Ausgabe geprueft und akzeptiert wurde.

Eine Delta-Datei unter `corpus/accepted_deltas/*.json` beschreibt darum pro
Bild (Schluessel: die ersten 8 Zeichen des Bild-SHA, wie in den Golden-/
Replay-Dateinamen) die NEUEN, akzeptierten Matcher-Ausgabefelder plus
Begruendung und Verweis auf Fix-Commit/Ergebnisdokument. `resolve_diffs`
vergleicht einen Replay wahlweise gegen das Original-Golden ODER (wenn das
fehlschlaegt und ein Delta existiert) gegen das akzeptierte Delta - passt
keines von beiden, bleibt es FAIL. Eine neue, nicht akzeptierte Abweichung
auf einem Bild, das bereits ein Delta hat, faellt also weiterhin durch.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from ..config import project_root
from .compare import compare_tier2

ACCEPTED_DIR = project_root() / "corpus" / "accepted_deltas"


def load_all(accepted_dir: Path | None = None) -> dict:
    """sha8 -> Delta-Eintrag, gemergt ueber alle *.json im Verzeichnis
    (sortiert nach Dateiname, damit ein spaeterer Eintrag einen frueheren
    fuer dasselbe Bild bewusst ueberschreiben kann)."""
    d = accepted_dir or ACCEPTED_DIR
    merged: dict = {}
    if not d.is_dir():
        return merged
    for f in sorted(d.glob("*.json")):
        payload = json.loads(f.read_text(encoding="utf-8"))
        for sha8, entry in payload.get("images", {}).items():
            merged[sha8] = {
                **entry,
                "_source": f.name,
                "_fix_commit": payload.get("fix_commit"),
                "_results_doc": payload.get("results_doc"),
            }
    return merged


def _as_report(expected: dict) -> SimpleNamespace:
    """Minimal-Duck-Type fuer compare_tier2: nur die vier Tier-2-Felder,
    die dort verglichen werden (decision/candidates/gate_passed/
    llr_margin/max_z_winner)."""
    return SimpleNamespace(
        decision=expected["decision"],
        candidates=[SimpleNamespace(article_number=a)
                   for a in expected["candidates"]],
        gate_passed=expected["gate_passed"],
        llr_margin=expected.get("llr_margin"),
        max_z_winner=expected.get("max_z_winner"))


def resolve_diffs(sha: str, actual, diffs: list,
                  accepted_dir: Path | None = None) -> list:
    """`diffs` ist das Ergebnis von `compare_tier2(golden, actual)`. Leer
    (bereits PASS/DRIFT) bleibt unangetastet. Bei einer FAIL-Abweichung:
    gibt es fuer dieses Bild einen akzeptierten Delta-Eintrag, wird
    STATTDESSEN gegen dessen erwartete Felder verglichen - reproduziert der
    Replay das Delta exakt, PASS; jede darueber hinausgehende, nicht
    akzeptierte Abweichung bleibt FAIL."""
    if not diffs:
        return diffs
    entry = load_all(accepted_dir).get(sha[:8])
    if entry is None:
        return diffs
    return compare_tier2(_as_report(entry["expected"]), actual)
