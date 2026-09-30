"""
Offline, regex-based redaction for free text.

This is the teaching / no-network version. It only catches what a pattern
was written for; production uses Amazon Comprehend Medical DetectPHI (see
scripts/deidentify_with_comprehend_medical.py).
"""

import re

# Two capitalised words ("Allison Hill") or a "PT: Surname" label.
NAME_LIKE = re.compile(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b|PT: ?[A-Za-z]+")
ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
PHONE = re.compile(r"(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}(?:\s*x\d+)?")
# Any line ending in a US-style "ST 12345" postcode -- covers street addresses
# and military ones ("PSC 5116, Box 3726, APO AP 44084") that a
# street-number pattern misses.
POSTAL_ADDRESS_LINE = re.compile(r"^[^\n]*\b[A-Z]{2} \d{5}(?:-\d{4})?[ \t]*$", re.MULTILINE)

# Labelled fields in a referral letter -> placeholder used for the value.
LETTER_LABELS = {
    "Patient Name": "[PATIENT_NAME]",
    "Date of Birth": "[DOB]",
    "Referring Physician": "[PHYSICIAN]",
    "Phone": "[PHONE]",
    "Date": "[DATE]",
}


def redact_free_text(text: str) -> str:
    """Short annotation strings (e.g. DICOM burned-in text, descriptions)."""
    if not text:
        return ""
    text = NAME_LIKE.sub("[REDACTED]", text)
    return ISO_DATE.sub("[REDACTED-DATE]", text)


def redact_referral_letter(text: str) -> tuple[str, dict]:
    """
    Two passes:
      1. Harvest the values of labelled fields ("Patient Name: ...") and
         replace every occurrence of each value anywhere in the letter
         (so a signature repeating the doctor's name is caught too).
      2. Pattern sweep for addresses, phone numbers and dates.
    Returns the redacted text and a count of redactions per category.
    """
    counts: dict[str, int] = {}
    harvested: list[tuple[str, str]] = []
    for label, placeholder in LETTER_LABELS.items():
        for m in re.finditer(rf"^{re.escape(label)}:[ \t]*(.+?)[ \t]*$", text, flags=re.MULTILINE):
            harvested.append((m.group(1), placeholder))

    # Longest values first so "Dr. Amanda Diaz" is replaced before "Amanda".
    for value, placeholder in sorted(harvested, key=lambda p: len(p[0]), reverse=True):
        n = text.count(value)
        if n:
            text = text.replace(value, placeholder)
            counts[placeholder] = counts.get(placeholder, 0) + n

    for pattern, placeholder in (
        (POSTAL_ADDRESS_LINE, "[ADDRESS]"),
        (PHONE, "[PHONE]"),
        (ISO_DATE, "[DATE]"),
    ):
        text, n = pattern.subn(placeholder, text)
        if n:
            counts[placeholder] = counts.get(placeholder, 0) + n
    return text, counts
