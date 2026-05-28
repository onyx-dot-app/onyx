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

    def claims(self, host: str, ctx: InjectionContext) -> bool:  # noqa: ARG002
        # Host is irrelevant: the matcher has already proven this request
        # belongs to a connected app.
        return ctx.match is not None

    def resolve(self, request: http.Request, ctx: InjectionContext) -> dict[str, str]:
        match = ctx.match
        if match is None:
            # `claims` guarantees this is unreachable; runtime check so a
            # broken Protocol contract surfaces as a 403, not a NoneType crash.
            raise CredentialUnavailableError(
                "ExternalAppResolver invoked without an ActionMatch"
            )

        try:
            with ctx.db_session_factory(ctx.sandbox.tenant_id) as db:
                return resolve_injection_headers(
                    db, match.external_app_id, ctx.sandbox.user_id
                )
        except Exception as e:
            logger.exception(
                "external_app_resolver.error external_app_id=%s host=%s",
                match.external_app_id,
                request.host,
            )
            raise CredentialUnavailableError(
                f"external_app_id={match.external_app_id} resolution failed: "
                f"{type(e).__name__}"
            ) from e
