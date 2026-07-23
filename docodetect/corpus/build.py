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
    # phase-b ist GESCHLOSSEN. Der Eintrag zeigte auf data/captures — den
    # Ordner, in den jede neue Identifikation schreibt. Solange dort nichts
    # lag, fiel das nicht auf; sobald wieder bewertet wird, haette der
    # naechste Build die frischen Reports stillschweigend in phase-b
    # aufgenommen und ihnen dessen eingefrorenes Buendel vom 20.07.
    # untergeschoben (anderer Hintergrund, andere DB). Die Session-Metadaten
    # bleiben erhalten: Manifest.sessions wird gemergt, nicht ersetzt.
    # Neues Material bekommt eine neue Session mit eigenem Snapshot.
    #   ("phase-b", str(_P / "data/captures"), str(_P / "data/captures")),
    # 2026-07-23 aufgenommen (Schritt 7). Quelle ist ein archivierter
    # analyze-Lauf, damit der Bestand reproduzierbar bleibt: data/captures
    # wird von jedem `analyze --archive` geleert, ein Verweis dorthin waere
    # nach dem naechsten Lauf ins Leere gelaufen.
    #
    # phase-c1 (LOEFFEL-14-Messreihe, 18 Bilder) ist HERAUSGENOMMEN und liegt
    # in backups/2026-07-23-phase-c1-nicht-korpusfaehig/. Sie fiel im Tier-1-
    # Lauf 18/18 durch: ihr Hintergrund vom 22.07. existiert nicht mehr
    # (capture-background hat ihn am 23.07. ueberschrieben). Der Eintrag darf
    # NICHT zurueck — sonst baut jeder Lauf die verworfene Session neu und
    # der naechste --check rot. Details: Ergebnisdokument, Abschnitt 3.2.
    # phase-c2 liest aus cross-mac-final/reports (44 bewertete Cross-Tests:
    # die 23 aus cross_test_2 PLUS die 21 der Verdichtung vom 2026-07-23,
    # 18:19-18:28). Der Nachtrag ist dieselbe Session — kein Enrollment und
    # keine Aera-Grenze zwischen 17:20 und 18:28 (letztes Enrollment 17:07,
    # Buendel-Snapshot 17:52), db_match_ratio 100 % gegen die Buendel-DB. Der
    # Superset-Ordner ist die einzige Provenienz-Quelle; die 23 werden beim
    # Rebuild als Dublette uebersprungen, nur die 21 kommen neu hinzu.
    ("phase-c2", str(_P / "reports/analysis/cross-mac-final/reports"),
     str(_P / "data/captures")),
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
    # --- 2026-07-23 (Schritt 7) ------------------------------------------
    # phase-c1: Messreihe LOEFFEL-14 vom 2026-07-22, 18 bewertete Reports.
    # BEWUSST Tier-1-only, obwohl der DB-Abgleich 100 % ergibt (geprueft am
    # 2026-07-23). Der Grund liegt nicht in der DB, sondern in der Config:
    # die Entscheidungen dieser Reihe entstanden unter den DAMALS lokalen
    # sigma_floors, die erst spaeter am 2026-07-22 versioniert in
    # config.yaml wanderten. Als Tier-2-Goldens produzierten sie auf jedem
    # kuenftigen Lauf Delta-Laerm gegen eine Entscheidungsbasis, die es so
    # nie wieder gibt. Ihr Wert ist die MESS-Serie: 18 Auflagen desselben
    # Loeffels sind der Wiederholbarkeits-Beleg, und der ist reine Tier-1-
    # Groesse (Segmentierung + Geometrie, entscheidungsfrei).
    #
    # ACHTUNG Hintergrund: der Hintergrund DIESER Session existiert nicht
    # mehr — calibration/background.png wurde am 2026-07-23 um 14:55 fuer
    # die Golden-Fixtures neu aufgenommen und hat den vom 22.07.
    # ueberschrieben. Gebuendelt wird darum der heutige. Belegt statt
    # geraten (Messung 2026-07-23): der Aera-Abgleich der 18 Captures gegen
    # den heutigen Hintergrund ergibt Median-|diff| 0 (Schranke 6), gegen
    # den aeltesten verfuegbaren vom 20.07. Median 1; die beiden
    # Hintergruende unterscheiden sich untereinander um Median 1 / Mittel
    # 1,06. Die Beleuchtung der Box ist ueber die drei Tage stabil. Den
    # Beweis fuehrt aber nicht diese Rechnung, sondern der Tier-1-Lauf: er
    # reproduziert die Messwerte vom 22.07. gegen den heutigen Hintergrund.
    # Faellt er, ist phase-c1 nicht korpusfaehig.
    "phase-c1": {
        "background": str(_P / "calibration/background.png"),
        "calibration": str(_P / "calibration/calibration.json"),
        "db": str(_P / "doco_detect.sqlite3"),
        "tier1_only": True,
        "tier1_grund": ("bewusst Tier-1-only: Entscheidungen entstanden "
                        "unter den damals lokalen sigma_floors, als "
                        "Tier-2-Goldens nur Delta-Laerm; der Wert der "
                        "Session ist die Mess-Serie"),
    },
    # phase-c2: die 23 bewerteten Cross-Tests vom 2026-07-23, voll Tier 2.
    # Sie liefen bereits gegen die heutige config.yaml und die heutige DB
    # (nach dem Gabel/Messer-Enrollment) — Entstehungs- und Replay-Zustand
    # sind identisch, der Replay muss sie darum exakt reproduzieren.
    "phase-c2": {
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
            "uebersprungen_ohne_bild": 0, "sessions": {},
            "bundle_konflikt": []}
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
        # tier1_only ist eine BEWUSSTE Herabstufung: der DB-Abgleich wird
        # trotzdem gerechnet und protokolliert, damit die Provenienz nicht
        # "kein Snapshot verfuegbar" behauptet, wo in Wahrheit "Snapshot
        # passt, wird aber nicht verwendet" gilt. Die Unterscheidung ist der
        # ganze Punkt: ein Leser muss erkennen koennen, ob eine Session
        # Tier 1 ist, weil sie es nicht besser kann, oder weil jemand
        # entschieden hat.
        nur_tier1 = bool(quellen.get("tier1_only"))
        verified, has_db = 0.0, False
        if quellen.get("db") and Path(quellen["db"]).exists():
            verified = db_match_ratio(reports, quellen["db"])
            has_db = verified >= 1.0 and not nur_tier1

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
            provenance=(
                f"DB-Abgleich {verified:.0%} gegen {quellen.get('db')} — "
                f"{quellen.get('tier1_grund', 'herabgestuft')}"
                if nur_tier1 else
                f"DB-Abgleich {verified:.0%} gegen {quellen.get('db')}"
                if quellen.get("db") else
                "kein DB-Snapshot verfuegbar -> Tier-1-only"))

        # Ein gebuendelter Session-Zustand ist EINGEFROREN. Er darf von einem
        # spaeteren Build nie stillschweigend ersetzt werden: die Quellpfade
        # in BUNDLE_QUELLEN zeigen auf LEBENDE Dateien
        # (calibration/background.png wird bei jedem capture-background
        # ueberschrieben, doco_detect.sqlite3 waechst mit jedem Enrollment).
        # Ohne diese Schranke tauschte ein Build vom 2026-07-23 den
        # Hintergrund von phase-a (20.07.) gegen den heutigen — die 67 alten
        # Tier-1-Bilder laegen dann gegen eine andere Segmentierungs-
        # Grundlage, und der naechste --check meldete eine Code-Regression,
        # die keine ist. Genau das war beim Bau von phase-c beinahe passiert.
        for key, ziel in (("background", "background.png"),
                          ("calibration", "calibration.json")):
            q = quellen.get(key)
            zielpfad = bundle_dir / ziel
            if not q or not Path(q).exists() or not zielpfad.exists():
                continue
            if sha256_file(Path(q)) != sha256_file(zielpfad):
                stat["bundle_konflikt"].append(
                    f"{session}/{ziel}: gebuendelt bleibt der bestehende "
                    f"Stand; die Quelle {q} ist inzwischen eine andere Datei. "
                    f"Ein bewusster Austausch geht ueber ein Verschieben der "
                    f"Session nach backups/ und einen Neubau.")

        if not dry_run:
            bundle_dir.mkdir(parents=True, exist_ok=True)
            for key, ziel in (("background", "background.png"),
                              ("calibration", "calibration.json")):
                q = quellen.get(key)
                # exist_ok=False in der Wirkung: nur schreiben, was fehlt.
                if q and Path(q).exists() and not (bundle_dir / ziel).exists():
                    shutil.copy2(q, bundle_dir / ziel)
            if has_db and not db_ziel.exists():
                copy_db_readonly(quellen["db"], db_ziel)
            elif not has_db and db_ziel.exists():
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
