"""Tests für docodetect/stammdaten.py: Abgleich der geometrischen Stammdaten
mit den Enrollment-Mittelwerten.

Läuft ausschließlich gegen Temp-DBs (nie die echte doco_detect.sqlite3).

Run: pytest tests/test_stammdaten.py -v
"""

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.database import Article, Database  # noqa: E402
from docodetect.features import Features  # noqa: E402
from docodetect.stammdaten import apply_sync, compute_sync  # noqa: E402


def _feats(diameter_mm: float) -> Features:
    return Features(equiv_diameter_mm=diameter_mm, circle_diameter_mm=diameter_mm,
                    area_mm2=1000.0, perimeter_mm=100.0, circularity=0.5,
                    aspect_ratio=0.2, mean_hsv=[0.0, 0.0, 200.0],
                    hue_hist=[0.0] * 32, solidity=0.7,
                    hu_moments=[1.0] * 7)


@pytest.fixture
def db(tmp_path):
    d = Database({"paths": {"db_file": str(tmp_path / "t.sqlite3")}})
    d.init_schema()
    yield d
    d.close()


def _article(nr, **kw):
    base = dict(article_number=nr, name=nr, category=None, diameter_mm=None,
                width_mm=None, depth_mm=None, height_mm=None, color_desc=None,
                notes=None)
    return Article(**{**base, **kw})


def test_runder_artikel_bekommt_den_enrollment_mittelwert(db):
    """Der diameter_mm-Zweig bleibt vom hypot/max-Fix fuer laengliche
    Artikel (siehe test_laenglicher_artikel_...unten) unberuehrt -- er
    nutzt weder hypot() noch max(), sondern diameter_mm direkt."""
    db.create_article(_article("RUND", diameter_mm=200.0))
    for d in (203.0, 205.0):          # Mittel 204.0
        db.add_reference("RUND", _feats(d))

    rows, skipped = compute_sync(db)
    assert len(rows) == 1 and not skipped
    r = rows[0]
    assert r.nominal_alt == pytest.approx(200.0)
    assert r.nominal_neu == pytest.approx(204.0)
    assert r.diff_mm == pytest.approx(4.0)
    assert r.felder == {"diameter_mm": (200.0, 204.0)}

    # compute_sync allein aendert nichts
    assert db.get_article("RUND").diameter_mm == pytest.approx(200.0)
    apply_sync(db, rows)
    assert db.get_article("RUND").diameter_mm == pytest.approx(204.0)


def test_laenglicher_artikel_behaelt_sein_seitenverhaeltnis(db):
    """width/depth sind minAreaRect-Seiten, der Enrollment-Mittelwert ist ein
    minEnclosingCircle-Ø. Angeglichen wird die Groesse, die der Vorfilter
    vergleicht – max(width, depth), die Laenge –, das Seitenverhaeltnis
    bleibt erhalten."""
    db.create_article(_article("LOEFFEL", width_mm=190.0, depth_mm=25.0))
    for d in (194.0, 196.0):          # Mittel 195.0
        db.add_reference("LOEFFEL", _feats(d))

    rows, _ = compute_sync(db)
    apply_sync(db, rows)
    art = db.get_article("LOEFFEL")

    assert max(art.width_mm, art.depth_mm) == pytest.approx(195.0, abs=0.02)
    assert art.width_mm / art.depth_mm == pytest.approx(190.0 / 25.0, rel=1e-3)


def test_laenglicher_artikel_wird_gegen_laenge_synchronisiert_nicht_diagonale(db):
    """Realer Fall LOEFFEL-4 (Ergebnisdokument 2026-07-23, Abschnitt 6):
    width=183.21mm, depth=37.18mm. compute_sync muss den Skalierungsfaktor
    gegen max(width,depth)=183.21 bilden -- NICHT gegen die Diagonale
    hypot(width,depth)=186.94, das war der Defekt (Befund E2, dritte
    Fundstelle derselben Fehlerklasse nach Vorfilter- und Flaechen-Check).

    Reale Konsequenz (der Vorfilter in matcher.py vergleicht exakt
    row.nominal_alt/neu gegen den gemessenen Kreisdurchmesser, separat
    getestet in test_matching_decisions.py): eine Aufnahme mit gemessenem
    Kreisdurchmesser 190.42mm liegt bei 6.0mm Toleranz gegen den
    unsynchronisierten Nominalwert 183.21mm um 7.21mm daneben -> Kill.
    Gegen den synchronisierten Wert 186.49mm sind es nur noch 3.93mm ->
    bleibt im Kandidatenset. Das war der einzige Vorfilter-Kill des Tages
    (2026-07-23)."""
    db.create_article(_article("LOEFFEL-4", width_mm=183.21, depth_mm=37.18))
    for d in (184.00, 188.98):        # Mittel 186.49 (Enrollment-Mittel)
        db.add_reference("LOEFFEL-4", _feats(d))

    rows, _ = compute_sync(db)
    row = rows[0]
    assert row.nominal_alt == pytest.approx(183.21, abs=0.01)   # max(w,d)
    assert row.nominal_neu == pytest.approx(186.49, abs=0.01)

    # Gegenprobe: die verworfene Diagonale waere ein anderer, falscher Wert.
    assert math.hypot(183.21, 37.18) == pytest.approx(186.94, abs=0.01)
    assert row.nominal_alt != pytest.approx(186.94, abs=0.01)

    measured = 190.42
    assert abs(measured - row.nominal_alt) == pytest.approx(7.21, abs=0.01)
    assert abs(measured - row.nominal_neu) == pytest.approx(3.93, abs=0.01)

    apply_sync(db, rows)
    art = db.get_article("LOEFFEL-4")
    assert max(art.width_mm, art.depth_mm) == pytest.approx(186.49, abs=0.02)
    assert art.width_mm / art.depth_mm == pytest.approx(183.21 / 37.18, rel=1e-3)


def test_ein_shot_wird_uebersprungen_und_begruendet(db):
    db.create_article(_article("EINS", diameter_mm=200.0))
    db.add_reference("EINS", _feats(210.0))

    rows, skipped = compute_sync(db)               # min_shots=2 (Default)
    assert rows == [] and any("EINS" in s for s in skipped)
    assert db.get_article("EINS").diameter_mm == pytest.approx(200.0)

    rows, _ = compute_sync(db, min_shots=1)        # bewusst zugelassen
    assert len(rows) == 1 and rows[0].nominal_neu == pytest.approx(210.0)


def test_artikel_ohne_referenzen_bleiben_unberuehrt(db):
    db.create_article(_article("OHNE", diameter_mm=180.0))
    rows, skipped = compute_sync(db)
    assert rows == [] and skipped == []
    assert db.get_article("OHNE").diameter_mm == pytest.approx(180.0)


def test_update_geometry_weist_fremde_spalten_ab(db):
    db.create_article(_article("X", diameter_mm=100.0))
    with pytest.raises(ValueError, match="name"):
        db.update_geometry("X", name="neu")
    assert db.get_article("X").name == "X"
