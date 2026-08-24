from pathlib import Path
from types import TracebackType
from typing import Any
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

import pytest
from pydantic import ValidationError
from requests.exceptions import HTTPError
from simple_salesforce.exceptions import SalesforceExpiredSession

from onyx.connectors.interfaces import CredentialsProviderInterface
from onyx.connectors.salesforce import auth, salesforce_calls
from onyx.connectors.salesforce import connector as salesforce_connector
from onyx.connectors.salesforce.auth import (
    SalesforceOAuthTokenError,
    build_salesforce_client,
    exchange_salesforce_authorization_code,
    refresh_salesforce_oauth_credentials,
)
from onyx.connectors.salesforce.connector import SalesforceConnector
from onyx.connectors.salesforce.models import (
    SalesforceAuthenticationMethod,
    SalesforceLegacyCredentials,
    SalesforceOAuthCredentials,
    SalesforceSessionCredentials,
    parse_salesforce_credentials,
    validate_salesforce_my_domain_url,
)
from onyx.connectors.salesforce.onyx_salesforce import OnyxSalesforce

PRODUCTION_LOGIN_URL = "https://acme.my.salesforce.com"
SANDBOX_LOGIN_URL = "https://acme--dev.sandbox.my.salesforce.com"
INSTANCE_URL = "https://na123.salesforce.com"
OAUTH_CREDENTIALS = {
    "authentication_method": SalesforceAuthenticationMethod.OAUTH,
    "sf_access_token": "access-token",
    "sf_refresh_token": "refresh-token",
    "sf_instance_url": INSTANCE_URL,
    "sf_login_url": PRODUCTION_LOGIN_URL,
}
LEGACY_CREDENTIALS = {
    "sf_username": "admin@example.com",
    "sf_password": "password",
    "sf_security_token": "security-token",
    "is_sandbox": True,
}


class RecordingCredentialsProvider(CredentialsProviderInterface):
    def __init__(self, credentials: dict[str, Any]) -> None:
        self.credentials = credentials
        self.set_calls: list[dict[str, Any]] = []
        self.enter_count = 0

    def __enter__(self) -> "RecordingCredentialsProvider":
        self.enter_count += 1
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def get_tenant_id(self) -> str | None:
        return None

    def get_provider_key(self) -> str:
        return "salesforce-test"

    def get_credentials(self) -> dict[str, Any]:
        return self.credentials

    def set_credentials(self, credential_json: dict[str, Any]) -> None:
        self.credentials = credential_json
        self.set_calls.append(credential_json)

    def is_dynamic(self) -> bool:
        return True


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (PRODUCTION_LOGIN_URL, PRODUCTION_LOGIN_URL),
        (f"{PRODUCTION_LOGIN_URL}/", PRODUCTION_LOGIN_URL),
        (f"{PRODUCTION_LOGIN_URL}:443", PRODUCTION_LOGIN_URL),
        (SANDBOX_LOGIN_URL, SANDBOX_LOGIN_URL),
        ("https://ACME.MY.SALESFORCE.COM", PRODUCTION_LOGIN_URL),
    ],
)
def test_salesforce_my_domain_url_accepts_canonical_hosts(
    url: str, expected: str
) -> None:
    assert validate_salesforce_my_domain_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "acme.my.salesforce.com",
        "http://acme.my.salesforce.com",
        "https://my.salesforce.com",
        "https://salesforce.com",
        "https://acme.salesforce.com",
        "https://acme.my.salesforce.com.evil.example",
        "https://user:password@acme.my.salesforce.com",
        "https://@acme.my.salesforce.com",
        "https://acme.my.salesforce.com:8443",
        "https://acme.my.salesforce.com/services/oauth2/token",
        "https://acme.my.salesforce.com?",
        "https://acme.my.salesforce.com?target=evil",
        "https://acme.my.salesforce.com#",
        "https://acme.my.salesforce.com#fragment",
        "https://acme..my.salesforce.com",
        "https://acme.-dev.my.salesforce.com",
    ],
)
def test_salesforce_my_domain_url_rejects_noncanonical_urls(url: str) -> None:
    with pytest.raises(ValueError):
        validate_salesforce_my_domain_url(url)


def test_salesforce_credentials_dispatch_legacy_without_method() -> None:
    credentials = parse_salesforce_credentials(LEGACY_CREDENTIALS)

    assert isinstance(credentials, SalesforceLegacyCredentials)
    assert credentials.authentication_method is None
    assert credentials.is_sandbox is True


def test_salesforce_credentials_reject_unknown_method() -> None:
    with pytest.raises(ValueError, match="Unsupported Salesforce"):
        parse_salesforce_credentials({"authentication_method": "unknown"})


@patch("onyx.connectors.salesforce.auth.OnyxSalesforce")
def test_build_salesforce_client_constructs_legacy_client(
    salesforce_class: MagicMock,
) -> None:
    provider = RecordingCredentialsProvider(LEGACY_CREDENTIALS)

    build_salesforce_client(provider)

    salesforce_class.assert_called_once_with(
        username=LEGACY_CREDENTIALS["sf_username"],
        password=LEGACY_CREDENTIALS["sf_password"],
        security_token=LEGACY_CREDENTIALS["sf_security_token"],
        domain="test",
    )


@patch("onyx.connectors.salesforce.auth.OnyxSalesforce")
def test_build_salesforce_client_constructs_oauth_client(
    salesforce_class: MagicMock,
) -> None:
    provider = RecordingCredentialsProvider(OAUTH_CREDENTIALS)

    build_salesforce_client(provider)

    kwargs = salesforce_class.call_args.kwargs
    assert kwargs["session_id"] == OAUTH_CREDENTIALS["sf_access_token"]
    assert kwargs["instance_url"] == INSTANCE_URL
    assert callable(kwargs["refresh_callback"])
    assert "username" not in kwargs


@patch("onyx.connectors.salesforce.connector.build_salesforce_client")
def test_load_credentials_supports_oauth_static_provider(
    build_client: MagicMock,
) -> None:
    connector = SalesforceConnector()

    assert connector.load_credentials(OAUTH_CREDENTIALS) is None

    provider = build_client.call_args.args[0]
    parsed = parse_salesforce_credentials(provider.get_credentials())
    assert isinstance(parsed, SalesforceOAuthCredentials)


@patch("onyx.connectors.salesforce.connector.build_salesforce_client")
def test_load_credentials_supports_legacy_static_provider(
    build_client: MagicMock,
) -> None:
    connector = SalesforceConnector()

    assert connector.load_credentials(LEGACY_CREDENTIALS) is None

    provider = build_client.call_args.args[0]
    parsed = parse_salesforce_credentials(provider.get_credentials())
    assert isinstance(parsed, SalesforceLegacyCredentials)


def _token_response(
    *,
    access_token: str = "new-access-token",
    refresh_token: str | None = "new-refresh-token",
    instance_url: str = INSTANCE_URL,
) -> MagicMock:
    response = MagicMock()
    response.ok = True
    payload = {
        "access_token": access_token,
        "instance_url": instance_url,
    }
    if refresh_token is not None:
        payload["refresh_token"] = refresh_token
    response.json.return_value = payload
    return response


def _configure_oauth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "SALESFORCE_CLIENT_ID", "client-id")
    monkeypatch.setattr(auth, "SALESFORCE_CLIENT_SECRET", "client-secret")


def test_authorization_code_exchange_uses_typed_form(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_oauth(monkeypatch)
    request = MagicMock(return_value=_token_response())
    monkeypatch.setattr(auth, "request_with_retries", request)

    credentials = exchange_salesforce_authorization_code(
        login_url=f"{PRODUCTION_LOGIN_URL}/",
        code="authorization-code",
        redirect_uri="https://onyx.example/oauth/callback",
        code_verifier="pkce-verifier",
    )

    assert credentials == SalesforceOAuthCredentials(
        authentication_method=SalesforceAuthenticationMethod.OAUTH,
        sf_access_token="new-access-token",
        sf_refresh_token="new-refresh-token",
        sf_instance_url=INSTANCE_URL,
        sf_login_url=PRODUCTION_LOGIN_URL,
    )
    assert request.call_args.kwargs["url"] == (
        f"{PRODUCTION_LOGIN_URL}/services/oauth2/token"
    )
    assert request.call_args.kwargs["log_request_data"] is False
    assert request.call_args.kwargs["tries"] == 1
    assert request.call_args.kwargs["data"] == {
        "grant_type": "authorization_code",
        "code": "authorization-code",
        "client_id": "client-id",
        "client_secret": "client-secret",
        "redirect_uri": "https://onyx.example/oauth/callback",
        "code_verifier": "pkce-verifier",
    }


def _error_response(payload: Any, status_code: int = 400) -> MagicMock:
    response = MagicMock()
    response.ok = False
    response.status_code = status_code
    response.json.return_value = payload
    return response


def test_token_exchange_includes_safe_structured_oauth_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_oauth(monkeypatch)
    response = _error_response(
        {
            "error": "invalid_grant",
            "error_description": (
                "Rejected authorization-code with client-secret and pkce-verifier"
            ),
        }
    )
    monkeypatch.setattr(
        auth,
        "request_with_retries",
        MagicMock(side_effect=HTTPError(response=response)),
    )

    with pytest.raises(SalesforceOAuthTokenError) as exc_info:
        exchange_salesforce_authorization_code(
            login_url=PRODUCTION_LOGIN_URL,
            code="authorization-code",
            redirect_uri="https://onyx.example/oauth/callback",
            code_verifier="pkce-verifier",
        )

    message = str(exc_info.value)
    assert message.startswith(
        "Salesforce token request failed with status 400: invalid_grant:"
    )
    assert message.count("[REDACTED]") == 3
    assert "authorization-code" not in message
    assert "client-secret" not in message
    assert "pkce-verifier" not in message


@patch("onyx.utils.retry_wrapper.requests.request")
def test_token_exchange_does_not_retry_terminal_oauth_error(
    request: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_oauth(monkeypatch)
    response = _error_response({"error": "invalid_grant"})
    response.raise_for_status.side_effect = HTTPError(response=response)
    request.return_value = response

    with pytest.raises(SalesforceOAuthTokenError):
        exchange_salesforce_authorization_code(
            login_url=PRODUCTION_LOGIN_URL,
            code="authorization-code",
            redirect_uri="https://onyx.example/oauth/callback",
            code_verifier="pkce-verifier",
        )

    request.assert_called_once()


def test_token_refresh_redacts_sensitive_values_from_oauth_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_oauth(monkeypatch)
    response = _error_response(
        {
            "error": "invalid_grant",
            "error_description": "Rejected refresh-token with client-secret",
        }
    )
    monkeypatch.setattr(
        auth,
        "request_with_retries",
        MagicMock(side_effect=HTTPError(response=response)),
    )

    with pytest.raises(SalesforceOAuthTokenError) as exc_info:
        refresh_salesforce_oauth_credentials(
            SalesforceOAuthCredentials.model_validate(OAUTH_CREDENTIALS)
        )

    message = str(exc_info.value)
    assert message.count("[REDACTED]") == 2
    assert "refresh-token" not in message
    assert "client-secret" not in message


def test_token_exchange_uses_generic_error_for_malformed_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_oauth(monkeypatch)
    monkeypatch.setattr(
        auth,
        "request_with_retries",
        MagicMock(
            return_value=_error_response(
                {"error": ["invalid_grant"], "error_description": {"message": "bad"}},
                status_code=429,
            )
        ),
    )

    with pytest.raises(
        SalesforceOAuthTokenError,
        match=r"^Salesforce token request failed with status 429$",
    ):
        exchange_salesforce_authorization_code(
            login_url=PRODUCTION_LOGIN_URL,
            code="authorization-code",
            redirect_uri="https://onyx.example/oauth/callback",
            code_verifier="pkce-verifier",
        )


def test_token_exchange_uses_generic_error_for_non_json_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_oauth(monkeypatch)
    response = _error_response(None, status_code=502)
    response.json.side_effect = ValueError("not JSON")
    monkeypatch.setattr(
        auth,
        "request_with_retries",
        MagicMock(return_value=response),
    )

    with pytest.raises(
        SalesforceOAuthTokenError,
        match=r"^Salesforce token request failed with status 502$",
    ):
        exchange_salesforce_authorization_code(
            login_url=PRODUCTION_LOGIN_URL,
            code="authorization-code",
            redirect_uri="https://onyx.example/oauth/callback",
            code_verifier="pkce-verifier",
        )


def test_authorization_code_exchange_requires_refresh_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_oauth(monkeypatch)
    monkeypatch.setattr(
        auth,
        "request_with_retries",
        MagicMock(return_value=_token_response(refresh_token=None)),
    )

    with pytest.raises(ValueError, match="did not include a refresh token"):
        exchange_salesforce_authorization_code(
            login_url=PRODUCTION_LOGIN_URL,
            code="authorization-code",
            redirect_uri="https://onyx.example/oauth/callback",
            code_verifier="pkce-verifier",
        )


def test_refresh_token_falls_back_to_existing_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_oauth(monkeypatch)
    request = MagicMock(return_value=_token_response(refresh_token=None))
    monkeypatch.setattr(auth, "request_with_retries", request)
    current = SalesforceOAuthCredentials.model_validate(OAUTH_CREDENTIALS)

    refreshed = refresh_salesforce_oauth_credentials(current)

    assert refreshed.sf_access_token == "new-access-token"
    assert refreshed.sf_refresh_token == "refresh-token"
    assert request.call_args.kwargs["data"]["grant_type"] == "refresh_token"


@patch("onyx.connectors.salesforce.auth.OnyxSalesforce")
def test_refresh_callback_persists_rotated_credentials(
    salesforce_class: MagicMock,
) -> None:
    provider = RecordingCredentialsProvider(OAUTH_CREDENTIALS.copy())
    rotated = SalesforceOAuthCredentials(
        authentication_method=SalesforceAuthenticationMethod.OAUTH,
        sf_access_token="rotated-access-token",
        sf_refresh_token="rotated-refresh-token",
        sf_instance_url="https://na456.salesforce.com",
        sf_login_url=PRODUCTION_LOGIN_URL,
    )

    with patch(
        "onyx.connectors.salesforce.auth.refresh_salesforce_oauth_credentials",
        return_value=rotated,
    ) as refresh:
        build_salesforce_client(provider)
        callback = salesforce_class.call_args.kwargs["refresh_callback"]
        session = callback("access-token")

    refresh.assert_called_once()
    assert provider.enter_count == 1
    assert provider.set_calls == [rotated.model_dump(mode="json")]
    assert session == SalesforceSessionCredentials(
        sf_access_token="rotated-access-token",
        sf_instance_host="na456.salesforce.com",
    )


@patch("onyx.connectors.salesforce.auth.OnyxSalesforce")
def test_refresh_callback_reuses_credentials_rotated_by_other_job(
    salesforce_class: MagicMock,
) -> None:
    provider = RecordingCredentialsProvider(
        {
            **OAUTH_CREDENTIALS,
            "sf_access_token": "already-rotated-access-token",
        }
    )

    with patch(
        "onyx.connectors.salesforce.auth.refresh_salesforce_oauth_credentials"
    ) as refresh:
        build_salesforce_client(provider)
        callback = salesforce_class.call_args.kwargs["refresh_callback"]
        session = callback("expired-access-token")

    refresh.assert_not_called()
    assert provider.set_calls == []
    assert session.sf_access_token == "already-rotated-access-token"


def test_onyx_salesforce_refreshes_invalid_session_mid_run() -> None:
    invalid_session = MagicMock(status_code=401)
    invalid_session.json.return_value = [{"errorCode": "INVALID_SESSION_ID"}]
    successful_response = MagicMock(status_code=200, headers={})
    session = MagicMock()
    session.proxies = {}
    session.request.side_effect = [invalid_session, successful_response]
    refresh_callback = MagicMock(
        return_value=SalesforceSessionCredentials(
            sf_access_token="new-access-token",
            sf_instance_host="na456.salesforce.com",
        )
    )
    client = OnyxSalesforce(
        session_id="expired-access-token",
        instance_url=INSTANCE_URL,
        session=session,
        refresh_callback=refresh_callback,
    )

    response = client._call_salesforce(
        "GET", f"{INSTANCE_URL}/services/data/v59.0/sobjects"
    )

    assert response is successful_response
    refresh_callback.assert_called_once_with("expired-access-token")
    assert client.session_id == "new-access-token"
    assert client.sf_instance == "na456.salesforce.com"
    assert (
        session.request.call_args_list[1]
        .args[1]
        .startswith("https://na456.salesforce.com/")
    )
    assert session.request.call_args_list[1].kwargs["headers"]["Authorization"] == (
        "Bearer new-access-token"
    )


@pytest.mark.parametrize("payload", [[], {}, "unauthorized"])
def test_onyx_salesforce_routes_malformed_unauthorized_response(
    payload: Any,
) -> None:
    unauthorized = MagicMock(
        status_code=401,
        url=f"{INSTANCE_URL}/services/data/v59.0/sobjects",
        text="unauthorized",
    )
    unauthorized.json.return_value = payload
    session = MagicMock()
    session.proxies = {}
    session.request.return_value = unauthorized
    refresh_callback = MagicMock()
    client = OnyxSalesforce(
        session_id="expired-access-token",
        instance_url=INSTANCE_URL,
        session=session,
        refresh_callback=refresh_callback,
    )

    with pytest.raises(SalesforceExpiredSession):
        client._call_salesforce("GET", unauthorized.url)

    refresh_callback.assert_not_called()


def test_bulk_download_rebuilds_client_after_session_refresh(tmp_path: Path) -> None:
    original_path = tmp_path / "result.csv"
    original_path.write_text("Id\n001\n")
    expired = SalesforceExpiredSession(
        INSTANCE_URL,
        401,
        "Contact",
        b"INVALID_SESSION_ID",
    )
    expired_bulk_type = MagicMock()
    expired_bulk_type.download.side_effect = expired
    refreshed_bulk_type = MagicMock()
    refreshed_bulk_type.download.return_value = [{"file": str(original_path)}]

    sf_client = MagicMock(spec=OnyxSalesforce)
    sf_client.session_id = "expired-access-token"
    sf_client.bulk2_url = f"{INSTANCE_URL}/services/data/v59.0/jobs/"
    sf_client.proxies = {}
    sf_client.session = MagicMock()

    def refresh_session() -> None:
        sf_client.session_id = "new-access-token"

    sf_client.refresh_session.side_effect = refresh_session
    bulk_handler = MagicMock(
        bulk2_url=sf_client.bulk2_url,
        headers={},
        session=sf_client.session,
    )
    with (
        patch.object(
            salesforce_calls, "SFBulk2Handler", return_value=bulk_handler
        ) as handler,
        patch.object(
            salesforce_calls,
            "SFBulk2Type",
            side_effect=[expired_bulk_type, refreshed_bulk_type],
        ),
    ):
        sf_type, paths = salesforce_calls._bulk_retrieve_from_salesforce(
            "Contact",
            "SELECT Id FROM Contact",
            str(tmp_path),
            sf_client,
        )

    assert sf_type == "Contact"
    assert paths == [str(tmp_path / "Contact.result.csv")]
    sf_client.refresh_session.assert_called_once_with()
    assert [call.kwargs["session_id"] for call in handler.call_args_list] == [
        "expired-access-token",
        "new-access-token",
    ]


def test_oauth_credentials_reject_untrusted_instance_url() -> None:
    with pytest.raises(ValidationError):
        SalesforceOAuthCredentials.model_validate(
            {
                **OAUTH_CREDENTIALS,
                "sf_instance_url": "https://internal.example",
            }
        )


@pytest.mark.parametrize("login_url", [PRODUCTION_LOGIN_URL, SANDBOX_LOGIN_URL])
def test_salesforce_authorization_url_uses_my_domain_and_pkce(
    monkeypatch: pytest.MonkeyPatch, login_url: str
) -> None:
    monkeypatch.setattr(salesforce_connector, "SALESFORCE_CLIENT_ID", "client-id")

    authorization_url = SalesforceConnector.oauth_authorization_url(
        base_domain="https://onyx.example/",
        state="oauth-state",
        additional_kwargs={"salesforce_my_domain_url": login_url},
        code_challenge="pkce-challenge",
    )

    parsed = urlsplit(authorization_url)
    assert f"{parsed.scheme}://{parsed.netloc}" == login_url
    assert parsed.path == "/services/oauth2/authorize"
    assert parse_qs(parsed.query) == {
        "client_id": ["client-id"],
        "response_type": ["code"],
        "redirect_uri": ["https://onyx.example/connector/oauth/callback/salesforce"],
        "scope": ["api refresh_token"],
        "state": ["oauth-state"],
        "code_challenge": ["pkce-challenge"],
        "code_challenge_method": ["S256"],
    }


def test_salesforce_code_exchange_requires_pkce_verifier() -> None:
    with pytest.raises(ValueError, match="PKCE code verifier"):
        SalesforceConnector.oauth_code_to_token(
            base_domain="https://onyx.example",
            code="authorization-code",
            additional_kwargs={"salesforce_my_domain_url": PRODUCTION_LOGIN_URL},
        )


def test_salesforce_code_exchange_returns_json_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exchange = MagicMock(
        return_value=SalesforceOAuthCredentials.model_validate(OAUTH_CREDENTIALS)
    )
    monkeypatch.setattr(
        salesforce_connector, "exchange_salesforce_authorization_code", exchange
    )

    credentials = SalesforceConnector.oauth_code_to_token(
        base_domain="https://onyx.example/",
        code="authorization-code",
        additional_kwargs={"salesforce_my_domain_url": PRODUCTION_LOGIN_URL},
        code_verifier="pkce-verifier",
    )

    assert credentials == OAUTH_CREDENTIALS
    exchange.assert_called_once_with(
        login_url=PRODUCTION_LOGIN_URL,
        code="authorization-code",
        redirect_uri="https://onyx.example/connector/oauth/callback/salesforce",
        code_verifier="pkce-verifier",
    )


@pytest.mark.parametrize(
    ("client_id", "client_secret", "expected"),
    [
        ("client-id", "client-secret", True),
        (None, "client-secret", False),
        ("client-id", None, False),
        (None, None, False),
    ],
)
def test_salesforce_oauth_enabled_requires_both_client_values(
    monkeypatch: pytest.MonkeyPatch,
    client_id: str | None,
    client_secret: str | None,
    expected: bool,
) -> None:
    monkeypatch.setattr(salesforce_connector, "SALESFORCE_CLIENT_ID", client_id)
    monkeypatch.setattr(salesforce_connector, "SALESFORCE_CLIENT_SECRET", client_secret)

    assert SalesforceConnector.oauth_enabled() is expected
    assert SalesforceConnector.supports_manual_credentials is True
