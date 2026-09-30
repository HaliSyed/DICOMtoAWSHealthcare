#!/usr/bin/env python3
"""
generate_referral_letters.py

Generates fully SYNTHETIC referral-letter text files, standing in for the
scanned PDFs that would go through the manual / Textract path (Path B).

These are plain .txt files for the workshop repo. In the live session, print
a few to PDF (or photocopy/scan them) so Textract has something to OCR.

Usage (from the repo root):
    python scripts/generate_referral_letters.py --count 10 --out data/referral_letters
"""

import argparse
import os
import random
from datetime import date, timedelta

from faker import Faker

fake = Faker()
Faker.seed(7)
random.seed(7)

REFERENCE_DATE = date(2026, 9, 29)  # stands in for "today" so reruns are identical

REASONS = [
    "persistent lower back pain",
    "suspected rotator cuff tear",
    "follow-up on a previously noted lung nodule",
    "unexplained abdominal discomfort",
    "annual breast screening",
    "post-fall head trauma evaluation",
]

CLINICS = [
    "Northgate Family Clinic",
    "Meridian Primary Care",
    "Harborview Community Health",
    "Sunstone Wellness Group",
]


def make_letter(i: int) -> str:
    patient_name = fake.name()
    patient_dob = (REFERENCE_DATE - timedelta(days=random.randint(18 * 365, 85 * 365))).isoformat()
    referring_doc = f"Dr. {fake.first_name()} {fake.last_name()}"
    clinic = random.choice(CLINICS)
    letter_date = (REFERENCE_DATE - timedelta(days=random.randint(1, 200))).isoformat()
    reason = random.choice(REASONS)
    phone = fake.phone_number()
    address = fake.address().replace("\n", ", ")

    return f"""{clinic}
{address}
Phone: {phone}

Date: {letter_date}

RE: Imaging Referral

Patient Name: {patient_name}
Date of Birth: {patient_dob}
Referring Physician: {referring_doc}

To the Radiology Department,

Please arrange imaging for the above-named patient regarding {reason}.
The patient has consented to this referral. Kindly send the report back
to our clinic upon completion.

Regards,
{referring_doc}
{clinic}
"""


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic referral letters")
    parser.add_argument("--count", type=int, default=10, help="Number of letters to generate")
    parser.add_argument("--out", type=str, default="data/referral_letters", help="Output directory")
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)
    for i in range(1, args.count + 1):
        text = make_letter(i)
        path = os.path.join(args.out, f"referral_{i:03d}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    print(f"Wrote {args.count} synthetic referral letters to {args.out}")


if __name__ == "__main__":
    main()
