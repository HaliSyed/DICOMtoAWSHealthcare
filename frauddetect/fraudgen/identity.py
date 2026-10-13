"""Identity documents: national ID cards, driving licences, passports.

Layouts are generic (no state emblems or real security artwork); they reproduce
what a parser has to cope with: field order, bilingual labels, RTL text, number
formats, MRZ zones and barcodes.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from . import people as P
from . import render as R
from .mrz import td1, td3
from .render import esc, mm

CARD = (mm(85.6), mm(54))
PASSPORT = (mm(125), mm(88))
PAPER = (mm(95), mm(62))

_MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def dmy(d: date, sep: str = "/") -> str:
    return f"{d.day:02d}{sep}{d.month:02d}{sep}{d.year}"


def mdy(d: date) -> str:
    return f"{d.month:02d}/{d.day:02d}/{d.year}"


def dmony(d: date) -> str:
    return f"{d.day:02d} {_MON[d.month - 1]} {d.year}"


def yymmdd(d: date) -> str:
    return d.strftime("%y%m%d")


@dataclass
class Field:
    key: str
    label: str  # HTML allowed (bilingual labels)
    value: str
    rtl: bool = False
    wide: bool = False
    big: bool = False


@dataclass
class IdDoc:
    doc_type: str
    region: str
    country: str
    layout: str  # card | passport | paper
    title: str  # HTML
    subtitle: str  # HTML
    person: P.Person
    fields: list[Field]
    back_fields: list[Field] = field(default_factory=list)
    mrz: list[str] = field(default_factory=list)
    barcode: str = ""
    real_id_star: bool = False
    theme: tuple = (0.12, 0.32, 0.55)
    truth: dict = field(default_factory=dict)  # canonical values (ISO dates, raw numbers)

    def get(self, key: str) -> Field:
        for f in self.fields + self.back_fields:
            if f.key == key:
                return f
        raise KeyError(key)


def _validity(rng: random.Random, as_of: date, years: int) -> tuple[date, date]:
    issue = as_of - timedelta(days=rng.randint(60, years * 365 - 120))
    expiry = date(issue.year + years, issue.month, min(issue.day, 28)) - timedelta(days=1)
    return issue, expiry


def _truth(p: P.Person, **kw) -> dict:
    base = {"given": p.given, "surname": p.surname, "sex": p.sex, "dob": p.dob.isoformat(),
            "place_of_birth": p.place_of_birth, "address": p.address}
    if p.given_native:
        base["name_native"] = p.full_name_native
    if p.father_name:
        base["father_name"] = p.father_name
    base.update({k: (v.isoformat() if isinstance(v, date) else v) for k, v in kw.items()})
    return base


# --- passports (TD3, shared by all regions) -----------------------------------

_PASSPORT_TITLE = {
    "UAE": ("UNITED ARAB EMIRATES · <span dir='rtl'>الإمارات العربية المتحدة</span>", "PASSPORT · <span dir='rtl'>جواز سفر</span>"),
    "UK": ("UNITED KINGDOM OF GREAT BRITAIN AND NORTHERN IRELAND", "PASSPORT · PASSEPORT"),
    "US": ("UNITED STATES OF AMERICA", "PASSPORT · PASSEPORT · PASAPORTE"),
    "PK": ("ISLAMIC REPUBLIC OF PAKISTAN · <span dir='rtl'>اسلامی جمہوریہ پاکستان</span>", "PASSPORT · <span dir='rtl'>پاسپورٹ</span>"),
    "IN": ("REPUBLIC OF INDIA · भारत गणराज्य", "PASSPORT · पासपोर्ट"),
    "BD": ("PEOPLE'S REPUBLIC OF BANGLADESH · গণপ্রজাতন্ত্রী বাংলাদেশ", "PASSPORT · পাসপোর্ট"),
    "AU": ("AUSTRALIA", "PASSPORT"),
    "NZ": ("NEW ZEALAND · AOTEAROA", "PASSPORT · URUWHENUA"),
    "FR": ("RÉPUBLIQUE FRANÇAISE", "PASSEPORT · PASSPORT"),
    "DE": ("BUNDESREPUBLIK DEUTSCHLAND", "REISEPASS · PASSPORT · PASSEPORT"),
    "ES": ("REINO DE ESPAÑA", "PASAPORTE · PASSPORT"),
}

_AUTHORITY = {"UAE": "Dubai", "UK": "HMPO", "US": "United States Department of State",
              "PK": "DGI&P Islamabad", "IN": "Mumbai", "BD": "DIP Dhaka", "AU": "Australia",
              "NZ": "New Zealand", "FR": "Préfecture de Paris", "DE": "Stadt Berlin", "ES": "DGP Madrid"}

_THEME = {"UAE": (0.1, 0.4, 0.3), "UK": (0.35, 0.1, 0.2), "US": (0.1, 0.2, 0.45),
          "PK": (0.05, 0.35, 0.15), "IN": (0.1, 0.15, 0.4), "BD": (0.0, 0.4, 0.25),
          "AU": (0.1, 0.25, 0.4), "NZ": (0.05, 0.1, 0.15), "FR": (0.3, 0.05, 0.15),
          "DE": (0.4, 0.05, 0.1), "ES": (0.4, 0.1, 0.1)}

_BILINGUAL = {
    "UAE": {"surname": "Surname / <span dir='rtl'>اللقب</span>", "given": "Given Names / <span dir='rtl'>الاسم</span>",
            "native": "<span dir='rtl'>الاسم بالعربية</span>"},
    "PK": {"surname": "Surname / <span dir='rtl'>خاندانی نام</span>", "given": "Given Names / <span dir='rtl'>نام</span>",
           "native": "<span dir='rtl'>نام اردو میں</span>"},
    "IN": {"surname": "उपनाम / Surname", "given": "दिया गया नाम / Given Name(s)", "native": "नाम / Name (Hindi)"},
    "BD": {"surname": "Surname / বংশগত নাম", "given": "Given Name / প্রদত্ত নাম", "native": "নাম / Name (Bangla)"},
    "FR": {"surname": "Nom / Surname", "given": "Prénoms / Given names"},
    "DE": {"surname": "Name / Surname / Nom", "given": "Vornamen / Given names / Prénoms"},
    "ES": {"surname": "Apellidos / Surname", "given": "Nombre / Given names"},
}


def passport(p: P.Person, rng: random.Random, as_of: date, extra_personal: str = "") -> IdDoc:
    r = p.region
    num = P.passport_number(r, rng)
    issue, expiry = _validity(rng, as_of, 10 if r not in ("PK", "BD", "IN") else 10)
    code = P.ISO3[r]
    labels = _BILINGUAL.get(r, {})
    fdate = mdy if r == "US" else dmony
    uk_numbered = r == "UK"
    def L(key: str, default: str, n: int) -> str:
        lab = labels.get(key, default)
        return f"{lab} ({n})" if uk_numbered else lab
    fields = [
        Field("doc_type", "Type", "P"), Field("country_code", "Code", code),
        Field("document_number", "Passport No.", num),
        Field("surname", L("surname", "Surname", 1), p.surname.upper(), wide=True),
        Field("given_names", L("given", "Given Names", 2), p.given.upper(), wide=True),
    ]
    if p.given_native:
        fields.append(Field("name_native", labels["native"], p.full_name_native,
                            rtl=r in ("UAE", "PK"), wide=True))
    if r == "PK":
        fields.append(Field("father_name", "Father Name / <span dir='rtl'>والد کا نام</span>",
                            p.father_name.upper(), wide=True))
    fields += [
        Field("nationality", L("nat", "Nationality", 3), P.NATIONALITY[r].upper()),
        Field("dob", L("dob", "Date of Birth", 4), fdate(p.dob)),
        Field("sex", L("sex", "Sex", 5), p.sex),
        Field("place_of_birth", L("pob", "Place of Birth", 6), p.place_of_birth.upper()),
        Field("issue_date", L("issue", "Date of Issue", 7), fdate(issue)),
        Field("authority", L("auth", "Authority", 8), _AUTHORITY[r]),
        Field("expiry_date", L("exp", "Date of Expiry", 9), fdate(expiry)),
    ]
    doc_code = "PA" if r == "AU" else "P"
    mrz = td3(doc_code, code, p.surname, p.given, num, code, yymmdd(p.dob), p.sex, yymmdd(expiry),
              extra_personal)
    title, sub = _PASSPORT_TITLE[r]
    return IdDoc("passport", r, code, "passport", title, sub, p, fields, mrz=mrz, theme=_THEME[r],
                 truth=_truth(p, document_number=num, issue_date=issue, expiry_date=expiry,
                              nationality=code, personal_number=extra_personal))


# --- region-specific cards -----------------------------------------------------


def emirates_id(p: P.Person, rng, as_of) -> IdDoc:
    eid = P.emirates_id(p.dob.year, rng)
    card_no = P.digits(rng, 9)
    issue, expiry = _validity(rng, as_of, 5)
    fields = [
        Field("id_number", "ID Number / <span dir='rtl'>رقم الهوية</span>", eid, big=True, wide=True),
        Field("name_native", "<span dir='rtl'>الاسم</span>", p.full_name_native, rtl=True, wide=True),
        Field("name", "Name", p.full_name, wide=True),
        Field("dob", "Date of Birth / <span dir='rtl'>تاريخ الميلاد</span>", dmy(p.dob)),
        Field("nationality", "Nationality / <span dir='rtl'>الجنسية</span>", "United Arab Emirates"),
        Field("sex", "Sex / <span dir='rtl'>الجنس</span>", p.sex),
        Field("issue_date", "Issuing Date / <span dir='rtl'>تاريخ الإصدار</span>", dmy(issue)),
        Field("expiry_date", "Expiry Date / <span dir='rtl'>تاريخ الانتهاء</span>", dmy(expiry)),
    ]
    back = [
        Field("card_number", "Card Number / <span dir='rtl'>رقم البطاقة</span>", card_no),
        Field("occupation", "Occupation / <span dir='rtl'>المهنة</span>", rng.choice(["Engineer", "Manager", "Accountant", "Teacher"])),
        Field("issuing_place", "Issuing Place / <span dir='rtl'>مكان الإصدار</span>", rng.choice(["Dubai", "Abu Dhabi", "Sharjah"])),
    ]
    mrz = td1("IL", "ARE", p.surname, p.given, card_no, "ARE", yymmdd(p.dob), p.sex,
              yymmdd(expiry), optional1=eid.replace("-", ""))
    return IdDoc("emirates_id", "UAE", "ARE", "card",
                 "UNITED ARAB EMIRATES · <span dir='rtl'>دولة الإمارات العربية المتحدة</span>",
                 "Identity Card · <span dir='rtl'>بطاقة الهوية</span>", p, fields, back, mrz,
                 theme=_THEME["UAE"],
                 truth=_truth(p, id_number=eid, card_number=card_no, issue_date=issue, expiry_date=expiry))


def uk_driving_licence(p: P.Person, rng, as_of) -> IdDoc:
    num = P.uk_driving_licence(p.surname, p.given, p.dob, p.sex, rng)
    issue_no = f"{rng.randint(1, 9)}{rng.randint(0, 9)}"
    issue, expiry = _validity(rng, as_of, 10)
    fields = [
        Field("surname", "1.", p.surname.upper(), wide=True),
        Field("given_names", "2.", p.given.upper(), wide=True),
        Field("dob_place", "3.", f"{dmy(p.dob, '.')} UNITED KINGDOM", wide=True),
        Field("issue_date", "4a.", dmy(issue, ".")),
        Field("expiry_date", "4b.", dmy(expiry, ".")),
        Field("authority", "4c.", "DVLA"),
        Field("licence_number", "5.", f"{num}  {issue_no}", wide=True, big=True),
        Field("address", "8.", p.address, wide=True),
        Field("categories", "9.", "AM/A/B1/B/f/k/l/n/p/q", wide=True),
    ]
    back = [Field("categories_table", "9. Categories · 10. Valid from · 11. Valid to",
                  f"B  {dmy(issue, '.')}  {dmy(expiry, '.')}", wide=True)]
    return IdDoc("uk_driving_licence", "UK", "GBR", "card", "UK DRIVING LICENCE",
                 "UNITED KINGDOM · Photocard", p, fields, back, theme=(0.75, 0.35, 0.55),
                 truth=_truth(p, licence_number=num, issue_number=issue_no,
                              issue_date=issue, expiry_date=expiry))


_US_STATES = {
    "CA": ("CALIFORNIA", "636014", lambda r: P.letters(r, 1) + P.digits(r, 7)),
    "TX": ("TEXAS", "636015", lambda r: P.digits(r, 8)),
    "NY": ("NEW YORK", "636001", lambda r: P.digits(r, 9)),
    "FL": ("FLORIDA", "636010", lambda r: P.letters(r, 1) + P.digits(r, 12)),
}


def aamva_payload(iin: str, elements: list[tuple[str, str]]) -> str:
    """AAMVA DL/ID card design standard (2016) header + one DL subfile."""
    sub = "DL" + "".join(f"{k}{v}\n" for k, v in elements) + "\r"
    header_len = 21 + 10  # fixed header + one subfile designator
    header = f"@\n\x1e\rANSI {iin}100001DL{header_len:04d}{len(sub):04d}"
    return header + sub


def us_driving_licence(p: P.Person, rng, as_of) -> IdDoc:
    st = rng.choice(list(_US_STATES))
    state, iin, numfmt = _US_STATES[st]
    num = numfmt(rng)
    issue, expiry = _validity(rng, as_of, 8)
    dd = P.digits(rng, 10) + P.letters(rng, 2)
    height = rng.randint(60, 76)
    eyes = rng.choice(["BRO", "BLU", "GRN", "HAZ"])
    street, _, rest = p.address.partition(",")
    zip_code = P.digits(rng, 5)
    fields = [
        Field("licence_number", "DL", num, big=True), Field("class", "CLASS", "C"),
        Field("expiry_date", "EXP", mdy(expiry)), Field("issue_date", "ISS", mdy(issue)),
        Field("surname", "LN", p.surname.upper(), wide=True),
        Field("given_names", "FN", p.given.upper(), wide=True),
        Field("address", "", f"{street.upper()}, {p.place_of_birth.upper()}, {st} {zip_code}", wide=True),
        Field("dob", "DOB", mdy(p.dob)), Field("sex", "SEX", p.sex),
        Field("height", "HGT", f"{height // 12}'-{height % 12:02d}\""), Field("eyes", "EYES", eyes),
        Field("dd", "DD", dd, wide=True),
    ]
    sex_code = "1" if p.sex == "M" else "2"
    payload = aamva_payload(iin, [
        ("DAQ", num), ("DCS", p.surname.upper()), ("DAC", p.given.upper()), ("DAD", "NONE"),
        ("DBD", issue.strftime("%m%d%Y")), ("DBB", p.dob.strftime("%m%d%Y")),
        ("DBA", expiry.strftime("%m%d%Y")), ("DBC", sex_code), ("DAY", eyes),
        ("DAU", f"{height:03d} IN"), ("DAG", street.upper()), ("DAI", p.place_of_birth.upper()),
        ("DAJ", st), ("DAK", zip_code + "0000"), ("DCF", dd), ("DCG", "USA"),
        ("DCA", "C"), ("DDA", "F"),
    ])
    return IdDoc("us_driving_licence", "US", "USA", "card", f"{state} USA",
                 "DRIVER LICENSE", p, fields, [], barcode=payload, real_id_star=True,
                 theme=(0.15, 0.3, 0.55),
                 truth=_truth(p, state=st, licence_number=num, issue_date=issue, expiry_date=expiry,
                              real_id_compliant=True, aamva=payload))


def pk_cnic(p: P.Person, rng, as_of, nicop: bool = False) -> IdDoc:
    num = p.extra.setdefault("cnic", P.cnic(p.sex, rng))  # NICOP reuses the CNIC number
    issue, expiry = _validity(rng, as_of, 10 if not nicop else 7)
    stay = rng.choice(["United Arab Emirates", "United Kingdom", "Saudi Arabia"]) if nicop else "Pakistan"
    fields = [
        Field("name", "Name", p.full_name, wide=True),
        Field("name_native", "<span dir='rtl'>نام</span>", p.full_name_native, rtl=True, wide=True),
        Field("father_name", "Father Name / <span dir='rtl'>والد کا نام</span>", p.father_name, wide=True),
        Field("sex", "Gender", p.sex), Field("country_of_stay", "Country of Stay", stay),
        Field("id_number", "Identity Number", num, big=True),
        Field("dob", "Date of Birth", dmy(p.dob, ".")),
        Field("issue_date", "Date of Issue", dmy(issue, ".")),
        Field("expiry_date", "Date of Expiry", dmy(expiry, ".")),
    ]
    back = [Field("address", "Present Address / <span dir='rtl'>موجودہ پتہ</span>", p.address, wide=True)]
    title = "National Identity Card for Overseas Pakistani" if nicop else "National Identity Card"
    return IdDoc("pk_nicop" if nicop else "pk_cnic", "PK", "PAK", "card",
                 "ISLAMIC REPUBLIC OF PAKISTAN · <span dir='rtl'>اسلامی جمہوریہ پاکستان</span>",
                 f"{title} · <span dir='rtl'>قومی شناختی کارڈ</span>", p, fields, back,
                 theme=_THEME["PK"],
                 truth=_truth(p, id_number=num, issue_date=issue, expiry_date=expiry, country_of_stay=stay))


def aadhaar(p: P.Person, rng, as_of) -> IdDoc:
    num = P.aadhaar(rng)
    gender = "पुरुष / MALE" if p.sex == "M" else "महिला / FEMALE"
    fields = [
        Field("name_native", "", p.full_name_native, wide=True),
        Field("name", "", p.full_name, wide=True),
        Field("dob", "जन्म तिथि / DOB", dmy(p.dob)), Field("sex", "", gender),
        Field("aadhaar_number", "", num, big=True, wide=True),
    ]
    back = [Field("address", "पता / Address", p.address, wide=True)]
    return IdDoc("aadhaar", "IN", "IND", "card", "भारत सरकार · Government of India",
                 "आधार · Aadhaar", p, fields, back, theme=(0.85, 0.45, 0.1),
                 truth=_truth(p, aadhaar_number=num.replace(" ", "")))


def pan_card(p: P.Person, rng, as_of) -> IdDoc:
    num = P.pan(p.surname, rng)
    fields = [
        Field("pan", "स्थायी लेखा संख्या / Permanent Account Number", num, big=True, wide=True),
        Field("name", "नाम / Name", p.full_name.upper(), wide=True),
        Field("father_name", "पिता का नाम / Father's Name", p.father_name.upper(), wide=True),
        Field("dob", "जन्म की तारीख / Date of Birth", dmy(p.dob)),
    ]
    return IdDoc("pan_card", "IN", "IND", "card", "आयकर विभाग · INCOME TAX DEPARTMENT",
                 "Permanent Account Number Card", p, fields, [], theme=(0.1, 0.35, 0.55),
                 truth=_truth(p, pan=num))


def bd_nid(p: P.Person, rng, as_of, smart: bool = True) -> IdDoc:
    num = P.bd_nid(p.dob, rng, smart)
    fields = [
        Field("name_native", "নাম", p.full_name_native, wide=True),
        Field("name", "Name", p.full_name.upper(), wide=True),
        Field("father_name", "পিতা", p.father_name_native or p.father_name, wide=True),
        Field("mother_name", "মাতা", p.mother_name, wide=True),
        Field("dob", "Date of Birth", dmony(p.dob)),
        Field("nid_number", "ID NO" if smart else "জাতীয় পরিচয়পত্র নম্বর / NID No", num, big=True),
    ]
    back = [Field("address", "ঠিকানা / Address", p.address, wide=True),
            Field("blood_group", "রক্তের গ্রুপ / Blood Group", rng.choice(["A+", "B+", "O+", "AB+", "O-"]))]
    mrz, issue, expiry = [], None, None
    if smart:
        issue, expiry = _validity(rng, as_of, 10)
        back.append(Field("issue_date", "প্রদানের তারিখ / Issue Date", dmony(issue)))
        mrz = td1("I", "BGD", p.surname, p.given, num[:9], "BGD", yymmdd(p.dob), p.sex,
                  yymmdd(expiry), optional1=num[9:])
    return IdDoc("bd_smart_nid" if smart else "bd_paper_nid", "BD", "BGD", "card" if smart else "paper",
                 "গণপ্রজাতন্ত্রী বাংলাদেশ সরকার · Government of the People's Republic of Bangladesh",
                 "জাতীয় পরিচয় পত্র · National ID Card", p, fields, back, mrz, theme=_THEME["BD"],
                 truth=_truth(p, nid_number=num, nid_digits=len(num), issue_date=issue, expiry_date=expiry))


_AU_STATES = {
    "NSW": (lambda r: P.digits(r, 8), lambda r: P.digits(r, 10), "front"),
    "VIC": (lambda r: P.digits(r, 9), lambda r: P.letters(r, 1) + P.digits(r, 7), "back"),
    "QLD": (lambda r: P.digits(r, 9), lambda r: P.digits(r, 10), "front"),
}


def au_driving_licence(p: P.Person, rng, as_of) -> IdDoc:
    st = rng.choice(list(_AU_STATES))
    lic_fmt, card_fmt, card_side = _AU_STATES[st]
    lic, card = lic_fmt(rng), card_fmt(rng)
    issue, expiry = _validity(rng, as_of, 5)
    fields = [
        Field("name", "", f"{p.given.upper()} {p.surname.upper()}", wide=True, big=True),
        Field("address", "", p.address.upper(), wide=True),
        Field("licence_number", "Licence No.", lic, big=True),
        Field("dob", "Date of Birth", dmony(p.dob)),
        Field("expiry_date", "Licence Expiry", dmony(expiry)),
        Field("class", "Class", "C"),
    ]
    back = []
    card_field = Field("card_number", "Card Number", card)
    (fields if card_side == "front" else back).append(card_field)
    return IdDoc("au_driving_licence", "AU", "AUS", "card", f"{st} AUSTRALIA", "DRIVER LICENCE",
                 p, fields, back, theme=(0.1, 0.3, 0.45),
                 truth=_truth(p, state=st, licence_number=lic, card_number=card, card_number_side=card_side,
                              issue_date=issue, expiry_date=expiry))


def medicare_card(p: P.Person, rng, as_of) -> IdDoc:
    num, irn = P.medicare(rng)
    valid_to = date(as_of.year + rng.randint(1, 5), rng.randint(1, 12), 1)
    fields = [
        Field("medicare_number", "", num, big=True, wide=True),
        Field("irn", "", irn),
        Field("name", "", f"{p.given.upper()} {p.surname.upper()}", wide=True),
        Field("valid_to", "VALID TO", f"{valid_to.month:02d}/{valid_to.year}"),
    ]
    return IdDoc("au_medicare", "AU", "AUS", "card", "medicare", "AUSTRALIA", p, fields, [],
                 theme=(0.1, 0.5, 0.25),
                 truth=_truth(p, medicare_number=num.replace(" ", ""), irn=irn,
                              valid_to=f"{valid_to.year}-{valid_to.month:02d}"))


def nz_driving_licence(p: P.Person, rng, as_of) -> IdDoc:
    lic = P.letters(rng, 2) + P.digits(rng, 6)
    version = P.digits(rng, 3)
    issue, expiry = _validity(rng, as_of, 10)
    fields = [
        Field("surname", "1.", p.surname.upper(), wide=True),
        Field("given_names", "2.", p.given.upper(), wide=True),
        Field("dob", "3.", dmy(p.dob, "-")),
        Field("issue_date", "4a.", dmy(issue, "-")), Field("expiry_date", "4b.", dmy(expiry, "-")),
        Field("licence_number", "5.", lic, big=True), Field("version", "5a. Version", version),
        Field("class", "9.", "1"),
    ]
    return IdDoc("nz_driving_licence", "NZ", "NZL", "card", "NEW ZEALAND", "DRIVER LICENCE",
                 p, fields, [], theme=(0.15, 0.2, 0.25),
                 truth=_truth(p, licence_number=lic, version=version, issue_date=issue, expiry_date=expiry))


def de_id_card(p: P.Person, rng, as_of) -> IdDoc:
    num = P.german_id_number(rng)
    issue, expiry = _validity(rng, as_of, 10)
    fields = [
        Field("card_number", "", num, big=True),
        Field("surname", "Name / Surname / Nom", p.surname.upper(), wide=True),
        Field("given_names", "Vornamen / Given names / Prénoms", p.given.upper(), wide=True),
        Field("dob", "Geburtstag / Date of birth / Date de naissance", dmy(p.dob, ".")),
        Field("nationality", "Staatsangehörigkeit / Nationality", "DEUTSCH"),
        Field("place_of_birth", "Geburtsort / Place of birth / Lieu de naissance", p.place_of_birth.upper()),
        Field("expiry_date", "Gültig bis / Date of expiry / Date d'expiration", dmy(expiry, ".")),
    ]
    back = [Field("address", "Anschrift / Address / Adresse", p.address.upper(), wide=True),
            Field("issue_date", "Datum / Date", dmy(issue, "."))]
    mrz = td1("ID", "D", p.surname, p.given, num, "D", yymmdd(p.dob), "<", yymmdd(expiry))
    return IdDoc("de_id_card", "EU", "D", "card", "BUNDESREPUBLIK DEUTSCHLAND",
                 "PERSONALAUSWEIS · IDENTITY CARD · CARTE D'IDENTITÉ", p, fields, back, mrz,
                 theme=_THEME["DE"],
                 truth=_truth(p, card_number=num, issue_date=issue, expiry_date=expiry, country="DE"))


def es_dni(p: P.Person, rng, as_of) -> IdDoc:
    dni = P.spanish_dni(rng)
    support = P.letters(rng, 3) + P.digits(rng, 6)
    issue, expiry = _validity(rng, as_of, 10)
    second = p.extra.setdefault("second_surname", rng.choice(["GARCÍA", "MUÑOZ", "IBÁÑEZ", "PÉREZ"]))
    fields = [
        Field("surname", "APELLIDOS", f"{p.surname.upper()} {second}", wide=True),
        Field("given_names", "NOMBRE", p.given.upper(), wide=True),
        Field("sex", "SEXO", p.sex), Field("nationality", "NACIONALIDAD", "ESP"),
        Field("dob", "FECHA DE NACIMIENTO", dmy(p.dob, " ")),
        Field("support_number", "NÚM SOPORT", support),
        Field("expiry_date", "VÁLIDO HASTA", dmy(expiry, " ")),
        Field("dni", "DNI", dni, big=True),
    ]
    mrz = td1("ID", "ESP", f"{p.surname} {second}", p.given, support, "ESP", yymmdd(p.dob), p.sex,
              yymmdd(expiry), optional1=dni)
    return IdDoc("es_dni", "EU", "ESP", "card", "REINO DE ESPAÑA", "DOCUMENTO NACIONAL DE IDENTIDAD",
                 p, fields, [], mrz, theme=_THEME["ES"],
                 truth=_truth(p, dni=dni, support_number=support, issue_date=issue, expiry_date=expiry,
                              second_surname=second, country="ES"))


# --- rendering -----------------------------------------------------------------


def _lighten(c: tuple, k: float) -> tuple:
    return tuple(min(1.0, v + (1 - v) * k) for v in c)


def _draw_fields(pg: R.Page, fields: list[Field], x0: float, y0: float, x1: float, y1: float,
                 lsize: float, vsize: float, value_family: str | None = None) -> None:
    rows: list[list[Field]] = []
    pending: list[Field] = []
    for f in fields:
        if f.wide:
            if pending:
                rows.append(pending)
                pending = []
            rows.append([f])
        else:
            pending.append(f)
            if len(pending) == 2:
                rows.append(pending)
                pending = []
    if pending:
        rows.append(pending)
    row_h = min((y1 - y0) / max(len(rows), 1), (lsize + vsize * 1.5) * 1.35)
    y = y0
    for row in rows:
        col_w = (x1 - x0) / len(row)
        for i, f in enumerate(row):
            cx = x0 + i * col_w
            vs = vsize * (1.25 if f.big else 1.0)
            if f.label:
                pg.html((cx, y, cx + col_w - 2, y + lsize * 1.6), f.label, size=lsize, color="#555")
            vy = y + (lsize * 1.25 if f.label else 0)
            pg.html((cx, vy, cx + col_w - 2, vy + vs * 1.6), esc(f.value) if not f.big else f"<b>{esc(f.value)}</b>",
                    size=vs, rtl=f.rtl, align="right" if f.rtl else "left", family=value_family)
        y += row_h + (vsize * 0.3 if any(f.big for f in row) else 0)


def _star(pg: R.Page, cx: float, cy: float, r: float) -> None:
    import math
    import pymupdf

    pts = []
    for k in range(10):
        rad = r if k % 2 == 0 else r * 0.42
        a = math.pi / 2 + k * math.pi / 5
        pts.append(pymupdf.Point(cx + rad * math.cos(a), cy - rad * math.sin(a)))
    pts.append(pts[0])
    pg.page.draw_polyline(pts, fill=(0.95, 0.75, 0.1), color=(0.6, 0.45, 0.0), width=0.4)


def render_id(doc: IdDoc, path: Path, seed: int, value_family: str | None = None,
              metadata: dict | None = None) -> None:
    pdf = R.new_doc()
    rng = random.Random(seed)
    w, h = {"card": CARD, "passport": PASSPORT, "paper": PAPER}[doc.layout]
    paper = doc.layout == "paper"
    bg = (0.97, 0.95, 0.86) if paper else _lighten(doc.theme, 0.9)

    # front
    pg = R.Page(pdf, w, h)
    pg.rect((0, 0, w, h), fill=bg, radius=None if paper else 0.04)
    pg.guilloche(rng, color=_lighten(doc.theme, 0.65))
    band = mm(10) if doc.layout != "passport" else mm(12)
    pg.rect((0, 0, w, band), fill=doc.theme)
    tsize = band * 0.30
    pg.html((mm(2), mm(0.8), w - mm(2), band * 0.55), f"<b>{doc.title}</b>", size=tsize, color="#fff", align="center")
    pg.html((mm(2), band * 0.52, w - mm(2), band), doc.subtitle, size=tsize * 0.9, color="#fff", align="center")
    if doc.real_id_star:
        _star(pg, w - mm(6), band + mm(4), mm(2.8))
    if doc.layout == "passport":
        portrait = (mm(5), band + mm(4), mm(36), band + mm(44))
        lsize, vsize = 4.6, 7.2
        mrz_y = h - mm(17)
    else:
        portrait = (mm(3), band + mm(3), mm(24), band + mm(30))
        lsize, vsize = 3.8, 5.6
        mrz_y = h
    pg.portrait(portrait, seed)
    fx0 = portrait[2] + mm(3)
    fbottom = (mrz_y - mm(1)) if doc.layout == "passport" else h - mm(3)
    _draw_fields(pg, doc.fields, fx0, band + mm(1.5), w - mm(3), fbottom, lsize, vsize, value_family)
    if doc.layout == "passport" and doc.mrz:
        pg.rect((0, mrz_y - mm(1), w, h), fill=(1, 1, 1), opacity=0.85)
        pg.mrz(doc.mrz, mrz_y)
    pg.specimen()

    # back (cards only)
    if doc.layout != "passport" and (doc.back_fields or doc.mrz or doc.barcode):
        pg = R.Page(pdf, w, h)
        pg.rect((0, 0, w, h), fill=bg)
        pg.guilloche(rng, color=_lighten(doc.theme, 0.7), lines=10)
        top = mm(4.5)
        bottom = h - (mm(17) if doc.mrz else mm(3))
        if doc.barcode:
            pg.image((mm(4), mm(18), w - mm(4), h - mm(4)), R.pdf417_png(doc.barcode))
            bottom = mm(16)
        if doc.back_fields:
            _draw_fields(pg, doc.back_fields, mm(4), top, w - mm(4), bottom, lsize, vsize, value_family)
        if doc.mrz:
            pg.rect((0, h - mm(17), w, h), fill=(1, 1, 1), opacity=0.9)
            pg.mrz(doc.mrz, h - mm(16))
        pg.specimen(footer_top=bool(doc.mrz))
    R.save(pdf, path, metadata)


# --- what each region gets ------------------------------------------------------

REGION_DOCS = {
    "UAE": [emirates_id, passport],
    "UK": [passport, uk_driving_licence],
    "US": [us_driving_licence, passport],
    "PK": [pk_cnic, lambda p, r, a: pk_cnic(p, r, a, nicop=True), "pk_passport"],
    "IN": [aadhaar, pan_card, passport],
    "BD": [bd_nid, lambda p, r, a: bd_nid(p, r, a, smart=False), passport],
    "AU": [au_driving_licence, medicare_card, passport],
    "NZ": [nz_driving_licence, passport],
    "DE": [de_id_card, passport],
    "FR": [passport],
    "ES": [es_dni, passport],
}


def build_region_docs(p: P.Person, rng: random.Random, as_of: date) -> list[IdDoc]:
    docs = []
    for b in REGION_DOCS[p.region]:
        if b == "pk_passport":  # Pakistani passports carry the CNIC as the personal number
            docs.append(passport(p, rng, as_of, extra_personal=p.extra["cnic"].replace("-", "")))
        else:
            docs.append(b(p, rng, as_of))
    return docs
