"""Classify an intercepted HTTPS request into a gated action.

The gate addon treats both a `None` return and any matcher exception as
"not gated" — the real security boundary is the proxy's iptables egress
lockdown, not this heuristic.
"""

import json
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from typing import Any, Protocol
from urllib.parse import parse_qs
from uuid import UUID

from mitmproxy import http
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.enums import EndpointPolicy, GatedAppKind
from onyx.db.external_app import get_external_apps
from onyx.db.gated_app import get_action_policies
from onyx.db.mcp import get_craft_enabled_mcp_servers
from onyx.db.models import ExternalApp, MCPServer
from onyx.db.users import fetch_user_by_id
from onyx.external_apps.credentials import app_is_available
from onyx.external_apps.matching.engine import (
    AllMatchedActions,
    GatedTarget,
    MatchedAction,
    apply_credential_gate,
    recognize_actions,
)
from onyx.external_apps.matching.request import ProxiedRequest
from onyx.sandbox_proxy.mcp_jsonrpc import (
    McpRpcClassification,
    McpRpcKind,
    classify_mcp_request,
)
from onyx.sandbox_proxy.resolvers.mcp_matching import (
    AmbiguousMCPTargetError,
    match_request,
    parse_target,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

# action_type for an unclassifiable request to a matched MCP host (fail closed).
MCP_UNCLASSIFIABLE_ACTION_TYPE = "mcp.unclassifiable"

# MCP tools default to ASK; a server's self-declared `readOnlyHint` never
# auto-grants. Only an admin override relaxes a tool.
MCP_TOOL_DEFAULT_POLICY = EndpointPolicy.ASK


class RequestEvaluator(Protocol):
    def evaluate(
        self, request: http.Request, tenant_id: str, user_id: UUID
    ) -> AllMatchedActions | None: ...


class CompositeRequestEvaluator(RequestEvaluator):
    """Runs sub-evaluators in order; first non-``None`` verdict wins.

    External apps are tried before MCP: on a host that is both a connected
    external app and a craft MCP server, the external-app attribution governs,
    mirroring the credential resolvers' claim order.
    """

    def __init__(self, evaluators: Sequence[RequestEvaluator]) -> None:
        self._evaluators = list(evaluators)

    def evaluate(
        self, request: http.Request, tenant_id: str, user_id: UUID
    ) -> AllMatchedActions | None:
        for evaluator in self._evaluators:
            matched = evaluator.evaluate(request, tenant_id, user_id)
            if matched is not None:
                return matched
        return None


def resolve_app_for_url(
    url: str,
    apps: Iterable[ExternalApp],
) -> ExternalApp | None:
    """Return the first ``app`` whose any ``upstream_url_patterns`` entry matches
    ``url``, or ``None`` if no connected app claims it.

    ``apps`` is expected id-ordered (as ``get_external_apps`` returns it), so the
    lowest-id app wins when patterns overlap. A malformed built-in regex is
    skipped rather than failing resolution for every other app.
    """
    for app in apps:
        for regex in app.upstream_url_regexes:
            try:
                if re.fullmatch(regex, url):
                    return app
            except re.error:
                logger.warning(
                    "skipping malformed upstream_url_pattern app_id=%s pattern=%r",
                    app.id,
                    regex,
                )
    return None


class ExternalAppRequestEvaluator(RequestEvaluator):
    """Matches a request against the tenant's connected external apps.

    Opens its own short tenant-scoped DB session (mirrors ``IdentityResolver``):
    load the tenant's apps, resolve the one owning the request URL, recognise the
    catalog action(s) via ``recognize_actions``, then apply the credential gate via
    ``apply_credential_gate`` to produce the verdict.
    """

    def evaluate(
        self, request: http.Request, tenant_id: str, user_id: UUID
    ) -> AllMatchedActions | None:
        with get_session_with_tenant(tenant_id=tenant_id) as db:
            apps = get_external_apps(db, enabled_only=True)
            app = resolve_app_for_url(request.url, apps)
            if app is None:
                return None

            # Catalog path matchers test the URL path only; mitmproxy's
            # `request.path` carries the query string, so drop it.
            proxied = ProxiedRequest(
                method=request.method or "",
                path=(request.path or "").split("?", 1)[0],
                body=request.raw_content,
            )
            matched_actions = apply_credential_gate(
                app,
                proxied,
                recognize_actions(db, app, proxied),
                is_available=app_is_available(db, app, user_id),
            )
            if matched_actions is None:
                return None

        return matched_actions.model_copy(update={"payload": _request_payload(request)})


class McpRequestEvaluator(RequestEvaluator):
    """Gates craft-enabled MCP servers: proxy-authoritative per-tool approvals.

    Attributes a request to a craft MCP server by the same host + path-prefix
    rule the credential resolver uses, scoped to the servers the sandbox user may
    access, then parses the JSON-RPC body:

    * protocol plumbing (handshake, discovery, resources) → ``None`` (off-catalog;
      the resolver injects credentials and the request forwards ungated);
    * ``tools/call`` → an ``AllMatchedActions`` over the invoked tool(s), each
      carrying its effective per-tool policy (admin override else default ASK);
    * unclassifiable body on a matched host → a single ``DENY`` action so the
      gate fails closed instead of forwarding with injected credentials.

    A request outside every server's ``server_url`` prefix isn't attributed here
    (returns ``None``); the resolver still fails it closed at injection time.
    """

    def evaluate(
        self,
        request: http.Request,
        tenant_id: str,
        user_id: UUID,
    ) -> AllMatchedActions | None:
        with get_session_with_tenant(tenant_id=tenant_id) as db:
            # Access-scoped candidates, so duplicate URLs split across groups
            # attribute to the one the user can reach rather than colliding.
            user = fetch_user_by_id(db, user_id)
            # Missing user → no servers; ``None`` would skip the filter, so guard.
            servers = (
                get_craft_enabled_mcp_servers(db, user) if user is not None else []
            )
            servers_by_id = {s.id: s for s in servers}
            targets = tuple(
                t
                for t in (
                    parse_target(s.id, s.server_url) for s in servers_by_id.values()
                )
                if t is not None
            )
            try:
                target = match_request(targets, request)
            except AmbiguousMCPTargetError:
                # No single target to gate against; the resolver fails any
                # non-plumbing request closed at injection.
                return None
            if target is None:
                return None
            server = servers_by_id[target.server_id]
            gated_target = GatedTarget(
                kind=GatedAppKind.MCP_SERVER, id=server.id, app_name=server.name
            )

            # Once attributed to an MCP host, a failure must fail closed: the
            # gate turns evaluator exceptions into "off-catalog", and the MCP
            # resolver claims by host — the request would forward with injected
            # credentials, ungated.
            try:
                classification = classify_mcp_request(
                    request.method or "", request.raw_content
                )
                if classification.kind is McpRpcKind.PLUMBING:
                    return None
                actions = _mcp_tool_actions(classification, server, request, db)
            except Exception:
                logger.exception(
                    "mcp_evaluator_error tenant=%s server=%s host=%s; denying",
                    tenant_id,
                    server.id,
                    request.host,
                )
                actions = (
                    MatchedAction(
                        action_type=MCP_UNCLASSIFIABLE_ACTION_TYPE,
                        display_name="Unrecognized MCP request",
                        description="MCP gating failed; blocked.",
                        policy=EndpointPolicy.DENY,
                    ),
                )

        return AllMatchedActions(
            actions=actions, target=gated_target, payload=_request_payload(request)
        )


def _mcp_tool_actions(
    classification: McpRpcClassification,
    server: MCPServer,
    request: http.Request,
    db: Session,
) -> tuple[MatchedAction, ...]:
    """One MatchedAction per invoked tool; a single DENY when unclassifiable."""
    if classification.kind is McpRpcKind.UNCLASSIFIABLE:
        path = (request.path or "").split("?", 1)[0]
        return (
            MatchedAction(
                action_type=MCP_UNCLASSIFIABLE_ACTION_TYPE,
                display_name="Unrecognized MCP request",
                description=(
                    f"{request.method} {path} could not be parsed "
                    "as an MCP tool call or protocol message; blocked."
                ),
                policy=EndpointPolicy.DENY,
            ),
        )
    stored = get_action_policies(db, GatedAppKind.MCP_SERVER, server.id)
    # One action per distinct tool (grants and policies key by tool name), with
    # the batch multiplicity surfaced so the approval card doesn't understate a
    # request that invokes the same tool several times.
    counts: Counter[str] = Counter(classification.tool_names)
    return tuple(
        MatchedAction(
            action_type=tool_name,
            display_name=tool_name,
            description=(
                f"Call the “{tool_name}” tool on {server.name}."
                + (f" This request invokes it {count} times." if count > 1 else "")
            ),
            policy=stored.get(tool_name, MCP_TOOL_DEFAULT_POLICY),
        )
        for tool_name, count in counts.items()
    )


def _request_payload(request: http.Request) -> dict[str, Any]:
    # The engine leaves `payload` empty — evaluators own raw content + type.
    decoded = _decode_body(
        request.raw_content or b"",
        (request.headers.get("content-type") or "").lower(),
    )
    return decoded or {}


def _decode_body(body: bytes, content_type: str) -> dict[str, Any] | None:
    if "application/json" in content_type:
        try:
            decoded = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if isinstance(decoded, dict):
            return decoded
        # A batched GraphQL POST (the canonical multi-action case) is a JSON
        # array at the top level. Wrap so the FE's dict-keyed payload view
        # still surfaces the queries.
        if isinstance(decoded, list):
            return {"batch": decoded}
        return None

    if "application/x-www-form-urlencoded" in content_type:
        try:
            raw = parse_qs(body.decode("utf-8"))
        except UnicodeDecodeError:
            return None
        # Collapse parse_qs's list-per-key to match the JSON shape.
        return {
            key: (values[0] if len(values) == 1 else values)
            for key, values in raw.items()
        }

    return None
