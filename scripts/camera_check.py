"""Phase-0-Hardware-Smoke-Test: Kamera-Backend, 4K-MJPG, Fokus-Lock.

Klärt die größten UI-Risiken (Backend-Wahl, MJPG-4K, Fokus-Lock), BEVOR
Qt-Code entsteht. Kein Qt, nur OpenCV. Alle Soll-Werte kommen aus
config/config.yaml (single source of truth) – die Konsole zeigt pro
Prüfung Soll/Ist und OK/FAIL.

    python scripts/camera_check.py [--config PFAD]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.camera import capture_backend, focus_lock_supported  # noqa: E402
from docodetect.config import load_config, resolve  # noqa: E402


def check(label: str, ok: bool, detail: str) -> bool:
    print(f"  [{'OK' if ok else 'FAIL'}] {label}: {detail}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    cam = load_config(ap.parse_args().config)["camera"]

    backend = capture_backend(cam)
    print(f"[camera_check] Backend {backend} auf {sys.platform}, Index {cam['index']}")
    cap = cv2.VideoCapture(cam["index"], backend)
    if not cap.isOpened():
        print("  [FAIL] Kamera lässt sich nicht öffnen – USB/Index prüfen.")
        return 1

    ok = True
    fourcc_req = cam.get("fourcc", "MJPG")
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc_req))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, cam["width"])
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cam["height"])

    w, h = cap.get(cv2.CAP_PROP_FRAME_WIDTH), cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    ok &= check("Auflösung", (w, h) == (cam["width"], cam["height"]),
                f"Soll {cam['width']}x{cam['height']}, Ist {int(w)}x{int(h)}"
                + ("" if (w, h) == (3840, 2160) else "  (4K=3840x2160 nicht aktiv)"))

    raw = int(cap.get(cv2.CAP_PROP_FOURCC))
    fourcc_is = "".join(chr((raw >> 8 * i) & 0xFF) for i in range(4))
    if raw <= 0 and sys.platform == "darwin":
        # AVFoundation kann FOURCC nicht zurücklesen (liefert -1) – wie beim
        # Fokus-Lock: Warnung auf dem Mac, harte Prüfung nur unter Windows.
        print(f"  [WARN] FOURCC nicht zurücklesbar (AVFoundation liefert {raw}) "
              f"– verlässlich prüfbar nur unter Windows/DSHOW.")
    else:
        ok &= check("FOURCC", fourcc_is == fourcc_req,
                    f"Soll {fourcc_req}, Ist {fourcc_is}")

    # Fokus-Lock: setzen und ZURÜCKLESEN. Auf macOS/AVFoundation erwartet
    # fehlschlagend (Plan §9.2) – dort Warnung statt FAIL, Messbetrieb Windows.
    cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
    focus_req = float(cam.get("focus_value", 30))
    cap.set(cv2.CAP_PROP_FOCUS, focus_req)
    af, focus = cap.get(cv2.CAP_PROP_AUTOFOCUS), cap.get(cv2.CAP_PROP_FOCUS)
    locked = af == 0 and abs(focus - focus_req) <= 1.0
    if focus_lock_supported():
        ok &= check("Fokus-Lock", locked,
                    f"AUTOFOCUS Ist {af} (Soll 0), FOCUS Ist {focus} (Soll {focus_req})")
    else:
        print(f"  [WARN] Fokus-Lock auf {sys.platform} nicht verlässlich "
              f"(AUTOFOCUS={af}, FOCUS={focus}) – Messbetrieb nur unter Windows.")

    for _ in range(int(cam.get("warmup_frames", 10))):  # Belichtung stabilisieren
        cap.read()

    ret, frame = cap.read()
    ok &= check("Frame", ret and frame is not None,
                f"{frame.shape[1]}x{frame.shape[0]}" if ret else "kein Bild")
    if ret:
        out = resolve("data/captures") / "camera_check.jpg"
        out.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(out), frame)
        print(f"  [OK] Testbild gespeichert: {out}")

    n, t0 = 0, time.perf_counter()
    while time.perf_counter() - t0 < 3.0:
        if cap.grab():
            n += 1
    fps = n / (time.perf_counter() - t0)
    ok &= check("Grab-FPS (3 s)", fps >= 5.0, f"{fps:.1f} fps")

    cap.release()
    print(f"[camera_check] {'ALLE PRÜFUNGEN OK' if ok else 'PRÜFUNGEN FEHLGESCHLAGEN'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
