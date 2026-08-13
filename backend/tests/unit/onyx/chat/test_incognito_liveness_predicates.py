"""Guards the split between "never started" and "explicitly ended".

A session holds no context until its first message, so absence and teardown
look identical in Redis. Anything deciding whether to accept new work must read
only the tombstone, or attaching a file before sending the first message is
rejected as an ended chat.
"""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from onyx.chat.incognito_context import (
    _TOMBSTONE,
    incognito_session_ended,
    incognito_session_torn_down,
)

MODULE = "onyx.chat.incognito_context"
LIVE_CONTEXT = b"1:[]"


def _with_stored(value: bytes | None) -> MagicMock:
    client = MagicMock()
    client.get.return_value = value
    return client


@pytest.mark.parametrize(
    "stored, torn_down, ended",
    [
        # Absence is the one row where the two predicates disagree, and the
        # reason a guard cannot be built on `ended`.
        (None, False, True),
        (_TOMBSTONE, True, True),
        (LIVE_CONTEXT, False, False),
    ],
    ids=["no_context_yet", "tombstoned", "live"],
)
def test_liveness_predicates_split_on_absence(
    stored: bytes | None, torn_down: bool, ended: bool
) -> None:
    with patch(f"{MODULE}.get_redis_client", return_value=_with_stored(stored)):
        assert incognito_session_torn_down(uuid4()) is torn_down
        assert incognito_session_ended(uuid4()) is ended
