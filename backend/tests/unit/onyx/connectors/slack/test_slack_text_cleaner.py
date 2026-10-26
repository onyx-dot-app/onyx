"""SlackTextCleaner runs in linear time on hostile markup and bounds the
users.info calls one message can cause."""

import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from onyx.connectors.slack.utils import (
    _MAX_USER_LOOKUPS_PER_MESSAGE,
    SlackTextCleaner,
)


def _cleaner() -> tuple[SlackTextCleaner, MagicMock]:
    fetch = MagicMock(
        side_effect=lambda user_id: SimpleNamespace(
            user={"profile": {"display_name": f"name-{user_id}", "real_name": ""}}
        )
    )
    return SlackTextCleaner(fetch_user_info=fetch), fetch


@pytest.mark.parametrize(
    "message",
    ["<#|" * 13000, "<@" * 20000, "<!" * 20000],
    ids=["channel", "user", "catchall"],
)
def test_hostile_markup_is_cleaned_quickly(message: str) -> None:
    cleaner, fetch = _cleaner()
    start = time.monotonic()
    cleaner.index_clean(message)
    assert time.monotonic() - start < 1
    fetch.assert_not_called()


def test_user_lookups_are_capped_per_message() -> None:
    cleaner, fetch = _cleaner()
    message = "".join(f"<@U{i:08d}>" for i in range(1000))
    cleaned = cleaner.index_clean(message)
    assert fetch.call_count == _MAX_USER_LOOKUPS_PER_MESSAGE
    assert "<@" not in cleaned


def test_malformed_user_ids_are_not_looked_up() -> None:
    cleaner, fetch = _cleaner()
    assert cleaner.index_clean("hi <@a01> <@a02>") == "hi @a01 @a02"
    fetch.assert_not_called()


def test_well_formed_markup_is_cleaned() -> None:
    cleaner, fetch = _cleaner()
    message = (
        "<@U12345678> see <#C12345678|general> and "
        "<!subteam^S123|@eng> or <!date^1|today>"
    )
    assert cleaner.index_clean(message) == (
        "@name-U12345678 see #general and @eng or today"
    )
    fetch.assert_called_once_with("U12345678")
