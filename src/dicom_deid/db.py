"""
Local database for de-identified imaging metadata.

Relational on purpose: DICOM is a strict hierarchy
(Patient -> Study -> Series -> Instance), which maps one-to-one onto tables
with foreign keys -- and onto FHIR later (Patient, ImagingStudy with nested
series/instances). The full de-identified header is kept alongside as JSON
for anything not promoted to a column.

SQLite by default (zero setup); set DATABASE_URL to use PostgreSQL. No
column type here is SQLite-specific, and JSON becomes JSONB on PostgreSQL.
Nothing in this schema holds a direct identifier: patients are known only by
their HMAC token, and source file paths (which often contain patient names)
are never stored.
"""

from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import JSON, Date, DateTime, Float, ForeignKey, Integer, String, Text, create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .config import get_database_url

JsonType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_token: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    sex: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    studies: Mapped[list["Study"]] = relationship(back_populates="patient")


class Study(Base):
    __tablename__ = "studies"

    id: Mapped[int] = mapped_column(primary_key=True)
    study_instance_uid: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    study_date_shifted: Mapped[date | None] = mapped_column(Date)
    study_time: Mapped[str | None] = mapped_column(String(32))
    accession_token: Mapped[str | None] = mapped_column(String(32))
    study_description: Mapped[str | None] = mapped_column(String(255))
    age_band: Mapped[str] = mapped_column(String(16), default="unknown")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    patient: Mapped[Patient] = relationship(back_populates="studies")
    series: Mapped[list["Series"]] = relationship(back_populates="study")


class Series(Base):
    __tablename__ = "series"

    id: Mapped[int] = mapped_column(primary_key=True)
    series_instance_uid: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    study_id: Mapped[int] = mapped_column(ForeignKey("studies.id"), index=True)
    modality: Mapped[str | None] = mapped_column(String(16), index=True)
    body_part_examined: Mapped[str | None] = mapped_column(String(64))
    series_description: Mapped[str | None] = mapped_column(String(255))
    series_number: Mapped[int | None] = mapped_column(Integer)
    series_date_shifted: Mapped[date | None] = mapped_column(Date)
    manufacturer: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    study: Mapped[Study] = relationship(back_populates="series")
    instances: Mapped[list["Instance"]] = relationship(back_populates="series")


class Instance(Base):
    __tablename__ = "instances"

    id: Mapped[int] = mapped_column(primary_key=True)
    sop_instance_uid: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    series_id: Mapped[int] = mapped_column(ForeignKey("series.id"), index=True)
    sop_class_uid: Mapped[str | None] = mapped_column(String(64))
    instance_number: Mapped[int | None] = mapped_column(Integer)
    rows: Mapped[int | None] = mapped_column(Integer)
    columns: Mapped[int | None] = mapped_column(Integer)
    slice_thickness: Mapped[float | None] = mapped_column(Float)
    pixel_spacing: Mapped[str | None] = mapped_column(String(64))
    photometric_interpretation: Mapped[str | None] = mapped_column(String(32))
    # CLEAN = released; QUARANTINED = held for manual review (e.g. burned-in text risk)
    status: Mapped[str] = mapped_column(String(16), index=True)
    status_reason: Mapped[str | None] = mapped_column(Text)
    stored_path: Mapped[str] = mapped_column(Text)
    file_sha256: Mapped[str] = mapped_column(String(64))
    dicom_json: Mapped[dict] = mapped_column(JsonType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    series: Mapped[Series] = relationship(back_populates="instances")


class DeidAuditEvent(Base):
    """
    One row per file per run -- what happened and why, without PHI. The
    source file is identified only by its SHA-256, which proves a given file
    was processed without revealing its content or its (often PHI-bearing)
    path.
    """

    __tablename__ = "deid_audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    source_sha256: Mapped[str] = mapped_column(String(64), index=True)
    sop_instance_uid: Mapped[str | None] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(24), index=True)
    reason: Mapped[str | None] = mapped_column(Text)
    profile_version: Mapped[str] = mapped_column(String(128))
    actions: Mapped[dict | None] = mapped_column(JsonType)


def _enable_sqlite_foreign_keys(dbapi_connection, _record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def make_engine(url: str | None = None) -> Engine:
    url = url or get_database_url()
    parsed = make_url(url)
    is_sqlite = parsed.get_backend_name() == "sqlite"
    if is_sqlite and parsed.database and parsed.database != ":memory:":
        Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url)
    if is_sqlite:
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return engine


def init_db(engine: Engine) -> None:
    """Create tables if missing. Phase 1 replaces this with Alembic migrations."""
    Base.metadata.create_all(engine)
