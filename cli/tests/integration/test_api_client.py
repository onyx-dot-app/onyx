"""Integration tests for the Onyx API client.

These tests require a running Onyx server. Configure via environment variables:
  ONYX_SERVER_URL - Server URL (default: http://localhost:3000)
  ONYX_API_KEY - API key or PAT for authentication

Run with:
  python -m dotenv -f .vscode/.env run -- pytest cli/tests/integration -xv
"""

from __future__ import annotations

import os
from pathlib import Path
from uuid import UUID

import pytest

from onyx_cli.api_client import OnyxApiClient
from onyx_cli.config import OnyxCliConfig
from onyx_cli.models import (
    MessageDeltaEvent,
    SessionCreatedEvent,
    StopEvent,
    StreamEventType,
)


def _get_config() -> OnyxCliConfig:
    return OnyxCliConfig(
        server_url=os.environ.get("ONYX_SERVER_URL", "http://localhost:3000"),
        api_key=os.environ.get("ONYX_API_KEY", os.environ.get("DANSWER_API_KEY", "")),
    )


@pytest.fixture
async def client() -> OnyxApiClient:
    config = _get_config()
    c = OnyxApiClient(config)
    yield c
    await c.close()


@pytest.mark.asyncio
async def test_list_personas(client: OnyxApiClient) -> None:
    """Test that we can list personas from the server."""
    personas = await client.list_personas()
    assert len(personas) > 0
    assert personas[0].name  # Should have a name


@pytest.mark.asyncio
async def test_list_chat_sessions(client: OnyxApiClient) -> None:
    """Test that we can list chat sessions."""
    sessions = await client.list_chat_sessions()
    # May be empty, just check it doesn't error
    assert isinstance(sessions, list)


@pytest.mark.asyncio
async def test_send_message_stream(client: OnyxApiClient) -> None:
    """Test full send message flow: session creation, streaming, stop."""
    session_id: UUID | None = None
    got_content = False
    got_stop = False

    async for event in client.send_message_stream(
        message="What is Onyx? Reply in one sentence.",
        persona_id=0,
    ):
        if isinstance(event, SessionCreatedEvent):
            session_id = event.chat_session_id
        elif isinstance(event, MessageDeltaEvent):
            got_content = True
        elif isinstance(event, StopEvent):
            got_stop = True
            break

    assert session_id is not None, "Should have received a session ID"
    assert got_content, "Should have received at least one content delta"
    assert got_stop, "Should have received a stop event"
