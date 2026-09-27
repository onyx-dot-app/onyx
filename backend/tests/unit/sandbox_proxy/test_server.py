"""Unit tests for sandbox-proxy process configuration."""

import pytest

from onyx.sandbox_proxy import server


def test_mitm_options_use_custom_upstream_ca_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        server,
        "SANDBOX_PROXY_SSL_VERIFY_UPSTREAM_TRUSTED_CA",
        "/var/run/sandbox-proxy/upstream-ca-bundle.crt",
    )

    options = server._build_mitm_options()

    assert (
        options.ssl_verify_upstream_trusted_ca
        == "/var/run/sandbox-proxy/upstream-ca-bundle.crt"
    )
    assert options.ssl_insecure is False


def test_mitm_options_keep_default_trust_store_without_custom_ca(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server, "SANDBOX_PROXY_SSL_VERIFY_UPSTREAM_TRUSTED_CA", None)

    options = server._build_mitm_options()

    assert options.ssl_verify_upstream_trusted_ca is None
    assert options.ssl_insecure is False
