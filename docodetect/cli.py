"""Command-line interface.

    python -m docodetect.cli init-db
    python -m docodetect.cli import-articles data/articles_example.csv
    python -m docodetect.cli capture-background
    python -m docodetect.cli calibrate [--image foto.jpg]
    python -m docodetect.cli create-article "Suppenloeffel" [--height-mm 0]
    python -m docodetect.cli delete-article ART-NR
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
from .config import load_config, resolve
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
    # verwaistes jpg hinterlässt (womöglich im Ordner eines anderen Artikels).
    img_path = None
    if store_photo:
        ref_dir = resolve(cfg["paths"]["reference_dir"]) / number
        img_path = str(ref_dir / f"{int(time.time() * 1000)}.jpg")

    article, feats, _ = pipe.create_article(
        img, name, article_number=number, height_mm=height_mm,
        category=category, image_path=img_path)

    if img_path:
        Path(img_path).parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(img_path, img)
    return article, feats


def _format_created(article) -> str:
    geo = (f"Ø {article.diameter_mm:.1f} mm" if article.diameter_mm
           else f"{article.width_mm:.1f} × {article.depth_mm:.1f} mm")
    return (f"'{article.name}' angelegt als {article.article_number}  "
            f"({geo}, Farbe: {article.color_desc})")


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
    stored = 0
    i = 0
    while i < shots:
        if input(f"  shot {i + 1}/{shots} > ").strip().lower() == "q":
            break
        img = cam.capture()
        img_path = ref_dir / f"{int(time.time() * 1000)}.jpg"
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


def main(argv=None):
    parser = argparse.ArgumentParser(prog="docodetect")
    parser.add_argument("--config", default=None, help="path to config.yaml")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init-db")

    p = sub.add_parser("import-articles")
    p.add_argument("csv")

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
    p.add_argument("--shots", type=int, default=8,
                   help="Aufnahmen je Artikel (Default: 8)")

    p = sub.add_parser("delete-article", help="remove an article incl. its references")
    p.add_argument("article_number")

    p = sub.add_parser("enroll")
    p.add_argument("article_number")
    p.add_argument("--shots", type=int, default=8)
    p.add_argument("--images", help="enroll from a folder of photos instead of live capture")

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

    args = parser.parse_args(argv)
    cfg = load_config(args.config)

    {
        "init-db": cmd_init_db,
        "import-articles": cmd_import_articles,
        "capture-background": cmd_capture_background,
        "calibrate": cmd_calibrate,
        "create-article": cmd_create_article,
        "batch-create": cmd_batch_create,
        "batch-enroll": cmd_batch_enroll,
        "delete-article": cmd_delete_article,
        "enroll": cmd_enroll,
        "identify": cmd_identify,
        "evaluate": cmd_evaluate,
        "list-cameras": cmd_list_cameras,
        "ab-report": cmd_ab_report,
        "make-smoke-testset": cmd_make_smoke_testset,
        "sync-stammdaten": cmd_sync_stammdaten,
        "analyze": cmd_analyze,
    }[args.cmd](args, cfg)


if __name__ == "__main__":
    main()
