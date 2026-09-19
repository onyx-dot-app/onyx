"""Tests for `_resolve_allowlist_user_ids` blank-entry handling.

Regression coverage for the bug where a `respond_member_group_list` containing
only blank entries (e.g. `[""]`, produced by leaving the members field empty in
the UI) silenced OnyxBot for the entire channel: the blank list was treated as a
configured allowlist that then resolved to zero users, so the invocation gate
dropped every sender.
"""

from unittest.mock import MagicMock, patch

from onyx.onyxbot.slack.handlers.handle_message import _resolve_allowlist_user_ids

_MODULE = "onyx.onyxbot.slack.handlers.handle_message"


def test_no_allowlist_key_returns_none() -> None:
    resolved, missing = _resolve_allowlist_user_ids({}, MagicMock())
    assert resolved is None
    assert missing == []


def test_blank_only_allowlist_is_treated_as_no_allowlist() -> None:
    client = MagicMock()
    resolved, missing = _resolve_allowlist_user_ids(
        {"respond_member_group_list": [""]}, client
    )
    # Must behave exactly like "no allowlist configured": no gate, no missing
    # entries, and no Slack lookups attempted.
    assert resolved is None
    assert missing == []
    client.assert_not_called()


def test_whitespace_only_entries_are_treated_as_no_allowlist() -> None:
    resolved, missing = _resolve_allowlist_user_ids(
        {"respond_member_group_list": ["", "   ", "\t"]}, MagicMock()
    )
    assert resolved is None
    assert missing == []


def test_blank_entries_are_filtered_but_real_entries_still_resolve() -> None:
    with (
        patch(
            f"{_MODULE}.fetch_slack_user_ids_from_emails",
            return_value=(["U1"], []),
        ) as mock_emails,
        patch(
            f"{_MODULE}.fetch_user_ids_from_groups",
            return_value=([], []),
        ),
    ):
        resolved, missing = _resolve_allowlist_user_ids(
            {"respond_member_group_list": ["a@example.com", ""]}, MagicMock()
        )

    # The blank entry is dropped before lookup; the real entry is preserved.
    mock_emails.assert_called_once()
    assert mock_emails.call_args.args[0] == ["a@example.com"]
    assert resolved == ["U1"]
    assert missing == []
