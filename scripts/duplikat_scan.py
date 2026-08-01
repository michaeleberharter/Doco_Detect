"""Duplikat-Scan über einen eingelernten Bestand — Profildistanz d/sigma.

**Rein lesend.** Das Skript öffnet die DB nur für SELECTs (kein `init_schema`,
kein `add_*`, kein `commit`), rechnet auf den gespeicherten Referenz-PNGs und
gibt ausschliesslich einen Befund aus. Es ändert weder DB noch Config noch
Referenzen noch Baseline. Ohne `--csv` schreibt es überhaupt keine Datei.

Warum es das gibt: am 2026-08-01 waren drei von fünfzehn „Artikeln" dasselbe
Besteckteil (MESSER-2/-5/-6), und das fiel erst auf, nachdem drei Analysen
darauf aufgebaut hatten. Die Prüfung gehört nach dem Einlernen und VOR die
erste Auswertung — Methode und Schwelle:
docs/2026-08-01-duplikatpruefung-methode.md.

Verfahren (1:1 die dort beschriebene Methode):

    w(s)      Breitenprofil je Shot, längennormiert auf u = s/L,
              101 Stützstellen
    Prototyp  Mittel der Shot-Profile eines Artikels
    d(A,B)    RMS über u von |w_A(u) − w_B(u)|                      [mm]
    sigma(A)  RMS über die Shots von d(w_i, Prototyp_A)             [mm]
    d/sigma   d(A,B) / sqrt((sigma(A)² + sigma(B)²) / 2)

Die Kennzahl ist **d/sigma, nicht d**: ein absoluter Abstand sagt nichts,
solange man die eigene Messstreuung nicht kennt. `d/sigma < 1` heisst wörtlich,
dass zwei Artikel näher beieinanderliegen als zwei Aufnahmen desselben
Artikels.

**Die Lücke zählt mehr als die Schwelle.** Genau daran ist der erste Durchgang
am 2026-08-01 gescheitert: mit d/sigma <= 1,0 als Verdachtsgrenze wurde nur
eines von drei Duplikatpaaren gemeldet, obwohl die sortierte Liste drei Paare
unter 1,6 und dann nichts bis 2,18 zeigte. Deshalb gibt dieses Skript IMMER
den unteren Rand der sortierten Liste aus (nicht nur, was unter der Schwelle
liegt), markiert die grösste Lücke darin und sagt ausdrücklich, wenn Lücke und
Schwelle auseinanderfallen.

Keine Messlogik dupliziert: Segmentierung und Kontur-Geometrie kommen über
`Pipeline.analyze` und `enrollment_sheet._shot_geometry` — dasselbe Muster, mit
dem `enrollment_sheet.py` aus `features.py` importiert.

**Bekannte Grenze — die Längen-Normierung blendet die Länge aus.** Zwei
formgleiche Artikel verschiedener Länge (ein Löffel und sein größerer Bruder)
haben nach der Normierung auf u = s/L ein sehr ähnliches Profil und können als
Paar mit kleinem d/sigma auftauchen, ohne Duplikate zu sein. Deshalb steht in
der Ausgabe zu jedem auffälligen Paar die mittlere Länge beider Artikel: weicht
sie deutlich ab, ist es kein Duplikat, sondern eine Formfamilie. Die Länge ist
im Scoring ohnehin das schwerste Merkmal — dieser Scan misst bewusst das, was
die Länge NICHT sieht.

**Verifiziert am 2026-08-01** gegen den Bestand `neuenroll-2026-08` (40
Artikel, 220 Referenzbilder, 780 Paare, 1007 s):

- **3 von 3 bekannten Duplikaten gefunden** — MESSER-2/-5/-6 auf den Rängen
  1-3 (d/sigma 0,92 · 1,21 · 1,55), als ein Cluster zusammengefasst, mit einem
  Sprung von ×1,46 zum nächsten Paar.
- **Positivkontrolle bestanden:** MESSER-5/MESSER-7 — das enge, aber echte
  Nachbarpaar — liegt bei **12,68 sigma auf Rang 272 von 780**, wird also
  nicht mitgezogen. Ein Detektor, der nur unten etwas findet, wäre damit noch
  nicht belegt; erst beide Enden zusammen sind es.
- Die Distanzen reproduzieren die Werte der ursprünglichen Ad-hoc-Rechnung auf
  zwei Nachkommastellen (0,25 · 0,38 · 0,48 mm).

Aufruf:
    .venv/bin/python scripts/duplikat_scan.py --sandbox neuenroll-2026-08

Kosten: die Segmentierung läuft je Referenzbild neu (~3-5 s je 4K-Bild), für
40 Artikel mit ~220 Aufnahmen also etwa eine Viertelstunde. Keine Kamera nötig.

Exit-Codes (das Skript ändert nie etwas, der Code ist selbst ein Befund):
    0   gelaufen, kein Verdacht
    3   gelaufen, Verdachtsfälle vorhanden -> physisch prüfen
    1   NICHT fahrbar (z. B. keine Referenzbilder) oder Abbruch
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.config import load_config, sandbox_cfg  # noqa: E402
from docodetect.enrollment_sheet import _geometry_for, _load_image  # noqa: E402
from docodetect.pipeline import Pipeline  # noqa: E402

# Verdachtsschwelle aus docs/2026-08-01-duplikatpruefung-methode.md. Bewusst
# grosszuegig: ein Falschalarm kostet einen Blick auf den Gegenstand, ein
# uebersehenes Duplikat mehrere Analysen.
SCHWELLE_DEFAULT = 2.0

# Stuetzstellen des laengennormierten Profils (u = s/L).
N_GITTER = 101

# So viele Paare vom unteren Rand werden IMMER gezeigt, damit die Luecke
# sichtbar ist und nicht an der Schwelle abgeschnitten wird.
N_RAND_DEFAULT = 15


# ------------------------------------------------------------------ Profile

def profil_normiert(geom, n: int = N_GITTER) -> np.ndarray | None:
    """Breitenprofil eines Shots auf u = s/L, n Stuetzstellen.

    Laengen-Normierung statt Ausrichtung am Breitenmaximum: der argmax sitzt
    bei Besteck auf einem bis zu 30 mm breiten Plateau und zittert deshalb um
    mehrere Millimeter (w(s)-Negativbefund, Abschnitt 5c). u = s/L war dort die
    stabilste der geprueften Ausrichtungen (0,404 gegen 0,500 mm RMS).
    """
    if geom is None:
        return None
    s = np.asarray(geom.s_mm, dtype=float)
    w = np.asarray(geom.w_mm, dtype=float)
    if len(s) < 5 or not np.isfinite(w).all():
        return None
    spann = float(s.max() - s.min())
    if spann <= 0:
        return None
    u = (s - s.min()) / spann
    return np.interp(np.linspace(0.0, 1.0, n), u, w)


def rms_differenz(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.sqrt(np.mean((a - b) ** 2)))


def artikel_profil(profile: list) -> tuple[np.ndarray, float | None]:
    """-> (Prototyp, sigma). sigma = None bei < 2 verwertbaren Shots."""
    stapel = np.vstack(profile)
    prototyp = stapel.mean(axis=0)
    if len(profile) < 2:
        return prototyp, None
    abstaende = [rms_differenz(p, prototyp) for p in profile]
    sigma = float(np.sqrt(np.mean(np.square(abstaende))))
    return prototyp, sigma


# ------------------------------------------------------------------ Bestand

def sammle_bestand(cfg: dict, nur: set | None, fortschritt: bool):
    """-> (daten, hinweise). daten = {artikel: {...}}, hinweise = Klartext-Liste.

    Liest ausschliesslich; `Pipeline` oeffnet die DB ueber `Database(cfg)`,
    das nur `sqlite3.connect` macht — `init_schema` wird NICHT gerufen.
    """
    pipe = Pipeline(cfg)
    hinweise: list[str] = []
    daten: dict = {}
    try:
        mmpp = float(pipe.cal.mm_per_px)
        artikel = pipe.db.articles_with_references()
        if nur:
            artikel = [a for a in artikel if a in nur]
        for i, nr in enumerate(sorted(artikel), 1):
            meta = pipe.db.references_with_meta(nr)
            mit_pfad = [ip for ip, _ in meta if ip]
            profile, laengen = [], []
            fehlend_bild = 0
            fehlend_seg = 0
            for ip in mit_pfad:
                bild = _load_image(ip, cfg)
                if bild is None:
                    fehlend_bild += 1
                    continue
                g = _geometry_for(pipe, bild, mmpp)
                p = profil_normiert(g)
                if p is None:
                    fehlend_seg += 1
                    continue
                profile.append(p)
                laengen.append(float(g.ext_full))
            daten[nr] = {
                "n_referenzen": len(meta),
                "n_mit_pfad": len(mit_pfad),
                "n_profile": len(profile),
                "fehlend_bild": fehlend_bild,
                "fehlend_seg": fehlend_seg,
                "profile": profile,
                "laenge_mm": (float(np.mean(laengen)) if laengen else None),
            }
            if fortschritt:
                print(f"  [{i:>3}/{len(artikel)}] {nr:<14} "
                      f"{len(profile)}/{len(meta)} Shots verwertbar",
                      flush=True)
    finally:
        pipe.close()

    ohne_pfad = [nr for nr, d in daten.items() if d["n_mit_pfad"] == 0]
    if ohne_pfad:
        hinweise.append(
            f"{len(ohne_pfad)} Artikel ohne ein einziges gesetztes "
            f"reference_features.image_path: {', '.join(sorted(ohne_pfad))}")
    return daten, hinweise


def pruefe_fahrbarkeit(daten: dict, hinweise: list) -> str | None:
    """Klartext-Begruendung, wenn der Scan NICHT fahrbar ist — sonst None.

    Ein leeres Ergebnis waere hier die gefaehrlichste Ausgabe: es liest sich
    wie „keine Duplikate gefunden". Der Altbestand der Produktiv-DB hat 334 von
    359 reference_features-Zeilen ohne image_path — dort ist der Scan
    schlicht nicht durchfuehrbar, und das muss als Befund erscheinen.
    """
    gesamt_ref = sum(d["n_referenzen"] for d in daten.values())
    gesamt_pfad = sum(d["n_mit_pfad"] for d in daten.values())
    brauchbar = [nr for nr, d in daten.items() if d["n_profile"] >= 1]

    if not daten:
        return ("Kein Artikel mit Referenzen im Bestand. Es gibt nichts zu "
                "vergleichen.")
    if gesamt_pfad == 0:
        return (
            f"KEIN einziges Referenzbild vorhanden: alle {gesamt_ref} "
            f"reference_features-Zeilen haben image_path = NULL.\n"
            "Der Scan braucht die gespeicherten Referenz-PNGs — aus "
            "features_json allein ist kein Breitenprofil rekonstruierbar.\n"
            "Das ist der Zustand des Altbestands (eingelernt vor der "
            "PNG-Persistenz vom 2026-07-28). Für diesen Bestand ist die "
            "Duplikatprüfung erst nach einem Neu-Enrollment fahrbar.")
    if len(brauchbar) < 2:
        return (
            f"Nur {len(brauchbar)} Artikel mit verwertbarem Profil — für "
            "einen Paarvergleich sind mindestens zwei nötig.\n"
            f"Referenzen gesamt: {gesamt_ref}, davon mit image_path: "
            f"{gesamt_pfad}." + ("\n" + "\n".join(hinweise) if hinweise else ""))
    return None


# ------------------------------------------------------------------ Paare

def paarliste(daten: dict):
    """-> (paare, sigma_gepoolt, geschaetzt). paare sortiert nach d/sigma."""
    artikel = sorted(nr for nr, d in daten.items() if d["n_profile"] >= 1)
    proto, sigma = {}, {}
    for nr in artikel:
        proto[nr], sigma[nr] = artikel_profil(daten[nr]["profile"])

    echte = [s for s in sigma.values() if s is not None]
    sigma_gepoolt = float(np.sqrt(np.mean(np.square(echte)))) if echte else None

    geschaetzt = sorted(nr for nr in artikel if sigma[nr] is None)
    for nr in geschaetzt:
        sigma[nr] = sigma_gepoolt

    paare = []
    for i, a in enumerate(artikel):
        for b in artikel[i + 1:]:
            if sigma[a] is None or sigma[b] is None:
                continue
            d = rms_differenz(proto[a], proto[b])
            seff = float(np.sqrt((sigma[a] ** 2 + sigma[b] ** 2) / 2.0))
            if seff <= 0:
                continue
            la, lb = daten[a].get("laenge_mm"), daten[b].get("laenge_mm")
            paare.append({
                "a": a, "b": b, "d": d, "d_sigma": d / seff,
                "geschaetzt": (a in geschaetzt) or (b in geschaetzt),
                "laenge_a": la, "laenge_b": lb,
                "d_laenge": (abs(la - lb) if la is not None and lb is not None
                             else None),
            })
    paare.sort(key=lambda p: p["d_sigma"])
    return paare, sigma_gepoolt, geschaetzt


def luecken_kandidaten(paare: list, bis: int, k: int = 3) -> list:
    """Die k groessten Spruenge im unteren Rand, absteigend nach Faktor.

    -> [{"i", "faktor", "unten", "oben", "n_darunter", "anteil"}, ...]

    **Bewusst mehrere Kandidaten statt einer Antwort.** Der groesste Faktor
    allein trifft die richtige Luecke nicht zuverlaessig: auf der dokumentierten
    Verteilung vom 2026-08-01 (0,92 · 1,20 · 1,53 — Luecke — 2,18 · 2,26 · 2,28
    · 3,36) ist der Sprung 2,28 -> 3,36 mit 1,47 rechnerisch groesser als der
    echte Sprung 1,53 -> 2,18 mit 1,42. Ein Skript, das hier automatisch
    entscheidet, entscheidet falsch — und wiederholt damit genau den Fehler,
    den es verhindern soll.

    Was die Kandidaten unterscheidbar macht, ist `n_darunter`: unterhalb der
    echten Luecke liegen 3 von 780 Paaren, unterhalb eines Tail-Sprungs
    hunderte. Diese Zahl steht deshalb in der Ausgabe — die Trennlinie zieht
    der Mensch, nicht das Skript.
    """
    rand = paare[:max(bis, 2)]
    kandidaten = []
    for i in range(len(rand) - 1):
        v, w = rand[i]["d_sigma"], rand[i + 1]["d_sigma"]
        if v <= 0:
            continue
        kandidaten.append({
            "i": i, "faktor": w / v, "unten": v, "oben": w,
            "n_darunter": i + 1,
            "anteil": (i + 1) / len(paare) if paare else 0.0,
        })
    kandidaten.sort(key=lambda c: c["faktor"], reverse=True)
    return kandidaten[:k]


def cluster(paare: list, schwelle: float) -> list:
    """Transitive Huelle ueber die auffaelligen Paare.

    Duplikate treten in Clustern auf: sind A/B und B/C auffaellig, ist A/C es
    auch. Drei auffaellige Paare bedeuten drei Exemplare DESSELBEN Artikels,
    nicht drei aehnliche Artikel — genau die Fehldeutung vom 2026-08-01.
    """
    eltern: dict = {}

    def wurzel(x):
        eltern.setdefault(x, x)
        while eltern[x] != x:
            eltern[x] = eltern[eltern[x]]
            x = eltern[x]
        return x

    for p in paare:
        if p["d_sigma"] >= schwelle:
            break
        ra, rb = wurzel(p["a"]), wurzel(p["b"])
        if ra != rb:
            eltern[ra] = rb
    gruppen: dict = {}
    for x in eltern:
        gruppen.setdefault(wurzel(x), []).append(x)
    return [sorted(g) for g in gruppen.values() if len(g) > 1]


# ------------------------------------------------------------------ Ausgabe

def _laengen(p: dict) -> str:
    """' · Länge 214,2 / 213,6 mm (Δ 0,6)' — macht Formfamilien erkennbar."""
    la, lb = p.get("laenge_a"), p.get("laenge_b")
    if la is None or lb is None:
        return ""
    return f" · Länge {la:.1f} / {lb:.1f} mm (Δ {abs(la - lb):.1f})"


def zahlenstrahl(paare: list, schwelle: float, breite: int = 62) -> list:
    """ASCII-Zahlenstrahl der d/sigma-Werte — macht Bimodalität sichtbar."""
    if not paare:
        return []
    obergrenze = max(schwelle * 2.0, paare[min(len(paare), 30) - 1]["d_sigma"])
    if obergrenze <= 0:
        return []
    zeile = [" "] * breite
    for p in paare:
        if p["d_sigma"] > obergrenze:
            break
        i = min(breite - 1, int(p["d_sigma"] / obergrenze * (breite - 1)))
        zeile[i] = "#" if zeile[i] in (" ", ".") else "#"
    i_s = min(breite - 1, int(schwelle / obergrenze * (breite - 1)))
    marke = [" "] * breite
    marke[i_s] = "^"
    return [
        "  " + "".join(zeile),
        "  " + "".join(marke) + f"  Schwelle {schwelle:.2f}",
        f"  0{' ' * (breite - 12)}d/sigma {obergrenze:.2f}",
    ]


def bericht(paare, daten, schwelle, n_rand, sigma_gepoolt, geschaetzt,
            hinweise, gefiltert):
    verdacht = [p for p in paare if p["d_sigma"] < schwelle]
    n_art = len([nr for nr, d in daten.items() if d["n_profile"] >= 1])
    n_shots = sum(d["n_profile"] for d in daten.values())

    print()
    print("=" * 74)
    print("DUPLIKAT-SCAN — Befund (nichts geändert, nichts geschrieben)")
    print("=" * 74)
    if gefiltert:
        print("\n!! TEIL-LAUF (--artikel gesetzt) — das ist KEIN vollständiger")
        print("   Duplikat-Scan. Duplikate treten paarweise auf; ein gefilterter")
        print("   Lauf kann den Partner ausserhalb des Filters nicht sehen.")
    print(f"\nArtikel mit Profil: {n_art} · verwertbare Shots: {n_shots} · "
          f"Paare: {len(paare)}")
    if geschaetzt:
        print(f"sigma geschätzt (< 2 Shots, gepoolt {sigma_gepoolt:.3f} mm): "
              f"{', '.join(geschaetzt)}")
        print("  -> für diese Artikel ist der Test schwächer, ihr eigenes "
              "sigma ist unbekannt.")
    for h in hinweise:
        print(f"Hinweis: {h}")

    unvollstaendig = [(nr, d) for nr, d in sorted(daten.items())
                      if d["fehlend_bild"] or d["fehlend_seg"]]
    if unvollstaendig:
        print("\nNicht verwertete Aufnahmen:")
        for nr, d in unvollstaendig:
            teile = []
            if d["fehlend_bild"]:
                teile.append(f"{d['fehlend_bild']}× Bild fehlt")
            if d["fehlend_seg"]:
                teile.append(f"{d['fehlend_seg']}× Segmentierung/Kontur")
            print(f"  {nr:<14} {', '.join(teile)}")

    print(f"\n{'-' * 74}")
    print(f"UNTERER RAND der sortierten Liste ({min(n_rand, len(paare))} von "
          f"{len(paare)} Paaren)")
    print("Die Lücke lesen, nicht nur die Schwelle — deshalb steht hier auch,")
    print("was oberhalb der Schwelle liegt.")
    print("-" * 74)
    # Luecken werden ueber ein WEITERES Fenster gesucht als die Tabelle zeigt:
    # ein zu kleines --rand darf die Trennlinie nicht unsichtbar machen.
    kandidaten = luecken_kandidaten(paare, max(n_rand, 25))
    markiert = {c["i"]: r for r, c in enumerate(kandidaten, 1)
                if c["i"] < n_rand}
    print(f"{'Rang':>4}  {'Paar':<30} {'d [mm]':>8} {'d/sigma':>8} "
          f"{'Δ zum vorigen':>14}")
    vorher = None
    for i, p in enumerate(paare[:n_rand]):
        delta = "" if vorher is None else f"×{p['d_sigma'] / vorher:.2f}"
        stern = " *" if p["geschaetzt"] else "  "
        print(f"{i + 1:>4}  {p['a'] + ' / ' + p['b']:<30} {p['d']:>8.2f} "
              f"{p['d_sigma']:>8.2f}{stern}{delta:>12}")
        vorher = p["d_sigma"]
        if i in markiert:
            c = kandidaten[markiert[i] - 1]
            n = c["n_darunter"]
            print(f"      {'':-<26} LÜCKE {markiert[i]}  ×{c['faktor']:.2f}  "
                  f"({n} Paar{'e' if n != 1 else ''} darunter) {'':-<8}")
    if geschaetzt:
        print("  * = mindestens ein Artikel des Paares hat ein geschätztes sigma")

    for zeile in zahlenstrahl(paare, schwelle):
        print(zeile)

    print(f"\n{'-' * 74}")
    print("BEFUND")
    print("-" * 74)
    if kandidaten:
        print("Kandidaten für die Trennlinie (grösste Sprünge im unteren "
              "Rand) — die Wahl trifft der Mensch:")
        for r, c in enumerate(kandidaten, 1):
            ausserhalb = ("  (unterhalb der Tabelle)"
                          if c["i"] >= n_rand else "")
            print(f"  {r}. nach Rang {c['n_darunter']:>2}: "
                  f"{c['unten']:.2f} -> {c['oben']:.2f}  (Faktor "
                  f"{c['faktor']:.2f}) · darunter {c['n_darunter']} von "
                  f"{len(paare)} Paaren ({c['anteil'] * 100:.1f} %)"
                  f"{ausserhalb}")
        print("  Ein Sprung mit WENIGEN Paaren darunter trennt „dasselbe "
              "Objekt“ von „verschiedene Objekte“;")
        print("  ein Sprung mit vielen Paaren darunter ist die dünne "
              "Besetzung des Verteilungsschwanzes.")

    # Fällt die Schwelle mitten in eine Gruppe, die ein Sprung nach OBEN
    # abschliesst, dann meldet die Schwelle zu wenig — der Fehler vom
    # 2026-08-01. Massgeblich ist die kleinste solche Gruppe, nicht der
    # groesste Faktor.
    # Nur diese eine Richtung wird gemeldet. Ein Sprung UNTERHALB der Schwelle
    # ist harmlos: dort wird ohnehin physisch geprueft, und die Methode nimmt
    # Falschalarme bewusst in Kauf („kostet einen Blick auf den Gegenstand").
    # Eine Meldung „die Schwelle ist zu weit" koennte jemanden von einer
    # Pruefung abbringen — genau die falsche Richtung.
    zu_eng = sorted((c for c in kandidaten
                     if c["unten"] >= schwelle
                     and c["n_darunter"] > len(verdacht)),
                    key=lambda c: c["n_darunter"])
    nachtrag: list[str] = []
    if zu_eng:
        c = zu_eng[0]
        extra = [p for p in paare[:c["n_darunter"]] if p["d_sigma"] >= schwelle]
        nachtrag.append(
            f"Die Schwelle {schwelle:.2f} schneidet unterhalb eines Sprungs: "
            f"nach Rang {c['n_darunter']} springt d/sigma von "
            f"{c['unten']:.2f} auf {c['oben']:.2f} (×{c['faktor']:.2f}).")
        nachtrag.append(
            f"  Nach der Methode gehören die {len(extra)} Paare zwischen "
            "Schwelle und Sprung mit angesehen — am 2026-08-01 wurden")
        nachtrag.append(
            "  genau so zwei von drei Duplikaten übersehen "
            "(d/sigma 1,20 und 1,53 bei Schwelle 1,0):")
        for p in extra:
            nachtrag.append(f"    {p['a']:<14} / {p['b']:<14} "
                            f"d/sigma = {p['d_sigma']:.2f}{_laengen(p)}")
    if not verdacht:
        print(f"\nKein Paar unter d/sigma = {schwelle:.2f}. Kein "
              "Duplikatverdacht aus der Schwelle.")
        if nachtrag:
            print()
            for z in nachtrag:
                print(z)
            return 3
        if kandidaten:
            print("Die Sprünge oben trotzdem ansehen — die Lücke ist das "
                  "stärkere Signal als die Schwelle.")
        return 0

    print(f"\n{len(verdacht)} Paar(e) unter d/sigma = {schwelle:.2f} — "
          "PHYSISCH PRÜFEN:")
    for p in verdacht:
        print(f"  {p['a']:<14} / {p['b']:<14} d = {p['d']:.2f} mm · "
              f"d/sigma = {p['d_sigma']:.2f}{_laengen(p)}")
    if any(p.get("d_laenge") is not None and p["d_laenge"] > 3.0
           for p in verdacht):
        print("  ! Paare mit deutlich verschiedener Länge sind eher eine "
              "Formfamilie als ein Duplikat —")
        print("    die Normierung auf u = s/L blendet die Länge aus "
              "(siehe Modul-Docstring).")
    gruppen = cluster(paare, schwelle)
    if any(len(g) > 2 for g in gruppen):
        print("\nCluster (transitive Hülle) — mehrere Einträge desselben "
              "Gegenstands:")
        for g in gruppen:
            if len(g) > 2:
                print(f"  {' = '.join(g)}   ({len(g)} Einträge, "
                      "vermutlich EIN Objekt)")
    if nachtrag:
        print()
        for z in nachtrag:
            print(z)
    print("\nNächster Schritt: die Gegenstände nebeneinanderlegen und "
          "vergleichen — nicht die Zahlen weiter deuten.")
    print("Bestätigt sich ein Duplikat: Eintrag entfernen und die Auswertung "
          "neu rechnen,")
    print("nicht umetikettieren (docs/2026-08-01-duplikatpruefung-methode.md).")
    return 3


def schreibe_csv(pfad: Path, paare: list) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    with open(pfad, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["artikel_a", "artikel_b", "d_mm", "d_sigma",
                    "sigma_geschaetzt"])
        for p in paare:
            w.writerow([p["a"], p["b"], f"{p['d']:.4f}",
                        f"{p['d_sigma']:.4f}", int(p["geschaetzt"])])
    print(f"\nAlle {len(paare)} Paare geschrieben nach {pfad}")


# ------------------------------------------------------------------ main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Duplikat-Scan über die Breitenprofile eines Bestands. "
                    "Rein lesend, gibt nur einen Befund aus.",
        epilog="Exit: 0 = kein Verdacht · 3 = Verdacht (physisch prüfen) · "
               "1 = nicht fahrbar.")
    ap.add_argument("--sandbox", metavar="NAME",
                    help="Bestand unter data/sandbox/NAME/ statt Produktiv-DB")
    ap.add_argument("--schwelle", type=float, default=SCHWELLE_DEFAULT,
                    help=f"Verdachtsschwelle d/sigma (Default "
                         f"{SCHWELLE_DEFAULT}; die Lücke zählt mehr)")
    ap.add_argument("--rand", type=int, default=N_RAND_DEFAULT,
                    help=f"wie viele Paare vom unteren Rand gezeigt werden "
                         f"(Default {N_RAND_DEFAULT})")
    ap.add_argument("--artikel", metavar="A,B,C",
                    help="nur diese Artikelnummern (TEIL-LAUF, keine Freigabe)")
    ap.add_argument("--csv", metavar="PFAD", type=Path,
                    help="alle Paare zusätzlich als CSV (sonst wird keine "
                         "Datei geschrieben)")
    ap.add_argument("--still", action="store_true",
                    help="keine Fortschrittszeilen je Artikel")
    args = ap.parse_args(argv)

    cfg = load_config()
    if args.sandbox:
        cfg = sandbox_cfg(cfg, args.sandbox)
    nur = ({a.strip() for a in args.artikel.split(",") if a.strip()}
           if args.artikel else None)

    print("Duplikat-Scan — Segmentierung je Referenzbild, das dauert "
          "(~3-5 s je 4K-Bild).")
    t0 = time.time()
    daten, hinweise = sammle_bestand(cfg, nur, fortschritt=not args.still)

    grund = pruefe_fahrbarkeit(daten, hinweise)
    if grund:
        print("\n" + "=" * 74)
        print("SCAN NICHT FAHRBAR")
        print("=" * 74)
        print(grund)
        print("\nDas ist ein Befund, kein leeres Ergebnis: der Bestand ist "
              "NICHT auf Duplikate geprüft.")
        return 1

    paare, sigma_gepoolt, geschaetzt = paarliste(daten)
    code = bericht(paare, daten, args.schwelle, args.rand, sigma_gepoolt,
                   geschaetzt, hinweise, gefiltert=bool(nur))
    if args.csv:
        schreibe_csv(args.csv, paare)
    print(f"\nLaufzeit {time.time() - t0:.0f} s.")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
