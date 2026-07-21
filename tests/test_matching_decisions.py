"""Entscheidungs- und Randfall-Tests gegen den ECHTEN Matcher mit den
ECHTEN Schwellen aus config/config.yaml (Fixture, nie duplizieren).
Synthetische Feature-Vektoren, keine Kamera. Spec:
docs/superpowers/specs/2026-07-20-multi-candidate-decision-ui-design.md
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.calibration import Calibration  # noqa: E402
from docodetect.config import load_config  # noqa: E402
from docodetect.database import Article, Database  # noqa: E402
from docodetect.features import Features  # noqa: E402
from docodetect.matcher import match  # noqa: E402


@pytest.fixture()
def cfg(tmp_path):
    """Echte config.yaml (Schwellen NIE duplizieren); DB nach tmp,
    KEIN captures_dir -> identify/match schreiben nie nach data/."""
    c = load_config()
    c["paths"] = {"db_file": str(tmp_path / "t.sqlite3")}
    return c


@pytest.fixture()
def cal(cfg):
    return Calibration(mm_per_px=0.2,
                       camera_height_mm=float(cfg["geometry"]["camera_height_mm"]),
                       image_width=1920, image_height=1080,
                       marker_size_mm=50.0, created_unix=0.0)


def fake(d=200.0, lab=(95.0, 0.0, 0.0), peak=0):
    """Voller Feature-Satz (Zonen + Solidity), damit Kandidaten MIT
    Referenzen über alle Merkmale gescort werden."""
    def hist(p):
        h = [0.0] * 128
        h[p] = 1.0
        return h
    return Features(
        equiv_diameter_mm=d, circle_diameter_mm=d,
        area_mm2=3.14159 * (d / 2) ** 2, perimeter_mm=3.14159 * d,
        circularity=0.90, aspect_ratio=1.0,
        mean_hsv=[0.0, 0.0, 200.0], hue_hist=[1.0 / 32] * 32,
        mean_saturation=0.0,
        hu_moments=[3.2, 8.0, 10.0, 10.0, 10.0, 10.0, 10.0],
        solidity=0.95, lab_center=list(lab), lab_rim=list(lab),
        hs_hist_center=hist(peak), hs_hist_rim=hist(peak))


def make_db(cfg, articles):
    """articles: Liste (nr, diameter_mm, height_mm, [ref-Features])."""
    db = Database(cfg)
    db.init_schema()
    for nr, d, h, refs in articles:
        db.create_article(Article(article_number=nr, name=nr, category=None,
                                  diameter_mm=d, width_mm=None, depth_mm=None,
                                  height_mm=h, color_desc=None, notes=None))
        for f in refs:
            db.add_reference(nr, f)
    return db


# ---------- Task 1: margin_to_next ----------

def test_margin_to_next_ranked(cfg, cal, tmp_path):
    """Drei Kandidaten: Platz 1 tragt margin zum Zweiten (== llr_margin),
    der letzte None."""
    db = make_db(cfg, [
        ("A", 200.0, 0.0, [fake(200.0)] * 2),
        ("B", 200.0, 0.0, [fake(201.5)] * 2),
        ("C", 200.0, 0.0, [fake(203.0)] * 2),
    ])
    try:
        rep = match(fake(200.0), db, cal, cfg)
        assert len(rep.candidates) == 3
        c0, c1, c2 = rep.candidates
        assert c0.margin_to_next == pytest.approx(c0.log_score - c1.log_score)
        assert c0.margin_to_next == pytest.approx(rep.llr_margin)
        assert c1.margin_to_next == pytest.approx(c1.log_score - c2.log_score)
        assert c2.margin_to_next is None
    finally:
        db.close()


def test_margin_to_next_single_candidate_is_none(cfg, cal, tmp_path):
    db = make_db(cfg, [("A", 200.0, 0.0, [fake(200.0)] * 2)])
    try:
        rep = match(fake(200.0), db, cal, cfg)
        assert rep.candidates[0].margin_to_next is None
    finally:
        db.close()


def test_old_report_json_without_margin_field_loads(cfg, cal, tmp_path):
    """Rueckwaertskompatibilitaet: Alt-JSONs ohne margin_to_next laden."""
    from docodetect.matcher import MatchReport
    db = make_db(cfg, [("A", 200.0, 0.0, [fake(200.0)] * 2)])
    try:
        d = match(fake(200.0), db, cal, cfg).to_dict()
        for c in d["candidates"]:
            c.pop("margin_to_next")
        rep = MatchReport.from_dict(d)
        assert rep.candidates[0].margin_to_next is None
    finally:
        db.close()


# ---------- Entscheidungsregeln mit echten Schwellen ----------

def test_auto_accept_clear_winner(cfg, cal, tmp_path):
    db = make_db(cfg, [("A", 200.0, 0.0, [fake(200.0)] * 3)])
    try:
        rep = match(fake(200.0), db, cal, cfg)
        assert rep.decision == "accept" and rep.gate_passed
    finally:
        db.close()


def test_confirm_wegen_margin(cfg, cal, tmp_path):
    """Zwei fast identische Artikel: Gate ok, Margin unter Schwelle."""
    db = make_db(cfg, [("A", 200.0, 0.0, [fake(200.0)] * 2),
                       ("B", 200.0, 0.0, [fake(200.5)] * 2)])
    try:
        rep = match(fake(200.2), db, cal, cfg)
        assert rep.decision == "ambiguous" and rep.gate_passed
        assert rep.llr_margin < float(cfg["matching"]["min_llr_margin"])
    finally:
        db.close()


def test_confirm_ohne_referenzen(cfg, cal, tmp_path):
    """Geometry-only-Sieger kann NIE accept werden."""
    db = make_db(cfg, [("A", 200.0, 0.0, [])])
    try:
        rep = match(fake(200.0), db, cal, cfg)
        assert rep.decision == "ambiguous"
        assert not rep.candidates[0].has_references
    finally:
        db.close()


def test_no_match_gate_bei_fremder_farbe(cfg, cal, tmp_path):
    """Ø passt, Farbe völlig fremd -> max|z| über Gate -> reject
    ('score zu niedrig' ist in der Statistik-Semantik NO_MATCH,
    nicht CONFIRM — Spec-Entscheidung 3)."""
    db = make_db(cfg, [("A", 200.0, 0.0, [fake(200.0, lab=(95.0, 0.0, 0.0))] * 2)])
    try:
        rep = match(fake(200.0, lab=(20.0, 30.0, 30.0)), db, cal, cfg)
        assert rep.decision == "reject" and not rep.gate_passed
        assert rep.max_z_winner > float(cfg["matching"]["max_z_accept"])
    finally:
        db.close()


def test_no_match_leerer_vorfilter(cfg, cal, tmp_path):
    db = make_db(cfg, [("A", 300.0, 0.0, [])])
    try:
        rep = match(fake(200.0), db, cal, cfg)
        assert rep.decision == "reject" and rep.candidates == []
    finally:
        db.close()


# ---------- Randfälle EXAKT auf der Schwelle ----------

def test_gate_boundary_z_exakt_gleich_schwelle_akzeptiert(cfg, cal, tmp_path):
    """max|z| == max_z_accept MUSS bestehen (<=, nicht <). Konstruktion:
    sigma_enroll=0 (identische Shots) -> sigma_eff == sigma_floor; Distanz
    = z * floor exakt. 3.5 * 1.5 = 5.25 mm <= 6 mm Toleranz (Vorfilter ok).
    Binaer exakt: 5.25/1.5 == 3.5."""
    zmax = float(cfg["matching"]["max_z_accept"])
    floor = float(cfg["matching"]["sigma_floors"]["diameter_mm"])
    d_ref = 200.0
    d_meas = d_ref + zmax * floor
    assert d_meas - d_ref <= float(cfg["matching"]["diameter_tolerance_mm"])
    db = make_db(cfg, [("A", d_ref, 0.0, [fake(d_ref)] * 2)])
    try:
        rep = match(fake(d_meas), db, cal, cfg)
        assert rep.max_z_winner == pytest.approx(zmax)
        assert rep.gate_passed and rep.decision == "accept"
    finally:
        db.close()


def test_gate_boundary_knapp_darueber_rejected(cfg, cal, tmp_path):
    zmax = float(cfg["matching"]["max_z_accept"])
    floor = float(cfg["matching"]["sigma_floors"]["diameter_mm"])
    d_ref = 200.0
    d_meas = d_ref + (zmax + 0.01) * floor
    db = make_db(cfg, [("A", d_ref, 0.0, [fake(d_ref)] * 2)])
    try:
        rep = match(fake(d_meas), db, cal, cfg)
        assert not rep.gate_passed and rep.decision == "reject"
    finally:
        db.close()


def test_margin_boundary_exakt_gleich_schwelle_akzeptiert(cfg, cal, tmp_path):
    """LLR-Margin == min_llr_margin MUSS accepten (>=). Konstruktion:
    Sieger A mit Referenzen, alle z == 0 -> log_score 0. B OHNE Referenzen
    (geometry-only): einziges Merkmal ist der Ø, dessen weighted == logL
    (wsum-Renormierung auf EIN Merkmal) -> llr == 0.5 * z_B^2 EXAKT.
    z_B = 2 -> llr = 2.0 == min_llr_margin (Config-Default)."""
    min_llr = float(cfg["matching"]["min_llr_margin"])
    floor = float(cfg["matching"]["sigma_floors"]["diameter_mm"])
    z_b = (2.0 * min_llr) ** 0.5
    geo_err_b = z_b * floor          # 3.0 mm bei Default-Config
    assert geo_err_b <= float(cfg["matching"]["diameter_tolerance_mm"])
    db = make_db(cfg, [("A", 200.0, 0.0, [fake(200.0)] * 2),
                       ("B", 200.0 - geo_err_b, 0.0, [])])
    try:
        rep = match(fake(200.0), db, cal, cfg)
        assert rep.candidates[0].article_number == "A"
        assert rep.llr_margin == pytest.approx(min_llr, abs=1e-3)
        assert rep.decision == "accept"
    finally:
        db.close()


def test_margin_boundary_knapp_darunter_confirm(cfg, cal, tmp_path):
    min_llr = float(cfg["matching"]["min_llr_margin"])
    floor = float(cfg["matching"]["sigma_floors"]["diameter_mm"])
    geo_err_b = ((2.0 * min_llr) ** 0.5 - 0.1) * floor   # llr < Schwelle
    db = make_db(cfg, [("A", 200.0, 0.0, [fake(200.0)] * 2),
                       ("B", 200.0 - geo_err_b, 0.0, [])])
    try:
        rep = match(fake(200.0), db, cal, cfg)
        assert rep.llr_margin < min_llr
        assert rep.decision == "ambiguous"
    finally:
        db.close()


# ---------- Höhenkompensation kandidatenspezifisch ----------

def test_hoehenkorrektur_pro_kandidat_formel(cfg, cal, tmp_path):
    """Gleicher Pixelkreis, zwei Kandidaten mit h=0 und h=60: der
    korrigierte mm-Wert MUSS pro Kandidat der Formel
    true = measured * (Z - h) / Z entsprechen (Z aus config)."""
    z_cam = float(cfg["geometry"]["camera_height_mm"])
    measured = 175.0
    db = make_db(cfg, [
        ("FLACH", measured, 0.0, []),                                # h=0
        ("SCHUESSEL", measured * (z_cam - 60.0) / z_cam, 60.0, []),  # h=60
    ])
    try:
        rep = match(fake(measured), db, cal, cfg)
        by = {c.article_number: c for c in rep.candidates}
        assert set(by) == {"FLACH", "SCHUESSEL"}
        assert by["FLACH"].corrected_diameter_mm == pytest.approx(measured)
        assert by["SCHUESSEL"].corrected_diameter_mm == pytest.approx(
            measured * (z_cam - 60.0) / z_cam)
        assert (by["FLACH"].corrected_diameter_mm
                != by["SCHUESSEL"].corrected_diameter_mm)
    finally:
        db.close()


# ---------- Vorfilter: laengliche Artikel vergleichen gegen Laenge ----------
# Siehe docs/superpowers/plans/2026-07-21-vorfilter-laengliche-artikel.md:
# _nominal_size_mm verglich fuer width_mm/depth_mm-Artikel bisher gegen die
# Diagonale des minAreaRect (hypot), gemessen wird aber der
# minEnclosingCircle-Durchmesser, der fuer eine "Stadion"-Form (Schaft +
# abgerundete Enden, wie Loeffel/Gabel/Messer) der LAENGE entspricht.

def test_laenglicher_artikel_vergleicht_gegen_laenge_nicht_diagonale(cfg, cal, tmp_path):
    """Kern des Fixes: Ø-Vergleich fuer laengliche Artikel (width/depth
    gesetzt) muss gegen die LAENGE (max(width,depth)) gehen, nicht gegen
    die Diagonale (hypot). Ein Loeffel mit Laenge 190mm/Breite 40mm hat
    Diagonale ~194.15mm - eine Messung von 187mm liegt 7.15mm von der
    Diagonale entfernt (> 6mm Toleranz, waere ALT gekillt) aber nur 3mm
    von der Laenge entfernt (<= 6mm, UEBERLEBT den Vorfilter)."""
    db = Database(cfg)
    db.init_schema()
    db.create_article(Article(
        article_number="LOEFFEL", name="Loeffel", category=None,
        diameter_mm=None, width_mm=190.0, depth_mm=40.0, height_mm=None,
        color_desc=None, notes=None))
    db.add_reference("LOEFFEL", fake(190.0))
    try:
        rep = match(fake(187.0), db, cal, cfg)
        assert [c.article_number for c in rep.candidates] == ["LOEFFEL"]
        assert rep.candidates[0].nominal_size_mm == pytest.approx(190.0)
    finally:
        db.close()


def test_laenglicher_artikel_ausserhalb_laengen_toleranz_wird_gekillt(cfg, cal, tmp_path):
    """Gegenprobe: liegt die Messung auch von der LAENGE weiter als 6mm weg,
    bleibt der Artikel zu Recht draussen (kein pauschales Aufweichen)."""
    db = Database(cfg)
    db.init_schema()
    db.create_article(Article(
        article_number="LOEFFEL", name="Loeffel", category=None,
        diameter_mm=None, width_mm=190.0, depth_mm=40.0, height_mm=None,
        color_desc=None, notes=None))
    db.add_reference("LOEFFEL", fake(190.0))
    try:
        rep = match(fake(180.0), db, cal, cfg)  # 10mm von der Laenge weg
        assert rep.candidates == []
        assert rep.decision == "reject"
    finally:
        db.close()


def test_rundes_produkt_unveraendert_ueber_diameter_mm(cfg, cal, tmp_path):
    """Runde Artikel (diameter_mm gesetzt) durchlaufen weiterhin den
    Diameter-Zweig von _nominal_size_mm - der Fix darf diesen Pfad nicht
    beruehren."""
    db = make_db(cfg, [("TELLER", 200.0, 0.0, [fake(200.0)])])
    try:
        rep = match(fake(200.0), db, cal, cfg)
        assert rep.candidates[0].nominal_size_mm == pytest.approx(200.0)
    finally:
        db.close()


def test_laenglich_width_gleich_depth_randfall(cfg, cal, tmp_path):
    """Randfall width==depth (entartete 'Stadion'-Form == Kreis): die
    Laenge (max(width,depth)) UND die Diagonale (hypot) fallen hier
    auseinander (50 vs. 70.7mm) - der Fix muss weiterhin gegen die Laenge
    vergleichen, nicht gegen die (hier besonders grosse) Diagonale."""
    db = Database(cfg)
    db.init_schema()
    db.create_article(Article(
        article_number="QUADRAT", name="Quadrat", category=None,
        diameter_mm=None, width_mm=50.0, depth_mm=50.0, height_mm=None,
        color_desc=None, notes=None))
    db.add_reference("QUADRAT", fake(50.0))
    try:
        rep = match(fake(52.0), db, cal, cfg)  # 2mm von der Laenge (50) weg
        assert [c.article_number for c in rep.candidates] == ["QUADRAT"]
        assert rep.candidates[0].nominal_size_mm == pytest.approx(50.0)
    finally:
        db.close()


def test_laenglich_hoehenkompensation_bleibt_pro_kandidat_wirksam(cfg, cal, tmp_path):
    """Die Formel fuer corrected_diameter_mm (Hoehenkompensation) ist von
    der Nominal-Wahl unabhaengig - muss fuer laengliche Artikel mit
    height_mm > 0 weiterhin greifen (wie bei runden Artikeln)."""
    from docodetect.features import height_corrected_scale
    db = Database(cfg)
    db.init_schema()
    db.create_article(Article(
        article_number="LOEFFEL_HOCH", name="Loeffel", category=None,
        diameter_mm=None, width_mm=190.0, depth_mm=40.0, height_mm=15.0,
        color_desc=None, notes=None))
    db.add_reference("LOEFFEL_HOCH", fake(190.0))
    try:
        measured_circle = 195.0
        rep = match(fake(measured_circle), db, cal, cfg)
        expected = height_corrected_scale(measured_circle, 15.0, cal.camera_height_mm)
        assert rep.candidates[0].corrected_diameter_mm == pytest.approx(
            round(expected, 2))
    finally:
        db.close()


# ---------- border_clipped bleibt Fehlerpfad ----------

def test_border_clipped_erzeugt_kein_match_ergebnis(cfg, cal, tmp_path):
    """identify() mit angeschnittenem Objekt -> reject ohne Kandidaten
    (kein Match-Ergebnis, keine Messwert-Luege)."""
    import cv2
    import numpy as np
    from docodetect.database import Database as _DB
    from docodetect.pipeline import Pipeline

    bg = np.full((1080, 1920, 3), 200, dtype=np.uint8)
    noise = np.random.default_rng(42).integers(-5, 5, bg.shape, dtype=np.int16)
    bg = np.clip(bg.astype(np.int16) + noise, 0, 255).astype(np.uint8)

    pipe = Pipeline.__new__(Pipeline)
    pipe.cfg, pipe.cal, pipe.background = cfg, cal, bg
    pipe.db = _DB(cfg)
    pipe.db.init_schema()
    try:
        img = bg.copy()
        cv2.circle(img, (30, 540), 500, (250, 250, 250), -1)  # ragt links raus
        out = pipe.identify(img)
        assert out.report.decision == "reject"
        assert out.report.candidates == []
        assert out.report.touches_border is True
    finally:
        pipe.db.close()
