"""Tests für die Messreihen-Helfer (batch-create/batch-enroll) und den
A/B-Vergleich (ab-report).

Beide sind dünne Wrapper: die Batch-Kommandos nutzen exakt dieselben Kerne wie
`create-article`/`enroll`, `ab-report` dieselbe Aggregation wie `evaluate`.
Getestet wird deshalb vor allem die BEDIENUNG (q = Abbruch, r = verwerfen und
wiederholen) und dass ein verworfener Artikel wirklich verschwindet – sonst
verfälschen Fehlmessungen still die Messreihe.

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
