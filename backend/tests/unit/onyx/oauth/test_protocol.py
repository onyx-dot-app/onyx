from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import TypeAdapter, ValidationError

from onyx.oauth.models import PKCECodeVerifier
from onyx.oauth.protocol import (
    build_authorization_code_token_body,
    build_authorization_url,
    validate_authorization_params,
)


@pytest.mark.parametrize(
    "key",
    [
        "client_id",
        "redirect_uri",
        "response_type",
        "state",
        "scope",
        "code_challenge",
        "code_challenge_method",
    ],
)
@pytest.mark.parametrize("in_endpoint", [True, False])
def test_protocol_fields_cannot_be_configured(key: str, in_endpoint: bool) -> None:
    endpoint = "https://provider.example/authorize"
    extras = {key: "override"}
    if in_endpoint:
        endpoint += f"?{key}=override"
        extras = {}
    with pytest.raises(ValueError, match="cannot override"):
        build_authorization_url(
            authorization_url=endpoint,
            client_id="client",
            redirect_uri="https://onyx.example/callback",
            state="state",
            additional_params=extras,
        )


def test_provider_scope_and_query_encoding() -> None:
    url = build_authorization_url(
        authorization_url="https://provider.example/authorize?audience=old#section",
        client_id="client",
        redirect_uri="https://onyx.example/callback",
        state="state",
        scope="read,write",
        scope_param="user_scope",
        additional_params={
            "optional_scope": "https://example.com/write",
            "audience": "new",
        },
        code_challenge="challenge",
    )
    query = parse_qs(urlparse(url).query)
    assert query["user_scope"] == ["read,write"]
    assert "scope" not in query
    assert query["audience"] == ["new"]
    assert query["optional_scope"] == ["https://example.com/write"]
    assert query["response_type"] == ["code"]
    assert query["code_challenge_method"] == ["S256"]
    assert "code_verifier" not in query
    assert urlparse(url).fragment == "section"


def test_custom_scope_field_cannot_be_overridden() -> None:
    with pytest.raises(ValueError, match="user_scope"):
        validate_authorization_params(
            "https://provider.example", {"user_scope": "bot"}, scope_param="user_scope"
        )


@pytest.mark.parametrize("in_endpoint", [True, False])
def test_resource_ownership_depends_on_flow(in_endpoint: bool) -> None:
    endpoint = "https://provider.example/authorize"
    extras = {"resource": "https://api.example"}
    if in_endpoint:
        endpoint += "?resource=https%3A%2F%2Fapi.example"
        extras = {}

    def build(*, owns_resource: bool = False, resource: str | None = None) -> str:
        return build_authorization_url(
            authorization_url=endpoint,
            client_id="client",
            redirect_uri="https://onyx.example",
            state="state",
            additional_params=extras,
            owns_resource=owns_resource,
            resource=resource,
        )

    assert parse_qs(urlparse(build()).query)["resource"] == ["https://api.example"]
    with pytest.raises(ValueError, match="resource"):
        build(owns_resource=True)
    with pytest.raises(ValueError, match="resource"):
        build(resource="https://another.example")


def test_token_body_supports_basic_auth_and_pkce() -> None:
    assert build_authorization_code_token_body(
        code="code", redirect_uri="callback"
    ) == {
        "grant_type": "authorization_code",
        "code": "code",
        "redirect_uri": "callback",
    }
    body = build_authorization_code_token_body(
        code="code",
        redirect_uri="callback",
        client_id="client",
        client_secret="secret",
        code_verifier="verifier",
    )
    assert body["client_id"] == "client"
    assert body["client_secret"] == "secret"
    assert body["code_verifier"] == "verifier"


def test_pkce_verifier_rejects_non_protocol_characters() -> None:
    verifier = TypeAdapter(PKCECodeVerifier)
    assert verifier.validate_python("a" * 43) == "a" * 43
    with pytest.raises(ValidationError):
        verifier.validate_python("+" * 43)


def test_repeated_endpoint_resources_are_preserved() -> None:
    url = build_authorization_url(
        authorization_url="https://accounts.google.com/authorize?resource=first&resource=second",
        client_id="client",
        redirect_uri="callback",
        state="state",
    )
    assert parse_qs(urlparse(url).query)["resource"] == ["first", "second"]
