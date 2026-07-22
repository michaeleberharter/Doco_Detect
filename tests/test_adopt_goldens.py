"""Uebernahme-Helfer fuer die Segmentierungs-Goldens (scripts/adopt_goldens.py).

Laeuft auf einem synthetischen Mini-Fixture: ein gleichmaessiger „Boden" als
Hintergrund und ein heller Block als Objekt. Das reicht NICHT, um
Segmentierungsqualitaet zu pruefen (dafuer gibt es
tests/test_real_captures.py auf echten Aufnahmen) — hier geht es um den
Helfer: Zuordnung parsen, Era abgleichen, Einwaende erheben, Manifest und
Dateien korrekt ablegen. Die Segmentierung laeuft dabei ECHT, damit die
Verdrahtung mitgeprueft wird.
"""

import importlib.util
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_QUELLE = Path(__file__).resolve().parent.parent / "scripts" / "adopt_goldens.py"
_spec = importlib.util.spec_from_file_location("adopt_goldens", _QUELLE)
adopt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(adopt)


# --- synthetisches Mini-Fixture -------------------------------------------

def _boden(hoehe=240, breite=320, wert=90, seed=0):
    rng = np.random.default_rng(seed)
    rauschen = rng.integers(0, 4, (hoehe, breite, 3)).astype(np.uint8)
    return np.full((hoehe, breite, 3), wert, np.uint8) + rauschen


def _mit_objekt(bg):
    img = bg.copy()
    cv2.rectangle(img, (120, 90), (200, 150), (210, 210, 210), -1)
    return img


@pytest.fixture
def fixture_satz(tmp_path):
    """Hintergrund + eine Objekt-Szene + eine Leer-Szene als PNG-Dateien."""
    bg = _boden()
    pfade = {}
    for name, bild in (("bg", bg), ("objekt", _mit_objekt(bg)), ("leer", bg.copy())):
        p = tmp_path / f"{name}.png"
        cv2.imwrite(str(p), bild)
        pfade[name] = p
    return pfade


# --- Zuordnung parsen ------------------------------------------------------

def test_zuordnung_mit_pfad_und_raises(fixture_satz):
    z = adopt.parse_zuordnung([
        f"01-objekt={fixture_satz['objekt']}",
        f"15-leere-box={fixture_satz['leer']}:raises"])
    assert [(s, k) for s, _, k in z] == [("01-objekt", "segment"),
                                         ("15-leere-box", "raises")]
    assert z[0][1] == fixture_satz["objekt"]


def test_zuordnung_ohne_gleichheitszeichen_bricht_ab():
    with pytest.raises(SystemExit, match="keine Zuordnung"):
        adopt.parse_zuordnung(["01-objekt"])


def test_zuordnung_doppelte_szene_bricht_ab(fixture_satz):
    with pytest.raises(SystemExit, match="mehrfach"):
        adopt.parse_zuordnung([f"01-objekt={fixture_satz['objekt']}",
                               f"01-objekt={fixture_satz['leer']}"])


def test_unbekannte_quelle_bricht_ab():
    with pytest.raises(SystemExit, match="nicht gefunden"):
        adopt.parse_zuordnung(["01-objekt=gibtsnicht"])


# --- Messen und Pruefen ----------------------------------------------------

def test_messen_liefert_flaeche_und_erkennt_leere_box(fixture_satz):
    bg = cv2.imread(str(fixture_satz["bg"]))
    z = adopt.parse_zuordnung([
        f"01-objekt={fixture_satz['objekt']}",
        f"15-leere-box={fixture_satz['leer']}:raises"])
    befunde = adopt.messen(z, bg)

    objekt = next(b for b in befunde if b["szene"] == "01-objekt")
    assert objekt["area_px"] > 0 and objekt["fehler"] is None
    leer = next(b for b in befunde if b["szene"] == "15-leere-box")
    assert leer["fehler"] is not None, "leere Box haette werfen muessen"
    assert adopt.pruefen(befunde) == []


def test_era_abstand_verhindert_uebernahme(tmp_path, fixture_satz):
    """Szene aus einer anderen Beleuchtung: der Helfer muss ablehnen, statt
    ein unvergleichbares Golden festzuschreiben."""
    hell = _boden(wert=150, seed=1)
    p = tmp_path / "hell.png"
    cv2.imwrite(str(p), _mit_objekt(hell))
    bg = cv2.imread(str(fixture_satz["bg"]))
    befunde = adopt.messen(adopt.parse_zuordnung([f"01-objekt={p}"]), bg)
    probleme = adopt.pruefen(befunde)
    assert any("Era-Abstand" in x for x in probleme), probleme


def test_raises_deklariert_aber_maske_geliefert(fixture_satz):
    bg = cv2.imread(str(fixture_satz["bg"]))
    befunde = adopt.messen(
        adopt.parse_zuordnung([f"15-leere-box={fixture_satz['objekt']}:raises"]), bg)
    assert any("raises" in x for x in adopt.pruefen(befunde))


def test_segment_deklariert_aber_abgebrochen(fixture_satz):
    bg = cv2.imread(str(fixture_satz["bg"]))
    befunde = adopt.messen(
        adopt.parse_zuordnung([f"01-objekt={fixture_satz['leer']}"]), bg)
    assert any("abgebrochen" in x or "unbrauchbar" in x
               for x in adopt.pruefen(befunde))


# --- Schreiben -------------------------------------------------------------

def test_schreiben_legt_szenen_hintergrund_und_manifest_ab(tmp_path, fixture_satz):
    bg = cv2.imread(str(fixture_satz["bg"]))
    z = adopt.parse_zuordnung([
        f"01-objekt={fixture_satz['objekt']}",
        f"15-leere-box={fixture_satz['leer']}:raises"])
    befunde = adopt.messen(z, bg)
    ziel = tmp_path / "golden_captures"

    adopt.schreiben(befunde, fixture_satz["bg"], ziel=ziel)

    assert (ziel / "background.png").is_file()
    assert (ziel / "scenes" / "01-objekt.png").is_file()
    assert (ziel / "scenes" / "15-leere-box.png").is_file()

    m = json.loads((ziel / "goldens.json").read_text(encoding="utf-8"))
    assert m["background"] == "background.png"
    assert m["scenes"]["01-objekt"]["kind"] == "segment"
    assert m["scenes"]["01-objekt"]["area_px"] > 0
    assert m["scenes"]["15-leere-box"]["kind"] == "raises"
    # Eine raises-Szene hat kein Flaechen-Golden - sonst wuerde
    # test_real_captures sie als unvollstaendig melden.
    assert "area_px" not in m["scenes"]["15-leere-box"]


def test_zweite_uebernahme_ergaenzt_statt_zu_ersetzen(tmp_path, fixture_satz):
    """Nachziehen einer einzelnen Szene darf die uebrigen nicht verlieren —
    sonst kostet eine Korrektur an Szene 7 den ganzen Satz."""
    bg = cv2.imread(str(fixture_satz["bg"]))
    ziel = tmp_path / "golden_captures"
    adopt.schreiben(
        adopt.messen(adopt.parse_zuordnung(
            [f"01-objekt={fixture_satz['objekt']}"]), bg),
        fixture_satz["bg"], ziel=ziel)
    adopt.schreiben(
        adopt.messen(adopt.parse_zuordnung(
            [f"02-objekt={fixture_satz['objekt']}"]), bg),
        fixture_satz["bg"], ziel=ziel)

    m = json.loads((ziel / "goldens.json").read_text(encoding="utf-8"))
    assert set(m["scenes"]) == {"01-objekt", "02-objekt"}


def test_dry_run_schreibt_nichts(tmp_path, fixture_satz, monkeypatch, capsys):
    monkeypatch.setattr(adopt, "ZIEL", tmp_path / "golden_captures")
    code = adopt.main([f"01-objekt={fixture_satz['objekt']}",
                       "--background", str(fixture_satz["bg"]), "--dry-run"])
    assert code == 0
    assert "nichts geschrieben" in capsys.readouterr().out
    assert not (tmp_path / "golden_captures").exists()


def test_main_lehnt_era_abweichung_mit_exit_1_ab(tmp_path, fixture_satz, monkeypatch):
    hell = tmp_path / "hell.png"
    cv2.imwrite(str(hell), _mit_objekt(_boden(wert=150, seed=1)))
    monkeypatch.setattr(adopt, "ZIEL", tmp_path / "golden_captures")
    code = adopt.main([f"01-objekt={hell}",
                       "--background", str(fixture_satz["bg"])])
    assert code == 1
    assert not (tmp_path / "golden_captures").exists()


def test_overlay_dir_schreibt_kontrollbilder(tmp_path, fixture_satz):
    bg = cv2.imread(str(fixture_satz["bg"]))
    overlays = tmp_path / "overlays"
    adopt.messen(adopt.parse_zuordnung([f"01-objekt={fixture_satz['objekt']}"]),
                 bg, overlay_dir=overlays)
    bild = cv2.imread(str(overlays / "01-objekt.png"))
    assert bild is not None and bild.shape == (240, 320, 3)
