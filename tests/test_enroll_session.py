"""Tests für die crash-sichere Einlern-Session (Schritte 2 und 3).

Design: docs/superpowers/specs/2026-08-05-crashsichere-einlern-session-design.md

Schritt 2 – die ABLAGE: Journal-Mechanik, N = distinkte i, Retake vernichtet
nichts, append_shot weist Fremdpfade ab, Fingerabdruck (gesetzt in begin,
geprüft in stage_frame), halbe Journalzeilen, Durabilitäts-Reihenfolge.

Schritt 3 – UMZUG UND BUCHUNG: Invariante U1 (alle Dateien vor der
Transaktion), die vier Fälle in beiden Richtungen, k<N als
Invariantenverletzung, Zustand 3, Lückenlosigkeit, Fingerabdruck vor der
Transaktion, und dass remeasure_session das Journal nicht anfasst.

Ohne Qt, ohne Kamera, alles gegen Temp-Verzeichnisse und Temp-DBs.
"""

import json
import os
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.calibration import Calibration  # noqa: E402
from docodetect.database import Article, Database  # noqa: E402
from docodetect.features import Features  # noqa: E402
from docodetect.pipeline import (EnrollSessionError, append_shot,  # noqa: E402
                                 begin_enroll_session, commit_enroll_session,
                                 discard_enroll_session, list_enroll_sessions,
                                 load_enroll_session, referenzbild_pfad,
                                 remeasure_session, stage_frame)

ARTIKEL = "T-270"


# ---------- Aufbau ----------

def make_cfg(tmp_path):
    """Alle Pfade unter tmp_path. enroll_sessions_dir und reference_dir liegen
    als Geschwister auf demselben Mount – die Voraussetzung des Umzugs."""
    return {
        "calibration": {"file": str(tmp_path / "calibration.json"),
                        "background_file": str(tmp_path / "background.png")},
        "paths": {"db_file": str(tmp_path / "db.sqlite3"),
                  "reference_dir": str(tmp_path / "reference"),
                  "enroll_sessions_dir": str(tmp_path / "enroll_sessions"),
                  "backups_dir": str(tmp_path / "backups")},
        "features": {"ring_zones": {"center_max": 0.60, "rim_min": 0.75},
                     "hs_hist_bins": [16, 8]},
        # Nur fuer remeasure_session: die Abweichungstoleranz ist
        # 0,1 * sigma_floor, bezogen ueber matcher._sigma_floor.
        "matching": {"sigma_floors": {"diameter_mm": 0.6, "circularity": 0.01,
                                      "solidity": 0.01}},
    }


def _optik_anlegen(cfg, fuellwert=200):
    """Kalibrierung + Hintergrund – der Optikzustand, den der Fingerabdruck
    hasht. Keine Kamera nötig."""
    Calibration(mm_per_px=0.2, camera_height_mm=300.0, image_width=1920,
                image_height=1080, marker_size_mm=50.0,
                created_unix=0.0).save(cfg["calibration"]["file"])
    bg = np.full((64, 96, 3), fuellwert, dtype=np.uint8)
    cv2.imwrite(cfg["calibration"]["background_file"], bg)


def _artikel_anlegen(cfg):
    db = Database(cfg)
    db.init_schema()
    db.create_article(Article(
        article_number=ARTIKEL, name="Teller flach 27", category="Teller",
        diameter_mm=270.0, width_mm=None, depth_mm=None, height_mm=25.0,
        color_desc=None, notes=None))
    db.close()


def _feats(d_mm=270.0):
    return Features(
        equiv_diameter_mm=d_mm, circle_diameter_mm=d_mm, area_mm2=57255.0,
        perimeter_mm=848.0, circularity=0.95, aspect_ratio=1.0,
        mean_hsv=[0.0, 0.0, 200.0], solidity=0.99, hu_moments=[1.0] * 7,
        lab_center=[80.0, 0.0, 0.0], lab_rim=[80.0, 0.0, 0.0],
        hs_hist_center=[1.0], hs_hist_rim=[1.0])


def _frame(wert=120):
    return np.full((64, 96, 3), wert, dtype=np.uint8)


@pytest.fixture
def cfg(tmp_path):
    c = make_cfg(tmp_path)
    _optik_anlegen(c)
    _artikel_anlegen(c)
    return c


# ---------- begin_enroll_session ----------

def test_begin_legt_ablage_vollstaendig_an(cfg):
    s = begin_enroll_session(cfg, ARTIKEL, target_shots=12)
    d = s.info.path
    assert (d / "session.json").is_file()
    assert (d / "journal.jsonl").is_file()
    assert (d / "optik" / "calibration.json").is_file()
    assert (d / "optik" / "background.png").is_file()
    assert not (d / "session.json.tmp").exists()   # temp+rename sauber beendet
    assert s.info.article_number == ARTIKEL
    assert s.info.target_shots == 12
    assert s.info.n_shots == 0
    assert s.info.zustand == "offen"


def test_begin_SETZT_den_fingerabdruck_korrekt(cfg):
    """begin PRUEFT nicht – es gibt keinen Vergleichswert. Geprueft wird, dass
    die drei Hashes korrekt in session.json landen."""
    import hashlib
    s = begin_enroll_session(cfg, ARTIKEL, target_shots=3)
    kopf = json.loads((s.info.path / "session.json").read_text(encoding="utf-8"))
    fp = kopf["fingerprint"]

    erwartet_cal = hashlib.sha256(
        Path(cfg["calibration"]["file"]).read_bytes()).hexdigest()
    erwartet_bg = hashlib.sha256(
        Path(cfg["calibration"]["background_file"]).read_bytes()).hexdigest()
    erwartet_feat = hashlib.sha256(
        json.dumps(cfg["features"], sort_keys=True).encode("utf-8")).hexdigest()

    assert fp["calibration_sha256"] == erwartet_cal
    assert fp["background_sha256"] == erwartet_bg
    assert fp["features_cfg_sha256"] == erwartet_feat
    assert fp["mm_per_px"] == 0.2
    assert fp["camera_height_mm"] == 300.0


def test_features_hash_ist_kanonisiert(cfg):
    """Eine Umformatierung ohne Wertaenderung (andere Schluesselreihenfolge)
    darf den Abdruck NICHT aendern – sonst schlaegt er bei jedem YAML-Umbau an."""
    s1 = begin_enroll_session(cfg, ARTIKEL, target_shots=1)
    cfg2 = dict(cfg)
    cfg2["features"] = {"hs_hist_bins": [16, 8],
                        "ring_zones": {"rim_min": 0.75, "center_max": 0.60}}
    s2 = begin_enroll_session(cfg2, ARTIKEL, target_shots=1)
    assert (s1.info.fingerprint["features_cfg_sha256"]
            == s2.info.fingerprint["features_cfg_sha256"])


def test_begin_unbekannter_artikel_wirft_keyerror(cfg):
    with pytest.raises(KeyError):
        begin_enroll_session(cfg, "GIBTSNICHT", target_shots=3)


def test_begin_bei_verschiedenen_mounts_wirft_mount(cfg, monkeypatch):
    """Echtes EXDEV ist auf einem Mount nicht herstellbar – geprueft wird der
    Zweig. Die Verifikation gegen zwei echte Dateisysteme steht als offener
    Punkt in der Verifikationsliste des Designs (Abschnitt 8, Zeile 3)."""
    # Beide Verzeichnisse muessen EXISTIEREN, sonst laeuft
    # _naechster_vorhandener auf den gemeinsamen Elternordner hoch und die
    # Pruefung vergleicht zweimal denselben Pfad – trivial gleicher Mount.
    Path(cfg["paths"]["enroll_sessions_dir"]).mkdir(parents=True, exist_ok=True)
    Path(cfg["paths"]["reference_dir"]).mkdir(parents=True, exist_ok=True)

    echt = Path.stat

    class _Stat:
        def __init__(self, s, dev):
            self._s, self.st_dev = s, dev

        def __getattr__(self, n):
            return getattr(self._s, n)

    def gefaelscht(self, *a, **kw):
        s = echt(self, *a, **kw)
        return _Stat(s, 999) if "enroll_sessions" in str(self) else s

    # Path.stat und NICHT os.stat: pathlib bindet os.stat beim Import, ein
    # Patch auf os.stat erreicht Path.stat daher nicht.
    monkeypatch.setattr(Path, "stat", gefaelscht)
    with pytest.raises(EnrollSessionError) as e:
        begin_enroll_session(cfg, ARTIKEL, target_shots=3)
    assert e.value.kind == "mount"


# ---------- stage_frame ----------

def test_stage_frame_schreibt_und_vergibt_laufende_nummern(cfg):
    s = begin_enroll_session(cfg, ARTIKEL, target_shots=3)
    p0 = stage_frame(cfg, s, _frame())
    p1 = stage_frame(cfg, s, _frame(130))
    assert p0.name == "raw_000.png" and p1.name == "raw_001.png"
    assert p0.stat().st_size > 0 and p1.stat().st_size > 0
    # Noch KEIN Shot: der Commit-Record ist die Journalzeile, nicht die Datei.
    assert load_enroll_session(cfg, s.info.path).info.n_shots == 0


def test_stage_frame_PRUEFT_den_fingerabdruck_und_behaelt_das_rohbild(cfg):
    """Die Pruefung steht NACH dem Schreiben: ein 4K-Frame wird nicht
    weggeworfen, nur weil zwischendurch jemand kalibriert hat. Dieselbe
    Behandlung wie bei SegmentationError."""
    s = begin_enroll_session(cfg, ARTIKEL, target_shots=3)
    Calibration(mm_per_px=0.25, camera_height_mm=300.0, image_width=1920,
                image_height=1080, marker_size_mm=50.0,
                created_unix=1.0).save(cfg["calibration"]["file"])

    vorher = set(p.name for p in s.info.path.glob("raw_*.png"))
    with pytest.raises(EnrollSessionError) as e:
        stage_frame(cfg, s, _frame())
    assert e.value.kind == "fingerprint"
    assert "calibration_sha256" in e.value.detail["abweichend"]

    nachher = set(p.name for p in s.info.path.glob("raw_*.png"))
    neu = nachher - vorher
    assert len(neu) == 1, "das Rohbild muss trotz Abweichung liegen bleiben"
    assert (s.info.path / neu.pop()).stat().st_size > 0
    assert load_enroll_session(cfg, s.info.path).info.n_shots == 0


def test_stage_frame_prueft_auch_den_features_block(cfg):
    s = begin_enroll_session(cfg, ARTIKEL, target_shots=3)
    cfg["features"]["hs_hist_bins"] = [32, 8]
    with pytest.raises(EnrollSessionError) as e:
        stage_frame(cfg, s, _frame())
    assert e.value.kind == "fingerprint"
    assert "features_cfg_sha256" in e.value.detail["abweichend"]


def test_geaenderter_hintergrund_schlaegt_an(cfg):
    s = begin_enroll_session(cfg, ARTIKEL, target_shots=3)
    cv2.imwrite(cfg["calibration"]["background_file"],
                np.full((64, 96, 3), 111, dtype=np.uint8))
    with pytest.raises(EnrollSessionError) as e:
        stage_frame(cfg, s, _frame())
    assert "background_sha256" in e.value.detail["abweichend"]


# ---------- append_shot ----------

def _shot(cfg, s, d_mm=270.0, i=None):
    p = stage_frame(cfg, s, _frame())
    return append_shot(cfg, s, p, _feats(d_mm), i=i)


def test_append_shot_zaehlt_hoch_und_haelt_reihenfolge(cfg):
    s = begin_enroll_session(cfg, ARTIKEL, target_shots=3)
    for d in (270.0, 271.0, 272.0):
        s = _shot(cfg, s, d)
    assert s.info.n_shots == 3
    assert [sh.i for sh in s.shots] == [0, 1, 2]
    assert [sh.d_mm for sh in s.shots] == [270.0, 271.0, 272.0]
    assert all(sh.raw_path.is_file() for sh in s.shots)


def test_N_ist_die_zahl_distinkter_i_nicht_der_zeilen(cfg):
    """Drei Zeilen mit i in {0,1,1} sind ZWEI Shots. Daran haengen
    'Aufnahme 9 von 12', die Thumbnail-Leiste und die Zahl der zu
    verschiebenden Dateien."""
    s = begin_enroll_session(cfg, ARTIKEL, target_shots=3)
    s = _shot(cfg, s, 270.0)
    s = _shot(cfg, s, 271.0)
    s = _shot(cfg, s, 999.0, i=1)          # Retake von i=1

    zeilen = (s.info.path / "journal.jsonl").read_text(
        encoding="utf-8").strip().splitlines()
    assert len(zeilen) == 3, "drei Journalzeilen"
    assert s.info.n_shots == 2, "aber zwei Shots"
    assert [sh.i for sh in s.shots] == [0, 1]
    assert s.shots[1].d_mm == 999.0, "es gilt die LETZTE Zeile je i"


def test_retake_vernichtet_die_alte_aufnahme_nicht(cfg):
    s = begin_enroll_session(cfg, ARTIKEL, target_shots=3)
    s = _shot(cfg, s, 270.0)
    alt = s.shots[0].raw_path
    s = _shot(cfg, s, 280.0, i=0)
    neu = s.shots[0].raw_path
    assert alt != neu
    assert alt.is_file(), "der verworfene Versuch bleibt als Material liegen"
    assert neu.is_file()


def test_append_shot_weist_optik_hintergrund_ab(cfg):
    """Der Fall, fuer den die Namenspruefung ZUSAETZLICH zur
    Enthaltensein-Pruefung existiert: die Datei liegt im Session-Ordner und
    existiert – ist aber kein Roh-Shot."""
    s = begin_enroll_session(cfg, ARTIKEL, target_shots=3)
    with pytest.raises(ValueError, match="stage_frame"):
        append_shot(cfg, s, s.info.path / "optik" / "background.png", _feats())


def test_append_shot_weist_fremdpfad_ausserhalb_ab(cfg, tmp_path):
    s = begin_enroll_session(cfg, ARTIKEL, target_shots=3)
    fremd = tmp_path / "raw_000.png"
    cv2.imwrite(str(fremd), _frame())
    with pytest.raises(ValueError, match="Session-Ordner"):
        append_shot(cfg, s, fremd, _feats())


def test_append_shot_weist_fehlende_oder_leere_datei_ab(cfg):
    s = begin_enroll_session(cfg, ARTIKEL, target_shots=3)
    fehlt = s.info.path / "raw_042.png"
    with pytest.raises(ValueError, match="fehlt oder ist leer"):
        append_shot(cfg, s, fehlt, _feats())
    fehlt.write_bytes(b"")
    with pytest.raises(ValueError, match="fehlt oder ist leer"):
        append_shot(cfg, s, fehlt, _feats())


def test_journal_ist_append_only(cfg):
    """Jede Aufnahme haengt genau eine Zeile an; bestehende Zeilen bleiben
    Byte-fuer-Byte unveraendert."""
    s = begin_enroll_session(cfg, ARTIKEL, target_shots=3)
    j = s.info.path / "journal.jsonl"
    s = _shot(cfg, s, 270.0)
    nach_eins = j.read_bytes()
    s = _shot(cfg, s, 271.0)
    nach_zwei = j.read_bytes()
    assert nach_zwei.startswith(nach_eins), "Praefix unveraendert = append-only"
    assert nach_zwei.count(b"\n") == 2


# ---------- Journal lesen: halbe Zeile vs. kaputte Zeile ----------

def test_abgeschnittene_letzte_zeile_wird_still_verworfen(cfg):
    """Der abgeschnittene Schreibvorgang eines Absturzes. Zeile n-1 bleibt
    davon unberuehrt – genau die Eigenschaft, die ein neu geschriebener
    JSON-Block nicht haette."""
    s = begin_enroll_session(cfg, ARTIKEL, target_shots=3)
    s = _shot(cfg, s, 270.0)
    s = _shot(cfg, s, 271.0)
    j = s.info.path / "journal.jsonl"
    roh = j.read_text(encoding="utf-8")
    j.write_text(roh + '{"i":2,"file":"raw_002.png","d_m', encoding="utf-8")

    wieder = load_enroll_session(cfg, s.info.path)
    assert wieder.info.n_shots == 2
    assert [sh.d_mm for sh in wieder.shots] == [270.0, 271.0]


def test_kaputte_zeile_in_der_mitte_wirft_valueerror(cfg):
    """Dort ist etwas anderes passiert als ein Abbruch am Ende – das wird
    gemeldet, nicht uebersprungen."""
    s = begin_enroll_session(cfg, ARTIKEL, target_shots=3)
    s = _shot(cfg, s, 270.0)
    s = _shot(cfg, s, 271.0)
    j = s.info.path / "journal.jsonl"
    zeilen = j.read_text(encoding="utf-8").splitlines()
    zeilen[0] = '{"i":0,"file":"kaputt'
    j.write_text("\n".join(zeilen) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="unlesbar"):
        load_enroll_session(cfg, s.info.path)


def test_leeres_journal_ergibt_null_shots(cfg):
    s = begin_enroll_session(cfg, ARTIKEL, target_shots=3)
    assert load_enroll_session(cfg, s.info.path).info.n_shots == 0


def test_load_ohne_session_json_wirft_filenotfound(cfg, tmp_path):
    with pytest.raises(FileNotFoundError):
        load_enroll_session(cfg, tmp_path / "gibtsnicht")


def test_fingerabdruck_gegen_realistisch_grosse_hintergrunddatei(tmp_path):
    """Die uebrigen Tests hashen eine 64x96-Attrappe (~240 B). Ein Hash ueber
    240 B sagt nichts darueber, wie der Abdruck mit echten Dateien umgeht.

    Hier laeuft er gegen ein echtes 4K-Bild von mehreren MB. Die exakte Groesse
    ist unerheblich und trifft die echte calibration/background.png (1,26 MB
    gemessen) NICHT — synthetisches Rauschen komprimiert deutlich schlechter
    als eine Box-Aufnahme, hier landen wir bei rund 5 MB. Die Aussage des Tests
    ist "echte Datei statt Attrappe", nicht "exakt so gross wie im Betrieb".

    BEWUSST erzeugt statt aus calibration/ gelesen: calibration/*.png ist
    gitignored (.gitignore:7, versioniert ist nur .gitkeep). Ein Test gegen die
    echte Datei wuerde im frischen Clone, im Worktree und auf der Windows-Box
    vor dem ersten capture-background fehlschlagen — und CLAUDE.md untersagt
    Tests ohnehin den Zugriff auf calibration/.
    """
    import hashlib

    cfg = make_cfg(tmp_path)
    _optik_anlegen(cfg)
    _artikel_anlegen(cfg)

    # Verlauf + Rauschen + Weichzeichner: raeumlich korreliert wie ein Foto,
    # statt als reines Pixelrauschen auf zweistellige MB aufzulaufen.
    rng = np.random.default_rng(7)
    y = np.linspace(60, 200, 2160, dtype=np.float32)[:, None]
    gross = np.repeat(y, 3840, axis=1)[:, :, None].repeat(3, axis=2)
    gross = np.clip(gross + rng.integers(-25, 26, gross.shape), 0, 255)
    gross = cv2.GaussianBlur(gross.astype(np.uint8), (15, 15), 0)
    cv2.imwrite(cfg["calibration"]["background_file"], gross)

    groesse = Path(cfg["calibration"]["background_file"]).stat().st_size
    assert groesse > 1_000_000, f"Testdatei zu klein fuer die Aussage: {groesse} B"

    s = begin_enroll_session(cfg, ARTIKEL, target_shots=3)
    erwartet = hashlib.sha256(
        Path(cfg["calibration"]["background_file"]).read_bytes()).hexdigest()
    assert s.info.fingerprint["background_sha256"] == erwartet

    # Und er schlaegt auch bei einer grossen Datei auf eine Aenderung an –
    # ein Hash, der nur bei Attrappen greift, waere wertlos.
    gross[0, 0] = [1, 2, 3]
    cv2.imwrite(cfg["calibration"]["background_file"], gross)
    with pytest.raises(EnrollSessionError) as e:
        stage_frame(cfg, s, _frame())
    assert "background_sha256" in e.value.detail["abweichend"]


# ---------- Durabilitaets-Reihenfolge ----------

def test_png_liegt_auf_platte_BEVOR_die_journalzeile_entsteht(cfg):
    """Die Regel selbst, nicht ihre Absicherung.

    Die fsync-Reihenfolge (naechster Test) belegt, dass beide durabel gemacht
    werden. Hier wird geprueft, was inhaltlich gilt: nach stage_frame liegt das
    vollstaendige PNG auf der Platte und das Journal ist noch UNVERAENDERT;
    erst append_shot erzeugt die Zeile, und das PNG bleibt dabei Byte-fuer-Byte
    gleich. Eine durable Journalzeile ueber einem noch nicht geschriebenen PNG
    waere schlimmer als gar keine Zeile — die Leseseite haelt sie fuer gueltig,
    weil sie sauber parst.
    """
    s = begin_enroll_session(cfg, ARTIKEL, target_shots=3)
    journal = s.info.path / "journal.jsonl"
    assert journal.read_bytes() == b"", "frische Session: Journal leer"

    p = stage_frame(cfg, s, _frame())
    assert p.is_file() and p.stat().st_size > 0, "PNG liegt vollstaendig"
    png_nach_stage = p.read_bytes()
    assert journal.read_bytes() == b"", \
        "nach stage_frame darf noch KEINE Journalzeile existieren"

    append_shot(cfg, s, p, _feats())
    zeilen = journal.read_text(encoding="utf-8").strip().splitlines()
    assert len(zeilen) == 1, "erst append_shot erzeugt die Zeile"
    assert json.loads(zeilen[0])["file"] == p.name, "sie zeigt auf dieses PNG"
    assert p.read_bytes() == png_nach_stage, "das PNG wurde dabei nicht angefasst"



def test_durabilitaet_png_liegt_vor_der_journalzeile(cfg, monkeypatch):
    """Reihenfolge aus Design 3.7: PNG schreiben -> fsync(Datei) ->
    fsync(Verzeichnis) -> Journalzeile -> fsync. Eine durable Journalzeile
    ueber einem nicht-durablen PNG waere schlimmer als gar keine Zeile: die
    Leseseite haelt sie fuer gueltig, weil sie sauber parst.

    Geprueft wird die REIHENFOLGE der Aufrufe. Dass fsync gegen einen
    STROMAUSFALL schuetzt, ist damit NICHT gezeigt – ein SIGKILL laesst den
    Page-Cache intakt. Diese Zeile bleibt unverifiziert (Design 7.2).
    """
    import os as _os
    from docodetect import pipeline as pl

    ablauf = []
    echt_fsync = _os.fsync

    def fsync_spion(fd):
        ablauf.append("fsync")
        return echt_fsync(fd)

    echt_dir = pl._fsync_verzeichnis

    def dir_spion(p):
        ablauf.append("fsync_dir")
        return echt_dir(p)

    monkeypatch.setattr(_os, "fsync", fsync_spion)
    monkeypatch.setattr(pl, "_fsync_verzeichnis", dir_spion)

    s = begin_enroll_session(cfg, ARTIKEL, target_shots=3)
    ablauf.clear()
    p = stage_frame(cfg, s, _frame())
    # Der dritte Eintrag ist der os.fsync INNERHALB von _fsync_verzeichnis –
    # der Verzeichnis-fsync ist selbst ein fsync. Massgeblich ist: der
    # PNG-Inhalt wird zuerst durabel, dann der Verzeichniseintrag.
    assert ablauf == ["fsync", "fsync_dir", "fsync"], \
        "PNG-fsync vor Verzeichnis-fsync, beides VOR der Journalzeile"

    ablauf.clear()
    append_shot(cfg, s, p, _feats())
    assert ablauf == ["fsync"], \
        "Journalzeile wird gefsynct; kein weiterer Verzeichnis-fsync noetig"


def test_fsync_verzeichnis_ist_auf_windows_ein_noop(monkeypatch, tmp_path):
    """POSIX-only: ein Verzeichnis laesst sich auf Windows nicht als
    Dateideskriptor oeffnen. Der uebersprungene Zweig ist auf dem Mac nicht
    erreichbar – hier wird nur belegt, DASS uebersprungen wird."""
    import os as _os
    from docodetect import pipeline as pl

    monkeypatch.setattr(_os, "name", "nt")
    gerufen = []
    monkeypatch.setattr(_os, "open",
                        lambda *a, **kw: gerufen.append(a) or 0)
    pl._fsync_verzeichnis(tmp_path)
    assert gerufen == [], "auf Windows wird kein Verzeichnis geoeffnet"


# ---------- Auflisten ----------

def test_list_gibt_alle_sessions_neueste_zuerst(cfg):
    a = begin_enroll_session(cfg, ARTIKEL, target_shots=3)
    b = begin_enroll_session(cfg, ARTIKEL, target_shots=5)
    alle = list_enroll_sessions(cfg)
    assert len(alle) == 2
    assert alle[0].ts >= alle[1].ts
    assert {i.ts for i in alle} == {a.info.ts, b.info.ts}


def test_mehrere_sessions_je_artikel_sind_zulaessig(cfg):
    """Zwei ts-Ordner unter demselben Artikel, etwa nach zwei Abstuerzen.
    Beide werden gefuehrt; das Fortsetzen adressiert spaeter eine KONKRETE
    Session, nie 'die fuer diesen Artikel'."""
    a = begin_enroll_session(cfg, ARTIKEL, target_shots=3)
    b = begin_enroll_session(cfg, ARTIKEL, target_shots=3)
    assert a.info.path != b.info.path
    assert len(list_enroll_sessions(cfg, article_number=ARTIKEL)) == 2


def test_list_filtert_nach_artikel(cfg):
    db = Database(cfg)
    db.create_article(Article(
        article_number="T-999", name="Zweiter", category=None,
        diameter_mm=200.0, width_mm=None, depth_mm=None, height_mm=10.0,
        color_desc=None, notes=None))
    db.close()
    begin_enroll_session(cfg, ARTIKEL, target_shots=3)
    begin_enroll_session(cfg, "T-999", target_shots=3)
    assert len(list_enroll_sessions(cfg)) == 2
    assert [i.article_number
            for i in list_enroll_sessions(cfg, article_number="T-999")] == ["T-999"]


def test_list_ohne_wurzelverzeichnis_ist_leer(tmp_path):
    cfg = make_cfg(tmp_path)
    assert list_enroll_sessions(cfg) == []


def test_fingerprint_ok_kippt_bei_neukalibrierung(cfg):
    s = begin_enroll_session(cfg, ARTIKEL, target_shots=3)
    assert list_enroll_sessions(cfg)[0].fingerprint_ok is True
    Calibration(mm_per_px=0.25, camera_height_mm=300.0, image_width=1920,
                image_height=1080, marker_size_mm=50.0,
                created_unix=1.0).save(cfg["calibration"]["file"])
    assert list_enroll_sessions(cfg)[0].fingerprint_ok is False
    assert s.info.path.is_dir(), "die Session bleibt bestehen, nur nicht fortsetzbar"


# ============================================================================
# Schritt 3: Umzug, Buchen, Verwerfen, remeasure_session
# ============================================================================

def _sitzung(cfg, n=3, start=270.0):
    """Session mit n vermessenen Shots."""
    s = begin_enroll_session(cfg, ARTIKEL, target_shots=n)
    for k in range(n):
        s = append_shot(cfg, s, stage_frame(cfg, s, _frame(100 + k)),
                        _feats(start + k))
    return s


def _ziel(cfg, s, i):
    return (Path(cfg["paths"]["reference_dir"]) / ARTIKEL
            / f"{s.info.ts}_{i:02d}.png")


def _refs(cfg):
    db = Database(cfg)
    try:
        return db.references_with_meta(ARTIKEL)
    finally:
        db.close()


# ---------- Buchen: der Normalfall ----------

def test_commit_verschiebt_und_bucht(cfg):
    s = _sitzung(cfg, 3)
    quellen = [sh.raw_path for sh in s.shots]
    assert commit_enroll_session(cfg, s) == 3

    for i in range(3):
        assert _ziel(cfg, s, i).is_file(), f"Shot {i} liegt im reference_dir"
    assert not any(q.exists() for q in quellen), "die Quellen sind umgezogen"

    meta = _refs(cfg)
    # Gebucht wird der reference_dir-RELATIVE POSIX-Pfad (R4) ...
    assert [p for p, _ in meta] == [f"{ARTIKEL}/{s.info.ts}_{i:02d}.png"
                                    for i in range(3)]
    for p, _ in meta:
        assert "\\" not in p and not Path(p).is_absolute()
    # ... und die Fassade (R9) loest ihn auf die umgezogene Datei auf.
    assert [referenzbild_pfad(cfg, p) for p, _ in meta] == \
        [_ziel(cfg, s, i) for i in range(3)]
    assert not s.info.path.exists(), "Session-Ordner ist weggeraeumt"


def test_commit_raeumt_nach_backups_statt_zu_loeschen(cfg):
    s = _sitzung(cfg, 2)
    commit_enroll_session(cfg, s)
    treffer = list(Path(cfg["paths"]["backups_dir"]).glob(
        f"*-enroll-sessions/{ARTIKEL}-{s.info.ts}"))
    assert len(treffer) == 1, "Session-Rest liegt unter backups/"
    assert (treffer[0] / "journal.jsonl").is_file()
    assert (treffer[0] / "session.json").is_file()


def test_commit_bucht_die_journalwerte(cfg):
    s = _sitzung(cfg, 2, start=265.5)
    commit_enroll_session(cfg, s)
    gemessen = [f.circle_diameter_mm for _, f in _refs(cfg)]
    assert gemessen == [265.5, 266.5]


# ---------- U1: Dateien vor der Transaktion ----------

def test_U1_dateien_liegen_im_ziel_bevor_die_transaktion_laeuft(cfg, monkeypatch):
    """Bricht die Transaktion ab, muessen ALLE Dateien im Ziel liegen und die
    DB LEER sein – das ist der wiederaufnehmbare Zustand. Die umgekehrte
    Reihenfolge erzeugte Zeilen mit toten image_path."""
    from docodetect.database import Database as _DB

    def boom(self, nr, items):
        raise RuntimeError("Transaktion abgebrochen")

    s = _sitzung(cfg, 3)
    monkeypatch.setattr(_DB, "add_references", boom)
    with pytest.raises(RuntimeError):
        commit_enroll_session(cfg, s)

    for i in range(3):
        assert _ziel(cfg, s, i).is_file(), "alle Dateien sind umgezogen"
    assert _refs(cfg) == [], "die DB ist leer"
    assert s.info.path.is_dir(), "die Session lebt und ist wiederaufnehmbar"

    monkeypatch.undo()
    assert commit_enroll_session(cfg, s) == 3, "zweites commit vollendet"
    assert len(_refs(cfg)) == 3


def test_zustand_nach_abgebrochener_transaktion(cfg, monkeypatch):
    from docodetect.database import Database as _DB
    s = _sitzung(cfg, 2)
    monkeypatch.setattr(_DB, "add_references",
                        lambda self, nr, items: (_ for _ in ()).throw(RuntimeError()))
    with pytest.raises(RuntimeError):
        commit_enroll_session(cfg, s)
    assert load_enroll_session(cfg, s.info.path).info.zustand == "umzug_unterbrochen"


# ---------- Vier Faelle vorwaerts ----------

def test_umzug_ist_idempotent_teilweise_verschoben(cfg):
    """Fall 'Quelle weg, Ziel da' -> ueberspringen. Der Abbruchpunkt mitten im
    Umzug ist damit wiederaufnehmbar."""
    s = _sitzung(cfg, 3)
    ziel_dir = Path(cfg["paths"]["reference_dir"]) / ARTIKEL
    ziel_dir.mkdir(parents=True, exist_ok=True)
    import os as _os
    _os.rename(str(s.shots[0].raw_path), str(_ziel(cfg, s, 0)))   # Shot 0 vorab

    assert commit_enroll_session(cfg, s) == 3
    assert len(_refs(cfg)) == 3


def test_fremdkollision_bricht_ab(cfg):
    """Fall 'Quelle da UND Ziel da' – das Ziel traegt die Session-ts, kann also
    nicht von einer anderen Session desselben Artikels stammen."""
    s = _sitzung(cfg, 2)
    ziel_dir = Path(cfg["paths"]["reference_dir"]) / ARTIKEL
    ziel_dir.mkdir(parents=True, exist_ok=True)
    _ziel(cfg, s, 0).write_bytes(b"fremd")

    with pytest.raises(EnrollSessionError) as e:
        commit_enroll_session(cfg, s)
    assert e.value.kind == "kollision"
    assert _refs(cfg) == [], "nichts gebucht"
    assert _ziel(cfg, s, 0).read_bytes() == b"fremd", "fremde Datei unangetastet"


def test_verschwundene_datei_bricht_ab(cfg):
    """Fall 'Quelle weg UND Ziel fehlt'."""
    s = _sitzung(cfg, 2)
    s.shots[1].raw_path.unlink()
    with pytest.raises(EnrollSessionError) as e:
        commit_enroll_session(cfg, s)
    assert e.value.kind == "datei_fehlt"


# ---------- k<N-Assertion und Zustand 3 ----------

def test_k_kleiner_N_ist_eine_invariantenverletzung(cfg):
    """Der Zustand DARF nicht entstehen – kein Angebot, nur Befund, und keine
    Datei wird dabei bewegt."""
    s = _sitzung(cfg, 3)
    db = Database(cfg)
    try:                                     # k=1 von 3 kuenstlich herstellen
        db.add_reference(ARTIKEL, s.shots[0].features, str(_ziel(cfg, s, 0)))
    finally:
        db.close()

    quellen_vorher = [q.exists() for q in (sh.raw_path for sh in s.shots)]
    with pytest.raises(EnrollSessionError) as e:
        commit_enroll_session(cfg, s)
    assert e.value.kind == "invariante"
    assert e.value.detail["erwartet_n"] == 3
    assert len(e.value.detail["gefunden"]) == 1
    assert [q.exists() for q in (sh.raw_path for sh in s.shots)] == quellen_vorher


def test_zustand3_raeumt_nur_auf_und_bucht_nicht_doppelt(cfg):
    """Absturz zwischen Transaktion und Aufraeumen: alle Zeilen da, alle
    Dateien im Ziel, Session-Ordner steht noch."""
    s = _sitzung(cfg, 2)
    ziele = [_ziel(cfg, s, i) for i in range(2)]
    ziele[0].parent.mkdir(parents=True, exist_ok=True)
    import os as _os
    for sh, z in zip(s.shots, ziele):
        _os.rename(str(sh.raw_path), str(z))
    db = Database(cfg)
    try:
        db.add_references(ARTIKEL, [(sh.features, str(z))
                                    for sh, z in zip(s.shots, ziele)])
    finally:
        db.close()

    assert load_enroll_session(cfg, s.info.path).info.zustand \
        == "gebucht_aufraeumen_offen"
    assert commit_enroll_session(cfg, s) == 2
    assert len(_refs(cfg)) == 2, "nicht doppelt gebucht"
    assert not s.info.path.exists()


# ---------- Lueckenlosigkeit ----------

def test_commit_verweigert_bei_luecke(cfg):
    s = _sitzung(cfg, 2)
    s = append_shot(cfg, s, stage_frame(cfg, s, _frame()), _feats(273.0), i=5)
    with pytest.raises(EnrollSessionError) as e:
        commit_enroll_session(cfg, s)
    assert e.value.kind == "luecke"
    assert _refs(cfg) == []


def test_commit_verweigert_bei_null_shots(cfg):
    s = begin_enroll_session(cfg, ARTIKEL, target_shots=3)
    with pytest.raises(EnrollSessionError) as e:
        commit_enroll_session(cfg, s)
    assert e.value.kind == "luecke"


# ---------- Fingerabdruck vor der Transaktion ----------

def test_commit_verweigert_bei_geaenderter_optik(cfg):
    """Der kritische Moment: hier entsteht sigma_enroll. Wuerde unter X
    aufgenommen und unter X' gebucht, laege in reference_stats ein
    sigma_enroll aus X, gegen das kuenftig unter X' gemessen wird."""
    s = _sitzung(cfg, 2)
    Calibration(mm_per_px=0.25, camera_height_mm=300.0, image_width=1920,
                image_height=1080, marker_size_mm=50.0,
                created_unix=1.0).save(cfg["calibration"]["file"])
    with pytest.raises(EnrollSessionError) as e:
        commit_enroll_session(cfg, s)
    assert e.value.kind == "fingerprint"
    assert _refs(cfg) == [], "nichts gebucht"
    assert all(sh.raw_path.exists() for sh in s.shots), "keine Datei bewegt"
    assert "optik_kopie" in e.value.detail, "der Ausweg wird genannt"


# ---------- Verwerfen ----------

def test_discard_schiebt_nach_verworfen_ohne_zu_loeschen(cfg):
    s = _sitzung(cfg, 2)
    dateien = [sh.raw_path.name for sh in s.shots]
    ziel = discard_enroll_session(cfg, s)
    assert ziel.is_dir()
    assert not s.info.path.exists()
    for n in dateien:
        assert (ziel / n).is_file(), f"{n} ist erhalten"
    assert (ziel / "info.json").is_file()
    assert (ziel / "journal.jsonl").is_file()
    assert _refs(cfg) == [], "kein DB-Eintrag"


def test_discard_holt_bereits_verschobene_dateien_zurueck(cfg):
    """Rueckumzug, Fall 'Quelle weg, Ziel da, keine DB-Zeile'. Ohne ihn waere
    ein abgebrochener Umzug eine Sackgasse."""
    s = _sitzung(cfg, 3)
    ziel_dir = Path(cfg["paths"]["reference_dir"]) / ARTIKEL
    ziel_dir.mkdir(parents=True, exist_ok=True)
    import os as _os
    _os.rename(str(s.shots[0].raw_path), str(_ziel(cfg, s, 0)))

    ziel = discard_enroll_session(cfg, s)
    assert not _ziel(cfg, s, 0).exists(), "aus reference_dir zurueckgeholt"
    assert (ziel / s.shots[0].raw_path.name).is_file()
    protokoll = json.loads((ziel / "info.json").read_text())["rueckumzug"]
    assert protokoll[0]["aktion"] == "zurueckgeholt"


def test_discard_laesst_gebuchte_referenz_in_ruhe(cfg):
    """Rueckumzug, Fall 'Quelle weg, Ziel da, DB-Zeile vorhanden'. Die
    DB-Schranke ist die entscheidende – sie verhindert, dass der Rueckumzug
    eine echte Referenz aus reference_dir zieht."""
    s = _sitzung(cfg, 2)
    ziel_dir = Path(cfg["paths"]["reference_dir"]) / ARTIKEL
    ziel_dir.mkdir(parents=True, exist_ok=True)
    import os as _os
    _os.rename(str(s.shots[0].raw_path), str(_ziel(cfg, s, 0)))
    db = Database(cfg)
    try:
        db.add_reference(ARTIKEL, s.shots[0].features, str(_ziel(cfg, s, 0)))
    finally:
        db.close()

    ziel = discard_enroll_session(cfg, s)
    assert _ziel(cfg, s, 0).is_file(), "gebuchte Referenz bleibt liegen"
    protokoll = json.loads((ziel / "info.json").read_text())["rueckumzug"]
    assert protokoll[0]["aktion"] == "gebucht_nicht_angefasst"


def test_discard_meldet_verlorene_datei_statt_zu_scheitern(cfg):
    s = _sitzung(cfg, 2)
    s.shots[1].raw_path.unlink()
    ziel = discard_enroll_session(cfg, s)
    protokoll = json.loads((ziel / "info.json").read_text())["rueckumzug"]
    assert protokoll[1]["aktion"] == "VERLOREN"


# ---------- relative Buchung: die beiden Inversionen an _zeilen_je_pfad ----


def test_zweiter_commit_nach_zustand3_bucht_nicht_doppelt(cfg, monkeypatch):
    """Inversion 1: Absturz zwischen Transaktion und Aufraeumen (Zustand 3),
    dann Wiederaufnahme. Die RELATIV gespeicherten Zeilen muessen als
    'vollstaendig' erkannt werden — kippte der Vergleich (relativ vs.
    absoluter Zielpfad), buchte der zweite commit alle N Zeilen DOPPELT und
    verfaelschte reference_stats."""
    from docodetect import pipeline as pl
    s = _sitzung(cfg, 2)
    monkeypatch.setattr(pl, "_raeume_nach_backups", lambda c, sess: None)
    assert commit_enroll_session(cfg, s) == 2
    monkeypatch.undo()
    assert s.info.path.exists(), "Zustand 3: Aufraeumen steht noch aus"
    assert len(_refs(cfg)) == 2

    assert commit_enroll_session(cfg, s) == 2      # Wiederaufnahme
    assert len(_refs(cfg)) == 2, "KEINE Doppelbuchung"
    assert not s.info.path.exists(), "jetzt aufgeraeumt"


def test_discard_nach_zustand3_zieht_keine_gebuchten_referenzen(cfg,
                                                                monkeypatch):
    """Inversion 2: dieselbe Lage, aber VERWERFEN statt fortsetzen. Die
    DB-Schranke muss die relativ gespeicherten Zeilen erkennen — sonst zoege
    der Rueckumzug echte (gebuchte) Referenzen aus reference_dir. Das
    Gegenstueck mit ABSOLUTER Altbestands-Zeile ist
    test_discard_laesst_gebuchte_referenz_in_ruhe."""
    from docodetect import pipeline as pl
    s = _sitzung(cfg, 2)
    monkeypatch.setattr(pl, "_raeume_nach_backups", lambda c, sess: None)
    commit_enroll_session(cfg, s)
    monkeypatch.undo()

    ziel = discard_enroll_session(cfg, s)
    for i in range(2):
        assert _ziel(cfg, s, i).is_file(), "gebuchte Referenz bleibt liegen"
    assert len(_refs(cfg)) == 2, "DB-Zeilen unangetastet"
    protokoll = json.loads((ziel / "info.json").read_text())["rueckumzug"]
    assert {e["aktion"] for e in protokoll} == {"gebucht_nicht_angefasst"}


# ---------- referenzbild_pfad (R9-Fassade) ----------


def test_referenzbild_pfad_fassade(cfg):
    """R9/R6: relative Neuform, absoluter Altbestand, None, fehlende Datei.
    Nie ein Pfad auf eine nicht vorhandene Datei."""
    ref = Path(cfg["paths"]["reference_dir"])
    (ref / ARTIKEL).mkdir(parents=True)
    datei = ref / ARTIKEL / "123_00.png"
    cv2.imwrite(str(datei), _frame(1))

    assert referenzbild_pfad(cfg, None) is None
    assert referenzbild_pfad(cfg, "") is None
    # relativ (Neuform, POSIX) -> gegen das aktive reference_dir
    assert referenzbild_pfad(cfg, f"{ARTIKEL}/123_00.png") == datei
    # absolut (Altbestand) -> unveraendert benutzt
    assert referenzbild_pfad(cfg, str(datei)) == datei
    # fehlende Datei -> None statt Pfad ins Leere, in beiden Formen
    assert referenzbild_pfad(cfg, f"{ARTIKEL}/999_00.png") is None
    assert referenzbild_pfad(cfg, str(ref / ARTIKEL / "999_00.png")) is None


def test_add_reference_verweigert_backslash_in_relativer_form(cfg):
    """R4-Wache: eine Separator-Regression (Path-Join statt f-String in
    einem Schreiber) entstuende nur auf Windows und waere auf dem Mac in
    keiner Suite sichtbar — deshalb weist die DB-Schicht relative Pfade mit
    Backslash auf JEDER Plattform zurueck. Absolute Pfade bleiben erlaubt."""
    db = Database(cfg)
    try:
        with pytest.raises(ValueError, match="POSIX"):
            db.add_reference(ARTIKEL, _feats(270.0), "T-270\\123_00.png")
        with pytest.raises(ValueError, match="POSIX"):
            db.add_references(ARTIKEL, [(_feats(270.0), "T-270\\1_00.png")])
        assert _refs(cfg) == [], "nichts halb geschrieben"
    finally:
        db.close()


# ---------- Schreibbarkeits-Probe (Fail-fast in begin) ----------


def test_begin_scheitert_frueh_wenn_reference_dir_eine_datei_ist(cfg):
    """Fail-fast-Ersatz fuer den entfallenen Root-Anker-Abbruch: steht an der
    reference_dir-Position eine DATEI, scheitert begin_enroll_session sofort
    (kind='schreibprobe') — nicht erst der Umzug nach der letzten Aufnahme.
    Und: keine Session als Nebenwirkung."""
    Path(cfg["paths"]["reference_dir"]).write_bytes(b"im Weg")
    with pytest.raises(EnrollSessionError) as e:
        begin_enroll_session(cfg, ARTIKEL, target_shots=2)
    assert e.value.kind == "schreibprobe"
    assert not (Path(cfg["paths"]["enroll_sessions_dir"]) / ARTIKEL).exists()


@pytest.mark.skipif(
    sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="chmod-Schreibsperre greift nur auf POSIX ohne root")
def test_begin_scheitert_frueh_bei_unbeschreibbarem_reference_dir(cfg):
    ref = Path(cfg["paths"]["reference_dir"])
    ref.mkdir(parents=True)
    ref.chmod(0o500)
    try:
        with pytest.raises(EnrollSessionError) as e:
            begin_enroll_session(cfg, ARTIKEL, target_shots=2)
        assert e.value.kind == "schreibprobe"
    finally:
        ref.chmod(0o700)


@pytest.mark.skipif(
    sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="chmod-Schreibsperre greift nur auf POSIX ohne root")
def test_begin_scheitert_frueh_bei_unbeschreibbarem_artikelordner(cfg):
    """reference_dir-Wurzel beschreibbar, aber der BESTEHENDE Artikelordner
    (das tatsaechliche Buchungsziel) nicht: die Probe muss den Artikelordner
    treffen — eine Wurzel-Probe liefe daran vorbei, und der Fehler fiele
    erst beim Umzug nach der letzten Aufnahme."""
    artikel_dir = Path(cfg["paths"]["reference_dir"]) / ARTIKEL
    artikel_dir.mkdir(parents=True)
    artikel_dir.chmod(0o500)
    try:
        with pytest.raises(EnrollSessionError) as e:
            begin_enroll_session(cfg, ARTIKEL, target_shots=2)
        assert e.value.kind == "schreibprobe"
    finally:
        artikel_dir.chmod(0o700)


# ---------- remeasure_session ----------

def _remeasure_mit(monkeypatch, feats_je_aufruf):
    """measure_shot ersetzen: die Testframes sind flach und nicht
    segmentierbar. Geprueft wird hier die Abweichungs- und Schreiblogik von
    remeasure_session, NICHT die Messung selbst – die ist derselbe Aufruf, den
    der Dialog heute schon macht und der anderswo abgedeckt ist."""
    from docodetect import pipeline as pl
    folge = iter(feats_je_aufruf)
    monkeypatch.setattr(pl, "measure_shot",
                        lambda bild, c: (next(folge), None))


def test_remeasure_faesst_das_journal_NICHT_an(cfg, monkeypatch):
    """Fortsetzen ist der Rettungspfad. Eine Operation, die dort schreibt, kann
    den Zustand beschaedigen, den sie retten soll."""
    s = _sitzung(cfg, 2, start=270.0)
    journal = s.info.path / "journal.jsonl"
    vorher = journal.read_bytes()

    _remeasure_mit(monkeypatch, [_feats(299.0), _feats(298.0)])
    neu, abw = remeasure_session(cfg, s)

    assert journal.read_bytes() == vorher, "Journal Byte-fuer-Byte unveraendert"
    assert [sh.d_mm for sh in neu.shots] == [299.0, 298.0], "neue Werte nur im Rueckgabewert"
    assert len(abw) >= 2, "die Abweichung wird gemeldet"


def test_commit_nach_remeasure_bucht_die_journalwerte(cfg, monkeypatch):
    """Der Kern der Entscheidung: gebucht wird, was im Journal steht."""
    s = _sitzung(cfg, 2, start=270.0)
    _remeasure_mit(monkeypatch, [_feats(299.0), _feats(298.0)])
    remeasure_session(cfg, s)
    monkeypatch.undo()

    commit_enroll_session(cfg, s)
    assert [f.circle_diameter_mm for _, f in _refs(cfg)] == [270.0, 271.0]


def test_remeasure_abweichung_ist_warnung_kein_abbruch(cfg, monkeypatch):
    s = _sitzung(cfg, 2, start=270.0)
    _remeasure_mit(monkeypatch, [_feats(270.0), _feats(280.0)])
    neu, abw = remeasure_session(cfg, s)      # wirft NICHT
    betroffen = {a["i"] for a in abw}
    assert betroffen == {1}, "nur der abweichende Shot wird gemeldet"
    d = [a for a in abw if a["merkmal"] == "diameter_mm"][0]
    assert d["journal"] == 271.0 and d["neu"] == 280.0
    assert d["toleranz"] == pytest.approx(0.06), "0,1 * sigma_floor 0,6"


def test_remeasure_ohne_abweichung_meldet_nichts(cfg, monkeypatch):
    s = _sitzung(cfg, 2, start=270.0)
    _remeasure_mit(monkeypatch, [_feats(270.0), _feats(271.0)])
    _neu, abw = remeasure_session(cfg, s)
    assert abw == []


def test_remeasure_verweigert_bei_geaenderter_optik(cfg, monkeypatch):
    s = _sitzung(cfg, 2)
    Calibration(mm_per_px=0.25, camera_height_mm=300.0, image_width=1920,
                image_height=1080, marker_size_mm=50.0,
                created_unix=1.0).save(cfg["calibration"]["file"])
    _remeasure_mit(monkeypatch, [_feats(270.0), _feats(271.0)])
    with pytest.raises(EnrollSessionError) as e:
        remeasure_session(cfg, s)
    assert e.value.kind == "fingerprint"


def test_remeasure_schreibt_weder_reference_dir_noch_image_path(cfg,
                                                               monkeypatch):
    """R8-Ergaenzung zur Referenzbild-Persistenz: Fortsetzen ist auch
    gegenueber reference_dir und der DB strikt lesend — es entsteht weder
    eine Datei unter reference_dir noch eine Zeile/ein image_path."""
    s = _sitzung(cfg, 2, start=270.0)
    ref = Path(cfg["paths"]["reference_dir"])
    ref_vorher = sorted(str(p) for p in ref.rglob("*")) if ref.exists() else None
    db_vorher = [(p, f.circle_diameter_mm) for p, f in _refs(cfg)]

    _remeasure_mit(monkeypatch, [_feats(299.0), _feats(298.0)])
    remeasure_session(cfg, s)

    ref_nachher = sorted(str(p) for p in ref.rglob("*")) if ref.exists() else None
    assert ref_nachher == ref_vorher, "reference_dir unangetastet"
    assert [(p, f.circle_diameter_mm) for p, f in _refs(cfg)] == db_vorher, \
        "keine DB-Zeile, kein image_path geschrieben"


def test_remeasure_meldet_fortschritt(cfg, monkeypatch):
    s = _sitzung(cfg, 3, start=270.0)
    _remeasure_mit(monkeypatch, [_feats(270.0), _feats(271.0), _feats(272.0)])
    schritte = []
    remeasure_session(cfg, s, progress=lambda k, n: schritte.append((k, n)))
    assert schritte == [(1, 3), (2, 3), (3, 3)]
