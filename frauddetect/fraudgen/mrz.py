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


# --- editing existing MRZ lines (used by custom cases) -------------------------------

# (line, start, end) of each field and where its check digit sits
_TD3 = {"number": (1, 0, 9), "number_cd": (1, 9), "dob": (1, 13, 19), "dob_cd": (1, 19), "sex": (1, 20, 21),
        "expiry": (1, 21, 27), "expiry_cd": (1, 27), "composite_cd": (1, 43), "country": (0, 2, 5)}
_TD1 = {"number": (0, 5, 14), "number_cd": (0, 14), "dob": (1, 0, 6), "dob_cd": (1, 6), "sex": (1, 7, 8),
        "expiry": (1, 8, 14), "expiry_cd": (1, 14), "composite_cd": (1, 29), "country": (0, 2, 5)}


def _layout(lines: list[str]) -> dict:
    return _TD3 if len(lines) == 2 else _TD1


def _put(lines: list[str], line: int, start: int, value: str) -> None:
    s = lines[line]
    lines[line] = s[:start] + value + s[start + len(value):]


def _recompute(lines: list[str]) -> None:
    lay = _layout(lines)
    for f in ("number", "dob", "expiry"):
        ln, a, b = lay[f]
        _put(lines, lay[f + "_cd"][0], lay[f + "_cd"][1], cd(lines[ln][a:b]))
    if lay is _TD3:
        l2 = lines[1]
        _put(lines, 1, 43, cd(l2[0:10] + l2[13:20] + l2[21:43]))
    else:
        l1, l2 = lines[0], lines[1]
        _put(lines, 1, 29, cd(l1[5:30] + l2[0:7] + l2[8:15] + l2[18:29]))


def retouch(lines: list[str], number: str | None = None, dob: str | None = None, sex: str | None = None,
            expiry: str | None = None, country: str | None = None, optional1: str | None = None) -> list[str]:
    """Change MRZ fields and recompute every check digit, so the MRZ stays
    internally valid (dob/expiry are YYMMDD). Returns a new list."""
    out = list(lines)
    lay = _layout(out)
    for key, val, width in (("number", number, 9), ("dob", dob, 6), ("expiry", expiry, 6), ("sex", sex, 1),
                            ("country", country, 3)):
        if val is not None:
            ln, a, _ = lay[key]
            _put(out, ln, a, mrz_field(val, width) if key != "sex" else val)
    if optional1 is not None and lay is _TD1:
        _put(out, 0, 15, mrz_field(optional1, 15))
    _recompute(out)
    return out


def break_check_digit(lines: list[str], target: str) -> list[str]:
    """Corrupt one check digit: document_number | dob | expiry | composite."""
    out = list(lines)
    lay = _layout(out)
    ln, pos = lay[{"document_number": "number_cd", "dob": "dob_cd", "expiry": "expiry_cd",
                   "composite": "composite_cd"}[target]]
    c = out[ln][pos]
    _put(out, ln, pos, str((int(c) + 1) % 10) if c.isdigit() else "1")
    return out
