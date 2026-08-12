"""Manifest des Real-Capture-Testsets.

Einzige versionierte Datei des Testsets (testset/manifest.json im Repo).
Alle Pfade darin sind relativ zu paths.testset_dir — das Testset zieht wie
der Korpus als Ordner um, ohne dass ein Pfad bricht.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..config import project_root

MANIFEST_PATH = project_root() / "testset" / "manifest.json"

DEFAULT_TESTSET_DIR = "../Doco_Detect_testset"

# Wahrheit "Objekt ist nicht in der Datenbank" (reporting.NO_MATCH) — als
# Ordnername unter captures/ zulaessig, prueft der Builder nie gegen die DB.
NO_MATCH_ARTIKEL = "NO_MATCH"


def testset_root(cfg: dict) -> Path:
    """Wurzel des Testsets, relativ zum Projekt aufgeloest."""
    raw = cfg.get("paths", {}).get("testset_dir") or DEFAULT_TESTSET_DIR
    p = Path(raw)
    return p if p.is_absolute() else (project_root() / p).resolve()


@dataclass
class CaptureEntry:
    sha: str              # SHA-256 des Capture-PNG
    artikel: str          # WAHRER Artikel (aus der Bewertung, nie Vorhersage)
    label_herkunft: str   # verdict-richtig | verdict-falsch+artikel | evaluate-label
    snapshot: str         # fingerprint[:12] des Zustands-Snapshots
    timestamp: str        # Aufnahmezeitpunkt aus dem Report (µs)
    image_rel: str
    report_rel: str
    notiz: str | None = None


@dataclass
class TestsetManifest:
    # pytest sammelt sonst jede in Testmodule importierte "Test*"-Klasse
    # als vermeintliche Testklasse ein — das hier ist ein Datentraeger.
    __test__ = False

    version: int = 1
    generated: str = ""
    # fingerprint[:12] -> Kopf des Snapshots (Plattform, Backend-Override,
    # Versionen, code_fingerprint, mm_per_px/camera_height_mm, eingefroren).
    snapshots: dict = field(default_factory=dict)
    captures: list = field(default_factory=list)

    def by_sha(self) -> dict:
        return {e.sha: e for e in self.captures}

    def save(self) -> Path:
        MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": self.version,
            "generated": self.generated,
            "snapshots": dict(sorted(self.snapshots.items())),
            # sortiert -> stabile git-Diffs unabhaengig von der Build-Reihenfolge
            "captures": [asdict(e) for e in
                         sorted(self.captures, key=lambda e: e.sha)],
        }
        MANIFEST_PATH.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
        return MANIFEST_PATH

    @staticmethod
    def load() -> "TestsetManifest":
        if not MANIFEST_PATH.exists():
            return TestsetManifest()
        d = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        return TestsetManifest(
            version=d.get("version", 1), generated=d.get("generated", ""),
            snapshots=d.get("snapshots", {}),
            captures=[CaptureEntry(**e) for e in d.get("captures", [])])
