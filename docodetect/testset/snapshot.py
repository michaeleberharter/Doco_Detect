"""Zustands-Snapshots: einfrieren, pruefen, Replay-Config bauen.

Ein Snapshot ist der komplette Zustand, gegen den eine Gruppe von
Aufnahmen gerechnet wurde: Hintergrund, Kalibrierung, DB-Stand und die
wirksamen Config-Bloecke (features + matching). Aufnahmen derselben
Session teilen EINEN Snapshot; die Zuordnung laeuft ueber den
Gesamt-Fingerprint aus pipeline.aufnahme_zustand — nie ueber
Rekonstruktion.

Eingefroren wird NUR, wenn der Live-Zustand beim Build exakt dem
zustand-Block des Reports entspricht (Hash-Gleichheit aller Komponenten).
Ist der Zustand schon weitergezogen (neu kalibriert, neu eingelernt),
ist er verloren — das wird gemeldet, nicht angenaehert.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from ..config import resolve
from ..corpus.bundle import bundle_cfg, copy_db_readonly
from ..pipeline import _ZUSTAND_KOMPONENTEN, _db_zustand_sha256, _sha256_datei

SNAPSHOT_DATEIEN = ("background.png", "calibration.json", "db.sqlite3",
                    "zustand.json")


def snapshot_dir(root: Path, fp12: str) -> Path:
    return Path(root) / "snapshots" / fp12


def lade_zustand(root: Path, fp12: str) -> dict:
    return json.loads((snapshot_dir(root, fp12) / "zustand.json")
                      .read_text(encoding="utf-8"))


def _cfg_block_sha256(block: dict) -> str:
    """Identisch zur Kanonisierung in pipeline.aufnahme_zustand/_fingerabdruck
    — nur so ist der Rueckvergleich gegen die Komponenten-Hashes gueltig."""
    return hashlib.sha256(
        json.dumps(block, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def friere_snapshot_ein(cfg: dict, root: Path, zustand: dict,
                        code_fp: str) -> Path:
    """Live-Zustand unter snapshots/<fp12>/ einfrieren.

    Voraussetzung (prueft der Aufrufer per Fingerprint-Gleichheit): die
    Live-Dateien SIND der Zustand aus `zustand`. Nach dem Kopieren wird
    jede Datei gegen ihren Komponenten-Hash verifiziert — ein Enrollment
    oder eine Kalibrierung, die WAEHREND des Builds dazwischenfunkt,
    fliegt hier auf statt still ein falsches Buendel zu hinterlassen."""
    fp12 = zustand["fingerprint"][:12]
    ziel = snapshot_dir(root, fp12)
    ziel.mkdir(parents=True, exist_ok=True)

    import shutil
    shutil.copy2(str(resolve(cfg["calibration"]["background_file"])),
                 str(ziel / "background.png"))
    shutil.copy2(str(resolve(cfg["calibration"]["file"])),
                 str(ziel / "calibration.json"))
    copy_db_readonly(resolve(cfg["paths"]["db_file"]), ziel / "db.sqlite3")

    payload = dict(zustand)
    payload["config"] = {"features": cfg.get("features", {}),
                         "matching": cfg.get("matching", {})}
    payload["code_fingerprint"] = code_fp
    payload["eingefroren"] = datetime.now().isoformat(timespec="seconds")
    (ziel / "zustand.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")

    befunde = pruefe_snapshot(root, fp12)
    if befunde:
        raise RuntimeError(
            f"Snapshot {fp12} direkt nach dem Einfrieren inkonsistent "
            f"({'; '.join(befunde)}) — Zustand hat sich waehrend des Builds "
            f"geaendert. Build wiederholen, wenn nichts mehr schreibt.")
    return ziel


def pruefe_snapshot(root: Path, fp12: str) -> list:
    """Integritaet eines Snapshots: Dateien vorhanden UND ihre Hashes
    entsprechen den Komponenten des Fingerprints. -> Liste von Befunden,
    [] = intakt. Ein unvollstaendiges oder veraendertes Buendel ist ein
    FEHLER des ganzen Snapshots, nie ein stiller Teil-Lauf."""
    d = snapshot_dir(root, fp12)
    befunde = []
    fehlend = [n for n in SNAPSHOT_DATEIEN if not (d / n).is_file()]
    if fehlend:
        return [f"unvollstaendig: {', '.join(fehlend)} fehlt"]
    try:
        z = lade_zustand(root, fp12)
    except (json.JSONDecodeError, OSError) as exc:
        return [f"zustand.json unlesbar: {exc}"]

    # Gesamt-Fingerprint muss zu seinen Komponenten passen
    gesamt = hashlib.sha256()
    for k in _ZUSTAND_KOMPONENTEN:
        gesamt.update(str(z.get(k, "")).encode("utf-8"))
    if gesamt.hexdigest() != z.get("fingerprint"):
        befunde.append("fingerprint passt nicht zu den Komponenten")

    if _sha256_datei(d / "background.png") != z.get("background_sha256"):
        befunde.append("background.png weicht vom eingefrorenen Hash ab")
    if _sha256_datei(d / "calibration.json") != z.get("calibration_sha256"):
        befunde.append("calibration.json weicht vom eingefrorenen Hash ab")

    # DB ueber den Zeilen-Hash (nicht Dateibytes: die Backup-API normalisiert
    # Journal/Freelist, Bytes sind kein stabiler Vergleich). Read-only-URI +
    # SimpleNamespace statt Database: Database.__init__ legt fehlende Dateien
    # an und liefe Schema-Migrationen — beides hat in einer Pruefung nichts
    # verloren.
    con = sqlite3.connect(f"file:{d / 'db.sqlite3'}?mode=ro", uri=True)
    try:
        db_hash = _db_zustand_sha256(SimpleNamespace(conn=con))
    except sqlite3.Error as exc:
        befunde.append(f"db.sqlite3 nicht pruefbar: {exc}")
        db_hash = None
    finally:
        con.close()
    if db_hash is not None and db_hash != z.get("db_zustand_sha256"):
        befunde.append("db.sqlite3 weicht vom eingefrorenen DB-Stand ab")

    konfig = z.get("config") or {}
    if _cfg_block_sha256(konfig.get("features", {})) != z.get("features_cfg_sha256"):
        befunde.append("features-Block weicht vom eingefrorenen Hash ab")
    if _cfg_block_sha256(konfig.get("matching", {})) != z.get("matching_cfg_sha256"):
        befunde.append("matching-Block weicht vom eingefrorenen Hash ab")
    return befunde


def snapshot_cfg(cfg: dict, root: Path, fp12: str) -> dict:
    """Replay-Config fuer einen Snapshot: wie corpus.bundle.bundle_cfg
    (DB/Kalibrierung/Hintergrund aufs Buendel, captures_dir=None — das
    Replay schreibt nie Captures), zusaetzlich features- und matching-Block
    aus dem EINGEFRORENEN Zustand statt der Live-Config. Die Bloecke sind
    Teil des Fingerprints — mit Live-Werten rechnete das Replay gegen einen
    anderen Zustand, als das Buendel behauptet."""
    out = bundle_cfg(cfg, snapshot_dir(root, fp12))
    konfig = lade_zustand(root, fp12).get("config") or {}
    out["features"] = konfig.get("features", {})
    out["matching"] = konfig.get("matching", {})
    return out
