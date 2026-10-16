import asyncio
import json
from collections.abc import AsyncGenerator, Awaitable, Callable, Iterator
from contextlib import suppress
from typing import Literal, TypedDict

import httpx
from mcp import ClientSession
from mcp.client.auth.utils import extract_resource_metadata_from_www_auth

from onyx.db.enums import MCPTransport
from onyx.server.features.mcp.client import _call_mcp_client_function_async
from onyx.server.features.mcp.models import (
    MCPOAuthProbeResult,
    MCPPublicProbeResult,
    MCPSetupProbeResult,
    MCPUnknownAuthProbeResult,
    MCPUnreachableProbeResult,
)
from onyx.server.features.mcp.oauth_discovery import discover_oauth_capabilities
from onyx.server.features.mcp.ssrf import mcp_ssrf_httpx_client_factory
from onyx.utils.url import SSRFException


class MCPProbeProgress(TypedDict):
    type: Literal["progress"]
    stage: Literal["contacting_server", "authentication"]
    state: Literal["pending", "success", "error"]


class MCPProbeCompletion(TypedDict):
    type: Literal["result"]
    result: dict[str, object]


Progress = Callable[[MCPProbeProgress], Awaitable[None]]


async def stream_mcp_probe(server_url: str) -> AsyncGenerator[str, None]:
    queue: asyncio.Queue[MCPProbeProgress | MCPProbeCompletion] = asyncio.Queue()

    async def run() -> None:
        result = await probe_mcp_server(server_url, queue.put)
        await queue.put({"type": "result", "result": result.model_dump(mode="json")})

    task = asyncio.create_task(run())
    try:
        while True:
            event = await queue.get()
            yield json.dumps(event) + "\n"
            if event["type"] == "result":
                break
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


def _leaf_errors(error: Exception) -> Iterator[Exception]:
    if isinstance(error, ExceptionGroup):
        for child in error.exceptions:
            yield from _leaf_errors(child)
    else:
        yield error


async def probe_mcp_server(
    server_url: str, progress: Progress | None = None
) -> MCPSetupProbeResult:
    contacted = False

    async def report_contact() -> None:
        nonlocal contacted
        if not contacted:
            contacted = True
            if progress:
                await progress(
                    {
                        "type": "progress",
                        "stage": "contacting_server",
                        "state": "success",
                    }
                )
                await progress(
                    {"type": "progress", "stage": "authentication", "state": "pending"}
                )

    if progress:
        await progress(
            {"type": "progress", "stage": "contacting_server", "state": "pending"}
        )
    result: MCPSetupProbeResult = MCPUnreachableProbeResult()
    try:
        async with asyncio.timeout(25):
            for transport in (MCPTransport.STREAMABLE_HTTP, MCPTransport.SSE):
                transport_result = await _probe_transport(
                    server_url, transport, report_contact
                )
                if transport_result is not None:
                    result = transport_result
                    break
    except Exception:
        result = MCPUnreachableProbeResult()
    if progress:
        await progress(
            {
                "type": "progress",
                "stage": "authentication" if contacted else "contacting_server",
                "state": "success" if result.kind in ("public", "oauth") else "error",
            }
        )
    return result


async def _probe_transport(
    server_url: str,
    transport: Literal[MCPTransport.STREAMABLE_HTTP, MCPTransport.SSE],
    contacted: Callable[[], Awaitable[None]],
) -> MCPSetupProbeResult | None:
    challenges: list[httpx.Response] = []
    sse_established = False

    async def record_challenge(response: httpx.Response) -> None:
        # The SSE SDK logs message-POST errors instead of propagating them.
        nonlocal sse_established
        if (
            transport == MCPTransport.SSE
            and response.request.method == "GET"
            and response.is_success
            and response.headers.get("content-type", "").startswith("text/event-stream")
        ):
            sse_established = True
        if response.status_code in (401, 403):
            challenges.append(response)
            await contacted()

    def probe_client_factory(
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        auth: httpx.Auth | None = None,
    ) -> httpx.AsyncClient:
        client = mcp_ssrf_httpx_client_factory(
            headers=headers, timeout=timeout, auth=auth
        )
        client.event_hooks["response"].append(record_challenge)
        return client

    try:

        async def inspect(session: ClientSession) -> tuple[str, int]:
            initialized = await session.initialize()
            await contacted()
            tools = await session.list_tools()
            return initialized.serverInfo.name, len(tools.tools)

        async with asyncio.timeout(5):
            name, tool_count = await _call_mcp_client_function_async(
                inspect,
                server_url,
                transport=transport,
                httpx_client_factory=probe_client_factory,
            )
        await contacted()
        return MCPPublicProbeResult(
            transport=transport, server_name=name, tool_count=tool_count
        )
    except Exception as error:
        errors = list(_leaf_errors(error))
        if any(isinstance(item, SSRFException) for item in errors):
            return MCPUnreachableProbeResult(reason="blocked")
        challenge = (
            challenges[0]
            if challenges
            else next(
                (
                    item.response
                    for item in errors
                    if isinstance(item, httpx.HTTPStatusError)
                    and item.response.status_code in (401, 403)
                ),
                None,
            )
        )
        if challenge is not None:
            await contacted()
            discovery = await discover_oauth_capabilities(
                server_url,
                challenge_url=extract_resource_metadata_from_www_auth(challenge),
            )
            if discovery.status == "metadata_found":
                return MCPOAuthProbeResult(
                    discovery=discovery,
                    transport=MCPTransport.SSE if sse_established else None,
                )
            return MCPUnknownAuthProbeResult(
                transport=MCPTransport.SSE if sse_established else None
            )
    return None
