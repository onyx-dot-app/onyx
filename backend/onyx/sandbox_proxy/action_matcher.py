"""Classify an intercepted HTTPS request into a gated action.

The gate addon depends only on the ``ActionMatcher`` Protocol; alternate
implementations (e.g. a per-provider parser registry) can be dropped in
without touching the gate.

The default v0 implementation, ``SlackSendMessageMatcher``, hardcodes a
single action — Slack ``chat.postMessage``. It's deliberately small
enough to delete and replace once a broader registry is ready.

The matcher is a heuristic over arbitrary HTTPS bodies. ``None`` return
means "not gated" and the gate forwards unchanged. Exceptions raised
out of ``match`` are also treated as fail-open (logged but not gated) —
the gate addon's docstring explains the rationale; the real security
boundary is the proxy's iptables egress lockdown, not classification.
"""

import json
from dataclasses import dataclass
from typing import Any
from typing import Protocol
from urllib.parse import parse_qs

from mitmproxy import http

ACTION_TYPE_SLACK_SEND_MESSAGE = "slack.send_message"


@dataclass(frozen=True)
class ActionMatch:
    """Successful classification of a gated request."""

    action_type: str
    payload: dict[str, Any]


class ActionMatcher(Protocol):
    """Single-method seam used by the gate addon.

    Implementations must return ``None`` for non-gated traffic and
    must not raise for "this isn't my action type" — only for genuine
    parse errors. Either way the gate falls open."""

    def match(self, request: http.Request) -> ActionMatch | None: ...


class SlackSendMessageMatcher:
    """Matches Slack Web API ``chat.postMessage`` requests.

    Slack's Web API accepts both ``application/json`` and
    ``application/x-www-form-urlencoded`` for this method, so both body
    encodings are decoded — catches the official SDKs and direct curl
    invocations.

    Bypass-hardening: host suffix match (so ``slack.com.`` and
    subdomains like ``foo.slack.com`` are caught), case-insensitive path
    prefix, and required ``POST`` method. Other Slack API methods
    (chat.postEphemeral, files.upload, etc.) are not gated here — they
    will be picked up by the broader matcher registry when it lands.
    """

    _SLACK_HOST_SUFFIX = "slack.com"
    _METHOD_PATH = "/api/chat.postmessage"

    def match(self, request: http.Request) -> ActionMatch | None:
        if not self._is_slack_host(request.host or ""):
            return None
        if (request.method or "").upper() != "POST":
            return None
        path_lower = (request.path or "").lower()
        if not path_lower.startswith(self._METHOD_PATH):
            return None

        body = request.raw_content or b""
        content_type = (request.headers.get("content-type") or "").lower()

        payload = self._decode_body(body, content_type)
        if payload is None:
            return None

        return ActionMatch(
            action_type=ACTION_TYPE_SLACK_SEND_MESSAGE,
            payload=payload,
        )

    @classmethod
    def _is_slack_host(cls, host: str) -> bool:
        host = host.lower().rstrip(".")
        return host == cls._SLACK_HOST_SUFFIX or host.endswith(
            "." + cls._SLACK_HOST_SUFFIX
        )

    @staticmethod
    def _decode_body(body: bytes, content_type: str) -> dict[str, Any] | None:
        if "application/json" in content_type:
            try:
                decoded = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return None
            if not isinstance(decoded, dict):
                return None
            return decoded

        if "application/x-www-form-urlencoded" in content_type:
            try:
                raw = parse_qs(body.decode("utf-8"))
            except UnicodeDecodeError:
                return None
            # parse_qs returns lists per key; collapse single-element
            # lists so the payload looks like the JSON shape.
            return {
                key: (values[0] if len(values) == 1 else values)
                for key, values in raw.items()
            }

        return None
