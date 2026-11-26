"""PostgreSQL gives the same results as SQLite.

Skipped unless DEID_TEST_POSTGRES_URL points at an empty, disposable database,
e.g. postgresql+psycopg://user@localhost:5432/deid_test. The test drops and
recreates the `public` schema, so never point it at data you want to keep.
"""
import os

import pytest
from sqlalchemy import inspect, text

from conftest import TEST_SECRET
from dicom_deid.db import make_engine
from dicom_deid.pipeline import db_report, ingest

PG_URL = os.environ.get("DEID_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not PG_URL, reason="DEID_TEST_POSTGRES_URL not set")


def test_postgres_matches_sqlite_and_reingest_is_idempotent(synthetic_dir, tmp_path):
    reports = {}
    for name, url in (("sqlite", f"sqlite:///{(tmp_path / 'deid.sqlite').as_posix()}"), ("postgres", PG_URL)):
        engine = make_engine(url)
        if name == "postgres":
            with engine.begin() as conn:
                conn.execute(text("DROP SCHEMA public CASCADE"))
                conn.execute(text("CREATE SCHEMA public"))
        summary = ingest(synthetic_dir, tmp_path / name / "deid", tmp_path / name / "q", engine,
                         secret=TEST_SECRET, profile="utility")
        assert summary.failed == 0
        reports[name] = db_report(engine)
        if name == "postgres":
            pg_engine = engine
    assert reports["postgres"] == reports["sqlite"]

    with pg_engine.connect() as conn:
        kind = conn.execute(text("select data_type from information_schema.columns "
                                 "where table_name='deid_audit_events' and column_name='actions'")).scalar()
    assert kind == "jsonb"
    assert {"patients", "studies", "series", "instances", "deid_audit_events"} <= set(inspect(pg_engine).get_table_names())

    again = ingest(synthetic_dir, tmp_path / "again" / "deid", tmp_path / "again" / "q", pg_engine,
                   secret=TEST_SECRET, profile="utility")
    assert again.clean == 0 and again.quarantined == 0 and again.duplicates > 0
    after = db_report(pg_engine)
    assert {k: v for k, v in after.items() if k != "audit_events"} == \
           {k: v for k, v in reports["postgres"].items() if k != "audit_events"}
