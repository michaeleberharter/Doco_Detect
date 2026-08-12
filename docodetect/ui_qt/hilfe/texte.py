"""Laden und Aufbereiten der Hilfetexte. Qt-frei.

- Markdown-Paketdaten über importlib.resources (KEINE CWD-relativen
  Pfade — der Kiosk-Autostart läuft aus beliebigem Arbeitsverzeichnis).
- Sprachauflösung: <aktive Sprache> -> "de" als Fallback, je Datei.
- Platzhalter {{config:pfad.zum.key}} werden aus der LAUFENDEN Config
  gefüllt (Freigabe Checkpoint 1): ui.* aus dem effektiven ui-Dict
  (QSettings-Ebene inklusive), alles andere aus dem cfg-Dict der App —
  damit zeigen die Texte, was WIRKT, auch unter --config/--sandbox/--demo.
  Ein unbekannter Key wird SICHTBAR markiert, nie zum Leerstring.
"""

from __future__ import annotations

import re
from importlib.resources import files

SPRACHE = "de"          # aktive Sprache; Struktur ist mehrsprachig angelegt

_PLATZHALTER = re.compile(r"\{\{config:([A-Za-z0-9_.]+)\}\}")
_UMLAUTE = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
                          "Ä": "ae", "Ö": "oe", "Ü": "ue"})


def slug(text: str) -> str:
    """Deterministischer Abschnitts-Slug einer Überschrift.
    »Kalibrierung geändert« -> »kalibrierung-geaendert«."""
    t = text.strip().translate(_UMLAUTE).lower()
    t = re.sub(r"[^a-z0-9]+", "-", t)
    return t.strip("-")


def lade_thema(thema: str, sprache: str = SPRACHE) -> str:
    """Rohes Markdown eines Themas; fällt je Datei auf »de« zurück."""
    kandidaten = [sprache] if sprache == "de" else [sprache, "de"]
    wurzel = files(__package__)
    for lang in kandidaten:
        pfad = wurzel / lang / f"{thema}.md"
        try:
            return pfad.read_text(encoding="utf-8")
        except (FileNotFoundError, NotADirectoryError):
            continue
    raise FileNotFoundError(
        f"Hilfethema '{thema}' fehlt (gesucht: {kandidaten})")


def titel(markdown: str) -> str:
    """Erste H1 des Textes — die eine Quelle für den Navigationstitel."""
    for zeile in markdown.splitlines():
        if zeile.startswith("# "):
            return zeile[2:].strip()
    return ""


def abschnitts_slugs(markdown: str) -> list[str]:
    """Slugs aller H2-Überschriften (die gültigen Sub-Anker)."""
    return [slug(z[3:]) for z in markdown.splitlines() if z.startswith("## ")]


def _formatiert(wert) -> str:
    """Anzeigeform eines Config-Werts: deutsche Kommazahl, sonst str."""
    if isinstance(wert, bool):
        return "an" if wert else "aus"
    if isinstance(wert, float):
        return f"{wert:g}".replace(".", ",")
    return str(wert)


def _nachschlagen(pfad: str, cfg: dict, ui: dict):
    """ui.* aus dem effektiven ui-Dict, alles andere per Punktpfad aus cfg.
    -> Wert oder KeyError."""
    if pfad.startswith("ui."):
        feld = pfad[3:]
        if feld not in ui:
            raise KeyError(pfad)
        return ui[feld]
    teil = cfg
    for schluessel in pfad.split("."):
        if not isinstance(teil, dict) or schluessel not in teil:
            raise KeyError(pfad)
        teil = teil[schluessel]
    return teil


def loese_platzhalter(text: str, cfg: dict, ui: dict) -> tuple[str, list[str]]:
    """{{config:...}} ersetzen. -> (aufgelöster Text, unbekannte Pfade).

    Unbekannte Keys bleiben SICHTBAR im Text stehen (»⟨unbekannter
    Config-Schlüssel: …⟩«) — der Pflichttest macht daraus einen Fehler,
    zur Laufzeit fällt es dem Leser auf statt still zu fehlen."""
    unbekannt: list[str] = []

    def _ersetze(m: re.Match) -> str:
        pfad = m.group(1)
        try:
            return _formatiert(_nachschlagen(pfad, cfg, ui))
        except KeyError:
            unbekannt.append(pfad)
            return f"⟨unbekannter Config-Schlüssel: {pfad}⟩"

    return _PLATZHALTER.sub(_ersetze, text), unbekannt


def platzhalter_pfade(markdown: str) -> list[str]:
    """Alle {{config:...}}-Pfade eines Textes (für die Pflichttests)."""
    return _PLATZHALTER.findall(markdown)
