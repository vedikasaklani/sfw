"""Run the engine offline on a snapshot file, e.g.

    python -m app.recommendations ../docs/examples/recommendation-snapshot.json --backend lightfm
"""
import argparse
import json
import sys
from datetime import date

from app.recommendations import BACKENDS, HAS_LIGHTFM, recommend, resolve_backend


def main(argv=None):
    parser = argparse.ArgumentParser(description="Rank a recommendation-metadata 1.0 snapshot.")
    parser.add_argument("snapshot", help="path to a snapshot JSON file ('-' for stdin)")
    parser.add_argument("--backend", choices=BACKENDS, default="auto")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--today", type=date.fromisoformat, help="fix 'today' (YYYY-MM-DD) for reproducible recency weights")
    args = parser.parse_args(argv)
    snapshot = json.load(sys.stdin if args.snapshot == "-" else open(args.snapshot, encoding="utf-8"))
    engine = resolve_backend(args.backend)
    rows = recommend(snapshot, args.limit, today=args.today, backend=engine)
    json.dump({"engine": engine, "lightfm_installed": HAS_LIGHTFM, "items": rows}, sys.stdout, indent=2, ensure_ascii=False)
    print()


if __name__ == "__main__":
    main()
