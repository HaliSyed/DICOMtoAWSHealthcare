# Fraud-detection test documents

Synthetic identity documents, bank statements and trade documents for testing a
document fraud-detection pipeline, plus the scripts that generate more of them.
Every value is invented, every page is stamped **SPECIMEN · SYNTHETIC TEST DATA ·
NOT VALID**, and every file has a ground-truth JSON next to it.

This folder only produces test data. It contains no detection logic.

**Guides**

- This README: what the dataset contains, coverage, and the built-in fraud cases.
- [HOWTO.md](HOWTO.md): step by step, how to generate everything, pick cases, and
  **write your own fraud cases in a JSON file** (with a full option reference).
- [examples/custom_cases_uae.json](examples/custom_cases_uae.json): 10 ready-made
  custom cases, 8 of them for the UAE.

- [What is synthetic and what is real](#what-is-synthetic-and-what-is-real)
- [Quick start](#quick-start)
- [Output layout](#output-layout)
- [Coverage](#coverage), including [UAE coverage](#uae-coverage)
- [Fraud and edge cases](#fraud-and-edge-cases-04-tier)
- [Custom cases](#custom-cases)
- [Known limitations](#known-limitations)
- [Code layout](#code-layout)

## What is synthetic and what is real

| Real (so parsers are tested properly) | Synthetic (so nothing can be misused) |
|---|---|
| Number formats and check digits: ICAO 9303 MRZ, Emirates ID (Luhn), Aadhaar (Verhoeff), PAN, CNIC, UK licence encoding, Medicare, Spanish DNI letter, IBAN mod-97, ABA, IFSC, BSB, NZ account, ISO 6346 containers | People, addresses, document numbers |
| Field labels, scripts and order (Arabic/Urdu RTL, Bengali, Devanagari, German/French/Spanish) | Layouts: generic, with no state emblems, seals or real security artwork |
| UN/LOCODE ports, HS codes, Incoterms, MT940, CAMT.053, OFX, MT700, UN/CEFACT CII | Banks, carrier, vessels, companies (all fictional names) |
| AAMVA PDF417 payload structure, REAL ID star | Photos: a grey silhouette, never a face |

For official layouts (real specimen passports and IDs), use the EU PRADO
register as the README of the main project suggests; this generator does not
copy them.

## Quick start

```bash
venv\Scripts\activate                       # from the repository root
pip install -r frauddetect/requirements.txt
cd frauddetect
python generate.py                          # ~4 min, writes ./test_dataset
python -m pytest tests                      # generator self-checks (33 tests, ~2 min)
python generate.py --custom examples/custom_cases_uae.json   # add your own cases (HOWTO.md)
```

Options:

```bash
python generate.py --variants 3                       # 3 people / statements / shipments per region
python generate.py --seed 42 --as-of 2027-01-31 --out D:/data/fraud_ds --overwrite
python generate.py --sections identity,bank            # skip trade, degraded tiers and fraud cases
python generate.py --sections fraud --cases ID20,BK05  # just some adversarial cases
python generate.py --custom my_cases.json             # only your own cases, rest of the dataset untouched
```

The same seed, as-of date and fonts always produce the same documents. Fonts
come from `C:/Windows/Fonts` (Arial, Nirmala UI, Times, Courier, OCR-A); on
other systems set `FRAUDGEN_FONT_DIR` to a folder holding those files.

`test_dataset/` is generated output and is not committed.

## Output layout

```
test_dataset/
├── manifest.csv               one row per file: tier, region, doc_type, label, expected result, findings
├── 01_pristine_digital/       native PDFs with a real text layer
│   ├── identity/<UAE|UK|US|PK|IN|BD|AU|NZ|EU>/   <doc>.pdf + <doc>.json
│   ├── bank_statements/<region>/                 statement .pdf + .mt940 + .camt053.xml + .ofx + .json
│   └── trade/<scenario>_NN/                      invoice, packing list, B/L, L/C (.pdf + MT700) + CII XML
│                                                 + the seller's own bank statement
├── 02_scanned_physical/       same documents as image-only PDFs: 300 DPI greyscale, skew, blur, noise, dust
├── 03_mobile_captures/        same documents as JPEG phone photos: perspective, glare, low light, motion blur
└── 04_adversarial_fraud/
    ├── identity/ bank_statement/ trade/ cross_document/   one folder per fraud case
    └── edge_cases/                                         must pass a correct validator
```

Each degraded file has a JSON sidecar giving the source document, the ground
truth file and the capture effects applied (skew angle, glare position, gamma).

Each fraud or edge-case folder is one *submission*: the documents, a JSON per
document, and `case.json` with `expected_result` (`fail`, `review` or `pass`)
and `expected_findings`, the list of planted defects. Score a validator per
finding rather than just per document.

## Coverage

### Identity documents (01 tier, per variant)

| Region | Documents | What it exercises |
|---|---|---|
| UAE | Emirates ID (front + back with TD1 MRZ), passport | Arabic/English, RTL, `784-YYYY-NNNNNNN-C` with Luhn and birth year |
| UK | Passport (numbered fields, surname first), driving licence | DVLA number encoding surname, DOB and sex |
| US | Driver licence (front + PDF417 back), passport | State formats (CA, TX, NY, FL), REAL ID star, AAMVA barcode, MM/DD/YYYY |
| PK | CNIC, NICOP (same number), passport | Urdu/English, `XXXXX-XXXXXXX-X`, gender digit, CNIC in passport MRZ |
| IN | Aadhaar, PAN card, passport | Devanagari, Verhoeff, `AAAPA1234A` structure |
| BD | Smart NID (10 digits, MRZ), old paper NID (17 digits), passport | Bengali, both NID formats |
| AU | Driver licence (NSW, VIC, QLD), Medicare card, passport | Card number separate from licence number (on the back for VIC), Medicare check digit |
| NZ | Driver licence, passport | Licence number + version number |
| EU | German ID card (TD1), Spanish DNI (TD1), French/German/Spanish passports | Multilingual labels, `D<<` code, DNI letter, ICAO transliteration (Ü → UE) |

### UAE coverage

The UAE is covered in every part of the dataset:

| Area | What is generated |
|---|---|
| Identity | **Emirates ID** (front with Arabic/English fields; back with card number, occupation and TD1 MRZ carrying the 15-digit ID), **UAE passport** (bilingual labels, Arabic name, TD3 MRZ `P<ARE…`) |
| Bank | **Al Waha National Bank PJSC** (fictional) AED statements: `AE` IBAN (23 chars, mod-97), AED shown as `AED`, `Dh` or `د.إ`, Arabic title, personal and corporate accounts, MT940 / CAMT.053 / OFX |
| Trade | **UAE→Pakistan** (Jebel Ali `AEJEA` → Karachi) with a UAE seller and a UAE corporate statement, and **Australia→UAE** (→ Jebel Ali) with a UAE issuing bank |
| Built-in fraud cases | ID01 passport MRZ, ID05 Emirates ID Luhn, ID06 Emirates ID birth-year segment, ID18 expiry before issue, BK01 IBAN, BK12 cash deposit before cut-off, BK13 someone else's statement, TR01, TR02, TR04, TR05, TR10 (UAE shipments) |
| Edge cases | EC01 MOHAMMAD vs Mohammed, EC02 "SHEIKH" in given names |
| Custom examples | CU01–CU08 in `examples/custom_cases_uae.json`: expired passport, minor's Emirates ID, Emirates ID vs passport DOB, DOB overlay with phone photo, AED salary overlay + inflated balance, funds parking, name spelling, Jebel Ali shipment with diverted payment |

Not yet covered for the UAE: UAE driving licence, trade licence, Ejari
tenancy contract, salary certificate, visa or residence permit page. These can
be added as new document types.

### Bank statements

One statement per bank per variant: UAE, UK, US, PK, IN, BD, AU, NZ, DE, FR, NL.
The holder is the same person as that region's identity documents, so genuine
cross-document checks match. Opening balances run through the nine proof-of-funds
buckets (< £50K up to £10M+). The ground truth gives the GBP equivalent and
bucket at fixed synthetic FX rates.

Formats covered: AED shown as `AED`, `Dh` or `د.إ`; sort code with 8-digit
account; ABA routing; PK IBAN; IFSC with lakh/crore grouping (`1,02,34,567.89`);
BDT `৳`/`Tk`; BSB; NZ `XX-XXXX-XXXXXXX-XX`; DE/FR/NL IBAN with `1.234,56` /
`1 234,56`; headings in German, French and Dutch; UK `04 May 2026`, US
`05/04/2026`, DE `04.05.2026`.

### Trade documents

Four lanes: UAE→Pakistan (polymers), India→UK (textiles), Bangladesh→Germany
(garments), Australia→UAE (frozen meat). Each has a commercial invoice, packing
list, bill of lading, letter of credit (PDF + MT700), CII invoice XML and the
seller's corporate bank statement. The invoice's beneficiary account is the
account on that statement.

## Fraud and edge cases (04 tier)

| ID | Expected | Planted defect |
|---|---|---|
| ID01 | fail | UAE passport MRZ document-number check digit wrong |
| ID02 | fail | UK passport MRZ composite check digit wrong |
| ID03 | fail | Indian passport printed DOB differs from MRZ DOB |
| ID04 | fail | Pakistani passport printed surname differs from MRZ |
| ID05 | fail | Emirates ID fails Luhn |
| ID06 | fail | Emirates ID birth-year segment differs from DOB (checksum valid) |
| ID07 | fail | CNIC last digit parity contradicts gender |
| ID08 | fail | Aadhaar fails Verhoeff |
| ID09 | fail | Aadhaar starts with 1 (valid Verhoeff) |
| ID10 | fail | PAN holder-type and surname-initial characters wrong |
| ID11 | fail | UK licence number encodes a different DOB |
| ID12 | fail | US licence PDF417 DOB differs from front |
| ID13 | fail | AU licence card number = licence number |
| ID14 | fail | Medicare check digit wrong |
| ID15 | fail | Spanish DNI control letter wrong |
| ID16 | fail | 17-digit BD NID prefix is not the birth year |
| ID17 | fail | NZ licence expired |
| ID18 | fail | Emirates ID expiry before issue |
| ID19 | fail | UK licence holder aged 15 |
| ID20 | fail | German ID PDF: DOB patched over in a different font, incremental save, Photoshop producer |
| ID21 | fail | Two French passports, different holders, same number |
| ID22 | fail | US passport MRZ issuing state `CAN` |
| ID23 | fail | Pakistani passport personal number ≠ holder's CNIC |
| BK01 | fail | IBAN fails mod-97 |
| BK02 | fail | ABA routing check digit wrong |
| BK03 | fail | One debit edited; running balance no longer adds up |
| BK04 | fail | Closing balance inflated ×3.2; MT940/CAMT keep the real one |
| BK05 | fail | Salary credit patched ×10 in a different font, incremental save |
| BK06 | fail | IFSC 5th character is letter O, not zero |
| BK07 | fail | Valid IBAN embeds a different sort code |
| BK08 | fail | Statement period ends in the future |
| BK09 | fail | Transaction dated before the statement period |
| BK10 | fail | Three rows use `1,234.56` in a `1.234,56` statement |
| BK11 | fail | PDF genuine, MT940/CAMT/OFX altered |
| BK12 | review | Large round cash deposit two days before period end |
| BK13 | fail | ID for one person, statement in another's name |
| TR01 | fail | Invoice line ≠ qty × price, total ≠ sum of lines |
| TR02 | fail | Invoice seller "Al Nour … FZE" vs account holder "Al Noor … LLC" |
| TR03 | fail | Container number fails ISO 6346 |
| TR04 | fail | B/L to order of shipper, wrong notify party |
| TR05 | fail | B/L port of discharge differs from L/C |
| TR06 | fail | Shipped on board after L/C latest shipment date |
| TR07 | fail | Invoice exceeds L/C amount + 5% tolerance |
| TR08 | fail | Packing list gross weight 12% above B/L |
| TR09 | fail | B/L goods description differs from invoice |
| TR10 | fail | Same invoice number on two shipments (double financing) |
| TR11 | fail | Invoice beneficiary account is not the seller's account |
| EC01 | pass | Passport MOHAMMAD vs statement Mohammed |
| EC02 | pass | "SHEIKH" in given names |
| EC03 | pass | `04/05/2026` = 5 April in the US statement, 4 May in the UK one |
| EC04 | pass | ü, ñ, é, ï with ICAO MRZ transliteration |
| EC05 | pass | "Private Limited" vs "Pvt Ltd" |
| EC06 | pass | Same holder's 17-digit paper NID and 10-digit smart NID |

Most identity cases also include a phone photo (`*_photo.jpg`) of the tampered
document, because that is how most fraudulent uploads arrive.

## Custom cases

You can define your own fraud cases in a JSON file: who is on the documents,
which documents are in the submission, and which defects to plant. No Python is
needed. Example: an expired UAE passport with a bad MRZ check digit:

```json
{"cases": [{
  "id": "CU01", "name": "uae_passport_expired_and_bad_mrz",
  "expected_result": "fail",
  "expected_findings": ["document_expired", "mrz_check_digit_document_number"],
  "person": {"region": "UAE", "given": "Omar", "surname": "Al Hammadi",
             "given_native": "عمر", "surname_native": "الحمادي", "sex": "M", "dob": "1988-03-14"},
  "documents": [{"type": "passport", "photo": true, "mutations": [
    {"op": "expire", "days_ago": 45},
    {"op": "break_check_digit", "target": "mrz_document_number"}
  ]}]
}]}
```

```bash
python generate.py --custom my_cases.json
# -> test_dataset/04_adversarial_fraud/custom/CU01_uae_passport_expired_and_bad_mrz/
```

The options:

- **Identity:** expire, set_expiry, set_issue, set_dob, break_check_digit, set_number, set_name, set_field, set_mrz_country, set_barcode_field, overlay.
- **Bank statements:** edit_amount, overlay, inflate_closing, add_transaction, move_transaction, shift_period, mixed_number_format, alter_structured_files, break_check_digit, set_account, set_holder.
- **Trade:** divert_payment, late_shipment, scale_quantity, line_amount, break_container, gross_weight, set.

All of them are explained in [HOWTO.md](HOWTO.md#5-option-reference).

## Known limitations

- **Bengali and Devanagari text layers are unreliable.** The PDFs render these
  scripts correctly, but shaped conjuncts have no one-to-one Unicode mapping, so
  extracted text is garbled (real Indian and Bangladeshi PDFs often behave the
  same way). Use OCR or the ground-truth JSON. Arabic, Urdu and Latin text
  extracts cleanly.
- Layouts are generic. They test field parsing, not template matching against
  official designs.
- No security features (holograms, UV, microprint) and no faces, so liveness and
  face matching cannot be tested with this data.
- FX rates for the balance buckets are fixed synthetic values, not market rates.

## Code layout

| File | Purpose |
|---|---|
| `generate.py` | CLI; builds all tiers and `manifest.csv` |
| `fraudgen/checksums.py` | Check-digit algorithms |
| `fraudgen/mrz.py` | ICAO 9303 TD1/TD3 MRZ builder |
| `fraudgen/people.py` | Fictional people and per-region document numbers |
| `fraudgen/identity.py` | ID cards, licences, passports and their rendering |
| `fraudgen/banking.py` | Statements, MT940, CAMT.053, OFX |
| `fraudgen/trade.py` | Invoice, packing list, B/L, L/C, MT700, CII |
| `fraudgen/degrade.py` | Scan and phone-capture effects |
| `fraudgen/fraud.py` | Built-in adversarial and edge-case catalogue |
| `fraudgen/custom.py` | Reads custom-case JSON files and applies the mutations |
| `examples/custom_cases_uae.json` | Example custom cases (UAE, India, UK) |
| `HOWTO.md` | Step-by-step guide and option reference |
| `fraudgen/render.py` | PDF drawing helpers, fonts, SPECIMEN watermark |
| `tests/test_fraudgen.py` | Checks that genuine documents pass every rule and that each planted defect is present |

To add a case without code, use a custom JSON file ([HOWTO.md](HOWTO.md)). To
add a permanent built-in case, add a function decorated with `@case(...)` in
`fraudgen/fraud.py` and a matching assertion in the tests.
