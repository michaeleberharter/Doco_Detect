"""Streamlit-Test-UI für die Stage-1-Pipeline – treibt die echte BoxCamera.

Ruft ausschließlich docodetect/{pipeline,calibration,camera,database}.py auf,
keine eigene Bildverarbeitung. Kein Bild-Upload, keine synthetischen
Testbilder: jeder Schritt schießt ein frisches 4K-Foto über die reale Kamera
(Index/Auflösung aus config/config.yaml: camera.*).

Start:  streamlit run app.py
"""

from __future__ import annotations

from dataclasses import asdict

import cv2
import numpy as np
import pandas as pd
import streamlit as st
import yaml

from docodetect import config as cfg_module
from docodetect.calibration import run_calibration, save_background
from docodetect.camera import BoxCamera, CameraError
from docodetect.config import load_config, resolve
from docodetect.database import Database
from docodetect.pipeline import Pipeline

st.set_page_config(page_title="Doco_Detect – Live-Test-UI", layout="wide")

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


def render_features(feats) -> None:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Ø (mm)", f"{feats.circle_diameter_mm:.1f}")
    c2.metric("Fläche (cm²)", f"{feats.area_mm2 / 100:.1f}")
    c3.metric("Rundheit", f"{feats.circularity:.3f}")
    c4.metric("Seitenverh.", f"{feats.aspect_ratio:.3f}")
    with st.expander("Alle Merkmale (JSON)"):
        st.json(asdict(feats))


def ready_for_pipeline(cfg: dict) -> bool:
    return (resolve(cfg["calibration"]["file"]).exists()
            and resolve(cfg["calibration"]["background_file"]).exists())


# ---------- Config laden ----------

if "cfg_path" not in st.session_state:
    st.session_state.cfg_path = str(cfg_module.DEFAULT_CONFIG_PATH)

st.sidebar.title("Doco_Detect")
st.sidebar.text_input("Config-Pfad", key="cfg_path")

if "cfg" not in st.session_state or st.sidebar.button("🔄 Config neu laden"):
    try:
        st.session_state.cfg = load_config(st.session_state.cfg_path)
    except Exception as e:
        st.sidebar.error(f"Config-Fehler: {e}")
        st.stop()

cfg = st.session_state.cfg

st.sidebar.subheader("Status")
for label, path in {
    "Datenbank": resolve(cfg["paths"]["db_file"]),
    "Hintergrund": resolve(cfg["calibration"]["background_file"]),
    "Kalibrierung": resolve(cfg["calibration"]["file"]),
}.items():
    st.sidebar.markdown(f"{'✅' if path.exists() else '❌'} {label} — `{path.name}`")

st.sidebar.subheader("Kamera")
st.sidebar.caption(f"Index {cfg['camera']['index']}  ·  "
                   f"{cfg['camera']['width']}×{cfg['camera']['height']}")
if st.sidebar.button("🔌 Kamera freigeben"):
    release_camera()
    st.session_state.preview_on = False
    st.sidebar.success("Kamera geschlossen.")


# ---------- Live-Vorschau (verkleinert, ~3 fps, pausiert während Capture) ----------

st.subheader("📹 Live-Vorschau")
st.toggle("Vorschau aktiv – Objekt in der Box positionieren", key="preview_on", value=False)


@st.fragment(run_every=0.3)
def live_preview():
    if not st.session_state.get("preview_on"):
        st.caption("Vorschau aus.")
        return
    if st.session_state.get("capturing"):
        st.caption("⏸️ Vorschau pausiert – Aufnahme läuft…")
        return
    try:
        cam = get_camera(cfg)
        frame = cam.capture()
    except CameraError as e:
        st.error(f"Kamera-Fehler: {e}  \n{CAMERA_HINT}")
        st.session_state.preview_on = False
        release_camera()
        return
    st.image(resize_width(frame, 960), channels="BGR")


live_preview()

st.divider()

tab_db, tab_bg, tab_cal, tab_identify, tab_enroll, tab_config = st.tabs([
    "🗄️ Datenbank", "1️⃣ Hintergrund", "2️⃣ Kalibrieren",
    "3️⃣ Identifizieren", "4️⃣ Einlernen", "⚙️ Config",
])


# ---------- Tab: Datenbank ----------

with tab_db:
    st.header("Artikel-Datenbank")

    if st.button("Schema initialisieren"):
        db = Database(cfg)
        db.init_schema()
        db.close()
        st.success("Schema angelegt/geprüft.")

    csv_file = st.file_uploader("Artikel-Stammdaten-CSV importieren", type=["csv"], key="csv_upload")
    if csv_file and st.button("CSV importieren"):
        import tempfile
        from pathlib import Path
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
            tmp.write(csv_file.getvalue())
            tmp_path = tmp.name
        db = Database(cfg)
        db.init_schema()
        try:
            n = db.import_articles_csv(tmp_path)
            st.success(f"{n} Artikel importiert/aktualisiert.")
        except Exception as e:
            st.error(str(e))
        finally:
            db.close()
            Path(tmp_path).unlink(missing_ok=True)

    st.subheader("Aktuelle Artikel")
    try:
        db = Database(cfg)
        articles = db.all_articles()
        with_refs = set(db.articles_with_references())
        db.close()
        if articles:
            rows = [{**asdict(a), "referenzen": a.article_number in with_refs} for a in articles]
            st.dataframe(pd.DataFrame(rows), width="stretch")
        else:
            st.info("Noch keine Artikel importiert.")
    except Exception as e:
        st.warning(f"Datenbank nicht lesbar: {e}")


# ---------- Tab: Hintergrund ----------

with tab_bg:
    st.header("1. Hintergrund aufnehmen")
    st.write("Box **leer** stellen, dann aufnehmen. Das Foto dient als Referenz "
             "für die Hintergrund-Segmentierung.")
    if st.button("📸 Hintergrund aufnehmen", type="primary"):
        try:
            frame = capture_frame(cfg)
        except CameraError as e:
            st.error(f"Kamera-Fehler: {e}  \n{CAMERA_HINT}")
        else:
            save_background(frame, cfg)
            st.success(f"Hintergrund gespeichert ({frame.shape[1]}×{frame.shape[0]} px).")
            st.image(resize_width(frame, 960), channels="BGR", caption="Aufgenommener Hintergrund")


# ---------- Tab: Kalibrieren ----------

with tab_cal:
    st.header("2. Kalibrieren")
    bg_path = resolve(cfg["calibration"]["background_file"])
    if not bg_path.exists():
        st.warning("Erst Hintergrund aufnehmen (Schritt 1).")
    else:
        st.write(f"ArUco-Marker **{cfg['calibration']['aruco_dict']}**, ID "
                f"**{cfg['calibration']['marker_id']}**, "
                f"**{cfg['calibration']['marker_size_mm']} mm** Kantenlänge flach in "
                "die Box legen, dann kalibrieren.")
        if st.button("📐 Kalibrieren", type="primary"):
            try:
                frame = capture_frame(cfg)
            except CameraError as e:
                st.error(f"Kamera-Fehler: {e}  \n{CAMERA_HINT}")
            else:
                try:
                    cal = run_calibration(frame, cfg)
                except RuntimeError as e:
                    st.error(f"Kalibrierung fehlgeschlagen: {e}")
                    st.image(resize_width(frame, 960), channels="BGR", caption="Aufgenommenes Bild")
                else:
                    fov_w = cal.mm_per_px * cal.image_width
                    fov_h = cal.mm_per_px * cal.image_height
                    st.success(f"mm_per_px = {cal.mm_per_px:.5f}  |  "
                              f"sichtbarer Bodenbereich ≈ {fov_w:.0f} × {fov_h:.0f} mm")
                    if min(fov_w, fov_h) < 220:
                        st.info("Hinweis: Gegenstände über ~"
                               f"{min(fov_w, fov_h) - 20:.0f} mm berühren den Bildrand "
                               "und werden abgelehnt (siehe README, FOV-Limitierung).")
                    st.image(resize_width(frame, 960), channels="BGR", caption="Kalibrierbild")


# ---------- Tab: Identifizieren ----------

with tab_identify:
    st.header("3. Identifizieren")
    if not ready_for_pipeline(cfg):
        st.warning("Erst Hintergrund + Kalibrierung anlegen (Schritte 1-2).")
    else:
        st.write("Objekt in die Box legen, dann auslösen.")
        if st.button("🔍 Identifizieren", type="primary"):
            try:
                frame = capture_frame(cfg)
                pipe = Pipeline(cfg)
                try:
                    outcome = pipe.identify(frame)
                finally:
                    pipe.close()
            except CameraError as e:
                st.error(f"Kamera-Fehler: {e}  \n{CAMERA_HINT}")
            except Exception as e:
                st.error(f"Fehler: {e}")
            else:
                r = outcome.result
                if r.decision == "auto":
                    st.success(f"AUTO — {r.message}")
                elif r.decision == "confirm":
                    st.warning(f"CONFIRM — {r.message}")
                else:
                    st.error(f"NO MATCH — {r.message}")

                col1, col2 = st.columns(2)
                col1.image(resize_width(frame, 960), channels="BGR", caption="Original")
                if outcome.segmentation is not None:
                    col2.image(resize_width(make_overlay(frame, outcome.segmentation), 960),
                              channels="BGR", caption="Segmentierung (rot = Kontur, grün = Maske)")
                else:
                    col2.info("Keine Segmentierung möglich (siehe Meldung oben).")

                if outcome.features is not None:
                    render_features(outcome.features)

                if r.candidates:
                    st.subheader("Top-3-Kandidaten")
                    rows = [{
                        "Rang": i + 1,
                        "Artikel": c.article.article_number,
                        "Name": c.article.name,
                        "Score": c.score,
                        "Δ Geometrie (mm)": c.geometry_error_mm,
                        "Ø korrigiert (mm)": c.corrected_diameter_mm,
                        "Farbdistanz": c.color_dist,
                        "Formdistanz": c.shape_dist,
                        "Referenzen?": c.has_references,
                    } for i, c in enumerate(r.candidates[:3])]
                    st.dataframe(pd.DataFrame(rows), width="stretch")


# ---------- Tab: Einlernen ----------

with tab_enroll:
    st.header("4. Einlernen (optional)")
    if not ready_for_pipeline(cfg):
        st.warning("Erst Hintergrund + Kalibrierung anlegen (Schritte 1-2).")
    else:
        try:
            db = Database(cfg)
            articles = db.all_articles()
            db.close()
        except Exception as e:
            articles = None
            st.error(f"Datenbank nicht lesbar: {e}  \n"
                    "Erst im Tab 'Datenbank' Schema initialisieren/Artikel importieren.")

        if articles is not None and not articles:
            st.warning("Keine Artikel in der Datenbank – erst im Tab 'Datenbank' importieren.")
        elif articles:
            article_number = st.selectbox(
                "Artikelnummer", [a.article_number for a in articles], key="enroll_article"
            )
            st.write("Objekt in die Box legen, dann einlernen.")
            if st.button("➕ Einlernen", type="primary"):
                try:
                    frame = capture_frame(cfg)
                    pipe = Pipeline(cfg)
                    try:
                        feats = pipe.enroll(frame, article_number)
                    finally:
                        pipe.close()
                except CameraError as e:
                    st.error(f"Kamera-Fehler: {e}  \n{CAMERA_HINT}")
                except Exception as e:
                    st.error(f"Fehler: {e}")
                else:
                    st.success(f"Referenz für {article_number} gespeichert.")
                    st.image(resize_width(frame, 960), channels="BGR", caption="Eingelerntes Foto")
                    render_features(feats)


# ---------- Tab: Config ----------

with tab_config:
    st.header("Parameter (nur diese Session, bis gespeichert)")

    st.subheader("Segmentierung")
    seg = cfg["segmentation"]
    seg["diff_threshold"] = st.slider("diff_threshold", 0, 100, int(seg["diff_threshold"]))
    seg["morph_kernel"] = st.slider("morph_kernel (ungerade)", 1, 51, int(seg["morph_kernel"]), step=2)
    seg["min_area_px"] = st.number_input("min_area_px", value=int(seg["min_area_px"]), step=1000)
    seg["border_margin_px"] = st.number_input("border_margin_px", value=int(seg["border_margin_px"]))

    st.subheader("Matching")
    m = cfg["matching"]
    m["diameter_tolerance_mm"] = st.slider("diameter_tolerance_mm", 0.0, 30.0, float(m["diameter_tolerance_mm"]))
    m["area_tolerance_pct"] = st.slider("area_tolerance_pct", 0.0, 50.0, float(m["area_tolerance_pct"]))
    m["auto_accept_score"] = st.slider("auto_accept_score", 0.0, 1.0, float(m["auto_accept_score"]))
    m["auto_accept_margin"] = st.slider("auto_accept_margin", 0.0, 1.0, float(m["auto_accept_margin"]))

    st.caption("Änderungen wirken sofort auf Identify/Enroll in dieser Session.")
    if st.button("💾 Dauerhaft in config.yaml speichern"):
        with open(st.session_state.cfg_path, "w", encoding="utf-8") as fh:
            yaml.safe_dump(cfg, fh, allow_unicode=True, sort_keys=False)
        st.success(f"Gespeichert nach {st.session_state.cfg_path}")
