"""
Test cases for onyx/utils/gpu_utils.py with DISABLE_MODEL_SERVER environment variable
"""

import os
from unittest import TestCase
from unittest.mock import patch, MagicMock
import requests

from onyx.utils.gpu_utils import _get_gpu_status_from_model_server


class TestGPUUtils(TestCase):
    """Test cases for GPU utilities with DISABLE_MODEL_SERVER support"""

    @patch.dict(os.environ, {"DISABLE_MODEL_SERVER": "true"})
    def test_disable_model_server_true(self) -> None:
        """Test that GPU status returns False when DISABLE_MODEL_SERVER is true"""
        result = _get_gpu_status_from_model_server(indexing=False)
        assert result is False

    @patch.dict(os.environ, {"DISABLE_MODEL_SERVER": "True"})
    def test_disable_model_server_capital_true(self) -> None:
        """Test that GPU status returns False when DISABLE_MODEL_SERVER is True (capital)"""
        # "True" WILL trigger disable because .lower() is called
        result = _get_gpu_status_from_model_server(indexing=False)
        assert result is False

    @patch.dict(os.environ, {"DISABLE_MODEL_SERVER": "1"})
    @patch("requests.get")
    def test_disable_model_server_one(self, mock_get: MagicMock) -> None:
        """Test that GPU status makes request when DISABLE_MODEL_SERVER is 1"""
        # "1" should NOT trigger disable (only "true" should)
        mock_response = MagicMock()
        mock_response.json.return_value = {"gpu_available": True}
        mock_get.return_value = mock_response

        result = _get_gpu_status_from_model_server(indexing=False)
        assert result is True
        mock_get.assert_called_once()

    @patch.dict(os.environ, {"DISABLE_MODEL_SERVER": "yes"})
    @patch("requests.get")
    def test_disable_model_server_yes(self, mock_get: MagicMock) -> None:
        """Test that GPU status makes request when DISABLE_MODEL_SERVER is yes"""
        # "yes" should NOT trigger disable (only "true" should)
        mock_response = MagicMock()
        mock_response.json.return_value = {"gpu_available": False}
        mock_get.return_value = mock_response

        result = _get_gpu_status_from_model_server(indexing=True)
        assert result is False
        mock_get.assert_called_once()

    @patch.dict(os.environ, {"DISABLE_MODEL_SERVER": "false"})
    @patch("requests.get")
    def test_disable_model_server_false(self, mock_get: MagicMock) -> None:
        """Test that GPU status makes request when DISABLE_MODEL_SERVER is false"""
        mock_response = MagicMock()
        mock_response.json.return_value = {"gpu_available": True}
        mock_get.return_value = mock_response

        result = _get_gpu_status_from_model_server(indexing=True)
        assert result is True
        mock_get.assert_called_once()

    @patch.dict(os.environ, {}, clear=True)
    @patch("requests.get")
    def test_disable_model_server_not_set(self, mock_get: MagicMock) -> None:
        """Test that GPU status makes request when DISABLE_MODEL_SERVER is not set"""
        mock_response = MagicMock()
        mock_response.json.return_value = {"gpu_available": False}
        mock_get.return_value = mock_response

        result = _get_gpu_status_from_model_server(indexing=False)
        assert result is False
        mock_get.assert_called_once()

    def test_disabled_host_fallback(self) -> None:
        """Test that disabled host is handled correctly"""
        # Directly test the disabled host check
        with patch("onyx.utils.gpu_utils.INDEXING_MODEL_SERVER_HOST", "disabled"):
            result = _get_gpu_status_from_model_server(indexing=True)
            assert result is False

    @patch.dict(os.environ, {"DISABLE_MODEL_SERVER": "false"})
    @patch("requests.get")
    def test_request_exception_handling(self, mock_get: MagicMock) -> None:
        """Test that exceptions are properly raised when GPU status request fails"""
        mock_get.side_effect = requests.RequestException("Connection error")

        with self.assertRaises(requests.RequestException):
            _get_gpu_status_from_model_server(indexing=False)

    @patch.dict(os.environ, {"DISABLE_MODEL_SERVER": "true"})
    @patch("requests.get")
    def test_gpu_status_request_with_disable(self, mock_get: MagicMock) -> None:
        """Test that no request is made when DISABLE_MODEL_SERVER is true"""
        result = _get_gpu_status_from_model_server(indexing=True)
        assert result is False
        # Verify that no HTTP request was made
        mock_get.assert_not_called()