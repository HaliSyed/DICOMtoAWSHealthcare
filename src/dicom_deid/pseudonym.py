"""
Pseudonymisation primitives shared by the DICOM pipeline and the CSV demo.

Everything here is keyed with HMAC-SHA256 (see config.get_secret). A plain
salted hash is not enough: MRNs come from a small, guessable space, so with a
public salt anyone could hash every possible MRN and reverse the token.
"""

import hashlib
import hmac
import uuid
from datetime import date, timedelta

from .config import get_secret

MAX_SHIFT_WEEKS = 26  # dates move by up to +/- 26 weeks (~6 months)


def _digest(purpose: str, value: str, secret: bytes | None = None) -> bytes:
    key = secret if secret is not None else get_secret()
    return hmac.new(key, f"{purpose}:{value}".encode("utf-8"), hashlib.sha256).digest()


def patient_token(patient_id: str, secret: bytes | None = None) -> str:
    """Same patient_id -> same token (studies stay linked); not reversible without the key."""
    return "PT-" + _digest("patient", patient_id.strip(), secret).hex()[:16].upper()


def accession_token(accession_number: str, secret: bytes | None = None) -> str:
    return "AC-" + _digest("accession", accession_number.strip(), secret).hex()[:12].upper()


def remap_uid(original_uid: str, secret: bytes | None = None) -> str:
    """
    Deterministic replacement UID under the 2.25 (UUID-derived) root, so the
    Study/Series/Instance hierarchy and cross-references survive
    de-identification while the original UIDs (which often embed site and
    device identifiers) do not.
    """
    raw = _digest("uid", original_uid.strip(), secret)[:16]
    return f"2.25.{uuid.UUID(bytes=raw, version=4).int}"


def date_shift_days(token: str, secret: bytes | None = None) -> int:
    """
    Per-patient offset in whole weeks, never zero. Whole weeks keep
    day-of-week patterns (weekend admissions, clinic days) intact, and one
    offset per patient keeps the intervals between their studies exact.
    """
    n = int.from_bytes(_digest("date-shift", token, secret)[:4], "big")
    weeks = n % (2 * MAX_SHIFT_WEEKS) - MAX_SHIFT_WEEKS  # -26 .. 25
    if weeks >= 0:
        weeks += 1  # -26 .. -1, 1 .. 26
    return weeks * 7


def shift_date(d: date, days: int) -> date:
    return d + timedelta(days=days)


def age_at(birth: date, on: date) -> int:
    return on.year - birth.year - ((on.month, on.day) < (birth.month, birth.day))


def age_band(age: int | None) -> str:
    """10-year bands; 90+ collapsed into one band (very old ages are rare enough to identify)."""
    if age is None or age < 0:
        return "unknown"
    if age >= 90:
        return "90+"
    start = (age // 10) * 10
    return f"{start}-{start + 9}"
