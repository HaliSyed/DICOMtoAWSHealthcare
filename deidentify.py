#!/usr/bin/env python3
"""
deidentify.py

Takes the raw synthetic study table (data/raw_studies.csv) and produces a
de-identified version (data/deidentified_studies.csv), matching the pattern
described in the workshop:

    Raw intake  -->  De-identification  -->  Store & Index

What this script does to each record:
    1. patient_name          -> DROPPED
    2. patient_id             -> replaced with a one-way token (patient_token)
    3. patient_birth_date     -> DROPPED, replaced with a 10-year age_band
    4. referring_physician    -> DROPPED
    5. burned_in_annotation   -> scanned for leftover names/dates, redacted
    6. study_date             -> date-shifted per patient (keeps day-of-week
                                  patterns useful for research, breaks the
                                  link to the real calendar date)
    7. All PHI columns removed entirely from the output schema, not just
       blanked -- an empty column is still a column an audit has to explain.

This is a teaching / demo implementation. For a real deployment, use
Amazon Comprehend Medical's PHI detection (DetectPHI) as the production
path -- see the README for a working, commented example call.
"""

import argparse
import csv
import hashlib
import random
import re
from datetime import datetime, timedelta

# Fields that must never appear in the de-identified output.
PHI_COLUMNS = [
    "patient_name",
    "patient_id",
    "patient_birth_date",
    "referring_physician",
    "burned_in_annotation",
]

# Fields that aren't direct identifiers on their own, but are dropped anyway
# because a downstream field already carries the de-identified equivalent
# (exact age alongside age_band defeats the point of banding it).
QUASI_IDENTIFIER_COLUMNS_TO_DROP = [
    "patient_age",  # superseded by age_band
]

# Very small illustrative name-pattern matcher for the burned_in_annotation
# free-text field. A real pipeline uses Comprehend Medical's DetectPHI
# instead of regex -- this is here so the demo has something visible to
# show working end-to-end without an AWS call.
NAME_LIKE_PATTERN = re.compile(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b|PT: ?[A-Za-z]+")
# Dates in free text are identifying too (e.g. combined with a known visit
# date, they can re-link a "redacted" record) -- catch ISO dates as well.
DATE_LIKE_PATTERN = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


def tokenize_patient_id(patient_id: str, salt: str = "workshop-demo-salt") -> str:
    """
    One-way token: same input always produces the same token (so repeat
    studies for one patient still link together), but the token cannot be
    reversed back to the original MRN.
    """
    digest = hashlib.sha256(f"{salt}:{patient_id}".encode()).hexdigest()
    return f"PT-{digest[:10].upper()}"


def to_age_band(birth_date_str: str) -> str:
    """Collapse an exact birth date into a 10-year band, e.g. '40-49'."""
    dob = datetime.fromisoformat(birth_date_str).date()
    today = datetime.today().date()
    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    band_start = (age // 10) * 10
    return f"{band_start}-{band_start + 9}"


def shift_date(date_str: str, patient_token: str) -> str:
    """
    Shift a date by a consistent, per-patient offset derived from their
    token. Preserves relative timing between studies for the same patient
    while breaking the link to the real calendar date.
    """
    seed = int(hashlib.sha256(patient_token.encode()).hexdigest(), 16) % 365
    offset = timedelta(days=seed - 182)  # +/- ~6 months
    d = datetime.fromisoformat(date_str).date()
    return (d + offset).isoformat()


def redact_free_text(text: str) -> str:
    """Redact anything name-shaped out of a free-text field."""
    if not text:
        return ""
    text = NAME_LIKE_PATTERN.sub("[REDACTED]", text)
    text = DATE_LIKE_PATTERN.sub("[REDACTED-DATE]", text)
    return text


def deidentify_record(raw: dict) -> dict:
    patient_token = tokenize_patient_id(raw["patient_id"])
    age_band = to_age_band(raw["patient_birth_date"])
    shifted_date = shift_date(raw["study_date"], patient_token)
    redacted_annotation = redact_free_text(raw["burned_in_annotation"])

    fields_removed = ",".join(PHI_COLUMNS + QUASI_IDENTIFIER_COLUMNS_TO_DROP)

    drop_cols = set(PHI_COLUMNS) | set(QUASI_IDENTIFIER_COLUMNS_TO_DROP)
    record = {k: v for k, v in raw.items() if k not in drop_cols}
    record["patient_token"] = patient_token
    record["age_band"] = age_band
    record["study_date_shifted"] = shifted_date
    record["study_date"] = None  # drop original date entirely
    record["burned_in_annotation_redacted"] = redacted_annotation
    record["deid_status"] = "COMPLETE"
    record["phi_fields_removed"] = fields_removed
    del record["study_date"]

    return record


def main():
    parser = argparse.ArgumentParser(description="De-identify synthetic study metadata")
    parser.add_argument("--in", dest="infile", default="../data/raw_studies.csv")
    parser.add_argument("--out", dest="outfile", default="../data/deidentified_studies.csv")
    args = parser.parse_args()

    with open(args.infile, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        raw_records = list(reader)

    deidentified = [deidentify_record(r) for r in raw_records]

    fieldnames = list(deidentified[0].keys())
    with open(args.outfile, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(deidentified)

    print(f"De-identified {len(deidentified)} records -> {args.outfile}")
    print(f"PHI columns removed from schema: {', '.join(PHI_COLUMNS)}")

    # Quick spot-check printed to console for the live demo
    print("\n--- Sample: before vs after ---")
    sample_raw = raw_records[0]
    sample_deid = deidentified[0]
    print(f"BEFORE: patient_name={sample_raw['patient_name']!r}, "
          f"patient_id={sample_raw['patient_id']!r}, "
          f"patient_birth_date={sample_raw['patient_birth_date']!r}, "
          f"study_date={sample_raw['study_date']!r}")
    print(f"AFTER:  patient_token={sample_deid['patient_token']!r}, "
          f"age_band={sample_deid['age_band']!r}, "
          f"study_date_shifted={sample_deid['study_date_shifted']!r}")


if __name__ == "__main__":
    main()
