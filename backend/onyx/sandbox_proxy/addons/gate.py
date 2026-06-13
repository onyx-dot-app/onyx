"""Gate addon: enforces approval policy on identified sandbox egress.

Fail-closed: identity, body-size cap, and unidentified-sandbox checks.
Fail-open: `RequestEvaluator` exceptions and non-matching action types.
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
from onyx.external_apps.matching.engine import actions_requiring_approval
from onyx.external_apps.matching.engine import AllMatchedActions
from onyx.sandbox_proxy import approval_cache
from onyx.sandbox_proxy.credential_injection import CredentialInjectionDispatcher
from onyx.sandbox_proxy.credential_injection import InjectionContext
from onyx.sandbox_proxy.credential_injection import InjectionOutcome
from onyx.sandbox_proxy.errors import http_403
from onyx.sandbox_proxy.errors import SandboxProxyError
from onyx.sandbox_proxy.identity import ResolvedSandbox
from onyx.sandbox_proxy.identity import SessionContext
from onyx.sandbox_proxy.logging_utils import approval_decided_args
from onyx.sandbox_proxy.logging_utils import APPROVAL_DECIDED_FIELDS
from onyx.sandbox_proxy.logging_utils import credential_outcome_label
from onyx.sandbox_proxy.logging_utils import egress_approval_matched_args
from onyx.sandbox_proxy.logging_utils import EGRESS_APPROVAL_MATCHED_FIELDS
from onyx.sandbox_proxy.logging_utils import egress_matched_args
from onyx.sandbox_proxy.logging_utils import EGRESS_MATCHED_FIELDS
from onyx.sandbox_proxy.logging_utils import egress_session_matched_args
from onyx.sandbox_proxy.logging_utils import EGRESS_SESSION_MATCHED_FIELDS
from onyx.sandbox_proxy.logging_utils import egress_target_args
from onyx.sandbox_proxy.logging_utils import EGRESS_TARGET_FIELDS
from onyx.sandbox_proxy.logging_utils import full_log_id
from onyx.sandbox_proxy.logging_utils import sandbox_log_label
from onyx.sandbox_proxy.logging_utils import short_log_id
from onyx.sandbox_proxy.request_evaluator import RequestEvaluator
from onyx.server.features.build.db import action_approval
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Bodies over this cap are fail-closed (rejected), not parsed by the matcher.
PARSER_MAX_BODY_BYTES = 1_048_576


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
class _ApprovalGrant:
    """A decision to approve a gated request without parking it.

    Produced by a grant source in ``_resolve_approval_grant``. Carries how to
    attribute the audit row (``decided_via``) and any bell entry to raise.
    """

    decided_via: ApprovalDecidedVia
    notif_type: NotificationType | None = None
    notification_title: str | None = None
    notification_data: dict[str, str | int] | None = None


# TTL bounds staleness past a run's RUNNING -> terminal transition.
_GRANT_CACHE_TTL_S = 60.0
_GRANT_CACHE_MAX_ENTRIES = 4096


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
        identity: _IdentityResolver,
        request_evaluator: RequestEvaluator,
        cache_factory: CacheFactory,
        proxy_instance_id: str,
        credential_dispatcher: CredentialInjectionDispatcher,
        stream_responses: bool = True,
    ) -> None:
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
        # Tracks running `request()` coroutines so the drain can `asyncio.wait`
        # on real completion instead of sleeping. Self-cleaning.
        self._inflight_tasks: set[asyncio.Task[None]] = set()
        # Per-session memoization of the scheduled-run grant lookup.
        # Lock-guarded because `_live_grants` runs on the gate's worker threads.
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
        if tag:
            self._conn_session_tags[conn_id] = tag

    def client_disconnected(self, client: object) -> None:
        """Drops the connection's cached session tag to bound memory."""
        conn_id = getattr(client, "id", None)
        if conn_id is not None:
            self._conn_session_tags.pop(conn_id, None)

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

        gate_target = await self._resolve_and_match(flow)
        # Strip the in-band session tag so it never reaches the origin
        flow.request.headers.pop("Proxy-Authorization", None)
        if gate_target is None:
            return
        ctx, matched_actions = gate_target

        # Grant sources can approve without asking the user. Check
        # before we insert a pending row, then re-check after insert to close the
        # window where a session grant appears between those two steps.
        applied_approval_id = await self._apply_approval_grant(ctx, matched_actions)
        if applied_approval_id is not None:
            # Fail closed: an unguarded raise here would let mitmproxy forward
            # the original request, bypassing the gate after an APPROVED row
            # exists.
            try:
                await self._dispatch_approved_request(
                    flow, ctx, matched_actions, approval_id=applied_approval_id
                )
            except Exception:
                logger.exception(
                    "approval_dispatch_error tenant=%s sandbox=%s "
                    "session=%s app_name=%r action_type=%s session_id=%s",
                    ctx.tenant_id,
                    sandbox_log_label(ctx),
                    short_log_id(ctx.session_id),
                    matched_actions.app_name,
                    matched_actions.governing_action.action_type,
                    full_log_id(ctx.session_id),
                )
                flow.response = http_403(SandboxProxyError.INTERNAL_ERROR)
            return

        # mitmproxy forwards the original request on unhandled addon exceptions,
        # silently bypassing the gate. Fail closed instead.
        approval_id: UUID | None = None
        try:
            approval_id = self._persist_approval_row(ctx, matched_actions)
            if (
                await self._apply_approval_grant(
                    ctx, matched_actions, approval_id=approval_id
                )
                is not None
            ):
                self._parked.remove(ctx.tenant_id, approval_id)
                decision = ApprovalDecision.APPROVED
            else:
                decision = await self._await_decision(approval_id, ctx, matched_actions)
            self._write_response_for_decision(flow, decision)
            if decision == ApprovalDecision.APPROVED:
                await self._dispatch_approved_request(
                    flow, ctx, matched_actions, approval_id=approval_id
                )
            else:
                reason = (
                    SandboxProxyError.USER_REJECTED.value
                    if decision == ApprovalDecision.REJECTED
                    else SandboxProxyError.NOT_AUTHORIZED.value
                )
                logger.info(
                    "egress_block " + EGRESS_APPROVAL_MATCHED_FIELDS + " reason=%s",
                    *egress_approval_matched_args(
                        flow, ctx, matched_actions, EndpointPolicy.ASK, approval_id
                    ),
                    reason,
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

    async def _dispatch_approved_request(
        self,
        flow: http.HTTPFlow,
        ctx: SessionContext,
        matched_actions: AllMatchedActions,
        *,
        approval_id: UUID | None = None,
    ) -> None:
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
                flow, ctx, matched_actions, EndpointPolicy.ASK
            )
        else:
            fields = EGRESS_APPROVAL_MATCHED_FIELDS
            args = egress_approval_matched_args(
                flow, ctx, matched_actions, EndpointPolicy.ASK, approval_id
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

    # --------------------------------------------------------------------------
    # request() helpers
    # --------------------------------------------------------------------------

    async def _resolve_and_match(
        self, flow: http.HTTPFlow
    ) -> tuple[SessionContext, AllMatchedActions] | None:
        """Identity -> matcher -> (only if gated) in-band session resolution.

        Returns `(ctx, matched_actions)` to proceed, or `None` two ways:
        * fail-closed — sets a 403 `flow.response` first (unidentified
          sandbox, oversize body, unattributable gated request).
        * fail-open — leaves the response untouched so mitmproxy forwards
          unchanged (matcher crash, non-matching request).

        Session resolution is LAST: only gated actions need a session tag;
        Non-gated traffic (npm, apt, pip) is identified at the pod level.
        """
        src_ip = self._extract_src_ip(flow)
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
            sandbox = self._identity.resolve_sandbox(src_ip)
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

        try:
            matched_actions = self._request_evaluator.evaluate(
                flow.request, sandbox.tenant_id, sandbox.user_id
            )
        except Exception as e:
            # Matcher crash falls through as off-catalog: host-only resolvers
            # still get a chance to inject so the request doesn't forward with a
            # placeholder credential.
            logger.exception(
                "matcher_error tenant=%s sandbox=%s host=%s error=%r",
                sandbox.tenant_id,
                sandbox_log_label(sandbox),
                flow.request.host,
                str(e),
            )
            matched_actions = None

        # ALWAYS / DENY / off-catalog terminate here; ASK falls through to the
        # approval pipeline in `request()`.
        if matched_actions is None:
            injection = self._dispatch_injection_or_block(
                flow, sandbox=sandbox, matched_actions=None
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

        if matched_actions.governing_action.policy is EndpointPolicy.DENY:
            flow.response = http_403(SandboxProxyError.POLICY_DENIED)
            logger.info(
                "egress_block " + EGRESS_MATCHED_FIELDS + " reason=%s",
                *egress_matched_args(
                    flow, sandbox, matched_actions, EndpointPolicy.DENY
                ),
                SandboxProxyError.POLICY_DENIED.value,
            )
            return None

        if matched_actions.governing_action.policy is EndpointPolicy.ALWAYS:
            # Off-thread: see the ASK path in `request` — the resolver may
            # refresh an expiring OAuth token before injecting on this
            # auto-approved call.
            injection = await asyncio.to_thread(
                self._dispatch_injection_or_block,
                flow,
                sandbox=sandbox,
                matched_actions=matched_actions,
            )
            if injection is InjectionOutcome.BLOCKED:
                logger.warning(
                    "egress_block "
                    + EGRESS_MATCHED_FIELDS
                    + " reason=%s credential_outcome=%s",
                    *egress_matched_args(
                        flow, sandbox, matched_actions, EndpointPolicy.ALWAYS
                    ),
                    SandboxProxyError.CREDENTIAL_ERROR.value,
                    credential_outcome_label(injection),
                )
            else:
                logger.info(
                    "egress_allow " + EGRESS_MATCHED_FIELDS + " credential_outcome=%s",
                    *egress_matched_args(
                        flow, sandbox, matched_actions, EndpointPolicy.ALWAYS
                    ),
                    credential_outcome_label(injection),
                )
            return None

        # ASK: resolve the originating session before prompting. An
        # unattributable action is blocked, not guessed.
        try:
            session_id = self._resolve_gated_session(flow, sandbox)
        except Exception:
            logger.exception(
                "session_lookup_error tenant=%s sandbox=%s host=%s app_name=%r "
                "action_type=%s",
                sandbox.tenant_id,
                sandbox_log_label(sandbox),
                flow.request.host,
                matched_actions.app_name,
                matched_actions.governing_action.action_type,
            )
            flow.response = http_403(SandboxProxyError.NO_ACTIVE_SESSION)
            return None
        if session_id is None:
            logger.info(
                "egress_block " + EGRESS_MATCHED_FIELDS + " reason=%s",
                *egress_matched_args(
                    flow, sandbox, matched_actions, EndpointPolicy.ASK
                ),
                SandboxProxyError.NO_ACTIVE_SESSION.value,
            )
            flow.response = http_403(SandboxProxyError.NO_ACTIVE_SESSION)
            return None

        ctx = sandbox.with_session(session_id)
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

    def _resolve_approval_grant(
        self, db: Session, ctx: SessionContext, matched_actions: AllMatchedActions
    ) -> _ApprovalGrant | None:
        """Resolve a gated request to a reusable approval grant, or ``None``."""
        # Grant sources are checked in order, first hit wins.
        return self._scheduled_task_grant(db, ctx, matched_actions) or (
            self._session_grant(db, ctx, matched_actions)
        )

    @cachedmethod(
        operator.attrgetter("_grant_cache"),
        key=lambda _self, _db, session_id: session_id,
        lock=operator.attrgetter("_grant_cache_lock"),
    )
    def _live_grants(self, db: Session, session_id: UUID) -> ScheduledRunGrants:
        return get_live_scheduled_run_grants(db_session=db, session_id=session_id)

    def _scheduled_task_grant(
        self, db: Session, ctx: SessionContext, matched_actions: AllMatchedActions
    ) -> _ApprovalGrant | None:
        """
        Grant source: a RUNNING scheduled run whose task pre-approves the
        matched app.
        """
        grants = self._live_grants(db, ctx.session_id)
        if grants is None:
            return None
        run_id, granted_app_ids = grants
        if matched_actions.external_app_id not in granted_app_ids:
            return None
        return _ApprovalGrant(
            decided_via=ApprovalDecidedVia.PRE_APPROVAL,
            notif_type=NotificationType.SCHEDULED_TASK_PRE_APPROVED_ACTION,
            notification_title=f"Scheduled task used {matched_actions.app_name} (pre-approved)",
            notification_data={
                "run_id": str(run_id),
                "external_app_id": matched_actions.external_app_id,
            },
        )

    def _session_grant(
        self, db: Session, ctx: SessionContext, matched_actions: AllMatchedActions
    ) -> _ApprovalGrant | None:
        """The user approved this app/action for the session."""
        action_types = actions_requiring_approval(matched_actions.actions)
        if not action_types:
            return None
        cache: CacheBackend | None = None
        try:
            cache = self._cache_factory(ctx.tenant_id)
            if approval_cache.cached_session_grants_cover(
                session_id=ctx.session_id,
                external_app_id=matched_actions.external_app_id,
                action_types=action_types,
                cache=cache,
            ):
                return _ApprovalGrant(decided_via=ApprovalDecidedVia.SESSION_GRANT)
        except CACHE_TRANSIENT_ERRORS as e:
            logger.warning(
                "approval_grant_cache_error tenant=%s session=%s "
                "external_app_id=%s operation=%s error=%r",
                ctx.tenant_id,
                short_log_id(ctx.session_id),
                matched_actions.external_app_id,
                "check",
                str(e),
            )

        grant_source_rows = action_approval.list_session_grant_action_approvals(
            db,
            session_id=ctx.session_id,
            external_app_id=matched_actions.external_app_id,
        )
        granted_action_types: set[str] = set()
        for grant_source_row in grant_source_rows:
            granted_action_types.update(
                actions_requiring_approval(grant_source_row.actions)
            )
        if not set(action_types).issubset(granted_action_types):
            return None

        if cache is not None:
            try:
                for grant_source_row in grant_source_rows:
                    approval_cache.cache_session_grant_actions(
                        session_id=ctx.session_id,
                        external_app_id=matched_actions.external_app_id,
                        action_types=actions_requiring_approval(
                            grant_source_row.actions
                        ),
                        source_approval_id=grant_source_row.approval_id,
                        cache=cache,
                    )
            except CACHE_TRANSIENT_ERRORS as e:
                logger.warning(
                    "approval_grant_cache_error tenant=%s session=%s "
                    "external_app_id=%s operation=%s error=%r",
                    ctx.tenant_id,
                    short_log_id(ctx.session_id),
                    matched_actions.external_app_id,
                    "hydrate",
                    str(e),
                )
        return _ApprovalGrant(decided_via=ApprovalDecidedVia.SESSION_GRANT)

    async def _apply_approval_grant(
        self,
        ctx: SessionContext,
        matched_actions: AllMatchedActions,
        *,
        approval_id: UUID | None = None,
    ) -> UUID | None:
        try:
            return await asyncio.to_thread(
                self._try_apply_approval_grant,
                ctx,
                matched_actions,
                approval_id,
            )
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

    def _try_apply_approval_grant(
        self,
        ctx: SessionContext,
        matched_actions: AllMatchedActions,
        approval_id: UUID | None,
    ) -> UUID | None:
        """Apply an existing approval grant to a new or already-persisted row."""
        with get_session_with_tenant(tenant_id=ctx.tenant_id) as db:
            grant = self._resolve_approval_grant(db, ctx, matched_actions)
            if grant is None:
                return None
            if approval_id is None:
                row = action_approval.insert_action_approval(
                    db,
                    session_id=ctx.session_id,
                    actions=[
                        a.model_dump(mode="json") for a in matched_actions.actions
                    ],
                    app_name=matched_actions.app_name,
                    payload=matched_actions.payload,
                    external_app_id=matched_actions.external_app_id,
                    decision=ApprovalDecision.APPROVED,
                    decided_via=grant.decided_via,
                )
                applied_approval_id = row.approval_id
            else:
                decided = action_approval.try_record_decision(
                    db,
                    approval_id=approval_id,
                    decision=ApprovalDecision.APPROVED,
                    decided_via=grant.decided_via,
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
                source=grant.decided_via.value,
            ),
        )
        try:
            if grant.notif_type is not None:
                self._notify_approval_grant(ctx, grant)
        except Exception as e:
            logger.warning(
                "approval_notify_error approval=%s error=%r approval_id=%s",
                short_log_id(applied_approval_id),
                str(e),
                full_log_id(applied_approval_id),
            )
        return applied_approval_id

    def _persist_approval_row(
        self, ctx: SessionContext, matched_actions: AllMatchedActions
    ) -> UUID:
        """Commits the row, register it for the drain, announce to the chat.

        Announce is best-effort: a miss degrades to the FE surfacing the card on
        the next `/live` refetch, so we don't fail the request.
        """
        actions_payload = [a.model_dump(mode="json") for a in matched_actions.actions]
        with get_session_with_tenant(tenant_id=ctx.tenant_id) as db:
            row = action_approval.insert_action_approval(
                db,
                session_id=ctx.session_id,
                actions=actions_payload,
                app_name=matched_actions.app_name,
                payload=matched_actions.payload,
                external_app_id=matched_actions.external_app_id,
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
                "approval_announce_error approval=%s error=%r approval_id=%s",
                short_log_id(approval_id),
                str(e),
                full_log_id(approval_id),
            )

        logger.info(
            "approval_requested tenant=%s sandbox=%s session=%s approval=%s "
            "app_name=%r external_app_id=%s action_type=%s action_count=%s "
            "proxy_instance=%s session_id=%s approval_id=%s",
            ctx.tenant_id,
            sandbox_log_label(ctx),
            short_log_id(ctx.session_id),
            short_log_id(approval_id),
            matched_actions.app_name,
            matched_actions.external_app_id,
            matched_actions.governing_action.action_type,
            len(matched_actions.actions),
            self._proxy_instance_id,
            full_log_id(ctx.session_id),
            full_log_id(approval_id),
        )

        try:
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
                approval_id, approval_cache.WAIT_TIMEOUT_S, cache
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
    ) -> InjectionOutcome:
        """Runs the credential dispatcher; Fails closed with a 403 on BLOCKED."""
        outcome = self._credential_dispatcher.apply(
            flow,
            InjectionContext(
                sandbox=sandbox,
                matched_actions=matched_actions,
            ),
        )
        if outcome is InjectionOutcome.BLOCKED:
            flow.response = http_403(SandboxProxyError.CREDENTIAL_ERROR)
        return outcome

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

    def _notify_approval_grant(
        self, ctx: SessionContext, grant: _ApprovalGrant
    ) -> None:
        """Best-effort bell entry for an auto-approved action.

        ``create_notification`` dedups on (user, type, additional_data), so the
        grant source must keep ``notification_data`` a stable per-scope key —
        anything per-request would defeat the dedup.
        """
        if (
            grant.notif_type is None
            or grant.notification_title is None
            or grant.notification_data is None
        ):
            return
        with get_session_with_tenant(tenant_id=ctx.tenant_id) as db:
            create_notification(
                user_id=ctx.user_id,
                notif_type=grant.notif_type,
                db_session=db,
                title=grant.notification_title,
                additional_data=grant.notification_data,
                autocommit=True,
            )

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
        """Resolves the originating session from the Proxy-Authorization tag.

        Returns None (caller fails closed) if the tag is absent, malformed, or
        doesn't resolve to one of this user's sessions. DB errors propagate to
        the caller, which also fails closed.
        """
        tag = self._extract_session_tag(flow)
        if tag is None:
            logger.warning(
                "session_missing tenant=%s sandbox=%s host=%s",
                sandbox.tenant_id,
                sandbox_log_label(sandbox),
                flow.request.host,
            )
            return None
        try:
            tagged_id = UUID(tag)
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
            "session_verified tenant=%s sandbox=%s session=%s host=%s",
            sandbox.tenant_id,
            sandbox_log_label(sandbox),
            short_log_id(exact),
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
            "session_tag_resolved conn=%s host=%s cached=%s direct=%s "
            "proxy_auth_present=%s session=%s",
            conn_id or "-",
            flow.request.host,
            short_log_id(cached),
            short_log_id(direct),
            str(direct_auth_header is not None).lower(),
            short_log_id(tag),
        )
        return tag


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
