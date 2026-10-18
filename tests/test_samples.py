"""
End-to-end run of the pipeline over the committed sample DICOM files
(tests/data/dicom/): compressed multi-frame XA angiography and RLE
palette-colour ultrasound.
"""

import pytest

from conftest import REPO_ROOT, TEST_SECRET
from dicom_deid.db import make_engine
from dicom_deid.pipeline import db_report, ingest

SAMPLES = REPO_ROOT / "tests" / "data" / "dicom"
pytestmark = pytest.mark.skipif(not any(SAMPLES.glob("*.DCM")), reason="sample DICOM files not present")


def test_samples_ingest(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'deid.sqlite').as_posix()}")
    summary = ingest(SAMPLES, tmp_path / "out", tmp_path / "q", engine, secret=TEST_SECRET)
    assert summary.failed == 0 and summary.not_dicom == 0
    # XA and US without BurnedInAnnotation must never be auto-released
    assert summary.quarantined == 5 and summary.clean == 0
    report = db_report(engine)
    assert report["patients"] == 4  # two XA files belong to the same patient...
    assert report["instances"] == 5
    assert report["series_by_modality"] == {"XA": 3, "US": 1}  # ...and the same series


def test_samples_no_leak(tmp_path):
    import pydicom

    db_file = tmp_path / "deid.sqlite"
    engine = make_engine(f"sqlite:///{db_file.as_posix()}")
    ingest(SAMPLES, tmp_path / "out", tmp_path / "q", engine, secret=TEST_SECRET)
    engine.dispose()

    phi = set()
    for path in SAMPLES.glob("*.DCM"):
        ds = pydicom.dcmread(path, stop_before_pixels=True)
        for kw in ("PatientID", "PatientBirthDate", "AccessionNumber", "InstitutionName",
                   "StudyInstanceUID", "SOPInstanceUID"):
            if str(ds.get(kw, "") or "").strip():
                phi.add(str(ds.get(kw)).strip())
        pn = ds.get("PatientName")
        if pn:
            phi.update(p for p in (pn.family_name, pn.given_name) if p)
    phi = {v for v in phi if len(v) >= 4}
    assert phi

    blobs = [db_file.read_bytes()] + [p.read_bytes() for p in (tmp_path / "q").rglob("*.dcm")]
    assert not {v for v in phi if any(v.encode() in b for b in blobs)}
