"""Sandbox-facing 403 error codes and response builder.

Every 403 the proxy returns to the sandbox carries a stable `error` code plus a
human-readable `message`. The agent running in the sandbox reads the `message`
to understand what happened and what to do next; tooling and dashboards match on
the stable `error` code. Keeping the codes, their prose, and the response shape
in one place keeps the gate and the credential dispatcher emitting the same
contract.
"""

from __future__ import annotations

import json
from enum import Enum

from mitmproxy import http


class SandboxProxyError(str, Enum):
    """Stable `error` codes returned to the sandbox in a 403 body."""

    UNIDENTIFIED_SANDBOX = "unidentified_sandbox"
    NO_ACTIVE_SESSION = "no_active_session"
    BODY_TOO_LARGE = "body_too_large"
    USER_REJECTED = "user_rejected"
    NOT_AUTHORIZED = "not_authorized"
    INTERNAL_ERROR = "internal_error"
    POLICY_DENIED = "policy_denied"
    CREDENTIAL_ERROR = "credential_error"
    DESTINATION_BLOCKED = "destination_blocked"

    @property
    def message(self) -> str:
        """Prose explaining what happened and the recommended next step.

        Addressed to the agent in the sandbox that receives the 403.
        """
        return _SANDBOX_ERROR_MESSAGES[self]


_SANDBOX_ERROR_MESSAGES: dict[SandboxProxyError, str] = {
    SandboxProxyError.UNIDENTIFIED_SANDBOX: (
        "The proxy could not identify which workspace this request came from, so "
        "it was blocked before reaching the network. This is an internal setup "
        "issue, not a problem with the request itself — changing the request "
        "will not help. Retry once; if it keeps failing, report that outbound "
        "requests are currently failing and stop attempting this call."
    ),
    SandboxProxyError.NO_ACTIVE_SESSION: (
        "This request needs to be tied to an active Craft session for approval, "
        "but no such session could be found, so it was blocked. This usually "
        "means the session ended or the request was made outside of a Craft "
        "session. Retrying the same request will not help — tell the user the "
        "action could not be authorized and ask how they want to proceed."
    ),
    SandboxProxyError.BODY_TOO_LARGE: (
        "The request body is larger than the size limit the proxy allows, so it "
        "was blocked. Shrink the payload and try again — for example, send fewer "
        "items per request, paginate, or break the work into smaller calls. "
        "Large file uploads should go through a dedicated upload flow rather "
        "than an inline request body."
    ),
    SandboxProxyError.USER_REJECTED: (
        "The user reviewed this action and chose to reject it, so it was not "
        "performed. Do not retry the same request — the rejection is "
        "intentional. Stop, tell the user the action was declined, and ask how "
        "they would like to continue or whether to take a different approach."
    ),
    SandboxProxyError.NOT_AUTHORIZED: (
        "This action required the user's approval, but no response came back in "
        "time and the request expired, so it was not performed. The user may "
        "have been away from the screen. You may retry once to prompt them "
        "again; if it keeps expiring, pause and let the user know this action is "
        "waiting on their approval."
    ),
    SandboxProxyError.INTERNAL_ERROR: (
        "The proxy hit an unexpected error while handling this request and "
        "blocked it as a precaution. This is not a problem with the request "
        "itself. Retry once; if it keeps failing, report that the action could "
        "not be completed due to an internal error and stop retrying."
    ),
    SandboxProxyError.POLICY_DENIED: (
        "This request targets an integration that the workspace administrator "
        "has set to always deny, so it was blocked by policy. Retrying will not "
        "help and the policy cannot be overridden from here. Tell the user this "
        "integration is disabled by policy and look for an approach that does "
        "not depend on it."
    ),
    SandboxProxyError.CREDENTIAL_ERROR: (
        "The proxy could not obtain the credentials needed to authenticate this "
        "request, so it was blocked. The integration is likely not connected, or "
        "its saved credentials have expired or been revoked. Ask the user to "
        "connect or reconnect this integration in their Craft settings, then "
        "retry."
    ),
    SandboxProxyError.DESTINATION_BLOCKED: (
        "This request targets an internal network address that sandboxes are not "
        "allowed to reach, so it was blocked before any connection was made. Only "
        "the public internet and the Onyx API server are reachable from here. "
        "This is a fixed security boundary, not a transient error — do not retry "
        "against internal hosts (databases, caches, metadata endpoints, etc.)."
    ),
}


def http_403(code: SandboxProxyError) -> http.Response:
    """Build a sandbox-visible 403.

    The JSON body is `{"error": <code>, "message": <prose>}`: the stable `error`
    code for tooling to match on, and human-readable `message` prose the agent
    can act on.
    """
    body = json.dumps({"error": code.value, "message": code.message}).encode()
    return http.Response.make(
        403,
        content=body,
        headers={"content-type": "application/json"},
    )
