"""Deterministisches Smoke-Testset – materialisierte Regressions-Baseline.

Materialisiert die synthetischen Test-Primitiven der Suite
(tests/test_pipeline_synthetic.py: Seed-42-Boden + draw_plate/draw_bar;
tests/test_scoring.py: roter Dekorrand) als Dateien auf Platte:

    data/testset-smoke/<artikelnr>/*.png     (7 Artikel x 2 = 14 Bilder)
    calibration/calibration.json             (echter ArUco-Pfad, ~0,2 mm/px)
    calibration/background.png               (Seed-42-Boden)
    <db_file>                                (frisch eingelernt, je 3 Shots)

Bestehende Kalibrier-/DB-Dateien werden vorher nach *.bak-<zeit>* gesichert
(nie überschrieben). Fester Seed: zwei Läufe erzeugen byteidentische Bilder.

WICHTIG zur Einordnung: Das Juli-Set "smoke-synthetic" (n=14) war nie
eingecheckt und ist nicht rekonstruierbar – dieses Set ist die NEUE
Baseline (User-Entscheidung 2026-07-19), gleiche Größenordnung, neuer
Inhalt. Bewusst enthaltene bekannte Fehlermodi:

- TELLER-200/img_02_rand.png: Objekt am Bildrand -> Segmentierungs-Reject.
- TELLER-180-HOCH: Stammdaten-Höhe 25 mm, Bilder aber FLACH gezeichnet ->
  die Höhenkompensation rechnet ~-15 mm (180 * 275/300 = 165), der wahre
  Artikel fällt aus dem Vorfilter und die Bilder laufen in die erwartete
  Verwechslung mit TELLER-180 ("confidently wrong"-Accept).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from .calibration import run_calibration, save_background
from .config import resolve
from .database import Article, Database
from .pipeline import Pipeline

SEED = 42            # wie tests/test_pipeline_synthetic.make_background
MM_PER_PX = 0.2      # ergibt sich real aus dem Marker (136 mm -> 680 px)
W, H = 1920, 1080
CENTER = (960, 540)

ENROLL_JITTER = (-1, 0, 1)   # px am Radius – Einlern-Shots
TEST_JITTER = (2, 3)         # px – Testbilder, nie identisch mit Einlernen

N_IMAGES = 14


# ---------- Zeichen-Primitive (1:1-Rezepte aus der Testsuite) ----------

def make_background() -> np.ndarray:
    bg = np.full((H, W, 3), 200, dtype=np.uint8)
    noise = np.random.default_rng(SEED).integers(-5, 5, bg.shape, dtype=np.int16)
    return np.clip(bg.astype(np.int16) + noise, 0, 255).astype(np.uint8)


def _radius(d_mm: float, jitter: int) -> int:
    return int(round(d_mm / MM_PER_PX / 2)) + jitter


def draw_plate(bg, d_mm, jitter=0, center=CENTER,
               fill=(250, 250, 250), rim=(150, 150, 150)):
    img = bg.copy()
    r = _radius(d_mm, jitter)
    cv2.circle(img, center, r, fill, -1)
    cv2.circle(img, center, r, rim, 3)
    return img


def draw_red_rim_plate(bg, d_mm, jitter=0):
    """Rote Fahne + weißes Zentrum (tests/test_scoring._red_rim_plate)."""
    img = bg.copy()
    r = _radius(d_mm, jitter)
    cv2.circle(img, CENTER, r, (40, 40, 220), -1)
    cv2.circle(img, CENTER, int(r * 0.62), (250, 250, 250), -1)
    return img


def draw_bar(bg, length_mm, width_mm, jitter=0):
    """Löffel-Ersatz (tests/test_pipeline_synthetic.draw_bar), Jitter wirkt
    auf die Länge (Pendant zum Radius-Jitter der Teller)."""
    img = bg.copy()
    length = int(round(length_mm / MM_PER_PX)) + 2 * jitter
    width = int(round(width_mm / MM_PER_PX))
    x0, y0 = CENTER[0] - length // 2, CENTER[1] - width // 2
    cv2.rectangle(img, (x0, y0), (x0 + length, y0 + width), (170, 170, 170), -1)
    return img


def _marker_scene(img: np.ndarray, cfg: dict) -> np.ndarray:
    """ArUco-Marker in Bildmitte (gleiches Rezept wie ui_qt/demo_scenes) –
    die Kalibrierung läuft über den ECHTEN Pfad, nicht als Konstante."""
    cal = cfg["calibration"]
    mpx = int(round(float(cal["marker_size_mm"]) / MM_PER_PX))
    d = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, cal["aruco_dict"]))
    marker = cv2.aruco.generateImageMarker(d, int(cal["marker_id"]), mpx)
    x0, y0 = (W - mpx) // 2, (H - mpx) // 2
    pad = 80  # weiße Ruhezone wie beim gedruckten Marker
    cv2.rectangle(img, (x0 - pad, y0 - pad), (x0 + mpx + pad, y0 + mpx + pad),
                  (255, 255, 255), -1)
    img[y0:y0 + mpx, x0:x0 + mpx] = cv2.cvtColor(marker, cv2.COLOR_GRAY2BGR)
    return img


# ---------- Set-Definition ----------

@dataclass(frozen=True)
class SmokeArticle:
    article_number: str
    name: str
    category: str
    diameter_mm: float | None
    width_mm: float | None
    depth_mm: float | None
    height_mm: float | None
    draw: object = field(repr=False)  # (bg, jitter) -> Bild


def _teller(d_mm, **kw):
    return lambda bg, j: draw_plate(bg, d_mm, j, **kw)


ARTICLES = [
    SmokeArticle("TELLER-160", "Teller flach 16", "Teller",
                 160.0, None, None, None, _teller(160.0)),
    SmokeArticle("TELLER-180", "Teller flach 18", "Teller",
                 180.0, None, None, None, _teller(180.0)),
    SmokeArticle("TELLER-200", "Teller flach 20", "Teller",
                 200.0, None, None, None, _teller(200.0)),
    SmokeArticle("TELLER-DEKOR-200", "Teller Dekorrand 20", "Teller",
                 200.0, None, None, None,
                 lambda bg, j: draw_red_rim_plate(bg, 200.0, j)),
    # Schüssel: Rand 60 mm über Boden -> in APPARENTER Größe gezeichnet
    # (140 * 300/240 = 175 mm); die Höhenkompensation rechnet zurück.
    SmokeArticle("SCHUESSEL-140", "Schüssel 14", "Schüssel",
                 140.0, None, None, 60.0,
                 _teller(175.0, fill=(230, 190, 150), rim=(170, 120, 80))),
    SmokeArticle("LOEFFEL", "Servierlöffel", "Besteck",
                 None, 150.0, 30.0, None,
                 lambda bg, j: draw_bar(bg, 150.0, 30.0, j)),
    # Die Höhenkompensations-Falle: DB sagt 25 mm hoch, gezeichnet wird
    # flach – bewusst enthaltener Fehlermodus (siehe Modul-Docstring).
    SmokeArticle("TELLER-180-HOCH", "Teller flach 18 (Falsch-Höhe)", "Teller",
                 180.0, None, None, 25.0, _teller(180.0)),
]


# ---------- Erzeugung ----------

def _backup(path: Path) -> Path | None:
    """Vorhandene Datei nach <stem>.bak-<zeit><suffix> verschieben – die
    Namensform hält die bestehenden .gitignore-Muster gültig
    (calibration/*.json, calibration/*.png, *.sqlite3)."""
    if not path.exists():
        return None
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = path.with_name(f"{path.stem}.bak-{ts}{path.suffix}")
    path.rename(bak)
    return bak


def generate(cfg: dict, out_dir: str | Path) -> dict:
    """Testset + Kalibrierung + Hintergrund + eingelernte DB materialisieren.
    Gibt eine Zusammenfassung (Pfade, Zähler, Backups) zurück."""
    out_dir = Path(out_dir)
    backups = []
    for p in (resolve(cfg["calibration"]["file"]),
              resolve(cfg["calibration"]["background_file"]),
              resolve(cfg["paths"]["db_file"])):
        b = _backup(Path(p))
        if b:
            backups.append(b)

    bg = make_background()
    save_background(bg, cfg)
    cal = run_calibration(_marker_scene(bg.copy(), cfg), cfg)

    db = Database(cfg)
    db.init_schema()
    for a in ARTICLES:
        db.create_article(Article(
            article_number=a.article_number, name=a.name, category=a.category,
            diameter_mm=a.diameter_mm, width_mm=a.width_mm, depth_mm=a.depth_mm,
            height_mm=a.height_mm, color_desc=None, notes="smoke-testset"))
    db.close()

    pipe = Pipeline(cfg)
    try:
        for a in ARTICLES:
            for j in ENROLL_JITTER:
                pipe.enroll(a.draw(bg, j), a.article_number)
    finally:
        pipe.close()

    n = 0
    for a in ARTICLES:
        art_dir = out_dir / a.article_number
        art_dir.mkdir(parents=True, exist_ok=True)
        for i, j in enumerate(TEST_JITTER, 1):
            if a.article_number == "TELLER-200" and i == 2:
                # Randfall: Teller ragt links aus dem Bild
                img = draw_plate(bg, 200.0, j, center=(300, 540))
                name = f"img_{i:02d}_rand.png"
            else:
                img = a.draw(bg, j)
                name = f"img_{i:02d}.png"
            cv2.imwrite(str(art_dir / name), img)
            n += 1

    return {"testset_dir": str(out_dir), "n_images": n,
            "n_articles": len(ARTICLES), "mm_per_px": cal.mm_per_px,
            "backups": [str(b) for b in backups]}
