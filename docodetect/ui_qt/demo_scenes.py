"""Synthetische Demo-Szenen für --demo – bewusst Qt-frei (rein numpy/cv2).

Sechs Szenen tragen die komplette Abnahme ohne Hardware: Hintergrund,
Marker (Kalibrierung), Teller 18, Teller 20, Schüssel 14, Randbild
(Rand-Warnung). Physik wie in der echten Box: Objekte sind mit ihrer
APPARENTEN Größe gezeichnet (nominal * Z/(Z-h), Z = 300 mm Kamerahöhe),
die Höhenkompensation des Matchers rechnet auf den Nominal-Ø zurück.

Bewusste Abweichung vom Plan („Teller 27/25“): bei 300 mm Kamerahöhe sind
nur ~37×21 cm Boden sichtbar (README, FOV-Limitierung) – ein 27er-Teller
berührt IMMER den Rand und kann nie gemessen werden. Das Kit nutzt daher
18/20 cm (die größten Größen, die physisch in die Box passen, vgl.
tests/test_pipeline_synthetic.py).

Der Boden ist in ALLEN Szenen pixelidentisch (fester Seed) – wie in der
echten Box, wo derselbe Boden fotografiert wird; nur die Objekte variieren
(Positions-Jitter pro Variante, fürs Einlernen mit echter Streuung).
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

DEMO_MM_PER_PX = 0.2          # Demo-Maßstab: 1920 px -> 384 mm Boden
_Z = 300.0                    # Kamerahöhe mm (wie geometry.camera_height_mm)
_FLOOR_SEED = 42
_FLOOR_FILL = 200


@dataclass(frozen=True)
class DemoArticle:
    article_number: str
    name: str
    scene_name: str
    diameter_mm: float        # Nominal (Stammdaten)
    height_mm: float          # -> apparente Größe in der Szene
    category: str
    fill_bgr: tuple           # Objektfarbe
    rim_bgr: tuple            # Randring


DEMO_ARTICLES = [
    DemoArticle("DEMO-T18", "Teller flach 18", "Teller 18",
                180.0, 10.0, "Teller", (250, 250, 250), (150, 150, 150)),
    DemoArticle("DEMO-T20", "Teller flach 20", "Teller 20",
                200.0, 10.0, "Teller", (245, 245, 245), (160, 160, 160)),
    DemoArticle("DEMO-SCH14", "Schüssel 14", "Schüssel",
                140.0, 60.0, "Schüssel", (230, 190, 150), (170, 120, 80)),
]

SCENE_NAMES = ["Hintergrund", "Marker", "Teller 18", "Teller 20",
               "Schüssel", "Randbild"]


def _floor(w: int, h: int) -> np.ndarray:
    """Boden mit festem Seed – in allen Szenen identisch (siehe Docstring)."""
    rng = np.random.default_rng(_FLOOR_SEED)
    bg = np.full((h, w, 3), _FLOOR_FILL, dtype=np.int16)
    bg += rng.integers(-5, 5, bg.shape, dtype=np.int16)
    return np.clip(bg, 0, 255).astype(np.uint8)


def _apparent_px(art: DemoArticle) -> int:
    apparent_mm = art.diameter_mm * _Z / (_Z - art.height_mm)
    return int(round(apparent_mm / DEMO_MM_PER_PX))


def _jitter(name: str, variant: int, max_px: int = 30) -> tuple:
    """Deterministischer Positions-Jitter pro (Szene, Variante); Variante 0
    liegt zentriert, damit die Vorschau ruhig aussieht."""
    if variant == 0:
        return 0, 0
    rng = np.random.default_rng(abs(hash((name, variant))) % (2 ** 32))
    return (int(rng.integers(-max_px, max_px + 1)),
            int(rng.integers(-max_px, max_px + 1)))


def _draw_dish(img: np.ndarray, art: DemoArticle, center: tuple) -> None:
    r = _apparent_px(art) // 2
    cv2.circle(img, center, r, art.fill_bgr, thickness=-1)
    cv2.circle(img, center, r, art.rim_bgr, thickness=6)
    # Dekorring im Zentrum – gibt der Ring-Zonen-Farbanalyse etwas zu messen
    cv2.circle(img, center, int(r * 0.45), art.rim_bgr, thickness=2)


def _draw_marker(img: np.ndarray, cfg: dict) -> None:
    cal = cfg["calibration"]
    marker_px = int(round(float(cal["marker_size_mm"]) / DEMO_MM_PER_PX))
    d = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, cal["aruco_dict"]))
    marker = cv2.aruco.generateImageMarker(d, int(cal["marker_id"]), marker_px)
    h, w = img.shape[:2]
    x0, y0 = (w - marker_px) // 2, (h - marker_px) // 2
    pad = 80  # weiße Ruhezone, wie beim gedruckten Marker
    cv2.rectangle(img, (x0 - pad, y0 - pad),
                  (x0 + marker_px + pad, y0 + marker_px + pad),
                  (255, 255, 255), thickness=-1)
    img[y0:y0 + marker_px, x0:x0 + marker_px] = cv2.cvtColor(
        marker, cv2.COLOR_GRAY2BGR)


def build_scene(cfg: dict, name: str, variant: int = 0) -> np.ndarray:
    """Eine Szene in Kamera-Auflösung (cfg camera.width/height) rendern."""
    w = int(cfg["camera"]["width"])
    h = int(cfg["camera"]["height"])
    img = _floor(w, h)
    cx, cy = w // 2, h // 2
    by_scene = {a.scene_name: a for a in DEMO_ARTICLES}

    if name == "Hintergrund":
        pass
    elif name == "Marker":
        _draw_marker(img, cfg)
    elif name in by_scene:
        jx, jy = _jitter(name, variant)
        _draw_dish(img, by_scene[name], (cx + jx, cy + jy))
    elif name == "Randbild":
        # Teller 20 weit links – Kontur schneidet den Bildrand
        _draw_dish(img, by_scene["Teller 20"], (300, cy))
    else:
        raise KeyError(f"Unbekannte Demo-Szene: {name!r} (bekannt: {SCENE_NAMES})")
    return img
