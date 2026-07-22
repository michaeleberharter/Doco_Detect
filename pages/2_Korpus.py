"""Korpus: zeigt die Artefakte, die `corpus-report` erzeugt hat.

REINE ANZEIGE. Diese Seite rechnet nichts — sie sucht fertige Reviews unter
reports/corpus/ und rendert deren PNG/CSV. Kanonisch sind die Dateien auf
Platte, nicht diese Seite; wer die Zahlen weitergibt, gibt die CSV weiter.

Neue Reviews entstehen ausschliesslich ueber die CLI:

    python -m docodetect.cli corpus-report --run letzte
    python -m docodetect.cli corpus-report --compare <run_a> <run_b>
"""

from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd
import streamlit as st

from docodetect.config import load_config, resolve

st.set_page_config(page_title="Korpus", layout="wide")
st.title("Korpus-Review")

if "cfg" not in st.session_state:
    st.session_state.cfg = load_config()
cfg = st.session_state.cfg

WURZEL = resolve(cfg.get("corpus_report", {}).get("output_dir", "reports/corpus"))

# Reihenfolge und Ueberschriften der vier Ansichten — identisch zur
# HTML-Uebersicht, damit beide Wege dasselbe Bild zeigen.
ANSICHTEN = [
    ("1. Drift-Review",
     ["drift_scatter.png", "decision_matrix.png"],
     ["drift_review.csv", "decision_matrix.csv", "top1_wechsel.csv"]),
    ("2. Baseline-Verlauf",
     ["baseline_verlauf.png"], ["baseline_verlauf.csv"]),
    ("3. Verteilungen",
     ["verteilungen.png"], ["verteilungen.csv"]),
    ("4. Konfusionsmatrix und Quoten",
     ["confusion_matrix.png", "confusion_matrix_accept.png", "quoten.png"],
     ["quoten.csv", "confusion_matrix.csv", "confusion_matrix_accept.csv"]),
    ("5. Tier-1-Drift je Merkmal",
     ["tier1_drift.png"], ["tier1_drift.csv"]),
]


def reviews() -> list[Path]:
    """Vorhandene Reviews, neueste zuerst."""
    if not WURZEL.is_dir():
        return []
    return sorted((p for p in WURZEL.iterdir()
                   if p.is_dir() and (p / "drift_review.csv").exists()),
                  key=lambda p: p.stat().st_mtime, reverse=True)


vorhanden = reviews()
if not vorhanden:
    st.info(
        f"Noch keine Review unter `{WURZEL}`.\n\n"
        "Diese Seite zeigt nur fertige Artefakte an, sie erzeugt keine. "
        "Erzeugen mit:\n\n"
        "```\npython -m docodetect.cli corpus-report --run letzte\n```")
    st.stop()

namen = [p.name for p in vorhanden]
gewaehlt = st.sidebar.radio("Review", namen, index=0)
review = vorhanden[namen.index(gewaehlt)]
st.sidebar.caption(f"Artefakte: `{review}`")

zeilen = list(csv.DictReader(open(review / "drift_review.csv",
                                  newline="", encoding="utf-8")))

kopf = st.columns(4)
kopf[0].metric("Bilder", len(zeilen))
for spalte, band in zip(kopf[1:], ("pass", "drift", "fail")):
    spalte.metric(band.upper(), sum(1 for z in zeilen if z["band"] == band))

st.caption(
    "Alle Band-Urteile stammen aus `metrics.json` bzw. `failures/` des Laufs, "
    "alle Quoten einer Laufseite aus dessen `metrics.json`. Hier wird nichts "
    "nachgerechnet.")

auffaellig = [z for z in zeilen
              if z["aenderung"] in ("entscheidung", "top1")]
if auffaellig:
    st.subheader(f"Entscheidungs- oder Rang-1-Wechsel ({len(auffaellig)})")
    st.dataframe(pd.DataFrame(auffaellig)[
        ["sha8", "band", "aenderung", "label", "decision_alt", "decision_neu",
         "top1_alt", "top1_neu", "llr_margin_alt", "llr_margin_neu",
         "max_z_alt", "max_z_neu", "treiber_neu", "delta_status",
         "delta_kategorie"]], width="stretch", hide_index=True)

for titel, bilder, tabellen in ANSICHTEN:
    da = [b for b in bilder if (review / b).exists()]
    tab = [t for t in tabellen if (review / t).exists()]
    if not da and not tab:
        continue
    st.subheader(titel)
    for name in da:
        st.image(str(review / name), width="stretch")
    for name in tab:
        with st.expander(name):
            st.dataframe(pd.read_csv(review / name), width="stretch",
                         hide_index=True)
            st.download_button(f"{name} herunterladen",
                               (review / name).read_bytes(), file_name=name,
                               key=f"{review.name}-{name}")

if (review / "index.html").exists():
    st.caption(f"Vollstaendige Uebersicht als HTML: `{review / 'index.html'}`")
