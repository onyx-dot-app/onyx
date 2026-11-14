"""Preview requests through the webapp proxy record sandbox activity."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from starlette.requests import Request
from starlette.responses import Response

from onyx.server.features.build import webapp_proxy


def _get_webapp(mark: MagicMock) -> tuple[Response, AsyncMock]:
    request = Request({"type": "http", "method": "GET", "headers": []})
    proxied = Response(content=b"ok")
    proxy_request = AsyncMock(return_value=proxied)
    with (
        patch.object(webapp_proxy, "_check_webapp_access", AsyncMock()),
        patch.object(webapp_proxy, "_proxy_request", proxy_request),
        patch.object(webapp_proxy, "mark_preview_activity", mark),
    ):
        response = asyncio.run(
            webapp_proxy.get_webapp(uuid4(), request, path="", user=MagicMock())
        )
    return response, proxy_request


def test_preview_request_marks_activity() -> None:
    mark = MagicMock()
    response, proxy_request = _get_webapp(mark)

    session_id = proxy_request.call_args.args[2]
    mark.assert_called_once_with(session_id)
    assert response.body == b"ok"


def test_activity_failure_does_not_fail_the_preview() -> None:
    mark = MagicMock(side_effect=RuntimeError("cache down"))
    response, proxy_request = _get_webapp(mark)

    proxy_request.assert_awaited_once()
    assert response.body == b"ok"
