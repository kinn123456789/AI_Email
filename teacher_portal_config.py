"""
Centralized configuration for the Teacher Portal API.

teacher_portal_api_reader.py (reads) and teacher_api_sender.py (writes) both
source their base URL, auth headers, and request timeout from here, so the
preprod -> production switch is a single environment variable change with no
code change required.
"""

import os
from dotenv import load_dotenv

load_dotenv()

DEFAULT_BASE_URL = "https://api.preprod.coralacademy.com"


def get_base_url():
    """Teacher Portal API base URL. Defaults to preprod; set
    TEACHER_PORTAL_BASE_URL to point at a different environment without a
    code change."""
    return os.getenv("TEACHER_PORTAL_BASE_URL", DEFAULT_BASE_URL)


def get_api_key():
    """Teacher Portal API key, read from the environment."""
    return os.getenv("TEACHER_PORTAL_API_KEY")


def get_timeout(default_seconds):
    """Request timeout in seconds. Set TEACHER_PORTAL_TIMEOUT to override;
    falls back to the caller-provided default if unset or invalid."""
    value = os.getenv("TEACHER_PORTAL_TIMEOUT")
    if not value:
        return default_seconds
    try:
        return float(value)
    except ValueError:
        return default_seconds


def build_headers(api_key, extra=None):
    """Builds the x-api-key auth header, raising a clear error if the key is
    missing. `api_key` is passed in rather than read from the environment
    here, so callers (and their tests) can still override it directly on
    their own module."""
    if not api_key:
        raise ValueError(
            "TEACHER_PORTAL_API_KEY is not configured. Set it in your environment or .env file."
        )

    headers = {"x-api-key": api_key}

    if extra:
        headers.update(extra)

    return headers
