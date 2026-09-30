#!/usr/bin/env python3
"""
generate_synthetic_data.py

Generates a fully SYNTHETIC dataset that mimics the shape of DICOM study
metadata as it would sit in a raw intake table, BEFORE de-identification.

Every name, ID, date, and hospital below is invented by Faker or randomly
sampled from fixed lists. Nothing in this file is derived from, or traceable
to, any real patient, physician, or institution.

Output is reproducible: fixed seeds, a fixed reference date instead of
"today", and UIDs drawn from the seeded RNG. (Faker's name lists can still
differ between Faker versions.) About a third of patients have more than
one study, so the de-identified output can show that repeat studies still
link to the same patient_token.

Usage (from the repo root):
    python scripts/generate_synthetic_data.py --count 120 --out data/raw_studies.csv
"""

import argparse
import csv
import random
from datetime import date, timedelta

from faker import Faker

fake = Faker()
Faker.seed(42)
random.seed(42)

REFERENCE_DATE = date(2026, 9, 29)  # stands in for "today" so reruns are identical
REPEAT_PATIENT_RATE = 0.35          # chance a record belongs to an existing patient

MODALITIES = ["CT", "MRI", "X-RAY", "ULTRASOUND", "MAMMOGRAPHY", "PET"]
BODY_PARTS = [
    "CHEST", "ABDOMEN", "HEAD", "SPINE", "KNEE", "SHOULDER",
    "PELVIS", "LIVER", "BREAST", "LUNG",
]
MANUFACTURERS = ["Siemens Healthineers", "GE HealthCare", "Philips", "Canon Medical"]
HOSPITALS = [
    "Northgate General Hospital",
    "Meridian Health Center",
    "Harborview Imaging Institute",
    "Sunstone Medical City",
    "Crestline Diagnostics",
]
STUDY_DESCRIPTIONS = {
    "CHEST": "Routine chest screening",
    "ABDOMEN": "Abdominal pain workup",
    "HEAD": "Post-trauma head CT",
    "SPINE": "Lower back pain evaluation",
    "KNEE": "Post-injury knee MRI",
    "SHOULDER": "Rotator cuff evaluation",
    "PELVIS": "Pelvic pain workup",
    "LIVER": "Liver lesion follow-up",
    "BREAST": "Annual mammography screening",
    "LUNG": "Nodule follow-up scan",
}


def random_date(start=date(2023, 1, 1), end=REFERENCE_DATE):
    return start + timedelta(days=random.randint(0, (end - start).days))


def random_dob(min_age=1, max_age=90):
    age = random.randint(min_age, max_age)
    return REFERENCE_DATE - timedelta(days=age * 365 + random.randint(0, 364))


def age_on(dob: date, on: date) -> int:
    return on.year - dob.year - ((on.month, on.day) < (dob.month, dob.day))


def seeded_uid() -> str:
    return f"1.2.840.{random.getrandbits(40)}"


def new_patient() -> dict:
    return {
        "patient_name": fake.name(),
        "patient_id": f"MRN{random.randint(1000000, 9999999)}",
        "patient_birth_date": random_dob(),
        "patient_sex": random.choice(["M", "F"]),
    }


def make_record(i: int, patients: list) -> dict:
    if patients and random.random() < REPEAT_PATIENT_RATE:
        patient = random.choice(patients)
    else:
        patient = new_patient()
        patients.append(patient)
    body_part = random.choice(BODY_PARTS)
    modality = random.choice(MODALITIES)
    dob = patient["patient_birth_date"]
    study_date = random_date(start=max(date(2023, 1, 1), dob + timedelta(days=30)))
    age = age_on(dob, study_date)

    return {
        "study_id": f"STU-{i:05d}",
        "sop_instance_uid": seeded_uid(),
        "series_uid": seeded_uid(),
        "accession_number": f"ACC{random.randint(100000, 999999)}",
        "modality": modality,
        "body_part_examined": body_part,
        "study_date": study_date.isoformat(),
        "study_description": STUDY_DESCRIPTIONS[body_part],
        "institution_name": random.choice(HOSPITALS),
        "manufacturer": random.choice(MANUFACTURERS),
        "rows": random.choice([512, 1024, 2048]),
        "columns": random.choice([512, 1024, 2048]),
        "slice_thickness": round(random.uniform(0.5, 5.0), 1),
        "pixel_spacing": f"{round(random.uniform(0.3, 1.2), 2)}\\{round(random.uniform(0.3, 1.2), 2)}",
        # --- PHI fields: these must never survive de-identification ---
        "patient_name": patient["patient_name"],
        "patient_id": patient["patient_id"],
        "patient_birth_date": dob.isoformat(),
        "patient_sex": patient["patient_sex"],
        "patient_age": f"{age:03d}Y",  # age at the study date, as in DICOM
        "referring_physician": f"Dr. {fake.last_name()}",
        "burned_in_annotation": random.choice([
            "", "", "", "",  # most studies have no burned-in text
            f"PT: {fake.last_name()}",
            f"{fake.name()} - {study_date.isoformat()}",
        ]),
    }


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic DICOM study metadata")
    parser.add_argument("--count", type=int, default=120, help="Number of records to generate")
    parser.add_argument("--out", type=str, default="data/raw_studies.csv", help="Output CSV path")
    args = parser.parse_args()

    patients: list = []
    records = [make_record(i + 1, patients) for i in range(args.count)]

    fieldnames = list(records[0].keys())
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)

    print(f"Wrote {len(records)} synthetic records ({len(patients)} patients) to {args.out}")


if __name__ == "__main__":
    main()
