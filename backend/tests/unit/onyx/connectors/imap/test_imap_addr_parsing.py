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


def test_parse_singular_addr_multiple_takes_first() -> None:
    assert _parse_singular_addr("a@example.com, b@example.com") == (
        "",
        "a@example.com",
    )


def test_parse_singular_addr_garbage_header_returns_display_name() -> None:
    assert _parse_singular_addr('"') == ('"', "")


def test_parse_singular_addr_bare_display_name_without_address() -> None:
    assert _parse_singular_addr(
        "FabLab München Recommended Updates (Confluence) [NOREPLY]"
    ) == ("FabLab München Recommended Updates (Confluence) [NOREPLY]", "")
