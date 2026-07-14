"""Gemeinsame Streamlit-Helfer für app.py und die Seiten unter pages/.

Kamera-Verwaltung (EIN geteiltes BoxCamera-Objekt pro Session, nur offen
während Vorschau/Aufnahme) und Bild-Overlays. Keine Bildverarbeitung –
die läuft ausschließlich in docodetect/.
"""

from __future__ import annotations

import cv2
import numpy as np
import streamlit as st

from docodetect.camera import BoxCamera

CAMERA_HINT = "Prüfe `camera.index` (und USB-Verbindung) in config/config.yaml."


# ---------- Kamera: ein gemeinsames, sauber verwaltetes BoxCamera-Objekt ----------
#
# Es existiert höchstens EIN offenes BoxCamera-Objekt pro Session
# (st.session_state.cam). Es wird nur geöffnet, wenn die Live-Vorschau läuft
# oder gerade eine Aufnahme passiert, und danach wieder freigegeben, damit
# das USB-Gerät nicht dauerhaft blockiert wird (z.B. für die CLI parallel).

def get_camera(cfg: dict) -> BoxCamera:
    cam = st.session_state.get("cam")
    if cam is None:
        cam = BoxCamera(cfg)
        cam.open()
        st.session_state.cam = cam
    return cam


def release_camera() -> None:
    cam = st.session_state.get("cam")
    if cam is not None:
        cam.close()
    st.session_state.cam = None


def capture_frame(cfg: dict) -> np.ndarray:
    """One fresh 4K frame via the shared BoxCamera. Opens the camera on
    demand (full warm-up) and closes it again unless the live preview is
    active, so a single action never leaves the device locked open."""
    st.session_state.capturing = True
    try:
        cam = get_camera(cfg)
        return cam.capture()
    finally:
        st.session_state.capturing = False
        if not st.session_state.get("preview_on"):
            release_camera()


def resize_width(image: np.ndarray, width: int) -> np.ndarray:
    h, w = image.shape[:2]
    if w <= width:
        return image
    scale = width / w
    return cv2.resize(image, (width, int(round(h * scale))))


def make_overlay(image: np.ndarray, seg) -> np.ndarray:
    color_mask = np.zeros_like(image)
    color_mask[seg.mask > 0] = (0, 255, 0)
    blended = cv2.addWeighted(image, 0.8, color_mask, 0.2, 0)
    cv2.drawContours(blended, [seg.contour], -1, (0, 0, 255), 3)
    return blended


def draw_report_overlay(image: np.ndarray, report) -> np.ndarray:
    """Kontur-Overlay aus dem im MatchReport gespeicherten Polygon –
    funktioniert auch für aus JSON geladene Reports (keine
    SegmentationResult nötig). Rot = Randberührung, grün = ok."""
    out = image.copy()
    if report.contour:
        pts = np.asarray(report.contour, dtype=np.int32).reshape(-1, 1, 2)
        color = (0, 0, 255) if report.touches_border else (0, 255, 0)
        cv2.polylines(out, [pts], isClosed=True, color=color, thickness=3)
    return out
