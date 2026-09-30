from datetime import date

from conftest import TEST_SECRET
from dicom_deid.pseudonym import (
    MAX_SHIFT_WEEKS,
    age_at,
    age_band,
    date_shift_days,
    patient_token,
    remap_uid,
)


def test_patient_token_is_deterministic_and_keyed():
    a = patient_token("MRN1234567", TEST_SECRET)
    assert a == patient_token("MRN1234567", TEST_SECRET)
    assert a != patient_token("MRN1234568", TEST_SECRET)
    assert a != patient_token("MRN1234567", b"another-secret")
    assert a.startswith("PT-") and "1234567" not in a


def test_date_shift_whole_weeks_never_zero():
    shifts = {date_shift_days(patient_token(f"MRN{i}", TEST_SECRET), TEST_SECRET) for i in range(500)}
    assert all(s % 7 == 0 and s != 0 for s in shifts)
    assert all(abs(s) <= MAX_SHIFT_WEEKS * 7 for s in shifts)
    assert any(s < 0 for s in shifts) and any(s > 0 for s in shifts)


def test_remapped_uid_is_valid_and_stable():
    uid = remap_uid("1.2.826.0.1.3680043.8.498.12345", TEST_SECRET)
    assert uid == remap_uid("1.2.826.0.1.3680043.8.498.12345", TEST_SECRET)
    assert uid.startswith("2.25.") and len(uid) <= 64
    assert all(part.isdigit() for part in uid.split("."))


def test_age_and_bands():
    assert age_at(date(1990, 6, 15), date(2020, 6, 14)) == 29
    assert age_at(date(1990, 6, 15), date(2020, 6, 15)) == 30
    assert age_band(0) == "0-9"
    assert age_band(45) == "40-49"
    assert age_band(93) == "90+"
    assert age_band(None) == "unknown"
