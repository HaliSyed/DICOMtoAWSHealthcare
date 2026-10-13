# How to generate fraud test cases

A step-by-step guide to producing the test documents: the full dataset, chosen
built-in fraud cases, and **your own custom cases** written as a JSON file (no
Python needed). For what the dataset contains and why, see
[README.md](README.md).

- [1. Set up once](#1-set-up-once)
- [2. Generate the full dataset](#2-generate-the-full-dataset)
- [3. Generate only some built-in fraud cases](#3-generate-only-some-built-in-fraud-cases)
- [4. Create your own cases](#4-create-your-own-cases)
- [5. Option reference](#5-option-reference)
- [6. Recipes: "I want to test …"](#6-recipes-i-want-to-test-)
- [7. Reading the results](#7-reading-the-results)
- [8. Troubleshooting](#8-troubleshooting)

---

## 1. Set up once

From the repository root, in a terminal:

```bash
venv\Scripts\activate                        # Windows (Git Bash: source venv/Scripts/activate)
pip install -r frauddetect/requirements.txt
cd frauddetect
python -m pytest tests                       # optional: 33 checks, about 2 minutes
```

All commands below are run from inside `frauddetect/`.

## 2. Generate the full dataset

```bash
python generate.py --overwrite
```

This writes `test_dataset/` (about 450 files, 100 MB, 8 minutes): pristine
PDFs, scans, phone photos, 47 built-in fraud cases, 6 edge cases and
`manifest.csv`.

| To get … | Add |
|---|---|
| More documents per region (3 people, 3 statements, 3 shipments each) | `--variants 3` |
| A different but repeatable set | `--seed 42` |
| Documents dated around another "today" (expiry, statement periods) | `--as-of 2027-01-31` |
| Output somewhere else | `--out D:/data/fraud_ds` |
| Only some parts | `--sections identity,bank,trade,degraded,fraud` (any subset) |

`--overwrite` deletes the old tier folders in the output first. Without it the
script refuses to write over an existing dataset.

## 3. Generate only some built-in fraud cases

Every built-in case has an ID (the table is in [README.md](README.md#fraud-and-edge-cases-04-tier)).

```bash
# just three cases, into a fresh folder
python generate.py --out ../fraud_sample --sections fraud --cases ID05,BK05,TR11

# every UAE-related built-in case
python generate.py --out ../fraud_uae --sections fraud \
    --cases ID01,ID05,ID06,ID18,BK01,BK12,BK13,TR01,TR02,TR04,TR05,TR10,EC01,EC02
```

## 4. Create your own cases

Write a JSON file describing the cases, then run:

```bash
python generate.py --custom examples/custom_cases_uae.json
```

With `--custom` alone, only your cases are generated. They go to
`test_dataset/04_adversarial_fraud/custom/<id>_<name>/` with their own
`manifest_custom.csv`, and the rest of the dataset is left as it is.
Re-running the same file replaces just those case folders. To build everything
plus your cases in one go, add `--sections identity,bank,trade,degraded,fraud --overwrite`.

A working file with 10 cases (8 for the UAE) is in
[`examples/custom_cases_uae.json`](examples/custom_cases_uae.json). Copy it and
edit.

### 4.1 The smallest possible case

```json
{
  "cases": [
    {
      "id": "MY01",
      "name": "expired_emirates_id",
      "expected_result": "fail",
      "expected_findings": ["document_expired"],
      "person": {"region": "UAE"},
      "documents": [
        {"type": "emirates_id", "mutations": [{"op": "expire", "days_ago": 30}]}
      ]
    }
  ]
}
```

This builds an Emirates ID for a generated UAE person, sets the expiry to
30 days before the as-of date (printed date and MRZ both), and records that a
correct validator must **fail** it with the finding `document_expired`.

### 4.2 How a case is put together

```text
case
├── id, name, description, region            labels (id must be unique in the file)
├── expected_result                          fail | review | pass
├── expected_findings                        your names for the defects you planted
├── person            or   people            who is on the documents
└── documents[]                              one or more documents
    ├── type                                 emirates_id, passport, bank_statement, trade, ...
    ├── holder                               which person (when you used "people")
    ├── file                                 optional output file name
    ├── photo                                true = also save a phone photo (identity documents)
    └── mutations[]                          the defects, applied in order
```

**Steps to write a case:**

1. Decide what the validator should conclude: `fail` (reject), `review`
   (send to a human) or `pass` (must accept, e.g. a legitimate spelling variant).
2. Describe the person, or leave the details out and let the generator invent them.
3. List the documents in the submission. Several documents make a
   cross-document case (ID + statement, invoice + seller statement).
4. Add mutations to the documents that should carry a defect. Leave the others clean.
5. Write `expected_findings` so you can score each check separately.

### 4.3 People

`person` is used by every document. For several people, use `people` and point
each document at one with `holder`:

```json
"people": {
  "applicant": {"region": "UK", "given": "Sarah", "surname": "Whitfield", "sex": "F", "dob": "1985-05-04"},
  "other":     {"region": "UK", "given": "Daniel", "surname": "Okafor", "sex": "M"}
},
"documents": [
  {"type": "uk_driving_licence", "holder": "applicant"},
  {"type": "bank_statement", "bank": "UK", "holder": "other"}
]
```

| Field | Meaning |
|---|---|
| `region` (required) | `UAE`, `UK`, `US`, `PK`, `IN`, `BD`, `AU`, `NZ`, `DE`, `FR`, `ES`, `NL` |
| `given`, `surname` | Latin-script name |
| `given_native`, `surname_native` | Arabic / Urdu / Devanagari / Bengali name. **Required together with `given`/`surname` for UAE, PK, IN, BD**, so the two scripts agree |
| `sex` | `M` or `F` |
| `dob` or `age` | `"1990-02-14"`, or an age in years at the as-of date |
| `place_of_birth`, `address`, `father_name`, `father_name_native`, `mother_name` | Optional; generated if missing |

Anything you leave out is generated (repeatably, from the seed).

### 4.4 Documents

| `type` | Extra settings |
|---|---|
| Identity: `emirates_id`, `passport`, `uk_driving_licence`, `us_driving_licence`, `pk_cnic`, `pk_nicop`, `aadhaar`, `pan_card`, `bd_smart_nid`, `bd_paper_nid`, `au_driving_licence`, `au_medicare`, `nz_driving_licence`, `de_id_card`, `es_dni` | `photo: true` adds a phone capture. The holder's region must fit the document (see §5.1). |
| `bank_statement` | `bank`: `UAE`, `UK`, `US`, `PK`, `IN`, `BD`, `AU`, `NZ`, `DE`, `FR`, `NL`. `bucket`: 0–8 (balance band, default 3). `months` (default 3). `corporate`: true for a business account. `holder_name` prints a different name than the person's. |
| `trade` | `scenario`: `UAE_to_PK`, `AU_to_UAE`, `IN_to_UK`, `BD_to_DE`. `documents`: any of `commercial_invoice`, `packing_list`, `bill_of_lading`, `letter_of_credit` (default all). `seller_statement: true` adds the seller's own bank statement, which can take its own `seller_statement_mutations`. |

## 5. Option reference

### 5.1 Identity documents: fields

Use these names in `set_field` and `overlay`.

| Type | Holder region | Fields | MRZ |
|---|---|---|---|
| `emirates_id` | UAE | id_number, name_native, name, dob, nationality, sex, issue_date, expiry_date, card_number, occupation, issuing_place | TD1 (back) |
| `passport` | UAE, UK, US, PK, IN, BD, AU, NZ, FR, DE, ES | doc_type, country_code, document_number, surname, given_names, nationality, dob, sex, place_of_birth, issue_date, authority, expiry_date (+ name_native for UAE/PK/IN/BD, father_name for PK) | TD3 |
| `uk_driving_licence` | UK | surname, given_names, dob_place, issue_date, expiry_date, authority, licence_number, address, categories, categories_table | – |
| `us_driving_licence` | US | licence_number, class, expiry_date, issue_date, surname, given_names, address, dob, sex, height, eyes, dd | PDF417 barcode |
| `pk_cnic`, `pk_nicop` | PK | name, name_native, father_name, sex, country_of_stay, id_number, dob, issue_date, expiry_date, address | – |
| `aadhaar` | IN | name_native, name, dob, sex, aadhaar_number, address | – |
| `pan_card` | IN | pan, name, father_name, dob | – |
| `bd_smart_nid` | BD | name_native, name, father_name, mother_name, dob, nid_number, address, blood_group, issue_date | TD1 (back) |
| `bd_paper_nid` | BD | name_native, name, father_name, mother_name, dob, nid_number, address, blood_group | – |
| `au_driving_licence` | AU | name, address, licence_number, dob, expiry_date, class, card_number | – |
| `au_medicare` | AU | medicare_number, irn, name, valid_to | – |
| `nz_driving_licence` | NZ | surname, given_names, dob, issue_date, expiry_date, licence_number, version, class | – |
| `de_id_card` | DE | card_number, surname, given_names, dob, nationality, place_of_birth, expiry_date, address, issue_date | TD1 (back) |
| `es_dni` | ES | surname, given_names, sex, nationality, dob, support_number, expiry_date, dni | TD1 (back) |

### 5.2 Identity mutations

| `op` | Settings | What it plants |
|---|---|---|
| `expire` | `days_ago` (default 30) | Expiry in the past. Printed date and MRZ are both changed, so the MRZ stays valid. |
| `set_expiry` | `date` or `days_from_today` (negative = past), `mrz` (default true) | Any expiry date. With `"mrz": false` the MRZ keeps the old date (visual vs MRZ mismatch). |
| `set_issue` | `date` or `days_from_today` | Issue date, e.g. after the expiry date |
| `set_dob` | `date` or `age`; `printed` (default true), `mrz` (default true), `barcode` (default true) | New date of birth. Set one of the flags to false to create a mismatch between the printed DOB, the MRZ and the US barcode. |
| `break_check_digit` | `target`: `mrz_document_number`, `mrz_dob`, `mrz_expiry`, `mrz_composite`, `id_number` | One check digit wrong. `id_number` breaks the document's own number rule: Emirates ID Luhn, Aadhaar Verhoeff, Medicare digit, DNI letter, CNIC gender digit, PAN holder type, UK licence DOB encoding, 17-digit BD NID birth year. Breaking an MRZ field digit also breaks the composite digit, as it would on a real document. |
| `set_number` | `value`, `mrz` (default true) | Replaces the main document number, e.g. to duplicate another document's number or test a format. US barcode `DAQ` follows. |
| `set_name` | `given`, `surname`, `mrz` (default false) | Changes the printed name. With `"mrz": true` the MRZ name changes too (a consistent spelling variant). |
| `set_field` | `field`, `value` | Any printed field, as plain text. Nothing else changes. |
| `set_mrz_country` | `code`, e.g. `"CAN"` | Issuing state in the MRZ |
| `set_barcode_field` | `element` (AAMVA code, e.g. `DBB`), `value` | US licence barcode only |
| `overlay` | `field`, `value`, `producer` (optional) | **PDF tamper**: white patch over the printed field, new value typed in a different font, saved as an incremental update, producer set to Photoshop. Combine with `photo: true` for a phone shot of the tampered card. |

### 5.3 Bank statement mutations

`txn` picks a transaction: a number (0 = first), or `salary`, `largest_credit`,
`largest_debit`, `first`, `last`.

| `op` | Settings | What it plants |
|---|---|---|
| `edit_amount` | `txn`, `factor` or `amount`, `recompute` (default false) | Changes an amount without fixing the balance column, so the arithmetic breaks |
| `overlay` | `txn`, `factor` or `value` | PDF tamper of that amount (white patch, different font, incremental save) |
| `inflate_closing` | `factor` (default 3), `structured_files`: `genuine` (default) or `tampered` | Printed closing balance inflated. With `genuine`, MT940/CAMT/OFX keep the real figure. |
| `add_transaction` | `amount`, `description`, `date` or `days_before_end` | A new transaction; balances are recomputed (e.g. funds parked before the cut-off) |
| `move_transaction` | `txn`, `days_before_start` | A transaction dated outside the statement period |
| `shift_period` | `days` | Moves the whole statement (positive = into the future) |
| `mixed_number_format` | `rows` (default 3), `style` (`en`, `de`, `fr`, `lakh`) | Some rows printed in another number format |
| `alter_structured_files` | `txn`, `add_amount` | PDF genuine, MT940/CAMT/OFX changed |
| `break_check_digit` | `target`: `iban`, `routing_number`, `ifsc` | Invalid IBAN / ABA routing / IFSC |
| `set_account` | `key`, `value` | Any account identifier (`iban`, `sort_code`, `account_number`, …) |
| `set_holder` | `name` | Printed account holder |

### 5.4 Trade mutations

| `op` | Settings | What it plants |
|---|---|---|
| `divert_payment` | `account` (optional dict) | Invoice asks for payment to an account that is not on the seller's statement |
| `late_shipment` | `days` (default 6) | Shipped-on-board date after the L/C latest shipment date |
| `scale_quantity` | `factor` | Invoice quantities and total scaled (e.g. 1.25 exceeds the L/C plus tolerance) |
| `line_amount` | `line` (1-based), `factor` | One invoice line ≠ quantity × price; total not updated |
| `break_container` | `index` (default 0) | ISO 6346 check digit wrong on the B/L |
| `gross_weight` | `factor` | Packing-list gross weight differs from the B/L |
| `set` | `doc`, `key`, `value` | Any of: **invoice** `seller_name`, `buyer_name`, `account_name`, `invoice_no`, `invoice_date`, `total`, `pod`; **bl** `consignee`, `notify_name`, `shipper_name`, `bl_no`, `goods_description`, `pod`, `on_board`, `gross_total`; **packing** `gross_total`; **lc** `beneficiary`, `amount`, `latest_shipment`, `expiry`, `pod`. `pod` is `["PKBQM", "Port Qasim, Pakistan"]`; dates are `YYYY-MM-DD`. |

## 6. Recipes: "I want to test …"

| Test | Document | Mutations |
|---|---|---|
| Expired Emirates ID | `emirates_id` | `{"op": "expire", "days_ago": 10}` |
| Emirates ID number typo | `emirates_id` | `{"op": "break_check_digit", "target": "id_number"}` |
| Edited DOB on a photographed ID | `emirates_id`, `"photo": true` | `{"op": "overlay", "field": "dob", "value": "01/01/1980"}` |
| Passport DOB ≠ Emirates ID DOB | `emirates_id` + `passport` | on the passport: `{"op": "set_dob", "date": "1984-01-01"}` |
| Printed DOB ≠ MRZ DOB | `passport` | `{"op": "set_dob", "date": "1984-01-01", "mrz": false}` |
| Minor applying | any ID | person `"age": 16` |
| Name spelt differently (must pass) | `passport` + `bank_statement` | on the passport: `{"op": "set_name", "given": "Mohamed", "mrz": true}`; `expected_result: "pass"` |
| Someone else's bank statement | ID + `bank_statement` with another `holder` | – |
| Photoshopped AED salary | `bank_statement`, `bank: "UAE"` | `{"op": "overlay", "txn": "salary", "factor": 5}` |
| Proof of funds inflated | `bank_statement` | `{"op": "inflate_closing", "factor": 3}` |
| Money parked before cut-off | `bank_statement` | `{"op": "add_transaction", "days_before_end": 1, "amount": 2000000}`; `expected_result: "review"` |
| Invalid UAE IBAN | `bank_statement`, `bank: "UAE"` | `{"op": "break_check_digit", "target": "iban"}` |
| Invoice paid to a fraudster | `trade` with `seller_statement: true` | `{"op": "divert_payment"}` |
| Wrong discharge port | `trade` | `{"op": "set", "doc": "bl", "key": "pod", "value": ["PKBQM", "Port Qasim, Pakistan"]}` |
| Seller name ≠ account holder | `trade` with `seller_statement: true` | `{"op": "set", "doc": "invoice", "key": "seller_name", "value": "Al Nour Trading FZE"}` |

## 7. Reading the results

Each case folder contains:

- the documents (`.pdf`, `.jpg`, and `.mt940` / `.camt053.xml` / `.ofx` / `.mt700.txt` / `.cii.xml` where relevant);
- one `.json` per PDF or photo, holding the true values, the MRZ, the printed
  fields, and a `tampers` / `planted` section for anything that was changed;
- `case.json`, holding the `expected_result`, the `expected_findings` and the
  list of files.

`manifest.csv` (or `manifest_custom.csv`) has one row per file. A simple way to
score a validator:

1. Run each case folder through it as one submission.
2. Compare its decision with `expected_result`.
3. Compare the reasons it gives with `expected_findings`; count each finding as hit or missed.

Remember that `expected_findings` are **your labels**. Map them to whatever
codes your validator emits.

## 8. Troubleshooting

| Message | Fix |
|---|---|
| `error in custom spec: case X document 1: holder 'default' not defined` | Add a `person` to the case, or `holder` + `people` |
| `… needs a holder from [...]` | The document doesn't exist for that region (e.g. `emirates_id` with a UK person) |
| `… for UAE give both 'given' and 'given_native'` | Custom names in Arabic, Urdu, Hindi or Bengali regions need both scripts |
| `field 'x' not on emirates_id; fields are [...]` | Use one of the listed field names (§5.1) |
| `… already has ['01_pristine_digital', …]. Use --overwrite` | Add `--overwrite`, choose another `--out`, or use `--custom` alone |
| `Fonts missing from C:/Windows/Fonts` | Set `FRAUDGEN_FONT_DIR` to a folder with arial, arialbd, Nirmala, NirmalaB, times, timesbd, cour, OCRAEXT, georgia, calibri, tahoma |
| JSON error | Check commas and quotes; Arabic text can be typed directly (save the file as UTF-8) |
