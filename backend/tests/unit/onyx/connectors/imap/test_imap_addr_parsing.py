import pytest

from onyx.connectors.imap.connector import _parse_addrs
from onyx.connectors.imap.connector import _parse_singular_addr


def test_parse_singular_addr_quoted_comma_in_display_name() -> None:
    name, addr = _parse_singular_addr(
        '"Shop-News, Deutsche Post" <service-shop@deutschepost.de>'
    )
    assert name == "Shop-News, Deutsche Post"
    assert addr == "service-shop@deutschepost.de"


def test_parse_addrs_multiple_recipients() -> None:
    addrs = _parse_addrs('a@example.com, "B, C" <b@example.com>')
    assert addrs == [("", "a@example.com"), ("B, C", "b@example.com")]


def test_parse_singular_addr_multiple_raises() -> None:
    with pytest.raises(RuntimeError, match="singular"):
        _parse_singular_addr("a@example.com, b@example.com")


def test_parse_addrs_drops_fragments_without_at() -> None:
    # Unquoted 'Lastname, Firstname' display name; the bare fragment is
    # a display-name remnant, not an address.
    assert _parse_addrs("Restle, Rüdiger <ruediger.restle@example.com>") == [
        ("Rüdiger", "ruediger.restle@example.com")
    ]


def test_parse_addrs_angle_addr_fallback_for_comments_and_brackets() -> None:
    # getaddresses yields nothing on 'name (comment) [TAG] <a@b.c>'.
    assert _parse_addrs(
        "FabLab München Recommended Updates (Confluence) [NOREPLY] "
        "<wiki@example.com>"
    ) == [
        (
            "FabLab München Recommended Updates (Confluence) [NOREPLY]",
            "wiki@example.com",
        )
    ]
