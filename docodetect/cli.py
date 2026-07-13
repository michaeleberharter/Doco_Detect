"""Command-line interface.

    python -m docodetect.cli init-db
    python -m docodetect.cli import-articles data/articles_example.csv
    python -m docodetect.cli capture-background
    python -m docodetect.cli calibrate [--image foto.jpg]
    python -m docodetect.cli enroll ART-NR --shots 8 [--images dir/]
    python -m docodetect.cli identify [--image foto.jpg]
    python -m docodetect.cli evaluate data/testset/

`evaluate` expects a folder layout of  testset/<article_number>/*.jpg
and prints per-class accuracy + the confusion pairs (that output decides
whether stage 2 is needed at all).
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from .calibration import run_calibration, save_background
from .camera import BoxCamera, load_image
from .config import load_config, resolve
from .database import Database
from .pipeline import Pipeline


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


def cmd_enroll(args, cfg):
    pipe = Pipeline(cfg)
    ref_dir = resolve(cfg["paths"]["reference_dir"]) / args.article_number
    ref_dir.mkdir(parents=True, exist_ok=True)

    if args.images:  # enroll from existing photos
        paths = sorted(Path(args.images).glob("*.[jp][pn]g"))
        if not paths:
            sys.exit(f"No images found in {args.images}")
        for p in paths:
            feats = pipe.enroll(load_image(p), args.article_number, str(p))
            print(f"  {p.name}: Ø {feats.circle_diameter_mm:.1f} mm (floor plane)")
        print(f"[enroll] {len(paths)} references stored for {args.article_number}")
        return

    print(f"[enroll] {args.shots} shots for {args.article_number}. "
          "Rotate/move the item between shots. ENTER = capture, q = abort.")
    with BoxCamera(cfg) as cam:
        for i in range(args.shots):
            if input(f"  shot {i + 1}/{args.shots} > ").strip().lower() == "q":
                break
            img = cam.capture()
            img_path = ref_dir / f"{int(time.time() * 1000)}.jpg"
            import cv2
            cv2.imwrite(str(img_path), img)
            feats = pipe.enroll(img, args.article_number, str(img_path))
            print(f"    Ø {feats.circle_diameter_mm:.1f} mm, "
                  f"circularity {feats.circularity:.3f}")
    pipe.close()


def _print_result(outcome):
    r = outcome.result
    print(f"\n[{r.decision.upper()}] {r.message}")
    if outcome.features:
        f = outcome.features
        print(f"  measured (floor plane): Ø {f.circle_diameter_mm:.1f} mm, "
              f"area {f.area_mm2 / 100:.1f} cm², circularity {f.circularity:.3f}")
    for i, c in enumerate(r.candidates, 1):
        ref = "" if c.has_references else "  [no references – geometry only]"
        print(f"  {i}. {c.article.article_number}  {c.article.name}  "
              f"score {c.score:.2f}  Δgeo {c.geometry_error_mm:.1f} mm{ref}")


def cmd_identify(args, cfg):
    pipe = Pipeline(cfg)
    outcome = pipe.identify(_get_image(args, cfg))
    _print_result(outcome)
    pipe.close()


def cmd_evaluate(args, cfg):
    pipe = Pipeline(cfg)
    testset = Path(args.testset)
    per_class = defaultdict(Counter)
    confusions = Counter()
    total = correct = 0

    for class_dir in sorted(p for p in testset.iterdir() if p.is_dir()):
        truth = class_dir.name
        for img_path in sorted(class_dir.glob("*.[jp][pn]g")):
            outcome = pipe.identify(load_image(img_path))
            pred = (outcome.result.candidates[0].article.article_number
                    if outcome.result.candidates else "NO_MATCH")
            total += 1
            per_class[truth][pred] += 1
            if pred == truth:
                correct += 1
            else:
                confusions[(truth, pred)] += 1
                print(f"  MISS {img_path.name}: {truth} -> {pred}")

    print(f"\n=== top-1 accuracy: {correct}/{total} "
          f"({100.0 * correct / max(total, 1):.1f} %) ===")
    if confusions:
        print("confusion pairs (truth -> predicted):")
        for (t, p), n in confusions.most_common():
            print(f"  {t} -> {p}: {n}x")
        print("\nThese pairs are the shortlist for stage 2 (embeddings) "
              "or for tightening tolerances/features.")
    pipe.close()


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

    p = sub.add_parser("enroll")
    p.add_argument("article_number")
    p.add_argument("--shots", type=int, default=8)
    p.add_argument("--images", help="enroll from a folder of photos instead of live capture")

    p = sub.add_parser("identify")
    p.add_argument("--image", help="use an image file instead of the camera")

    p = sub.add_parser("evaluate")
    p.add_argument("testset", help="folder: testset/<article_number>/*.jpg")

    args = parser.parse_args(argv)
    cfg = load_config(args.config)

    {
        "init-db": cmd_init_db,
        "import-articles": cmd_import_articles,
        "capture-background": cmd_capture_background,
        "calibrate": cmd_calibrate,
        "enroll": cmd_enroll,
        "identify": cmd_identify,
        "evaluate": cmd_evaluate,
    }[args.cmd](args, cfg)


if __name__ == "__main__":
    main()
