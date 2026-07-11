"""Unit tests for the web connector's URL rewrite helpers (pure functions)."""

from onyx.connectors.web.connector import _parse_url_rewrites
from onyx.connectors.web.connector import _rewrite_url
from onyx.connectors.web.connector import WebConnector


def test_parse_url_rewrites_pairs() -> None:
    """The admin form submits [source, target] pairs."""
    parsed = _parse_url_rewrites(
        [
            ["https://mirror.internal", "https://docs.example.com"],
            ["http://a", "http://b"],
        ]
    )
    assert parsed == {
        "https://mirror.internal": "https://docs.example.com",
        "http://a": "http://b",
    }


def test_parse_url_rewrites_arrow_strings() -> None:
    """Hand-written API configs may use "source -> target" strings."""
    parsed = _parse_url_rewrites(
        [
            "https://mirror.internal -> https://docs.example.com",
            "http://a -> http://b",
        ]
    )
    assert parsed == {
        "https://mirror.internal": "https://docs.example.com",
        "http://a": "http://b",
    }


def test_parse_url_rewrites_skips_invalid_entries() -> None:
    parsed = _parse_url_rewrites(
        [
            "no-arrow-here",  # no separator
            " -> https://target.only",  # empty source
            "https://source.only -> ",  # empty target
            ["https://one.element"],  # not a pair
            ["", "https://empty.source"],  # empty pair source
            ["https://ok", "https://fine"],
        ]
    )
    assert parsed == {"https://ok": "https://fine"}


def test_rewrite_url_first_matching_prefix_wins() -> None:
    rewrites = {
        "https://mirror.internal/docs": "https://docs.example.com",
        "https://mirror.internal": "https://www.example.com",
    }
    assert (
        _rewrite_url("https://mirror.internal/docs/page", rewrites)
        == "https://docs.example.com/page"
    )
    assert (
        _rewrite_url("https://mirror.internal/blog", rewrites)
        == "https://www.example.com/blog"
    )


def test_rewrite_url_replaces_prefix_only_once() -> None:
    rewrites = {"https://a": "https://b"}
    # Only the leading prefix is replaced, not later occurrences in the path.
    assert (
        _rewrite_url("https://a/redirect?to=https://a", rewrites)
        == "https://b/redirect?to=https://a"
    )


def test_rewrite_url_no_match_returns_unchanged() -> None:
    assert _rewrite_url("https://other.example.com/x", {"https://a": "https://b"}) == (
        "https://other.example.com/x"
    )


def test_web_connector_parses_url_rewrites() -> None:
    connector = WebConnector(
        base_url="https://mirror.internal/docs",
        web_connector_type="single",
        url_rewrites=[["https://mirror.internal", "https://docs.example.com"]],
    )
    assert connector.url_rewrites == {
        "https://mirror.internal": "https://docs.example.com"
    }


def test_web_connector_defaults_to_no_rewrites() -> None:
    connector = WebConnector(
        base_url="https://docs.example.com",
        web_connector_type="single",
    )
    assert connector.url_rewrites == {}
