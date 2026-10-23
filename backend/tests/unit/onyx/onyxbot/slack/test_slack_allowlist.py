from unittest.mock import MagicMock
from onyx.onyxbot.slack.handlers.handle_message import _resolve_allowlist_user_ids


def test_resolve_allowlist_empty_or_blank_returns_none():
    client = MagicMock()

    # Empty list
    resolved, missing = _resolve_allowlist_user_ids({"respond_member_group_list": []}, client)
    assert resolved is None
    assert missing == []

    # List of blank / whitespace strings
    resolved, missing = _resolve_allowlist_user_ids({"respond_member_group_list": ["", "  ", "\t"]}, client)
    assert resolved is None
    assert missing == []


def test_resolve_allowlist_strips_valid_entries():
    client = MagicMock()
    mock_user_resp = MagicMock()
    mock_user_resp.data = {"ok": True, "user": {"id": "U12345"}}
    client.users_lookupByEmail.return_value = mock_user_resp

    resolved, missing = _resolve_allowlist_user_ids(
        {"respond_member_group_list": ["  user@example.com  ", ""]},
        client,
    )
    assert resolved == ["U12345"]
    assert missing == []

