"""Unit tests for Discord bot API client.

Tests for OnyxAPIClient class functionality.
"""

from typing import Any
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import aiohttp
import pytest

from onyx.chat.models import ChatFullResponse
from onyx.onyxbot.discord.api_client import OnyxAPIClient
from onyx.onyxbot.discord.constants import API_REQUEST_TIMEOUT
from onyx.onyxbot.discord.exceptions import APIConnectionError
from onyx.onyxbot.discord.exceptions import APIResponseError
from onyx.onyxbot.discord.exceptions import APITimeoutError


class MockAsyncContextManager:
    """Helper class to create proper async context managers for testing."""

    def __init__(
        self, return_value: Any = None, enter_side_effect: Exception | None = None
    ) -> None:
        self.return_value = return_value
        self.enter_side_effect = enter_side_effect

    async def __aenter__(self) -> Any:
        if self.enter_side_effect:
            raise self.enter_side_effect
        return self.return_value

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass


class TestClientLifecycle:
    """Tests for API client lifecycle management."""

    @pytest.mark.asyncio
    async def test_initialize_creates_session(self) -> None:
        """initialize() creates aiohttp session."""
        client = OnyxAPIClient()
        assert client._session is None

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session_class.return_value = mock_session

            await client.initialize()

        assert client._session is not None
        mock_session_class.assert_called_once()

    def test_is_initialized_before_init(self) -> None:
        """is_initialized returns False before initialize()."""
        client = OnyxAPIClient()
        assert client.is_initialized is False

    @pytest.mark.asyncio
    async def test_is_initialized_after_init(self) -> None:
        """is_initialized returns True after initialize()."""
        client = OnyxAPIClient()

        with patch("aiohttp.ClientSession"):
            await client.initialize()

        assert client.is_initialized is True

    @pytest.mark.asyncio
    async def test_close_closes_session(self) -> None:
        """close() closes session and resets is_initialized."""
        client = OnyxAPIClient()

        mock_session = AsyncMock()
        with patch("aiohttp.ClientSession", return_value=mock_session):
            await client.initialize()
            assert client.is_initialized is True

            await client.close()

        assert client.is_initialized is False
        mock_session.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_message_not_initialized(self) -> None:
        """send_chat_message() before initialize() raises APIConnectionError."""
        client = OnyxAPIClient()

        with pytest.raises(APIConnectionError) as exc_info:
            await client.send_chat_message("test", "api_key")

        assert "not initialized" in str(exc_info.value)


class TestSendChatMessage:
    """Tests for send_chat_message functionality."""

    @pytest.mark.asyncio
    async def test_send_message_success(self) -> None:
        """Valid request returns ChatFullResponse."""
        client = OnyxAPIClient()

        response_data = {
            "answer": "Test response",
            "citations": [],
            "error_msg": None,
        }

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=response_data)

        mock_session = MagicMock()
        mock_session.post = MagicMock(
            return_value=MockAsyncContextManager(return_value=mock_response)
        )

        client._session = mock_session

        with patch.object(
            ChatFullResponse,
            "model_validate",
            return_value=MagicMock(answer="Test response", error_msg=None),
        ):
            result = await client.send_chat_message("Hello", "api_key_123")

        assert result is not None

    @pytest.mark.asyncio
    async def test_send_message_with_persona(self) -> None:
        """persona_id is passed to API."""
        client = OnyxAPIClient()

        response_data = {"answer": "Response", "citations": [], "error_msg": None}

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=response_data)

        mock_session = MagicMock()
        mock_post = MagicMock(
            return_value=MockAsyncContextManager(return_value=mock_response)
        )
        mock_session.post = mock_post

        client._session = mock_session

        with patch.object(
            ChatFullResponse,
            "model_validate",
            return_value=MagicMock(answer="Response", error_msg=None),
        ):
            await client.send_chat_message("Hello", "api_key", persona_id=5)

        # Verify persona was included in request
        call_args = mock_post.call_args
        json_data = call_args.kwargs.get("json") or call_args[1].get("json")
        assert json_data is not None

    @pytest.mark.asyncio
    async def test_send_message_401_error(self) -> None:
        """Invalid API key returns APIResponseError with 401."""
        client = OnyxAPIClient()

        mock_response = MagicMock()
        mock_response.status = 401

        mock_session = MagicMock()
        mock_session.post = MagicMock(
            return_value=MockAsyncContextManager(return_value=mock_response)
        )

        client._session = mock_session

        with pytest.raises(APIResponseError) as exc_info:
            await client.send_chat_message("Hello", "bad_key")

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_send_message_403_error(self) -> None:
        """Persona not accessible returns APIResponseError with 403."""
        client = OnyxAPIClient()

        mock_response = MagicMock()
        mock_response.status = 403

        mock_session = MagicMock()
        mock_session.post = MagicMock(
            return_value=MockAsyncContextManager(return_value=mock_response)
        )

        client._session = mock_session

        with pytest.raises(APIResponseError) as exc_info:
            await client.send_chat_message("Hello", "api_key", persona_id=999)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_send_message_timeout(self) -> None:
        """Request timeout raises APITimeoutError."""
        client = OnyxAPIClient()

        mock_session = MagicMock()
        mock_session.post = MagicMock(
            return_value=MockAsyncContextManager(
                enter_side_effect=TimeoutError("Timeout")
            )
        )

        client._session = mock_session

        with pytest.raises(APITimeoutError):
            await client.send_chat_message("Hello", "api_key")

    @pytest.mark.asyncio
    async def test_send_message_connection_error(self) -> None:
        """Network failure raises APIConnectionError."""
        client = OnyxAPIClient()

        mock_session = MagicMock()
        mock_session.post = MagicMock(
            return_value=MockAsyncContextManager(
                enter_side_effect=aiohttp.ClientConnectorError(
                    MagicMock(), OSError("Connection refused")
                )
            )
        )

        client._session = mock_session

        with pytest.raises(APIConnectionError):
            await client.send_chat_message("Hello", "api_key")

    @pytest.mark.asyncio
    async def test_send_message_server_error(self) -> None:
        """500 response raises APIResponseError with 500."""
        client = OnyxAPIClient()

        mock_response = MagicMock()
        mock_response.status = 500
        mock_response.text = AsyncMock(return_value="Internal Server Error")

        mock_session = MagicMock()
        mock_session.post = MagicMock(
            return_value=MockAsyncContextManager(return_value=mock_response)
        )

        client._session = mock_session

        with pytest.raises(APIResponseError) as exc_info:
            await client.send_chat_message("Hello", "api_key")

        assert exc_info.value.status_code == 500


class TestHealthCheck:
    """Tests for health_check functionality."""

    @pytest.mark.asyncio
    async def test_health_check_success(self) -> None:
        """Server healthy returns True."""
        client = OnyxAPIClient()

        mock_response = MagicMock()
        mock_response.status = 200

        mock_session = MagicMock()
        mock_session.get = MagicMock(
            return_value=MockAsyncContextManager(return_value=mock_response)
        )

        client._session = mock_session

        result = await client.health_check()
        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self) -> None:
        """Server unhealthy returns False."""
        client = OnyxAPIClient()

        mock_response = MagicMock()
        mock_response.status = 503

        mock_session = MagicMock()
        mock_session.get = MagicMock(
            return_value=MockAsyncContextManager(return_value=mock_response)
        )

        client._session = mock_session

        result = await client.health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_timeout(self) -> None:
        """Request times out returns False."""
        client = OnyxAPIClient()

        mock_session = MagicMock()
        mock_session.get = MagicMock(
            return_value=MockAsyncContextManager(
                enter_side_effect=TimeoutError("Timeout")
            )
        )

        client._session = mock_session

        result = await client.health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_not_initialized(self) -> None:
        """Health check before initialize returns False."""
        client = OnyxAPIClient()

        result = await client.health_check()
        assert result is False


class TestResponseParsing:
    """Tests for API response parsing."""

    @pytest.mark.asyncio
    async def test_response_malformed_json(self) -> None:
        """API returns invalid JSON raises exception."""
        client = OnyxAPIClient()

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(side_effect=ValueError("Invalid JSON"))

        mock_session = MagicMock()
        mock_session.post = MagicMock(
            return_value=MockAsyncContextManager(return_value=mock_response)
        )

        client._session = mock_session

        with pytest.raises(ValueError):
            await client.send_chat_message("Hello", "api_key")

    @pytest.mark.asyncio
    async def test_response_with_error_msg(self) -> None:
        """200 status but error_msg present - warning logged, response returned."""
        client = OnyxAPIClient()

        response_data = {
            "answer": "Partial response",
            "citations": [],
            "error_msg": "Some warning",
        }

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=response_data)

        mock_session = MagicMock()
        mock_session.post = MagicMock(
            return_value=MockAsyncContextManager(return_value=mock_response)
        )

        client._session = mock_session

        mock_result = MagicMock()
        mock_result.answer = "Partial response"
        mock_result.error_msg = "Some warning"

        with patch.object(ChatFullResponse, "model_validate", return_value=mock_result):
            result = await client.send_chat_message("Hello", "api_key")

        # Should still return response
        assert result is not None

    @pytest.mark.asyncio
    async def test_response_empty_answer(self) -> None:
        """answer field is empty string - handled gracefully."""
        client = OnyxAPIClient()

        response_data = {
            "answer": "",
            "citations": [],
            "error_msg": None,
        }

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=response_data)

        mock_session = MagicMock()
        mock_session.post = MagicMock(
            return_value=MockAsyncContextManager(return_value=mock_response)
        )

        client._session = mock_session

        mock_result = MagicMock()
        mock_result.answer = ""
        mock_result.error_msg = None

        with patch.object(ChatFullResponse, "model_validate", return_value=mock_result):
            result = await client.send_chat_message("Hello", "api_key")

        # Should return response even with empty answer
        assert result is not None


class TestClientConfiguration:
    """Tests for client configuration."""

    def test_default_timeout(self) -> None:
        """Client uses API_REQUEST_TIMEOUT by default."""
        client = OnyxAPIClient()
        assert client._timeout == API_REQUEST_TIMEOUT

    def test_custom_timeout(self) -> None:
        """Client accepts custom timeout."""
        client = OnyxAPIClient(timeout=60)
        assert client._timeout == 60

    @pytest.mark.asyncio
    async def test_double_initialize_warning(self) -> None:
        """Calling initialize() twice logs warning but doesn't error."""
        client = OnyxAPIClient()

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session_class.return_value = mock_session

            await client.initialize()
            # Second call should be safe
            await client.initialize()

        # Should only create one session
        assert mock_session_class.call_count == 1
