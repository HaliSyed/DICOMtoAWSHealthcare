"""Check-digit algorithms for identity, banking and shipping numbers.

Every generator in this package builds numbers that pass these checks, and the
adversarial tier deliberately breaks them, so a validator under test can be
scored against a known answer.
"""

from __future__ import annotations

import string

# --- ICAO 9303 (passports, ID cards, MRZ) -----------------------------------

_ICAO_WEIGHTS = (7, 3, 1)


def _icao_value(ch: str) -> int:
    if ch.isdigit():
        return int(ch)
    if ch == "<":
        return 0
    return ord(ch.upper()) - 55  # A=10 ... Z=35


def icao_check_digit(data: str) -> str:
    """ICAO 9303 part 3 check digit (weights 7,3,1 repeating, mod 10)."""
    total = sum(_icao_value(c) * _ICAO_WEIGHTS[i % 3] for i, c in enumerate(data))
    return str(total % 10)


# --- Luhn (Emirates ID, cards) ----------------------------------------------


def luhn_check_digit(digits: str) -> str:
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = int(d)
        if i % 2 == 0:  # positions that get doubled once the check digit is appended
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return str((10 - total % 10) % 10)


def luhn_valid(number: str) -> bool:
    return luhn_check_digit(number[:-1]) == number[-1]


# --- Verhoeff (Aadhaar) ------------------------------------------------------

_VD = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
    [2, 3, 4, 0, 1, 7, 8, 9, 5, 6], [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
    [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
    [8, 7, 6, 5, 9, 3, 2, 1, 0, 4], [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]
_VP = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
    [5, 8, 0, 3, 7, 9, 6, 1, 4, 2], [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
    [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]
_VINV = [0, 4, 3, 2, 1, 5, 6, 7, 8, 9]


def verhoeff_check_digit(digits: str) -> str:
    c = 0
    for i, d in enumerate(reversed(digits)):
        c = _VD[c][_VP[(i + 1) % 8][int(d)]]
    return str(_VINV[c])


def verhoeff_valid(number: str) -> bool:
    c = 0
    for i, d in enumerate(reversed(number)):
        c = _VD[c][_VP[i % 8][int(d)]]
    return c == 0


# --- IBAN (ISO 13616, mod 97) ------------------------------------------------


def _iban_numeric(s: str) -> int:
    return int("".join(str(int(c, 36)) for c in s))


def iban_build(country: str, bban: str) -> str:
    check = 98 - _iban_numeric(bban + country + "00") % 97
    return f"{country}{check:02d}{bban}"


def iban_valid(iban: str) -> bool:
    s = iban.replace(" ", "")
    return _iban_numeric(s[4:] + s[:4]) % 97 == 1


def iban_format(iban: str) -> str:
    return " ".join(iban[i:i + 4] for i in range(0, len(iban), 4))


# --- US ABA routing transit number -------------------------------------------


def aba_check_digit(first8: str) -> str:
    w = (3, 7, 1, 3, 7, 1, 3, 7)
    total = sum(int(d) * w[i] for i, d in enumerate(first8))
    return str((10 - total % 10) % 10)


def aba_valid(rtn: str) -> bool:
    return len(rtn) == 9 and aba_check_digit(rtn[:8]) == rtn[8]


# --- Australian Medicare -----------------------------------------------------


def medicare_check_digit(first8: str) -> str:
    w = (1, 3, 7, 9, 1, 3, 7, 9)
    return str(sum(int(d) * w[i] for i, d in enumerate(first8)) % 10)


# --- Spanish DNI letter ------------------------------------------------------

_DNI_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"


def dni_letter(number: int) -> str:
    return _DNI_LETTERS[number % 23]


# --- ISO 6346 container numbers ----------------------------------------------


def _iso6346_values() -> dict[str, int]:
    vals, n = {}, 10
    for ch in string.ascii_uppercase:
        if n % 11 == 0:  # multiples of 11 are skipped
            n += 1
        vals[ch] = n
        n += 1
    return vals


_ISO6346 = _iso6346_values()


def iso6346_check_digit(first10: str) -> str:
    total = sum(
        (_ISO6346[c] if c.isalpha() else int(c)) * (2 ** i) for i, c in enumerate(first10)
    )
    return str(total % 11 % 10)
