from typing import Any

import pytest

from onyx.connectors.microsoft_utils.config import configured_ru_per_minute


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        (600, 600),
        # The write path validates a numeric string and stores it as sent.
        ("600", 600),
        (None, None),
        (0, None),
        ("0", None),
        ("-5", None),
        ("6.5", None),
        # The write path validates with the same model, which reads true as 1.
        (True, 1),
    ],
)
def test_the_stored_ru_per_minute(stored: Any, expected: int | None) -> None:
    assert configured_ru_per_minute({"ru_per_minute": stored}) == expected
