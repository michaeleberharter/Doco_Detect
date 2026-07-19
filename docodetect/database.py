"""SQLite persistence: article master data + enrolled reference features.

Two tables:

articles           – master data. Map/export your DO&CO database into the
                     CSV schema (see data/articles_example.csv) and import.
reference_features – one row per enrolled photo of an article (Features as
                     JSON). Used by the matcher for color/shape comparison.

Why SQLite: zero-ops, single file, plenty fast for thousands of articles.
Swap for the real company DB later by reimplementing this module's API.
"""

from __future__ import annotations

import csv
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .config import resolve
from .features import EnrollmentStats, Features, compute_enrollment_stats

# German umlauts -> ASCII, so auto-generated article numbers stay clean keys.
_UMLAUT_MAP = str.maketrans({
    "ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss",
})


def _slug(name: str) -> str:
    """Uppercase ASCII slug of a free-text name, usable as an article_number."""
    s = name.strip().translate(_UMLAUT_MAP)
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").upper()
    return s or "ARTIKEL"

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY,
    article_number TEXT UNIQUE NOT NULL,   -- key used everywhere in the CLI
    name TEXT NOT NULL,
    category TEXT,                         -- Teller / Schuessel / Tasse / ...
    diameter_mm REAL,                      -- nominal, from master data
    width_mm REAL,                         -- for non-round items
    depth_mm REAL,
    height_mm REAL,                        -- IMPORTANT: used for height compensation
    color_desc TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS reference_features (
    id INTEGER PRIMARY KEY,
    article_number TEXT NOT NULL REFERENCES articles(article_number),
    image_path TEXT,
    features_json TEXT NOT NULL,
    created_unix REAL DEFAULT (unixepoch())
);
CREATE INDEX IF NOT EXISTS idx_ref_article ON reference_features(article_number);

CREATE TABLE IF NOT EXISTS reference_stats (
    article_number TEXT PRIMARY KEY REFERENCES articles(article_number),
    stats_json TEXT NOT NULL,
    updated_unix REAL DEFAULT (unixepoch())
);
"""

CSV_COLUMNS = ["article_number", "name", "category", "diameter_mm", "width_mm",
               "depth_mm", "height_mm", "color_desc", "notes"]


@dataclass
class Article:
    article_number: str
    name: str
    category: str | None
    diameter_mm: float | None
    width_mm: float | None
    depth_mm: float | None
    height_mm: float | None
    color_desc: str | None
    notes: str | None


class Database:
    def __init__(self, cfg: dict):
        self.path = resolve(cfg["paths"]["db_file"])
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row

    def init_schema(self) -> None:
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        # Migration for pre-stats databases: reference_stats is a pure cache
        # over reference_features, so a full rebuild is always safe.
        n = self.recompute_all_stats()
        print(f"[db] schema ready at {self.path}"
              + (f" ({n} Artikel-Statistiken aktualisiert)" if n else ""))

    # ---------- articles ----------

    def import_articles_csv(self, csv_path: str | Path) -> int:
        """Import/update articles from CSV (upsert on article_number)."""
        n = 0
        with open(csv_path, newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            missing = set(["article_number", "name"]) - set(reader.fieldnames or [])
            if missing:
                raise ValueError(f"CSV missing required columns: {missing}. "
                                 f"Expected columns: {CSV_COLUMNS}")
            for row in reader:
                vals = {c: (row.get(c) or None) for c in CSV_COLUMNS}
                for num_col in ("diameter_mm", "width_mm", "depth_mm", "height_mm"):
                    if vals[num_col] is not None:
                        vals[num_col] = float(str(vals[num_col]).replace(",", "."))
                self.conn.execute(
                    f"""INSERT INTO articles ({",".join(CSV_COLUMNS)})
                        VALUES ({",".join(":" + c for c in CSV_COLUMNS)})
                        ON CONFLICT(article_number) DO UPDATE SET
                        {",".join(f"{c}=excluded.{c}" for c in CSV_COLUMNS[1:])}""",
                    vals,
                )
                n += 1
        self.conn.commit()
        print(f"[db] imported/updated {n} articles from {csv_path}")
        return n

    def create_article(self, article: Article) -> None:
        """Insert one brand-new article (master data), e.g. created live from a
        camera measurement instead of a CSV. Raises if the number already
        exists – use import_articles_csv for upserts."""
        if self.get_article(article.article_number) is not None:
            raise KeyError(f"Article '{article.article_number}' already exists.")
        self.conn.execute(
            f"""INSERT INTO articles ({",".join(CSV_COLUMNS)})
                VALUES ({",".join(":" + c for c in CSV_COLUMNS)})""",
            {c: getattr(article, c) for c in CSV_COLUMNS},
        )
        self.conn.commit()

    def delete_article(self, article_number: str) -> bool:
        """Remove an article AND all its enrolled reference features – e.g. a
        live-created article whose measurement turned out wrong. Reference
        photos on disk (data/reference/<nr>/) are kept. Returns True if the
        article existed."""
        self.conn.execute(
            "DELETE FROM reference_features WHERE article_number = ?", (article_number,)
        )
        self.conn.execute(
            "DELETE FROM reference_stats WHERE article_number = ?", (article_number,)
        )
        cur = self.conn.execute(
            "DELETE FROM articles WHERE article_number = ?", (article_number,)
        )
        self.conn.commit()
        return cur.rowcount > 0

    def generate_article_number(self, name: str, prefix: str = "") -> str:
        """Derive a unique article_number from a free-text name, appending
        -2, -3, ... on collision."""
        base = f"{prefix}{_slug(name)}"
        candidate, n = base, 1
        while self.get_article(candidate) is not None:
            n += 1
            candidate = f"{base}-{n}"
        return candidate

    def get_article(self, article_number: str) -> Article | None:
        row = self.conn.execute(
            "SELECT * FROM articles WHERE article_number = ?", (article_number,)
        ).fetchone()
        return self._to_article(row) if row else None

    def all_articles(self) -> list[Article]:
        rows = self.conn.execute("SELECT * FROM articles ORDER BY article_number").fetchall()
        return [self._to_article(r) for r in rows]

    @staticmethod
    def _to_article(row: sqlite3.Row) -> Article:
        return Article(
            article_number=row["article_number"], name=row["name"],
            category=row["category"], diameter_mm=row["diameter_mm"],
            width_mm=row["width_mm"], depth_mm=row["depth_mm"],
            height_mm=row["height_mm"], color_desc=row["color_desc"],
            notes=row["notes"],
        )

    # ---------- reference features ----------

    def add_reference(self, article_number: str, features: Features,
                      image_path: str | None = None) -> None:
        if self.get_article(article_number) is None:
            raise KeyError(f"Unknown article_number '{article_number}' – import it first.")
        self.conn.execute(
            "INSERT INTO reference_features (article_number, image_path, features_json) "
            "VALUES (?, ?, ?)",
            (article_number, image_path, features.to_json()),
        )
        self._recompute_stats(article_number)
        self.conn.commit()

    def references_for(self, article_number: str) -> list[Features]:
        rows = self.conn.execute(
            "SELECT features_json FROM reference_features WHERE article_number = ?",
            (article_number,),
        ).fetchall()
        return [Features.from_json(r["features_json"]) for r in rows]

    def articles_with_references(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT article_number FROM reference_features"
        ).fetchall()
        return [r["article_number"] for r in rows]

    def reference_counts(self) -> dict:
        """article_number -> Anzahl Referenzen (eine Abfrage, fürs UI-Listing)."""
        rows = self.conn.execute(
            "SELECT article_number, COUNT(*) AS n FROM reference_features "
            "GROUP BY article_number"
        ).fetchall()
        return {r["article_number"]: r["n"] for r in rows}

    # ---------- enrollment statistics (cache over reference_features) ----------

    def _recompute_stats(self, article_number: str) -> None:
        """reference_stats is a pure cache over reference_features – rebuilt on
        every change so it can never go stale. Does not commit."""
        feats = self.references_for(article_number)
        if not feats:
            self.conn.execute(
                "DELETE FROM reference_stats WHERE article_number = ?",
                (article_number,))
            return
        self.conn.execute(
            "INSERT INTO reference_stats (article_number, stats_json) VALUES (?, ?) "
            "ON CONFLICT(article_number) DO UPDATE SET stats_json=excluded.stats_json, "
            "updated_unix=unixepoch()",
            (article_number, compute_enrollment_stats(feats).to_json()))

    def stats_for(self, article_number: str) -> EnrollmentStats | None:
        row = self.conn.execute(
            "SELECT stats_json FROM reference_stats WHERE article_number = ?",
            (article_number,)).fetchone()
        return EnrollmentStats.from_json(row["stats_json"]) if row else None

    def recompute_all_stats(self) -> int:
        nrs = self.articles_with_references()
        for nr in nrs:
            self._recompute_stats(nr)
        self.conn.commit()
        return len(nrs)

    def close(self) -> None:
        self.conn.close()
