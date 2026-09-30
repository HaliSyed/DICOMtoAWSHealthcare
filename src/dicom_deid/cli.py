"""
Command line entry point:  dicom-deid <command>   (or: python -m dicom_deid <command>)

  synth    generate synthetic DICOM files with (fake) PHI
  ingest   read -> de-identify -> verify -> store files + local DB
  report   summarise what is in the database
"""

import argparse
import json
from pathlib import Path

from .db import make_engine
from .pipeline import db_report, ingest
from .synthetic import generate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dicom-deid", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", help="SQLAlchemy URL (default: $DATABASE_URL or sqlite:///data/db/deid.sqlite)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("synth", help="generate synthetic DICOM files")
    p.add_argument("--out", type=Path, default=Path("data/dicom/raw"))
    p.add_argument("--patients", type=int, default=6)
    p.add_argument("--seed", type=int, default=42)

    p = sub.add_parser("ingest", help="de-identify a folder of DICOM files into the local DB")
    p.add_argument("--src", type=Path, default=Path("data/dicom/raw"))
    p.add_argument("--out", type=Path, default=Path("data/dicom/deid"))
    p.add_argument("--quarantine", type=Path, default=Path("data/dicom/quarantine"))

    sub.add_parser("report", help="summarise the database contents")

    args = parser.parse_args(argv)

    if args.command == "synth":
        files = generate(args.out, patients=args.patients, seed=args.seed)
        print(f"Wrote {len(files)} synthetic DICOM files (+1 non-DICOM decoy) to {args.out}")
        return 0

    engine = make_engine(args.db)
    if args.command == "ingest":
        if not args.src.exists():
            parser.error(f"source not found: {args.src} (run 'dicom-deid synth' first?)")
        summary = ingest(args.src, args.out, args.quarantine, engine)
        print(json.dumps(summary.as_dict(), indent=2))
        print(f"Released -> {args.out}   Held for review -> {args.quarantine}   DB -> {engine.url}")
        return 1 if summary.failed else 0

    print(json.dumps(db_report(engine), indent=2, default=str))
    return 0
