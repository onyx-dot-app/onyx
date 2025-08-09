"""Outline API client for communicating with Outline knowledge base platform.

This module provides the OutlineApiClient class and associated exception classes
for interacting with Outline's RPC-style API endpoints. Handles authentication,
rate limiting, error handling, and URL normalization for both self-hosted and
cloud-hosted Outline instances.
"""

import time
from typing import Any
from urllib.parse import urljoin
from urllib.parse import urlparse

import requests


class OutlineClientError(ConnectionError):
    """Base exception for Outline client errors"""


class OutlineClientRequestFailedError(OutlineClientError):
    def __init__(self, status: int, error: str) -> None:
        self.status_code = status
        self.error = error
        super().__init__(f"Outline Client request failed with status {status}: {error}")


class OutlineClientAuthenticationError(OutlineClientError):
    def __init__(self) -> None:
        super().__init__("Outline authentication failed. Please check your API token.")


class OutlineClientRateLimitError(OutlineClientError):
    def __init__(self, retry_after: int) -> None:
        self.retry_after = retry_after
        super().__init__(
            f"Outline API rate limit exceeded. Retry after {retry_after} seconds."
        )


class OutlineApiClient:
    """API client for Outline knowledge base platform.

    Provides access to Outline's RPC-style API endpoints for fetching collections
    and documents. Supports both self-hosted and cloud-hosted Outline instances.

    Features:
    - Automatic URL normalization for various Outline deployment formats
    - Bearer token authentication with API keys
    - Built-in rate limiting and retry logic with exponential backoff
    - Comprehensive error handling for authentication, rate limits, and network issues

    Args:
        base_url: The base URL of your Outline instance (e.g., "https://outline.example.com")
        api_token: Your Outline API token for authentication
        max_retries: Maximum number of retry attempts for failed requests (default: 3)
        initial_backoff: Initial backoff delay in seconds for retries (default: 1.0)

    Raises:
        ValueError: If the base_url is invalid or cannot be normalized
        OutlineClientError: For various client-side errors during API communication
    """

    def __init__(
        self,
        base_url: str,
        api_token: str,
        max_retries: int = 3,
        initial_backoff: float = 1.0,
    ) -> None:
        self.base_url = self._normalize_url(base_url)
        self.api_token = api_token
        self.max_retries = max_retries
        self.initial_backoff = initial_backoff
        self._session = requests.Session()
        self._session.headers.update(self._build_headers())

    def _normalize_url(self, url: str) -> str:
        """Normalize URL to ensure proper format for both self-hosted and cloud instances.

        Handles various URL formats and ensures a consistent base URL format:
        - Adds https:// prefix if no protocol is specified
        - Removes trailing slashes to ensure consistent URL building
        - Validates that the URL has a valid netloc (domain)

        Args:
            url: The raw URL input from the user

        Returns:
            Normalized URL in the format: "https://domain.com/path" (no trailing slash)

        Raises:
            ValueError: If the URL is empty or lacks a valid domain
        """
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        parsed = urlparse(url)
        if not parsed.netloc:
            raise ValueError(f"Invalid Outline base URL: {url}")

        # Ensure URL ends without trailing slash
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"

    def _build_headers(self) -> dict[str, str]:
        """Build HTTP headers for API requests.

        Creates standard headers required for Outline API communication:
        - Bearer token authentication
        - JSON content type specification
        - JSON accept header for responses

        Returns:
            Dictionary of HTTP headers for API requests
        """
        return {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _build_api_url(self, endpoint: str) -> str:
        """Build complete API URL for RPC-style endpoints.

        Combines the base URL with the API path and endpoint name to create
        the full URL for API requests. Outline uses RPC-style endpoints like
        "collections.list" and "documents.list".

        Args:
            endpoint: The API endpoint name (e.g., "collections.list", "documents.list")

        Returns:
            Complete URL for the API endpoint (e.g., "https://outline.com/api/collections.list")
        """
        return urljoin(self.base_url + "/api/", endpoint.lstrip("/"))

    def post(self, endpoint: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Make POST request to Outline RPC API with comprehensive error handling.

        Sends a POST request to the specified endpoint with automatic retry logic
        for rate limiting and network errors. Implements exponential backoff for
        robust error recovery.

        Args:
            endpoint: The API endpoint name (e.g., "collections.list")
            data: Optional request payload as a dictionary

        Returns:
            JSON response from the API as a dictionary

        Raises:
            OutlineClientAuthenticationError: For 401 authentication failures
            OutlineClientRateLimitError: For 429 rate limiting (after all retries)
            OutlineClientRequestFailedError: For other HTTP errors (4xx, 5xx)
            OutlineClientError: For network errors after all retries
        """
        url = self._build_api_url(endpoint)

        for attempt in range(self.max_retries + 1):
            try:
                response = self._session.post(url, json=data or {})
                return self._handle_response(response)
            except OutlineClientRateLimitError as e:
                if attempt == self.max_retries:
                    raise
                # Wait for the specified retry-after time plus some backoff
                sleep_time = e.retry_after + (self.initial_backoff * (2**attempt))
                time.sleep(sleep_time)
                continue
            except requests.exceptions.RequestException as e:
                if attempt == self.max_retries:
                    raise OutlineClientError(
                        f"Request failed after {self.max_retries + 1} attempts: {str(e)}"
                    )
                # Exponential backoff for network errors
                sleep_time = self.initial_backoff * (2**attempt)
                time.sleep(sleep_time)
                continue

        raise OutlineClientError("Request failed after all retry attempts")

    def _handle_response(self, response: requests.Response) -> dict[str, Any]:
        """Handle API response and convert HTTP errors to appropriate exceptions.

        Processes the HTTP response and converts various error conditions into
        specific exception types for better error handling by calling code.

        Args:
            response: The HTTP response object from requests

        Returns:
            Parsed JSON response as a dictionary, or empty dict if JSON parsing fails

        Raises:
            OutlineClientAuthenticationError: For 401 authentication failures
            OutlineClientRateLimitError: For 429 rate limiting with retry-after info
            OutlineClientRequestFailedError: For other HTTP errors (4xx, 5xx)
        """
        try:
            json_data = response.json()
        except ValueError:
            json_data = {}

        if response.status_code == 401:
            raise OutlineClientAuthenticationError()
        elif response.status_code == 429:
            # Handle rate limiting
            retry_after = int(response.headers.get("Retry-After", "60"))
            raise OutlineClientRateLimitError(retry_after)
        elif response.status_code >= 400:
            error_message = json_data.get("message", response.reason or "Unknown error")
            raise OutlineClientRequestFailedError(response.status_code, error_message)

        return json_data

    def get_collections(
        self,
        limit: int = 25,
        offset: int = 0,
        sort: str = "updatedAt",
        direction: str = "DESC",
    ) -> dict[str, Any]:
        """Retrieve collections from the Outline workspace.

        Fetches a paginated list of collections (document groups) from the Outline
        workspace. Collections represent organized groups of documents.

        Args:
            limit: Maximum number of collections to return (default: 25)
            offset: Number of collections to skip for pagination (default: 0)
            sort: Field to sort by (default: "updatedAt")
            direction: Sort direction - "ASC" or "DESC" (default: "DESC")

        Returns:
            API response containing collection data in the format:
            {
                "data": [
                    {
                        "id": "collection-id",
                        "name": "Collection Name",
                        "description": "Description",
                        "updatedAt": "2023-12-01T10:00:00Z",
                        ...
                    }
                ]
            }
        """
        return self.post(
            "collections.list",
            {"limit": limit, "offset": offset, "sort": sort, "direction": direction},
        )

    def get_collection_documents(
        self,
        collection_id: str,
        limit: int = 25,
        offset: int = 0,
        sort: str = "updatedAt",
        direction: str = "DESC",
    ) -> dict[str, Any]:
        """Retrieve documents within a specific collection.

        Fetches a paginated list of documents that belong to the specified
        collection. Documents contain the actual content and metadata.

        Args:
            collection_id: The unique identifier of the collection
            limit: Maximum number of documents to return (default: 25)
            offset: Number of documents to skip for pagination (default: 0)
            sort: Field to sort by (default: "updatedAt")
            direction: Sort direction - "ASC" or "DESC" (default: "DESC")

        Returns:
            API response containing document data in the format:
            {
                "data": [
                    {
                        "id": "document-id",
                        "title": "Document Title",
                        "text": "Document content...",
                        "urlId": "document-slug",
                        "updatedAt": "2023-12-01T11:00:00Z",
                        "emoji": "📝",
                        ...
                    }
                ]
            }
        """
        return self.post(
            "documents.list",
            {
                "collection": collection_id,
                "limit": limit,
                "offset": offset,
                "sort": sort,
                "direction": direction,
            },
        )
