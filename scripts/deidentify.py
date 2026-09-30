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
    6. study_date             -> date-shifted per patient by whole weeks
                                  (keeps day-of-week patterns and the gaps
                                  between one patient's studies, breaks the
                                  link to the real calendar date)
    7. All PHI columns removed entirely from the output schema, not just
       blanked -- an empty column is still a column an audit has to explain.

This is the CSV teaching demo. The token, date-shift and redaction logic is
shared with the DICOM pipeline (src/dicom_deid), so a patient gets the same
token here as in the DICOM database. For free text in production, use
Amazon Comprehend Medical's DetectPHI -- see
deidentify_with_comprehend_medical.py.
"""

import argparse
import csv
from datetime import date

from dicom_deid.pseudonym import age_at, age_band, date_shift_days, patient_token, shift_date
from dicom_deid.text_deid import redact_free_text

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


def deidentify_record(raw: dict) -> dict:
    token = patient_token(raw["patient_id"])
    study_date = date.fromisoformat(raw["study_date"])
    # Age at the time of the study, not today -- otherwise the output
    # changes depending on the day the script is run.
    band = age_band(age_at(date.fromisoformat(raw["patient_birth_date"]), study_date))
    shifted_date = shift_date(study_date, date_shift_days(token)).isoformat()
    redacted_annotation = redact_free_text(raw["burned_in_annotation"])

    fields_removed = ",".join(PHI_COLUMNS + QUASI_IDENTIFIER_COLUMNS_TO_DROP)

    drop_cols = set(PHI_COLUMNS) | set(QUASI_IDENTIFIER_COLUMNS_TO_DROP)
    record = {k: v for k, v in raw.items() if k not in drop_cols}
    del record["study_date"]  # original date dropped entirely
    record["patient_token"] = token
    record["age_band"] = band
    record["study_date_shifted"] = shifted_date
    record["burned_in_annotation_redacted"] = redacted_annotation
    record["deid_status"] = "COMPLETE"
    record["phi_fields_removed"] = fields_removed

    return record


def main():
    parser = argparse.ArgumentParser(description="De-identify synthetic study metadata")
    parser.add_argument("--in", dest="infile", default="data/raw_studies.csv")
    parser.add_argument("--out", dest="outfile", default="data/deidentified_studies.csv")
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
