"""Trade documents for one shipment: commercial invoice, packing list, bill of
lading and letter of credit (PDF + MT700 text + UN/CEFACT CII XML).

All parties, banks, carrier and vessels are fictional. Ports use real UN/LOCODEs
and container numbers carry valid ISO 6346 check digits.
"""

from __future__ import annotations

import copy
import dataclasses
import random
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from . import banking as B
from . import people as P
from . import render as R
from .render import esc


@dataclass
class Party:
    name: str
    address: str
    country: str  # ISO2


@dataclass
class Item:
    description: str
    hs_code: str
    quantity: float
    unit: str
    unit_price: float
    packages: int
    net_kg: float
    gross_kg: float
    cbm: float

    @property
    def amount(self) -> float:
        return round(self.quantity * self.unit_price, 2)


@dataclass
class Container:
    number: str
    seal: str
    size_type: str
    packages: int
    gross_kg: float
    cbm: float


@dataclass
class Shipment:
    scenario: str
    seller: Party
    buyer: Party
    notify: Party
    issuing_bank: str
    advising_bank: str
    seller_bank_code: str  # key into banking.BANKS
    items: list[Item]
    currency: str
    incoterm: str
    pol: tuple[str, str]  # (UN/LOCODE, name)
    pod: tuple[str, str]
    vessel: str
    voyage: str
    invoice_no: str
    invoice_date: date
    lc_no: str
    lc_issue: date
    lc_amount: float
    lc_tolerance_pct: int
    latest_shipment: date
    lc_expiry: date
    bl_no: str
    on_board: date
    containers: list[Container]
    seller_account: dict = field(default_factory=dict)
    # Values printed on individual documents; fraud cases change these per document.
    overrides: dict = field(default_factory=lambda: {"invoice": {}, "packing": {}, "bl": {}, "lc": {}})

    @property
    def total(self) -> float:
        return round(sum(i.amount for i in self.items), 2)

    def v(self, doc: str, key: str, default):
        return self.overrides[doc].get(key, default)

    def truth(self) -> dict:
        return {
            "scenario": self.scenario,
            "seller": vars(self.seller), "buyer": vars(self.buyer), "notify_party": vars(self.notify),
            "issuing_bank": self.issuing_bank, "advising_bank": self.advising_bank,
            "currency": self.currency, "incoterm": self.incoterm,
            "port_of_loading": {"locode": self.pol[0], "name": self.pol[1]},
            "port_of_discharge": {"locode": self.pod[0], "name": self.pod[1]},
            "vessel": self.vessel, "voyage": self.voyage,
            "invoice_no": self.invoice_no, "invoice_date": self.invoice_date.isoformat(),
            "invoice_total": self.total,
            "lc_no": self.lc_no, "lc_issue": self.lc_issue.isoformat(), "lc_amount": self.lc_amount,
            "lc_tolerance_pct": self.lc_tolerance_pct, "latest_shipment": self.latest_shipment.isoformat(),
            "lc_expiry": self.lc_expiry.isoformat(), "bl_no": self.bl_no, "on_board": self.on_board.isoformat(),
            "items": [dict(vars(i), amount=i.amount) for i in self.items],
            "containers": [vars(c) for c in self.containers],
            "gross_kg_total": round(sum(i.gross_kg for i in self.items), 1),
            "seller_payment_account": self.seller_account,
            "document_overrides": _plain(self.overrides),
        }


def _plain(obj):
    """JSON-ready copy: dataclasses -> dicts, dates -> ISO strings, int keys -> str."""
    if dataclasses.is_dataclass(obj):
        d = {k: _plain(v) for k, v in vars(obj).items()}
        if isinstance(obj, Item):
            d["amount"] = obj.amount
        return d
    if isinstance(obj, dict):
        return {str(k): _plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_plain(v) for v in obj]
    if isinstance(obj, date):
        return obj.isoformat()
    return obj


SCENARIOS = {
    "UAE_to_PK": dict(
        seller=Party("Al Noor General Trading LLC", "Office 1204, Jebel Ali Free Zone, Dubai, UAE", "AE"),
        buyer=Party("Karachi Polymer Industries (Pvt) Ltd", "Plot 45, Sector 7-A, Korangi Industrial Area, Karachi", "PK"),
        issuing_bank="Indus Valley Bank Limited, Karachi", advising_bank="Al Waha National Bank PJSC, Dubai",
        seller_bank_code="UAE", pol=("AEJEA", "Jebel Ali, UAE"), pod=("PKKHI", "Karachi, Pakistan"),
        incoterm="CFR Karachi", goods=[("LLDPE granules, film grade", "3901.40", "MT", 1150, 25),
                                       ("HDPE granules, blow moulding grade", "3901.20", "MT", 1240, 25)]),
    "IN_to_UK": dict(
        seller=Party("Coromandel Cotton Exports Pvt Ltd", "SF No. 112, Avinashi Road, Tiruppur 641603, India", "IN"),
        buyer=Party("Pennine Home Textiles Ltd", "Unit 9, Trafford Park, Manchester M17 1AB, UK", "GB"),
        issuing_bank="Thameside Bank plc, London", advising_bank="Deccan Commercial Bank Ltd, Mumbai",
        seller_bank_code="IN", pol=("INNSA", "Nhava Sheva, India"), pod=("GBFXT", "Felixstowe, UK"),
        incoterm="CIF Felixstowe", goods=[("100% cotton bed linen sets, printed", "6302.31", "SET", 14.5, 1),
                                          ("Cotton terry towels, 500 GSM", "6302.60", "PCS", 2.9, 1)]),
    "BD_to_DE": dict(
        seller=Party("Meghna Knit Composite Ltd", "Plot 18, BSCIC Industrial Estate, Gazipur 1700, Bangladesh", "BD"),
        buyer=Party("Hanse Mode Import GmbH", "Spaldingstraße 64, 20097 Hamburg, Germany", "DE"),
        issuing_bank="Rheinland Handelsbank AG, Düsseldorf", advising_bank="Padma Trust Bank PLC, Dhaka",
        seller_bank_code="BD", pol=("BDCGP", "Chattogram, Bangladesh"), pod=("DEHAM", "Hamburg, Germany"),
        incoterm="FOB Chattogram", goods=[("Men's knitted cotton T-shirts", "6109.10", "PCS", 2.35, 1),
                                          ("Men's knitted cotton polo shirts", "6105.10", "PCS", 4.1, 1)]),
    "AU_to_UAE": dict(
        seller=Party("Murray Basin Agri Exports Pty Ltd", "22 Wharf Road, Port Melbourne VIC 3207, Australia", "AU"),
        buyer=Party("Gulf Fresh Foods Trading LLC", "Warehouse 7, Al Quoz Industrial 3, Dubai, UAE", "AE"),
        issuing_bank="Al Waha National Bank PJSC, Dubai", advising_bank="Southern Cross Savings Bank Ltd, Melbourne",
        seller_bank_code="AU", pol=("AUMEL", "Melbourne, Australia"), pod=("AEJEA", "Jebel Ali, UAE"),
        incoterm="CFR Jebel Ali", goods=[("Frozen boneless beef, 90CL", "0202.30", "KG", 7.8, 27),
                                          ("Frozen lamb shoulder cuts", "0204.43", "KG", 9.4, 25)]),
}

VESSELS = ["MERIDIAN PEARL", "MERIDIAN HORIZON", "OCEANIC DAWN", "OCEANIC TRIDENT"]


def make_shipment(key: str, rng: random.Random, as_of: date, seq: int = 1) -> Shipment:
    sc = SCENARIOS[key]
    items, containers = [], []
    for desc, hs, unit, price, kg_per_unit_pkg in sc["goods"]:
        if unit == "MT":
            qty = float(rng.choice([44, 66, 88, 110]))
            pkgs = int(qty * 1000 / 25)
            net = qty * 1000
        elif unit == "KG":
            qty = float(rng.choice([24000, 26000, 52000]))
            pkgs = int(qty / kg_per_unit_pkg)
            net = qty
        else:
            qty = float(rng.choice([6000, 8400, 12000, 18000]))
            pkgs = int(qty / rng.choice([24, 36, 50]))
            net = qty * rng.uniform(0.18, 0.9)
        gross = round(net * 1.04, 1)
        cbm = round(gross / rng.uniform(380, 620), 2)
        items.append(Item(desc, hs, qty, unit, price, pkgs, round(net, 1), gross, cbm))
    total_gross = sum(i.gross_kg for i in items)
    n_cont = max(1, round(total_gross / 24000))
    for k in range(n_cont):
        containers.append(Container(P.container_number(rng), "SL" + P.digits(rng, 7),
                                    "40RF" if "Frozen" in items[0].description else "40HC",
                                    sum(i.packages for i in items) // n_cont,
                                    round(total_gross / n_cont, 1),
                                    round(sum(i.cbm for i in items) / n_cont, 2)))
    lc_issue = as_of - timedelta(days=rng.randint(70, 90))
    latest = as_of - timedelta(days=rng.randint(8, 15))
    on_board = latest - timedelta(days=rng.randint(3, 12))
    inv_date = on_board - timedelta(days=rng.randint(1, 4))
    total = round(sum(i.amount for i in items), 2)
    sh = Shipment(
        key, sc["seller"], sc["buyer"], copy.deepcopy(sc["buyer"]), sc["issuing_bank"], sc["advising_bank"],
        sc["seller_bank_code"], items, "USD", sc["incoterm"], sc["pol"], sc["pod"],
        rng.choice(VESSELS), f"{rng.randint(100, 499)}{rng.choice('EWNS')}",
        f"INV-{as_of.year}-{seq:03d}{P.digits(rng, 3)}", inv_date,
        f"LC{P.letters(rng, 2)}{P.digits(rng, 8)}", lc_issue,
        round(total * 1.05, -2), 5, latest, latest + timedelta(days=21),
        f"OMLU{P.letters(rng, 3)}{P.digits(rng, 7)}", on_board, containers)
    return sh


# --- helpers ---------------------------------------------------------------------

_ONES = ["", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE", "TEN", "ELEVEN",
         "TWELVE", "THIRTEEN", "FOURTEEN", "FIFTEEN", "SIXTEEN", "SEVENTEEN", "EIGHTEEN", "NINETEEN"]
_TENS = ["", "", "TWENTY", "THIRTY", "FORTY", "FIFTY", "SIXTY", "SEVENTY", "EIGHTY", "NINETY"]


def _words(n: int) -> str:
    if n < 20:
        return _ONES[n]
    if n < 100:
        return (_TENS[n // 10] + " " + _ONES[n % 10]).strip()
    if n < 1000:
        return (_ONES[n // 100] + " HUNDRED " + _words(n % 100)).strip()
    for div, name in ((10**9, "BILLION"), (10**6, "MILLION"), (1000, "THOUSAND")):
        if n >= div:
            return (_words(n // div) + f" {name} " + _words(n % div)).strip()
    return ""


def amount_in_words(x: float, cur: str = "US DOLLARS") -> str:
    whole, cents = int(x), round((x - int(x)) * 100)
    return f"{cur} {_words(whole)} AND CENTS {cents:02d}/100 ONLY" if cents else f"{cur} {_words(whole)} ONLY"


def money(x: float) -> str:
    return f"{x:,.2f}"


def fd(d: date) -> str:
    return d.strftime("%d %b %Y").upper()


def _box(pg: R.Page, rect, title: str, body_html: str, size: float = 8) -> None:
    pg.rect(rect, color=(0.4, 0.4, 0.4), width=0.6)
    x0, y0, x1, y1 = rect
    pg.html((x0 + 4, y0 + 2, x1 - 4, y0 + 12), f"<span class='lbl'>{esc(title)}</span>", size=6.5)
    pg.html((x0 + 4, y0 + 12, x1 - 4, y1 - 2), body_html, size=size)


def _party(p: Party) -> str:
    return f"<b>{esc(p.name)}</b><br>{esc(p.address)}"


def _header(pg: R.Page, title: str, subtitle: str = "") -> None:
    pg.rect((0, 0, 595, 6), fill=(0.15, 0.25, 0.4))
    pg.html((36, 18, 560, 40), f"<b>{esc(title)}</b>", size=16, align="center")
    if subtitle:
        pg.html((36, 40, 560, 54), esc(subtitle), size=8, align="center", color="#555")


# --- documents ------------------------------------------------------------------


def render_invoice(sh: Shipment, path: Path, metadata: dict | None = None) -> None:
    o = sh.overrides["invoice"]
    pdf = R.new_doc()
    pg = R.Page(pdf, *B.A4)
    _header(pg, "COMMERCIAL INVOICE")
    seller = Party(o.get("seller_name", sh.seller.name), sh.seller.address, sh.seller.country)
    buyer = Party(o.get("buyer_name", sh.buyer.name), sh.buyer.address, sh.buyer.country)
    _box(pg, (36, 60, 300, 130), "Seller / Exporter", _party(seller))
    _box(pg, (300, 60, 560, 130), "Invoice No. / Date",
         f"<b>{esc(o.get('invoice_no', sh.invoice_no))}</b><br>{fd(o.get('invoice_date', sh.invoice_date))}"
         f"<br><span class='lbl'>L/C No.</span> {esc(sh.lc_no)} dated {fd(sh.lc_issue)}")
    _box(pg, (36, 130, 300, 200), "Buyer / Consignee", _party(buyer))
    _box(pg, (300, 130, 560, 200), "Terms",
         f"Incoterms® 2020: <b>{esc(sh.incoterm)}</b><br>Payment: Documentary credit at sight"
         f"<br>Country of origin: {esc(sh.seller.country)}")
    _box(pg, (36, 200, 210, 240), "Port of Loading", f"{esc(sh.pol[1])} ({sh.pol[0]})")
    _box(pg, (210, 200, 385, 240), "Port of Discharge",
         f"{esc(o.get('pod', sh.pod)[1])} ({o.get('pod', sh.pod)[0]})")
    _box(pg, (385, 200, 560, 240), "Vessel / Voyage", f"{esc(sh.vessel)} / {esc(sh.voyage)}")
    rows = ""
    items = o.get("items", sh.items)
    for i, it in enumerate(items, 1):
        amt = o.get("line_amounts", {}).get(i - 1, it.amount)
        rows += (f"<tr><td>{i}</td><td>{esc(it.description)}</td><td>{it.hs_code}</td>"
                 f"<td class='num'>{it.quantity:,.0f} {it.unit}</td><td class='num'>{money(it.unit_price)}</td>"
                 f"<td class='num'>{money(amt)}</td></tr>")
    total = o.get("total", sh.total)
    rows += (f"<tr><td></td><td colspan='4'><b>TOTAL {esc(sh.incoterm)} ({sh.currency})</b></td>"
             f"<td class='num'><b>{money(total)}</b></td></tr>")
    pg.html((36, 250, 560, 420),
            "<table><tr><th>#</th><th>Description of goods</th><th>HS code</th><th class='num'>Quantity</th>"
            f"<th class='num'>Unit price</th><th class='num'>Amount</th></tr>{rows}</table>", size=8)
    pg.html((36, 425, 560, 450), f"<span class='lbl'>Amount in words:</span> {amount_in_words(total)}", size=8)
    acct = o.get("seller_account", sh.seller_account)
    acct_html = "<br>".join(f"{B._ID_LABEL.get(k, k)}: {esc(v)}" for k, v in acct.items())
    bank_name = B.BANKS[sh.seller_bank_code].name
    _box(pg, (36, 460, 330, 545), "Beneficiary bank details",
         f"Account name: <b>{esc(o.get('account_name', seller.name))}</b><br>{esc(bank_name)}<br>{acct_html}"
         f"<br>SWIFT: {B.BANKS[sh.seller_bank_code].bic}")
    marks = ", ".join(c.number for c in sh.containers)
    _box(pg, (330, 460, 560, 545), "Marks & numbers / Containers", esc(marks), size=7.5)
    pg.html((36, 560, 560, 600), "We certify that this invoice is true and correct and that the origin of the "
            "goods is as stated above.", size=8)
    pg.line((380, 650), (560, 650))
    pg.html((380, 653, 560, 680), f"For and on behalf of<br><b>{esc(seller.name)}</b>", size=8)
    pg.specimen()
    R.save(pdf, path, metadata)


def render_packing_list(sh: Shipment, path: Path, metadata: dict | None = None) -> None:
    o = sh.overrides["packing"]
    pdf = R.new_doc()
    pg = R.Page(pdf, *B.A4)
    _header(pg, "PACKING LIST")
    _box(pg, (36, 60, 300, 130), "Shipper / Exporter", _party(sh.seller))
    _box(pg, (300, 60, 560, 130), "Reference", f"Invoice No. <b>{esc(sh.invoice_no)}</b><br>"
         f"Date {fd(sh.invoice_date)}<br>L/C No. {esc(sh.lc_no)}")
    _box(pg, (36, 130, 300, 200), "Consignee", _party(sh.buyer))
    _box(pg, (300, 130, 560, 200), "Shipment", f"{esc(sh.pol[1])} → {esc(sh.pod[1])}<br>"
         f"Vessel {esc(sh.vessel)} / {esc(sh.voyage)}")
    rows = ""
    for i, it in enumerate(sh.items):
        gross = o.get("gross_kg", {}).get(i, it.gross_kg)
        rows += (f"<tr><td>{esc(it.description)}</td><td class='num'>{it.packages:,}</td>"
                 f"<td class='num'>{it.net_kg:,.1f}</td><td class='num'>{gross:,.1f}</td>"
                 f"<td class='num'>{it.cbm:,.2f}</td></tr>")
    tg = o.get("gross_total", sum(o.get("gross_kg", {}).get(i, it.gross_kg) for i, it in enumerate(sh.items)))
    rows += (f"<tr><td><b>TOTAL</b></td><td class='num'><b>{sum(i.packages for i in sh.items):,}</b></td>"
             f"<td class='num'><b>{sum(i.net_kg for i in sh.items):,.1f}</b></td><td class='num'><b>{tg:,.1f}</b></td>"
             f"<td class='num'><b>{sum(i.cbm for i in sh.items):,.2f}</b></td></tr>")
    pg.html((36, 215, 560, 380), "<table><tr><th>Description</th><th class='num'>Packages</th>"
            f"<th class='num'>Net kg</th><th class='num'>Gross kg</th><th class='num'>CBM</th></tr>{rows}</table>",
            size=8)
    crow = "".join(f"<tr><td>{c.number}</td><td>{c.seal}</td><td>{c.size_type}</td>"
                   f"<td class='num'>{c.packages:,}</td><td class='num'>{c.gross_kg:,.1f}</td></tr>"
                   for c in sh.containers)
    pg.html((36, 390, 560, 520), "<table><tr><th>Container</th><th>Seal</th><th>Type</th>"
            f"<th class='num'>Packages</th><th class='num'>Gross kg</th></tr>{crow}</table>", size=8)
    pg.line((380, 650), (560, 650))
    pg.html((380, 653, 560, 680), f"For and on behalf of<br><b>{esc(sh.seller.name)}</b>", size=8)
    pg.specimen()
    R.save(pdf, path, metadata)


def render_bill_of_lading(sh: Shipment, path: Path, metadata: dict | None = None) -> None:
    o = sh.overrides["bl"]
    pdf = R.new_doc()
    pg = R.Page(pdf, *B.A4)
    _header(pg, "BILL OF LADING", "FOR COMBINED TRANSPORT OR PORT TO PORT SHIPMENT · "
            "OCEANIC MERIDIAN LINES (fictional carrier)")
    consignee = o.get("consignee", f"TO ORDER OF {sh.issuing_bank.split(',')[0].upper()}")
    notify = Party(o.get("notify_name", sh.notify.name), sh.notify.address, sh.notify.country)
    pod = o.get("pod", sh.pod)
    _box(pg, (36, 60, 330, 125), "Shipper", _party(Party(o.get("shipper_name", sh.seller.name),
                                                         sh.seller.address, sh.seller.country)))
    _box(pg, (330, 60, 560, 125), "B/L No.", f"<b>{esc(o.get('bl_no', sh.bl_no))}</b><br>"
         f"Booking ref. {esc(sh.bl_no[-7:])}<br>Export ref. {esc(sh.invoice_no)}")
    _box(pg, (36, 125, 330, 185), "Consignee", f"<b>{esc(consignee)}</b>")
    _box(pg, (330, 125, 560, 185), "Notify Party", _party(notify), size=7.5)
    _box(pg, (36, 185, 200, 220), "Vessel", esc(sh.vessel))
    _box(pg, (200, 185, 330, 220), "Voyage No.", esc(sh.voyage))
    _box(pg, (330, 185, 560, 220), "Place of Receipt", esc(sh.pol[1]))
    _box(pg, (36, 220, 330, 255), "Port of Loading", f"{esc(sh.pol[1])} ({sh.pol[0]})")
    _box(pg, (330, 220, 560, 255), "Port of Discharge", f"{esc(pod[1])} ({pod[0]})")
    containers = o.get("containers", sh.containers)
    crow = "".join(f"<tr><td>{c.number}<br>Seal {c.seal}</td><td>{c.size_type}</td><td class='num'>{c.packages:,}</td>"
                   f"<td class='num'>{c.gross_kg:,.1f}</td><td class='num'>{c.cbm:,.2f}</td></tr>" for c in containers)
    desc = o.get("goods_description", "; ".join(f"{i.description} (HS {i.hs_code})" for i in sh.items))
    gross_total = o.get("gross_total", sum(c.gross_kg for c in containers))
    pg.html((36, 265, 560, 420), "<table><tr><th>Container / Seal</th><th>Type</th><th class='num'>Packages</th>"
            f"<th class='num'>Gross kg</th><th class='num'>CBM</th></tr>{crow}"
            f"<tr><td colspan='3'><b>TOTAL</b></td><td class='num'><b>{gross_total:,.1f}</b></td><td></td></tr></table>",
            size=8)
    _box(pg, (36, 425, 560, 490), "Description of goods (said to contain)",
         f"{esc(desc)}<br>L/C No. {esc(sh.lc_no)}", size=8)
    freight = "FREIGHT PREPAID" if sh.incoterm.startswith(("CFR", "CIF")) else "FREIGHT COLLECT"
    _box(pg, (36, 490, 200, 525), "Freight", freight)
    _box(pg, (200, 490, 380, 525), "Number of original B/Ls", "THREE (3)")
    _box(pg, (380, 490, 560, 525), "Place and date of issue", f"{esc(sh.pol[1].split(',')[0])}, "
         f"{fd(o.get('on_board', sh.on_board))}")
    _box(pg, (36, 525, 560, 575), "Shipped on board",
         f"<b>SHIPPED ON BOARD {fd(o.get('on_board', sh.on_board))}</b> · vessel {esc(sh.vessel)} at "
         f"{esc(sh.pol[1])}")
    pg.line((380, 650), (560, 650))
    pg.html((380, 653, 560, 690), "Signed as Carrier<br><b>OCEANIC MERIDIAN LINES</b>", size=8)
    pg.specimen()
    R.save(pdf, path, metadata)


def mt700(sh: Shipment) -> str:
    o = sh.overrides["lc"]
    goods = "\n".join(f"+{i.description.upper()}, HS {i.hs_code}, {i.quantity:,.0f} {i.unit} "
                      f"AT USD {i.unit_price:,.2f} PER {i.unit}" for i in sh.items)
    lines = [
        f"{{1:F01{B.BANKS[{'UAE_to_PK': 'PK', 'IN_to_UK': 'UK', 'BD_to_DE': 'DE', 'AU_to_UAE': 'UAE'}[sh.scenario]].bic}XXXX0000000000}}"
        f"{{2:I700{B.BANKS[sh.seller_bank_code].bic}XXXXN}}{{4:",
        ":27:1/1", ":40A:IRREVOCABLE", f":20:{sh.lc_no}", f":31C:{sh.lc_issue.strftime('%y%m%d')}",
        ":40E:UCP LATEST VERSION",
        f":31D:{o.get('expiry', sh.lc_expiry).strftime('%y%m%d')}{sh.seller.address.split(',')[-1].strip().upper()}",
        f":50:{sh.buyer.name.upper()}\n{sh.buyer.address.upper()}",
        f":59:{o.get('beneficiary', sh.seller.name).upper()}\n{sh.seller.address.upper()}",
        f":32B:USD{o.get('amount', sh.lc_amount):,.2f}".replace(",", "X").replace(".", ",").replace("X", ""),
        f":39A:{sh.lc_tolerance_pct:02d}/{sh.lc_tolerance_pct:02d}",
        ":41D:ANY BANK BY NEGOTIATION", ":42C:SIGHT",
        f":42D:{sh.issuing_bank.split(',')[0].upper()}",
        ":43P:NOT ALLOWED", ":43T:ALLOWED",
        f":44E:{sh.pol[1].upper()}", f":44F:{o.get('pod', sh.pod)[1].upper()}",
        f":44C:{o.get('latest_shipment', sh.latest_shipment).strftime('%y%m%d')}",
        f":45A:{goods}\n{sh.incoterm.upper()} INCOTERMS 2020",
        ":46A:+SIGNED COMMERCIAL INVOICE IN 3 ORIGINALS\n+PACKING LIST IN 3 ORIGINALS\n"
        f"+FULL SET CLEAN ON BOARD OCEAN BILLS OF LADING MADE OUT TO ORDER OF "
        f"{sh.issuing_bank.split(',')[0].upper()} NOTIFY APPLICANT\n+CERTIFICATE OF ORIGIN",
        ":47A:+ALL DOCUMENTS MUST INDICATE THIS L/C NUMBER\n+DISCREPANCY FEE USD 75.00",
        ":71D:ALL BANK CHARGES OUTSIDE ISSUING BANK ARE FOR BENEFICIARY",
        ":48:21/DAYS AFTER SHIPMENT DATE", ":49:WITHOUT", "-}",
    ]
    return "\r\n".join(lines) + "\r\n"


def render_lc(sh: Shipment, path: Path, metadata: dict | None = None) -> None:
    pdf = R.new_doc()
    pg = R.Page(pdf, *B.A4)
    _header(pg, "DOCUMENTARY CREDIT ADVICE", f"Advised by {sh.advising_bank} · MT700 received from "
            f"{sh.issuing_bank}")
    body = esc(mt700(sh)).replace("\r\n", "<br>").replace("\n", "<br>")
    pg.html((36, 64, 560, 800), body, size=7.5, family="mono")
    pg.specimen()
    R.save(pdf, path, metadata)


def cii_xml(sh: Shipment) -> bytes:
    """Minimal UN/CEFACT Cross Industry Invoice (D16B) for structured ingestion tests."""
    ns = {"rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
          "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
          "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100"}
    for k, v in ns.items():
        ET.register_namespace(k, v)
    q = lambda p, t: f"{{{ns[p]}}}{t}"  # noqa: E731

    def sub(parent, p, t, text=None, **attrs):
        e = ET.SubElement(parent, q(p, t), attrs)
        if text is not None:
            e.text = str(text)
        return e

    o = sh.overrides["invoice"]
    root = ET.Element(q("rsm", "CrossIndustryInvoice"))
    ctx = sub(root, "rsm", "ExchangedDocumentContext")
    sub(sub(ctx, "ram", "GuidelineSpecifiedDocumentContextParameter"), "ram", "ID", "urn:cen.eu:en16931:2017")
    doc = sub(root, "rsm", "ExchangedDocument")
    sub(doc, "ram", "ID", o.get("invoice_no", sh.invoice_no))
    sub(doc, "ram", "TypeCode", "380")
    dt = sub(doc, "ram", "IssueDateTime")
    sub(dt, "udt", "DateTimeString", o.get("invoice_date", sh.invoice_date).strftime("%Y%m%d"), format="102")
    tx = sub(root, "rsm", "SupplyChainTradeTransaction")
    for i, it in enumerate(o.get("items", sh.items), 1):
        li = sub(tx, "ram", "IncludedSupplyChainTradeLineItem")
        sub(sub(li, "ram", "AssociatedDocumentLineDocument"), "ram", "LineID", i)
        prod = sub(li, "ram", "SpecifiedTradeProduct")
        sub(prod, "ram", "Name", it.description)
        sub(sub(prod, "ram", "DesignatedProductClassification"), "ram", "ClassCode", it.hs_code, listID="HS")
        sub(sub(sub(li, "ram", "SpecifiedLineTradeAgreement"), "ram", "NetPriceProductTradePrice"),
            "ram", "ChargeAmount", f"{it.unit_price:.2f}")
        sub(sub(li, "ram", "SpecifiedLineTradeDelivery"), "ram", "BilledQuantity", f"{it.quantity:.0f}", unitCode=it.unit)
        amt = o.get("line_amounts", {}).get(i - 1, it.amount)
        sub(sub(sub(li, "ram", "SpecifiedLineTradeSettlement"), "ram", "SpecifiedTradeSettlementLineMonetarySummation"),
            "ram", "LineTotalAmount", f"{amt:.2f}")
    ag = sub(tx, "ram", "ApplicableHeaderTradeAgreement")
    for tag, party in (("SellerTradeParty", Party(o.get("seller_name", sh.seller.name), sh.seller.address, sh.seller.country)),
                       ("BuyerTradeParty", sh.buyer)):
        pt = sub(ag, "ram", tag)
        sub(pt, "ram", "Name", party.name)
        addr = sub(pt, "ram", "PostalTradeAddress")
        sub(addr, "ram", "LineOne", party.address)
        sub(addr, "ram", "CountryID", party.country)
    dl = sub(tx, "ram", "ApplicableHeaderTradeDelivery")
    ev = sub(dl, "ram", "ActualDeliverySupplyChainEvent")
    sub(sub(ev, "ram", "OccurrenceDateTime"), "udt", "DateTimeString", sh.on_board.strftime("%Y%m%d"), format="102")
    st = sub(tx, "ram", "ApplicableHeaderTradeSettlement")
    sub(st, "ram", "InvoiceCurrencyCode", sh.currency)
    ms = sub(st, "ram", "SpecifiedTradeSettlementHeaderMonetarySummation")
    sub(ms, "ram", "GrandTotalAmount", f"{o.get('total', sh.total):.2f}")
    ET.indent(root)
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="utf-8")


def render_shipment(sh: Shipment, folder: Path, prefix: str) -> dict[str, Path]:
    folder.mkdir(parents=True, exist_ok=True)
    out = {
        "commercial_invoice": folder / f"{prefix}_commercial_invoice.pdf",
        "packing_list": folder / f"{prefix}_packing_list.pdf",
        "bill_of_lading": folder / f"{prefix}_bill_of_lading.pdf",
        "letter_of_credit": folder / f"{prefix}_letter_of_credit.pdf",
    }
    render_invoice(sh, out["commercial_invoice"])
    render_packing_list(sh, out["packing_list"])
    render_bill_of_lading(sh, out["bill_of_lading"])
    render_lc(sh, out["letter_of_credit"])
    out["mt700"] = folder / f"{prefix}_letter_of_credit.mt700.txt"
    out["mt700"].write_text(mt700(sh), encoding="utf-8", newline="")
    out["cii"] = folder / f"{prefix}_commercial_invoice.cii.xml"
    out["cii"].write_bytes(cii_xml(sh))
    return out
