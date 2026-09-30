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

    p = sub.add_parser("inspect", help="summarise DICOM files (no PHI values shown) and optionally export PNG previews")
    p.add_argument("paths", type=Path, nargs="+", help="DICOM files or folders")
    p.add_argument("--export-png", type=Path, metavar="DIR",
                   help="write frames as PNG (raw pixels: burned-in text survives, keep under data/dicom/)")
    p.add_argument("--every", type=int, default=1, help="with --export-png: every Nth frame")
    p.add_argument("--max-frames", type=int, help="with --export-png: at most this many frames per file")
    p.add_argument("--json", action="store_true", help="print full details as JSON")

    args = parser.parse_args(argv)

    if args.command == "inspect":
        return _inspect(args)

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


def _inspect(args) -> int:
    from pydicom.errors import InvalidDicomError

    from .loader import export_png, read_info
    from .reader import iter_candidate_files

    infos, problems = [], 0
    for root in args.paths:
        for path in iter_candidate_files(root):
            try:
                info = read_info(path)
            except InvalidDicomError:
                continue
            infos.append(info)
            problems += not info.decodable and info.has_pixel_data
            if args.export_png and info.decodable:
                written = export_png(path, args.export_png, every_nth=args.every, max_frames=args.max_frames)
                print(f"{path.name}: {len(written)} PNG frame(s) -> {args.export_png}")

    if args.json:
        print(json.dumps([i.as_dict() for i in infos], indent=2))
        return 1 if problems else 0

    header = f"{'file':<14} {'mod':<5} {'transfer syntax':<28} {'size':>9} {'frames':>6} {'decodes':<7} {'identity':<10} burned-in risk"
    print(header)
    print("-" * len(header))
    for i in infos:
        size = f"{i.rows}x{i.columns}" if i.rows else "-"
        identity = "removed" if i.identity_removed else f"{len(i.identifying_attributes_present)} fields"
        decodes = "yes" if i.decodable else ("no" if i.has_pixel_data else "-")
        print(f"{i.file_name[:14]:<14} {str(i.modality or '-'):<5} {i.transfer_syntax[:28]:<28} {size:>9} "
              f"{i.frames:>6} {decodes:<7} {identity:<10} {'yes' if i.burned_in_risk else 'no'}")
    print(f"\n{len(infos)} DICOM file(s). 'identity: N fields' = N identifying attributes present (values not shown).")
    return 1 if problems else 0
