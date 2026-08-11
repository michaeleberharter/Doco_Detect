"""Admin-Passwort-Modul: Hash setzen/prüfen, Datei-Zustände.

Qt-frei; der Schutzzweck ist Fehlklick-Schutz, keine Sicherheitsgrenze
(Spec Abschnitt 3). Recovery = Datei löschen."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect import admin_auth  # noqa: E402


def test_unkonfiguriert_bis_passwort_gesetzt(tmp_path):
    f = tmp_path / "auth.json"
    assert not admin_auth.is_configured(f)
    admin_auth.set_password("geheim", f)
    assert admin_auth.is_configured(f)


def test_verify_richtig_und_falsch(tmp_path):
    f = tmp_path / "auth.json"
    admin_auth.set_password("geheim", f)
    assert admin_auth.verify_password("geheim", f) is True
    assert admin_auth.verify_password("falsch", f) is False


def test_verify_ohne_datei_ist_false(tmp_path):
    assert admin_auth.verify_password("egal", tmp_path / "fehlt.json") is False


def test_defekte_datei_verweigert_statt_crash(tmp_path):
    f = tmp_path / "auth.json"
    f.write_text("{kaputt", encoding="utf-8")
    assert admin_auth.is_configured(f)          # Datei da, aber unlesbar
    assert admin_auth.verify_password("egal", f) is False


def test_leeres_passwort_verboten(tmp_path):
    with pytest.raises(ValueError):
        admin_auth.set_password("", tmp_path / "auth.json")


def test_klartext_steht_nicht_in_der_datei(tmp_path):
    f = tmp_path / "auth.json"
    admin_auth.set_password("geheim", f)
    inhalt = f.read_text(encoding="utf-8")
    assert "geheim" not in inhalt
    d = json.loads(inhalt)
    assert d["algo"] == "pbkdf2-sha256"
    assert set(d) >= {"algo", "iterations", "salt", "hash"}
