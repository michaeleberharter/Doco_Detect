"""Load and validate config/config.yaml.

Single source of truth for all tunable parameters. Access via:

    from docodetect.config import load_config
    cfg = load_config()
    cfg["camera"]["width"]
"""

from __future__ import annotations

import copy
import re
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


def local_override(path: str | Path | None = None) -> dict:
    """Die unversionierte `config.local.yaml` als dict; leer, wenn keine da ist.

    `load_config` legt sie per Deep-Merge über die Haupt-Config, danach ist
    dem Ergebnis nicht mehr anzusehen, welcher Wert von wo kam. Wer genau das
    wissen muss – der Korpus-Wächter in `corpus/runner.py` –, fragt hier."""
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    local_path = cfg_path.with_name(LOCAL_CONFIG_NAME)
    if not local_path.exists():
        return {}
    with open(local_path, "r", encoding="utf-8") as fh:
        local = yaml.safe_load(fh) or {}
    if not isinstance(local, dict):
        raise ValueError(f"{local_path} muss ein YAML-Mapping enthalten.")
    return local


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

    local = local_override(cfg_path)
    if local:
        cfg = _deep_merge(cfg, local)
        print(f"[config] lokale Überschreibung aktiv ({LOCAL_CONFIG_NAME}): "
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


# ---------------------------------------------------------------- Sandbox

SANDBOX_ROOT = "data/sandbox"

# Nur harmlose Namensbestandteile: kein Pfadseparator, kein Traversal, keine
# Leer- oder Sonderzeichen, die eine Shell oder ein Dateisystem anders liest.
_SANDBOX_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")

# Der Name ist PFLICHT und hat bewusst KEINEN Default. Ein Sammelordner lüde
# dazu ein, zwei Testläufe still in denselben Stand zu schreiben — und
# reference_stats kennt keinen Session-Begriff: zwei Einlern-Sessions
# desselben Artikels verschmelzen dort zu EINEM Mittelwert und EINEM sigma,
# der Basis für sigma_eff im Matcher (siehe
# docs/2026-07-31-reference-stats-keine-sessions.md).


def validate_sandbox_name(name: str) -> str:
    """Sandbox-Namen prüfen. Wirft ValueError mit handlungsleitender Meldung."""
    if not name or not _SANDBOX_NAME_RE.match(name):
        raise ValueError(
            f"Ungültiger Sandbox-Name {name!r}. Erlaubt sind nur "
            "Buchstaben, Ziffern, Punkt, Unterstrich und Bindestrich "
            "(kein Pfadseparator).")
    if set(name) <= {"."}:
        raise ValueError(
            f"Ungültiger Sandbox-Name {name!r}: '.' und '..' zeigen aus dem "
            "Sandbox-Verzeichnis heraus.")
    return name


def sandbox_cfg(cfg: dict, name: str, *, verbose: bool = True) -> dict:
    """Kopie der Config, deren SCHREIB-Pfade unter data/sandbox/<name>/ liegen.

    Umgelenkt werden genau die fünf Ziele, die ein Test-Enrollment samt
    Prüflauf berührt:

        paths.db_file        -> data/sandbox/<name>/doco_detect.sqlite3
        paths.reference_dir  -> data/sandbox/<name>/reference
        paths.captures_dir   -> data/sandbox/<name>/captures
        analysis.output_dir  -> data/sandbox/<name>/reports
        (data/sandbox/<name>/verworfen folgt automatisch: discard_enrollment
         leitet den Pfad aus reference_dir.parent ab)

    NICHT umgelenkt und damit bewusst GETEILT: calibration.file und
    calibration.background_file. Ein Test-Enrollment gegen eine andere Skala
    zu messen wäre wertlos. Weil beide damit produktiver Zustand bleiben,
    sind die Befehle, die sie schreiben (`calibrate`, `capture-background`,
    `make-smoke-testset`), unter --sandbox gesperrt — ebenso die
    entsprechenden Qt-Knöpfe.

    Ebenso unangetastet: matching, features, camera, geometry.
    Das übergebene `cfg` bleibt unverändert.
    """
    validate_sandbox_name(name)
    root = f"{SANDBOX_ROOT}/{name}"
    out = copy.deepcopy(cfg)
    out.setdefault("paths", {})
    out.setdefault("analysis", {})
    out["paths"]["db_file"] = f"{root}/doco_detect.sqlite3"
    out["paths"]["reference_dir"] = f"{root}/reference"
    out["paths"]["captures_dir"] = f"{root}/captures"
    out["analysis"]["output_dir"] = f"{root}/reports"
    # Marker für die Sperren in CLI und Qt-UI. Bewusst im cfg und nicht als
    # Extra-Parameter: die Qt-Dialoge bekommen ausschliesslich cfg gereicht.
    out["sandbox"] = name
    if verbose:
        print(sandbox_banner(out))
    return out


def sandbox_pfade(cfg: dict) -> dict:
    """Die fünf umgelenkten Ziele, aufgelöst – EINE Definition.

    Startmeldung und Verzeichnisanlage müssen zwingend dieselben fünf Ziele
    meinen. Getrennt gepflegt driften sie beim nächsten hinzugefügten Pfad
    auseinander, und zwar in der unauffälligen Richtung: die Meldung nennt
    ihn, angelegt wird er nicht."""
    ref = resolve(cfg["paths"]["reference_dir"])
    return {
        "db": resolve(cfg["paths"]["db_file"]),
        "referenzen": ref,
        "verworfen": ref.parent / "verworfen",
        "captures": resolve(cfg["paths"]["captures_dir"]),
        "berichte": resolve(cfg["analysis"]["output_dir"]),
    }


def sandbox_banner(cfg: dict) -> str:
    """Die fünf aufgelösten Sandbox-Pfade als Startmeldung.

    Beantwortet den einzigen ernsthaften Einwand gegen das Umlenken von
    analysis.output_dir („dann liegt das Diagnoseblatt nicht am gewohnten
    Ort"): es steht beim Start da, wo es liegt."""
    return ("[sandbox] '{name}' aktiv — db={db} · referenzen={referenzen} · "
            "verworfen={verworfen} · captures={captures} · "
            "berichte={berichte}").format(name=cfg.get("sandbox"),
                                          **sandbox_pfade(cfg))


def sandbox_verzeichnisse_anlegen(cfg: dict) -> list:
    """Die fünf umgelenkten Ziele anlegen. Gibt die NEU angelegten zurück.

    Ohne das scheitert der erste Befehl in einer frischen Sandbox an
    `sqlite3.OperationalError: unable to open database file`: sqlite legt die
    DATEI an, nicht ihren Ordner. Die übrigen vier Ziele legen ihre Schreiber
    zwar selbst an (`_save_capture_and_report`, `enroll`, `discard_enrollment`,
    `analyze`), aber erst im Moment des ersten Schreibens – die Startmeldung
    nennt dann fünf Pfade, von denen keiner existiert.

    Bewusst NICHT in `sandbox_cfg`: die bleibt eine reine Config-Umformung
    ohne Nebenwirkung. Sonst legte jeder Test, der nur die Pfadform prüft,
    Verzeichnisse im echten Projektbaum an. Die Aufrufer (CLI `main`, Qt
    `__main__`) rufen das hier ERST NACH ihrer Sperrprüfung – ein gesperrter
    Befehl darf keinen Ordner hinterlassen."""
    p = sandbox_pfade(cfg)
    ordner = [p["db"].parent,        # nur der Ordner; die Datei macht sqlite
              p["referenzen"], p["verworfen"], p["captures"], p["berichte"]]
    neu = [d for d in ordner if not d.exists()]
    for d in ordner:
        d.mkdir(parents=True, exist_ok=True)
    return neu
