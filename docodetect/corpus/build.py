"""corpus-build: Korpus aus Captures, archivierten Reports und Backups bauen.

Idempotent und hash-dedupliziert. Aufgenommen werden die drei sauberen
Sessions der Bestandsaufnahme (Spec 1.2); erster_test_loeffel (gemischte
Aufloesung, 3 bewertete) und smoke-v2-uiqt (synthetisch, Bilder fehlen)
bleiben bewusst draussen.
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from ..config import project_root
from ..reporting import load_reports
from .bundle import (SessionBundle, copy_db_readonly, db_match_ratio,
                     recover_mm_per_px, recover_sigma_floors,
                     write_session_json)
from .manifest import ImageEntry, Manifest, corpus_root, sha256_file

_P = project_root()

# (Session, Report-Ordner, Bild-Suchordner). Reihenfolge = Aufnahme-Reihenfolge.
#
# AUSGESCHLOSSEN, jeweils weil der Session-Zustand nicht mehr rekonstruierbar
# ist — ein Buendel, das man nicht einfrieren kann, taugt nicht als Golden:
#   test_2_loeffel  (14:52-15:31): Der Hintergrund der Session existiert nicht
#       mehr. calibration/background.png stammt von 15:45, also von NACH der
#       Session; background-alt.png aus den Backups wurde geprueft und liefert
#       dasselbe Ergebnis. Im Erstlauf fielen dort Farb-, Form- UND
#       Pixelgroessen durch — ein echter Segmentierungsunterschied, keine
#       blosse mm-Skalierung.
#   erster_test_loeffel: nur 3 bewertete Reports, gemischt 1080p/4K, alte
#       sigma_floors.
#   smoke-v2-uiqt: synthetisch (mm_per_px 0,2), Bilder nicht auffindbar.
SOURCES = [
    ("phase-a", str(_P / "reports/analysis/test_n_60_loeffel/reports"),
     str(_P / "data/captures")),
    ("phase-b", str(_P / "data/captures"), str(_P / "data/captures")),
]

# Buendel-Quellen je Session. Die DB-Zuordnung stammt aus dem exakten
# Referenz-Abgleich der Bestandsaufnahme (Spec 1.2) und wird beim Build
# erneut verifiziert — sie wird hier NICHT geglaubt, nur vorgeschlagen.
BUNDLE_QUELLEN = {
    "phase-a": {
        "background": str(_P / "calibration/background.png"),
        "calibration": str(_P / "calibration/calibration.json"),
        "db": None,      # kein passender Snapshot -> Tier-1-only
    },
    "phase-b": {
        "background": str(_P / "calibration/background.png"),
        "calibration": str(_P / "calibration/calibration.json"),
        "db": str(_P / "doco_detect.sqlite3"),
    },
}

# Zusaetzliche Fundorte fuer Capture-PNGs, wenn image_path ins Leere zeigt.
BILD_POOLS = [str(_P / "data/captures"),
              str(_P / "backups/2026-07-20-vor-ab-test/captures")]


def _finde_bild(image_path: str | None, such_dir: str) -> Path | None:
    if not image_path:
        return None
    direkt = Path(image_path)
    if direkt.exists():
        return direkt
    name = direkt.name
    for pool in [such_dir, *BILD_POOLS]:
        p = Path(pool) / name
        if p.exists():
            return p
    return None


def build_corpus(cfg: dict, *, dry_run: bool = False) -> dict:
    root = corpus_root(cfg)
    manifest = Manifest.load()
    bekannt = manifest.by_sha()
    stat = {"neu": 0, "gesamt": 0, "uebersprungen_dublette": 0,
            "uebersprungen_ohne_bild": 0, "sessions": {}}
    eintraege = list(manifest.images)
    gesehen = set(bekannt)

    for session, report_dir, such_dir in SOURCES:
        if not Path(report_dir).is_dir():
            continue
        paare = load_reports(report_dir)
        reports = [r for _, r in paare]
        if not reports:
            continue

        quellen = BUNDLE_QUELLEN.get(session, {})
        bundle_dir = root / session / "bundle"
        db_ziel = bundle_dir / "db.sqlite3"
        verified, has_db = 0.0, False
        if quellen.get("db") and Path(quellen["db"]).exists():
            verified = db_match_ratio(reports, quellen["db"])
            has_db = verified >= 1.0

        mmpp = [v for v in (recover_mm_per_px(r) for r in reports) if v]
        mmpp_median = sorted(mmpp)[len(mmpp) // 2] if mmpp else None
        floors = {}
        for r in reports:
            floors.update(recover_sigma_floors(r))

        sb = SessionBundle(
            name=session, bundle_dir=str(bundle_dir.relative_to(root)),
            has_db=has_db, db_verified=round(verified, 4),
            mm_per_px=mmpp_median, sigma_floors=floors,
            tier=2 if has_db else 1,
            provenance=(f"DB-Abgleich {verified:.0%} gegen {quellen.get('db')}"
                        if quellen.get("db") else
                        "kein DB-Snapshot verfuegbar -> Tier-1-only"))

        if not dry_run:
            bundle_dir.mkdir(parents=True, exist_ok=True)
            for key, ziel in (("background", "background.png"),
                              ("calibration", "calibration.json")):
                q = quellen.get(key)
                if q and Path(q).exists():
                    shutil.copy2(q, bundle_dir / ziel)
            if has_db:
                copy_db_readonly(quellen["db"], db_ziel)
            elif db_ziel.exists():
                db_ziel.unlink()
            write_session_json(bundle_dir, sb)

        n_session = 0
        for _, rep in paare:
            bild = _finde_bild(rep.image_path, such_dir)
            if bild is None:
                stat["uebersprungen_ohne_bild"] += 1
                continue
            sha = sha256_file(bild)
            if sha in gesehen:
                stat["uebersprungen_dublette"] += 1
                continue
            gesehen.add(sha)

            artikel = rep.label if (rep.label and rep.verdict) else "_unbewertet"
            bild_rel = f"{session}/images/{artikel}/{sha[:8]}.png"
            rep_rel = f"{session}/reports/{sha[:8]}.json"
            if not dry_run:
                ziel_bild = root / bild_rel
                ziel_bild.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(bild, ziel_bild)
                ziel_rep = root / rep_rel
                ziel_rep.parent.mkdir(parents=True, exist_ok=True)
                ziel_rep.write_text(rep.to_json(), encoding="utf-8")

            eintraege.append(ImageEntry(
                sha=sha, session=session, article=artikel, image_rel=bild_rel,
                report_rel=rep_rel, label=rep.label, verdict=rep.verdict,
                # Tier 2 braucht Buendel-DB UND ein Urteil
                tier=2 if (sb.tier2_ready and artikel != "_unbewertet") else 1))
            stat["neu"] += 1
            n_session += 1

        stat["sessions"][session] = {
            "tier": sb.tier, "db_verified": sb.db_verified,
            "mm_per_px": sb.mm_per_px, "neu": n_session,
            "n_images": sum(1 for e in eintraege if e.session == session)}

    manifest.images = eintraege
    # Mergen statt ersetzen: Sessions, deren Report-Ordner in diesem Lauf
    # fehlt (verschoben/archiviert), behalten ihre Metadaten. Sonst wuerden
    # ihre Bilder in manifest.images verwaisen -> Bild ohne Session-Eintrag.
    manifest.sessions = {**manifest.sessions, **stat["sessions"]}
    manifest.generated = datetime.now().isoformat(timespec="seconds")
    stat["gesamt"] = len(eintraege)
    if not dry_run:
        manifest.save()
    return stat
