"""HTTP to GitHub and Jev."""

import json
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any

__all__ = ["request_json"]

RETRY_STATUSES: frozenset[int] = frozenset({429, 500, 502, 503, 504, 529})
MAX_ATTEMPTS: int = 5


def request_json(
    url: str,
    method: str = "GET",
    headers: Mapping[str, str] | None = None,
    body: object | None = None,
    timeout: float = 60.0,
) -> Any:
    """Send one JSON request and return the parsed body, or None for an empty one.

    Retries RETRY_STATUSES and network errors with exponential backoff, then raises.
    """
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(MAX_ATTEMPTS):
        request = urllib.request.Request(  # noqa: S310
            url,
            data=data,
            method=method,
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
                raw = response.read()
            return json.loads(raw) if raw else None
        except urllib.error.HTTPError as error:
            if error.code not in RETRY_STATUSES or attempt == MAX_ATTEMPTS - 1:
                detail = error.read()[:500].decode(errors="replace")
                raise RuntimeError(
                    f"{method} {url} returned {error.code}: {detail}"
                ) from error
            retry_after = error.headers.get("Retry-After", "")
            time.sleep(float(retry_after) if retry_after.isdigit() else 2**attempt)
        except (urllib.error.URLError, TimeoutError) as error:
            if attempt == MAX_ATTEMPTS - 1:
                raise RuntimeError(f"{method} {url} failed: {error}") from error
            time.sleep(2**attempt)
    raise AssertionError("unreachable")
