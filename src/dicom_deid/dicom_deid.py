"""
DICOM de-identification.

Implements a practical subset of the DICOM PS3.15 Annex E "Basic Application
Level Confidentiality Profile", plus a per-patient date shift. Rules, in the
order they are applied:

  1. Private tags, overlays (60xx) and curves (50xx) are removed -- vendors
     routinely hide names and IDs in private tags.
  2. Attributes in REMOVE_KEYWORDS are deleted wherever they appear,
     including inside sequences.
  3. Attributes in EMPTY_KEYWORDS are kept but emptied (they are Type 2 in
     most IODs, so deleting them would make the file non-conformant).
  4. Generic, recursive rules by VR -- these catch attributes nobody thought
     to list:
       PN  -> emptied (every person name, anywhere)
       DA  -> shifted by the patient's offset
       DT  -> date part shifted, time kept
       UI  -> remapped to a deterministic 2.25.* UID, except standard
              DICOM UIDs (1.2.840.10008.*) and SOP class UIDs
  5. PatientName / PatientID are set to the patient token, AccessionNumber
     to an accession token, and free-text descriptions are regex-redacted.
  6. De-identification markers are written (PatientIdentityRemoved etc.).

Pixel data is NOT inspected. Images whose pixels may contain burned-in text
are flagged via burned_in_risk() and quarantined by the pipeline instead of
being released.
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import date

from pydicom.dataset import Dataset
from pydicom.multival import MultiValue
from pydicom.tag import Tag

from .pseudonym import (
    accession_token,
    age_at,
    age_band,
    date_shift_days,
    patient_token,
    remap_uid,
    shift_date,
)
from .text_deid import redact_free_text

PROFILE_VERSION = "dicom-deid 0.1: PS3.15 E.1 subset + date shift"  # LO VR: max 64 chars
STANDARD_UID_ROOT = "1.2.840.10008."

REMOVE_KEYWORDS = [
    # Patient
    "OtherPatientIDs", "OtherPatientIDsSequence", "OtherPatientNames",
    "PatientBirthName", "PatientMotherBirthName", "PatientAddress",
    "PatientTelephoneNumbers", "PatientAge", "PatientSize", "PatientWeight",
    "MedicalRecordLocator", "EthnicGroup", "Occupation", "MilitaryRank",
    "BranchOfService", "CountryOfResidence", "RegionOfResidence",
    "PatientReligiousPreference", "PatientComments", "AdditionalPatientHistory",
    "AdmittingDiagnosesDescription", "IssuerOfPatientID", "PatientInsurancePlanCodeSequence",
    "ResponsiblePerson", "ResponsibleOrganization", "ReferencedPatientSequence",
    # People / organisation / equipment
    "InstitutionName", "InstitutionAddress", "InstitutionalDepartmentName",
    "InstitutionCodeSequence", "StationName", "DeviceSerialNumber",
    "PhysiciansOfRecord", "PerformingPhysicianName", "NameOfPhysiciansReadingStudy",
    "OperatorsName", "RequestingPhysician", "ReferringPhysicianAddress",
    "ReferringPhysicianTelephoneNumbers",
    # Orders / free text
    "RequestedProcedureID", "ScheduledProcedureStepID", "PerformedProcedureStepID",
    "StudyComments", "ImageComments", "RequestedContrastAgent", "TextComments",
]

EMPTY_KEYWORDS = ["PatientBirthDate", "PatientBirthTime", "ReferringPhysicianName", "StudyID"]

TEXT_REDACT_KEYWORDS = ["StudyDescription", "SeriesDescription", "ProtocolName"]

# Modalities / SOP classes that commonly carry burned-in text in the pixels.
BURNED_IN_RISK_MODALITIES = {"US", "SC", "OT", "XA", "ES", "XC", "DOC", "GM", "SM"}
SECONDARY_CAPTURE_ROOT = "1.2.840.10008.5.1.4.1.1.7"

_REMOVE_TAGS = {Tag(k) for k in REMOVE_KEYWORDS}


@dataclass
class DeidResult:
    dataset: Dataset
    patient_token: str
    shift_days: int
    age_band: str
    burned_in_risk: str | None
    actions: dict = field(default_factory=dict)
    # Original identifier strings, kept in memory only so the verifier can
    # check none survived. Never persist or log these.
    original_identifiers: list = field(default_factory=list, repr=False)


def _parse_da(value) -> date | None:
    s = str(value or "").strip()
    if len(s) < 8 or not s[:8].isdigit():
        return None
    try:
        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except ValueError:
        return None


def _values(elem) -> list:
    v = elem.value
    if v is None or v == "":
        return []
    return list(v) if isinstance(v, (list, MultiValue)) else [v]


def collect_identifiers(ds: Dataset) -> list[str]:
    """Strings that must not appear anywhere in the de-identified output."""
    found: set[str] = set()
    for kw in ("PatientID", "AccessionNumber", "OtherPatientIDs", "PatientBirthDate",
               "PatientTelephoneNumbers", "MedicalRecordLocator"):
        if kw in ds:
            found.update(str(v).strip() for v in _values(ds[kw]))
    if "PatientAddress" in ds:
        found.add(str(ds.PatientAddress).strip())
    for elem in ds.iterall():
        if elem.VR == "PN":
            for pn in _values(elem):
                for part in (pn.family_name, pn.given_name, pn.middle_name):
                    found.add(str(part).strip())
    return sorted(i for i in found if len(i) >= 3)


def burned_in_risk(ds: Dataset) -> str | None:
    flag = str(ds.get("BurnedInAnnotation", "") or "").strip().upper()
    if flag == "YES":
        return "BurnedInAnnotation=YES"
    if flag == "NO":
        return None
    modality = str(ds.get("Modality", "") or "")
    sop_class = str(ds.get("SOPClassUID", "") or "")
    if sop_class.startswith(SECONDARY_CAPTURE_ROOT):
        return "BurnedInAnnotation not set and image is a Secondary Capture (screenshots often carry burned-in text)"
    if modality in BURNED_IN_RISK_MODALITIES:
        return f"BurnedInAnnotation not set and modality {modality} often carries burned-in text"
    return None


def _age(ds: Dataset) -> int | None:
    birth = _parse_da(ds.get("PatientBirthDate"))
    ref = next(
        (d for d in (_parse_da(ds.get(k)) for k in ("StudyDate", "SeriesDate", "AcquisitionDate", "ContentDate")) if d),
        None,
    )
    if birth and ref:
        return age_at(birth, ref)
    age_str = str(ds.get("PatientAge", "") or "")
    if len(age_str) == 4 and age_str[:3].isdigit():
        return int(age_str[:3]) if age_str[3] == "Y" else 0
    return None


def _pseudonym_key(ds: Dataset) -> str:
    pid = str(ds.get("PatientID", "") or "").strip()
    if pid:
        return pid
    name = str(ds.get("PatientName", "") or "").strip()
    dob = str(ds.get("PatientBirthDate", "") or "").strip()
    if name or dob:
        return f"name:{name}|dob:{dob}"
    # Nothing to link on: treat each study as its own patient.
    return f"study:{ds.get('StudyInstanceUID', '')}"


def _remove_recursive(ds: Dataset, actions: Counter) -> None:
    for elem in list(ds):
        if elem.tag in _REMOVE_TAGS:
            del ds[elem.tag]
            actions["removed"] += 1
        elif elem.VR == "SQ":
            for item in elem.value:
                _remove_recursive(item, actions)


def _remove_groups(ds: Dataset, actions: Counter) -> None:
    for elem in list(ds):
        group = elem.tag.group
        if 0x5000 <= group <= 0x50FF or 0x6000 <= group <= 0x60FF:
            del ds[elem.tag]
            actions["overlay_curve_removed"] += 1
        elif elem.VR == "SQ":
            for item in elem.value:
                _remove_groups(item, actions)


def _shift_da(value: str, days: int) -> str:
    d = _parse_da(value)
    return shift_date(d, days).strftime("%Y%m%d") if d else ""


def _apply_generic(ds: Dataset, days: int, secret: bytes | None, actions: Counter) -> None:
    for elem in list(ds):
        vr = elem.VR
        if vr == "SQ":
            for item in elem.value:
                _apply_generic(item, days, secret, actions)
            continue
        vals = _values(elem)
        if not vals:
            continue
        if vr == "PN":
            elem.value = ""
            actions["person_name_emptied"] += 1
        elif vr == "DA":
            new = [_shift_da(v, days) for v in vals]
            elem.value = new if len(new) > 1 else new[0]
            actions["date_shifted"] += 1
        elif vr == "DT":
            new = [(_shift_da(str(v)[:8], days) + str(v)[8:]) if _parse_da(v) else "" for v in vals]
            elem.value = new if len(new) > 1 else new[0]
            actions["datetime_shifted"] += 1
        elif vr == "UI":
            keyword = elem.keyword or ""
            if keyword.endswith("ClassUID"):
                continue
            new = [str(v) if str(v).startswith(STANDARD_UID_ROOT) else remap_uid(str(v), secret) for v in vals]
            if new != [str(v) for v in vals]:
                elem.value = new if len(new) > 1 else new[0]
                actions["uid_remapped"] += 1


def deidentify(ds: Dataset, secret: bytes | None = None) -> DeidResult:
    """De-identify `ds` in place and return it with what was done."""
    actions: Counter = Counter()
    identifiers = collect_identifiers(ds)
    token = patient_token(_pseudonym_key(ds), secret)
    days = date_shift_days(token, secret)
    band = age_band(_age(ds))
    risk = burned_in_risk(ds)
    original_accession = str(ds.get("AccessionNumber", "") or "").strip()

    # 1. private tags, overlays, curves
    n_private = sum(1 for e in ds.iterall() if e.tag.is_private)
    ds.remove_private_tags()
    actions["private_removed"] = n_private
    _remove_groups(ds, actions)

    # 2-3. explicit removals and empties
    _remove_recursive(ds, actions)
    for kw in EMPTY_KEYWORDS:
        if kw in ds:
            ds[kw].value = ""
            actions["emptied"] += 1

    # 4. generic VR rules
    _apply_generic(ds, days, secret, actions)

    # 5. pseudonyms and free-text redaction
    ds.PatientName = token
    ds.PatientID = token
    if original_accession:
        ds.AccessionNumber = accession_token(original_accession, secret)
    for kw in TEXT_REDACT_KEYWORDS:
        if kw in ds and ds[kw].value:
            redacted = redact_free_text(str(ds[kw].value))
            if redacted != str(ds[kw].value):
                ds[kw].value = redacted
                actions["text_redacted"] += 1

    # 6. markers
    ds.PatientIdentityRemoved = "YES"
    ds.DeidentificationMethod = PROFILE_VERSION
    ds.LongitudinalTemporalInformationModified = "MODIFIED"

    meta = getattr(ds, "file_meta", None)
    if meta is not None:
        if "SOPInstanceUID" in ds:
            meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
        for kw in ("SourceApplicationEntityTitle", "SendingApplicationEntityTitle",
                   "ReceivingApplicationEntityTitle"):
            if kw in meta:
                del meta[kw]

    return DeidResult(
        dataset=ds,
        patient_token=token,
        shift_days=days,
        age_band=band,
        burned_in_risk=risk,
        actions=dict(actions),
        original_identifiers=identifiers,
    )
