"""Shared helpers for the CSV/Excel retrieval benchmark scripts.

Run those scripts as modules from ``backend/`` so this package resolves:

    uv run python -m scripts.run_csv_benchmark_cycle --label x ...
"""

from typing import TypedDict
from urllib.parse import urlencode

import requests

# Every request carries a timeout. A stalled call must not outlive the polling
# deadlines the callers set, which are only checked between requests.
REQUEST_TIMEOUT_S = 60


class SearchDoc(TypedDict, total=False):
    """The fields of a search hit that scoring reads."""

    semantic_identifier: str
    score: float | None


def login(base_url: str, email: str, password: str) -> dict[str, str]:
    """Authenticate and return headers carrying the session cookie."""
    resp = requests.post(
        f"{base_url}/api/auth/login",
        data=urlencode({"username": email, "password": password}),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=REQUEST_TIMEOUT_S,
    )
    resp.raise_for_status()
    cookie = resp.cookies.get("fastapiusersauth")
    if not cookie:
        raise RuntimeError("Login succeeded but no fastapiusersauth cookie")
    return {
        "Content-Type": "application/json",
        "Cookie": f"fastapiusersauth={cookie}",
    }
