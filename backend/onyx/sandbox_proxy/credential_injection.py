"""Host-claim dispatcher for sandbox-proxy credential injection.

`CredentialInjectionDispatcher` walks a registered list of `CredentialResolver`s
and asks each in turn whether it owns the request. The first one that claims
renders its auth headers; the dispatcher writes them onto `flow.request` so the
real secret never has to live in the sandbox pod. Resolution outcomes are
explicit (`PASS_THROUGH` / `INJECTED` / `BLOCKED`) and the dispatcher never
raises. The high-level `apply_or_block(flow, ctx)` does both the dispatch and
the fail-closed 403 in one call; tests use `apply(flow, ctx)` when they want
to inspect the outcome directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from mitmproxy import http

from onyx.external_apps.matching.engine import RequestMatch
from onyx.sandbox_proxy.errors import http_403
from onyx.sandbox_proxy.errors import SandboxProxyError
from onyx.sandbox_proxy.identity import ResolvedSandbox
from onyx.utils.logger import setup_logger

logger = setup_logger()


class CredentialUnavailableError(Exception):
    """A resolver claimed a request but couldn't produce its credential."""


@dataclass(frozen=True)
class InjectionContext:
    """Per-request inputs every resolver receives.

    `match` is the request-level match (carrying `external_app_id`), or
    `None` on off-catalog forwards. `sandbox.tenant_id` is what resolvers
    key their per-tenant lookups by.
    """

    sandbox: ResolvedSandbox
    match: RequestMatch | None


class CredentialResolver(Protocol):
    """One credential source: claims a request, then renders headers."""

    def claims(self, request: http.Request, ctx: InjectionContext) -> bool:
        """Cheap predicate: does this resolver own this request?

        Implementations should key off `request.host` (and `ctx.match` /
        `ctx.sandbox.tenant_id` for per-context routing); they MUST NOT open
        a DB session — that's `resolve()`'s job.
        """
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
        resolver = self._pick(flow.request, ctx)
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

    def apply_or_block(self, flow: http.HTTPFlow, ctx: InjectionContext) -> None:
        """Run `apply`; on `BLOCKED`, write a sandbox-visible 403 to `flow`.

        The single seam most call sites want — they don't need to inspect the
        outcome, just to fail closed on it. Tests that need to assert on the
        outcome directly call `apply` instead.
        """
        if self.apply(flow, ctx) is InjectionOutcome.BLOCKED:
            flow.response = http_403(SandboxProxyError.CREDENTIAL_ERROR)

    def _pick(
        self, request: http.Request, ctx: InjectionContext
    ) -> CredentialResolver | None:
        for resolver in self._resolvers:
            try:
                if resolver.claims(request, ctx):
                    return resolver
            except Exception:
                # One buggy resolver must not deny the others a chance.
                logger.exception(
                    "credential_injection.claims_error resolver=%s host=%s",
                    type(resolver).__name__,
                    request.host,
                )
        return None
