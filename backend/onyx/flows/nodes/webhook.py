"""Webhook node: POST a payload to an outside system.

The HTTP node can already send a POST. What it cannot do is prove the delivery
came from here, and that is the whole difference: this node signs the body it
sends so the receiver can tell a real delivery from anything else that found
the URL.

The scheme is the ordinary one. The signed string is the timestamp, a dot, and
the exact bytes of the body; the signature is HMAC-SHA256 of that under the
flow's signing secret, in hex. Signing the timestamp too is what stops a
captured delivery being replayed later — a receiver rejects anything older
than its own tolerance.

To verify::

    signed = f"{headers['X-Onyx-Timestamp']}.{raw_body}"
    expected = hmac.new(secret, signed.encode(), hashlib.sha256).hexdigest()
    hmac.compare_digest(expected, headers["X-Onyx-Signature"])
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import httpx

from onyx.db.enums import FlowErrorClass
from onyx.flows.expressions import (
    ExpressionError,
    RunContext,
    render_text,
    resolve_structure,
)
from onyx.flows.models import WebhookNode
from onyx.flows.nodes.base import NodeExecutionError, NodeOutcome, NodeRuntime
from onyx.flows.nodes.http import KEPT_RESPONSE_HEADERS
from onyx.utils.logger import setup_logger
from onyx.utils.url import SSRFException

logger = setup_logger()

SIGNATURE_HEADER = "X-Onyx-Signature"
TIMESTAMP_HEADER = "X-Onyx-Timestamp"

# Enough of the receiver's reply to tell a rejection from an acceptance,
# without turning the run history into a log of other people's HTML.
MAX_RESPONSE_PREVIEW_CHARS = 500


def execute_webhook(
    node: WebhookNode, context: RunContext, runtime: NodeRuntime
) -> NodeOutcome:
    """Build the delivery, sign it, send it, and report what came back."""
    try:
        url = render_text(node.url, context)
        headers = {
            render_text(name, context): render_text(value, context)
            for name, value in node.headers.items()
        }
        payload = resolve_structure(node.payload, context)
    except ExpressionError as exc:
        raise NodeExecutionError(FlowErrorClass.EXPRESSION_ERROR, str(exc)) from exc

    # Serialised once and sent verbatim. The receiver verifies the bytes it
    # was given, so re-encoding anywhere between here and the socket would
    # invalidate a signature that is otherwise correct.
    body = json.dumps(payload if payload is not None else {}, default=str)
    timestamp = int(time.time())

    headers["Content-Type"] = "application/json"
    headers[TIMESTAMP_HEADER] = str(timestamp)
    signed = runtime.webhook_signing_secret is not None
    if signed:
        headers[SIGNATURE_HEADER] = sign_payload(
            runtime.webhook_signing_secret or "", timestamp, body
        )
    else:
        logger.warning(
            "flow webhook node has no signing secret, sending unsigned node=%s",
            node.id,
        )

    try:
        response = runtime.http_client.post(
            url,
            content=body.encode(),
            headers=headers,
            timeout=httpx.Timeout(node.timeout_seconds),
        )
    except SSRFException as exc:
        raise NodeExecutionError(
            FlowErrorClass.HTTP_ERROR, f"blocked by SSRF policy: {exc}"
        ) from exc
    except httpx.TimeoutException as exc:
        raise NodeExecutionError(
            FlowErrorClass.TIMEOUT,
            f"POST {url} timed out after {node.timeout_seconds}s",
        ) from exc
    except httpx.HTTPError as exc:
        raise NodeExecutionError(
            FlowErrorClass.HTTP_ERROR, f"POST {url} failed: {exc}"
        ) from exc

    delivered = response.status_code < 400
    if node.fail_on_error_status and not delivered:
        raise NodeExecutionError(
            FlowErrorClass.HTTP_ERROR,
            f"POST {url} returned {response.status_code}: {_preview(response)}",
        )

    if not delivered:
        # Default behaviour: note it and carry on. A receiver being down is
        # their outage, not a reason to stop an automation that has already
        # done its work.
        logger.warning(
            "flow webhook was not accepted node=%s status=%d",
            node.id,
            response.status_code,
        )

    return NodeOutcome(
        output={
            "delivered": delivered,
            "signed": signed,
            "status": response.status_code,
            "headers": {
                name: value
                for name, value in response.headers.items()
                if name.lower() in KEPT_RESPONSE_HEADERS
            },
            "response": _preview(response),
        }
    )


def sign_payload(secret: str, timestamp: int, body: str) -> str:
    """The signature a receiver recomputes to check a delivery."""
    signed = f"{timestamp}.{body}".encode()
    return hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()


def _preview(response: httpx.Response) -> str:
    text = response.text
    if len(text) <= MAX_RESPONSE_PREVIEW_CHARS:
        return text
    return text[:MAX_RESPONSE_PREVIEW_CHARS] + "…"
