import json
from unittest.mock import MagicMock

import pytest
import requests

from onyx.oauth import discovery
from onyx.server.security.models import SSRFProtectionLevel
from onyx.utils.url import SSRFException

_AUTH_URL = "https://issuer.example/authorize"
_TOKEN_URL = "https://issuer.example/token"
_ISSUER = "https://issuer.example"


def _metadata(**updates: object) -> dict[str, object]:
    return {
        "issuer": _ISSUER,
        "authorization_endpoint": _AUTH_URL,
        "token_endpoint": _TOKEN_URL,
        **updates,
    }


def _response(body: object, status: int = 200) -> MagicMock:
    response = MagicMock(spec=requests.Response)
    response.__enter__.return_value = response
    response.status_code = status
    response.iter_content.return_value = [json.dumps(body).encode()]
    return response


def _session(monkeypatch: pytest.MonkeyPatch) -> tuple[MagicMock, MagicMock]:
    session = MagicMock(spec=requests.Session)
    session.__enter__.return_value = session
    session.cookies = MagicMock()
    monkeypatch.setattr(discovery, "ssrf_safe_get", session.get)
    settings = MagicMock()
    settings.ssrf_protection_level = SSRFProtectionLevel.VALIDATE_ALL
    monkeypatch.setattr(discovery, "get_security_settings", lambda: settings)
    guard = MagicMock()
    monkeypatch.setattr(discovery, "validate_oauth_endpoint_url", guard)
    return session, guard


@pytest.mark.parametrize(
    ("methods", "expected"),
    [
        (["S256"], "supported"),
        (["plain"], "unsupported"),
        ([], "unsupported"),
        ("S256", "unknown"),
        ([42], "unknown"),
        (None, "unknown"),
    ],
)
def test_capability_requires_a_valid_methods_list(
    monkeypatch: pytest.MonkeyPatch, methods: object, expected: str
) -> None:
    session, _ = _session(monkeypatch)
    session.get.return_value = _response(
        _metadata(code_challenge_methods_supported=methods)
    )
    assert discovery.detect_pkce_support(_AUTH_URL, _TOKEN_URL) == expected
    for call in session.get.call_args_list:
        assert call.kwargs["follow_redirects"] is False
        assert call.kwargs["stream"] is True
        assert call.kwargs["timeout"] <= 0.75
        assert call.kwargs["headers"] == {"Accept": "application/json"}
        assert call.kwargs["trust_env"] is False
        assert call.kwargs["https_only"] is True
        assert call.kwargs["allow_private_network"] is False


def test_verified_metadata_without_pkce_is_unsupported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, _ = _session(monkeypatch)
    session.get.return_value = _response(_metadata())
    assert discovery.detect_pkce_support(_AUTH_URL, _TOKEN_URL) == "unsupported"


@pytest.mark.parametrize(
    "field", ["issuer", "authorization_endpoint", "token_endpoint"]
)
def test_mismatched_metadata_is_not_trusted(
    monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    session, _ = _session(monkeypatch)
    session.get.return_value = _response(
        _metadata(
            **{field: "https://other.example"},
            code_challenge_methods_supported=["S256"],
        )
    )
    assert discovery.detect_pkce_support(_AUTH_URL, _TOKEN_URL) == "unknown"


@pytest.mark.parametrize("status", [301, 302, 307, 308, 404, 500])
def test_non_success_metadata_is_unknown(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    session, _ = _session(monkeypatch)
    response = _response(_metadata(code_challenge_methods_supported=["S256"]), status)
    session.get.return_value = response
    assert discovery.detect_pkce_support(_AUTH_URL, _TOKEN_URL) == "unknown"
    response.iter_content.assert_not_called()


def test_path_issuer_uses_oidc_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    session, _ = _session(monkeypatch)
    issuer = "https://issuer.example/realms/tenant"
    auth_url = issuer + "/protocol/openid-connect/auth"
    token_url = issuer + "/protocol/openid-connect/token"
    metadata = _metadata(
        issuer=issuer,
        authorization_endpoint=auth_url,
        token_endpoint=token_url,
        code_challenge_methods_supported=["S256"],
    )

    def get(url: str, **_: object) -> MagicMock:
        return _response(
            metadata if url == issuer + "/.well-known/openid-configuration" else {}, 200
        )

    session.get.side_effect = get
    assert discovery.detect_pkce_support(auth_url, token_url) == "supported"


@pytest.mark.parametrize("body", [None, [], "invalid", {}])
def test_malformed_metadata_is_unknown(
    monkeypatch: pytest.MonkeyPatch, body: object
) -> None:
    session, _ = _session(monkeypatch)
    session.get.return_value = _response(body)
    assert discovery.detect_pkce_support(_AUTH_URL, _TOKEN_URL) == "unknown"


def test_invalid_json_is_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    session, _ = _session(monkeypatch)
    response = _response({})
    response.iter_content.return_value = [b"not-json"]
    session.get.return_value = response
    assert discovery.detect_pkce_support(_AUTH_URL, _TOKEN_URL) == "unknown"


def test_timeout_is_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    session, _ = _session(monkeypatch)
    session.get.side_effect = requests.Timeout()
    assert discovery.detect_pkce_support(_AUTH_URL, _TOKEN_URL) == "unknown"


def test_blocked_discovery_url_is_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    session, _ = _session(monkeypatch)
    session.get.side_effect = SSRFException("blocked")
    assert discovery.detect_pkce_support(_AUTH_URL, _TOKEN_URL) == "unknown"


def test_size_limit_rejects_response(monkeypatch: pytest.MonkeyPatch) -> None:
    session, _ = _session(monkeypatch)
    response = _response({})
    response.iter_content.return_value = [b" " * (discovery._MAX_METADATA_BYTES + 1)]
    session.get.return_value = response
    assert discovery.detect_pkce_support(_AUTH_URL, _TOKEN_URL) == "unknown"


def test_total_budget_stops_slow_response(monkeypatch: pytest.MonkeyPatch) -> None:
    session, _ = _session(monkeypatch)
    session.get.return_value = _response(
        _metadata(code_challenge_methods_supported=["S256"])
    )
    monkeypatch.setattr(
        discovery.time, "monotonic", MagicMock(side_effect=[0, 0, 0, 11])
    )
    assert discovery.detect_pkce_support(_AUTH_URL, _TOKEN_URL) == "unknown"
    session.get.assert_called_once()


def test_path_issuer_uses_rfc8414_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    session, _ = _session(monkeypatch)
    issuer = "https://issuer.example/tenant"
    auth_url = issuer + "/authorize"
    token_url = issuer + "/token"
    metadata = _metadata(
        issuer=issuer,
        authorization_endpoint=auth_url,
        token_endpoint=token_url,
        code_challenge_methods_supported=["S256"],
    )
    session.get.return_value = _response(metadata)
    assert discovery.detect_pkce_support(auth_url, token_url) == "supported"
    assert session.get.call_args.args[0] == (
        "https://issuer.example/.well-known/oauth-authorization-server/tenant"
    )


def test_invalid_configured_endpoint_never_makes_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, guard = _session(monkeypatch)
    guard.side_effect = SSRFException("blocked")
    assert (
        discovery.detect_pkce_support("http://169.254.169.254/auth", _TOKEN_URL)
        == "unknown"
    )
    session.get.assert_not_called()


def test_candidate_count_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    session, _ = _session(monkeypatch)
    session.get.return_value = _response({}, 404)
    assert (
        discovery.detect_pkce_support(
            "https://issuer.example/a/b/c/d/e/f/authorize", _TOKEN_URL
        )
        == "unknown"
    )
    assert session.get.call_count == 11


@pytest.mark.parametrize(
    ("level", "allow_private", "block_loopback", "block_link_local"),
    [
        (SSRFProtectionLevel.ALLOW_PRIVATE_NETWORK, True, True, False),
        (SSRFProtectionLevel.DISABLED, True, False, True),
    ],
)
def test_discovery_preserves_tenant_network_policy(
    monkeypatch: pytest.MonkeyPatch,
    level: SSRFProtectionLevel,
    allow_private: bool,
    block_loopback: bool,
    block_link_local: bool,
) -> None:
    session, _ = _session(monkeypatch)
    settings = MagicMock()
    settings.ssrf_protection_level = level
    monkeypatch.setattr(discovery, "get_security_settings", lambda: settings)
    session.get.return_value = _response(_metadata())
    assert discovery.detect_pkce_support(_AUTH_URL, _TOKEN_URL) == "unsupported"
    kwargs = session.get.call_args.kwargs
    assert kwargs["allow_private_network"] is allow_private
    assert kwargs["block_loopback_and_link_local"] is block_loopback
    assert kwargs["block_link_local_only"] is block_link_local
