import warnings
from pathlib import Path

import pytest

from dicom_deid.synthetic import generate

REPO_ROOT = Path(__file__).resolve().parent.parent
TEST_SECRET = b"unit-test-secret"

warnings.filterwarnings("ignore", message="DEID_SECRET not set")


@pytest.fixture(scope="session")
def synthetic_dir(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("raw")
    generate(out, patients=5, seed=42, size=16)
    return out
