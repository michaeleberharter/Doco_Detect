"""testset-build: bewertete Report-JSONs zu Buendeln einfrieren.

Liest Reports aus paths.captures_dir (oder --quelle), legt jede Aufnahme
unter ihrem WAHREN Artikel ab (aus der Bewertung, nie aus der Vorhersage)
und friert je Zustands-Fingerprint EINEN Snapshot ein.

Regeln (Spec, Freigabe 2026-08-12):
- Ohne Bewertung, "Falsch" ohne wahren Artikel, ohne zustand-Block, ohne
  verlustfreies PNG: ueberspringen und ZAEHLEN, nie raten.
- Widersprueche (gleiches Bild mit zwei Wahrheiten, Label ohne
  DB-Artikel) werden GEMELDET, nicht aufgeloest — die Aufnahme bleibt
  draussen, der Befund steht im Ergebnis.
- Pflicht-Eingangstest je Aufnahme: der Fidelity-Check (Nachrechnung von
  matcher.match auf dem gespeicherten measured-Block) laeuft gegen den
  BUENDEL-Zustand — Nominalwerte zum Report-Zeitpunkt, nie heutige
  Stammdaten (Vorbild scripts/corpus_fidelity_check.py, dort gegen den
  Live-Zustand).
"""

from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from ..calibration import Calibration
from ..config import resolve
from ..corpus.manifest import sha256_file
from ..corpus.runner import code_fingerprint
from ..database import Database
from ..features import Features
from ..matcher import match
from ..pipeline import aufnahme_zustand
from ..reporting import NO_MATCH, load_reports
from .manifest import NO_MATCH_ARTIKEL, CaptureEntry, TestsetManifest, testset_root
from .snapshot import friere_snapshot_ein, lade_zustand, pruefe_snapshot, \
    snapshot_cfg, snapshot_dir

# Toleranz der llr-Nachrechnung — wie scripts/corpus_fidelity_check.py.
_LLR_TOL = 1e-3


def _wahrheit(rep) -> tuple:
    """(wahrer Artikel, Label-Herkunft) oder (None, Ueberspring-Grund)."""
    if rep.verdict == "correct":
        if not rep.label:
            return None, "bewertet_ohne_label"
        return rep.label, "verdict-richtig"
    if rep.verdict == "wrong":
        if not rep.label:
            return None, "falsch_ohne_artikel"
        return rep.label, "verdict-falsch+artikel"
    if rep.label:
        return rep.label, "evaluate-label"
    return None, "unbewertet"


def _artikel_in_db(db_pfad: Path, artikel: str) -> bool:
    con = sqlite3.connect(f"file:{db_pfad}?mode=ro", uri=True)
    try:
        return con.execute(
            "SELECT 1 FROM articles WHERE article_number = ?",
            (artikel,)).fetchone() is not None
    finally:
        con.close()


def _fidelity_gruende(rep, bcfg: dict, db: Database,
                      cal: Calibration) -> list:
    """Nachrechnung gegen den Buendel-Zustand. [] = exakt reproduziert.
    Leerer measured-Block (Segmentierungs-Reject) hat nichts nachzurechnen
    — der Wert solcher Aufnahmen liegt im Replay der Segmentierung."""
    if not rep.measured:
        return []
    nach = match(Features(**rep.measured), db, cal, bcfg, label=rep.label)
    gruende = []
    if nach.decision != rep.decision:
        gruende.append(f"decision {rep.decision}->{nach.decision}")
    alt_top = rep.candidates[0].article_number if rep.candidates else None
    neu_top = nach.candidates[0].article_number if nach.candidates else None
    if alt_top != neu_top:
        gruende.append(f"top1 {alt_top}->{neu_top}")
    if (rep.llr_margin is None) != (nach.llr_margin is None):
        gruende.append(f"llr {rep.llr_margin}->{nach.llr_margin}")
    elif rep.llr_margin is not None \
            and abs(nach.llr_margin - rep.llr_margin) >= _LLR_TOL:
        gruende.append(f"llr {rep.llr_margin}->{round(nach.llr_margin, 4)}")
    return gruende


def build_testset(cfg: dict, quelle=None, dry_run: bool = False) -> dict:
    """Ergebnis-dict: aufgenommen/uebersprungen (Grund -> n)/befunde/
    snapshots_neu. Befunde sind Meldungen, keine Entscheidungen."""
    root = testset_root(cfg)
    quelle = Path(quelle) if quelle else resolve(cfg["paths"]["captures_dir"])
    # Chronologisch (Capture-Namen sind Zeitstempel) — stabile Reihenfolge,
    # stabiler Erstbefund bei Widerspruechen.
    reports = list(reversed(load_reports(quelle, sort_by="name")))

    manifest = TestsetManifest.load()
    bekannte = manifest.by_sha()

    live = None            # Live-Zustand, einmal berechnet wenn gebraucht
    code_fp = code_fingerprint()
    fidelity_ctx: dict = {}   # fp12 -> (bcfg, Database, Calibration)

    aufgenommen = 0
    uebersprungen: dict = {}
    befunde: list = []
    snapshots_neu: list = []

    def skip(grund: str, meldung: str | None = None) -> None:
        uebersprungen[grund] = uebersprungen.get(grund, 0) + 1
        if meldung:
            befunde.append(meldung)

    try:
        for pfad, rep in reports:
            wahrheit, herkunft = _wahrheit(rep)
            if wahrheit is None:
                skip(herkunft)
                continue
            artikel = NO_MATCH_ARTIKEL if wahrheit == NO_MATCH else wahrheit

            z = rep.zustand
            if not z or "fingerprint" not in z:
                grund = (z or {}).get("fehler")
                skip("ohne_zustand",
                     f"{pfad.name}: kein zustand-Block"
                     + (f" ({grund})" if grund else "")
                     + " — Report aus der Zeit vor dem Schreibpfad-Fix oder "
                       "Provenienz-Fehler; wird nie rekonstruiert.")
                continue

            if not rep.image_path:
                skip("ohne_bild")
                continue
            bild = Path(rep.image_path)
            if not bild.is_file():
                skip("bild_fehlt", f"{pfad.name}: {bild.name} fehlt auf Platte")
                continue
            if bild.suffix.lower() != ".png":
                skip("kein_png",
                     f"{pfad.name}: {bild.name} ist kein verlustfreies PNG — "
                     f"nicht exakt nachrechenbar (docs/2026-08-12-qt-captures-"
                     f"jpg-verlustbehaftet.md)")
                continue

            fp12 = z["fingerprint"][:12]
            if not snapshot_dir(root, fp12).is_dir():
                if live is None:
                    db_live = Database(cfg)
                    try:
                        live = aufnahme_zustand(cfg, db_live)
                    finally:
                        db_live.close()
                if live["fingerprint"] != z["fingerprint"]:
                    komponenten = [k for k in ("calibration_sha256",
                                               "background_sha256",
                                               "db_zustand_sha256",
                                               "features_cfg_sha256",
                                               "matching_cfg_sha256")
                                   if live.get(k) != z.get(k)]
                    skip("zustand_nicht_mehr_vorhanden",
                         f"{pfad.name}: Aufnahmezustand {fp12} existiert "
                         f"nicht mehr (abweichend: {', '.join(komponenten)}; "
                         f"mm_per_px damals {z.get('mm_per_px')}, heute "
                         f"{live.get('mm_per_px')}) — Snapshot haette vor der "
                         f"Aenderung eingefroren werden muessen.")
                    continue
                if dry_run:
                    skip("dry_run_snapshot_fehlt")
                    continue
                friere_snapshot_ein(cfg, root, z, code_fp)
                snapshots_neu.append(fp12)
                manifest.snapshots[fp12] = {
                    "fingerprint": z["fingerprint"],
                    "eingefroren": datetime.now().isoformat(timespec="seconds"),
                    "system": z.get("system"),
                    "plattform": z.get("plattform"),
                    "python": z.get("python"),
                    "opencv": z.get("opencv"),
                    "numpy": z.get("numpy"),
                    "camera_backend_override": z.get("camera_backend_override"),
                    "code_fingerprint": code_fp,
                    "mm_per_px": z.get("mm_per_px"),
                    "camera_height_mm": z.get("camera_height_mm"),
                }
            else:
                intakt = pruefe_snapshot(root, fp12)
                if intakt:
                    skip("snapshot_defekt",
                         f"{pfad.name}: Snapshot {fp12} inkonsistent: "
                         f"{'; '.join(intakt)}")
                    continue

            sha = sha256_file(bild)
            if sha in bekannte:
                alt = bekannte[sha]
                if alt.artikel == artikel:
                    skip("dublette")
                else:
                    skip("widerspruch_label",
                         f"{pfad.name}: Bild {sha[:8]} steht bereits als "
                         f"'{alt.artikel}' im Testset, jetzt als '{artikel}' "
                         f"bewertet — Widerspruch, beide Urteile bleiben "
                         f"unaufgeloest, Aufnahme nicht uebernommen.")
                continue

            if artikel != NO_MATCH_ARTIKEL and not _artikel_in_db(
                    snapshot_dir(root, fp12) / "db.sqlite3", artikel):
                skip("label_unbekannt_in_db",
                     f"{pfad.name}: wahrer Artikel '{artikel}' existiert im "
                     f"Buendel-DB-Stand {fp12} nicht — Fehlklick oder "
                     f"Duplikat-Name? Nicht uebernommen.")
                continue

            if fp12 not in fidelity_ctx:
                bcfg = snapshot_cfg(cfg, root, fp12)
                fidelity_ctx[fp12] = (
                    bcfg, Database(bcfg),
                    Calibration.load(resolve(bcfg["calibration"]["file"])))
            bcfg, db_b, cal_b = fidelity_ctx[fp12]
            gruende = _fidelity_gruende(rep, bcfg, db_b, cal_b)
            if gruende:
                skip("fidelity_abweichung",
                     f"{pfad.name}: Buendel-Zustand reproduziert den Report "
                     f"nicht ({'; '.join(gruende)}) — nicht uebernommen.")
                continue

            ziel_dir = root / "captures" / artikel
            ziel_bild = ziel_dir / bild.name
            ziel_report = ziel_dir / pfad.name
            if ziel_bild.exists() or ziel_report.exists():
                skip("zielname_belegt",
                     f"{pfad.name}: Zielname unter captures/{artikel}/ schon "
                     f"belegt, Inhalt aber neu ({sha[:8]}) — nicht "
                     f"ueberschrieben.")
                continue
            if not dry_run:
                ziel_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(bild), str(ziel_bild))
                shutil.copy2(str(pfad), str(ziel_report))
            eintrag = CaptureEntry(
                sha=sha, artikel=artikel, label_herkunft=herkunft,
                snapshot=fp12, timestamp=rep.timestamp,
                image_rel=f"captures/{artikel}/{ziel_bild.name}",
                report_rel=f"captures/{artikel}/{ziel_report.name}")
            manifest.captures.append(eintrag)
            bekannte[sha] = eintrag
            aufgenommen += 1
    finally:
        for _, db_b, _ in fidelity_ctx.values():
            db_b.close()

    if not dry_run and (aufgenommen or snapshots_neu):
        manifest.generated = datetime.now().isoformat(timespec="seconds")
        manifest.save()

    return {"quelle": str(quelle), "aufgenommen": aufgenommen,
            "uebersprungen": dict(sorted(uebersprungen.items())),
            "befunde": befunde, "snapshots_neu": snapshots_neu,
            "gesamt_im_testset": len(manifest.captures),
            "dry_run": dry_run}
