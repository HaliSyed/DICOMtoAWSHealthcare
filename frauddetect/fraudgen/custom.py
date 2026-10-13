"""Custom fraud cases from a JSON file, without writing Python.

A case names one or more documents, the people on them, and a list of
mutations (the planted defects). See HOWTO.md for every option and
examples/custom_cases_uae.json for a working file.

    {"cases": [{
        "id": "CU01", "name": "expired_uae_passport",
        "expected_result": "fail", "expected_findings": ["document_expired"],
        "person": {"region": "UAE", "given": "Omar", "surname": "Al Hammadi"},
        "documents": [{"type": "passport", "mutations": [{"op": "expire", "days_ago": 30}]}]
    }]}
"""

from __future__ import annotations

import copy
import dataclasses
import json
import random
import re
import shutil
import zlib
from datetime import date, timedelta
from pathlib import Path

from . import banking as B
from . import checksums as ck
from . import fraud as F
from . import identity as I
from . import people as P
from . import trade as T
from .mrz import break_check_digit, retouch


class SpecError(ValueError):
    """A problem in the custom-case file; the message names the case and the field."""


# --- what can be built ----------------------------------------------------------------

ID_TYPES = {
    "emirates_id": (I.emirates_id, {"UAE"}),
    "passport": (I.passport, {"UAE", "UK", "US", "PK", "IN", "BD", "AU", "NZ", "FR", "DE", "ES"}),
    "uk_driving_licence": (I.uk_driving_licence, {"UK"}),
    "us_driving_licence": (I.us_driving_licence, {"US"}),
    "pk_cnic": (I.pk_cnic, {"PK"}),
    "pk_nicop": (lambda p, r, a: I.pk_cnic(p, r, a, nicop=True), {"PK"}),
    "aadhaar": (I.aadhaar, {"IN"}),
    "pan_card": (I.pan_card, {"IN"}),
    "bd_smart_nid": (I.bd_nid, {"BD"}),
    "bd_paper_nid": (lambda p, r, a: I.bd_nid(p, r, a, smart=False), {"BD"}),
    "au_driving_licence": (I.au_driving_licence, {"AU"}),
    "au_medicare": (I.medicare_card, {"AU"}),
    "nz_driving_licence": (I.nz_driving_licence, {"NZ"}),
    "de_id_card": (I.de_id_card, {"DE"}),
    "es_dni": (I.es_dni, {"ES"}),
}

# the main number printed on each document type
MAIN_NUMBER = {"emirates_id": "id_number", "passport": "document_number", "uk_driving_licence": "licence_number",
               "us_driving_licence": "licence_number", "pk_cnic": "id_number", "pk_nicop": "id_number",
               "aadhaar": "aadhaar_number", "pan_card": "pan", "bd_smart_nid": "nid_number",
               "bd_paper_nid": "nid_number", "au_driving_licence": "licence_number",
               "au_medicare": "medicare_number", "nz_driving_licence": "licence_number",
               "de_id_card": "card_number", "es_dni": "dni"}

BANK_HOLDER_REGION = {"UAE": "UAE", "UK": "UK", "US": "US", "PK": "PK", "IN": "IN", "BD": "BD", "AU": "AU",
                      "NZ": "NZ", "DE": "DE", "FR": "FR", "NL": "NL"}
TRADE_DOCS = ("commercial_invoice", "packing_list", "bill_of_lading", "letter_of_credit")
PERSON_KEYS = {"region", "given", "surname", "given_native", "surname_native", "sex", "dob", "age",
               "place_of_birth", "address", "father_name", "father_name_native", "mother_name"}


# --- people -----------------------------------------------------------------------------


def build_person(spec: dict, ctx: F.Ctx, key: str, where: str) -> P.Person:
    unknown = set(spec) - PERSON_KEYS
    if unknown:
        raise SpecError(f"{where}: unknown person field(s) {sorted(unknown)}; allowed {sorted(PERSON_KEYS)}")
    region = spec.get("region")
    if region not in P.ISO3:
        raise SpecError(f"{where}: person.region must be one of {sorted(P.ISO3)}")
    p = P.make_person(region, ctx.rng(f"custom-person-{key}"), ctx.as_of, 0)
    for k in ("given", "surname", "given_native", "surname_native", "place_of_birth", "address",
              "father_name", "father_name_native", "mother_name"):
        if k in spec:
            setattr(p, k, spec[k])
    if "sex" in spec:
        if spec["sex"] not in ("M", "F"):
            raise SpecError(f"{where}: person.sex must be M or F")
        p.sex = spec["sex"]
    if "dob" in spec:
        p.dob = _date(spec["dob"], where + ".dob")
    elif "age" in spec:
        p.dob = date(ctx.as_of.year - int(spec["age"]), p.dob.month, min(p.dob.day, 28))
    if region in ("UAE", "PK", "IN", "BD") and ("given" in spec) != ("given_native" in spec):
        # generated native name would no longer match a custom Latin name (or vice versa)
        raise SpecError(f"{where}: for {region} give both 'given' and 'given_native' (and surname/surname_native)")
    return p


def _date(v, where: str) -> date:
    try:
        return date.fromisoformat(v)
    except (TypeError, ValueError):
        raise SpecError(f"{where}: expected a date as YYYY-MM-DD, got {v!r}") from None


def _when(m: dict, ctx: F.Ctx, where: str, date_key: str = "date", rel_key: str = "days_from_today") -> date:
    if date_key in m:
        return _date(m[date_key], where)
    if rel_key in m:
        return ctx.as_of + timedelta(days=int(m[rel_key]))
    raise SpecError(f"{where}: give '{date_key}' (YYYY-MM-DD) or '{rel_key}' (number, negative = past)")


# --- identity mutations ---------------------------------------------------------------------

_DATE_FORMATS = [lambda d: I.dmy(d), lambda d: I.dmy(d, "."), lambda d: I.dmy(d, "-"), lambda d: I.dmy(d, " "),
                 I.mdy, I.dmony]


def _replace_printed_date(doc: I.IdDoc, old: date, new: date) -> int:
    """Rewrite every printed occurrence of `old`, keeping each field's own date format."""
    n = 0
    for f in doc.fields + doc.back_fields:
        for fmt in _DATE_FORMATS:
            if fmt(old) in f.value:
                f.value = f.value.replace(fmt(old), fmt(new))
                n += 1
                break
    return n


def _yy(d: date) -> str:
    return d.strftime("%y%m%d")


def _set_main_number(doc: I.IdDoc, value: str, update_mrz: bool) -> None:
    key = MAIN_NUMBER[doc.doc_type]
    f = doc.get(key)
    old = doc.truth[key]
    if doc.doc_type == "uk_driving_licence":
        f.value = f"{value}  {doc.truth['issue_number']}"
    elif doc.doc_type == "aadhaar":
        v = value.replace(" ", "")
        f.value = f"{v[:4]} {v[4:8]} {v[8:]}"
        value = v
    elif doc.doc_type == "au_medicare":
        v = value.replace(" ", "")
        f.value = f"{v[:4]} {v[4:9]} {v[9:]}"
        value = v
    else:
        f.value = value
    doc.truth[key] = value
    if doc.barcode and doc.doc_type == "us_driving_licence":
        doc.barcode = doc.barcode.replace(f"DAQ{old}\n", f"DAQ{value}\n")
    if update_mrz and doc.mrz:
        if doc.doc_type in ("passport", "de_id_card"):
            doc.mrz = retouch(doc.mrz, number=value)
        elif doc.doc_type == "emirates_id":
            doc.mrz = retouch(doc.mrz, optional1=value.replace("-", ""))
        elif doc.doc_type == "es_dni":
            doc.mrz = retouch(doc.mrz, optional1=value)


def _break_number(doc: I.IdDoc, where: str) -> None:
    """Make the main number fail its own check rule while staying well-formed."""
    key = MAIN_NUMBER[doc.doc_type]
    n = doc.truth[key]
    t = doc.doc_type
    if t == "emirates_id":
        bad = n[:-1] + str((int(n[-1]) + 3) % 10)
    elif t == "aadhaar":
        bad = n[:-1] + str((int(n[-1]) + 1) % 10)
    elif t == "au_medicare":
        bad = n[:8] + str((int(n[8]) + 5) % 10) + n[9:]
    elif t == "es_dni":
        bad = n[:-1] + next(c for c in "TRWAGMY" if c != n[-1])
    elif t in ("pk_cnic", "pk_nicop"):
        last = int(n[-1])
        bad = n[:-1] + str((last + 1) % 10)  # flips the gender parity
    elif t == "pan_card":
        bad = n[:3] + "C" + n[4:]  # company holder type on a personal card
    elif t == "uk_driving_licence":
        bad = n[:6] + f"{(int(n[6:8]) % 12) + 1:02d}" + n[8:]  # month no longer matches DOB
    elif t == "bd_paper_nid":
        bad = str(int(n[:4]) + 5) + n[4:]
    else:
        raise SpecError(f"{where}: break_check_digit target 'id_number' is not defined for {t}; "
                        "use an mrz_* target or set_number")
    _set_main_number(doc, bad, update_mrz=True)


def apply_id_mutation(doc: I.IdDoc, m: dict, ctx: F.Ctx, where: str) -> dict | None:
    """Apply one mutation. Returns overlay instructions for after rendering, if any."""
    op = m.get("op")
    p = doc.person
    if op == "set_field":
        try:
            doc.get(m["field"]).value = str(m["value"])
        except KeyError:
            names = [f.key for f in doc.fields + doc.back_fields]
            raise SpecError(f"{where}: field {m.get('field')!r} not on {doc.doc_type}; fields are {names}") from None
    elif op == "set_number":
        _set_main_number(doc, str(m["value"]), m.get("mrz", True))
    elif op == "break_check_digit":
        target = m.get("target")
        if target == "id_number":
            _break_number(doc, where)
        elif target in ("mrz_document_number", "mrz_dob", "mrz_expiry", "mrz_composite"):
            if not doc.mrz:
                raise SpecError(f"{where}: {doc.doc_type} has no MRZ")
            doc.mrz = break_check_digit(doc.mrz, target[4:])
        else:
            raise SpecError(f"{where}: target must be id_number, mrz_document_number, mrz_dob, mrz_expiry "
                            "or mrz_composite")
    elif op == "set_dob":
        new = _date(m["date"], where) if "date" in m else date(ctx.as_of.year - int(m["age"]), p.dob.month,
                                                                 min(p.dob.day, 28))
        printed, in_mrz = m.get("printed", True), m.get("mrz", True)
        old = date.fromisoformat(doc.truth["dob"])
        if printed:
            _replace_printed_date(doc, old, new)
        if in_mrz and doc.mrz:
            doc.mrz = retouch(doc.mrz, dob=_yy(new))
        if doc.barcode and m.get("barcode", True):
            doc.barcode = doc.barcode.replace("DBB" + old.strftime("%m%d%Y"), "DBB" + new.strftime("%m%d%Y"))
        if printed:
            doc.truth["dob"] = new.isoformat()
        doc.truth.setdefault("planted", {})["dob"] = {"printed": printed, "mrz": in_mrz, "value": new.isoformat()}
    elif op in ("set_expiry", "expire", "set_issue"):
        key = "issue_date" if op == "set_issue" else "expiry_date"
        if not doc.truth.get(key):
            raise SpecError(f"{where}: {doc.doc_type} has no printed {key}")
        if op == "expire":
            new = ctx.as_of - timedelta(days=int(m.get("days_ago", 30)))
        else:
            new = _when(m, ctx, where)
        old = date.fromisoformat(doc.truth[key])
        _replace_printed_date(doc, old, new)
        doc.truth[key] = new.isoformat()
        if key == "expiry_date" and doc.mrz and m.get("mrz", True):
            doc.mrz = retouch(doc.mrz, expiry=_yy(new))
    elif op == "set_name":
        given, surname = m.get("given", p.given), m.get("surname", p.surname)
        for k, v in (("given_names", given.upper()), ("surname", surname.upper())):
            try:
                doc.get(k).value = v
            except KeyError:
                pass
        for k in ("name",):
            try:
                f = doc.get(k)
                f.value = f"{given} {surname}" if not f.value.isupper() else f"{given} {surname}".upper()
            except KeyError:
                pass
        if m.get("mrz", False) and doc.mrz:
            from .mrz import mrz_name
            if len(doc.mrz) == 2:
                doc.mrz[0] = doc.mrz[0][:5] + mrz_name(surname, given, 39)
            else:
                doc.mrz[2] = mrz_name(surname, given, 30)
    elif op == "set_mrz_country":
        if not doc.mrz:
            raise SpecError(f"{where}: {doc.doc_type} has no MRZ")
        doc.mrz = retouch(doc.mrz, country=m["code"])
    elif op == "set_barcode_field":
        if not doc.barcode:
            raise SpecError(f"{where}: only us_driving_licence has a barcode")
        el = m["element"]
        doc.barcode = re.sub(rf"{el}[^\n]*\n", f"{el}{m['value']}\n", doc.barcode, count=1)
    elif op == "overlay":
        try:
            original = doc.get(m["field"]).value
        except KeyError:
            raise SpecError(f"{where}: overlay field {m.get('field')!r} not on {doc.doc_type}") from None
        return {"search": original, "value": str(m["value"]), "page": 0 if doc.get(m["field"]) in doc.fields else 1,
                "producer": m.get("producer", "Adobe Photoshop 25.1 (Windows)")}
    else:
        raise SpecError(f"{where}: unknown identity op {op!r}")
    return None


# --- bank statement mutations -------------------------------------------------------------------


def _pick_txn(st: B.Statement, sel, where: str) -> int:
    if isinstance(sel, int):
        if not 0 <= sel < len(st.txns):
            raise SpecError(f"{where}: txn index {sel} out of range 0..{len(st.txns) - 1}")
        return sel
    picks = {
        # salary on personal statements, else the largest customer receipt on corporate ones
        "salary": lambda: next((i for i, t in enumerate(st.txns)
                                if t.amount > 0 and t.description.startswith(("SALARY", "PAYROLL"))),
                               max(range(len(st.txns)), key=lambda i: st.txns[i].amount)),
        "largest_credit": lambda: max(range(len(st.txns)), key=lambda i: st.txns[i].amount),
        "largest_debit": lambda: min(range(len(st.txns)), key=lambda i: st.txns[i].amount),
        "first": lambda: 0, "last": lambda: len(st.txns) - 1,
    }
    if sel not in picks:
        raise SpecError(f"{where}: txn must be an index or one of {sorted(picks)}")
    return picks[sel]()


def apply_bank_mutation(st: B.Statement, m: dict, ctx: F.Ctx, where: str, state: dict) -> dict | None:
    op = m.get("op")
    if op == "set_holder":
        st.holder = m["name"]
    elif op == "set_account":
        st.account[m["key"]] = str(m["value"])
    elif op == "break_check_digit":
        t = m.get("target")
        a = st.account
        if t == "iban" and "iban" in a:
            i = a["iban"]
            a["iban"] = i[:10] + str((int(i[10]) + 1) % 10) + i[11:]
        elif t == "routing_number" and "routing_number" in a:
            r = a["routing_number"]
            a["routing_number"] = r[:8] + str((int(r[8]) + 1) % 10)
        elif t == "ifsc" and "ifsc" in a:
            a["ifsc"] = a["ifsc"][:4] + "O" + a["ifsc"][5:]
        else:
            raise SpecError(f"{where}: target {t!r} not available; this account has {sorted(a)}")
    elif op == "edit_amount":
        i = _pick_txn(st, m.get("txn", "largest_debit"), where)
        before = st.txns[i].amount
        st.txns[i].amount = round(before * float(m["factor"]), 2) if "factor" in m else float(m["amount"])
        if m.get("recompute", False):
            st.recompute_balances()
        state.setdefault("planted", []).append({"op": op, "txn": i, "before": before, "after": st.txns[i].amount})
    elif op == "inflate_closing":
        state.setdefault("genuine", copy.deepcopy(st))
        st.closing_override = round(st.closing * float(m.get("factor", 3)), 2)
        if m.get("structured_files", "genuine") == "tampered":
            state.pop("genuine")
    elif op == "add_transaction":
        if "date" in m:
            d = _date(m["date"], where)
        else:
            d = st.end - timedelta(days=int(m.get("days_before_end", 2)))
        st.txns.append(B.Txn(d, m.get("description", "CASH DEPOSIT"), float(m["amount"]),
                             ref="CU" + P.digits(random.Random(where), 8)))
        st.txns.sort(key=lambda t: t.day)
        st.recompute_balances()
    elif op == "move_transaction":
        i = _pick_txn(st, m.get("txn", "first"), where)
        st.txns[i].day = st.start - timedelta(days=int(m.get("days_before_start", 9)))
        st.txns.sort(key=lambda t: t.day)
        st.recompute_balances()
    elif op == "shift_period":
        days = int(m["days"])
        for t in st.txns:
            t.day += timedelta(days=days)
        st.start += timedelta(days=days)
        st.end += timedelta(days=days)
        if st.issued:
            st.issued += timedelta(days=days)
    elif op == "mixed_number_format":
        rng = random.Random(where)
        st.row_styles = {i: m.get("style", "en") for i in rng.sample(range(len(st.txns)), int(m.get("rows", 3)))}
    elif op == "alter_structured_files":
        alt = copy.deepcopy(state.get("genuine", st))
        i = _pick_txn(alt, m.get("txn", 3), where)
        alt.txns[i].amount = round(alt.txns[i].amount + float(m.get("add_amount", 25000)), 2)
        alt.recompute_balances()
        state["structured"] = alt
    elif op == "overlay":
        i = _pick_txn(st, m.get("txn", "salary"), where)
        amt = st.txns[i].amount
        new = amt * float(m["factor"]) if "factor" in m else float(m["value"])
        style = st.bank.num_style
        return {"search": B.fmt_num(abs(amt), style), "value": B.fmt_num(abs(new), style), "page": 0,
                "producer": m.get("producer", "Adobe Photoshop 25.1 (Windows)")}
    else:
        raise SpecError(f"{where}: unknown bank_statement op {op!r}")
    return None


# --- trade mutations ----------------------------------------------------------------------------

_TRADE_SET_KEYS = {
    "invoice": {"seller_name", "buyer_name", "account_name", "invoice_no", "invoice_date", "total", "pod"},
    "bl": {"consignee", "notify_name", "shipper_name", "bl_no", "goods_description", "pod", "on_board", "gross_total"},
    "packing": {"gross_total"},
    "lc": {"beneficiary", "amount", "latest_shipment", "expiry", "pod"},
}
_DATE_KEYS = {"invoice_date", "on_board", "latest_shipment", "expiry"}


def apply_trade_mutation(sh: T.Shipment, m: dict, ctx: F.Ctx, where: str) -> None:
    op = m.get("op")
    o = sh.overrides
    if op == "set":
        doc, key, value = m.get("doc"), m.get("key"), m.get("value")
        if doc not in _TRADE_SET_KEYS or key not in _TRADE_SET_KEYS[doc]:
            raise SpecError(f"{where}: 'set' supports {{doc: keys}} = "
                            f"{ {d: sorted(k) for d, k in _TRADE_SET_KEYS.items()} }")
        if key == "pod":
            value = tuple(value)
        elif key in _DATE_KEYS:
            value = _date(value, where)
        o[doc][key] = value
    elif op == "line_amount":
        line = int(m.get("line", 2)) - 1
        o["invoice"].setdefault("line_amounts", {})[line] = round(sh.items[line].amount * float(m["factor"]), 2)
    elif op == "scale_quantity":
        items = [dataclasses.replace(i, quantity=i.quantity * float(m["factor"])) for i in sh.items]
        o["invoice"].update(items=items, total=round(sum(i.amount for i in items), 2))
    elif op == "late_shipment":
        o["bl"]["on_board"] = sh.latest_shipment + timedelta(days=int(m.get("days", 6)))
    elif op == "break_container":
        cs = copy.deepcopy(o["bl"].get("containers", sh.containers))
        k = int(m.get("index", 0))
        c = cs[k].number
        cs[k].number = c[:-1] + str((int(c[-1]) + 1) % 10)
        o["bl"]["containers"] = cs
    elif op == "gross_weight":
        o["packing"]["gross_kg"] = {0: round(sh.items[0].gross_kg + sum(i.gross_kg for i in sh.items)
                                             * (float(m["factor"]) - 1), 1)}
    elif op == "divert_payment":
        o["invoice"]["seller_account"] = m.get("account") or B.make_account(
            B.BANKS[sh.seller_bank_code], random.Random(where))
    else:
        raise SpecError(f"{where}: unknown trade op {op!r}")


# --- runner -------------------------------------------------------------------------------------


def _overlay_all(path: Path, overlays: list[dict], truth: dict) -> None:
    for ov in overlays:
        info = F.overlay(path, ov["search"], ov["value"], page_no=ov["page"], producer=ov["producer"])
        truth.setdefault("tampers", []).append(info["tamper"])


def run_custom(spec_path: Path, root: Path, as_of: date, seed: int) -> list[dict]:
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SpecError(f"{spec_path.name}: not valid JSON ({e})") from None
    cases = spec.get("cases")
    if not isinstance(cases, list) or not cases:
        raise SpecError(f"{spec_path.name}: needs a non-empty 'cases' list")
    ids = [c.get("id") for c in cases]
    if len(ids) != len(set(ids)) or not all(ids):
        raise SpecError(f"{spec_path.name}: every case needs a unique 'id'")
    ctx = F.Ctx(as_of, seed)
    rows = []
    for c in cases:
        rows += _run_case(c, ctx, root)
    return rows


def _run_case(c: dict, ctx: F.Ctx, root: Path) -> list[dict]:
    cid = str(c["id"])
    where = f"case {cid}"
    expected = c.get("expected_result", "fail")
    if expected not in ("fail", "review", "pass"):
        raise SpecError(f"{where}: expected_result must be fail, review or pass")
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", c.get("name", "custom")).strip("_")
    folder = root / "custom" / f"{cid}_{slug}"
    if folder.exists():  # re-running a spec replaces that case only
        shutil.rmtree(folder)
    people: dict[str, P.Person] = {}
    if "person" in c:
        people["default"] = build_person(c["person"], ctx, f"{cid}-default", where + ".person")
    for name, ps in (c.get("people") or {}).items():
        people[name] = build_person(ps, ctx, f"{cid}-{name}", f"{where}.people.{name}")
    docs = c.get("documents")
    if not isinstance(docs, list) or not docs:
        raise SpecError(f"{where}: needs a non-empty 'documents' list")

    produced: list = []
    for n, d in enumerate(docs, 1):
        w = f"{where} document {n}"
        dtype = d.get("type")
        rng = ctx.rng(f"custom-{cid}-{n}")
        holder_key = d.get("holder", "default")
        muts = d.get("mutations", [])
        if dtype in ID_TYPES:
            if holder_key not in people:
                raise SpecError(f"{w}: holder {holder_key!r} not defined (add 'person' or 'people')")
            p = copy.deepcopy(people[holder_key])
            builder, regions = ID_TYPES[dtype]
            if p.region not in regions:
                raise SpecError(f"{w}: {dtype} needs a holder from {sorted(regions)}, got {p.region}")
            if dtype == "passport" and p.region == "PK":
                p.extra.setdefault("cnic", P.cnic(p.sex, rng))
                doc = I.passport(p, rng, ctx.as_of, extra_personal=p.extra["cnic"].replace("-", ""))
            else:
                doc = builder(p, rng, ctx.as_of)
            overlays = [ov for i, m in enumerate(muts)
                        if (ov := apply_id_mutation(doc, m, ctx, f"{w} mutation {i + 1}"))]
            path = folder / d.get("file", f"{dtype}_{n}.pdf")
            rows = F.emit_id(doc, path, zlib.crc32(f"{cid}/{path.name}".encode()),
                             photo=bool(d.get("photo", False)) and not overlays, rng=rng)
            if overlays:
                _overlay_all(path, overlays, rows[0][2])
                if d.get("photo"):
                    from . import degrade as D
                    from . import render as R
                    img = R.rasterize(path, 300)[0]
                    ph, fx = D.mobile(img, rng)
                    jpg = path.with_name(path.stem + "_photo.jpg")
                    D.save_jpeg(ph, jpg)
                    rows.append((jpg, dtype, dict(rows[0][2], capture=fx)))
            produced += rows
        elif dtype == "bank_statement":
            code = d.get("bank")
            if code not in B.BANKS:
                raise SpecError(f"{w}: bank must be one of {sorted(B.BANKS)}")
            if holder_key in people:
                hp = people[holder_key]
            else:
                hp = P.make_person(BANK_HOLDER_REGION[code], rng, ctx.as_of, 0)
            bucket = int(d.get("bucket", 3))
            if not 0 <= bucket <= 8:
                raise SpecError(f"{w}: bucket must be 0..8")
            st = B.make_statement(B.BANKS[code], d.get("holder_name", hp.full_name), hp.address, rng,
                                  ctx.as_of, bucket, months=int(d.get("months", 3)),
                                  corporate=bool(d.get("corporate", False)))
            state: dict = {}
            overlays = [ov for i, m in enumerate(muts)
                        if (ov := apply_bank_mutation(st, m, ctx, f"{w} mutation {i + 1}", state))]
            path = folder / d.get("file", f"statement_{code.lower()}_{n}.pdf")
            extra = {"planted": state["planted"]} if "planted" in state else None
            rows = F.emit_statement(st, path, extra, bank_files_from=state.get("structured") or state.get("genuine"))
            if overlays:
                _overlay_all(path, overlays, rows[0][2])
            produced += rows
        elif dtype == "trade":
            scenario = d.get("scenario")
            if scenario not in T.SCENARIOS:
                raise SpecError(f"{w}: scenario must be one of {sorted(T.SCENARIOS)}")
            sh, st = F._ship(ctx, scenario, f"custom-{cid}-{n}")
            for i, m in enumerate(muts):
                apply_trade_mutation(sh, m, ctx, f"{w} mutation {i + 1}")
            wanted = tuple(d.get("documents", TRADE_DOCS))
            bad = set(wanted) - set(TRADE_DOCS)
            if bad:
                raise SpecError(f"{w}: unknown trade documents {sorted(bad)}; choose from {list(TRADE_DOCS)}")
            produced += F.emit_shipment(sh, folder, wanted, d.get("prefix", f"{scenario}_{n}"))
            if d.get("seller_statement", False):
                sst_muts = d.get("seller_statement_mutations", [])
                state = {}
                for i, m in enumerate(sst_muts):
                    apply_bank_mutation(st, m, ctx, f"{w} seller_statement mutation {i + 1}", state)
                produced += F.emit_statement(st, folder / f"{scenario}_{n}_seller_statement.pdf")
        else:
            raise SpecError(f"{w}: type must be one of {sorted(ID_TYPES) + ['bank_statement', 'trade']}")

    label = "edge_case" if expected == "pass" else "fraud"
    meta = {"case_id": cid, "slug": slug, "category": "custom", "region": c.get("region", ""),
            "label": label, "expected_result": expected, "expected_findings": c.get("expected_findings", []),
            "description": c.get("description", ""), "as_of": ctx.as_of.isoformat(), "source": "custom spec",
            "files": sorted({p.name for p, _, _ in produced})}
    F.write_json(folder / "case.json", meta)
    out, seen = [], set()
    for path, doc_type, truth in produced:
        if path.suffix in (".pdf", ".jpg"):
            gt = path.with_suffix(".json")
            if gt not in seen:
                F.write_json(gt, dict(truth, case=meta))
                seen.add(gt)
        out.append({"file": path, "tier": "04_adversarial_fraud", "category": "custom", "region": meta["region"],
                    "doc_type": doc_type, "label": label, "case_id": cid, "expected_result": expected,
                    "expected_findings": ";".join(meta["expected_findings"]), "ground_truth": folder / "case.json",
                    "notes": meta["description"]})
    return out
