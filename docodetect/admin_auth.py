"""Admin-Zugang: Passwort-Hash setzen und prüfen (Qt-frei).

Fehlklick-Schutz, KEINE Sicherheitsgrenze (Spec Abschnitt 3): DB, Config
und Captures liegen unverschlüsselt daneben. Gespeichert wird nur ein
PBKDF2-HMAC-SHA256-Hash mit Salt in einer gitignorten JSON-Datei.

Bewusst PBKDF2 statt scrypt (Befund 2026-08-10): `hashlib.scrypt` fehlt
bei LibreSSL-Builds (macOS-Systempython), `pbkdf2_hmac` ist auf allen
Builds garantiert — und die Auth-Datei muss auf Mac UND Windows-Box mit
demselben Verfahren prüfbar sein. Algo, Iterationen und Salt stehen mit
in der Datei, damit ein späterer Parameterwechsel Altdateien nicht
unlesbar macht. Recovery bei vergessenem Passwort: Datei löschen — beim
nächsten Öffnen wird neu vergeben (README, Abschnitt Qt-UI)."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path

from .config import resolve

AUTH_FILE = "config/admin_auth.local.json"
_ALGO = "pbkdf2-sha256"
_ITERATIONS = 200_000
_DKLEN = 32


def _pfad(auth_file: str | Path | None) -> Path:
    return resolve(AUTH_FILE if auth_file is None else auth_file)


def is_configured(auth_file: str | Path | None = None) -> bool:
    return _pfad(auth_file).exists()


def set_password(password: str,
                 auth_file: str | Path | None = None) -> Path:
    """Hash+Salt schreiben (atomar: tmp + os.replace). Leeres Passwort ist
    ungültig — der Dialog verhindert das zusätzlich."""
    if not password:
        raise ValueError("Leeres Admin-Passwort ist nicht erlaubt.")
    salt = os.urandom(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt,
                            _ITERATIONS, dklen=_DKLEN)
    p = _pfad(auth_file)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"algo": _ALGO, "iterations": _ITERATIONS,
                               "salt": salt.hex(), "hash": h.hex()}),
                   encoding="utf-8")
    os.replace(tmp, p)
    return p


def verify_password(password: str,
                    auth_file: str | Path | None = None) -> bool:
    """False bei falschem Passwort UND bei fehlender/defekter Datei — eine
    defekte Datei crasht nie und sperrt nie aus (Recovery: löschen).
    Iterationen kommen aus der Datei, nicht aus der Konstante: so bleibt
    eine mit anderen Parametern geschriebene Datei prüfbar."""
    try:
        d = json.loads(_pfad(auth_file).read_text(encoding="utf-8"))
        if d.get("algo") != _ALGO:
            return False
        salt = bytes.fromhex(d["salt"])
        soll = bytes.fromhex(d["hash"])
        ist = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt,
                                  int(d["iterations"]), dklen=len(soll))
    except (OSError, ValueError, KeyError, TypeError,
            json.JSONDecodeError):
        return False
    return hmac.compare_digest(ist, soll)
