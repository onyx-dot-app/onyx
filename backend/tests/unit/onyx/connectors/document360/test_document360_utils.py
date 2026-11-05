"""Regression tests for Document360 datetime parsing (issue #14117).

Document360 returns timestamps in ISO-8601 format with a trailing 'Z',
but the fractional-seconds portion is optional.  The old strptime format
string required ``.%f`` and failed when no fractional seconds were present.
"""

from datetime import datetime, timezone

import pytest

# We test the helper directly so we don't need the full connector import graph.
from onyx.connectors.document360.utils import parse_document360_datetime


@pytest.mark.parametrize(
    "raw, expected",
    [
        # No fractional seconds
        (
            "2025-02-03T14:06:14Z",
            datetime(2025, 2, 3, 14, 6, 14, tzinfo=timezone.utc),
        ),
        # Three-digit fractional seconds
        (
            "2025-04-24T09:23:54.494Z",
            datetime(2025, 4, 24, 9, 23, 54, 494_000, tzinfo=timezone.utc),
        ),
        # Two-digit fractional seconds
        (
            "2026-01-05T14:48:29.93Z",
            datetime(2026, 1, 5, 14, 48, 29, 930_000, tzinfo=timezone.utc),
        ),
    ],
    ids=[
        "no_fractional",
        "three_digit_fractional",
        "two_digit_fractional",
    ],
)
def test_parse_document360_datetime(raw: str, expected: datetime) -> None:
    result = parse_document360_datetime(raw)
    assert result == expected
    assert result.tzinfo is timezone.utc
