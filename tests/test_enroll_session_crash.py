"""Absturzsimulation der Einlern-Session – Schritt 4, der Beweis des Pakets.

Design: docs/superpowers/specs/2026-08-05-crashsichere-einlern-session-design.md

Ein KINDPROZESS faehrt die Session ueber die Fassaden und meldet ueber eine
Markerdatei, dass er einen definierten Punkt erreicht hat. Der Elternprozess
schiesst ihn dort mit SIGKILL ab — kein Handler, kein `finally`, kein
Aufraeumen, so nah an einem Absturz wie es ohne Hardware geht. Geprueft wird
danach AUSSCHLIESSLICH, was auf der Platte liegt.

Fuenf Abschusspunkte, je einer pro Zustand aus Abschnitt 3.10 des Designs.

GRENZE, die im Bericht stehen muss: SIGKILL beendet den PROZESS, laesst aber
den Page-Cache des Betriebssystems intakt. Diese Tests pruefen damit den
Prozessabsturz, NICHT den Stromausfall — der eigentliche Zweck von fsync ist
damit ENTWORFEN, aber NICHT VERIFIZIERT. Verifikation braeuchte
Crash-Consistency-Werkzeug (dm-flakey, VM-Snapshot), das dieses Projekt nicht
hat. Kein Test hier ist so beschriftet, als deckte er das ab.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PROJEKT = Path(__file__).resolve().parent.parent

from docodetect.database import Database  # noqa: E402
from docodetect.pipeline import (commit_enroll_session,  # noqa: E402
                                 list_enroll_sessions, load_enroll_session,
                                 referenzbild_pfad)
from test_enroll_session import (ARTIKEL, _artikel_anlegen,  # noqa: E402
                                 _optik_anlegen, make_cfg)

# Das Kind laeuft in einem EIGENEN Interpreter – nur so ist der SIGKILL echt.
_KIND = r'''
import json, os, sys, time
from pathlib import Path

projekt, cfg_datei, punkt, marke, n, artikel = sys.argv[1:7]
sys.path.insert(0, projekt)
n = int(n)

import numpy as np
from docodetect import pipeline as pl
from docodetect.database import Database
from docodetect.features import Features

cfg = json.loads(Path(cfg_datei).read_text())


def halt():
    """Punkt erreicht: Marke setzen und auf den SIGKILL warten."""
    Path(marke).write_text("da")
    while True:
        time.sleep(0.2)


def frame(w=120):
    return np.full((64, 96, 3), w, dtype=np.uint8)


def feats(d):
    return Features(
        equiv_diameter_mm=d, circle_diameter_mm=d, area_mm2=57255.0,
        perimeter_mm=848.0, circularity=0.95, aspect_ratio=1.0,
        mean_hsv=[0.0, 0.0, 200.0], solidity=0.99, hu_moments=[1.0] * 7,
        lab_center=[80.0, 0.0, 0.0], lab_rim=[80.0, 0.0, 0.0],
        hs_hist_center=[1.0], hs_hist_rim=[1.0])


s = pl.begin_enroll_session(cfg, artikel, target_shots=n)

if punkt == "png_vor_journal":
    for i in range(n - 1):
        s = pl.append_shot(cfg, s, pl.stage_frame(cfg, s, frame()), feats(270.0 + i))
    pl.stage_frame(cfg, s, frame())        # PNG liegt, KEINE Journalzeile
    halt()

if punkt == "k_journalzeilen":
    for i in range(2):
        s = pl.append_shot(cfg, s, pl.stage_frame(cfg, s, frame()), feats(270.0 + i))
    halt()

for i in range(n):                          # ab hier: vollstaendige Session
    s = pl.append_shot(cfg, s, pl.stage_frame(cfg, s, frame()), feats(270.0 + i))

if punkt == "mitten_im_umzug":
    echt, zaehler = os.rename, {"k": 0}

    def haenger(a, b):
        if zaehler["k"] >= 1:
            halt()
        zaehler["k"] += 1
        return echt(a, b)
    os.rename = haenger
    pl.commit_enroll_session(cfg, s)

if punkt == "vor_transaktion":
    Database.add_references = lambda self, nr, items: halt()
    pl.commit_enroll_session(cfg, s)

if punkt == "vor_backups":
    pl._raeume_nach_backups = lambda c, sess: halt()
    pl.commit_enroll_session(cfg, s)

sys.exit(99)                                # nie erreicht
'''


@pytest.fixture
def cfg(tmp_path):
    c = make_cfg(tmp_path)
    _optik_anlegen(c)
    _artikel_anlegen(c)
    return c


def _abschuss(tmp_path, cfg, punkt, n=3):
    """Kind bis `punkt` laufen lassen, dann SIGKILL. Gibt die Session zurueck,
    wie sie danach AUF DER PLATTE liegt."""
    skript = tmp_path / "kind.py"
    skript.write_text(_KIND, encoding="utf-8")
    cfg_datei = tmp_path / "cfg.json"
    cfg_datei.write_text(json.dumps(cfg), encoding="utf-8")
    marke = tmp_path / f"marke_{punkt}"

    fehlerdatei = tmp_path / f"kind_{punkt}.err"
    with open(fehlerdatei, "wb") as err:     # Datei statt PIPE: eine volle Pipe
        p = subprocess.Popen(                # koennte das Kind blockieren, und
            [sys.executable, str(skript), str(PROJEKT), str(cfg_datei), punkt,
             str(marke), str(n), ARTIKEL],   # gelesen wird erst im Fehlerfall
            stdout=subprocess.DEVNULL, stderr=err)
        for _ in range(600):                # bis 60 s
            if marke.exists():
                break
            if p.poll() is not None:
                raise AssertionError(
                    f"Kind endete vor dem Punkt {punkt!r} (rc={p.returncode}):\n"
                    + fehlerdatei.read_text(encoding="utf-8", errors="replace"))
            time.sleep(0.1)
        else:
            p.kill(); p.wait()
            raise AssertionError(f"Kind erreichte {punkt!r} nicht")

        p.kill()                             # unabfangbar – kein finally, kein atexit
        rc = p.wait()

    # Ohne diese Zusicherung meldete ein Kind, das den Abschusspunkt nie
    # erreicht, still gruen. Plattformabhaengig, weil Popen.kill() sich
    # unterscheidet (CPython subprocess.py): POSIX sendet SIGKILL -> rc -9
    # (bzw. 137 ueber eine Shell), Windows ruft TerminateProcess(handle, 1)
    # -> rc 1. Semantisch ist beides dasselbe: unabfangbar, ohne Aufraeumen.
    # 99 ist der Sentinel des Kindes fuer "bis zum Ende durchgelaufen".
    assert rc != 99, f"Kind lief durch statt abgeschossen zu werden ({punkt})"
    if sys.platform == "win32":
        assert rc == 1, f"kein TerminateProcess, rc={rc}"
    else:
        assert rc in (-9, 137), f"kein SIGKILL, rc={rc}"

    offen = list_enroll_sessions(cfg)
    assert len(offen) == 1, f"genau eine Session erwartet, gefunden: {len(offen)}"
    return load_enroll_session(cfg, offen[0].path)


def _refs(cfg):
    db = Database(cfg)
    try:
        return db.references_with_meta(ARTIKEL)
    finally:
        db.close()


def _keine_toten_pfade(cfg):
    """Nach JEDEM Abschusspunkt: keine DB-Zeile darf ins Leere zeigen.
    Aufgeloest wird wie ueberall ueber die Fassade (die Zeilen sind seit der
    Relativ-Umstellung reference_dir-relativ gespeichert)."""
    for pfad, _ in _refs(cfg):
        assert pfad and referenzbild_pfad(cfg, pfad) is not None, \
            f"DB-Zeile zeigt ins Leere: {pfad}"


def _dateien_vollzaehlig(s, cfg):
    """Nach JEDEM Abschusspunkt: keine Datei eines Shots ist verschwunden."""
    ref = Path(cfg["paths"]["reference_dir"]) / ARTIKEL
    for shot in s.shots:
        ziel = ref / f"{s.info.ts}_{shot.i:02d}.png"
        assert shot.raw_path.is_file() or ziel.is_file(), \
            f"Shot {shot.i} ist weder in der Session noch im Ziel"


# ---------- Punkt 1: PNG geschrieben, VOR der Journalzeile ----------

def test_abschuss_zwischen_png_und_journalzeile(tmp_path, cfg):
    s = _abschuss(tmp_path, cfg, "png_vor_journal", n=3)

    assert s.info.n_shots == 2, "das letzte PNG zaehlt NICHT als Shot"
    rohbilder = sorted(p.name for p in s.info.path.glob("raw_*.png"))
    assert len(rohbilder) == 3, "das Waisen-PNG liegt da"
    im_journal = {sh.raw_path.name for sh in s.shots}
    waise = set(rohbilder) - im_journal
    assert len(waise) == 1
    assert (s.info.path / waise.pop()).stat().st_size > 0, "vollstaendig geschrieben"

    assert s.info.zustand == "offen", "Session ist fortsetzbar"
    assert _refs(cfg) == []
    _keine_toten_pfade(cfg)
    _dateien_vollzaehlig(s, cfg)


# ---------- Punkt 2: nach k Journalzeilen ----------

def test_abschuss_nach_k_journalzeilen(tmp_path, cfg):
    s = _abschuss(tmp_path, cfg, "k_journalzeilen", n=3)

    assert s.info.n_shots == 2
    assert [sh.i for sh in s.shots] == [0, 1]
    assert [sh.d_mm for sh in s.shots] == [270.0, 271.0]
    assert s.info.zustand == "offen"
    assert _refs(cfg) == []
    _keine_toten_pfade(cfg)
    _dateien_vollzaehlig(s, cfg)


def test_nach_abschuss_sind_weitere_aufnahmen_moeglich(tmp_path, cfg):
    """Die Rettung, nicht nur der Befund: fortsetzen und zu Ende bringen."""
    from docodetect.pipeline import append_shot, stage_frame
    from test_enroll_session import _feats, _frame

    s = _abschuss(tmp_path, cfg, "k_journalzeilen", n=3)
    s = append_shot(cfg, s, stage_frame(cfg, s, _frame()), _feats(272.0))
    assert s.info.n_shots == 3
    assert commit_enroll_session(cfg, s) == 3
    assert len(_refs(cfg)) == 3
    _keine_toten_pfade(cfg)


# ---------- Punkt 3: mitten im Umzug ----------

def test_abschuss_mitten_im_umzug(tmp_path, cfg):
    s = _abschuss(tmp_path, cfg, "mitten_im_umzug", n=3)
    ref = Path(cfg["paths"]["reference_dir"]) / ARTIKEL

    verschoben = sorted(p.name for p in ref.glob("*.png")) if ref.is_dir() else []
    assert len(verschoben) == 1, f"genau eine Datei umgezogen, gefunden: {verschoben}"
    assert s.info.zustand == "umzug_unterbrochen"
    assert _refs(cfg) == [], "die DB ist leer – U1 haelt"
    _keine_toten_pfade(cfg)
    _dateien_vollzaehlig(s, cfg)

    assert commit_enroll_session(cfg, s) == 3, "commit fuehrt den Umzug zu Ende"
    assert len(_refs(cfg)) == 3
    _keine_toten_pfade(cfg)
    assert not s.info.path.exists()


# ---------- Punkt 4: alle Renames durch, VOR der Transaktion ----------

def test_abschuss_vor_der_transaktion(tmp_path, cfg):
    s = _abschuss(tmp_path, cfg, "vor_transaktion", n=3)
    ref = Path(cfg["paths"]["reference_dir"]) / ARTIKEL

    assert len(sorted(ref.glob("*.png"))) == 3, "alle Dateien im Ziel"
    assert list(s.info.path.glob("raw_*.png")) == [], "keine Quelle mehr in der Session"
    assert _refs(cfg) == [], "DB leer – genau der Zustand, den U1 garantiert"
    assert s.info.zustand == "umzug_unterbrochen"
    _keine_toten_pfade(cfg)
    _dateien_vollzaehlig(s, cfg)

    assert commit_enroll_session(cfg, s) == 3, "commit bucht nach"
    assert len(_refs(cfg)) == 3
    _keine_toten_pfade(cfg)


# ---------- Punkt 5: Transaktion durch, VOR dem Aufraeumen ----------

def test_abschuss_vor_dem_aufraeumen(tmp_path, cfg):
    s = _abschuss(tmp_path, cfg, "vor_backups", n=3)

    assert len(_refs(cfg)) == 3, "die Transaktion ist durch"
    assert s.info.zustand == "gebucht_aufraeumen_offen"
    assert s.info.path.is_dir(), "der Session-Ordner steht noch"
    _keine_toten_pfade(cfg)
    _dateien_vollzaehlig(s, cfg)

    assert commit_enroll_session(cfg, s) == 3
    assert len(_refs(cfg)) == 3, "NICHT doppelt gebucht"
    assert not s.info.path.exists(), "nur noch aufgeraeumt"
    _keine_toten_pfade(cfg)


# ---------- Die Grenze, ausdruecklich ----------

def test_sigkill_prueft_prozessabsturz_nicht_stromausfall():
    """Kein Test hier belegt, dass fsync gegen einen Stromausfall schuetzt.

    SIGKILL beendet den Prozess, der Page-Cache des Betriebssystems bleibt
    intakt – die Daten sind danach da, ob fsync lief oder nicht. Die
    Durabilitaets-Reihenfolge aus Design 3.7 ist damit ENTWORFEN, aber NICHT
    VERIFIZIERT. Dieser Test haelt das fest, damit die Luecke nicht mit der
    Zeit als geschlossen gilt.
    """
    from docodetect import pipeline as pl
    assert hasattr(pl, "_fsync_verzeichnis"), \
        "die Reihenfolge existiert im Code – ihre Wirkung gegen Stromausfall " \
        "ist hier NICHT geprueft (Design 7.2, Verifikationsliste Abschnitt 8)"
