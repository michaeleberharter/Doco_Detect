"""Generate the printable ArUco calibration marker (DICT_4X4_50, id 0).

Prints a PNG at 300 DPI so that the marker is EXACTLY 50.0 mm when printed
at 100 % scale ("Tatsächliche Größe" im Druckdialog, NICHT "an Seite
anpassen"). Verify with a caliper after printing – the printed size is the
single most important number in the whole system.

Usage: python scripts/generate_marker.py
"""

import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from docodetect.config import load_config  # noqa: E402

DPI = 300
MM_PER_INCH = 25.4

cfg = load_config()
size_mm = cfg["calibration"]["marker_size_mm"]
marker_id = cfg["calibration"]["marker_id"]
dict_name = cfg["calibration"]["aruco_dict"]

px = int(round(size_mm / MM_PER_INCH * DPI))
aruco_dict = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, dict_name))
marker = cv2.aruco.generateImageMarker(aruco_dict, marker_id, px)

# white quiet zone (required for reliable detection)
border = px // 5
canvas = np.full((px + 2 * border, px + 2 * border), 255, dtype=np.uint8)
canvas[border:border + px, border:border + px] = marker

out = Path(__file__).parent / f"aruco_{dict_name}_id{marker_id}_{size_mm:.0f}mm_{DPI}dpi.png"
cv2.imwrite(str(out), canvas)
print(f"Marker written to {out}")
print(f"Print at 100% scale ({DPI} DPI) -> marker edge must measure {size_mm} mm. "
      "Check with a caliper!")
