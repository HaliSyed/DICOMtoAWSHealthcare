"""
Runtime configuration, read from environment variables (or a local .env).

Only the keys this package needs are read from .env -- anything else in that
file (e.g. unrelated tokens) is ignored and never enters the process env.
"""

import os
import warnings
from pathlib import Path

DEV_SECRET = "dev-only-insecure-secret-do-not-use-with-real-data"
DEFAULT_DATABASE_URL = "sqlite:///data/db/deid.sqlite"
_KEYS = ("DEID_SECRET", "DATABASE_URL")
_warned = False


def _read_dotenv(path: Path = Path(".env")) -> dict:
    values = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key in _KEYS and value.strip():
            values[key] = value.strip().strip('"').strip("'")
    return values


def _get(key: str) -> str | None:
    return os.environ.get(key) or _read_dotenv().get(key)


def get_secret() -> bytes:
    """
    Key for all HMAC-based pseudonymisation. With real data this MUST be a
    managed secret (e.g. AWS Secrets Manager / KMS) -- anyone holding it can
    re-compute tokens from known MRNs.
    """
    global _warned
    secret = _get("DEID_SECRET")
    if not secret:
        if not _warned:
            warnings.warn(
                "DEID_SECRET not set -- using the built-in development secret. "
                "Fine for synthetic data, never for real patient data.",
                stacklevel=2,
            )
            _warned = True
        secret = DEV_SECRET
    return secret.encode("utf-8")


def get_database_url() -> str:
    return _get("DATABASE_URL") or DEFAULT_DATABASE_URL
