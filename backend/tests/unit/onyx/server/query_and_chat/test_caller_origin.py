"""Key and token callers get an origin from their credential, not from the request body."""

import pytest
from fastapi import Request

from onyx.configs.constants import DISCORD_SERVICE_API_KEY_NAME
from onyx.server.query_and_chat.chat_backend import _caller_origin
from onyx.server.query_and_chat.models import MessageOrigin
from shared_configs.contextvars import UsageCredentialIdentity
from shared_configs.enums import UsageCredentialType

_KEY: str = "Bearer on_key"
_PAT: str = "Bearer onyx_pat_token"
_DISCORD: str = DISCORD_SERVICE_API_KEY_NAME


@pytest.mark.parametrize(
    "authorization, credential_type, name, claimed, expected",
    [
        # A session caller keeps the origin that its client sends.
        (None, UsageCredentialType.SESSION, None, "webapp", "webapp"),
        (_KEY, UsageCredentialType.API_KEY, "integration", "discordbot", "api"),
        (_PAT, UsageCredentialType.PAT, _DISCORD, "discordbot", "api"),
        # The Discord bot's service key reports Discord, whatever the body says.
        (_KEY, UsageCredentialType.API_KEY, _DISCORD, "discordbot", "discordbot"),
        (_KEY, UsageCredentialType.API_KEY, _DISCORD, "webapp", "discordbot"),
    ],
)
def test_only_the_discord_service_key_reports_discord(
    authorization: str | None,
    credential_type: UsageCredentialType,
    name: str | None,
    claimed: str,
    expected: str,
) -> None:
    headers: list[tuple[bytes, bytes]] = (
        [] if authorization is None else [(b"authorization", authorization.encode())]
    )
    credential = UsageCredentialIdentity(credential_type, "1", name)
    request = Request(
        {"type": "http", "headers": headers, "state": {"usage_credential": credential}}
    )
    assert _caller_origin(request, MessageOrigin(claimed)) == MessageOrigin(expected)
