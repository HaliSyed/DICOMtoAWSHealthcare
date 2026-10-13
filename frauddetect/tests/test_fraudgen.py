"""Self-checks for the generator: genuine documents must pass every real-world
rule, and every planted defect must actually be present. If these fail, the
dataset's ground truth cannot be trusted."""

from __future__ import annotations

import json
import random
import re
import sys
from datetime import date
from pathlib import Path

import pymupdf
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fraudgen import banking as B  # noqa: E402
from fraudgen import checksums as ck  # noqa: E402
from fraudgen import fraud as F  # noqa: E402
from fraudgen import identity as I  # noqa: E402
from fraudgen import people as P  # noqa: E402
from fraudgen import trade as T  # noqa: E402
from fraudgen.mrz import td1, td3  # noqa: E402

AS_OF = date(2026, 10, 13)
cd = ck.icao_check_digit


# --- MRZ validators used by the tests ---------------------------------------------


def td3_ok(l1: str, l2: str) -> bool:
    return (len(l1) == len(l2) == 44 and cd(l2[0:9]) == l2[9] and cd(l2[13:19]) == l2[19]
            and cd(l2[21:27]) == l2[27] and cd(l2[0:10] + l2[13:20] + l2[21:43]) == l2[43])


def td1_ok(l1: str, l2: str, l3: str) -> bool:
    return (len(l1) == len(l2) == len(l3) == 30 and cd(l1[5:14]) == l1[14] and cd(l2[0:6]) == l2[6]
            and cd(l2[8:14]) == l2[14] and cd(l1[5:30] + l2[0:7] + l2[8:15] + l2[18:29]) == l2[29])


# --- reference vectors --------------------------------------------------------------


def test_checksums_match_published_examples():
    assert cd("L898902C3") == "6" and cd("740812") == "2" and cd("120415") == "9"
    assert ck.luhn_check_digit("7992739871") == "3"
    assert ck.verhoeff_check_digit("236") == "3" and ck.verhoeff_valid("2363")
    assert ck.iban_valid("GB82WEST12345698765432") and ck.iban_valid("DE89370400440532013000")
    assert ck.aba_valid("011000015")
    assert ck.iso6346_check_digit("CSQU305438") == "3"
    assert ck.dni_letter(12345678) == "Z"


def test_mrz_matches_icao_specimen():
    assert td3("P", "UTO", "ERIKSSON", "ANNA MARIA", "L898902C3", "UTO", "740812", "F", "120415", "ZE184226B") == [
        "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<", "L898902C36UTO7408122F1204159ZE184226B<<<<<10"]
    assert td1("I", "UTO", "ERIKSSON", "ANNA MARIA", "D23145890", "UTO", "740812", "F", "120415") == [
        "I<UTOD231458907<<<<<<<<<<<<<<<", "7408122F1204159UTO<<<<<<<<<<<6", "ERIKSSON<<ANNA<MARIA<<<<<<<<<<"]


def test_mrz_icao_transliteration():
    assert td1("ID", "D", "Müller-Lüdenscheidt", "Jürgen", "T22000129", "D", "640812", "<", "310101")[2] \
        .startswith("MUELLER<LUEDENSCHEIDT<<JUERGEN")


# --- genuine identity documents ---------------------------------------------------------


def _all_docs(n: int = 4):
    for region in I.REGION_DOCS:
        for v in range(n):
            rng = random.Random(f"t-{region}-{v}")
            p = P.make_person(region, rng, AS_OF, v)
            for d in I.build_region_docs(p, rng, AS_OF):
                yield p, d


def test_genuine_identity_documents_pass_all_rules():
    for p, d in _all_docs():
        t = d.truth
        if len(d.mrz) == 2:
            assert td3_ok(*d.mrz), (d.doc_type, d.mrz)
        elif len(d.mrz) == 3:
            assert td1_ok(*d.mrz), (d.doc_type, d.mrz)
        if t.get("expiry_date"):
            assert date.fromisoformat(t["expiry_date"]) > AS_OF, d.doc_type
        if t.get("issue_date") and t.get("expiry_date"):
            assert t["issue_date"] < t["expiry_date"]
        if d.doc_type == "emirates_id":
            n = t["id_number"].replace("-", "")
            assert ck.luhn_valid(n) and n[3:7] == str(p.dob.year) and n.startswith("784")
        if d.doc_type == "aadhaar":
            n = t["aadhaar_number"]
            assert len(n) == 12 and n[0] in "23456789" and ck.verhoeff_valid(n)
        if d.doc_type == "pan_card":
            assert re.fullmatch(r"[A-Z]{3}P[A-Z]\d{4}[A-Z]", t["pan"])
            assert t["pan"][4] == p.surname.replace("Al ", "")[0].upper()
        if d.doc_type in ("pk_cnic", "pk_nicop"):
            assert re.fullmatch(r"\d{5}-\d{7}-\d", t["id_number"])
            assert (int(t["id_number"][-1]) % 2 == 1) == (p.sex == "M")
        if d.doc_type == "uk_driving_licence":
            n = t["licence_number"]
            month = p.dob.month + (50 if p.sex == "F" else 0)
            assert n[5] + n[10] == f"{p.dob.year % 100:02d}" and n[6:8] == f"{month:02d}" and n[8:10] == f"{p.dob.day:02d}"
        if d.doc_type == "au_medicare":
            n = t["medicare_number"]
            assert ck.medicare_check_digit(n[:8]) == n[8]
        if d.doc_type == "au_driving_licence":
            assert t["card_number"] != t["licence_number"]
        if d.doc_type == "es_dni":
            assert ck.dni_letter(int(t["dni"][:8])) == t["dni"][8]
        if d.doc_type == "bd_paper_nid":
            assert len(t["nid_number"]) == 17 and t["nid_number"][:4] == str(p.dob.year)
        if d.doc_type == "bd_smart_nid":
            assert len(t["nid_number"]) == 10
        if d.doc_type == "us_driving_licence":
            assert "DBB" + p.dob.strftime("%m%d%Y") in d.barcode and d.barcode.startswith("@\n\x1e\rANSI ")
        if d.doc_type == "passport" and p.region == "PK":
            assert d.mrz[1][28:41] == p.extra["cnic"].replace("-", "")


def test_rendered_id_has_searchable_text_and_specimen(tmp_path):
    rng = random.Random(1)
    p = P.make_person("UAE", rng, AS_OF, 0)
    d = I.emirates_id(p, rng, AS_OF)
    path = tmp_path / "eid.pdf"
    I.render_id(d, path, 1)
    with pymupdf.open(str(path)) as doc:
        text = "".join(pg.get_text() for pg in doc)
        assert d.truth["id_number"] in text
        assert p.full_name_native.split()[0] in text  # Arabic survives as real text
        assert all("SPECIMEN" in pg.get_text() for pg in doc)
        assert path.stat().st_size < 400_000  # fonts are subset


# --- bank statements ---------------------------------------------------------------------


def test_bucket_amounts_land_in_their_bucket():
    assert [B.bucket_of_gbp(v) for v in B.BUCKET_GBP] == list(range(9))


def test_number_formats():
    assert B.fmt_num(10234567.891, "lakh") == "1,02,34,567.89"
    assert B.fmt_num(1234.5, "de") == "1.234,50"
    assert B.fmt_num(1234.5, "fr") == "1 234,50"
    assert B.fmt_num(-99.0, "en") == "-99.00"


@pytest.mark.parametrize("code", list(B.BANKS))
def test_genuine_statements_reconcile(code):
    st = B.make_statement(B.BANKS[code], "A HOLDER", "1 Street", random.Random(code), AS_OF, 4)
    a = st.account
    if "iban" in a:
        assert ck.iban_valid(a["iban"])
    if "routing_number" in a and code == "US":
        assert ck.aba_valid(a["routing_number"])
    if "ifsc" in a:
        assert re.fullmatch(r"[A-Z]{4}0\d{6}", a["ifsc"])
    if "sort_code" in a:
        assert a["sort_code"].replace("-", "") in a["iban"]
    if "bsb" in a:
        assert re.fullmatch(r"\d{3}-\d{3}", a["bsb"])
    if code == "NZ":
        assert re.fullmatch(r"\d{2}-\d{4}-\d{7}-\d{2}", a["account_number"])
    bal = st.opening
    for t in st.txns:
        bal = round(bal + t.amount, 2)
        assert abs(bal - t.balance) < 0.005
        assert st.start <= t.day <= st.end
    assert abs(bal - st.closing) < 0.005
    assert st.end < AS_OF
    mt = B.to_mt940(st)
    assert f":62F:C{st.end.strftime('%y%m%d')}{st.bank.currency}{B._mt_amount(st.closing)}" in mt
    camt = B.to_camt053(st).decode()
    assert f"{st.closing:.2f}" in camt and "CLBD" in camt


# --- trade -------------------------------------------------------------------------------


@pytest.mark.parametrize("scenario", list(T.SCENARIOS))
def test_genuine_shipment_is_consistent(scenario):
    sh = T.make_shipment(scenario, random.Random(scenario), AS_OF)
    for c in sh.containers:
        assert ck.iso6346_check_digit(c.number[:10]) == c.number[10]
    assert sh.total <= sh.lc_amount * (1 + sh.lc_tolerance_pct / 100)
    assert sh.lc_issue < sh.invoice_date <= sh.on_board <= sh.latest_shipment < sh.lc_expiry
    assert abs(sum(c.gross_kg for c in sh.containers) - sum(i.gross_kg for i in sh.items)) < 1
    assert f":20:{sh.lc_no}" in T.mt700(sh)


def test_amount_in_words():
    assert T.amount_in_words(155760) == "US DOLLARS ONE HUNDRED FIFTY FIVE THOUSAND SEVEN HUNDRED SIXTY ONLY"


# --- adversarial cases --------------------------------------------------------------------


def test_case_ids_unique():
    ids = [c.case_id for c in F.CASES]
    assert len(ids) == len(set(ids))


SAMPLE = {"ID01", "ID05", "ID08", "ID12", "ID20", "BK01", "BK03", "BK04", "BK05", "TR03", "TR11", "EC03", "EC04"}


@pytest.fixture(scope="module")
def cases(tmp_path_factory):
    root = tmp_path_factory.mktemp("fraud")
    rows = F.run_cases(root, AS_OF, 99, SAMPLE)
    folders = {p.parent.name.split("_")[0]: p.parent for p in root.glob("*/*/case.json")}
    return root, rows, folders


def _gt(folder: Path, name: str) -> dict:
    return json.loads((folder / name).read_text(encoding="utf-8"))


def test_every_case_has_metadata(cases):
    _, rows, folders = cases
    assert set(folders) == SAMPLE
    for cid, folder in folders.items():
        meta = _gt(folder, "case.json")
        assert meta["expected_findings"] and meta["expected_result"] in ("fail", "review", "pass")
    assert all(Path(r["file"]).exists() for r in rows)


def test_planted_identity_defects_present(cases):
    f = cases[2]
    l2 = _gt(f["ID01"], "uae_passport.json")["mrz"][1]
    assert cd(l2[0:9]) != l2[9]
    eid = _gt(f["ID05"], "emirates_id.json")["holder"]["id_number"].replace("-", "")
    assert not ck.luhn_valid(eid)
    a = _gt(f["ID08"], "aadhaar.json")["holder"]["aadhaar_number"]
    assert not ck.verhoeff_valid(a)
    us = _gt(f["ID12"], "us_driving_licence.json")
    assert "DBB" + date.fromisoformat(us["holder"]["dob"]).strftime("%m%d%Y") not in us["pdf417_aamva"]
    with pymupdf.open(str(f["ID20"] / "de_id_card.pdf")) as d:
        assert "Photoshop" in d.metadata["producer"]
    # incremental save: the original revision is still in the file
    assert (f["ID20"] / "de_id_card.pdf").read_bytes().count(b"%%EOF") >= 2


def test_planted_bank_defects_present(cases):
    f = cases[2]
    assert not ck.iban_valid(_gt(f["BK01"], "statement.json")["account"]["iban"])
    t = _gt(f["BK03"], "statement.json")
    bal, broken = t["opening_balance"], False
    for row in t["transactions"]:
        bal = round(bal + row["amount"], 2)
        broken |= abs(bal - row["balance"]) > 0.005
    assert broken
    bk4 = _gt(f["BK04"], "statement.json")
    mt = (f["BK04"] / "statement.mt940").read_text()
    assert bk4["printed_closing_balance"] > bk4["closing_balance"] * 3
    assert B._mt_amount(bk4["closing_balance"]) in mt
    with pymupdf.open(str(f["BK05"] / "statement.pdf")) as d:
        assert d.metadata["producer"].startswith("Adobe Photoshop")


def test_planted_trade_defects_present(cases):
    f = cases[2]
    bl = _gt(f["TR03"], "IN_to_UK_bill_of_lading.json")
    bad = bl["document_overrides"]["bl"]["containers"][0]["number"]
    assert ck.iso6346_check_digit(bad[:10]) != bad[10]
    inv = _gt(f["TR11"], "AU_to_UAE_commercial_invoice.json")
    stmt = _gt(f["TR11"], "seller_statement.json")
    assert inv["document_overrides"]["invoice"]["seller_account"]["account_number"] != stmt["account"]["account_number"]


def test_edge_cases_render_as_intended(cases):
    f = cases[2]
    for name in ("statement_us.pdf", "statement_uk.pdf"):
        with pymupdf.open(str(f["EC03"] / name)) as d:
            assert "04/05/2026" in "".join(p.get_text() for p in d)
    de = _gt(f["EC04"], "de_id_card.json")
    assert de["mrz"][2].startswith("MUELLER<LUEDENSCHEIDT<<JUERGEN")
    assert de["printed_fields"]["surname"] == "MÜLLER-LÜDENSCHEIDT"


# --- custom cases (examples/custom_cases_uae.json) -----------------------------------------

from fraudgen import custom as C  # noqa: E402
from fraudgen.mrz import break_check_digit, retouch  # noqa: E402

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "custom_cases_uae.json"


def test_mrz_retouch_keeps_check_digits_valid():
    a = td3("P", "UTO", "ERIKSSON", "ANNA MARIA", "L898902C3", "UTO", "740812", "F", "120415", "ZE184226B")
    assert retouch(a, dob="800101") == td3("P", "UTO", "ERIKSSON", "ANNA MARIA", "L898902C3", "UTO", "800101", "F",
                                            "120415", "ZE184226B")
    b = td1("I", "UTO", "ERIKSSON", "ANNA MARIA", "D23145890", "UTO", "740812", "F", "120415")
    assert td1_ok(*retouch(b, number="X12345678", expiry="300101"))
    assert not td3_ok(*break_check_digit(a, "dob"))


@pytest.fixture(scope="module")
def custom(tmp_path_factory):
    root = tmp_path_factory.mktemp("custom")
    rows = C.run_custom(EXAMPLE, root, AS_OF, 99)
    folders = {p.parent.name.split("_")[0]: p.parent for p in root.glob("custom/*/case.json")}
    return rows, folders


def test_example_spec_produces_every_case(custom):
    rows, folders = custom
    assert set(folders) == {f"CU{i:02d}" for i in range(1, 11)}
    assert all(Path(r["file"]).exists() for r in rows)


def test_custom_mutations_land(custom):
    f = custom[1]
    cu01 = _gt(f["CU01"], "passport_1.json")
    assert cu01["holder"]["expiry_date"] < AS_OF.isoformat()
    assert cd(cu01["mrz"][1][0:9]) != cu01["mrz"][1][9]
    assert cd(cu01["mrz"][1][21:27]) == cu01["mrz"][1][27]  # expiry change kept the MRZ consistent
    cu02 = _gt(f["CU02"], "emirates_id_1.json")
    assert AS_OF.year - int(cu02["holder"]["dob"][:4]) == 16 and td1_ok(*cu02["mrz"])
    cu03 = _gt(f["CU03"], "passport.json")
    assert cu03["holder"]["dob"] == "1986-07-02" and td3_ok(*cu03["mrz"]) and cu03["mrz"][1][13:19] == "860702"
    cu05 = _gt(f["CU05"], "statement.json")
    assert cu05["printed_closing_balance"] > cu05["closing_balance"] * 2 and cu05["tampers"]
    cu07 = _gt(f["CU07"], "passport_1.json")
    assert "MOHAMED" in cu07["mrz"][0] and td3_ok(*cu07["mrz"])
    assert not ck.verhoeff_valid(_gt(f["CU09"], "aadhaar_1.json")["holder"]["aadhaar_number"])
    assert _gt(f["CU09"], "pan_card_2.json")["holder"]["pan"][3] == "C"


def test_bad_spec_names_the_problem(tmp_path):
    spec = tmp_path / "bad.json"
    spec.write_text('{"cases":[{"id":"X","person":{"region":"UAE"},"documents":[{"type":"emirates_id",'
                    '"mutations":[{"op":"explode"}]}]}]}', encoding="utf-8")
    with pytest.raises(C.SpecError, match="case X document 1 mutation 1: unknown identity op"):
        C.run_custom(spec, tmp_path, AS_OF, 1)
