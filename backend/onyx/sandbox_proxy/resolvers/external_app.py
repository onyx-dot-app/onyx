"""External-app credential resolver.

Claims a request iff the matcher has attributed it to a connected `ExternalApp`
(`ctx.matched_actions is not None`) and renders the app's `auth_template` from the org +
per-user credentials via `resolve_injection_headers`. Per-header fail-open
behaviour for missing placeholders lives in `build_auth_headers`.
"""

from __future__ import annotations

from mitmproxy import http

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.external_apps.credentials import resolve_injection_headers
from onyx.external_apps.token_refresh import ensure_fresh_credentials
from onyx.sandbox_proxy.credential_injection import CredentialResolver
from onyx.sandbox_proxy.credential_injection import CredentialUnavailableError
from onyx.sandbox_proxy.credential_injection import InjectionContext
from onyx.utils.logger import setup_logger

logger = setup_logger()


class ExternalAppResolver(CredentialResolver):
    """`CredentialResolver` for matcher-attributed external-app requests."""

    def claims(
        self,
        request: http.Request,  # noqa: ARG002
        ctx: InjectionContext,
    ) -> bool:
        # The matcher has already proven URL→app attribution; host is unused.
        return ctx.matched_actions is not None

    def resolve(self, request: http.Request, ctx: InjectionContext) -> dict[str, str]:
        matched_actions = ctx.matched_actions
        if matched_actions is None:
            # `claims` guarantees this is unreachable; explicit raise so a
            # broken Protocol contract surfaces as a 403, not a NoneType crash.
            raise CredentialUnavailableError(
                "ExternalAppResolver invoked without a matched request"
            )

        # Lazily refresh an expired/expiring OAuth token before rendering, so the
        # injected `Bearer` is live. A no-op for fresh or non-OAuth credentials,
        # and single-flighted across the fleet via a Redis lock; it opens its own
        # short sessions and never raises for a refresh outcome (a dead grant
        # clears the credential, which renders as empty headers below).
        ensure_fresh_credentials(
            ctx.sandbox.tenant_id,
            matched_actions.external_app_id,
            ctx.sandbox.user_id,
        )

        with get_session_with_tenant(tenant_id=ctx.sandbox.tenant_id) as db:
            headers = resolve_injection_headers(
                db, matched_actions.external_app_id, ctx.sandbox.user_id
            )

        # Per-app debug line so `external_app_id` survives in logs even when
        # the dispatcher's credential logs group by resolver.
        # Empty `headers` means "app disabled / deleted / placeholders unfillable" —
        # the request still forwards (upstream 401 surfaces to the user).
        header_names = ",".join(sorted(headers)) or "-"
        logger.debug(
            "external_app_resolver.resolved external_app_id=%s host=%s "
            "header_count=%s header_names=%s",
            matched_actions.external_app_id,
            request.host,
            len(headers),
            header_names,
        )
        return headers
