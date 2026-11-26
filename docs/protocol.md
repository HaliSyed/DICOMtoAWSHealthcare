# Experimental protocol

**Status: FROZEN.** Every open decision is resolved (see
[Open decisions](#open-decisions)). This version is merged into `main` before
any experiment is run, so the commit timestamp records the plan ahead of the
results. From now on, any change is made in a new commit, listed under
[Deviations](#deviations-from-this-protocol), and reported in the paper.

**Software under test:** this repository. Every result file records the
commit hash it was produced from (see [results_schema.md](results_schema.md)).
The frozen protocol is released as v0.2.0 ("protocol frozen"), which gives it
a Zenodo DOI and timestamp. v1.0.0 is released after the experiments.

---

## 1. Aim

Measure how well the pipeline removes identifying metadata from DICOM files,
how much the independent verifier adds on top of the de-identification
rules, and what the privacy safeguards cost in research utility.

This is a software evaluation. It does not test clinical outcomes, and no
result will be presented as proof of anonymity or of regulatory compliance.

## 2. Data

| Dataset | Used in | Notes |
|---|---|---|
| **MIDI-B** (Medical Image De-Identification Benchmark, NCI, on TCIA): DICOM files with synthetic identifiers planted, an answer key and an official scoring script | E1, E2(a), E4, E6 | Collections `MIDI-B-Synthetic-Validation` (216 patients) and `MIDI-B-Synthetic-Test` (322 patients): in total 538 patients, 605 studies, 708 series and 53,581 instances (Rutherford et al., arXiv:2508.01889). DOI: 10.7937/cf2p-aw56. Licence: CC BY 4.0 under the TCIA Data Usage Policy; citation required (confirmed on the TCIA collection page). Cite as: "Data in Support of the MIDI-B Challenge (MIDI-B-Synthetic-Validation, MIDI-B-Curated-Validation, MIDI-B-Synthetic-Test, MIDI-B-Curated-Test)", Version 1. Collection version: 1, updated 2025-05-02. Access date: the date of the copy used, recorded in `data/midi/PROVENANCE.md` when the copy is downloaded, together with a check that the sizes match TCIA (Synthetic Validation 7.63 GB, 216 subjects; Synthetic Test 11.09 GB, 322 subjects). Only the two Synthetic collections are used; the Curated collections are not. Scoring script: https://github.com/CBIIT/MIDI_validation_script pinned at commit `ccc0939317d5ffd14edda33bc04641490d6f2254` (2026-06-22; latest tag v3.14), also written to each `run.json`. The test answer key is public, so the test set is run once, at the frozen commit, and never used for tuning. File checksums are written to `results/datasets.json` by the scripts. **Never committed to git.** Splits: see 2.1. |
| **Synthetic cohort** (part of this study, built by `experiments/cohort.py`; `dicom-deid synth` is not used): 100 synthetic patients with 3 to 5 studies each, including at least 20 children under 2 years at their first study and at least 5 patients over 90, generated with seed `20261125` | E3, E7 | Generated, never downloaded; the seed and generator commit are recorded. |
| **Seeded-identifier set**: 200 planted synthetic identifiers in at least 20 synthetic files, seed `20261125` | E2(b) | See E2(b). |
| **Attribute list** of everything the pipeline removes or changes | E5 | Produced from the de-identification rules at the frozen commit. |

### 2.0 No real patient or hospital data

**No hospital or patient data is used in this study.** The data are the MIDI-B
Synthetic collections (public, with synthetic identifiers), the synthetic
cohort and the seeded-identifier set. No file from Al-Kareem Hospital or from
any other hospital, and no personal record, enters any experiment.

- Al-Kareem Hospital, Rawalpindi appears only in the raters' background in E5
  (one rater formerly worked there; both support the hospital in good faith).
- The only DICOM files in this repository are five public Rubo Medical demo
  samples in `tests/data/dicom/` (patient name "Rubo DEMO"). They are used by
  the test suite only, in no experiment.
- Checked on 2026-11-26: no hospital name and no non-synthetic patient data in
  the tracked files or in the git history. Real data is processed only in a
  separate, access-controlled environment inside the UAE, never in this
  repository.
- If real or modified-real data were ever added, that would be a deviation
  and would need consent and ethics approval first.

### 2.1 Tuning and test discipline

- De-identification and verifier rules, and the tuned comparator
  configuration (E1), may be developed **only** on the MIDI-B **validation**
  set.
- The MIDI-B **test** set is run **once**, at the frozen commit, after all
  development has stopped. If that run fails for a technical reason (crash, not a
  score), the fix and the re-run are reported as a deviation.
- No rule is added, removed or changed after the test-set results are seen.

## 3. Experiments

**No success thresholds are set.** Each experiment instead pre-specifies its
primary metric, and the paper reports it whatever its value:

| Experiment | Primary metric |
|---|---|
| E1 | Pass rate per MIDI-B category (and overall) on the test set |
| E2(a) | Share of E1 failures caught by quarantine |
| E2(b) | Verifier sensitivity per planting location |
| E3 | Linkage, collision and interval checks (expected 100% / 0 / 0 days) |
| E4 | Quarantine rate per modality and per reason |
| E5 | Cohen's kappa between the two raters |
| E6 | Files per second (median of 5 runs) |
| E7 | Age error and share of unique records, per profile |

Unless stated otherwise, proportions are reported with counts, denominators
and **95% Wilson score confidence intervals**. Files from one patient are not
independent, so file-level results are also given per patient where the
data allows (cluster bootstrap by patient, 2,000 resamples, as a sensitivity
analysis).

### E1: Metadata de-identification on MIDI (headline result)

- **Question.** How well does the pipeline remove patient data on a public
  benchmark others also use?
- **Method.** Run the pipeline (basic profile) on the MIDI test set. Score the
  output with MIDI's official scoring script against the answer key.
- **Metrics.** Pass/fail rate per MIDI category and overall, as produced by
  the scoring script, with 95% CIs.
- **Comparison.** pydicom's `deid` package on the same files, scored with
  the same script, run twice: once with its default recipe, and once with a
  recipe tuned on the validation set only. Its version and both recipes are
  recorded. RSNA CTP is added only if time allows, under the same rules, and
  reported as a deviation if added.
- **Primary metric.** Per-category pass rate with 95% CIs. No threshold.

### E2: Does the verifier catch what the rules miss? (main contribution)

- **Question.** When the de-identification rules miss an identifier, does the
  independent verifier stop the file from being released?
- **E2(a), on MIDI.** For every file that E1 scores as still leaking, check
  whether the pipeline quarantined it.
  Primary metric: share of leaking files that were quarantined, with 95% CI.
  These are the mistakes that never leave the pipeline.
- **E2(b), seeded identifiers.** Plant 50 synthetic identifiers in each of 4
  locations, 200 in total, spread over at least 20 synthetic files (seed
  `20261125`):
  1. top-level attributes;
  2. nested sequences;
  3. private tags;
  4. free-text attributes.
  The plants are generated from this specification, independently of the
  de-identification and verifier rules.
  Primary metric: verifier sensitivity per location and overall, with 95%
  CIs. Secondary: false-positive rate on files with no plant.
- **No success threshold.**

### E3: Longitudinal linkage and time intervals

- **Question.** After pseudonymisation, are a patient's scans still linked,
  with the gaps between them unchanged?
- **Method.** The synthetic cohort (100 patients, 3 to 5 studies each, known
  dates), basic and utility profiles.
- **Metrics.**
  - Linkage: every patient keeps exactly one token (expected 100%).
  - Collisions: no two patients share a token (expected 0).
  - Intervals: every gap between two studies of one patient is unchanged to
    the day (expected 100%; any non-zero error is reported with its size).
- **Expected result.** All three expectations met; any failure is reported as a defect, not a threshold miss.

### E4: Quarantine volume and reasons

- **Question.** How many files are held back for review, and why?
- **Method.** From the E1 run, count quarantined files by modality (CT, MR,
  US, and so on) and by recorded reason (`status_reason`: burned-in text risk,
  residual-identifier check failed).
- **Metrics.** Quarantine rate per modality and per reason, with 95% CIs.
  Ultrasound is reported separately because of its role in obstetrics.
- **No success threshold.**

### E5: Clinical relevance of removed attributes

- **Question.** Which removed or changed details would clinicians need?
- **Raters.** Dr. Syeda Sana Ali (Specialist Obstetrician and Gynaecologist,
  Al Tadawi Specialty Hospital, UAE; formerly permanent staff at Al-Kareem
  Hospital, Rawalpindi, Pakistan) and Dr. Syeda Itrat Fatima (Senior Clinical
  Fellow, Paediatrics, Addenbrooke's Hospital, Cambridge, UK). Both support
  Al-Kareem Hospital in good faith.
- **Method.** The two raters, independently and without seeing each other's
  ratings, rate every attribute the pipeline removes or changes:
  *essential*, *useful* or *not needed*, with a one-line reason.
- **Limitations, stated in the paper.** Both raters are co-authors and
  therefore not independent of the study. Neither is a radiologist, and no
  radiologist rated the attributes, so the ratings reflect the needs of
  obstetric and paediatric users of imaging, not of image interpretation.
- **Metrics.** Cohen's kappa with a 95% bootstrap CI (primary), and linearly
  weighted kappa (secondary, because the scale is ordered). Disagreements are
  resolved by discussion after kappa is computed; both the independent and
  the resolved ratings are published.
- **No success threshold.**

### E6: Performance

- **Question.** How fast is the pipeline?
- **Method.** Time the full ingest on a stated machine (CPU, RAM, disk, OS,
  Python version recorded). 5 runs after one warm-up run, on the MIDI-B
  validation set.
- **Metrics.** Files per second and MB per second (median and range over the
  5 runs) and peak memory. Peak memory is the process's peak resident set size, read with `psutil` (an
  experiment-only dependency, version recorded).
- **No success threshold.**

### E7: Age accuracy versus re-identification risk

- **Question.** How wrong does a patient's age become under each
  de-identification profile, and does keeping exact age make records easier
  to single out?
- **Profiles.**
  - *basic*: 10-year age band, ages 90 and over collapsed into `90+`.
  - *utility*: `PatientAge` kept in its finest DICOM unit (days, weeks, months
    or years), computed at the study date, with ages of 90 and over capped
    at `090Y`; size and weight kept.
- **Method.** The synthetic cohort, whose true ages are known, including
  the children under 2 and the patients over 90.
- **Metrics.**
  - Age error: absolute difference, in years, between the **true** age and
    the age the output allows; median and 95th percentile, reported
    separately for children under 2, adults under 90 and patients aged 90
    and over. Error is always measured against the true age, never against
    a capped or banded value. For *basic* the age allowed is the band
    midpoint (`0-9` is 4.5 years, `10-19` is 14.5, and so on). For the
    `90+` band, and for *utility* at 90 and over, the age allowed is 90 (the
    value written as `090Y`), so the error is `true age - 90`. Patients
    aged 90 and over are reported separately and the paper explains that
    the cap, not the pipeline, causes their error. For *utility* below 90
    the age is kept exactly, so the error is 0. Children under 2 are the
    group where the profiles differ most.
  - Uniqueness: share of records that are unique (k = 1) and share with
    k < 5, over four quasi-identifiers (age as kept by the profile,
    PatientSex, Modality, and study year-month after date shifting), under
    each profile. The **primary unit is one study**, the unit of release.
    Secondary: the share of patients with at least one unique study.
- **No success threshold.**

### E8: AI-agent use of de-identified data

AI-agent use of de-identified data (OctoTools) is future work and out of
scope for this study.

## 4. What we will not do

- Tune any rule on the MIDI test set, or re-run the test set to improve a score.
- Drop files, categories or patients from the results without reporting them.
- Report a percentage without its count and denominator.
- Describe the results as anonymisation, as regulatory compliance or as
  clinical validation.
- Claim anything about burned-in pixel text beyond what the quarantine rule
  does: pixel data is not inspected.

## 5. Reproducibility

Each experiment has one script under `experiments/` (E1 to E7). Each script
writes its results and the commit hash, configuration, seed, dataset
checksums and software versions it ran with (see
[results_schema.md](results_schema.md)). Separate scripts rebuild every figure
from the saved results alone. The README section "Reproducing the paper"
gives the exact commands.

## Open decisions

All resolved; the protocol is frozen.

| # | Where | Decision | Answer |
|---|---|---|---|
| 1 | E7, age error | Age allowed by the `90+` band | Resolved: 90 (`090Y`); error is `true age - 90` |
| 2 | E7, uniqueness | Unit of a record | Resolved: one study (primary); patients with a unique study (secondary) |
| 3 | Section 2 | MIDI-B licence check, collection version, access date, scoring script commit hash | Resolved: CC BY 4.0 (TCIA Data Usage Policy); version 1 (2025-05-02); access date in `data/midi/PROVENANCE.md`; scorer pinned at `ccc0939` |
| 4 | E5 | Hospital of the two raters | Resolved: Dr. Sana Ali, Al Tadawi Specialty Hospital, UAE (formerly Al-Kareem Hospital, Rawalpindi); Dr. Itrat Fatima, Addenbrooke's Hospital, Cambridge, UK; both support Al-Kareem Hospital in good faith |
| 5 | E5 | Titles of the two raters | Resolved: Specialist Obstetrician and Gynaecologist (Dr. Sana Ali); Senior Clinical Fellow, Paediatrics (Dr. Itrat Fatima) |
| 6 | Section 2.0 | Which experiments use the modified real-source files | Resolved: none; no real data is used |
| 7 | Section 2.0 | Consent scope, ethics or institutional approval | Resolved: not applicable, no real data is used |
| 8 | Section 2.0 | How the files were modified; counts per source | Resolved: not applicable |
| 9 | Section 2.0 | Where the files are held; licence of each public source | Resolved: not applicable; the only public source is MIDI-B (row 3) |

## Deviations from this protocol

None so far. Each deviation is listed here with its date, what changed, why,
and which results it affects.
