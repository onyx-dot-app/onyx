"""Guards which incognito sessions the upload endpoint accepts files for.

The guard must read the teardown tombstone alone, since an absent context key
means the session is new: switching incognito on mints the id client-side, so
uploads arrive naming a session that holds no context until its first message.
"""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import BackgroundTasks

from onyx.chat.incognito_context import _TOMBSTONE
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.projects.api import upload_user_files

MODULE = "onyx.server.features.projects.api"
CONTEXT_MODULE = "onyx.chat.incognito_context"
# No context key exists until the first message of a session is sent.
NO_CONTEXT_YET = None


def _upload(
    *,
    stored_before: bytes | None = NO_CONTEXT_YET,
    stored_after: bytes | None = NO_CONTEXT_YET,
    allowed: bool = True,
    expect_upload: bool = True,
) -> MagicMock:
    """Runs the endpoint against a fresh incognito session id and returns the
    marking helper, so the caller can assert whether cleanup was queued.

    *stored_before* and *stored_after* are what Redis holds for the context key
    on the pre-check and the post-check. Driving the store rather than the
    predicate keeps the assertion on which verdict the endpoint asks for.
    """
    redis_client = MagicMock()
    redis_client.get.side_effect = [stored_before, stored_after]
    with (
        patch(f"{MODULE}.incognito_allowed_for_user", return_value=allowed),
        patch(f"{CONTEXT_MODULE}.get_redis_client", return_value=redis_client),
        patch(f"{MODULE}.upload_files_to_user_files_with_indexing") as upload_impl,
        patch(f"{MODULE}.mark_incognito_user_files_deleting") as mark,
        patch(f"{MODULE}.CategorizedFilesSnapshot"),
    ):
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
        finally:
            # In a finally so a refused upload still asserts nothing was
            # written. A guard moved below the write would pass otherwise.
            assert upload_impl.call_count == (1 if expect_upload else 0)
    return mark


def test_a_session_that_has_sent_no_message_yet_accepts_the_upload() -> None:
    mark = _upload()

    mark.assert_not_called()


def test_an_upload_racing_teardown_is_queued_for_deletion() -> None:
    """The pre-check passed and the tombstone landed mid-upload, so the rows
    exist and the post-check is what catches them."""
    mark = _upload(stored_after=_TOMBSTONE)

    mark.assert_called_once()


def test_an_upload_into_an_ended_session_never_writes_a_row() -> None:
    with pytest.raises(OnyxError) as raised:
        _upload(stored_before=_TOMBSTONE, expect_upload=False)

    assert raised.value.error_code is OnyxErrorCode.INVALID_INPUT


def test_a_user_without_incognito_is_refused() -> None:
    with pytest.raises(OnyxError) as raised:
        _upload(allowed=False, expect_upload=False)

    assert raised.value.error_code is OnyxErrorCode.UNAUTHORIZED
