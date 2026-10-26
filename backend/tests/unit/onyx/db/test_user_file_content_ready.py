"""Readiness for chat is decided by status plus the upload-time token count."""

import pytest

from onyx.db.enums import UserFileStatus
from onyx.db.models import UserFile


@pytest.mark.parametrize(
    ("status", "token_count", "expected"),
    [
        (UserFileStatus.COMPLETED, None, True),
        (UserFileStatus.SKIPPED, None, True),
        (UserFileStatus.PROCESSING, 42, True),
        (UserFileStatus.INDEXING, 42, True),
        (UserFileStatus.PROCESSING, 0, False),
        (UserFileStatus.PROCESSING, None, False),
        (UserFileStatus.FAILED, 42, False),
        (UserFileStatus.CANCELED, 42, False),
        (UserFileStatus.DELETING, 42, False),
    ],
)
def test_content_ready(
    status: UserFileStatus, token_count: int | None, expected: bool
) -> None:
    assert UserFile(status=status, token_count=token_count).content_ready is expected
