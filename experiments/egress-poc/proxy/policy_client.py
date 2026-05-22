"""Thin async client for the credential broker with positive + negative caches.

The proxy hot path is sync-ish (mitmproxy hooks), but async-aware. We use
httpx.AsyncClient and await from async hooks. On any broker error we fail
closed (deny).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from cachetools import TTLCache

log = logging.getLogger("egress-poc.proxy")

# Conservative defaults; the broker can request shorter TTLs via the
# cache_ttl_seconds field but we never extend beyond these ceilings.
_ALLOW_TTL_SECONDS = 30
_DENY_TTL_SECONDS = 5
_CACHE_MAX = 2048


class PolicyClient:
    def __init__(self, broker_url: str) -> None:
        self._broker_url = broker_url.rstrip("/")
        self._allow_cache: TTLCache[tuple[str, ...], dict[str, Any]] = TTLCache(
            maxsize=_CACHE_MAX, ttl=_ALLOW_TTL_SECONDS
        )
        self._deny_cache: TTLCache[tuple[str, ...], dict[str, Any]] = TTLCache(
            maxsize=_CACHE_MAX, ttl=_DENY_TTL_SECONDS
        )
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(2.0, connect=0.5))

    @staticmethod
    def _key(
        session_token: str, scheme: str, host: str, method: str, path: str
    ) -> tuple[str, ...]:
        # Path is canonicalized to first 8 segments to cache variant URLs
        # under the same policy while keeping distinct API surfaces apart.
        segments = path.split("/")[:9]
        return (session_token, scheme, host.lower(), method.upper(), "/".join(segments))

    async def evaluate(
        self,
        session_token: str,
        scheme: str,
        host: str,
        method: str,
        path: str,
        client_ip: str | None = None,
    ) -> dict[str, Any]:
        key = self._key(session_token, scheme, host, method, path)
        if (cached := self._allow_cache.get(key)) is not None:
            return cached
        if (cached := self._deny_cache.get(key)) is not None:
            return cached

        try:
            response = await self._client.post(
                f"{self._broker_url}/policy/evaluate",
                json={
                    "session_token": session_token,
                    "method": method,
                    "scheme": scheme,
                    "host": host,
                    "path": path,
                    "client_ip": client_ip,
                    "tenant_hint": None,
                },
            )
            response.raise_for_status()
            data: dict[str, Any] = response.json()
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as e:
            log.warning("broker call failed, failing closed: %r", e)
            return {
                "decision": "deny",
                "category": "UNKNOWN",
                "service_slug": None,
                "inject_headers": {},
                "strip_headers": [],
                "upstream_url": None,
                "cache_ttl_seconds": _DENY_TTL_SECONDS,
                "reason": f"broker_error: {type(e).__name__}",
            }

        if data.get("decision") == "deny":
            self._deny_cache[key] = data
        else:
            self._allow_cache[key] = data
        return data

    async def aclose(self) -> None:
        await self._client.aclose()
