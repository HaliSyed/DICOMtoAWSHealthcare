"""The `basic` and `utility` de-identification profiles.

`utility` keeps exact age (in its finest DICOM unit), size and weight for
research on age; everything else, including tokens, UIDs and date shifts,
must be identical to `basic` so the two outputs stay linkable.
"""
from datetime import date

import pydicom
import pytest
from pydicom.dataset import Dataset

from conftest import TEST_SECRET
from dicom_deid.db import DeidAuditEvent, make_engine
from dicom_deid.dicom_deid import _utility_age, age_string, deidentify
from dicom_deid.pipeline import ingest
from dicom_deid.verify import find_residual_phi
from sqlalchemy import select
from sqlalchemy.orm import Session

from test_pipeline import _raw_phi


def _first_ct(synthetic_dir):
    for path in sorted(synthetic_dir.rglob("IM*")):
        ds = pydicom.dcmread(path)
        if ds.Modality == "CT":
            ds.PatientSize, ds.PatientWeight = "1.72", "68.5"
            return path, ds
    pytest.skip("no CT in synthetic set")


@pytest.mark.parametrize("birth, ref, expected", [
    (date(2026, 1, 1), date(2026, 1, 1), "000D"),     # day of birth
    (date(2026, 1, 1), date(2026, 1, 11), "010D"),    # newborn
    (date(2026, 1, 1), date(2026, 1, 28), "027D"),    # last day reported in days
    (date(2026, 1, 1), date(2026, 1, 29), "004W"),    # 28 days -> weeks
    (date(2026, 1, 1), date(2026, 5, 21), "020W"),    # 140 days
    (date(2026, 1, 1), date(2026, 8, 5), "007M"),     # past 26 weeks -> months
    (date(2020, 3, 15), date(2024, 3, 14), "047M"),   # one day before 4 years
    (date(2020, 3, 15), date(2024, 3, 15), "004Y"),   # 4th birthday -> years
    (date(1933, 6, 1), date(2026, 5, 31), "092Y"),    # over 90: kept exact in utility
    (date(2026, 2, 1), date(2026, 1, 1), None),       # birth after study: unusable
])
def test_age_string_uses_finest_unit(birth, ref, expected):
    assert age_string(birth, ref) == expected


@pytest.mark.filterwarnings("ignore:Invalid value for VR AS")
def test_utility_age_without_birth_date_keeps_recorded_value():
    ds = Dataset()
    ds.PatientAge = "005M"
    assert _utility_age(ds) == "005M"
    ds.PatientAge = "45Y"  # malformed: dropped, not guessed
    assert _utility_age(ds) is None


def test_utility_keeps_age_size_weight_and_nothing_else(synthetic_dir):
    _, ds = _first_ct(synthetic_dir)
    _, ds2 = _first_ct(synthetic_dir)
    expected_age = age_string(date.fromisoformat(f"{ds.PatientBirthDate[:4]}-{ds.PatientBirthDate[4:6]}-{ds.PatientBirthDate[6:]}"),
                              date.fromisoformat(f"{ds.StudyDate[:4]}-{ds.StudyDate[4:6]}-{ds.StudyDate[6:]}"))

    basic = deidentify(ds, TEST_SECRET)
    utility = deidentify(ds2, TEST_SECRET, profile="utility")
    b, u = basic.dataset, utility.dataset

    for kw in ("PatientAge", "PatientSize", "PatientWeight"):
        assert kw not in b, kw
    assert u.PatientAge == expected_age
    assert str(u.PatientSize) == "1.72" and str(u.PatientWeight) == "68.5"

    # linkage is identical: same token, date shift, UIDs, age band
    assert utility.patient_token == basic.patient_token
    assert utility.shift_days == basic.shift_days
    assert utility.age_band == basic.age_band
    for kw in ("StudyDate", "StudyInstanceUID", "SeriesInstanceUID", "SOPInstanceUID", "AccessionNumber"):
        assert u[kw].value == b[kw].value, kw

    assert "utility" in u.DeidentificationMethod and "utility" not in b.DeidentificationMethod
    assert len(u.DeidentificationMethod) <= 64
    assert find_residual_phi(u, utility.original_identifiers, utility.patient_token) == []


def test_unknown_profile_is_refused(synthetic_dir):
    _, ds = _first_ct(synthetic_dir)
    with pytest.raises(ValueError):
        deidentify(ds, TEST_SECRET, profile="research")


def test_utility_ingest_has_no_leaks_and_records_profile(synthetic_dir, tmp_path):
    db_file = tmp_path / "deid.sqlite"
    engine = make_engine(f"sqlite:///{db_file.as_posix()}")
    summary = ingest(synthetic_dir, tmp_path / "out", tmp_path / "q", engine, secret=TEST_SECRET, profile="utility")
    assert summary.failed == 0
    with Session(engine) as s:
        versions = set(s.scalars(select(DeidAuditEvent.profile_version)))
    engine.dispose()
    assert versions and all("utility" in v for v in versions)

    phi = _raw_phi(synthetic_dir)
    blobs = [db_file.read_bytes()] + [p.read_bytes() for p in tmp_path.rglob("*.dcm")]
    assert {v for v in phi for blob in blobs if v.encode() in blob} == set()
    # exact age survives in the released files
    released = [pydicom.dcmread(p) for p in (tmp_path / "out").rglob("*.dcm")]
    assert released and all("PatientAge" in d for d in released)
