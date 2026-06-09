"""Host-claim dispatcher for sandbox-proxy credential injection.

`CredentialInjectionDispatcher` walks a registered list of `CredentialResolver`s
and asks each in turn whether it owns the request. The first one that claims
renders its auth headers; the dispatcher writes them onto `flow.request` so the
real secret never has to live in the sandbox pod. Resolution outcomes are
explicit (`PASS_THROUGH` / `CLAIMED` / `INJECTED` / `BLOCKED`) and the
dispatcher never raises.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from mitmproxy import http

from onyx.external_apps.matching.engine import AllMatchedActions
from onyx.sandbox_proxy.identity import ResolvedSandbox
from onyx.utils.logger import setup_logger

logger = setup_logger()


class CredentialUnavailableError(Exception):
    """A resolver claimed a request but couldn't produce its credential."""


@dataclass(frozen=True)
class InjectionContext:
    """Per-request inputs every resolver receives.

    `matched_actions` is the actions matched for this request (carrying
    `external_app_id`), or `None` on off-catalog forwards. `sandbox.tenant_id` is
    what resolvers key their per-tenant lookups by.
    """

    sandbox: ResolvedSandbox
    matched_actions: AllMatchedActions | None


class CredentialResolver(Protocol):
    """One credential source: claims a request, then renders headers."""

    def claims(self, request: http.Request, ctx: InjectionContext) -> bool:
        """Cheap predicate: does this resolver own this request?

        Implementations should key off `request.host` (and `ctx.matched_actions` /
        `ctx.sandbox.tenant_id` for per-context routing); they MUST NOT open
        a DB session — that's `resolve()`'s job.
        """
        ...

    def resolve(self, request: http.Request, ctx: InjectionContext) -> dict[str, str]:
        """Render auth headers; raise `CredentialUnavailableError` to fail closed."""
        ...


class InjectionOutcome(Enum):
    PASS_THROUGH = "pass_through"
    CLAIMED = "claimed"
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
                "credential_unavailable resolver=%s host=%s error=%r",
                resolver_name,
                host,
                str(e),
            )
            return InjectionOutcome.BLOCKED
        except Exception:
            logger.exception(
                "credential_resolver_error resolver=%s host=%s",
                resolver_name,
                host,
            )
            return InjectionOutcome.BLOCKED

        if not headers:
            logger.debug(
                "credential_claimed resolver=%s host=%s "
                "header_count=%s header_names=%s",
                resolver_name,
                host,
                0,
                "-",
            )
            return InjectionOutcome.CLAIMED

        for name, value in headers.items():
            flow.request.headers[name] = value
        # Header NAMES only — never log the injected secret values.
        logger.debug(
            "credential_injected resolver=%s host=%s header_count=%s header_names=%s",
            resolver_name,
            host,
            len(headers),
            ",".join(sorted(headers)),
        )
        return InjectionOutcome.INJECTED

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
                    "credential_claim_error resolver=%s host=%s",
                    type(resolver).__name__,
                    request.host,
                )
        return None
