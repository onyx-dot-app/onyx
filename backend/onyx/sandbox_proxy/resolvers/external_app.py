"""External-app credential resolver.

Claims a request iff the matcher has attributed it to a connected `ExternalApp`
(`ctx.match is not None`) and renders the app's `auth_template` from the org +
per-user credentials via `resolve_injection_headers`. Per-header fail-open
behaviour for missing placeholders lives in `build_auth_headers`.
"""

from __future__ import annotations

from mitmproxy import http

from onyx.external_apps.credentials import resolve_injection_headers
from onyx.sandbox_proxy.credential_injection import CredentialUnavailableError
from onyx.sandbox_proxy.credential_injection import InjectionContext
from onyx.utils.logger import setup_logger

logger = setup_logger()


class ExternalAppResolver:
    """`CredentialResolver` for matcher-attributed external-app requests."""

    def claims(
        self,
        request: http.Request,  # noqa: ARG002
        ctx: InjectionContext,
    ) -> bool:
        # The matcher has already proven URL→app attribution; host is unused.
        return ctx.match is not None

    def resolve(self, request: http.Request, ctx: InjectionContext) -> dict[str, str]:
        match = ctx.match
        if match is None:
            # `claims` guarantees this is unreachable; explicit raise so a
            # broken Protocol contract surfaces as a 403, not a NoneType crash.
            raise CredentialUnavailableError(
                "ExternalAppResolver invoked without an ActionMatch"
            )

        with ctx.db_session_factory(ctx.sandbox.tenant_id) as db:
            headers = resolve_injection_headers(
                db, match.external_app_id, ctx.sandbox.user_id
            )

        # Per-app audit line so `external_app_id` survives in logs even when
        # the dispatcher's `credential_injection.applied` log groups by resolver.
        # Empty `headers` means "app disabled / deleted / placeholders unfillable" —
        # the request still forwards (upstream 401 surfaces to the user).
        logger.info(
            "external_app_resolver.resolved external_app_id=%s host=%s headers=%s",
            match.external_app_id,
            request.host,
            sorted(headers),
        )
        return headers
