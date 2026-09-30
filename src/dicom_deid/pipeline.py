"""
Phase 0 pipeline: read DICOM -> de-identify -> verify -> store file + metadata.

    src/  (raw, PHI)                    out/ (released)      quarantine/ (held)
       |                                   ^                     ^
       +--> read -> deidentify -> verify --+-- CLEAN             +-- burned-in risk
                                           |                         or residual PHI
                                           +--> database (patients/studies/series/
                                                instances + audit event per file)

Each file is its own transaction: one bad file is recorded as FAILED and
the run carries on.
"""

import hashlib
import io
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

import pydicom
from pydicom.errors import InvalidDicomError
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from .db import DeidAuditEvent, Instance, Patient, Series, Study, init_db
from .dicom_deid import PROFILE_VERSION, deidentify
from .reader import extract_metadata, iter_candidate_files, to_dicom_json
from .verify import find_residual_phi

CLEAN = "CLEAN"
QUARANTINED = "QUARANTINED"


@dataclass
class IngestSummary:
    run_id: str
    files_seen: int = 0
    clean: int = 0
    quarantined: int = 0
    duplicates: int = 0
    failed: int = 0
    not_dicom: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


def _get_or_create(session: Session, model, key: str, value, **fields):
    obj = session.scalar(select(model).where(getattr(model, key) == value))
    if obj is None:
        obj = model(**{key: value}, **fields)
        session.add(obj)
        session.flush()
    return obj


def _audit(session: Session, run_id: str, source_sha256: str, outcome: str,
           reason: str | None = None, sop_uid: str | None = None, actions: dict | None = None) -> None:
    session.add(DeidAuditEvent(
        run_id=run_id, source_sha256=source_sha256, outcome=outcome, reason=reason,
        sop_instance_uid=sop_uid, profile_version=PROFILE_VERSION, actions=actions,
    ))


def _process_file(session: Session, raw: bytes, src_hash: str, run_id: str,
                  out_dir: Path, quarantine_dir: Path, secret: bytes | None) -> str:
    ds = pydicom.dcmread(io.BytesIO(raw))
    result = deidentify(ds, secret)
    deid = result.dataset
    if "SOPInstanceUID" not in deid or "StudyInstanceUID" not in deid or "SeriesInstanceUID" not in deid:
        raise ValueError("missing Study/Series/SOP Instance UID")

    reasons = []
    if result.burned_in_risk:
        reasons.append(result.burned_in_risk)
    issues = find_residual_phi(deid, result.original_identifiers, result.patient_token)
    if issues:
        reasons.append("residual PHI check failed: " + "; ".join(issues))
    status = QUARANTINED if reasons else CLEAN

    meta = extract_metadata(deid)
    sop_uid = meta["instance"]["sop_instance_uid"]
    if session.scalar(select(Instance.id).where(Instance.sop_instance_uid == sop_uid)):
        _audit(session, run_id, src_hash, "SKIPPED_DUPLICATE", sop_uid=sop_uid)
        return "duplicate"

    patient = _get_or_create(session, Patient, "patient_token", result.patient_token, **meta["patient"])
    study_fields = {k: v for k, v in meta["study"].items() if k != "study_instance_uid"}
    study = _get_or_create(session, Study, "study_instance_uid", meta["study"]["study_instance_uid"],
                           patient_id=patient.id, age_band=result.age_band, **study_fields)
    series_fields = {k: v for k, v in meta["series"].items() if k != "series_instance_uid"}
    series = _get_or_create(session, Series, "series_instance_uid", meta["series"]["series_instance_uid"],
                            study_id=study.id, **series_fields)

    base = out_dir if status == CLEAN else quarantine_dir
    target = base / study.study_instance_uid / series.series_instance_uid / f"{sop_uid}.dcm"
    buffer = io.BytesIO()
    deid.save_as(buffer, enforce_file_format=True)
    data = buffer.getvalue()

    instance_fields = {k: v for k, v in meta["instance"].items() if k != "sop_instance_uid"}
    session.add(Instance(
        sop_instance_uid=sop_uid, series_id=series.id, status=status,
        status_reason="; ".join(reasons) or None, stored_path=target.as_posix(),
        file_sha256=hashlib.sha256(data).hexdigest(), dicom_json=to_dicom_json(deid),
        **instance_fields,
    ))
    _audit(session, run_id, src_hash, status, reason="; ".join(reasons) or None,
           sop_uid=sop_uid, actions=result.actions)
    session.flush()

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return status.lower()


def ingest(src: Path, out_dir: Path, quarantine_dir: Path, engine: Engine,
           secret: bytes | None = None) -> IngestSummary:
    init_db(engine)
    summary = IngestSummary(run_id=str(uuid.uuid4()))
    out_dir, quarantine_dir = Path(out_dir), Path(quarantine_dir)

    for path in iter_candidate_files(Path(src)):
        summary.files_seen += 1
        raw = path.read_bytes()
        src_hash = hashlib.sha256(raw).hexdigest()
        with Session(engine) as session:
            try:
                outcome = _process_file(session, raw, src_hash, summary.run_id, out_dir, quarantine_dir, secret)
                session.commit()
            except InvalidDicomError:
                session.rollback()
                _audit(session, summary.run_id, src_hash, "NOT_DICOM")
                session.commit()
                outcome = "not_dicom"
            except Exception as exc:  # noqa: BLE001 -- record and continue with the next file
                session.rollback()
                # Exception type only: messages can quote tag values (PHI).
                _audit(session, summary.run_id, src_hash, "FAILED", reason=type(exc).__name__)
                session.commit()
                outcome = "failed"
        if outcome == "duplicate":
            summary.duplicates += 1
        else:
            setattr(summary, outcome, getattr(summary, outcome) + 1)
    return summary


def db_report(engine: Engine) -> dict:
    init_db(engine)
    with Session(engine) as s:
        count = lambda model: s.scalar(select(func.count()).select_from(model))  # noqa: E731
        by_status = dict(s.execute(select(Instance.status, func.count()).group_by(Instance.status)).all())
        by_modality = dict(s.execute(select(Series.modality, func.count()).group_by(Series.modality)).all())
        multi_study = s.scalar(
            select(func.count()).select_from(
                select(Study.patient_id).group_by(Study.patient_id).having(func.count() > 1).subquery()
            )
        )
        return {
            "patients": count(Patient),
            "patients_with_multiple_studies": multi_study,
            "studies": count(Study),
            "series": count(Series),
            "instances": count(Instance),
            "instances_by_status": by_status,
            "series_by_modality": by_modality,
            "audit_events": count(DeidAuditEvent),
        }
