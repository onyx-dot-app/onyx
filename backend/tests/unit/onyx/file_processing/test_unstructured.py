from unittest.mock import patch

from onyx.file_processing import unstructured


def test_unstructured_client_kwargs_omits_server_url_when_unset() -> None:
    with (
        patch.object(unstructured, "UNSTRUCTURED_API_URL", ""),
        patch.object(unstructured, "get_unstructured_api_key", return_value="test-key"),
    ):
        kwargs = unstructured._unstructured_client_kwargs()

    assert kwargs == {"api_key_auth": "test-key"}


def test_unstructured_client_kwargs_uses_configured_server_url() -> None:
    with (
        patch.object(unstructured, "UNSTRUCTURED_API_URL", "http://unstructured:8000"),
        patch.object(unstructured, "get_unstructured_api_key", return_value="test-key"),
    ):
        kwargs = unstructured._unstructured_client_kwargs()

    assert kwargs == {
        "api_key_auth": "test-key",
        "server_url": "http://unstructured:8000",
    }
