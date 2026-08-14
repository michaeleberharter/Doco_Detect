"""Tests für die Messreihen-Helfer (batch-create/batch-enroll), die
CLI-Befehle `delete-references` und `list-articles` und den A/B-Vergleich
(ab-report).

Beide sind dünne Wrapper: die Batch-Kommandos nutzen exakt dieselben Kerne wie
`create-article`/`enroll`, `ab-report` dieselbe Aggregation wie `evaluate`.
Getestet wird deshalb vor allem die BEDIENUNG (q = Abbruch, r = verwerfen und
wiederholen) und dass ein verworfener Artikel wirklich verschwindet – sonst
verfälschen Fehlmessungen still die Messreihe.

`delete-references` steht hier, weil es denselben DB-Kern benutzt wie der
„r"-Zweig von batch-enroll (Database.delete_references) und dieselbe Umgebung
braucht. Geprüft wird zusätzlich das, was der CLI-Befehl eigenmächtig tut:
Fotos VERSCHIEBEN statt löschen und die beiden Exit-Codes unterscheiden.

Ohne Kamera: die Aufnahme wird durch ein synthetisches Bild ersetzt
(conftest.py sperrt echte Geräte ohnehin).
"""

import sys
from argparse import Namespace
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect import cli  # noqa: E402
from docodetect.calibration import Calibration  # noqa: E402
from docodetect.database import Database  # noqa: E402
from docodetect.matcher import CandidateReport, MatchReport  # noqa: E402
from docodetect.reporting import (compare_runs, max_z_distribution,  # noqa: E402
                                  top_k_accuracy)

MM_PER_PX = 0.2


def _bg(w=1920, h=1080):
    bg = np.full((h, w, 3), 200, dtype=np.int16)
    bg += np.random.default_rng(42).integers(-5, 5, bg.shape, dtype=np.int16)
    return np.clip(bg, 0, 255).astype(np.uint8)


def _bar(bg, length_mm=140.0, width_mm=30.0):
    """Löffel-Ersatz (länglich) – wie in tests/test_pipeline_synthetic.py."""
    img = bg.copy()
    L, W = int(length_mm / MM_PER_PX), int(width_mm / MM_PER_PX)
    x0, y0 = 960 - L // 2, 540 - W // 2
    cv2.rectangle(img, (x0, y0), (x0 + L, y0 + W), (170, 170, 170), -1)
    return img


@pytest.fixture()
def batch_env(tmp_path, monkeypatch):
    """Config + Kalibrierung + Hintergrund unter tmp_path; die 'Kamera'
    liefert immer dasselbe synthetische Löffelbild."""
    from docodetect.config import load_config

    cfg = load_config()
    cfg["camera"] = {"index": 0, "width": 1920, "height": 1080}
    cfg["calibration"]["file"] = str(tmp_path / "calibration.json")
    cfg["calibration"]["background_file"] = str(tmp_path / "background.png")
    cfg["paths"] = {"db_file": str(tmp_path / "db.sqlite3"),
                    "reference_dir": str(tmp_path / "reference")}
    bg = _bg()
    cv2.imwrite(cfg["calibration"]["background_file"], bg)
    Calibration(mm_per_px=MM_PER_PX, camera_height_mm=300.0, image_width=1920,
                image_height=1080, marker_size_mm=72.5,
                created_unix=0.0).save(cfg["calibration"]["file"])

    class FakeCam:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def capture(self):
            return _bar(bg)

    monkeypatch.setattr(cli, "BoxCamera", lambda _cfg: FakeCam())
    return cfg


def _answers(monkeypatch, seq):
    """input() der Reihe nach mit vorgegebenen Antworten bedienen."""
    it = iter(seq)
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(it))


# ---------- batch-create ----------

def test_batch_create_creates_numbered_articles(batch_env, monkeypatch):
    _answers(monkeypatch, ["", "", "", "", "", ""])   # 3x (aufnehmen, weiter)
    cli.cmd_batch_create(
        Namespace(name_prefix="Löffel", count=3, height_mm=0.0, category=None),
        batch_env)
    db = Database(batch_env)
    try:
        numbers = [a.article_number for a in db.all_articles()]
        assert numbers == ["LOEFFEL-1", "LOEFFEL-2", "LOEFFEL-3"]
        # länglich -> width/depth statt diameter (sonst wirft der Flächen-Check
        # den Löffel bei der Wiedererkennung raus)
        art = db.get_article("LOEFFEL-1")
        assert art.diameter_mm is None
        assert art.width_mm and art.depth_mm and art.width_mm > art.depth_mm
        assert len(db.references_for("LOEFFEL-1")) == 1   # 1 Shot pro Artikel
    finally:
        db.close()


def test_batch_create_q_aborts(batch_env, monkeypatch):
    _answers(monkeypatch, ["", "", "q"])              # 1 Artikel, dann Abbruch
    cli.cmd_batch_create(
        Namespace(name_prefix="Löffel", count=5, height_mm=0.0, category=None),
        batch_env)
    db = Database(batch_env)
    try:
        assert [a.article_number for a in db.all_articles()] == ["LOEFFEL-1"]
    finally:
        db.close()


def test_batch_create_r_discards_and_repeats(batch_env, monkeypatch):
    """r nach der Messung: Artikel wird gelöscht und derselbe Name erneut
    aufgenommen – die Nummer darf NICHT auf LOEFFEL-1-2 weiterlaufen."""
    _answers(monkeypatch, ["", "r", "", ""])          # aufnehmen, verwerfen, nochmal, weiter
    cli.cmd_batch_create(
        Namespace(name_prefix="Löffel", count=1, height_mm=0.0, category=None),
        batch_env)
    db = Database(batch_env)
    try:
        assert [a.article_number for a in db.all_articles()] == ["LOEFFEL-1"]
        assert len(db.references_for("LOEFFEL-1")) == 1
    finally:
        db.close()


# ---------- batch-enroll ----------

def test_batch_enroll_adds_shots_per_article(batch_env, monkeypatch):
    _answers(monkeypatch, ["", ""])
    cli.cmd_batch_create(
        Namespace(name_prefix="Löffel", count=1, height_mm=0.0, category=None),
        batch_env)
    _answers(monkeypatch, ["", "", "", ""])           # einlegen, 2 Shots, weiter
    cli.cmd_batch_enroll(
        Namespace(prefix="LOEFFEL", count=1, shots=2), batch_env)
    db = Database(batch_env)
    try:
        assert len(db.references_for("LOEFFEL-1")) == 3   # 1 aus create + 2
        assert db.stats_for("LOEFFEL-1").n_shots == 3
    finally:
        db.close()


def test_batch_enroll_r_reenrolls_without_duplicates(batch_env, monkeypatch):
    """r nach dem Einlernen verwirft ALLE Referenzen des Artikels und lernt
    neu ein – sonst summieren sich zwei Messreihen zu einer falschen Statistik."""
    _answers(monkeypatch, ["", ""])
    cli.cmd_batch_create(
        Namespace(name_prefix="Löffel", count=1, height_mm=0.0, category=None),
        batch_env)
    _answers(monkeypatch, ["", "", "r", "", "", ""])   # einlegen, 1 Shot, r, nochmal
    cli.cmd_batch_enroll(
        Namespace(prefix="LOEFFEL", count=1, shots=1), batch_env)
    db = Database(batch_env)
    try:
        # nach dem Verwerfen zählt NUR die zweite Runde (der create-Shot ist
        # mit weg – delete_references räumt den Artikel komplett leer)
        assert len(db.references_for("LOEFFEL-1")) == 1
    finally:
        db.close()


def test_batch_enroll_skips_missing_articles(batch_env, monkeypatch, capsys):
    _answers(monkeypatch, [])                          # kein input() nötig
    cli.cmd_batch_enroll(
        Namespace(prefix="LOEFFEL", count=2, shots=1), batch_env)
    out = capsys.readouterr().out
    assert "LOEFFEL-1 existiert nicht" in out and "LOEFFEL-2 existiert nicht" in out


def test_delete_references_keeps_article(batch_env, monkeypatch):
    _answers(monkeypatch, ["", ""])
    cli.cmd_batch_create(
        Namespace(name_prefix="Löffel", count=1, height_mm=0.0, category=None),
        batch_env)
    db = Database(batch_env)
    try:
        assert db.delete_references("LOEFFEL-1") == 1
        assert db.get_article("LOEFFEL-1") is not None   # Artikel bleibt
        assert db.references_for("LOEFFEL-1") == []
        assert db.stats_for("LOEFFEL-1") is None         # Statistik mit geleert
    finally:
        db.close()


# ---------- delete-references (CLI) ----------

def _mit_einem_artikel(env, monkeypatch):
    """LOEFFEL-1 anlegen (1 Referenz + 1 Foto auf Platte)."""
    _answers(monkeypatch, ["", ""])
    cli.cmd_batch_create(
        Namespace(name_prefix="Löffel", count=1, height_mm=0.0, category=None),
        env)
    return Path(env["paths"]["reference_dir"]) / "LOEFFEL-1"


def test_cli_delete_references_leert_db_und_behaelt_artikel(batch_env, monkeypatch):
    _mit_einem_artikel(batch_env, monkeypatch)
    cli.cmd_delete_references(Namespace(article_number="LOEFFEL-1"), batch_env)
    db = Database(batch_env)
    try:
        assert db.get_article("LOEFFEL-1") is not None    # Artikel bleibt
        assert db.references_for("LOEFFEL-1") == []
        # reference_stats MUSS mit weg: der Matcher liest has_references aus
        # stats_for() – eine übrig gebliebene Zeile führte den Artikel weiter
        # als eingelernt, ohne dass es noch Referenzen gäbe.
        assert db.stats_for("LOEFFEL-1") is None
    finally:
        db.close()


def test_cli_delete_references_verschiebt_fotos_statt_zu_loeschen(batch_env,
                                                                  monkeypatch):
    """move-don't-delete: der Ordner ist weg, sein Inhalt liegt vollständig
    unter verworfen/<nr>/<zeitstempel>/ – samt info.json als Beleg."""
    import json

    ref_ordner = _mit_einem_artikel(batch_env, monkeypatch)
    fotos = sorted(p.name for p in ref_ordner.glob("*.png"))
    assert fotos, "Vorbedingung: batch-create legt ein Foto ab"

    cli.cmd_delete_references(Namespace(article_number="LOEFFEL-1"), batch_env)

    assert not ref_ordner.exists()
    verworfen = ref_ordner.parent.parent / "verworfen" / "LOEFFEL-1"
    ziele = list(verworfen.iterdir())
    assert len(ziele) == 1, "genau ein Zeitstempel-Ordner"
    assert sorted(p.name for p in ziele[0].glob("*.png")) == fotos
    info = json.loads((ziele[0] / "info.json").read_text(encoding="utf-8"))
    assert info["article_number"] == "LOEFFEL-1"
    assert info["geloeschte_db_zeilen"] == 1
    assert info["verschobene_dateien"] == len(fotos)
    assert info["zeilen_ohne_image_path"] == 0


def test_cli_delete_references_folgt_dem_reference_dir(tmp_path, batch_env,
                                                       monkeypatch):
    """Das Ziel entsteht AUS reference_dir (../verworfen/), nie aus einem
    Literal – nur so landet der Befehl unter --sandbox im Sandbox-Baum statt
    im produktiven data/verworfen/. Dass reference_dir selbst umgelenkt wird,
    prüft test_sandbox.py; hier zählt die Ableitung."""
    _mit_einem_artikel(batch_env, monkeypatch)
    cli.cmd_delete_references(Namespace(article_number="LOEFFEL-1"), batch_env)
    assert (tmp_path / "verworfen" / "LOEFFEL-1").is_dir()


def test_cli_delete_references_ohne_referenzen_ist_exit_0(batch_env, monkeypatch,
                                                          capsys):
    """Zielzustand schon erreicht: idempotent, kein Abbruch."""
    _mit_einem_artikel(batch_env, monkeypatch)
    cli.cmd_delete_references(Namespace(article_number="LOEFFEL-1"), batch_env)
    capsys.readouterr()
    cli.cmd_delete_references(Namespace(article_number="LOEFFEL-1"), batch_env)
    assert "keine Referenzen" in capsys.readouterr().out


def test_cli_delete_references_unbekannter_artikel_ist_exit_1(batch_env):
    """Muss sich vom Leerfall unterscheiden: delete_references() gibt für
    beide 0 zurück, der Tippfehler darf nicht still durchlaufen."""
    with pytest.raises(SystemExit) as e:
        cli.cmd_delete_references(Namespace(article_number="GIBTSNICHT"),
                                  batch_env)
    assert e.value.code != 0
    assert "nicht gefunden" in str(e.value)


def test_cli_delete_references_zweimal_in_derselben_sekunde(batch_env,
                                                            monkeypatch):
    """Zwei Läufe im selben Zeitstempel dürfen nicht ineinander verschachteln
    (shutil.move in einen EXISTIERENDEN Ordner legt ihn sonst hinein)."""
    ref_ordner = _mit_einem_artikel(batch_env, monkeypatch)
    db = Database(batch_env)
    try:
        feats = db.references_for("LOEFFEL-1")[0]     # für die zweite Runde
    finally:
        db.close()
    monkeypatch.setattr(cli.time, "strftime", lambda *a: "20260801-120000")
    cli.cmd_delete_references(Namespace(article_number="LOEFFEL-1"), batch_env)

    ref_ordner.mkdir(parents=True)
    (ref_ordner / "zweite_runde.png").write_bytes(b"x")
    db = Database(batch_env)
    try:
        db.add_reference("LOEFFEL-1", feats,
                         str(ref_ordner / "zweite_runde.png"))
    finally:
        db.close()
    cli.cmd_delete_references(Namespace(article_number="LOEFFEL-1"), batch_env)

    verworfen = ref_ordner.parent.parent / "verworfen" / "LOEFFEL-1"
    assert sorted(p.name for p in verworfen.iterdir()) == [
        "20260801-120000", "20260801-120000-2"]
    assert (verworfen / "20260801-120000-2" / "zweite_runde.png").exists()


def test_cli_delete_references_quarantaene_absoluter_altbestand(batch_env,
                                                                monkeypatch):
    """Schritt 5 der Windows-Sequenz trifft den ECHTEN Altbestand: Zeilen mit
    ABSOLUTEM image_path (Stand vor der Relativ-Umstellung, z.B. die
    LOEFFEL-3-Einlernung von vor der Optik-Korrektur — Beweismaterial für
    Auflage vs. Optik). Die Quarantäne arbeitet ORDNER-basiert, liest
    image_path also gar nicht — genau das belegt der Test: unabhängig von der
    Pfad-Form der Zeilen wird der komplette Ordnerinhalt verschoben und nichts
    verloren, auch keine Waisen-Datei ohne DB-Zeile. (Alle 25 echten
    Altbestands-Pfade zeigen IN reference_dir; Pfade außerhalb gibt es im
    Bestand nicht.)"""
    import json

    ref_ordner = _mit_einem_artikel(batch_env, monkeypatch)
    db = Database(batch_env)
    try:
        feats = db.references_for("LOEFFEL-1")[0]
        alt = ref_ordner / "1785264879302_00.png"
        cv2.imwrite(str(alt), np.zeros((8, 8, 3), dtype=np.uint8))
        db.add_reference("LOEFFEL-1", feats, str(alt))  # absolut, wie Altbestand
    finally:
        db.close()
    waise = ref_ordner / "waise_ohne_zeile.png"
    cv2.imwrite(str(waise), np.zeros((8, 8, 3), dtype=np.uint8))
    dateien = sorted(p.name for p in ref_ordner.iterdir())

    cli.cmd_delete_references(Namespace(article_number="LOEFFEL-1"), batch_env)

    assert not ref_ordner.exists()
    verworfen = ref_ordner.parent.parent / "verworfen" / "LOEFFEL-1"
    ziel = next(iter(verworfen.iterdir()))
    angekommen = sorted(p.name for p in ziel.iterdir() if p.name != "info.json")
    assert angekommen == dateien       # nichts verloren, auch die Waise nicht
    info = json.loads((ziel / "info.json").read_text(encoding="utf-8"))
    assert info["geloeschte_db_zeilen"] == 2
    assert info["verschobene_dateien"] == len(dateien)


# ---------- delete-article (CLI) ----------

def test_cli_delete_article_verschiebt_fotos_statt_zu_loeschen(batch_env,
                                                               monkeypatch):
    """delete-article zieht mit delete-references gleich: Stammdaten und
    DB-Zeilen weg, die Fotos vollständig unter verworfen/ — nicht mehr liegen
    gelassen (der alte Vorbehalt stammt aus der Zeit vor den Einlernbildern)."""
    import json

    ref_ordner = _mit_einem_artikel(batch_env, monkeypatch)
    fotos = sorted(p.name for p in ref_ordner.glob("*.png"))
    assert fotos, "Vorbedingung: batch-create legt ein Foto ab"

    cli.cmd_delete_article(Namespace(article_number="LOEFFEL-1"), batch_env)

    db = Database(batch_env)
    try:
        assert db.get_article("LOEFFEL-1") is None
    finally:
        db.close()
    assert not ref_ordner.exists()
    verworfen = ref_ordner.parent.parent / "verworfen" / "LOEFFEL-1"
    ziele = list(verworfen.iterdir())
    assert len(ziele) == 1, "genau ein Zeitstempel-Ordner"
    assert sorted(p.name for p in ziele[0].glob("*.png")) == fotos
    info = json.loads((ziele[0] / "info.json").read_text(encoding="utf-8"))
    assert info["grund"] == "delete-article (CLI)"
    assert info["geloeschte_db_zeilen"] == 1
    assert info["verschobene_dateien"] == len(fotos)


def test_cli_delete_article_unbekannter_artikel_ist_exit_1(batch_env):
    """Ein Tippfehler in der Nummer darf insbesondere KEINEN Foto-Ordner in
    Quarantäne schieben — das Verschieben steht NACH der Existenz-Prüfung."""
    with pytest.raises(SystemExit) as e:
        cli.cmd_delete_article(Namespace(article_number="GIBTSNICHT"),
                               batch_env)
    assert e.value.code != 0
    assert "nicht gefunden" in str(e.value)
    verworfen = Path(batch_env["paths"]["reference_dir"]).parent / "verworfen"
    assert not verworfen.exists()


def test_verwerfen_meldet_zielort_wenn_info_json_scheitert(batch_env,
                                                           monkeypatch,
                                                           capsys):
    """Die Fotos SIND nach dem Move verschoben — scheitert danach nur das
    info.json (Platte voll, Windows-Sperre auf dem neuen Ordner), darf das
    nicht als 'liess sich nicht verschieben' enden: der Bediener fände den
    Zielort sonst nie. Erwartet: kein Abbruch, Zielort in der Ausgabe."""
    ref_ordner = _mit_einem_artikel(batch_env, monkeypatch)
    fotos = sorted(p.name for p in ref_ordner.glob("*.png"))

    orig = Path.write_text

    def kaputt(self, *a, **k):
        if self.name == "info.json":
            raise OSError(28, "No space left on device")
        return orig(self, *a, **k)

    monkeypatch.setattr(Path, "write_text", kaputt)
    cli.cmd_delete_references(Namespace(article_number="LOEFFEL-1"), batch_env)

    assert not ref_ordner.exists()
    verworfen = ref_ordner.parent.parent / "verworfen" / "LOEFFEL-1"
    ziel = next(iter(verworfen.iterdir()))
    assert sorted(p.name for p in ziel.glob("*.png")) == fotos
    out = capsys.readouterr().out
    assert str(ziel) in out                       # Zielort wird genannt
    assert "info.json war nicht schreibbar" in out


def test_batch_enroll_r_verschiebt_fotos_der_ersten_runde(batch_env,
                                                          monkeypatch):
    """Der r-Zweig räumt auch die Platte: die Fotos der verworfenen Runde
    liegen unter verworfen/, im Referenz-Ordner bleiben NUR die der zweiten
    Runde — sonst wären alte und neue Aufnahmen nicht mehr unterscheidbar."""
    import json

    _answers(monkeypatch, ["", ""])
    cli.cmd_batch_create(
        Namespace(name_prefix="Löffel", count=1, height_mm=0.0, category=None),
        batch_env)
    ref_ordner = Path(batch_env["paths"]["reference_dir"]) / "LOEFFEL-1"
    fotos_runde1 = sorted(p.name for p in ref_ordner.glob("*.png"))

    _answers(monkeypatch, ["", "", "r", "", "", ""])   # Runde 1, r, Runde 2
    cli.cmd_batch_enroll(Namespace(prefix="LOEFFEL", count=1, shots=1),
                         batch_env)

    verworfen = ref_ordner.parent.parent / "verworfen" / "LOEFFEL-1"
    ziele = list(verworfen.iterdir())
    assert len(ziele) == 1
    weg = sorted(p.name for p in ziele[0].iterdir() if p.name != "info.json")
    assert len(weg) == len(fotos_runde1) + 1   # create-Foto + Runde-1-Shot
    info = json.loads((ziele[0] / "info.json").read_text(encoding="utf-8"))
    assert info["grund"] == "batch-enroll r (neu einlernen)"
    assert info["geloeschte_db_zeilen"] == 2   # create-Referenz + Runde-1-Shot
    assert info["verschobene_dateien"] == len(weg)
    assert info["zeilen_ohne_image_path"] == 0
    # im Referenz-Ordner liegt NUR noch die zweite Runde
    assert len(list(ref_ordner.glob("*.png"))) == 1
    db = Database(batch_env)
    try:
        assert len(db.references_for("LOEFFEL-1")) == 1
    finally:
        db.close()


# ---------- list-articles (CLI) ----------

def _teller_ohne_referenzen(env, nummer="TELLER-1"):
    """Runder Artikel MIT Höhe und OHNE Referenzen – deckt die drei Zweige ab,
    die batch-create nicht erzeugt (Ø statt B×T, Höhe gesetzt, 0 Referenzen)."""
    from docodetect.database import Article
    db = Database(env)
    db.init_schema()
    try:
        db.create_article(Article(
            article_number=nummer, name="Teller rund", category="Teller",
            diameter_mm=200.0, width_mm=None, depth_mm=None, height_mm=20.0,
            color_desc="weiss", notes=None))
    finally:
        db.close()


def test_list_articles_zeigt_masse_und_referenzzahl(batch_env, monkeypatch,
                                                    capsys):
    _mit_einem_artikel(batch_env, monkeypatch)      # LOEFFEL-1, länglich, 1 Ref
    _teller_ohne_referenzen(batch_env)
    capsys.readouterr()

    cli.cmd_list_articles(Namespace(), batch_env)
    out = capsys.readouterr().out

    # init_schema() meldet sich vor der Tabelle – Kopfzeile über den Inhalt
    # finden, nicht über die Position.
    zeilen = out.splitlines()
    kopf = next(z for z in zeilen if z.startswith("Artikelnummer"))
    assert kopf.split() == ["Artikelnummer", "Bezeichnung", "Maße", "Referenzen"]
    loeffel = next(z for z in zeilen if z.startswith("LOEFFEL-1"))
    teller = next(z for z in zeilen if z.startswith("TELLER-1"))
    assert "×" in loeffel and "mm" in loeffel      # länglich -> B × T
    assert loeffel.split()[-1] == "1"
    assert "Ø 200.0 mm" in teller and "h 20 mm" in teller
    assert teller.split()[-1] == "0"               # ohne Referenzen, nicht fehlend
    assert "2 Artikel, davon 1 eingelernt (1 Referenz gesamt)." in out


def test_list_articles_leere_datenbank_ist_kein_fehler(batch_env, capsys):
    """Schema da, aber keine Artikel: Exit 0 mit Hinweis."""
    db = Database(batch_env)
    db.init_schema()
    db.close()
    capsys.readouterr()
    cli.cmd_list_articles(Namespace(), batch_env)   # darf nicht werfen
    assert "Keine Artikel" in capsys.readouterr().out


def test_list_articles_ohne_schema_ist_exit_1(batch_env):
    """Kein Schema ist ein anderer Zustand als 'keine Artikel' – ein
    vertippter Sandbox-Name darf nicht wie ein leerer Bestand aussehen."""
    with pytest.raises(SystemExit) as e:
        cli.cmd_list_articles(Namespace(), batch_env)
    assert e.value.code != 0
    assert "init-db" in str(e.value)


def test_list_articles_schreibt_nicht_in_die_datenbank(batch_env, monkeypatch):
    """Auflisten muss lesend sein. Mit init_schema() liefe bei JEDEM Aufruf
    recompute_all_stats() und schriebe alle reference_stats neu."""
    _mit_einem_artikel(batch_env, monkeypatch)
    db_datei = Path(batch_env["paths"]["db_file"])
    vorher = db_datei.read_bytes()
    cli.cmd_list_articles(Namespace(), batch_env)
    assert db_datei.read_bytes() == vorher


def test_list_articles_spalten_sind_ausgerichtet(batch_env, monkeypatch, capsys):
    """Verschieden lange Nummern dürfen die Spalten nicht verschieben – sonst
    ist die Liste bei 40 Artikeln nicht mehr lesbar."""
    _answers(monkeypatch, ["", ""] * 11)
    cli.cmd_batch_create(
        Namespace(name_prefix="Löffel", count=11, height_mm=0.0, category=None),
        batch_env)
    capsys.readouterr()

    cli.cmd_list_articles(Namespace(), batch_env)
    zeilen = [z for z in capsys.readouterr().out.splitlines()
              if z.startswith("LOEFFEL-")]
    assert len(zeilen) == 11
    # LOEFFEL-1 und LOEFFEL-11 verschieden lang -> Bezeichnung muss trotzdem
    # in derselben Spalte beginnen
    spalten = {z.index("Löffel ") for z in zeilen}
    assert len(spalten) == 1


def test_list_articles_geometrie_ohne_masse_wirft_nicht(batch_env, capsys):
    """CSV-Import ohne Geometriespalten: die frühere Formatierung wäre an
    None gescheitert."""
    from docodetect.database import Article
    db = Database(batch_env)
    db.init_schema()
    try:
        db.create_article(Article(
            article_number="OHNE-MASS", name="Nur Stammdaten", category=None,
            diameter_mm=None, width_mm=None, depth_mm=None, height_mm=None,
            color_desc=None, notes=None))
    finally:
        db.close()
    capsys.readouterr()
    cli.cmd_list_articles(Namespace(), batch_env)
    zeile = next(z for z in capsys.readouterr().out.splitlines()
                 if z.startswith("OHNE-MASS"))
    assert "—" in zeile


# ---------- ab-report ----------

def _rep(decision, label, winners, max_z=1.0):
    cands = [CandidateReport(
        article_number=nr, name=nr, nominal_size_mm=140.0, height_mm=0.0,
        corrected_diameter_mm=140.0, geometry_error_mm=0.5,
        has_references=True, n_shots=1, features=[], log_score=-0.1,
        posterior=0.9, max_abs_z=max_z) for nr in winners]
    return MatchReport(decision=decision, message="", candidates=cands,
                       max_z_winner=max_z, label=label,
                       gate_passed=decision != "reject")


def test_top_k_accuracy_counts_truth_within_k():
    reports = [_rep("accept", "A", ["A", "B", "C"]),      # Top-1 korrekt
               _rep("ambiguous", "B", ["A", "B", "C"]),   # erst auf Platz 2
               _rep("reject", "C", [])]                   # gar nicht
    assert top_k_accuracy(reports, 1) == (1, 3)
    assert top_k_accuracy(reports, 3) == (2, 3)


def test_top_k_ignores_unlabeled():
    assert top_k_accuracy([_rep("accept", None, ["A"])], 3) == (0, 0)


def test_max_z_distribution_quartiles():
    reports = [_rep("accept", "A", ["A"], max_z=z) for z in (1.0, 2.0, 3.0, 4.0)]
    d = max_z_distribution(reports)
    assert d["n"] == 4 and d["min"] == 1.0 and d["max"] == 4.0
    assert d["median"] == 2.0            # untere Mitte bei gerader Anzahl
    assert max_z_distribution([]) == {}


def test_compare_runs_shows_both_phases_and_delta():
    a = [_rep("ambiguous", "A", ["B", "A"], max_z=3.0)]   # falsch, Wahrheit auf 2
    b = [_rep("accept", "A", ["A", "B"], max_z=1.0)]      # richtig
    out = compare_runs(a, b, k=3, label_a="A (1 Shot)", label_b="B (8 Shots)")
    assert "A (1 Shot)" in out and "B (8 Shots)" in out
    assert "Erfolgsrate %" in out and "korrekt in Top-3 %" in out
    assert "ACCEPT %" in out and "max|z|" in out
    assert "0.0" in out and "100.0" in out                # 0 % -> 100 %
