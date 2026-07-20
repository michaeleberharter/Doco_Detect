"""Manifest des Regressions-Korpus.

Einzige versionierte Datei des Korpus. Alle Pfade darin sind relativ zu
paths.corpus_dir, damit der Korpus 1:1 auf den Windows-Rechner umziehen
kann: Ordner kopieren, corpus_dir in config.local.yaml setzen, fertig.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..config import project_root

MANIFEST_PATH = project_root() / "corpus" / "manifest.json"

DEFAULT_CORPUS_DIR = "../Doco_Detect_corpus"


def sha256_file(path: str | Path, chunk: int = 1 << 20) -> str:
    """Inhalts-Hash einer Datei. Blockweise, damit 4K-PNGs nicht komplett
    in den Speicher müssen."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def corpus_root(cfg: dict) -> Path:
    """Wurzel des Korpus, relativ zum Projekt aufgelöst."""
    raw = cfg.get("paths", {}).get("corpus_dir") or DEFAULT_CORPUS_DIR
    p = Path(raw)
    return p if p.is_absolute() else (project_root() / p).resolve()


@dataclass
class ImageEntry:
    sha: str
    session: str
    article: str          # wahrer Artikel; "_unbewertet" ohne Label
    image_rel: str
    report_rel: str
    label: str | None
    verdict: str | None
    tier: int             # hoechste Stufe, die dieses Bild fahren kann (1 oder 2)


@dataclass
class Manifest:
    version: int = 1
    generated: str = ""
    sessions: dict = field(default_factory=dict)
    images: list = field(default_factory=list)

    def by_sha(self) -> dict:
        return {e.sha: e for e in self.images}

    def save(self) -> Path:
        MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": self.version,
            "generated": self.generated,
            "sessions": dict(sorted(self.sessions.items())),
            # sortiert -> stabile git-Diffs, auch wenn der Build die
            # Reihenfolge der Quellen aendert
            "images": [asdict(e) for e in sorted(self.images, key=lambda e: e.sha)],
        }
        MANIFEST_PATH.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
        return MANIFEST_PATH

    @staticmethod
    def load() -> "Manifest":
        if not MANIFEST_PATH.exists():
            return Manifest()
        d = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        return Manifest(version=d.get("version", 1), generated=d.get("generated", ""),
                        sessions=d.get("sessions", {}),
                        images=[ImageEntry(**e) for e in d.get("images", [])])
