import pytest

from onyx.utils.url import sanitize_next_url


@pytest.mark.parametrize(
    "value",
    [
        # scheme-bearing payloads
        "javascript:alert(1)",
        "https://evil.example.com",
        "http://evil.example.com/path",
        "data:text/html,<script>alert(1)</script>",
        # protocol-relative / netloc forms
        "//evil.com",
        "//evil.com/path",
        # backslash tricks that browsers normalize to "//"
        "/\\evil.com",
        "\\\\evil.com",
        # whitespace + control-char prefixes that browsers strip then reinterpret
        "  //evil.com",
        "\t//evil.com",
        "\x01//evil.com",
        # malformed authority (urlparse raises / startswith guard catches)
        "https://[::1",
        "//[::1",
        # non-relative / empty
        "evil.com",
        "",
        "   ",
        None,
    ],
)
def test_sanitize_next_url_rejects_unsafe(value: str | None) -> None:
    assert sanitize_next_url(value) == "/"


@pytest.mark.parametrize(
    "value",
    [
        "/",
        "/chat",
        "/admin/connectors?foo=bar",
        "/path/to/page#section",
    ],
)
def test_sanitize_next_url_allows_relative_paths(value: str) -> None:
    assert sanitize_next_url(value) == value
