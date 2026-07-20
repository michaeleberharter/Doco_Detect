"""Runner: Tier-1- und Tier-2-Replay ueber einen ProcessPool.

Der Replay ruft ausschliesslich pipeline.measure_shot() und
Pipeline.identify() gegen eine Buendel-Config mit captures_dir=None. Damit
bleibt der Messpfad unberuehrt UND der Lauf schreibt nichts nach
data/captures.
"""

from __future__ import annotations

import atexit
import copy
import hashlib
import json
import math
import shutil
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..config import project_root
from ..pipeline import _centroid_px
from .bundle import bundle_cfg
from .compare import FAIL, PASS, compare_tier1, compare_tier2, worst_band
from .manifest import ImageEntry, Manifest, corpus_root, sha256_file

# Quelldateien, deren Aenderung jedes Ergebnis ungueltig macht. Pfade
# relativ zu docodetect/ — corpus/compare.py gehoert dazu, weil dessen
# QUANTUM/SOFT-Tabellen unmittelbar den gecachten Bandwert erzeugen.
CODE_DATEIEN = ("segmentation.py", "features.py", "matcher.py", "pipeline.py",
                "calibration.py", "database.py", "corpus/compare.py")

# Buendel-Bestandteile, die jedes Replay-Ergebnis dieser Session bestimmen.
BUENDEL_DATEIEN = ("db.sqlite3", "calibration.json", "background.png")

# Config-Teilbaeume, die das Ergebnis beeinflussen. camera/ui/paths sind
# bewusst NICHT dabei — ein anderer Kamera-Index aendert kein Messergebnis
# auf gespeicherten Bildern.
CONFIG_TEILE = ("matching", "features", "geometry")

DEFAULT_WORKERS = 8   # gemessenes Optimum, 10 bringt nichts (Spec 5.1)


def code_fingerprint() -> str:
    h = hashlib.sha256()
    basis = project_root() / "docodetect"
    for name in CODE_DATEIEN:
        p = basis.joinpath(*name.split("/"))
        if not p.exists():
            # Ein stillschweigend uebergangener Bestandteil waere schlimmer
            # als gar keiner: der Cache wuerde dann nicht mehr invalidieren.
            raise FileNotFoundError(
                f"Fingerprint-Bestandteil fehlt: {p} — CODE_DATEIEN passt "
                f"nicht mehr zum Quellbaum.")
        h.update(name.encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def config_fingerprint(cfg: dict) -> str:
    teil = {k: cfg.get(k, {}) for k in CONFIG_TEILE}
    return hashlib.sha256(
        json.dumps(teil, sort_keys=True, default=str).encode()).hexdigest()


def golden_fingerprint(root: Path, entry) -> str:
    """SHA des Golden-Reports. Ein korrigiertes Golden muss den Cache
    invalidieren — der Bild-SHA allein aendert sich dabei nicht."""
    p = Path(root) / entry.report_rel
    return sha256_file(p) if p.exists() else "fehlt"


def bundle_fingerprint(root: Path, session: str) -> str:
    """Fingerprint des eingefrorenen Session-Zustands ueber Groesse und
    mtime. Ein neuer DB-Snapshot aendert jedes Tier-2-Ergebnis."""
    bdir = Path(root) / session / "bundle"
    h = hashlib.sha256()
    for name in BUENDEL_DATEIEN:
        p = bdir / name
        h.update(name.encode())
        if p.exists():
            st = p.stat()
            h.update(f"{st.st_size}:{st.st_mtime_ns}".encode())
    return h.hexdigest()


def auswahl(images: list, *, sessions=None, articles=None, tier=None,
            subset=None) -> list:
    """Deterministische, gefilterte Aufgabenliste. Sortiert nach
    (Session, SHA), damit Laeufe vergleichbar bleiben und --subset stabil
    denselben Ausschnitt trifft."""
    out = list(images)
    if sessions:
        out = [e for e in out if e.session in set(sessions)]
    if articles:
        out = [e for e in out if e.article in set(articles)]
    if tier == 2:
        out = [e for e in out if e.tier >= 2]
    out.sort(key=lambda e: (e.session, e.sha))
    # subset=0 heisst 'kein Bild' — nicht 'alle Bilder'.
    return out[:subset] if subset is not None else out


@dataclass
class RunResult:
    sha: str
    session: str
    article: str
    tier: int                  # tatsaechlich gefahrene Stufe
    band: str
    tier_capability: int = 0   # hoechste Stufe, die dieses Bild fahren KANN
    diffs: list = field(default_factory=list)
    error: str | None = None
    # Tier-2-Replay-Report als JSON-Text. Wandert mit in den Cache, damit ein
    # Cache-Treffer den Report im neuen Lauf-Ordner materialisieren kann —
    # sonst waeren die Tier-2-Quoten unter --changed-only unvollstaendig.
    # Tier 1 laesst das Feld None.
    replay_json: str | None = None


def _json_safe(obj):
    """NaN/Infinity sind kein gueltiges JSON. Nicht-endliche Gleitkommazahlen
    (z.B. die delta=nan-Marker aus compare.py) werden zu null."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return obj


# --- Worker ---------------------------------------------------------------

_CTX: dict = {}


def _worker_init(cfg: dict, root_str: str) -> None:
    _CTX["cfg"] = cfg
    _CTX["root"] = Path(root_str)
    _CTX["bundles"] = {}


def _worker_tmpdir() -> Path:
    """Ein temporaerer Ordner je Worker-Prozess, am Prozessende geraeumt."""
    if "tmpdir" not in _CTX:
        d = tempfile.mkdtemp(prefix="docodetect-corpus-")
        _CTX["tmpdir"] = d
        atexit.register(shutil.rmtree, d, True)
    return Path(_CTX["tmpdir"])


def _bundle_for(session: str) -> dict:
    """Buendel-Config je Session, einmal pro Worker gebaut."""
    if session not in _CTX["bundles"]:
        bdir = _CTX["root"] / session / "bundle"
        _CTX["bundles"][session] = bundle_cfg(_CTX["cfg"], bdir)
    return _CTX["bundles"][session]


def _tier1_cfg(bcfg: dict) -> dict:
    """Tier-1-Config: wie die Buendel-Config, aber paths.db_file zeigt in
    einen temporaeren Worker-Ordner.

    Grund: measure_shot baut intern Pipeline(cfg) -> Database(cfg), und
    sqlite3.connect legt eine 0-Byte-Datei an, wenn der Pfad fehlt.
    Tier-1-Sessions haben per Konstruktion KEINE db.sqlite3 im Buendel
    (build.py loescht eine verirrte Datei sogar). Ohne diese Umleitung
    schriebe der Runner also genau in den fingerprint-verifizierten
    Session-Zustand hinein. Tier 2 nutzt weiter die echte Buendel-DB.
    """
    out = copy.deepcopy(bcfg)
    out.setdefault("paths", {})
    out["paths"]["db_file"] = str(_worker_tmpdir() / "tier1-leer.sqlite3")
    return out


def _replay_dir(root: Path, run_id: str) -> Path:
    """Replay-Reports je Lauf getrennt — ein geteilter Ordner wuerde bei
    gefilterten Laeufen alte mit frischen Ergebnissen mischen."""
    return Path(root) / "runs" / run_id / "replay"


def run_one(entry_dict: dict, tier: int, run_id: str) -> dict:
    """Ein Bild replayen. Laeuft im Worker-Prozess, gibt reine dicts zurueck
    (Dataclasses ueber Prozessgrenzen sind unnoetig fehleranfaellig)."""
    import cv2

    from ..matcher import MatchReport
    from ..pipeline import Pipeline, measure_shot
    from ..segmentation import SegmentationError

    # Alles ab hier laeuft im try: ein kaputter Manifest-Eintrag oder ein
    # fehlendes Buendel darf eine FAIL-Zeile erzeugen, nie den ganzen Lauf
    # abreissen (ex.map wuerde im Elternprozess weiterwerfen und saemtliche
    # Ergebnisse samt Cache-Write verlieren).
    res = RunResult(sha=str(entry_dict.get("sha", "?")),
                    session=str(entry_dict.get("session", "?")),
                    article=str(entry_dict.get("article", "?")),
                    tier=tier, band=PASS)
    try:
        e = ImageEntry(**entry_dict)
        res.tier_capability = e.tier
        tier2_lauf = tier == 2 and e.tier >= 2
        res.tier = 2 if tier2_lauf else 1
        root, bcfg = _CTX["root"], _bundle_for(e.session)

        golden = MatchReport.from_json(
            (root / e.report_rel).read_text(encoding="utf-8"))
        img = cv2.imread(str(root / e.image_rel))
        if img is None:
            res.error = "Bild nicht lesbar"
            res.band = FAIL
            return _json_safe(asdict(res))

        if tier2_lauf:
            pipe = Pipeline(bcfg)
            try:
                outcome = pipe.identify(img, source_path=str(root / e.image_rel),
                                        label=e.label)
            finally:
                pipe.close()
            # Replay-Report ablegen: daraus rechnet report.tier2_quotas() die
            # Kennzahlen. Muss hier passieren, weil der Report nur im Worker
            # existiert — captures_dir ist im Buendel bewusst None, die
            # Pipeline schreibt also selbst nichts.
            replay = _replay_dir(root, run_id)
            replay.mkdir(parents=True, exist_ok=True)
            rep = outcome.report
            rep.label, rep.verdict = e.label, e.verdict
            replay_json = rep.to_json()
            (replay / f"{e.sha[:8]}.json").write_text(replay_json,
                                                      encoding="utf-8")
            # Zusaetzlich im Ergebnis mitfuehren: nur so ueberlebt der Report
            # den Cache und steht einem spaeteren --changed-only-Lauf zur
            # Verfuegung.
            res.replay_json = replay_json
            diffs = compare_tier2(golden, rep)
        else:
            try:
                feats, seg = measure_shot(img, _tier1_cfg(bcfg))
                diffs = compare_tier1(golden, feats, seg.area_px,
                                      _centroid_px(seg))
            except SegmentationError:
                # measured ist leer <-> die Segmentierung des Goldens brach
                # ebenfalls ab (pipeline.identify baut den Fehlerreport ohne
                # measured-Argument). decision == "reject" taugt NICHT: der
                # Geometrie-Vorfilter und das z-Gate verwerfen auch nach
                # erfolgreicher Messung.
                if not (golden.measured or {}):
                    diffs = []
                else:
                    res.error = "SegmentationError, Golden war messbar"
                    res.band = FAIL
                    return _json_safe(asdict(res))

        res.diffs = [asdict(d) for d in diffs]
        res.band = worst_band(diffs)
    except Exception as exc:                       # noqa: BLE001
        res.error = f"{type(exc).__name__}: {exc}"
        res.band = FAIL
    return _json_safe(asdict(res))


# --- Orchestrierung -------------------------------------------------------

def _cache_path(root: Path) -> Path:
    return Path(root) / ".cache" / "results.json"


def _materialisiere_replay(root: Path, run_id: str, ergebnisse: list) -> int:
    """Mitgefuehrte Replay-Reports in das Replay-Verzeichnis des aktuellen
    Laufs schreiben. Gibt die Zahl der geschriebenen Reports zurueck."""
    mit_report = [r for r in ergebnisse if r.get("replay_json")]
    if not mit_report:
        return 0
    replay = _replay_dir(root, run_id)
    replay.mkdir(parents=True, exist_ok=True)
    for r in mit_report:
        ziel = replay / f"{str(r.get('sha', '?'))[:8]}.json"
        if not ziel.exists():
            ziel.write_text(r["replay_json"], encoding="utf-8")
    return len(mit_report)


def _cache_key(sha: str, tier: int, code_fp: str, cfg_fp: str,
               golden_fp: str = "", bundle_fp: str = "") -> str:
    return (f"{sha}:{tier}:{code_fp[:16]}:{cfg_fp[:16]}"
            f":{golden_fp[:16]}:{bundle_fp[:16]}")


def run_corpus(cfg: dict, *, sessions=None, articles=None, tier: int = 1,
               subset=None, workers: int = DEFAULT_WORKERS,
               changed_only: bool = False, run_id: str | None = None) -> dict:
    root = corpus_root(cfg)
    if not root.exists():
        raise RuntimeError(
            f"Korpus-Verzeichnis fehlt: {root}. Zuerst 'corpus-build' "
            f"ausfuehren oder paths.corpus_dir korrigieren.")

    manifest = Manifest.load()
    if not manifest.images:
        raise RuntimeError(
            "Korpus-Manifest ist leer — kein einziges Bild zum Replayen. "
            "Zuerst 'corpus-build' ausfuehren. 'Keine Bilder' ist kein "
            "gruener Lauf.")

    aufgaben = auswahl(manifest.images, sessions=sessions, articles=articles,
                       tier=tier, subset=subset)
    if not aufgaben:
        raise RuntimeError(
            "Die Auswahl (sessions/articles/tier/subset) trifft kein "
            "einziges Bild. Filter pruefen oder 'corpus-build' erneut "
            "ausfuehren — ein leerer Lauf darf nicht wie 'alles gruen' "
            "aussehen.")

    run_id = run_id or time.strftime("%Y%m%d-%H%M%S")
    code_fp, cfg_fp = code_fingerprint(), config_fingerprint(cfg)

    # Buendel-Fingerprint je Session, einmal berechnet.
    bundle_fps = {s: bundle_fingerprint(root, s)
                  for s in {e.session for e in aufgaben}}

    def key(e) -> str:
        return _cache_key(e.sha, tier, code_fp, cfg_fp,
                          golden_fingerprint(root, e), bundle_fps[e.session])

    # Den bestehenden Cache IMMER laden: ein Lauf mit --subset darf den
    # Cache des vollen Laufs nicht wegwerfen.
    cache: dict = {}
    cp = _cache_path(root)
    if cp.exists():
        try:
            cache = json.loads(cp.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            cache = {}

    offen, ergebnisse, aus_cache = [], [], []
    for e in aufgaben:
        k = key(e)
        if changed_only and k in cache:
            treffer = cache[k]
            ergebnisse.append(treffer)
            aus_cache.append(treffer)
        else:
            offen.append(e)

    # Cache-Treffer tragen ihren Tier-2-Replay-Report mit sich. Er muss im
    # Verzeichnis des AKTUELLEN Laufs landen, sonst rechnet cmd_corpus_run die
    # Quoten nur ueber die frisch gerechnete Teilmenge — im Extremfall ueber
    # gar nichts, und das Merge-Gate schwiege stillschweigend.
    _materialisiere_replay(root, run_id, aus_cache)

    t0 = time.time()
    if offen:
        with ProcessPoolExecutor(max_workers=workers, initializer=_worker_init,
                                 initargs=(cfg, str(root))) as ex:
            frisch = list(ex.map(run_one, [asdict(e) for e in offen],
                                 [tier] * len(offen), [run_id] * len(offen),
                                 chunksize=1))
        ergebnisse.extend(frisch)
        for e, r in zip(offen, frisch):
            cache[key(e)] = r
    dauer = time.time() - t0

    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps(_json_safe(cache), allow_nan=False),
                  encoding="utf-8")

    ergebnisse.sort(key=lambda r: (r["session"], r["sha"]))
    return {"results": ergebnisse, "tier": tier, "dauer_s": round(dauer, 1),
            "n": len(ergebnisse), "neu_gerechnet": len(offen),
            "bilder_pro_s": round(len(offen) / dauer, 2) if dauer > 0 and offen else None,
            "code_fingerprint": code_fp, "config_fingerprint": cfg_fp,
            "run_id": run_id}
