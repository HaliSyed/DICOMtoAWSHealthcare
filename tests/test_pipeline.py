import pydicom
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from conftest import TEST_SECRET
from dicom_deid.db import DeidAuditEvent, Instance, Patient, Study, make_engine
from dicom_deid.pipeline import db_report, ingest


def _raw_phi(synthetic_dir) -> set[str]:
    phi = set()
    for path in synthetic_dir.rglob("IM*"):
        ds = pydicom.dcmread(path)
        pn = ds.PatientName
        phi.update({pn.family_name, pn.given_name, ds.PatientID, ds.PatientBirthDate, ds.OtherPatientIDs,
                    ds.AccessionNumber, ds.InstitutionName, ds.StudyInstanceUID, ds.SOPInstanceUID,
                    ds.ReferringPhysicianName.family_name, ds.OperatorsName.family_name})
        phi.add(path.parent.parent.parent.name)  # "Last_First" folder name
    return {p for p in phi if p and len(p) >= 4}


def test_ingest_end_to_end(synthetic_dir, tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'deid.sqlite').as_posix()}")
    summary = ingest(synthetic_dir, tmp_path / "out", tmp_path / "q", engine, secret=TEST_SECRET)

    n_dicom = len(list(synthetic_dir.rglob("IM*")))
    assert summary.failed == 0
    assert summary.not_dicom == 1
    assert summary.clean + summary.quarantined == n_dicom
    assert summary.quarantined >= 1  # synthetic set always includes ultrasound

    with Session(engine) as s:
        assert s.scalar(select(Instance).where(Instance.status == "QUARANTINED")).status_reason
        for inst in s.scalars(select(Instance)):
            folder = "out" if inst.status == "CLEAN" else "q"
            assert f"/{folder}/" in inst.stored_path
            assert pydicom.dcmread(inst.stored_path).PatientIdentityRemoved == "YES"
        # every patient appears once, however many studies they have
        tokens = s.scalars(select(Patient.patient_token)).all()
        assert len(tokens) == len(set(tokens)) == 5
        assert all(st.age_band != "unknown" for st in s.scalars(select(Study)))
        assert s.scalar(select(DeidAuditEvent).where(DeidAuditEvent.outcome == "NOT_DICOM"))


def test_no_phi_anywhere_in_outputs(synthetic_dir, tmp_path):
    db_file = tmp_path / "deid.sqlite"
    engine = make_engine(f"sqlite:///{db_file.as_posix()}")
    ingest(synthetic_dir, tmp_path / "out", tmp_path / "q", engine, secret=TEST_SECRET)
    engine.dispose()

    phi = _raw_phi(synthetic_dir)
    blobs = [db_file.read_bytes()] + [p.read_bytes() for p in tmp_path.rglob("*.dcm")]
    leaks = {v for v in phi for blob in blobs if v.encode() in blob}
    assert leaks == set()


def test_reingest_is_idempotent(synthetic_dir, tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'deid.sqlite').as_posix()}")
    first = ingest(synthetic_dir, tmp_path / "out", tmp_path / "q", engine, secret=TEST_SECRET)
    second = ingest(synthetic_dir, tmp_path / "out", tmp_path / "q", engine, secret=TEST_SECRET)
    assert second.duplicates == first.clean + first.quarantined
    assert second.clean == second.quarantined == 0
    report = db_report(engine)
    assert report["instances"] == first.clean + first.quarantined
    assert report["audit_events"] == 2 * first.files_seen


def test_corrupt_file_is_recorded_and_run_continues(synthetic_dir, tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    good = next(synthetic_dir.rglob("IM*"))
    (src / "good").write_bytes(good.read_bytes())
    # Valid preamble + header start, then truncated mid-dataset.
    (src / "broken").write_bytes(good.read_bytes()[:400])
    engine = make_engine(f"sqlite:///{(tmp_path / 'deid.sqlite').as_posix()}")
    summary = ingest(src, tmp_path / "out", tmp_path / "q", engine, secret=TEST_SECRET)
    assert summary.clean + summary.quarantined == 1
    assert summary.failed + summary.not_dicom == 1


def test_foreign_keys_enforced(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'deid.sqlite').as_posix()}")
    db_report(engine)  # creates tables
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
