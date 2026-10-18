"""Fictional people and region-specific document numbers.

All names are invented or drawn from Faker. Numbers follow each scheme's real
format and check-digit rule so that only the adversarial tier fails validation.
"""

from __future__ import annotations

import random
import string
from dataclasses import dataclass, field
from datetime import date, timedelta

from faker import Faker

from . import checksums as ck

# (given, surname, given_native, surname_native, sex)
_NATIVE_NAMES: dict[str, list[tuple[str, str, str, str, str]]] = {
    "UAE": [
        ("Tareq", "Al Mahmood", "طارق", "المحمود", "M"),
        ("Fatima", "Al Suwaidi", "فاطمة", "السويدي", "F"),
        ("Ahmed", "Al Mansoori", "أحمد", "المنصوري", "M"),
        ("Mariam", "Al Hashimi", "مريم", "الهاشمي", "F"),
        ("Khalid", "Al Nuaimi", "خالد", "النعيمي", "M"),
        ("Noura", "Al Ketbi", "نورة", "الكتبي", "F"),
        ("Mohammed", "Al Falasi", "محمد", "الفلاسي", "M"),
        ("Aisha", "Al Zaabi", "عائشة", "الزعابي", "F"),
    ],
    "PK": [
        ("Muhammad", "Ali", "محمد", "علی", "M"),
        ("Ayesha", "Khan", "عائشہ", "خان", "F"),
        ("Bilal", "Ahmed", "بلال", "احمد", "M"),
        ("Sana", "Qureshi", "ثناء", "قریشی", "F"),
        ("Usman", "Raza", "عثمان", "رضا", "M"),
        ("Hira", "Malik", "حرا", "ملک", "F"),
        ("Imran", "Siddiqui", "عمران", "صدیقی", "M"),
        ("Zainab", "Hussain", "زینب", "حسین", "F"),
    ],
    "IN": [
        ("Anil", "Kumar", "अनिल", "कुमार", "M"),
        ("Priya", "Sharma", "प्रिया", "शर्मा", "F"),
        ("Rahul", "Verma", "राहुल", "वर्मा", "M"),
        ("Sunita", "Patel", "सुनीता", "पटेल", "F"),
        ("Vikram", "Singh", "विक्रम", "सिंह", "M"),
        ("Neha", "Gupta", "नेहा", "गुप्ता", "F"),
        ("Arjun", "Reddy", "अर्जुन", "रेड्डी", "M"),
        ("Kavita", "Iyer", "कविता", "अय्यर", "F"),
    ],
    "BD": [
        ("Rahim", "Uddin", "রহিম", "উদ্দিন", "M"),
        ("Fatema", "Begum", "ফাতেমা", "বেগম", "F"),
        ("Kamal", "Hossain", "কামাল", "হোসেন", "M"),
        ("Nasrin", "Akter", "নাসরিন", "আক্তার", "F"),
        ("Abdul", "Karim", "আব্দুল", "করিম", "M"),
        ("Shirin", "Sultana", "শিরিন", "সুলতানা", "F"),
        ("Jamal", "Mia", "জামাল", "মিয়া", "M"),
        ("Ruma", "Khatun", "রুমা", "খাতুন", "F"),
    ],
}

_FAKER_LOCALE = {
    "UK": "en_GB", "US": "en_US", "AU": "en_AU", "NZ": "en_NZ",
    "DE": "de_DE", "FR": "fr_FR", "ES": "es_ES", "NL": "nl_NL",
    "UAE": "en_US", "PK": "en_US", "IN": "en_IN", "BD": "en_US",
}

ISO3 = {
    "UAE": "ARE", "UK": "GBR", "US": "USA", "PK": "PAK", "IN": "IND", "BD": "BGD",
    "AU": "AUS", "NZ": "NZL", "DE": "D", "FR": "FRA", "ES": "ESP", "NL": "NLD",
}

NATIONALITY = {
    "UAE": "United Arab Emirates", "UK": "British Citizen", "US": "United States of America",
    "PK": "Pakistani", "IN": "Indian", "BD": "Bangladeshi", "AU": "Australian",
    "NZ": "New Zealand", "DE": "Deutsch", "FR": "Française", "ES": "Española", "NL": "Nederlandse",
}

_CITIES = {
    "UAE": ["Dubai", "Abu Dhabi", "Sharjah", "Al Ain"],
    "UK": ["London", "Manchester", "Leeds", "Bristol"],
    "US": ["Sacramento", "Austin", "Albany", "Tallahassee"],
    "PK": ["Karachi", "Lahore", "Islamabad", "Peshawar"],
    "IN": ["Mumbai", "New Delhi", "Bengaluru", "Chennai"],
    "BD": ["Dhaka", "Chattogram", "Sylhet", "Khulna"],
    "AU": ["Sydney", "Melbourne", "Brisbane", "Perth"],
    "NZ": ["Auckland", "Wellington", "Christchurch", "Hamilton"],
    "DE": ["Berlin", "München", "Köln", "Düsseldorf"],
    "FR": ["Paris", "Lyon", "Orléans", "Besançon"],
    "ES": ["Madrid", "Málaga", "A Coruña", "Cádiz"],
    "NL": ["Amsterdam", "Rotterdam", "Utrecht", "Den Haag"],
}


@dataclass
class Person:
    region: str
    given: str
    surname: str
    sex: str  # "M" or "F"
    dob: date
    place_of_birth: str
    address: str
    given_native: str = ""
    surname_native: str = ""
    father_name: str = ""
    father_name_native: str = ""
    mother_name: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def full_name(self) -> str:
        return f"{self.given} {self.surname}"

    @property
    def full_name_native(self) -> str:
        return f"{self.given_native} {self.surname_native}".strip()


_FAKERS: dict[str, Faker] = {}


def make_person(region: str, rng: random.Random, as_of: date, index: int = 0) -> Person:
    loc = _FAKER_LOCALE[region]
    fk = _FAKERS.setdefault(loc, Faker(loc))  # building a Faker is slow; reseeding keeps output deterministic
    fk.seed_instance(rng.randrange(1 << 30))
    age_days = rng.randint(21 * 365, 64 * 365)
    dob = as_of - timedelta(days=age_days)
    city = rng.choice(_CITIES[region])
    if region in _NATIVE_NAMES:
        pool = _NATIVE_NAMES[region]
        given, surname, g_n, s_n, sex = pool[index % len(pool)]
        fathers = [p for p in pool if p[4] == "M" and p[0] != given]
        f = rng.choice(fathers)
        mothers = [p for p in pool if p[4] == "F" and p[0] != given]
        m = rng.choice(mothers)
        person = Person(region, given, surname, sex, dob, city, _address(region, fk, rng, city),
                        g_n, s_n, f"{f[0]} {surname}", f"{f[2]} {s_n}", f"{m[0]} {m[1]}")
    else:
        sex = "M" if index % 2 == 0 else "F"
        given = fk.first_name_male() if sex == "M" else fk.first_name_female()
        person = Person(region, given, fk.last_name(), sex, dob, city, _address(region, fk, rng, city))
    return person


def _address(region: str, fk: Faker, rng: random.Random, city: str) -> str:
    if region == "UAE":
        return f"Villa {rng.randint(1, 120)}, Street {rng.randint(1, 40)}, {city}, UAE"
    if region == "PK":
        return f"House {rng.randint(1, 900)}, Block {rng.choice('ABCDEFG')}, {city}"
    if region == "BD":
        return f"House {rng.randint(1, 90)}, Road {rng.randint(1, 30)}, {city}"
    if region == "IN":
        return f"Flat {rng.randint(101, 1204)}, {fk.street_name()}, {city} {rng.randint(110001, 600099)}"
    return fk.address().replace("\n", ", ")


# --- document numbers --------------------------------------------------------


def digits(rng: random.Random, n: int) -> str:
    return "".join(rng.choice(string.digits) for _ in range(n))


def letters(rng: random.Random, n: int, alphabet: str = string.ascii_uppercase) -> str:
    return "".join(rng.choice(alphabet) for _ in range(n))


def emirates_id(birth_year: int, rng: random.Random) -> str:
    body = f"784{birth_year}{digits(rng, 7)}"
    return f"784-{birth_year}-{body[7:]}-{ck.luhn_check_digit(body)}"


def cnic(sex: str, rng: random.Random) -> str:
    last = rng.choice("13579" if sex == "M" else "02468")
    return f"{rng.choice('1234567')}{digits(rng, 4)}-{digits(rng, 7)}-{last}"


def aadhaar(rng: random.Random) -> str:
    body = rng.choice("23456789") + digits(rng, 10)
    n = body + ck.verhoeff_check_digit(body)
    return f"{n[:4]} {n[4:8]} {n[8:]}"


def pan(surname: str, rng: random.Random) -> str:
    return f"{letters(rng, 3)}P{surname.replace('Al ', '')[0].upper()}{digits(rng, 4)}{letters(rng, 1)}"


def bd_nid(dob: date, rng: random.Random, smart: bool) -> str:
    if smart:
        return rng.choice("123456789") + digits(rng, 9)
    return f"{dob.year}{digits(rng, 13)}"


def uk_driving_licence(surname: str, given: str, dob: date, sex: str, rng: random.Random) -> str:
    """DVLA layout: SURNM 5 | decade | month(+50 female) | day | year | initials | 9 | 2 check chars."""
    s = "".join(c for c in surname.upper() if c.isalpha())
    s = (s + "99999")[:5]
    month = dob.month + (50 if sex == "F" else 0)
    yy = f"{dob.year % 100:02d}"
    initials = (given[0].upper() + "9")[:2]
    return f"{s}{yy[0]}{month:02d}{dob.day:02d}{yy[1]}{initials}9{letters(rng, 2)}"


def medicare(rng: random.Random) -> tuple[str, str]:
    first8 = rng.choice("23456") + digits(rng, 7)
    number = first8 + ck.medicare_check_digit(first8) + rng.choice("123456789")
    return f"{number[:4]} {number[4:9]} {number[9]}", str(rng.randint(1, 5))


def spanish_dni(rng: random.Random) -> str:
    n = rng.randint(10_000_000, 79_999_999)
    return f"{n}{ck.dni_letter(n)}"


def german_id_number(rng: random.Random) -> str:
    return letters(rng, 9, "CFGHJKLMNPRTVWXYZ0123456789")


def passport_number(region: str, rng: random.Random) -> str:
    fmt = {
        "UAE": lambda: "N" + digits(rng, 7),
        "UK": lambda: digits(rng, 9),
        "US": lambda: rng.choice("56") + digits(rng, 8),
        "PK": lambda: letters(rng, 2) + digits(rng, 7),
        "IN": lambda: letters(rng, 1) + digits(rng, 7),
        "BD": lambda: letters(rng, 2) + digits(rng, 7),
        "AU": lambda: "P" + letters(rng, 1) + digits(rng, 7),
        "NZ": lambda: letters(rng, 2) + digits(rng, 6),
        "FR": lambda: digits(rng, 2) + letters(rng, 2) + digits(rng, 5),
        "DE": lambda: "C" + letters(rng, 8, "CFGHJKLMNPRTVWXYZ0123456789"),
        "ES": lambda: letters(rng, 3) + digits(rng, 6),
    }
    return fmt[region]()


def container_number(rng: random.Random, owner: str = "OMLU") -> str:
    first10 = owner + digits(rng, 6)
    return first10 + ck.iso6346_check_digit(first10)
