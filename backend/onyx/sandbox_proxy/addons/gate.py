"""Gate addon: enforces approval policy on identified sandbox egress.

Managed actions require a verified session and current permission settings.
Recognition failures block forwarding; unrelated traffic remains ungated.
"""

import asyncio
import base64
import binascii
from collections.abc import Callable
from typing import Any
from uuid import UUID

from mitmproxy import connection, http
from mitmproxy.proxy import server_hooks
from sqlalchemy.orm import Session

from onyx.cache.interface import CACHE_TRANSIENT_ERRORS, CacheBackend
from onyx.configs.constants import NotificationType
from onyx.db import action_approval
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.enums import (
    ActionPolicy,
    ApprovalDecidedVia,
    ApprovalDecision,
    IntegrationKind,
)
from onyx.db.integration import get_integration_by_id
from onyx.db.notification import create_notification
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.matching.engine import (
    AllMatchedActions,
    GatedTarget,
    actions_requiring_approval,
)
from onyx.integrations.actions import integration_actions
from onyx.integrations.craft import resolve_craft_action_policies
from onyx.integrations.models import EffectivePolicy
from onyx.integrations.policy import always_asks, resolve_chat_action_policies
from onyx.sandbox_proxy import approval_cache
from onyx.sandbox_proxy.credential_injection import CredentialInjectionDispatcher
from onyx.sandbox_proxy.destination_policy import (
    clear_destination,
    is_node_only_api_path,
    pin_destination,
    resolve_destination,
)
from onyx.sandbox_proxy.errors import SandboxProxyError, http_403
from onyx.sandbox_proxy.logging_utils import (
    APPROVAL_DECIDED_FIELDS,
    EGRESS_APPROVAL_MATCHED_FIELDS,
    EGRESS_SESSION_MATCHED_FIELDS,
    EGRESS_TARGET_FIELDS,
    approval_decided_args,
    credential_outcome_label,
    egress_approval_matched_args,
    egress_session_matched_args,
    egress_target_args,
    full_log_id,
    sandbox_log_label,
    short_log_id,
)
from onyx.sandbox_proxy.mcp_jsonrpc import MCP_UNCLASSIFIABLE_ACTION_TYPE
from onyx.sandbox_proxy.models import (
    DestinationPolicyConfig,
    InjectionContext,
    InjectionOutcome,
    McpProtocolRequest,
)
from onyx.sandbox_proxy.request_evaluator import RequestEvaluator
from onyx.sandbox_proxy.resolvers.integration import IntegrationResolver
from onyx.sandbox_proxy.sandbox_identity.models import ResolvedSandbox, SessionContext
from onyx.sandbox_proxy.sandbox_identity.resolution import (
    SandboxIdentityResolver,
    source_ip,
)
from onyx.sandbox_proxy.sandbox_identity.signed import (
    SESSION_HINT_HEADER,
    SignedIdentityError,
    SignedIdentityVerifier,
    parse_signed_identity_header,
)
from onyx.server.features.build.configs import (
    MCP_SESSION_TAG_HEADER,
    SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS,
)
from onyx.tools.tool_name import app_action_tool_name, custom_tool_name
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Bodies over this cap are fail-closed (rejected), not parsed by the matcher.
# 32 MiB = Anthropic's Messages API request-body limit, so the proxy is never
# the false blocker: anything the upstream would accept passes through, and a
# genuinely oversized request gets the upstream's own 413, not an opaque 403.
PARSER_MAX_BODY_BYTES = 32 * 1024 * 1024


CacheFactory = Callable[[str], CacheBackend]


_GATE_POLICY: dict[EffectivePolicy, ActionPolicy] = {
    EffectivePolicy.ALLOW: ActionPolicy.ALWAYS,
    EffectivePolicy.ASK: ActionPolicy.ASK,
    EffectivePolicy.BLOCKED: ActionPolicy.DENY,
}


def resolve_gate_policies(
    db_session: Session,
    *,
    recognized_actions: AllMatchedActions,
    user_id: UUID,
    chat_session_id: UUID | None = None,
) -> dict[str, ActionPolicy]:
    """The stored policy of each recognized action, as the gate applies it.
    With ``chat_session_id``, the policies are those of the agent of the
    chat, with no chat grant and no run mode: an Ask stays Ask."""
    integration = get_integration_by_id(
        recognized_actions.target.integration_id, db_session
    )
    if integration is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Integration no longer exists")
    action_keys = {action.action_type for action in recognized_actions.actions}
    if chat_session_id is not None:
        resolved = resolve_chat_action_policies(
            db_session,
            integration=integration,
            action_keys=action_keys,
            user_id=user_id,
            chat_session_id=chat_session_id,
        )
    else:
        resolved = resolve_craft_action_policies(
            db_session,
            integration=integration,
            actions=integration_actions(integration.id, db_session),
            action_keys=action_keys,
            user_id=user_id,
        )
    return {key: _GATE_POLICY[policy] for key, policy in resolved.items()}


# Relative deep link routed through the Next router by NotificationsPopover.tsx;
# must mirror the frontend's CRAFT_PATH + sessionId search param.
_CRAFT_SESSION_LINK_TEMPLATE = "/craft/v1?sessionId={session_id}"


class ParkedApprovals:
    """Approvals the proxy is currently parked on, grouped by tenant.

    Mutated only from the event loop; the drain reads via `snapshot()` to
    iterate safely while the source mutates.
    """

    def __init__(self) -> None:
        self._by_tenant: dict[str, set[UUID]] = {}

    def add(self, tenant_id: str, approval_id: UUID) -> None:
        self._by_tenant.setdefault(tenant_id, set()).add(approval_id)

    def remove(self, tenant_id: str, approval_id: UUID) -> None:
        parked = self._by_tenant.get(tenant_id)
        if parked is None:
            return
        parked.discard(approval_id)
        if not parked:
            del self._by_tenant[tenant_id]

    def snapshot(self) -> list[tuple[str, set[UUID]]]:
        """One-shot copy safe to iterate while the source mutates."""
        return [(tenant_id, ids.copy()) for tenant_id, ids in self._by_tenant.items()]


class GateAddon:
    """mitmproxy addon that gates external-app requests on user approval."""

    def __init__(
        self,
        identity: SandboxIdentityResolver,
        request_evaluator: RequestEvaluator,
        cache_factory: CacheFactory,
        proxy_instance_id: str,
        credential_dispatcher: CredentialInjectionDispatcher,
        destination_policy: DestinationPolicyConfig,
        stream_responses: bool = True,
        integration_resolver: IntegrationResolver | None = None,
        signed_identity: SignedIdentityVerifier | None = None,
    ) -> None:
        self._signed_identity = signed_identity
        # client connection id -> identity verified from the relay's signed
        # header on the connection's first request (CONNECT or plain HTTP).
        self._conn_signed_sandboxes: dict[str, ResolvedSandbox] = {}
        # Signed connection id -> id of the plain-HTTP flow that bound it. The
        # relay forces `Connection: close`, so any other plain flow is rejected.
        self._conn_signed_plain_flow: dict[str, str] = {}
        # Connections whose first request carried no signed header; they keep
        # the IP identity and can never switch to a signed one.
        self._conn_unsigned: set[str] = set()
        self._destination_policy = destination_policy
        self._integration_resolver = integration_resolver
        self._identity = identity
        self._request_evaluator = request_evaluator
        self._cache_factory = cache_factory
        self._proxy_instance_id = proxy_instance_id
        self._credential_dispatcher = credential_dispatcher
        self._stream_responses = stream_responses
        # Invariant: `_persist_approval_row` is the only writer;
        # `_await_decision`'s finally and the post-persist grant recheck are the
        # only removers.
        self._parked = ParkedApprovals()
        # client connection id -> session tag, captured from the CONNECT's
        # Proxy-Authorization (only place it's visible for MITM'd HTTPS).
        self._conn_session_tags: dict[str, str] = {}
        # Eager CONNECT opens TCP before mitmproxy marks the server as TLS.
        self._conn_connect_origins: dict[str, tuple[str, int]] = {}
        # Pool selection follows request(); include pending and open upstream addresses.
        self._upstream_addresses: dict[
            str, dict[connection.Server, tuple[str, ...]]
        ] = {}
        # Tracks running `request()` coroutines so the drain can `asyncio.wait`
        # on real completion instead of sleeping. Self-cleaning.
        self._inflight_tasks: set[asyncio.Task[None]] = set()

    # ------------------------------------------------------------------
    # mitmproxy hooks
    # ------------------------------------------------------------------

    async def http_connect(self, flow: http.HTTPFlow) -> None:
        """Identify the peer and capture the CONNECT's per-session tag.

        For MITM'd HTTPS the header rides on the CONNECT, not the decrypted
        inner request, so this is the only place it's visible. Keyed by client
        connection id (one tunnel per subprocess = one session); evicted in
        `client_disconnected`. Best-effort.
        """
        # Refuse to open a tunnel to an internal address, with a clear 403 the
        # agent can act on. Best-effort early deny on the CONNECT host; the decrypted
        # inner request is re-checked in `request`, and `server_connect` is the
        # authoritative rebinding-proof enforcement (resolve-once + IP pin). The check
        # can do a blocking DNS lookup, so run it off the event loop.
        if not await self._bind_signed_identity(flow):
            return
        if (
            await asyncio.to_thread(
                resolve_destination,
                self._destination_policy,
                flow.request.host,
                flow.request.port,
                scheme="https",
                peer=flow.client_conn.peername,
                identity=self._identity,
                integration_resolver=self._integration_resolver,
                sandbox=self._conn_signed_sandboxes.get(flow.client_conn.id),
            )
            is None
        ):
            logger.info(
                "egress_denied_internal_destination phase=connect host=%s port=%s",
                flow.request.host,
                flow.request.port,
            )
            flow.response = http_403(SandboxProxyError.DESTINATION_BLOCKED)
            return

        if await asyncio.to_thread(self._resolve_sandbox, flow) is None:
            return

        conn_id = getattr(flow.client_conn, "id", None)  # ods: ignore[getattr]
        auth_header = flow.request.headers.get("Proxy-Authorization")
        tag = self._session_hint(flow) or _parse_proxy_auth_username(auth_header)

        logger.debug(
            "session_tag_capture conn=%s host=%s port=%s session=%s "
            "proxy_auth_present=%s",
            conn_id or "-",
            flow.request.host,
            flow.request.port,
            short_log_id(tag),
            str(auth_header is not None).lower(),
        )
        if conn_id is None:
            return
        self._conn_connect_origins[conn_id] = (flow.request.host, flow.request.port)
        if tag:
            self._conn_session_tags[conn_id] = tag

    def client_disconnected(self, client: object) -> None:
        """Drops the connection's cached session tag to bound memory."""
        conn_id = getattr(client, "id", None)  # ods: ignore[getattr]
        if conn_id is not None:
            self._conn_session_tags.pop(conn_id, None)
            self._conn_connect_origins.pop(conn_id, None)
            self._upstream_addresses.pop(conn_id, None)
            self._conn_signed_sandboxes.pop(conn_id, None)
            self._conn_signed_plain_flow.pop(conn_id, None)
            self._conn_unsigned.discard(conn_id)

    async def server_connect(self, data: server_hooks.ServerConnectionHookData) -> None:
        """Validate the final addresses and pin them while preserving TLS SNI."""
        server = data.server
        if server.error or not server.address:
            return
        host, port = server.address[0], server.address[1]
        scheme = (
            "https"
            if server.tls
            or self._conn_connect_origins.get(data.client.id) == (host, port)
            else "http"
        )
        addresses = await asyncio.to_thread(
            resolve_destination,
            self._destination_policy,
            host,
            port,
            scheme=scheme,
            peer=data.client.peername,
            identity=self._identity,
            integration_resolver=self._integration_resolver,
            sandbox=self._conn_signed_sandboxes.get(data.client.id),
        )
        if addresses is None:
            logger.info(
                "egress_denied_internal_destination phase=server_connect host=%s port=%s",
                host,
                port,
            )
            server.error = "destination_blocked: unresolved or forbidden destination"
            return
        # TLS verifies the original hostname, even before the client sends SNI.
        if server.sni is None:
            server.sni = host
        try:
            pin_destination(host, port, addresses)
        except RuntimeError:
            server.error = "destination_blocked: upstream resolver unavailable"
            return
        self._upstream_addresses.setdefault(data.client.id, {})[server] = addresses

    def server_connected(self, data: server_hooks.ServerConnectionHookData) -> None:
        clear_destination()
        upstreams = self._upstream_addresses.get(data.client.id)
        if upstreams is not None and data.server in upstreams and data.server.peername:
            upstreams[data.server] = (data.server.peername[0],)

    def server_connect_error(self, data: server_hooks.ServerConnectionHookData) -> None:
        clear_destination()
        self.server_disconnected(data)

    def server_disconnected(self, data: server_hooks.ServerConnectionHookData) -> None:
        upstreams = self._upstream_addresses.get(data.client.id)
        if upstreams is not None:
            upstreams.pop(data.server, None)
            if not upstreams:
                self._upstream_addresses.pop(data.client.id, None)

    def responseheaders(self, flow: http.HTTPFlow) -> None:
        """
        Streams the response body to the sandbox instead of buffering it whole.

        Must run here, not in `response`: by then the body is already buffered.
        """
        if not self._stream_responses:
            return
        if flow.response is not None:
            flow.response.stream = True

    async def request(self, flow: http.HTTPFlow) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._inflight_tasks.add(task)
            task.add_done_callback(self._inflight_tasks.discard)

        if not await self._bind_signed_identity(flow):
            return
        if is_node_only_api_path(
            self._destination_policy,
            flow.request.host,
            flow.request.port,
            flow.request.path_components,
        ):
            logger.warning(
                "egress_denied_node_route method=%s host=%s port=%s",
                flow.request.method,
                flow.request.host,
                flow.request.port,
            )
            flow.response = http_403(SandboxProxyError.DESTINATION_BLOCKED)
            return
        upstream_addresses = tuple(
            address
            for server, addresses in self._upstream_addresses.get(
                flow.client_conn.id, {}
            ).items()
            if server.address == (flow.request.host, flow.request.port)
            and server.tls == (flow.request.scheme == "https")
            for address in addresses
        )
        # Deny forwards to internal addresses with a clear 403 — both plain-HTTP
        # (GET http://internal/...) and the decrypted inner request of a MITM'd
        # HTTPS tunnel, so the structured error reaches the agent regardless of
        # scheme. `server_connect` is the authoritative rebinding-proof backstop +
        # pin. Resolution can block, so run it off the event loop.
        if (
            await asyncio.to_thread(
                resolve_destination,
                self._destination_policy,
                flow.request.host,
                flow.request.port,
                scheme=flow.request.scheme,
                peer=flow.client_conn.peername,
                identity=self._identity,
                integration_resolver=self._integration_resolver,
                upstream_addresses=upstream_addresses,
                sandbox=self._conn_signed_sandboxes.get(flow.client_conn.id),
            )
            is None
        ):
            logger.info(
                "egress_denied_internal_destination phase=request host=%s port=%s",
                flow.request.host,
                flow.request.port,
            )
            flow.response = http_403(SandboxProxyError.DESTINATION_BLOCKED)
            return

        gate_target = await self._resolve_and_match(flow)
        # Strip the in-band session tags so they never reach the origin
        flow.request.headers.pop("Proxy-Authorization", None)
        if self._signed_identity is not None:
            flow.request.headers.pop(SESSION_HINT_HEADER, None)
        flow.request.headers.pop(MCP_SESSION_TAG_HEADER, None)
        if gate_target is None:
            return
        ctx, matched_actions = gate_target

        # One guarded forwarding path: addon errors must not authorize egress.
        approval_id: UUID | None = None
        try:
            if matched_actions.governing_action.policy is ActionPolicy.ASK:
                approval_id = await asyncio.to_thread(
                    self._apply_session_grant, ctx, matched_actions
                )
                if approval_id is None:
                    approval_id = self._persist_approval_row(
                        ctx,
                        matched_actions,
                        _approval_payload(flow, ctx, matched_actions),
                    )
                    # Close the race with a session grant created during persistence.
                    if (
                        await asyncio.to_thread(
                            self._apply_session_grant,
                            ctx,
                            matched_actions,
                            approval_id=approval_id,
                        )
                        is not None
                    ):
                        self._parked.remove(ctx.tenant_id, approval_id)
                        decision = ApprovalDecision.APPROVED
                    elif ctx.chat_command_id is not None and not (
                        await asyncio.to_thread(self._command_in_foreground, ctx)
                    ):
                        # The command's call ended during persistence, so no
                        # card can show this request.
                        self._parked.remove(ctx.tenant_id, approval_id)
                        decision = await asyncio.to_thread(
                            self._claim_expired_or_read_winner,
                            approval_id,
                            ctx.tenant_id,
                        )
                        if decision is not ApprovalDecision.APPROVED:
                            flow.response = _approval_needs_tool(matched_actions)
                            return
                    else:
                        decision = await self._await_decision(
                            approval_id, ctx, matched_actions
                        )
                    self._write_response_for_decision(flow, decision)
                    if decision is not ApprovalDecision.APPROVED:
                        return
                current = await asyncio.to_thread(
                    self._recheck_approval, flow, ctx, matched_actions, approval_id
                )
                if current is None:
                    return
                matched_actions = current
            current_policy = matched_actions.governing_action.policy
            # Off-thread: resolvers may refresh an expiring OAuth token before
            # rendering headers; keep that off the proxy event loop so a slow token
            # endpoint stalls only this request, not every in-flight flow.
            injection = await asyncio.to_thread(
                self._dispatch_injection_or_block,
                flow,
                sandbox=ctx.without_session(),
                matched_actions=matched_actions,
            )
            if approval_id is None:
                fields = EGRESS_SESSION_MATCHED_FIELDS
                args = egress_session_matched_args(
                    flow, ctx, matched_actions, current_policy
                )
            else:
                fields = EGRESS_APPROVAL_MATCHED_FIELDS
                args = egress_approval_matched_args(
                    flow, ctx, matched_actions, current_policy, approval_id
                )

            if injection is InjectionOutcome.BLOCKED:
                logger.warning(
                    "egress_block " + fields + " reason=%s credential_outcome=%s",
                    *args,
                    SandboxProxyError.CREDENTIAL_ERROR.value,
                    credential_outcome_label(injection),
                )
            else:
                logger.info(
                    "egress_allow " + fields + " credential_outcome=%s",
                    *args,
                    credential_outcome_label(injection),
                )
        except Exception:
            logger.exception(
                "approval_unhandled_error tenant=%s sandbox=%s session=%s "
                "approval=%s app_name=%r action_type=%s session_id=%s approval_id=%s",
                ctx.tenant_id,
                sandbox_log_label(ctx),
                short_log_id(ctx.session_id),
                short_log_id(approval_id),
                matched_actions.app_name,
                matched_actions.governing_action.action_type,
                full_log_id(ctx.session_id),
                full_log_id(approval_id),
            )
            flow.response = http_403(SandboxProxyError.INTERNAL_ERROR)
            if approval_id is not None:
                self._terminalize_after_unhandled_error(approval_id, ctx.tenant_id)

    def _recheck_approval(
        self,
        flow: http.HTTPFlow,
        ctx: SessionContext,
        matched_actions: AllMatchedActions,
        approval_id: UUID,
    ) -> AllMatchedActions | None:
        """Recheck the original execution and persisted decision before forwarding."""
        from_chat = ctx.chat_command_id is not None
        recognized = self._request_evaluator.evaluate(
            flow.request,
            ctx.tenant_id,
            ctx.user_id,
            ctx.session_id if from_chat else None,
        )
        if (
            not isinstance(recognized, AllMatchedActions)
            or recognized.target.integration_id != matched_actions.target.integration_id
            or {a.action_type for a in recognized.actions}
            != {a.action_type for a in matched_actions.actions}
        ):
            flow.response = http_403(SandboxProxyError.POLICY_DENIED)
            return None
        current_actions = self._resolve_request_policies(ctx, recognized, from_chat)
        if current_actions.governing_action.policy is ActionPolicy.DENY:
            flow.response = http_403(SandboxProxyError.POLICY_DENIED)
            return None
        with get_session_with_tenant(tenant_id=ctx.tenant_id) as db:
            approval = action_approval.get_action_approval(db, approval_id)
            owned = approval is not None and (
                (
                    approval.chat_session_id == ctx.session_id
                    and approval.command_id == ctx.chat_command_id
                )
                if from_chat
                else approval.session_id == ctx.session_id
            )
            if (
                approval is None
                or not owned
                or approval.decision is not ApprovalDecision.APPROVED
            ):
                flow.response = http_403(SandboxProxyError.NOT_AUTHORIZED)
                return None
            # A grant covers only the actions that asked when it was given.
            if (
                approval.decided_via
                in (ApprovalDecidedVia.SESSION_GRANT, ApprovalDecidedVia.COMMAND_GRANT)
                and current_actions.governing_action.policy is ActionPolicy.ASK
                and not self._session_grant(db, ctx, current_actions)
            ):
                flow.response = http_403(SandboxProxyError.NOT_AUTHORIZED)
                return None
        return current_actions

    # --------------------------------------------------------------------------
    # request() helpers
    # --------------------------------------------------------------------------

    async def _resolve_and_match(
        self, flow: http.HTTPFlow
    ) -> tuple[SessionContext, AllMatchedActions] | None:
        """Recognize actions, resolve execution identity, then apply live settings."""
        sandbox: ResolvedSandbox | None = self._resolve_sandbox(flow)
        if sandbox is None:
            return None

        # raw_content is None for streamed bodies; treat None as oversize so a
        # future stream opt-in can't silently bypass the cap.
        raw = flow.request.raw_content
        if raw is None or len(raw) > PARSER_MAX_BODY_BYTES:
            logger.info(
                "egress_block "
                + EGRESS_TARGET_FIELDS
                + " reason=%s body_bytes=%s body_limit=%s",
                *egress_target_args(flow, sandbox),
                SandboxProxyError.BODY_TOO_LARGE.value,
                "-" if raw is None else len(raw),
                PARSER_MAX_BODY_BYTES,
            )
            flow.response = http_403(SandboxProxyError.BODY_TOO_LARGE)
            return None

        tag = self._extract_session_tag(flow)
        try:
            matched_actions = await asyncio.to_thread(
                self._evaluate, flow, sandbox, tag
            )
        except Exception:
            logger.exception("request_recognition_failed tenant=%s", sandbox.tenant_id)
            flow.response = http_403(SandboxProxyError.INTERNAL_ERROR)
            return None

        if matched_actions is None:
            # Off-thread like the ALWAYS path: host-claiming resolvers may hit
            # the DB or refresh an expiring OAuth token before injecting.
            injection = await asyncio.to_thread(
                self._dispatch_injection_or_block,
                flow,
                sandbox=sandbox,
                matched_actions=None,
            )
            if injection is InjectionOutcome.BLOCKED:
                logger.warning(
                    "egress_block "
                    + EGRESS_TARGET_FIELDS
                    + " reason=%s credential_outcome=%s",
                    *egress_target_args(flow, sandbox),
                    SandboxProxyError.CREDENTIAL_ERROR.value,
                    credential_outcome_label(injection),
                )
            elif injection is not InjectionOutcome.PASS_THROUGH:
                logger.info(
                    "egress_allow "
                    + EGRESS_TARGET_FIELDS
                    + " policy=%s credential_outcome=%s",
                    *egress_target_args(flow, sandbox),
                    "off_catalog",
                    credential_outcome_label(injection),
                )
            return None

        action_label = (
            matched_actions.governing_action.action_type
            if isinstance(matched_actions, AllMatchedActions)
            else "MCP protocol"
        )
        try:
            session = await asyncio.to_thread(
                self._resolve_gated_session, flow, sandbox, tag
            )
        except Exception:
            logger.exception(
                "session_lookup_error tenant=%s sandbox=%s host=%s app_name=%r "
                "action_type=%s",
                sandbox.tenant_id,
                sandbox_log_label(sandbox),
                flow.request.host,
                matched_actions.target.app_name,
                action_label,
            )
            flow.response = http_403(SandboxProxyError.NO_ACTIVE_SESSION)
            return None
        if session is None:
            logger.info(
                "egress_block " + EGRESS_TARGET_FIELDS + " reason=%s",
                *egress_target_args(flow, sandbox),
                SandboxProxyError.NO_ACTIVE_SESSION.value,
            )
            flow.response = http_403(SandboxProxyError.NO_ACTIVE_SESSION)
            return None

        if isinstance(matched_actions, McpProtocolRequest):
            try:
                await asyncio.to_thread(
                    self._dispatch_injection_or_block,
                    flow,
                    sandbox=sandbox,
                    matched_actions=None,
                    protocol_target=matched_actions.target,
                )
            except Exception:
                logger.exception(
                    "mcp_protocol_authorization_failed tenant=%s", sandbox.tenant_id
                )
                flow.response = http_403(SandboxProxyError.INTERNAL_ERROR)
            return None

        session_id, from_chat, command_id = session
        ctx = sandbox.with_session(
            session_id, chat_command_id=command_id if from_chat else None
        )
        try:
            matched_actions = await asyncio.to_thread(
                self._resolve_request_policies, ctx, matched_actions, from_chat
            )
        except Exception:
            logger.exception("request_policy_failed tenant=%s", sandbox.tenant_id)
            flow.response = http_403(SandboxProxyError.INTERNAL_ERROR)
            return None
        if matched_actions.governing_action.policy is ActionPolicy.DENY:
            flow.response = http_403(SandboxProxyError.POLICY_DENIED)
            return None
        if (
            from_chat
            and matched_actions.governing_action.policy is ActionPolicy.ASK
            and not await asyncio.to_thread(self._command_in_foreground, ctx)
        ):
            # Only a call that waits on the command can show a card; a
            # background process has none.
            logger.info(
                "egress_block " + EGRESS_TARGET_FIELDS + " reason=%s",
                *egress_target_args(flow, sandbox),
                SandboxProxyError.APPROVAL_NEEDS_TOOL.value,
            )
            flow.response = _approval_needs_tool(matched_actions)
            return None
        logger.debug(
            "approval_match tenant=%s sandbox=%s session=%s host=%s "
            "method=%s app_name=%r action_type=%s",
            ctx.tenant_id,
            sandbox_log_label(ctx),
            short_log_id(ctx.session_id),
            flow.request.host,
            flow.request.method,
            matched_actions.app_name,
            matched_actions.governing_action.action_type,
        )
        return ctx, matched_actions

    def _evaluate(
        self, flow: http.HTTPFlow, sandbox: ResolvedSandbox, tag: str | None
    ) -> AllMatchedActions | McpProtocolRequest | None:
        try:
            session_tag = UUID(tag) if tag else None
        except ValueError:
            session_tag = None
        return self._request_evaluator.evaluate(
            flow.request, sandbox.tenant_id, sandbox.user_id, session_tag
        )

    def _resolve_request_policies(
        self,
        ctx: SessionContext,
        recognized_actions: AllMatchedActions,
        from_chat: bool = False,
    ) -> AllMatchedActions:
        """Apply the current integration policies of the user. A request
        from a chat takes the policies of the agent of that chat."""
        target = recognized_actions.target
        with get_session_with_tenant(tenant_id=ctx.tenant_id) as db:
            effective_policies = resolve_gate_policies(
                db,
                recognized_actions=recognized_actions,
                user_id=ctx.user_id,
                chat_session_id=ctx.session_id if from_chat else None,
            )
        if MCP_UNCLASSIFIABLE_ACTION_TYPE in effective_policies:
            effective_policies[MCP_UNCLASSIFIABLE_ACTION_TYPE] = ActionPolicy.DENY
        return AllMatchedActions(
            actions=tuple(
                action.model_copy(
                    update={"policy": effective_policies[action.action_type]}
                )
                for action in recognized_actions.actions
            ),
            target=target,
            payload=recognized_actions.payload,
        )

    def _command_in_foreground(self, ctx: SessionContext) -> bool:
        """A call of the chat's run waits on the command that sent the
        request, so a card can show it. False on a cache error."""
        if ctx.chat_command_id is None:
            return False
        try:
            return approval_cache.command_in_foreground(
                ctx.chat_command_id, ctx.session_id, self._cache_factory(ctx.tenant_id)
            )
        except CACHE_TRANSIENT_ERRORS as e:
            logger.warning(
                "approval_foreground_cache_error tenant=%s session=%s error=%r",
                ctx.tenant_id,
                short_log_id(ctx.session_id),
                str(e),
            )
            return False

    def _command_grant(
        self, ctx: SessionContext, matched_actions: AllMatchedActions
    ) -> bool:
        """The user approved these actions for the rest of the command."""
        command_id = ctx.chat_command_id
        action_types = approval_cache.command_grant_actions(matched_actions.actions)
        if command_id is None or not action_types:
            return False
        try:
            return approval_cache.command_grants_cover(
                command_id,
                matched_actions.target.integration_id,
                action_types,
                self._cache_factory(ctx.tenant_id),
            )
        except CACHE_TRANSIENT_ERRORS as e:
            logger.warning(
                "approval_grant_cache_error tenant=%s session=%s "
                "integration=%s operation=%s error=%r",
                ctx.tenant_id,
                short_log_id(ctx.session_id),
                matched_actions.target.integration_id,
                "command_check",
                str(e),
            )
            return False

    def _session_grant(
        self, db: Session, ctx: SessionContext, matched_actions: AllMatchedActions
    ) -> bool:
        """The user approved these identified actions for the session, or
        for the rest of the command of a chat request."""
        if ctx.chat_command_id is not None:
            return self._command_grant(ctx, matched_actions)
        if any(
            always_asks(matched_actions.target.kind, action.action_type)
            for action in matched_actions.actions
        ):
            return False
        action_types = actions_requiring_approval(matched_actions.actions)
        if not action_types:
            return False
        target = matched_actions.target
        cache: CacheBackend | None = None
        try:
            cache = self._cache_factory(ctx.tenant_id)
            if approval_cache.cached_session_grants_cover(
                session_id=ctx.session_id,
                integration_id=target.integration_id,
                action_types=action_types,
                cache=cache,
            ):
                return True
        except CACHE_TRANSIENT_ERRORS as e:
            logger.warning(
                "approval_grant_cache_error tenant=%s session=%s "
                "integration=%s operation=%s error=%r",
                ctx.tenant_id,
                short_log_id(ctx.session_id),
                target.integration_id,
                "check",
                str(e),
            )

        grant_source_rows = action_approval.list_session_grant_action_approvals(
            db,
            session_id=ctx.session_id,
            integration_id=target.integration_id,
        )
        granted_action_types = approval_cache.hydrate_session_grants(
            session_id=ctx.session_id,
            integration_id=target.integration_id,
            rows=grant_source_rows,
            cache=cache,
        )
        return set(action_types).issubset(granted_action_types)

    def _apply_session_grant(
        self,
        ctx: SessionContext,
        matched_actions: AllMatchedActions,
        *,
        approval_id: UUID | None = None,
    ) -> UUID | None:
        """Apply an existing session grant (or, for a chat request, command
        grant) in the caller's worker thread."""
        grant = (
            ApprovalDecidedVia.SESSION_GRANT
            if ctx.chat_command_id is None
            else ApprovalDecidedVia.COMMAND_GRANT
        )
        try:
            with get_session_with_tenant(tenant_id=ctx.tenant_id) as db:
                if not self._session_grant(db, ctx, matched_actions):
                    return None
                if approval_id is None:
                    row = action_approval.insert_action_approval(
                        db,
                        **_approval_owner(ctx),
                        actions=[
                            a.model_dump(mode="json") for a in matched_actions.actions
                        ],
                        app_name=matched_actions.app_name,
                        payload=matched_actions.payload,
                        integration_id=matched_actions.target.integration_id,
                        decision=ApprovalDecision.APPROVED,
                        decided_via=grant,
                    )
                    applied_approval_id = row.approval_id
                else:
                    decided = action_approval.try_record_decision(
                        db,
                        approval_id=approval_id,
                        decision=ApprovalDecision.APPROVED,
                        decided_via=grant,
                    )
                    if decided is None:
                        return None
                    applied_approval_id = approval_id
                db.commit()

            logger.info(
                "approval_decided " + APPROVAL_DECIDED_FIELDS,
                *approval_decided_args(
                    ctx,
                    applied_approval_id,
                    matched_actions,
                    decision=ApprovalDecision.APPROVED.value,
                    wake="-",
                    source=grant.value,
                ),
            )
            return applied_approval_id
        except Exception:
            logger.exception(
                "approval_grant_check_error tenant=%s sandbox=%s "
                "session=%s approval=%s app_name=%r action_type=%s session_id=%s "
                "approval_id=%s",
                ctx.tenant_id,
                sandbox_log_label(ctx),
                short_log_id(ctx.session_id),
                short_log_id(approval_id),
                matched_actions.app_name,
                matched_actions.governing_action.action_type,
                full_log_id(ctx.session_id),
                full_log_id(approval_id),
            )
            return None

    def _persist_approval_row(
        self,
        ctx: SessionContext,
        matched_actions: AllMatchedActions,
        payload: dict[str, Any],
    ) -> UUID:
        """Commits the row, register it for the drain, announce to the chat.

        Announce is best-effort: a miss degrades to the FE surfacing the card on
        the next `/live` refetch, so we don't fail the request. A chat
        command's row is announced to the call that waits on the command.
        """
        actions_payload = [a.model_dump(mode="json") for a in matched_actions.actions]
        with get_session_with_tenant(tenant_id=ctx.tenant_id) as db:
            row = action_approval.insert_action_approval(
                db,
                **_approval_owner(ctx),
                actions=actions_payload,
                app_name=matched_actions.app_name,
                payload=payload,
                integration_id=matched_actions.target.integration_id,
            )
            approval_id = row.approval_id
            db.commit()

        self._parked.add(ctx.tenant_id, approval_id)
        try:
            approval_cache.announce_approval(
                approval_id,
                ctx.chat_command_id or ctx.session_id,
                self._cache_factory(ctx.tenant_id),
            )
        except CACHE_TRANSIENT_ERRORS as e:
            logger.warning(
                "approval_announce_error approval=%s error=%r approval_id=%s",
                short_log_id(approval_id),
                str(e),
                full_log_id(approval_id),
            )

        logger.info(
            "approval_requested tenant=%s sandbox=%s session=%s approval=%s "
            "app_name=%r integration=%s action_type=%s action_count=%s "
            "proxy_instance=%s session_id=%s approval_id=%s",
            ctx.tenant_id,
            sandbox_log_label(ctx),
            short_log_id(ctx.session_id),
            short_log_id(approval_id),
            matched_actions.app_name,
            matched_actions.target.integration_id,
            matched_actions.governing_action.action_type,
            len(matched_actions.actions),
            self._proxy_instance_id,
            full_log_id(ctx.session_id),
            full_log_id(approval_id),
        )

        try:
            # The chat already shows the card on the call that waits.
            if ctx.chat_command_id is None:
                self._notify_approval_requested(approval_id, ctx, matched_actions)
        except Exception as e:
            logger.warning(
                "approval_notify_error approval=%s error=%r approval_id=%s",
                short_log_id(approval_id),
                str(e),
                full_log_id(approval_id),
            )

        return approval_id

    async def _await_decision(
        self,
        approval_id: UUID,
        ctx: SessionContext,
        matched_actions: AllMatchedActions,
    ) -> ApprovalDecision:
        """Parks on the wake channel; claims EXPIRED on timeout / cancel.

        Owns removal of the parked-approvals entry in the `finally` block.
        """
        cache = self._cache_factory(ctx.tenant_id)
        try:
            decision = await approval_cache.wait_for_wake(
                approval_id, SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS, cache
            )
            if decision is not None:
                logger.info(
                    "approval_decided " + APPROVAL_DECIDED_FIELDS,
                    *approval_decided_args(
                        ctx,
                        approval_id,
                        matched_actions,
                        decision=decision.value,
                        wake="received",
                        source="wake",
                    ),
                )
                return decision
            resolved = self._claim_expired_or_read_winner(approval_id, ctx.tenant_id)
            source = "timeout" if resolved == ApprovalDecision.EXPIRED else "db_winner"
            logger.info(
                "approval_decided " + APPROVAL_DECIDED_FIELDS,
                *approval_decided_args(
                    ctx,
                    approval_id,
                    matched_actions,
                    decision=resolved.value,
                    wake="missed",
                    source=source,
                ),
            )
            return resolved
        except asyncio.CancelledError:
            # Sandbox socket closed mid-wait. Terminalize the audit row, then
            # re-raise so mitmproxy releases the flow.
            self._claim_expired_or_read_winner(approval_id, ctx.tenant_id)
            raise
        finally:
            self._parked.remove(ctx.tenant_id, approval_id)

    def _claim_expired_or_read_winner(
        self, approval_id: UUID, tenant_id: str
    ) -> ApprovalDecision:
        """
        Conditionally claims EXPIRED; If the API already wrote a decision,
        returns that winner instead so the caller forwards/rejects correctly.
        """
        with get_session_with_tenant(tenant_id=tenant_id) as db:
            claimed = action_approval.try_record_decision(
                db,
                approval_id=approval_id,
                decision=ApprovalDecision.EXPIRED,
            )
            if claimed is not None:
                db.commit()
                return ApprovalDecision.EXPIRED
            existing = action_approval.get_action_approval(db, approval_id)
            if existing is None or existing.decision is None:
                # FK cascade dropped the row (build_session deleted).
                # Treat as expired so the upstream call is rejected.
                logger.error(
                    "approval_row_missing tenant=%s approval=%s approval_id=%s",
                    tenant_id,
                    short_log_id(approval_id),
                    full_log_id(approval_id),
                )
                return ApprovalDecision.EXPIRED
            return existing.decision

    def _write_response_for_decision(
        self, flow: http.HTTPFlow, decision: ApprovalDecision
    ) -> None:
        if decision == ApprovalDecision.APPROVED:
            return
        code = (
            SandboxProxyError.USER_REJECTED
            if decision == ApprovalDecision.REJECTED
            else SandboxProxyError.NOT_AUTHORIZED
        )
        flow.response = http_403(code)

    def _dispatch_injection_or_block(
        self,
        flow: http.HTTPFlow,
        *,
        sandbox: ResolvedSandbox,
        matched_actions: AllMatchedActions | None,
        protocol_target: GatedTarget | None = None,
    ) -> InjectionOutcome:
        """Runs the credential dispatcher; Fails closed with a 403 on BLOCKED."""
        result = self._credential_dispatcher.apply(
            flow,
            InjectionContext(
                sandbox=sandbox,
                matched_actions=matched_actions,
                protocol_target=protocol_target,
            ),
        )
        if result.outcome is InjectionOutcome.BLOCKED:
            flow.response = http_403(
                SandboxProxyError.CREDENTIAL_ERROR, detail=result.block_detail
            )
        return result.outcome

    def _terminalize_after_unhandled_error(
        self, approval_id: UUID, tenant_id: str
    ) -> None:
        """Claims EXPIRED + wakes the parked BLPOP after an exception.

        For when the request hook fails after the row is committed but before a
        decision is recorded. Each step swallows its own errors so cleanup can't
        mask the original exception.
        """
        try:
            decision = self._claim_expired_or_read_winner(approval_id, tenant_id)
        except Exception:
            logger.exception(
                "approval_terminalize_error tenant=%s approval=%s "
                "operation=%s approval_id=%s",
                tenant_id,
                short_log_id(approval_id),
                "db",
                full_log_id(approval_id),
            )
            return
        try:
            approval_cache.send_wake(
                approval_id, decision, self._cache_factory(tenant_id)
            )
        except Exception:
            logger.exception(
                "approval_terminalize_error tenant=%s approval=%s "
                "operation=%s approval_id=%s",
                tenant_id,
                short_log_id(approval_id),
                "wake",
                full_log_id(approval_id),
            )

    # ------------------------------------------------------------------
    # SIGTERM drain
    # ------------------------------------------------------------------

    async def drain_inflight(self) -> None:
        """Drains parked approvals on SIGTERM, bounded by caller.

        Two best-effort phases:
        1. Terminalize each parked approval (claim EXPIRED or read the
           winner) and wake its parked BLPOP.
        2. `asyncio.wait` on tracked `request()` tasks so they return to
           mitmproxy before the caller tears down connections.
        """
        for tenant_id, approval_ids in self._parked.snapshot():
            cache = self._cache_factory(tenant_id)
            for approval_id in approval_ids:
                try:
                    decision = self._claim_expired_or_read_winner(
                        approval_id, tenant_id
                    )
                    try:
                        approval_cache.send_wake(approval_id, decision, cache)
                    except CACHE_TRANSIENT_ERRORS:
                        pass
                    if decision == ApprovalDecision.EXPIRED:
                        logger.info(
                            "drain_expired tenant=%s approval=%s approval_id=%s",
                            tenant_id,
                            short_log_id(approval_id),
                            full_log_id(approval_id),
                        )
                    else:
                        logger.info(
                            "drain_forwarded tenant=%s approval=%s "
                            "decision=%s approval_id=%s",
                            tenant_id,
                            short_log_id(approval_id),
                            decision.value,
                            full_log_id(approval_id),
                        )
                except Exception as e:
                    logger.warning(
                        "drain_error tenant=%s approval=%s error=%r approval_id=%s",
                        tenant_id,
                        short_log_id(approval_id),
                        str(e),
                        full_log_id(approval_id),
                    )

        # Exclude self so we don't deadlock if drain ever ends up registered in
        # the inflight set.
        self_task = asyncio.current_task()
        pending = [t for t in self._inflight_tasks if t is not self_task]
        if pending:
            logger.info("drain_wait requests=%s", len(pending))
            await asyncio.wait(pending)

    # --------------------------------------------------------------------------
    # Notification dispatch
    # --------------------------------------------------------------------------

    def _notify_approval_requested(
        self, approval_id: UUID, ctx: SessionContext, matched_actions: AllMatchedActions
    ) -> None:
        """Best-effort APPROVAL_REQUESTED notification dispatch.

        Body carries no PII; the full payload lives on the action_approval row,
        which the popover fetches when the chat loads.
        """
        with get_session_with_tenant(tenant_id=ctx.tenant_id) as db:
            create_notification(
                user_id=ctx.user_id,
                notif_type=NotificationType.APPROVAL_REQUESTED,
                db_session=db,
                title="Craft is requesting approval",
                additional_data={
                    "approval_id": str(approval_id),
                    "session_id": str(ctx.session_id),
                    "action_type": matched_actions.governing_action.action_type,
                    "action_count": len(matched_actions.actions),
                    "app_name": matched_actions.app_name,
                    "link": _CRAFT_SESSION_LINK_TEMPLATE.format(
                        session_id=ctx.session_id
                    ),
                },
                autocommit=True,
            )

    # --------------------------------------------------------------------------
    # internal helpers
    # --------------------------------------------------------------------------

    async def _bind_signed_identity(self, flow: http.HTTPFlow) -> bool:
        """Verify the relay's signed header and bind it to the client connection.

        Only the connection's first request (CONNECT or plain HTTP) can bind;
        requests inside a tunnel use the CONNECT's identity. Returns False if
        the flow was rejected; never falls back to IP identity after a bad token.
        Without a verifier (pod runtime) this is a no-op.
        """
        verifier = self._signed_identity
        if verifier is None:
            return True
        conn_id = flow.client_conn.id
        if conn_id in self._conn_signed_sandboxes:
            return True
        if flow.request.method != "CONNECT" and conn_id in self._conn_connect_origins:
            return True
        token = parse_signed_identity_header(
            flow.request.headers.get("Proxy-Authorization")
        )
        if token is None:
            self._conn_unsigned.add(conn_id)
            return True
        if conn_id in self._conn_unsigned:
            logger.warning(
                "identity_signed_rejected reason=after_unsigned_request host=%s",
                flow.request.host,
            )
            flow.response = http_403(SandboxProxyError.UNIDENTIFIED_SANDBOX)
            return False
        sandbox = await asyncio.to_thread(
            self._verify_signed_identity, verifier, flow, token
        )
        if sandbox is None:
            return False
        self._conn_signed_sandboxes[conn_id] = sandbox
        if flow.request.method != "CONNECT":
            self._conn_signed_plain_flow[conn_id] = flow.id
        return True

    def _verify_signed_identity(
        self, verifier: SignedIdentityVerifier, flow: http.HTTPFlow, token: str
    ) -> ResolvedSandbox | None:
        src_ip = source_ip(flow.client_conn.peername) or "-"
        try:
            claims, owner = verifier.verify(token)
        except SignedIdentityError as error:
            reason = error.reason.value
        except Exception:
            # A DB or cache blip can't be allowed to grant egress.
            logger.exception("identity_signed_error src_ip=%s", src_ip)
            reason = "internal_error"
        else:
            logger.debug(
                "identity_signed_verified tenant=%s sandbox=%s node=%s "
                "generation=%s src_ip=%s",
                claims.tenant_id,
                claims.sandbox_id,
                claims.node_id,
                claims.generation,
                src_ip,
            )
            return ResolvedSandbox(
                sandbox_id=claims.sandbox_id,
                user_id=owner,
                tenant_id=claims.tenant_id,
                sandbox_name=f"vm-{claims.sandbox_id}",
                sandbox_ip=src_ip,
            )
        logger.warning(
            "identity_signed_rejected reason=%s src_ip=%s host=%s",
            reason,
            src_ip,
            flow.request.host,
        )
        flow.response = http_403(SandboxProxyError.UNIDENTIFIED_SANDBOX)
        return None

    def _session_hint(self, flow: http.HTTPFlow) -> str | None:
        """The relay's session hint header; the pod runtime has no relay."""
        if self._signed_identity is None:
            return None
        return flow.request.headers.get(SESSION_HINT_HEADER)

    def _resolve_sandbox(self, flow: http.HTTPFlow) -> ResolvedSandbox | None:
        """Identify the peer before accepting HTTP requests or CONNECT tunnels."""
        conn_id = flow.client_conn.id
        signed = self._conn_signed_sandboxes.get(conn_id)
        if signed is not None:
            plain_flow = self._conn_signed_plain_flow.get(conn_id)
            if plain_flow is None or plain_flow == flow.id:
                return signed
            logger.warning(
                "identity_signed_connection_reused tenant=%s sandbox=%s host=%s",
                signed.tenant_id,
                sandbox_log_label(signed),
                flow.request.host,
            )
            flow.response = http_403(SandboxProxyError.UNIDENTIFIED_SANDBOX)
            return None
        if (
            self._signed_identity is not None
            and parse_signed_identity_header(
                flow.request.headers.get("Proxy-Authorization")
            )
            is not None
        ):
            # A signed header that did not bind was rejected; never use the IP.
            flow.response = http_403(SandboxProxyError.UNIDENTIFIED_SANDBOX)
            return None

        src_ip = source_ip(flow.client_conn.peername)
        if src_ip is None:
            # mitmproxy peername returned no usable IP -- should never happen
            # over real TCP. Log loudly so a stuck NAT or transport-mode mishap
            # doesn't read as "everything just 403's silently".
            peer = flow.client_conn.peername
            peer_label = "-" if peer is None else ":".join(str(part) for part in peer)
            logger.warning(
                "identity_missing_src_ip host=%s peer=%s",
                flow.request.host,
                peer_label,
            )
            flow.response = http_403(SandboxProxyError.UNIDENTIFIED_SANDBOX)
            return None

        try:
            sandbox: ResolvedSandbox | None = self._identity.resolve_sandbox(src_ip)
        except Exception:
            # A DB blip can't be allowed to grant ungated egress.
            logger.exception(
                "identity_error src_ip=%s host=%s",
                src_ip,
                flow.request.host,
            )
            flow.response = http_403(SandboxProxyError.UNIDENTIFIED_SANDBOX)
            return None
        if sandbox is None:
            # Source IP isn't in the lookup cache. Two common causes:
            # (1) Container died + evicted before its last request drained.
            # (2) Deployment-shape SNAT masks the sandbox's real bridge IP (e.g.
            # proxy outside the sandbox bridge).
            logger.warning(
                "identity_unknown_sandbox src_ip=%s host=%s",
                src_ip,
                flow.request.host,
            )
            flow.response = http_403(SandboxProxyError.UNIDENTIFIED_SANDBOX)
            return None

        return sandbox

    def _resolve_gated_session(
        self, flow: http.HTTPFlow, sandbox: ResolvedSandbox, tag: str | None
    ) -> tuple[UUID, bool, UUID | None] | None:
        """Resolves the originating session from the Proxy-Authorization tag:
        the session id, whether it is a chat (not a Craft session), and the
        chat VM command that the tag names, if any.

        Returns None (caller fails closed) if the tag is absent, malformed, or
        doesn't resolve to one of this user's sessions. DB errors propagate to
        the caller, which also fails closed.
        """
        if tag is None:
            logger.warning(
                "session_missing tenant=%s sandbox=%s host=%s",
                sandbox.tenant_id,
                sandbox_log_label(sandbox),
                flow.request.host,
            )
            return None
        try:
            tagged_id, command_id = parse_session_tag(tag)
        except ValueError:
            logger.warning(
                "session_malformed tenant=%s sandbox=%s host=%s",
                sandbox.tenant_id,
                sandbox_log_label(sandbox),
                flow.request.host,
            )
            return None
        exact = self._identity.resolve_session_by_id(
            tagged_id, sandbox.user_id, sandbox.tenant_id
        )
        from_chat = exact is None
        if exact is None:
            exact = self._identity.resolve_chat_session(
                tagged_id, sandbox.user_id, sandbox.tenant_id
            )
        if exact is None:
            # Stale, foreign, or tampered tag. Fail closed — do not guess.
            logger.warning(
                "session_unverified tenant=%s sandbox=%s session=%s host=%s",
                sandbox.tenant_id,
                sandbox_log_label(sandbox),
                short_log_id(tagged_id),
                flow.request.host,
            )
            return None
        logger.debug(
            "session_verified tenant=%s sandbox=%s session=%s chat=%s host=%s",
            sandbox.tenant_id,
            sandbox_log_label(sandbox),
            short_log_id(exact),
            from_chat,
            flow.request.host,
        )
        return exact, from_chat, command_id

    def _extract_session_tag(self, flow: http.HTTPFlow) -> str | None:
        """The originating session tag, or None.

        HTTPS: cached from the CONNECT in `http_connect`. HTTP: read off the
        request directly, since there's no CONNECT to carry the header.
        """
        conn_id = getattr(flow.client_conn, "id", None)  # ods: ignore[getattr]
        cached = self._conn_session_tags.get(conn_id) if conn_id else None
        # The relay moves the proxy-URL userinfo into the hint header; pod
        # sandboxes still send it as basic auth.
        direct = self._session_hint(flow) or _parse_proxy_auth_username(
            flow.request.headers.get("Proxy-Authorization")
        )
        # opencode's in-process MCP client can't ride the proxy-userinfo tag
        # (shared process, untagged base proxy), so it carries the session id in a
        # header stamped by the per-session opencode.json, which wins for MCP
        # requests. This is a same-user attribution hint, not a security boundary:
        # the sandbox is one trust domain per user, so a compromised process can
        # read any of its sessions' tags and forge this header — signing it buys
        # nothing (the value is stored in-sandbox in plaintext). Cross-user is
        # still blocked by the src-IP-pinned sandbox identity in resolve_sandbox.
        mcp_header = flow.request.headers.get(MCP_SESSION_TAG_HEADER)
        return mcp_header or cached or direct


def parse_session_tag(tag: str) -> tuple[UUID, UUID | None]:
    """The session of a tag, and the chat VM command that it names. A chat
    command sends `<chat session>.<command hex>`
    (`harness_sandbox.py:command_proxy_user`); a Craft tag is the session
    alone. Raises ValueError for a malformed tag."""
    session, separator, command = tag.partition(".")
    return UUID(session), UUID(command) if separator else None


def _approval_owner(ctx: SessionContext) -> dict[str, Any]:
    """The `insert_action_approval` arguments that own a request's row."""
    if ctx.chat_command_id is None:
        return {"session_id": ctx.session_id}
    return {"session_id": None, "chat_command": (ctx.session_id, ctx.chat_command_id)}


def _approval_payload(
    flow: http.HTTPFlow, ctx: SessionContext, matched_actions: AllMatchedActions
) -> dict[str, Any]:
    """What the card shows. A chat card also names the method and path."""
    if ctx.chat_command_id is None:
        return matched_actions.payload
    payload: dict[str, Any] = {
        "method": flow.request.method,
        "path": flow.request.path,
    }
    if matched_actions.payload:
        payload["body"] = matched_actions.payload
    return payload


def _approval_needs_tool(matched_actions: AllMatchedActions) -> http.Response:
    return http_403(
        SandboxProxyError.APPROVAL_NEEDS_TOOL, detail=_app_tool_hint(matched_actions)
    )


def _app_tool_hint(matched_actions: AllMatchedActions) -> str:
    """Which chat tools send the refused request with an approval card."""
    target = matched_actions.target
    if target.kind is not IntegrationKind.API:
        return f"Use the tool of {target.app_name} for this action."
    tool_name = custom_tool_name if target.api_app else app_action_tool_name
    tools = [
        tool_name(target.integration_id, action.action_type)
        for action in matched_actions.actions
        if target.chat_tools
        and action.policy is ActionPolicy.ASK
        and not (target.api_app and always_asks(target.kind, action.action_type))
    ]
    if not tools:
        return f"{target.app_name} has no tool for this request."
    # Chat offers only the connect tool while the user has no sign-in.
    connect = (
        f" If {target.app_name} is not connected, call "
        f"{app_action_tool_name(target.integration_id, 'connect')} instead."
    )
    if len(tools) == 1:
        return f"For {target.app_name}, call: {tools[0]}.{connect}"
    # Each tool sends one action, e.g. one GraphQL root field.
    return (
        f"For {target.app_name}, split the request: one call of each of "
        f"{', '.join(tools)}.{connect}"
    )


# ------------------------------------------------------------------------------
# Proxy-Authorization parsing
# ------------------------------------------------------------------------------


def _parse_proxy_auth_username(header_value: str | None) -> str | None:
    """Extracts the basic-auth username from a `Proxy-Authorization` header.

    The proxy-tag plugin encodes the BuildSession id as the username and uses a
    placeholder password (the password is required for Python's
    `urllib.request.ProxyHandler` to emit the header at all, but the proxy
    treats it as discardable — see session-proxy-tag.ts). Never raises.
    """
    if not header_value:
        return None
    parts = header_value.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "basic":
        return None
    try:
        decoded = base64.b64decode(parts[1], validate=True).decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None
    username = decoded.split(":", 1)[0]
    return username or None
