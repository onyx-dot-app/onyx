"""Host-claim dispatcher for sandbox-proxy credential injection.

`CredentialInjectionDispatcher` walks a registered list of `CredentialResolver`s
and asks each in turn whether it owns the request. The first one that claims
renders its auth headers; the dispatcher writes them onto `flow.request` so the
real secret never has to live in the sandbox pod. Resolution outcomes are
explicit (`PASS_THROUGH` / `INJECTED` / `BLOCKED`) and the dispatcher never
raises — fail-closed mapping to a 403 is the caller's job.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from mitmproxy import http

from onyx.external_apps.matching.engine import ActionMatch
from onyx.sandbox_proxy.identity import DBSessionFactory
from onyx.sandbox_proxy.identity import ResolvedSandbox
from onyx.utils.logger import setup_logger

logger = setup_logger()


class CredentialUnavailableError(Exception):
    """A resolver claimed a request but couldn't produce its credential."""


@dataclass(frozen=True)
class InjectionContext:
    """Per-request inputs every resolver receives.

    `match` is `None` on off-catalog forwards. `sandbox.tenant_id` is what
    resolvers key their per-tenant lookups by.
    """

    sandbox: ResolvedSandbox
    match: ActionMatch | None
    db_session_factory: DBSessionFactory


class CredentialResolver(Protocol):
    """One credential source: claims a request by host, then renders headers."""

    def claims(self, host: str, ctx: InjectionContext) -> bool:
        """Cheap, no-DB predicate: does this resolver own this request?"""
        ...

    def resolve(self, request: http.Request, ctx: InjectionContext) -> dict[str, str]:
        """Render auth headers; raise `CredentialUnavailableError` to fail closed."""
        ...


class InjectionOutcome(Enum):
    PASS_THROUGH = "pass_through"
    INJECTED = "injected"
    BLOCKED = "blocked"


class CredentialInjectionDispatcher:
    """First-claim-wins dispatch across a fixed list of resolvers."""

    def __init__(self, resolvers: list[CredentialResolver]) -> None:
        self._resolvers = list(resolvers)

    def apply(self, flow: http.HTTPFlow, ctx: InjectionContext) -> InjectionOutcome:
        host = flow.request.host
        resolver = self._pick(host, ctx)
        if resolver is None:
            return InjectionOutcome.PASS_THROUGH

        resolver_name = type(resolver).__name__
        try:
            headers = resolver.resolve(flow.request, ctx)
        except CredentialUnavailableError as e:
            logger.warning(
                "credential_injection.unavailable resolver=%s host=%s error=%s",
                resolver_name,
                host,
                str(e),
            )
            return InjectionOutcome.BLOCKED
        except Exception:
            logger.exception(
                "credential_injection.resolver_error resolver=%s host=%s",
                resolver_name,
                host,
            )
            return InjectionOutcome.BLOCKED

        for name, value in headers.items():
            flow.request.headers[name] = value
        # Header NAMES only — never log the injected secret values.
        logger.info(
            "credential_injection.applied resolver=%s host=%s headers=%s",
            resolver_name,
            host,
            sorted(headers),
        )
        return InjectionOutcome.INJECTED

    def _pick(self, host: str, ctx: InjectionContext) -> CredentialResolver | None:
        for resolver in self._resolvers:
            try:
                if resolver.claims(host, ctx):
                    return resolver
            except Exception:
                # One buggy resolver must not deny the others a chance.
                logger.exception(
                    "credential_injection.claims_error resolver=%s host=%s",
                    type(resolver).__name__,
                    host,
                )
        return None
