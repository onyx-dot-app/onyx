"""HTTP node: call an endpoint and hand the response downstream.

Every request goes through an SSRF-validating transport rather than a
one-time check on the configured URL. A flow author controls the URL, and
that URL can be assembled from a webhook payload at run time, so the guard has
to sit where redirects are re-entered too — the same reasoning as the MCP
client in ``onyx/server/features/mcp/ssrf.py``.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from onyx.db.enums import FlowErrorClass
from onyx.flows.expressions import (
    ExpressionError,
    RunContext,
    render_text,
    resolve_structure,
    walk_path,
)
from onyx.flows.models import HttpNode
from onyx.flows.nodes.base import NodeExecutionError, NodeOutcome, NodeRuntime
from onyx.server.security.models import outbound_ssrf_params
from onyx.server.security.store import get_security_settings
from onyx.utils.logger import setup_logger
from onyx.utils.url import SSRFException, validate_outbound_http_url

logger = setup_logger()

# A response is persisted into `flow_node_run.output` and read back by later
# nodes, so it has to stay small enough to keep a run row sane.
MAX_RESPONSE_BYTES = 1_000_000

# Response headers worth keeping. The full set is mostly noise and can carry
# `set-cookie`, which has no business being written to the run history.
KEPT_RESPONSE_HEADERS = frozenset(
    {
        "content-type",
        "content-length",
        "etag",
        "last-modified",
        "location",
        "retry-after",
        "x-request-id",
    }
)


class FlowSSRFTransport(httpx.HTTPTransport):
    """Validates every outbound URL, including each redirect hop."""

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        validate_flow_outbound_url(str(request.url))
        return super().handle_request(request)


def validate_flow_outbound_url(url: str, *, resolve_dns: bool = True) -> str:
    """Apply the tenant's SSRF policy to a URL a flow wants to fetch.

    Flow URLs are user-authored and run unattended, so they are treated like
    the other LLM-initiated paths rather than like an admin-configured
    connector.
    """
    params = outbound_ssrf_params(get_security_settings().ssrf_protection_level)
    return validate_outbound_http_url(
        url,
        allow_private_network=params.allow_private_network,
        block_loopback_and_link_local=params.block_loopback_and_link_local,
        block_link_local_only=params.block_link_local_only,
        resolve_dns=resolve_dns,
    )


def build_http_client(timeout_seconds: float = 30.0) -> httpx.Client:
    """The client a run uses for every HTTP node."""
    return httpx.Client(
        timeout=httpx.Timeout(timeout_seconds),
        follow_redirects=True,
        transport=FlowSSRFTransport(),
    )


def execute_http(
    node: HttpNode, context: RunContext, runtime: NodeRuntime
) -> NodeOutcome:
    """Resolve the request from the context, send it, shape the response."""
    try:
        url = render_text(node.url, context)
        headers = {
            render_text(name, context): render_text(value, context)
            for name, value in node.headers.items()
        }
        query = {
            render_text(name, context): render_text(value, context)
            for name, value in node.query.items()
        }
        body = resolve_structure(node.body, context) if node.body is not None else None
    except ExpressionError as exc:
        raise NodeExecutionError(FlowErrorClass.EXPRESSION_ERROR, str(exc)) from exc

    request_kwargs: dict[str, Any] = {
        "headers": headers,
        "params": query or None,
        "timeout": httpx.Timeout(node.timeout_seconds),
    }
    if body is not None:
        if isinstance(body, str):
            request_kwargs["content"] = body
        else:
            request_kwargs["json"] = body

    try:
        response = runtime.http_client.request(node.method, url, **request_kwargs)
    except SSRFException as exc:
        raise NodeExecutionError(
            FlowErrorClass.HTTP_ERROR, f"blocked by SSRF policy: {exc}"
        ) from exc
    except httpx.TimeoutException as exc:
        raise NodeExecutionError(
            FlowErrorClass.TIMEOUT,
            f"{node.method} {url} timed out after {node.timeout_seconds}s",
        ) from exc
    except httpx.HTTPError as exc:
        raise NodeExecutionError(
            FlowErrorClass.HTTP_ERROR, f"{node.method} {url} failed: {exc}"
        ) from exc

    parsed_body = _parse_body(response)
    output: dict[str, Any] = {
        "status": response.status_code,
        "headers": {
            name: value
            for name, value in response.headers.items()
            if name.lower() in KEPT_RESPONSE_HEADERS
        },
        "body": parsed_body,
    }

    if node.fail_on_error_status and response.status_code >= 400:
        raise NodeExecutionError(
            FlowErrorClass.HTTP_ERROR,
            f"{node.method} {url} returned {response.status_code}: "
            f"{_short_error_body(parsed_body)}",
        )

    if node.result_path:
        try:
            return NodeOutcome(
                output=walk_path(parsed_body, node.result_path, root_name="body")
            )
        except ExpressionError as exc:
            raise NodeExecutionError(FlowErrorClass.EXPRESSION_ERROR, str(exc)) from exc

    return NodeOutcome(output=output)


def _parse_body(response: httpx.Response) -> Any:
    """Decode a response into something JSONB can hold.

    Oversized bodies are truncated rather than raising: a node that already
    performed its side effect should not be reported as failed just because
    the reply was chatty.
    """
    raw = response.content
    if len(raw) > MAX_RESPONSE_BYTES:
        logger.warning(
            "flow http response truncated url=%s bytes=%d",
            response.request.url,
            len(raw),
        )
        return {
            "truncated": True,
            "bytes": len(raw),
            "preview": raw[:2000].decode("utf-8", errors="replace"),
        }

    if not raw:
        return None

    content_type = response.headers.get("content-type", "")
    if "json" in content_type.lower():
        try:
            return json.loads(raw)
        except ValueError:
            # Claimed JSON and was not. Text is more useful than an error.
            return raw.decode("utf-8", errors="replace")
    return raw.decode("utf-8", errors="replace")


def _short_error_body(body: Any) -> str:
    """A one-line hint for the failure message, never the whole payload."""
    if body is None:
        return "(empty body)"
    rendered = body if isinstance(body, str) else json.dumps(body, default=str)
    return rendered[:300]
