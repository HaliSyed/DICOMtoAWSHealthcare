# Testing Report: Phase 0

**Date:** 2026-09-30
**Scope:** DICOM read → extract → de-identify → verify → local DB, plus the workshop scripts (Demo 1 CSV table, Demo 2 referral letters)
**Result:** ✅ **39 / 39 automated tests passed.** Manual end-to-end and leak-scan checks also passed. **PostgreSQL was not tested** (see [Not tested](#6-not-tested)).

All data used in testing is synthetic (Faker, fixed seeds) or comes from the
public sample files that ship with pydicom. No real patient data was used.

---

## 1. Test environment

This section lists every component the tests ran on, what it is for, and where
this project uses it. Anything marked *planned* is not in the code yet.

### 1.1 Platform

| Item | Version tested | What it is | Purpose in this project |
|---|---|---|---|
| **OS** | Windows 10 Pro 10.0.19045 | Operating system of the test machine | The only OS tested so far. The code has no Windows-specific parts (it uses `pathlib` for all paths), but Linux/macOS still need a CI run (see [Not tested](#6-not-tested)). |
| **Python** | 3.11.9 (minimum 3.10) | The programming language and interpreter | Runs all code. 3.10+ is required because the code uses modern type hints such as `str \| None`. |
| **SQLite** | 3.45.1 (via Python's built-in `sqlite3` module) | A file-based SQL database engine that needs no server | **The Phase 0 local database** (`data/db/deid.sqlite`). It stores patients, studies, series, instances and the audit log. It was chosen for Phase 0 because it needs no install and works offline, e.g. in a workshop room. PostgreSQL replaces it in Phase 1 without code changes. |

### 1.2 Core libraries (installed with the package)

These are declared under `dependencies` in `pyproject.toml`, so every install gets them.

| Library | Version tested | What it is | Purpose in this project | Used in |
|---|---|---|---|---|
| **pydicom** | 3.0.2 | The standard Python library for reading, editing and writing DICOM files | **The core of the pipeline.** It reads DICOM files (any transfer syntax, including compressed, without decoding pixels) and walks every element, including nested sequences. It edits, removes and empties tags, removes private tags, writes the de-identified file with correct file meta, and exports the header as DICOM JSON. Its bundled sample files (`pydicom.data`) are also the real-vendor test set. | `dicom_deid.py`, `verify.py`, `reader.py`, `pipeline.py`, `synthetic.py`, `leak_scan.py`, tests |
| **SQLAlchemy** | 2.1.1 | A database toolkit and ORM (object-relational mapper) for Python | Defines the tables as Python classes and runs all inserts and queries. It also creates the schema and turns on SQLite foreign keys. **Its main job is database portability:** the same code runs on SQLite now and PostgreSQL in Phase 1 by changing only `DATABASE_URL`, and the JSON column becomes JSONB on PostgreSQL automatically. | `db.py`, `pipeline.py`, tests |
| **numpy** | 2.4.6 | The standard array library for numerical Python | Holds decoded image frames as arrays. pydicom needs it to decode pixel data, and the loader uses it for display scaling (8-bit conversion, windowing). | `loader.py`, tests |
| **Pillow** | 12.3.0 | The standard Python imaging library | pydicom's decoder for **JPEG Baseline** and **JPEG 2000** pixel data (the supplied angiography files are JPEG Baseline), and the PNG writer for `export_png` / `dicom-deid inspect --export-png`. | `loader.py` (via pydicom), tests |
| **Faker** | 40.40.0 | A generator of realistic fake data (names, addresses, phone numbers, dates) | Produces **all synthetic PHI** used in tests: patient and physician names, addresses and phone numbers. It runs with fixed seeds, so outputs are repeatable. This lets the project test de-identification without any real patient data. Note that name lists can change between Faker versions. | `synthetic.py`, `generate_synthetic_data.py`, `generate_referral_letters.py` |

### 1.3 Optional libraries (installed as extras)

Extras are declared under `optional-dependencies` in `pyproject.toml`. `requirements.txt` installs `aws` and `dev`.

| Library | Version tested | Extra | What it is | Purpose in this project |
|---|---|---|---|---|
| **pytest** | 9.1.1 | `dev` | Python's most widely used test framework | Runs the 24 automated tests. It provides temporary folders (so tests never touch your real `data/`), shared fixtures (a synthetic DICOM set generated once per test run) and parametrised tests (one test run against 4 vendor files). |
| **boto3** (+ botocore) | 1.43.105 | `aws` | The official AWS SDK for Python | Makes the Amazon Comprehend Medical `DetectPHI` call in `scripts/deidentify_with_comprehend_medical.py`. It is installed but **not exercised in testing**, since that needs AWS credentials. In Phase 1+ it will also be used for S3, AWS HealthImaging, Secrets Manager/KMS and Textract. |
| **psycopg** 3 | *not installed* | `postgres` | The PostgreSQL driver for Python | Lets SQLAlchemy talk to PostgreSQL (`DATABASE_URL=postgresql+psycopg://…`). It is **not tested yet** because there was no PostgreSQL server or Docker on the test machine. This is the first task of Phase 1. |

### 1.4 Build and install tooling

| Tool | Version | Purpose |
|---|---|---|
| **pip** | 26.2.1 | Installs the package and its dependencies from `requirements.txt` |
| **setuptools** | ≥ 68 (fetched automatically at build time) | Builds the `dicom_deid` package from `pyproject.toml` and creates the `dicom-deid` command |
| **venv** | built into Python | Keeps this project's libraries in an isolated environment (`venv/`, git-ignored) |

### 1.5 Python standard library modules used

These ship with Python, so there is nothing to install. The security-relevant
ones are listed first.

| Module | Purpose in this project |
|---|---|
| `hmac`, `hashlib` | **Pseudonymisation.** HMAC-SHA256 keyed with `DEID_SECRET` generates patient and accession tokens, remapped UIDs and date-shift offsets. SHA-256 also gives the file fingerprints used in the audit log and the `instances` table. |
| `re` | Regex redaction of free text (names, dates, phone numbers, addresses) and the verifier's whole-word identifier matching |
| `uuid` | Builds valid `2.25.*` DICOM UIDs from HMAC output, and generates a unique `run_id` per ingest |
| `datetime` | Date shifting, age-at-study calculation, audit timestamps (UTC) |
| `pathlib`, `io` | Cross-platform file paths; writing DICOM to memory before saving (so the file hash is computed on exactly what is written) |
| `argparse` | Command-line options for `dicom-deid` and all scripts |
| `csv`, `json` | Demo 1 CSV input/output; JSON output of `ingest` and `report` |
| `random` | Seeded randomness for the synthetic generators (repeatable output) |
| `dataclasses`, `collections` | The `DeidResult` and `IngestSummary` result objects; counting de-identification actions |
| `os`, `warnings`, `sys` | Reading environment variables; warning when the development secret is in use; script exit codes |
| `subprocess` | Tests run the workshop scripts exactly as a user would, as separate processes |

### 1.6 Planned for later phases (not in the code yet)

| Library / tool | Phase | Purpose |
|---|---|---|
| **PostgreSQL 16** + psycopg | 1 | Production database: concurrency, roles, row-level security, encryption, backups |
| **pylibjpeg** (+ plugins) | 1 | Decode JPEG Extended / Lossless / JPEG-LS, which Pillow cannot (currently reported as not decodable) |
| **Alembic** | 1 | Database schema migrations (replaces `create_all`) |
| **pynetdicom** | 1 | Receive images directly from PACS/modalities over the DICOM network protocol (C-STORE SCP) |
| **hl7apy** or **python-hl7** | 1 | Parse HL7 v2 messages (ADT, ORM/OMI, ORU) so they can be de-identified and linked to DICOM studies |
| OCR (Amazon Textract / Rekognition, or Tesseract via `pytesseract` for on-premises data) on frames from `loader.iter_frames` | 1 | Find and mask burned-in text in quarantined ultrasound and screenshot images |
| Defacing tool (e.g. `pydeface`) | 1 | Remove facial features from head CT/MR volumes |
| **GitHub Actions** | 1 | Continuous integration: run the tests on Linux, macOS and Windows for every push |
| **fhir.resources** | 2 | Python FHIR R4 models for building and validating `Patient`, `ImagingStudy`, `DiagnosticReport`, etc. |
| **HAPI FHIR JPA server** (or AWS HealthLake) | 2 | The FHIR server itself (a Java service running on PostgreSQL), subject to UAE data-residency checks |
| **pgvector** | Later | Vector similarity search inside PostgreSQL, only once the AI phase produces image embeddings |

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
39 passed, 1 warning
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

### 3.5 Reading DICOM files: `tests/test_loader.py`

| # | Test | What it proves | Result |
|---|---|---|---|
| 25 | `test_read_info_synthetic` | The summary lists which identifying attributes are present, counts private tags, and never includes an identifying value | ✅ PASS |
| 26–28 | `test_compressed_frames_decode[…]` | JPEG Baseline colour, RLE monochrome and RLE colour pydicom samples decode to the right shape | ✅ PASS |
| 29 | `test_undecodable_is_reported_not_raised` | A JPEG Extended file (no decoder installed) is reported as not decodable, with the reason, instead of crashing | ✅ PASS |
| 30 | `test_multiframe_selection_and_uint8` | A 4-frame file yields 4 frames, frame selection returns the right frames, and the 8-bit conversion spans 0–255 | ✅ PASS |
| 31 | `test_export_png` | PNG export respects `every_nth` and `max_frames` and writes greyscale images | ✅ PASS |
| 32 | `test_cli_inspect` | `dicom-deid inspect` output shows no patient name or ID | ✅ PASS |
| 33–37 | `test_local_dicom_files_fully_decode[…]` | Every frame of each sample file in `tests/data/dicom/` decodes with the header's dimensions and frame count. Extra files placed in `data/` are also tested where present. | ✅ PASS (all 5 sample files) |

### 3.6 Sample files through the pipeline: `tests/test_samples.py`

| # | Test | What it proves | Result |
|---|---|---|---|
| 38 | `test_samples_ingest` | All 5 sample files ingest without failure and all are quarantined (XA/US without a burned-in flag). They resolve to 4 patients and 4 series (3 XA, 1 US), because two files share a patient and series. | ✅ PASS |
| 39 | `test_samples_no_leak` | No patient name, ID, birth date, accession, institution or original UID from the samples appears in the de-identified files or the database | ✅ PASS |

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

### 4.4 Sample DICOM files (`tests/data/dicom/`)

The repo owner supplied five DICOM files for testing. They carry patient
identity fields and have no de-identification markers, so they were first
**treated as potentially real data**: processed outside the repo, with only
counts and outcomes recorded. A check of the patient-name fields, which
reported only whether a marker was present and never the value, showed every
file carries the **"Rubo" demo placeholder**. They are the public **Rubo Medical
demo sample files**, and the repo owner then committed them under
`tests/data/dicom/` as permanent test data. Any other DICOM file stays
git-ignored (`*.dcm` / `*.DCM`).

| File | Modality | Compression | Frames | Outcome | Private tags removed |
|---|---|---|---|---|---|
| `0002.DCM` | XA (angiography) | JPEG Baseline | 96 | QUARANTINED | 14 |
| `0003.DCM` | XA | JPEG Baseline | 17 | QUARANTINED | 14 |
| `0004.DCM` | XA | JPEG Baseline | 17 | QUARANTINED | 14 |
| `0009.DCM` | XA | JPEG Baseline | 137 | QUARANTINED | 13 |
| `0020.DCM` | US multi-frame | RLE Lossless | 11 | QUARANTINED | 0 |

- ✅ **All five quarantined, which is correct.** `BurnedInAnnotation` is missing, and XA and US images very often have identifying text burned into the pixels. They need OCR review (Phase 1) before release.
- ✅ Header de-identification completed on every file: identity removed, private tags gone, every person name emptied, dates shifted, UIDs remapped. Multi-frame pixel data stayed intact in both compressed formats.
- ✅ Linkage: the 5 files resolved to **4 patients** (two files share one token).
- ✅ Leak scan: **25** identity values collected from the originals, **0** found in the output files or the database.
- ✅ **Pixel decoding** (`dicom-deid inspect`, `loader.iter_frames`): all **278 frames** decode. That is 96 + 17 + 17 + 137 frames of 512×512 8-bit JPEG Baseline angiography, and 11 frames of 430×600 RLE palette-colour ultrasound, which is expanded to RGB for PNG preview.

### 4.5 Workshop scripts

| Check | Result |
|---|---|
| `generate_synthetic_data.py` run twice → byte-identical output | ✅ 120 records, 76 patients |
| `deidentify.py` on the committed CSV | ✅ 120 records de-identified |
| `generate_referral_letters.py` + `deidentify_referral_letters.py` | ✅ All 10 letters: every address, phone, date, DOB, patient name and physician redacted. Only clinic names remain (by design). |
| `deidentify_with_comprehend_medical.py --help` | ✅ Parses. The real AWS call was **not** executed (no credentials, and synthetic-only policy). |

### 4.6 Repository hygiene before push

| Check | Result |
|---|---|
| `.env` (holds the GitHub token) is git-ignored | ✅ Confirmed with `git check-ignore` |
| `venv/`, `data/dicom/`, `data/db/`, `*.zip`, `*.dcm` not staged | ✅ 0 matches in the staged file list |
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
| 8 | README described a referral-letter (Demo 2) de-identification step that did not exist | Documentation did not match the code | Added `scripts/deidentify_referral_letters.py` |

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
