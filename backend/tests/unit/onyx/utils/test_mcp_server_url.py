import pytest

from onyx.utils.url import mcp_server_url_problem, normalize_mcp_server_url


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


@pytest.mark.parametrize(
    ("url", "problem"),
    [
        ("https://${HOST}/mcp", "variable"),
        ("ftp://mcp.example.com/mcp", "invalid"),
        ("https://mcp.example.com:99999/mcp", "invalid"),
        ("https://user:secret@mcp.example.com/mcp", "credential"),
        ("https://mcp.example.com/mcp?api_key=SECRET", "credential"),
        ("https://mcp.example.com/mcp?team=a&Token=SECRET", "credential"),
        ("https://mcp.example.com/mcp?access_token=SECRET", "credential"),
        ("https://mcp.example.com/mcp?x-api-key=SECRET", "credential"),
        ("https://mcp.example.com/mcp?key=", "credential"),
        ("https://mcp.example.com/mcp?sig=abc", "credential"),
        ("https://mcp.example.com/mcp?team=a", None),
        ("https://mcp.example.com/mcp", None),
    ],
)
def test_names_why_a_url_is_refused(url: str, problem: str | None) -> None:
    assert mcp_server_url_problem(url) == problem
    assert (normalize_mcp_server_url(url) is None) == (problem is not None)
