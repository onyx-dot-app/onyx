"""Guards which incognito sessions the upload endpoint accepts files for.

Switching incognito on mints the session id client-side, so uploads arrive
naming a session that holds no context until its first message. Only a teardown
tombstone closes a session to new files, and an upload that overlaps one has to
claim its own rows however the request ends.
"""

from dataclasses import dataclass
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import BackgroundTasks

from onyx.chat.incognito_context import _TOMBSTONE
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.projects.api import upload_user_files

MODULE = "onyx.server.features.projects.api"
CONTEXT_MODULE = "onyx.chat.incognito_context"
# No context key exists until the first message of a session is sent.
NO_CONTEXT_YET = None


@dataclass
class Attempt:
    """What one upload request did, including how it ended."""

    wrote_rows: bool
    claimed_rows: bool
    error: Exception | None


def _upload(
    *,
    stored: list[bytes | None],
    allowed: bool = True,
    upload_fails: bool = False,
) -> Attempt:
    """Run the endpoint against a fresh incognito session id.

    *stored* is what Redis holds for the context key on the pre-check and then
    the post-check, which is the only thing separating an ordinary upload from
    one racing a teardown.
    """
    redis_client = MagicMock()
    redis_client.get.side_effect = list(stored)
    with (
        patch(f"{MODULE}.incognito_allowed_for_user", return_value=allowed),
        patch(f"{CONTEXT_MODULE}.get_redis_client", return_value=redis_client),
        patch(
            f"{MODULE}.upload_files_to_user_files_with_indexing",
            side_effect=ConnectionError("indexing hand-off failed")
            if upload_fails
            else None,
        ) as upload_impl,
        patch(f"{MODULE}.mark_incognito_user_files_deleting") as mark,
        patch(f"{MODULE}.CategorizedFilesSnapshot"),
    ):
        error: Exception | None = None
        try:
            upload_user_files(
                bg_tasks=BackgroundTasks(),
                files=[],
                project_id=None,
                temp_id_map=None,
                incognito_session_id=uuid4(),
                user=MagicMock(id=uuid4()),
                db_session=MagicMock(),
            )
        except Exception as raised:
            error = raised
        return Attempt(
            wrote_rows=upload_impl.call_count == 1,
            claimed_rows=mark.call_count == 1,
            error=error,
        )


def test_a_session_that_has_sent_no_message_yet_accepts_the_upload() -> None:
    """The case that rejected the first attachment of every new incognito
    chat: no message sent, so no context key exists."""
    attempt = _upload(stored=[NO_CONTEXT_YET, NO_CONTEXT_YET])

    assert attempt.error is None
    assert attempt.wrote_rows
    assert not attempt.claimed_rows


def test_an_upload_racing_teardown_is_queued_for_deletion() -> None:
    attempt = _upload(stored=[NO_CONTEXT_YET, _TOMBSTONE])

    assert attempt.claimed_rows


def test_an_upload_that_fails_after_writing_still_claims_its_rows() -> None:
    """Rows are committed before the indexing hand-off, which can still fail,
    so a torn-down session's files must not be left stored and unmarked."""
    attempt = _upload(stored=[NO_CONTEXT_YET, _TOMBSTONE], upload_fails=True)

    assert attempt.error is not None
    assert attempt.claimed_rows


def test_an_upload_into_an_ended_session_never_writes_a_row() -> None:
    attempt = _upload(stored=[_TOMBSTONE])

    assert isinstance(attempt.error, OnyxError)
    assert attempt.error.error_code is OnyxErrorCode.INVALID_INPUT
    assert not attempt.wrote_rows


def test_a_user_without_incognito_is_refused() -> None:
    attempt = _upload(stored=[], allowed=False)

    assert isinstance(attempt.error, OnyxError)
    assert attempt.error.error_code is OnyxErrorCode.UNAUTHORIZED
    assert not attempt.wrote_rows
