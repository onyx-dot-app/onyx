"""Unit tests for build_auth_headers — pure auth_template → headers rendering."""

from __future__ import annotations

from onyx.external_apps.credentials import build_auth_headers


def test_fills_placeholder_from_credentials() -> None:
    headers = build_auth_headers(
        {"Authorization": "Bearer {access_token}"},
        {"access_token": "xoxb-123"},
    )
    assert headers == {"Authorization": "Bearer xoxb-123"}


def test_omits_header_with_unfilled_placeholder() -> None:
    # The token isn't available -> the header is dropped, not half-rendered.
    headers = build_auth_headers(
        {"Authorization": "Bearer {access_token}", "X-Static": "always"},
        {},
    )
    assert headers == {"X-Static": "always"}


def test_static_header_needs_no_credentials() -> None:
    assert build_auth_headers({"X-Api-Version": "2025-01"}, {}) == {
        "X-Api-Version": "2025-01"
    }


def test_multiple_placeholders_all_required() -> None:
    template = {"Authorization": "{scheme} {token}"}
    assert build_auth_headers(template, {"scheme": "Bearer"}) == {}  # token missing
    assert build_auth_headers(template, {"scheme": "Bearer", "token": "t"}) == {
        "Authorization": "Bearer t"
    }


def test_credential_value_with_braces_is_not_reinterpreted() -> None:
    # A value containing braces must be substituted literally, not re-formatted.
    headers = build_auth_headers(
        {"Authorization": "Bearer {access_token}"},
        {"access_token": "ab{cd}ef"},
    )
    assert headers == {"Authorization": "Bearer ab{cd}ef"}


def test_extra_credentials_are_ignored() -> None:
    headers = build_auth_headers(
        {"Authorization": "Bearer {access_token}"},
        {"access_token": "t", "client_secret": "unused"},
    )
    assert headers == {"Authorization": "Bearer t"}


def test_non_string_template_value_skipped() -> None:
    headers = build_auth_headers(
        {"Authorization": "Bearer {t}", "Bad": 123},  # type: ignore[dict-item]
        {"t": "x"},
    )
    assert headers == {"Authorization": "Bearer x"}


def test_attribute_or_index_access_skips_only_the_bad_header() -> None:
    # `{t.x}` / `{t[x]}` raise AttributeError / TypeError during render; they
    # must skip only that header, not abort the whole render.
    headers = build_auth_headers(
        {
            "Authorization": "Bearer {t}",
            "Attr": "{t.value}",
            "Index": "{t[id]}",
        },
        {"t": "x"},
    )
    assert headers == {"Authorization": "Bearer x"}
