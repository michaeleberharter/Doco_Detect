"""Tests für den rechnerlokalen Config-Override (config/config.local.yaml).

Motivation: camera.index unterscheidet sich pro Rechner (Mac: UGREEN auf 1,
FaceTime auf 0; Windows-Box: 0). Der Wert darf die geteilte config.yaml nicht
verändern. Deep-Merge heißt: nur die genannten Keys gewinnen, alles andere
bleibt exakt wie in der Haupt-Config.
"""

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.config import LOCAL_CONFIG_NAME, load_config  # noqa: E402


def _write_main(tmp_path, extra=None):
    """Vollständige Minimal-Config (alle Pflichtsektionen) nach tmp_path."""
    cfg = {
        "camera": {"index": 0, "width": 3840, "height": 2160, "fourcc": "MJPG",
                   "autofocus": False, "focus_value": 30},
        "geometry": {"camera_height_mm": 300.0},
        "calibration": {"file": "calibration/calibration.json",
                        "background_file": "calibration/background.png",
                        "marker_size_mm": 136.0},
        "matching": {"diameter_tolerance_mm": 6.0, "max_z_accept": 3.5},
        "paths": {"db_file": "doco_detect.sqlite3"},
    }
    if extra:
        cfg.update(extra)
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return p


def _write_local(tmp_path, data):
    p = tmp_path / LOCAL_CONFIG_NAME
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return p


def test_without_local_file_config_is_unchanged(tmp_path):
    cfg = load_config(_write_main(tmp_path))
    assert cfg["camera"]["index"] == 0
    assert cfg["camera"]["width"] == 3840


def test_local_override_wins_for_named_key_only(tmp_path):
    """Der Kernfall: camera.index lokal auf 1, alle anderen camera-Keys
    (und alle anderen Sektionen) bleiben unverändert."""
    main = _write_main(tmp_path)
    _write_local(tmp_path, {"camera": {"index": 1}})
    cfg = load_config(main)
    assert cfg["camera"]["index"] == 1
    assert cfg["camera"]["width"] == 3840       # nicht angefasst
    assert cfg["camera"]["fourcc"] == "MJPG"
    assert cfg["matching"]["max_z_accept"] == 3.5
    assert cfg["geometry"]["camera_height_mm"] == 300.0


def test_local_override_is_deep_not_replacing_sections(tmp_path):
    """Eine Sektion im Override darf die Sektion der Haupt-Config nicht
    ersetzen – sonst würden fehlende Keys still verschwinden."""
    main = _write_main(tmp_path)
    _write_local(tmp_path, {"matching": {"max_z_accept": 4.0}})
    cfg = load_config(main)
    assert cfg["matching"]["max_z_accept"] == 4.0
    assert cfg["matching"]["diameter_tolerance_mm"] == 6.0   # überlebt


def test_local_override_can_add_new_keys(tmp_path):
    main = _write_main(tmp_path)
    _write_local(tmp_path, {"camera": {"backend": "CAP_AVFOUNDATION"}})
    cfg = load_config(main)
    assert cfg["camera"]["backend"] == "CAP_AVFOUNDATION"
    assert cfg["camera"]["index"] == 0


def test_empty_local_file_is_harmless(tmp_path):
    main = _write_main(tmp_path)
    (tmp_path / LOCAL_CONFIG_NAME).write_text("", encoding="utf-8")
    assert load_config(main)["camera"]["index"] == 0


def test_non_mapping_local_file_raises_clear_error(tmp_path):
    main = _write_main(tmp_path)
    (tmp_path / LOCAL_CONFIG_NAME).write_text("- 1\n- 2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Mapping"):
        load_config(main)


def test_local_override_does_not_touch_the_main_file(tmp_path):
    """Die geteilte config.yaml darf durch den Override nie verändert werden."""
    main = _write_main(tmp_path)
    before = main.read_text(encoding="utf-8")
    _write_local(tmp_path, {"camera": {"index": 1}})
    load_config(main)
    assert main.read_text(encoding="utf-8") == before
