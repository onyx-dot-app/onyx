"""The gateway owns the credential: an API key is sent as is, an expiring
OAuth token is refreshed once under the provider's lock and written back,
and Linear's refusals and listing faults surface as typed errors."""

import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.linear.source_operations import (
    LinearAuthError,
    LinearSourceOperations,
)

OPS = "onyx.connectors.linear.source_operations"


def _provider(credentials: dict[str, Any]) -> MagicMock:
    provider = MagicMock()
    provider.get_credentials.return_value = credentials
    provider.__enter__.return_value = provider
    return provider


def _page(nodes: list[dict[str, Any]], end_cursor: str | None) -> MagicMock:
    response = MagicMock()
    response.json.return_value = {
        "data": {
            "teams": {
                "nodes": nodes,
                "pageInfo": {
                    "hasNextPage": end_cursor is not None,
                    "endCursor": end_cursor,
                },
            }
        }
    }
    return response


def test_an_api_key_is_read_once_and_sent_as_is() -> None:
    provider = _provider({"linear_api_key": "lin_api_test"})
    ops = LinearSourceOperations(credentials_provider=provider)

    assert ops._api_key() == "lin_api_test"
    assert ops._api_key() == "lin_api_test"
    assert provider.get_credentials.call_count == 1
    provider.__enter__.assert_not_called()


@patch(f"{OPS}.refresh_oauth_token")
def test_an_expiring_token_is_refreshed_under_the_lock_and_written_back(
    refresh: MagicMock,
) -> None:
    expiring = {
        "access_token": "old",
        "refresh_token": "r",
        "expire_at": int(time.time()) + 60,
    }
    fresh = {
        "access_token": "new",
        "refresh_token": "r2",
        "expire_at": int(time.time()) + 3600,
    }
    refresh.return_value = fresh
    provider = _provider(expiring)
    ops = LinearSourceOperations(credentials_provider=provider)

    assert ops._api_key() == "Bearer new"

    provider.__enter__.assert_called_once()
    refresh.assert_called_once_with(expiring)
    provider.set_credentials.assert_called_once_with(fresh)
    assert ops._api_key() == "Bearer new"
    assert refresh.call_count == 1


@patch(f"{OPS}.refresh_oauth_token")
def test_a_token_another_sync_already_refreshed_is_reused(refresh: MagicMock) -> None:
    expiring = {
        "access_token": "old",
        "refresh_token": "r",
        "expire_at": int(time.time()) + 60,
    }
    fresh = {
        "access_token": "new",
        "refresh_token": "r2",
        "expire_at": int(time.time()) + 3600,
    }
    provider = _provider(expiring)
    # The second read, under the lock, sees the other sync's refresh.
    provider.get_credentials.side_effect = [expiring, fresh]
    ops = LinearSourceOperations(credentials_provider=provider)

    assert ops._api_key() == "Bearer new"

    refresh.assert_not_called()
    provider.set_credentials.assert_not_called()


def test_a_refused_credential_is_a_typed_error() -> None:
    response = MagicMock()
    response.status_code = 401
    response.ok = False
    response.text = "Authentication required"
    ops = LinearSourceOperations(
        credentials_provider=OnyxStaticCredentialsProvider(
            None, "linear", {"linear_api_key": "bad"}
        )
    )
    with (
        patch(f"{OPS}.requests.post", return_value=response) as post,
        pytest.raises(LinearAuthError),
    ):
        ops.get_viewer()

    post.assert_called_once()


def test_a_cursor_that_stops_advancing_is_refused() -> None:
    ops = LinearSourceOperations(
        credentials_provider=OnyxStaticCredentialsProvider(
            None, "linear", {"linear_api_key": "k"}
        )
    )
    with (
        patch(f"{OPS}._make_query", return_value=_page([], "same")),
        pytest.raises(RuntimeError, match="stopped advancing"),
    ):
        ops.list_teams()


def test_team_members_are_paged_per_team() -> None:
    ops = LinearSourceOperations(
        credentials_provider=OnyxStaticCredentialsProvider(
            None, "linear", {"linear_api_key": "k"}
        )
    )

    def membership_page(email: str, end_cursor: str | None) -> MagicMock:
        response = MagicMock()
        response.json.return_value = {
            "data": {
                "team": {
                    "memberships": {
                        "nodes": [
                            {
                                "user": {
                                    "email": email,
                                    "active": True,
                                    "guest": False,
                                    "app": False,
                                }
                            }
                        ],
                        "pageInfo": {
                            "hasNextPage": end_cursor is not None,
                            "endCursor": end_cursor,
                        },
                    }
                }
            }
        }
        return response

    pages = [membership_page("ann@x", "c1"), membership_page("bob@x", None)]
    with patch(f"{OPS}._make_query", side_effect=pages) as query:
        members = ops.list_team_members(team_id="t1")

    assert [member.email for member in members] == ["ann@x", "bob@x"]
    sent = [call.args[0]["variables"] for call in query.call_args_list]
    assert sent == [
        {"teamId": "t1", "first": 100, "after": None},
        {"teamId": "t1", "first": 100, "after": "c1"},
    ]
