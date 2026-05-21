"""Gate addon: enforces approval policy on identified sandbox egress.

A gated request flows through the addon as:

1. ``request(flow)`` resolves identity + classifies the action.
2. ``_create_request`` writes the ``action_approval`` row and the
   Redis liveness key in one transaction — Redis failure rolls the
   DB back. The chat surface fetches live rows via
   ``GET /approvals/sessions/{id}/live``.
3. ``_await_decision`` spawns a heartbeat task and blocks on the
   ``approval:wake:{id}`` channel until the decision API signals or
   the wait window elapses.
4. ``_apply_decision_to_flow`` either forwards (APPROVED) or rejects
   with a 403 (REJECTED / EXPIRED).

Decomposing ``request`` into helpers lets the SIGTERM drain path
re-use ``_claim_expired_or_read`` and ``_apply_decision_to_flow``,
and gives the policy-evaluator surface a clean extension point.

Default-open philosophy: ``ActionMatcher`` exceptions and ambiguous
classification fall open (forwarded). The real security boundary is
the proxy's iptables egress lockdown, not classification. Body-size
cap, unidentified-sandbox checks, and identity-resolver exceptions
remain fail-closed — see ``_match_action``.
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
from onyx.sandbox_proxy.identity import SessionContext
from onyx.server.features.build.db import action_approval
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Outer cap on how long a single approval can keep an upstream socket
# parked. Sandbox HTTP clients must set their own timeout >= this
# value (see the AGENTS.md note) or they'll give up before the user
# has time to decide.
WAIT_TIMEOUT_S = 180

# Hard cap on the body the matcher will look at. Oversize bodies are
# fail-closed: a real DoS attempt against the matcher or exfiltration
# wouldn't show up in summary/payload anyway.
PARSER_MAX_BODY_BYTES = 1_048_576


class _Resolver(Protocol):
    def resolve(self, src_ip: str) -> SessionContext | None: ...


DBSessionFactory = Callable[[str], AbstractContextManager[Session]]
CacheFactory = Callable[[str], CacheBackend]


# 403 codes exposed to the sandbox-side caller. This is a separate
# protocol from `OnyxError` — the sandbox sees only this enum.
_CODE_UNIDENTIFIED_SANDBOX = "unidentified_sandbox"
_CODE_BODY_TOO_LARGE = "body_too_large"
_CODE_USER_REJECTED = "user_rejected"
_CODE_NOT_AUTHORIZED = "not_authorized"
_CODE_INTERNAL_ERROR = "internal_error"


class GateAddon:
    """mitmproxy addon that gates external-app requests on user approval."""

    METADATA_KEY = "onyx_session_context"  # mirrors PassthroughAddon

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
        # Approvals the proxy is currently parked on, mapped to their
        # tenant_id so the SIGTERM drain can route the conditional
        # UPDATE back to the right schema. Touched only from the event
        # loop (mitmproxy hooks + drain via ``loop.add_signal_handler``)
        # so a plain dict without a lock is correct.
        self._inflight_tenant_by_approval: dict[UUID, str] = {}
        # Asyncio tasks running our request() hook. Used by the drain
        # to await actual completion instead of sleeping a magic
        # constant. Entries are added on hook entry and discarded
        # automatically via ``add_done_callback``.
        self._inflight_tasks: set[asyncio.Task[None]] = set()

    # ------------------------------------------------------------------
    # mitmproxy hook
    # ------------------------------------------------------------------

    async def request(self, flow: http.HTTPFlow) -> None:
        # Track this hook's task so drain_inflight can wait for actual
        # completion. add_done_callback ensures the set drains itself.
        task = asyncio.current_task()
        if task is not None:
            self._inflight_tasks.add(task)
            task.add_done_callback(self._inflight_tasks.discard)

        match_result = self._match_action(flow)
        if match_result is None:
            return  # short-circuited (unidentified / oversize / non-gated)
        ctx, match = match_result

        # Fail closed on any unhandled exception from row creation or
        # the wait — mitmproxy's default on addon exceptions is to
        # forward the original request, which would silently bypass
        # the gate.
        approval_id: UUID | None = None
        try:
            approval_id = self._create_request(ctx, match)
            decision = await self._await_decision(approval_id, ctx, match)
            self._apply_decision_to_flow(flow, decision)
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
            # If the row was already committed, terminalize it so an
            # undecidable pending row doesn't leak into the audit.
            if approval_id is not None:
                self._safe_terminalize(approval_id, ctx.tenant_id)
        finally:
            # Belt-and-braces: _await_decision's own finally is the
            # canonical pop path, but if it raised before entering its
            # try block (e.g., constructing the cache backend) this
            # guards the drain dict against leaks.
            if approval_id is not None:
                self._inflight_tenant_by_approval.pop(approval_id, None)

    # ------------------------------------------------------------------
    # request() helpers
    # ------------------------------------------------------------------

    def _match_action(
        self, flow: http.HTTPFlow
    ) -> tuple[SessionContext, ActionMatch] | None:
        """Identity + body-size + matcher dispatch.

        Returns ``(ctx, match)`` to proceed, or sets ``flow.response``
        (fail-closed 403) and returns ``None``. A matcher crash also
        returns ``None`` but does NOT set ``flow.response`` — that
        falls open and the request is forwarded unchanged.
        """
        src_ip = self._extract_src_ip(flow)
        if src_ip is None:
            flow.response = _http_403(_CODE_UNIDENTIFIED_SANDBOX)
            return None

        # Prefer identity already resolved by PassthroughAddon — saves
        # a DB hit per request.
        ctx = flow.metadata.get(self.METADATA_KEY)
        if ctx is None:
            try:
                ctx = self._identity.resolve(src_ip)
            except Exception:
                # Identity is a precondition for gating. Fail closed
                # so a DB blip can't grant ungated egress.
                logger.exception(
                    "gate.identity_error src_ip=%s host=%s",
                    src_ip,
                    flow.request.host,
                )
                flow.response = _http_403(_CODE_UNIDENTIFIED_SANDBOX)
                return None
        if ctx is None:
            flow.response = _http_403(_CODE_UNIDENTIFIED_SANDBOX)
            return None

        # raw_content is None for streamed bodies (we don't enable
        # streaming today, but be defensive — treat as oversize so a
        # future addon enabling stream=True can't bypass the cap).
        raw = flow.request.raw_content
        if raw is None:
            flow.response = _http_403(_CODE_BODY_TOO_LARGE)
            return None
        if len(raw) > PARSER_MAX_BODY_BYTES:
            flow.response = _http_403(_CODE_BODY_TOO_LARGE)
            return None

        try:
            match = self._action_matcher.match(flow.request)
        except Exception as e:
            # Default open — the gate is a UX layer, not a sandbox
            # boundary. See module docstring.
            logger.exception(
                "gate.matcher_error host=%s error=%s",
                flow.request.host,
                str(e),
            )
            return None

        if match is None:
            return None  # non-gated; forward unchanged

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

    def _create_request(self, ctx: SessionContext, match: ActionMatch) -> UUID:
        """Persist the row, register for the drain, publish liveness.

        Liveness is published *after* ``db.commit()`` so a commit
        failure can't leave a phantom liveness key in Redis (which
        would surface a non-existent approval in the chat for up to
        ``LIVENESS_TTL_S``). A cache failure here is logged and
        swallowed; the heartbeat in ``_await_decision`` retries on
        each tick.
        """
        with self._db_session_factory(ctx.tenant_id) as db:
            row = action_approval.insert_action_approval(
                db,
                session_id=ctx.session_id,
                action_type=match.action_type,
                payload=match.payload,
            )
            approval_id = row.approval_id  # capture before commit detaches row
            db.commit()

        # Register here (not in _await_decision) so a SIGTERM firing
        # between commit and the caller's await still finds the row
        # in the drain dict.
        self._inflight_tenant_by_approval[approval_id] = ctx.tenant_id

        try:
            approval_cache.set_alive(
                approval_id,
                self._proxy_instance_id,
                self._cache_factory(ctx.tenant_id),
            )
        except CACHE_TRANSIENT_ERRORS as e:
            # Without liveness the chat won't surface the card, so the
            # user can't act on it — there's no point waiting. Mark
            # the row EXPIRED inline and bubble up so request() emits
            # a 403 to the sandbox.
            logger.warning(
                "gate.initial_set_alive_failed approval_id=%s error=%s",
                approval_id,
                str(e),
            )
            self._safe_terminalize(approval_id, ctx.tenant_id)
            raise

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
        """Heartbeat + BLPOP + timeout/cancel cleanup.

        Returns the recorded ``ApprovalDecision``. Always releases the
        liveness key and the in-flight tracking entry on exit.

        The in-flight entry is set in ``_create_request``; this method
        only owns its removal in the ``finally`` block.
        """
        cache = self._cache_factory(ctx.tenant_id)
        heartbeat = asyncio.create_task(self._heartbeat_loop(approval_id, cache))
        try:
            decision = await approval_cache.wait_for_wake(
                approval_id, WAIT_TIMEOUT_S, cache
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
            resolved = self._terminalize_as_expired(approval_id, ctx.tenant_id)
            if resolved == ApprovalDecision.EXPIRED:
                logger.info(
                    "gate.expired_on_timeout approval_id=%s session_id=%s tenant_id=%s",
                    approval_id,
                    ctx.session_id,
                    ctx.tenant_id,
                )
            return resolved
        except asyncio.CancelledError:
            # Sandbox-side socket closed mid-wait. Same cleanup as
            # timeout: try to claim EXPIRED so the audit row is
            # terminal; re-raise so mitmproxy releases the flow.
            self._terminalize_as_expired(approval_id, ctx.tenant_id)
            raise
        finally:
            heartbeat.cancel()
            # Settle the cancellation; log anything unexpected so a
            # silent heartbeat-loop bug doesn't go missing.
            try:
                await heartbeat
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception(
                    "gate.heartbeat_unexpected_error approval_id=%s",
                    approval_id,
                )
            try:
                approval_cache.clear_alive(approval_id, cache)
            except CACHE_TRANSIENT_ERRORS:
                pass
            self._inflight_tenant_by_approval.pop(approval_id, None)

    def _terminalize_as_expired(
        self, approval_id: UUID, tenant_id: str
    ) -> ApprovalDecision:
        """Race-safe terminal write — or read of the existing winner.

        Tries the conditional UPDATE to claim EXPIRED. If we lose (the
        API already wrote APPROVED / REJECTED), re-reads the row and
        returns the winner's decision so the caller forwards / rejects
        correctly. Used by both the normal wait-timeout path (with the
        live ``SessionContext.tenant_id``) and the SIGTERM drain path
        (with the tenant_id snapshotted at registration).
        """
        with self._db_session_factory(tenant_id) as db:
            row = action_approval.record_decision(
                db,
                approval_id=approval_id,
                decision=ApprovalDecision.EXPIRED,
            )
            if row is None:
                row = action_approval.get_action_approval(db, approval_id)
            if row is None or row.decision is None:
                # The row was deleted via FK cascade (build_session
                # dropped mid-flight) — reject the upstream call. This
                # branch is logically impossible if the row exists and
                # the conditional UPDATE failed to match, so log loud
                # if it ever fires.
                logger.error(
                    "gate.row_missing_on_claim approval_id=%s tenant_id=%s",
                    approval_id,
                    tenant_id,
                )
                return ApprovalDecision.EXPIRED
            decision = row.decision
            db.commit()
        return decision

    async def _heartbeat_loop(self, approval_id: UUID, cache: CacheBackend) -> None:
        """Refresh the liveness key every ``HEARTBEAT_INTERVAL_S``.

        A transient cache failure is swallowed; the next tick retries.
        If the proxy dies mid-loop, the key naturally lapses within
        ``LIVENESS_TTL_S``.
        """
        try:
            while True:
                await asyncio.sleep(approval_cache.HEARTBEAT_INTERVAL_S)
                try:
                    approval_cache.set_alive(
                        approval_id, self._proxy_instance_id, cache
                    )
                except CACHE_TRANSIENT_ERRORS as e:
                    logger.warning(
                        "gate.heartbeat_failed approval_id=%s error=%s",
                        approval_id,
                        str(e),
                    )
        except asyncio.CancelledError:
            return

    def _apply_decision_to_flow(
        self, flow: http.HTTPFlow, decision: ApprovalDecision
    ) -> None:
        if decision == ApprovalDecision.APPROVED:
            return  # forward upstream
        code = (
            _CODE_USER_REJECTED
            if decision == ApprovalDecision.REJECTED
            else _CODE_NOT_AUTHORIZED
        )
        flow.response = _http_403(code)

    def _safe_terminalize(self, approval_id: UUID, tenant_id: str) -> None:
        """Best-effort cleanup for an unexpected error path.

        Used when an exception fires after the row is committed but
        before a normal decision can be recorded — runs the same
        conditional UPDATE the timeout path uses, then clears the
        liveness key and pushes the resolved decision onto the wake
        channel. All sub-steps swallow their own errors so a failing
        cleanup never masks the original exception.
        """
        try:
            decision = self._terminalize_as_expired(approval_id, tenant_id)
        except Exception:
            logger.exception(
                "gate.safe_terminalize_db_failed approval_id=%s tenant_id=%s",
                approval_id,
                tenant_id,
            )
            return
        try:
            approval_cache.finalize(
                approval_id, decision, self._cache_factory(tenant_id)
            )
        except Exception:
            logger.exception(
                "gate.safe_terminalize_cache_failed approval_id=%s tenant_id=%s",
                approval_id,
                tenant_id,
            )

    # ------------------------------------------------------------------
    # SIGTERM drain
    # ------------------------------------------------------------------

    async def drain_inflight(self) -> None:
        """Best-effort cleanup of in-flight approvals on shutdown.

        Two phases:

        1. For each parked approval, write EXPIRED via the conditional
           UPDATE (or read back the winner if the API just decided),
           then push the decision onto the wake channel so the parked
           ``_await_decision`` coroutine's BLPOP unblocks immediately
           rather than waiting out ``WAIT_TIMEOUT_S``.
        2. Await every tracked ``request()`` task to actually finish
           — so the outer shutdown doesn't tear down connections while
           coroutines are still serializing their 403 / forward
           response. Outer ``_DRAIN_TIMEOUT_SECONDS`` bounds the wait
           when something hangs.
        """
        # Phase 1: snapshot to avoid mutation while we wake everyone.
        for approval_id, tenant_id in list(self._inflight_tenant_by_approval.items()):
            try:
                decision = self._terminalize_as_expired(approval_id, tenant_id)
                try:
                    approval_cache.finalize(
                        approval_id, decision, self._cache_factory(tenant_id)
                    )
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
                        "gate.drain_forwarded approval_id=%s tenant_id=%s decision=%s",
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

        # Phase 2: wait for the woken tasks to actually finish their
        # cleanup + return from the hook. Exclude the current task so
        # we don't deadlock if drain_inflight ever ends up tracked.
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

        Body is ``{approval_id, session_id, action_type}`` — no PII.
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

    The body is intentionally minimal — ``code`` is a stable string
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
