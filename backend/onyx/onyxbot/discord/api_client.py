"""Async HTTP client for communicating with Onyx API pods."""

import aiohttp

from onyx.chat.models import ChatFullResponse
from onyx.onyxbot.discord.constants import API_REQUEST_TIMEOUT
from onyx.onyxbot.discord.exceptions import APIConnectionError
from onyx.onyxbot.discord.exceptions import APIResponseError
from onyx.onyxbot.discord.exceptions import APITimeoutError
from onyx.server.query_and_chat.models import ChatSessionCreationRequest
from onyx.server.query_and_chat.models import MessageOrigin
from onyx.server.query_and_chat.models import SendMessageRequest
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import build_api_server_url_for_http_requests

logger = setup_logger()


class OnyxAPIClient:
    """Async HTTP client for sending chat requests to Onyx API pods.

    This client manages an aiohttp session for making non-blocking HTTP
    requests to the Onyx API server. It handles authentication with per-tenant
    API keys and multi-tenant routing.

    Usage:
        client = OnyxAPIClient()
        await client.initialize()
        try:
            response = await client.send_chat_message(
                message="What is our deployment process?",
                tenant_id="tenant_123",
                api_key="dn_xxx...",
                persona_id=1,
            )
            print(response.answer)
        finally:
            await client.close()
    """

    def __init__(
        self,
        timeout: int = API_REQUEST_TIMEOUT,
    ) -> None:
        """Initialize the API client.

        Args:
            timeout: Request timeout in seconds.
        """
        # Helm chart uses API_SERVER_URL_OVERRIDE_FOR_HTTP_REQUESTS to set the base URL
        # TODO: Ideally, this override is only used when someone is launching an Onyx service independently
        self._base_url = build_api_server_url_for_http_requests(
            respect_env_override_if_set=True
        ).rstrip("/")
        self._timeout = timeout
        self._session: aiohttp.ClientSession | None = None

    async def initialize(self) -> None:
        """Create the aiohttp session.

        Must be called before making any requests. The session is created
        with a total timeout and connection timeout.
        """
        if self._session is not None:
            logger.warning("API client session already initialized")
            return

        timeout = aiohttp.ClientTimeout(
            total=self._timeout,
            connect=30,  # 30 seconds to establish connection
        )
        self._session = aiohttp.ClientSession(timeout=timeout)
        logger.info(f"API client initialized with base URL: {self._base_url}")

    async def close(self) -> None:
        """Close the aiohttp session.

        Should be called when shutting down the bot to properly release
        resources.
        """
        if self._session is not None:
            await self._session.close()
            self._session = None
            logger.info("API client session closed")

    @property
    def is_initialized(self) -> bool:
        """Check if the session is initialized."""
        return self._session is not None

    async def send_chat_message(
        self,
        message: str,
        api_key: str,
        persona_id: int | None = None,
    ) -> ChatFullResponse:
        """Send a chat message to the Onyx API server and get a response.

        This method sends a non-streaming chat request to the API server. The response
        contains the complete answer with any citations and metadata.

        Args:
            message: The user's message to process.
            api_key: The API key for authentication.
            persona_id: Optional persona ID to use for the response.

        Returns:
            ChatFullResponse containing the answer, citations, and metadata.

        Raises:
            APIConnectionError: If unable to connect to the API.
            APITimeoutError: If the request times out.
            APIResponseError: If the API returns an error response.
        """
        if self._session is None:
            raise APIConnectionError(
                "API client not initialized. Call initialize() first."
            )

        url = f"{self._base_url}/chat/send-chat-message"

        # Build request payload
        request = SendMessageRequest(
            message=message,
            stream=False,
            origin=MessageOrigin.DISCORDBOT,
            chat_session_info=ChatSessionCreationRequest(
                persona_id=persona_id if persona_id is not None else 0,
            ),
        )

        # Build headers
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

                # Parse successful response
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
        """Check if the API server is healthy.

        Returns:
            True if the API server is reachable and healthy, False otherwise.
        """
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
