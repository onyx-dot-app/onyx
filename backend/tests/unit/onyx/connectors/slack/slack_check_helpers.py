"""Gateway, error and page builders that the Slack capability check tests share."""

from typing import Any
from unittest.mock import MagicMock, create_autospec

from onyx.connectors.slack.source_operations import (
    SlackApiError,
    SlackAuthTestResponse,
    SlackChannelMembersPage,
    SlackChannelsPage,
    SlackHistoryPage,
    SlackSourceOperations,
    SlackUsersPage,
)

ALL_INDEXING_SCOPES = [
    "channels:read",
    "channels:history",
    "channels:join",
    "groups:read",
    "groups:history",
    "users:read",
    "users:read.email",
]


def slack_error(error: str, needed: str | None = None) -> SlackApiError:
    data: dict[str, Any] = {"ok": False, "error": error}
    if needed is not None:
        data["needed"] = needed
    return SlackApiError("slack api error", data)


def auth_response(
    enterprise_id: str | None = None,
    granted_scopes: list[str] | None = None,
) -> SlackAuthTestResponse:
    return SlackAuthTestResponse(
        ok=True,
        url="https://example.slack.com",
        enterprise_id=enterprise_id,
        granted_scopes=granted_scopes,
    )


def autospec_gateway() -> MagicMock:
    """An autospecced gateway; tests set per-operation returns as needed."""
    gateway = create_autospec(SlackSourceOperations, instance=True)
    gateway.check_auth.return_value = auth_response()
    return gateway


def tracked_pages(pages: list[Any], consumed: list[Any]) -> Any:
    """A ``side_effect`` yielding ``pages`` lazily and recording each page the
    caller reads."""

    def make(**kwargs: Any) -> Any:
        del kwargs
        for page in pages:
            consumed.append(page)
            yield page

    return make


def page_side_effect(page: Any) -> Any:
    """A ``side_effect`` yielding a fresh one-page generator per call."""

    def make(**kwargs: Any) -> Any:
        del kwargs
        return iter([page])

    return make


def coherent_gateway() -> MagicMock:
    """An off-Grid gateway with every probe answering like a healthy token."""
    gateway = autospec_gateway()
    gateway.check_auth.return_value = auth_response(granted_scopes=ALL_INDEXING_SCOPES)

    def list_channels(**kwargs: Any) -> Any:
        if "public_channel" in kwargs["channel_types"]:
            return iter(
                [
                    SlackChannelsPage(
                        channels=[{"id": "C1", "name": "general", "is_member": True}]
                    )
                ]
            )
        return iter([SlackChannelsPage(channels=[{"id": "G1", "name": "secret"}])])

    gateway.list_channels.side_effect = list_channels
    gateway.fetch_channel_history.side_effect = page_side_effect(
        SlackHistoryPage(messages=[])
    )
    gateway.list_channel_members.side_effect = page_side_effect(
        SlackChannelMembersPage(members=["U1"])
    )
    gateway.list_users.side_effect = page_side_effect(
        SlackUsersPage(
            members=[
                {
                    "id": "U1",
                    "is_bot": False,
                    "deleted": False,
                    "profile": {"email": "user@example.com"},
                }
            ]
        )
    )
    return gateway
