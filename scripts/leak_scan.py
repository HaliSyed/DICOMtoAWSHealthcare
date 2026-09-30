#!/usr/bin/env python3
"""
leak_scan.py

Independent check after `dicom-deid ingest`: collects PHI strings from the
RAW input files (names, MRNs, national IDs, DOBs, phones, physicians,
institution, device serials, original UIDs and dates) and searches for each
one, byte for byte, in every released/quarantined output file and in the raw
database file. Prints only counts and which kind of value leaked -- never
the value itself.

Usage (from the repo root, after synth + ingest):
    python scripts/leak_scan.py
"""

import argparse
import sys
from pathlib import Path

import pydicom
from pydicom.errors import InvalidDicomError


def collect_phi(raw_dir: Path) -> dict[str, str]:
    """PHI string -> the attribute it came from."""
    phi: dict[str, str] = {}
    for path in sorted(p for p in raw_dir.rglob("*") if p.is_file()):
        try:
            ds = pydicom.dcmread(path)
        except InvalidDicomError:
            continue
        values = {
            "PatientID": ds.get("PatientID"),
            "PatientBirthDate": ds.get("PatientBirthDate"),
            "OtherPatientIDs": ds.get("OtherPatientIDs"),
            "AccessionNumber": ds.get("AccessionNumber"),
            "PatientTelephoneNumbers": ds.get("PatientTelephoneNumbers"),
            "PatientAddress (first 15 chars)": str(ds.get("PatientAddress", ""))[:15],
            "InstitutionName": ds.get("InstitutionName"),
            "DeviceSerialNumber": ds.get("DeviceSerialNumber"),
            "StudyInstanceUID": ds.get("StudyInstanceUID"),
            "SOPInstanceUID": ds.get("SOPInstanceUID"),
            "StudyDate": ds.get("StudyDate"),
        }
        for kw in ("PatientName", "ReferringPhysicianName", "OperatorsName", "PerformingPhysicianName"):
            pn = ds.get(kw)
            if pn:
                values[f"{kw}.family"] = pn.family_name
                values[f"{kw}.given"] = pn.given_name
        for source, value in values.items():
            if value and len(str(value)) >= 4:
                phi.setdefault(str(value), source)
    return phi


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan de-identified outputs for leaked PHI")
    parser.add_argument("--raw", type=Path, default=Path("data/dicom/raw"))
    parser.add_argument("--outputs", type=Path, nargs="+",
                        default=[Path("data/dicom/deid"), Path("data/dicom/quarantine")])
    parser.add_argument("--db-file", type=Path, default=Path("data/db/deid.sqlite"))
    args = parser.parse_args()

    phi = collect_phi(args.raw)
    targets = [p for d in args.outputs for p in d.rglob("*.dcm")]
    if args.db_file.is_file():
        targets.append(args.db_file)
    blobs = [p.read_bytes() for p in targets]

    leaked_sources = sorted({src for value, src in phi.items() if any(value.encode() in b for b in blobs)})
    print(f"PHI values collected from raw input: {len(phi)}")
    print(f"Files scanned: {len(targets)} ({len(targets) - args.db_file.is_file()} DICOM + database)")
    if leaked_sources:
        print(f"LEAKS FOUND in: {', '.join(leaked_sources)}")
        return 1
    print("Leaks found: 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
