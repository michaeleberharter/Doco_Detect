# Admin-Panel Melde-Punkt 1a — Implementierungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Melde-Punkt 1a des Admin-Panels: drei Lese-Fassaden in
`pipeline.py`, Passwort-Zugang (`admin_auth` + Dialog), Admin-Fenster-Gerüst
mit Sidebar, System-Status-Seite — gemäß Spec
[2026-08-08-admin-panel-design.md](../specs/2026-08-08-admin-panel-design.md)
(Commit `c4a8b00`).

**Architecture:** Das Panel ist reine Konsumentenschicht und importiert nur
`pipeline.py`/`config.resolve` plus das neue Qt-freie `admin_auth.py` — nie
`reporting.py`/`analysis.py`/`cli.py`. Pfade löst ausschließlich
`pipeline.py` bzw. `admin_auth.py` (eigene Auth-Datei) auf. Kein neuer
QThread-Pfad: 1a braucht keinen Worker, alle Zugriffe sind schnelle
Lesezugriffe.

**Tech Stack:** Python 3.9+, PySide6 (Muster der bestehenden ui_qt-Suite),
`hashlib.scrypt` (stdlib), pytest offscreen.

## Global Constraints

- **Nur Melde-Punkt 1a.** Report-Browser, Einzelreport, Prefilter-Seite (1b)
  werden NICHT angelegt — die Sidebar zeigt für sie Platzhalter.
- **Branch `feature/admin-panel-stufe1`.** Ausführung in zwei Blöcken mit
  zwei blockierenden Checkpoints (Festlegung 2026-08-10): Block 1 = Task 1
  (einziger Eingriff in Bestandscode), Block 2 = Tasks 2–7. **Commits erst
  nach Checkpoint-Freigabe** — die Commit-Steps der Tasks nennen Message
  und Dateien, ausgeführt werden sie erst nach Freigabe. Kein Push, kein
  Merge: volle Suite + beide Korpus-Stufen kommen erst zum Merge nach 1b.
- **Importregel (Spec Abschnitt 4):** neue UI-Module importieren nur
  `docodetect.pipeline`, `docodetect.config` (resolve), `docodetect.admin_auth`
  und ui_qt-interne Module. NIE `reporting`, `analysis`, `cli`.
- **Tests nur gegen `tmp_path`** — echte `doco_detect.sqlite3`, `data/`,
  `calibration/` werden nie berührt (CLAUDE.md). Kein Test öffnet eine
  Kamera (conftest-Autouse bleibt maßgeblich).
- **Kein neuer QThread-Pfad** — der QThread-Komplex ist Timo-eigen (Spec
  Abschnitt 4).
- **Sprache/Stil:** deutsche Docstrings/UI-Texte, Dezimalkomma in Anzeigen,
  ~79 Zeichen Zeilenlänge — wie der Bestand.
- **`config/admin_auth.local.json` ist gitignored** (Task 2) und wird nie
  committet.
- Testaufrufe seriell, UI-Module einzeln (Spec Abschnitt 10; Vollausgaben
  von Melde-Punkt-Läufen nach `~/Documents/tmp/`, nie `/tmp`).
- **Python-Floor 3.9** (`pyproject.toml:8: requires-python = ">=3.9"`;
  venv: 3.9.6): PEP-604-Annotationen (`X | Y`) nur in Dateien mit
  `from __future__ import annotations` — alle fünf neuen Module dieses
  Plans haben den Import; in Dateien ohne ihn (z. B. bestehende
  Testmodule) keine solchen Annotationen schreiben (Befund Block 1).

---

### Task 1: Drei Lese-Fassaden in pipeline.py

**Files:**
- Modify: `docodetect/pipeline.py` (direkt nach `render_report_overlay`,
  vor `list_articles`, ~Zeile 1129)
- Modify: `docodetect/reporting.py` (`load_reports` bekommt einen
  ADDITIVEN `sort_by`-Parameter, Default `"mtime"` = bisheriges
  Verhalten — Entscheidung 2026-08-10 nach dem mtime-Befund; kein
  bestehender Aufrufer ändert sich)
- Test: `tests/test_ui_facade.py` (bestehendes Zuhause der
  pipeline-Fassaden-Tests, ans Dateiende)

**Interfaces:**
- Consumes: `reporting.load_reports(folder, limit)` →
  `list[tuple[Path, MatchReport]]` (neueste zuerst, defekte JSONs
  übersprungen, setzt `report_path`); `reporting.judgement(report)`;
  `reporting.predicted_article(report)`; `pipeline._fingerabdruck(cfg)`
  (Zeile 368–394); `config.resolve`.
- Produces (Fassaden-Signaturen — Pfadauflösung IMMER hier, nie beim
  Aufrufer):
  - `load_saved_reports(cfg: dict, limit: int | None = None) -> list[tuple[Path, MatchReport]]` — löst `paths.captures_dir` auf und wählt
    ausdrücklich `sort_by="name"` (Dateiname = ms-Zeitstempel; stabil
    gegen `save_verdict`-Neuschreiben, Befund 2026-08-10)
  - `report_judgement(report: MatchReport) -> bool | None`
  - `report_predicted_article(report: MatchReport) -> str`
  - `optics_fingerprint(cfg: dict) -> dict | None` — löst
    `calibration.file` + `calibration.background_file` auf; `None` =
    Leerzustand „nicht kalibriert"

- [ ] **Step 1: Fehlschlagende Tests schreiben** — ans Ende von
  `tests/test_ui_facade.py`:

```python
# ---------- Lese-Fassaden (Admin-Panel 1a) ----------

from docodetect.matcher import MatchReport  # noqa: E402
from docodetect.pipeline import (load_saved_reports,  # noqa: E402
                                 optics_fingerprint, report_judgement,
                                 report_predicted_article)


def _schreibe_report(pfad, decision, verdict=None):
    # Ohne Typ-Annotationen: die Datei hat kein `from __future__ import
    # annotations`, und unter Python 3.9 wäre `str | None` ein TypeError.
    rep = MatchReport(decision=decision, message="Test", verdict=verdict)
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(rep.to_json(), encoding="utf-8")


def test_load_saved_reports_neueste_zuerst_limit_und_defekte(tmp_path):
    cfg = make_cfg(tmp_path)
    caps = tmp_path / "captures"
    cfg["paths"]["captures_dir"] = str(caps)
    # Die Fassade sortiert nach DATEINAME (absteigend) — Capture-Namen
    # sind ms-Zeitstempel. Kein sleep nötig, mtime ist egal.
    _schreibe_report(caps / "a.json", "reject")
    _schreibe_report(caps / "b.json", "accept")
    (caps / "kaputt.json").write_text("{nix", encoding="utf-8")
    alle = load_saved_reports(cfg)
    assert [p.name for p, _ in alle] == ["b.json", "a.json"]
    assert alle[0][1].report_path == str(caps / "b.json")
    nur_eins = load_saved_reports(cfg, limit=1)
    assert [p.name for p, _ in nur_eins] == ["b.json"]


def test_load_saved_reports_ohne_ordner_ist_leer(tmp_path):
    cfg = make_cfg(tmp_path)
    cfg["paths"]["captures_dir"] = str(tmp_path / "gibtsnicht")
    assert load_saved_reports(cfg) == []


def test_load_saved_reports_bewertung_aendert_reihenfolge_nicht(tmp_path):
    """Befund 2026-08-10: save_verdict schreibt das Report-JSON neu. Mit
    mtime-Sortierung springt ein nachträglich bewerteter alter Report in
    „neueste zuerst" nach vorn — genau die bewerteten Reports sind aber
    die, die man im Browser sucht. Maßgeblich ist der Dateiname
    (ms-Zeitstempel), nicht der Schreibzeitpunkt."""
    cfg = make_cfg(tmp_path)
    caps = tmp_path / "captures"
    cfg["paths"]["captures_dir"] = str(caps)
    _schreibe_report(caps / "20260810-100000-000.json", "reject")
    _schreibe_report(caps / "20260810-110000-000.json", "accept")
    # Nachträgliche Bewertung: die ÄLTERE Datei wird neu geschrieben,
    # ihr mtime ist jetzt der jüngste im Ordner.
    _schreibe_report(caps / "20260810-100000-000.json", "reject",
                     verdict="wrong")
    alle = load_saved_reports(cfg)
    assert [p.name for p, _ in alle] == ["20260810-110000-000.json",
                                         "20260810-100000-000.json"]


def test_load_saved_reports_fremddateien_crashen_nicht(tmp_path):
    """Dateien ohne Zeitstempel-Muster im Namen: kein Crash, deterministische
    Einsortierung (lexikografisch — 'z…' steht absteigend vor den
    Ziffern-Zeitstempeln, unabhängig vom Schreibzeitpunkt)."""
    cfg = make_cfg(tmp_path)
    caps = tmp_path / "captures"
    cfg["paths"]["captures_dir"] = str(caps)
    _schreibe_report(caps / "zzz-fremd.json", "reject")   # zuerst geschrieben
    _schreibe_report(caps / "20260810-120000-000.json", "accept")
    alle = load_saved_reports(cfg)
    assert [p.name for p, _ in alle] == ["zzz-fremd.json",
                                         "20260810-120000-000.json"]


def test_load_reports_unbekannter_sortierschluessel(tmp_path):
    """Der additive sort_by-Parameter kennt genau 'mtime' und 'name' —
    alles andere ist ein klarer Fehler, kein stilles Fallback."""
    from docodetect.reporting import load_reports
    with pytest.raises(ValueError):
        load_reports(tmp_path, sort_by="quatsch")


def test_report_judgement_und_prediction_delegieren():
    rep = MatchReport(decision="accept", message="", verdict="correct")
    assert report_judgement(rep) is True
    assert report_predicted_article(rep) == "NO_MATCH"  # keine Kandidaten
    assert report_judgement(MatchReport(decision="reject", message="")) is None


def test_optics_fingerprint_none_ohne_einrichtung(tmp_path):
    assert optics_fingerprint(make_cfg(tmp_path)) is None


def test_optics_fingerprint_liefert_hashes(tmp_path):
    import hashlib

    cfg = make_cfg(tmp_path)
    cfg["features"] = {"ring_zones": 3, "hs_hist_bins": [8, 8]}
    Calibration(mm_per_px=0.5, camera_height_mm=300.0, image_width=1920,
                image_height=1080, marker_size_mm=72.5,
                created_unix=time.time()).save(cfg["calibration"]["file"])
    cv2.imwrite(cfg["calibration"]["background_file"],
                np.zeros((8, 8, 3), dtype=np.uint8))
    fp = optics_fingerprint(cfg)
    assert fp is not None
    assert fp["mm_per_px"] == 0.5
    erwartet = hashlib.sha256(
        Path(cfg["calibration"]["background_file"]).read_bytes()).hexdigest()
    assert fp["background_sha256"] == erwartet
    assert set(fp) == {"calibration_sha256", "background_sha256",
                       "features_cfg_sha256", "mm_per_px",
                       "camera_height_mm"}
```

  (`make_cfg`, `Calibration`, `cv2`, `np`, `time`, `Path` sind in
  `test_ui_facade.py` bereits importiert bzw. definiert.)

- [ ] **Step 2: Fehlschlag verifizieren**

Run: `.venv/bin/pytest tests/test_ui_facade.py -v`
Expected: FAIL/ERROR mit `ImportError: cannot import name 'load_saved_reports'`

- [ ] **Step 3a: Additiver `sort_by`-Parameter in `reporting.load_reports`**
  (Default `"mtime"` = bisheriges Verhalten; `limit` greift dort NACH dem
  Sortieren — `sorted()` läuft über alle Dateien, der `break` kappt erst
  beim Einsammeln):

```python
def load_reports(folder: str | Path,
                 limit: int | None = None,
                 sort_by: str = "mtime") -> list[tuple[Path, MatchReport]]:
    """Alle Report-JSONs eines Ordners, absteigend sortiert (neueste zuerst).
    Defekte/fremde JSONs werden übersprungen statt die Ansicht zu killen.

    `sort_by` wählt den Schlüssel — additiv eingeführt (2026-08-10,
    Admin-Panel 1a), der Default bleibt das bisherige Verhalten:
    - "mtime": Schreibzeitpunkt der Datei. Achtung: save_verdict schreibt
      Report-JSONs neu — ein nachträglich bewerteter alter Report rückt
      damit nach vorn.
    - "name": Dateiname, lexikografisch. Capture-Namen sind ms-Zeitstempel
      (pipeline._save_capture_and_report), die Ordnung bleibt damit auch
      nach save_verdict stabil.
    `limit` greift NACH dem Sortieren (behält die ersten n der Ordnung)."""
    schluessel = {"mtime": (lambda p: p.stat().st_mtime),
                  "name": (lambda p: p.name)}
    if sort_by not in schluessel:
        raise ValueError("sort_by muss 'mtime' oder 'name' sein, "
                         f"nicht {sort_by!r}.")
    folder = Path(folder)
    if not folder.is_dir():
        return []
    out: list[tuple[Path, MatchReport]] = []
    for p in sorted(folder.glob("*.json"), key=schluessel[sort_by],
                    reverse=True):
        # … Schleifenkörper unverändert (parse, skip, report_path, limit) …
```

- [ ] **Step 3b: Fassaden implementieren** — in `docodetect/pipeline.py`
  nach `render_report_overlay` einfügen:

```python
# ---------- Lese-Fassaden für UIs (Admin-Panel, Spec Abschnitt 4) ----------
# Gegenstück zu confirm_result & Co.: UIs importieren reporting.py auch zum
# LESEN nie direkt, und Pfade löst ausschliesslich diese Schicht auf.

def load_saved_reports(cfg: dict,
                       limit: int | None = None
                       ) -> list[tuple[Path, MatchReport]]:
    """Gespeicherte Identifikations-Reports aus paths.captures_dir,
    neueste zuerst nach DATEINAME (ms-Zeitstempel) — bewusst nicht mtime:
    save_verdict schreibt Report-JSONs neu, ein bewerteter alter Report
    stünde sonst fälschlich vorn (Befund 2026-08-10). Defekte JSONs werden
    übersprungen; `limit` begrenzt auf die neuesten n."""
    from .reporting import load_reports
    return load_reports(resolve(cfg["paths"]["captures_dir"]), limit=limit,
                        sort_by="name")


def report_judgement(report: MatchReport) -> bool | None:
    """War die Top-1-Vorhersage richtig? True/False, None = unbewertet."""
    from .reporting import judgement
    return judgement(report)


def report_predicted_article(report: MatchReport) -> str:
    """Top-1-Artikelnummer des Reports; NO_MATCH ohne Kandidaten."""
    from .reporting import predicted_article
    return predicted_article(report)


def optics_fingerprint(cfg: dict) -> dict | None:
    """Optik-Fingerprint der aktuellen Konfiguration (Status-Seite).

    None, wenn Kalibrierung oder Hintergrund fehlen — das ist der
    Leerzustand „nicht kalibriert", kein Fehler (Spec Abschnitt 6)."""
    if not (resolve(cfg["calibration"]["file"]).exists()
            and resolve(cfg["calibration"]["background_file"]).exists()):
        return None
    return _fingerabdruck(cfg)
```

- [ ] **Step 4: Tests grün verifizieren**

Run: `.venv/bin/pytest tests/test_ui_facade.py -v`
Expected: PASS (alle, inkl. der bestehenden get_status/list_articles-Tests)

- [ ] **Step 5: Blockierender Checkpoint 1 — KEIN Commit.** Melden:
  implementierte Signaturen, rohes Testergebnis (unparaphrasiert),
  Befund zur mtime-Sortierung (siehe „Notizen für 1b"), Abweichungen vom
  Plan-Code. Auf Freigabe warten; erst danach Commit mit:

```bash
git add docodetect/pipeline.py tests/test_ui_facade.py
git commit -m "feat(pipeline): drei Lese-Fassaden fuer das Admin-Panel (1a)"
```

---

### Task 2: admin_auth.py (Qt-frei) + .gitignore + README

**Files:**
- Create: `docodetect/admin_auth.py`
- Create: `tests/test_admin_auth.py`
- Modify: `.gitignore` (eine Zeile)
- Modify: `README.md` (Recovery-Absatz, siehe Step 5)

**Interfaces:**
- Produces:
  - `AUTH_FILE = "config/admin_auth.local.json"` (Modul-Konstante)
  - `is_configured(auth_file: str | Path | None = None) -> bool`
  - `set_password(password: str, auth_file: str | Path | None = None) -> Path`
  - `verify_password(password: str, auth_file: str | Path | None = None) -> bool`
  - `auth_file=None` heißt: `config.resolve(AUTH_FILE)`. Tests übergeben
    einen tmp_path-Pfad (resolve lässt absolute Pfade unverändert).

- [ ] **Step 1: Fehlschlagende Tests schreiben** — `tests/test_admin_auth.py`:

```python
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
    assert d["algo"] == "scrypt"
    assert set(d) >= {"salt", "hash", "n", "r", "p"}
```

- [ ] **Step 2: Fehlschlag verifizieren**

Run: `.venv/bin/pytest tests/test_admin_auth.py -v`
Expected: ERROR `ModuleNotFoundError: No module named 'docodetect.admin_auth'`

- [ ] **Step 3: Modul implementieren** — `docodetect/admin_auth.py`:

```python
"""Admin-Zugang: Passwort-Hash setzen und prüfen (Qt-frei).

Fehlklick-Schutz, KEINE Sicherheitsgrenze (Spec Abschnitt 3): DB, Config
und Captures liegen unverschlüsselt daneben. Gespeichert wird nur ein
scrypt-Hash mit Salt in einer gitignorten JSON-Datei. Recovery bei
vergessenem Passwort: Datei löschen — beim nächsten Öffnen wird neu
vergeben (README, Abschnitt Qt-UI)."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path

from .config import resolve

AUTH_FILE = "config/admin_auth.local.json"
_SCRYPT = {"n": 16384, "r": 8, "p": 1}
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
    h = hashlib.scrypt(password.encode("utf-8"), salt=salt,
                       dklen=_DKLEN, **_SCRYPT)
    p = _pfad(auth_file)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"algo": "scrypt", **_SCRYPT,
                               "salt": salt.hex(), "hash": h.hex()}),
                   encoding="utf-8")
    os.replace(tmp, p)
    return p


def verify_password(password: str,
                    auth_file: str | Path | None = None) -> bool:
    """False bei falschem Passwort UND bei fehlender/defekter Datei — eine
    defekte Datei crasht nie und sperrt nie aus (Recovery: löschen)."""
    try:
        d = json.loads(_pfad(auth_file).read_text(encoding="utf-8"))
        salt = bytes.fromhex(d["salt"])
        soll = bytes.fromhex(d["hash"])
        params = {k: int(d[k]) for k in ("n", "r", "p")}
        ist = hashlib.scrypt(password.encode("utf-8"), salt=salt,
                             dklen=len(soll), **params)
    except (OSError, ValueError, KeyError, TypeError,
            json.JSONDecodeError):
        return False
    return hmac.compare_digest(ist, soll)
```

- [ ] **Step 4: Tests grün verifizieren**

Run: `.venv/bin/pytest tests/test_admin_auth.py -v`
Expected: PASS (6 Tests)

- [ ] **Step 5: .gitignore + README** — in `.gitignore` unter der
  bestehenden Zeile `config/config.local.yaml` ergänzen:

```
config/admin_auth.local.json
```

  In `README.md`, am Ende des Qt-UI-Abschnitts (der Abschnitt, in dem
  `pip install -r requirements-ui-qt.txt` und `python -m docodetect.ui_qt`
  beschrieben sind, vor der nächsten `##`-Überschrift) diesen Absatz
  einfügen:

```markdown
### Admin-Bereich (Schloss-Symbol in der Icon-Schiene)

Der Wartungsbereich ist passwortgeschützt. Beim ersten Öffnen wird das
Passwort festgelegt; gespeichert wird nur ein Hash in der gitignorten
Datei `config/admin_auth.local.json`. **Passwort vergessen:** diese Datei
löschen — beim nächsten Öffnen wird neu vergeben. Der Schutz ist ein
Fehlklick-Schutz für die Fotobox, keine Sicherheitsgrenze, und sperrt
nichts, was während einer Box-Session gebraucht wird.
```

- [ ] **Step 6: Commit**

```bash
git add docodetect/admin_auth.py tests/test_admin_auth.py .gitignore README.md
git commit -m "feat(admin): Passwort-Hash-Modul admin_auth + Doku (1a)"
```

---

### Task 3: Schloss-Icon + ToolRail-Knopf

**Files:**
- Modify: `docodetect/ui_qt/icons.py` (neuer Builder + `_BUILDERS`-Eintrag)
- Modify: `docodetect/ui_qt/widgets/tool_rail.py`
- Test: Create `tests/test_admin_ui.py` (neue Datei; läuft in der
  Einzelaufruf-Schleife des Test-Regimes)

**Interfaces:**
- Produces: `ToolRail.admin_requested: Signal()` (parameterlos);
  `ToolRail._admin: QToolButton`; Icon-Name `"lock"`.

- [ ] **Step 1: Fehlschlagende Tests schreiben** — `tests/test_admin_ui.py`:

```python
"""Admin-Panel 1a: Schloss-Knopf, Passwort-Gate, Fenster, Status-Seite.

Qt-Tests offscreen; Muster wie test_ui_state.py. Läuft im Test-Regime der
Spec (Abschnitt 10) als EIGENER pytest-Aufruf in der UI-Schleife."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(scope="module")
def qapp():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from docodetect.ui_qt.app import make_app
    return make_app()


def test_lock_icon_registriert(qapp):
    from docodetect.ui_qt import icons
    assert "lock" in icons._BUILDERS


def test_tool_rail_hat_admin_knopf_mit_signal(qapp):
    from docodetect.ui_qt.widgets.tool_rail import ToolRail
    rail = ToolRail()
    empfangen = []
    rail.admin_requested.connect(lambda: empfangen.append(True))
    rail._admin.click()
    assert empfangen == [True]
    assert rail._admin.isEnabled()        # immer aktiv (Spec Abschnitt 3)
```

- [ ] **Step 2: Fehlschlag verifizieren**

Run: `.venv/bin/pytest tests/test_admin_ui.py -v`
Expected: FAIL (`'lock' in _BUILDERS` bzw. `AttributeError: admin_requested`)

- [ ] **Step 3: Icon implementieren** — in `docodetect/ui_qt/icons.py` vor
  `_BUILDERS` einfügen und den Dict-Eintrag ergänzen:

```python
def _lock(path: QPainterPath) -> None:
    """Schloss – Admin-Bereich (ToolRail, Spec Abschnitt 3)."""
    path.addRoundedRect(6.0, 11.0, 12.0, 8.0, 2.0, 2.0)
    path.moveTo(8.5, 11.0)
    path.lineTo(8.5, 8.0)
    path.arcTo(8.5, 4.5, 7.0, 7.0, 180.0, -180.0)
    path.lineTo(15.5, 11.0)
```

```python
_BUILDERS = {"scan": _scan, "camera": _camera, "target": _target,
             "plus": _plus, "gear": _gear, "check": _check, "alert": _alert,
             "lock": _lock}
```

- [ ] **Step 4: ToolRail erweitern** — `tool_rail.py`: Signal ergänzen

```python
class ToolRail(QWidget):
    triggered = Signal(str)          # "identify" | "background" | ...
    theme_toggle = Signal()
    admin_requested = Signal()       # Schloss: Admin-Bereich (Spec §3)
```

  und in `__init__` zwischen `lay.addStretch(1)` und dem Zahnrad-Block:

```python
        # Schloss unterhalb der Arbeitsschritte, oberhalb des Zahnrads
        # (Spec Abschnitt 3). Immer aktiv – Admin muss auch ohne Kamera
        # erreichbar sein (Diagnose).
        self._admin = self._make_button("lock", "Admin")
        self._admin.setToolTip("Admin-Bereich öffnen (passwortgeschützt)")
        self._admin.clicked.connect(self.admin_requested.emit)
        lay.addWidget(self._admin, alignment=Qt.AlignHCenter)
```

  In `retheme()` die Icon-Schleife erweitern:

```python
        for b in list(self._buttons.values()) + [self._gear, self._admin]:
```

- [ ] **Step 5: Tests grün + Nachbarschaft prüfen**

Run: `.venv/bin/pytest tests/test_admin_ui.py -v && .venv/bin/pytest tests/test_ui_layout.py -v`
Expected: beide PASS (Layout-Tests decken die Schiene mit ab)

- [ ] **Step 6: Commit**

```bash
git add docodetect/ui_qt/icons.py docodetect/ui_qt/widgets/tool_rail.py tests/test_admin_ui.py
git commit -m "feat(ui): Schloss-Knopf in der Icon-Schiene (Admin-Zugang, 1a)"
```

---

### Task 4: Passwort-Gate-Dialog

**Files:**
- Create: `docodetect/ui_qt/admin/__init__.py` (leer)
- Create: `docodetect/ui_qt/admin/auth_dialog.py`
- Modify: `tests/test_admin_ui.py`

**Interfaces:**
- Consumes: `admin_auth.is_configured/set_password/verify_password`
  (Task 2, jeweils mit `auth_file`-Parameter).
- Produces:
  - `AdminAuthDialog(festlegen: bool, parent=None, auth_file: str | Path | None = None)`
    mit Widgets `eingabe`, `wiederholung`, `fehler` und Methode `_ok()`
  - `ensure_admin_access(parent=None, auth_file: str | Path | None = None) -> bool`

- [ ] **Step 1: Fehlschlagende Tests schreiben** — an `tests/test_admin_ui.py`
  anhängen:

```python
def test_auth_dialog_festlegen_schreibt_datei(qapp, tmp_path):
    from docodetect.ui_qt.admin.auth_dialog import AdminAuthDialog
    f = tmp_path / "auth.json"
    dlg = AdminAuthDialog(festlegen=True, auth_file=f)
    dlg.eingabe.setText("geheim")
    dlg.wiederholung.setText("geheim")
    dlg._ok()
    assert dlg.result() == 1
    assert f.exists()


def test_auth_dialog_ungleiche_wiederholung_bleibt_offen(qapp, tmp_path):
    from docodetect.ui_qt.admin.auth_dialog import AdminAuthDialog
    f = tmp_path / "auth.json"
    dlg = AdminAuthDialog(festlegen=True, auth_file=f)
    dlg.eingabe.setText("geheim")
    dlg.wiederholung.setText("anders")
    dlg._ok()
    assert dlg.result() == 0
    assert not f.exists()
    assert "stimmen nicht überein" in dlg.fehler.text()


def test_auth_dialog_pruefen_falsch_dann_richtig(qapp, tmp_path):
    from docodetect import admin_auth
    from docodetect.ui_qt.admin.auth_dialog import AdminAuthDialog
    f = tmp_path / "auth.json"
    admin_auth.set_password("geheim", f)
    dlg = AdminAuthDialog(festlegen=False, auth_file=f)
    dlg.eingabe.setText("falsch")
    dlg._ok()
    assert dlg.result() == 0                      # offen, kein Lockout
    assert dlg.fehler.text() == "Falsches Passwort."
    dlg.eingabe.setText("geheim")
    dlg._ok()
    assert dlg.result() == 1
```

- [ ] **Step 2: Fehlschlag verifizieren**

Run: `.venv/bin/pytest tests/test_admin_ui.py -v`
Expected: neue Tests ERROR (`ModuleNotFoundError: docodetect.ui_qt.admin`)

- [ ] **Step 3: Dialog implementieren** — leeres
  `docodetect/ui_qt/admin/__init__.py` anlegen, dann
  `docodetect/ui_qt/admin/auth_dialog.py`:

```python
"""Passwort-Gate des Admin-Bereichs (Spec Abschnitt 3).

Eine Dialogklasse, zwei Modi: Festlegen (Auth-Datei fehlt — zweimal
eingeben) und Prüfen. Kein Lockout: Fehlertext, Feld markiert, fertig.
Die Hash-Logik liegt Qt-frei in docodetect/admin_auth.py."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QLineEdit,
                               QVBoxLayout)

from docodetect import admin_auth


class AdminAuthDialog(QDialog):
    def __init__(self, festlegen: bool, parent=None,
                 auth_file: str | Path | None = None):
        super().__init__(parent)
        self._festlegen = festlegen
        self._auth_file = auth_file
        self.setWindowTitle("Admin-Passwort festlegen" if festlegen
                            else "Admin-Bereich")
        self.setMinimumWidth(360)
        lay = QVBoxLayout(self)
        hinweis = QLabel(
            "Erstes Öffnen: Admin-Passwort festlegen. Vergessen? Datei "
            f"{admin_auth.AUTH_FILE} löschen, dann neu vergeben."
            if festlegen else "Admin-Passwort eingeben.")
        hinweis.setWordWrap(True)
        lay.addWidget(hinweis)
        self.eingabe = QLineEdit()
        self.eingabe.setEchoMode(QLineEdit.Password)
        self.eingabe.setPlaceholderText("Passwort")
        lay.addWidget(self.eingabe)
        self.wiederholung = QLineEdit()
        self.wiederholung.setEchoMode(QLineEdit.Password)
        self.wiederholung.setPlaceholderText("Wiederholen")
        self.wiederholung.setVisible(festlegen)
        lay.addWidget(self.wiederholung)
        self.fehler = QLabel("")
        self.fehler.setObjectName("diagnoseLine")
        self.fehler.setWordWrap(True)
        lay.addWidget(self.fehler)
        knoepfe = QDialogButtonBox(QDialogButtonBox.Ok
                                   | QDialogButtonBox.Cancel)
        knoepfe.accepted.connect(self._ok)
        knoepfe.rejected.connect(self.reject)
        lay.addWidget(knoepfe)

    def _ok(self) -> None:
        pw = self.eingabe.text()
        if self._festlegen:
            if not pw:
                self.fehler.setText("Passwort darf nicht leer sein.")
                return
            if pw != self.wiederholung.text():
                self.fehler.setText("Passwörter stimmen nicht überein.")
                return
            admin_auth.set_password(pw, self._auth_file)
            self.accept()
            return
        if admin_auth.verify_password(pw, self._auth_file):
            self.accept()
        else:
            self.fehler.setText("Falsches Passwort.")   # kein Lockout
            self.eingabe.selectAll()
            self.eingabe.setFocus()


def ensure_admin_access(parent=None,
                        auth_file: str | Path | None = None) -> bool:
    """True = Zugang gewährt (Passwort neu gesetzt oder korrekt),
    False = abgebrochen. Kapselt beide Modi für das Hauptfenster."""
    dlg = AdminAuthDialog(not admin_auth.is_configured(auth_file),
                          parent, auth_file)
    return dlg.exec() == QDialog.Accepted
```

- [ ] **Step 4: Tests grün verifizieren**

Run: `.venv/bin/pytest tests/test_admin_ui.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add docodetect/ui_qt/admin/__init__.py docodetect/ui_qt/admin/auth_dialog.py tests/test_admin_ui.py
git commit -m "feat(admin): Passwort-Gate-Dialog (1a)"
```

---

### Task 5: Admin-Fenster-Gerüst + System-Status-Seite

**Files:**
- Create: `docodetect/ui_qt/admin/admin_window.py`
- Create: `docodetect/ui_qt/admin/pages/__init__.py` (leer)
- Create: `docodetect/ui_qt/admin/pages/status_page.py`
- Modify: `tests/test_admin_ui.py`

**Interfaces:**
- Consumes: `pipeline.get_status(cfg) -> PipelineStatus` (Felder:
  `calibrated`, `mm_per_px`, `calibrated_unix`, `background_present`,
  `article_count`, `articles_with_references`), `pipeline.list_articles(cfg)
  -> list[ArticleInfo]` (Feld `n_references`), `pipeline.optics_fingerprint`
  (Task 1), `config.resolve`, `widgets.common.section_label`.
- Produces:
  - `StatusPage(cfg: dict, camera_status: Callable[[], str], parent=None)`
    mit `refresh()` und Testhilfe `werte() -> dict`
  - `AdminWindow(cfg: dict, camera_status: Callable[[], str], parent=None)`
    mit `sidebar: QListWidget`, `stack: QStackedWidget`,
    `status_page: StatusPage`; `WA_DeleteOnClose` gesetzt

- [ ] **Step 1: Fehlschlagende Tests schreiben** — an `tests/test_admin_ui.py`
  anhängen:

```python
def _admin_cfg(tmp_path):
    """Minimal-Config wie test_ui_facade.make_cfg, plus captures_dir."""
    return {
        "calibration": {
            "file": str(tmp_path / "calibration.json"),
            "background_file": str(tmp_path / "background.png"),
        },
        "paths": {"db_file": str(tmp_path / "db.sqlite3"),
                  "captures_dir": str(tmp_path / "captures")},
        "stage2": {"enabled": False},
    }


def test_admin_window_seiten_und_leerzustand(qapp, tmp_path):
    from docodetect.ui_qt.admin.admin_window import AdminWindow
    win = AdminWindow(_admin_cfg(tmp_path), camera_status=lambda: "Demo")
    assert win.sidebar.count() == 5           # Status..Diagnose (Spec §4)
    w = win.status_page.werte()
    assert w["kamera"] == "Demo"
    assert w["fingerprint"] == "nicht kalibriert"
    assert w["kalibriert"] == "nicht kalibriert"
    assert w["artikel"].startswith("0")
    assert w["sandbox"] == "–"
    win.close()


def test_admin_window_sidebar_wechselt_seiten(qapp, tmp_path):
    from docodetect.ui_qt.admin.admin_window import AdminWindow
    win = AdminWindow(_admin_cfg(tmp_path), camera_status=lambda: "Demo")
    win.sidebar.setCurrentRow(2)
    assert win.stack.currentIndex() == 2
    win.close()


def test_status_page_fingerprint_mit_einrichtung(qapp, tmp_path):
    import time

    import cv2
    import numpy as np

    from docodetect.calibration import Calibration
    from docodetect.ui_qt.admin.pages.status_page import StatusPage

    cfg = _admin_cfg(tmp_path)
    cfg["features"] = {"ring_zones": 3, "hs_hist_bins": [8, 8]}
    Calibration(mm_per_px=0.5, camera_height_mm=300.0, image_width=1920,
                image_height=1080, marker_size_mm=72.5,
                created_unix=time.time()).save(cfg["calibration"]["file"])
    cv2.imwrite(cfg["calibration"]["background_file"],
                np.zeros((8, 8, 3), dtype=np.uint8))
    seite = StatusPage(cfg, camera_status=lambda: "verbunden")
    w = seite.werte()
    assert len(w["background_sha256"]) == 64
    assert w["mm_per_px"] == "0,5000"
```

- [ ] **Step 2: Fehlschlag verifizieren**

Run: `.venv/bin/pytest tests/test_admin_ui.py -v`
Expected: neue Tests ERROR (`ModuleNotFoundError: ...admin.admin_window`)

- [ ] **Step 3: Status-Seite implementieren** — leeres
  `docodetect/ui_qt/admin/pages/__init__.py` anlegen, dann
  `docodetect/ui_qt/admin/pages/status_page.py`:

```python
"""System-Status (Melde-Punkt 1a): rein lesende Übersicht.

Zwei Gruppen mit bewusster Kennzeichnung (Spec Abschnitt 8): „Optik &
Bestand" ist gegen Quellen AUSSERHALB des Panels prüfbar (CLI, Datei-Hash),
„Umgebung" sind die ausgenommenen Umgebungsfakten — sie beschreiben die
Maschine, nicht die Messung. Kein Worker: get_status/list_articles/
optics_fingerprint sind schnelle Lesezugriffe; 1a startet keinen zweiten
Thread-Pfad (Spec Abschnitt 4)."""

from __future__ import annotations

import shutil
from datetime import datetime
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFormLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from docodetect.config import resolve
from docodetect.pipeline import (get_status, list_articles,
                                 optics_fingerprint)

from ...widgets.common import section_label


def _fmt_bytes(n: float) -> str:
    for einheit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {einheit}".replace(".", ",")
        n /= 1024.0
    return f"{n:.1f} TB".replace(".", ",")


def _zeit(unix: float) -> str:
    return datetime.fromtimestamp(unix).strftime("%d.%m.%Y %H:%M")


class StatusPage(QWidget):
    def __init__(self, cfg: dict, camera_status: Callable[[], str],
                 parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self._camera_status = camera_status
        self._werte: dict = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(10)
        lay.setAlignment(Qt.AlignTop)
        lay.addWidget(section_label("Optik & Bestand"))
        self._form_optik = QFormLayout()
        lay.addLayout(self._form_optik)
        lay.addWidget(section_label("Umgebung (ausgenommen — nicht "
                                    "extern prüfbar)"))
        self._form_umgebung = QFormLayout()
        lay.addLayout(self._form_umgebung)
        self.refresh_button = QPushButton("Aktualisieren")
        self.refresh_button.clicked.connect(self.refresh)
        lay.addWidget(self.refresh_button, alignment=Qt.AlignLeft)
        self.refresh()

    @staticmethod
    def _leere(form: QFormLayout) -> None:
        while form.rowCount():
            form.removeRow(0)

    def _zeile(self, form: QFormLayout, titel: str, wert: str) -> None:
        lab = QLabel(wert)
        lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lab.setWordWrap(True)
        form.addRow(QLabel(titel), lab)

    def refresh(self) -> None:
        st = get_status(self.cfg)
        artikel = list_articles(self.cfg)
        fp = optics_fingerprint(self.cfg)
        db = resolve(self.cfg["paths"]["db_file"])
        bg = resolve(self.cfg["calibration"]["background_file"])

        w = {}
        w["artikel"] = (f"{st.article_count} (davon "
                        f"{st.articles_with_references} mit Referenzen)")
        w["referenzen"] = str(sum(a.n_references for a in artikel))
        w["kalibriert"] = (_zeit(st.calibrated_unix)
                           if st.calibrated_unix else "nicht kalibriert")
        w["mm_per_px"] = (f"{st.mm_per_px:.4f}".replace(".", ",")
                          if st.mm_per_px else "–")
        if fp is None:
            w["fingerprint"] = "nicht kalibriert"
        else:
            w["calibration_sha256"] = fp["calibration_sha256"]
            w["background_sha256"] = fp["background_sha256"]
            w["features_cfg_sha256"] = fp["features_cfg_sha256"]
        w["db"] = (f"{db} ({_fmt_bytes(db.stat().st_size)})"
                   if db.exists() else f"{db} (fehlt)")
        wurzel = db.parent if db.parent.exists() else resolve(".")
        w["plattenplatz"] = _fmt_bytes(shutil.disk_usage(wurzel).free)
        w["hintergrund"] = (f"vorhanden, Stand {_zeit(bg.stat().st_mtime)}"
                            if bg.exists() else "fehlt")
        w["kamera"] = self._camera_status()
        w["sandbox"] = "aktiv" if self.cfg.get("sandbox") else "–"
        self._werte = w

        self._leere(self._form_optik)
        self._zeile(self._form_optik, "Artikel", w["artikel"])
        self._zeile(self._form_optik, "Referenzen gesamt", w["referenzen"])
        self._zeile(self._form_optik, "Kalibriert am", w["kalibriert"])
        self._zeile(self._form_optik, "mm/px", w["mm_per_px"])
        if fp is None:
            self._zeile(self._form_optik, "Optik-Fingerprint",
                        w["fingerprint"])
        else:
            self._zeile(self._form_optik, "Kalibrierung (sha256)",
                        w["calibration_sha256"])
            self._zeile(self._form_optik, "Hintergrund (sha256)",
                        w["background_sha256"])
            self._zeile(self._form_optik, "features-Config (sha256)",
                        w["features_cfg_sha256"])
        self._leere(self._form_umgebung)
        self._zeile(self._form_umgebung, "Datenbank", w["db"])
        self._zeile(self._form_umgebung, "Freier Plattenplatz",
                    w["plattenplatz"])
        self._zeile(self._form_umgebung, "Hintergrund-Datei",
                    w["hintergrund"])
        self._zeile(self._form_umgebung, "Kamera", w["kamera"])
        self._zeile(self._form_umgebung, "Sandbox", w["sandbox"])

    def werte(self) -> dict:
        """Testhilfe (Muster main_window.headline_text): rohe Werte."""
        return dict(self._werte)
```

- [ ] **Step 4: Fenster implementieren** —
  `docodetect/ui_qt/admin/admin_window.py`:

```python
"""Admin-Fenster: Sidebar links, Seiten-Stack rechts (Spec Abschnitt 4).

Nicht-modal, EIN Fenster zur Zeit (das Hauptfenster fokussiert eine
bestehende Instanz). Teilt mit dem Hauptfenster keinen Zustand — die
einzige Meldung Hauptfenster → Admin in 1a ist der Kamera-Zustand als
Callable (Pull, kein gemeinsames Objekt, kein Rückkanal)."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QListWidget,
                               QMainWindow, QStackedWidget, QVBoxLayout,
                               QWidget)

from .pages.status_page import StatusPage

_SEITEN = ("Status", "Reports", "Analyse", "Artikel", "Diagnose")


def _platzhalter(text: str) -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    lab = QLabel(text)
    lab.setAlignment(Qt.AlignCenter)
    lab.setWordWrap(True)
    lab.setObjectName("guideLabel")
    lay.addWidget(lab)
    return w


class AdminWindow(QMainWindow):
    def __init__(self, cfg: dict, camera_status: Callable[[], str],
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("Doco Detect – Admin")
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setMinimumSize(900, 600)
        central = QWidget()
        lay = QHBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.sidebar = QListWidget()
        self.sidebar.setObjectName("adminSidebar")
        self.sidebar.setFixedWidth(180)
        self.sidebar.addItems(list(_SEITEN))
        lay.addWidget(self.sidebar)
        self.stack = QStackedWidget()
        self.status_page = StatusPage(cfg, camera_status)
        self.stack.addWidget(self.status_page)
        for name in _SEITEN[1:]:
            self.stack.addWidget(_platzhalter(
                f"„{name}“ kommt mit einer späteren Stufe "
                "(Spec Abschnitt 6)."))
        lay.addWidget(self.stack, stretch=1)
        self.sidebar.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.sidebar.setCurrentRow(0)
        self.setCentralWidget(central)
```

- [ ] **Step 5: Tests grün verifizieren**

Run: `.venv/bin/pytest tests/test_admin_ui.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add docodetect/ui_qt/admin/ tests/test_admin_ui.py
git commit -m "feat(admin): Fenster-Geruest mit Sidebar + System-Status-Seite (1a)"
```

---

### Task 6: Anbindung ans Hauptfenster

**Files:**
- Modify: `docodetect/ui_qt/main_window.py`
- Modify: `tests/test_admin_ui.py`

**Interfaces:**
- Consumes: `ToolRail.admin_requested` (Task 3),
  `ensure_admin_access` (Task 4), `AdminWindow` (Task 5).
- Produces: `MainWindow._open_admin_panel()`,
  `MainWindow._camera_status_text() -> str`,
  Attribut `MainWindow._admin_window: AdminWindow | None`.

- [ ] **Step 1: Fehlschlagenden Test schreiben** — an `tests/test_admin_ui.py`
  anhängen (die `make_main_cfg`-Hilfe ist die Demo-Config aus
  `tests/test_ui_state.py`, hier vollständig wiederholt):

```python
def make_main_cfg(tmp_path):
    """Minimal-Config für ein Demo-MainWindow (wie test_ui_state.py)."""
    return {
        "camera": {"width": 1920, "height": 1080},
        "calibration": {
            "file": str(tmp_path / "calibration.json"),
            "background_file": str(tmp_path / "background.png"),
            "aruco_dict": "DICT_4X4_50", "marker_id": 0,
            "marker_size_mm": 136.0,
        },
        "geometry": {"camera_height_mm": 300.0},
        "paths": {"db_file": str(tmp_path / "db.sqlite3")},
        "matching": {"diameter_tolerance_mm": 6.0, "top_k": 3},
        "stage2": {"enabled": False},
    }


def test_schloss_oeffnet_admin_nur_mit_zugang(qapp, tmp_path, monkeypatch):
    from docodetect.ui_qt import main_window as mw_mod
    from docodetect.ui_qt.admin import auth_dialog

    win = mw_mod.MainWindow(make_main_cfg(tmp_path), demo=True)
    monkeypatch.setattr(auth_dialog, "ensure_admin_access",
                        lambda parent=None, auth_file=None: False)
    win._open_admin_panel()
    assert win._admin_window is None              # Zugang verweigert
    monkeypatch.setattr(auth_dialog, "ensure_admin_access",
                        lambda parent=None, auth_file=None: True)
    win._open_admin_panel()
    assert win._admin_window is not None
    assert win._camera_status_text() == "Demo"
    erstes = win._admin_window
    win._open_admin_panel()                       # fokussiert nur
    assert win._admin_window is erstes
    win._admin_window.close()
    win.close()
```

- [ ] **Step 2: Fehlschlag verifizieren**

Run: `.venv/bin/pytest tests/test_admin_ui.py::test_schloss_oeffnet_admin_nur_mit_zugang -v`
Expected: FAIL (`AttributeError: _open_admin_panel`)

- [ ] **Step 3: MainWindow anbinden** — in `main_window.py`:

  In `__init__` bei den anderen Instanz-Attributen (nach
  `self._calibrate_dialog = None`):

```python
        self._admin_window = None            # offenes Admin-Fenster (1a)
```

  In `_wire_actions()` nach der `theme_toggle`-Zeile:

```python
        self.tool_rail.admin_requested.connect(self._open_admin_panel)
```

  Neue Methoden (nach `_open_enroll_dialog`/`_frage_offene_sessions`,
  vor „Job-Ergebnisse"):

```python
    # ---------- Admin-Bereich (Spec Admin-Panel, 1a) ----------

    def _camera_status_text(self) -> str:
        """Einseitige Meldung Hauptfenster → Admin (Spec §4): Pull über
        Callable, abgeleitet aus vorhandenem Zustand — kein geteiltes
        Objekt, kein Rückkanal."""
        if self.demo:
            return "Demo"
        return "verbunden" if self.camera_ok else "getrennt"

    def _open_admin_panel(self) -> None:
        """Schloss-Knopf: Passwort-Gate, dann EIN Admin-Fenster.
        Nicht-modal; erneutes Öffnen fokussiert die bestehende Instanz."""
        from .admin.auth_dialog import ensure_admin_access

        if self._admin_window is not None:
            self._admin_window.raise_()
            self._admin_window.activateWindow()
            return
        if not ensure_admin_access(self):
            return
        from .admin.admin_window import AdminWindow

        win = AdminWindow(self.cfg, self._camera_status_text, parent=self)
        win.destroyed.connect(
            lambda *_: setattr(self, "_admin_window", None))
        self._admin_window = win
        win.show()
```

- [ ] **Step 4: Tests grün + UI-Nachbarn verifizieren**

Run: `.venv/bin/pytest tests/test_admin_ui.py -v && .venv/bin/pytest tests/test_ui_state.py -v`
Expected: beide PASS

- [ ] **Step 5: Commit**

```bash
git add docodetect/ui_qt/main_window.py tests/test_admin_ui.py
git commit -m "feat(ui): Schloss-Knopf oeffnet Admin-Fenster mit Passwort-Gate (1a)"
```

---

### Task 7: Melde-Punkt 1a — Regime-Lauf + Abnahme-Stichprobe (blockierend)

**Files:** keine Code-Änderungen. Ausgaben nach `~/Documents/tmp/`.

- [ ] **Step 1: Testauswahl nach Spec Abschnitt 10 laufen lassen** (seriell,
  UI-Module einzeln; Vollausgabe in Datei):

```bash
OUT="$HOME/Documents/tmp/$(date +%Y-%m-%d)-melde-punkt-1a-tests.txt"; : > "$OUT"
for m in tests/test_ui_*.py tests/test_camera_worker.py \
         tests/test_demo_scenes.py tests/test_demo_seed_state.py \
         tests/test_icon_hidpi.py tests/test_admin_ui.py; do
    echo "== $m ==" >> "$OUT"; .venv/bin/pytest "$m" >> "$OUT" 2>&1 \
        || echo "PRUEFEN: $m (Summary in $OUT ansehen)"
done
.venv/bin/pytest tests/test_pipeline_synthetic.py tests/test_enroll_session*.py \
    tests/test_admin_auth.py >> "$OUT" 2>&1 || echo "PRUEFEN: pipeline-Block"
grep -h "passed\|failed\|error" "$OUT"
```

Expected: alle Summaries grün. **Erwartete Laufzeit ~220 s** (213 s
gemessen am 2026-08-10 plus wenige Sekunden für `test_admin_ui`/
`test_admin_auth`). Bekannte Eigenheit: `tests/test_ui_qt_smoke.py` kann
trotz grüner Summary mit Exit 134 enden (vorbestehender Teardown-Abort,
Spec Abschnitt 10) — maßgeblich ist die Summary-Zeile.

- [ ] **Step 2: Abnahme-Stichprobe Panel↔externe Quelle** — App normal
  starten (`.venv/bin/python -m docodetect.ui_qt`), Admin öffnen
  (Passwort beim ersten Mal festlegen), Status-Seite ablesen und JEDEN
  Wert der Gruppe „Optik & Bestand" gegen seinen Befehl vergleichen
  (alles read-only):

| Panel-Wert | Externer Befehl |
|---|---|
| Artikel / davon mit Referenzen | `.venv/bin/python -m docodetect.cli list-articles` (Zeilen zählen bzw. Referenz-Spalte > 0) |
| Referenzen gesamt | derselbe Befehl, Summe der Referenz-Spalte |
| Kalibriert am, mm/px | `python3 -m json.tool calibration/calibration.json` (`created_unix`, `mm_per_px`) |
| Kalibrierung (sha256) | `shasum -a 256 calibration/calibration.json` |
| Hintergrund (sha256) | `shasum -a 256 calibration/background.png` |
| features-Config (sha256) | `.venv/bin/python -c "import json,hashlib; from docodetect.config import load_config; print(hashlib.sha256(json.dumps(load_config()['features'], sort_keys=True).encode('utf-8')).hexdigest())"` |

  Die Gruppe „Umgebung" (DB-Pfad/-Größe, Plattenplatz,
  Hintergrund-Datei-Alter, Kamera, Sandbox) ist per Spec Abschnitt 8
  **ausgenommen** und auf der Seite als solche gekennzeichnet — keine
  externe Prüfung.

- [ ] **Step 3: Melden und STOPPEN.** Melde-Text enthält: Summary-Zeilen
  aller Testaufrufe, die Stichproben-Tabelle mit Panel-Wert, Befehl und
  externem Wert nebeneinander, Laufzeit. **Kein Merge, kein Push, kein
  Weiterarbeiten an 1b** — auf Antwort warten (Spec Abschnitt 11; volle
  Suite und beide Korpus-Stufen folgen erst zum Merge nach 1b).

---

## Notizen für 1b (nicht Teil von 1a)

- **NO_MATCH ist ein Sonderwert, kein Artikel** (Festlegung 2026-08-10):
  `report_predicted_article` liefert bei leerem Kandidatenset den
  Sonderwert `NO_MATCH` (bestehende reporting-Semantik). Die
  Report-Browser-Tabelle darf das NICHT als Artikelnummer darstellen,
  sondern als eigenen Zustand (z. B. „kein Kandidat").
- **Sortierschlüssel — entschieden (2026-08-10):** Der mtime-Befund
  (`save_verdict` schreibt das JSON neu, bewertete alte Reports springen
  nach vorn) ist in 1a ADDITIV gelöst: `load_reports(sort_by=…)` mit
  Default `"mtime"` (bisheriges Verhalten, kein Aufrufer geändert), die
  Fassade wählt ausdrücklich `"name"`. `test_floor_analysis.py` und sein
  Docstring bleiben unangetastet — floor_analysis behält mtime.

## Vorgemerkter eigener Vorgang (nicht Teil von 1a): globale Umstellung auf Dateiname

Festgelegt 2026-08-10 nach dem mtime-Befund; Start nur mit eigener
Freigabe. Inhalt:

- **Umstellung des `load_reports`-Defaults auf den Dateinamen** (analysis
  sortiert bereits selbst nach Stem, `analysis.py:642–649`; `save_verdict`
  macht mtime unzuverlässig).
- **Nachweis für floor_analysis:** `analyze-floors` auf identischem
  Bestand vor/nach der Umstellung, Ergebnis-Floors numerisch verglichen.
  Abweichung > 0 = Stopp und Meldung, keine stille Übernahme.
- **Latenter Befund (eigenständig, unabhängig von der Umstellung):**
  floor_analysis' `limit` greift heute auf „zuletzt geschrieben" statt
  „zuletzt aufgenommen" — mit `save_verdict` im Spiel ist das für
  bewertete Bestände falsch.
- **`corpus/build.py`:** Append-Reihenfolge künftiger Manifest-Einträge
  kann sich ändern (versioniertes Manifest, im Diff sichtbar) — vor der
  Umstellung klären, ob die Reihenfolge dort Bedeutung hat oder rein
  kosmetisch ist.
