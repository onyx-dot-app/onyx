from unittest.mock import Mock
from unittest.mock import patch

import pytest
import requests

from onyx.connectors.outline.client import OutlineApiClient
from onyx.connectors.outline.client import OutlineClientAuthenticationError
from onyx.connectors.outline.client import OutlineClientRateLimitError
from onyx.connectors.outline.client import OutlineClientRequestFailedError


class TestOutlineApiClient:
    """Unit tests for OutlineApiClient"""

    def test_url_normalization(self) -> None:
        """Test URL normalization for different input formats"""
        # Test with https URL
        client = OutlineApiClient("https://example.com", "token")
        assert client.base_url == "https://example.com"

        # Test with http URL
        client = OutlineApiClient("http://example.com", "token")
        assert client.base_url == "http://example.com"

        # Test without protocol (should default to https)
        client = OutlineApiClient("example.com", "token")
        assert client.base_url == "https://example.com"

        # Test with trailing slash
        client = OutlineApiClient("https://example.com/", "token")
        assert client.base_url == "https://example.com"

        # Test with path
        client = OutlineApiClient("https://example.com/path/", "token")
        assert client.base_url == "https://example.com/path"

    def test_url_normalization_invalid(self) -> None:
        """Test URL normalization with invalid URLs"""
        with pytest.raises(ValueError, match="Invalid Outline base URL"):
            OutlineApiClient("", "token")

        # Test with URL that results in empty netloc after parsing
        with pytest.raises(ValueError, match="Invalid Outline base URL"):
            OutlineApiClient("http://", "token")

    def test_build_api_url(self) -> None:
        """Test API URL building"""
        client = OutlineApiClient("https://example.com", "token")

        # Test basic endpoint
        url = client._build_api_url("collections.list")
        assert url == "https://example.com/api/collections.list"

        # Test endpoint with leading slash
        url = client._build_api_url("/collections.list")
        assert url == "https://example.com/api/collections.list"

    def test_build_headers(self) -> None:
        """Test header building"""
        client = OutlineApiClient("https://example.com", "test-token")
        headers = client._build_headers()

        expected_headers = {
            "Authorization": "Bearer test-token",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        assert headers == expected_headers

    def test_retry_configuration(self) -> None:
        """Test retry configuration"""
        # Test default values
        client = OutlineApiClient("https://example.com", "token")
        assert client.max_retries == 3
        assert client.initial_backoff == 1.0

        # Test custom values
        client_custom = OutlineApiClient(
            "https://example.com", "token", max_retries=5, initial_backoff=2.0
        )
        assert client_custom.max_retries == 5
        assert client_custom.initial_backoff == 2.0

    @patch("requests.Session.post")
    def test_successful_request(self, mock_post: Mock) -> None:
        """Test successful API request"""
        # Mock successful response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [{"id": "123", "name": "Test Collection"}]
        }
        mock_post.return_value = mock_response

        client = OutlineApiClient("https://example.com", "token")
        result = client.get_collections()

        assert result == {"data": [{"id": "123", "name": "Test Collection"}]}
        mock_post.assert_called_once()

    @patch("requests.Session.post")
    def test_authentication_error(self, mock_post: Mock) -> None:
        """Test authentication error handling"""
        # Mock 401 response
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.json.return_value = {"message": "Unauthorized"}
        mock_post.return_value = mock_response

        client = OutlineApiClient("https://example.com", "invalid-token")

        with pytest.raises(OutlineClientAuthenticationError):
            client.get_collections()

    @patch("time.sleep")
    @patch("requests.Session.post")
    def test_rate_limit_error(self, mock_post: Mock, mock_sleep: Mock) -> None:
        """Test rate limit error handling with retries"""
        # Mock 429 response that persists through retries
        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.headers = {"Retry-After": "10"}
        mock_response.json.return_value = {"message": "Rate limit exceeded"}
        mock_post.return_value = mock_response

        # Use client with minimal retries to speed up test
        client = OutlineApiClient("https://example.com", "token", max_retries=1)

        with pytest.raises(OutlineClientRateLimitError) as exc_info:
            client.get_collections()

        assert exc_info.value.retry_after == 10
        # Should have tried max_retries + 1 times (initial + 1 retry)
        assert mock_post.call_count == 2
        # Should have slept once (after first failure, before final retry)
        mock_sleep.assert_called_once()

    @patch("time.sleep")
    @patch("requests.Session.post")
    def test_rate_limit_recovery(self, mock_post: Mock, mock_sleep: Mock) -> None:
        """Test successful recovery from rate limiting"""
        # First response is rate limited, second succeeds
        rate_limit_response = Mock()
        rate_limit_response.status_code = 429
        rate_limit_response.headers = {"Retry-After": "5"}
        rate_limit_response.json.return_value = {"message": "Rate limit exceeded"}

        success_response = Mock()
        success_response.status_code = 200
        success_response.json.return_value = {"data": [{"id": "123"}]}

        mock_post.side_effect = [rate_limit_response, success_response]

        client = OutlineApiClient("https://example.com", "token")
        result = client.get_collections()

        # Should succeed after retry
        assert result == {"data": [{"id": "123"}]}
        assert mock_post.call_count == 2
        mock_sleep.assert_called_once()

    @patch("requests.Session.post")
    def test_client_error(self, mock_post: Mock) -> None:
        """Test client error handling"""
        # Mock 400 response
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.json.return_value = {"message": "Bad Request"}
        mock_post.return_value = mock_response

        client = OutlineApiClient("https://example.com", "token")

        with pytest.raises(OutlineClientRequestFailedError) as exc_info:
            client.get_collections()

        assert exc_info.value.status_code == 400
        assert "Bad Request" in str(exc_info.value)

    @patch("requests.Session.post")
    def test_server_error(self, mock_post: Mock) -> None:
        """Test server error handling"""
        # Mock 500 response
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.reason = "Internal Server Error"
        mock_response.json.return_value = {}
        mock_post.return_value = mock_response

        client = OutlineApiClient("https://example.com", "token")

        with pytest.raises(OutlineClientRequestFailedError) as exc_info:
            client.get_collections()

        assert exc_info.value.status_code == 500

    @patch("requests.Session.post")
    def test_json_decode_error(self, mock_post: Mock) -> None:
        """Test handling of non-JSON responses"""
        # Mock response with invalid JSON
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.side_effect = requests.exceptions.JSONDecodeError(
            "No JSON object could be decoded", "", 0
        )
        mock_post.return_value = mock_response

        client = OutlineApiClient("https://example.com", "token")
        result = client.get_collections()

        # Should return empty dict on JSON decode error
        assert result == {}

    @patch("time.sleep")
    @patch("requests.Session.post")
    def test_request_exception_with_retry(
        self, mock_post: Mock, mock_sleep: Mock
    ) -> None:
        """Test handling of request exceptions with retry"""
        # Mock request exception on first call, success on second
        mock_post.side_effect = [
            requests.exceptions.ConnectionError("Connection failed"),
            Mock(status_code=200, json=lambda: {"data": []}),
        ]

        client = OutlineApiClient("https://example.com", "token")
        result = client.get_collections()

        # Should succeed after retry
        assert result == {"data": []}
        assert mock_post.call_count == 2
        mock_sleep.assert_called_once()

    @patch("requests.Session.post")
    def test_get_collections_with_params(self, mock_post: Mock) -> None:
        """Test get_collections with parameters"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": []}
        mock_post.return_value = mock_response

        client = OutlineApiClient("https://example.com", "token")
        client.get_collections(limit=50, offset=10, sort="name", direction="ASC")

        # Verify the request was made with correct data including new parameters
        call_args = mock_post.call_args
        assert call_args[1]["json"] == {
            "limit": 50,
            "offset": 10,
            "sort": "name",
            "direction": "ASC",
        }

    @patch("requests.Session.post")
    def test_get_collection_documents_with_params(self, mock_post: Mock) -> None:
        """Test get_collection_documents method"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [{"id": "doc123", "title": "Test Doc"}]
        }
        mock_post.return_value = mock_response

        client = OutlineApiClient("https://example.com", "token")
        result = client.get_collection_documents("col123", limit=10, offset=5)

        assert result == {"data": [{"id": "doc123", "title": "Test Doc"}]}
        call_args = mock_post.call_args
        assert call_args[1]["json"] == {
            "collection": "col123",
            "limit": 10,
            "offset": 5,
            "sort": "updatedAt",
            "direction": "DESC",
        }
