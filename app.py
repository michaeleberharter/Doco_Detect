"""Streamlit-Test-UI für die Stage-1-Pipeline – treibt die echte BoxCamera.

Ruft ausschließlich docodetect/{pipeline,calibration,camera,database}.py auf,
keine eigene Bildverarbeitung. Kein Bild-Upload, keine synthetischen
Testbilder: jeder Schritt schießt ein frisches 4K-Foto über die reale Kamera
(Index/Auflösung aus config/config.yaml: camera.*).

Start:  streamlit run app.py
"""

from __future__ import annotations

from dataclasses import asdict

import pandas as pd
import streamlit as st
import yaml

from docodetect import config as cfg_module
from docodetect.calibration import run_calibration, save_background
from docodetect.camera import CameraError
from docodetect.config import load_config, resolve
from docodetect.database import Database
from docodetect.pipeline import Pipeline
from docodetect.segmentation import SegmentationError
from ui_common import (CAMERA_HINT, capture_frame, get_camera, make_overlay,
                       release_camera, resize_width)

st.set_page_config(page_title="Doco_Detect – Live-Test-UI", layout="wide")


def render_features(feats) -> None:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Ø (mm)", f"{feats.circle_diameter_mm:.1f}")
    c2.metric("Fläche (cm²)", f"{feats.area_mm2 / 100:.1f}")
    c3.metric("Rundheit", f"{feats.circularity:.3f}")
    c4.metric("Seitenverh.", f"{feats.aspect_ratio:.3f}")
    with st.expander("Alle Merkmale (JSON)"):
        st.json(asdict(feats))


def _render_identify_result(res: dict, cfg: dict) -> None:
    """Entscheidungsanzeige — nutzt dieselben Helfer wie die Qt-App
    (inhaltlich identisch, Streamlit-Bordmittel); einzige Render-Stelle
    des Identify-Ergebnisses. Speichert Verdicts über die pipeline-
    Fassaden confirm_result/reject_result (UIs importieren reporting.py
    nie direkt)."""
    from docodetect.pipeline import (channel_percentages, confirm_result,
                                     format_delta, format_diameter,
                                     format_rank_line, headline,
                                     list_articles, reject_result)

    report = res["report"]                       # MatchReport
    best = report.candidates[0] if report.candidates else None
    text, cls = headline(report.decision, best.name if best else None)
    {"accept": st.success, "confirm": st.warning, "reject": st.error}[cls](text)

    if report.decision == "reject":
        m = report.measured or {}
        if m:
            st.caption("Gemessen: Ø {:.1f} mm (Bodenebene) · Rundheit {:.2f} · "
                       "Fläche {:.0f} cm²".format(
                           m.get("circle_diameter_mm", 0),
                           m.get("circularity", 0),
                           m.get("area_mm2", 0) / 100).replace(".", ","))
        st.caption(report.message)
        return

    def _candidate_block(c):
        st.markdown(f"**{c.name}**  \n{c.article_number}")
        st.caption(f"{format_diameter(c)} · {format_delta(c, cfg)}")
        st.progress(min(1.0, c.posterior),
                    text=f"Gesamt {c.posterior * 100:.0f} %")
        cols = st.columns(3)
        titles = {"geometry": "Geometrie", "color": "Farbe", "shape": "Form"}
        for col, (ch, pct) in zip(cols, channel_percentages(c).items()):
            with col:
                if pct is None:
                    st.caption(f"{titles[ch]}: keine Daten")
                else:
                    st.progress(min(1.0, pct), text=titles[ch])

    if report.decision == "accept":
        _candidate_block(best)
        top_k = int(report.thresholds.get("top_k", 3))
        for rank, c in enumerate(report.candidates[1:top_k], start=2):
            st.caption(format_rank_line(c, rank))
        return

    # ambiguous: Kandidaten auswählbar + „Keiner davon" — nach dem ersten
    # gespeicherten Verdict verschwinden die Buttons (verdict_saved-Flag im
    # selben identify_result-Dict in session_state), damit ein Rerun (z.B.
    # durch einen anderen Widget-Klick) nicht versehentlich ein zweites,
    # widersprüchliches Verdict speichert.
    saved = res.get("verdict_saved")
    top_k = int(report.thresholds.get("top_k", 3))
    for c in report.candidates[:top_k]:
        _candidate_block(c)
        if not saved and st.button(f"✓ {c.article_number} bestätigen",
                                   key=f"conf_{c.article_number}"):
            try:
                confirm_result(report, c.article_number)
            except ValueError as e:
                st.error(f"Bestätigung nicht gespeichert: {e}")
            else:
                res["verdict_saved"] = c.article_number
                st.rerun()
    if saved:
        label = "Unbekannt" if saved == "__unknown__" else saved
        st.success(f"Bewertung gespeichert: {label} — im Testprotokoll vermerkt.")
    else:
        with st.expander("Keiner davon / manuell korrigieren"):
            arts = list_articles(cfg)
            labels = ["Unbekannt / nicht in der Liste"] + [
                f"{a.name}  ({a.article_number})" for a in arts]
            pick = st.selectbox("Wahrer Artikel", labels, key="none_of_these_pick")
            if st.button("Korrektur speichern", key="none_of_these_save"):
                nr = None if pick == labels[0] else arts[labels.index(pick) - 1].article_number
                try:
                    reject_result(report, nr)
                except ValueError as e:
                    st.error(f"Korrektur nicht gespeichert: {e}")
                else:
                    res["verdict_saved"] = nr or "__unknown__"
                    st.rerun()


def render_seg_debug(seg) -> None:
    """Show the intermediate stage masks so a wrong segmentation can be
    understood at a glance (which stage saw what) – the engine itself has
    no tunables; the capture in data/captures/ is the test case."""
    dbg = getattr(seg, "debug", None)
    if not dbg:
        return
    if dbg.get("n_plausible", 1) > 1:
        st.warning(f"{dbg['n_plausible']} plausible Teile erkannt – vermessen "
                   "wurde nur das best-bewertete. Liegt wirklich nur EIN Objekt "
                   "in der Box?")
    with st.expander("Stufen-Ansicht (Debug): Evidenz → Graph-Cut → Abschluss"):
        st.caption("**Evidenz** = Differenz+Textur zum leeren-Box-Referenzbild; "
                   "**Graph-Cut** = global optimale Objekt/Boden-Aufteilung; "
                   "**Abschluss** = kanten-umschlossene Spiegelzonen dem Objekt "
                   "zugeschlagen. Die finale Kontur rastet danach auf den "
                   "sichtbaren Bildkanten ein.")
        keys = [
            ("evidence", "Evidenz (Diff + Textur)"),
            ("cut", "Graph-Cut (global optimal)"),
            ("completed", "Kanten-Abschluss"),
        ]
        cols = st.columns(len(keys))
        for col, (key, label) in zip(cols, keys):
            m = dbg.get(key)
            if m is not None:
                col.image(resize_width(m, 480), caption=label)


def clear_pending_previews() -> None:
    """Unsaved create/enroll previews are measurements – they become invalid
    when calibration, background or config change, so drop them."""
    st.session_state.pop("create_pending", None)
    st.session_state.pop("enroll_pending", None)


def ready_for_pipeline(cfg: dict) -> bool:
    return (resolve(cfg["calibration"]["file"]).exists()
            and resolve(cfg["calibration"]["background_file"]).exists())


# ---------- Config laden ----------

if "cfg_path" not in st.session_state:
    st.session_state.cfg_path = str(cfg_module.DEFAULT_CONFIG_PATH)

st.sidebar.title("Doco_Detect")
st.sidebar.text_input("Config-Pfad", key="cfg_path")

if "cfg" not in st.session_state or st.sidebar.button("Config neu laden"):
    try:
        st.session_state.cfg = load_config(st.session_state.cfg_path)
    except Exception as e:
        st.sidebar.error(f"Config-Fehler: {e}")
        st.stop()
    clear_pending_previews()

cfg = st.session_state.cfg

st.sidebar.subheader("Status")
for label, path in {
    "Datenbank": resolve(cfg["paths"]["db_file"]),
    "Hintergrund": resolve(cfg["calibration"]["background_file"]),
    "Kalibrierung": resolve(cfg["calibration"]["file"]),
}.items():
    st.sidebar.markdown(f"{'[OK]' if path.exists() else '[fehlt]'} {label} — `{path.name}`")

st.sidebar.subheader("Kamera")
st.sidebar.caption(f"Index {cfg['camera']['index']}  ·  "
                   f"{cfg['camera']['width']}×{cfg['camera']['height']}")
if st.sidebar.button("Kamera freigeben"):
    release_camera()
    st.session_state.preview_on = False
    st.sidebar.success("Kamera geschlossen.")


# ---------- Live-Vorschau (verkleinert, ~3 fps, pausiert während Capture) ----------

st.subheader("Live-Vorschau")
st.toggle("Vorschau aktiv – Objekt in der Box positionieren", key="preview_on", value=False)


@st.fragment(run_every=0.3)
def live_preview():
    if not st.session_state.get("preview_on"):
        st.caption("Vorschau aus.")
        return
    if st.session_state.get("capturing"):
        st.caption("Vorschau pausiert – Aufnahme läuft…")
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

(tab_db, tab_bg, tab_cal, tab_identify, tab_new, tab_enroll,
 tab_config) = st.tabs([
    "Datenbank", "1. Hintergrund", "2. Kalibrieren",
    "3. Identifizieren", "Neuer Artikel", "4. Einlernen", "Config",
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

            st.subheader("Artikel löschen")
            st.caption("Z. B. einen falsch vermessenen, live angelegten Artikel entfernen "
                       "(inkl. eingelernter Referenzen; Fotos unter data/reference/ bleiben).")
            if del_msg := st.session_state.pop("del_msg", None):
                st.success(del_msg)
            del_nr = st.selectbox("Artikelnummer",
                                  [a.article_number for a in articles], key="del_article")
            del_sure = st.checkbox("Ja, wirklich löschen", key="del_sure")
            if st.button("Löschen", disabled=not del_sure):
                db = Database(cfg)
                try:
                    removed = db.delete_article(del_nr)
                finally:
                    db.close()
                if removed:
                    # Disarm the confirmation BEFORE the rerun: the checkbox
                    # state would otherwise survive while the selectbox jumps
                    # to another article – one stray click would delete it.
                    del st.session_state["del_sure"]
                    st.session_state["del_msg"] = f"{del_nr} gelöscht."
                    st.rerun()
                else:
                    st.warning(f"{del_nr} nicht gefunden.")
        else:
            st.info("Noch keine Artikel importiert.")
    except Exception as e:
        st.warning(f"Datenbank nicht lesbar: {e}")


# ---------- Tab: Hintergrund ----------

with tab_bg:
    st.header("1. Hintergrund aufnehmen")
    st.write("Box **leer** stellen, dann aufnehmen. Das Foto dient als Referenz "
             "für die Hintergrund-Segmentierung.")
    st.caption("Wichtig: nach jeder Änderung von Belichtung/Weißabgleich (Tab Config) "
               "hier den Hintergrund **neu aufnehmen** – sonst stimmt die Differenz nicht.")
    if st.button("Hintergrund aufnehmen", type="primary"):
        try:
            frame = capture_frame(cfg)
        except CameraError as e:
            st.error(f"Kamera-Fehler: {e}  \n{CAMERA_HINT}")
        else:
            save_background(frame, cfg)
            clear_pending_previews()
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
        if st.button("Kalibrieren", type="primary"):
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
                    clear_pending_previews()
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
        if st.button("Identifizieren", type="primary"):
            st.session_state.pop("identify_result", None)
            try:
                frame = capture_frame(cfg)
                pipe = Pipeline(cfg)
                try:
                    outcome = pipe.identify(
                        frame, source_path=st.session_state.get("last_capture_path"))
                finally:
                    pipe.close()
            except CameraError as e:
                st.error(f"Kamera-Fehler: {e}  \n{CAMERA_HINT}")
            except Exception as e:
                st.error(f"Fehler: {e}")
            else:
                # Ergebnis in der Session halten: jeder Button-Klick (z.B. die
                # Richtig/Falsch-Bewertung) löst einen Rerun aus – die Anzeige
                # muss ihn überleben.
                st.session_state.identify_result = {
                    "frame": frame, "report": outcome.report,
                    "features": outcome.features, "seg": outcome.segmentation,
                }

        res = st.session_state.get("identify_result")
        if res:
            frame = res["frame"]

            col1, col2 = st.columns(2)
            col1.image(resize_width(frame, 960), channels="BGR", caption="Original")
            if res["seg"] is not None:
                col2.image(resize_width(make_overlay(frame, res["seg"]), 960),
                           channels="BGR", caption="Segmentierung (rot = Kontur, grün = Maske)")
                render_seg_debug(res["seg"])
            else:
                col2.info("Keine Segmentierung möglich (siehe Meldung oben).")

            if res["features"] is not None:
                render_features(res["features"])

            _render_identify_result(res, cfg)
            st.caption("Volle Aufschlüsselung (z-Werte, Gewichte, "
                       "Top-1-vs-Top-2): Seite **Scoring-Analyse** in der Sidebar.")


# ---------- Tab: Neuer Artikel ----------

with tab_new:
    st.header("Neuen Artikel per Kamera anlegen")
    if not ready_for_pipeline(cfg):
        st.warning("Erst Hintergrund + Kalibrierung anlegen (Schritte 1-2).")
    else:
        st.write("Objekt (z. B. Löffel) in die Box legen, Namen eingeben, aufnehmen. "
                 "Kein CSV nötig – die Maße werden gemessen und als **Vorschau** "
                 "angezeigt. Gespeichert wird erst, wenn du die Segmentierung "
                 "geprüft und **übernommen** hast.")
        new_name = st.text_input("Name *", key="new_name",
                                 placeholder="z. B. Suppenlöffel")
        col_a, col_b = st.columns(2)
        new_number = col_a.text_input("Artikelnummer (leer = automatisch)",
                                      key="new_number")
        new_category = col_b.text_input("Kategorie (optional)", key="new_category",
                                        placeholder="Löffel / Teller / Tasse …")
        new_height = st.number_input(
            "Objekthöhe in mm (optional – 0 = flach, z. B. Löffel)",
            min_value=0.0, value=0.0, step=1.0, key="new_height",
            help="Nur nötig für erhöhte Objekte (Tasse, Schüssel). Bei flachen "
                 "Teilen 0 lassen.")

        if create_msg := st.session_state.pop("create_msg", None):
            st.success(create_msg)

        if st.button("Aufnehmen & prüfen", type="primary", key="create_capture",
                     disabled=not new_name.strip()):
            st.session_state.pop("create_pending", None)
            frame = None
            try:
                frame = capture_frame(cfg)
                db = Database(cfg)
                db.init_schema()
                db.close()
                pipe = Pipeline(cfg)
                try:
                    seg, feats = pipe.analyze(frame)
                    article = pipe.derive_article(
                        seg, feats, new_name.strip(),
                        article_number=(new_number.strip() or None),
                        height_mm=float(new_height),
                        category=(new_category.strip() or None),
                    )
                finally:
                    pipe.close()
            except CameraError as e:
                st.error(f"Kamera-Fehler: {e}  \n{CAMERA_HINT}")
            except SegmentationError as e:
                st.error(f"Segmentierung: {e}  \nEs wurde nichts gespeichert.")
                if frame is not None:
                    seg_err = getattr(e, "segmentation", None)
                    col1, col2 = st.columns(2)
                    col1.image(resize_width(frame, 960), channels="BGR",
                               caption="Original")
                    if seg_err is not None:
                        col2.image(resize_width(make_overlay(frame, seg_err), 960),
                                   channels="BGR",
                                   caption="Segmentierung (rot = Kontur, grün = Maske) "
                                           "– berührt den Rand")
                        render_seg_debug(seg_err)
                    else:
                        col2.info("Kein Objekt sicher segmentiert (leere Box?).")
            except Exception as e:
                st.error(f"Fehler: {e}")
            else:
                st.session_state.create_pending = {
                    "frame": frame, "seg": seg, "feats": feats, "article": article,
                    # Widget values at capture time – the preview is only valid
                    # for exactly these; edits afterwards lock the save button.
                    "inputs": {"name": new_name.strip(), "number": new_number.strip(),
                               "height": float(new_height),
                               "category": new_category.strip()},
                }

        pending = st.session_state.get("create_pending")
        if pending:
            art = pending["article"]
            geo = (f"Ø {art.diameter_mm:.1f} mm" if art.diameter_mm
                   else f"{art.width_mm:.1f} × {art.depth_mm:.1f} mm")
            st.info(f"**Vorschau – noch nichts gespeichert:** {art.article_number} – "
                    f"{art.name} ({geo}, Höhe: {art.height_mm or 0:.0f} mm, "
                    f"Kategorie: {art.category or '–'}, Farbe: {art.color_desc}).  \n"
                    "Segmentierung prüfen: Ist das **ganze** Objekt erfasst "
                    "(z. B. Löffelstiel mit Spitze)? Dann übernehmen – sonst "
                    "verwerfen, Objekt ggf. neu positionieren und erneut aufnehmen.")
            col1, col2 = st.columns(2)
            col1.image(resize_width(pending["frame"], 960), channels="BGR",
                       caption="Original")
            col2.image(resize_width(make_overlay(pending["frame"], pending["seg"]), 960),
                       channels="BGR",
                       caption="Segmentierung (rot = Kontur, grün = Maske)")
            render_seg_debug(pending["seg"])
            render_features(pending["feats"])
            inputs_now = {"name": new_name.strip(), "number": new_number.strip(),
                          "height": float(new_height), "category": new_category.strip()}
            inputs_changed = inputs_now != pending["inputs"]
            if inputs_changed:
                st.warning("Die Eingaben oben wurden **nach** der Aufnahme geändert – "
                           "die Vorschau (inkl. Höhenkorrektur der Maße!) gilt noch "
                           "für die alten Werte. Speichern ist gesperrt: bitte neu "
                           "aufnehmen oder verwerfen.")
            c_ok, c_no = st.columns(2)
            if c_ok.button("Artikel speichern", type="primary", key="create_commit",
                           disabled=inputs_changed):
                try:
                    pipe = Pipeline(cfg)
                except Exception as e:
                    st.error(f"Fehler: {e}")
                else:
                    try:
                        pipe.commit_article(art, pending["feats"])
                    except KeyError as e:
                        st.error(f"Artikelnummer bereits vergeben: {e}")
                    except Exception as e:
                        st.error(f"Fehler: {e}")
                    else:
                        st.session_state.pop("create_pending", None)
                        st.session_state["create_msg"] = (
                            f"Artikel {art.article_number} – {art.name} gespeichert "
                            "(inkl. 1 Referenz – sofort erkennbar).")
                        st.rerun()
                    finally:
                        pipe.close()
            if c_no.button("Verwerfen", key="create_discard"):
                st.session_state.pop("create_pending", None)
                st.rerun()


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
            st.write("Objekt in die Box legen, aufnehmen und prüfen – gespeichert "
                     "wird erst nach deiner Bestätigung.")
            if enroll_msg := st.session_state.pop("enroll_msg", None):
                st.success(enroll_msg)

            if st.button("Aufnehmen & prüfen", type="primary", key="enroll_capture"):
                st.session_state.pop("enroll_pending", None)
                frame = None
                try:
                    frame = capture_frame(cfg)
                    pipe = Pipeline(cfg)
                    try:
                        seg, feats = pipe.analyze(frame)
                    finally:
                        pipe.close()
                except CameraError as e:
                    st.error(f"Kamera-Fehler: {e}  \n{CAMERA_HINT}")
                except SegmentationError as e:
                    st.error(f"Segmentierung: {e}  \nEs wurde nichts gespeichert.")
                    if frame is not None:
                        seg_err = getattr(e, "segmentation", None)
                        col1, col2 = st.columns(2)
                        col1.image(resize_width(frame, 960), channels="BGR",
                                   caption="Original")
                        if seg_err is not None:
                            col2.image(resize_width(make_overlay(frame, seg_err), 960),
                                       channels="BGR",
                                       caption="Segmentierung (rot = Kontur, grün = Maske) "
                                               "– berührt den Rand")
                            render_seg_debug(seg_err)
                        else:
                            col2.info("Kein Objekt sicher segmentiert (leere Box, "
                                      "diff_threshold zu hoch?).")
                except Exception as e:
                    st.error(f"Fehler: {e}")
                else:
                    st.session_state.enroll_pending = {
                        "frame": frame, "seg": seg, "feats": feats,
                        "article_number": article_number,
                    }

            pending = st.session_state.get("enroll_pending")
            if pending:
                st.info(f"**Vorschau für {pending['article_number']} – noch nicht "
                        "gespeichert.** Nur eine Referenz mit korrekter Kontur "
                        "verbessert die Erkennung – eine falsche verschlechtert sie.")
                col1, col2 = st.columns(2)
                col1.image(resize_width(pending["frame"], 960), channels="BGR",
                           caption="Original")
                col2.image(resize_width(make_overlay(pending["frame"], pending["seg"]), 960),
                           channels="BGR",
                           caption="Segmentierung (rot = Kontur, grün = Maske)")
                render_seg_debug(pending["seg"])
                render_features(pending["feats"])
                sel_changed = pending["article_number"] != article_number
                if sel_changed:
                    st.warning(f"Die Auswahl oben steht jetzt auf **{article_number}**, "
                               f"die Vorschau gehört aber zu "
                               f"**{pending['article_number']}**. Speichern ist "
                               "gesperrt: Auswahl zurückstellen oder verwerfen und "
                               "neu aufnehmen.")
                e_ok, e_no = st.columns(2)
                if e_ok.button("Referenz speichern", type="primary", key="enroll_commit",
                               disabled=sel_changed):
                    try:
                        pipe = Pipeline(cfg)
                        try:
                            pipe.save_reference(pending["article_number"], pending["feats"])
                        finally:
                            pipe.close()
                    except KeyError:
                        st.error(f"Artikel {pending['article_number']} wurde inzwischen "
                                 "gelöscht – Referenz nicht gespeichert.")
                    except Exception as e:
                        st.error(f"Fehler: {e}")
                    else:
                        st.session_state.pop("enroll_pending", None)
                        st.session_state["enroll_msg"] = (
                            f"Referenz für {pending['article_number']} gespeichert.")
                        st.rerun()
                if e_no.button("Verwerfen", key="enroll_discard"):
                    st.session_state.pop("enroll_pending", None)
                    st.rerun()


# ---------- Tab: Config ----------

with tab_config:
    st.header("Parameter (nur diese Session, bis gespeichert)")

    st.subheader("Segmentierung")
    st.info("Die Segmentierung hat **keine Stellschrauben** – sie kalibriert "
            "jede Schwelle selbst am Bildpaar (Boden-Rauschdecke, Kantenstärke, "
            "Objekt-Anker). Stimmt eine Segmentierung nicht, ist das Foto der "
            "Testfall: es liegt automatisch in `data/captures/`.")

    st.subheader("Kamera – Belichtung / Weißabgleich")
    st.warning("Nach jeder Änderung hier: **Hintergrund neu aufnehmen** (Tab 1). "
               "Sonst passen Hintergrund- und Objektbild nicht zusammen und die "
               "Segmentierung wird falsch. Änderungen greifen beim nächsten Kamera-Öffnen.")
    cam = cfg["camera"]
    cam["lock_exposure"] = st.toggle("lock_exposure (feste Belichtung/Gain)",
                                     value=bool(cam.get("lock_exposure", False)))
    cam["exposure"] = st.number_input("exposure (UVC – kameraspezifisch, per Sweep ermitteln)",
                                      value=float(cam.get("exposure", -6.0)), step=1.0)
    cam["lock_white_balance"] = st.toggle("lock_white_balance",
                                          value=bool(cam.get("lock_white_balance", False)))
    cam["wb_temperature"] = st.number_input("wb_temperature (K)",
                                            value=int(cam.get("wb_temperature", 4600)), step=100)

    st.subheader("Matching")
    m = cfg["matching"]
    m["diameter_tolerance_mm"] = st.slider("diameter_tolerance_mm", 0.0, 30.0, float(m["diameter_tolerance_mm"]))
    m["area_tolerance_pct"] = st.slider("area_tolerance_pct", 0.0, 50.0, float(m["area_tolerance_pct"]))
    m["max_z_accept"] = st.slider("max_z_accept (absolutes Gate: max |z| des Siegers)",
                                  1.0, 6.0, float(m.get("max_z_accept", 3.5)))
    m["min_llr_margin"] = st.slider("min_llr_margin (Log-Likelihood-Vorsprung 1. vs 2.)",
                                    0.0, 10.0, float(m.get("min_llr_margin", 2.0)))
    m["adaptive_weight_alpha"] = st.slider("adaptive_weight_alpha (0 = keine Fisher-Adaption)",
                                           0.0, 5.0, float(m.get("adaptive_weight_alpha", 2.0)))

    st.caption("Änderungen wirken sofort auf Identify/Enroll in dieser Session.")
    if st.button("Dauerhaft in config.yaml speichern"):
        with open(st.session_state.cfg_path, "w", encoding="utf-8") as fh:
            yaml.safe_dump(cfg, fh, allow_unicode=True, sort_keys=False)
        st.success(f"Gespeichert nach {st.session_state.cfg_path}")
