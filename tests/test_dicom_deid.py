import pydicom
import pytest
from pydicom.data import get_testdata_file
from pydicom.dataset import Dataset
from pydicom.sequence import Sequence

from conftest import TEST_SECRET
from dicom_deid.dicom_deid import burned_in_risk, deidentify
from dicom_deid.pseudonym import date_shift_days
from dicom_deid.verify import find_residual_phi


def _first_ct(synthetic_dir):
    for path in sorted(synthetic_dir.rglob("IM*")):
        ds = pydicom.dcmread(path)
        if ds.Modality in ("CT", "MR"):
            return ds
    pytest.skip("no CT/MR in synthetic set")


def test_direct_identifiers_removed(synthetic_dir):
    ds = _first_ct(synthetic_dir)
    original = {
        "name": str(ds.PatientName), "mrn": ds.PatientID, "dob": ds.PatientBirthDate,
        "national_id": ds.OtherPatientIDs, "accession": ds.AccessionNumber,
    }
    result = deidentify(ds, TEST_SECRET)
    out = result.dataset

    assert str(out.PatientName) == out.PatientID == result.patient_token
    assert out.PatientBirthDate == ""
    assert out.AccessionNumber.startswith("AC-") and out.AccessionNumber != original["accession"]
    for kw in ("OtherPatientIDs", "PatientAddress", "PatientTelephoneNumbers", "InstitutionName",
               "OperatorsName", "PerformingPhysicianName", "PatientAge", "DeviceSerialNumber"):
        assert kw not in out, kw
    assert not any(e.tag.is_private for e in out.iterall())
    assert out.PatientIdentityRemoved == "YES"
    assert len(out.DeidentificationMethod) <= 64
    dump = str(out)
    for value in original.values():
        assert value not in dump


def test_person_name_inside_sequence_is_emptied(synthetic_dir):
    ds = _first_ct(synthetic_dir)
    assert ds.RequestAttributesSequence[0].ScheduledPerformingPhysicianName
    out = deidentify(ds, TEST_SECRET).dataset
    item = out.RequestAttributesSequence[0]
    assert item.ScheduledPerformingPhysicianName == ""
    assert "RequestedProcedureID" not in item


def test_dates_shifted_consistently_and_uids_remapped(synthetic_dir):
    ds = _first_ct(synthetic_dir)
    orig_study_date, orig_study_uid = ds.StudyDate, ds.StudyInstanceUID
    orig_class = ds.SOPClassUID
    result = deidentify(ds, TEST_SECRET)
    out = result.dataset

    from datetime import datetime
    delta = (datetime.strptime(out.StudyDate, "%Y%m%d") - datetime.strptime(orig_study_date, "%Y%m%d")).days
    assert delta == result.shift_days == date_shift_days(result.patient_token, TEST_SECRET)
    assert out.SeriesDate == out.StudyDate  # relative timing preserved
    assert out.StudyInstanceUID != orig_study_uid and out.StudyInstanceUID.startswith("2.25.")
    assert out.SOPClassUID == orig_class  # standard UIDs untouched
    assert out.file_meta.MediaStorageSOPInstanceUID == out.SOPInstanceUID
    assert "SourceApplicationEntityTitle" not in out.file_meta


def test_same_patient_same_token_across_studies(synthetic_dir):
    by_mrn: dict[str, set] = {}
    for path in synthetic_dir.rglob("IM*"):
        ds = pydicom.dcmread(path)
        mrn = ds.PatientID
        by_mrn.setdefault(mrn, set()).add(deidentify(ds, TEST_SECRET).patient_token)
    assert all(len(tokens) == 1 for tokens in by_mrn.values())
    assert len({next(iter(t)) for t in by_mrn.values()}) == len(by_mrn)


def test_verifier_catches_what_rules_missed():
    ds = Dataset()
    ds.PatientName = "Doe^Jane"
    ds.PatientID = "MRN7654321"
    ds.StudyDescription = "Follow-up for MRN7654321"
    ds.ProcedureCodeSequence = Sequence([Dataset()])
    ds.ProcedureCodeSequence[0].CodeMeaning = "Reviewed with Jane Doe"
    identifiers = ["MRN7654321", "Doe", "Jane"]
    ds.PatientIdentityRemoved = "YES"
    ds.PatientName = "PT-TOKEN"
    issues = find_residual_phi(ds, identifiers, "PT-TOKEN")
    assert any(i.startswith("StudyDescription") for i in issues)
    assert any(i.startswith("CodeMeaning") for i in issues)
    # Issues name the attribute, never the value.
    assert not any("MRN7654321" in i or "Jane" in i for i in issues)


def test_burned_in_risk_rules():
    ds = Dataset()
    ds.Modality = "CT"
    assert burned_in_risk(ds) is None
    ds.Modality = "US"
    assert "US" in burned_in_risk(ds)
    ds.BurnedInAnnotation = "NO"
    assert burned_in_risk(ds) is None
    ds.BurnedInAnnotation = "YES"
    assert burned_in_risk(ds) == "BurnedInAnnotation=YES"


@pytest.mark.parametrize("name", ["CT_small.dcm", "MR_small.dcm", "JPEG2000.dcm", "rtplan.dcm"])
def test_real_vendor_files_come_out_clean(name):
    path = get_testdata_file(name)
    if path is None:
        pytest.skip(f"{name} not bundled with this pydicom")
    ds = pydicom.dcmread(path)
    result = deidentify(ds, TEST_SECRET)
    assert find_residual_phi(result.dataset, result.original_identifiers, result.patient_token) == []
