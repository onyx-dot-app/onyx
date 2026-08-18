from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from fastapi import Request
from sqlalchemy.orm import Session

from onyx.auth.pkce import compute_s256_challenge, generate_pkce_pair
from onyx.configs.constants import DocumentSource
from onyx.connectors.egnyte.connector import EgnyteConnector
from onyx.connectors.interfaces import OAuthConnector
from onyx.connectors.linear.connector import LinearConnector
from onyx.db.models import User
from onyx.error_handling.exceptions import OnyxError
from onyx.redis.tenant_redis_client import TenantRedisClient
from onyx.server.documents import standard_oauth
from onyx.server.documents.standard_oauth import OAuthState


class DisabledOAuthConnector(OAuthConnector):
    supports_manual_credentials = True

    @classmethod
    def oauth_enabled(cls) -> bool:
        return False

    @classmethod
    def oauth_id(cls) -> DocumentSource:
        return DocumentSource.LINEAR

    @classmethod
    def oauth_authorization_url(
        cls,
        base_domain: str,  # noqa: ARG003
        state: str,  # noqa: ARG003
        additional_kwargs: dict[str, str],  # noqa: ARG003
        code_challenge: str | None = None,  # noqa: ARG003
    ) -> str:
        raise AssertionError("Disabled OAuth must not authorize")

    @classmethod
    def oauth_code_to_token(
        cls,
        base_domain: str,  # noqa: ARG003
        code: str,  # noqa: ARG003
        additional_kwargs: dict[str, str],  # noqa: ARG003
        code_verifier: str | None = None,  # noqa: ARG003
    ) -> dict[str, Any]:
        raise AssertionError("Disabled OAuth must not exchange tokens")


class PKCEOAuthConnector(OAuthConnector):
    supports_pkce = True

    @classmethod
    def oauth_id(cls) -> DocumentSource:
        return DocumentSource.LINEAR

    @classmethod
    def oauth_authorization_url(
        cls,
        base_domain: str,  # noqa: ARG003
        state: str,  # noqa: ARG003
        additional_kwargs: dict[str, str],  # noqa: ARG003
        code_challenge: str | None = None,  # noqa: ARG003
    ) -> str:
        return "https://provider.example/authorize"

    @classmethod
    def oauth_code_to_token(
        cls,
        base_domain: str,  # noqa: ARG003
        code: str,  # noqa: ARG003
        additional_kwargs: dict[str, str],  # noqa: ARG003
        code_verifier: str | None = None,  # noqa: ARG003
    ) -> dict[str, Any]:
        return {"access_token": "token"}


def _request(query_string: bytes = b"") -> Request:
    return Request({"type": "http", "query_string": query_string})


def test_pkce_generator_uses_s256() -> None:
    code_verifier, code_challenge = generate_pkce_pair()

    assert compute_s256_challenge(code_verifier) == code_challenge


def test_authorize_stores_verifier_and_passes_challenge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis_client = MagicMock()
    authorization_url = MagicMock(return_value="https://provider.example/authorize")
    monkeypatch.setattr(
        standard_oauth,
        "_discover_oauth_connectors",
        lambda: {DocumentSource.LINEAR: PKCEOAuthConnector},
    )
    monkeypatch.setattr(standard_oauth, "get_redis_client", lambda **_: redis_client)
    monkeypatch.setattr(
        standard_oauth, "generate_pkce_pair", lambda: ("verifier", "challenge")
    )
    monkeypatch.setattr(
        PKCEOAuthConnector, "oauth_authorization_url", authorization_url
    )

    response = standard_oauth.oauth_authorize(
        request=_request(),
        source=DocumentSource.LINEAR,
        desired_return_url="https://onyx.example/return",
        _=cast(User, object()),
    )

    assert response.redirect_url == "https://provider.example/authorize"
    stored_state = OAuthState.model_validate_json(redis_client.set.call_args.args[1])
    assert stored_state.code_verifier == "verifier"
    authorization_url.assert_called_once()
    assert authorization_url.call_args.args[3] == "challenge"


def test_authorize_skips_pkce_for_existing_connector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis_client = MagicMock()
    authorization_url = MagicMock(return_value="https://linear.app/oauth/authorize")
    generate_pkce_pair_mock = MagicMock()
    monkeypatch.setattr(
        standard_oauth,
        "_discover_oauth_connectors",
        lambda: {DocumentSource.LINEAR: LinearConnector},
    )
    monkeypatch.setattr(standard_oauth, "get_redis_client", lambda **_: redis_client)
    monkeypatch.setattr(standard_oauth, "generate_pkce_pair", generate_pkce_pair_mock)
    monkeypatch.setattr(LinearConnector, "oauth_authorization_url", authorization_url)

    standard_oauth.oauth_authorize(
        request=_request(),
        source=DocumentSource.LINEAR,
        desired_return_url="https://onyx.example/return",
        _=cast(User, object()),
    )

    generate_pkce_pair_mock.assert_not_called()
    stored_state = OAuthState.model_validate_json(redis_client.set.call_args.args[1])
    assert stored_state.code_verifier is None
    assert authorization_url.call_args.args[3] is None


def test_callback_consumes_state_and_passes_verifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oauth_state = OAuthState(
        desired_return_url="https://onyx.example/return",
        additional_kwargs={"instance": "example"},
        code_verifier="verifier",
    )
    redis_client = MagicMock()
    redis_client.getdel.return_value = oauth_state.model_dump_json().encode()
    code_to_token = MagicMock(return_value={"access_token": "token"})
    monkeypatch.setattr(
        standard_oauth,
        "_discover_oauth_connectors",
        lambda: {DocumentSource.LINEAR: PKCEOAuthConnector},
    )
    monkeypatch.setattr(standard_oauth, "get_redis_client", lambda: redis_client)
    monkeypatch.setattr(PKCEOAuthConnector, "oauth_code_to_token", code_to_token)
    monkeypatch.setattr(
        standard_oauth,
        "create_credential",
        lambda **_: SimpleNamespace(id=7),
    )

    response = standard_oauth.oauth_callback(
        source=DocumentSource.LINEAR,
        code="authorization-code",
        state="state-id",
        db_session=cast(Session, object()),
        user=cast(User, object()),
    )

    assert response.redirect_url == "https://onyx.example/return?credentialId=7"
    redis_client.getdel.assert_called_once_with("oauth_state:state-id")
    code_to_token.assert_called_once_with(
        standard_oauth.WEB_DOMAIN,
        "authorization-code",
        {"instance": "example"},
        "verifier",
    )


def test_callback_rejects_consumed_state(monkeypatch: pytest.MonkeyPatch) -> None:
    redis_client = MagicMock()
    redis_client.getdel.return_value = None
    monkeypatch.setattr(
        standard_oauth,
        "_discover_oauth_connectors",
        lambda: {DocumentSource.LINEAR: PKCEOAuthConnector},
    )
    monkeypatch.setattr(standard_oauth, "get_redis_client", lambda: redis_client)

    with pytest.raises(OnyxError, match="Invalid OAuth state"):
        standard_oauth.oauth_callback(
            source=DocumentSource.LINEAR,
            code="authorization-code",
            state="consumed-state",
            db_session=cast(Session, object()),
            user=cast(User, object()),
        )


def test_tenant_redis_getdel_prefixes_key() -> None:
    raw_client = MagicMock()
    raw_client.getdel.return_value = b"value"
    redis_client = TenantRedisClient("tenant", raw_client)

    assert redis_client.getdel("oauth_state:state-id") == b"value"
    raw_client.getdel.assert_called_once_with("tenant:oauth_state:state-id")


def test_oauth_details_reports_manual_capability_when_oauth_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        standard_oauth,
        "_discover_oauth_connectors",
        lambda: {DocumentSource.LINEAR: DisabledOAuthConnector},
    )

    details = standard_oauth.oauth_details(
        source=DocumentSource.LINEAR, _=cast(User, object())
    )

    assert details.oauth_enabled is False
    assert details.supports_manual_credentials is True
    assert details.additional_kwargs == []


@pytest.mark.parametrize(
    ("source", "connector_cls"),
    [
        (DocumentSource.EGNYTE, EgnyteConnector),
        (DocumentSource.LINEAR, LinearConnector),
    ],
)
def test_existing_oauth_connectors_report_manual_capability(
    monkeypatch: pytest.MonkeyPatch,
    source: DocumentSource,
    connector_cls: type[OAuthConnector],
) -> None:
    monkeypatch.setattr(
        standard_oauth,
        "_discover_oauth_connectors",
        lambda: {source: connector_cls},
    )

    details = standard_oauth.oauth_details(source=source, _=cast(User, object()))

    assert details.supports_manual_credentials is True


def test_oauth_details_defaults_non_oauth_sources_to_manual(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(standard_oauth, "_discover_oauth_connectors", lambda: {})

    details = standard_oauth.oauth_details(
        source=DocumentSource.SALESFORCE, _=cast(User, object())
    )

    assert details.oauth_enabled is False
    assert details.supports_manual_credentials is True


def _configure_disabled_connector(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        standard_oauth,
        "_discover_oauth_connectors",
        lambda: {DocumentSource.LINEAR: DisabledOAuthConnector},
    )


def test_disabled_oauth_connector_rejects_authorize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_disabled_connector(monkeypatch)

    with pytest.raises(OnyxError, match="OAuth is not configured"):
        standard_oauth.oauth_authorize(
            request=_request(),
            source=DocumentSource.LINEAR,
            desired_return_url="https://onyx.example/return",
            _=cast(User, object()),
        )


def test_disabled_oauth_connector_rejects_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_disabled_connector(monkeypatch)

    with pytest.raises(OnyxError, match="OAuth is not configured"):
        standard_oauth.oauth_callback(
            source=DocumentSource.LINEAR,
            code="authorization-code",
            state="state-id",
            db_session=cast(Session, object()),
            user=cast(User, object()),
        )
