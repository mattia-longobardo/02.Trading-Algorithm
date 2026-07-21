"""CLI della pipeline: python -m etoro_bot.main.

Esegue sempre una run reale nell'ambiente scelto dalle impostazioni effettive
(demo o real): non esiste più una modalità dry-run. L'unico modo per non
muovere denaro vero è l'ambiente demo di eToro stesso, oppure kill switch e
circuit breaker. Exit code 1 se la riconciliazione fallisce (run fermata, fail-safe).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from etoro_bot.graph.nodes.reconcile import ReconcileError
from etoro_bot.graph.runner import RunInProgressError, run_pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="eToro multi-agent swing trading bot")
    parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    try:
        summary = run_pipeline()
    except ReconcileError as exc:
        print(f"run fermata (riconciliazione fallita): {exc}", file=sys.stderr)
        return 1
    except RunInProgressError as exc:
        print(f"run non avviata: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
