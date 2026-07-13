"""Load and validate config/config.yaml.

Single source of truth for all tunable parameters. Access via:

    from docodetect.config import load_config
    cfg = load_config()
    cfg["camera"]["width"]
"""

from __future__ import annotations

import copy
from pathlib import Path

import yaml

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "config.yaml"

_REQUIRED_SECTIONS = ("camera", "geometry", "calibration", "segmentation", "matching", "paths")


def load_config(path: str | Path | None = None) -> dict:
    """Load YAML config and run basic sanity checks."""
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not cfg_path.exists():
        raise FileNotFoundError(f"Config not found: {cfg_path}")

    with open(cfg_path, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)

    for section in _REQUIRED_SECTIONS:
        if section not in cfg:
            raise KeyError(f"Missing config section: '{section}' in {cfg_path}")

    if cfg["camera"].get("autofocus", True):
        # Measurements are only reproducible with a fixed focus.
        print("[config] WARNING: camera.autofocus is true – set it to false "
              "for reproducible measurements.")

    if cfg["geometry"]["camera_height_mm"] <= 0:
        raise ValueError("geometry.camera_height_mm must be > 0")

    return copy.deepcopy(cfg)


def project_root() -> Path:
    return DEFAULT_CONFIG_PATH.parent.parent


def resolve(cfg_relative_path: str | Path) -> Path:
    """Resolve a path from the config relative to the project root."""
    p = Path(cfg_relative_path)
    return p if p.is_absolute() else project_root() / p
