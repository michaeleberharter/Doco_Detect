"""Aufnahmen aus der Fotobox als versionierte Segmentierungs-Goldens uebernehmen.

Schreibt nach `tests/fixtures/golden_captures/`: die Szenenbilder, den
zugehoerigen Hintergrund und `goldens.json` mit der je Szene gemessenen
Maskenflaeche. Der Test `tests/test_real_captures.py` liest genau diesen Satz.

    # 1. ansehen, nichts schreiben — Flaechen und Era-Abgleich pruefen
    python scripts/adopt_goldens.py --dry-run \\
        01-teeloeffel-flach=1784075122341 02-teeloeffel-diagonal=1784147898502

    # 2. uebernehmen
    python scripts/adopt_goldens.py \\
        01-teeloeffel-flach=1784075122341 ...

Rechts vom `=` steht eine Capture-ID aus `data/captures/` (ohne `.png`) ODER
ein Pfad zu einer Bilddatei. Zwei Sonderarten werden per Suffix markiert:

    01-leere-box=<id>:raises          # Segmentierung MUSS abbrechen
    17-teller-randberuehrung=<id>:border   # MUSS touches_border melden

`:border` ist kein Randfall der Bequemlichkeit: `segment()` wirft bei
Randberuehrung NICHT, es setzt nur das Flag — erst `Pipeline.analyze` macht
daraus einen Fehler. Ohne diese Szene bliebe unbemerkt, wenn die
Segmentierung die Randberuehrung verlernt und die Pipeline anfaengt,
abgeschnittene Objekte zu vermessen.

WICHTIG — die Flaeche, die hier gemessen wird, ist danach das Golden. Der
Helfer nimmt sie NICHT ab: vorher jede Maske ansehen (`--overlay-dir`
schreibt Kontroll-Overlays), erst danach ohne `--dry-run` laufen lassen.
Ein unbesehen uebernommenes Golden zementiert den Fehler, den es messen soll.

Der Hintergrund wird mitkopiert (Default `calibration/background.png`).
Das ist keine Bequemlichkeit: eine Aufnahme ist nur vergleichbar, solange
sie zur Beleuchtung ihres Hintergrunds passt. Szenen und Hintergrund
gehoeren deshalb als EIN Satz ins Repo.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import date
from pathlib import Path

import cv2
import numpy as np

PROJEKT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJEKT))

ZIEL = PROJEKT / "tests" / "fixtures" / "golden_captures"
ERA_MEDIAN_MAX = 6      # muss zu tests/test_real_captures.py passen


def _bildpfad(wert: str) -> Path:
    """Capture-ID oder Pfad -> Datei. IDs werden gegen data/captures/ aufgeloest."""
    p = Path(wert)
    if p.suffix and p.is_file():
        return p
    for kandidat in (PROJEKT / "data" / "captures" / f"{wert}.png",
                     PROJEKT / "data" / "captures" / f"{wert}.jpg"):
        if kandidat.is_file():
            return kandidat
    raise SystemExit(f"[adopt] Aufnahme nicht gefunden: {wert} "
                     f"(weder Pfad noch ID unter data/captures/)")


def parse_zuordnung(argumente: list[str]) -> list[tuple[str, Path, str]]:
    """`szene=quelle[:raises]` -> (szene, pfad, kind)."""
    out = []
    for arg in argumente:
        if "=" not in arg:
            raise SystemExit(f"[adopt] '{arg}' ist keine Zuordnung "
                             f"szene=capture-id (siehe --help)")
        szene, quelle = arg.split("=", 1)
        kind = "segment"
        for suffix, art in ((":raises", "raises"),
                            (":border", "touches_border")):
            if quelle.endswith(suffix):
                quelle, kind = quelle[:-len(suffix)], art
                break
        szene = szene.strip()
        if not szene:
            raise SystemExit(f"[adopt] leerer Szenenname in '{arg}'")
        out.append((szene, _bildpfad(quelle.strip()), kind))
    doppelt = {s for s, _, _ in out if [x for x, _, _ in out].count(s) > 1}
    if doppelt:
        raise SystemExit(f"[adopt] Szene mehrfach zugeordnet: "
                         f"{', '.join(sorted(doppelt))}")
    return out


def era_median(img, bg) -> float:
    """Median-|diff| zwischen Szenenboden und Hintergrund (Era-Abgleich)."""
    cue = cv2.GaussianBlur(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (3, 3), 0)
    bgc = cv2.GaussianBlur(cv2.cvtColor(bg, cv2.COLOR_BGR2GRAY), (3, 3), 0)
    return float(np.median(cv2.absdiff(cue, bgc)))


def _overlay(img, mask):
    """Kontroll-Overlay: Maske gruen ueber die Aufnahme gelegt."""
    out = img.copy()
    farbe = np.zeros_like(img)
    farbe[:, :, 1] = 255
    m = mask > 0
    out[m] = (0.55 * out[m] + 0.45 * farbe[m]).astype(out.dtype)
    kontur, _ = cv2.findContours((mask > 0).astype(np.uint8),
                                 cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(out, kontur, -1, (0, 0, 255), 2)
    return out


def messen(zuordnung, bg, *, overlay_dir: Path | None = None) -> list[dict]:
    """Je Szene segmentieren und den Befund einsammeln. Schreibt nichts nach
    ZIEL — nur (optional) Overlays zur Sichtabnahme."""
    from docodetect.segmentation import SegmentationError, segment

    befunde = []
    for szene, pfad, kind in zuordnung:
        img = cv2.imread(str(pfad))
        if img is None:
            raise SystemExit(f"[adopt] {szene}: Bild nicht lesbar ({pfad})")
        eintrag = {"szene": szene, "quelle": pfad, "kind": kind,
                   "era": era_median(img, bg), "area_px": None,
                   "touches_border": None, "fehler": None}
        try:
            s = segment(img, bg)
            eintrag["area_px"] = int(round(s.area_px))
            eintrag["touches_border"] = bool(s.touches_border)
            if overlay_dir is not None:
                overlay_dir.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(overlay_dir / f"{szene}.png"),
                            _overlay(img, s.mask))
        except SegmentationError as e:
            eintrag["fehler"] = str(e)
        befunde.append(eintrag)
    return befunde


def pruefen(befunde: list[dict]) -> list[str]:
    """Harte Einwaende gegen eine Uebernahme. Leer = uebernehmbar."""
    probleme = []
    for b in befunde:
        if b["era"] > ERA_MEDIAN_MAX:
            probleme.append(
                f"{b['szene']}: Era-Abstand {b['era']:.1f} > {ERA_MEDIAN_MAX} — "
                f"Aufnahme und Hintergrund passen nicht zusammen. Hintergrund "
                f"neu aufnehmen (capture-background) ODER die Szene erneut "
                f"schiessen; NICHT uebernehmen.")
        if b["kind"] == "raises" and b["fehler"] is None:
            probleme.append(
                f"{b['szene']}: als ':raises' deklariert, aber die "
                f"Segmentierung lieferte eine Maske ({b['area_px']} px). "
                f"Ist die Box wirklich leer?")
        if b["kind"] in ("segment", "touches_border") and b["fehler"] is not None:
            probleme.append(
                f"{b['szene']}: Segmentierung brach ab ({b['fehler']}) — als "
                f"Golden unbrauchbar.")
        # Randberuehrung ist eine Zusage, keine Nebenbeobachtung: eine
        # ':border'-Szene, die den Rand NICHT beruehrt, wuerde als Golden
        # genau das Gegenteil festschreiben. Und eine gewoehnliche Szene,
        # die ihn beruehrt, ist schlicht falsch aufgenommen — die Pipeline
        # wuerde sie im Betrieb ablehnen.
        if b["kind"] == "touches_border" and b["touches_border"] is False:
            probleme.append(
                f"{b['szene']}: als ':border' deklariert, aber die "
                f"Segmentierung meldet KEINE Randberuehrung. Objekt weiter "
                f"an den Rand legen oder groesseres Objekt nehmen.")
        if b["kind"] == "segment" and b["touches_border"] is True:
            probleme.append(
                f"{b['szene']}: beruehrt den Bildrand. Als gewoehnliche Szene "
                f"unbrauchbar — die Pipeline lehnt solche Aufnahmen ab. "
                f"Objekt zentrieren, oder bewusst als ':border' uebernehmen.")
    return probleme


def schreiben(befunde: list[dict], bg_quelle: Path, ziel: Path = ZIEL) -> Path:
    """Szenen, Hintergrund und Manifest ablegen. Ersetzt einen vorhandenen
    Satz NICHT teilweise: bestehende Eintraege bleiben, gleichnamige werden
    ueberschrieben."""
    szenen_dir = ziel / "scenes"
    szenen_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(bg_quelle, ziel / "background.png")

    manifest_pfad = ziel / "goldens.json"
    manifest = {"version": 1, "scenes": {}}
    if manifest_pfad.is_file():
        try:
            manifest = json.loads(manifest_pfad.read_text(encoding="utf-8"))
            manifest.setdefault("scenes", {})
        except ValueError:
            pass

    for b in befunde:
        shutil.copyfile(b["quelle"], szenen_dir / f"{b['szene']}.png")
        eintrag = {"kind": b["kind"], "quelle": b["quelle"].name}
        if b["kind"] in ("segment", "touches_border"):
            eintrag["area_px"] = b["area_px"]
        manifest["scenes"][b["szene"]] = eintrag

    manifest["uebernommen"] = date.today().isoformat()
    manifest["background"] = "background.png"
    manifest_pfad.write_text(
        json.dumps(manifest, indent=1, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")
    return manifest_pfad


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="adopt_goldens",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("zuordnung", nargs="+",
                    help="szene=capture-id[:raises], mehrfach")
    ap.add_argument("--background", default=None,
                    help="Hintergrund (Default calibration/background.png)")
    ap.add_argument("--dry-run", action="store_true",
                    help="nur messen und berichten, nichts schreiben")
    ap.add_argument("--overlay-dir", default=None,
                    help="Kontroll-Overlays fuer die Sichtabnahme hierhin")
    args = ap.parse_args(argv)

    bg_pfad = Path(args.background) if args.background else \
        PROJEKT / "calibration" / "background.png"
    if not bg_pfad.is_file():
        raise SystemExit(f"[adopt] Hintergrund fehlt: {bg_pfad}")
    bg = cv2.imread(str(bg_pfad))
    if bg is None:
        raise SystemExit(f"[adopt] Hintergrund nicht lesbar: {bg_pfad}")

    zuordnung = parse_zuordnung(args.zuordnung)
    overlay = Path(args.overlay_dir) if args.overlay_dir else None
    befunde = messen(zuordnung, bg, overlay_dir=overlay)

    print(f"{'Szene':32}{'Art':10}{'Era':>6}  {'Flaeche':>9}  Befund")
    print("-" * 78)
    for b in befunde:
        flaeche = "-" if b["area_px"] is None else f"{b['area_px']:,}"
        befund = b["fehler"] or "ok"
        print(f"{b['szene']:32}{b['kind']:10}{b['era']:6.1f}  {flaeche:>9}  "
              f"{befund[:28]}")

    probleme = pruefen(befunde)
    if probleme:
        print("\n[adopt] NICHT uebernommen:")
        for p in probleme:
            print(f"  - {p}")
        return 1

    if overlay:
        print(f"\n[adopt] Overlays: {overlay} — jede Maske ansehen, BEVOR "
              f"ohne --dry-run gelaufen wird.")
    if args.dry_run:
        print("\n[adopt] --dry-run: nichts geschrieben.")
        return 0

    ziel = schreiben(befunde, bg_pfad)
    print(f"\n[adopt] {len(befunde)} Szene(n) uebernommen -> {ziel}")
    print("[adopt] Jetzt: python -m pytest tests/test_real_captures.py -q")
    return 0


if __name__ == "__main__":
    sys.exit(main())
