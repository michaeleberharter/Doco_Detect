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
    return run(load_config(args.config), demo=args.demo)


if __name__ == "__main__":
    sys.exit(main())
