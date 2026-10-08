import importlib
import os
from pathlib import Path
from unittest.mock import patch

import certifi
import pytest

from onyx.document_index.opensearch.client import OpenSearchClient

_OS_TLS_ENV = (
    "SSL_CERT_FILE",
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


def test_ca_certs_falls_back_to_ssl_cert_file(tmp_path: Path) -> None:
    """customCACerts sets SSL_CERT_FILE, which opensearch-py ignores; the
    config must pass it through so internal-CA clusters verify."""
    bundle = tmp_path / "ca-certificates.crt"
    bundle.write_text("")
    import onyx.configs.app_configs as app_configs

    with patch.dict(os.environ, {}, clear=False):
        _clear_os_tls_env()
        os.environ["SSL_CERT_FILE"] = str(bundle)
        importlib.reload(app_configs)
        assert app_configs.OPENSEARCH_CA_CERTS == str(bundle)

        os.environ["OPENSEARCH_CA_CERTS"] = __file__
        importlib.reload(app_configs)
        assert app_configs.OPENSEARCH_CA_CERTS == __file__

        del os.environ["OPENSEARCH_CA_CERTS"]
        os.environ["SSL_CERT_FILE"] = "/no/such/bundle.crt"
        importlib.reload(app_configs)
        assert app_configs.OPENSEARCH_CA_CERTS is None
    importlib.reload(app_configs)


# --- readiness ping -------------------------------------------------------


def test_ping_logs_tls_failure() -> None:
    """A failed ping must log why it failed; opensearch-py's own ping() hides
    errors such as an untrusted server certificate."""
    from opensearchpy import SSLError

    with (
        patch("onyx.document_index.opensearch.client.OpenSearch") as mock_os,
        patch("onyx.document_index.opensearch.client.logger") as mock_logger,
    ):
        mock_os.return_value.transport.perform_request.side_effect = SSLError(
            "N/A", "CERTIFICATE_VERIFY_FAILED", None
        )
        assert OpenSearchClient().ping() is False
        logged: str = str(mock_logger.warning.call_args)
        assert "CERTIFICATE_VERIFY_FAILED" in logged


def test_ping_succeeds() -> None:
    with patch("onyx.document_index.opensearch.client.OpenSearch") as mock_os:
        mock_os.return_value.transport.perform_request.return_value = True
        assert OpenSearchClient().ping() is True
        mock_os.return_value.transport.perform_request.assert_called_once_with(
            "HEAD", "/"
        )
