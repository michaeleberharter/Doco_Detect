"""SQLite-Portabilitaet der DB-Zeitstempel + Sichtbarkeit der SQLite-Version.

Hintergrund (Windows-Eingang 2026-07-24): unixepoch() gibt es erst ab
SQLite 3.38; die mit Python 3.9 gebuendelte SQLite (Windows-3.9.6 = 3.35.5)
kennt es nicht — macOS verdeckte den Bug ueber seine neuere System-libsqlite.
Diese Tests pinnen den strftime-Ersatz (Wert UND Klasse) und dass die
SQLite-Version ab jetzt im env-Block der metrics.json steht.
"""
from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.corpus.report import umgebung  # noqa: E402
from docodetect.database import Article, Database  # noqa: E402
from docodetect.features import Features  # noqa: E402


def _features(diameter: float) -> Features:
    return Features(
        equiv_diameter_mm=diameter, circle_diameter_mm=diameter,
        area_mm2=3.14159 * (diameter / 2) ** 2, perimeter_mm=3.14159 * diameter,
        circularity=0.9, aspect_ratio=1.0,
        mean_hsv=[0.0, 0.0, 200.0], hue_hist=[1.0 / 32] * 32, mean_saturation=0.0,
        hu_moments=[3.2, 8.0, 10.0, 10.0, 10.0, 10.0, 10.0])


def _db(tmp_path) -> Database:
    db = Database({"paths": {"db_file": str(tmp_path / "t.sqlite3")}})
    db.init_schema()
    return db


def test_timestamps_and_schema_are_portable(tmp_path):
    """Laeuft auf JEDER SQLite (auch < 3.38, kein unixepoch). Zwei Referenzen
    treiben BEIDE reference_stats-Upsert-Zweige (INSERT und ON CONFLICT DO
    UPDATE); created_unix/updated_unix sind ganzzahlige Unix-Sekunden nahe
    jetzt. Zusaetzlich: das gespeicherte Schema einer frischen DB enthaelt
    nirgends 'unixepoch' — pinnt die ganze Klasse, nicht nur den Einzelwert."""
    before = int(time.time())
    db = _db(tmp_path)
    db.create_article(Article(
        article_number="TELLER-1", name="Teller", category=None,
        diameter_mm=200.0, width_mm=None, depth_mm=None, height_mm=None,
        color_desc=None, notes=None))
    try:
        db.add_reference("TELLER-1", _features(199.0))   # reference_stats: INSERT-Zweig
        db.add_reference("TELLER-1", _features(201.0))   # reference_stats: DO-UPDATE-Zweig
        after = int(time.time()) + 1

        created = [r[0] for r in db.conn.execute(
            "SELECT created_unix FROM reference_features "
            "WHERE article_number='TELLER-1'").fetchall()]
        assert len(created) == 2
        for ts in created:
            assert float(ts).is_integer(), f"created_unix nicht ganzzahlig: {ts!r}"
            assert before <= ts <= after, f"created_unix nicht nahe jetzt: {ts!r}"

        updated = db.conn.execute(
            "SELECT updated_unix FROM reference_stats "
            "WHERE article_number='TELLER-1'").fetchone()[0]
        assert float(updated).is_integer(), f"updated_unix nicht ganzzahlig: {updated!r}"
        assert before <= updated <= after, f"updated_unix nicht nahe jetzt: {updated!r}"

        schema_sql = "\n".join(
            (row[0] or "") for row in db.conn.execute(
                "SELECT sql FROM sqlite_master").fetchall())
        assert "unixepoch" not in schema_sql.lower(), (
            "Neu-DB-Schema enthaelt noch unixepoch():\n" + schema_sql)
    finally:
        db.close()


def test_env_block_records_sqlite_version():
    """Die SQLite-Version war der unsichtbare Unterschied Mac<->Windows und
    gehoert ab jetzt in den env-Block der metrics.json (docodetect.corpus.report
    .umgebung)."""
    env = umgebung()
    assert "sqlite_version" in env, f"kein sqlite_version im env-Block: {sorted(env)}"
    assert env["sqlite_version"] == sqlite3.sqlite_version
    teile = env["sqlite_version"].split(".")
    assert len(teile) >= 2 and all(t.isdigit() for t in teile[:2]), (
        f"kein plausibler Versionsstring: {env['sqlite_version']!r}")
