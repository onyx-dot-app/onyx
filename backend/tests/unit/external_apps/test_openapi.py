"""Credential boundaries for OpenAPI-derived Craft gateways."""

import re
from typing import Any

import pytest

from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.credentials import build_auth_headers
from onyx.external_apps.openapi import openapi_auth_configuration, openapi_url_patterns
from onyx.external_apps.url_glob import UrlGlob


def _schema(base: str) -> dict[str, Any]:
    return {
        "servers": [{"url": base}],
        "paths": {"/items": {"get": {"operationId": "items", "summary": "List items"}}},
    }


@pytest.mark.parametrize(
    "base",
    [
        "https://api.example.com",
        "https://api.example.com/",
        "https://API.example.com:443/",
    ],
)
def test_origin_servers_match_requests_without_widening_host(base: str) -> None:
    patterns = openapi_url_patterns(_schema(base))
    regexes = [UrlGlob.parse(pattern).to_regex() for pattern in patterns]
    assert any(
        re.fullmatch(regex, "https://api.example.com/?page=1") for regex in regexes
    )
    assert any(
        re.fullmatch(regex, "https://api.example.com/items/1") for regex in regexes
    )
    assert not any(
        re.fullmatch(regex, "https://api.example.com.evil.test/items")
        for regex in regexes
    )


def test_base_path_keeps_segment_boundary_and_includes_query() -> None:
    patterns = openapi_url_patterns(_schema("https://api.example.com/v1/"))
    regexes = [UrlGlob.parse(pattern).to_regex() for pattern in patterns]
    for url in [
        "https://api.example.com/v1",
        "https://api.example.com/v1?limit=1",
        "https://api.example.com/v1/items",
    ]:
        assert any(re.fullmatch(regex, url) for regex in regexes)
    assert not any(
        re.fullmatch(regex, "https://api.example.com/v10/items") for regex in regexes
    )


@pytest.mark.parametrize(
    "url",
    [
        "/api",
        "https://{tenant}.example.com",
        "https://*.example.com",
        "https://user:secret@example.com/api",
        "https://example.com/api?token=x",
        "https://example.com/api#fragment",
        "https://example.com:bad/api",
        "https://example.com/api\n",
        "https://example.com/v1/../outside",
        "https://example.com/v1/%2e%2e/outside",
        "https://example.com/v1/%5c..%5coutside",
    ],
)
def test_unsafe_or_unresolved_servers_rejected(url: str) -> None:
    with pytest.raises(OnyxError):
        openapi_url_patterns(_schema(url))


def test_operation_server_overrides_do_not_expand_credential_scope() -> None:
    schema = _schema("https://root.example.com")
    schema["paths"]["/items"]["get"]["servers"] = [{"url": "https://other.example.com"}]
    with pytest.raises(OnyxError, match="operation-level"):
        openapi_url_patterns(schema)


def test_multiple_root_servers_follow_existing_action_validation() -> None:
    schema = _schema("https://root.example.com")
    schema["servers"].append({"url": "https://other.example.com"})
    with pytest.raises(OnyxError, match="exactly one"):
        openapi_url_patterns(schema)


def test_header_values_remain_secret_and_literal() -> None:
    template, credentials = openapi_auth_configuration(
        [
            {"key": "Authorization", "value": "Bearer {literal-secret}"},
            {"key": "X-Key", "value": "second-secret"},
        ]
    )
    assert "secret" not in str(template)
    assert build_auth_headers(template, credentials) == {
        "Authorization": "Bearer {literal-secret}",
        "X-Key": "second-secret",
    }


def test_duplicate_headers_rejected_case_insensitively() -> None:
    with pytest.raises(OnyxError):
        openapi_auth_configuration(
            [
                {"key": "Authorization", "value": "one"},
                {"key": "authorization", "value": "two"},
            ]
        )


@pytest.mark.parametrize("name", ["", "Bad Header", "X-Key:", "X-Key\r\n", "Clé"])
def test_invalid_header_names_rejected(name: str) -> None:
    with pytest.raises(OnyxError):
        openapi_auth_configuration([{"key": name, "value": "secret"}])


@pytest.mark.parametrize(
    "value", ["secret\r\nX-Extra: injected", "secret\n", "secret\r"]
)
def test_header_line_breaks_rejected(value: str) -> None:
    with pytest.raises(OnyxError):
        openapi_auth_configuration([{"key": "X-Key", "value": value}])


def test_http_token_punctuation_allowed_in_header_names() -> None:
    name = "X-!#$%&'*+.^_`|~0129"
    template, credentials = openapi_auth_configuration(
        [{"key": name, "value": "secret"}]
    )
    assert build_auth_headers(template, credentials) == {name: "secret"}


@pytest.mark.parametrize(
    "url", [123, {"url": "https://example.com"}, ["https://example.com"]]
)
def test_non_string_server_url_rejected_as_invalid_input(url: Any) -> None:
    schema = _schema("https://example.com")
    schema["servers"][0]["url"] = url
    with pytest.raises(OnyxError, match="must be strings"):
        openapi_url_patterns(schema)
