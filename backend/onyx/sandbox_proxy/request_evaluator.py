"""Classify an intercepted HTTPS request into a gated action of an integration.

A `None` result identifies unrelated traffic. MCP protocol requests retain their target.
Exceptions are failures and must never authorize credential injection.
"""

import json
from typing import Any, Protocol
from urllib.parse import parse_qs
from uuid import UUID

from mitmproxy import http
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.enums import ActionPolicy, IntegrationActionPolicyValue, IntegrationKind
from onyx.db.models import Integration
from onyx.external_apps.matching.engine import (
    AllMatchedActions,
    GatedTarget,
    MatchedAction,
)
from onyx.external_apps.matching.request import ProxiedRequest
from onyx.integrations.craft import list_runnable_integrations
from onyx.integrations.models import RequestMatch
from onyx.integrations.registry import get_kind_handler
from onyx.sandbox_proxy.models import McpProtocolRequest
from onyx.utils.logger import setup_logger

logger = setup_logger()

# A stored policy value as the policy that an approval row shows.
ACTION_POLICY_FOR_VALUE: dict[IntegrationActionPolicyValue, ActionPolicy] = {
    IntegrationActionPolicyValue.ALLOW: ActionPolicy.ALWAYS,
    IntegrationActionPolicyValue.AUTO: ActionPolicy.ASK,
    IntegrationActionPolicyValue.ASK: ActionPolicy.ASK,
    IntegrationActionPolicyValue.BLOCKED: ActionPolicy.DENY,
}


class RequestEvaluator(Protocol):
    def evaluate(
        self, request: http.Request, tenant_id: str, user_id: UUID
    ) -> AllMatchedActions | McpProtocolRequest | None: ...


def _proxied_request(request: http.Request) -> ProxiedRequest:
    return ProxiedRequest(
        method=request.method or "",
        path=request.path or "",
        body=request.raw_content,
        url=request.url,
        headers=dict(request.headers.items()),
    )


def _matches(
    integrations: list[Integration], request: ProxiedRequest, db_session: Session
) -> list[tuple[Integration, RequestMatch]]:
    matches: list[tuple[Integration, RequestMatch]] = []
    for integration in integrations:
        try:
            match = get_kind_handler(integration.kind).match_request(
                integration, request, db_session
            )
        except Exception:
            # A broken integration is not matched, so it gets no credential.
            logger.exception(
                "integration_match_error integration=%s; skipping", integration.id
            )
            continue
        if match is not None:
            matches.append((integration, match))
    return matches


def _pick(
    matches: list[tuple[Integration, RequestMatch]],
) -> tuple[Integration, RequestMatch] | None:
    """An API integration wins over an MCP server on a shared host, and the
    lowest id wins between API integrations. Between MCP servers the longest
    path prefix wins; a tie has no single owner, so nothing is picked and the
    credential resolver blocks the request."""
    api = [match for match in matches if match[0].kind is IntegrationKind.API]
    if api:
        return min(api, key=lambda match: match[0].id)
    if not matches:
        return None
    longest = max(match.path_prefix_length for _, match in matches)
    winners = [m for m in matches if m[1].path_prefix_length == longest]
    if len(winners) > 1:
        logger.warning(
            "mcp_target_ambiguous integrations=%s",
            sorted(integration.id for integration, _ in winners),
        )
        return None
    return winners[0]


class IntegrationRequestEvaluator(RequestEvaluator):
    """Matches a request against the integrations that the sandbox owner can
    use (``list_runnable_integrations``), with ``match_request`` of each
    kind. The result carries the default policy of each action; the gate
    applies the stored policies.

    * an MCP protocol message gives ``McpProtocolRequest``;
    * an MCP body that does not parse gives one blocked action;
    * a request that no integration of the user claims gives ``None``. A
      request to the host of an MCP server is then blocked by the
      credential resolver.
    """

    def evaluate(
        self,
        request: http.Request,
        tenant_id: str,
        user_id: UUID,
    ) -> AllMatchedActions | McpProtocolRequest | None:
        with get_session_with_tenant(tenant_id=tenant_id) as db:
            picked = _pick(
                _matches(
                    list_runnable_integrations(db, user_id),
                    _proxied_request(request),
                    db,
                )
            )
            if picked is None:
                return None
            integration, match = picked
            target = GatedTarget(
                integration_id=integration.id,
                kind=integration.kind,
                app_name=integration.name,
            )
        if not match.actions:
            return McpProtocolRequest(target=target)
        return AllMatchedActions(
            actions=tuple(
                MatchedAction(
                    action_type=action.action_key,
                    display_name=action.display_name,
                    description=action.description,
                    policy=ACTION_POLICY_FOR_VALUE[action.default_policy],
                )
                for action in match.actions
            ),
            target=target,
            payload=_request_payload(request),
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
