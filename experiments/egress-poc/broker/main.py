"""Credential broker for the egress PoC.

The broker is the only component that reads the secrets/ directory. The proxy
calls POST /policy/evaluate with the parsed request, gets back a decision +
optional injected headers, and never sees the raw secret material.

Frozen contract — same shape will be used in V1, so don't drift:

    POST /policy/evaluate
    {
      "session_token": "...",
      "method":        "POST",
      "scheme":        "https",
      "host":          "api.allowed.example",
      "path":          "/v1/issues",
      "client_ip":     "...",
      "tenant_hint":   null
    }
    ->
    {
      "decision":          "allow" | "deny",
      "category":          "READ" | "WRITE" | "DELIVERY" | "DESTRUCTIVE" | "UNKNOWN",
      "service_slug":      "allowed" | null,
      "inject_headers":    {"Authorization": "Bearer ..."},
      "strip_headers":     ["Authorization", "Cookie", "X-API-Key"],
      "upstream_url":      "http://upstream:8000" | null,
      "cache_ttl_seconds": 30,
      "reason":            "matched_service" | "unregistered_default_deny" | ...
    }

Notes:
  - approve_required is not implemented in v0 (out of scope per plan).
  - upstream_url is a PoC-only addition: lets demos use mock hostnames
    (api.allowed.example) that the proxy routes to the upstream container.
    In V1 the proxy would resolve the host normally and this field would be
    unused (or used only by callers that want explicit pinning).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI
from pydantic import BaseModel
from pydantic import Field

SERVICES_PATH = Path(__file__).parent / "services.yaml"
SECRETS_DIR = Path(__file__).parent / "secrets"
EGRESS_DEFAULT_DENY = os.getenv("EGRESS_DEFAULT_DENY", "false").lower() == "true"
DEFAULT_CACHE_TTL = int(os.getenv("CACHE_TTL_SECONDS", "30"))
DEFAULT_DENY_CACHE_TTL = int(os.getenv("DENY_CACHE_TTL_SECONDS", "5"))


class EvaluateRequest(BaseModel):
    session_token: str
    method: str
    scheme: str
    host: str
    path: str
    client_ip: str | None = None
    tenant_hint: str | None = None


class EvaluateResponse(BaseModel):
    decision: str
    category: str
    service_slug: str | None
    inject_headers: dict[str, str] = Field(default_factory=dict)
    strip_headers: list[str] = Field(default_factory=list)
    upstream_url: str | None = None
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL
    reason: str


_registry: dict[str, Any] = {}


def _load_registry() -> dict[str, Any]:
    """Parse services.yaml into a host -> service dict + fallback config."""
    with SERVICES_PATH.open() as f:
        raw = yaml.safe_load(f) or {}
    by_host: dict[str, dict[str, Any]] = {}
    for svc in raw.get("services", []) or []:
        host = svc.get("host")
        if not host:
            continue
        by_host[host.lower()] = svc
    return {
        "by_host": by_host,
        "unregistered_upstream_url": raw.get("unregistered_upstream_url"),
    }


def _read_secret(name: str) -> str:
    path = SECRETS_DIR / name
    return path.read_text().strip()


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    global _registry
    _registry = _load_registry()
    yield


app = FastAPI(lifespan=_lifespan)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/policy/evaluate", response_model=None)
def evaluate(req: EvaluateRequest) -> EvaluateResponse:
    svc = _registry["by_host"].get(req.host.lower())

    # Unregistered host: deny if EGRESS_DEFAULT_DENY, else allow with no
    # credential injection (pass-through).
    if svc is None:
        if EGRESS_DEFAULT_DENY:
            return EvaluateResponse(
                decision="deny",
                category="UNKNOWN",
                service_slug=None,
                upstream_url=None,
                cache_ttl_seconds=DEFAULT_DENY_CACHE_TTL,
                reason="unregistered_default_deny",
            )
        return EvaluateResponse(
            decision="allow",
            category="UNKNOWN",
            service_slug=None,
            inject_headers={},
            strip_headers=[
                "Authorization",
                "Cookie",
                "X-API-Key",
                "Proxy-Authorization",
            ],
            upstream_url=_registry["unregistered_upstream_url"],
            cache_ttl_seconds=DEFAULT_CACHE_TTL,
            reason="unregistered_passthrough",
        )

    # Explicit deny rule.
    if svc.get("decision") == "deny":
        return EvaluateResponse(
            decision="deny",
            category="UNKNOWN",
            service_slug=svc.get("service_slug"),
            strip_headers=svc.get("strip_headers", []),
            upstream_url=None,
            cache_ttl_seconds=DEFAULT_DENY_CACHE_TTL,
            reason="explicit_deny",
        )

    # Registered service: classify, look up secret, build inject headers.
    classifications: dict[str, str] = svc.get("classifications", {}) or {}
    category = classifications.get(req.method.upper(), "UNKNOWN")

    inject_headers: dict[str, str] = {}
    secret_file = svc.get("secret_file")
    if secret_file:
        secret = _read_secret(secret_file)
        template = svc.get("inject_template", "{secret}")
        header_name = svc.get("inject_header", "Authorization")
        inject_headers[header_name] = template.format(secret=secret)

    return EvaluateResponse(
        decision="allow",
        category=category,
        service_slug=svc.get("service_slug"),
        inject_headers=inject_headers,
        strip_headers=svc.get("strip_headers", []),
        upstream_url=svc.get("upstream_url"),
        cache_ttl_seconds=DEFAULT_CACHE_TTL,
        reason="matched_service",
    )
