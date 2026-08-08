"""Natürliche Sortierung von Artikelnummern — und ihre Abgrenzung zum Messpfad.

Zwei Hälften, und die zweite ist die wichtigere:

1. Der Sortierschlüssel selbst (`display.natuerlicher_schluessel`) und die
   beiden Anzeigestellen, die ihn benutzen (`pipeline.list_articles`, das die
   Qt-Dialoge speist, und `cli.cmd_list_articles`).

2. **Wächter**: dass `Database.all_articles()` und `matcher.match()` davon
   NICHT betroffen sind — positiv geprüft, nicht nur nicht angefasst. Der
   naheliegende „Fix" wäre ein `ORDER BY` in der DB-Schicht gewesen; von dort
   holt sich der Matcher die Kandidaten, und `candidates.sort(key=log_score)`
   ist stabil. Weil `log_score` auf vier Stellen GERUNDET wird, sind exakte
   Gleichstände bei baugleichen Artikeln realistisch — dann entscheidet die
   DB-Reihenfolge über Top-1. Eine „kosmetische" Sortierung hätte damit im
   Messpfad gelandet.
"""

import sys
from argparse import Namespace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect import cli  # noqa: E402
from docodetect.calibration import Calibration  # noqa: E402
from docodetect.config import load_config  # noqa: E402
from docodetect.database import Article, Database  # noqa: E402
from docodetect.display import natuerlicher_schluessel  # noqa: E402
from docodetect.matcher import match  # noqa: E402
from docodetect.pipeline import list_articles  # noqa: E402

# dieselben Bausteine wie tests/test_matching_decisions.py
from test_matching_decisions import fake, make_db  # noqa: E402


def _sortiert(namen):
    return sorted(namen, key=natuerlicher_schluessel)


# ---------- 1) der Sortierschlüssel ----------

def test_zahlenteil_numerisch():
    assert _sortiert(["LOEFFEL-11", "LOEFFEL-2", "LOEFFEL-1"]) == [
        "LOEFFEL-1", "LOEFFEL-2", "LOEFFEL-11"]


def test_das_40_artikel_problem():
    """Der Fall aus der Praxis: 15 Gabeln in list-articles."""
    namen = [f"GABEL-{i}" for i in range(1, 16)]
    assert _sortiert(namen) == namen          # 1,2,3,...,15 statt 1,10,11,...


def test_ohne_ziffern_wirft_nicht():
    assert _sortiert(["TELLER", "GABEL", "MESSER"]) == [
        "GABEL", "MESSER", "TELLER"]


def test_mit_und_ohne_ziffern_gemischt():
    """Der Fall, an dem selbstgebaute Naturalsorts typisch scheitern:
    int gegen str im selben Tupel-Slot."""
    assert _sortiert(["TELLER", "GABEL-2", "GABEL-11", "GABEL"]) == [
        "GABEL", "GABEL-2", "GABEL-11", "TELLER"]


def test_mehrere_zahlengruppen():
    assert _sortiert(["A1-B10", "A1-B2", "A10-B1", "A2-B1"]) == [
        "A1-B2", "A1-B10", "A2-B1", "A10-B1"]


@pytest.mark.parametrize("wert", ["", "-", "42", "0", None, 7, "X" * 200,
                                  "9" * 40, "Ä-3", "a-1"])
def test_wirft_bei_keinem_eingabewert(wert):
    natuerlicher_schluessel(wert)              # darf nicht werfen


def test_grosse_zahlen_ohne_ueberlauf():
    assert _sortiert(["N-" + "9" * 30, "N-2"]) == ["N-2", "N-" + "9" * 30]


def test_ordnung_ist_total():
    """Führende Nullen dürfen nicht zu gleichwertigen Schlüsseln führen –
    sonst hinge die Reihenfolge an der Einfügereihenfolge."""
    assert natuerlicher_schluessel("L-01") != natuerlicher_schluessel("L-1")
    assert _sortiert(["L-1", "L-01"]) == _sortiert(["L-01", "L-1"])


def test_gross_kleinschreibung_egal():
    assert _sortiert(["loeffel-2", "LOEFFEL-1"]) == ["LOEFFEL-1", "loeffel-2"]


# ---------- 2) die Anzeigestellen ----------

@pytest.fixture()
def db_cfg(tmp_path):
    cfg = load_config()
    cfg["paths"] = {"db_file": str(tmp_path / "t.sqlite3")}
    db = Database(cfg)
    db.init_schema()
    for nr in ["LOEFFEL-11", "LOEFFEL-2", "LOEFFEL-1", "GABEL-3"]:
        db.create_article(Article(
            article_number=nr, name=nr, category=None, diameter_mm=None,
            width_mm=140.0, depth_mm=30.0, height_mm=None, color_desc=None,
            notes=None))
    db.close()
    return cfg


def test_list_articles_ist_natuerlich_sortiert(db_cfg):
    """Speist Artikel-Combo des Einlerndialogs UND den Korrekturdialog –
    beide ohne eigene Sortierung, beide damit miterledigt."""
    assert [a.article_number for a in list_articles(db_cfg)] == [
        "GABEL-3", "LOEFFEL-1", "LOEFFEL-2", "LOEFFEL-11"]


def test_cmd_list_articles_ist_natuerlich_sortiert(db_cfg, capsys):
    cli.cmd_list_articles(Namespace(), db_cfg)
    zeilen = [z.split()[0] for z in capsys.readouterr().out.splitlines()
              if z.startswith(("LOEFFEL-", "GABEL-"))]
    assert zeilen == ["GABEL-3", "LOEFFEL-1", "LOEFFEL-2", "LOEFFEL-11"]


# ---------- 3) Wächter: Messpfad NICHT betroffen ----------

def test_all_articles_bleibt_lexikografisch(db_cfg):
    """Positiv geprüft, nicht nur nicht angefasst: die DB-Schicht liefert
    weiter `ORDER BY article_number`. Die Gegenprobe darunter belegt, dass
    sich die beiden Ordnungen auf diesen Daten wirklich unterscheiden –
    sonst wäre der Wächter zahnlos."""
    db = Database(db_cfg)
    try:
        roh = [a.article_number for a in db.all_articles()]
    finally:
        db.close()
    assert roh == ["GABEL-3", "LOEFFEL-1", "LOEFFEL-11", "LOEFFEL-2"]
    assert roh != _sortiert(roh)


def test_matcher_kandidatenreihenfolge_folgt_der_db_nicht_der_anzeige(tmp_path):
    """Der eigentliche Grund für die Abgrenzung.

    Zwei baugleiche Artikel mit identischen Referenzen ergeben denselben, auf
    vier Stellen gerundeten log_score. `candidates.sort` ist stabil, also
    entscheidet die Reihenfolge aus `all_articles()` – lexikografisch, damit
    LOEFFEL-11 VOR LOEFFEL-2. Wäre die natürliche Sortierung in die DB-Schicht
    gerutscht, stünde hier LOEFFEL-2 vorn: eine stillschweigend geänderte
    Entscheidung."""
    cfg = load_config()
    cfg["paths"] = {"db_file": str(tmp_path / "t.sqlite3")}
    cal = Calibration(mm_per_px=0.2,
                      camera_height_mm=float(cfg["geometry"]["camera_height_mm"]),
                      image_width=1920, image_height=1080,
                      marker_size_mm=50.0, created_unix=0.0)
    db = make_db(cfg, [
        ("LOEFFEL-11", 200.0, 0.0, [fake(200.0)] * 2),
        ("LOEFFEL-2", 200.0, 0.0, [fake(200.0)] * 2),
    ])
    try:
        rep = match(fake(200.0), db, cal, cfg)
        nummern = [c.article_number for c in rep.candidates]
        # Vorbedingung: der Gleichstand ist echt, sonst prüft der Test nichts
        assert rep.candidates[0].log_score == rep.candidates[1].log_score
        assert nummern == ["LOEFFEL-11", "LOEFFEL-2"]
        assert nummern != _sortiert(nummern)
    finally:
        db.close()
