"""Admission distinguishes never-started sessions from explicit teardown."""

from unittest.mock import patch
from uuid import uuid4

import pytest

from onyx.chat.incognito_context import (
    _context_key,
    _tombstone_key,
    incognito_session_ended,
    incognito_session_torn_down,
    incognito_sessions_ended,
)
from onyx.chat.models import IncognitoState
from tests.unit.fakes import FakeCache


@pytest.mark.parametrize(
    "has_context, torn_down, ended",
    [(False, False, True), (True, True, True), (True, False, False)],
    ids=["never-started", "tombstoned", "live"],
)
def test_liveness_distinguishes_absence_from_teardown(
    has_context: bool, torn_down: bool, ended: bool
) -> None:
    cache = FakeCache()
    session_id = uuid4()
    if has_context:
        cache.set(_context_key(session_id), IncognitoState(version=1).model_dump_json())
    if torn_down:
        cache.set(_tombstone_key(session_id), 1)
    with patch("onyx.chat.incognito_context._cache", return_value=cache):
        assert incognito_session_torn_down(session_id) is torn_down
        assert incognito_session_ended(session_id) is ended


def test_batch_excludes_live_sessions_and_deduplicates_expired_sessions() -> None:
    cache = FakeCache()
    live, expired, ended = uuid4(), uuid4(), uuid4()
    for session in (live, ended):
        cache.set(_context_key(session), IncognitoState(version=1).model_dump_json())
    cache.set(_tombstone_key(ended), 1)
    with patch("onyx.chat.incognito_context._cache", return_value=cache):
        assert incognito_sessions_ended([live, expired, ended, expired]) == {
            expired,
            ended,
        }


def test_liveness_batches_keys_without_reading_context_values() -> None:
    cache = FakeCache()
    sessions = [uuid4() for _ in range(200)]
    for session_id in sessions:
        cache.set(_context_key(session_id), b"private content")
    with (
        patch("onyx.chat.incognito_context._cache", return_value=cache),
        patch.object(cache, "exists_many", wraps=cache.exists_many) as exists_many,
        patch.object(cache, "exists", side_effect=AssertionError("individual lookup")),
        patch.object(cache, "get", side_effect=AssertionError("content lookup")),
    ):
        assert incognito_sessions_ended(sessions) == set()
    exists_many.assert_called_once()
    assert len(exists_many.call_args.args[0]) == 400
