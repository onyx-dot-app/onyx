import base64
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from requests.exceptions import HTTPError
from requests.exceptions import RequestException
from requests.exceptions import Timeout
from urllib3.util.retry import Retry

from onyx.utils.logger import setup_logger

logger = setup_logger()
PAGE_SIZE = 100


class HighspotClientError(Exception):
    """Base exception for Highspot API client errors."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


class HighspotAuthenticationError(HighspotClientError):
    """Exception raised for authentication errors."""


class HighspotRateLimitError(HighspotClientError):
    """Exception raised when rate limit is exceeded."""

    def __init__(self, message: str, retry_after: Optional[str] = None):
        self.retry_after = retry_after
        super().__init__(message)


class HighspotClient:
    """
    Client for interacting with the Highspot API.

    Uses basic authentication with provided key (username) and secret (password).
    Implements retry logic, error handling, and connection pooling.
    """

    BASE_URL = "https://api-su2.highspot.com/v1.0/"

    def __init__(
        self,
        key: str,
        secret: str,
        base_url: str = BASE_URL,
        timeout: int = 30,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        status_forcelist: Optional[List[int]] = None,
    ):
        """
        Initialize the Highspot API client.

        Args:
            key: API key (used as username)
            secret: API secret (used as password)
            base_url: Base URL for the Highspot API
            timeout: Request timeout in seconds
            max_retries: Maximum number of retries for failed requests
            backoff_factor: Backoff factor for retries
            status_forcelist: HTTP status codes to retry on
        """
        if not key or not secret:
            raise ValueError("API key and secret are required")

        self.key = key
        self.secret = secret
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout = timeout

        # Set up session with retry logic
        self.session = requests.Session()
        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=backoff_factor,
            status_forcelist=status_forcelist or [429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST", "PUT", "DELETE"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        # Set up authentication
        self._setup_auth()

    def _setup_auth(self) -> None:
        """Set up basic authentication for the session."""
        auth = f"{self.key}:{self.secret}"
        encoded_auth = base64.b64encode(auth.encode()).decode()
        self.session.headers.update(
            {
                "Authorization": f"Basic {encoded_auth}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )

    def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Make a request to the Highspot API.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint
            params: URL parameters
            data: Form data
            json_data: JSON data
            headers: Additional headers

        Returns:
            API response as a dictionary

        Raises:
            HighspotClientError: On API errors
            HighspotAuthenticationError: On authentication errors
            HighspotRateLimitError: On rate limiting
            requests.exceptions.RequestException: On request failures
        """
        url = urljoin(self.base_url, endpoint)
        request_headers = {}
        if headers:
            request_headers.update(headers)

        try:
            logger.debug(f"Making {method} request to {url}")
            response = self.session.request(
                method=method,
                url=url,
                params=params,
                data=data,
                json=json_data,
                headers=request_headers,
                timeout=self.timeout,
            )
            response.raise_for_status()

            if response.content and response.content.strip():
                return response.json()
            return {}

        except HTTPError as e:
            status_code = e.response.status_code
            error_msg = str(e)

            try:
                error_data = e.response.json()
                if isinstance(error_data, dict):
                    error_msg = error_data.get("message", str(e))
            except (ValueError, KeyError):
                pass

            if status_code == 401:
                raise HighspotAuthenticationError(f"Authentication failed: {error_msg}")
            elif status_code == 429:
                retry_after = e.response.headers.get("Retry-After")
                raise HighspotRateLimitError(
                    f"Rate limit exceeded: {error_msg}", retry_after=retry_after
                )
            else:
                raise HighspotClientError(
                    f"API error {status_code}: {error_msg}", status_code=status_code
                )

        except Timeout:
            raise HighspotClientError("Request timed out")
        except RequestException as e:
            raise HighspotClientError(f"Request failed: {str(e)}")

    def get_spots(self) -> List[Dict[str, Any]]:
        """
        Get all available spots, paginated.

        Returns:
            List of spots with their names and IDs
        """
        all_spots = []
        has_more = True
        current_offset = 0

        while has_more:
            params = {"right": "view", "start": current_offset, "limit": PAGE_SIZE}
            response = self._make_request("GET", "spots", params=params)
            found_spots = response.get("collection", [])
            logger.info(f"Received {len(found_spots)} spots at offset {current_offset}")
            all_spots.extend(found_spots)
            if len(found_spots) < PAGE_SIZE:
                has_more = False
            else:
                current_offset += PAGE_SIZE
        logger.info(f"Total spots retrieved: {len(all_spots)}")
        return all_spots

    def get_spot(self, spot_id: str) -> Dict[str, Any]:
        """
        Get details for a specific spot.

        Args:
            spot_id: ID of the spot

        Returns:
            Spot details
        """
        if not spot_id:
            raise ValueError("spot_id is required")
        return self._make_request("GET", f"spots/{spot_id}")

    def get_spot_items(
        self, spot_id: str, offset: int = 0, page_size: int = PAGE_SIZE
    ) -> Dict[str, Any]:
        """
        Get items in a specific spot.

        Args:
            spot_id: ID of the spot
            offset: offset number
            page_size: Number of items per page

        Returns:
            Items in the spot
        """
        if not spot_id:
            raise ValueError("spot_id is required")

        params = {"spot": spot_id, "start": offset, "limit": page_size}
        return self._make_request("GET", "items", params=params)

    def get_item(self, item_id: str) -> Dict[str, Any]:
        """
        Get details for a specific item.

        Args:
            item_id: ID of the item

        Returns:
            Item details
        """
        if not item_id:
            raise ValueError("item_id is required")
        return self._make_request("GET", f"items/{item_id}")

    def get_item_content(self, item_id: str) -> bytes:
        """
        Get the raw content of an item.

        Args:
            item_id: ID of the item

        Returns:
            Raw content bytes
        """
        if not item_id:
            raise ValueError("item_id is required")

        url = urljoin(self.base_url, f"items/{item_id}/content")
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        return response.content

    def health_check(self) -> bool:
        """
        Check if the API is accessible and credentials are valid.

        Returns:
            True if API is accessible, False otherwise
        """
        try:
            self._make_request("GET", "spots", params={"limit": 1})
            return True
        except (HighspotClientError, HighspotAuthenticationError):
            return False
