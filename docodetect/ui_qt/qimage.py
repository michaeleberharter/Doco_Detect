"""numpy(BGR) -> QImage – die EINE Stelle für diese Konvertierung.

Das .copy() ist Pflicht: QImage referenziert sonst den numpy-Puffer, der im
Worker sofort überschrieben wird (Bildmüll/Absturz). bytesPerLine (3*w)
explizit setzen, sonst stolpert Qt über nicht-zusammenhängende Strides.
"""

from __future__ import annotations

import cv2
import numpy as np
from PySide6.QtGui import QImage


def bgr_to_qimage(frame_bgr: np.ndarray) -> QImage:
    rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    h, w, _ = rgb.shape
    return QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()


def downscale_width(frame: np.ndarray, max_width: int) -> np.ndarray:
    """Auf Vorschaubreite verkleinern (Seitenverhältnis bleibt)."""
    h, w = frame.shape[:2]
    if w <= max_width:
        return frame
    scale = max_width / w
    return cv2.resize(frame, (max_width, int(round(h * scale))),
                      interpolation=cv2.INTER_AREA)
