# DICOMtoAWSHealthcare

# From DICOM to Diagnosis — De-identification Demo

Companion repo for the **AWS Community Day UAE 2026** workshop:
**"From DICOM to Diagnosis: Building a Medical Imaging AI Pipeline on AWS."**

This repo contains a small, self-contained demo of the de-identification
stage of a medical imaging AI pipeline — the stage most tutorials skip, and
the one that actually determines whether a healthcare AI pilot survives
contact with a regulator.

## ⚠️ Important: this data is 100% synthetic

Every name, patient ID, date of birth, hospital, and physician in this
repository is machine-generated using [Faker](https://faker.readthedocs.io/)
with a fixed random seed. **None of it is derived from, or traceable to, any
real patient, clinician, or institution.** It exists purely to demonstrate
the shape of the problem and the shape of the fix.

Do not put real patient data in this repo, a fork of it, or any workshop
exercise based on it.

## What's here

```
medical-imaging-deid-demo/
├── README.md
├── requirements.txt
├── LICENSE
├── scripts/
│   ├── generate_synthetic_data.py             # creates the raw (pre-deid) dataset
│   ├── generate_referral_letters.py            # creates synthetic referral text (Path B)
│   ├── deidentify.py                            # the de-identification demo (offline, no AWS needed)
│   └── deidentify_with_comprehend_medical.py    # reference: the real AWS call (needs credentials)
└── data/
    ├── raw_studies.csv            # 120 synthetic records, WITH synthetic PHI
    ├── deidentified_studies.csv   # same 120 records, AFTER de-identification
    └── referral_letters/          # 10 synthetic referral letters (Path B / Textract demo)
```

## Quick start

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cd scripts
python generate_synthetic_data.py --count 120 --out ../data/raw_studies.csv
python generate_referral_letters.py --count 10 --out ../data/referral_letters
python deidentify.py --in ../data/raw_studies.csv --out ../data/deidentified_studies.csv
```

The `data/` folder already ships with pre-generated output, so the demo
works even without running anything live — useful if the venue Wi-Fi has
other plans.

## What the de-identification step actually does

| Field | Before | After |
|---|---|---|
| `patient_name` | `"Allison Hill"` | *dropped entirely* |
| `patient_id` | `"MRN1445199"` | `patient_token = "PT-BAE6458067"` (one-way hash, consistent per patient) |
| `patient_birth_date` | `"1994-06-07"` | `age_band = "30-39"` |
| `patient_age` | `"032Y"` | *dropped* (redundant with `age_band`, and a precise age can re-identify in a small dataset) |
| `referring_physician` | `"Dr. Walker"` | *dropped entirely* |
| `study_date` | `"2024-07-17"` | `study_date_shifted` — shifted by a consistent per-patient offset |
| `burned_in_annotation` | `"Stephanie Miller - 2024-07-17"` | `"[REDACTED] - [REDACTED-DATE]"` |

Two deliberate design choices worth pointing out live:

1. **PHI columns are removed from the schema, not blanked.** An empty
   `patient_name` column sitting in your table is still a column an auditor
   has to ask about. Dropping it removes the question.
2. **The patient token is a one-way hash, not an incrementing ID.** The same
   `patient_id` always produces the same `patient_token`, so repeat studies
   for one (synthetic) patient still link together for research purposes —
   but the token cannot be reversed back to the original MRN.

## Two versions of the redaction step, on purpose

- **`deidentify.py`** uses a small regex pattern to catch name- and
  date-shaped text in the `burned_in_annotation` field. This is what runs in
  the live demo — it works offline, with no AWS credentials, no network
  dependency, and no risk of the workshop stalling on a Wi-Fi hiccup.
- **`deidentify_with_comprehend_medical.py`** shows the production
  equivalent: a real call to
  [Amazon Comprehend Medical's `DetectPHI`](https://docs.aws.amazon.com/comprehend-medical/latest/dev/textanalysis-detectphi.html)
  operation, which uses a trained clinical NLP model instead of a hand-written
  pattern — catches far more than a regex ever will (medication names,
  clinical context, indirect identifiers), at the cost of needing AWS access.

The talking point: **ship the regex version in a slide deck; ship
Comprehend Medical in production.** A regex catches what you thought to
write a pattern for. Real PHI doesn't announce itself that neatly.

## Where this fits in the pipeline

```
Ingestion → De-identify → Store & Index → Preprocess → Inference → Report Gen → Delivery
              ▲
        you are here
```

This repo covers the **De-identify** stage only. `raw_studies.csv`
represents what lands in S3 straight from ingestion; `deidentified_studies.csv`
represents what's safe to hand to AWS HealthImaging and everything downstream.

## Path A vs. Path B

- **Path A (`raw_studies.csv` → `deidentify.py`)** — the AWS HealthImaging
  path: structured DICOM metadata, de-identified as a table.
- **Path B (`referral_letters/`)** — the manual / Textract path: free-text
  documents that would go through Amazon Textract for OCR, then Amazon
  Comprehend Medical for PHI detection before anything touches storage.

## License

MIT — see [LICENSE](LICENSE). Fork it, use it in your own workshop, adapt
the generators for your own synthetic datasets.

## Speaker

**Syed Haider Ali** — Aitropolis Technologies · AWS Community Builder

Session: *From DICOM to Diagnosis: Building a Medical Imaging AI Pipeline on AWS*
AWS Community Day UAE 2026
