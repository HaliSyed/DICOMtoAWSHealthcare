#!/usr/bin/env python3
"""
deidentify_with_comprehend_medical.py

REFERENCE ONLY -- this is the production-path equivalent of deidentify.py's
regex-based redact_free_text() function, using Amazon Comprehend Medical's
DetectPHI API instead of a hand-written pattern.

This script requires:
    - An AWS account with Comprehend Medical access
    - Credentials configured (aws configure / environment variables / role)
    - boto3 installed (pip install boto3)

It is NOT wired into the main deidentify.py pipeline on purpose -- keeping
the offline demo runnable without AWS credentials during the workshop.
Use this file to show the audience what the real call looks like, then
point back at the regex version for "what we're actually running today."

Region: Comprehend Medical is only offered in some AWS regions (not the UAE
region me-central-1 at the time of writing). Sending PHI to another country
is a cross-border transfer -- check it against your data-residency rules
before pointing this at real data. Synthetic data only in this repo.

Usage:
    python scripts/deidentify_with_comprehend_medical.py --text "Some referral text"
    python scripts/deidentify_with_comprehend_medical.py --file data/referral_letters/referral_001.txt
"""

import argparse
import json
import os

import boto3


def detect_phi(text: str, region: str = "us-east-1") -> list[dict]:
    """
    Calls Amazon Comprehend Medical's DetectPHI operation and returns the
    list of detected PHI entities: type, text, confidence score, and
    character offsets.
    """
    client = boto3.client("comprehendmedical", region_name=region)
    response = client.detect_phi(Text=text)
    return response["Entities"]


def redact(text: str, entities: list[dict]) -> str:
    """
    Replaces each detected PHI span with [REDACTED: <TYPE>], working from
    the end of the string backwards so earlier offsets stay valid.
    """
    redacted = text
    for entity in sorted(entities, key=lambda e: e["BeginOffset"], reverse=True):
        start, end = entity["BeginOffset"], entity["EndOffset"]
        redacted = redacted[:start] + f"[REDACTED:{entity['Type']}]" + redacted[end:]
    return redacted


def main():
    parser = argparse.ArgumentParser(description="Detect and redact PHI via Comprehend Medical")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--text", help="Free text to scan for PHI")
    source.add_argument("--file", help="Text file to scan (e.g. a referral letter)")
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    args = parser.parse_args()

    text = args.text if args.text is not None else open(args.file, encoding="utf-8").read()
    entities = detect_phi(text, region=args.region)

    print("Detected entities:")
    print(json.dumps(entities, indent=2, default=str))

    print("\nRedacted text:")
    print(redact(text, entities))


if __name__ == "__main__":
    main()
