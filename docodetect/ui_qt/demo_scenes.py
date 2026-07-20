"""Synthetische Demo-Szenen für --demo – bewusst Qt-frei (rein numpy/cv2).

Acht Szenen tragen die komplette Abnahme ohne Hardware: Hintergrund,
Marker (Kalibrierung), Teller 18, Teller 19, Teller 20, Schüssel 14,
Randbild (Rand-Warnung), Teller 19/20 (knapp) und Unbekanntes Objekt
(je ein erzwungener Entscheidungspfad, Spec 2026-07-20: CONFIRM/NO_MATCH).
Physik wie in der echten Box: Objekte sind mit ihrer APPARENTEN Größe
gezeichnet (nominal * Z/(Z-h), Z = 300 mm Kamerahöhe), die
Höhenkompensation des Matchers rechnet auf den Nominal-Ø zurück.

Bewusste Abweichung vom Plan („Teller 27/25“): bei 300 mm Kamerahöhe sind
nur ~37×21 cm Boden sichtbar (README, FOV-Limitierung) – ein 27er-Teller
berührt IMMER den Rand und kann nie gemessen werden. Das Kit nutzt daher
18/19/20 cm (die größten Größen, die physisch in die Box passen, vgl.
tests/test_pipeline_synthetic.py).

Der Boden ist in ALLEN Szenen pixelidentisch (fester Seed) – wie in der
echten Box, wo derselbe Boden fotografiert wird; nur die Objekte variieren
(Positions-Jitter pro Variante, fürs Einlernen mit echter Streuung).

Bewusste Abweichung vom Plan (Spec 2026-07-20, Task 7): TELLER-19 hat
height_mm=10.0 statt der geplanten 0 – bei Höhe 0 würde die Höhen-
kompensation des Matchers (features.height_corrected_scale) TELLER-20
(bestehend, height_mm=10.0) aus dem Vorfilter der „knapp"-Szene werfen
(corrected_d weicht 11,5 mm statt 5 mm vom Nominal-Ø ab, > 6-mm-Toleranz)
– das geforderte AMBIGUOUS mit BEIDEN Kandidaten wäre für keine
Zeichengröße erreichbar. Mit identischer Rim-Höhe wie TELLER-18/-20
liefert die Höhenkorrektur für beide Kandidaten symmetrisch 5 mm Abstand.
"""

from __future__ import annotations

import zlib
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
    DemoArticle("DEMO-T19", "Teller flach 19", "Teller 19",
                190.0, 10.0, "Teller", (248, 248, 248), (155, 155, 155)),
    DemoArticle("DEMO-T20", "Teller flach 20", "Teller 20",
                200.0, 10.0, "Teller", (245, 245, 245), (160, 160, 160)),
    DemoArticle("DEMO-SCH14", "Schüssel 14", "Schüssel",
                140.0, 60.0, "Schüssel", (230, 190, 150), (170, 120, 80)),
]

# Zwei zusätzliche Szenen erzwingen je einen Entscheidungspfad (Spec
# 2026-07-20), unabhängig von der Artikel-Seed-Liste – sie zeichnen
# denselben Teller-Typ (Farbe/Zeichenweise wie DEMO-T18/-T20), nur mit
# einer anderen apparenten Zielgröße:
#  - "Teller 19/20 (knapp)": nominal 195 mm, dieselbe Rim-Höhe (10 mm) wie
#    DEMO-T19/-T20 -> nach Höhenkorrektur exakt 5 mm Abstand zu BEIDEN
#    Nominal-Ø (190/200), je innerhalb der ±6-mm-Toleranz.
#  - "Unbekanntes Objekt": 120 mm, 70 mm vom nächsten Artikel (190) entfernt
#    -> leerer Vorfilter.
_KNAPP_ART = DemoArticle("DEMO-KNAPP", "Teller (knapp 195)",
                         "Teller 19/20 (knapp)", 195.0, 10.0, "Teller",
                         (247, 247, 247), (157, 157, 157))
_UNKNOWN_ART = DemoArticle("DEMO-UNBEKANNT", "Unbekanntes Objekt",
                           "Unbekanntes Objekt", 120.0, 0.0, "Teller",
                           (247, 247, 247), (157, 157, 157))

SCENE_NAMES = ["Hintergrund", "Marker", "Teller 18", "Teller 20",
               "Schüssel", "Randbild", "Teller 19/20 (knapp)",
               "Unbekanntes Objekt"]


def _floor(w: int, h: int) -> np.ndarray:
    """Boden mit festem Seed – in allen Szenen identisch (siehe Docstring)."""
    rng = np.random.default_rng(_FLOOR_SEED)
    bg = np.full((h, w, 3), _FLOOR_FILL, dtype=np.int16)
    bg += rng.integers(-5, 5, bg.shape, dtype=np.int16)
    return np.clip(bg, 0, 255).astype(np.uint8)


def _apparent_px(art: DemoArticle) -> int:
    apparent_mm = art.diameter_mm * _Z / (_Z - art.height_mm)
    return int(round(apparent_mm / DEMO_MM_PER_PX))


def _jitter(name: str, variant: int, max_x: int, max_y: int) -> tuple:
    """Deterministischer Positions-Jitter pro (Szene, Variante); Variante 0
    liegt zentriert, damit die Vorschau ruhig aussieht. Die Grenzen kommen
    vom Aufrufer (objektgrößen-bewusst): ein Teller 20 hat bei 1080 px Höhe
    nur ~23 px Luft – blinder ±30-px-Jitter würde ihn über den Rand schieben
    und die Einlern-Shots als Randberührung scheitern lassen.

    Liefert zusätzlich einen kleinen Radius-Jitter (+-3 px, dritter
    Rückgabewert, EIGENER RNG – siehe unten): ohne ihn sind alle 5
    Einlern-Varianten eines Artikels im Ø pixelidentisch (Jitter bewegt
    bisher nur die Position) -> der Hu-Moment-Prototyp (proto_std) friert
    auf 0 ein. Bei den fast perfekten synthetischen Kreisen sind die
    log-transformierten Hu-Momente 6/7 nahe eines Rohwerts von 0 numerisch
    instabil (Vorzeichen kippt bei +-1 px); mit proto_std=0 bleibt nur der
    sigma_floor (0.15) im Nenner -> jedes Zwischenbild reißt den z-Gate.
    Gleiche Idee wie smoke_testset.ENROLL_JITTER = (-1, 0, 1) fürs
    Einlernen dort.

    Der Radius-Jitter nutzt bewusst eine EIGENE, über zlib.crc32 auf dem
    UTF-8-Bytestring geseedete RNG statt (wie die Position) Pythons
    eingebautes hash(): Strings hashen dort per Default prozess-
    randomisiert (PYTHONHASHSEED), d.h. `hash((name, variant))` liefert
    bei jedem Interpreter-Start einen anderen Wert. Für die Position war
    das bisher folgenlos (kein Test/Matcher-Pfad hängt an einem exakten
    Positionswert); der Radius bestimmt aber direkt Ø/Hu-Momente/Gate-
    Ergebnis – ein von Lauf zu Lauf anderer Wert würde Tests/Demo-
    Erwartungen zufällig kippen lassen. crc32 ist ein fester Algorithmus
    und liefert denselben Seed in jedem Prozess. (Die Positions-RNG bleibt
    unverändert an hash(), um bestehende, an die exakten Positionswerte
    gebundene Erwartungen nicht zu verschieben – siehe Task-7-Bericht.)"""
    if variant == 0:
        return 0, 0, 0
    rng = np.random.default_rng(abs(hash((name, variant))) % (2 ** 32))
    jx = int(rng.integers(-max_x, max_x + 1)) if max_x > 0 else 0
    jy = int(rng.integers(-max_y, max_y + 1)) if max_y > 0 else 0
    r_seed = zlib.crc32(f"{name}:{variant}:radius".encode("utf-8")) % (2 ** 32)
    jr = int(np.random.default_rng(r_seed).integers(-3, 4))
    return jx, jy, jr


def _draw_dish(img: np.ndarray, art: DemoArticle, center: tuple,
               radius_jitter_px: int = 0) -> None:
    r = _apparent_px(art) // 2 + radius_jitter_px
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
        art = by_scene[name]
        r = _apparent_px(art) // 2
        margin = 12  # Mindestabstand zum Rand, sonst Randberührungs-Reject
        max_x = max(0, min(30, w // 2 - r - margin))
        max_y = max(0, min(30, h // 2 - r - margin))
        jx, jy, jr = _jitter(name, variant, max_x, max_y)
        _draw_dish(img, art, (cx + jx, cy + jy), radius_jitter_px=jr)
    elif name == "Randbild":
        # Teller 20 weit links – Kontur schneidet den Bildrand
        _draw_dish(img, by_scene["Teller 20"], (300, cy))
    elif name == "Teller 19/20 (knapp)":
        # Spec 2026-07-20: erzwingt CONFIRM (knappes Fenster)
        _draw_dish(img, _KNAPP_ART, (cx, cy))
    elif name == "Unbekanntes Objekt":
        # Spec 2026-07-20: erzwingt NO_MATCH (ausserhalb aller Toleranzen)
        _draw_dish(img, _UNKNOWN_ART, (cx, cy))
    else:
        raise KeyError(f"Unbekannte Demo-Szene: {name!r} (bekannt: {SCENE_NAMES})")
    return img
