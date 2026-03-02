"""Shared async HTTP client for communicating with Onyx API pods."""

import aiohttp

from onyx.chat.models import ChatFullResponse
from onyx.onyxbot.constants import API_REQUEST_TIMEOUT
from onyx.onyxbot.exceptions import APIConnectionError
from onyx.onyxbot.exceptions import APIResponseError
from onyx.onyxbot.exceptions import APITimeoutError
from onyx.server.query_and_chat.models import ChatSessionCreationRequest
from onyx.server.query_and_chat.models import MessageOrigin
from onyx.server.query_and_chat.models import SendMessageRequest
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import build_api_server_url_for_http_requests

logger = setup_logger()


class OnyxAPIClient:
    """Async HTTP client for sending chat requests to Onyx API pods.

    Used by both Discord and Teams bots. The ``origin`` parameter controls
    which ``MessageOrigin`` value is attached to outgoing requests for
    telemetry tracking.
    """

    def __init__(
        self,
        origin: MessageOrigin,
        timeout: int = API_REQUEST_TIMEOUT,
    ) -> None:
        self._origin = origin
        self._base_url = build_api_server_url_for_http_requests(
            respect_env_override_if_set=True
        ).rstrip("/")
        self._timeout = timeout
        self._session: aiohttp.ClientSession | None = None

    async def initialize(self) -> None:
        """Create the aiohttp session."""
        if self._session is not None:
            logger.warning("API client session already initialized")
            return

        timeout = aiohttp.ClientTimeout(
            total=self._timeout,
            connect=30,
        )
        self._session = aiohttp.ClientSession(timeout=timeout)
        logger.info(f"API client initialized with base URL: {self._base_url}")

    async def close(self) -> None:
        """Close the aiohttp session."""
        if self._session is not None:
            await self._session.close()
            self._session = None
            logger.info("API client session closed")

    @property
    def is_initialized(self) -> bool:
        return self._session is not None

    async def send_chat_message(
        self,
        message: str,
        api_key: str,
        persona_id: int | None = None,
    ) -> ChatFullResponse:
        """Send a chat message to the Onyx API server and get a response."""
        if self._session is None:
            raise APIConnectionError(
                "API client not initialized. Call initialize() first."
            )

        url = f"{self._base_url}/chat/send-chat-message"

        request = SendMessageRequest(
            message=message,
            stream=False,
            origin=self._origin,
            chat_session_info=ChatSessionCreationRequest(
                persona_id=persona_id if persona_id is not None else 0,
            ),
        )

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

        try:
            async with self._session.post(
                url,
                json=request.model_dump(mode="json"),
                headers=headers,
            ) as response:
                if response.status == 401:
                    raise APIResponseError(
                        "Authentication failed - invalid API key",
                        status_code=401,
                    )
                elif response.status == 403:
                    raise APIResponseError(
                        "Access denied - insufficient permissions",
                        status_code=403,
                    )
                elif response.status == 404:
                    raise APIResponseError(
                        "API endpoint not found",
                        status_code=404,
                    )
                elif response.status >= 500:
                    error_text = await response.text()
                    raise APIResponseError(
                        f"Server error: {error_text}",
                        status_code=response.status,
                    )
                elif response.status >= 400:
                    error_text = await response.text()
                    raise APIResponseError(
                        f"Request error: {error_text}",
                        status_code=response.status,
                    )

                data = await response.json()
                response_obj = ChatFullResponse.model_validate(data)

                if response_obj.error_msg:
                    logger.warning(f"Chat API returned error: {response_obj.error_msg}")

                return response_obj

        except aiohttp.ClientConnectorError as e:
            logger.error(f"Failed to connect to API: {e}")
            raise APIConnectionError(
                f"Failed to connect to API at {self._base_url}: {e}"
            ) from e

        except TimeoutError as e:
            logger.error(f"API request timed out after {self._timeout}s")
            raise APITimeoutError(
                f"Request timed out after {self._timeout} seconds"
            ) from e

        except aiohttp.ClientError as e:
            logger.error(f"HTTP client error: {e}")
            raise APIConnectionError(f"HTTP client error: {e}") from e

    async def health_check(self) -> bool:
        """Check if the API server is healthy."""
        if self._session is None:
            logger.warning("API client not initialized. Call initialize() first.")
            return False

        try:
            url = f"{self._base_url}/health"
            async with self._session.get(
                url, timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                return response.status == 200
        except Exception as e:
            logger.warning(f"API server health check failed: {e}")
            return False
