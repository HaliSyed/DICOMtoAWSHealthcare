import numpy as np
import pydicom
import pytest
from PIL import Image
from pydicom.data import get_testdata_file

from conftest import REPO_ROOT
from dicom_deid.cli import main as cli_main
from dicom_deid.loader import export_png, iter_frames, load_frames, read_info, to_uint8

# Sample DICOM files committed under tests/data/dicom/, plus any extra files
# placed by hand in data/ (git-ignored, so those run only where they exist).
def _dicom_files(folder):
    return sorted(p for p in folder.glob("*") if p.suffix.lower() in (".dcm", ".dicom"))


SAMPLE_DICOM = _dicom_files(REPO_ROOT / "tests" / "data" / "dicom")
LOCAL_DICOM = SAMPLE_DICOM + [p for folder in (REPO_ROOT / "data", REPO_ROOT / "data" / "incoming")
                              for p in _dicom_files(folder) if p.name not in {s.name for s in SAMPLE_DICOM}]


@pytest.fixture
def multiframe(tmp_path):
    """4-frame 16-bit monochrome file; frame i is filled with value 100 * (i + 1)."""
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, generate_uid

    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.MediaStorageSOPClassUID = ds.SOPClassUID = SecondaryCaptureImageStorage
    ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID = generate_uid()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.Modality, ds.Rows, ds.Columns, ds.NumberOfFrames = "XA", 8, 8, 4
    ds.SamplesPerPixel, ds.PhotometricInterpretation = 1, "MONOCHROME2"
    ds.BitsAllocated, ds.BitsStored, ds.HighBit, ds.PixelRepresentation = 16, 12, 11, 0
    frames = np.stack([np.full((8, 8), 100 * (i + 1), dtype=np.uint16) for i in range(4)])
    frames[0, 0, 0] = 0  # give frame 0 some contrast
    ds.PixelData = frames.tobytes()
    path = tmp_path / "multiframe.dcm"
    ds.save_as(path, enforce_file_format=True)
    return path


def _sample(name):
    path = get_testdata_file(name, download=False)
    if path is None:
        pytest.skip(f"{name} not bundled with this pydicom")
    return path


def test_read_info_synthetic(synthetic_dir):
    path = next(synthetic_dir.rglob("IM*"))
    info = read_info(path)
    assert info.decodable and info.frames == 1 and info.rows == 16
    assert not info.identity_removed
    assert {"PatientName", "PatientID", "PatientBirthDate"} <= set(info.identifying_attributes_present)
    assert info.private_tag_count >= 2
    # values are never included, only attribute names
    ds = pydicom.dcmread(path)
    assert ds.PatientID not in str(info.as_dict())


@pytest.mark.parametrize("name,shape", [
    ("SC_rgb_jpeg_dcmtk.dcm", (100, 100, 3)),   # JPEG Baseline, colour
    ("MR_small_RLE.dcm", (64, 64)),             # RLE Lossless
    ("SC_rgb_rle.dcm", (100, 100, 3)),          # RLE colour
])
def test_compressed_frames_decode(name, shape):
    path = _sample(name)
    info = read_info(path)
    assert info.compressed and info.decodable
    frames = load_frames(path)
    assert frames.shape == (1, *shape)


def test_undecodable_is_reported_not_raised():
    path = _sample("JPEG-lossy.dcm")  # JPEG Extended: needs a plugin Pillow does not provide
    info = read_info(path)
    assert info.has_pixel_data and not info.decodable
    assert "no decoder" in info.decode_error


def test_multiframe_selection_and_uint8(multiframe):
    path = multiframe
    ds = pydicom.dcmread(path)
    assert read_info(path).frames == 4
    assert len(list(iter_frames(path))) == 4
    picked = load_frames(path, indices=[0, 2])
    assert picked.shape == (2, 8, 8)
    assert picked[1].max() == 300 and np.array_equal(picked[1], list(iter_frames(path))[2])
    img = to_uint8(picked[0], ds)
    assert img.dtype == np.uint8 and img.min() == 0 and img.max() == 255


def test_export_png(multiframe, tmp_path):
    written = export_png(multiframe, tmp_path / "png", every_nth=2)
    assert [p.name for p in written] == ["multiframe_f0000.png", "multiframe_f0002.png"]
    assert len(export_png(multiframe, tmp_path / "png2", max_frames=3)) == 3
    assert all(Image.open(p).mode == "L" for p in written)


def test_cli_inspect(synthetic_dir, capsys):
    assert cli_main(["inspect", str(synthetic_dir)]) == 0
    out = capsys.readouterr().out
    assert "DICOM file(s)" in out
    ds = pydicom.dcmread(next(synthetic_dir.rglob("IM*")))
    assert ds.PatientID not in out and str(ds.PatientName.family_name) not in out


@pytest.mark.skipif(not LOCAL_DICOM, reason="no sample DICOM files found")
@pytest.mark.parametrize("path", LOCAL_DICOM, ids=lambda p: p.name)
def test_local_dicom_files_fully_decode(path):
    info = read_info(path)
    assert info.decodable, info.decode_error
    count = 0
    for frame in iter_frames(path):
        assert frame.shape[:2] == (info.rows, info.columns)
        count += 1
    assert count == info.frames
    ds = pydicom.dcmread(path)
    rgb_or_grey = to_uint8(frame, ds)
    assert rgb_or_grey.dtype == np.uint8
