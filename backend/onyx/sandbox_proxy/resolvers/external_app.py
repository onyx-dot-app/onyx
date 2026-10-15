"""External-app credential resolver.

Claims a request iff the matcher has attributed it to a connected `ExternalApp`
(`ctx.matched_actions is not None`) and renders the app's `auth_template` from the org +
per-user credentials via `resolve_injection_headers`. Per-header fail-open
behaviour for missing placeholders lives in `build_auth_headers`.
"""

from __future__ import annotations

from mitmproxy import http

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.enums import GatedAppKind
from onyx.db.external_app import get_external_app_by_id, get_external_apps
from onyx.db.models import ExternalApp
from onyx.external_apps.credentials import (
    ExternalAppCredentialsError,
    app_is_available,
    resolve_injection_headers,
)
from onyx.external_apps.matching.engine import (
    AmbiguousExternalAppTargetError,
    resolve_app_for_url,
)
from onyx.external_apps.token_refresh import ensure_fresh_credentials
from onyx.sandbox_proxy.credential_injection import (
    CredentialResolver,
    CredentialUnavailableError,
)
from onyx.sandbox_proxy.models import InjectionContext
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _openapi_auth_identity(
    app: ExternalApp | None,
) -> tuple[int, int | None, bool] | None:
    tool = app.openapi_tool if app is not None else None
    if tool is None:
        return None
    return tool.id, tool.oauth_config_id, tool.passthrough_auth


class ExternalAppResolver(CredentialResolver):
    """`CredentialResolver` for matcher-attributed external-app requests."""

    def claims(
        self,
        request: http.Request,  # noqa: ARG002
        ctx: InjectionContext,
    ) -> bool:
        # The matcher has already proven URL→app attribution; host is unused. An
        # MCP-server target is another resolver's — external app only here.
        actions = ctx.matched_actions
        return actions is not None and actions.target.kind is GatedAppKind.EXTERNAL_APP

    def resolve(self, request: http.Request, ctx: InjectionContext) -> dict[str, str]:
        matched_actions = ctx.matched_actions
        if (
            matched_actions is None
            or matched_actions.target.kind is not GatedAppKind.EXTERNAL_APP
        ):
            # `claims` guarantees this is unreachable; explicit raise so a
            # broken Protocol contract surfaces as a 403, not a NoneType crash.
            raise CredentialUnavailableError(
                "ExternalAppResolver invoked without an external-app request"
            )
        external_app_id = matched_actions.target.id

        # Lazily refresh an expired/expiring OAuth token before rendering, so the
        # injected `Bearer` is live. A no-op for fresh or non-OAuth credentials,
        # and single-flighted across the fleet via a Redis lock; it opens its own
        # short sessions and never raises for a refresh outcome (a dead grant
        # clears the credential, which renders as empty headers below).
        ensure_fresh_credentials(
            ctx.sandbox.tenant_id,
            external_app_id,
            ctx.sandbox.user_id,
        )

        with get_session_with_tenant(tenant_id=ctx.sandbox.tenant_id) as db:
            auth_identity = _openapi_auth_identity(
                get_external_app_by_id(db, external_app_id)
            )
            try:
                headers = resolve_injection_headers(
                    db, external_app_id, ctx.sandbox.user_id
                )
            except ExternalAppCredentialsError as error:
                raise CredentialUnavailableError(
                    str(error), sandbox_detail=str(error)
                ) from error

        # OAuth refresh can wait on a remote server. Recheck ownership afterward
        # in a fresh session so cached ORM rows cannot retain an obsolete scope.
        with get_session_with_tenant(tenant_id=ctx.sandbox.tenant_id) as db:
            try:
                app = resolve_app_for_url(
                    request.url, get_external_apps(db, enabled_only=True)
                )
            except AmbiguousExternalAppTargetError as error:
                raise CredentialUnavailableError(
                    str(error), sandbox_detail=str(error)
                ) from error
            if (
                app is None
                or app.id != external_app_id
                or _openapi_auth_identity(app) != auth_identity
                or (
                    app.openapi_tool_id is not None
                    and not app_is_available(db, app, ctx.sandbox.user_id)
                )
            ):
                detail = "The app's configuration or availability changed; retry the request."
                raise CredentialUnavailableError(detail, sandbox_detail=detail)

        # Per-app debug line so `external_app_id` survives in logs even when
        # the dispatcher's credential logs group by resolver.
        # Empty headers remain valid for apps that require no authentication.
        header_names = ",".join(sorted(headers)) or "-"
        logger.debug(
            "external_app_resolver.resolved external_app_id=%s host=%s "
            "header_count=%s header_names=%s",
            external_app_id,
            request.host,
            len(headers),
            header_names,
        )
        return headers
