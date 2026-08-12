"""Pflichttests des Hilfe-Systems — Inhalte (Freigabe Checkpoint 1).

Vier Zusicherungen, alle auf den Markdown-QUELLEN (kein Fenster nötig):
1. Anker-Vollständigkeit in BEIDE Richtungen: jede Zustands-Konstante ist
   gemappt (ANKER) oder begründet ausgenommen (KEIN_ANKER), und jedes
   ANKER-Ziel existiert (Themendatei + H2-Slug). Ein toter Hilfe-Link im
   Fehlermoment ist schlimmer als kein Link.
2. Platzhalter lösen ALLE auf; ein unbekannter Key ist ein Testfehler und
   zur Laufzeit ein sichtbarer Marker, nie ein stiller Leerstring.
3. Sprachfallback: unbekannte Sprache fällt je Datei auf de zurück.
4. Ampel: JEDER Handlungsschritt (Aufzählungspunkt) trägt genau eine der
   drei Klassen GRÜN/GELB/ROT.

PySide6 wird nur für settings.effective_ui gebraucht (QSettings-Ebene der
ui-Platzhalter); die Testinstanz ist eine Ini unter tmp_path — der echte
Benutzer-Scope wird nie berührt (Regel wie test_ui_settings).
"""

import os
import re
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from docodetect.ui_qt.hilfe import anker, texte  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DE_DIR = REPO / "docodetect" / "ui_qt" / "hilfe" / "de"

_AMPEL = re.compile(r"^- (🟢 \*\*GRÜN\*\*|🟡 \*\*GELB\*\*|🔴 \*\*ROT\*\*) — \S")
_QUERVERWEIS = re.compile(r"\(hilfe:([a-z0-9-]+)(?:#([a-z0-9-]+))?\)")


@pytest.fixture(scope="module")
def cfg() -> dict:
    with open(REPO / "config" / "config.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@pytest.fixture()
def eff_ui(cfg, tmp_path):
    from PySide6.QtCore import QSettings

    from docodetect.ui_qt import settings as settings_mod
    leer = QSettings(str(tmp_path / "test.ini"), QSettings.IniFormat)
    return settings_mod.effective_ui(cfg, settings=leer)


def _zustands_konstanten() -> dict:
    """Alle Zustands-Konstanten des Anker-Moduls (GROSSBUCHSTABEN-Namen mit
    String-Wert) — die maßgebliche Liste der erfassten Zustände."""
    return {name: wert for name, wert in vars(anker).items()
            if name.isupper() and isinstance(wert, str)
            and name not in ("SPRACHE",)}


# ---------- 1. Anker-Vollständigkeit (beide Richtungen) ----------

def test_themen_und_dateien_deckungsgleich():
    dateien = {p.stem for p in DE_DIR.glob("*.md")}
    themen = set(anker.ALLE_THEMEN)
    assert dateien == themen, (
        f"nur als Datei: {sorted(dateien - themen)}; "
        f"nur im Register: {sorted(themen - dateien)}")


def test_jeder_zustand_gemappt_oder_begruendet_ausgenommen():
    konstanten = _zustands_konstanten()
    werte = list(konstanten.values())
    assert len(werte) == len(set(werte)), "doppelte Zustands-Werte"
    gemappt = set(anker.ANKER) | set(anker.KEIN_ANKER)
    assert set(werte) == gemappt, (
        f"ohne Zuordnung: {sorted(set(werte) - gemappt)}; "
        f"Zuordnung ohne Konstante: {sorted(gemappt - set(werte))}")
    doppelt = set(anker.ANKER) & set(anker.KEIN_ANKER)
    assert not doppelt, f"gleichzeitig ANKER und KEIN_ANKER: {sorted(doppelt)}"
    for zustand, grund in anker.KEIN_ANKER.items():
        assert grund.strip(), f"Ausnahme ohne Begründung: {zustand}"


def test_jedes_ankerziel_existiert():
    for zustand, (thema, abschnitt) in anker.ANKER.items():
        assert thema in anker.ALLE_THEMEN, (zustand, thema)
        md = texte.lade_thema(thema)
        assert texte.titel(md), f"{thema}: keine H1"
        if abschnitt is not None:
            slugs = texte.abschnitts_slugs(md)
            assert abschnitt in slugs, (
                f"{zustand}: Abschnitt '{abschnitt}' fehlt in {thema}.md "
                f"(vorhanden: {slugs})")


def test_querverweise_zeigen_auf_existierende_ziele():
    for thema in anker.ALLE_THEMEN:
        md = texte.lade_thema(thema)
        for ziel, abschnitt in _QUERVERWEIS.findall(md):
            assert ziel in anker.ALLE_THEMEN, (thema, ziel)
            if abschnitt:
                assert abschnitt in texte.abschnitts_slugs(
                    texte.lade_thema(ziel)), (thema, ziel, abschnitt)


# ---------- 2. Platzhalter ----------

def test_alle_platzhalter_loesen_auf(cfg, eff_ui):
    for thema in anker.ALLE_THEMEN:
        roh = texte.lade_thema(thema)
        aufgeloest, unbekannt = texte.loese_platzhalter(roh, cfg, eff_ui)
        assert unbekannt == [], f"{thema}: unbekannte Keys {unbekannt}"
        assert "{{config:" not in aufgeloest, thema


def test_unbekannter_platzhalter_ist_sichtbar_und_gemeldet(cfg, eff_ui):
    aufgeloest, unbekannt = texte.loese_platzhalter(
        "Wert: {{config:gibts.nicht}}", cfg, eff_ui)
    assert unbekannt == ["gibts.nicht"]
    # Sichtbarer Marker, KEIN stiller Leerstring.
    assert "gibts.nicht" in aufgeloest
    assert aufgeloest != "Wert: "


def test_ui_platzhalter_nutzen_effektive_ebene(cfg, eff_ui):
    aufgeloest, unbekannt = texte.loese_platzhalter(
        "{{config:ui.enroll_shots}}", cfg, eff_ui)
    assert unbekannt == []
    assert aufgeloest == str(eff_ui["enroll_shots"])


# ---------- 3. Sprachfallback ----------

def test_sprachfallback_auf_de():
    de = texte.lade_thema("nicht-gefunden")
    assert texte.lade_thema("nicht-gefunden", sprache="xx") == de


def test_unbekanntes_thema_faellt_laut():
    with pytest.raises(FileNotFoundError):
        texte.lade_thema("gibt-es-nicht")


# ---------- 4. Ampel an jedem Handlungsschritt ----------

def test_jeder_schritt_traegt_eine_ampelklasse():
    verstoesse = []
    for thema in anker.ALLE_THEMEN:
        for nr, zeile in enumerate(texte.lade_thema(thema).splitlines(), 1):
            if zeile.startswith("- ") and not _AMPEL.match(zeile):
                verstoesse.append(f"{thema}.md:{nr}: {zeile[:60]}")
    assert not verstoesse, "Schritte ohne Ampel-Klasse:\n" + "\n".join(verstoesse)


def test_rote_schritte_existieren_und_nennen_die_technik():
    """Die Ampel-Kernregel: ROT kommt vor (die Messgrundlagen-Themen) und
    das Einrichtungs-Thema trägt die Begründung (stiller Wandel der
    Messgrundlage) im Fließtext."""
    einrichtung = texte.lade_thema("einrichtung")
    assert "🔴" in einrichtung
    assert "Messgrundlage" in einrichtung
    rote = [t for t in anker.ALLE_THEMEN if "🔴" in texte.lade_thema(t)]
    assert "masse-daneben" in rote and "nicht-gefunden" in rote
