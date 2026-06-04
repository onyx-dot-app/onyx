"""Gate addon: enforces approval policy on identified sandbox egress.

Fail-closed: identity, body-size cap, and unidentified-sandbox checks.
Fail-open: `ActionMatcher` exceptions and non-matching action types.
"""

import asyncio
import base64
import binascii
import operator
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from cachetools import cachedmethod
from cachetools import TTLCache
from mitmproxy import http
from sqlalchemy.orm import Session

from onyx.cache.interface import CACHE_TRANSIENT_ERRORS
from onyx.cache.interface import CacheBackend
from onyx.configs.constants import NotificationType
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.enums import ApprovalDecidedVia
from onyx.db.enums import ApprovalDecision
from onyx.db.enums import EndpointPolicy
from onyx.db.notification import create_notification
from onyx.db.scheduled_task import get_live_scheduled_run_grants
from onyx.db.scheduled_task import ScheduledRunGrants
from onyx.external_apps.matching.engine import RequestMatch
from onyx.sandbox_proxy import approval_cache
from onyx.sandbox_proxy.action_matcher import ActionMatcher
from onyx.sandbox_proxy.credential_injection import CredentialInjectionDispatcher
from onyx.sandbox_proxy.credential_injection import InjectionContext
from onyx.sandbox_proxy.errors import http_403
from onyx.sandbox_proxy.errors import SandboxProxyError
from onyx.sandbox_proxy.identity import ResolvedSandbox
from onyx.sandbox_proxy.identity import SessionContext
from onyx.sandbox_proxy.snapshot_egress import SnapshotEgressPolicy
from onyx.server.features.build.db import action_approval
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Bodies over this cap are fail-closed (rejected), not parsed by the matcher.
PARSER_MAX_BODY_BYTES = 1_048_576

# flow.metadata flag set in `requestheaders` for confirmed snapshot egress, so
# `request` skips the body cap + matcher and lets the streamed upload through.
_SNAPSHOT_STREAM_FLAG = "onyx_snapshot_stream"


class _IdentityResolver(Protocol):
    """Subset of `IdentityResolver` the gate uses."""

    def resolve_sandbox(self, src_ip: str) -> ResolvedSandbox | None: ...

    def resolve_session_by_id(
        self, session_id: UUID, user_id: UUID, tenant_id: str
    ) -> UUID | None: ...


CacheFactory = Callable[[str], CacheBackend]


# Relative deep link routed through the Next router by NotificationsPopover.tsx;
# must mirror the frontend's CRAFT_PATH + sessionId search param.
_CRAFT_SESSION_LINK_TEMPLATE = "/craft/v1?sessionId={session_id}"


@dataclass(frozen=True)
class _AutoApproval:
    """A decision to approve a gated request without parking it.

    Produced by a grant source in ``_resolve_auto_approval``; the
    mint/inject/notify path that consumes it is source-agnostic. Carries how
    to attribute the audit row (``decided_via``) and the bell entry to raise.
    """

    decided_via: ApprovalDecidedVia
    notif_type: NotificationType
    notification_title: str
    notification_data: dict[str, str | int]


# TTL bounds staleness past a run's RUNNING -> terminal transition.
_GRANT_CACHE_TTL_S = 60.0
_GRANT_CACHE_MAX_ENTRIES = 4096


class ParkedApprovals:
    """Approvals the proxy is currently parked on, grouped by tenant.

    Mutated only from the event loop; the drain reads via `snapshot()`
    to iterate safely while the source mutates.
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
        identity: _IdentityResolver,
        action_matcher: ActionMatcher,
        cache_factory: CacheFactory,
        proxy_instance_id: str,
        credential_dispatcher: CredentialInjectionDispatcher,
        snapshot_policy: SnapshotEgressPolicy | None = None,
        stream_responses: bool = True,
    ) -> None:
        self._identity = identity
        self._action_matcher = action_matcher
        self._cache_factory = cache_factory
        self._proxy_instance_id = proxy_instance_id
        self._credential_dispatcher = credential_dispatcher
        self._snapshot_policy = snapshot_policy
        self._stream_responses = stream_responses
        # Invariant: `_persist_approval_row` is the only writer;
        # `_await_decision`'s finally is the only remover.
        self._parked = ParkedApprovals()
        # client connection id -> session tag, captured from the CONNECT's
        # Proxy-Authorization (only place it's visible for MITM'd HTTPS).
        self._conn_session_tags: dict[str, str] = {}
        # Tracks running `request()` coroutines so the drain can `asyncio.wait`
        # on real completion instead of sleeping. Self-cleaning.
        self._inflight_tasks: set[asyncio.Task[None]] = set()
        # Per-session memoization of the scheduled-run grant lookup. Lock-guarded
        # because `_live_grants` runs on the gate's worker threads.
        self._grant_cache: TTLCache[UUID, ScheduledRunGrants] = TTLCache(
            maxsize=_GRANT_CACHE_MAX_ENTRIES, ttl=_GRANT_CACHE_TTL_S
        )
        self._grant_cache_lock = threading.Lock()

    # ------------------------------------------------------------------
    # mitmproxy hooks
    # ------------------------------------------------------------------

    def http_connect(self, flow: http.HTTPFlow) -> None:
        """Capture the per-session tag from the CONNECT's Proxy-Authorization.

        For MITM'd HTTPS the header rides on the CONNECT, not the decrypted
        inner request, so this is the only place it's visible. Keyed by client
        connection id (one tunnel per subprocess = one session); evicted in
        `client_disconnected`. Best-effort.
        """
        conn_id = getattr(flow.client_conn, "id", None)
        auth_header = flow.request.headers.get("Proxy-Authorization")
        tag = _parse_proxy_auth_username(auth_header)

        logger.debug(
            "gate.http_connect conn_id=%s host=%s port=%s proxy_auth=%r parsed_tag=%s",
            conn_id,
            flow.request.host,
            flow.request.port,
            auth_header,
            tag,
        )
        if conn_id is None:
            return
        if tag:
            self._conn_session_tags[conn_id] = tag

    def client_disconnected(self, client: object) -> None:
        """Drop the connection's cached session tag to bound memory."""
        conn_id = getattr(client, "id", None)
        if conn_id is not None:
            self._conn_session_tags.pop(conn_id, None)

    def responseheaders(self, flow: http.HTTPFlow) -> None:
        """Stream the response body to the sandbox instead of buffering it whole.

        Must run here, not in `response`: by then the body is already buffered.
        """
        if not self._stream_responses:
            return
        if flow.response is not None:
            flow.response.stream = True

    async def requestheaders(self, flow: http.HTTPFlow) -> None:
        """Opt a tenant-scoped snapshot upload into unbuffered streaming.

        Must run here, not in `request`: mitmproxy only honors
        `flow.request.stream = True` before the body is read. Anything not
        confirmed as the resolving tenant's snapshot egress falls through to
        `request`'s normal cap + matcher path.
        """
        policy = self._snapshot_policy
        if policy is None:
            return
        if not policy.host_matches(flow.request.host):
            return

        src_ip = self._extract_src_ip(flow)
        if src_ip is None:
            return
        try:
            sandbox = self._identity.resolve_sandbox(src_ip)
        except Exception:
            # Let `request` re-resolve and fail closed on the DB error.
            return
        if sandbox is None:
            return

        if not policy.should_stream(
            host=flow.request.host,
            port=flow.request.port,
            path_components=tuple(flow.request.path_components),
            tenant_id=sandbox.tenant_id,
        ):
            return

        flow.request.stream = True
        flow.metadata[_SNAPSHOT_STREAM_FLAG] = True
        logger.info(
            "gate.snapshot_stream sandbox_id=%s tenant_id=%s host=%s method=%s",
            sandbox.sandbox_id,
            sandbox.tenant_id,
            flow.request.host,
            flow.request.method,
        )

    async def request(self, flow: http.HTTPFlow) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._inflight_tasks.add(task)
            task.add_done_callback(self._inflight_tasks.discard)

        if flow.metadata.get(_SNAPSHOT_STREAM_FLAG):
            # Already validated in `requestheaders`; body is streaming.
            return

        gate_target = await self._resolve_and_match(flow)
        # Strip the in-band session tag so it never reaches the origin
        flow.request.headers.pop("Proxy-Authorization", None)
        if gate_target is None:
            return
        ctx, match = gate_target

        # Auto-approval short-circuit: a grant source (today: a RUNNING
        # scheduled run pre-approving this app) skips the park. Off-thread to
        # keep sync DB work off the event loop; failure falls through to park.
        try:
            auto_approved = await asyncio.to_thread(self._try_auto_approve, ctx, match)
        except Exception:
            logger.exception(
                "gate.auto_approval_check_error session_id=%s tenant_id=%s "
                "action_type=%s",
                ctx.session_id,
                ctx.tenant_id,
                match.decisive.action_type,
            )
            auto_approved = False
        if auto_approved:
            # Fail closed: an unguarded raise here would let mitmproxy forward
            # the original request, bypassing the gate after an APPROVED row exists.
            try:
                await asyncio.to_thread(
                    self._dispatch_injection_or_block,
                    flow,
                    sandbox=ctx.without_session(),
                    match=match,
                )
            except Exception:
                logger.exception(
                    "gate.auto_approved_dispatch_error session_id=%s tenant_id=%s "
                    "action_type=%s",
                    ctx.session_id,
                    ctx.tenant_id,
                    match.decisive.action_type,
                )
                flow.response = http_403(SandboxProxyError.INTERNAL_ERROR)
            return

        # mitmproxy forwards the original request on unhandled addon
        # exceptions, silently bypassing the gate. Fail closed instead.
        approval_id: UUID | None = None
        try:
            approval_id = self._persist_approval_row(ctx, match)
            decision = await self._await_decision(approval_id, ctx, match)
            self._write_response_for_decision(flow, decision)
            if decision == ApprovalDecision.APPROVED:
                # Off-thread: the external-app resolver may refresh an expiring
                # OAuth token (token POST + Redis lock) before rendering headers;
                # keep that off the proxy event loop so a slow token endpoint
                # stalls only this request, not every in-flight flow.
                await asyncio.to_thread(
                    self._dispatch_injection_or_block,
                    flow,
                    sandbox=ctx.without_session(),
                    match=match,
                )
        except Exception:
            logger.exception(
                "gate.unhandled_error session_id=%s tenant_id=%s "
                "approval_id=%s action_type=%s",
                ctx.session_id,
                ctx.tenant_id,
                approval_id,
                match.decisive.action_type,
            )
            flow.response = http_403(SandboxProxyError.INTERNAL_ERROR)
            if approval_id is not None:
                self._terminalize_after_unhandled_error(approval_id, ctx.tenant_id)

    # ------------------------------------------------------------------
    # request() helpers
    # ------------------------------------------------------------------

    async def _resolve_and_match(
        self, flow: http.HTTPFlow
    ) -> tuple[SessionContext, RequestMatch] | None:
        """Identity → matcher → (only if gated) in-band session resolution.

        Returns `(ctx, match)` to proceed, or `None` two ways:
        * fail-closed — sets a 403 `flow.response` first (unidentified
          sandbox, oversize body, unattributable gated request).
        * fail-open — leaves the response untouched so mitmproxy forwards
          unchanged (matcher crash, non-matching request).

        Session resolution is LAST: only gated actions need a session tag;
        non-gated traffic (npm, apt, pip) is identified at the pod level.
        """
        src_ip = self._extract_src_ip(flow)
        if src_ip is None:
            flow.response = http_403(SandboxProxyError.UNIDENTIFIED_SANDBOX)
            return None

        try:
            sandbox = self._identity.resolve_sandbox(src_ip)
        except Exception:
            # A DB blip can't be allowed to grant ungated egress.
            logger.exception(
                "gate.identity_error src_ip=%s host=%s",
                src_ip,
                flow.request.host,
            )
            flow.response = http_403(SandboxProxyError.UNIDENTIFIED_SANDBOX)
            return None
        if sandbox is None:
            flow.response = http_403(SandboxProxyError.UNIDENTIFIED_SANDBOX)
            return None

        # raw_content is None for streamed bodies; treat None as oversize so a
        # future stream opt-in can't silently bypass the cap.
        raw = flow.request.raw_content
        if raw is None or len(raw) > PARSER_MAX_BODY_BYTES:
            flow.response = http_403(SandboxProxyError.BODY_TOO_LARGE)
            return None

        try:
            match = self._action_matcher.match(flow.request, sandbox.tenant_id)
        except Exception as e:
            # Matcher crash falls through as off-catalog: host-only resolvers
            # still get a chance to inject so the request doesn't forward with
            # a placeholder credential.
            logger.exception(
                "gate.matcher_error host=%s error=%s",
                flow.request.host,
                str(e),
            )
            match = None

        # Audit every evaluated request. session_id is the unvalidated claimed
        # tag (the ASK path validates it below); off_catalog = nothing matched.
        logger.info(
            "gate.request tenant_id=%s sandbox_id=%s session_id=%s host=%s "
            "action_type=%s policy=%s",
            sandbox.tenant_id,
            sandbox.sandbox_id,
            self._extract_session_tag(flow),
            flow.request.host,
            match.decisive.action_type if match is not None else "-",
            match.decisive.policy.value if match is not None else "off_catalog",
        )

        # ALWAYS / DENY / off-catalog terminate here; ASK falls through to the
        # approval pipeline in `request()`.
        if match is None:
            self._dispatch_injection_or_block(flow, sandbox=sandbox, match=None)
            return None

        if match.decisive.policy is EndpointPolicy.DENY:
            flow.response = http_403(SandboxProxyError.POLICY_DENIED)
            return None

        if match.decisive.policy is EndpointPolicy.ALWAYS:
            # Off-thread: see the ASK path in `request` — the resolver may refresh
            # an expiring OAuth token before injecting on this auto-approved call.
            await asyncio.to_thread(
                self._dispatch_injection_or_block, flow, sandbox=sandbox, match=match
            )
            return None

        # ASK: resolve the originating session before prompting. An
        # unattributable action is blocked, not guessed.
        try:
            session_id = self._resolve_gated_session(flow, sandbox)
        except Exception:
            logger.exception(
                "gate.session_lookup_error sandbox_id=%s user_id=%s host=%s",
                sandbox.sandbox_id,
                sandbox.user_id,
                flow.request.host,
            )
            flow.response = http_403(SandboxProxyError.NO_ACTIVE_SESSION)
            return None
        if session_id is None:
            logger.info(
                "gate.unattributed_block sandbox_id=%s user_id=%s "
                "tenant_id=%s action_type=%s host=%s",
                sandbox.sandbox_id,
                sandbox.user_id,
                sandbox.tenant_id,
                match.decisive.action_type,
                flow.request.host,
            )
            flow.response = http_403(SandboxProxyError.NO_ACTIVE_SESSION)
            return None

        ctx = sandbox.with_session(session_id)
        logger.info(
            "gate.match session_id=%s tenant_id=%s sandbox_id=%s "
            "action_type=%s host=%s",
            ctx.session_id,
            ctx.tenant_id,
            ctx.sandbox_id,
            match.decisive.action_type,
            flow.request.host,
        )
        return ctx, match

    def _resolve_auto_approval(
        self, db: Session, ctx: SessionContext, match: RequestMatch
    ) -> _AutoApproval | None:
        """Resolve a gated request to an auto-approval, or ``None`` to park."""
        # Scheduled-task grants are the only auto-approval type today. As other
        # types appear (session-scoped, per-action), each becomes a source
        # resolved here — first hit wins.
        return self._scheduled_task_grant(db, ctx, match)

    @cachedmethod(
        operator.attrgetter("_grant_cache"),
        key=lambda _self, _db, session_id: session_id,
        lock=operator.attrgetter("_grant_cache_lock"),
    )
    def _live_grants(self, db: Session, session_id: UUID) -> ScheduledRunGrants:
        return get_live_scheduled_run_grants(db_session=db, session_id=session_id)

    def _scheduled_task_grant(
        self, db: Session, ctx: SessionContext, match: RequestMatch
    ) -> _AutoApproval | None:
        """Grant source: a RUNNING scheduled run whose task pre-approves the
        matched app."""
        grants = self._live_grants(db, ctx.session_id)
        if grants is None:
            return None
        run_id, granted_app_ids = grants
        if match.external_app_id not in granted_app_ids:
            return None
        return _AutoApproval(
            decided_via=ApprovalDecidedVia.PRE_APPROVAL,
            notif_type=NotificationType.SCHEDULED_TASK_PRE_APPROVED_ACTION,
            notification_title=f"Scheduled task used {match.app_name} (pre-approved)",
            notification_data={
                "run_id": str(run_id),
                "external_app_id": match.external_app_id,
            },
        )

    def _try_auto_approve(self, ctx: SessionContext, match: RequestMatch) -> bool:
        """Mint a pre-decided APPROVED row if a grant source covers this
        request; False otherwise (falls through to the park). Source-agnostic.

        Bypassing ``try_record_decision``'s arbiter is safe: nothing parks
        on a pre-decided row.
        """
        with get_session_with_tenant(tenant_id=ctx.tenant_id) as db:
            approval = self._resolve_auto_approval(db, ctx, match)
            if approval is None:
                return False
            row = action_approval.insert_action_approval(
                db,
                session_id=ctx.session_id,
                actions=[a.model_dump(mode="json") for a in match.actions],
                app_name=match.app_name,
                payload=match.payload,
                external_app_id=match.external_app_id,
                decision=ApprovalDecision.APPROVED,
                decided_via=approval.decided_via,
            )
            approval_id = row.approval_id
            db.commit()

        logger.info(
            "gate.auto_approved approval_id=%s session_id=%s tenant_id=%s "
            "decided_via=%s external_app_id=%s action_type=%s",
            approval_id,
            ctx.session_id,
            ctx.tenant_id,
            approval.decided_via,
            match.external_app_id,
            match.decisive.action_type,
        )
        try:
            self._notify_auto_approved(ctx, approval)
        except Exception as e:
            logger.warning(
                "gate.auto_approve_notify_failed approval_id=%s error=%s",
                approval_id,
                str(e),
            )
        return True

    def _persist_approval_row(self, ctx: SessionContext, match: RequestMatch) -> UUID:
        """Commit the row, register it for the drain, announce to the chat.

        Announce is best-effort: a miss degrades to the FE surfacing the
        card on the next `/live` refetch, so we don't fail the request.
        """
        actions_payload = [a.model_dump(mode="json") for a in match.actions]
        with get_session_with_tenant(tenant_id=ctx.tenant_id) as db:
            row = action_approval.insert_action_approval(
                db,
                session_id=ctx.session_id,
                actions=actions_payload,
                app_name=match.app_name,
                payload=match.payload,
                external_app_id=match.external_app_id,
            )
            approval_id = row.approval_id
            db.commit()

        self._parked.add(ctx.tenant_id, approval_id)
        try:
            approval_cache.announce_approval(
                approval_id,
                ctx.session_id,
                self._cache_factory(ctx.tenant_id),
            )
        except CACHE_TRANSIENT_ERRORS as e:
            logger.warning(
                "gate.announce_failed approval_id=%s error=%s",
                approval_id,
                str(e),
            )

        logger.info(
            "gate.row_committed approval_id=%s session_id=%s tenant_id=%s "
            "sandbox_id=%s proxy_instance_id=%s action_type=%s action_count=%s",
            approval_id,
            ctx.session_id,
            ctx.tenant_id,
            ctx.sandbox_id,
            self._proxy_instance_id,
            match.decisive.action_type,
            len(match.actions),
        )

        try:
            self._notify_approval_requested(approval_id, ctx, match)
        except Exception as e:
            logger.warning(
                "approval.notify_failed approval_id=%s error=%s",
                approval_id,
                str(e),
            )

        return approval_id

    async def _await_decision(
        self,
        approval_id: UUID,
        ctx: SessionContext,
        match: RequestMatch,
    ) -> ApprovalDecision:
        """Park on the wake channel; claim EXPIRED on timeout / cancel.

        Owns removal of the parked-approvals entry in the `finally` block.
        """
        cache = self._cache_factory(ctx.tenant_id)
        try:
            decision = await approval_cache.wait_for_wake(
                approval_id, approval_cache.WAIT_TIMEOUT_S, cache
            )
            if decision is not None:
                logger.info(
                    "gate.wake_received approval_id=%s session_id=%s "
                    "tenant_id=%s decision=%s",
                    approval_id,
                    ctx.session_id,
                    ctx.tenant_id,
                    decision.value,
                )
                return decision
            logger.info(
                "gate.wake_timeout approval_id=%s session_id=%s tenant_id=%s "
                "action_type=%s",
                approval_id,
                ctx.session_id,
                ctx.tenant_id,
                match.decisive.action_type,
            )
            resolved = self._claim_expired_or_read_winner(approval_id, ctx.tenant_id)
            if resolved == ApprovalDecision.EXPIRED:
                logger.info(
                    "gate.expired_on_timeout approval_id=%s session_id=%s tenant_id=%s",
                    approval_id,
                    ctx.session_id,
                    ctx.tenant_id,
                )
            return resolved
        except asyncio.CancelledError:
            # Sandbox socket closed mid-wait. Terminalize the audit row,
            # then re-raise so mitmproxy releases the flow.
            self._claim_expired_or_read_winner(approval_id, ctx.tenant_id)
            raise
        finally:
            self._parked.remove(ctx.tenant_id, approval_id)

    def _claim_expired_or_read_winner(
        self, approval_id: UUID, tenant_id: str
    ) -> ApprovalDecision:
        """Conditionally claim EXPIRED; if the API already wrote a decision,
        return that winner instead so the caller forwards/rejects correctly.
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
                    "gate.row_missing_on_claim approval_id=%s tenant_id=%s",
                    approval_id,
                    tenant_id,
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
        match: RequestMatch | None,
    ) -> None:
        """Run the credential dispatcher; fail closed with a 403 on BLOCKED."""
        self._credential_dispatcher.apply_or_block(
            flow,
            InjectionContext(
                sandbox=sandbox,
                match=match,
            ),
        )

    def _terminalize_after_unhandled_error(
        self, approval_id: UUID, tenant_id: str
    ) -> None:
        """Claim EXPIRED + wake the parked BLPOP after an exception.

        For when the request hook fails after the row is committed but
        before a decision is recorded. Each step swallows its own errors
        so cleanup can't mask the original exception.
        """
        try:
            decision = self._claim_expired_or_read_winner(approval_id, tenant_id)
        except Exception:
            logger.exception(
                "gate.terminalize_db_failed approval_id=%s tenant_id=%s",
                approval_id,
                tenant_id,
            )
            return
        try:
            approval_cache.send_wake(
                approval_id, decision, self._cache_factory(tenant_id)
            )
        except Exception:
            logger.exception(
                "gate.terminalize_wake_failed approval_id=%s tenant_id=%s",
                approval_id,
                tenant_id,
            )

    # ------------------------------------------------------------------
    # SIGTERM drain
    # ------------------------------------------------------------------

    async def drain_inflight(self) -> None:
        """Drain parked approvals on SIGTERM, bounded by caller.

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
                            "gate.drain_expired approval_id=%s tenant_id=%s",
                            approval_id,
                            tenant_id,
                        )
                    else:
                        logger.info(
                            "gate.drain_forwarded approval_id=%s "
                            "tenant_id=%s decision=%s",
                            approval_id,
                            tenant_id,
                            decision.value,
                        )
                except Exception as e:
                    logger.warning(
                        "gate.drain_error approval_id=%s tenant_id=%s error=%s",
                        approval_id,
                        tenant_id,
                        str(e),
                    )

        # Exclude self so we don't deadlock if drain ever ends up
        # registered in the inflight set.
        self_task = asyncio.current_task()
        pending = [t for t in self._inflight_tasks if t is not self_task]
        if pending:
            logger.info("gate.drain_awaiting_tasks count=%d", len(pending))
            await asyncio.wait(pending)

    # ------------------------------------------------------------------
    # Notification dispatch
    # ------------------------------------------------------------------

    def _notify_auto_approved(
        self, ctx: SessionContext, approval: _AutoApproval
    ) -> None:
        """Best-effort bell entry for an auto-approved action.

        ``create_notification`` dedups on (user, type, additional_data), so
        the grant source must keep ``notification_data`` a stable per-scope
        key — anything per-request would defeat the dedup.
        """
        with get_session_with_tenant(tenant_id=ctx.tenant_id) as db:
            create_notification(
                user_id=ctx.user_id,
                notif_type=approval.notif_type,
                db_session=db,
                title=approval.notification_title,
                additional_data=approval.notification_data,
                autocommit=True,
            )

    def _notify_approval_requested(
        self, approval_id: UUID, ctx: SessionContext, match: RequestMatch
    ) -> None:
        """Best-effort APPROVAL_REQUESTED notification dispatch.

        Body carries no PII; the full payload lives on the action_approval
        row, which the popover fetches when the chat loads.
        """
        with get_session_with_tenant(tenant_id=ctx.tenant_id) as db:
            create_notification(
                user_id=ctx.user_id,
                notif_type=NotificationType.APPROVAL_REQUESTED,
                db_session=db,
                title="Craft is awaiting approval",
                additional_data={
                    "approval_id": str(approval_id),
                    "session_id": str(ctx.session_id),
                    "action_type": match.decisive.action_type,
                    "action_count": len(match.actions),
                    "app_name": match.app_name,
                    "link": _CRAFT_SESSION_LINK_TEMPLATE.format(
                        session_id=ctx.session_id
                    ),
                },
                autocommit=True,
            )

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    def _extract_src_ip(self, flow: http.HTTPFlow) -> str | None:
        peer = flow.client_conn.peername
        if peer is None or len(peer) < 1:
            return None
        addr = peer[0]
        if not isinstance(addr, str):
            return None
        return addr

    def _resolve_gated_session(
        self, flow: http.HTTPFlow, sandbox: ResolvedSandbox
    ) -> UUID | None:
        """Resolve the originating session from the Proxy-Authorization tag.

        Returns None (caller fails closed) if the tag is absent, malformed,
        or doesn't resolve to one of this user's sessions. DB errors
        propagate to the caller, which also fails closed.
        """
        tag = self._extract_session_tag(flow)
        if tag is None:
            logger.warning(
                "gate.session_tag_missing sandbox_id=%s user_id=%s host=%s",
                sandbox.sandbox_id,
                sandbox.user_id,
                flow.request.host,
            )
            return None
        try:
            tagged_id = UUID(tag)
        except ValueError:
            logger.warning(
                "gate.session_tag_malformed sandbox_id=%s user_id=%s host=%s",
                sandbox.sandbox_id,
                sandbox.user_id,
                flow.request.host,
            )
            return None
        exact = self._identity.resolve_session_by_id(
            tagged_id, sandbox.user_id, sandbox.tenant_id
        )
        if exact is None:
            # Stale, foreign, or tampered tag. Fail closed — do not guess.
            logger.warning(
                "gate.session_tag_unverified sandbox_id=%s user_id=%s host=%s",
                sandbox.sandbox_id,
                sandbox.user_id,
                flow.request.host,
            )
            return None
        logger.info(
            "gate.session_exact session_id=%s sandbox_id=%s host=%s",
            exact,
            sandbox.sandbox_id,
            flow.request.host,
        )
        return exact

    def _extract_session_tag(self, flow: http.HTTPFlow) -> str | None:
        """The originating session tag, or None.

        HTTPS: cached from the CONNECT in `http_connect`. HTTP: read off the
        request directly, since there's no CONNECT to carry the header.
        """
        conn_id = getattr(flow.client_conn, "id", None)
        cached = self._conn_session_tags.get(conn_id) if conn_id else None
        direct_auth_header = flow.request.headers.get("Proxy-Authorization")
        direct = _parse_proxy_auth_username(direct_auth_header)
        tag = cached or direct

        logger.debug(
            "gate.session_tag_extract conn_id=%s host=%s cached=%s "
            "direct=%s direct_proxy_auth=%r resolved=%s",
            conn_id,
            flow.request.host,
            cached,
            direct,
            direct_auth_header,
            tag,
        )
        return tag


# -----------------------------------------------------------------------
# Proxy-Authorization parsing
# -----------------------------------------------------------------------


def _parse_proxy_auth_username(header_value: str | None) -> str | None:
    """Extract the basic-auth username from a `Proxy-Authorization` header.

    The proxy-tag plugin encodes the BuildSession id as the username and
    uses a placeholder password (the password is required for Python's
    `urllib.request.ProxyHandler` to emit the header at all, but the
    proxy treats it as discardable — see session-proxy-tag.ts). Never
    raises.
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
