"""Gate addon: enforces approval policy on identified sandbox egress.

A gated request flows through the addon as:

1. `_resolve_and_match` looks up the sandbox identity and classifies
   the action.
2. `_persist_approval_row` commits the `action_approval` row and
   pushes onto the session's announce list so the api-server's
   chat-stream merger surfaces the card on the open SSE.
3. `_await_decision` parks on `approval:wake:{id}` until the
   decision API signals, the wait window elapses, or the sandbox
   socket closes. On timeout / cancel it claims EXPIRED.
4. `_write_response_for_decision` either forwards (APPROVED) or
   rejects with a 403 (REJECTED / EXPIRED).

Fail-open vs fail-closed: identity, body-size cap, and unidentified
sandbox checks are fail-closed. `ActionMatcher` exceptions and
"not my action type" fall open.
"""

import asyncio
import json
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Protocol
from uuid import UUID

from mitmproxy import http
from sqlalchemy.orm import Session

from onyx.cache.interface import CACHE_TRANSIENT_ERRORS
from onyx.cache.interface import CacheBackend
from onyx.configs.constants import NotificationType
from onyx.db.enums import ApprovalDecision
from onyx.db.notification import create_notification
from onyx.sandbox_proxy import approval_cache
from onyx.sandbox_proxy.action_matcher import ActionMatch
from onyx.sandbox_proxy.action_matcher import ActionMatcher
from onyx.sandbox_proxy.identity import ResolvedSandbox
from onyx.sandbox_proxy.identity import SessionContext
from onyx.server.features.build.db import action_approval
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Hard cap on the body the matcher will look at. Oversize bodies are
# fail-closed: a real DoS attempt against the matcher or exfiltration
# wouldn't show up in summary/payload anyway.
PARSER_MAX_BODY_BYTES = 1_048_576


class _Resolver(Protocol):
    def resolve_sandbox(self, src_ip: str) -> ResolvedSandbox | None: ...

    def resolve_active_session(self, user_id: UUID, tenant_id: str) -> UUID | None: ...


DBSessionFactory = Callable[[str], AbstractContextManager[Session]]
CacheFactory = Callable[[str], CacheBackend]


# 403 codes exposed to the sandbox-side caller. This is a separate
# protocol from `OnyxError` — the sandbox sees only this enum.
_CODE_UNIDENTIFIED_SANDBOX = "unidentified_sandbox"
_CODE_NO_ACTIVE_SESSION = "no_active_session"
_CODE_BODY_TOO_LARGE = "body_too_large"
_CODE_USER_REJECTED = "user_rejected"
_CODE_NOT_AUTHORIZED = "not_authorized"
_CODE_INTERNAL_ERROR = "internal_error"


class ParkedApprovals:
    """Approvals the proxy is currently parked on, grouped by tenant.

    Cross-tenant in-memory state — UUIDs and tenant slugs, no user
    data. The SIGTERM drain walks this per-tenant so one cache backend
    can be reused across each tenant's parked approvals.

    Mutated only from the event loop; the drain reads via
    `snapshot()` to iterate safely while the source mutates.
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
        identity: _Resolver,
        action_matcher: ActionMatcher,
        db_session_factory: DBSessionFactory,
        cache_factory: CacheFactory,
        proxy_instance_id: str,
    ) -> None:
        self._identity = identity
        self._action_matcher = action_matcher
        self._db_session_factory = db_session_factory
        self._cache_factory = cache_factory
        self._proxy_instance_id = proxy_instance_id
        # Invariant: `_persist_approval_row` is the only writer;
        # `_await_decision`'s finally is the only remover.
        self._parked = ParkedApprovals()
        # Each running `request()` coroutine registers itself here so
        # the drain can `asyncio.wait` on real completion instead of
        # sleeping. Self-cleaning via `add_done_callback`.
        self._inflight_tasks: set[asyncio.Task[None]] = set()

    # ------------------------------------------------------------------
    # mitmproxy hook
    # ------------------------------------------------------------------

    async def request(self, flow: http.HTTPFlow) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._inflight_tasks.add(task)
            task.add_done_callback(self._inflight_tasks.discard)

        gate_target = self._resolve_and_match(flow)
        if gate_target is None:
            return
        ctx, match = gate_target

        # mitmproxy forwards the original request on unhandled addon
        # exceptions, which would silently bypass the gate. Fail closed
        # here and terminalize any row we already committed.
        approval_id: UUID | None = None
        try:
            approval_id = self._persist_approval_row(ctx, match)
            decision = await self._await_decision(approval_id, ctx, match)
            self._write_response_for_decision(flow, decision)
        except Exception:
            logger.exception(
                "gate.unhandled_error session_id=%s tenant_id=%s "
                "approval_id=%s action_type=%s",
                ctx.session_id,
                ctx.tenant_id,
                approval_id,
                match.action_type,
            )
            flow.response = _http_403(_CODE_INTERNAL_ERROR)
            if approval_id is not None:
                self._terminalize_after_unhandled_error(approval_id, ctx.tenant_id)

    # ------------------------------------------------------------------
    # request() helpers
    # ------------------------------------------------------------------

    def _resolve_and_match(
        self, flow: http.HTTPFlow
    ) -> tuple[SessionContext, ActionMatch] | None:
        """Identity → matcher → (only if gated) active-session lookup.

        Returns `(ctx, match)` to proceed. Two `None` shapes:

        * fail-closed — sets `flow.response` to a 403 before
          returning (unidentified sandbox, oversize body, gated
          request but no active session to route the card to).
        * fail-open — returns `None` without touching the response
          (matcher crash, non-matching request); mitmproxy then
          forwards the request unchanged.

        Session liveness is intentionally checked LAST. Non-gated
        traffic (npm install, apt, pip, etc.) is identified at the
        pod level but doesn't need an active session — startup-time
        and inter-session egress shouldn't depend on session state.
        """
        src_ip = self._extract_src_ip(flow)
        if src_ip is None:
            flow.response = _http_403(_CODE_UNIDENTIFIED_SANDBOX)
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
            flow.response = _http_403(_CODE_UNIDENTIFIED_SANDBOX)
            return None
        if sandbox is None:
            flow.response = _http_403(_CODE_UNIDENTIFIED_SANDBOX)
            return None

        # raw_content is None for streamed bodies. We don't enable
        # streaming today; treat None as oversize so a future stream
        # opt-in can't silently bypass the cap.
        raw = flow.request.raw_content
        if raw is None or len(raw) > PARSER_MAX_BODY_BYTES:
            flow.response = _http_403(_CODE_BODY_TOO_LARGE)
            return None

        try:
            match = self._action_matcher.match(flow.request)
        except Exception as e:
            logger.exception(
                "gate.matcher_error host=%s error=%s",
                flow.request.host,
                str(e),
            )
            return None

        if match is None:
            return None

        # Gated — now we need a session to route the card to.
        try:
            session_id = self._identity.resolve_active_session(
                sandbox.user_id, sandbox.tenant_id
            )
        except Exception:
            logger.exception(
                "gate.session_lookup_error sandbox_id=%s user_id=%s host=%s",
                sandbox.sandbox_id,
                sandbox.user_id,
                flow.request.host,
            )
            flow.response = _http_403(_CODE_NO_ACTIVE_SESSION)
            return None
        if session_id is None:
            logger.info(
                "gate.no_active_session sandbox_id=%s user_id=%s "
                "tenant_id=%s action_type=%s host=%s",
                sandbox.sandbox_id,
                sandbox.user_id,
                sandbox.tenant_id,
                match.action_type,
                flow.request.host,
            )
            flow.response = _http_403(_CODE_NO_ACTIVE_SESSION)
            return None

        ctx = sandbox.with_session(session_id)
        logger.info(
            "gate.match session_id=%s tenant_id=%s sandbox_id=%s "
            "action_type=%s host=%s",
            ctx.session_id,
            ctx.tenant_id,
            ctx.sandbox_id,
            match.action_type,
            flow.request.host,
        )
        return ctx, match

    def _persist_approval_row(self, ctx: SessionContext, match: ActionMatch) -> UUID:
        """Commit the row, register it for the drain, announce to the chat.

        The announce is best-effort and runs after `db.commit()`. A
        missed announce degrades to "FE surfaces the card on the next
        `/live` refetch (reconnect / remount)" — the row is already
        in Postgres, so we don't fail the request over it.
        """
        with self._db_session_factory(ctx.tenant_id) as db:
            row = action_approval.insert_action_approval(
                db,
                session_id=ctx.session_id,
                action_type=match.action_type,
                payload=match.payload,
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
            "sandbox_id=%s proxy_instance_id=%s action_type=%s",
            approval_id,
            ctx.session_id,
            ctx.tenant_id,
            ctx.sandbox_id,
            self._proxy_instance_id,
            match.action_type,
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
        match: ActionMatch,
    ) -> ApprovalDecision:
        """Park on the wake channel; claim EXPIRED on timeout / cancel.

        Returns the recorded `ApprovalDecision`. The parked-approvals
        entry is set in `_persist_approval_row`; this method owns its
        removal in the `finally` block.
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
                match.action_type,
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
            # Sandbox-side socket closed mid-wait. Claim EXPIRED so the
            # audit row is terminal, then re-raise so mitmproxy releases
            # the flow.
            self._claim_expired_or_read_winner(approval_id, ctx.tenant_id)
            raise
        finally:
            self._parked.remove(ctx.tenant_id, approval_id)

    def _claim_expired_or_read_winner(
        self, approval_id: UUID, tenant_id: str
    ) -> ApprovalDecision:
        """Race-safe terminal write — or read of the existing winner.

        Tries the conditional UPDATE to claim EXPIRED. If we lose
        (the API already wrote APPROVED / REJECTED), reads the row
        and returns the winning decision so the caller forwards or
        rejects accordingly. Used by both the wait-timeout path and
        the SIGTERM drain.
        """
        with self._db_session_factory(tenant_id) as db:
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
                # FK cascade dropped the row mid-flight (build_session
                # deleted). Treat as expired so the upstream call is
                # rejected; the row no longer exists to update.
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
            _CODE_USER_REJECTED
            if decision == ApprovalDecision.REJECTED
            else _CODE_NOT_AUTHORIZED
        )
        flow.response = _http_403(code)

    def _terminalize_after_unhandled_error(
        self, approval_id: UUID, tenant_id: str
    ) -> None:
        """Claim EXPIRED + wake the parked BLPOP after an exception.

        Called when the request hook fails after the row is committed
        but before a decision is recorded. Each sub-step swallows its
        own errors so a failing cleanup doesn't mask the original
        exception.
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

        Two phases, each best-effort:

        1. For every parked approval (iterated per-tenant so each
           tenant uses one cache backend), claim EXPIRED (or read the
           winner if the API just decided) and push the decision onto
           the wake channel so the parked BLPOP returns immediately.
           Runs synchronously in the event loop; at the documented
           scale (few hundred approvals max) this completes well
           inside `_DRAIN_TIMEOUT_S`.
        2. `asyncio.wait` on every tracked `request()` task so the
           hook coroutines pick up their wakes and return to mitmproxy
           before the outer caller tears down connections.
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

    def _notify_approval_requested(
        self, approval_id: UUID, ctx: SessionContext, match: ActionMatch
    ) -> None:
        """Best-effort APPROVAL_REQUESTED notification dispatch.

        Body is `{approval_id, session_id, action_type}` — no PII.
        The full payload lives on the action_approval row; the popover
        fetches it when the chat loads. Failures are swallowed by the
        caller.
        """
        with self._db_session_factory(ctx.tenant_id) as db:
            create_notification(
                user_id=ctx.user_id,
                notif_type=NotificationType.APPROVAL_REQUESTED,
                db_session=db,
                title="Craft is awaiting approval",
                additional_data={
                    "approval_id": str(approval_id),
                    "session_id": str(ctx.session_id),
                    "action_type": match.action_type,
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


# -----------------------------------------------------------------------
# Sandbox-facing 403 helper
# -----------------------------------------------------------------------


def _http_403(code: str) -> http.Response:
    """Build a 403 response visible to the sandbox.

    The body is intentionally minimal — `code` is a stable string
    the SDK / curl wrapper can match on. Locked enum:

      unidentified_sandbox | body_too_large | user_rejected
      | not_authorized | internal_error
    """
    body = json.dumps({"error": code}).encode()
    return http.Response.make(
        403,
        content=body,
        headers={"content-type": "application/json"},
    )
