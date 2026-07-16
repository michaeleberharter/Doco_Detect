"""Scoring-Analyse: rendert ausschließlich MatchReport-Objekte.

Datenquellen: live (pipeline.identify über die echte BoxCamera) oder
gespeicherte Report-JSONs aus data/captures/ (die Pipeline legt sie bei
jeder Identifikation automatisch ab). Keine eigene Bildverarbeitung –
alles kommt aus docodetect/{pipeline,reporting}.py.

Beantwortet für die Testphase:
- WELCHES Merkmal hat die Entscheidung getragen? (Log-Beitrags-Chart)
- Warum A statt B? (Kontrast Top-1 vs Top-2)
- Wie hat die Fisher-Adaption die Gewichte verschoben? (Diskriminanz-Panel)
- Warum ACCEPT/AMBIGUOUS/REJECT? (Gate-Ampel: max|z| + LLR-Margin)
"""

from __future__ import annotations

from pathlib import Path

import cv2
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from docodetect.camera import CameraError
from docodetect.config import load_config, resolve
from docodetect.pipeline import Pipeline
from docodetect.reporting import load_reports, predicted_article, summarize
from ui_common import (CAMERA_HINT, capture_frame, draw_report_overlay,
                       resize_width)

st.set_page_config(page_title="Scoring-Analyse", layout="wide")
st.title("Scoring-Analyse")

if "cfg" not in st.session_state:
    st.session_state.cfg = load_config()
cfg = st.session_state.cfg

Z_GREEN, Z_YELLOW = 1.0, 2.5


def z_style(z):
    try:
        z = abs(float(z))
    except (TypeError, ValueError):
        return ""
    if z < Z_GREEN:
        return "background-color:#1a7f37;color:white"
    if z < Z_YELLOW:
        return "background-color:#b58900;color:white"
    return "background-color:#b02a37;color:white"


def show_decision(report) -> None:
    badge = {"accept": ("ACCEPT", st.success),
             "ambiguous": ("AMBIGUOUS", st.warning),
             "reject": ("REJECT", st.error)}
    label, fn = badge.get(report.decision, (report.decision.upper(), st.info))
    fn(f"{label} — {report.message}")


def render_gate(report) -> None:
    thr = report.thresholds or {}
    c1, c2, c3 = st.columns(3)
    max_z = report.max_z_winner
    zt = thr.get("max_z_accept")
    c1.metric("max |z| Sieger", "–" if max_z is None else f"{max_z:.2f}",
              delta=None if (max_z is None or zt is None) else f"Gate: ≤ {zt}",
              delta_color="off")
    llr = report.llr_margin
    lt = thr.get("min_llr_margin")
    c2.metric("LLR-Margin (1. vs 2.)", "∞ (1 Kandidat)" if llr is None else f"{llr:.2f}",
              delta=None if lt is None else f"Schwelle: ≥ {lt}", delta_color="off")
    top_post = report.candidates[0].posterior if report.candidates else None
    c3.metric("Posterior Top-1", "–" if top_post is None else f"{top_post:.0%}")


def render_image(report) -> None:
    if not report.image_path or not Path(report.image_path).exists():
        st.info("Bilddatei nicht (mehr) vorhanden – nur die Zahlen des Reports.")
        return
    img = cv2.imread(report.image_path)
    if img is None:
        st.info(f"Bild nicht lesbar: {report.image_path}")
        return
    col1, col2 = st.columns(2)
    col1.image(resize_width(img, 960), channels="BGR", caption="Aufnahme")
    border = ("berührt den Bildrand!" if report.touches_border
              else "Randprüfung ok")
    col2.image(resize_width(draw_report_overlay(img, report), 960), channels="BGR",
               caption=f"Kontur aus dem Report — {border}")


def render_measured(report) -> None:
    m = report.measured or {}
    if not m:
        return
    st.subheader("Gemessene Merkmale (Floor-Ebene)")
    cols = {"Ø Kreis (mm)": m.get("circle_diameter_mm"),
            "Ø äquiv. (mm)": m.get("equiv_diameter_mm"),
            "Fläche (cm²)": round(m.get("area_mm2", 0) / 100, 1),
            "Rundheit": m.get("circularity"),
            "Solidity": m.get("solidity"),
            "Lab Zentrum": str(m.get("lab_center")),
            "Lab Rand": str(m.get("lab_rim"))}
    st.dataframe(pd.DataFrame([cols]), width="stretch", hide_index=True)
    if report.candidates:
        st.caption("Höhenkompensiert pro Kandidat (Vorfilter):")
        rows = [{"Artikel": c.article_number, "Höhe (mm)": c.height_mm,
                 "Ø korrigiert (mm)": c.corrected_diameter_mm,
                 "Nominal (mm)": c.nominal_size_mm,
                 "Δ Geometrie (mm)": c.geometry_error_mm}
                for c in report.candidates]
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


def render_candidate_tables(report) -> None:
    st.subheader("Kandidaten: Merkmals-Aufschlüsselung")
    top_k = int((report.thresholds or {}).get("top_k", 3))
    for i, c in enumerate(report.candidates):
        ref = "" if c.has_references else " · keine Referenzen (nur Geometrie)"
        with st.expander(
                f"#{i + 1}  {c.article_number} — {c.name} · log-Score "
                f"{c.log_score:.3f} · Posterior {c.posterior:.0%}{ref}",
                expanded=(i < top_k)):
            rows = [{"Merkmal": f.feature, "Messwert": f.measured,
                     "Referenz": f.reference, "Distanz": f.distance,
                     "σ_enroll": f.sigma_enroll, "σ_eff": f.sigma_eff,
                     "z": f.z, "logL": f.log_contrib, "w_eff": f.w_eff,
                     "gewichtet": f.weighted}
                    for f in c.features]
            rows.append({"Merkmal": "Σ log-Score / Posterior", "Messwert": None,
                         "Referenz": None, "Distanz": None, "σ_enroll": None,
                         "σ_eff": None, "z": None, "logL": None, "w_eff": None,
                         "gewichtet": f"{c.log_score:.3f} / {c.posterior:.1%}"})
            df = pd.DataFrame(rows)
            st.dataframe(df.style.map(z_style, subset=["z"]), width="stretch",
                         hide_index=True)


def render_contribution_chart(report) -> None:
    top_k = int((report.thresholds or {}).get("top_k", 3))
    data = [{"Merkmal": f.feature, "gewichteter Log-Beitrag": f.weighted,
             "Artikel": c.article_number}
            for c in report.candidates[:top_k] for f in c.features]
    if not data:
        return
    st.subheader("Gewichtete Log-Beiträge — welches Merkmal trägt die Entscheidung?")
    fig = px.bar(pd.DataFrame(data), x="Merkmal", y="gewichteter Log-Beitrag",
                 color="Artikel", barmode="group")
    st.plotly_chart(fig, width="stretch")
    st.caption("Weniger negativ = besser. Ein einzelner stark negativer Balken "
               "zeigt das Merkmal, das den Kandidaten disqualifiziert.")


def render_discriminance(report) -> None:
    st.subheader("Diskriminanz-Panel: Fisher-Adaption der Gewichte")
    if not report.fisher_d_norm:
        st.caption("Adaption entfiel — nur 1 Kandidat, α = 0 oder keine "
                   "trennenden Merkmale (alle D_f = 0).")
    else:
        dn = pd.DataFrame({"Merkmal": list(report.fisher_d_norm),
                           "D_norm": list(report.fisher_d_norm.values())})
        st.plotly_chart(px.bar(dn, x="Merkmal", y="D_norm",
                               title="normierte Fisher-Diskriminanz D_f"),
                        width="stretch")
    if report.w_global and report.w_eff:
        feats = report.feature_names or list(report.w_global)
        fig = go.Figure()
        fig.add_bar(name="w_global", x=feats,
                    y=[report.w_global.get(f, 0.0) for f in feats])
        fig.add_bar(name="w_eff (adaptiert)", x=feats,
                    y=[report.w_eff.get(f, 0.0) for f in feats])
        fig.update_layout(barmode="group", title=f"Gewichte vor/nach Adaption "
                                                 f"(α = {report.alpha})")
        st.plotly_chart(fig, width="stretch")


def render_top1_vs_top2(report) -> None:
    if len(report.candidates) < 2:
        return
    c1, c2 = report.candidates[0], report.candidates[1]
    st.subheader(f"Kontrast: {c1.article_number} (Top-1) vs. "
                 f"{c2.article_number} (Top-2)")
    st.caption("Die direkte Antwort auf „warum hat er A statt B gewählt?\" — "
               "pro Merkmal, wer vorne liegt und um wieviel Log-Beitrag.")
    f1 = {f.feature: f for f in c1.features}
    f2 = {f.feature: f for f in c2.features}
    rows = []
    for name in report.feature_names:
        a, b = f1.get(name), f2.get(name)
        if a is None and b is None:
            continue
        wa = a.weighted if a else None
        wb = b.weighted if b else None
        delta = (wa - wb) if (wa is not None and wb is not None) else None
        rows.append({"Merkmal": name,
                     f"z {c1.article_number}": a.z if a else None,
                     f"z {c2.article_number}": b.z if b else None,
                     "Δ gewichtet (1−2)": round(delta, 4) if delta is not None else None,
                     "Vorteil": ("—" if delta is None else
                                 c1.article_number if delta > 0 else
                                 c2.article_number if delta < 0 else "gleich")})
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


def render_report(report) -> None:
    show_decision(report)
    render_gate(report)
    render_image(report)
    render_measured(report)
    if report.candidates:
        render_candidate_tables(report)
        render_contribution_chart(report)
        render_discriminance(report)
        render_top1_vs_top2(report)
    meta = f"Zeitstempel: {report.timestamp}"
    if report.label:
        meta += f" · Label: {report.label}"
    st.caption(meta)


tab_single, tab_batch = st.tabs(["Einzel-Report", "Batch-Auswertung"])

with tab_single:
    captures_dir = resolve(cfg["paths"].get("captures_dir", "data/captures"))
    col_live, col_pick = st.columns([1, 2])
    with col_live:
        if st.button("Live identifizieren", type="primary"):
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
                st.session_state.analysis_report = outcome.report
    with col_pick:
        loaded = load_reports(captures_dir, limit=25)
        if loaded:
            options = {f"{p.name} · {rep.decision} · {predicted_article(rep)}": rep
                       for p, rep in loaded}
            choice = st.selectbox("Gespeicherten Report laden (neueste zuerst)",
                                  ["– aktuelle Live-Analyse –"] + list(options))
            if choice != "– aktuelle Live-Analyse –":
                st.session_state.analysis_report = options[choice]
        else:
            st.caption(f"Keine gespeicherten Reports in `{captures_dir}` – "
                       "jede Identifikation legt dort automatisch einen ab.")

    report = st.session_state.get("analysis_report")
    if report is None:
        st.info("Live identifizieren oder oben einen gespeicherten Report wählen.")
    else:
        render_report(report)

with tab_batch:
    folder = st.text_input("Report-Ordner",
                           value=str(resolve(cfg["paths"].get("captures_dir",
                                                              "data/captures"))))
    reports = [r for _, r in load_reports(folder)]
    if not reports:
        st.info("Keine Report-JSONs gefunden.")
    else:
        s = summarize(reports)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Reports", s.total)
        c2.metric("Top-1-Accuracy",
                  f"{s.accuracy:.1%}" if s.labeled else "– (keine Labels)")
        c3.metric("ACCEPT-Anteil",
                  f"{s.decision_counts.get('accept', 0) / s.total:.0%}")
        c4.metric("REJECT-Anteil",
                  f"{s.decision_counts.get('reject', 0) / s.total:.0%}")
        st.plotly_chart(px.pie(names=list(s.decision_counts),
                               values=list(s.decision_counts.values()),
                               title="Entscheidungsverteilung"), width="stretch")
        if s.posteriors_correct or s.posteriors_wrong:
            df = pd.DataFrame(
                [{"Posterior": p, "Ergebnis": "korrekt"} for p in s.posteriors_correct]
                + [{"Posterior": p, "Ergebnis": "falsch"} for p in s.posteriors_wrong])
            st.plotly_chart(px.histogram(df, x="Posterior", color="Ergebnis",
                                         barmode="overlay", nbins=20,
                                         title="Posterior-Verteilung korrekt vs. falsch"),
                            width="stretch")
        if s.per_class:
            labels = sorted(s.per_class)
            preds = sorted({p for row in s.per_class.values() for p in row})
            z = [[s.per_class[t].get(p, 0) for p in preds] for t in labels]
            st.plotly_chart(px.imshow(z, x=preds, y=labels, text_auto=True,
                                      labels={"x": "Vorhersage", "y": "Wahrheit"},
                                      title="Verwechslungsmatrix"), width="stretch")
        if s.confusion:
            st.subheader("Verwechslungspaare (nur Fehler)")
            st.dataframe(pd.DataFrame(s.confusion,
                                      columns=["Wahrheit", "Vorhersage", "Anzahl"]),
                         width="stretch", hide_index=True)
