"""Bank statements (PDF) plus the same data as MT940, CAMT.053 and OFX.

Banks are fictional; identifiers (IBAN, sort code, ABA, IFSC, BSB, NZ account)
follow the real formats and check rules. Opening balances are spread across the
proof-of-funds balance buckets (< £50K ... £10M+) so every bucket is covered.
"""

from __future__ import annotations

import random
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from . import checksums as ck
from . import people as P
from . import render as R
from .render import esc

# GBP-equivalent opening balances, one per bucket 0..8 (fixed synthetic FX below)
BUCKET_GBP = [32_000, 76_000, 185_000, 410_000, 820_000, 1_850_000, 3_600_000, 7_200_000, 14_500_000]
FX_PER_GBP = {"GBP": 1.0, "AED": 4.85, "USD": 1.32, "PKR": 370.0, "INR": 112.0, "BDT": 160.0,
              "AUD": 2.0, "NZD": 2.2, "EUR": 1.17}


def bucket_of_gbp(gbp: float) -> int:
    edges = [50e3, 100e3, 250e3, 500e3, 1e6, 2.5e6, 5e6, 10e6]
    return sum(gbp >= e for e in edges)


# --- number / currency formatting ---------------------------------------------


def fmt_num(x: float, style: str) -> str:
    neg = x < 0
    whole, frac = f"{abs(x):.2f}".split(".")
    if style == "lakh":  # 12,34,567.89
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole_s = ",".join(groups + [tail]) if groups else tail
        out = f"{whole_s}.{frac}"
    else:
        g = f"{int(whole):,}"
        out = {"en": f"{g}.{frac}", "de": f"{g.replace(',', '.')},{frac}",
               "fr": f"{g.replace(',', ' ')},{frac}"}[style]
    return f"-{out}" if neg else out


@dataclass
class Bank:
    code: str
    region: str
    name: str
    address: str
    currency: str
    num_style: str
    date_style: str  # dmy | mdy | dmy_dot | d_mon_y
    symbols: list[str]  # templates with {n}
    labels: dict
    colour: tuple
    bic: str


_EN = {"title": "Account Statement", "date": "Date", "desc": "Description", "debit": "Debit",
       "credit": "Credit", "balance": "Balance", "opening": "Opening balance",
       "closing": "Closing balance", "credits": "Total credits", "debits": "Total debits",
       "period": "Statement period", "holder": "Account holder", "page": "Page"}

BANKS = {
    "UAE": Bank("UAE", "UAE", "Al Waha National Bank PJSC", "Al Waha Tower, Sheikh Zayed Road, Dubai, UAE",
                "AED", "en", "dmy", ["AED {n}", "Dh {n}", "{n} د.إ"],
                dict(_EN, title="Account Statement · <span dir='rtl'>كشف حساب</span>"), (0.05, 0.35, 0.3), "AWNBAEAD"),
    "UK": Bank("UK", "UK", "Thameside Bank plc", "1 Riverside Walk, London EC4R 3TT", "GBP", "en", "d_mon_y",
               ["£{n}"], _EN, (0.0, 0.25, 0.45), "THMSGB2L"),
    "US": Bank("US", "US", "Liberty Harbor Bank, N.A.", "200 Harbor Plaza, Wilmington, DE 19801", "USD", "en", "mdy",
               ["${n}"], dict(_EN, debit="Withdrawals", credit="Deposits"), (0.1, 0.2, 0.4), "LHBKUS33"),
    "PK": Bank("PK", "PK", "Indus Valley Bank Limited", "IVB House, I.I. Chundrigar Road, Karachi", "PKR", "en", "dmy",
               ["PKR {n}", "Rs. {n}"], _EN, (0.0, 0.4, 0.2), "INVBPKKA"),
    "IN": Bank("IN", "IN", "Deccan Commercial Bank Ltd", "DCB Bhavan, Nariman Point, Mumbai 400021", "INR", "lakh", "dmy",
               ["₹{n}", "INR {n}"], dict(_EN, desc="Narration", debit="Withdrawal (Dr)", credit="Deposit (Cr)"),
               (0.45, 0.15, 0.1), "DECBINBB"),
    "BD": Bank("BD", "BD", "Padma Trust Bank PLC", "Padma Tower, Motijheel C/A, Dhaka 1000", "BDT", "lakh", "dmy",
               ["৳{n}", "Tk {n}"], dict(_EN, title="Statement of Account · হিসাব বিবরণী"), (0.0, 0.4, 0.3), "PDTBBDDH"),
    "AU": Bank("AU", "AU", "Southern Cross Savings Bank Ltd", "100 Collins Street, Melbourne VIC 3000", "AUD", "en", "d_mon_y",
               ["${n}", "A${n}"], _EN, (0.85, 0.55, 0.0), "SCSBAU2S"),
    "NZ": Bank("NZ", "NZ", "Tasman Harbour Bank Ltd", "50 Customhouse Quay, Wellington 6011", "NZD", "en", "dmy",
               ["${n}", "NZ${n}"], _EN, (0.1, 0.1, 0.35), "TSHBNZ22"),
    "DE": Bank("DE", "EU", "Rheinland Handelsbank AG", "Königsallee 10, 40212 Düsseldorf", "EUR", "de", "dmy_dot",
               ["{n} €"], {"title": "Kontoauszug", "date": "Datum", "desc": "Buchungstext", "debit": "Soll",
                           "credit": "Haben", "balance": "Saldo", "opening": "Alter Kontostand",
                           "closing": "Neuer Kontostand", "credits": "Summe Haben", "debits": "Summe Soll",
                           "period": "Zeitraum", "holder": "Kontoinhaber", "page": "Seite"},
               (0.0, 0.3, 0.5), "RHHBDEDD"),
    "FR": Bank("FR", "EU", "Banque du Val de Loire", "12 rue Royale, 45000 Orléans", "EUR", "fr", "dmy",
               ["{n} €"], {"title": "Relevé de compte", "date": "Date", "desc": "Libellé", "debit": "Débit",
                           "credit": "Crédit", "balance": "Solde", "opening": "Solde précédent",
                           "closing": "Nouveau solde", "credits": "Total crédits", "debits": "Total débits",
                           "period": "Période", "holder": "Titulaire", "page": "Page"},
               (0.4, 0.1, 0.3), "BVDLFRPP"),
    "NL": Bank("NL", "EU", "Lage Landen Bank N.V.", "Herengracht 500, 1017 CB Amsterdam", "EUR", "de", "dmy",
               ["€ {n}"], {"title": "Rekeningafschrift", "date": "Datum", "desc": "Omschrijving", "debit": "Af",
                           "credit": "Bij", "balance": "Saldo", "opening": "Beginsaldo", "closing": "Eindsaldo",
                           "credits": "Totaal bij", "debits": "Totaal af", "period": "Periode",
                           "holder": "Rekeninghouder", "page": "Pagina"},
               (0.9, 0.45, 0.0), "LLBKNL2A"),
}

PERSON_REGION_FOR_BANK = {"DE": "DE", "FR": "FR", "NL": "NL"}

_MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def fmt_date(d: date, style: str) -> str:
    return {"dmy": f"{d.day:02d}/{d.month:02d}/{d.year}", "mdy": f"{d.month:02d}/{d.day:02d}/{d.year}",
            "dmy_dot": f"{d.day:02d}.{d.month:02d}.{d.year}",
            "d_mon_y": f"{d.day:02d} {_MON[d.month - 1]} {d.year}"}[style]


# --- account identifiers -------------------------------------------------------


def make_account(bank: Bank, rng: random.Random) -> dict:
    d = lambda n: P.digits(rng, n)  # noqa: E731
    c = bank.code
    if c == "UAE":
        iban = ck.iban_build("AE", "097" + d(16))
        return {"iban": iban, "account_number": iban[7:]}
    if c == "UK":
        sort, acct = d(6), d(8)
        return {"sort_code": f"{sort[:2]}-{sort[2:4]}-{sort[4:]}", "account_number": acct,
                "iban": ck.iban_build("GB", "THMS" + sort + acct)}
    if c == "US":
        first8 = "0" + rng.choice("12") + d(6)
        return {"routing_number": first8 + ck.aba_check_digit(first8), "account_number": d(rng.choice([10, 12]))}
    if c == "PK":
        iban = ck.iban_build("PK", "INVB" + d(16))
        return {"iban": iban, "account_number": iban[8:]}
    if c == "IN":
        return {"ifsc": "DECB0" + d(6), "account_number": d(rng.choice([11, 12, 14]))}
    if c == "BD":
        return {"routing_number": d(9), "account_number": d(13)}
    if c == "AU":
        bsb = d(6)
        return {"bsb": f"{bsb[:3]}-{bsb[3:]}", "account_number": d(rng.choice([6, 8, 9]))}
    if c == "NZ":
        return {"account_number": f"{d(2)}-{d(4)}-{d(7)}-{d(2)}"}
    if c == "DE":
        iban = ck.iban_build("DE", "37040044" + d(10))
        return {"iban": iban, "account_number": iban[12:]}
    if c == "FR":
        bank_c, branch, acct = "30004", d(5), d(11)
        rib = 97 - (89 * int(bank_c) + 15 * int(branch) + 3 * int(acct)) % 97
        iban = ck.iban_build("FR", f"{bank_c}{branch}{acct}{rib:02d}")
        return {"iban": iban, "account_number": acct, "rib_key": f"{rib:02d}"}
    if c == "NL":
        iban = ck.iban_build("NL", "LLBK" + d(10))
        return {"iban": iban, "account_number": iban[8:]}
    raise ValueError(c)


_ID_LABEL = {"iban": "IBAN", "sort_code": "Sort Code", "account_number": "Account No.",
             "routing_number": "Routing No. (ABA)", "ifsc": "IFSC", "bsb": "BSB", "rib_key": "Clé RIB"}


# --- transactions ----------------------------------------------------------------

_PERSONAL = {
    "salary": ["SALARY {employer}", "PAYROLL {employer}"],
    "rent": ["RENT PAYMENT STANDING ORDER", "HOUSING RENT TRANSFER"],
    "utility": ["ELECTRICITY & WATER BILL", "INTERNET & MOBILE BILL", "GAS UTILITY DIRECT DEBIT"],
    "grocery": ["CARD PURCHASE FRESHMART", "CARD PURCHASE CITY GROCERS", "POS DAILY NEEDS STORE"],
    "atm": ["ATM WITHDRAWAL {city}"],
    "shop": ["CARD PURCHASE ONLINE RETAIL", "CARD PURCHASE FUEL STATION", "RESTAURANT {city}"],
    "transfer_in": ["TRANSFER FROM {name}", "INWARD REMITTANCE {name}"],
    "transfer_out": ["TRANSFER TO {name}", "FAMILY SUPPORT {name}"],
    "interest": ["INTEREST CREDIT"],
}
_CORPORATE = {
    "receipt": ["TT RECEIPT {name}", "INWARD SWIFT {name}", "CUSTOMER PAYMENT {name}"],
    "supplier": ["SUPPLIER PAYMENT {name}", "OUTWARD TT {name}"],
    "payroll": ["PAYROLL BATCH"], "charges": ["BANK CHARGES", "LC ISSUANCE COMMISSION"],
    "freight": ["FREIGHT PAYMENT OCEANIC MERIDIAN LINES"], "utility": ["OFFICE RENT", "UTILITIES"],
}


@dataclass
class Txn:
    day: date
    description: str
    amount: float  # +credit / -debit
    balance: float = 0.0
    ref: str = ""


@dataclass
class Statement:
    bank: Bank
    holder: str
    holder_address: str
    account: dict
    start: date
    end: date
    opening: float
    txns: list[Txn]
    statement_no: str
    symbol_template: str
    corporate: bool = False
    bucket: int = 0
    # rendered values; fraud cases edit these without touching txns
    closing_override: float | None = None
    summary_override: dict = field(default_factory=dict)
    row_styles: dict = field(default_factory=dict)  # txn index -> number style (tamper cases)
    issued: date | None = None

    @property
    def closing(self) -> float:
        return round(self.opening + sum(t.amount for t in self.txns), 2)

    def recompute_balances(self) -> None:
        bal = self.opening
        for t in self.txns:
            bal = round(bal + t.amount, 2)
            t.balance = bal

    def money(self, x: float) -> str:
        return self.symbol_template.format(n=fmt_num(x, self.bank.num_style))

    def truth(self) -> dict:
        return {
            "bank": self.bank.name, "bic": self.bank.bic, "country": self.bank.code, "region": self.bank.region,
            "currency": self.bank.currency, "holder": self.holder, "holder_address": self.holder_address,
            "account": self.account, "statement_no": self.statement_no,
            "period_start": self.start.isoformat(), "period_end": self.end.isoformat(),
            "opening_balance": self.opening, "closing_balance": self.closing,
            "closing_balance_gbp": round(self.closing / FX_PER_GBP[self.bank.currency], 2),
            "balance_bucket": bucket_of_gbp(self.closing / FX_PER_GBP[self.bank.currency]),
            "number_style": self.bank.num_style, "date_style": self.bank.date_style,
            "currency_display": self.symbol_template,
            "transactions": [{"date": t.day.isoformat(), "description": t.description, "amount": t.amount,
                              "balance": t.balance, "ref": t.ref} for t in self.txns],
        }


def _scale(bank: Bank, gbp: float, rng: random.Random, jitter: float = 0.25) -> float:
    v = gbp * FX_PER_GBP[bank.currency] * rng.uniform(1 - jitter, 1 + jitter)
    return round(v, 2) if v < 1000 else round(v, 0)


def make_statement(bank: Bank, holder: str, address: str, rng: random.Random, as_of: date,
                   bucket: int, months: int = 3, corporate: bool = False,
                   counterparties: list[str] | None = None) -> Statement:
    end = as_of.replace(day=1) - timedelta(days=1)
    start = end
    for _ in range(months - 1):
        start = start.replace(day=1) - timedelta(days=1)
    start = start.replace(day=1)
    opening_gbp = BUCKET_GBP[bucket] * rng.uniform(0.9, 1.1)
    opening = round(opening_gbp * FX_PER_GBP[bank.currency], 2)
    names = counterparties or ["A. RAHMAN", "J. SMITH", "M. KHAN", "S. PATEL", "L. MARTIN", "K. NGUYEN"]
    city = bank.address.split(",")[-1].strip().split(" ")[0].upper()
    income_gbp = max(2500.0, BUCKET_GBP[bucket] * 0.02)
    txns: list[Txn] = []
    m = start
    while m <= end:
        mdays = ((m.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)).day
        day = lambda lo, hi: m.replace(day=rng.randint(lo, min(hi, mdays)))  # noqa: E731
        plan: list[tuple[date, str, float]] = []
        if corporate:
            for _ in range(rng.randint(3, 6)):
                plan.append((day(1, 28), rng.choice(_CORPORATE["receipt"]).format(name=rng.choice(names)),
                             _scale(bank, income_gbp * 1.5, rng, 0.6)))
            for _ in range(rng.randint(2, 4)):
                plan.append((day(1, 28), rng.choice(_CORPORATE["supplier"]).format(name=rng.choice(names)),
                             -_scale(bank, income_gbp * 1.1, rng, 0.6)))
            plan.append((day(25, 28), "PAYROLL BATCH", -_scale(bank, income_gbp * 0.6, rng)))
            plan.append((day(1, 5), rng.choice(_CORPORATE["utility"]), -_scale(bank, income_gbp * 0.05, rng)))
            plan.append((day(10, 20), rng.choice(_CORPORATE["freight"]), -_scale(bank, income_gbp * 0.08, rng)))
            plan.append((day(28, 31), rng.choice(_CORPORATE["charges"]), -_scale(bank, 45, rng, 0.5)))
        else:
            plan.append((day(25, 28), rng.choice(_PERSONAL["salary"]).format(employer=rng.choice(
                ["GLOBAL TRADING LLC", "NORTHWIND LTD", "HORIZON SERVICES", "APEX HOLDINGS"])),
                _scale(bank, income_gbp, rng, 0.02)))
            plan.append((day(1, 3), rng.choice(_PERSONAL["rent"]), -_scale(bank, income_gbp * 0.3, rng, 0.02)))
            for _ in range(2):
                plan.append((day(5, 15), rng.choice(_PERSONAL["utility"]), -_scale(bank, 90, rng)))
            for _ in range(rng.randint(4, 7)):
                plan.append((day(1, 31), rng.choice(_PERSONAL["grocery"]), -_scale(bank, 60, rng, 0.6)))
            for _ in range(rng.randint(2, 4)):
                plan.append((day(1, 31), rng.choice(_PERSONAL["shop"]).format(city=city), -_scale(bank, 45, rng, 0.7)))
            plan.append((day(1, 31), _PERSONAL["atm"][0].format(city=city), -_scale(bank, 200, rng, 0)))
            if rng.random() < 0.6:
                plan.append((day(1, 31), rng.choice(_PERSONAL["transfer_in"]).format(name=rng.choice(names)),
                             _scale(bank, 400, rng, 0.6)))
            if rng.random() < 0.5:
                plan.append((day(1, 31), rng.choice(_PERSONAL["transfer_out"]).format(name=rng.choice(names)),
                             -_scale(bank, 300, rng, 0.6)))
            plan.append((day(mdays, mdays), "INTEREST CREDIT", round(opening * 0.0004, 2)))
        for d_, desc, amt in plan:
            txns.append(Txn(d_, desc, amt, ref=P.letters(rng, 2) + P.digits(rng, 8)))
        m = (m.replace(day=28) + timedelta(days=4)).replace(day=1)
    txns.sort(key=lambda t: (t.day, t.ref))
    st = Statement(bank, holder, address, make_account(bank, rng), start, end, opening, txns,
                   f"{end.year}{end.month:02d}-{P.digits(rng, 4)}", rng.choice(bank.symbols),
                   corporate, bucket, issued=end + timedelta(days=rng.randint(1, 4)))
    st.recompute_balances()
    return st


# --- PDF rendering ----------------------------------------------------------------

A4 = (595.0, 842.0)
FIRST_PAGE_ROWS, PAGE_ROWS = 30, 44


def _pages(txns: list) -> list[list]:
    pages, rest = [txns[:FIRST_PAGE_ROWS]], txns[FIRST_PAGE_ROWS:]
    while rest:
        pages.append(rest[:PAGE_ROWS])
        rest = rest[PAGE_ROWS:]
    return pages


def render_statement(st: Statement, path: Path, metadata: dict | None = None) -> None:
    b, L = st.bank, st.bank.labels
    pdf = R.new_doc()
    pages = _pages(st.txns)
    n_pages = len(pages)
    hexcol = "#%02x%02x%02x" % tuple(int(v * 255) for v in b.colour)
    credits = sum(t.amount for t in st.txns if t.amount > 0)
    debits = -sum(t.amount for t in st.txns if t.amount < 0)
    summary = {"opening": st.opening, "credits": credits, "debits": debits,
               "closing": st.closing_override if st.closing_override is not None else st.closing}
    summary.update(st.summary_override)
    fd = lambda d: fmt_date(d, b.date_style)  # noqa: E731
    for pi in range(n_pages):
        pg = R.Page(pdf, *A4)
        pg.rect((0, 0, A4[0], 8), fill=b.colour)
        pg.html((36, 22, 330, 50), f"<b>{esc(b.name)}</b>", size=17, color=hexcol)
        pg.text((36, 48, 330, 62), b.address, size=8, color="#555")
        pg.html((340, 22, 560, 60), f"<b>{L['title']}</b>", size=13, align="right")
        pg.text((340, 44, 560, 60), f"No. {st.statement_no}", size=8, align="right", color="#555")
        y = 80
        if pi == 0:
            pg.html((36, y, 300, y + 70),
                    f"<span class='lbl'>{L['holder']}</span><br><b>{esc(st.holder)}</b><br>{esc(st.holder_address)}",
                    size=9)
            ids = "".join(
                f"<tr><td class='lbl'>{_ID_LABEL[k]}</td><td>{esc(ck.iban_format(v) if k == 'iban' else v)}</td></tr>"
                for k, v in st.account.items())
            ids += (f"<tr><td class='lbl'>BIC/SWIFT</td><td>{b.bic}</td></tr>"
                    f"<tr><td class='lbl'>{L['period']}</td><td>{fd(st.start)} – {fd(st.end)}</td></tr>"
                    f"<tr><td class='lbl'>Currency</td><td>{b.currency}</td></tr>")
            pg.rect((318, y - 4, 560, y + 86), color=(0.7, 0.7, 0.7), fill=(0.97, 0.97, 0.97))
            pg.html((324, y, 556, y + 84), f"<table>{ids}</table>", size=8)
            y += 96
            rows = "".join(f"<td style='width:25%'><span class='lbl'>{L[k]}</span><br><b>{esc(st.money(summary[k]))}</b></td>"
                           for k in ("opening", "credits", "debits", "closing"))
            pg.rect((36, y - 4, 560, y + 34), color=b.colour, width=0.8)
            pg.html((42, y, 556, y + 32), f"<table><tr>{rows}</tr></table>", size=9)
            y += 48
        chunk = pages[pi]
        head = (f"<tr><th>{L['date']}</th><th>{L['desc']}</th><th class='num'>{L['debit']}</th>"
                f"<th class='num'>{L['credit']}</th><th class='num'>{L['balance']}</th></tr>")
        body = ""
        if pi == 0:
            body += f"<tr><td>{fd(st.start)}</td><td>{L['opening'].upper()}</td><td></td><td></td><td class='num'>{fmt_num(st.opening, b.num_style)}</td></tr>"
        offset = sum(len(c) for c in pages[:pi])
        for k, t in enumerate(chunk):
            ns = st.row_styles.get(offset + k, b.num_style)
            dr = fmt_num(-t.amount, ns) if t.amount < 0 else ""
            cr = fmt_num(t.amount, ns) if t.amount > 0 else ""
            body += (f"<tr><td>{fd(t.day)}</td><td>{esc(t.description)}</td><td class='num'>{dr}</td>"
                     f"<td class='num'>{cr}</td><td class='num'>{fmt_num(t.balance, ns)}</td></tr>")
        if pi == n_pages - 1:
            body += f"<tr><td>{fd(st.end)}</td><td><b>{L['closing'].upper()}</b></td><td></td><td></td><td class='num'><b>{fmt_num(summary['closing'], b.num_style)}</b></td></tr>"
        pg.html((36, y, 560, 800), f"<table>{head}{body}</table>", size=8)
        pg.line((36, 806), (560, 806), color=(0.7, 0.7, 0.7))
        pg.text((36, 809, 400, 822), f"{b.name} · Synthetic test bank · BIC {b.bic}", size=6.5, color="#777")
        pg.text((400, 809, 560, 822), f"{L['page']} {pi + 1} / {n_pages}", size=6.5, color="#777", align="right")
        pg.specimen()
    R.save(pdf, path, metadata)


# --- machine-readable formats ------------------------------------------------------


def _mt_amount(x: float) -> str:
    return f"{abs(x):.2f}".replace(".", ",")


def _account_id(st: Statement) -> str:
    a = st.account
    if "iban" in a:
        return a["iban"]
    if "sort_code" in a:
        return a["sort_code"].replace("-", "") + a["account_number"]
    for k in ("routing_number", "ifsc", "bsb"):
        if k in a:
            return f"{a[k].replace('-', '')}/{a['account_number']}"
    return a["account_number"]


def to_mt940(st: Statement) -> str:
    cur = st.bank.currency
    cd = lambda x: "C" if x >= 0 else "D"  # noqa: E731
    closing = st.closing_override if st.closing_override is not None else st.closing
    lines = [f"{{1:F01{st.bank.bic}XXXX0000000000}}{{2:O940{st.bank.bic}XXXXN}}{{4:",
             f":20:{st.statement_no}", f":25:{_account_id(st)}", f":28C:{st.statement_no[-4:]}/1",
             f":60F:{cd(st.opening)}{st.start.strftime('%y%m%d')}{cur}{_mt_amount(st.opening)}"]
    for t in st.txns:
        lines.append(f":61:{t.day.strftime('%y%m%d%m%d')}{cd(t.amount)}{_mt_amount(t.amount)}NTRF{t.ref}//{t.ref[-6:]}")
        lines.append(f":86:{t.description[:65]}")
    lines.append(f":62F:{cd(closing)}{st.end.strftime('%y%m%d')}{cur}{_mt_amount(closing)}")
    lines.append("-}")
    return "\r\n".join(lines) + "\r\n"


def to_camt053(st: Statement) -> bytes:
    ns = "urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"
    ET.register_namespace("", ns)
    q = lambda t: f"{{{ns}}}{t}"  # noqa: E731

    def sub(parent, tag, text=None, **attrs):
        e = ET.SubElement(parent, q(tag), attrs)
        if text is not None:
            e.text = str(text)
        return e

    cur = st.bank.currency
    closing = st.closing_override if st.closing_override is not None else st.closing
    doc = ET.Element(q("Document"))
    root = sub(doc, "BkToCstmrStmt")
    gh = sub(root, "GrpHdr")
    sub(gh, "MsgId", f"MSG{st.statement_no}")
    sub(gh, "CreDtTm", datetime.combine(st.issued or st.end, datetime.min.time()).isoformat())
    s = sub(root, "Stmt")
    sub(s, "Id", st.statement_no)
    sub(s, "CreDtTm", datetime.combine(st.issued or st.end, datetime.min.time()).isoformat())
    ft = sub(s, "FrToDt")
    sub(ft, "FrDtTm", f"{st.start.isoformat()}T00:00:00")
    sub(ft, "ToDtTm", f"{st.end.isoformat()}T23:59:59")
    acct = sub(s, "Acct")
    aid = sub(acct, "Id")
    if "iban" in st.account:
        sub(aid, "IBAN", st.account["iban"])
    else:
        sub(sub(aid, "Othr"), "Id", _account_id(st))
    sub(acct, "Ccy", cur)
    sub(sub(acct, "Ownr"), "Nm", st.holder)
    sub(sub(sub(acct, "Svcr"), "FinInstnId"), "BIC", st.bank.bic)
    for code, amt, d in (("OPBD", st.opening, st.start), ("CLBD", closing, st.end)):
        bal = sub(s, "Bal")
        sub(sub(sub(bal, "Tp"), "CdOrPrtry"), "Cd", code)
        sub(bal, "Amt", f"{abs(amt):.2f}", Ccy=cur)
        sub(bal, "CdtDbtInd", "CRDT" if amt >= 0 else "DBIT")
        sub(sub(bal, "Dt"), "Dt", d.isoformat())
    for t in st.txns:
        n = sub(s, "Ntry")
        sub(n, "NtryRef", t.ref)
        sub(n, "Amt", f"{abs(t.amount):.2f}", Ccy=cur)
        sub(n, "CdtDbtInd", "CRDT" if t.amount > 0 else "DBIT")
        sub(n, "Sts", "BOOK")
        sub(sub(n, "BookgDt"), "Dt", t.day.isoformat())
        sub(sub(n, "ValDt"), "Dt", t.day.isoformat())
        sub(sub(sub(sub(n, "NtryDtls"), "TxDtls"), "RmtInf"), "Ustrd", t.description)
    ET.indent(doc)
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(doc, encoding="utf-8")


def to_ofx(st: Statement) -> str:
    cur = st.bank.currency
    closing = st.closing_override if st.closing_override is not None else st.closing
    tx = "".join(
        f"<STMTTRN><TRNTYPE>{'CREDIT' if t.amount > 0 else 'DEBIT'}</TRNTYPE>"
        f"<DTPOSTED>{t.day.strftime('%Y%m%d')}</DTPOSTED><TRNAMT>{t.amount:.2f}</TRNAMT>"
        f"<FITID>{t.ref}</FITID><NAME>{esc(t.description[:32])}</NAME></STMTTRN>\n"
        for t in st.txns)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n<?OFX OFXHEADER="200" VERSION="220" '
        'SECURITY="NONE" OLDFILEUID="NONE" NEWFILEUID="NONE"?>\n<OFX><BANKMSGSRSV1><STMTTRNRS>'
        f"<TRNUID>{st.statement_no}</TRNUID><STATUS><CODE>0</CODE><SEVERITY>INFO</SEVERITY></STATUS><STMTRS>"
        f"<CURDEF>{cur}</CURDEF><BANKACCTFROM><BANKID>{esc(st.bank.bic)}</BANKID>"
        f"<ACCTID>{esc(_account_id(st))}</ACCTID><ACCTTYPE>CHECKING</ACCTTYPE></BANKACCTFROM>\n"
        f"<BANKTRANLIST><DTSTART>{st.start.strftime('%Y%m%d')}</DTSTART><DTEND>{st.end.strftime('%Y%m%d')}</DTEND>\n"
        f"{tx}</BANKTRANLIST><LEDGERBAL><BALAMT>{closing:.2f}</BALAMT>"
        f"<DTASOF>{st.end.strftime('%Y%m%d')}</DTASOF></LEDGERBAL></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>\n")


def write_bank_files(st: Statement, base: Path) -> list[Path]:
    """Write <base>.mt940 / .camt053.xml / .ofx next to the PDF."""
    base.parent.mkdir(parents=True, exist_ok=True)
    out = [base.with_suffix(".mt940"), base.with_suffix(".camt053.xml"), base.with_suffix(".ofx")]
    out[0].write_text(to_mt940(st), encoding="utf-8", newline="")
    out[1].write_bytes(to_camt053(st))
    out[2].write_text(to_ofx(st), encoding="utf-8")
    return out
