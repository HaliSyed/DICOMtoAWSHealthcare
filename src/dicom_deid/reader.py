"""Finding DICOM files and extracting the metadata we index in the database."""

from datetime import date
from pathlib import Path

from pydicom.dataset import Dataset
from pydicom.multival import MultiValue
from pydicom.tag import Tag

PIXEL_DATA = Tag("PixelData")
SKIP_NAMES = {"DICOMDIR"}


def iter_candidate_files(root: Path):
    """Every regular file under root, in stable order. DICOM files often have no extension."""
    root = Path(root)
    if root.is_file():
        yield root
        return
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        if path.name.upper() not in SKIP_NAMES and not path.name.startswith("."):
            yield path


def _s(ds: Dataset, kw: str) -> str | None:
    v = ds.get(kw)
    if v is None:
        return None
    if isinstance(v, MultiValue):
        v = "\\".join(str(x) for x in v)
    s = str(v).strip()
    return s or None


def _i(ds: Dataset, kw: str) -> int | None:
    try:
        return int(ds.get(kw)) if ds.get(kw) not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _f(ds: Dataset, kw: str) -> float | None:
    try:
        return float(ds.get(kw)) if ds.get(kw) not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _da(ds: Dataset, kw: str) -> date | None:
    s = _s(ds, kw)
    if not s or len(s) < 8 or not s[:8].isdigit():
        return None
    try:
        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except ValueError:
        return None


def extract_metadata(ds: Dataset) -> dict:
    """
    Study / series / instance level fields from an ALREADY de-identified
    dataset. Calling this on raw data would put PHI in the database.
    """
    return {
        "patient": {"sex": _s(ds, "PatientSex")},
        "study": {
            "study_instance_uid": _s(ds, "StudyInstanceUID"),
            "study_date_shifted": _da(ds, "StudyDate"),
            "study_time": _s(ds, "StudyTime"),
            "accession_token": _s(ds, "AccessionNumber"),
            "study_description": _s(ds, "StudyDescription"),
        },
        "series": {
            "series_instance_uid": _s(ds, "SeriesInstanceUID"),
            "modality": _s(ds, "Modality"),
            "body_part_examined": _s(ds, "BodyPartExamined"),
            "series_description": _s(ds, "SeriesDescription"),
            "series_number": _i(ds, "SeriesNumber"),
            "series_date_shifted": _da(ds, "SeriesDate"),
            "manufacturer": _s(ds, "Manufacturer"),
        },
        "instance": {
            "sop_instance_uid": _s(ds, "SOPInstanceUID"),
            "sop_class_uid": _s(ds, "SOPClassUID"),
            "instance_number": _i(ds, "InstanceNumber"),
            "rows": _i(ds, "Rows"),
            "columns": _i(ds, "Columns"),
            "slice_thickness": _f(ds, "SliceThickness"),
            "pixel_spacing": _s(ds, "PixelSpacing"),
            "photometric_interpretation": _s(ds, "PhotometricInterpretation"),
        },
    }


def to_dicom_json(ds: Dataset) -> dict:
    """
    Full header as DICOM JSON (PS3.18 Annex F), without pixel data or other
    bulk binary values. This is the same model DICOMweb and AWS HealthImaging
    use, so Phase 2's FHIR ImagingStudy mapping can read from it directly.
    """
    header = Dataset()
    for elem in ds:
        if elem.tag != PIXEL_DATA:
            header.add(elem)
    return header.to_json_dict(
        bulk_data_threshold=1024,
        bulk_data_element_handler=lambda _elem: "omitted:bulk-data",
    )
