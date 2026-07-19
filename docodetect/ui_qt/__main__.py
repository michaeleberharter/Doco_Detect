"""Entry point: python -m docodetect.ui_qt [--demo] [--config PFAD]."""

from __future__ import annotations

import argparse
import sys


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(prog="docodetect.ui_qt",
                                 description="Doco Detect – Bediener-UI")
    ap.add_argument("--demo", action="store_true",
                    help="Testbilder statt Kamera (Entwicklungsmodus)")
    ap.add_argument("--config", default=None, help="Pfad zu config.yaml")
    args = ap.parse_args(argv)

    from docodetect.config import load_config

    from .app import run
    cfg = load_config(args.config)
    if args.demo:
        # Demo darf die echte Einrichtung nie anfassen: alle Schreib-Pfade
        # (DB, Kalibrierung, Hintergrund, Captures) nach data/demo/.
        from .demo_source import apply_demo_paths
        cfg = apply_demo_paths(cfg)
    return run(cfg, demo=args.demo)


if __name__ == "__main__":
    sys.exit(main())
