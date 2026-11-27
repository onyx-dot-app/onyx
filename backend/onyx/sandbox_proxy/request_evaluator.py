"""Classify an intercepted HTTPS request into a gated action of an integration.

A `None` result identifies unrelated traffic. MCP protocol requests retain their target.
Exceptions are failures and must never authorize credential injection.
"""

import json
from collections.abc import Collection
from typing import Any, Protocol
from urllib.parse import parse_qs
from uuid import UUID

from mitmproxy import http
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.enums import (
    ActionPolicy,
    ExternalAppType,
    IntegrationActionPolicyValue,
    IntegrationKind,
)
from onyx.db.integration import list_enabled_integrations_by_id
from onyx.db.models import Integration
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.matching.engine import (
    AllMatchedActions,
    GatedTarget,
    MatchedAction,
)
from onyx.external_apps.matching.request import ProxiedRequest
from onyx.integrations.models import RequestMatch
from onyx.integrations.policy import chat_session_integrations
from onyx.integrations.registry import get_kind_handler
from onyx.sandbox_proxy.models import McpProtocolRequest
from onyx.sandbox_proxy.resolvers.mcp_matching import IntegrationMatchTarget, may_match
from onyx.sandbox_proxy.usable_integrations import UsableIntegrations
from onyx.utils.logger import setup_logger

logger = setup_logger()

_ACTION_POLICY_FOR_VALUE: dict[IntegrationActionPolicyValue, ActionPolicy] = {
    IntegrationActionPolicyValue.ALLOW: ActionPolicy.ALWAYS,
    IntegrationActionPolicyValue.AUTO: ActionPolicy.ASK,
    IntegrationActionPolicyValue.ASK: ActionPolicy.ASK,
    IntegrationActionPolicyValue.BLOCKED: ActionPolicy.DENY,
}


class RequestEvaluator(Protocol):
    def evaluate(
        self,
        request: http.Request,
        tenant_id: str,
        user_id: UUID,
        session_tag: UUID | None = None,
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
    candidates: list[tuple[Integration, IntegrationMatchTarget]],
    request: ProxiedRequest,
    db_session: Session,
) -> list[tuple[Integration, IntegrationMatchTarget, RequestMatch]]:
    matches: list[tuple[Integration, IntegrationMatchTarget, RequestMatch]] = []
    for integration, target in candidates:
        # An error blocks the request: skipping the integration could let a
        # broader one claim it with its own credential.
        if target.load_error is not None:
            raise OnyxError(OnyxErrorCode.INVALID_INPUT, target.load_error)
        match = get_kind_handler(integration.kind).match_request(
            integration, target, request, db_session
        )
        if match is not None:
            matches.append((integration, target, match))
    return matches


def _pick(
    matches: list[tuple[Integration, IntegrationMatchTarget, RequestMatch]],
) -> tuple[Integration, IntegrationMatchTarget, RequestMatch] | None:
    """An API integration wins over an MCP server on a shared host, and the
    lowest id wins between API integrations. Between MCP servers the longest
    path prefix wins; a tie has no single owner, so nothing is picked and the
    credential resolver blocks the request."""
    api = [match for match in matches if match[0].kind is IntegrationKind.API]
    if api:
        return min(api, key=lambda match: match[0].id)
    if not matches:
        return None
    longest = max(match.path_prefix_length for _, _, match in matches)
    winners = [m for m in matches if m[2].path_prefix_length == longest]
    if len(winners) > 1:
        logger.warning(
            "mcp_target_ambiguous integrations=%s",
            sorted(integration.id for integration, _, _ in winners),
        )
        return None
    return winners[0]


class IntegrationRequestEvaluator(RequestEvaluator):
    """Matches a request against the integrations that the sandbox owner
    turned on, or for a ``session_tag`` of a chat of the owner, the
    integrations of the agent of that chat. The gate applies the stored
    policies.

    * an MCP protocol message gives ``McpProtocolRequest``;
    * an MCP body that does not parse gives one blocked action;
    * a request that no integration of the user claims gives ``None``. A
      request to the host of an MCP server is then blocked by the
      credential resolver.
    """

    def __init__(self, usable: UsableIntegrations | None = None) -> None:
        self._usable = usable or UsableIntegrations()

    def evaluate(
        self,
        request: http.Request,
        tenant_id: str,
        user_id: UUID,
        session_tag: UUID | None = None,
    ) -> AllMatchedActions | McpProtocolRequest | None:
        candidates = [
            target
            for target in self._usable.targets(tenant_id)
            if may_match(target, request)
        ]
        if not candidates:
            return None
        usable = self._usable_ids(tenant_id, user_id, session_tag)
        candidates = [c for c in candidates if c.integration_id in usable]
        if not candidates:
            return None
        with get_session_with_tenant(tenant_id=tenant_id) as db:
            integrations = {
                integration.id: integration
                for integration in list_enabled_integrations_by_id(
                    db, [c.integration_id for c in candidates]
                )
            }
            picked = _pick(
                _matches(
                    [
                        (integrations[c.integration_id], c)
                        for c in candidates
                        if c.integration_id in integrations
                    ],
                    _proxied_request(request),
                    db,
                )
            )
            if picked is None:
                return None
            integration, match_target, match = picked
            target = GatedTarget(
                integration_id=integration.id,
                kind=integration.kind,
                app_name=integration.name,
                api_app=integration.kind is IntegrationKind.API
                and match_target.endpoint is not None,
                chat_tools=match_target.app_type is not ExternalAppType.CUSTOM,
            )
        if not match.actions:
            return McpProtocolRequest(target=target)
        return AllMatchedActions(
            actions=tuple(
                MatchedAction(
                    action_type=action.action_key,
                    display_name=action.display_name,
                    description=action.description,
                    policy=_ACTION_POLICY_FOR_VALUE[action.default_policy],
                )
                for action in match.actions
            ),
            target=target,
            payload=_request_payload(request),
        )

    def _usable_ids(
        self, tenant_id: str, user_id: UUID, session_tag: UUID | None
    ) -> Collection[int]:
        """A custom agent or a task uses its linked integrations, turned on
        or not, so a chat reads the integrations of its agent."""
        if session_tag is not None:
            with get_session_with_tenant(tenant_id=tenant_id) as db:
                held = chat_session_integrations(db, user_id, session_tag)
            if held is not None:
                return held.keys()
        return self._usable.get(tenant_id, user_id).on


def _request_payload(request: http.Request) -> dict[str, Any]:
    # The engine leaves `payload` empty — evaluators own raw content + type.
    decoded = _decode_body(
        request.raw_content or b"",
        (request.headers.get("content-type") or "").lower(),
    )
    return decoded or {}


def _decode_body(body: bytes, content_type: str) -> dict[str, Any] | None:
    media_type = content_type.split(";", 1)[0].strip()
    if media_type == "application/json" or media_type.endswith("+json"):
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
            # The card shows an empty field: it can clear a value.
            raw = parse_qs(body.decode("utf-8"), keep_blank_values=True)
        except UnicodeDecodeError:
            return None
        # Collapse parse_qs's list-per-key to match the JSON shape.
        return {
            key: (values[0] if len(values) == 1 else values)
            for key, values in raw.items()
        }

    return None
