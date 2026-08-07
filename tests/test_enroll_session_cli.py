"""CLI der Einlern-Sessions – Schritt 5: der Rettungspfad OHNE GUI.

Design: docs/superpowers/specs/2026-08-05-crashsichere-einlern-session-design.md

Gefahren wird ueber `cli.main(argv)`, also ueber den echten Argumentparser und
die echte Befehlsverteilung — nicht ueber die cmd_-Funktionen direkt. Sonst
bliebe ungeprueft, ob ein Befehl ueberhaupt registriert ist.

Der Punkt dieser Schicht: Auflisten, Ansehen, Buchen und Verwerfen laufen ohne
Qt und ohne Kamera. Der Rettungsfall ist genau der, in dem Qt das kaputte Teil
ist. Nur ZUSAETZLICHE Aufnahmen brauchen eine Kamera.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect import cli  # noqa: E402
from docodetect.database import Database  # noqa: E402
from docodetect.pipeline import (append_shot, begin_enroll_session,  # noqa: E402
                                 stage_frame)
from test_enroll_session import (ARTIKEL, _artikel_anlegen, _feats,  # noqa: E402
                                 _frame, _optik_anlegen, make_cfg)


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    c = make_cfg(tmp_path)
    _optik_anlegen(c)
    _artikel_anlegen(c)
    # main() laedt sonst die echte config.yaml und wuerde gegen den
    # Produktivbestand laufen.
    monkeypatch.setattr(cli, "load_config", lambda *a, **kw: c)
    return c


def _sitzung(cfg, n=3, start=270.0):
    s = begin_enroll_session(cfg, ARTIKEL, target_shots=n)
    for k in range(n):
        s = append_shot(cfg, s, stage_frame(cfg, s, _frame(100 + k)),
                        _feats(start + k))
    return s


def _lauf(capsys, *argv):
    """cli.main ueber den echten Parser. Gibt (stdout, stderr, exitcode).

    `sys.exit("Meldung")` ist die Hausform im Bestand (so auch
    cmd_delete_references). Den Text schreibt der INTERPRETER beim Verlassen
    nach stderr — faengt der Test SystemExit ab, wird er nie gedruckt und
    steckt stattdessen in e.code. Hier wird er zurueck in stderr gefaltet,
    damit der Test dasselbe sieht wie eine echte Shell: Text auf stderr,
    Exitcode 1."""
    code, meldung = 0, ""
    try:
        cli.main(list(argv))
    except SystemExit as e:
        if isinstance(e.code, int):
            code = e.code
        elif e.code is None:
            code = 0
        else:
            code, meldung = 1, str(e.code)
    aus = capsys.readouterr()
    return aus.out, aus.err + meldung, code


def _refs(cfg):
    db = Database(cfg)
    try:
        return db.references_with_meta(ARTIKEL)
    finally:
        db.close()


# ---------- list ----------

def test_list_ohne_sessions(cfg, capsys):
    out, _err, code = _lauf(capsys, "list-enroll-sessions")
    assert code == 0
    assert "Keine offene Einlern-Session" in out


def test_list_zeigt_session_mit_zustand_und_optik(cfg, capsys):
    s = _sitzung(cfg, 3)
    out, _err, code = _lauf(capsys, "list-enroll-sessions")
    assert code == 0
    assert ARTIKEL in out and str(s.info.ts) in out
    assert "3/3 Aufnahmen" in out
    assert "offen" in out
    assert "Optik unveraendert" in out


def test_list_json_ist_maschinenlesbar(cfg, capsys):
    s = _sitzung(cfg, 2)
    out, _err, code = _lauf(capsys, "list-enroll-sessions", "--json")
    assert code == 0
    daten = json.loads(out)
    assert len(daten) == 1
    assert daten[0]["article_number"] == ARTIKEL
    assert daten[0]["ts"] == s.info.ts
    assert daten[0]["n_shots"] == 2
    assert daten[0]["zustand"] == "offen"
    assert daten[0]["fingerprint_ok"] is True


def test_list_filtert_nach_artikel(cfg, capsys):
    from docodetect.database import Article
    db = Database(cfg)
    db.create_article(Article(article_number="T-999", name="Zweiter",
                              category=None, diameter_mm=200.0, width_mm=None,
                              depth_mm=None, height_mm=10.0, color_desc=None,
                              notes=None))
    db.close()
    _sitzung(cfg, 1)
    begin_enroll_session(cfg, "T-999", target_shots=2)
    out, _e, _c = _lauf(capsys, "list-enroll-sessions", "--article", "T-999")
    assert "T-999" in out and ARTIKEL not in out


# ---------- --ts-Pflicht bei Mehrdeutigkeit ----------

def test_zwei_sessions_verlangen_ts(cfg, capsys):
    """Zwei Abstuerze hintereinander erzeugen genau das. Es wird NICHT geraten:
    eine falsch gewaehlte Session buchte fremde Aufnahmen unter die Nummer."""
    a = _sitzung(cfg, 1)
    b = _sitzung(cfg, 2)
    for befehl in ("show-enroll-session", "commit-enroll-session",
                   "discard-enroll-session"):
        _out, err, code = _lauf(capsys, befehl, ARTIKEL)
        assert code == 1, befehl
        assert "--ts ist dann Pflicht" in err, befehl
        assert str(a.info.ts) in err and str(b.info.ts) in err, befehl


def test_ts_waehlt_die_richtige_session(cfg, capsys):
    a = _sitzung(cfg, 1, start=200.0)
    _b = _sitzung(cfg, 2, start=300.0)
    out, _err, code = _lauf(capsys, "show-enroll-session", ARTIKEL,
                            "--ts", str(a.info.ts))
    assert code == 0
    assert f"ts {a.info.ts}" in out
    assert "1 von 1 geplant" in out


def test_unbekannte_ts_nennt_die_vorhandenen(cfg, capsys):
    s = _sitzung(cfg, 1)
    _out, err, code = _lauf(capsys, "show-enroll-session", ARTIKEL, "--ts", "1")
    assert code == 1
    assert str(s.info.ts) in err


def test_unbekannter_artikel_endet_sauber(cfg, capsys):
    _out, err, code = _lauf(capsys, "show-enroll-session", "GIBTSNICHT")
    assert code == 1
    assert "Keine offene Einlern-Session" in err


# ---------- show ----------

def test_show_nennt_ort_jeder_aufnahme(cfg, capsys):
    s = _sitzung(cfg, 2)
    out, _err, code = _lauf(capsys, "show-enroll-session", ARTIKEL)
    assert code == 0
    assert "Zustand:   offen" in out
    assert out.count("Session") >= 2, "je Aufnahme der Ort"
    assert "270.0" in out or "270,0" in out or "270.0" in out.replace(" ", "")


def test_show_meldet_geaenderte_optik_mit_ausweg(cfg, capsys):
    from docodetect.calibration import Calibration
    _sitzung(cfg, 2)
    Calibration(mm_per_px=0.25, camera_height_mm=300.0, image_width=1920,
                image_height=1080, marker_size_mm=50.0,
                created_unix=1.0).save(cfg["calibration"]["file"])
    out, _err, code = _lauf(capsys, "show-enroll-session", ARTIKEL)
    assert code == 0
    assert "GEAENDERT" in out
    assert "Nicht fortsetzbar" in out
    assert "optik" in out, "der Ausweg wird genannt"


# ---------- commit ----------

def test_commit_bucht(cfg, capsys):
    _sitzung(cfg, 3)
    out, _err, code = _lauf(capsys, "commit-enroll-session", ARTIKEL)
    assert code == 0
    assert "3 Referenzen gebucht" in out
    assert len(_refs(cfg)) == 3


def test_commit_dry_run_bewegt_nichts(cfg, capsys):
    s = _sitzung(cfg, 3)
    out, _err, code = _lauf(capsys, "commit-enroll-session", ARTIKEL, "--dry-run")
    assert code == 0
    assert "Buchungsstand 'leer'" in out
    assert out.count("verschieben") == 3, "Plan je Aufnahme"
    assert "Nichts bewegt, nichts gebucht" in out
    assert _refs(cfg) == [], "DB unberuehrt"
    assert all(sh.raw_path.is_file() for sh in s.shots), "Dateien unberuehrt"
    assert s.info.path.is_dir(), "Session unberuehrt"


def test_commit_dry_run_laesst_die_pruefungen_echt_laufen(cfg, capsys):
    """Ein Probelauf, der andere Fehler meldet als der echte Lauf, taeuscht
    Sicherheit vor."""
    from docodetect.calibration import Calibration
    _sitzung(cfg, 2)
    Calibration(mm_per_px=0.25, camera_height_mm=300.0, image_width=1920,
                image_height=1080, marker_size_mm=50.0,
                created_unix=1.0).save(cfg["calibration"]["file"])
    _out, err, code = _lauf(capsys, "commit-enroll-session", ARTIKEL, "--dry-run")
    assert code == 1
    assert "FINGERPRINT" in err
    assert "optik_kopie" in err, "der Ausweg steht im detail"


def test_commit_meldet_luecke_als_befund(cfg, capsys):
    s = _sitzung(cfg, 2)
    append_shot(cfg, s, stage_frame(cfg, s, _frame()), _feats(9.0), i=7)
    _out, err, code = _lauf(capsys, "commit-enroll-session", ARTIKEL)
    assert code == 1
    assert "LUECKE" in err
    assert _refs(cfg) == []


# ---------- discard ----------

def test_discard_verwirft_und_loescht_nichts(cfg, capsys):
    s = _sitzung(cfg, 2)
    namen = [sh.raw_path.name for sh in s.shots]
    out, _err, code = _lauf(capsys, "discard-enroll-session", ARTIKEL)
    assert code == 0
    assert "nichts geloescht" in out
    assert not s.info.path.exists()
    verworfen = Path(cfg["paths"]["reference_dir"]).parent / "verworfen" / ARTIKEL
    ziel = next(verworfen.iterdir())
    for n in namen:
        assert (ziel / n).is_file(), f"{n} ist erhalten"
    assert _refs(cfg) == []


def test_discard_dry_run_zeigt_gegenrichtung_ohne_zu_bewegen(cfg, capsys):
    """Der Rueckumzug greift AUS reference_dir heraus – die gefaehrlichere
    Richtung, und genau dort will man vorher sehen, was passieren soll."""
    import os
    s = _sitzung(cfg, 3)
    ziel_dir = Path(cfg["paths"]["reference_dir"]) / ARTIKEL
    ziel_dir.mkdir(parents=True, exist_ok=True)
    umgezogen = ziel_dir / f"{s.info.ts}_00.png"
    os.rename(str(s.shots[0].raw_path), str(umgezogen))

    out, _err, code = _lauf(capsys, "discard-enroll-session", ARTIKEL, "--dry-run")
    assert code == 0
    assert "zurueckholen" in out, "die eine verschobene Datei"
    assert out.count("nichts_zu_tun") == 2, "die beiden noch in der Session"
    assert "Nichts bewegt, kein info.json" in out
    assert umgezogen.is_file(), "nichts zurueckgeholt"
    assert s.info.path.is_dir()
    assert not (s.info.path / "info.json").exists()


def test_dry_run_und_echter_lauf_planen_dasselbe_COMMIT(cfg, capsys):
    """EINE Stelle entscheidet (_umzug_plan), zwei lesen sie. Ein --dry-run,
    der etwas anderes sagt als der echte Lauf, waere schlimmer als keiner."""
    s = _sitzung(cfg, 3)
    out_dry, _e, _c = _lauf(capsys, "commit-enroll-session", ARTIKEL, "--dry-run")
    geplant = [z for z in out_dry.splitlines() if "verschieben" in z]
    assert len(geplant) == 3

    _out, _e, code = _lauf(capsys, "commit-enroll-session", ARTIKEL)
    assert code == 0
    gebucht = sorted(p for p, _ in _refs(cfg))
    for zeile in geplant:
        ziel = zeile.split()[-1]
        assert ziel in gebucht, f"geplantes Ziel {ziel} wurde auch gebucht"


def test_dry_run_und_echter_lauf_planen_dasselbe_DISCARD(cfg, capsys):
    """Dieselbe Zusicherung fuer die GEGENRICHTUNG (_reverse_plan) – und die
    ist die gefaehrlichere: der Rueckumzug greift AUS reference_dir heraus.

    Geprueft wird, dass jede im Probelauf mit 'zurueckholen' angekuendigte
    Datei danach wirklich zurueckgeholt (und mit der Session gesichert) ist,
    und dass keine andere Datei angefasst wurde."""
    import os
    s = _sitzung(cfg, 3)
    ziel_dir = Path(cfg["paths"]["reference_dir"]) / ARTIKEL
    ziel_dir.mkdir(parents=True, exist_ok=True)
    umgezogen = ziel_dir / f"{s.info.ts}_00.png"
    os.rename(str(s.shots[0].raw_path), str(umgezogen))

    out_dry, _e, _c = _lauf(capsys, "discard-enroll-session", ARTIKEL, "--dry-run")
    zurueck = [z for z in out_dry.splitlines() if "zurueckholen" in z]
    ruhe = [z for z in out_dry.splitlines() if "nichts_zu_tun" in z]
    assert len(zurueck) == 1 and len(ruhe) == 2
    angekuendigt = Path(zurueck[0].split()[-1])          # der Zielpfad im Plan
    assert angekuendigt == umgezogen

    _out, _e, code = _lauf(capsys, "discard-enroll-session", ARTIKEL)
    assert code == 0

    assert not umgezogen.exists(), "die angekuendigte Datei wurde zurueckgeholt"
    assert not any(ziel_dir.glob("*.png")), "und keine andere blieb liegen"
    verworfen = Path(cfg["paths"]["reference_dir"]).parent / "verworfen" / ARTIKEL
    gesichert = next(verworfen.iterdir())
    protokoll = json.loads((gesichert / "info.json").read_text())["rueckumzug"]
    assert [e["aktion"] for e in protokoll] == \
        ["zurueckgeholt", "nichts_zu_tun", "nichts_zu_tun"], \
        "das Protokoll deckt sich mit dem Probelauf"
    assert len(list(gesichert.glob("raw_*.png"))) == 3, "alle drei gesichert"


# ---------- der Rettungspfad als Ganzes ----------

def test_rettungspfad_ohne_qt_vollstaendig(cfg, capsys, monkeypatch):
    """Eine unterbrochene Session vom Terminal aus zu Ende bringen – ohne dass
    Qt ueberhaupt importierbar ist.

    PySide6 wird fuer die Dauer des Tests unimportierbar gemacht: wuerde
    irgendein Pfad die GUI anfassen, schluege der Test fehl statt still zu
    funktionieren."""
    import builtins
    echt_import = builtins.__import__

    def kein_qt(name, *a, **kw):
        if name.startswith("PySide6"):
            raise ImportError("PySide6 ist in diesem Test nicht verfuegbar")
        return echt_import(name, *a, **kw)
    monkeypatch.setattr(builtins, "__import__", kein_qt)
    for mod in [m for m in list(sys.modules) if m.startswith("PySide6")]:
        monkeypatch.delitem(sys.modules, mod, raising=False)

    s = _sitzung(cfg, 3)                       # "abgestuerzte" Session

    out, _e, c = _lauf(capsys, "list-enroll-sessions")
    assert c == 0 and ARTIKEL in out

    out, _e, c = _lauf(capsys, "show-enroll-session", ARTIKEL)
    assert c == 0 and "Zustand:   offen" in out

    out, _e, c = _lauf(capsys, "commit-enroll-session", ARTIKEL, "--dry-run")
    assert c == 0 and "Nichts bewegt" in out

    out, _e, c = _lauf(capsys, "commit-enroll-session", ARTIKEL)
    assert c == 0 and "3 Referenzen gebucht" in out

    assert len(_refs(cfg)) == 3
    assert not s.info.path.exists()
    for pfad, _f in _refs(cfg):
        assert Path(pfad).is_file(), "keine Zeile zeigt ins Leere"
