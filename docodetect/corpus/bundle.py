"""Session-Buendel: Fingerprints, Verifikation, Replay-Config.

Reports tragen kein Session-Feld (das Einbetten wuerde pipeline.py
beruehren und ist aufgeschoben). Die Zuordnung laeuft deshalb ueber drei
aus den Reports REKONSTRUIERBARE Fingerprints — siehe Spec 1.1.
"""

from __future__ import annotations

import copy
import json
import math
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path

import cv2
import numpy as np

# Merkmalsname im Report -> Name des sigma_floor in der Config
FLOOR_NAMES = {
    "diameter_mm": "diameter_mm",
    "circularity": "circularity",
    "solidity": "solidity",
    "delta_e_center": "delta_e",
    "delta_e_rim": "delta_e",
    "hist_center": "hist_bhattacharyya",
    "hist_rim": "hist_bhattacharyya",
    "hu_log": "hu_log",
}


def recover_mm_per_px(report) -> float | None:
    """Kalibrier-Fingerprint: der gespeicherte Kreis-Ø in mm geteilt durch
    den aus der Kontur gerechneten Kreis-Ø in px. Die Kontur ist auf ~400
    Punkte ausgeduennt, das Ergebnis daher auf ~0,1 % genau — genug, um
    Kalibrier-Epochen zu TRENNEN, nicht um eine Kalibrierung zu ersetzen."""
    d_mm = (report.measured or {}).get("circle_diameter_mm")
    if not d_mm or not report.contour:
        return None
    pts = np.asarray(report.contour, dtype=np.float32).reshape(-1, 1, 2)
    if len(pts) < 3:
        return None
    _, radius_px = cv2.minEnclosingCircle(pts)
    if radius_px <= 0:
        return None
    return float(d_mm) / (2.0 * float(radius_px))


def recover_sigma_floors(report) -> dict:
    """Config-Fingerprint: sigma_eff^2 = sigma_enroll^2 + sigma_floor^2,
    also floor = sqrt(eff^2 - enroll^2). Liefert je Floor-Name den Median
    ueber alle Kandidaten/Merkmale."""
    samples: dict = {}
    for cand in report.candidates:
        for f in cand.features:
            name = FLOOR_NAMES.get(f.feature)
            if name is None:
                continue
            var = f.sigma_eff ** 2 - f.sigma_enroll ** 2
            if var > 0:
                samples.setdefault(name, []).append(math.sqrt(var))
    out = {}
    for name, vals in samples.items():
        vals.sort()
        out[name] = round(vals[len(vals) // 2], 4)
    return out


def db_match_ratio(reports: list, db_path: str | Path) -> float:
    """Anteil der Kandidaten-Referenzwerte, die EXAKT zu diesem DB-Snapshot
    passen. Geprueft wird das Enrollment-Mittel des Ø plus n_shots — beides
    steht im Report und in reference_stats. 1.0 = dieser Snapshot ist der
    Zustand, gegen den damals gematcht wurde. Alles darunter heisst:
    falsche DB, Session faellt auf Tier 1 zurueck."""
    db_path = Path(db_path)
    if not db_path.exists():
        return 0.0
    stats: dict = {}
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        for art, sj in con.execute(
                "SELECT article_number, stats_json FROM reference_stats"):
            s = json.loads(sj)
            stats[art] = (s.get("n_shots"),
                          s.get("scalar_mean", {}).get("diameter_mm"))
    except sqlite3.Error:
        return 0.0
    finally:
        con.close()

    hit = total = 0
    for r in reports:
        for cand in r.candidates:
            ref = next((f.reference for f in cand.features
                        if f.feature == "diameter_mm"), None)
            if ref is None:
                continue
            total += 1
            got = stats.get(cand.article_number)
            if got and got[0] == cand.n_shots and got[1] is not None \
                    and abs(got[1] - ref) < 1e-9:
                hit += 1
    return hit / total if total else 0.0


def copy_db_readonly(src: str | Path, dst: str | Path) -> None:
    """DB-Snapshot ziehen, ohne die Quelle anzufassen: Backup-API auf einer
    mode=ro-Verbindung. Die echte doco_detect.sqlite3 wird dabei nur
    gelesen — kein Schreibzugriff, kein Journal, kein Schema-Eingriff."""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    quelle = sqlite3.connect(f"file:{Path(src)}?mode=ro", uri=True)
    ziel = sqlite3.connect(dst)
    try:
        quelle.backup(ziel)
    finally:
        ziel.close()
        quelle.close()


@dataclass
class SessionBundle:
    name: str
    bundle_dir: str
    has_db: bool
    db_verified: float          # Anteil exakt passender Referenzwerte (0..1)
    mm_per_px: float | None
    sigma_floors: dict = field(default_factory=dict)
    tier: int = 1
    provenance: str = ""

    @property
    def tier2_ready(self) -> bool:
        """Tier 2 nur bei vollstaendig verifiziertem Snapshot. Ein knapp
        verfehlter Abgleich ist KEIN 'fast richtig', sondern eine andere
        Datenbank."""
        return self.has_db and self.db_verified >= 1.0


def write_session_json(bundle_dir: str | Path, bundle: SessionBundle) -> Path:
    p = Path(bundle_dir) / "session.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(asdict(bundle), indent=2, ensure_ascii=False) + "\n",
                 encoding="utf-8")
    return p


def bundle_cfg(cfg: dict, bundle_dir: str | Path) -> dict:
    """Replay-Config: zeigt auf das Buendel statt auf den Live-Zustand und
    schaltet das Schreiben von Captures ab (pipeline._save_capture_and_report
    kehrt bei captures_dir=None sofort zurueck). Das Original-cfg bleibt
    unveraendert."""
    b = Path(bundle_dir)
    out = copy.deepcopy(cfg)
    out.setdefault("paths", {})
    out.setdefault("calibration", {})
    out["paths"]["db_file"] = str(b / "db.sqlite3")
    out["paths"]["captures_dir"] = None
    out["calibration"]["file"] = str(b / "calibration.json")
    out["calibration"]["background_file"] = str(b / "background.png")
    return out
