"""The synthetic study cohort used by experiments E3 and E7 (docs/protocol.md)."""
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

import pydicom
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiments.cohort import PROTOCOL_SEED, generate_cohort  # noqa: E402


@pytest.fixture(scope="module")
def cohort(tmp_path_factory):
    out = tmp_path_factory.mktemp("cohort")
    manifest = generate_cohort(out)
    return out, manifest


def _patients(manifest):
    by_patient: dict[int, list[dict]] = {}
    for row in manifest["instances"]:
        by_patient.setdefault(row["patient"], []).append(row)
    return by_patient


def _first_age_days(rows):
    first = min(rows, key=lambda r: r["study_date"])
    return (date.fromisoformat(first["study_date"]) - date.fromisoformat(first["birth_date"])).days


def test_protocol_spec_is_met(cohort):
    _, manifest = cohort
    assert manifest["seed"] == PROTOCOL_SEED == 20261125
    patients = _patients(manifest)
    assert len(patients) == 100
    for rows in patients.values():
        assert 3 <= len({r["study_uid"] for r in rows}) <= 5
    first_ages = [_first_age_days(rows) for rows in patients.values()]
    assert sum(a < 2 * 365 for a in first_ages) >= 20          # children under 2
    assert sum(a >= 90 * 365.25 for a in first_ages) >= 5      # over 90


def test_ground_truth_matches_files(cohort):
    out, manifest = cohort
    mrns = set()
    for row in manifest["instances"]:
        ds = pydicom.dcmread(out / row["file"])
        assert ds.PatientID == row["patient_id"]
        assert ds.PatientBirthDate == row["birth_date"].replace("-", "")
        assert ds.StudyDate == row["study_date"].replace("-", "")
        assert ds.StudyInstanceUID == row["study_uid"]
        assert ds.PatientSex == row["sex"] and ds.Modality == row["modality"]
        assert ds.PatientAge == row["recorded_age"]
        assert row["birth_date"] <= row["study_date"] <= "2026-09-29"
        mrns.add((row["patient"], row["patient_id"]))
    assert len({m for _, m in mrns}) == len({p for p, _ in mrns}) == 100  # one ID per patient, all distinct


def test_same_seed_same_cohort_different_seed_different(cohort, tmp_path):
    out, manifest = cohort
    again = generate_cohort(tmp_path / "again")
    assert again == manifest
    first = manifest["instances"][0]["file"]
    assert hashlib.sha256((out / first).read_bytes()).digest() == \
        hashlib.sha256((tmp_path / "again" / first).read_bytes()).digest()
    other = generate_cohort(tmp_path / "other", seed=1)
    assert other["instances"] != manifest["instances"]


def test_manifest_written_and_folders_carry_no_names(cohort):
    out, manifest = cohort
    on_disk = json.loads((out / "ground_truth.json").read_text(encoding="utf-8"))
    assert on_disk == manifest
    for row in manifest["instances"]:
        assert row["file"].startswith("p") and "_" not in row["file"].split("/")[0]
