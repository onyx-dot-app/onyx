"""Shared rendering helpers for sandbox proxy logs."""

from uuid import UUID

from mitmproxy import http

from onyx.db.enums import EndpointPolicy
from onyx.external_apps.matching.engine import AllMatchedActions
from onyx.sandbox_proxy.credential_injection import InjectionOutcome
from onyx.sandbox_proxy.identity import ResolvedSandbox
from onyx.sandbox_proxy.identity import SessionContext

_EGRESS_CONTEXT_FIELDS = "tenant=%s sandbox=%s"
_EGRESS_SESSION_FIELDS = f"{_EGRESS_CONTEXT_FIELDS} session=%s"
_EGRESS_APPROVAL_FIELDS = f"{_EGRESS_SESSION_FIELDS} approval=%s"
_EGRESS_REQUEST_FIELDS = "host=%s method=%s"
_EGRESS_ACTION_FIELDS = "app_name=%r external_app_id=%s action_type=%s policy=%s"
APPROVAL_DECIDED_FIELDS = (
    f"{_EGRESS_APPROVAL_FIELDS} app_name=%r external_app_id=%s action_type=%s "
    "decision=%s wake=%s source=%s session_id=%s approval_id=%s"
)

EGRESS_TARGET_FIELDS = f"{_EGRESS_CONTEXT_FIELDS} {_EGRESS_REQUEST_FIELDS}"
EGRESS_MATCHED_FIELDS = f"{EGRESS_TARGET_FIELDS} {_EGRESS_ACTION_FIELDS}"
EGRESS_SESSION_MATCHED_FIELDS = (
    f"{_EGRESS_SESSION_FIELDS} {_EGRESS_REQUEST_FIELDS} {_EGRESS_ACTION_FIELDS}"
)
EGRESS_APPROVAL_MATCHED_FIELDS = (
    f"{_EGRESS_APPROVAL_FIELDS} {_EGRESS_REQUEST_FIELDS} {_EGRESS_ACTION_FIELDS}"
)


def short_log_id(value: UUID | str | None) -> str:
    if value is None:
        return "-"
    text = str(value)
    try:
        return str(UUID(text))[:8]
    except ValueError:
        return text


def full_log_id(value: UUID | str | None) -> str:
    if value is None:
        return "-"
    text = str(value)
    try:
        return str(UUID(text))
    except ValueError:
        return text


def sandbox_log_label(sandbox: ResolvedSandbox | SessionContext) -> str:
    return sandbox.sandbox_name or short_log_id(sandbox.sandbox_id)


def credential_outcome_label(outcome: InjectionOutcome) -> str:
    if outcome is InjectionOutcome.PASS_THROUGH:
        return "none"
    if outcome is InjectionOutcome.CLAIMED:
        return "claimed_no_headers"
    if outcome is InjectionOutcome.INJECTED:
        return "headers_injected"
    return outcome.value


def _policy_label(policy: EndpointPolicy | str) -> str:
    return policy.value if isinstance(policy, EndpointPolicy) else policy


def _egress_context_args(sandbox: ResolvedSandbox | SessionContext) -> tuple[str, str]:
    return sandbox.tenant_id, sandbox_log_label(sandbox)


def _egress_request_args(flow: http.HTTPFlow) -> tuple[str, str]:
    return flow.request.host, flow.request.method


def _egress_action_args(
    matched_actions: AllMatchedActions, policy: EndpointPolicy | str
) -> tuple[object, ...]:
    return (
        matched_actions.app_name,
        matched_actions.external_app_id,
        matched_actions.governing_action.action_type,
        _policy_label(policy),
    )


def egress_target_args(
    flow: http.HTTPFlow, sandbox: ResolvedSandbox | SessionContext
) -> tuple[object, ...]:
    return (
        *_egress_context_args(sandbox),
        *_egress_request_args(flow),
    )


def egress_matched_args(
    flow: http.HTTPFlow,
    sandbox: ResolvedSandbox | SessionContext,
    matched_actions: AllMatchedActions,
    policy: EndpointPolicy | str,
) -> tuple[object, ...]:
    return (
        *egress_target_args(flow, sandbox),
        *_egress_action_args(matched_actions, policy),
    )


def egress_session_matched_args(
    flow: http.HTTPFlow,
    ctx: SessionContext,
    matched_actions: AllMatchedActions,
    policy: EndpointPolicy | str,
) -> tuple[object, ...]:
    return (
        *_egress_context_args(ctx),
        short_log_id(ctx.session_id),
        *_egress_request_args(flow),
        *_egress_action_args(matched_actions, policy),
    )


def egress_approval_matched_args(
    flow: http.HTTPFlow,
    ctx: SessionContext,
    matched_actions: AllMatchedActions,
    policy: EndpointPolicy | str,
    approval_id: UUID,
) -> tuple[object, ...]:
    return (
        *_egress_context_args(ctx),
        short_log_id(ctx.session_id),
        short_log_id(approval_id),
        *_egress_request_args(flow),
        *_egress_action_args(matched_actions, policy),
    )


def approval_decided_args(
    ctx: SessionContext,
    approval_id: UUID,
    matched_actions: AllMatchedActions,
    *,
    decision: str,
    wake: str,
    source: str,
) -> tuple[object, ...]:
    return (
        *_egress_context_args(ctx),
        short_log_id(ctx.session_id),
        short_log_id(approval_id),
        matched_actions.app_name,
        matched_actions.external_app_id,
        matched_actions.governing_action.action_type,
        decision,
        wake,
        source,
        full_log_id(ctx.session_id),
        full_log_id(approval_id),
    )
