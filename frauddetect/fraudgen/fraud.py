"""Adversarial and edge-case documents.

Each case is one folder (a "submission") holding its documents, a ground-truth
JSON per document and case.json with the expected outcome:
  expected_result = fail    -> a correct validator must reject or flag it
  expected_result = review  -> suspicious, should go to manual review
  expected_result = pass    -> edge case a correct validator must still accept
expected_findings names each defect that was planted, so results can be scored
per check rather than per document.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import random
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

import pymupdf

from . import banking as B
from . import checksums as ck
from . import degrade as D
from . import identity as I
from . import people as P
from . import render as R
from . import trade as T
from .mrz import td1, td3


@dataclass
class Case:
    case_id: str
    slug: str
    category: str  # identity | bank_statement | trade | cross_document
    region: str
    expected_result: str
    findings: list[str]
    description: str
    fn: Callable


CASES: list[Case] = []


def case(case_id, slug, category, region, expected_result, findings, description):
    def deco(fn):
        CASES.append(Case(case_id, slug, category, region, expected_result, findings, description, fn))
        return fn
    return deco


class Ctx:
    def __init__(self, as_of: date, seed: int):
        self.as_of = as_of
        self.seed = seed

    def rng(self, key: str) -> random.Random:
        return random.Random(f"{self.seed}-{key}")


# --- shared helpers ------------------------------------------------------------------


def id_truth(doc: I.IdDoc) -> dict:
    t = {"doc_type": doc.doc_type, "region": doc.region, "issuing_country": doc.country,
         "holder": doc.truth, "printed_fields": {f.key: f.value for f in doc.fields + doc.back_fields}}
    if doc.mrz:
        t["mrz"] = doc.mrz
    if doc.barcode:
        t["pdf417_aamva"] = doc.barcode
    return t


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def emit_id(doc: I.IdDoc, path: Path, seed: int, extra: dict | None = None, photo: bool = True,
            rng: random.Random | None = None) -> list[tuple[Path, str, dict]]:
    I.render_id(doc, path, seed)
    truth = id_truth(doc)
    truth.update(extra or {})
    out = [(path, doc.doc_type, truth)]
    if photo:  # one phone capture of the front, the way most fraud attempts arrive
        img = R.rasterize(path, 300)[0]
        ph, fx = D.mobile(img, rng or random.Random(seed))
        jpg = path.with_name(path.stem + "_photo.jpg")
        D.save_jpeg(ph, jpg)
        out.append((jpg, doc.doc_type, dict(truth, capture=fx, source_pdf=path.name)))
    return out


def emit_statement(st: B.Statement, path: Path, extra: dict | None = None,
                   bank_files_from: B.Statement | None = None) -> list[tuple[Path, str, dict]]:
    B.render_statement(st, path)
    truth = st.truth()
    truth["printed_closing_balance"] = st.closing_override if st.closing_override is not None else st.closing
    truth.update(extra or {})
    out = [(path, "bank_statement", truth)]
    for f in B.write_bank_files(bank_files_from or st, path):
        out.append((f, "bank_statement_" + f.suffixes[0].lstrip("."), truth))
    return out


def overlay(path: Path, search: str, new_text: str, page_no: int = 0, nth: int = 0,
            producer: str = "Adobe Photoshop 25.1 (Windows)") -> dict:
    """Crude edit as a fraudster would do it: white patch + retyped value in a
    different font, saved as an incremental update so the original revision stays
    in the file (a forensic tell)."""
    doc = pymupdf.open(str(path))
    page = doc[page_no]
    hits = page.search_for(search)
    if not hits:
        doc.close()
        raise ValueError(f"text not found for overlay in {path.name}")
    r = hits[min(nth, len(hits) - 1)]
    patch = pymupdf.Rect(r.x0 - 0.5, r.y0 - 0.3, r.x1 + 0.5, r.y1 + 0.3)
    page.draw_rect(patch, color=None, fill=(1, 1, 1))
    fs = r.height * 0.78
    page.insert_text(pymupdf.Point(r.x0, r.y1 - r.height * 0.2), new_text, fontname="tiro", fontsize=fs,
                     color=(0.08, 0.08, 0.08))
    meta = dict(doc.metadata)
    meta.update({"producer": producer, "modDate": "D:20261012231544+04'00'",
                 "creator": "Microsoft Word for Microsoft 365"})
    doc.set_metadata(meta)
    doc.saveIncr()
    doc.close()
    return {"tamper": {"method": "white_patch_overlay_incremental_save", "page": page_no,
                       "original_text": search, "new_text": new_text,
                       "bbox": [round(v, 1) for v in patch], "font": "Times-Roman (differs from document font)",
                       "pdf_producer": producer}}


def person(ctx: Ctx, region: str, key: str, idx: int = 0) -> P.Person:
    return P.make_person(region, ctx.rng(f"person-{key}"), ctx.as_of, idx)


def _td1_with_optional1(mrz: list[str], value: str) -> list[str]:
    l1 = mrz[0][:15] + (value + "<" * 15)[:15]
    l2 = mrz[1][:-1]
    comp = ck.icao_check_digit(l1[5:30] + l2[0:7] + l2[8:15] + l2[18:29])
    return [l1, l2 + comp, mrz[2]]


def _eid_doc(p: P.Person, rng, as_of, eid: str | None = None, issue: date | None = None,
             expiry: date | None = None) -> I.IdDoc:
    d = I.emirates_id(p, rng, as_of)
    if eid:
        d.get("id_number").value = eid
        d.truth["id_number"] = eid
    if issue:
        d.get("issue_date").value = I.dmy(issue)
        d.truth["issue_date"] = issue.isoformat()
    if expiry:
        d.get("expiry_date").value = I.dmy(expiry)
        d.truth["expiry_date"] = expiry.isoformat()
    exp = date.fromisoformat(d.truth["expiry_date"])
    d.mrz = td1("IL", "ARE", p.surname, p.given, d.truth["card_number"], "ARE", I.yymmdd(p.dob), p.sex,
                I.yymmdd(exp), optional1=d.truth["id_number"].replace("-", ""))
    return d


def _passport_with(p: P.Person, rng, as_of, number: str | None = None, personal: str = "") -> I.IdDoc:
    d = I.passport(p, rng, as_of, extra_personal=personal)
    if number:
        d.get("document_number").value = number
        d.truth["document_number"] = number
        exp = date.fromisoformat(d.truth["expiry_date"])
        code = P.ISO3[p.region]
        d.mrz = td3("PA" if p.region == "AU" else "P", code, p.surname, p.given, number, code,
                    I.yymmdd(p.dob), p.sex, I.yymmdd(exp), personal)
    return d


def _shift_years(d: date, years: int) -> date:
    return date(d.year + years, d.month, min(d.day, 28))


# =============================================================================
# Identity
# =============================================================================


@case("ID01", "passport_mrz_document_number_check_digit", "identity", "UAE", "fail",
      ["mrz_check_digit_document_number"], "UAE passport whose MRZ document-number check digit is wrong.")
def _id01(ctx, folder, rng):
    d = I.passport(person(ctx, "UAE", "id01"), rng, ctx.as_of)
    l2 = d.mrz[1]
    d.mrz[1] = l2[:9] + str((int(l2[9]) + 1) % 10) + l2[10:]
    return emit_id(d, folder / "uae_passport.pdf", 101, rng=rng)


@case("ID02", "passport_mrz_composite_check_digit", "identity", "UK", "fail",
      ["mrz_check_digit_composite"], "UK passport with a wrong composite (final) MRZ check digit.")
def _id02(ctx, folder, rng):
    d = I.passport(person(ctx, "UK", "id02"), rng, ctx.as_of)
    d.mrz[1] = d.mrz[1][:-1] + str((int(d.mrz[1][-1]) + 3) % 10)
    return emit_id(d, folder / "uk_passport.pdf", 102, rng=rng)


@case("ID03", "passport_dob_visual_vs_mrz", "identity", "IN", "fail",
      ["dob_mismatch_visual_vs_mrz"], "Indian passport: printed DOB made 3 years older; MRZ still has the real DOB.")
def _id03(ctx, folder, rng):
    p = person(ctx, "IN", "id03")
    d = I.passport(p, rng, ctx.as_of)
    d.get("dob").value = I.dmony(_shift_years(p.dob, -3))
    return emit_id(d, folder / "in_passport.pdf", 103, {"planted": {"printed_dob": _shift_years(p.dob, -3).isoformat(),
                                                                     "mrz_dob": p.dob.isoformat()}}, rng=rng)


@case("ID04", "passport_name_visual_vs_mrz", "identity", "PK", "fail",
      ["name_mismatch_visual_vs_mrz"], "Pakistani passport: printed surname replaced, MRZ name unchanged.")
def _id04(ctx, folder, rng):
    p = person(ctx, "PK", "id04")
    d = I.passport(p, rng, ctx.as_of)
    d.get("surname").value = "QURESHI" if p.surname != "Qureshi" else "MALIK"
    return emit_id(d, folder / "pk_passport.pdf", 104, rng=rng)


@case("ID05", "emirates_id_luhn_fail", "identity", "UAE", "fail",
      ["emirates_id_check_digit"], "Emirates ID number fails the Luhn check (front and MRZ agree).")
def _id05(ctx, folder, rng):
    p = person(ctx, "UAE", "id05", 2)
    good = P.emirates_id(p.dob.year, rng)
    bad = good[:-1] + str((int(good[-1]) + 4) % 10)
    return emit_id(_eid_doc(p, rng, ctx.as_of, eid=bad), folder / "emirates_id.pdf", 105, rng=rng)


@case("ID06", "emirates_id_birth_year_segment", "identity", "UAE", "fail",
      ["emirates_id_birth_year_mismatch"], "Emirates ID 784-YYYY segment differs from the printed year of birth (checksum valid).")
def _id06(ctx, folder, rng):
    p = person(ctx, "UAE", "id06", 3)
    eid = P.emirates_id(p.dob.year + 6, rng)
    return emit_id(_eid_doc(p, rng, ctx.as_of, eid=eid), folder / "emirates_id.pdf", 106, rng=rng)


@case("ID07", "cnic_gender_digit", "identity", "PK", "fail",
      ["cnic_gender_digit_mismatch"], "CNIC last digit is even (female) on a male holder's card.")
def _id07(ctx, folder, rng):
    p = person(ctx, "PK", "id07", 0)  # male
    p.extra["cnic"] = f"{rng.choice('1234567')}{P.digits(rng, 4)}-{P.digits(rng, 7)}-{rng.choice('2468')}"
    return emit_id(I.pk_cnic(p, rng, ctx.as_of), folder / "pk_cnic.pdf", 107, rng=rng)


@case("ID08", "aadhaar_verhoeff_fail", "identity", "IN", "fail",
      ["aadhaar_verhoeff_check"], "Aadhaar number with one digit altered so the Verhoeff check fails.")
def _id08(ctx, folder, rng):
    d = I.aadhaar(person(ctx, "IN", "id08", 1), rng, ctx.as_of)
    n = d.truth["aadhaar_number"]
    bad = n[:-1] + str((int(n[-1]) + 1) % 10)
    d.get("aadhaar_number").value = f"{bad[:4]} {bad[4:8]} {bad[8:]}"
    d.truth["aadhaar_number"] = bad
    return emit_id(d, folder / "aadhaar.pdf", 108, rng=rng)


@case("ID09", "aadhaar_invalid_first_digit", "identity", "IN", "fail",
      ["aadhaar_first_digit_0_or_1"], "Aadhaar starting with 1 (never issued) but with a valid Verhoeff digit.")
def _id09(ctx, folder, rng):
    d = I.aadhaar(person(ctx, "IN", "id09", 2), rng, ctx.as_of)
    body = "1" + P.digits(rng, 10)
    n = body + ck.verhoeff_check_digit(body)
    d.get("aadhaar_number").value = f"{n[:4]} {n[4:8]} {n[8:]}"
    d.truth["aadhaar_number"] = n
    return emit_id(d, folder / "aadhaar.pdf", 109, rng=rng)


@case("ID10", "pan_structure", "identity", "IN", "fail",
      ["pan_holder_type_not_individual", "pan_surname_initial_mismatch"],
      "PAN with 4th char 'C' (company) on a personal card and 5th char not the surname initial.")
def _id10(ctx, folder, rng):
    p = person(ctx, "IN", "id10", 4)
    d = I.pan_card(p, rng, ctx.as_of)
    wrong = next(c for c in "ZXQW" if c != p.surname[0].upper())
    bad = f"{P.letters(rng, 3)}C{wrong}{P.digits(rng, 4)}{P.letters(rng, 1)}"
    d.get("pan").value = bad
    d.truth["pan"] = bad
    return emit_id(d, folder / "pan_card.pdf", 110, rng=rng)


@case("ID11", "uk_driving_licence_dob_encoding", "identity", "UK", "fail",
      ["uk_dl_number_dob_mismatch"], "UK licence number encodes a different date of birth than field 3.")
def _id11(ctx, folder, rng):
    p = person(ctx, "UK", "id11", 1)
    d = I.uk_driving_licence(p, rng, ctx.as_of)
    other = p.dob + timedelta(days=400)
    num = P.uk_driving_licence(p.surname, p.given, other, p.sex, rng)
    d.get("licence_number").value = f"{num}  {d.truth['issue_number']}"
    d.truth["licence_number"] = num
    return emit_id(d, folder / "uk_driving_licence.pdf", 111,
                   {"planted": {"dob_encoded_in_number": other.isoformat()}}, rng=rng)


@case("ID12", "us_dl_barcode_vs_front", "identity", "US", "fail",
      ["pdf417_dob_mismatch_with_front"], "US licence whose PDF417 barcode DOB (DBB) differs from the printed DOB.")
def _id12(ctx, folder, rng):
    p = person(ctx, "US", "id12")
    d = I.us_driving_licence(p, rng, ctx.as_of)
    old = "DBB" + p.dob.strftime("%m%d%Y")
    new = "DBB" + _shift_years(p.dob, -4).strftime("%m%d%Y")
    d.barcode = d.barcode.replace(old, new)
    return emit_id(d, folder / "us_driving_licence.pdf", 112,
                   {"planted": {"barcode_dob": _shift_years(p.dob, -4).isoformat()}}, rng=rng)


@case("ID13", "au_dl_card_number_equals_licence", "identity", "AU", "fail",
      ["au_card_number_equals_licence_number"],
      "Australian licence where the card number is just the licence number (DVS needs both, and they differ).")
def _id13(ctx, folder, rng):
    d = I.au_driving_licence(person(ctx, "AU", "id13"), rng, ctx.as_of)
    d.get("card_number").value = d.truth["licence_number"]
    d.truth["card_number"] = d.truth["licence_number"]
    return emit_id(d, folder / "au_driving_licence.pdf", 113, rng=rng)


@case("ID14", "medicare_check_digit", "identity", "AU", "fail",
      ["medicare_check_digit"], "Medicare card with a wrong 9th (check) digit.")
def _id14(ctx, folder, rng):
    d = I.medicare_card(person(ctx, "AU", "id14", 1), rng, ctx.as_of)
    n = d.truth["medicare_number"]
    bad = n[:8] + str((int(n[8]) + 5) % 10) + n[9]
    d.get("medicare_number").value = f"{bad[:4]} {bad[4:9]} {bad[9]}"
    d.truth["medicare_number"] = bad
    return emit_id(d, folder / "medicare.pdf", 114, rng=rng)


@case("ID15", "es_dni_letter", "identity", "EU", "fail",
      ["es_dni_control_letter"], "Spanish DNI whose control letter does not match number mod 23.")
def _id15(ctx, folder, rng):
    d = I.es_dni(person(ctx, "ES", "id15"), rng, ctx.as_of)
    dni = d.truth["dni"]
    wrong = next(c for c in "TRWAGMY" if c != dni[-1])
    bad = dni[:-1] + wrong
    d.get("dni").value = bad
    d.truth["dni"] = bad
    d.mrz = _td1_with_optional1(d.mrz, bad)
    return emit_id(d, folder / "es_dni.pdf", 115, rng=rng)


@case("ID16", "bd_nid17_birth_year", "identity", "BD", "fail",
      ["bd_nid_birth_year_prefix_mismatch"], "Old 17-digit Bangladesh NID whose first 4 digits are not the birth year.")
def _id16(ctx, folder, rng):
    p = person(ctx, "BD", "id16", 2)
    d = I.bd_nid(p, rng, ctx.as_of, smart=False)
    bad = f"{p.dob.year + 5}{d.truth['nid_number'][4:]}"
    d.get("nid_number").value = bad
    d.truth["nid_number"] = bad
    return emit_id(d, folder / "bd_paper_nid.pdf", 116, rng=rng)


@case("ID17", "expired_document", "identity", "NZ", "fail",
      ["document_expired"], "NZ driver licence that expired before the as-of date.")
def _id17(ctx, folder, rng):
    d = I.nz_driving_licence(person(ctx, "NZ", "id17"), rng, ctx.as_of)
    exp = ctx.as_of - timedelta(days=rng.randint(30, 400))
    iss = _shift_years(exp, -10) + timedelta(days=1)
    d.get("expiry_date").value, d.get("issue_date").value = I.dmy(exp, "-"), I.dmy(iss, "-")
    d.truth.update(expiry_date=exp.isoformat(), issue_date=iss.isoformat())
    return emit_id(d, folder / "nz_driving_licence.pdf", 117, rng=rng)


@case("ID18", "expiry_before_issue", "identity", "UAE", "fail",
      ["expiry_before_issue"], "Emirates ID whose expiry date is earlier than its issue date.")
def _id18(ctx, folder, rng):
    p = person(ctx, "UAE", "id18", 5)
    iss = ctx.as_of - timedelta(days=120)
    return emit_id(_eid_doc(p, rng, ctx.as_of, issue=iss, expiry=iss - timedelta(days=730)),
                   folder / "emirates_id.pdf", 118, rng=rng)


@case("ID19", "underage_holder", "identity", "UK", "fail",
      ["holder_under_minimum_age"], "UK driving licence for a 15-year-old (consistent data, holder too young).")
def _id19(ctx, folder, rng):
    p = person(ctx, "UK", "id19", 0)
    p.dob = date(ctx.as_of.year - 15, p.dob.month, min(p.dob.day, 28))
    return emit_id(I.uk_driving_licence(p, rng, ctx.as_of), folder / "uk_driving_licence.pdf", 119, rng=rng)


@case("ID20", "font_overlay_tamper", "identity", "EU", "fail",
      ["visual_tamper_font_mismatch", "pdf_incremental_edit", "pdf_producer_image_editor",
       "dob_mismatch_visual_vs_mrz"],
      "German ID card PDF with DOB covered by a white patch and retyped in a different font.")
def _id20(ctx, folder, rng):
    p = person(ctx, "DE", "id20")
    d = I.de_id_card(p, rng, ctx.as_of)
    path = folder / "de_id_card.pdf"
    I.render_id(d, path, 120)
    new_dob = _shift_years(p.dob, -6)
    info = overlay(path, I.dmy(p.dob, "."), I.dmy(new_dob, "."))
    truth = id_truth(d)
    truth.update(info)
    img = R.rasterize(path, 300)[0]
    ph, fx = D.mobile(img, rng)
    jpg = path.with_name(path.stem + "_photo.jpg")
    D.save_jpeg(ph, jpg)
    return [(path, d.doc_type, truth), (jpg, d.doc_type, dict(truth, capture=fx))]


@case("ID21", "duplicate_passport_number", "cross_document", "EU", "fail",
      ["duplicate_document_number_different_holders"], "Two French passports, different holders, same number.")
def _id21(ctx, folder, rng):
    a, b = person(ctx, "FR", "id21a", 0), person(ctx, "FR", "id21b", 1)
    da = I.passport(a, rng, ctx.as_of)
    db = _passport_with(b, rng, ctx.as_of, number=da.truth["document_number"])
    return (emit_id(da, folder / "fr_passport_holder_a.pdf", 1211, rng=rng)
            + emit_id(db, folder / "fr_passport_holder_b.pdf", 1212, rng=rng))


@case("ID22", "mrz_issuing_state_mismatch", "identity", "US", "fail",
      ["mrz_issuing_state_mismatch"], "US passport whose MRZ line 1 issuing state reads CAN.")
def _id22(ctx, folder, rng):
    d = I.passport(person(ctx, "US", "id22", 1), rng, ctx.as_of)
    d.mrz[0] = d.mrz[0][:2] + "CAN" + d.mrz[0][5:]
    return emit_id(d, folder / "us_passport.pdf", 122, rng=rng)


@case("ID23", "pk_passport_cnic_mismatch", "cross_document", "PK", "fail",
      ["passport_personal_number_differs_from_cnic"],
      "Pakistani passport whose MRZ personal number is not the holder's CNIC (CNIC supplied alongside).")
def _id23(ctx, folder, rng):
    p = person(ctx, "PK", "id23", 2)
    cnic = I.pk_cnic(p, rng, ctx.as_of)
    other = P.cnic(p.sex, rng).replace("-", "")
    pp = I.passport(p, rng, ctx.as_of, extra_personal=other)
    return (emit_id(cnic, folder / "pk_cnic.pdf", 1231, rng=rng)
            + emit_id(pp, folder / "pk_passport.pdf", 1232, rng=rng))


# =============================================================================
# Bank statements
# =============================================================================


def _stmt(ctx, code: str, region: str, key: str, bucket: int, as_of: date | None = None, idx: int = 0,
          bank: B.Bank | None = None) -> tuple[B.Statement, P.Person]:
    p = person(ctx, region, key, idx)
    rng = ctx.rng(f"stmt-{key}")
    st = B.make_statement(bank or B.BANKS[code], p.full_name, p.address, rng, as_of or ctx.as_of, bucket)
    return st, p


@case("BK01", "iban_checksum", "bank_statement", "UAE", "fail", ["iban_mod97_check"],
      "UAE statement whose IBAN fails the ISO 13616 mod-97 check.")
def _bk01(ctx, folder, rng):
    st, _ = _stmt(ctx, "UAE", "UAE", "bk01", 3)
    iban = st.account["iban"]
    bad = iban[:10] + str((int(iban[10]) + 1) % 10) + iban[11:]
    st.account.update(iban=bad, account_number=bad[7:])
    return emit_statement(st, folder / "statement.pdf")


@case("BK02", "aba_checksum", "bank_statement", "US", "fail", ["aba_routing_check_digit"],
      "US statement with an ABA routing number whose check digit is wrong.")
def _bk02(ctx, folder, rng):
    st, _ = _stmt(ctx, "US", "US", "bk02", 1)
    r = st.account["routing_number"]
    st.account["routing_number"] = r[:8] + str((int(r[8]) + 1) % 10)
    return emit_statement(st, folder / "statement.pdf")


@case("BK03", "running_balance_break", "bank_statement", "UK", "fail",
      ["running_balance_arithmetic", "summary_vs_transactions"],
      "UK statement where one debit was reduced after printing; the balance column no longer adds up.")
def _bk03(ctx, folder, rng):
    st, _ = _stmt(ctx, "UK", "UK", "bk03", 2)
    idx = next(i for i, t in enumerate(st.txns) if t.amount < -500)
    original = st.txns[idx].amount
    st.txns[idx].amount = round(original * 0.3, 2)
    return emit_statement(st, folder / "statement.pdf",
                          {"planted": {"txn_index": idx, "original_amount": original, "printed_amount": st.txns[idx].amount}})


@case("BK04", "inflated_closing_balance", "bank_statement", "IN", "fail",
      ["closing_balance_not_supported_by_transactions", "pdf_vs_structured_mismatch", "balance_bucket_inflated"],
      "Indian statement with the closing balance (summary and last row) inflated 3.2x; MT940/CAMT keep the real one.")
def _bk04(ctx, folder, rng):
    st, _ = _stmt(ctx, "IN", "IN", "bk04", 3)
    genuine = copy.deepcopy(st)
    st.closing_override = round(st.closing * 3.2, 2)
    return emit_statement(st, folder / "statement.pdf", {"planted": {"real_closing": genuine.closing}},
                          bank_files_from=genuine)


@case("BK05", "pdf_amount_overlay", "bank_statement", "AU", "fail",
      ["visual_tamper_font_mismatch", "pdf_incremental_edit", "pdf_producer_image_editor", "running_balance_arithmetic"],
      "Australian statement PDF with a salary credit patched over in a different font (x10).")
def _bk05(ctx, folder, rng):
    st, _ = _stmt(ctx, "AU", "AU", "bk05", 1)
    path = folder / "statement.pdf"
    files = emit_statement(st, path)
    sal = next(t for t in st.txns if t.description.startswith(("SALARY", "PAYROLL")))
    info = overlay(path, B.fmt_num(sal.amount, "en"), B.fmt_num(sal.amount * 10, "en"))
    files[0][2].update(info)
    return files


@case("BK06", "ifsc_format", "bank_statement", "IN", "fail", ["ifsc_format_fifth_char_not_zero"],
      "Indian statement whose IFSC has letter O instead of zero in position 5.")
def _bk06(ctx, folder, rng):
    st, _ = _stmt(ctx, "IN", "IN", "bk06", 1, idx=3)
    st.account["ifsc"] = st.account["ifsc"][:4] + "O" + st.account["ifsc"][5:]
    return emit_statement(st, folder / "statement.pdf")


@case("BK07", "sort_code_iban_mismatch", "bank_statement", "UK", "fail", ["sort_code_not_in_iban"],
      "UK statement where the IBAN (valid mod-97) embeds a different sort code from the one printed.")
def _bk07(ctx, folder, rng):
    st, _ = _stmt(ctx, "UK", "UK", "bk07", 4, idx=1)
    st.account["iban"] = ck.iban_build("GB", "THMS" + P.digits(rng, 6) + st.account["account_number"])
    return emit_statement(st, folder / "statement.pdf")


@case("BK08", "future_dated_statement", "bank_statement", "PK", "fail", ["statement_period_in_future"],
      "Pakistani statement whose period ends after the as-of date.")
def _bk08(ctx, folder, rng):
    st, _ = _stmt(ctx, "PK", "PK", "bk08", 2, as_of=ctx.as_of + timedelta(days=75))
    return emit_statement(st, folder / "statement.pdf", {"as_of": ctx.as_of.isoformat()})


@case("BK09", "transaction_outside_period", "bank_statement", "BD", "fail", ["transaction_date_outside_period"],
      "Bangladeshi statement containing a transaction dated before the statement period.")
def _bk09(ctx, folder, rng):
    st, _ = _stmt(ctx, "BD", "BD", "bk09", 2)
    st.txns[0].day = st.start - timedelta(days=9)
    st.recompute_balances()
    return emit_statement(st, folder / "statement.pdf")


@case("BK10", "mixed_decimal_separators", "bank_statement", "EU", "fail", ["inconsistent_number_format"],
      "Dutch statement where three rows use 1,234.56 instead of 1.234,56 (pasted from another statement).")
def _bk10(ctx, folder, rng):
    p = P.make_person("NL", ctx.rng("person-bk10"), ctx.as_of)
    st = B.make_statement(B.BANKS["NL"], p.full_name, p.address, ctx.rng("stmt-bk10"), ctx.as_of, 3)
    st.row_styles = {i: "en" for i in rng.sample(range(len(st.txns)), 3)}
    return emit_statement(st, folder / "statement.pdf", {"planted": {"rows_with_en_format": sorted(st.row_styles)}})


@case("BK11", "structured_vs_pdf", "bank_statement", "EU", "fail", ["pdf_vs_structured_mismatch"],
      "German statement: the PDF is genuine but the MT940/CAMT.053/OFX carry a different amount and closing balance.")
def _bk11(ctx, folder, rng):
    st, _ = _stmt(ctx, "DE", "DE", "bk11", 4)
    alt = copy.deepcopy(st)
    alt.txns[3].amount = round(alt.txns[3].amount + 25_000, 2)
    alt.recompute_balances()
    return emit_statement(st, folder / "statement.pdf", bank_files_from=alt)


@case("BK12", "round_deposit_before_cutoff", "bank_statement", "UAE", "review",
      ["large_round_cash_deposit_near_period_end", "balance_bucket_inflated_by_single_credit"],
      "UAE statement with a large round cash deposit two days before period end (funds parking).")
def _bk12(ctx, folder, rng):
    st, _ = _stmt(ctx, "UAE", "UAE", "bk12", 2, idx=4)
    st.txns.append(B.Txn(st.end - timedelta(days=2), "CASH DEPOSIT BRANCH", 2_500_000.0,
                         ref=P.letters(rng, 2) + P.digits(rng, 8)))
    st.txns.sort(key=lambda t: t.day)
    st.recompute_balances()
    return emit_statement(st, folder / "statement.pdf")


@case("BK13", "holder_differs_from_id", "cross_document", "UAE", "fail", ["holder_name_mismatch_with_id"],
      "Emirates ID for one person submitted with a statement in another person's name.")
def _bk13(ctx, folder, rng):
    a = person(ctx, "UAE", "bk13a", 2)
    b = person(ctx, "UAE", "bk13b", 4)
    st = B.make_statement(B.BANKS["UAE"], b.full_name, b.address, ctx.rng("stmt-bk13"), ctx.as_of, 4)
    return (emit_id(I.emirates_id(a, rng, ctx.as_of), folder / "emirates_id.pdf", 1301, photo=False)
            + emit_statement(st, folder / "statement.pdf"))


# =============================================================================
# Trade
# =============================================================================


def _ship(ctx, scenario: str, key: str, seq: int = 1) -> tuple[T.Shipment, B.Statement]:
    rng = ctx.rng(f"ship-{key}")
    sh = T.make_shipment(scenario, rng, ctx.as_of, seq)
    st = B.make_statement(B.BANKS[sh.seller_bank_code], sh.seller.name, sh.seller.address, rng, ctx.as_of, 5,
                          corporate=True, counterparties=[sh.buyer.name.upper()[:28], "OCEANIC MERIDIAN LINES"])
    sh.seller_account = dict(st.account)
    return sh, st


def emit_shipment(sh: T.Shipment, folder: Path, docs=("commercial_invoice", "packing_list", "bill_of_lading",
                                                     "letter_of_credit"), prefix: str = "") -> list:
    out = T.render_shipment(sh, folder, prefix or sh.scenario)
    truth = sh.truth()
    rows = []
    for k, path in out.items():
        base = {"mt700": "letter_of_credit", "cii": "commercial_invoice"}.get(k, k)
        if base in docs:
            rows.append((path, k, truth))
        else:
            path.unlink()
    return rows


@case("TR01", "invoice_arithmetic", "trade", "UAE", "fail",
      ["invoice_line_amount_not_qty_x_price", "invoice_total_not_sum_of_lines"],
      "Commercial invoice where line 2 amount is not quantity x unit price and the total ignores it.")
def _tr01(ctx, folder, rng):
    sh, _ = _ship(ctx, "UAE_to_PK", "tr01")
    sh.overrides["invoice"]["line_amounts"] = {1: round(sh.items[1].amount * 1.18, 2)}
    return emit_shipment(sh, folder)


@case("TR02", "seller_vs_account_holder", "cross_document", "UAE", "fail",
      ["seller_name_mismatch_with_account_holder"],
      "Invoice seller 'Al Nour General Trading FZE' vs statement holder 'Al Noor General Trading LLC' (different legal entity).")
def _tr02(ctx, folder, rng):
    sh, st = _ship(ctx, "UAE_to_PK", "tr02")
    sh.overrides["invoice"].update(seller_name="Al Nour General Trading FZE",
                                   account_name="Al Nour General Trading FZE")
    return emit_shipment(sh, folder, ("commercial_invoice",)) + emit_statement(st, folder / "seller_statement.pdf")


@case("TR03", "container_check_digit", "trade", "IN", "fail", ["container_iso6346_check_digit"],
      "Bill of lading listing a container number with a wrong ISO 6346 check digit.")
def _tr03(ctx, folder, rng):
    sh, _ = _ship(ctx, "IN_to_UK", "tr03")
    cs = copy.deepcopy(sh.containers)
    c = cs[0].number
    cs[0].number = c[:-1] + str((int(c[-1]) + 1) % 10)
    sh.overrides["bl"]["containers"] = cs
    return emit_shipment(sh, folder)


@case("TR04", "bl_consignee_not_per_lc", "trade", "UAE", "fail",
      ["bl_consignee_not_per_lc", "bl_notify_party_not_applicant"],
      "B/L consigned 'to order of shipper' with an unrelated notify party; the L/C requires order of issuing bank.")
def _tr04(ctx, folder, rng):
    sh, _ = _ship(ctx, "UAE_to_PK", "tr04")
    sh.overrides["bl"].update(consignee="TO ORDER OF SHIPPER", notify_name="Sindh Plastics Trading Co.")
    return emit_shipment(sh, folder)


@case("TR05", "port_of_discharge_mismatch", "trade", "UAE", "fail", ["bl_port_of_discharge_differs_from_lc"],
      "B/L discharges at Port Qasim (PKBQM) while L/C and invoice say Karachi (PKKHI).")
def _tr05(ctx, folder, rng):
    sh, _ = _ship(ctx, "UAE_to_PK", "tr05")
    sh.overrides["bl"]["pod"] = ("PKBQM", "Port Qasim, Pakistan")
    return emit_shipment(sh, folder)


@case("TR06", "late_shipment", "trade", "BD", "fail", ["shipment_after_lc_latest_date"],
      "Shipped-on-board date is 6 days after the L/C latest shipment date (44C).")
def _tr06(ctx, folder, rng):
    sh, _ = _ship(ctx, "BD_to_DE", "tr06")
    sh.overrides["bl"]["on_board"] = sh.latest_shipment + timedelta(days=6)
    return emit_shipment(sh, folder)


@case("TR07", "invoice_exceeds_lc", "trade", "AU", "fail", ["invoice_amount_exceeds_lc_plus_tolerance"],
      "Invoice quantities inflated 25% so the total exceeds the L/C amount plus 5% tolerance.")
def _tr07(ctx, folder, rng):
    sh, _ = _ship(ctx, "AU_to_UAE", "tr07")
    items = [dataclasses.replace(i, quantity=i.quantity * 1.25) for i in sh.items]
    sh.overrides["invoice"].update(items=items, total=round(sum(i.amount for i in items), 2))
    return emit_shipment(sh, folder)


@case("TR08", "weight_mismatch", "trade", "IN", "fail", ["gross_weight_packing_list_vs_bl"],
      "Packing list gross weight is 12% higher than the bill of lading.")
def _tr08(ctx, folder, rng):
    sh, _ = _ship(ctx, "IN_to_UK", "tr08")
    sh.overrides["packing"]["gross_kg"] = {0: round(sh.items[0].gross_kg * 1.12 + sh.items[1].gross_kg * 0.12, 1)}
    return emit_shipment(sh, folder)


@case("TR09", "goods_description_mismatch", "trade", "BD", "fail", ["goods_description_bl_vs_invoice"],
      "B/L describes used tyres (HS 4012.20) while invoice and L/C describe knitted garments.")
def _tr09(ctx, folder, rng):
    sh, _ = _ship(ctx, "BD_to_DE", "tr09")
    sh.overrides["bl"]["goods_description"] = "Used passenger car tyres, mixed sizes (HS 4012.20)"
    return emit_shipment(sh, folder)


@case("TR10", "duplicate_invoice_number", "cross_document", "UAE", "fail",
      ["duplicate_invoice_number_different_shipments"],
      "The same invoice number presented for two different shipments under two L/Cs (double financing).")
def _tr10(ctx, folder, rng):
    a, _ = _ship(ctx, "UAE_to_PK", "tr10a", 7)
    b, _ = _ship(ctx, "AU_to_UAE", "tr10b", 8)
    b.overrides["invoice"]["invoice_no"] = a.invoice_no
    docs = ("commercial_invoice", "letter_of_credit")
    return emit_shipment(a, folder, docs, "shipment_a") + emit_shipment(b, folder, docs, "shipment_b")


@case("TR11", "payment_account_diversion", "cross_document", "AU", "fail",
      ["invoice_beneficiary_account_differs_from_seller_statement"],
      "Invoice asks for payment to an account that is not the seller's (business-email-compromise pattern).")
def _tr11(ctx, folder, rng):
    sh, st = _ship(ctx, "AU_to_UAE", "tr11")
    bsb = P.digits(rng, 6)
    sh.overrides["invoice"]["seller_account"] = {"bsb": f"{bsb[:3]}-{bsb[3:]}", "account_number": P.digits(rng, 9)}
    return emit_shipment(sh, folder, ("commercial_invoice",)) + emit_statement(st, folder / "seller_statement.pdf")


# =============================================================================
# Edge cases: must pass
# =============================================================================


@case("EC01", "transliteration_mohammad_mohammed", "cross_document", "UAE", "pass",
      ["name_transliteration_variant"],
      "Passport says MOHAMMAD, bank statement says Mohammed. Same person; fuzzy name match must accept it.")
def _ec01(ctx, folder, rng):
    p = person(ctx, "UAE", "ec01", 6)  # Mohammed Al Falasi
    pp_holder = copy.deepcopy(p)
    pp_holder.given = "Mohammad"
    st = B.make_statement(B.BANKS["UAE"], p.full_name, p.address, ctx.rng("stmt-ec01"), ctx.as_of, 3)
    return (emit_id(I.passport(pp_holder, rng, ctx.as_of), folder / "uae_passport.pdf", 2101, photo=False)
            + emit_statement(st, folder / "statement.pdf"))


@case("EC02", "sheikh_in_given_names", "cross_document", "UAE", "pass", ["honorific_in_name_field"],
      "Passport given names 'SHEIKH KHALID'; statement holder 'Khalid Al Nuaimi'. Honorific must not break matching.")
def _ec02(ctx, folder, rng):
    p = person(ctx, "UAE", "ec02", 4)  # Khalid Al Nuaimi
    pp_holder = copy.deepcopy(p)
    pp_holder.given = "Sheikh Khalid"
    st = B.make_statement(B.BANKS["UAE"], p.full_name, p.address, ctx.rng("stmt-ec02"), ctx.as_of, 6)
    return (emit_id(I.passport(pp_holder, rng, ctx.as_of), folder / "uae_passport.pdf", 2201, photo=False)
            + emit_statement(st, folder / "statement.pdf"))


@case("EC03", "date_ambiguity_us_vs_uk", "bank_statement", "US/UK", "pass", ["ambiguous_date_format"],
      "Both statements print '04/05/2026'. US (MM/DD) means 5 April 2026; UK (DD/MM) means 4 May 2026. "
      "Ground truth holds ISO dates.")
def _ec03(ctx, folder, rng):
    as_of = date(2026, 6, 10)  # period March-May 2026
    out = []
    for code, region, real in (("US", "US", date(2026, 4, 5)), ("UK", "UK", date(2026, 5, 4))):
        bank = dataclasses.replace(B.BANKS[code], date_style="mdy" if code == "US" else "dmy")
        st, _ = _stmt(ctx, code, region, f"ec03{code}", 2, as_of=as_of, bank=bank)
        st.txns.append(B.Txn(real, "TRANSFER FROM J. SMITH", 1234.56, ref="EC03" + P.digits(rng, 6)))
        st.txns.sort(key=lambda t: t.day)
        st.recompute_balances()
        out += emit_statement(st, folder / f"statement_{code.lower()}.pdf",
                              {"planted": {"printed": "04/05/2026", "iso": real.isoformat()}})
    return out


@case("EC04", "character_sets", "identity", "EU", "pass", ["diacritics_and_mrz_transliteration"],
      "Names with ü, ñ, é, ï: printed with accents, MRZ transliterated per ICAO (Ü->UE, Ñ->N, É->E).")
def _ec04(ctx, folder, rng):
    out = []
    specs = [("DE", "Jürgen", "Müller-Lüdenscheidt", "M", I.de_id_card, "de_id_card"),
             ("ES", "María José", "Muñoz", "F", I.es_dni, "es_dni"),
             ("FR", "Éloïse", "Lefèvre", "F", I.passport, "fr_passport")]
    for k, (region, given, surname, sex, builder, name) in enumerate(specs):
        p = person(ctx, region, f"ec04{region}", k)
        p.given, p.surname, p.sex = given, surname, sex
        if region == "ES":
            p.extra["second_surname"] = "IBÁÑEZ"
        out += emit_id(builder(p, rng, ctx.as_of), folder / f"{name}.pdf", 2400 + k, photo=False)
    return out


@case("EC05", "legal_suffix_variant", "cross_document", "IN", "pass", ["company_suffix_variant"],
      "Invoice seller 'Coromandel Cotton Exports Private Limited' vs statement 'Coromandel Cotton Exports Pvt Ltd'.")
def _ec05(ctx, folder, rng):
    sh, st = _ship(ctx, "IN_to_UK", "ec05")
    sh.overrides["invoice"].update(seller_name="Coromandel Cotton Exports Private Limited",
                                   account_name="Coromandel Cotton Exports Private Limited")
    return emit_shipment(sh, folder, ("commercial_invoice",)) + emit_statement(st, folder / "seller_statement.pdf")


@case("EC06", "bd_nid_old_and_smart", "identity", "BD", "pass", ["nid_10_and_17_digit_formats"],
      "Same holder with an old 17-digit paper NID and a 10-digit smart NID; both formats are valid.")
def _ec06(ctx, folder, rng):
    p = person(ctx, "BD", "ec06", 5)
    return (emit_id(I.bd_nid(p, rng, ctx.as_of, smart=False), folder / "bd_paper_nid.pdf", 2601, photo=False)
            + emit_id(I.bd_nid(p, rng, ctx.as_of, smart=True), folder / "bd_smart_nid.pdf", 2602, photo=False))


# --- runner ------------------------------------------------------------------------


def run_cases(root: Path, as_of: date, seed: int, only: set[str] | None = None) -> list[dict]:
    """Generate every case under root; return manifest rows."""
    ctx = Ctx(as_of, seed)
    rows = []
    for c in CASES:
        if only and c.case_id not in only:
            continue
        sub = "edge_cases" if c.expected_result == "pass" else c.category
        folder = root / sub / f"{c.case_id}_{c.slug}"
        produced = c.fn(ctx, folder, ctx.rng(f"case-{c.case_id}"))
        label = "edge_case" if c.expected_result == "pass" else "fraud"
        meta = {"case_id": c.case_id, "slug": c.slug, "category": c.category, "region": c.region,
                "label": label, "expected_result": c.expected_result, "expected_findings": c.findings,
                "description": c.description, "as_of": as_of.isoformat(),
                "files": sorted({p.name for p, _, _ in produced})}
        write_json(folder / "case.json", meta)
        seen = set()
        for path, doc_type, truth in produced:
            if path.suffix in (".pdf", ".jpg"):
                gt = path.with_suffix(".json")
                if gt not in seen:
                    write_json(gt, dict(truth, case=meta))
                    seen.add(gt)
            rows.append({"file": path, "tier": "04_adversarial_fraud", "category": c.category, "region": c.region,
                         "doc_type": doc_type, "label": label, "case_id": c.case_id,
                         "expected_result": c.expected_result, "expected_findings": ";".join(c.findings),
                         "ground_truth": folder / "case.json", "notes": c.description})
    return rows
