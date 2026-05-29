"""Sandbox-facing 403 error codes and response builder.

Every 403 the proxy returns to the sandbox carries a stable `error` code that
the sandbox-side SDK / curl wrapper matches on. Keeping the codes and the
response shape in one place keeps the gate and the credential dispatcher
emitting the same contract.
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


def http_403(code: SandboxProxyError) -> http.Response:
    """Build a sandbox-visible 403 whose JSON body is `{"error": <code>}`."""
    body = json.dumps({"error": code.value}).encode()
    return http.Response.make(
        403,
        content=body,
        headers={"content-type": "application/json"},
    )
