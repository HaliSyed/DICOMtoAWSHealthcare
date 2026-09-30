"""
Synthetic DICOM generator -- realistic headers, fake people, noise pixels.

Every person, ID, address and institution is invented (Faker, fixed seed).
The files are deliberately "dirty" in the ways real archives are, so the
pipeline has something to prove itself against:

  * PHI in standard tags (name, MRN, DOB, address, phone, physicians)
  * a UAE-format national ID in OtherPatientIDs
  * PHI hidden in a vendor private tag block
  * a person name nested inside a sequence
  * a patient name typed into a free-text StudyDescription
  * ultrasound with BurnedInAnnotation=YES, and one with the flag missing
  * folder names built from patient names (why source paths are never stored)
  * one non-DICOM file mixed in
  * several studies per patient (to prove longitudinal linkage survives)
"""

import random
from datetime import date, timedelta
from pathlib import Path

from faker import Faker
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.sequence import Sequence
from pydicom.uid import (
    CTImageStorage,
    ExplicitVRLittleEndian,
    MRImageStorage,
    UltrasoundImageStorage,
    generate_uid,
)

REFERENCE_DATE = date(2026, 9, 29)  # fixed, so output is identical on every run

MODALITIES = {
    "CT": (CTImageStorage, ["CHEST", "ABDOMEN", "HEAD", "PELVIS"], 16),
    "MR": (MRImageStorage, ["HEAD", "KNEE", "SPINE", "SHOULDER"], 16),
    "US": (UltrasoundImageStorage, ["ABDOMEN", "BREAST", "PELVIS"], 8),
}
DESCRIPTIONS = {
    "CHEST": "Routine chest screening", "ABDOMEN": "Abdominal pain workup",
    "HEAD": "Post-trauma head imaging", "PELVIS": "Pelvic pain workup",
    "KNEE": "Post-injury knee MRI", "SPINE": "Lower back pain evaluation",
    "SHOULDER": "Rotator cuff evaluation", "BREAST": "Breast lesion follow-up",
}
HOSPITALS = ["Northgate General Hospital", "Meridian Health Center", "Crestline Diagnostics"]
MANUFACTURERS = ["Siemens Healthineers", "GE HealthCare", "Philips", "Canon Medical"]


def _uid(*parts) -> str:
    return generate_uid(entropy_srcs=[str(p) for p in parts])


def _emirates_id(rng: random.Random, birth_year: int) -> str:
    return f"784-{birth_year}-{rng.randint(0, 9999999):07d}-{rng.randint(0, 9)}"


def _instance(rng, fake_person, study, series, n, size) -> Dataset:
    sop_class, _, bits = MODALITIES[series["modality"]]
    sop_uid = _uid(series["uid"], n)

    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = sop_class
    meta.MediaStorageSOPInstanceUID = sop_uid
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.SourceApplicationEntityTitle = "NORTHGATE_PACS"

    ds = Dataset()
    ds.file_meta = meta
    p = fake_person
    ds.SOPClassUID, ds.SOPInstanceUID = sop_class, sop_uid
    ds.StudyInstanceUID, ds.SeriesInstanceUID = study["uid"], series["uid"]
    ds.FrameOfReferenceUID = _uid(series["uid"], "for")
    ds.Modality = series["modality"]
    ds.StudyDate = ds.SeriesDate = ds.AcquisitionDate = ds.ContentDate = study["date"].strftime("%Y%m%d")
    ds.StudyTime = ds.SeriesTime = "093015"
    ds.AccessionNumber = study["accession"]
    ds.StudyID = study["study_id"]
    ds.StudyDescription = study["description"]
    ds.SeriesDescription = f"{series['modality']} {series['body_part'].title()} series {series['number']}"
    ds.SeriesNumber, ds.InstanceNumber = series["number"], n
    ds.BodyPartExamined = series["body_part"]

    ds.PatientName = f"{p['last']}^{p['first']}"
    ds.PatientID = p["mrn"]
    ds.PatientBirthDate = p["dob"].strftime("%Y%m%d")
    ds.PatientSex = p["sex"]
    age = study["date"].year - p["dob"].year - ((study["date"].month, study["date"].day) < (p["dob"].month, p["dob"].day))
    ds.PatientAge = f"{age:03d}Y"
    ds.PatientAddress = p["address"]
    ds.PatientTelephoneNumbers = p["phone"]
    ds.OtherPatientIDs = p["national_id"]
    ds.ReferringPhysicianName = study["referrer"]
    ds.PerformingPhysicianName = study["performer"]
    ds.OperatorsName = study["operator"]
    ds.InstitutionName = study["hospital"]
    ds.InstitutionAddress = study["hospital_address"]
    ds.StationName = f"{series['modality']}-ROOM-{rng.randint(1, 4)}"
    ds.Manufacturer = series["manufacturer"]
    ds.DeviceSerialNumber = f"SN{rng.randint(100000, 999999)}"

    request = Dataset()
    request.RequestedProcedureID = f"RP{rng.randint(10000, 99999)}"
    request.ScheduledProcedureStepID = f"SPS{rng.randint(10000, 99999)}"
    request.ScheduledPerformingPhysicianName = study["performer"]
    ds.RequestAttributesSequence = Sequence([request])

    block = ds.private_block(0x0009, "NORTHGATE_PACS_1", create=True)
    block.add_new(0x01, "LO", f"{p['first']} {p['last']}")
    block.add_new(0x02, "LO", p["mrn"])

    if series["modality"] in ("CT", "MR"):
        ds.SliceThickness = rng.choice(["1.0", "2.5", "5.0"])
    ds.PixelSpacing = [f"{rng.uniform(0.3, 1.0):.3f}"] * 2
    if series["burned_in"] is not None:
        ds.BurnedInAnnotation = series["burned_in"]

    ds.Rows = ds.Columns = size
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = ds.BitsStored = bits
    ds.HighBit = bits - 1
    ds.PixelRepresentation = 0
    ds.PixelData = rng.randbytes(size * size * (bits // 8))
    return ds


def generate(out_dir: Path, patients: int = 6, seed: int = 42, size: int = 64) -> list[Path]:
    fake = Faker()
    fake.seed_instance(seed)
    rng = random.Random(seed)
    out_dir = Path(out_dir)
    written: list[Path] = []

    for pi in range(patients):
        dob = REFERENCE_DATE - timedelta(days=rng.randint(18 * 365, 88 * 365))
        person = {
            "first": fake.first_name(), "last": fake.last_name(), "sex": rng.choice("MF"),
            "mrn": f"MRN{rng.randint(1000000, 9999999)}", "dob": dob,
            "address": fake.address().replace("\n", ", "), "phone": fake.numerify("+971-5#-###-####"),
            "national_id": _emirates_id(rng, dob.year),
        }
        study_date = REFERENCE_DATE - timedelta(days=rng.randint(200, 900))
        for si in range(rng.randint(1, 3)):
            study_date += timedelta(days=rng.randint(20, 150))
            modality = rng.choice(list(MODALITIES))
            body_part = rng.choice(MODALITIES[modality][1])
            description = DESCRIPTIONS[body_part]
            if pi == 0 and si == 0:
                description += f" - {person['first']} {person['last']}"  # PHI typed into free text
            study = {
                "uid": _uid(seed, pi, si), "date": study_date, "description": description,
                "accession": f"ACC{rng.randint(100000, 999999)}", "study_id": str(rng.randint(1000, 9999)),
                "referrer": f"{fake.last_name()}^{fake.first_name()}^^Dr.",
                "performer": f"{fake.last_name()}^{fake.first_name()}",
                "operator": f"{fake.last_name()}^{fake.first_name()}",
                "hospital": rng.choice(HOSPITALS), "hospital_address": fake.address().replace("\n", ", "),
            }
            folder = out_dir / f"{person['last']}_{person['first']}" / f"{study_date:%Y-%m-%d}_{modality}"
            for se in range(1, rng.randint(1, 2) + 1):
                series = {
                    "uid": _uid(study["uid"], se), "modality": modality, "body_part": body_part,
                    "number": se, "manufacturer": rng.choice(MANUFACTURERS),
                    # US: flag set to YES, or missing entirely (both must be quarantined)
                    "burned_in": rng.choice(["YES", None]) if modality == "US" else "NO",
                }
                for n in range(1, rng.randint(1, 3) + 1):
                    ds = _instance(rng, person, study, series, n, size)
                    path = folder / f"series{se}" / f"IM{n:04d}"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    ds.save_as(path, enforce_file_format=True)
                    written.append(path)

    notes = out_dir / "transfer_notes.txt"
    notes.write_text("Batch exported from PACS. Not a DICOM file.\n", encoding="utf-8")
    return written
