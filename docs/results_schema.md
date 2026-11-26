# Results schema

How every experiment in [protocol.md](protocol.md) writes its results, so the
paper's numbers and figures can be rebuilt from the saved files alone.

## Rules for every result file

- **One folder per experiment:** `results/E1/` to `results/E7/`.
- **Aggregates only.** No patient names, IDs, birth dates, accession
  numbers, free-text values or source file paths, even synthetic ones. Files
  are referred to by a SHA-256 hash or by a position in a sorted list.
- **Errors by category,** never by exception message (messages can quote
  identifying values): only the exception type is recorded.
- **Every percentage comes with its count and denominator.**

## `run.json` (in every experiment folder)

Written by each experiment script before any result:

| Field | Meaning |
|---|---|
| `experiment` | `E1` … `E7` |
| `commit` | Full git commit hash of this repository; the run stops if the working tree has uncommitted changes |
| `started_utc`, `finished_utc` | ISO 8601 timestamps |
| `command` | The exact command line |
| `profile` | `basic` or `utility` (or both, for E3/E7) |
| `seed` | `20261125` for synthetic data, `null` otherwise |
| `dataset` | Dataset name, version, DOI, **access date**, split (`validation` / `test`), and the SHA-256 of the sorted list of input-file hashes. For MIDI-B: version `1`, DOI `10.7937/cf2p-aw56`, access date `2026-07-02` |
| `scorer` | E1 and E2(a) only: `repository` (`https://github.com/CBIIT/MIDI_validation_script`) and `commit` (the full 40-character hash used; must equal `ccc0939317d5ffd14edda33bc04641490d6f2254`). `null` for the other experiments |
| `environment` | OS, CPU, RAM, Python version, and versions of pydicom, numpy, SQLAlchemy, psutil and any comparator tool |
| `deviations` | References to entries in the protocol's Deviations section, or empty |

## Per-experiment outputs

| Experiment | File | Contents |
|---|---|---|
| E1 | `scores.csv` | One row per tool × configuration × MIDI-B category: `tool`, `config`, `category`, `passed`, `total`, `rate`, `ci_low`, `ci_high` |
| E1 | `scoring_output/` | The official scoring script's own output, unmodified |
| E2(a) | `leak_capture.csv` | One row per E1 category: `leaking_files`, `quarantined`, `rate`, `ci_low`, `ci_high` |
| E2(b) | `plants.csv` | One row per planted identifier: `location` (top_level, nested_sequence, private_tag, free_text), `attribute`, `file_index`, `detected` (bool). The planted value itself is not stored. |
| E2(b) | `sensitivity.csv` | Per location and overall: `detected`, `planted`, `sensitivity`, `ci_low`, `ci_high`; plus the false-positive rate on files with no plant |
| E3 | `linkage.json` | `patients`, `patients_with_one_token`, `token_collisions`, `intervals_checked`, `intervals_changed`, `max_interval_error_days`, per profile |
| E4 | `quarantine.csv` | One row per modality × reason: `quarantined`, `total`, `rate`, `ci_low`, `ci_high` |
| E5 | `ratings.csv` | One row per attribute: `attribute`, `rater_1`, `rater_2`, `reason_1`, `reason_2` (independent ratings), `resolved` |
| E5 | `agreement.json` | Cohen's kappa and linearly weighted kappa, each with a 95% bootstrap CI, and the confusion matrix |
| E6 | `timing.csv` | One row per run (warm-up marked): `run`, `files`, `bytes`, `seconds`, `files_per_s`, `mb_per_s`, `peak_rss_mb` |
| E7 | `age_error.csv` | Per profile and age group (child under 2, adult, over 90): `n`, `median_abs_error_years`, `p95_abs_error_years` |
| E7 | `uniqueness.csv` | Per profile: `records`, `unique_k1`, `k_lt_5`, with 95% CIs, over age as kept, PatientSex, Modality and study year-month |

## Figures

Figure scripts read only these files and write to `results/figures/`.
They never read DICOM data or the database, so any figure can be rebuilt
without access to the datasets.
