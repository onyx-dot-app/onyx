"""The MCP open_urls tool enforces the API's per-request URL cap itself, so a
caller gets a clear error instead of a validation dump."""

from typing import Any

import pytest
from fastmcp.exceptions import ToolError
from fastmcp.server.auth.auth import AccessToken

import onyx.mcp_server.tools.search as search_module
from tests.unit.onyx.mcp_server.tool_result import error_payload


@pytest.mark.asyncio
async def test_open_urls_rejects_more_than_configured_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(search_module, "OPEN_URLS_MAX_URLS_PER_REQUEST", 3)

    async def _no_post(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("api server must not be called")

    monkeypatch.setattr(
        search_module,
        "require_access_token",
        lambda: AccessToken(token="test-token", client_id="test", scopes=[]),
    )
    monkeypatch.setattr(search_module, "_post_model", _no_post)

    urls = [f"https://example.com/{i}" for i in range(4)]
    with pytest.raises(ToolError) as exc:
        await search_module.open_urls(urls)
    payload = error_payload(exc.value)

    assert payload["results"] == []
    assert payload["error"].startswith("Too many URLs")
