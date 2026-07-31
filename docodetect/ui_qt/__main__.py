"""Entry point: python -m docodetect.ui_qt [--demo|--sandbox NAME] [--config PFAD]."""

from __future__ import annotations

import argparse
import sys


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(prog="docodetect.ui_qt",
                                 description="Doco Detect – Bediener-UI")
    ap.add_argument("--demo", action="store_true",
                    help="Testbilder statt Kamera (Entwicklungsmodus)")
    ap.add_argument("--sandbox", default=None, metavar="NAME",
                    help="isolierter Stand unter data/sandbox/NAME (DB, "
                         "Referenzen, Verworfene, Captures, Berichte). "
                         "Kalibrieren und Hintergrund-Aufnehmen sind darin "
                         "gesperrt, weil beide geteilt bleiben.")
    ap.add_argument("--config", default=None, help="Pfad zu config.yaml")
    args = ap.parse_args(argv)

    # Beides zusammen ergäbe zwei einander überschreibende Umlenkungen — und
    # die Demo lenkt Kalibrierung/Hintergrund mit um, die Sandbox bewusst
    # nicht. Welcher Stand dann gilt, wäre reine Reihenfolgen-Frage.
    if args.demo and args.sandbox is not None:
        print("[sandbox] --sandbox und --demo schliessen sich aus: die Demo "
              "lenkt auch Kalibrierung und Hintergrund um, die Sandbox teilt "
              "beide bewusst. Nur eines von beiden angeben.", file=sys.stderr)
        return 1

    from docodetect.config import load_config, sandbox_cfg

    cfg = load_config(args.config)
    if args.demo:
        # Demo darf die echte Einrichtung nie anfassen: alle Schreib-Pfade
        # (DB, Kalibrierung, Hintergrund, Captures) nach data/demo/.
        from .demo_source import apply_demo_paths
        cfg = apply_demo_paths(cfg)
    elif args.sandbox is not None:
        try:
            cfg = sandbox_cfg(cfg, args.sandbox)
        except ValueError as e:
            print(f"[sandbox] {e}", file=sys.stderr)
            return 1

    # Qt erst NACH der Argumentprüfung laden: ein Bedienfehler soll ohne
    # PySide6-Import abbrechen (schneller, und testbar ohne GUI-Stack).
    from .app import run
    return run(cfg, demo=args.demo)


if __name__ == "__main__":
    sys.exit(main())
