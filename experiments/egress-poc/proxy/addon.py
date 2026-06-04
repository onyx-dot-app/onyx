"""Composed mitmproxy addon implementing the seven egress-pipeline steps:

  1. tls_clienthello — SNI validation, fail-closed on missing/invalid SNI
  2. http_connect    — Proxy-Authorization for CONNECT in explicit mode
  3. request         — host validation, authn (plain HTTP), policy, inject
  4. response        — audit-trail close

Audit events are emitted as one JSON object per line on stdout.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from typing import Any
from urllib.parse import urlparse

from authn import is_valid_session_token
from authn import parse_proxy_authorization

# mitmproxy is installed in the proxy container's venv only.
from mitmproxy import http  # ty: ignore[unresolved-import]
from mitmproxy import tls as mtls  # ty: ignore[unresolved-import]
from policy_client import PolicyClient
from validators import canonicalize_host
from validators import InvalidHost

log = logging.getLogger("egress-poc.proxy")

BROKER_URL = os.getenv("BROKER_URL", "http://broker:8000")
TRANSPARENT_DEFAULT_TOKEN = os.getenv(
    "TRANSPARENT_DEFAULT_TOKEN", "transparent-default"
)


def _audit(event: str, **fields: Any) -> None:
    payload = {"event": event, "ts": round(time.time(), 6), **fields}
    print(json.dumps(payload, default=str), flush=True)


class EgressAddon:
    """One addon, six pipeline steps, ~250 LOC."""

    def __init__(self) -> None:
        self._policy = PolicyClient(BROKER_URL)
        # session_token bound to an authenticated client_conn (set on CONNECT,
        # consumed by subsequent inner requests within the same TLS tunnel).
        self._authenticated_clients: dict[int, str] = {}

    # ---- mitmproxy hooks ----

    def tls_clienthello(self, data: mtls.ClientHelloData) -> None:
        sni = data.client_hello.sni
        if not sni:
            _audit(
                "denied",
                reason="no_sni",
                peer=str(data.context.client.peername),
            )
            data.ignore_connection = True
            return
        try:
            canonicalize_host(sni)
        except InvalidHost as e:
            _audit(
                "denied",
                reason="invalid_sni",
                sni=sni,
                detail=str(e),
                peer=str(data.context.client.peername),
            )
            data.ignore_connection = True

    def http_connect(self, flow: http.HTTPFlow) -> None:
        """Authenticate the explicit-mode CONNECT request.

        Fires only in regular-proxy mode. Transparent mode doesn't issue a
        CONNECT through mitmproxy.
        """
        header = flow.request.headers.get("Proxy-Authorization")
        _user, token = parse_proxy_authorization(header)
        if not is_valid_session_token(token):
            _audit(
                "denied",
                reason="bad_session_token",
                stage="http_connect",
                host=flow.request.pretty_host,
            )
            flow.response = http.Response.make(
                407,
                b"proxy authentication required\n",
                {
                    "Proxy-Authenticate": 'Basic realm="onyx-egress-poc"',
                    "X-Egress-Deny-Reason": "bad_session_token",
                },
            )
            return
        # Bind the authenticated token to this client connection so subsequent
        # in-tunnel requests don't need to re-present Proxy-Authorization.
        assert token is not None
        self._authenticated_clients[id(flow.client_conn)] = token
        _audit(
            "authenticated",
            stage="http_connect",
            host=flow.request.pretty_host,
            session_token_present=True,
        )

    async def request(self, flow: http.HTTPFlow) -> None:
        request_id = uuid.uuid4().hex
        flow.metadata["request_id"] = request_id

        host_raw = flow.request.pretty_host
        method = flow.request.method
        path = flow.request.path
        scheme = flow.request.scheme
        peer = flow.client_conn.peername
        client_ip = peer[0] if peer else None

        # Detect mode from connection history, not from the local socket
        # port. We can't trust sockname[1] for this: mitmproxy's transparent
        # mode overwrites client.sockname with the original (pre-DNAT)
        # destination, so e.g. an HTTPS transparent connection has
        # sockname[1] == 443, not 8443.
        #
        # Signals:
        #   - had_connect: this client_conn was authenticated via CONNECT
        #     earlier in the lifecycle. Only happens on the regular listener
        #     (8444), so this implies explicit mode with a tunneled TLS req.
        #   - has_proxy_auth_header: the request itself carries
        #     Proxy-Authorization. Only happens for plain-HTTP-via-explicit
        #     (curl -x http://...), which doesn't issue a CONNECT.
        #   - otherwise: transparent.
        had_connect_authn = id(flow.client_conn) in self._authenticated_clients
        proxy_auth_header = flow.request.headers.get("Proxy-Authorization")
        transparent = not had_connect_authn and not proxy_auth_header

        # 1. Host validation (parser-differential defense).
        try:
            host = canonicalize_host(host_raw)
        except InvalidHost as e:
            _audit(
                "denied",
                request_id=request_id,
                reason="invalid_host",
                host=host_raw,
                detail=str(e),
            )
            flow.response = http.Response.make(
                400,
                b"invalid host\n",
                {"X-Egress-Deny-Reason": "invalid_host"},
            )
            return

        # 2. Authentication.
        if transparent:
            session_token = TRANSPARENT_DEFAULT_TOKEN
        elif had_connect_authn:
            session_token = self._authenticated_clients[id(flow.client_conn)]
        else:
            # Plain HTTP through the explicit proxy (no CONNECT): the
            # Proxy-Authorization header is on this request directly.
            _user, parsed_token = parse_proxy_authorization(proxy_auth_header)
            if not is_valid_session_token(parsed_token):
                _audit(
                    "denied",
                    request_id=request_id,
                    reason="bad_session_token",
                    stage="request",
                    host=host,
                )
                flow.response = http.Response.make(
                    407,
                    b"proxy authentication required\n",
                    {
                        "Proxy-Authenticate": 'Basic realm="onyx-egress-poc"',
                        "X-Egress-Deny-Reason": "bad_session_token",
                    },
                )
                return
            assert parsed_token is not None
            session_token = parsed_token

        # Strip the proxy header before it ever reaches the upstream.
        flow.request.headers.pop("Proxy-Authorization", None)

        _audit(
            "received",
            request_id=request_id,
            host=host,
            method=method,
            path=path,
            scheme=scheme,
            client_ip=client_ip,
            transparent=transparent,
        )

        # 3. Policy.
        decision = await self._policy.evaluate(
            session_token=session_token,
            scheme=scheme,
            host=host,
            method=method,
            path=path,
            client_ip=client_ip,
        )
        _audit(
            "policy_decision",
            request_id=request_id,
            host=host,
            decision=decision["decision"],
            category=decision["category"],
            service_slug=decision.get("service_slug"),
            reason=decision.get("reason"),
        )

        if decision["decision"] == "deny":
            flow.response = http.Response.make(
                403,
                b"host not allowed\n",
                {"X-Egress-Deny-Reason": decision.get("reason", "deny")},
            )
            return

        # 4. Header strip + inject (strip first, ALWAYS, then merge).
        for name in decision.get("strip_headers", []) or []:
            flow.request.headers.pop(name, None)
        for name, value in (decision.get("inject_headers", {}) or {}).items():
            flow.request.headers[name] = value
            _audit("injected", request_id=request_id, header=name)

        # 5. Upstream override (PoC: routes mock hostnames to upstream:8000).
        upstream_url = decision.get("upstream_url")
        if upstream_url:
            up = urlparse(upstream_url)
            original_host_header = flow.request.headers.get("Host", host)
            new_scheme = up.scheme or "http"
            new_host = up.hostname or host
            new_port = up.port or (443 if new_scheme == "https" else 80)
            flow.request.scheme = new_scheme
            flow.request.host = new_host
            flow.request.port = new_port
            # Preserve the Host header so the mock upstream observes the
            # client's intended hostname, not "upstream".
            flow.request.headers["Host"] = original_host_header
            _audit(
                "upstream_override",
                request_id=request_id,
                original_host=host,
                upstream_host=new_host,
                upstream_port=new_port,
            )

        _audit("forwarded", request_id=request_id, host=host, method=method, path=path)

    def response(self, flow: http.HTTPFlow) -> None:
        request_id = flow.metadata.get("request_id")
        if not request_id:
            return
        status = flow.response.status_code if flow.response else None
        _audit(
            "responded",
            request_id=request_id,
            status=status,
            host=flow.request.pretty_host,
        )

    def error(self, flow: http.HTTPFlow) -> None:
        request_id = flow.metadata.get("request_id") if flow.metadata else None
        msg = flow.error.msg if flow.error else "unknown"
        _audit("error", request_id=request_id, msg=msg)

    def client_disconnected(self, client) -> None:
        # Drop authn binding when the TCP connection goes away.
        self._authenticated_clients.pop(id(client), None)
