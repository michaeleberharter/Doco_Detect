"""Runner: Tier-1- und Tier-2-Replay ueber einen ProcessPool.

Der Replay ruft ausschliesslich pipeline.measure_shot() und
Pipeline.identify() gegen eine Buendel-Config mit captures_dir=None. Damit
bleibt der Messpfad unberuehrt UND der Lauf schreibt nichts nach
data/captures.
"""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..config import project_root
from .bundle import bundle_cfg
from .compare import FAIL, PASS, compare_tier1, compare_tier2, worst_band
from .manifest import ImageEntry, Manifest, corpus_root

# Quelldateien, deren Aenderung jedes Ergebnis ungueltig macht.
CODE_DATEIEN = ("segmentation.py", "features.py", "matcher.py", "pipeline.py",
                "calibration.py", "database.py")

# Config-Teilbaeume, die das Ergebnis beeinflussen. camera/ui/paths sind
# bewusst NICHT dabei — ein anderer Kamera-Index aendert kein Messergebnis
# auf gespeicherten Bildern.
CONFIG_TEILE = ("matching", "features", "geometry")

DEFAULT_WORKERS = 8   # gemessenes Optimum, 10 bringt nichts (Spec 5.1)


def code_fingerprint() -> str:
    h = hashlib.sha256()
    basis = project_root() / "docodetect"
    for name in CODE_DATEIEN:
        p = basis / name
        h.update(name.encode())
        h.update(p.read_bytes() if p.exists() else b"")
    return h.hexdigest()


def config_fingerprint(cfg: dict) -> str:
    teil = {k: cfg.get(k, {}) for k in CONFIG_TEILE}
    return hashlib.sha256(
        json.dumps(teil, sort_keys=True, default=str).encode()).hexdigest()


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
    return out[:subset] if subset else out


@dataclass
class RunResult:
    sha: str
    session: str
    article: str
    tier: int
    band: str
    diffs: list = field(default_factory=list)
    error: str | None = None


# --- Worker ---------------------------------------------------------------

_CTX: dict = {}


def _worker_init(cfg: dict, root_str: str) -> None:
    _CTX["cfg"] = cfg
    _CTX["root"] = Path(root_str)
    _CTX["bundles"] = {}


def _bundle_for(session: str) -> dict:
    """Buendel-Config je Session, einmal pro Worker gebaut."""
    if session not in _CTX["bundles"]:
        bdir = _CTX["root"] / session / "bundle"
        _CTX["bundles"][session] = bundle_cfg(_CTX["cfg"], bdir)
    return _CTX["bundles"][session]


def run_one(entry_dict: dict, tier: int) -> dict:
    """Ein Bild replayen. Laeuft im Worker-Prozess, gibt reine dicts zurueck
    (Dataclasses ueber Prozessgrenzen sind unnoetig fehleranfaellig)."""
    import cv2

    from ..matcher import MatchReport
    from ..pipeline import Pipeline, measure_shot
    from ..segmentation import SegmentationError

    e = ImageEntry(**entry_dict)
    root, bcfg = _CTX["root"], _bundle_for(e.session)
    res = RunResult(sha=e.sha, session=e.session, article=e.article,
                    tier=e.tier, band=PASS)
    try:
        golden = MatchReport.from_json(
            (root / e.report_rel).read_text(encoding="utf-8"))
        img = cv2.imread(str(root / e.image_rel))
        if img is None:
            res.error = "Bild nicht lesbar"
            res.band = FAIL
            return asdict(res)

        if tier == 2 and e.tier >= 2:
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
            replay = root / "runs" / "_replay"
            replay.mkdir(parents=True, exist_ok=True)
            rep = outcome.report
            rep.label, rep.verdict = e.label, e.verdict
            (replay / f"{e.sha[:8]}.json").write_text(rep.to_json(),
                                                      encoding="utf-8")
            diffs = compare_tier2(golden, rep)
        else:
            try:
                feats, seg = measure_shot(img, bcfg)
                centroid = None
                m = cv2.moments(seg.contour)
                if m["m00"]:
                    centroid = [round(m["m10"] / m["m00"], 1),
                                round(m["m01"] / m["m00"], 1)]
                diffs = compare_tier1(golden, feats, seg.area_px, centroid)
            except SegmentationError:
                # Golden brach ebenfalls ab -> reproduziert; sonst Regression.
                if golden.touches_border or golden.decision == "reject":
                    diffs = []
                else:
                    res.error = "SegmentationError, Golden war messbar"
                    res.band = FAIL
                    return asdict(res)

        res.diffs = [asdict(d) for d in diffs]
        res.band = worst_band(diffs)
    except Exception as exc:                       # noqa: BLE001
        res.error = f"{type(exc).__name__}: {exc}"
        res.band = FAIL
    return asdict(res)


# --- Orchestrierung -------------------------------------------------------

def _cache_path(root: Path) -> Path:
    return root / ".cache" / "results.json"


def _cache_key(sha: str, tier: int, code_fp: str, cfg_fp: str) -> str:
    return f"{sha}:{tier}:{code_fp[:16]}:{cfg_fp[:16]}"


def run_corpus(cfg: dict, *, sessions=None, articles=None, tier: int = 1,
               subset=None, workers: int = DEFAULT_WORKERS,
               changed_only: bool = False) -> dict:
    import time

    root = corpus_root(cfg)
    manifest = Manifest.load()
    aufgaben = auswahl(manifest.images, sessions=sessions, articles=articles,
                       tier=tier, subset=subset)
    code_fp, cfg_fp = code_fingerprint(), config_fingerprint(cfg)

    cache: dict = {}
    cp = _cache_path(root)
    if changed_only and cp.exists():
        cache = json.loads(cp.read_text(encoding="utf-8"))

    offen, ergebnisse = [], []
    for e in aufgaben:
        k = _cache_key(e.sha, tier, code_fp, cfg_fp)
        if changed_only and k in cache:
            ergebnisse.append(cache[k])
        else:
            offen.append(e)

    t0 = time.time()
    if offen:
        with ProcessPoolExecutor(max_workers=workers, initializer=_worker_init,
                                 initargs=(cfg, str(root))) as ex:
            frisch = list(ex.map(run_one, [asdict(e) for e in offen],
                                 [tier] * len(offen), chunksize=1))
        ergebnisse.extend(frisch)
        for e, r in zip(offen, frisch):
            cache[_cache_key(e.sha, tier, code_fp, cfg_fp)] = r
    dauer = time.time() - t0

    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps(cache), encoding="utf-8")

    ergebnisse.sort(key=lambda r: (r["session"], r["sha"]))
    return {"results": ergebnisse, "tier": tier, "dauer_s": round(dauer, 1),
            "n": len(ergebnisse), "neu_gerechnet": len(offen),
            "bilder_pro_s": round(len(offen) / dauer, 2) if dauer > 0 and offen else None,
            "code_fingerprint": code_fp, "config_fingerprint": cfg_fp}
