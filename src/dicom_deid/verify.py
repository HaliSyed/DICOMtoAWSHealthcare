"""
Independent post-check on a de-identified dataset.

The de-identifier applies rules; this module does not trust them. It scans
every element (including inside sequences) for anything that should not be
there. Issues name the attribute only -- never the offending value.
"""

import re

from pydicom.dataset import Dataset
from pydicom.multival import MultiValue

TEXT_VRS = {"AE", "AS", "CS", "DA", "DS", "DT", "IS", "LO", "LT", "PN", "SH", "ST", "TM", "UC", "UR", "UT"}
# Long identifiers (MRNs, national IDs) match anywhere in a value. Short ones
# (surnames like "Ali" or "Lee") match as whole words only -- still caught in
# "reviewed with Jane Lee", without flagging every value that contains "lee".
# Errs towards quarantine: a surname that is also a common word ("Head")
# causes a false positive, never a leak.
MIN_SUBSTRING_LEN = 5


def find_residual_phi(ds: Dataset, original_identifiers: list[str], patient_token: str) -> list[str]:
    issues: list[str] = []
    if str(ds.get("PatientIdentityRemoved", "")) != "YES":
        issues.append("PatientIdentityRemoved not set")

    long_ids = [i.lower() for i in original_identifiers if len(i) >= MIN_SUBSTRING_LEN]
    short_ids = [re.compile(rf"(?<![a-z0-9]){re.escape(i.lower())}(?![a-z0-9])")
                 for i in original_identifiers if len(i) < MIN_SUBSTRING_LEN]

    for elem in ds.iterall():
        name = elem.keyword or str(elem.tag)
        if elem.tag.is_private:
            issues.append(f"{name}: private tag present")
            continue
        group = elem.tag.group
        if 0x5000 <= group <= 0x50FF or 0x6000 <= group <= 0x60FF:
            issues.append(f"{name}: overlay/curve present")
            continue
        if elem.VR == "PN" and elem.value not in (None, ""):
            if not (elem.keyword == "PatientName" and str(elem.value) == patient_token):
                issues.append(f"{name}: person name present")
            continue
        if elem.VR not in TEXT_VRS or elem.value in (None, ""):
            continue
        values = list(elem.value) if isinstance(elem.value, (list, MultiValue)) else [elem.value]
        for v in values:
            text = str(v).lower()
            if any(i in text for i in long_ids) or any(p.search(text) for p in short_ids):
                issues.append(f"{name}: contains an original identifier")
                break
    return sorted(set(issues))
