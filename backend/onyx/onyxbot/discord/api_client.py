"""Async HTTP client for communicating with Onyx API pods."""

from collections.abc import Sequence

import aiohttp

from onyx.chat.models import ChatFullResponse
from onyx.file_store.models import FileDescriptor
from onyx.onyxbot.discord.attachments import MessageAttachment
from onyx.onyxbot.discord.constants import API_REQUEST_TIMEOUT
from onyx.onyxbot.discord.exceptions import (
    APIConnectionError,
    APIResponseError,
    APITimeoutError,
)
from onyx.server.query_and_chat.models import (
    ChatFileUploadResponse,
    ChatSessionCreationRequest,
    MessageOrigin,
    SendMessageRequest,
)
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
        logger.info("API client initialized with base URL: %s", self._base_url)

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

    @staticmethod
    async def _raise_for_error_status(response: aiohttp.ClientResponse) -> None:
        """Translate an error response into the matching APIResponseError."""
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

    def _translate_transport_error(self, e: Exception) -> Exception:
        """Wrap an aiohttp transport failure in the matching APIError."""
        if isinstance(e, aiohttp.ClientConnectorError):
            logger.error("Failed to connect to API: %s", e)
            return APIConnectionError(
                f"Failed to connect to API at {self._base_url}: {e}"
            )

        if isinstance(e, TimeoutError):
            logger.error("API request timed out after %ss", self._timeout)
            return APITimeoutError(f"Request timed out after {self._timeout} seconds")

        logger.error("HTTP client error: %s", e)
        return APIConnectionError(f"HTTP client error: {e}")

    async def send_chat_message(
        self,
        message: str,
        api_key: str,
        persona_id: int | None = None,
        file_descriptors: list[FileDescriptor] | None = None,
    ) -> ChatFullResponse:
        """Send a chat message to the Onyx API server and get a response.

        This method sends a non-streaming chat request to the API server. The response
        contains the complete answer with any citations and metadata.

        Args:
            message: The user's message to process.
            api_key: The API key for authentication.
            persona_id: Optional persona ID to use for the response.
            file_descriptors: Files to attach to the message, as returned by
                `upload_chat_files`.

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
            file_descriptors=file_descriptors or [],
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
                await self._raise_for_error_status(response)

                # Parse successful response
                data = await response.json()
                response_obj = ChatFullResponse.model_validate(data)

                if response_obj.error_msg:
                    logger.warning(
                        "Chat API returned error: %s", response_obj.error_msg
                    )

                return response_obj

        except (aiohttp.ClientError, TimeoutError) as e:
            raise self._translate_transport_error(e) from e

    async def upload_chat_files(
        self,
        files: Sequence[MessageAttachment],
        api_key: str,
    ) -> list[FileDescriptor]:
        """Upload files to Onyx so they can be attached to a chat message.

        Args:
            files: The downloaded attachments to upload.
            api_key: The API key for authentication.

        Returns:
            Descriptors for the accepted files, to pass to `send_chat_message`.
            Files the server rejected (e.g. over its size limit) are logged and
            omitted, so this can be shorter than `files`.

        Raises:
            APIConnectionError: If unable to connect to the API.
            APITimeoutError: If the request times out.
            APIResponseError: If the API returns an error response.
        """
        if self._session is None:
            raise APIConnectionError(
                "API client not initialized. Call initialize() first."
            )

        if not files:
            return []

        url = f"{self._base_url}/chat/file"

        form = aiohttp.FormData()
        for file in files:
            form.add_field(
                "files",
                file.data,
                filename=file.filename,
                content_type=file.content_type,
            )

        # Content-Type is set by aiohttp so the multipart boundary matches.
        headers = {"Authorization": f"Bearer {api_key}"}

        try:
            async with self._session.post(url, data=form, headers=headers) as response:
                await self._raise_for_error_status(response)

                data = await response.json()
                upload_response = ChatFileUploadResponse.model_validate(data)

                for rejected in upload_response.rejected_files:
                    logger.warning(
                        "Onyx rejected attachment '%s': %s",
                        rejected.filename,
                        rejected.reason,
                    )

                return upload_response.files

        except (aiohttp.ClientError, TimeoutError) as e:
            raise self._translate_transport_error(e) from e

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
            logger.warning("API server health check failed: %s", e)
            return False
