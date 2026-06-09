"""Shared rendering helpers for sandbox proxy logs."""

from uuid import UUID

from mitmproxy import http

from onyx.db.enums import EndpointPolicy
from onyx.external_apps.matching.engine import AllMatchedActions
from onyx.sandbox_proxy.credential_injection import InjectionOutcome
from onyx.sandbox_proxy.identity import ResolvedSandbox
from onyx.sandbox_proxy.identity import SessionContext

LOG_ID_PREFIX_LEN = 8

EGRESS_TARGET_FIELDS = "tenant=%s sandbox=%s host=%s method=%s"
EGRESS_MATCHED_FIELDS = (
    EGRESS_TARGET_FIELDS + " app=%r external_app_id=%s action_type=%s policy=%s"
)
EGRESS_SESSION_MATCHED_FIELDS = (
    "tenant=%s sandbox=%s session=%s host=%s method=%s app=%r "
    "external_app_id=%s action_type=%s policy=%s"
)
EGRESS_APPROVAL_MATCHED_FIELDS = (
    "tenant=%s sandbox=%s session=%s approval=%s host=%s method=%s app=%r "
    "external_app_id=%s action_type=%s policy=%s"
)


def short_log_id(value: UUID | str | None) -> str:
    if value is None:
        return "-"
    text = str(value)
    try:
        return str(UUID(text))[:LOG_ID_PREFIX_LEN]
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
    if outcome is InjectionOutcome.INJECTED:
        return "headers_injected"
    return outcome.value


def _policy_label(policy: EndpointPolicy | str) -> str:
    return policy.value if isinstance(policy, EndpointPolicy) else policy


def egress_target_args(
    flow: http.HTTPFlow, sandbox: ResolvedSandbox | SessionContext
) -> tuple[object, ...]:
    return (
        sandbox.tenant_id,
        sandbox_log_label(sandbox),
        flow.request.host,
        flow.request.method,
    )


def egress_matched_args(
    flow: http.HTTPFlow,
    sandbox: ResolvedSandbox | SessionContext,
    matched_actions: AllMatchedActions,
    policy: EndpointPolicy | str,
) -> tuple[object, ...]:
    return (
        *egress_target_args(flow, sandbox),
        matched_actions.app_name,
        matched_actions.external_app_id,
        matched_actions.governing_action.action_type,
        _policy_label(policy),
    )


def egress_session_matched_args(
    flow: http.HTTPFlow,
    ctx: SessionContext,
    matched_actions: AllMatchedActions,
    policy: EndpointPolicy | str,
) -> tuple[object, ...]:
    return (
        ctx.tenant_id,
        sandbox_log_label(ctx),
        short_log_id(ctx.session_id),
        flow.request.host,
        flow.request.method,
        matched_actions.app_name,
        matched_actions.external_app_id,
        matched_actions.governing_action.action_type,
        _policy_label(policy),
    )


def egress_approval_matched_args(
    flow: http.HTTPFlow,
    ctx: SessionContext,
    matched_actions: AllMatchedActions,
    policy: EndpointPolicy | str,
    approval_id: UUID | None,
) -> tuple[object, ...]:
    return (
        ctx.tenant_id,
        sandbox_log_label(ctx),
        short_log_id(ctx.session_id),
        short_log_id(approval_id),
        flow.request.host,
        flow.request.method,
        matched_actions.app_name,
        matched_actions.external_app_id,
        matched_actions.governing_action.action_type,
        _policy_label(policy),
    )
