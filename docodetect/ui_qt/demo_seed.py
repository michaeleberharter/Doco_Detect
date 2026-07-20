"""Lebenszyklus der Demo-Daten: einlernen und veralteten Stand erkennen.

Die Demo schreibt in eine EIGENE, dauerhafte Ablage (data/demo/, siehe
demo_source.apply_demo_paths). Genau daraus entstand die Regression vom
2026-07-20: Der Stand wurde einmal geseedet und blieb liegen, während sich
die Demo-Definitionen weiterentwickelten. Als Task 7 den Artikel DEMO-T19
und den Radius-Jitter einführte, zeigte die App weiter den alten Stand –

  - DEMO-T19 fehlte           -> "Teller 19/20 (knapp)" fand nur EINEN Kandidaten
  - Einlern-Shots identisch   -> hu_proto_std ~ 0, sigma_eff = Floor 0.15
                              -> z = 111 statt ~2 -> REJECT statt CONFIRM

Die alte Bedingung „seede, wenn noch keine Referenzen da sind" konnte das
nicht sehen: Referenzen waren ja vorhanden, nur veraltete. Deshalb hier ein
Fingerabdruck über die Demo-Definitionen (Artikeltabelle + Zeichen-/Jitter-
Code in demo_scenes.py). Ändert er sich, wird der Demo-Stand verworfen und
neu aufgebaut – die Demo repariert sich selbst, statt still Falsches zu
zeigen.

Qt-frei, damit die Logik ohne Fenster testbar ist.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from docodetect.config import resolve
from docodetect.pipeline import Pipeline, list_articles

from .demo_scenes import DEMO_ARTICLES, build_scene

_MARKER_NAME = "demo_seed.fingerprint"
_ENROLL_VARIANTS = range(1, 6)      # 5 Shots pro Artikel (Streuung fürs Scoring)


def demo_fingerprint() -> str:
    """Kurzer Hash über alles, was den geseedeten Stand bestimmt: die
    Artikeltabelle UND den Quelltext von demo_scenes.py (Zeichnung, Jitter,
    apparente Größen). Bewusst grob – ein geänderter Kommentar löst ein
    unnötiges Neu-Einlernen aus, aber niemals bleibt ein inhaltlich
    veralteter Stand unbemerkt liegen. Falsch-positiv kostet Sekunden,
    falsch-negativ kostet eine falsche Entscheidung im Demo-Modus."""
    h = hashlib.sha256()
    h.update(repr([(a.article_number, a.name, a.scene_name, a.diameter_mm,
                    a.height_mm, a.fill_bgr, a.rim_bgr)
                   for a in DEMO_ARTICLES]).encode("utf-8"))
    scenes_src = Path(__file__).with_name("demo_scenes.py")
    h.update(scenes_src.read_bytes())
    return h.hexdigest()[:32]


def _marker_path(cfg: dict) -> Path:
    """Fingerabdruck liegt neben der Demo-DB – bewusst als Datei und nicht
    als Tabelle: database.py soll später gegen die echte DO&CO-Datenbank
    austauschbar bleiben und darf keine Demo-Spezifika tragen."""
    return resolve(cfg["paths"]["db_file"]).with_name(_MARKER_NAME)


def _read_fingerprint(cfg: dict) -> str | None:
    p = _marker_path(cfg)
    try:
        return p.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _write_fingerprint(cfg: dict, value: str | None = None) -> None:
    p = _marker_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(value if value is not None else demo_fingerprint(),
                 encoding="utf-8")


def seed_needed(cfg: dict) -> tuple:
    """(True, Grund) wenn der Demo-Stand fehlt, unvollständig oder veraltet
    ist. Der Grund ist für die Statusanzeige/Logs gedacht."""
    if _read_fingerprint(cfg) != demo_fingerprint():
        return True, "Demo-Definitionen geändert (oder noch nie eingelernt)"
    have = {a.article_number: a.n_references for a in list_articles(cfg)}
    missing = [a.article_number for a in DEMO_ARTICLES
               if not have.get(a.article_number)]
    if missing:
        return True, f"Referenzen fehlen: {', '.join(missing)}"
    return False, ""


def seed_demo(cfg: dict) -> dict:
    """Demo-Artikel (neu) einlernen – idempotent: ein vorhandener Stand wird
    vorher entfernt, damit ein Re-Seed nach Definitionsänderung möglich ist
    (create_article wirft sonst KeyError). Gelöscht wird ausschließlich, was
    in DEMO_ARTICLES steht (Nummern mit DEMO--Präfix), und immer nur in der
    Demo-Ablage, in die die Demo-Config zeigt.

    Läuft über dieselben Pipeline-Aufrufe wie eine echte Einrichtung; der
    direkte db-Zugriff fürs Aufräumen ist der von CLAUDE.md für
    Setup-Aktionen vorgesehene Weg."""
    pipe = Pipeline(cfg)
    pipe.db.init_schema()
    try:
        for art in DEMO_ARTICLES:
            pipe.db.delete_article(art.article_number)   # alten Stand verwerfen
            for v in _ENROLL_VARIANTS:
                img = build_scene(cfg, art.scene_name, v)
                if v == _ENROLL_VARIANTS[0]:
                    pipe.create_article(
                        img, art.name, article_number=art.article_number,
                        height_mm=art.height_mm, category=art.category)
                else:
                    pipe.enroll(img, art.article_number)
    finally:
        pipe.close()
    _write_fingerprint(cfg)
    return {"kind": "seed", "n": len(DEMO_ARTICLES)}
