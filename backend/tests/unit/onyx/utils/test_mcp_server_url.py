import pytest

from onyx.utils.url import normalize_mcp_server_url


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("HTTPS://MCP.Example.COM/mcp", "https://mcp.example.com/mcp"),
        ("https://mcp.example.com:443/mcp", "https://mcp.example.com/mcp"),
        ("http://mcp.example.com:80/mcp", "http://mcp.example.com/mcp"),
        ("https://mcp.example.com/mcp/", "https://mcp.example.com/mcp"),
        ("https://mcp.example.com/", "https://mcp.example.com"),
        ("https://mcp.example.com/mcp?Team=A", "https://mcp.example.com/mcp?Team=A"),
        ("https://mcp.example.com:8443/mcp", "https://mcp.example.com:8443/mcp"),
        ("http://mcp.example.com:443/mcp", "http://mcp.example.com:443/mcp"),
        ("https://mcp.example.com/MCP", "https://mcp.example.com/MCP"),
        ("https://[::1]:443/mcp", "https://[::1]/mcp"),
    ],
)
def test_normalizes_like_claude_code(url: str, expected: str) -> None:
    assert normalize_mcp_server_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://${HOST}/mcp",
        "ftp://mcp.example.com/mcp",
        "mcp.example.com/mcp",
        "https:///mcp",
        "https://mcp.example.com:99999/mcp",
        "https://user:secret@mcp.example.com/mcp",
        "https://[::1/mcp",
    ],
)
def test_refuses_what_cannot_match(url: str) -> None:
    assert normalize_mcp_server_url(url) is None
