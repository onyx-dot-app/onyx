import json
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from fastapi import Request
from pydantic import Field
from sqlalchemy.orm import Session

from onyx.auth.pkce import compute_s256_challenge, generate_pkce_pair
from onyx.configs.constants import DocumentSource
from onyx.connectors.egnyte.connector import EgnyteConnector
from onyx.connectors.interfaces import OAuthConnector
from onyx.connectors.linear.connector import LinearConnector
from onyx.db.models import User
from onyx.error_handling.exceptions import OnyxError
from onyx.server.documents import standard_oauth
from tests.unit.fakes import FakeCache


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

    class AdditionalOauthKwargs(OAuthConnector.AdditionalOauthKwargs):
        instance: str = Field(default="default", min_length=1)

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


class OtherOAuthConnector(PKCEOAuthConnector):
    supports_pkce = False

    @classmethod
    def oauth_id(cls) -> DocumentSource:
        return DocumentSource.SALESFORCE


def _request(query_string: bytes = b"") -> Request:
    return Request({"type": "http", "query_string": query_string})


def _user(user_id: str = "user-1") -> User:
    return cast(User, SimpleNamespace(id=user_id))


def _configure_cache(monkeypatch: pytest.MonkeyPatch) -> FakeCache:
    cache = FakeCache()
    monkeypatch.setattr(standard_oauth, "get_cache_backend", lambda: cache)
    return cache


def test_pkce_generator_uses_s256() -> None:
    code_verifier, code_challenge = generate_pkce_pair()

    assert compute_s256_challenge(code_verifier) == code_challenge


def test_authorize_passes_pkce_challenge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_cache(monkeypatch)
    authorization_url = MagicMock(return_value="https://provider.example/authorize")
    monkeypatch.setattr(
        standard_oauth,
        "_discover_oauth_connectors",
        lambda: {DocumentSource.LINEAR: PKCEOAuthConnector},
    )
    monkeypatch.setattr(
        standard_oauth, "generate_pkce_pair", lambda: ("verifier", "challenge")
    )
    monkeypatch.setattr(standard_oauth, "WEB_DOMAIN", "https://onyx.example")
    monkeypatch.setattr(
        PKCEOAuthConnector, "oauth_authorization_url", authorization_url
    )

    result = standard_oauth.oauth_authorize(
        request=_request(),
        source=DocumentSource.LINEAR,
        desired_return_url="/admin/connectors/linear?step=0",
        user=_user(),
    )

    assert result.redirect_url == "https://provider.example/authorize"
    assert authorization_url.call_args.args[3] == "challenge"


def test_authorize_skips_pkce_for_existing_connector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_cache(monkeypatch)
    authorization_url = MagicMock(return_value="https://linear.app/oauth/authorize")
    generate_pkce_pair_mock = MagicMock()
    monkeypatch.setattr(
        standard_oauth,
        "_discover_oauth_connectors",
        lambda: {DocumentSource.LINEAR: LinearConnector},
    )
    monkeypatch.setattr(standard_oauth, "generate_pkce_pair", generate_pkce_pair_mock)
    monkeypatch.setattr(LinearConnector, "oauth_authorization_url", authorization_url)

    standard_oauth.oauth_authorize(
        request=_request(),
        source=DocumentSource.LINEAR,
        desired_return_url="/admin/connectors/linear",
        user=_user(),
    )

    generate_pkce_pair_mock.assert_not_called()
    assert authorization_url.call_args.args[3] is None


def test_authorize_does_not_persist_attempt_when_provider_url_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = _configure_cache(monkeypatch)
    monkeypatch.setattr(
        standard_oauth,
        "_discover_oauth_connectors",
        lambda: {DocumentSource.LINEAR: LinearConnector},
    )
    monkeypatch.setattr(
        LinearConnector,
        "oauth_authorization_url",
        MagicMock(side_effect=ValueError("invalid provider configuration")),
    )

    with pytest.raises(ValueError, match="invalid provider configuration"):
        standard_oauth.oauth_authorize(
            request=_request(),
            source=DocumentSource.LINEAR,
            desired_return_url="/return",
            user=_user(),
        )

    assert cache.store == {}


def test_callback_consumes_owned_attempt_and_passes_stored_verifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_cache(monkeypatch)
    code_to_token = MagicMock(return_value={"access_token": "token"})
    authorization_url = MagicMock(return_value="https://provider.example/authorize")
    monkeypatch.setattr(
        standard_oauth,
        "_discover_oauth_connectors",
        lambda: {DocumentSource.LINEAR: PKCEOAuthConnector},
    )
    monkeypatch.setattr(
        standard_oauth, "generate_pkce_pair", lambda: ("verifier", "challenge")
    )
    monkeypatch.setattr(
        PKCEOAuthConnector, "oauth_authorization_url", authorization_url
    )
    monkeypatch.setattr(PKCEOAuthConnector, "oauth_code_to_token", code_to_token)
    monkeypatch.setattr(
        standard_oauth,
        "create_credential",
        lambda **_: SimpleNamespace(id=7),
    )

    standard_oauth.oauth_authorize(
        request=_request(b"instance=example"),
        source=DocumentSource.LINEAR,
        desired_return_url="/return?existing=1#section",
        user=_user(),
    )
    state = authorization_url.call_args.args[1]

    result = standard_oauth.oauth_callback(
        source=DocumentSource.LINEAR,
        code="authorization-code",
        state=state,
        db_session=cast(Session, object()),
        user=_user(),
    )

    assert result.redirect_url == (
        f"{standard_oauth.WEB_DOMAIN}/return?existing=1&credentialId=7#section"
    )
    code_to_token.assert_called_once_with(
        standard_oauth.WEB_DOMAIN,
        "authorization-code",
        {"instance": "example"},
        "verifier",
    )


def test_callback_is_bound_to_the_initiating_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_cache(monkeypatch)
    authorization_url = MagicMock(return_value="https://linear.app/oauth/authorize")
    code_to_token = MagicMock(return_value={"access_token": "token"})
    create_credential_mock = MagicMock(return_value=SimpleNamespace(id=7))
    monkeypatch.setattr(
        standard_oauth,
        "_discover_oauth_connectors",
        lambda: {DocumentSource.LINEAR: LinearConnector},
    )
    monkeypatch.setattr(LinearConnector, "oauth_authorization_url", authorization_url)
    monkeypatch.setattr(LinearConnector, "oauth_code_to_token", code_to_token)
    monkeypatch.setattr(standard_oauth, "create_credential", create_credential_mock)

    standard_oauth.oauth_authorize(
        request=_request(),
        source=DocumentSource.LINEAR,
        desired_return_url="/return",
        user=_user("user-1"),
    )
    state = authorization_url.call_args.args[1]

    with pytest.raises(OnyxError, match="Invalid or expired"):
        standard_oauth.oauth_callback(
            source=DocumentSource.LINEAR,
            code="authorization-code",
            state=state,
            db_session=cast(Session, object()),
            user=_user("user-2"),
        )
    code_to_token.assert_not_called()
    create_credential_mock.assert_not_called()

    result = standard_oauth.oauth_callback(
        source=DocumentSource.LINEAR,
        code="authorization-code",
        state=state,
        db_session=cast(Session, object()),
        user=_user("user-1"),
    )
    assert result.redirect_url == f"{standard_oauth.WEB_DOMAIN}/return?credentialId=7"


def test_callback_through_wrong_source_does_not_consume_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_cache(monkeypatch)
    authorization_url = MagicMock(return_value="https://linear.app/oauth/authorize")
    linear_code_to_token = MagicMock(return_value={"access_token": "token"})
    other_code_to_token = MagicMock(return_value={"access_token": "other"})
    monkeypatch.setattr(
        standard_oauth,
        "_discover_oauth_connectors",
        lambda: {
            DocumentSource.LINEAR: LinearConnector,
            DocumentSource.SALESFORCE: OtherOAuthConnector,
        },
    )
    monkeypatch.setattr(LinearConnector, "oauth_authorization_url", authorization_url)
    monkeypatch.setattr(LinearConnector, "oauth_code_to_token", linear_code_to_token)
    monkeypatch.setattr(OtherOAuthConnector, "oauth_code_to_token", other_code_to_token)
    monkeypatch.setattr(
        standard_oauth,
        "create_credential",
        lambda **_: SimpleNamespace(id=7),
    )

    standard_oauth.oauth_authorize(
        request=_request(),
        source=DocumentSource.LINEAR,
        desired_return_url="/return",
        user=_user(),
    )
    state = authorization_url.call_args.args[1]

    with pytest.raises(OnyxError, match="Invalid or expired"):
        standard_oauth.oauth_callback(
            source=DocumentSource.SALESFORCE,
            code="authorization-code",
            state=state,
            db_session=cast(Session, object()),
            user=_user(),
        )
    other_code_to_token.assert_not_called()

    result = standard_oauth.oauth_callback(
        source=DocumentSource.LINEAR,
        code="authorization-code",
        state=state,
        db_session=cast(Session, object()),
        user=_user(),
    )
    assert result.redirect_url == f"{standard_oauth.WEB_DOMAIN}/return?credentialId=7"
    linear_code_to_token.assert_called_once()


def test_callback_revalidates_stored_connector_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = _configure_cache(monkeypatch)
    authorization_url = MagicMock(return_value="https://provider.example/authorize")
    code_to_token = MagicMock(return_value={"access_token": "token"})
    monkeypatch.setattr(
        standard_oauth,
        "_discover_oauth_connectors",
        lambda: {DocumentSource.LINEAR: PKCEOAuthConnector},
    )
    monkeypatch.setattr(
        standard_oauth, "generate_pkce_pair", lambda: ("verifier", "challenge")
    )
    monkeypatch.setattr(
        PKCEOAuthConnector, "oauth_authorization_url", authorization_url
    )
    monkeypatch.setattr(PKCEOAuthConnector, "oauth_code_to_token", code_to_token)

    standard_oauth.oauth_authorize(
        request=_request(b"instance=example"),
        source=DocumentSource.LINEAR,
        desired_return_url="/return",
        user=_user(),
    )
    state = authorization_url.call_args.args[1]
    key = next(iter(cache.store))
    stored_attempt = json.loads(cache.store[key])
    stored_attempt["payload"]["additional_kwargs"]["instance"] = ""
    cache.store[key] = json.dumps(stored_attempt).encode()

    with pytest.raises(OnyxError, match="Invalid OAuth configuration"):
        standard_oauth.oauth_callback(
            source=DocumentSource.LINEAR,
            code="authorization-code",
            state=state,
            db_session=cast(Session, object()),
            user=_user(),
        )
    code_to_token.assert_not_called()


@pytest.mark.parametrize(
    "return_path",
    [
        "https://attacker.example/return",
        "//attacker.example/return",
        "/\\attacker.example/redirect",
        "/safe\nredirect",
    ],
)
def test_authorize_rejects_non_local_return_path(
    monkeypatch: pytest.MonkeyPatch,
    return_path: str,
) -> None:
    _configure_cache(monkeypatch)
    monkeypatch.setattr(
        standard_oauth,
        "_discover_oauth_connectors",
        lambda: {DocumentSource.LINEAR: PKCEOAuthConnector},
    )

    with pytest.raises(OnyxError, match="OAuth return"):
        standard_oauth.oauth_authorize(
            request=_request(),
            source=DocumentSource.LINEAR,
            desired_return_url=return_path,
            user=_user(),
        )


def test_callback_normalizes_same_origin_return_and_replaces_credential_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_cache(monkeypatch)
    authorization_url = MagicMock(return_value="https://linear.app/oauth/authorize")
    monkeypatch.setattr(
        standard_oauth,
        "_discover_oauth_connectors",
        lambda: {DocumentSource.LINEAR: LinearConnector},
    )
    monkeypatch.setattr(LinearConnector, "oauth_authorization_url", authorization_url)
    monkeypatch.setattr(
        LinearConnector,
        "oauth_code_to_token",
        MagicMock(return_value={"access_token": "token"}),
    )
    monkeypatch.setattr(
        standard_oauth,
        "create_credential",
        lambda **_: SimpleNamespace(id=7),
    )
    monkeypatch.setattr(standard_oauth, "WEB_DOMAIN", "https://onyx.example")

    standard_oauth.oauth_authorize(
        request=_request(),
        source=DocumentSource.LINEAR,
        desired_return_url=(
            "https://onyx.example/return?step=0&credentialId=999#setup"
        ),
        user=_user(),
    )
    state = authorization_url.call_args.args[1]

    result = standard_oauth.oauth_callback(
        source=DocumentSource.LINEAR,
        code="authorization-code",
        state=state,
        db_session=cast(Session, object()),
        user=_user(),
    )
    assert result.redirect_url == (
        "https://onyx.example/return?step=0&credentialId=7#setup"
    )


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
            desired_return_url="/return",
            user=_user(),
        )


def test_disabled_oauth_connector_rejects_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_disabled_connector(monkeypatch)

    with pytest.raises(OnyxError, match="OAuth is not configured"):
        standard_oauth.oauth_callback(
            source=DocumentSource.LINEAR,
            code="authorization-code",
            state="a" * 43,
            db_session=cast(Session, object()),
            user=_user(),
        )
