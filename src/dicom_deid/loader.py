"""
Reading DICOM files as they arrive: header summary and decoded pixel frames.

This is the entry point for handling real-world files (multi-frame
angiography, cine ultrasound, compressed transfer syntaxes) before or
alongside de-identification:

  read_info(path)        -> DicomFileInfo   PHI-free summary of one file
  iter_frames(path)      -> numpy arrays    one decoded frame at a time
  load_frames(path)      -> numpy array     all (or selected) frames at once
  to_uint8(frame, ds)    -> numpy array     8-bit display version of a frame
  export_png(path, dir)  -> [Path]          frames as PNG previews

Nothing here returns or prints PHI values. read_info() reports WHICH
identifying attributes are present, never what they contain. PNG previews
are the raw pixels, so burned-in text survives. Treat them as PHI and keep
them under git-ignored data/dicom/.

Decoding uses pydicom's pixel handlers: RLE natively, JPEG Baseline and
JPEG 2000 via Pillow. JPEG Extended / Lossless / JPEG-LS need an extra
plugin (e.g. pylibjpeg); read_info() reports this as not decodable rather
than failing.
"""

from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pydicom
from pydicom.dataset import Dataset
from pydicom.pixels import apply_color_lut, apply_voi_lut, iter_pixels

from .dicom_deid import burned_in_risk

# Attributes whose presence (not value) is reported by read_info().
IDENTIFYING_KEYWORDS = [
    "PatientName", "PatientID", "PatientBirthDate", "OtherPatientIDs", "PatientAddress",
    "PatientTelephoneNumbers", "AccessionNumber", "ReferringPhysicianName",
    "PerformingPhysicianName", "OperatorsName", "InstitutionName", "InstitutionAddress",
    "StationName", "DeviceSerialNumber",
]


@dataclass
class DicomFileInfo:
    file_name: str
    file_size_bytes: int
    modality: str | None
    sop_class: str
    transfer_syntax: str
    compressed: bool
    rows: int | None
    columns: int | None
    frames: int
    samples_per_pixel: int | None
    photometric_interpretation: str | None
    bits_allocated: int | None
    bits_stored: int | None
    frame_time_ms: float | None
    has_pixel_data: bool
    decodable: bool
    decode_error: str | None
    identity_removed: bool
    identifying_attributes_present: list = field(default_factory=list)
    private_tag_count: int = 0
    burned_in_risk: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def _dataset(src: Path | str | Dataset, stop_before_pixels: bool = False) -> Dataset:
    return src if isinstance(src, Dataset) else pydicom.dcmread(src, stop_before_pixels=stop_before_pixels)


def _int(ds: Dataset, kw: str) -> int | None:
    try:
        return int(ds.get(kw)) if ds.get(kw) not in (None, "") else None
    except (TypeError, ValueError):
        return None


def frame_count(ds: Dataset) -> int:
    return _int(ds, "NumberOfFrames") or 1


def read_info(path: Path | str) -> DicomFileInfo:
    """Header summary plus a test decode of the first frame."""
    path = Path(path)
    ds = pydicom.dcmread(path)
    ts = ds.file_meta.TransferSyntaxUID
    has_pixels = "PixelData" in ds or "FloatPixelData" in ds or "DoubleFloatPixelData" in ds

    decodable, error = False, None
    if has_pixels:
        try:
            next(iter_pixels(ds))
            decodable = True
        except Exception as exc:  # noqa: BLE001 -- report, don't fail
            error = f"{type(exc).__name__}: no decoder available for {ts.name}" \
                if isinstance(exc, (RuntimeError, NotImplementedError)) else type(exc).__name__

    frame_time = ds.get("FrameTime")
    return DicomFileInfo(
        file_name=path.name,
        file_size_bytes=path.stat().st_size,
        modality=str(ds.get("Modality") or "") or None,
        sop_class=getattr(ds.get("SOPClassUID"), "name", str(ds.get("SOPClassUID", ""))),
        transfer_syntax=ts.name,
        compressed=ts.is_compressed,
        rows=_int(ds, "Rows"),
        columns=_int(ds, "Columns"),
        frames=frame_count(ds),
        samples_per_pixel=_int(ds, "SamplesPerPixel"),
        photometric_interpretation=str(ds.get("PhotometricInterpretation") or "") or None,
        bits_allocated=_int(ds, "BitsAllocated"),
        bits_stored=_int(ds, "BitsStored"),
        frame_time_ms=float(frame_time) if frame_time not in (None, "") else None,
        has_pixel_data=has_pixels,
        decodable=decodable,
        decode_error=error,
        identity_removed=str(ds.get("PatientIdentityRemoved", "")).upper() == "YES",
        identifying_attributes_present=[k for k in IDENTIFYING_KEYWORDS if str(ds.get(k, "") or "").strip()],
        private_tag_count=sum(1 for e in ds.iterall() if e.tag.is_private),
        burned_in_risk=burned_in_risk(ds),
    )


def iter_frames(src: Path | str | Dataset) -> Iterator[np.ndarray]:
    """
    Decoded frames one at a time (rows x cols, or rows x cols x 3 for colour,
    converted to RGB). Keeps memory flat for long cine loops.
    """
    yield from iter_pixels(_dataset(src))


def load_frames(src: Path | str | Dataset, indices: list[int] | None = None) -> np.ndarray:
    """All frames as one array (frames x rows x cols[ x 3]), or only `indices`."""
    wanted = set(indices) if indices is not None else None
    frames = [f for i, f in enumerate(iter_frames(src)) if wanted is None or i in wanted]
    if not frames:
        raise ValueError("no frames selected")
    return np.stack(frames)


def to_uint8(frame: np.ndarray, ds: Dataset) -> np.ndarray:
    """
    8-bit display version: applies the file's VOI LUT / window if it has one,
    otherwise stretches min..max. MONOCHROME1 is inverted so bone is white.
    PALETTE COLOR (common in ultrasound) is expanded through its colour table.
    """
    if str(ds.get("PhotometricInterpretation", "")) == "PALETTE COLOR":
        rgb = apply_color_lut(frame, ds)
        return rgb if rgb.dtype == np.uint8 else (rgb >> 8).astype(np.uint8)
    data = frame
    if ds.get("SamplesPerPixel", 1) == 1:
        data = apply_voi_lut(frame, ds) if ("WindowCenter" in ds or "VOILUTSequence" in ds) else frame
    data = data.astype(np.float64)
    lo, hi = float(data.min()), float(data.max())
    out = np.zeros_like(data) if hi == lo else (data - lo) / (hi - lo) * 255.0
    if str(ds.get("PhotometricInterpretation", "")) == "MONOCHROME1":
        out = 255.0 - out
    return out.round().astype(np.uint8)


def export_png(path: Path | str, out_dir: Path | str, every_nth: int = 1, max_frames: int | None = None) -> list[Path]:
    """
    Write frames as PNG previews: <out_dir>/<file stem>_f0000.png ...
    The pixels are unmodified, so burned-in text is still there. Treat the output as PHI.
    """
    from PIL import Image

    path, out_dir = Path(path), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ds = pydicom.dcmread(path)
    written: list[Path] = []
    for i, frame in enumerate(iter_frames(ds)):
        if i % every_nth:
            continue
        if max_frames is not None and len(written) >= max_frames:
            break
        target = out_dir / f"{path.stem}_f{i:04d}.png"
        Image.fromarray(to_uint8(frame, ds)).save(target)
        written.append(target)
    return written
