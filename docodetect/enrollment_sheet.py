"""Enrollment-Diagnoseblatt: aus den N Shots eines Artikels ein PNG mit fuenf
Feldern.

Einstieg:  build_enrollment_sheet(cfg, article_number=..., out=...) -> Path
CLI:       python -m docodetect.cli enrollment-sheet <artikelnummer> [--out p]

Reine **Diagnose-/Konsumentenschicht** wie analysis.py – KEIN Messpfad. Sie
liest reference_features (image_path + Features), re-segmentiert die
gespeicherten Shots ueber pipeline.analyze fuer die Kontur und rendert ueber
matplotlib. Sie aendert nie Pipeline, Matcher, Segmentierung, Schwellen.

Die fuenf Felder:
  (1) Konturband – alle N Konturen ueber Schwerpunkt + PCA-Hauptachse
      ausgerichtet, aeusserste rot. Restfehler der Ausrichtung in mm.
  (2) Breitenprofil w(s) – Ausdehnung senkrecht zur Achse, 0 = Breitenmaximum.
  (3) Messwert ueber Shot-Nummer – ext_full (bzw. circle_diameter_mm) und
      lat_p98 in Aufnahmereihenfolge, Median als Linie. Drift vs. Streuung.
  (4) Streuungstabelle ueber ALLE Scoring-Merkmale – Mittel/Std/Min-Max/
      Spannweite, aeusserster Shot, dessen klassisches UND robustes
      Leave-one-out-z, Rohdistanzen der Vektor-Merkmale, Vergleich zur
      bisherigen Referenzstreuung, Auffaelligkeit je Shot.
  (5) Heatmap Shot x Merkmal – Leave-one-out-z, zwei getrennte Bloecke:
      Skalare signiert (divergierend), Vektoren einseitig.

Felder (1)-(3) brauchen die Kontur (Bild); Shots ohne image_path werden dort
ausgelassen und im Blatt als fehlend ausgewiesen. Felder (4)/(5) laufen rein
auf reference_features und funktionieren auch fuer reine Altbestands-Artikel.

Die Geometrie-Helfer (_densify/_pca_axes/_proj/_pctl, ext_full/lat_p98, w(s))
sind 1:1 aus den eingefrorenen C-Serie-Skripten uebernommen:
scripts/tail_extent_check.py und scripts/tail_profile_check.py. Sie werden hier
kopiert (nicht importiert), damit jene Skripte read-only bleiben; die
Produktionsmessung nutzt sie NICHT (sie misst circle_diameter_mm).

WARNUNG (Bildunterschrift): Das Blatt ist KEIN Messinstrument. Die starre
Schwerpunkt-/PCA-Registrierung hat laut C4 einen Boden von 2-9 mm; das Blatt
zeigt die Bandbreite, nicht lokalisierte Differenzen.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import matplotlib

matplotlib.use("Agg")  # headless – nie ein Fenster oeffnen (wie analysis.py)
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.cm import ScalarMappable  # noqa: E402
from matplotlib.colors import Normalize  # noqa: E402
import numpy as np  # noqa: E402

from .config import resolve  # noqa: E402
from .features import Features, scalar_value  # noqa: E402
# _PROTO_SRC = kanonische (Attribut, Distanzfunktion) je Vektor-Merkmal. Bewusst
# der private Name aus features.py: die Distanzabbildung ist Messlogik und darf
# nicht dupliziert werden (CLAUDE.md). Nur-Lesen, features.py bleibt unberuehrt.
from .features import _PROTO_SRC  # noqa: E402
from .pipeline import Pipeline  # noqa: E402
from .plotstyle import DIV, OUTLIER, SEQ, panel_label, style_context  # noqa: E402
from .segmentation import SegmentationError  # noqa: E402

# C-Serie saubere Gruppen: Streuung von ext_full lag bei 0,43-0,92 mm.
C_SERIES_EXT_STD_MM = (0.43, 0.92)
Z_CAP = 4.0                        # Betrag der z-Werte in der Heatmap gedeckelt
_DENSIFY_STEP_PX = 0.5             # tail_profile_check.py:99 (feiner, fuellt 1-mm-Bins;
                                   # ext_full nutzt ohnehin die Rohkontur-Extrema)


# ============================================================ Geometrie-Helfer
# --- 1:1 aus scripts/tail_extent_check.py / tail_profile_check.py (eingefroren) ---

def _densify(poly: np.ndarray, step: float = _DENSIFY_STEP_PX) -> np.ndarray:
    """Geschlossenes Polygon bogenlaengen-gleichmaessig nachsamplen."""
    p = poly.astype(np.float64)
    n = len(p)
    out = []
    for i in range(n):
        a, b = p[i], p[(i + 1) % n]
        d = float(np.hypot(*(b - a)))
        k = max(1, int(d / step))
        for j in range(k):
            out.append(a + (b - a) * (j / k))
    return np.asarray(out, dtype=np.float64)


def _pca_axes(points: np.ndarray):
    """Haupt- und Nebenachse (Einheitsvektoren) plus Schwerpunkt."""
    center = points.mean(axis=0)
    cov = np.cov((points - center).T)
    vals, vecs = np.linalg.eigh(cov)          # aufsteigend
    order = np.argsort(vals)[::-1]
    main = vecs[:, order[0]]
    minor = vecs[:, order[1]]
    return center, main / np.linalg.norm(main), minor / np.linalg.norm(minor)


def _proj(points: np.ndarray, axis: np.ndarray) -> np.ndarray:
    """Skalarprojektion der Punkte auf eine Achse (einsum vermeidet eine
    spuriose divide-by-zero-Warnung des matmul-SIMD-Pfads)."""
    return np.einsum("ij,j->i", points, axis)


def _pctl(a: np.ndarray, lo: float, hi: float) -> float:
    return float(np.percentile(a, hi) - np.percentile(a, lo))


# ============================================================ Shot-Geometrie

@dataclass
class ShotGeom:
    """Kontur-abgeleitete Groessen eines Shots, alle in mm. None-Felder =
    Kontur fehlt (kein Bild / Segmentierung schlug fehl)."""
    ext_full: float                 # Laenge = Spann der PCA-Hauptachse (Rohextrema)
    lat_p98: float                  # 1-99-Perzentilbreite der Nebenachse
    xy_mm: np.ndarray               # (K,2) ausgerichtete Kontur (Schwerpunkt=0)
    s_mm: np.ndarray                # Profilposition, 0 = Breitenmaximum
    w_mm: np.ndarray                # Breite w(s)


def _shot_geometry(contour_px: np.ndarray, mmpp: float) -> ShotGeom | None:
    """ext_full/lat_p98/ausgerichtete Kontur/Breitenprofil aus einer Kontur.
    Methode 1:1 wie die C-Serie: bogenlaengen-gleichmaessige Kontur -> PCA,
    ext_full aus den Rohkontur-Extrema, lat_p98 aus den Nebenachsen-Perzentilen,
    w(s) je 1-mm-Bin als Ausdehnung senkrecht zur Hauptachse."""
    contour = np.asarray(contour_px, dtype=np.float64).reshape(-1, 2)
    if len(contour) < 5:
        return None
    dense = _densify(contour)
    center, main, minor = _pca_axes(dense)

    # ext_full aus den EXAKTEN Extrema der Rohkontur (C: tail_extent_check).
    proj_main_orig = _proj(contour - center, main)
    ext_full = float(proj_main_orig.max() - proj_main_orig.min()) * mmpp

    proj_minor_dense = _proj(dense - center, minor)
    lat_p98 = _pctl(proj_minor_dense, 1.0, 99.0) * mmpp

    # Breitenprofil w(s), 1-mm-Bins (C: tail_profile_check._profile).
    s_raw = _proj(dense - center, main)
    s_dense = (s_raw - s_raw.min()) * mmpp
    m_dense = proj_minor_dense * mmpp
    L = float(s_dense.max())
    nb = int(math.floor(L)) + 1
    if nb < 5:
        return None
    w = np.full(nb, np.nan)
    binidx = np.clip(np.floor(s_dense).astype(int), 0, nb - 1)
    for b in range(nb):
        sel = binidx == b
        if sel.sum() >= 2:
            w[b] = m_dense[sel].max() - m_dense[sel].min()
    ii = np.arange(nb)
    good = ~np.isnan(w)
    if good.sum() < 3:
        return None
    w = np.interp(ii, ii[good], w[good])
    ws = np.convolve(w, np.ones(3) / 3.0, mode="same")   # leichte Glaettung

    i_wmax = int(np.argmax(ws))
    s_wmax = i_wmax + 0.5
    # Achsenvorzeichen ueber das Breitenmaximum: Maximum in die erste Haelfte
    # legen, damit alle Shots gleich orientiert ueberlagern.
    if s_wmax > L / 2.0:
        main = -main
        ws = ws[::-1]
        s_wmax = L - s_wmax
    # Deterministische Nebenachse (rechtshaendig) statt PCA-Eigenvektor-Vorzeichen
    # -> N Konturen ueberlagern ohne Spiegel-Mehrdeutigkeit. Gleiche Linie wie
    # der Minor-Eigenvektor, daher lat_p98/w(s) unveraendert.
    minor = np.array([-main[1], main[0]], dtype=np.float64)

    t_mm = _proj(contour - center, main) * mmpp
    n_mm = _proj(contour - center, minor) * mmpp
    xy_mm = np.column_stack([t_mm, n_mm])

    s_grid = (np.arange(len(ws)) + 0.5) - s_wmax     # 0 = Breitenmaximum
    return ShotGeom(ext_full=ext_full, lat_p98=lat_p98, xy_mm=xy_mm,
                    s_mm=s_grid, w_mm=ws)


# ============================================================ Statistik (z-Werte)

def _loo_classic_z(x: np.ndarray) -> np.ndarray:
    """Leave-one-out z je Wert: (x_i - mean_{j!=i}) / std_{j!=i} (ddof=1)."""
    n = len(x)
    z = np.full(n, np.nan)
    for i in range(n):
        others = np.delete(x, i)
        if len(others) < 2:
            continue
        s = float(others.std(ddof=1))
        if s > 0:
            z[i] = (x[i] - float(others.mean())) / s
    return z


def _loo_robust_z(x: np.ndarray) -> np.ndarray:
    """Robustes Leave-one-out z: (x_i - median_{j!=i}) / (1.4826 * MAD_{j!=i}).
    Bei N=12 ist std ueber 11 Werte selbst kippanfaellig, wenn zwei Shots
    streuen – der robuste Wert steht daneben, nicht statt."""
    n = len(x)
    z = np.full(n, np.nan)
    for i in range(n):
        others = np.delete(x, i)
        med = float(np.median(others))
        mad = float(np.median(np.abs(others - med)))
        if mad > 0:
            z[i] = (x[i] - med) / (1.4826 * mad)
    return z


def _global_classic_z(d: np.ndarray) -> np.ndarray:
    s = float(d.std(ddof=1)) if len(d) > 1 else 0.0
    if s <= 0:
        return np.full(len(d), np.nan)
    return (d - float(d.mean())) / s


def _global_robust_z(d: np.ndarray) -> np.ndarray:
    """Robustes z ueber die Distanzmenge: (d_i - median_j d_j) / (1.4826*MAD).
    0 = Normalfall (nicht 1 wie eine RMS-Ratio), damit die Skala mit den
    Skalaren vergleichbar bleibt."""
    med = float(np.median(d))
    mad = float(np.median(np.abs(d - med)))
    if mad <= 0:
        return np.full(len(d), np.nan)
    return (d - med) / (1.4826 * mad)


def _vector_distances(vectors: list) -> list:
    """d_i = Distanz von Shot i zum Leave-one-out-Prototyp (Mittel der anderen
    N-1 Vektoren), via der kanonischen Distanzfunktion. None-Eintraege bleiben
    None. Braucht >=3 konsistente Vektoren, sonst alles None."""
    key_present = [i for i, v in enumerate(vectors) if v]
    if len(key_present) < 3:
        return [None] * len(vectors)
    if len({len(vectors[i]) for i in key_present}) != 1:
        return [None] * len(vectors)   # inkonsistente Laenge (alte Referenzen)
    return key_present


@dataclass
class FeatureRow:
    key: str
    label: str
    unit: str
    kind: str                       # "scalar" | "vector"
    n: int
    mean: float
    std: float
    vmin: float
    vmax: float
    span: float
    extreme_shot: int | None        # 1-basiert (Aufnahmereihenfolge)
    z_classic_extreme: float
    z_robust_extreme: float
    stored_sigma: float | None
    z_full: np.ndarray = field(default_factory=lambda: np.array([]))   # len N, robustes z (nan=fehlt)
    raw_full: np.ndarray = field(default_factory=lambda: np.array([]))  # len N, Wert/Distanz


@dataclass
class SheetMetrics:
    n_shots: int
    n_with_image: int
    rows: list                      # list[FeatureRow]
    scalar_keys: list               # Merkmalsreihenfolge Heatmap-Block A
    vector_keys: list               # Merkmalsreihenfolge Heatmap-Block B
    conspicuity: np.ndarray         # len N: bei wie vielen Merkmalen Shot aeusserster
    # Feld (3):
    ext_full_series: np.ndarray     # len N (nan=fehlt)
    lat_p98_series: np.ndarray
    diameter_series: np.ndarray
    # Feld (1)/(2):
    highlight_shot: int | None      # 1-basiert, aeusserster im Konturband
    align_residual_mm: float | None


# Skalare Merkmale: (key, label, unit, extractor(Features)->float|None)
def _area_mm2(f: Features) -> float | None:
    a = getattr(f, "area_mm2", None)
    return float(a) if a else None


_SCALAR_SPECS = [
    ("diameter_mm", "Ø (circle)", "mm", lambda f: scalar_value(f, "diameter_mm")),
    ("circularity", "circularity", "", lambda f: scalar_value(f, "circularity")),
    ("solidity", "solidity", "", lambda f: scalar_value(f, "solidity")),
    ("aspect_ratio", "aspect_ratio", "", lambda f: float(f.aspect_ratio)),
    ("area", "area", "mm²", _area_mm2),
]
# Vektor-Merkmale in fester Reihenfolge (Keys von _PROTO_SRC).
_VECTOR_KEYS = ["delta_e_center", "delta_e_rim", "hist_center", "hist_rim", "hu_log"]
_VECTOR_LABELS = {
    "delta_e_center": "ΔE center", "delta_e_rim": "ΔE rim",
    "hist_center": "hist center", "hist_rim": "hist rim", "hu_log": "hu_log",
}
# Fuer welche Merkmale die reference_stats einen Vergleichswert liefern:
_STORED_SCALAR = {"diameter_mm", "circularity", "solidity"}


def _extreme(z_robust: np.ndarray, z_classic: np.ndarray):
    """Index (0-basiert) des Shots mit groesstem |z_robust|, mit Rueckfall auf
    |z_classic|. None, wenn nichts auswertbar."""
    for z in (z_robust, z_classic):
        if np.isfinite(z).any():
            return int(np.nanargmax(np.abs(z)))
    return None


def compute_sheet_metrics(feats_list: list, geoms: list,
                          stored_stats=None) -> SheetMetrics:
    """Alle Zahlen des Blatts – rein aus features_list (+ optionaler Geometrie),
    ohne matplotlib. `geoms[i]` ist die ShotGeom von Shot i oder None. Shots in
    Aufnahmereihenfolge. `stored_stats` = EnrollmentStats des Artikels fuer die
    Vergleichsspalte (bisherige Referenzstreuung) oder None."""
    n = len(feats_list)
    n_img = sum(g is not None for g in geoms)
    rows: list = []
    scalar_keys: list = []
    vector_keys: list = []
    # Auffaelligkeit je Shot: bei wie vielen Merkmalen ist der Shot der aeusserste
    conspicuity = np.zeros(n, dtype=int)

    def _add_scalar_row(key, label, unit, values, stored_sigma):
        idx = [i for i, v in enumerate(values) if v is not None]
        raw_full = np.full(n, np.nan)
        for i in idx:
            raw_full[i] = values[i]
        if len(idx) < 3:
            return None
        x = np.array([values[i] for i in idx], dtype=np.float64)
        zc_sub, zr_sub = _loo_classic_z(x), _loo_robust_z(x)
        zc = np.full(n, np.nan)
        zr = np.full(n, np.nan)
        for k, i in enumerate(idx):
            zc[i] = zc_sub[k]
            zr[i] = zr_sub[k]
        ex = _extreme(zr, zc)
        if ex is not None:
            conspicuity[ex] += 1
        row = FeatureRow(
            key=key, label=label, unit=unit, kind="scalar", n=len(idx),
            mean=float(x.mean()), std=float(x.std(ddof=1)) if len(x) > 1 else 0.0,
            vmin=float(x.min()), vmax=float(x.max()),
            span=float(x.max() - x.min()),
            extreme_shot=(ex + 1) if ex is not None else None,
            z_classic_extreme=float(zc[ex]) if ex is not None else float("nan"),
            z_robust_extreme=float(zr[ex]) if ex is not None else float("nan"),
            stored_sigma=stored_sigma, z_full=zr, raw_full=raw_full)
        return row

    # --- Skalare aus den Features ---
    for key, label, unit, extract in _SCALAR_SPECS:
        values = [extract(f) for f in feats_list]
        sigma = None
        if stored_stats is not None and key in _STORED_SCALAR:
            sigma = stored_stats.scalar_std.get(key)
        row = _add_scalar_row(key, label, unit, values, sigma)
        if row is not None:
            rows.append(row)
            scalar_keys.append(key)

    # --- ext_full / lat_p98 aus der Geometrie (nur wenn Bilder da sind) ---
    for key, label in (("ext_full", "ext_full"), ("lat_p98", "lat_p98")):
        values = [getattr(g, key) if g is not None else None for g in geoms]
        row = _add_scalar_row(key, label, "mm", values, None)
        if row is not None:
            rows.append(row)
            scalar_keys.append(key)

    # --- Vektor-Merkmale: Distanz zum Leave-one-out-Prototyp ---
    for key in _VECTOR_KEYS:
        attr, dist_fn = _PROTO_SRC[key]
        vectors = [getattr(f, attr, None) for f in feats_list]
        idx = _vector_distances(vectors)
        raw_full = np.full(n, np.nan)
        if len(idx) < 3:
            continue
        arr = {i: np.asarray(vectors[i], dtype=np.float64) for i in idx}
        d = np.zeros(len(idx), dtype=np.float64)
        for k, i in enumerate(idx):
            others = [arr[j] for j in idx if j != i]
            proto = np.mean(others, axis=0).tolist()
            d[k] = dist_fn(arr[i].tolist(), proto)
            raw_full[i] = d[k]
        zc_sub, zr_sub = _global_classic_z(d), _global_robust_z(d)
        zc = np.full(n, np.nan)
        zr = np.full(n, np.nan)
        for k, i in enumerate(idx):
            zc[i] = zc_sub[k]
            zr[i] = zr_sub[k]
        ex = _extreme(zr, zc)
        if ex is not None:
            conspicuity[ex] += 1
        sigma = stored_stats.proto_std.get(key) if stored_stats is not None else None
        rows.append(FeatureRow(
            key=key, label=_VECTOR_LABELS[key], unit="dist", kind="vector",
            n=len(idx), mean=float(d.mean()),
            std=float(d.std(ddof=1)) if len(d) > 1 else 0.0,
            vmin=float(d.min()), vmax=float(d.max()),
            span=float(d.max() - d.min()),
            extreme_shot=(ex + 1) if ex is not None else None,
            z_classic_extreme=float(zc[ex]) if ex is not None else float("nan"),
            z_robust_extreme=float(zr[ex]) if ex is not None else float("nan"),
            stored_sigma=sigma, z_full=zr, raw_full=raw_full))
        vector_keys.append(key)

    # --- Feld (3)-Reihen ---
    ext_full_series = np.array(
        [g.ext_full if g is not None else np.nan for g in geoms])
    lat_p98_series = np.array(
        [g.lat_p98 if g is not None else np.nan for g in geoms])
    diameter_series = np.array(
        [scalar_value(f, "diameter_mm") for f in feats_list], dtype=np.float64)

    # --- Feld (1)/(2): aeusserster Shot + Ausrichtungs-Restfehler ---
    highlight, residual = _contour_outlier(geoms)

    return SheetMetrics(
        n_shots=n, n_with_image=n_img, rows=rows,
        scalar_keys=scalar_keys, vector_keys=vector_keys,
        conspicuity=conspicuity, ext_full_series=ext_full_series,
        lat_p98_series=lat_p98_series, diameter_series=diameter_series,
        highlight_shot=highlight, align_residual_mm=residual)


def _polar_signature(xy_mm: np.ndarray, k: int = 180) -> np.ndarray | None:
    """Radius r(theta) um den Schwerpunkt (=Ursprung), k Winkelbins. Aeussere
    Grenze je Bin, Luecken zirkulaer interpoliert. None bei zu duennem Profil."""
    t, nrm = xy_mm[:, 0], xy_mm[:, 1]
    theta = np.arctan2(nrm, t) % (2 * np.pi)
    r = np.hypot(t, nrm)
    bidx = np.clip((theta / (2 * np.pi) * k).astype(int), 0, k - 1)
    rr = np.full(k, np.nan)
    for b in range(k):
        sel = bidx == b
        if sel.any():
            rr[b] = r[sel].max()
    good = ~np.isnan(rr)
    if good.sum() < k // 2:
        return None
    return np.interp(np.arange(k), np.arange(k)[good], rr[good], period=k)


def _contour_outlier(geoms: list):
    """(1-basierter Index des vom Median am weitesten entfernten Shots,
    Restfehler in mm = Median der Abstaende zum Median-Kontur). (None, None)
    wenn <2 Konturen."""
    sigs = {}
    for i, g in enumerate(geoms):
        if g is None:
            continue
        s = _polar_signature(g.xy_mm)
        if s is not None:
            sigs[i] = s
    if len(sigs) < 2:
        return None, None
    idx = sorted(sigs)
    M = np.array([sigs[i] for i in idx])
    med = np.median(M, axis=0)
    dist = np.sqrt(((M - med) ** 2).mean(axis=1))
    far = idx[int(np.argmax(dist))]
    return far + 1, float(np.median(dist))


# ============================================================ Rendering
# NUR Darstellung – keine Kennzahl wird hier berechnet. Stil zentral aus
# docodetect.plotstyle: Panel-Labels ausserhalb der Achsen, duenne Achsen ohne
# top/right-spine, serifenlos; Shot-Kurven sequenziell (SEQ=viridis) nach
# Shot-Index, auffaelligster Shot in kontrastierendem Rot (OUTLIER), skalare
# z-Heatmap divergierend (DIV).


def _shot_color(i: int, n: int):
    return plt.get_cmap(SEQ)(i / max(1, n - 1))


def _shot_index_colorbar(fig, ax, n: int) -> None:
    if n < 2:
        return
    sm = ScalarMappable(norm=Normalize(1, n), cmap=plt.get_cmap(SEQ))
    cb = fig.colorbar(sm, ax=ax, fraction=0.045, pad=0.02)
    cb.set_label("Shot-Index", fontsize=7)
    cb.ax.tick_params(labelsize=6, width=0.5)
    cb.outline.set_linewidth(0.5)


def _draw_contour_band(fig, ax, geoms, highlight_shot, residual, n_total, letter):
    panel_label(ax, letter)
    present = [(i, g) for i, g in enumerate(geoms) if g is not None]
    if not present:
        ax.text(0.5, 0.5, "keine Bilder – Konturband nicht verfügbar",
                ha="center", va="center", transform=ax.transAxes, color="0.4")
        ax.set_axis_off()
        return
    hi = (highlight_shot - 1) if highlight_shot else None
    for i, g in present:
        if i == hi:
            continue
        xy = np.vstack([g.xy_mm, g.xy_mm[:1]])
        ax.plot(xy[:, 0], xy[:, 1], color=_shot_color(i, n_total),
                lw=0.7, alpha=0.85)
    if hi is not None and geoms[hi] is not None:
        xy = np.vstack([geoms[hi].xy_mm, geoms[hi].xy_mm[:1]])
        ax.plot(xy[:, 0], xy[:, 1], color=OUTLIER, lw=1.6,
                label=f"Shot {highlight_shot} (äußerster)")
        ax.legend(loc="upper right")
    ax.set_aspect("equal")
    ax.axhline(0, color="0.9", lw=0.5, zorder=0)
    ax.axvline(0, color="0.9", lw=0.5, zorder=0)
    ax.set_xlabel("entlang PCA-Hauptachse [mm]")
    ax.set_ylabel("senkrecht [mm]")
    res = f"{residual:.2f} mm" if residual is not None else "n/a"
    ax.set_title(f"Konturband · N={len(present)} · Restfehler {res}")
    _shot_index_colorbar(fig, ax, n_total)


def _draw_profiles(ax, geoms, highlight_shot, n_total, letter):
    panel_label(ax, letter)
    present = [(i, g) for i, g in enumerate(geoms) if g is not None]
    if not present:
        ax.text(0.5, 0.5, "keine Bilder – Breitenprofil nicht verfügbar",
                ha="center", va="center", transform=ax.transAxes, color="0.4")
        ax.set_axis_off()
        return
    hi = (highlight_shot - 1) if highlight_shot else None
    for i, g in present:
        if i == hi:
            continue
        ax.plot(g.s_mm, g.w_mm, color=_shot_color(i, n_total), lw=0.7, alpha=0.85)
    if hi is not None and geoms[hi] is not None:
        g = geoms[hi]
        ax.plot(g.s_mm, g.w_mm, color=OUTLIER, lw=1.6,
                label=f"Shot {highlight_shot}")
        ax.legend(loc="upper right")
    ax.axvline(0, color="0.9", lw=0.5, zorder=0)
    ax.set_xlabel("s entlang Achse [mm]  (0 = Breitenmaximum)")
    ax.set_ylabel("Breite w(s) [mm]")
    ax.set_title("Breitenprofil w(s) · Farbe = Shot-Index")


def _draw_value_over_shot(ax, m: SheetMetrics, letter):
    panel_label(ax, letter)
    x = np.arange(1, m.n_shots + 1)
    has_ext = np.isfinite(m.ext_full_series).any()
    y = m.ext_full_series if has_ext else m.diameter_series
    label = "ext_full [mm]" if has_ext else "circle_diameter_mm [mm]"
    finite = np.isfinite(y)
    ax.plot(x, y, color="0.75", lw=0.8, zorder=2)
    ax.scatter(x[finite], y[finite], c=x[finite], cmap=SEQ, vmin=1,
               vmax=m.n_shots, s=26, zorder=3, label=label)
    if finite.any():
        med = float(np.nanmedian(y))
        ax.axhline(med, color="0.35", ls="--", lw=0.9,
                   label=f"Median {med:.2f} mm")
    hi = m.highlight_shot
    if hi and finite[hi - 1]:
        ax.scatter([hi], [y[hi - 1]], s=90, facecolors="none",
                   edgecolors=OUTLIER, linewidths=1.4, zorder=4,
                   label=f"äußerster Shot {hi}")
    ax.set_xlabel("Shot-Index (Aufnahmereihenfolge)")
    ax.set_ylabel(label)
    ax.set_xticks(x)
    ax.set_title("Messwert über Shot-Nummer – Drift vs. Streuung")
    lines, labels = ax.get_legend_handles_labels()
    if np.isfinite(m.lat_p98_series).any():
        ax2 = ax.twinx()
        ax2.spines["right"].set_visible(True)
        ax2.spines["top"].set_visible(False)
        ax2.plot(x, m.lat_p98_series, "^-", color="#8c6d31", lw=0.9, ms=4,
                 label="lat_p98 [mm]")
        ax2.set_ylabel("lat_p98 [mm]", color="#8c6d31")
        ax2.tick_params(axis="y", labelcolor="#8c6d31")
        l2, la2 = ax2.get_legend_handles_labels()
        lines += l2
        labels += la2
    ax.legend(lines, labels, loc="best", ncol=2)


def _draw_table(ax, m: SheetMetrics, letter):
    panel_label(ax, letter)
    ax.set_axis_off()
    cols = ["Merkmal", "Einh.", "n", "Mittel", "Std", "Min", "Max",
            "Spannw.", "Extrem-Shot", "z_klass", "z_rob", "Ref-σ"]

    def _f(v, nd=3):
        return "–" if v is None or (isinstance(v, float) and not np.isfinite(v)) \
            else f"{v:.{nd}f}"

    lo, hi = C_SERIES_EXT_STD_MM
    ax.set_title(
        "Streuungstabelle über alle Scoring-Merkmale   "
        f"(Vergleich: σ(ext_full) sauberer C-Serie-Gruppen {lo:.2f}–{hi:.2f} mm)",
        loc="left")
    if not m.rows:                       # <3 Shots: keine Leave-one-out-Statistik
        ax.text(0.0, 0.5, "Streuungstabelle und Heatmap brauchen ≥3 Shots für "
                f"die Leave-one-out-Statistik (hier N={m.n_shots}).",
                transform=ax.transAxes, va="center", ha="left", color="0.4")
        return

    cell_text = []
    colors = []
    for r in m.rows:
        cell_text.append([
            r.label, r.unit, str(r.n), _f(r.mean), _f(r.std), _f(r.vmin),
            _f(r.vmax), _f(r.span),
            "–" if r.extreme_shot is None else str(r.extreme_shot),
            _f(r.z_classic_extreme, 2), _f(r.z_robust_extreme, 2),
            _f(r.stored_sigma)])
        # Zeile dezent hervorheben, wenn der Extrem-Shot robust auffaellig ist
        flag = np.isfinite(r.z_robust_extreme) and abs(r.z_robust_extreme) >= 3.0
        colors.append(["#fbe4e2" if flag else "white"] * len(cols))

    # bbox laesst unten Platz fuer die volle Auffaelligkeits-Zeile (die als
    # Tabellenzelle bei vielen auffaelligen Shots abschneiden wuerde).
    tab = ax.table(cellText=cell_text, colLabels=cols, cellColours=colors,
                   cellLoc="center", bbox=[0, 0.12, 1, 0.82])
    tab.auto_set_font_size(False)
    tab.set_fontsize(6.8)
    for cell in tab.get_celld().values():
        cell.set_linewidth(0.4)
        cell.set_edgecolor("0.8")
    consp = "  ".join(f"S{i+1}:{c}" for i, c in enumerate(m.conspicuity) if c)
    ax.text(0.0, 0.03,
            "Auffälligkeit je Shot (Anzahl Merkmale, bei denen Shot äußerster): "
            + (consp or "keine"), transform=ax.transAxes, fontsize=7,
            va="center", ha="left")


def _draw_heatmaps(fig, gs_slot, m: SheetMetrics, letter):
    inner = gs_slot.subgridspec(1, 3, width_ratios=[len(m.scalar_keys) + 1.4,
                                                    len(m.vector_keys) + 1.4, 2.2],
                                wspace=0.7)
    ax_s = fig.add_subplot(inner[0, 0])
    ax_v = fig.add_subplot(inner[0, 1])
    ax_c = fig.add_subplot(inner[0, 2])
    panel_label(ax_s, letter)
    row_by_key = {r.key: r for r in m.rows}
    yt = [f"S{i+1}" for i in range(m.n_shots)]
    cmap_scalar = plt.get_cmap(DIV).copy()
    cmap_scalar.set_bad("0.85")          # maskierte Zelle (kein robustes Signal)
    cmap_vector = plt.get_cmap("Reds").copy()
    cmap_vector.set_bad("0.85")

    def _matrix(keys):
        if not keys:
            return None
        return np.array([row_by_key[k].z_full for k in keys]).T  # (N, F)

    def _label_axes(ax, keys):
        ax.set_xticks(range(len(keys)))
        ax.set_xticklabels([row_by_key[k].label for k in keys],
                           rotation=45, ha="right")
        ax.set_yticks(range(m.n_shots))
        ax.set_yticklabels(yt)
        ax.tick_params(length=0)
        for s in ax.spines.values():
            s.set_visible(False)

    # Block A: Skalare, signiert, divergierend
    Zs = _matrix(m.scalar_keys)
    if Zs is not None:
        im = ax_s.imshow(np.ma.masked_invalid(np.clip(Zs, -Z_CAP, Z_CAP)),
                         cmap=cmap_scalar, vmin=-Z_CAP, vmax=Z_CAP, aspect="auto")
        _label_axes(ax_s, m.scalar_keys)
        ax_s.set_title("Skalare · z signiert", fontsize=8)
        cb = fig.colorbar(im, ax=ax_s, fraction=0.06, pad=0.03)
        cb.set_label("z (leave-one-out)", fontsize=7)
        cb.ax.tick_params(labelsize=6, width=0.5)
        cb.outline.set_linewidth(0.5)
    else:
        ax_s.set_axis_off()

    # Block B: Vektoren, einseitig (nur "weit weg" faerbt) – bewusst getrennt
    Zv = _matrix(m.vector_keys)
    if Zv is not None:
        im = ax_v.imshow(np.ma.masked_invalid(np.clip(Zv, 0.0, Z_CAP)),
                         cmap=cmap_vector, vmin=0.0, vmax=Z_CAP, aspect="auto")
        _label_axes(ax_v, m.vector_keys)
        ax_v.set_title("Vektoren · z einseitig", fontsize=8)
        cb = fig.colorbar(im, ax=ax_v, fraction=0.06, pad=0.03)
        cb.set_label("|z| (≥0)", fontsize=7)
        cb.ax.tick_params(labelsize=6, width=0.5)
        cb.outline.set_linewidth(0.5)
    else:
        ax_v.set_axis_off()

    # Auffaelligkeit je Shot als Balken (auffaellige ZEILE = schlechter Shot)
    bar_colors = [OUTLIER if (m.highlight_shot == i + 1) else "0.45"
                  for i in range(m.n_shots)]
    ax_c.barh(range(m.n_shots), m.conspicuity, color=bar_colors, height=0.7)
    ax_c.set_yticks(range(m.n_shots))
    ax_c.set_yticklabels(yt)
    ax_c.invert_yaxis()
    ax_c.tick_params(length=2)
    ax_c.set_xlabel("# Merkmale äußerster")
    ax_c.set_title("Auffälligkeit/Shot", fontsize=8)


def render_sheet(m: SheetMetrics, geoms: list, out_path: Path,
                 title: str, subnote: str = "") -> Path:
    with style_context():
        # Ohne jedes Bild entfallen Konturband + Breitenprofil GANZ (statt zwei
        # leere Panels ueber die halbe Blatthoehe): Blatt kuerzer, Panel-Labels
        # neu durchbuchstabiert (a=Messwert, b=Tabelle, c=Heatmap).
        has_img = m.n_with_image > 0
        if has_img:
            fig = plt.figure(figsize=(13.5, 19.5))
            gs = fig.add_gridspec(4, 2, height_ratios=[3.0, 2.2, 2.8, 3.2],
                                  hspace=0.5, wspace=0.24)
            _draw_contour_band(fig, fig.add_subplot(gs[0, 0]), geoms,
                               m.highlight_shot, m.align_residual_mm, m.n_shots, "a")
            _draw_profiles(fig.add_subplot(gs[0, 1]), geoms, m.highlight_shot,
                           m.n_shots, "b")
            _draw_value_over_shot(fig.add_subplot(gs[1, :]), m, "c")
            _draw_table(fig.add_subplot(gs[2, :]), m, "d")
            _draw_heatmaps(fig, gs[3, :], m, "e")
        else:
            fig = plt.figure(figsize=(13.5, 13.5))
            gs = fig.add_gridspec(3, 1, height_ratios=[2.2, 2.8, 3.2], hspace=0.5)
            _draw_value_over_shot(fig.add_subplot(gs[0, 0]), m, "a")
            _draw_table(fig.add_subplot(gs[1, 0]), m, "b")
            _draw_heatmaps(fig, gs[2, 0], m, "c")

        miss = m.n_shots - m.n_with_image
        head = f"{title}   ·   N={m.n_shots} Shots"
        if miss:
            head += f"   ·   {miss} ohne Bild"
        fig.suptitle(head, fontsize=12, y=0.996, fontweight="bold")
        zdef = ("z_klass=(x−mean_{j≠i})/std, z_rob=(x−median)/(1.4826·MAD) "
                "leave-one-out; Vektor-z über die Distanzmenge (0=Normalfall).")
        # Der Registrierungs-Vorbehalt gilt nur den Kontur-Feldern – ohne Bild
        # weglassen.
        contour_note = (
            "Kein Messinstrument: die starre Schwerpunkt-/PCA-Registrierung hat "
            "laut C4 einen Boden von 2–9 mm – das Blatt zeigt die Bandbreite, "
            "nicht lokalisierte Differenzen.  Skala Kontur-Felder: Bodenebene "
            "wie C-Serie, kein Höhenausgleich.  ") if has_img else ""
        caption = contour_note + zdef
        if subnote:
            caption = subnote + "  " + caption
        fig.text(0.5, 0.005, caption, ha="center", va="bottom", fontsize=7,
                 wrap=True, color="0.3")

        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out_path, dpi=220, bbox_inches="tight")
        plt.close(fig)
    return out_path


# ============================================================ Orchestrierung

def _load_image(src, cfg) -> np.ndarray | None:
    """src = np.ndarray (Qt-Frame) ODER Pfad-String (image_path) ODER None."""
    if src is None:
        return None
    if isinstance(src, np.ndarray):
        return src
    p = Path(src)
    if not p.is_absolute():
        p = resolve(src)
    if not p.exists():
        return None
    img = cv2.imread(str(p))
    return img


def _geometry_for(pipe: Pipeline, image: np.ndarray | None,
                  mmpp: float) -> ShotGeom | None:
    if image is None:
        return None
    try:
        seg, _ = pipe.analyze(image)
    except SegmentationError:
        return None
    if seg.contour is None:
        return None
    return _shot_geometry(seg.contour, mmpp)


def build_enrollment_sheet(cfg: dict, article_number: str | None = None,
                           shots: list | None = None,
                           out: str | Path | None = None) -> Path:
    """Diagnoseblatt eines Artikels erzeugen und als PNG schreiben.

    Zwei Aufrufwege ueber DIESELBE Logik:
      - CLI / nachtraeglich: article_number gesetzt, shots=None -> die
        gespeicherten Referenzen werden aus der DB geladen (image_path noetig
        fuer Felder 1-3).
      - Qt pre-commit (STUFE 4): shots=[(bild_oder_pfad_oder_None, Features), ...]
        in Aufnahmereihenfolge – NUR die Shots dieser Session, noch nicht in der
        DB. article_number optional (Titel + Vergleich zur bisherigen
        Referenzstreuung des Artikels).

    Gibt den Pfad des geschriebenen PNG zurueck. Raises ValueError, wenn weder
    shots noch (article_number mit Referenzen) vorliegen.
    """
    pipe = Pipeline(cfg)
    try:
        mmpp = float(pipe.cal.mm_per_px)
        if shots is None:
            if not article_number:
                raise ValueError("article_number oder shots erforderlich.")
            meta = pipe.db.references_with_meta(article_number)
            if not meta:
                raise ValueError(
                    f"Artikel '{article_number}' hat keine Referenzen.")
            sources = [ip for ip, _ in meta]
            feats_list = [f for _, f in meta]
        else:
            if not shots:
                raise ValueError("shots ist leer.")
            sources = [s for s, _ in shots]
            feats_list = [f for _, f in shots]

        geoms = [_geometry_for(pipe, _load_image(src, cfg), mmpp)
                 for src in sources]

        stored_stats = None
        subnote = ""
        if article_number:
            stored_stats = pipe.db.stats_for(article_number)
            if shots is not None and stored_stats is not None:
                subnote = (f"Vergleichsspalte Ref-σ = bisherige "
                           f"Referenzstreuung von {article_number} "
                           f"({stored_stats.n_shots} Shots).")

        metrics = compute_sheet_metrics(feats_list, geoms, stored_stats)
    finally:
        pipe.close()

    title = f"Enrollment-Diagnoseblatt · {article_number or 'Session'}"
    if out is None:
        # Neben die uebrigen Analyse-Artefakte, damit sie dieselbe Ablage/
        # Archivierung erben (nicht mehr nach ~/Documents/tmp).
        base = cfg.get("analysis", {}).get("output_dir", "reports/analysis")
        out = resolve(base) / "enrollment" / f"{article_number or 'session'}.png"
    return render_sheet(metrics, geoms, Path(out), title, subnote)
