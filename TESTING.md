# Testing Report: Phase 0

**Date:** 2026-09-30
**Scope:** DICOM read → extract → de-identify → verify → local DB, plus the workshop scripts (Path A CSV, Path B letters)
**Result:** ✅ **24 / 24 automated tests passed.** Manual end-to-end and leak-scan checks also passed. **PostgreSQL was not tested** (see [Not tested](#6-not-tested)).

All data used in testing is synthetic (Faker, fixed seeds) or comes from the
public sample files that ship with pydicom. No real patient data was used.

---

## 1. Test environment

| Item | Version |
|---|---|
| OS | Windows 10 Pro 10.0.19045 |
| Python | 3.11.9 |
| pydicom | 3.0.2 |
| SQLAlchemy | 2.1.1 |
| Faker | 40.40.0 |
| pytest | 9.1.1 |
| Database | SQLite (bundled with Python) |

## 2. How to reproduce

```bash
pip install -r requirements.txt

# Automated suite
pytest -v

# Manual end-to-end run (same as README Quick Start) + leak scan
dicom-deid synth
dicom-deid ingest
dicom-deid report
python scripts/leak_scan.py
```

---

## 3. Automated tests (pytest)

```text
24 passed, 1 warning in 4.22s
```

The single warning is expected. pydicom complains about the deliberately truncated file used in `test_corrupt_file_is_recorded_and_run_continues`.

### 3.1 Pseudonymisation: `tests/test_pseudonym.py`

| # | Test | What it proves | Result |
|---|---|---|---|
| 1 | `test_patient_token_is_deterministic_and_keyed` | The same MRN gives the same token. A different MRN, or a different secret key, gives a different token. The token does not contain the MRN digits. | ✅ PASS |
| 2 | `test_date_shift_whole_weeks_never_zero` | Over 500 patients, every shift is a whole number of weeks, never zero, within ±26 weeks, and both directions occur | ✅ PASS |
| 3 | `test_remapped_uid_is_valid_and_stable` | Remapped UIDs are deterministic, start with `2.25.`, are ≤ 64 chars and digits-only (valid DICOM UI) | ✅ PASS |
| 4 | `test_age_and_bands` | Age is correct around birthdays; bands `0-9`, `40-49`, `90+`, `unknown` | ✅ PASS |

### 3.2 DICOM de-identification: `tests/test_dicom_deid.py`

| # | Test | What it proves | Result |
|---|---|---|---|
| 5 | `test_direct_identifiers_removed` | PatientName and PatientID become the token and the DOB is emptied. Accession becomes an `AC-` token. National ID, address, phone, institution, operators, physicians, age and device serial are removed. No private tags remain. De-identification markers are set, and the method string is ≤ 64 chars. None of the original values appear in the dataset. | ✅ PASS |
| 6 | `test_person_name_inside_sequence_is_emptied` | A physician name nested inside `RequestAttributesSequence` is emptied, and order IDs inside the sequence are removed | ✅ PASS |
| 7 | `test_dates_shifted_consistently_and_uids_remapped` | StudyDate moves by exactly the patient's shift. SeriesDate stays aligned. Study UID is remapped, SOP Class UID is unchanged, file-meta UID matches, and the sending AE title is removed. | ✅ PASS |
| 8 | `test_same_patient_same_token_across_studies` | Every file for one patient gets one token, and different patients get different tokens (longitudinal linkage survives) | ✅ PASS |
| 9 | `test_verifier_catches_what_rules_missed` | The independent verifier flags an MRN left in free text and a short surname inside a nested sequence. Its messages name the attribute, never the value. | ✅ PASS |
| 10 | `test_burned_in_risk_rules` | CT is not flagged. US with no flag is flagged. `BurnedInAnnotation=NO` clears the flag and `=YES` sets it. | ✅ PASS |
| 11 | `test_real_vendor_files_come_out_clean[CT_small.dcm]` | Real vendor CT with **179 private tags**: the verifier reports zero issues | ✅ PASS |
| 12 | `test_real_vendor_files_come_out_clean[MR_small.dcm]` | Real vendor MR | ✅ PASS |
| 13 | `test_real_vendor_files_come_out_clean[JPEG2000.dcm]` | Compressed pixel data (JPEG 2000) is handled without decoding | ✅ PASS |
| 14 | `test_real_vendor_files_come_out_clean[rtplan.dcm]` | Non-image object (radiotherapy plan) | ✅ PASS |

### 3.3 Pipeline and database: `tests/test_pipeline.py`

| # | Test | What it proves | Result |
|---|---|---|---|
| 15 | `test_ingest_end_to_end` | Every DICOM file ends up either clean or quarantined, and the non-DICOM file is skipped and audited. Quarantined rows carry a reason. Stored files are in the correct folder and re-read as de-identified. Each of the 5 patients appears exactly once. Every study has an age band. | ✅ PASS |
| 16 | `test_no_phi_anywhere_in_outputs` | **Leak scan.** Names, MRNs, national IDs, DOBs, accessions, institution, physicians, original UIDs and the PHI folder names from the raw input are searched for byte-for-byte in every output file and in the SQLite file itself. None were found. | ✅ PASS |
| 17 | `test_reingest_is_idempotent` | A second run over the same input stores nothing new, reports every file as a duplicate, and adds audit events | ✅ PASS |
| 18 | `test_corrupt_file_is_recorded_and_run_continues` | A truncated DICOM file is recorded as failed / not-DICOM, and the good file in the same run is still processed | ✅ PASS |
| 19 | `test_foreign_keys_enforced` | SQLite foreign-key enforcement is switched on | ✅ PASS |

### 3.4 Workshop scripts: `tests/test_scripts.py`

| # | Test | What it proves | Result |
|---|---|---|---|
| 20 | `test_csv_generator_is_reproducible` | Two runs of `generate_synthetic_data.py` produce byte-identical CSVs | ✅ PASS |
| 21 | `test_csv_deidentify` | PHI columns are removed from the schema and no raw name, MRN or DOB appears in the output. Repeat patients keep one token, and the dataset really does contain repeat patients. | ✅ PASS |
| 22 | `test_redact_free_text` | `"Stephanie Miller - 2024-07-17"` → `"[REDACTED] - [REDACTED-DATE]"`, and `"PT: Walker"` → `"[REDACTED]"` | ✅ PASS |
| 23 | `test_referral_letter_redaction` | Patient name, DOB, physician (including the repeat in the signature), phone, letter date and military APO address are all removed. The clinic name is kept by design. | ✅ PASS |
| 24 | `test_referral_letters_script` | The script processes all 10 letters, and no patient name survives | ✅ PASS |

---

## 4. Manual / end-to-end checks

### 4.1 README Quick Start, run exactly as written

```text
$ dicom-deid synth
Wrote 27 synthetic DICOM files (+1 non-DICOM decoy) to data\dicom\raw

$ dicom-deid ingest
{ "files_seen": 28, "clean": 19, "quarantined": 8, "duplicates": 0, "failed": 0, "not_dicom": 1 }

$ dicom-deid report
{ "patients": 6, "patients_with_multiple_studies": 2, "studies": 8, "series": 14,
  "instances": 27, "instances_by_status": { "CLEAN": 19, "QUARANTINED": 8 },
  "series_by_modality": { "CT": 9, "MR": 1, "US": 4 }, "audit_events": 28 }

$ python -m dicom_deid report    # alternative entry point: OK
```

✅ The numbers match the README. All 8 quarantined files are ultrasound: 5 with `BurnedInAnnotation=YES` and 3 with the flag missing.

The synthetic input is deliberately "dirty". It contains PHI in standard tags,
a UAE-format national ID, PHI in a vendor private block, a physician name nested
in a sequence, a patient name typed into `StudyDescription`, patient names as
folder names, and one non-DICOM file.

- ✅ The patient name in the description came out as `"Pelvic pain workup - [REDACTED]"`.
- ✅ Output paths are built from de-identified UIDs only, e.g. `data/dicom/deid/2.25.1000…/2.25…/2.25….dcm`.

### 4.2 Leak scan (`scripts/leak_scan.py`)

This runs independently of the pipeline code. It collects PHI values from the
**raw** files and searches for each one byte-for-byte in every output DICOM file
and in the raw database file.

```text
PHI values collected from raw input: 166
Files scanned: 28 (27 DICOM + database)
Leaks found: 0
```

The values checked were patient names, MRNs, national IDs, DOBs, phone numbers,
addresses, accession numbers, institution, device serials, referring, performing
and operator names, and original Study/SOP UIDs and study dates.

> An earlier one-off version of this scan, run while developing, checked 145
> values and also found 0 leaks. `leak_scan.py` collects more attribute types,
> hence 166.

### 4.3 Real vendor DICOM files (bundled with pydicom)

Nine public sample files were ingested together:

| File | Modality | Outcome | Private tags removed | Notes |
|---|---|---|---|---|
| `CT_small.dcm` | CT | CLEAN | **179** | Heavy vendor private data |
| `693_J2KI.dcm` | CT | CLEAN | 0 | JPEG 2000 compressed |
| `MR_small.dcm` | MR | CLEAN | 0 | |
| `MR_small_bigendian.dcm` | MR | SKIPPED_DUPLICATE | – | Same SOP Instance UID as `MR_small.dcm`, so the duplicate was detected correctly |
| `emri_small.dcm` | MR | CLEAN | 0 | Multi-frame |
| `rtplan.dcm` | RTPLAN | CLEAN | 0 | Non-image object |
| `JPEG2000.dcm` | NM | QUARANTINED | 65 | Secondary Capture SOP class, so a burned-in text risk |
| `SC_rgb.dcm` | OT | QUARANTINED | 0 | Secondary Capture |
| `US1_UNCR.dcm` | US | QUARANTINED | 0 | Ultrasound without `BurnedInAnnotation` |

✅ 0 failures, and every quarantine decision was correct.

### 4.4 Workshop scripts

| Check | Result |
|---|---|
| `generate_synthetic_data.py` run twice → byte-identical output | ✅ 120 records, 76 patients |
| `deidentify.py` on the committed CSV | ✅ 120 records de-identified |
| `generate_referral_letters.py` + `deidentify_referral_letters.py` | ✅ All 10 letters: every address, phone, date, DOB, patient name and physician redacted. Only clinic names remain (by design). |
| `deidentify_with_comprehend_medical.py --help` | ✅ Parses. The real AWS call was **not** executed (no credentials, and synthetic-only policy). |

### 4.5 Repository hygiene before push

| Check | Result |
|---|---|
| `.env` (holds the GitHub token) is git-ignored | ✅ Confirmed with `git check-ignore` |
| `venv/`, `data/dicom/`, `data/db/`, `.claude/`, `*.zip` not staged | ✅ 0 matches in the staged file list |
| Staged content scanned for the token pattern `github_pat_` | ✅ 0 matches (checked again immediately before push) |

---

## 5. Defects found by testing, and fixed

### 5.1 In the original code (baseline run before any changes)

| # | Defect | Impact | Fix |
|---|---|---|---|
| 1 | No code read DICOM files or wrote to a database. Only a CSV imitation existed. | The project's stated goal was not implemented | New `dicom_deid` package: reader, de-identifier, verifier, database, pipeline and CLI |
| 2 | `to_age_band()` used today's date | The de-identified output changed depending on the day it was run | Age is now calculated at the study date |
| 3 | `shift_date()` claimed to preserve day of week but shifted by arbitrary days | The documentation was wrong and a research feature was lost | Shift in whole weeks, never zero |
| 4 | Synthetic generators used `date.today()` and unseeded `uuid4()` | Regenerated data never matched the committed data | Fixed reference date and seeded UIDs |
| 5 | `patient_age` was computed from the year only | Off by up to one year | Proper age at the study date |
| 6 | Each of the 120 CSV records had a unique patient | Patient linkage, the main point of the token, was never demonstrated | About 35% repeat patients (76 patients / 120 studies) |
| 7 | Token was SHA-256 with a hard-coded public salt | MRNs could be brute-forced back from tokens | HMAC-SHA256 with the secret `DEID_SECRET` |
| 8 | README described a Path B (letters) de-identification step that did not exist | Documentation did not match the code | Added `scripts/deidentify_referral_letters.py` |

### 5.2 In the new code (caught by the tests before release)

| # | Defect | Caught by | Fix |
|---|---|---|---|
| 9 | `DeidentificationMethod` was 76 characters, over the DICOM LO limit of 64 | pydicom warning during the first end-to-end run | Shortened the string; test 5 now asserts ≤ 64 |
| 10 | The verifier only matched short identifiers (< 5 chars) as a whole value, so "Doe" in "Reviewed with Jane Doe" was missed. This matters for common short names such as *Ali*, *Khan*, *Syed* and *Lee*. | Test 9 **failed** | Short identifiers now match as whole words anywhere in a value (fails safe) |
| 11 | The street-address regex missed military addresses (`PSC 5116, Box 3726, APO AP 44084`) | Manual review of letter output (referral_008) | Line-level rule: any line ending in `ST 12345` |
| 12 | The quarantine reason said "modality NM" when the actual trigger was the Secondary Capture SOP class | Vendor-file run (4.3) | The message now names the real trigger |

---

## 6. Not tested

| Area | Why | Plan |
|---|---|---|
| **PostgreSQL** | Docker is not installed on the test machine. The code uses only portable SQLAlchemy types (JSON → JSONB on Postgres), but this has **not** been run. | First task of Phase 1: run the suite with `DATABASE_URL=postgresql+psycopg://…` |
| **Amazon Comprehend Medical** call | Needs AWS credentials; synthetic-only policy | Phase 1, with a residency review first |
| **Burned-in pixel text** | Phase 0 does not inspect pixels by design; risky images are quarantined instead | Phase 1 OCR + masking |
| **Real clinical DICOM / HL7** | Out of scope for this public repo | Phase 1, controlled environment only |
| **Performance at scale** | Largest run was 28 files | Load test in Phase 1 (thousands of studies) |
| **Linux / macOS** | Only run on Windows | CI (GitHub Actions) matrix in Phase 1 |
