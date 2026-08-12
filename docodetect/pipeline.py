"""End-to-end pipeline: image -> segmentation -> features -> match.

Both the CLI and any future UI/REST service call ONLY this module, so the
process stays identical everywhere.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from .calibration import (Calibration, load_background, load_calibration,
                          run_calibration, save_background)
from .config import resolve
from .database import Article, Database
from .features import (SCALAR_FEATURES, Features, describe_color_hsv, extract,
                       height_corrected_scale, min_area_rect_mm, scalar_value)
from .matcher import DECISION_REJECT, MatchReport, match
from .display import (channel_percentages, format_delta, format_diameter,  # noqa: F401
                      format_measured, format_rank_line, headline,
                      natuerlicher_schluessel)  # Re-Export: UIs importieren Anzeige-Helfer NUR über pipeline
from .reporting import NO_MATCH  # noqa: F401 — Re-Export: UIs beziehen
# Konstanten/Typen über pipeline, nie reporting/matcher direkt (Spec
# Zugriffsweg, Revision 2026-08-11); MatchReport (oben) ebenso.
from .segmentation import SegmentationError, SegmentationResult, segment


@dataclass
class IdentifyOutcome:
    features: Features | None
    segmentation: SegmentationResult | None
    report: MatchReport


@dataclass
class PipelineStatus:
    """Einrichtungszustand für UIs (Statusleiste + NOT_READY-Führung).
    Muss auch VOR jeder Einrichtung funktionieren – get_status() setzt
    keine Kalibrierung voraus und legt keine Dateien an."""
    calibrated: bool
    mm_per_px: float | None
    calibrated_unix: float | None
    background_present: bool
    article_count: int
    articles_with_references: int
    stage2_enabled: bool

    @property
    def ready(self) -> bool:
        """Identifizieren möglich (Kalibrierung + Hintergrund vorhanden)."""
        return self.calibrated and self.background_present


@dataclass
class ArticleInfo:
    """Artikel-Zeile fürs UI (Einlern-Dropdown, Listen) – Stammdaten plus
    Referenzanzahl, ohne dass die UI database.py anfassen muss."""
    article_number: str
    name: str
    category: str | None
    diameter_mm: float | None
    height_mm: float | None
    n_references: int
    # Additiv 2026-08-11 (Stufe 3 Teil A): minAreaRect-Seiten der
    # länglichen Artikel — Nominal ist max(width, depth), nie hypot.
    width_mm: float | None = None
    depth_mm: float | None = None


@dataclass
class AnalysisRunInfo:
    """Gültiger Analyse-Lauf unter analysis.output_dir (Listbarkeits-
    Kriterium, Spec Stufe 2): report.md UND metrics.json vorhanden.
    mtime_unix ist die DATEIZEIT von report.md — report.md wird genau
    einmal am Laufende geschrieben (analysis.py, Audit 2026-08-11: kein
    Pfad schreibt es neu), die Anzeige beschriftet sie als Dateizeit."""
    run_id: str
    path: Path
    mtime_unix: float


def get_status(cfg: dict) -> PipelineStatus:
    """Reine Status-Abfrage ohne Nebenwirkungen: fehlende/kaputte Dateien
    bedeuten 'nicht eingerichtet', nie eine Exception. Insbesondere wird
    KEINE leere SQLite-Datei angelegt (sqlite3.connect würde das tun)."""
    mm_per_px = calibrated_unix = None
    try:
        cal = load_calibration(cfg)
        mm_per_px, calibrated_unix = cal.mm_per_px, cal.created_unix
    except Exception:
        pass

    background_present = resolve(cfg["calibration"]["background_file"]).exists()

    article_count = with_refs = 0
    if resolve(cfg["paths"]["db_file"]).exists():
        db = Database(cfg)
        try:
            article_count = len(db.all_articles())
            with_refs = len(db.articles_with_references())
        except Exception:
            pass  # DB ohne Schema o.ä. -> zählt als leer
        finally:
            db.close()

    return PipelineStatus(
        calibrated=mm_per_px is not None, mm_per_px=mm_per_px,
        calibrated_unix=calibrated_unix, background_present=background_present,
        article_count=article_count, articles_with_references=with_refs,
        stage2_enabled=bool(cfg.get("stage2", {}).get("enabled", False)))


def capture_background(image: np.ndarray, cfg: dict):
    """Einzelbild-Fassade: Hintergrund-Referenz aus einem Frame speichern.
    Dünne Weiterleitung an calibration.py, damit die UI-Regel hält (UIs
    importieren nur pipeline)."""
    return save_background(image, cfg)


def calibrate(image: np.ndarray, cfg: dict) -> Calibration:
    """Einzelbild-Fassade: ArUco-Kalibrierung aus einem Frame. Wirft
    RuntimeError mit handlungsleitender Meldung, wenn kein Marker gefunden
    wird (calibration.py)."""
    return run_calibration(image, cfg)


def measure_shot(image: np.ndarray, cfg: dict) -> tuple[Features, SegmentationResult]:
    """Einzel-Shot fürs Einlernen VERMESSEN, ohne etwas zu persistieren –
    erste Hälfte des Zwei-Schritt-Ablaufs (analyze -> save_reference), damit
    ein Einlern-Dialog einzelne Aufnahmen wiederholen kann, ohne verwaiste
    Referenzen in der DB zu hinterlassen. Raises SegmentationError
    (Randberührung) wie enroll."""
    pipe = Pipeline(cfg)
    try:
        seg, feats = pipe.analyze(image)
    finally:
        pipe.close()
    return feats, seg


def save_enrollment(cfg: dict, article_number: str,
                    shots: list) -> int:
    """Zweite Hälfte des Einlern-Ablaufs: alle bestätigten Shots
    [(image, Features), ...] auf einmal persistieren – Referenzfoto nach
    paths.reference_dir/<artikel>/ (wie die CLI) + Features in die
    DB (Enrollment-Statistik wird dabei aktualisiert).

    OHNE PRODUKTIVAUFRUFER seit 2026-08-08 (Schritt 7 des Session-Pakets):
    der Qt-Einlerndialog arbeitet jetzt auf einer EnrollSession und bucht ueber
    commit_enroll_session, das die Dateien vor der Transaktion verschiebt
    (Invariante U1). Diese Fassade nimmt dagegen In-Memory-Shots entgegen und
    schreibt Datei und DB-Zeile ineinander verschraenkt – ein Absturz dazwischen
    hinterliesse genau den Zustand, gegen den das Paket gebaut ist.

    Sie bleibt trotzdem: drei Tests haengen daran (test_enrollment_sheet.py:91
    und :217, test_ui_facade.py:226) und sind seither ihre EINZIGE Absicherung.
    Wer sie „der neuen Welt anpasst", entfernt genau diese. Zusammenlegen oder
    entfernen ist als eigener Schritt vorgemerkt (Vormerkliste 16) – bewusst
    NICHT im selben Paket, das den Einlernpfad umbaut."""
    ref_dir = resolve(cfg["paths"]["reference_dir"]) / article_number
    ref_dir.mkdir(parents=True, exist_ok=True)
    pipe = Pipeline(cfg)
    try:
        ts = int(datetime.now().timestamp() * 1000)
        for i, (img, feats) in enumerate(shots):
            # Verlustloses PNG statt JPG: die Shots sollen kuenftige
            # Kanten-/Streuungsanalysen tragen, und JPG-Artefakte sitzen genau
            # an der Kontur. {i:02d} = Index in Aufnahmereihenfolge,
            # nullgepadded, damit die lexikalische Dateinamen-Sortierung nicht
            # bei zweistelligen Indizes kippt (_10 vor _2).
            path = ref_dir / f"{ts}_{i:02d}.png"
            cv2.imwrite(str(path), img)
            pipe.save_reference(article_number, feats, str(path))
    finally:
        pipe.close()
    return len(shots)


def enrollment_sheet_for_shots(cfg: dict, article_number: str, shots: list,
                               out=None):
    """UI-Fassade (STUFE 4): Enrollment-Diagnoseblatt aus den In-Memory-Shots
    EINER Einlern-Session – VOR dem Speichern – rendern.
    shots = [(frame_bgr, Features), ...] in Aufnahmereihenfolge. Die gesamte
    Logik liegt in enrollment_sheet.build_enrollment_sheet; diese Fassade
    existiert nur, damit die Qt-UI (wie vorgeschrieben) ausschliesslich
    pipeline.py ruft. Gibt den Pfad des PNG zurueck."""
    from .enrollment_sheet import build_enrollment_sheet
    return build_enrollment_sheet(cfg, article_number=article_number,
                                  shots=shots, out=out)


def discard_enrollment(cfg: dict, article_number: str, shots: list,
                       sheet_png=None):
    """Ein im Einlerndialog VERWORFENES Enrollment sichern statt loeschen: die
    aufgenommenen Frames (+ Diagnoseblatt + info.json) nach
    <reference_dir>/../verworfen/<artikel>/<zeitstempel>/ schreiben.

    Beruehrt bewusst WEDER die DB NOCH reference_dir: beim pre-commit-Verwerfen
    war dort nie etwas gespeichert (kein Schema-/Pfad-Vertrag betroffen). Ein
    verworfenes Enrollment ist das interessanteste Material fuer die Frage,
    warum es verworfen wurde – genau die Daten, die der C-Serie fehlten. Gibt
    den Zielordner zurueck."""
    import json
    import shutil
    from pathlib import Path

    ref_dir = resolve(cfg["paths"]["reference_dir"])
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = ref_dir.parent / "verworfen" / article_number / ts
    dest.mkdir(parents=True, exist_ok=True)
    for i, (frame, _feats) in enumerate(shots):
        cv2.imwrite(str(dest / f"{ts}_{i:02d}.png"), frame)
    if sheet_png and Path(sheet_png).exists():
        shutil.copy2(str(sheet_png), str(dest / "diagnoseblatt.png"))
    (dest / "info.json").write_text(
        json.dumps({"article_number": article_number, "timestamp": ts,
                    "n_shots": len(shots),
                    "grund": "im Einlerndialog verworfen (pre-commit, nie in DB)"},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    return dest


def persist_enrollment_sheet(cfg: dict, article_number: str, sheet_png):
    """Ein beim „Übernehmen" angenommenes Enrollment-Diagnoseblatt dauerhaft
    neben die übrigen Analyse-Artefakte legen: Kopie nach
    analysis.output_dir/enrollment/<artikelnummer>.png. Gibt den Zielpfad
    zurück; wirft bei fehlender Quelle oder Schreibfehler.

    Bewusst OHNE eigenes Fehler-Schlucken: das Kopieren ist eine Nebenausgabe,
    der Aufrufer (Einlerndialog) behandelt einen Fehler best-effort — der
    DB-Eintrag steht zu dem Zeitpunkt bereits, das Übernehmen darf NIE an einer
    fehlgeschlagenen Kopie scheitern (nur warnen)."""
    import shutil
    from pathlib import Path

    src = Path(sheet_png)
    if not src.is_file():
        raise FileNotFoundError(f"Diagnoseblatt nicht gefunden: {src}")
    dest_dir = resolve(cfg["analysis"]["output_dir"]) / "enrollment"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{article_number}.png"
    shutil.copy2(str(src), str(dest))
    return dest


# ============================================================================
# Crash-sichere Einlern-Session (Schritt 2 von 8)
# Design: docs/superpowers/specs/2026-08-05-crashsichere-einlern-session-design.md
#
# Leitsatz: KEIN Statusfeld, und keine Datei wird je zweimal geschrieben. Jeder
# Zwischenzustand ist aus (Journal, Dateisystem, DB) ABLEITBAR. Was nie
# ueberschrieben wird, kann nicht halb ueberschrieben sein — das gilt fuer den
# JSON-Block wie fuer das PNG.
#
# NOCH NICHT hier (Schritt 3): Umzug nach reference_dir, Buchen, Verwerfen,
# remeasure_session.
# ============================================================================

# Roh-Shots tragen eine laufende Nummer, die NIE wiederverwendet wird — der
# Endname {ts}_{i:02d}.png entsteht erst beim Umzug (Schritt 3). Ein Retake
# schreibt also eine NEUE Datei und laesst die alte liegen, statt sie zu
# ueberschreiben: ein Rewrite auf Dateiebene waere derselbe Verstoss gegen die
# Append-only-Regel wie ein neu geschriebener JSON-Block, nur eine Ebene tiefer.
_RAW_NAME_RE = re.compile(r"^raw_(\d{3,})\.png$")

# Teile des Fingerabdrucks, deren Abweichung das Fortsetzen verweigert. Die
# Klartextwerte (mm_per_px, camera_height_mm) stehen nur daneben, damit eine
# Meldung die Abweichung BEZIFFERN kann — verglichen werden die Hashes.
_FINGERPRINT_HASHES = ("calibration_sha256", "background_sha256",
                       "features_cfg_sha256")


class EnrollSessionError(RuntimeError):
    """Session-Befund, den der Aufrufer dem Menschen erklaeren muss.

    `kind` waehlt die Behandlung, `detail` traegt die Zahlen fuer die Meldung.
    Ein Typ mit `kind` statt sechs Unterklassen — Hausform ist Nutzlast auf
    einem Typ (SegmentationError traegt `.segmentation`), und jeder Aufrufer
    faengt ohnehin die ganze Familie und verzweigt nur fuer die Abhilfe.

    kind: mount | fingerprint | kollision | datei_fehlt | luecke | invariante
    """

    def __init__(self, message: str, *, kind: str, detail: dict | None = None):
        super().__init__(message)
        self.kind = kind
        self.detail = detail or {}


@dataclass
class SessionShot:
    i: int                    # logische Shot-Position (ein Retake ersetzt sie)
    raw_path: Path
    d_mm: float
    features: Features


@dataclass
class SessionInfo:
    """Kopf einer Session OHNE Journal-Inhalt – fuer Listen und Dialoge."""
    path: Path
    article_number: str
    ts: int
    created: str
    target_shots: int
    n_shots: int              # DISTINKTE i, nicht Zeilen (siehe _lies_journal)
    zustand: str
    fingerprint: dict
    fingerprint_ok: bool
    age_secs: float


@dataclass
class EnrollSession:
    info: SessionInfo
    shots: list[SessionShot] = field(default_factory=list)


# ---------- interne Helfer ----------

def _sessions_root(cfg: dict) -> Path:
    return resolve(cfg["paths"]["enroll_sessions_dir"])


def _sha256_datei(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _fsync_verzeichnis(p: Path) -> None:
    """Verzeichniseintrag durabel machen.

    Auf Windows NICHT durchfuehrbar: ein Verzeichnis laesst sich dort nicht als
    Dateideskriptor oeffnen, os.fsync haette kein Ziel. Der Schritt wird dort
    uebersprungen. Folge (bewusst in Kauf genommen, nicht stillschweigend):
    nach einem STROMAUSFALL — nicht nach einem Prozessabsturz, dafuer genuegt
    der Page-Cache — kann auf NTFS ein Verzeichniseintrag fehlen, dessen
    Journalzeile schon durabel ist. Das ist erkennbar (Datei weg, Journalzeile
    da) und fuehrt zu einem Befund, nicht zu einer stillen Falschmessung.
    """
    if os.name == "nt":
        return
    fd = os.open(str(p), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _naechster_vorhandener(p: Path) -> Path:
    """Naechster existierender Vorfahr – erlaubt die Mount-Pruefung, BEVOR die
    Verzeichnisse angelegt sind, ohne sie als Nebenwirkung anzulegen."""
    p = Path(p).resolve()
    while not p.exists() and p != p.parent:
        p = p.parent
    return p


def _pruefe_mount(cfg: dict) -> None:
    """enroll_sessions_dir und reference_dir muessen auf DEMSELBEN Dateisystem
    liegen. Der Umzug beim Buchen ist ein os.rename; ueber Dateisystemgrenzen
    hinweg ist der nicht atomar (EXDEV). Geprueft statt unterstellt — und zwar
    beim Anlegen der Session, also bevor ein einziger Shot existiert. Eine
    Session, die erst nach zwoelf Aufnahmen am Umzug scheitert, waere genau der
    Schaden, den dieses Paket verhindern soll."""
    a = _naechster_vorhandener(_sessions_root(cfg))
    b = _naechster_vorhandener(resolve(cfg["paths"]["reference_dir"]))
    if a.stat().st_dev != b.stat().st_dev:
        raise EnrollSessionError(
            "Einlern-Sessions und Referenzverzeichnis liegen auf verschiedenen "
            "Dateisystemen – der Umzug beim Buchen waere nicht atomar. "
            f"Sessions: {a} · Referenzen: {b}",
            kind="mount",
            detail={"enroll_sessions_dir": str(a), "reference_dir": str(b)})


def _fingerabdruck(cfg: dict) -> dict:
    """Optikzustand als Hashes ueber die ROHDATEIEN plus die Klartextwerte.

    Rohdateien statt abgeleiteter Werte: eine neu geschriebene Kalibrierung mit
    zufaellig gleichem mm_per_px ist trotzdem ein anderer Optikzustand.

    Der features-Block gehoert dazu, weil er die Merkmalsberechnung
    parametrisiert – und er ist VOLLSTAENDIG: features.extract liest aus cfg
    ausschliesslich features.ring_zones und features.hs_hist_bins, sonst
    nichts. Kanonisiert (sort_keys), damit eine YAML-Umformatierung ohne
    Wertaenderung nicht faelschlich anschlaegt. `matching` bleibt draussen: es
    parametrisiert das Scoring, nicht die Messung.

    Kosten: 0,5 ms gemessen (sha256 ueber beide Dateien, 1,26 MB) gegen ~1 s
    Segmentierung je Aufnahme.
    """
    cal = load_calibration(cfg)
    return {
        "calibration_sha256": _sha256_datei(resolve(cfg["calibration"]["file"])),
        "background_sha256": _sha256_datei(
            resolve(cfg["calibration"]["background_file"])),
        "features_cfg_sha256": hashlib.sha256(
            json.dumps(cfg.get("features", {}), sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "mm_per_px": cal.mm_per_px,
        "camera_height_mm": cal.camera_height_mm,
    }


def _pruefe_fingerabdruck(cfg: dict, session: EnrollSession) -> None:
    """Wirft kind='fingerprint', wenn sich der Optikzustand seit dem Anlegen
    geaendert hat. Sonst mischte eine sigma_enroll zwei Optikzustaende."""
    jetzt = _fingerabdruck(cfg)
    soll = session.info.fingerprint
    abweichend = [k for k in _FINGERPRINT_HASHES if soll.get(k) != jetzt.get(k)]
    if not abweichend:
        return
    raise EnrollSessionError(
        "Optikzustand hat sich seit dem Anlegen der Session geaendert "
        f"({', '.join(abweichend)}). Die Aufnahmen dieser Session sind unter "
        f"mm_per_px {soll.get('mm_per_px')} entstanden, aktuell gilt "
        f"{jetzt.get('mm_per_px')}. Auswege: alte Kalibrierung aus "
        f"{session.info.path / 'optik'} zurueckholen, Session verwerfen, oder "
        "unter dem aktuellen Zustand neu einlernen.",
        kind="fingerprint",
        detail={"abweichend": abweichend, "soll": soll, "jetzt": jetzt,
                "optik_kopie": str(session.info.path / "optik")})


def _pruefe_luecken(session: EnrollSession) -> None:
    """Die distinkten i muessen exakt {0..N-1} sein – lueckenlos ab 0.

    Eine Luecke hiesse, dass die Endnamen {ts}_{i:02d} Spruenge enthalten und
    die Sortierung in references_with_meta eine Position ohne Datei anspricht.
    N == target_shots wird NICHT verlangt: weniger Shots als geplant zu
    speichern ist ein zulaessiger Bedienfall, target_shots ist Anzeigegroesse."""
    idx = sorted({s.i for s in session.shots})
    if not idx:
        raise EnrollSessionError(
            f"Session {session.info.path} enthaelt keine Aufnahme.",
            kind="luecke", detail={"i": idx, "n": 0})
    if idx != list(range(len(idx))):
        raise EnrollSessionError(
            f"Luecke in der Shot-Reihenfolge: {idx} (erwartet 0..{len(idx) - 1}).",
            kind="luecke", detail={"i": idx, "erwartet": list(range(len(idx)))})


def _lies_journal(journal: Path, sess_dir: Path) -> list[SessionShot]:
    """Journal lesen, je i die LETZTE Zeile behalten, nach i sortieren.

    Eine nicht parsebare LETZTE Zeile wird stillschweigend verworfen – das ist
    der abgeschnittene Schreibvorgang eines Absturzes. Eine nicht parsebare
    Zeile IN DER MITTE ist ein Befund (ValueError) und wird nicht uebersprungen:
    dort ist etwas anderes passiert als ein Abbruch am Ende.
    """
    if not journal.exists():
        return []
    zeilen = journal.read_text(encoding="utf-8").splitlines()
    je_i: dict = {}
    for nr, zeile in enumerate(zeilen):
        if not zeile.strip():
            continue
        try:
            d = json.loads(zeile)
        except json.JSONDecodeError as e:
            if nr == len(zeilen) - 1:
                break        # abgeschnittene letzte Zeile: kein Shot, kein Fehler
            raise ValueError(
                f"Journal {journal} ist in Zeile {nr + 1} von {len(zeilen)} "
                f"unlesbar (nicht die letzte Zeile): {e}") from e
        je_i[int(d["i"])] = d
    # Features(**d) ist der Gegenpart zu asdict() – dieselbe Form, die
    # Features.from_json intern benutzt (features.py: Features(**json.loads(s))).
    return [SessionShot(i=i, raw_path=sess_dir / d["file"],
                        d_mm=float(d["d_mm"]),
                        features=Features(**d["features"]))
            for i, d in sorted(je_i.items())]


def _lade_session(cfg: dict, sess_dir: Path) -> EnrollSession:
    sess_dir = Path(sess_dir)
    kopf_datei = sess_dir / "session.json"
    if not kopf_datei.is_file():
        raise FileNotFoundError(f"Keine Einlern-Session unter {sess_dir}")
    kopf = json.loads(kopf_datei.read_text(encoding="utf-8"))
    shots = _lies_journal(sess_dir / "journal.jsonl", sess_dir)
    try:
        ok = not [k for k in _FINGERPRINT_HASHES
                  if kopf["fingerprint"].get(k) != _fingerabdruck(cfg).get(k)]
    except Exception:
        ok = False          # keine Kalibrierung da -> nicht fortsetzbar
    journal = sess_dir / "journal.jsonl"
    stand = journal.stat().st_mtime if journal.exists() else kopf["ts"] / 1000.0
    info = SessionInfo(
        path=sess_dir, article_number=kopf["article_number"], ts=int(kopf["ts"]),
        created=kopf["created"], target_shots=int(kopf["target_shots"]),
        n_shots=len(shots), zustand="offen",
        fingerprint=kopf["fingerprint"], fingerprint_ok=ok,
        age_secs=max(0.0, time.time() - stand))
    session = EnrollSession(info=info, shots=shots)
    info.zustand = _zustand(cfg, session)
    return session


def _zustand(cfg: dict, session: EnrollSession) -> str:
    """Zustand ABLEITEN aus (Journal, Dateisystem, DB) – nie gespeichert.

    Ein Statusfeld muesste bei jedem Uebergang neu geschrieben werden; was nie
    geschrieben wird, kann nicht halb geschrieben sein und nicht mit der
    Wirklichkeit auseinanderlaufen.
    """
    ziele = _zielpfade(cfg, session)
    if not ziele:
        return "offen"
    quellen_da = sum(1 for _, q, _ in ziele if q.exists())
    ziele_da = sum(1 for _, _, z in ziele if z.exists())
    if ziele_da == 0:
        return "offen"
    if quellen_da == 0 and ziele_da == len(ziele):
        # Alles umgezogen – gebucht oder noch nicht? Nur die DB weiss es.
        if resolve(cfg["paths"]["db_file"]).exists():
            db = Database(cfg)
            try:
                je = _zeilen_je_pfad(db, session.info.article_number,
                                     [z for _, _, z in ziele])
            except Exception:
                je = {}
            finally:
                db.close()
            if je and all(je.values()):
                return "gebucht_aufraeumen_offen"
    return "umzug_unterbrochen"


# ---------- Fassaden ----------

def begin_enroll_session(cfg: dict, article_number: str, *,
                         target_shots: int) -> EnrollSession:
    """Neue Einlern-Session anlegen und auf Platte verankern.

    Legt <enroll_sessions_dir>/<artikel>/<ts>/ an, schreibt session.json
    (temp+fsync+rename+fsync-Verzeichnis), das leere journal.jsonl und die
    optik/-Kopien von calibration.json und background.png. Die Kopien machen
    die Session selbstbeschreibend: bei spaeterer Fingerabdruck-Abweichung ist
    "alte Kalibrierung zurueckholen" ein echter Ausweg statt einer Sackgasse.

    Prueft VOR dem Anlegen: Mount-Gleichheit (EnrollSessionError kind='mount')
    und dass der Artikel existiert (KeyError, wie database.add_reference).
    Fail-fast, bevor ein einziger Shot existiert.

    SETZT den Fingerabdruck – prueft ihn hier nicht, es gibt noch keinen
    Vergleichswert.
    """
    _pruefe_mount(cfg)
    db = Database(cfg)
    try:
        if db.get_article(article_number) is None:
            raise KeyError(
                f"Unknown article_number '{article_number}' – import it first.")
    finally:
        db.close()

    abdruck = _fingerabdruck(cfg)
    ts = int(time.time() * 1000)
    sess_dir = _sessions_root(cfg) / article_number / str(ts)
    sess_dir.mkdir(parents=True, exist_ok=True)

    optik = sess_dir / "optik"
    optik.mkdir(exist_ok=True)
    shutil.copy2(str(resolve(cfg["calibration"]["file"])),
                 str(optik / "calibration.json"))
    shutil.copy2(str(resolve(cfg["calibration"]["background_file"])),
                 str(optik / "background.png"))
    _fsync_verzeichnis(optik)

    kopf = {"article_number": article_number, "ts": ts,
            "created": datetime.now().isoformat(timespec="microseconds"),
            "target_shots": int(target_shots), "fingerprint": abdruck,
            "owner": {"pid": os.getpid(), "host": socket.gethostname()},
            "sandbox": cfg.get("sandbox")}
    tmp = sess_dir / "session.json.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(kopf, fh, ensure_ascii=False, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    os.rename(str(tmp), str(sess_dir / "session.json"))

    journal = sess_dir / "journal.jsonl"
    with open(journal, "w", encoding="utf-8") as fh:
        fh.flush()
        os.fsync(fh.fileno())
    _fsync_verzeichnis(sess_dir)
    return _lade_session(cfg, sess_dir)


def stage_frame(cfg: dict, session: EnrollSession, frame: np.ndarray) -> Path:
    """Rohbild verankern, BEVOR es vermessen wird. Gibt den Pfad zurueck.

    Reihenfolge: PNG schreiben -> fsync(Datei) -> fsync(Verzeichnis) -> DANN
    den Fingerabdruck pruefen. Die Pruefung steht bewusst NACH dem Schreiben:
    die Kamera hat ausgeloest und das Objekt liegt in der Box – ein 4K-Frame
    wird nicht weggeworfen, nur weil zwischendurch jemand kalibriert hat. Bei
    Abweichung bleibt das Bild als Waise liegen (keine Journalzeile, kein
    gezaehlter Shot) und faehrt beim Aufraeumen als Material mit. Das ist
    dieselbe Behandlung wie bei SegmentationError.

    Vor measure_shot steht die Pruefung trotzdem – sie spart die ~1 s
    Segmentierung und eine sinnlose Messung gegen einen fremden Hintergrund.

    Erzeugt noch KEINEN Shot: Commit-Record ist die Journalzeile (append_shot),
    nicht die Existenz der Datei. Deshalb braucht das PNG auch kein
    temp+rename – ein halb geschriebenes raw_<NNN>.png ohne Journalzeile zaehlt
    nirgends mit.
    """
    sess_dir = session.info.path
    belegt = [int(m.group(1)) for m in
              (_RAW_NAME_RE.match(p.name) for p in sess_dir.glob("raw_*.png"))
              if m]
    pfad = sess_dir / f"raw_{(max(belegt) + 1 if belegt else 0):03d}.png"

    ok, buf = cv2.imencode(".png", frame)
    if not ok:
        raise RuntimeError("Rohbild liess sich nicht als PNG kodieren.")
    with open(pfad, "wb") as fh:
        fh.write(buf.tobytes())
        fh.flush()
        os.fsync(fh.fileno())
    _fsync_verzeichnis(sess_dir)

    _pruefe_fingerabdruck(cfg, session)
    return pfad


def append_shot(cfg: dict, session: EnrollSession, raw_path, feats: Features,
                *, i: int | None = None) -> EnrollSession:
    """Vermessenen Shot ins Journal uebernehmen – DAS ist der Commit-Record.

    Haengt EINE Zeile an, flush + fsync. i=None -> naechste freie Position,
    i=k -> Retake von k: eine NEUE Zeile mit demselben i, die alte Zeile und
    die alte Datei bleiben liegen. Es gilt die letzte Zeile je i.

    Prueft vorher (ValueError, Hausform fuer falsche Werte): raw_path liegt im
    Session-Ordner, der Name passt auf raw_<NNN>.png, die Datei existiert und
    ist nicht leer. Die Namenspruefung ist NICHT redundant zur Enthaltensein-
    Pruefung: ohne sie liesse sich <session>/optik/background.png uebergeben,
    das im Ordner liegt und existiert.
    """
    sess_dir = session.info.path.resolve()
    p = Path(raw_path).resolve()
    if not p.is_relative_to(sess_dir):
        raise ValueError(
            f"raw_path liegt nicht im Session-Ordner: {p} (Session {sess_dir})")
    if not _RAW_NAME_RE.match(p.name):
        raise ValueError(
            f"raw_path stammt nicht aus stage_frame: {p.name} "
            "(erwartet raw_<NNN>.png)")
    if not p.is_file() or p.stat().st_size == 0:
        raise ValueError(f"raw_path fehlt oder ist leer: {p}")

    if i is None:
        i = max((s.i for s in session.shots), default=-1) + 1
    zeile = {"i": int(i), "file": p.name,
             "t": datetime.now().isoformat(timespec="microseconds"),
             "d_mm": round(float(feats.circle_diameter_mm), 4),
             "features": asdict(feats)}
    with open(session.info.path / "journal.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(zeile, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    return _lade_session(cfg, session.info.path)


def load_enroll_session(cfg: dict, path) -> EnrollSession:
    """Eine konkrete Session laden (Artikel und ts stehen im Pfad). Billig:
    Journal lesen, je i die letzte Zeile behalten. MISST NICHT nach."""
    return _lade_session(cfg, Path(path))


def list_enroll_sessions(cfg: dict, *,
                         article_number: str | None = None) -> list[SessionInfo]:
    """Alle OFFENEN Sessions, neueste zuerst. Die Existenz des Ordners IST
    'offen' – es gibt kein Statusfeld, das damit auseinanderlaufen koennte.

    Liest nur session.json und journal.jsonl, misst nichts nach. Mehrere
    Sessions je Artikel sind zulaessig und werden ALLE zurueckgegeben; das
    Fortsetzen adressiert spaeter immer eine konkrete Session (Artikel + ts),
    nie 'die fuer diesen Artikel'.
    """
    root = _sessions_root(cfg)
    if not root.is_dir():
        return []
    infos: list[SessionInfo] = []
    for art_dir in sorted(root.iterdir()):
        if not art_dir.is_dir():
            continue
        if article_number is not None and art_dir.name != article_number:
            continue
        for sess_dir in sorted(art_dir.iterdir()):
            if not (sess_dir / "session.json").is_file():
                continue
            infos.append(_lade_session(cfg, sess_dir).info)
    return sorted(infos, key=lambda s: s.ts, reverse=True)


# ---------- Umzug, Buchen, Verwerfen (Schritt 3) ----------

def _zielpfade(cfg: dict, session: EnrollSession) -> list:
    """[(i, quelle, ziel), ...] – REINE FUNKTION von (session.json, journal).

    Der Endname {ts}_{i:02d}.png wird bei JEDEM Lauf neu aus der
    Journal-Reihenfolge gerechnet und nirgends gemerkt, in keiner
    Fortschrittsdatei, in keinem Feld. Genau deshalb ist die Wiederaufnahme
    idempotent: derselbe Eingang erzeugt dieselbe Zuordnung, beliebig oft.

    Die ts im Namen macht den Zielpfad ausserdem sessionweit eindeutig – eine
    Kollision kann daher nicht von einer anderen Session desselben Artikels
    stammen, sondern bedeutet einen fremden Schreibzugriff.
    """
    ref = resolve(cfg["paths"]["reference_dir"]) / session.info.article_number
    ts = session.info.ts
    return [(s.i, s.raw_path, ref / f"{ts}_{s.i:02d}.png") for s in session.shots]


def _zeilen_je_pfad(db: Database, article_number: str, ziele: list) -> dict:
    """ABFRAGEND, wirft nie: Zielpfad (str) -> zeigt eine reference_features-
    Zeile darauf? Einzige Stelle, die diese Zuordnung herstellt; speist den
    Rueckumzug (je Datei) und _pruefe_buchungsstand (aggregiert).

    Nutzt references_with_meta statt eigener SQL – database.py bleibt die
    einzige Schicht, die SQLite kennt.
    """
    vorhanden = {p for p, _ in db.references_with_meta(article_number) if p}
    return {str(z): str(z) in vorhanden for z in ziele}


def _pruefe_buchungsstand(db: Database, article_number: str, ziele: list) -> str:
    """WERFEND, fuer commit. Aggregiert _zeilen_je_pfad zu drei Faellen:

        keine Zeile     -> "leer"          (Normalfall: umziehen + buchen)
        alle N Zeilen   -> "vollstaendig"  (Zustand 3: nur noch aufraeumen)
        0 < k < N       -> EnrollSessionError(kind='invariante')

    Der mittlere Fall ist die k<N-Assertion: er DARF nicht entstehen, weil die
    Buchung transaktional ist (database.add_references). Tritt er auf, ist eine
    Design-Annahme verletzt – kein Angebot, keine Automatik, kein
    Selbstheilungsversuch. Jede Reparatur rechnete an reference_stats, und die
    kennt keinen Session-Begriff.
    """
    je = _zeilen_je_pfad(db, article_number, ziele)
    gebucht = [p for p, ja in je.items() if ja]
    if not gebucht:
        return "leer"
    if len(gebucht) == len(ziele):
        return "vollstaendig"
    raise EnrollSessionError(
        f"INVARIANTE VERLETZT: {len(gebucht)} von {len(ziele)} Referenzzeilen "
        f"fuer Artikel {article_number} vorhanden. Dieser Zustand darf nicht "
        "entstehen – die Buchung schreibt alle Zeilen in EINER Transaktion. "
        "Keine automatische Reparatur: sie rechnete an reference_stats.",
        kind="invariante",
        detail={"gefunden": sorted(gebucht), "erwartet_n": len(ziele),
                "article_number": article_number})


def _umzug_plan(ziele: list) -> list:
    """Vier-Faelle-Entscheidung je Datei, OHNE Seiteneffekt.

    EINE Stelle entscheidet, zwei lesen: _move_session_files fuehrt aus,
    --dry-run zeigt nur an. Getrennt gepflegt koennten Plan und Ausfuehrung
    auseinanderlaufen — und ein --dry-run, der etwas anderes sagt als der
    echte Lauf, ist schlimmer als keiner.
    """
    plan = []
    for i, quelle, ziel in ziele:
        q, z = quelle.exists(), ziel.exists()
        aktion = ("verschieben" if q and not z else
                  "bereits_erledigt" if not q and z else
                  "kollision" if q and z else "datei_fehlt")
        plan.append({"i": i, "quelle": str(quelle), "ziel": str(ziel),
                     "aktion": aktion})
    return plan


def _reverse_plan(ziele: list, je_pfad: dict) -> list:
    """Gegenrichtung, ebenfalls ohne Seiteneffekt. Dieselbe Trennung wie
    _umzug_plan: entscheiden hier, ausfuehren in _reverse_move."""
    plan = []
    for i, quelle, ziel in ziele:
        q, z = quelle.exists(), ziel.exists()
        if not q and z and je_pfad.get(str(ziel)):
            aktion = "gebucht_nicht_angefasst"
        elif not q and z:
            aktion = "zurueckholen"
        elif q and z:
            aktion = "ziel_ist_fremd_nicht_angefasst"
        elif q and not z:
            aktion = "nichts_zu_tun"
        else:
            aktion = "VERLOREN"
        plan.append({"i": i, "quelle": str(quelle), "ziel": str(ziel),
                     "aktion": aktion})
    return plan


def _move_session_files(cfg: dict, session: EnrollSession, ziele: list) -> list:
    """Umzug Session -> reference_dir, idempotent, vier Faelle je Datei.

    os.rename ist innerhalb eines Dateisystems atomar gegenueber Beobachtern
    (POSIX per Standard, Windows innerhalb eines Volumes). Ein Zustand, in dem
    Quelle UND Ziel aus DEMSELBEN Vorgang existieren, kann nicht auftreten –
    die vier Faelle sind damit vollstaendig und disjunkt:

        Quelle da, Ziel fehlt  -> verschieben
        Quelle weg, Ziel da    -> in einem frueheren Lauf erledigt, ueberspringen
        Quelle da UND Ziel da  -> Fremdkollision, Abbruch
        Quelle weg, Ziel fehlt -> Datei verschwunden, Abbruch

    shutil.move waere hier falsch: es faellt bei EXDEV still auf copy+delete
    zurueck – nicht atomar, und das Loeschen der Quelle waere ein verdeckter
    Regelverstoss. os.rename scheitert dort laut.

    Der PLAN wird von _umzug_plan gerechnet, damit --dry-run und die
    Ausfuehrung nicht auseinanderlaufen koennen: EINE Stelle entscheidet, zwei
    lesen sie. Und es wird ERST der ganze Plan geprueft, DANN bewegt – sonst
    liesse eine Kollision bei Datei k die Dateien 0..k-1 verschoben zurueck,
    also einen vermeidbaren Zwischenzustand.
    """
    plan = _umzug_plan(ziele)
    for e in plan:
        if e["aktion"] == "kollision":
            raise EnrollSessionError(
                f"Fremdkollision bei Shot {e['i']}: {e['ziel']} existiert "
                "bereits und stammt nicht aus diesem Umzug (der Zielname "
                "traegt die Session-ts, ist also sessionweit eindeutig). Es "
                "hat jemand anders in reference_dir geschrieben.",
                kind="kollision", detail=e)
        if e["aktion"] == "datei_fehlt":
            raise EnrollSessionError(
                f"Datei zu Shot {e['i']} ist verschwunden – weder "
                f"{e['quelle']} noch {e['ziel']} existiert.",
                kind="datei_fehlt", detail=e)

    ziel_dir = resolve(cfg["paths"]["reference_dir"]) / session.info.article_number
    ziel_dir.mkdir(parents=True, exist_ok=True)
    for e in plan:
        if e["aktion"] == "verschieben":
            os.rename(e["quelle"], e["ziel"])
    return plan


def _reverse_move(cfg: dict, session: EnrollSession, ziele: list,
                  je_pfad: dict) -> list:
    """Rueckumzug reference_dir -> Session, Gegenrichtung der vier Faelle.

    Ohne ihn waere ein abgebrochener Umzug eine Sackgasse: Teile laegen in
    reference_dir, der Rest in der Session, Fortsetzen braeche reproduzierbar
    wieder ab, und "ganzen Ordner nach verworfen/" verschoebe eine
    unvollstaendige Session.

    Zwei Schranken, damit nie eine echte Referenz aus reference_dir gezogen
    wird: der Name muss exakt {ts}_{i:02d}.png mit DIESER Session-ts sein (per
    Konstruktion von _zielpfade), und es darf KEINE reference_features-Zeile
    darauf zeigen. Die DB-Schranke ist die entscheidende.
    """
    plan = _reverse_plan(ziele, je_pfad)
    for e in plan:
        if e["aktion"] == "zurueckholen":
            os.rename(e["ziel"], e["quelle"])
            e["aktion"] = "zurueckgeholt"     # ausgefuehrt, nicht nur geplant
    return plan


def _raeume_nach_backups(cfg: dict, session: EnrollSession) -> Path:
    """Den (nach dem Umzug PNG-losen) Session-Ordner nach backups/ verschieben.
    Nie loeschen – move-don't-delete. Im Regelfall sind das einige KB
    (session.json + journal.jsonl + optik/); Waisen-PNGs und Retake-Vorgaenger
    fahren als Vollbilder mit, das sind dann Megabyte.

    Das Ziel kommt aus paths.backups_dir und NICHT aus einem Literal: sonst
    loeste resolve() immer gegen project_root() auf, und jeder Testlauf
    schriebe in den echten Projektbaum."""
    datum = datetime.now().strftime("%Y-%m-%d")
    ziel = (resolve(cfg.get("paths", {}).get("backups_dir", "backups"))
            / f"{datum}-enroll-sessions"
            / f"{session.info.article_number}-{session.info.ts}")
    ziel.parent.mkdir(parents=True, exist_ok=True)
    if ziel.exists():
        ziel = ziel.parent / f"{ziel.name}-{int(time.time() * 1000)}"
    shutil.move(str(session.info.path), str(ziel))
    return ziel


def commit_enroll_session(cfg: dict, session: EnrollSession) -> int:
    """Buchen unter INVARIANTE U1: erst ALLE N Dateien verschieben, danach ALLE
    N Referenzzeilen und die Neuberechnung von reference_stats in GENAU EINER
    Transaktion. Nie umgekehrt – die umgekehrte Reihenfolge erzeugt bei einem
    Absturz dazwischen genau die Zeilen mit toten image_path, gegen die das
    Paket gerichtet ist.

    Liest das Journal von der Platte NEU und benutzt das uebergebene Objekt nur
    fuer den Pfad: dieselbe Regel wie bei der Zuordnung i -> Endname. Ein
    veraltetes In-Memory-Objekt kann damit keine falschen Werte buchen. Gebucht
    werden die JOURNALWERTE.

    Pruefungen vor dem ersten Schreibzugriff, in dieser Reihenfolge:
      1. Lueckenlosigkeit (distinkte i == {0..N-1}, N >= 1)
      2. Mount-Gleichheit (die Config kann sich seit dem Anlegen geaendert haben)
      3. Fingerabdruck – der kritische Moment, hier entsteht sigma_enroll
      4. Buchungsstand (leer / vollstaendig / dazwischen -> kind='invariante')

    Bei Buchungsstand "vollstaendig" (Zustand 3: Absturz zwischen Transaktion
    und Aufraeumen) werden Umzug und Transaktion UEBERSPRUNGEN – es folgt nur
    das Aufraeumen. Rueckgabe ist in beiden Wegen N.
    """
    session = _lade_session(cfg, session.info.path)
    _pruefe_luecken(session)
    _pruefe_mount(cfg)
    _pruefe_fingerabdruck(cfg, session)

    artikel = session.info.article_number
    ziele = _zielpfade(cfg, session)
    nur_ziele = [z for _, _, z in ziele]

    db = Database(cfg)
    try:
        stand = _pruefe_buchungsstand(db, artikel, nur_ziele)
        if stand == "leer":
            _move_session_files(cfg, session, ziele)
            db.add_references(
                artikel,
                [(s.features, str(z)) for s, (_, _, z) in zip(session.shots, ziele)])
    finally:
        db.close()
    _raeume_nach_backups(cfg, session)
    return len(ziele)


def plan_commit_enroll_session(cfg: dict, session: EnrollSession) -> dict:
    """--dry-run fuer commit: ALLE VIER Pruefungen laufen echt, danach der
    Umzugsplan – aber keine Datei wird bewegt und die DB nur gelesen.

    Faellt eine Pruefung, wirft diese Fassade genauso wie commit selbst. Das
    ist der Punkt: ein Probelauf, der andere Fehler meldet als der echte,
    taeuscht Sicherheit vor."""
    session = _lade_session(cfg, session.info.path)
    _pruefe_luecken(session)
    _pruefe_mount(cfg)
    _pruefe_fingerabdruck(cfg, session)
    ziele = _zielpfade(cfg, session)
    db = Database(cfg)
    try:
        stand = _pruefe_buchungsstand(db, session.info.article_number,
                                      [z for _, _, z in ziele])
    finally:
        db.close()
    return {"stand": stand, "n": len(ziele), "plan": _umzug_plan(ziele),
            "article_number": session.info.article_number, "ts": session.info.ts}


def plan_discard_enroll_session(cfg: dict, session: EnrollSession) -> dict:
    """--dry-run fuer discard: die vollstaendige Gegenrichtungs-Tabelle je i,
    ohne eine Datei zu bewegen und ohne info.json zu schreiben.

    Der Rueckumzug greift AUS reference_dir heraus – das ist die gefaehrlichere
    Richtung, und genau dort will man vorher sehen, was passieren soll."""
    session = _lade_session(cfg, session.info.path)
    ziele = _zielpfade(cfg, session)
    db = Database(cfg)
    try:
        je_pfad = _zeilen_je_pfad(db, session.info.article_number,
                                  [z for _, _, z in ziele])
    finally:
        db.close()
    return {"n": len(ziele), "plan": _reverse_plan(ziele, je_pfad),
            "article_number": session.info.article_number, "ts": session.info.ts}


def discard_enroll_session(cfg: dict, session: EnrollSession, *,
                           sheet_png=None) -> Path:
    """Verwerfen: Rueckumzug, dann der VOLLSTAENDIGE Ordner nach
    data/verworfen/<artikel>/<ts>/. Loescht nichts.

    info.json protokolliert beide Orte vor dem Aufraeumen, jede Entscheidung je
    i und jede verlorene Datei – das ist das "warum verworfen"-Material.
    """
    session = _lade_session(cfg, session.info.path)
    artikel = session.info.article_number
    ziele = _zielpfade(cfg, session)

    db = Database(cfg)
    try:
        je_pfad = _zeilen_je_pfad(db, artikel, [z for _, _, z in ziele])
    finally:
        db.close()
    protokoll = _reverse_move(cfg, session, ziele, je_pfad)

    if sheet_png and Path(sheet_png).exists():
        shutil.copy2(str(sheet_png), str(session.info.path / "diagnoseblatt.png"))
    (session.info.path / "info.json").write_text(
        json.dumps({"article_number": artikel, "ts": session.info.ts,
                    "n_shots": session.info.n_shots,
                    "grund": "im Einlerndialog verworfen",
                    "rueckumzug": protokoll,
                    "reference_dir": str(resolve(cfg["paths"]["reference_dir"])
                                          / artikel)},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    ts_name = datetime.fromtimestamp(session.info.ts / 1000.0).strftime(
        "%Y%m%d-%H%M%S")
    dest = (resolve(cfg["paths"]["reference_dir"]).parent / "verworfen"
            / artikel / ts_name)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest = dest.parent / f"{ts_name}-{session.info.ts}"
    shutil.move(str(session.info.path), str(dest))
    return dest


def remeasure_session(cfg: dict, session: EnrollSession,
                      progress=None) -> tuple:
    """Fortsetzen: jeden Shot aus seinem PNG NEU vermessen (~1 s je Shot).

    LESEND – schreibt NICHTS, weder ins Journal noch sonstwohin. Fortsetzen ist
    der Rettungspfad; eine Operation, die dort schreibt, kann den Zustand
    beschaedigen, den sie retten soll. Ausserdem hat die Neumessung ungeprueften
    Determinismus: driftete sie, wanderte der Drift bei jedem Fortsetzen ins
    Journal und waere nach dreimaligem Fortsetzen eine sigma_enroll aus drei
    Segmentierungslaeufen – dieselbe Vermischung, gegen die der Fingerabdruck
    gebaut ist, nur innerhalb einer Session.

    Gibt (Session mit den NEU gemessenen Werten, Abweichungsliste) zurueck.
    Beides ausschliesslich ZUR ANZEIGE: commit_enroll_session liest das Journal
    von der Platte und bucht die JOURNALWERTE.

    Abweichung ist WARNUNG, nie Abbruch. Toleranz je Merkmal
    0,1 * sigma_floor, bezogen ueber matcher._sigma_floor – NICHT ueber direktes
    Lesen von matching.sigma_floors: nur _sigma_floor traegt die
    _FLOOR_KEY-Zuordnung (delta_e_center/_rim -> delta_e, beide Histogramm-Zonen
    -> hist_bhattacharyya). Direktes Lesen rechnete fuer diese vier Merkmale mit
    Floor 0 – exakt der Fehler, den analysis.py gemacht hat.

    progress(fertig, gesamt) wird je Shot gerufen.
    """
    from .matcher import _sigma_floor

    session = _lade_session(cfg, session.info.path)
    _pruefe_fingerabdruck(cfg, session)
    floors = cfg["matching"]["sigma_floors"]

    neue: list[SessionShot] = []
    abweichungen: list[dict] = []
    for k, shot in enumerate(session.shots, start=1):
        bild = cv2.imread(str(shot.raw_path))
        if bild is None:
            raise EnrollSessionError(
                f"Rohbild zu Shot {shot.i} nicht lesbar: {shot.raw_path}",
                kind="datei_fehlt", detail={"i": shot.i,
                                            "pfad": str(shot.raw_path)})
        feats, _seg = measure_shot(bild, cfg)
        neue.append(SessionShot(i=shot.i, raw_path=shot.raw_path,
                                d_mm=feats.circle_diameter_mm, features=feats))
        for name in SCALAR_FEATURES:
            alt, neu = scalar_value(shot.features, name), scalar_value(feats, name)
            if alt is None or neu is None:
                continue
            grenze = 0.1 * _sigma_floor(name, floors)
            if abs(neu - alt) > grenze:
                abweichungen.append({"i": shot.i, "merkmal": name,
                                     "journal": alt, "neu": neu,
                                     "delta": abs(neu - alt), "toleranz": grenze})
        if progress is not None:
            progress(k, len(session.shots))

    return EnrollSession(info=session.info, shots=neue), abweichungen


def confirm_result(report: MatchReport, article_number: str):
    """Manuelle Bestätigung einer AMBIGUOUS-Auswahl (Karten-Klick in der UI):
    Top-1 bestätigt = korrekt, anderer Kandidat = falsch mit wahrem Artikel.
    Schreibt ins gespeicherte Report-JSON (Batch-Auswertung liest es)."""
    from .reporting import predicted_article, save_verdict
    return save_verdict(report, correct=(article_number == predicted_article(report)),
                        true_article=article_number)


def confirm_no_match(report: MatchReport):
    """Bestätigung „zu Recht abgelehnt" (Button bei REJECT): das Objekt ist
    tatsächlich nicht in der Datenbank. Fassade wie confirm_result, damit UIs
    reporting.py nie direkt importieren müssen."""
    from .reporting import save_no_match_verdict
    return save_no_match_verdict(report)


def reject_result(report: MatchReport, true_article: str | None = None):
    """Manuelle Korrektur „Keiner davon" (Button bei AMBIGUOUS/REJECT):
    verdict=wrong, unabhängig von der Top-1-Vorhersage – der wahre Artikel
    (oder None = weiterhin unbekannt) fließt als Label ins Report-JSON, Futter
    für die Verwechslungsmatrix der Batch-Auswertung. Dünne Fassade wie
    confirm_result, damit UIs reporting.py nie direkt importieren müssen."""
    from .reporting import save_verdict
    return save_verdict(report, correct=False, true_article=true_article)


def render_report_overlay(image: np.ndarray, report: MatchReport) -> np.ndarray:
    """Annotiertes Ergebnisbild: Kontur (rot bei Randberührung, sonst grün)
    plus Ø-Maßlinie mit mm-Beschriftung. Arbeitet nur mit dem MatchReport
    (Kontur-Polygon + Messwerte) – funktioniert daher auch für aus JSON
    geladene Reports. Das Eingangsbild bleibt unverändert (Kopie)."""
    out = image.copy()
    if not report.contour:
        return out
    pts = np.asarray(report.contour, dtype=np.int32).reshape(-1, 1, 2)
    color = (0, 0, 255) if report.touches_border else (0, 255, 0)
    thickness = max(2, image.shape[1] // 640)
    cv2.polylines(out, [pts], isClosed=True, color=color, thickness=thickness)

    # Beschriftung: der höhenkompensierte Ø des Top-Kandidaten (dieselbe
    # Zahl wie auf der ResultCard – zwei verschiedene mm-Werte im selben
    # Ergebnis würden nur verwirren); ohne Kandidaten der Boden-Ebenen-Wert.
    d_mm = (report.measured or {}).get("circle_diameter_mm")
    if report.candidates:
        d_mm = report.candidates[0].corrected_diameter_mm
    if d_mm and not report.touches_border:
        # Maßlinie horizontal über die Konturbreite auf Schwerpunkthöhe
        xy = pts.reshape(-1, 2)
        cx, cy = report.centroid_px or xy.mean(axis=0)
        x0, x1 = int(xy[:, 0].min()), int(xy[:, 0].max())
        y = int(cy)
        cv2.line(out, (x0, y), (x1, y), (255, 255, 255), thickness)
        for x in (x0, x1):
            cv2.line(out, (x, y - 6 * thickness), (x, y + 6 * thickness),
                     (255, 255, 255), thickness)
        label = f"Ø {d_mm:.1f} mm".replace(".", ",")
        scale = image.shape[1] / 1500.0
        cv2.putText(out, label, (int(cx) + 4 * thickness, y - 4 * thickness),
                    cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0),
                    thickness * 3, cv2.LINE_AA)
        cv2.putText(out, label, (int(cx) + 4 * thickness, y - 4 * thickness),
                    cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255),
                    thickness, cv2.LINE_AA)
    return out


# ---------- Lese-Fassaden für UIs (Admin-Panel, Spec Abschnitt 4) ----------
# Gegenstück zu confirm_result & Co.: UIs importieren reporting.py auch zum
# LESEN nie direkt, und Pfade löst ausschliesslich diese Schicht auf.

def load_saved_reports(cfg: dict,
                       limit: int | None = None
                       ) -> list[tuple[Path, MatchReport]]:
    """Gespeicherte Identifikations-Reports aus paths.captures_dir,
    neueste zuerst nach DATEINAME (ms-Zeitstempel) — bewusst nicht mtime:
    save_verdict schreibt Report-JSONs neu, ein bewerteter alter Report
    stünde sonst fälschlich vorn (Befund 2026-08-10). Defekte JSONs werden
    übersprungen; `limit` begrenzt auf die neuesten n. Ohne
    paths.captures_dir: leere Liste — konsistent mit
    _save_capture_and_report, das dann nichts speichert."""
    from .reporting import load_reports
    cap = cfg.get("paths", {}).get("captures_dir")
    if not cap:
        return []
    return load_reports(resolve(cap), limit=limit, sort_by="name")


def report_judgement(report: MatchReport) -> bool | None:
    """War die Top-1-Vorhersage richtig? True/False, None = unbewertet."""
    from .reporting import judgement
    return judgement(report)


def report_predicted_article(report: MatchReport) -> str:
    """Top-1-Artikelnummer des Reports; NO_MATCH ohne Kandidaten."""
    from .reporting import predicted_article
    return predicted_article(report)


def optics_fingerprint(cfg: dict) -> dict | None:
    """Optik-Fingerprint der aktuellen Konfiguration (Status-Seite).

    None, wenn Kalibrierung oder Hintergrund fehlen — das ist der
    Leerzustand „nicht kalibriert", kein Fehler (Spec Abschnitt 6)."""
    if not (resolve(cfg["calibration"]["file"]).exists()
            and resolve(cfg["calibration"]["background_file"]).exists()):
        return None
    return _fingerabdruck(cfg)


def list_articles(cfg: dict) -> list[ArticleInfo]:
    """Artikel + Referenzanzahl fürs UI, NATÜRLICH sortiert (LOEFFEL-2 vor
    LOEFFEL-11). Leere Liste, solange keine DB existiert (kein Anlegen als
    Nebenwirkung, wie get_status).

    Die Sortierung sitzt hier und NICHT in `Database.all_articles()`: von
    dort holt sich `matcher.match()` die Kandidaten, und weil die spätere
    Sortierung nach dem gerundeten log_score stabil ist, entscheidet die
    DB-Reihenfolge bei Gleichstand über Top-1. Diese Fassade ist die
    Anzeigeschicht — sie speist die Artikel-Combo des Einlerndialogs und
    den Korrekturdialog, sonst nichts."""
    if not resolve(cfg["paths"]["db_file"]).exists():
        return []
    db = Database(cfg)
    try:
        counts = db.reference_counts()
        return [ArticleInfo(
            article_number=a.article_number, name=a.name, category=a.category,
            diameter_mm=a.diameter_mm, height_mm=a.height_mm,
            n_references=counts.get(a.article_number, 0),
            width_mm=a.width_mm, depth_mm=a.depth_mm)
            for a in sorted(db.all_articles(),
                            key=lambda a: natuerlicher_schluessel(
                                a.article_number))]
    except Exception:
        return []
    finally:
        db.close()


def run_report_analysis(cfg: dict,
                        reports_dir: str | Path | None = None,
                        run_id: str | None = None) -> Path:
    """Analyse-Lauf für UIs: Quell- UND Zielpfad werden HIER aufgelöst,
    analysis.run_analysis rechnet nur noch (Spec Stufe 2, Zugriffsweg;
    Freigabe 2026-08-11). Bewusst ohne archive und ohne publish — beides
    bleibt CLI-only: archive verschiebt Report-JSONs aus dem Bestand
    (Read-only-Definition, Spec Abschnitt 5), publish schreibt ins
    versionierte Archiv."""
    from .analysis import run_analysis
    src = resolve(reports_dir) if reports_dir else resolve(
        cfg.get("paths", {}).get("captures_dir", "data/captures"))
    out_base = resolve(cfg.get("analysis", {}).get("output_dir",
                                                   "reports/analysis"))
    return run_analysis(cfg, reports_dir=src, run_id=run_id,
                        out_dir=out_base)


def list_analysis_runs(cfg: dict) -> tuple[list[AnalysisRunInfo], int]:
    """Lauf-Historie unter analysis.output_dir: (gültige Läufe, Zahl der
    ungültigen Ordner). Gültig = report.md UND metrics.json (Listbarkeits-
    Kriterium, Spec Stufe 2) — der Rest wird gezählt, nie verschwiegen.
    Sortiert nach DATEIZEIT von report.md, neueste zuerst: run_ids sind
    teils frei vergeben (phase-b-korrigiert, stufeA-v2), Namen sortieren
    hier nichts (Freigabe-Ergänzung 4, 2026-08-11)."""
    base = resolve(cfg.get("analysis", {}).get("output_dir",
                                               "reports/analysis"))
    if not base.is_dir():
        return [], 0
    gueltig: list[AnalysisRunInfo] = []
    ungueltig = 0
    for d in sorted(base.iterdir()):
        if not d.is_dir():
            continue
        report_md = d / "report.md"
        if report_md.is_file() and (d / "metrics.json").is_file():
            gueltig.append(AnalysisRunInfo(
                run_id=d.name, path=d,
                mtime_unix=report_md.stat().st_mtime))
        else:
            ungueltig += 1
    gueltig.sort(key=lambda r: r.mtime_unix, reverse=True)
    return gueltig, ungueltig


def nominal_size_mm(article) -> float | None:
    """Wirksames Vorfilter-Nominal (Stufe 3 Teil A): diameter_mm bei
    runden, max(width, depth) bei länglichen Artikeln — EXAKT
    matcher._nominal_size_mm, hier nur öffentlich gemacht. Die Regel wird
    nirgends dupliziert (der hypot-Fehler vom 2026-07-21 entstand genau
    so). Nimmt Article wie ArticleInfo (duck-typed)."""
    from .matcher import _nominal_size_mm
    return _nominal_size_mm(article)


def export_analysis_run(run_dir: str | Path, ziel: str | Path,
                        als_zip: bool = False) -> Path:
    """Analyse-Lauf KOMPLETT an einen frei gewählten Ort AUSSERHALB des
    Projekts exportieren (Ordner-Kopie oder ZIP). Freigabe 2026-08-11.

    Bewusst NICHT --publish: publish kopiert Aggregate ins VERSIONIERTE
    reports/archive (CLI-only, Spec Punkt 6) — der Export ist eine
    private Komplett-Kopie. Regeln:
    - Quelle muss ein gültiger Lauf sein (report.md UND metrics.json,
      Listbarkeits-Kriterium) — fängt auch den zwischen Auswahl und
      Export verschwundenen Ordner ab.
    - Ziel im aufgelösten Projekt-Root ist gesperrt: der Export würde
      als vermeintlicher Lauf in der Historie auftauchen oder den
      Git-Status verschmutzen. Path.resolve() folgt Symlinks — der
      Symlink-Umweg ins Projekt ist damit mit abgedeckt.
    - Ziel existiert: Fehler, nie stumm überschreiben (Semantik von
      publish_run/publish_review).
    Guard-Verstöße: ValueError mit Hinweistext; IO-Fehler (OSError,
    z. B. Ziel nicht beschreibbar) propagieren — die Seite zeigt beide
    als Fehlertext."""
    from .config import project_root
    src = Path(run_dir)
    if not ((src / "report.md").is_file()
            and (src / "metrics.json").is_file()):
        raise ValueError("Kein gültiger Analyse-Lauf (report.md und "
                         f"metrics.json erwartet): {src}")
    ziel = Path(ziel).expanduser().resolve()
    if als_zip:
        # Endung normalisieren, BEVOR geprüft wird — auch '.ZIP':
        # make_archive schreibt immer kleingeschrieben, exists() muss
        # denselben Pfad prüfen (Review-Befund 2026-08-11).
        ziel = (ziel.with_suffix(".zip") if ziel.suffix.lower() == ".zip"
                else ziel.with_name(ziel.name + ".zip"))
    wurzel = Path(project_root()).resolve()
    gesperrt = ("Export ins Projektverzeichnis ist gesperrt "
                f"({wurzel}) — bitte einen Ort ausserhalb wählen.")
    if ziel == wurzel or wurzel in ziel.parents:
        raise ValueError(gesperrt)
    # Case-insensitive Dateisysteme (APFS/NTFS): resolve() kanonisiert
    # die Schreibweise nicht — ein handgetipptes 'DOCUMENTS/…' umginge
    # den Pfadvergleich. Deshalb zusätzlich Inode-Vergleich des tiefsten
    # EXISTIERENDEN Vorfahren des Ziels gegen den Root.
    try:
        wstat = wurzel.stat()
        probe = ziel
        while not probe.exists():
            probe = probe.parent
        while True:
            s = probe.stat()
            if (s.st_dev, s.st_ino) == (wstat.st_dev, wstat.st_ino):
                raise ValueError(gesperrt)
            if probe == probe.parent:
                break
            probe = probe.parent
    except OSError:
        pass    # Root/Vorfahr nicht statbar — Pfadvergleich oben bleibt
    if ziel.exists():
        raise ValueError(f"Ziel existiert bereits: {ziel}. Export "
                         "überschreibt nie.")
    if als_zip:
        ziel.parent.mkdir(parents=True, exist_ok=True)
        # base_dir=src.name: das Archiv trägt die run_id als oberste
        # Ebene — symmetrisch zum Ordner-Export, Entpacken kippt nichts
        # ins aktuelle Verzeichnis (Review 2026-08-11).
        return Path(shutil.make_archive(str(ziel.with_suffix("")), "zip",
                                        root_dir=src.parent,
                                        base_dir=src.name))
    return Path(shutil.copytree(src, ziel))


def reference_statistics(cfg: dict, article_number: str):
    """Enrollment-Statistik eines Artikels aus reference_stats (Stufe 3
    Teil B1): EnrollmentStats (n_shots, scalar_mean/std, proto_std) oder
    None — auch bei fehlender/kaputter DB oder schlanker Config (die UI
    ruft aus einem Qt-Slot; Review 2026-08-11). Die UI liest nur
    Attribute — kein features-Import in ui_qt."""
    db_file = cfg.get("paths", {}).get("db_file")
    if not db_file or not resolve(db_file).exists():
        return None
    try:
        db = Database(cfg)
    except Exception:
        return None
    try:
        return db.stats_for(article_number)
    except Exception:
        return None
    finally:
        db.close()


def min_shots_floor() -> int:
    """MIN_N der Floor-Analyse (floor_analysis.py) für den
    „n < MIN_N"-Marker der Referenz-Kennzahlen — lazy, damit pipeline
    floor_analysis nicht beim Import zieht (Konstanten über pipeline,
    Zugriffsweg-Präzedenz NO_MATCH)."""
    from .floor_analysis import MIN_N
    return int(MIN_N)


def config_with_origin(config_path: str | Path | None = None
                       ) -> list[tuple[str, str, str]]:
    """Effektive Config als (key_pfad, wert, herkunft) je Blatt-Key —
    Herkunft durch GETRENNTES Laden von Basis- und Lokal-Schicht
    (config.local_override), Merge nur auf Anzeige-Ebene. Read-only,
    kein Schreibpfad, kein Export (Spec Punkt 11)."""
    import yaml

    from .config import DEFAULT_CONFIG_PATH, _deep_merge, local_override
    pfad = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    with open(pfad, "r", encoding="utf-8") as fh:
        basis = yaml.safe_load(fh) or {}
    lokal = local_override(pfad)

    def _blaetter(d: dict, prefix: str = ""):
        for k in sorted(d, key=str):
            v = d[k]
            key = f"{prefix}{k}"
            if isinstance(v, dict):
                yield from _blaetter(v, key + ".")
            else:
                yield key, v

    def _hat(d: dict, key_pfad: str) -> bool:
        teil = d
        for t in key_pfad.split("."):
            if not isinstance(teil, dict) or t not in teil:
                return False
            teil = teil[t]
        return True

    effektiv = _deep_merge(basis, lokal) if lokal else basis
    return [(key, str(wert),
             "config.local.yaml" if _hat(lokal, key) else "config.yaml")
            for key, wert in _blaetter(effektiv)]


def _thin_contour(seg: SegmentationResult | None) -> list | None:
    """Konturpolygon fürs Report-Overlay – ausgedünnt, ein 4K-Teller braucht
    keine 10k Punkte im JSON."""
    if seg is None or seg.contour is None:
        return None
    pts = seg.contour.reshape(-1, 2)
    step = max(1, len(pts) // 400)
    return pts[::step].astype(int).tolist()


def _centroid_px(seg: SegmentationResult | None) -> list | None:
    """Objektschwerpunkt [x, y] in px – Grundlage der Positionsanalyse
    (Messfehler über die Bildposition, z.B. Randverzerrung des Objektivs)."""
    if seg is None or seg.contour is None:
        return None
    m = cv2.moments(seg.contour)
    if m["m00"] == 0:
        return None
    return [round(m["m10"] / m["m00"], 1), round(m["m01"] / m["m00"], 1)]


class Pipeline:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.cal: Calibration = load_calibration(cfg)
        self.background: np.ndarray = load_background(cfg)
        self.db = Database(cfg)

    def analyze(self, image: np.ndarray) -> tuple[SegmentationResult, Features]:
        """Segment and measure – shared by enroll and identify."""
        seg = segment(image, self.background)
        if seg.touches_border:
            raise SegmentationError(
                "Object touches the frame border – measurement would be wrong. "
                "Center the item; if it does not fit, see README (FOV limitation).",
                segmentation=seg,
            )
        feats = extract(image, seg, self.cal, self.cfg)
        return seg, feats

    def identify(self, image: np.ndarray, *, source_path: str | None = None,
                 label: str | None = None) -> IdentifyOutcome:
        try:
            seg, feats = self.analyze(image)
        except SegmentationError as e:
            # Keep the (border-touching) segmentation, if any, so the UI can
            # still show the contour that caused the rejection.
            seg_err = e.segmentation
            report = MatchReport(
                decision=DECISION_REJECT, message=f"Segmentierung: {e}",
                contour=_thin_contour(seg_err),
                touches_border=getattr(seg_err, "touches_border", None),
                timestamp=datetime.now().isoformat(timespec="microseconds"),
                image_path=source_path, label=label,
                centroid_px=_centroid_px(seg_err),
                image_size=[image.shape[1], image.shape[0]] if image is not None else None)
            self._save_capture_and_report(report, image)
            return IdentifyOutcome(None, seg_err, report)
        report = match(feats, self.db, self.cal, self.cfg,
                       image_path=source_path, label=label,
                       contour=_thin_contour(seg), touches_border=seg.touches_border)
        report.centroid_px = _centroid_px(seg)
        report.image_size = [image.shape[1], image.shape[0]]
        self._save_capture_and_report(report, image)
        return IdentifyOutcome(feats, seg, report)

    def _save_capture_and_report(self, report: MatchReport,
                                 image: np.ndarray | None) -> None:
        """Jede Identifikation hinterlässt Capture + Report-JSON in
        data/captures/ – Futter für das Scoring-Dashboard (Batch-Analyse).
        Ohne paths.captures_dir (z.B. synthetische Tests) wird nichts
        geschrieben; bei identify --image bleibt image_path das Original."""
        cap = self.cfg.get("paths", {}).get("captures_dir")
        if not cap:
            return
        d = resolve(cap)
        d.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
        if report.image_path is None and image is not None:
            p = d / f"{ts}.jpg"
            cv2.imwrite(str(p), image)
            report.image_path = str(p)
        json_path = d / f"{ts}.json"
        report.report_path = str(json_path)   # Feedback (richtig/falsch) schreibt hierhin zurück
        json_path.write_text(report.to_json(), encoding="utf-8")

    def enroll(self, image: np.ndarray, article_number: str,
               image_path: str | None = None) -> tuple[Features, SegmentationResult]:
        """Measure AND store in one step (CLI flow). Returns (features,
        segmentation) so callers can show the measured contour. UIs that want
        a confirm step call analyze() first and save_reference() on confirm."""
        seg, feats = self.analyze(image)
        self.db.add_reference(article_number, feats, image_path)
        return feats, seg

    def save_reference(self, article_number: str, feats: Features,
                       image_path: str | None = None) -> None:
        """Second half of the two-step enroll flow: persist an already-measured
        (and user-approved) reference.

        OHNE AUFRUFER seit 2026-08-08 (Schritt 7 des Session-Pakets): ihr
        einziger war save_enrollment, und der Einlerndialog geht jetzt ueber
        commit_enroll_session. Auch kein Test ruft sie direkt.

        Sie bleibt trotzdem stehen: sie ist die dokumentierte zweite Haelfte der
        Zwei-Schritt-Fassade (analyze -> save_reference, siehe enroll() oben),
        und ein UI, das einzelne Referenzen nachtraegt, waere ein legitimer
        kuenftiger Aufrufer. Zusammenlegen oder entfernen ist als eigener
        Schritt vorgemerkt (Vormerkliste 16)."""
        self.db.add_reference(article_number, feats, image_path)

    def create_article(self, image: np.ndarray, name: str, *,
                       article_number: str | None = None,
                       height_mm: float = 0.0,
                       category: str | None = None,
                       notes: str | None = None,
                       image_path: str | None = None,
                       add_reference: bool = True
                       ) -> tuple[Article, Features, SegmentationResult]:
        """Create a brand-new article straight from one live shot – no CSV.

        The footprint is derived from the measurement: round items get
        `diameter_mm`, elongated items (spoon, knife, oval platter) get
        `width_mm`/`depth_mm` – the latter matters because the matcher's area
        plausibility check only runs when `diameter_mm` is set and would
        otherwise reject a non-round item on re-identification. When a real
        `height_mm` is given, the stored size is the height-corrected true
        size, so re-measuring the same object stays self-consistent.

        By default the same shot is stored as the first reference so the
        article is identifiable immediately (colour + shape, not geometry
        only). `article_number` is auto-derived from `name` when omitted.

        Returns (article, features, segmentation) – the segmentation lets a
        UI show the same measured contour/mask preview as identify, so a bad
        segmentation is visible before trusting the new article.

        Raises SegmentationError (object touches the border – like enroll,
        NOT caught here) and KeyError (article_number already exists).
        """
        seg, feats = self.analyze(image)
        article = self.derive_article(seg, feats, name, article_number=article_number,
                                      height_mm=height_mm, category=category, notes=notes)
        self.commit_article(article, feats if add_reference else None, image_path)
        return article, feats, seg

    def derive_article(self, seg: SegmentationResult, feats: Features, name: str, *,
                       article_number: str | None = None,
                       height_mm: float = 0.0,
                       category: str | None = None,
                       notes: str | None = None) -> Article:
        """Build the article master data from a measurement WITHOUT persisting
        anything – first half of the two-step (preview -> confirm) create flow.
        Only reads the DB (to derive a unique article number)."""
        cc = self.cfg.get("create", {})
        circ_min = float(cc.get("round_circularity_min", 0.80))
        aspect_min = float(cc.get("round_aspect_min", 0.80))
        z = self.cal.camera_height_mm

        diameter_mm = width_mm = depth_mm = None
        if feats.circularity >= circ_min and feats.aspect_ratio >= aspect_min:
            diameter_mm = round(
                height_corrected_scale(feats.circle_diameter_mm, height_mm, z), 2)
        else:
            width_mm, depth_mm = min_area_rect_mm(seg.contour, self.cal, height_mm)

        number = article_number or self.db.generate_article_number(
            name, cc.get("article_number_prefix", ""))
        return Article(
            article_number=number, name=name, category=category,
            diameter_mm=diameter_mm, width_mm=width_mm, depth_mm=depth_mm,
            height_mm=(height_mm or None),
            color_desc=describe_color_hsv(feats.mean_hsv),
            notes=(notes or "Automatisch per Kamera angelegt."),
        )

    def commit_article(self, article: Article, feats: Features | None = None,
                       image_path: str | None = None) -> None:
        """Second half of the two-step create flow: insert the previewed
        article and (optionally) its first reference. Raises KeyError if the
        article number was taken in the meantime."""
        self.db.create_article(article)
        if feats is not None:
            self.db.add_reference(article.article_number, feats, image_path)

    def close(self) -> None:
        self.db.close()
