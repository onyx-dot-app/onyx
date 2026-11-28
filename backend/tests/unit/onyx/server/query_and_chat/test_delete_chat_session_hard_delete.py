"""Whether a chat delete removes the rows or only marks the chat deleted. On
the playground the request's `hard_delete` flag is ignored: the per-user image
limit counts the images of the user's chats, and a hard delete would give them
back."""

from unittest.mock import patch

import pytest

from onyx.server.query_and_chat import chat_backend


@pytest.mark.parametrize(
    ("requested", "setting", "expected"),
    [
        (None, False, False),
        (None, True, True),
        (True, False, True),
        (False, True, False),
    ],
)
def test_off_the_playground_the_request_decides_then_the_setting(
    requested: bool | None, setting: bool, expected: bool
) -> None:
    with (
        patch.object(chat_backend, "IS_PLAYGROUND", False),
        patch.object(chat_backend, "HARD_DELETE_CHATS", setting),
    ):
        assert chat_backend._hard_delete_for_request(requested) is expected


@pytest.mark.parametrize("requested", [None, True, False])
def test_on_the_playground_only_the_setting_decides(requested: bool | None) -> None:
    with (
        patch.object(chat_backend, "IS_PLAYGROUND", True),
        patch.object(chat_backend, "HARD_DELETE_CHATS", False),
    ):
        assert chat_backend._hard_delete_for_request(requested) is False
