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
from .features import (Features, describe_color_hsv, extract,
                       height_corrected_scale, min_area_rect_mm)
from .matcher import DECISION_REJECT, MatchReport, match
from .display import (channel_percentages, format_delta, format_diameter,  # noqa: F401
                      format_measured, format_rank_line, headline,
                      natuerlicher_schluessel)  # Re-Export: UIs importieren Anzeige-Helfer NUR über pipeline
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
    DB (Enrollment-Statistik wird dabei aktualisiert)."""
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
        n_shots=len(shots),
        # Schritt 2 kennt nur "offen": die beiden anderen Werte
        # ("umzug_unterbrochen", "gebucht_aufraeumen_offen") setzen die
        # Berechnung der Zielpfade voraus, und die gehoert zum Umzug
        # (Schritt 3). Solange es kein commit gibt, kann kein anderer Zustand
        # entstehen.
        zustand="offen",
        fingerprint=kopf["fingerprint"], fingerprint_ok=ok,
        age_secs=max(0.0, time.time() - stand))
    return EnrollSession(info=info, shots=shots)


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
            n_references=counts.get(a.article_number, 0))
            for a in sorted(db.all_articles(),
                            key=lambda a: natuerlicher_schluessel(
                                a.article_number))]
    except Exception:
        return []
    finally:
        db.close()


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
        (and user-approved) reference."""
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
