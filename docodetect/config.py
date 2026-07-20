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

# Lokale, NICHT versionierte Überschreibungen neben der Haupt-Config
# (z.B. camera.index, der pro Rechner anders ist).
LOCAL_CONFIG_NAME = "config.local.yaml"

# NOTE: no "segmentation" section – the segmentation engine self-calibrates
# and deliberately has no config keys (see docodetect/segmentation.py).
_REQUIRED_SECTIONS = ("camera", "geometry", "calibration", "matching", "paths")


def _deep_merge(base: dict, override: dict) -> dict:
    """Rekursiv mischen: verschachtelte Sektionen werden zusammengeführt,
    skalare Werte und Listen vom Override ersetzt. `base` bleibt unberührt."""
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(path: str | Path | None = None) -> dict:
    """Load YAML config and run basic sanity checks.

    Liegt neben der Config eine `config.local.yaml`, wird sie per Deep-Merge
    darübergelegt (lokale Keys gewinnen). So bleibt „alles in YAML“ erhalten,
    aber rechnerabhängige Werte – vor allem `camera.index`, der am Mac auf die
    UGREEN und nicht auf die FaceTime-Kamera zeigen muss – landen nicht im
    Repository. Die Datei ist per .gitignore ausgeschlossen."""
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not cfg_path.exists():
        raise FileNotFoundError(f"Config not found: {cfg_path}")

    with open(cfg_path, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)

    local_path = cfg_path.with_name(LOCAL_CONFIG_NAME)
    if local_path.exists():
        with open(local_path, "r", encoding="utf-8") as fh:
            local = yaml.safe_load(fh) or {}
        if not isinstance(local, dict):
            raise ValueError(f"{local_path} muss ein YAML-Mapping enthalten.")
        cfg = _deep_merge(cfg, local)
        if local:
            print(f"[config] lokale Überschreibung aktiv ({local_path.name}): "
                  f"{', '.join(sorted(local))}")

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
