"""The workshop scripts (CSV path A, referral letters path B)."""

import csv
import subprocess
import sys

from conftest import REPO_ROOT
from dicom_deid.text_deid import redact_free_text, redact_referral_letter

PHI_COLUMNS = {"patient_name", "patient_id", "patient_birth_date", "referring_physician",
               "burned_in_annotation", "patient_age", "study_date"}


def _run(*args):
    return subprocess.run([sys.executable, *args], cwd=REPO_ROOT, check=True, capture_output=True, text=True)


def test_csv_generator_is_reproducible(tmp_path):
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    _run("scripts/generate_synthetic_data.py", "--count", "30", "--out", str(a))
    _run("scripts/generate_synthetic_data.py", "--count", "30", "--out", str(b))
    assert a.read_bytes() == b.read_bytes()


def test_csv_deidentify(tmp_path):
    raw_path, out_path = tmp_path / "raw.csv", tmp_path / "deid.csv"
    _run("scripts/generate_synthetic_data.py", "--count", "60", "--out", str(raw_path))
    _run("scripts/deidentify.py", "--in", str(raw_path), "--out", str(out_path))

    raw = list(csv.DictReader(raw_path.open(encoding="utf-8")))
    deid = list(csv.DictReader(out_path.open(encoding="utf-8")))
    assert len(raw) == len(deid)
    assert PHI_COLUMNS.isdisjoint(deid[0].keys())

    text = out_path.read_text(encoding="utf-8")
    for r in raw:
        for col in ("patient_name", "patient_id", "patient_birth_date"):
            assert r[col] not in text

    # repeat studies of one patient keep one token
    token_by_mrn = {}
    for r, d in zip(raw, deid):
        token_by_mrn.setdefault(r["patient_id"], set()).add(d["patient_token"])
    assert all(len(t) == 1 for t in token_by_mrn.values())
    assert any(sum(1 for r in raw if r["patient_id"] == m) > 1 for m in token_by_mrn)


def test_redact_free_text():
    assert redact_free_text("Stephanie Miller - 2024-07-17") == "[REDACTED] - [REDACTED-DATE]"
    assert redact_free_text("PT: Walker") == "[REDACTED]"
    assert redact_free_text("") == ""


def test_referral_letter_redaction():
    letter = """Northgate Family Clinic
PSC 5116, Box 3726, APO AP 44084
Phone: 001-508-330-1661

Date: 2026-08-21

Patient Name: Chris Curtis
Date of Birth: 1945-09-02
Referring Physician: Dr. Amanda Diaz

Regards,
Dr. Amanda Diaz
Northgate Family Clinic
"""
    out, counts = redact_referral_letter(letter)
    for phi in ("Chris Curtis", "1945-09-02", "Amanda Diaz", "508-330-1661", "2026-08-21", "APO AP 44084"):
        assert phi not in out
    assert counts["[PHYSICIAN]"] == 2
    assert "Northgate Family Clinic" in out  # institution kept, as in the CSV path


def test_referral_letters_script(tmp_path):
    out = tmp_path / "letters"
    _run("scripts/deidentify_referral_letters.py", "--in", "data/referral_letters", "--out", str(out))
    raw = sorted((REPO_ROOT / "data/referral_letters").glob("*.txt"))
    assert len(list(out.glob("*.txt"))) == len(raw) > 0
    for path in raw:
        name_line = next(l for l in path.read_text(encoding="utf-8").splitlines() if l.startswith("Patient Name:"))
        assert name_line.split(":", 1)[1].strip() not in (out / path.name).read_text(encoding="utf-8")
