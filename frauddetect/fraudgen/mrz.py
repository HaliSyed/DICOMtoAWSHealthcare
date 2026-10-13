"""ICAO 9303 machine-readable zones: TD3 (passport, 2x44) and TD1 (ID card, 3x30)."""

from __future__ import annotations

import re
import unicodedata

from .checksums import icao_check_digit as cd


# ICAO 9303 part 3 recommended transliterations (others just lose the accent)
_TRANSLIT = str.maketrans({"Ä": "AE", "Ö": "OE", "Ü": "UE", "ß": "SS", "Å": "AA", "Æ": "AE",
                           "Ø": "OE", "Þ": "TH", "Œ": "OE", "ä": "AE", "ö": "OE", "ü": "UE",
                           "å": "AA", "æ": "AE", "ø": "OE", "þ": "TH", "œ": "OE"})


def mrz_field(text: str, length: int) -> str:
    """Upper-case, transliterate, map anything non-alphanumeric to '<', pad/trim."""
    t = unicodedata.normalize("NFKD", text.translate(_TRANSLIT)).encode("ascii", "ignore").decode().upper()
    t = re.sub(r"[^A-Z0-9]", "<", t)
    return (t + "<" * length)[:length]


def mrz_name(surname: str, given: str, length: int) -> str:
    return mrz_field(f"{surname}<<{given}", length)


def td3(doc_type: str, country: str, surname: str, given: str, number: str,
        nationality: str, dob: str, sex: str, expiry: str, optional: str = "") -> list[str]:
    """dob/expiry are YYMMDD."""
    l1 = mrz_field(doc_type, 2) + mrz_field(country, 3) + mrz_name(surname, given, 39)
    num = mrz_field(number, 9)
    opt = mrz_field(optional, 14)
    opt_cd = cd(opt) if optional else "<"
    body = num + cd(num) + mrz_field(nationality, 3) + dob + cd(dob) + sex + expiry + cd(expiry) + opt + opt_cd
    composite = cd(num + cd(num) + dob + cd(dob) + expiry + cd(expiry) + opt + opt_cd)
    return [l1, body + composite]


def td1(doc_type: str, country: str, surname: str, given: str, number: str,
        nationality: str, dob: str, sex: str, expiry: str,
        optional1: str = "", optional2: str = "") -> list[str]:
    num = mrz_field(number, 9)
    l1 = mrz_field(doc_type, 2) + mrz_field(country, 3) + num + cd(num) + mrz_field(optional1, 15)
    l2 = dob + cd(dob) + sex + expiry + cd(expiry) + mrz_field(nationality, 3) + mrz_field(optional2, 11)
    composite = cd(l1[5:30] + l2[0:7] + l2[8:15] + l2[18:29])
    return [l1, l2 + composite, mrz_name(surname, given, 30)]
