"""Classify an intercepted HTTPS request into a gated action.

The gate addon depends only on `ActionMatcher`; the v0
implementation here covers Slack's `chat.postMessage`. A broader
matcher registry will replace it later.

`None` return and matcher exceptions are both treated as "not
gated" by the gate addon — the real security boundary is the proxy's
iptables egress lockdown, not this heuristic.
"""

import json
from dataclasses import dataclass
from typing import Any
from typing import Protocol
from urllib.parse import parse_qs

from mitmproxy import http

ACTION_TYPE_SLACK_POST_MESSAGE = "slack.post_message"


@dataclass(frozen=True)
class ActionMatch:
    """Successful classification of a gated request."""

    action_type: str
    payload: dict[str, Any]


class ActionMatcher(Protocol):
    def match(self, request: http.Request) -> ActionMatch | None: ...


class SlackPostMessageMatcher:
    """Matches Slack Web API `chat.postMessage` requests.

    Accepts `application/json` and `application/x-www-form-urlencoded`
    bodies (the two encodings the official SDKs use). Host match is
    suffix-based so subdomains (e.g. `foo.slack.com`) and trailing
    dots are caught.
    """

    _SLACK_HOST = "slack.com"
    _POST_MESSAGE_PATH = "/api/chat.postmessage"

    def match(self, request: http.Request) -> ActionMatch | None:
        if not self._is_slack_host(request.host or ""):
            return None
        if (request.method or "").upper() != "POST":
            return None
        path_lower = (request.path or "").lower()
        if not path_lower.startswith(self._POST_MESSAGE_PATH):
            return None

        body = request.raw_content or b""
        content_type = (request.headers.get("content-type") or "").lower()

        # URL + method already identify this as a Slack send; gate it
        # even if the body fails to decode (an unparseable body is
        # Slack's problem to reject, not a bypass).
        payload = self._decode_body(body, content_type) or {}
        return ActionMatch(
            action_type=ACTION_TYPE_SLACK_POST_MESSAGE,
            payload=payload,
        )

    @classmethod
    def _is_slack_host(cls, host: str) -> bool:
        host = host.lower().rstrip(".")
        return host == cls._SLACK_HOST or host.endswith("." + cls._SLACK_HOST)

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
            # Collapse parse_qs's list-per-key to match the JSON shape.
            return {
                key: (values[0] if len(values) == 1 else values)
                for key, values in raw.items()
            }

        return None
