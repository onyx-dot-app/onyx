import importlib
import os
from unittest.mock import patch

import certifi
import pytest

from onyx.document_index.opensearch.client import OpenSearchClient

_OS_TLS_ENV = (
    "OPENSEARCH_VERIFY_CERTS",
    "OPENSEARCH_CA_CERTS",
    "OPENSEARCH_CLIENT_CERT",
    "OPENSEARCH_CLIENT_KEY",
)


# --- client wiring --------------------------------------------------------


def test_client_forwards_tls_kwargs() -> None:
    """The TLS settings must reach the underlying opensearch-py client — today
    verify_certs/ca_certs/client_cert/client_key aren't plumbed through at all."""
    with patch("onyx.document_index.opensearch.client.OpenSearch") as mock_os:
        OpenSearchClient(
            host="h",
            port=9200,
            use_ssl=True,
            verify_certs=True,
            ca_certs="/etc/ssl/os-ca.pem",
            client_cert="/etc/ssl/os-client.crt",
            client_key="/etc/ssl/os-client.key",
        )
        kwargs = mock_os.call_args.kwargs
        assert kwargs["use_ssl"] is True
        assert kwargs["verify_certs"] is True
        assert kwargs["ca_certs"] == "/etc/ssl/os-ca.pem"
        assert kwargs["client_cert"] == "/etc/ssl/os-client.crt"
        assert kwargs["client_key"] == "/etc/ssl/os-client.key"


def test_client_defaults_to_no_verification() -> None:
    """Back-compat: verification stays off by default so the bundled
    self-signed OpenSearch keeps working without opt-in config."""
    with patch("onyx.document_index.opensearch.client.OpenSearch") as mock_os:
        OpenSearchClient()
        assert mock_os.call_args.kwargs["verify_certs"] is False


# --- config validation ----------------------------------------------------


def _clear_os_tls_env() -> None:
    for var in _OS_TLS_ENV:
        os.environ.pop(var, None)


def test_client_cert_without_key_raises() -> None:
    with patch.dict(os.environ, {}, clear=False):
        _clear_os_tls_env()
        os.environ["OPENSEARCH_CLIENT_CERT"] = certifi.where()
        import onyx.configs.app_configs as app_configs

        with pytest.raises(ValueError, match="must both be set"):
            importlib.reload(app_configs)
    importlib.reload(app_configs)


def test_nonexistent_ca_raises() -> None:
    with patch.dict(os.environ, {}, clear=False):
        _clear_os_tls_env()
        os.environ["OPENSEARCH_CA_CERTS"] = "/no/such/os-ca.pem"
        import onyx.configs.app_configs as app_configs

        with pytest.raises(ValueError, match="does not exist"):
            importlib.reload(app_configs)
    importlib.reload(app_configs)
