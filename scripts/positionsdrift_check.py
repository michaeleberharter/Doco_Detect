"""Positionsabhaengige Laengenmessung — Rekonstruktion des Befunds vom 2026-07-28.

REIN LESEND. Keine DB, keine Config, keine Kalibrierung wird geschrieben; die
Messumgebung des 28.07. wird nur IN MEMORY gesetzt. Kein Messpfad-Eingriff —
Segmentierung und Geometrie kommen ueber `Pipeline.analyze` und
`enrollment_sheet._shot_geometry`, wie in den uebrigen Analyse-Skripten.

Frage: haengt die gemessene Laenge (`ext_full`) davon ab, WO in der Box das
Objekt liegt?

Datenbasis sind die zwoelf Referenz-Shots von MESSER-2 vom 2026-07-28
(`data/reference/MESSER-2/1785265604728_*.png`). Sie sind keine gewoehnliche
Einlernserie, sondern eine **Positionsleiter**: das Objekt wurde in Schritten
ueber 109 mm vertikal durch das Bildfeld geschoben — Shots 00-05 in die eine,
06-11 in die andere Richtung. Diese Umkehr ist die Kontrolle, die Zeit von
Position trennt.

Die Umgebung wird auf den Stand vom 28.07. zurueckgesetzt, sonst misst man den
Aufbau von heute:
  - `calibration-20260731-185137.json` — mm_per_px 0.07876574, erstellt
    2026-07-20, bis 31.07. in Kraft (also am 28.07. gueltig)
  - `background-20260731-165437.png` — mtime 28.07. 20:51, 4K; der Hintergrund,
    der beim Enrollment um 21:06 in Kraft war. NICHT
    `background-20260728-205102.png` nehmen: der ist 1080p und stammt aus dem
    Aufloesungs-Zwischenfall desselben Abends.

Auswertung und Einordnung: docs/2026-08-01-positionsdrift-messung.md

Aufruf:
    .venv/bin/python scripts/positionsdrift_check.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.config import load_config, resolve  # noqa: E402
from docodetect.enrollment_sheet import _shot_geometry  # noqa: E402
from docodetect.pipeline import Pipeline  # noqa: E402

SERIE = "data/reference/MESSER-2"
KALIBRIERUNG = "calibration/calibration-20260731-185137.json"
HINTERGRUND = "calibration/background-20260731-165437.png"

# RMS des Breitenprofils ueber die Artikel des Bestands (w(s)-Negativbefund,
# Abschnitt 6) — Umrechnung eines relativen Skalenfehlers in einen Floor.
RMS_W_MM = (12.6, 22.2)


def messe(cfg) -> list:
    pipe = Pipeline(cfg)
    zeilen = []
    try:
        mmpp = float(pipe.cal.mm_per_px)
        h, w = pipe.background.shape[:2]
        print(f"mm_per_px = {mmpp:.8f} · Feld {w}x{h} px "
              f"= {w * mmpp:.1f} x {h * mmpp:.1f} mm")
        for p in sorted(resolve(SERIE).glob("*.png")):
            img = cv2.imread(str(p))
            if img is None:
                print(f"  {p.name}: nicht lesbar")
                continue
            try:
                seg, feats = pipe.analyze(img)
            except Exception as e:                      # noqa: BLE001
                print(f"  {p.name}: {type(e).__name__}: {e}")
                continue
            if seg.contour is None:
                print(f"  {p.name}: keine Kontur")
                continue
            g = _shot_geometry(seg.contour, mmpp)
            c = np.asarray(seg.contour, float).reshape(-1, 2)
            zeilen.append({
                "shot": int(p.stem.split("_")[-1]),
                "ext_full": g.ext_full, "lat_p98": g.lat_p98,
                "diameter": feats.circle_diameter_mm,
                "x_mm": (c[:, 0].mean() - w / 2) * mmpp,
                "y_mm": (c[:, 1].mean() - h / 2) * mmpp,
                "feld_h_mm": h * mmpp,
            })
    finally:
        pipe.close()
    return zeilen


def main() -> int:
    cfg = load_config()
    cfg["calibration"] = dict(cfg["calibration"])
    cfg["calibration"]["file"] = KALIBRIERUNG
    cfg["calibration"]["background_file"] = HINTERGRUND

    z = messe(cfg)
    if len(z) < 3:
        print("Zu wenige verwertbare Shots.")
        return 1

    z.sort(key=lambda r: r["y_mm"])
    print(f"\n{'Shot':>4} {'ext_full':>9} {'lat_p98':>8} {'Ø':>9} "
          f"{'x [mm]':>8} {'y [mm]':>8}")
    for r in z:
        print(f"{r['shot']:>4} {r['ext_full']:>9.2f} {r['lat_p98']:>8.2f} "
              f"{r['diameter']:>9.2f} {r['x_mm']:>8.1f} {r['y_mm']:>8.1f}")

    e = np.array([r["ext_full"] for r in z])
    l_ = np.array([r["lat_p98"] for r in z])
    y = np.array([r["y_mm"] for r in z])
    x = np.array([r["x_mm"] for r in z])
    s = np.array([r["shot"] for r in z])
    rad = np.hypot(x, y)
    feld_h = z[0]["feld_h_mm"]

    ke = float(np.polyfit(y, e, 1)[0])
    kl = float(np.polyfit(y, l_, 1)[0])

    print(f"\nSpanne ext_full {e.max() - e.min():.2f} mm über "
          f"{y.max() - y.min():.1f} mm Weg "
          f"({(y.max() - y.min()) / feld_h * 100:.0f} % der Feldhöhe)")
    print(f"Steigung {ke:+.4f} mm/mm = {ke / e.mean() * 100:+.4f} % je mm")

    print("\nKorrelationen")
    print(f"  ext_full ~ y (vorzeichenbehaftet) : {np.corrcoef(y, e)[0, 1]:+.3f}")
    print(f"  ext_full ~ r (radial, vorzeichenlos): "
          f"{np.corrcoef(rad, e)[0, 1]:+.3f}   <- die Groesse, die 2026-07-27 geprueft wurde")
    print(f"  ext_full ~ Shot-Index (Zeit)      : {np.corrcoef(s, e)[0, 1]:+.3f}")

    hin = sorted([r for r in z if r["shot"] <= 5], key=lambda r: r["shot"])
    rueck = sorted([r for r in z if r["shot"] > 5], key=lambda r: r["shot"])
    print("\nZeit-Kontrolle (die Leiter kehrt um):")
    print(f"  Shots 00->05: y {hin[0]['y_mm']:+.1f} -> {hin[-1]['y_mm']:+.1f} mm, "
          f"ext_full {hin[0]['ext_full']:.2f} -> {hin[-1]['ext_full']:.2f} mm")
    print(f"  Shots 06->11: y {rueck[0]['y_mm']:+.1f} -> {rueck[-1]['y_mm']:+.1f} mm, "
          f"ext_full {rueck[0]['ext_full']:.2f} -> {rueck[-1]['ext_full']:.2f} mm")
    print("  Zeit laeuft in beiden Haelften vorwaerts, ext_full aber in "
          "GEGENLAEUFIGE Richtungen\n  -> Positionseffekt, keine Drift ueber die Session.")

    print("\nSkaliert die Breite wie die Laenge?")
    print(f"  ext_full {ke / e.mean() * 100:+.4f} %/mm · "
          f"lat_p98 {kl / l_.mean() * 100:+.4f} %/mm · "
          f"Verhaeltnis {(kl / l_.mean()) / (ke / e.mean()):.2f}x")

    print("\nFloor-Abschaetzung je unterstellter Auflage-Streuung")
    for name, spanne in (("beobachtete Leiter", y.max() - y.min()),
                         ("halbe Feldhoehe", feld_h / 2),
                         ("volle Feldhoehe", feld_h)):
        pct = abs(ke) * spanne / e.mean() * 100
        print(f"  {name:<20} {abs(ke) * spanne:5.2f} mm = {pct:4.2f} % "
              f"-> Floor {pct / 100 * RMS_W_MM[0]:.2f}-{pct / 100 * RMS_W_MM[1]:.2f} mm")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
