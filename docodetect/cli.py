"""Command-line interface.

    python -m docodetect.cli init-db
    python -m docodetect.cli import-articles data/articles_example.csv
    python -m docodetect.cli list-articles
    python -m docodetect.cli capture-background
    python -m docodetect.cli calibrate [--image foto.jpg]
    python -m docodetect.cli create-article "Suppenloeffel" [--height-mm 0]
    python -m docodetect.cli delete-article ART-NR
    python -m docodetect.cli delete-references ART-NR
    python -m docodetect.cli enroll ART-NR --shots 8 [--images dir/]
    python -m docodetect.cli identify [--image foto.jpg]
    python -m docodetect.cli evaluate data/testset/
    python -m docodetect.cli sync-stammdaten [--apply]

`evaluate` expects a folder layout of  testset/<article_number>/*.jpg
and prints per-class accuracy + the confusion pairs (that output decides
whether stage 2 is needed at all).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .calibration import run_calibration, save_background
from .camera import BoxCamera, load_image
from .config import (load_config, resolve, sandbox_cfg,
                     sandbox_verzeichnisse_anlegen)
from .database import Database
from .pipeline import Pipeline
from .segmentation import SegmentationError


def _get_image(args, cfg):
    if getattr(args, "image", None):
        return load_image(args.image)
    with BoxCamera(cfg) as cam:
        return cam.capture()


def cmd_init_db(args, cfg):
    Database(cfg).init_schema()


def cmd_import_articles(args, cfg):
    db = Database(cfg)
    db.init_schema()
    db.import_articles_csv(args.csv)


def cmd_capture_background(args, cfg):
    img = _get_image(args, cfg)
    save_background(img, cfg)


def cmd_calibrate(args, cfg):
    img = _get_image(args, cfg)
    run_calibration(img, cfg)


def _create_one(pipe, cfg, img, name, *, article_number=None, height_mm=0.0,
                category=None, store_photo=True):
    """Kern von `create-article`: EINEN Artikel aus EINEM Bild anlegen und das
    Foto (nur bei Live-Aufnahmen) als Referenz ablegen.

    Wirft SegmentationError / KeyError weiter, statt das Programm zu beenden –
    `create-article` bricht damit ab, `batch-create` bietet stattdessen an, die
    Aufnahme zu wiederholen."""
    import cv2

    prefix = cfg.get("create", {}).get("article_number_prefix", "")
    number = article_number or pipe.db.generate_article_number(name, prefix)
    # Foto erst NACH dem Anlegen schreiben, damit ein Fehlschlag kein
    # verwaistes png hinterlässt (womöglich im Ordner eines anderen Artikels).
    # Verlustloses PNG: Shots sollen kuenftige Kantenanalysen tragen.
    img_path = None
    if store_photo:
        ref_dir = resolve(cfg["paths"]["reference_dir"]) / number
        img_path = str(ref_dir / f"{int(time.time() * 1000)}.png")

    article, feats, _ = pipe.create_article(
        img, name, article_number=number, height_mm=height_mm,
        category=category, image_path=img_path)

    if img_path:
        Path(img_path).parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(img_path, img)
    return article, feats


def _format_geometrie(article) -> str:
    """Die Maße eines Artikels als eine Zeile: Ø bei runden Teilen, sonst
    Breite × Tiefe (beides die Seiten des minAreaRect). '—', wenn gar keine
    Maße hinterlegt sind – möglich bei CSV-Import ohne Geometriespalten,
    wo die frühere Fassung dieser Zeile an None gescheitert wäre.

    Ohne Höhe: `create-article` hat sie noch nie ausgegeben, und diese
    Ausgabe soll sich durch das Herausziehen der Zeile nicht ändern.
    `list-articles` hängt sie selbst an."""
    if article.diameter_mm:
        return f"Ø {article.diameter_mm:.1f} mm"
    if article.width_mm and article.depth_mm:
        return f"{article.width_mm:.1f} × {article.depth_mm:.1f} mm"
    return "—"


def _format_created(article) -> str:
    return (f"'{article.name}' angelegt als {article.article_number}  "
            f"({_format_geometrie(article)}, Farbe: {article.color_desc})")


def cmd_create_article(args, cfg):
    """Create a new article live: object under the camera, pass a name, done."""
    Database(cfg).init_schema()
    pipe = Pipeline(cfg)
    try:
        img = _get_image(args, cfg)
        try:
            article, _ = _create_one(
                pipe, cfg, img, args.name, article_number=args.article_number,
                height_mm=args.height_mm, category=args.category,
                store_photo=not getattr(args, "image", None))
        except (SegmentationError, KeyError) as e:
            sys.exit(f"[create] {e}")
        print(f"[create] {_format_created(article)}.")
        print("[create] 1 Referenzfoto gespeichert – Artikel ist sofort erkennbar.")
    finally:
        pipe.close()


_BATCH_KEYS = "Enter = Aufnahme · r = letzte verwerfen und wiederholen · q = Abbruch"


def cmd_batch_create(args, cfg):
    """Messreihe anlegen: N gleichartige Artikel nacheinander, je 1 Shot.

    Dünner Wrapper um dieselbe Logik wie `create-article` (_create_one) – nur
    die Bedienung ist auf „viele Objekte am Stück“ ausgelegt: die Kamera
    bleibt für den ganzen Durchlauf offen, und eine Fehlmessung kostet nur
    diesen einen Artikel."""
    Database(cfg).init_schema()
    pipe = Pipeline(cfg)
    created = []
    try:
        print(f"[batch-create] '{args.name_prefix} 1' … "
              f"'{args.name_prefix} {args.count}' anlegen "
              f"(Höhe {args.height_mm:g} mm, je 1 Aufnahme).")
        print(f"[batch-create] {_BATCH_KEYS}")
        with BoxCamera(cfg) as cam:
            i = 1
            while i <= args.count:
                name = f"{args.name_prefix} {i}"
                if input(f"\n  {name} einlegen > ").strip().lower() == "q":
                    print("[batch-create] abgebrochen.")
                    break
                try:
                    article, _ = _create_one(pipe, cfg, cam.capture(), name,
                                             height_mm=args.height_mm,
                                             category=args.category)
                except (SegmentationError, KeyError) as e:
                    print(f"    [Fehlmessung] {e}")
                    if input("    r = wiederholen, Enter = überspringen > "
                             ).strip().lower() == "r":
                        continue
                    i += 1
                    continue
                print(f"    {_format_created(article)}")
                if input("    Enter = weiter, r = verwerfen und wiederholen > "
                         ).strip().lower() == "r":
                    pipe.db.delete_article(article.article_number)
                    print(f"    {article.article_number} verworfen.")
                    continue
                created.append(article.article_number)
                i += 1
    finally:
        pipe.close()
    print(f"\n[batch-create] {len(created)} Artikel angelegt"
          + (f": {', '.join(created)}" if created else "."))
    if created:
        print(f"[batch-create] Weiter: python -m docodetect.cli batch-enroll "
              f"--prefix {created[0].rsplit('-', 1)[0]} --count {len(created)}")


def cmd_batch_enroll(args, cfg):
    """Messreihe einlernen: `enroll` für <prefix>-1 … <prefix>-N nacheinander.

    Dünner Wrapper um dieselbe Shot-Schleife wie `enroll` (_enroll_shots);
    die Kamera bleibt über alle Artikel offen."""
    Database(cfg).init_schema()   # frische DB: klare Meldung statt SQLite-Fehler
    pipe = Pipeline(cfg)
    done = []
    try:
        print(f"[batch-enroll] {args.shots} Shots je Artikel für "
              f"{args.prefix}-1 … {args.prefix}-{args.count}.")
        print(f"[batch-enroll] {_BATCH_KEYS} (r = Artikel komplett neu einlernen)")
        with BoxCamera(cfg) as cam:
            i = 1
            while i <= args.count:
                number = f"{args.prefix}-{i}"
                article = pipe.db.get_article(number)
                if article is None:
                    print(f"\n  [übersprungen] {number} existiert nicht "
                          "(zuerst batch-create ausführen).")
                    i += 1
                    continue
                if input(f"\n  {article.name} ({number}) einlegen > "
                         ).strip().lower() == "q":
                    print("[batch-enroll] abgebrochen.")
                    break
                n = _enroll_shots(pipe, cfg, cam, number, args.shots)
                _print_enroll_stats(pipe, number)
                if input("    Enter = weiter, r = Artikel neu einlernen > "
                         ).strip().lower() == "r":
                    removed = pipe.db.delete_references(number)
                    print(f"    {removed} Referenzen von {number} verworfen.")
                    continue
                done.append((number, n))
                i += 1
    finally:
        pipe.close()
    print(f"\n[batch-enroll] {len(done)} Artikel eingelernt"
          + (f" ({sum(n for _, n in done)} Shots gesamt)." if done else "."))


def cmd_list_articles(args, cfg):
    """Alle Artikel mit Maßen und Referenzzahl als Tabelle.

    Die einzige Übersicht dieser Art im Projekt: die Qt-UI hat keine
    Artikelliste, und bis hierher hatte auch die CLI keine – nur die
    entfernte Streamlit-Tabelle. Bewusst zwei Abfragen statt eines JOINs:
    `reference_counts()` gibt es bereits fürs UI-Listing, und Artikel OHNE
    Referenzen müssen mit `0` erscheinen, nicht fehlen. Genau die sind beim
    Einlernen die interessanten.

    Bewusst OHNE `init_schema()`, anders als die übrigen Befehle: das ruft
    `recompute_all_stats()` und schriebe bei jedem Auflisten sämtliche
    reference_stats neu. Ein Auflisten darf den Bestand nicht anfassen. Die
    fehlende Datenbank wird deshalb hier abgefangen – und von der leeren
    unterschieden, weil das zwei verschiedene Zustände sind."""
    import sqlite3

    from .display import natuerlicher_schluessel

    db = Database(cfg)
    try:
        # Natürlich sortiert (LOEFFEL-2 vor LOEFFEL-11) – NUR hier, nicht in
        # all_articles(): dort haengt der Matcher dran (siehe display.py).
        articles = sorted(db.all_articles(),
                          key=lambda a: natuerlicher_schluessel(a.article_number))
        counts = db.reference_counts()
    except sqlite3.OperationalError:
        sys.exit(f"[list-articles] Keine Artikel-Tabelle in {db.path}. "
                 "Zuerst 'init-db' oder 'import-articles' ausführen.")
    finally:
        db.close()

    if not articles:
        print("[list-articles] Keine Artikel in der Datenbank. "
              "Anlegen mit 'create-article' oder 'import-articles'.")
        return

    kopf = ("Artikelnummer", "Bezeichnung", "Maße", "Referenzen")
    zeilen = []
    for a in articles:
        masse = _format_geometrie(a)
        if a.height_mm:      # nur wenn gesetzt – sie steuert die Höhenkorrektur
            masse += f" · h {a.height_mm:.0f} mm"
        zeilen.append((a.article_number, a.name, masse,
                       str(counts.get(a.article_number, 0))))

    breite = [max(len(z[i]) for z in (kopf, *zeilen)) for i in range(4)]

    def _zeile(z) -> str:
        # Referenzzahl rechtsbündig: einstellig neben zweistellig soll als
        # Zahlenspalte lesbar bleiben.
        return (f"{z[0]:<{breite[0]}}  {z[1]:<{breite[1]}}  "
                f"{z[2]:<{breite[2]}}  {z[3]:>{breite[3]}}")

    strich = "-" * len(_zeile(kopf))
    print(_zeile(kopf))
    print(strich)
    for z in zeilen:
        print(_zeile(z))
    print(strich)
    eingelernt = sum(1 for a in articles if counts.get(a.article_number))
    n_refs = sum(counts.values())
    print(f"{len(articles)} Artikel, davon {eingelernt} eingelernt "
          f"({n_refs} Referenz{'en' if n_refs != 1 else ''} gesamt).")


def cmd_delete_article(args, cfg):
    db = Database(cfg)
    db.init_schema()  # fresh DB: clean "not found" instead of OperationalError
    try:
        removed = db.delete_article(args.article_number)
    finally:
        db.close()
    if removed:
        print(f"[delete] {args.article_number} gelöscht (inkl. Referenzen; "
              "Fotos unter data/reference/ bleiben liegen).")
    else:
        sys.exit(f"[delete] Artikel '{args.article_number}' nicht gefunden.")


def _verwerfe_referenzfotos(cfg, article_number: str):
    """Den Referenzfoto-Ordner eines Artikels VERSCHIEBEN statt löschen:
    <reference_dir>/<nr>/  ->  <reference_dir>/../verworfen/<nr>/<zeitstempel>/

    Dieselbe Ablagekonvention wie `pipeline.discard_enrollment` (dort
    pre-commit aus dem Einlerndialog, hier post-commit aus der CLI) – bewusst
    derselbe Ort, damit verworfenes Material nur an EINER Stelle gesucht werden
    muss. Gibt (Zielordner, Zahl verschobener Dateien) zurück, (None, 0) wenn
    es keinen Ordner gab."""
    import shutil

    ref_dir = resolve(cfg["paths"]["reference_dir"])
    src = ref_dir / article_number
    if not src.is_dir():
        return None, 0
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = ref_dir.parent / "verworfen" / article_number / stamp
    n = 2
    while dest.exists():        # zweiter Lauf in derselben Sekunde: nicht in
        dest = dest.with_name(f"{stamp}-{n}")   # den bestehenden Ordner hinein
        n += 1
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    return dest, sum(1 for p in dest.rglob("*") if p.is_file())


def cmd_delete_references(args, cfg):
    """Die Referenzen EINES Artikels verwerfen, den Artikel selbst behalten –
    für „nochmal einlernen" nach einer misslungenen Messreihe.

    Gegenstück zu `delete-article`, das zusätzlich die Stammdaten entfernt.
    Zwei bewusste Unterschiede zu dort:

    * Die Fotos werden nicht liegen gelassen, sondern nach data/verworfen/
      verschoben (move-don't-delete). Liegen bleiben hiesse: Dateien ohne
      jede DB-Zeile, die sich nach dem Neu-Einlernen nicht mehr von den
      neuen unterscheiden lassen.
    * Ein Artikel ohne Referenzen ist KEIN Fehler (Exit 0) – der Zielzustand
      ist bereits erreicht. Ein unbekannter Artikel dagegen schon (Exit 1):
      `delete_references` gibt in beiden Fällen 0 zurück, ohne die
      Vorabprüfung liefe ein Tippfehler in der Nummer still durch."""
    import json

    db = Database(cfg)
    db.init_schema()  # fresh DB: clean "not found" instead of OperationalError
    try:
        if db.get_article(args.article_number) is None:
            sys.exit(f"[delete-references] Artikel '{args.article_number}' "
                     "nicht gefunden.")
        meta = db.references_with_meta(args.article_number)
        ohne_pfad = sum(1 for pfad, _ in meta if not pfad)
        if not meta:
            print(f"[delete-references] {args.article_number} hatte keine "
                  "Referenzen – nichts zu tun.")
            ordner = resolve(cfg["paths"]["reference_dir"]) / args.article_number
            if ordner.is_dir() and any(ordner.iterdir()):
                print(f"[delete-references] Hinweis: {ordner} enthält trotzdem "
                      "Dateien. Ohne DB-Zeilen bleiben sie unangetastet.")
            return
        removed = db.delete_references(args.article_number)
    finally:
        db.close()

    print(f"[delete-references] {args.article_number}: {removed} Referenzen "
          "entfernt (Artikel und Stammdaten bleiben, reference_stats mit "
          "geleert).")
    # Erst die DB, dann die Dateien: schlägt das Verschieben fehl, sind die
    # Fotos noch da und der Artikel nur leer – der umgekehrte Fehlerfall
    # hinterliesse DB-Zeilen mit image_path auf verschobene Dateien.
    try:
        ziel, verschoben = _verwerfe_referenzfotos(cfg, args.article_number)
    except OSError as e:
        sys.exit(f"[delete-references] DB-Zeilen sind entfernt, aber die Fotos "
                 f"liessen sich nicht verschieben: {e}")
    if ziel is None:
        print("[delete-references] Kein Referenzfoto-Ordner vorhanden – "
              "nichts zu verschieben.")
    else:
        (ziel / "info.json").write_text(json.dumps(
            {"article_number": args.article_number,
             "timestamp": ziel.name,
             "grund": "delete-references (CLI)",
             "geloeschte_db_zeilen": removed,
             "verschobene_dateien": verschoben,
             "zeilen_ohne_image_path": ohne_pfad},
            ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[delete-references] {verschoben} Fotos verschoben nach {ziel}")
    if ohne_pfad:
        print(f"[delete-references] {ohne_pfad} der {removed} Zeilen hatten "
              "keinen image_path – dazu gibt es keine Datei.")


def cmd_enroll(args, cfg):
    pipe = Pipeline(cfg)
    ref_dir = resolve(cfg["paths"]["reference_dir"]) / args.article_number
    ref_dir.mkdir(parents=True, exist_ok=True)

    if args.images:  # enroll from existing photos
        paths = sorted(Path(args.images).glob("*.[jp][pn]g"))
        if not paths:
            sys.exit(f"No images found in {args.images}")
        for p in paths:
            feats, _ = pipe.enroll(load_image(p), args.article_number, str(p))
            print(f"  {p.name}: Ø {feats.circle_diameter_mm:.1f} mm (floor plane)")
        print(f"[enroll] {len(paths)} references stored for {args.article_number}")
        _print_enroll_stats(pipe, args.article_number)
        return

    print(f"[enroll] {args.shots} shots for {args.article_number}. "
          "Rotate/move the item between shots. ENTER = capture, q = abort.")
    with BoxCamera(cfg) as cam:
        _enroll_shots(pipe, cfg, cam, args.article_number, args.shots)
    _print_enroll_stats(pipe, args.article_number)
    pipe.close()


def _enroll_shots(pipe, cfg, cam, article_number: str, shots: int) -> int:
    """Kern von `enroll`: n Aufnahmen an einer bereits geöffneten Kamera.
    Gibt die Zahl der gespeicherten Shots zurück; 'q' bricht ab. Eine
    Fehlmessung (Randberührung) kostet nur diesen Shot, nicht den Durchlauf –
    wichtig für batch-enroll, wo 15 Artikel am Stück laufen."""
    import cv2

    ref_dir = resolve(cfg["paths"]["reference_dir"]) / article_number
    ref_dir.mkdir(parents=True, exist_ok=True)
    # Eine Aufnahme-Session = ein ts; {i:02d} = Index in Aufnahmereihenfolge
    # (nur erfolgreiche Shots), nullgepadded wie save_enrollment. Damit traegt
    # die lexikalische Dateinamen-Sortierung Feld (3) des Diagnoseblatts
    # explizit und kippt nicht bei zweistelligen Indizes (_10 vor _2).
    ts = int(time.time() * 1000)
    stored = 0
    i = 0
    while i < shots:
        if input(f"  shot {i + 1}/{shots} > ").strip().lower() == "q":
            break
        img = cam.capture()
        # Verlustloses PNG: Shots sollen kuenftige Kantenanalysen tragen.
        img_path = ref_dir / f"{ts}_{i:02d}.png"
        try:
            feats, _ = pipe.enroll(img, article_number, str(img_path))
        except SegmentationError as e:
            print(f"    [Fehlmessung] {e}")
            print("    -> nicht gespeichert, Shot wird wiederholt.")
            continue
        cv2.imwrite(str(img_path), img)
        stored += 1
        i += 1
        print(f"    Ø {feats.circle_diameter_mm:.1f} mm, "
              f"circularity {feats.circularity:.3f}")
    return stored


def _print_enroll_stats(pipe, article_number):
    """Nach dem Einlernen die aggregierte Statistik zeigen – die Streuung
    hier ist die Basis für sigma_eff im Matcher."""
    st = pipe.db.stats_for(article_number)
    if st and "diameter_mm" in st.scalar_mean:
        print(f"[enroll] Statistik ({st.n_shots} Shots): "
              f"Ø {st.scalar_mean['diameter_mm']:.1f} ± {st.scalar_std['diameter_mm']:.2f} mm, "
              f"Rundheit {st.scalar_mean['circularity']:.3f} ± {st.scalar_std['circularity']:.4f}")


def _print_result(outcome):
    r = outcome.report
    print(f"\n[{r.decision.upper()}] {r.message}")
    if outcome.features:
        f = outcome.features
        print(f"  measured (floor plane): Ø {f.circle_diameter_mm:.1f} mm, "
              f"area {f.area_mm2 / 100:.1f} cm², circularity {f.circularity:.3f}")
    top_k = int(r.thresholds.get("top_k", 3))
    for i, c in enumerate(r.candidates[:top_k], 1):
        ref = "" if c.has_references else "  [keine Referenzen – nur Geometrie]"
        print(f"  {i}. {c.article_number}  {c.name}  "
              f"Posterior {c.posterior:.0%}  log-Score {c.log_score:.2f}  "
              f"max|z| {c.max_abs_z:.1f}  Δgeo {c.geometry_error_mm:.1f} mm{ref}")


def cmd_identify(args, cfg):
    pipe = Pipeline(cfg)
    outcome = pipe.identify(_get_image(args, cfg),
                            source_path=getattr(args, "image", None))
    _print_result(outcome)
    pipe.close()


def cmd_evaluate(args, cfg):
    """Gelabelten Testordner durch identify() jagen und aggregieren – die
    Report-JSONs landen dabei in data/captures/ (Futter für den Batch-Tab
    der Scoring-Analyse, gleiche Aggregationslogik: reporting.py)."""
    from .reporting import format_summary, predicted_article, summarize
    pipe = Pipeline(cfg)
    reports = []
    for class_dir in sorted(p for p in Path(args.testset).iterdir() if p.is_dir()):
        truth = class_dir.name
        for img_path in sorted(class_dir.glob("*.[jp][pn]g")):
            outcome = pipe.identify(load_image(img_path),
                                    source_path=str(img_path), label=truth)
            reports.append(outcome.report)
            pred = predicted_article(outcome.report)
            if pred != truth:
                print(f"  MISS {img_path.name}: {truth} -> {pred} "
                      f"[{outcome.report.decision}]")
    print(format_summary(summarize(reports)))
    pipe.close()


def cmd_list_cameras(args, cfg):
    """Welcher Index ist die Box-Kamera? Probiert 0..--max-index durch."""
    from .camera import capture_backend, probe_cameras
    current = cfg["camera"].get("index")
    print(f"[cameras] Backend {capture_backend(cfg['camera'])} auf {sys.platform}, "
          f"aktuell konfiguriert: index {current}")
    results = probe_cameras(cfg["camera"], args.max_index)
    for index, ok, w, h in results:
        mark = " <- aktuell konfiguriert" if index == current else ""
        status = f"antwortet, {w}x{h}" if ok else "keine Kamera / belegt"
        print(f"  index {index}: {status}{mark}")
    if not any(ok for _, ok, _, _ in results):
        print("[cameras] Keine Kamera gefunden – USB-Verbindung prüfen "
              "(und ob ein anderes Programm die Kamera belegt).")
        return
    print("[cameras] Passenden Index dauerhaft setzen: camera.index in "
          "config/config.local.yaml (rechnerlokal, siehe README).")


def cmd_make_smoke_testset(args, cfg):
    """Deterministisches Smoke-Testset materialisieren (Regressions-Baseline):
    Testbilder + Kalibrierung + Hintergrund + frisch eingelernte Referenz-DB.
    Bestehende Kalibrier-/DB-Dateien werden gesichert, nie überschrieben."""
    from .smoke_testset import generate
    s = generate(cfg, resolve(args.out))
    for b in s["backups"]:
        print(f"[smoke] Gesichert: {b}")
    print(f"[smoke] {s['n_images']} Testbilder für {s['n_articles']} Artikel "
          f"unter {s['testset_dir']}")
    print(f"[smoke] Kalibrierung {s['mm_per_px']:.5f} mm/px; Hintergrund und "
          "Referenz-DB (je 3 Shots) frisch erzeugt.")
    print(f"[smoke] Weiter: python -m docodetect.cli evaluate {args.out}")


def cmd_ab_report(args, cfg):
    """Zwei Testrunden vergleichen (z.B. Phase A = 1 Shot, Phase B = 8 Shots)."""
    from .reporting import compare_runs, load_reports
    a = [r for _, r in load_reports(args.dir_a)]
    b = [r for _, r in load_reports(args.dir_b)]
    if not a or not b:
        sys.exit(f"[ab-report] Keine Reports in "
                 f"{args.dir_a if not a else args.dir_b} gefunden.")
    print(compare_runs(a, b, k=int(cfg["matching"].get("top_k", 3)),
                       label_a=args.label_a, label_b=args.label_b))


def cmd_sync_stammdaten(args, cfg):
    """Geometrische Stammdaten auf die Enrollment-Mittelwerte ziehen.

    Ohne --apply passiert NICHTS außer der Diff-Tabelle – der Default ist
    bewusst die Vorschau, weil dieser Befehl die Vorfilter-Basis aller
    betroffenen Artikel verschiebt."""
    from .stammdaten import apply_sync, compute_sync, format_table
    db = Database(cfg)
    try:
        rows, skipped = compute_sync(db, min_shots=args.min_shots)
        if args.apply and rows:
            apply_sync(db, rows)
        print(format_table(rows, skipped, args.min_shots,
                           applied=bool(args.apply and rows)))
    finally:
        db.close()


def cmd_analyze(args, cfg):
    """Sechs Auswertungen (PNG + CSV/JSON) über gespeicherte Report-JSONs."""
    from .analysis import publish_run, run_analysis
    out = run_analysis(cfg, args.reports_dir, args.run_id, archive=args.archive)
    print(f"[analyze] Artefakte unter {out}")
    print(f"[analyze] Bericht: {out / 'report.md'}")
    if args.archive:
        print("[analyze] Report-JSONs in den Lauf-Ordner verschoben – "
              "nächste Testrunde startet leer.")
    if args.publish:
        publish_run(cfg, out)


def cmd_analyze_floors(args, cfg):
    """sigma_floors aus einer Messreihe (Artikel N-fach neu aufgelegt)."""
    from .floor_analysis import (analyze_floors, format_diameter_summary,
                                 format_outliers, format_table,
                                 format_warnings, format_yaml_block)
    src = Path(args.reports_dir) if args.reports_dir else resolve(
        cfg.get("paths", {}).get("captures_dir", "data/captures"))
    report = analyze_floors(src, label=args.label, since=args.since,
                            until=args.until, limit=args.limit)
    print(f"[analyze-floors] {report.n_reports} Reports nach Filter "
          f"({report.n_usable} mit measured-Block) aus {src}")
    if report.n_usable == 0:
        print("[analyze-floors] keine auswertbaren Reports - Filter prüfen.")
        return
    print()
    print(format_table(report))
    print()
    print(format_yaml_block(report))
    d = format_diameter_summary(report)
    if d:
        print()
        print(d)
    for w in format_warnings(report):
        print(f"[analyze-floors] WARNUNG: {w}")
    o = format_outliers(report)
    if o:
        print()
        print(o)


def cmd_enrollment_sheet(args, cfg):
    """Enrollment-Diagnoseblatt (PNG) aus den N Shots eines Artikels."""
    from .enrollment_sheet import build_enrollment_sheet
    out = build_enrollment_sheet(cfg, article_number=args.article_number,
                                 out=args.out)
    print(f"[enrollment-sheet] geschrieben: {out}")


def cmd_contour_band(args, cfg):
    """(11) Konturband + Breitenprofil eines Artikels – separat, weil die
    Segmentierung je Aufnahme kostet (nicht Teil von `analyze`)."""
    from .enrollment_sheet import build_contour_band
    out = build_contour_band(cfg, args.article_number, session=args.session,
                             out=args.out)
    print(f"[contour-band] geschrieben: {out}")


# ---------- Einlern-Sessions: der Rettungspfad OHNE GUI ----------
#
# Auflisten, Ansehen, Buchen und Verwerfen laufen ohne Qt und ohne Kamera.
# Genau darum geht es: der Rettungsfall ist der, in dem Qt das kaputte Teil
# ist. Nur ZUSAETZLICHE Aufnahmen brauchen eine Kamera und damit die GUI
# (oder `enroll --images`).

def _alter(sekunden: float) -> str:
    if sekunden < 90:
        return f"vor {int(sekunden)} s"
    if sekunden < 5400:
        return f"vor {int(sekunden // 60)} min"
    if sekunden < 172800:
        return f"vor {int(sekunden // 3600)} h"
    return f"vor {int(sekunden // 86400)} Tagen"


def _finde_session(cfg, article_number, ts=None):
    """Genau EINE offene Session finden. Beendet den Prozess mit Klartext,
    wenn keine, keine passende oder mehrere in Frage kommen.

    `--ts` ist PFLICHT, sobald mehr als eine offene Session fuer den Artikel
    existiert — zwei Abstuerze hintereinander erzeugen genau das. Bei
    Mehrdeutigkeit wird NICHT geraten: eine falsch gewaehlte Session buchte
    fremde Aufnahmen unter die Artikelnummer."""
    from .pipeline import list_enroll_sessions, load_enroll_session

    offen = list_enroll_sessions(cfg, article_number=article_number)
    if not offen:
        sys.exit(f"[enroll-session] Keine offene Einlern-Session fuer "
                 f"'{article_number}'.")
    if ts is not None:
        treffer = [i for i in offen if str(i.ts) == str(ts)]
        if not treffer:
            vorhanden = ", ".join(str(i.ts) for i in offen)
            sys.exit(f"[enroll-session] Keine Session {ts} fuer "
                     f"'{article_number}'. Vorhanden: {vorhanden}")
        return load_enroll_session(cfg, treffer[0].path)
    if len(offen) > 1:
        zeilen = "\n".join(
            f"    --ts {i.ts}   {i.n_shots} Aufnahmen   {_alter(i.age_secs)}"
            f"   {i.zustand}" for i in offen)
        sys.exit(f"[enroll-session] {len(offen)} offene Sessions fuer "
                 f"'{article_number}' – --ts ist dann Pflicht:\n{zeilen}")
    return load_enroll_session(cfg, offen[0].path)


def _session_fehler(e) -> None:
    """EnrollSessionError als Klartext-Befund ausgeben und mit 1 enden.
    Der Aufrufer verzweigt auf .kind nur fuer die angebotene Abhilfe und
    rechnet nichts nach."""
    import json as _json

    print(f"[enroll-session] {e.kind.upper()}: {e}", file=sys.stderr)
    if e.detail:
        print(_json.dumps(e.detail, ensure_ascii=False, indent=2, default=str),
              file=sys.stderr)
    sys.exit(1)


def cmd_list_enroll_sessions(args, cfg):
    """Offene Einlern-Sessions, neueste zuerst. Die Existenz des Ordners IST
    'offen' – es gibt kein Statusfeld, das damit auseinanderlaufen koennte."""
    import json as _json

    from .pipeline import list_enroll_sessions

    offen = list_enroll_sessions(cfg, article_number=getattr(args, "article", None))
    if args.json:
        print(_json.dumps(
            [{"article_number": i.article_number, "ts": i.ts,
              "n_shots": i.n_shots, "target_shots": i.target_shots,
              "zustand": i.zustand, "fingerprint_ok": i.fingerprint_ok,
              "age_secs": round(i.age_secs, 1), "path": str(i.path)}
             for i in offen], ensure_ascii=False, indent=2))
        return
    if not offen:
        print("[enroll-sessions] Keine offene Einlern-Session.")
        return
    print(f"[enroll-sessions] {len(offen)} offen:\n")
    for i in offen:
        optik = "Optik unveraendert" if i.fingerprint_ok else \
            "!! Kalibrierung geaendert – nicht fortsetzbar"
        print(f"  {i.article_number:<14} ts {i.ts}  "
              f"{i.n_shots}/{i.target_shots} Aufnahmen  "
              f"{_alter(i.age_secs):<14} {i.zustand:<26} {optik}")


def cmd_show_enroll_session(args, cfg):
    """Detail einer Session: Zustand, Optik, Tabelle je Aufnahme mit dem Ort,
    an dem die Datei gerade liegt."""
    from pathlib import Path as _P

    from .pipeline import _zielpfade
    from .pipeline import EnrollSessionError

    s = _finde_session(cfg, args.article_number, getattr(args, "ts", None))
    i = s.info
    print(f"[enroll-session] {i.article_number}  ts {i.ts}")
    print(f"  Ordner:    {i.path}")
    print(f"  Angelegt:  {i.created}   ({_alter(i.age_secs)})")
    print(f"  Aufnahmen: {i.n_shots} von {i.target_shots} geplant")
    print(f"  Zustand:   {i.zustand}")
    print(f"  Optik:     {'unveraendert' if i.fingerprint_ok else 'GEAENDERT'}"
          f"   mm_per_px {i.fingerprint.get('mm_per_px')}")
    if not i.fingerprint_ok:
        print(f"  -> Nicht fortsetzbar. Auswege: alte Kalibrierung aus "
              f"{i.path / 'optik'} zurueckholen, verwerfen, oder neu einlernen.")
    if not s.shots:
        print("\n  (keine Aufnahme im Journal)")
        return
    print("\n    i   Ø mm     Datei liegt")
    for e in _zielpfade(cfg, s):
        idx, quelle, ziel = e
        shot = next(sh for sh in s.shots if sh.i == idx)
        ort = ("Session" if quelle.exists() else
               "reference_dir" if _P(ziel).exists() else "!! VERSCHWUNDEN")
        print(f"  {idx:3d}   {shot.d_mm:7.1f}   {ort}")


def _plan_ausgeben(plan: list) -> None:
    print("\n    i   Aktion                          Ziel")
    for e in plan:
        print(f"  {e['i']:3d}   {e['aktion']:<30}  {e['ziel']}")


def cmd_commit_enroll_session(args, cfg):
    """Session buchen (INVARIANTE U1) oder mit --dry-run nur pruefen.

    --dry-run laesst ALLE VIER Pruefungen echt laufen und zeigt den Umzugsplan,
    bewegt aber keine Datei und schreibt nichts."""
    from .pipeline import (EnrollSessionError, commit_enroll_session,
                           plan_commit_enroll_session)

    s = _finde_session(cfg, args.article_number, getattr(args, "ts", None))
    try:
        if args.dry_run:
            p = plan_commit_enroll_session(cfg, s)
            print(f"[commit --dry-run] {p['article_number']} ts {p['ts']}: "
                  f"{p['n']} Aufnahmen, Buchungsstand '{p['stand']}'")
            _plan_ausgeben(p["plan"])
            print("\n  Nichts bewegt, nichts gebucht.")
            return
        n = commit_enroll_session(cfg, s)
    except EnrollSessionError as e:
        _session_fehler(e)
    print(f"[commit] {s.info.article_number}: {n} Referenzen gebucht, "
          f"Session-Rest nach backups/ geraeumt.")


def cmd_discard_enroll_session(args, cfg):
    """Session verwerfen: Rueckumzug, dann der vollstaendige Ordner nach
    data/verworfen/. Loescht nichts.

    --dry-run zeigt die vollstaendige Gegenrichtungs-Tabelle je Aufnahme, ohne
    eine Datei zu bewegen und ohne info.json zu schreiben. Der Rueckumzug
    greift AUS reference_dir heraus – die gefaehrlichere Richtung."""
    from .pipeline import (EnrollSessionError, discard_enroll_session,
                           plan_discard_enroll_session)

    s = _finde_session(cfg, args.article_number, getattr(args, "ts", None))
    try:
        if args.dry_run:
            p = plan_discard_enroll_session(cfg, s)
            print(f"[discard --dry-run] {p['article_number']} ts {p['ts']}: "
                  f"{p['n']} Aufnahmen")
            _plan_ausgeben(p["plan"])
            print("\n  Nichts bewegt, kein info.json geschrieben.")
            return
        ziel = discard_enroll_session(cfg, s)
    except EnrollSessionError as e:
        _session_fehler(e)
    print(f"[discard] {s.info.article_number}: Session verworfen, vollstaendig "
          f"gesichert unter {ziel} (kein DB-Eintrag, nichts geloescht).")


def cmd_corpus_build(args, cfg):
    """Regressions-Korpus aus Captures, archivierten Reports und Backups bauen."""
    from .corpus.build import build_corpus
    stat = build_corpus(cfg, dry_run=args.dry_run)
    print(f"[corpus-build] {stat['neu']} neu, {stat['gesamt']} gesamt "
          f"({stat['uebersprungen_dublette']} Dubletten, "
          f"{stat['uebersprungen_ohne_bild']} ohne Bild)")
    for s, v in stat["sessions"].items():
        print(f"  {s:16} Tier {v['tier']}  DB-Abgleich {v['db_verified']:.0%}  "
              f"{v['n_images']} Bilder (+{v['neu']})")
    # Laut melden, nicht nur im Rueckgabewert fuehren: ein eingefrorenes
    # Buendel, dessen Quelle sich weitergedreht hat, ist der Fall, in dem
    # ein spaeterer --check eine Regression meldet, die keine ist.
    for meldung in stat.get("bundle_konflikt", []):
        print(f"[corpus-build] BUENDEL UNVERAENDERT: {meldung}")
    if args.dry_run:
        print("[corpus-build] dry-run – nichts geschrieben.")


def cmd_corpus_run(args, cfg):
    """Korpus-Replay: Tier 1 (Messung) bzw. Tier 2 (Entscheidung)."""
    import sys
    from datetime import datetime

    from .corpus import report as corpus_report
    from .corpus import runner as corpus_runner
    from .corpus.manifest import corpus_root
    from .corpus.verify import pruefe_bundle_db_konsistenz
    from .matcher import MatchReport

    # Konsistenz VOR dem Rechnen: eine als Tier-2-faehig ausgewiesene Session
    # ohne Buendel-DB laesst einen Tier-2-Lauf stillschweigend schmaler
    # werden (siehe corpus/verify.py). Lieber hier laut abbrechen als spaeter
    # ein zu enges, gruenes Merge-Gate.
    if corpus_root(cfg).exists():
        pruefe_bundle_db_konsistenz(corpus_root(cfg))

    run_id = args.run_id or datetime.now().strftime("%Y%m%d-%H%M%S")
    run = corpus_runner.run_corpus(
        cfg, sessions=args.session, articles=args.article, tier=args.tier,
        subset=args.subset, workers=args.workers,
        changed_only=args.changed_only, run_id=run_id,
        config_path=args.config)
    # run_corpus setzt den run_id, falls keiner uebergeben wurde
    run_id = run.get("run_id", run_id)

    quotas = {}
    quoten_unvollstaendig = False
    if args.tier == 2:
        root = corpus_root(cfg)
        reports = []
        for r in run["results"]:
            # Replay-Reports liegen lauf-scoped, NICHT in einem geteilten
            # Ordner — sonst mischt ein gefilterter Lauf alte mit frischen
            # Ergebnissen (Task-5-Review, Befund I5).
            p = root / "runs" / run_id / "replay" / f"{r['sha'][:8]}.json"
            if p.exists():
                reports.append(MatchReport.from_json(p.read_text(encoding="utf-8")))
        if reports:
            quotas = corpus_report.tier2_quotas(reports)
        # Sicherheitsnetz: fehlen Replay-Reports, decken die Quoten nur eine
        # Teilmenge ab. Ein stillschweigend uebersprungener Quoten-Vergleich
        # waere im Merge-Gate schlimmer als gar keiner.
        if len(reports) < len(run["results"]):
            quoten_unvollstaendig = True
            print(f"[corpus-run] WARNUNG: nur {len(reports)} von "
                  f"{len(run['results'])} Replay-Reports vorhanden — die "
                  f"Tier-2-Quoten decken nicht den ganzen Lauf ab.")

    out = corpus_report.write_run(corpus_root(cfg), run_id, run, quotas)
    print(f"[corpus-run] {run['n']} Bilder, Tier {run['tier']}, "
          f"{run['dauer_s']} s"
          + (f" ({run['bilder_pro_s']} Bilder/s)" if run["bilder_pro_s"] else ""))
    print(f"[corpus-run] Bericht: {out / 'summary.md'}")

    # --report: nach einem Lauf MIT Abweichungen die Drift-Review erzeugen.
    # Bewusst nur dann - ein durchweg gruener Lauf braucht keine Review, und
    # ein automatisch erzeugter Ordner je Lauf laesst reports/corpus/
    # unnoetig zuwachsen (siehe Hygiene-Notiz in docs/architektur.md).
    if getattr(args, "report", False):
        abweichend = sum(1 for r in run["results"] if r["band"] != "pass")
        if not abweichend:
            print("[corpus-run] --report: keine Abweichung, keine "
                  "Drift-Review erzeugt.")
        else:
            from .corpus.review import run_review
            try:
                ziel = run_review(cfg, run=run_id)
                print(f"[corpus-run] Drift-Review ({abweichend} abweichende "
                      f"Bilder): {ziel / 'index.html'}")
            except (RuntimeError, FileNotFoundError) as exc:
                # Die Review ist eine Zugabe, kein Gate: sie darf den
                # Exit-Code von --check nie beeinflussen.
                print(f"[corpus-run] --report uebersprungen: {exc}")

    if args.update_baseline:
        # Verweigern statt mergen. save_baseline() schreibt ERSETZEND, und
        # --tier hat Default 1 — quotas bleibt dort leer. Ein durchgelassener
        # Lauf schriebe also "quotas": {} und schaltete damit in
        # check_against_baseline JEDE Kennzahl dauerhaft ab (der Zweig
        # `if not alt: continue` greift dann fuer immer). Ein stilles Mergen
        # waere zwar bequemer, verbaende aber Quoten und Fingerprints aus
        # zwei verschiedenen Laeufen zu einer Baseline, die keinen realen
        # Zustand mehr beschreibt. Der laute Abbruch ist schwerer falsch zu
        # bedienen als eine Baseline gemischter Herkunft.
        if not quotas:
            print("[corpus-run] ABBRUCH: --update-baseline ohne Quoten. "
                  "Nur ein Tier-2-Lauf erzeugt die Soll-Quoten; mit --tier 1 "
                  "wuerde die Baseline mit leeren quotas ueberschrieben und "
                  "der Regressionsvergleich waere dauerhaft abgeschaltet.")
            print("[corpus-run] Stattdessen: corpus-run --tier 2 "
                  "--update-baseline")
            sys.exit(2)
        corpus_report.save_baseline({
            "generated": datetime.now().isoformat(timespec="seconds"),
            "run_id": run_id, "tier": run["tier"], "n": run["n"],
            "quoten_semantik": corpus_report.QUOTEN_SEMANTIK,
            "quotas": quotas, "code_fingerprint": run["code_fingerprint"],
            "config_fingerprint": run["config_fingerprint"]})
        print(f"[corpus-run] Baseline aktualisiert: {corpus_report.BASELINE_PATH}")
        print("[corpus-run] ACHTUNG: Begruendung im Commit ist Pflicht.")

    if args.check:
        baseline = corpus_report.load_baseline()
        code, meldungen = corpus_report.check_against_baseline(
            run, quotas, baseline, accept_drift=args.accept_drift)

        # Vollstaendigkeitsschranke: ein Ausschnitt kann sauber sein, ohne
        # dass der Korpus es ist. Ohne diese Pruefung sieht
        # `--check --subset 5` aus wie ein gruenes Merge-Gate. Der
        # Tier-2-Zweig hat mit quoten_unvollstaendig bereits ein solches
        # Netz — hier fehlte es fuer Tier 1.
        gefiltert = [n for n, v in (("--subset", args.subset is not None),
                                    ("--session", bool(args.session)),
                                    ("--article", bool(args.article))) if v]
        if gefiltert:
            code = 1
            meldungen.append(
                f"--check auf einem gefilterten Teil-Lauf ({', '.join(gefiltert)}) "
                f"— ein Ausschnitt ist keine Freigabe. Fuer das Merge-Gate "
                f"ohne Filter laufen lassen.")
        else:
            basis_n = baseline.get("n")
            if isinstance(basis_n, int) and run["n"] < basis_n:
                code = 1
                meldungen.append(
                    f"Nur {run['n']} Bilder geprueft, die Baseline fuehrt "
                    f"{basis_n} — der Lauf deckt den Korpus nicht ab. "
                    f"'corpus-build' pruefen, dann erneut laufen lassen.")

        if quoten_unvollstaendig:
            # Nicht auf 0 enden duerfen: ein Gate, das wegen fehlender Daten
            # schweigt, meldet Sicherheit, die es nicht geprueft hat.
            code = 1
            meldungen.append(
                "Tier-2-Quoten unvollstaendig — die Regressionspruefung "
                "deckt nicht alle Bilder ab. Lauf ohne --changed-only "
                "wiederholen.")
        for m in meldungen:
            print(f"[corpus-run] {m}")
        print("[corpus-run] " + ("OK" if code == 0 else "REGRESSION"))
        sys.exit(code)


def cmd_corpus_diff(args, cfg):
    """Zwei Korpus-Laeufe gegeneinander stellen."""
    from .corpus.diff import diff_runs, format_diff
    from .corpus.manifest import corpus_root
    print(format_diff(diff_runs(corpus_root(cfg), args.run_a, args.run_b)))


def cmd_corpus_report(args, cfg):
    """Drift-Review und Kennzahlen-Ansichten ueber fertige Laeufe.

    Rechnet NICHTS neu: liest Goldens, Replay-Reports, failures/, metrics.json
    und corpus/baseline.json und legt PNG/CSV/HTML unter reports/corpus/ ab.
    """
    from .corpus.review import publish_review, run_review
    try:
        out = run_review(cfg, run=args.run,
                         compare=tuple(args.compare) if args.compare else None)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        # Bedienfehler (Lauf abgebrochen, Lauf-ID falsch, Seiten ohne
        # gemeinsame Bilder) als Klartext, nicht als Traceback.
        sys.exit(f"[corpus-report] {exc}")
    print(f"[corpus-report] Artefakte unter {out}")
    print(f"[corpus-report] Uebersicht: {out / 'index.html'}")
    if args.publish:
        publish_review(cfg, out)


def cmd_corpus_triage(args, cfg):
    """Failures clustern und findings.md schreiben. Nur Befunde."""
    from .corpus.manifest import corpus_root
    from .corpus.triage import triage_run
    out = triage_run(cfg, corpus_root(cfg), args.run_id)
    print(f"[corpus-triage] Befunde: {out}")


# ---------- Sandbox-Sperren ----------

# Befehle, die AUSSERHALB der fünf umgelenkten Sandbox-Pfade schreiben. Sie
# unter --sandbox durchzulassen hiesse, dass ein Testlauf Produktivzustand
# mutiert — genau das, was die Sandbox verhindern soll. Klartext-Abbruch mit
# Exit 1, in derselben Härte wie `--check` auf einem gefilterten Korpus-Lauf.
_GETEILTE_KALIBRIERUNG = (
    "Kalibrierung und Hintergrund sind in der Sandbox bewusst GETEILT: ein "
    "Test-Enrollment muss gegen dieselbe Skala messen wie die Produktion, "
    "sonst misst es nichts. Damit bleiben beide Dateien produktiver Zustand "
    "und dürfen aus einer Sandbox heraus nicht überschrieben werden.")

SANDBOX_GESPERRT = {
    "calibrate": _GETEILTE_KALIBRIERUNG,
    "capture-background": _GETEILTE_KALIBRIERUNG,
    "make-smoke-testset":
        "make-smoke-testset verschiebt calibration.file, background_file UND "
        "db_file beiseite und schreibt sie neu. Zwei der drei Ziele sind "
        "nicht umgelenkt — der Befehl würde die produktive Kalibrierung "
        "wegrotieren.",
    "corpus-build":
        "Der Regressions-Korpus liest und schreibt ausserhalb der Sandbox "
        "(paths.corpus_dir, corpus/baseline.json, reports/corpus/). Ein "
        "Korpus, der aus einem Testbestand gebaut oder gegen ihn geprüft "
        "wird, ist kein Gate mehr.",
}
SANDBOX_GESPERRT.update({
    cmd: SANDBOX_GESPERRT["corpus-build"]
    for cmd in ("corpus-run", "corpus-diff", "corpus-report", "corpus-triage")
})


def pruefe_sandbox_sperre(cmd: str, args) -> None:
    """Beendet den Prozess mit Exit 1, wenn `cmd` unter --sandbox verboten ist.

    Zwei Klassen: ganze Befehle (SANDBOX_GESPERRT) und ein einzelner Schalter
    (`analyze --publish`), dessen Ziel analysis.publish_dir VERSIONIERT ist
    (.gitignore nimmt reports/archive/ ausdrücklich von reports/* aus) — ein
    Sandbox-Lauf landete dort im Commit."""
    grund = SANDBOX_GESPERRT.get(cmd)
    if grund:
        sys.exit(f"[sandbox] '{cmd}' ist unter --sandbox gesperrt. {grund}\n"
                 f"[sandbox] Ohne --sandbox ausführen.")
    if cmd == "analyze" and getattr(args, "publish", False):
        sys.exit(
            "[sandbox] 'analyze --publish' ist unter --sandbox gesperrt: "
            "analysis.publish_dir (reports/archive) ist versioniert, ein "
            "Sandbox-Lauf würde dort im Commit landen.\n"
            "[sandbox] 'analyze' ohne --publish läuft in der Sandbox.")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="docodetect")
    parser.add_argument("--config", default=None, help="path to config.yaml")
    parser.add_argument("--sandbox", default=None, metavar="NAME",
                        help="isolierter Stand unter data/sandbox/NAME "
                             "(DB, Referenzen, Verworfene, Captures, "
                             "Berichte). Kalibrierung und Hintergrund "
                             "bleiben geteilt. Name ist Pflicht.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init-db")

    p = sub.add_parser("import-articles")
    p.add_argument("csv")

    sub.add_parser("list-articles",
                   help="alle Artikel mit Maßen und Referenzzahl auflisten")

    p = sub.add_parser("capture-background")
    p.add_argument("--image", help="use an image file instead of the camera")

    p = sub.add_parser("calibrate")
    p.add_argument("--image", help="use an image file instead of the camera")

    p = sub.add_parser("create-article", help="create a new article live from one shot")
    p.add_argument("name", help="display name, e.g. \"Suppenloeffel\"")
    p.add_argument("--article-number", default=None,
                   help="explicit key (default: auto-derived from the name)")
    p.add_argument("--height-mm", type=float, default=0.0,
                   help="object height above the floor (0 = flat, e.g. a spoon)")
    p.add_argument("--category", default=None, help="e.g. Loeffel / Teller / Tasse")
    p.add_argument("--image", help="use an image file instead of the camera")

    p = sub.add_parser("batch-create", help="Messreihe: N gleichartige Artikel "
                       "nacheinander anlegen (je 1 Aufnahme)")
    p.add_argument("--name-prefix", default="Löffel",
                   help='Namensstamm, ergibt "<Prefix> 1".."<Prefix> N" (Default: Löffel)')
    p.add_argument("--count", type=int, default=15, help="Anzahl (Default: 15)")
    p.add_argument("--height-mm", type=float, default=0.0,
                   help="Objekthöhe über dem Boden (Default: 0 = flach)")
    p.add_argument("--category", default=None, help="z.B. Loeffel / Teller")

    p = sub.add_parser("batch-enroll", help="Messreihe: <prefix>-1..N "
                       "nacheinander einlernen")
    p.add_argument("--prefix", default="LOEFFEL",
                   help="Artikelnummern-Stamm (Default: LOEFFEL)")
    p.add_argument("--count", type=int, default=15, help="Anzahl (Default: 15)")
    p.add_argument("--shots", type=int, default=12,
                   help="Aufnahmen je Artikel (Default: 12)")

    p = sub.add_parser("delete-article", help="remove an article incl. its references")
    p.add_argument("article_number")

    p = sub.add_parser("delete-references",
                       help="Referenzen eines Artikels verwerfen, den Artikel "
                            "behalten (Fotos nach data/verworfen/)")
    p.add_argument("article_number")

    p = sub.add_parser("enroll")
    p.add_argument("article_number")
    p.add_argument("--shots", type=int, default=12)
    p.add_argument("--images", help="enroll from a folder of photos instead of live capture")

    p = sub.add_parser("enrollment-sheet",
                       help="Diagnoseblatt (PNG) aus den N Shots eines Artikels")
    p.add_argument("article_number")
    p.add_argument("--out", help="Ausgabepfad (Default: reports/enrollment/<nr>.png)")

    p = sub.add_parser("contour-band",
                       help="Konturband + Breitenprofil eines Artikels "
                            "(Segmentierung je Aufnahme)")
    p.add_argument("article_number")
    p.add_argument("--session",
                   help="nur Referenzen einer Einlern-Session (Teilstring des Dateinamens)")
    p.add_argument("--out", help="Ausgabepfad (Default: "
                                 "reports/analysis/contour_band/<nr>.png)")

    p = sub.add_parser("identify")
    p.add_argument("--image", help="use an image file instead of the camera")

    p = sub.add_parser("evaluate")
    p.add_argument("testset", help="folder: testset/<article_number>/*.jpg")

    p = sub.add_parser("list-cameras",
                       help="verfügbare Kamera-Indizes durchprobieren "
                            "(welcher Index ist die Box-Kamera?)")
    p.add_argument("--max-index", type=int, default=3,
                   help="höchster geprüfter Index (Default: 3)")

    p = sub.add_parser("make-smoke-testset",
                       help="deterministisches Smoke-Testset (Baseline) auf "
                            "Platte erzeugen: Bilder + Kalibrierung + Referenz-DB")
    p.add_argument("--out", default="data/testset-smoke",
                   help="Zielordner (Default: data/testset-smoke)")

    p = sub.add_parser("ab-report", help="zwei Capture-Ordner vergleichen "
                       "(Erfolgsrate, Entscheidungen, max|z|, Top-k)")
    p.add_argument("dir_a", help="Ordner mit Report-JSONs der Phase A")
    p.add_argument("dir_b", help="Ordner mit Report-JSONs der Phase B")
    p.add_argument("--label-a", default="A (1 Shot)")
    p.add_argument("--label-b", default="B (8 Shots)")

    p = sub.add_parser("sync-stammdaten",
                       help="geometrische Stammdaten der eingelernten Artikel "
                            "auf die Enrollment-Mittelwerte ziehen "
                            "(Default: nur Diff-Tabelle zeigen)")
    p.add_argument("--apply", action="store_true",
                   help="Änderungen wirklich in die DB schreiben "
                        "(ohne diesen Schalter passiert nichts)")
    p.add_argument("--min-shots", type=int, default=2,
                   help="Mindestzahl Enrollment-Shots (Default: 2 – gegen "
                        "einen einzelnen Shot zu synchronisieren bringt nichts)")

    p = sub.add_parser("analyze", help="Auswertungs-Artefakte (Grafiken + "
                       "CSV/JSON) aus gespeicherten Report-JSONs erzeugen")
    p.add_argument("reports_dir", nargs="?", default=None,
                   help="Ordner mit Report-JSONs (Default: paths.captures_dir)")
    p.add_argument("--run-id", default=None,
                   help="Name des Auswertungslaufs (Default: Timestamp)")
    p.add_argument("--archive", action="store_true",
                   help="ausgewertete Report-JSONs in den Lauf-Ordner "
                        "verschieben (nächste Testrunde startet leer)")
    p.add_argument("--publish", action="store_true",
                   help="aggregierte Artefakte (ohne rohe Report-JSONs) "
                        "zusätzlich ins versionierte Archiv kopieren "
                        "(analysis.publish_dir, Default reports/archive)")

    p = sub.add_parser("analyze-floors", help="matching.sigma_floors aus "
                       "einer Messreihe bestimmen (Artikel N-fach neu "
                       "aufgelegt) statt von Hand")
    p.add_argument("reports_dir", nargs="?", default=None,
                   help="Ordner mit Report-JSONs (Default: paths.captures_dir)")
    p.add_argument("--label", default=None,
                   help="nur Reports mit diesem Label (wahrer Artikel, "
                        "z.B. per UI-Bewertung gesetzt)")
    p.add_argument("--since", default=None,
                   help="nur Reports ab diesem Zeitstempel (ISO, wie im "
                        "Report-JSON: 2026-07-22T09:00:00)")
    p.add_argument("--until", default=None,
                   help="nur Reports bis zu diesem Zeitstempel (ISO)")
    p.add_argument("--limit", type=int, default=None,
                   help="nur die letzten N Reports (nach Filter, neueste "
                        "zuerst) - z.B. die letzten 20 einer Messreihe")

    # -- Einlern-Sessions: Rettungspfad ohne GUI --
    p = sub.add_parser("list-enroll-sessions",
                       help="offene Einlern-Sessions auflisten (neueste zuerst)")
    p.add_argument("--article", help="nur Sessions dieses Artikels")
    p.add_argument("--json", action="store_true", help="maschinenlesbar")

    p = sub.add_parser("show-enroll-session",
                       help="eine Einlern-Session im Detail (Zustand, Optik, "
                            "Aufnahmen und wo ihre Dateien liegen)")
    p.add_argument("article_number")
    p.add_argument("--ts", help="Pflicht, sobald mehrere Sessions offen sind")

    p = sub.add_parser("commit-enroll-session",
                       help="eine Einlern-Session buchen (Dateien umziehen + "
                            "eine Transaktion); --dry-run prueft nur")
    p.add_argument("article_number")
    p.add_argument("--ts", help="Pflicht, sobald mehrere Sessions offen sind")
    p.add_argument("--dry-run", action="store_true",
                   help="alle Pruefungen und den Umzugsplan zeigen, nichts bewegen")

    p = sub.add_parser("discard-enroll-session",
                       help="eine Einlern-Session verwerfen (Rueckumzug, dann "
                            "nach data/verworfen/); --dry-run zeigt nur")
    p.add_argument("article_number")
    p.add_argument("--ts", help="Pflicht, sobald mehrere Sessions offen sind")
    p.add_argument("--dry-run", action="store_true",
                   help="Gegenrichtungs-Tabelle zeigen, nichts bewegen")

    p = sub.add_parser("corpus-build",
                       help="Regressions-Korpus aufbauen/aktualisieren "
                            "(idempotent, dedupliziert per SHA-256)")
    p.add_argument("--dry-run", action="store_true",
                   help="nur zaehlen, nichts schreiben")

    p = sub.add_parser("corpus-run", help="Korpus-Replay gegen die Goldens")
    p.add_argument("--tier", type=int, choices=(1, 2), default=1)
    p.add_argument("--session", action="append",
                   help="nur diese Session (mehrfach angebbar)")
    p.add_argument("--article", action="append",
                   help="nur diesen Artikel (mehrfach angebbar)")
    p.add_argument("--subset", type=int, default=None,
                   help="nur die ersten N Bilder (deterministisch)")
    p.add_argument("--workers", type=int, default=8,
                   help="Prozesse (Default 8 – gemessenes Optimum)")
    p.add_argument("--changed-only", action="store_true",
                   help="Ergebnis-Cache nutzen; invalidiert bei Code- oder "
                        "Schwellenaenderung automatisch")
    p.add_argument("--run-id", default=None)
    p.add_argument("--check", action="store_true",
                   help="gegen baseline.json pruefen, Exit 1 bei Regression")
    p.add_argument("--accept-drift", action="store_true",
                   help="DRIFT tolerieren (nur bei bewusstem Bibliotheks-"
                        "Update oder Plattformwechsel; Re-Baselining faellig)")
    p.add_argument("--update-baseline", action="store_true",
                   help="Baseline aus diesem Lauf neu schreiben "
                        "(Begruendung im Commit ist Pflicht)")
    p.add_argument("--report", action="store_true",
                   help="nach einem Lauf MIT Abweichungen die Drift-Review "
                        "erzeugen (reports/corpus/<run-id>/index.html)")

    p = sub.add_parser("corpus-diff", help="zwei Korpus-Laeufe vergleichen")
    p.add_argument("run_a")
    p.add_argument("run_b")

    p = sub.add_parser("corpus-report",
                       help="Drift-Review + Kennzahlen-Ansichten aus fertigen "
                            "Laeufen (PNG/CSV/HTML, rechnet nichts neu)")
    p.add_argument("--run", default=None,
                   help="Goldens gegen diesen Lauf (Default/'letzte': der "
                        "zuletzt geschriebene Tier-2-Lauf)")
    p.add_argument("--compare", nargs=2, metavar=("RUN_A", "RUN_B"),
                   default=None,
                   help="statt gegen die Goldens: Lauf gegen Lauf")
    p.add_argument("--publish", action="store_true",
                   help="Artefakte zusaetzlich ins versionierte Archiv "
                        "kopieren (analysis.publish_dir, Praefix 'corpus-')")

    p = sub.add_parser("corpus-triage",
                       help="Failures eines Laufs clustern (nur Befunde)")
    p.add_argument("run_id")

    args = parser.parse_args(argv)
    cfg = load_config(args.config)

    if args.sandbox is not None:
        # Reihenfolge ist Absicht und muss so bleiben: Sperre, dann Umlenken,
        # dann Anlegen. Ein gesperrter Befehl bricht ab, BEVOR irgendein
        # Verzeichnis entsteht – sonst hinterliesse jeder Fehlversuch einen
        # leeren Sandbox-Baum.
        pruefe_sandbox_sperre(args.cmd, args)
        try:
            cfg = sandbox_cfg(cfg, args.sandbox)
        except ValueError as e:
            sys.exit(f"[sandbox] {e}")
        neu = sandbox_verzeichnisse_anlegen(cfg)
        if neu:   # die Pfade selbst stehen schon in der Startmeldung darüber
            print(f"[sandbox] {len(neu)} Verzeichnis(se) neu angelegt.")

    {
        "init-db": cmd_init_db,
        "import-articles": cmd_import_articles,
        "list-articles": cmd_list_articles,
        "capture-background": cmd_capture_background,
        "calibrate": cmd_calibrate,
        "create-article": cmd_create_article,
        "batch-create": cmd_batch_create,
        "batch-enroll": cmd_batch_enroll,
        "delete-article": cmd_delete_article,
        "delete-references": cmd_delete_references,
        "enroll": cmd_enroll,
        "enrollment-sheet": cmd_enrollment_sheet,
        "contour-band": cmd_contour_band,
        "identify": cmd_identify,
        "evaluate": cmd_evaluate,
        "list-cameras": cmd_list_cameras,
        "ab-report": cmd_ab_report,
        "make-smoke-testset": cmd_make_smoke_testset,
        "sync-stammdaten": cmd_sync_stammdaten,
        "analyze": cmd_analyze,
        "analyze-floors": cmd_analyze_floors,
        "list-enroll-sessions": cmd_list_enroll_sessions,
        "show-enroll-session": cmd_show_enroll_session,
        "commit-enroll-session": cmd_commit_enroll_session,
        "discard-enroll-session": cmd_discard_enroll_session,
        "corpus-build": cmd_corpus_build,
        "corpus-run": cmd_corpus_run,
        "corpus-diff": cmd_corpus_diff,
        "corpus-report": cmd_corpus_report,
        "corpus-triage": cmd_corpus_triage,
    }[args.cmd](args, cfg)


if __name__ == "__main__":
    main()
