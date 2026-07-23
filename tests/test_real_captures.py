"""Segmentierungs-Backstop auf ECHTEN Aufnahmen aus der Fotobox.

Synthetische Attrappen reproduzieren die Reflexionsstruktur von poliertem
Stahl nicht — diese Tests nageln die Segmentierungsqualitaet auf echten
Besteck-Fotos fest. Sie sind der EINZIGE korpus-unabhaengige Nachweis, dass
`segmentation.py` noch tut, was es soll: der Regressions-Korpus liegt
ausserhalb des Repos, ein Clone hat ihn nicht.

## Warum die Fixtures im Repo liegen

Bis 2026-07-22 lasen diese Tests aus `data/captures/` — einem Verzeichnis,
das seit dem ersten Commit gitignored ist. Fuer jeden Clone, jede CI und
jeden Dritten war der Backstop damit von Anfang an tot: die Tests skippten
sich still weg und die Suite blieb gruen. Auf dieser Maschine starb die
Abdeckung endgueltig am 2026-07-20, als ein Rig-Umbau den alten Bestand
loeschte; die Aufnahmen sind unwiederbringlich.

Deshalb liegen die Goldens jetzt VERSIONIERT unter
`tests/fixtures/golden_captures/` — Szenen, Hintergrund und Manifest
zusammen. Der Hintergrund gehoert zwingend dazu: eine Aufnahme ist nur
vergleichbar, solange sie zur Beleuchtung ihres Hintergrunds passt
(„Era"). Versionierte Aufnahmen gegen einen maschinenlokalen Hintergrund
zu pruefen haette die Bruchstelle nur verschoben.

## Warum FAIL und nicht SKIP

Ein fehlender Backstop ist ein Befund, kein Umstand. Fehlen die Fixtures,
schlaegt `test_golden_fixtures_vollstaendig` laut fehl statt zu skippen.
Dieser Test ist bewusst NICHT parametrisiert: eine Parametrisierung ueber
ein leeres Manifest sammelt null Tests ein und verschwindet lautlos — genau
der Fehlermodus, der hier lange unbemerkt blieb.

Fixtures aufnehmen/erneuern: siehe `docs/2026-07-23-golden-backstop.md`,
Kurzfassung `python scripts/adopt_goldens.py --help`.
"""

import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "golden_captures"
MANIFEST = FIXTURE_DIR / "goldens.json"
SCENES_DIR = FIXTURE_DIR / "scenes"
BACKGROUND = FIXTURE_DIR / "background.png"

AREA_TOL = 0.08            # zulaessige Masken-Drift, darueber = Regression
MIN_STEEL_COVERAGE = 0.93  # Anteil der Stark-Evidenz-Pixel, den die Maske deckt
STRONG_DIFF = 30           # „sicher Objekt"-Grauwertabstand (era-gebunden)
ERA_MEDIAN_MAX = 6         # Median-|diff| Boden gegen Hintergrund

# Die Szenen, die der Backstop abdecken MUSS. Bewusst hier und nicht nur im
# Manifest: waere die Liste allein das Manifest, machte eine Uebernahme von
# 3 statt 19 Szenen die Suite gruen. Eine Szene zu streichen ist damit eine
# bewusste, reviewbare Code-Aenderung — kein Nebeneffekt eines Hardware-Tags.
#
# Auswahlkriterium ist Objektklasse x Fehlermechanismus, NICHT eine runde
# Zahl. Aehnliche Lagen derselben Klasse gelten ausdruecklich nicht als
# redundant: die Segmentierung kalibriert pro Bild selbst, zwei benachbarte
# Lagen koennen verschiedene Kalibrier-Pfade treffen. Redundanz im
# Regressionsnetz ist Marge, kein Ballast.
#
# Nummerierung = Aufnahme-Reihenfolge. Die Leerbox steht bewusst vorn: sie
# wird direkt nach `capture-background` geschossen, solange die Box leer ist.
PFLICHT_SZENEN = (
    "01-leere-box",                    # muss SegmentationError werfen
    "02-teeloeffel-flach",
    "03-teeloeffel-diagonal",
    "04-teeloeffel-gebogen",
    # Bloom-Saum um ein kleines HELLES (poliertes) Objekt: der Saum ist
    # relativ zur Objektflaeche gross, das Annektieren waere hier am
    # verlockendsten. Nicht "matt" — Glow braucht die polierte Oberflaeche
    # (segmentation.py: "bloom glow around a bright object"; matt ist dort
    # die Eigenschaft des BODENS).
    "05-teeloeffel-klein-blank",
    "06-gabel-flach-links",
    "07-gabel-flach-rechts",
    "08-gabel-flach",
    "09-gabel-diagonal",
    "10-gabel-diagonal-spiegelferse",  # Spiegelkeil mit eigener Umriss-Struktur
    "11-gabel-vertikal",               # Spiegelhals, Brueckenfall
    "12-messer-flach",                 # Spiegelstreifen ueber die ganze Klinge
    "13-messer-diagonal",              # Kropf im Spiegel -> Zertrennungsfall
    "14-servierloeffel",
    "15-servierloeffel-flach",
    "16-teller-gross",                 # grossflaechig, Fahne
    "17-teller-randberuehrung",        # FOV-Grenze, touches_border MUSS greifen
    "18-glastasse-transparent",        # Transparent-Annex
    "19-glastasse-transparent-2",
)


def _manifest() -> dict:
    """Manifest lesen; leeres dict, wenn (noch) keins da ist. Fehlt es,
    meldet das der Vollstaendigkeits-Test — nicht jeder einzelne Szenentest."""
    if not MANIFEST.is_file():
        return {}
    try:
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    except ValueError:
        return {}


def _szenen() -> dict:
    return _manifest().get("scenes", {})


_UEBERNAHME = ("Aufnehmen und uebernehmen: docs/2026-07-23-golden-backstop.md "
               "(python scripts/adopt_goldens.py --help)")


def test_golden_fixtures_vollstaendig():
    """Der Backstop selbst. Faellt aus, sobald der Fixture-Satz fehlt,
    unvollstaendig ist oder Dateien vermissen laesst.

    NICHT parametrisiert: dieser Test muss auch dann existieren, wenn es
    keine einzige Szene gibt."""
    if not FIXTURE_DIR.is_dir():
        pytest.fail(
            f"Segmentierungs-Backstop ist tot: {FIXTURE_DIR} fehlt "
            f"vollstaendig. Ohne diese Fixtures prueft NICHTS im Repo die "
            f"Segmentierung auf echten Aufnahmen (der Korpus liegt "
            f"ausserhalb und fehlt jedem Clone). {_UEBERNAHME}")
    if not MANIFEST.is_file():
        pytest.fail(f"Fixture-Manifest fehlt: {MANIFEST}. {_UEBERNAHME}")
    if not BACKGROUND.is_file():
        pytest.fail(
            f"Fixture-Hintergrund fehlt: {BACKGROUND}. Die Szenen sind ohne "
            f"ihren Hintergrund nicht auswertbar — beide gehoeren zusammen "
            f"versioniert. {_UEBERNAHME}")

    szenen = _szenen()
    fehlend = [s for s in PFLICHT_SZENEN if s not in szenen]
    assert not fehlend, (
        f"{len(fehlend)} von {len(PFLICHT_SZENEN)} Pflicht-Szenen fehlen im "
        f"Manifest: {', '.join(fehlend)}. Eine Szene bewusst aufzugeben ist "
        f"erlaubt — dann aber PFLICHT_SZENEN in dieser Datei aendern, mit "
        f"Begruendung im Commit. {_UEBERNAHME}")

    ohne_datei = [s for s in szenen if not (SCENES_DIR / f"{s}.png").is_file()]
    assert not ohne_datei, (
        f"Im Manifest gelistet, aber keine Bilddatei unter {SCENES_DIR}: "
        f"{', '.join(sorted(ohne_datei))}")

    ohne_golden = [s for s, m in szenen.items()
                   if m.get("kind", "segment") in ("segment", "touches_border")
                   and not isinstance(m.get("area_px"), (int, float))]
    assert not ohne_golden, (
        f"Szenen ohne numerisches area_px im Manifest: "
        f"{', '.join(sorted(ohne_golden))}")


def test_scipy_vorhanden():
    """scipy steht in requirements.txt (maximum_flow fuer den Graph-Cut).
    Fehlt es, ist die Umgebung kaputt — kein Grund zu skippen."""
    import scipy  # noqa: F401


def _lade(scene_id: str):
    bg = cv2.imread(str(BACKGROUND))
    img = cv2.imread(str(SCENES_DIR / f"{scene_id}.png"))
    assert bg is not None, f"Hintergrund nicht lesbar: {BACKGROUND}"
    assert img is not None, f"Szene nicht lesbar: {scene_id}"
    return img, bg


def _era_pruefen(scene_id: str, img, bg):
    """Boden der Szene gegen den mitgelieferten Hintergrund.

    Frueher ein SKIP („anderes Beleuchtungs-Setup"), weil der Hintergrund
    maschinenlokal war und wechseln konnte. Jetzt liegen beide im selben
    versionierten Satz — eine Abweichung ist damit ein defekter Fixture-Satz
    und keine Umgebungsfrage."""
    cue = cv2.GaussianBlur(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (3, 3), 0)
    bgc = cv2.GaussianBlur(cv2.cvtColor(bg, cv2.COLOR_BGR2GRAY), (3, 3), 0)
    median = float(np.median(cv2.absdiff(cue, bgc)))
    assert median <= ERA_MEDIAN_MAX, (
        f"{scene_id}: Boden weicht vom mitgelieferten Hintergrund ab "
        f"(Median {median:.1f} > {ERA_MEDIAN_MAX}). Szene und background.png "
        f"stammen aus verschiedenen Beleuchtungs-Eras — der Fixture-Satz ist "
        f"inkonsistent, nicht die Segmentierung.")
    return cue, bgc


def _flaeche_und_abdeckung(scene_id, s, cue, bgc) -> None:
    """Die beiden Kernzusagen jeder messbaren Szene."""
    golden = _szenen()[scene_id]["area_px"]
    assert abs(s.area_px - golden) / golden <= AREA_TOL, (
        f"{scene_id}: Flaeche {s.area_px:.0f} gegen Golden {golden} "
        f"({(s.area_px - golden) / golden:+.1%})")

    strong = cv2.absdiff(cue, bgc) >= STRONG_DIFF
    coverage = float((strong & (s.mask > 0)).sum()) / max(1, int(strong.sum()))
    assert coverage >= MIN_STEEL_COVERAGE, (
        f"{scene_id}: Material-Abdeckung {coverage:.3f} – Objektmaterial verloren")
    assert cv2.contourArea(s.contour) > 0


@pytest.mark.parametrize("scene_id", sorted(
    s for s, m in _szenen().items() if m.get("kind", "segment") == "segment"))
def test_real_capture_segmentation(scene_id):
    from docodetect.segmentation import segment

    img, bg = _lade(scene_id)
    cue, bgc = _era_pruefen(scene_id, img, bg)
    s = segment(img, bg)
    _flaeche_und_abdeckung(scene_id, s, cue, bgc)
    assert not s.touches_border


@pytest.mark.parametrize("scene_id", sorted(
    s for s, m in _szenen().items() if m.get("kind") == "touches_border"))
def test_randberuehrung_wird_erkannt(scene_id):
    """Objekt groesser als das Sichtfeld: `segment()` WIRFT hier nicht, es
    setzt `touches_border` — erst `Pipeline.analyze` macht daraus einen
    Fehler (pipeline.py). Der Backstop haelt genau diese Arbeitsteilung
    fest: erkennt die Segmentierung die Randberuehrung nicht mehr, misst die
    Pipeline stillschweigend ein abgeschnittenes Objekt.

    Flaeche und Abdeckung werden trotzdem geprueft: das Fixture ist ein
    festes Bild, der sichtbare Anteil ist also reproduzierbar."""
    from docodetect.segmentation import segment

    img, bg = _lade(scene_id)
    cue, bgc = _era_pruefen(scene_id, img, bg)
    s = segment(img, bg)
    _flaeche_und_abdeckung(scene_id, s, cue, bgc)
    assert s.touches_border, (
        f"{scene_id}: Randberuehrung NICHT erkannt — die Pipeline wuerde ein "
        f"abgeschnittenes Objekt vermessen statt abzubrechen.")


@pytest.mark.parametrize("scene_id", sorted(
    s for s, m in _szenen().items() if m.get("kind") == "raises"))
def test_leere_box_wirft(scene_id):
    """Eine Aufnahme, die IST der Hintergrund (leere Box), muss werfen statt
    zu messen."""
    from docodetect.segmentation import SegmentationError, segment

    img, bg = _lade(scene_id)
    with pytest.raises(SegmentationError):
        segment(img, bg)
