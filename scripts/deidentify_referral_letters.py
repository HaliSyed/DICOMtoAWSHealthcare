#!/usr/bin/env python3
"""
deidentify_referral_letters.py

Path B, offline: de-identifies the synthetic referral letters in
data/referral_letters/ (the free-text documents that, in production, would
go through Amazon Textract for OCR and Amazon Comprehend Medical for PHI
detection).

Labelled fields ("Patient Name:", "Date of Birth:", ...) are harvested and
every occurrence of their values is replaced -- so the doctor's name in the
signature is caught too -- then addresses, phone numbers and dates are
swept by pattern.

Usage (from the repo root):
    python scripts/deidentify_referral_letters.py --in data/referral_letters --out data/referral_letters_deid
"""

import argparse
from pathlib import Path

from dicom_deid.text_deid import redact_referral_letter


def main():
    parser = argparse.ArgumentParser(description="De-identify synthetic referral letters (offline)")
    parser.add_argument("--in", dest="indir", type=Path, default=Path("data/referral_letters"))
    parser.add_argument("--out", dest="outdir", type=Path, default=Path("data/referral_letters_deid"))
    args = parser.parse_args()

    args.outdir.mkdir(parents=True, exist_ok=True)
    letters = sorted(args.indir.glob("*.txt"))
    for path in letters:
        redacted, counts = redact_referral_letter(path.read_text(encoding="utf-8"))
        (args.outdir / path.name).write_text(redacted, encoding="utf-8")
        summary = ", ".join(f"{k} x{v}" for k, v in sorted(counts.items()))
        print(f"{path.name}: {summary}")

    print(f"\nDe-identified {len(letters)} letters -> {args.outdir}")
    if letters:
        print("\n--- Sample: after ---")
        print((args.outdir / letters[0].name).read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
