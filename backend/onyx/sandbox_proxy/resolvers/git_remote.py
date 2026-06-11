"""GitHub git-over-HTTPS credential resolver (read: clone/fetch).

Claims git smart-HTTP *read* requests to github.com and injects the user's
GitHub external-app OAuth token as Basic auth (`x-access-token:<token>`, the
form GitHub requires now that account-password auth is disabled). The token is
injected by the proxy — outside the sandbox — so untrusted agent code never
sees it. Unauthenticated requests (no connected GitHub app) forward as-is, so
public clones keep working and private ones fail with GitHub's own 401/404.

This resolver is repo-agnostic: it injects the user's own credential for any
github.com repo that credential can reach, mirroring the read access the
existing api.github.com injection already grants. Push (`git-receive-pack`) is
deliberately NOT handled here — it requires ref-namespace enforcement and is
added by a separate layer.
"""

from __future__ import annotations

import base64

from mitmproxy import http

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.enums import ExternalAppType
from onyx.db.external_app import get_built_in_external_app
from onyx.external_apps.github_token import get_user_github_access_token
from onyx.external_apps.token_refresh import ensure_fresh_credentials
from onyx.sandbox_proxy.credential_injection import CredentialResolver
from onyx.sandbox_proxy.credential_injection import CredentialUnavailableError
from onyx.sandbox_proxy.credential_injection import InjectionContext
from onyx.sandbox_proxy.git_smart_http import parse_git_request
from onyx.sandbox_proxy.logging_utils import short_log_id
from onyx.utils.logger import setup_logger

logger = setup_logger()


class GitRemoteResolver(CredentialResolver):
    """`CredentialResolver` for git smart-HTTP reads (clone/fetch) to github.com."""

    def claims(
        self,
        request: http.Request,
        ctx: InjectionContext,  # noqa: ARG002
    ) -> bool:
        info = parse_git_request(request)
        return info is not None and not info.is_push

    def resolve(self, request: http.Request, ctx: InjectionContext) -> dict[str, str]:
        info = parse_git_request(request)
        if info is None or info.is_push:
            raise CredentialUnavailableError(
                "GitRemoteResolver invoked on a non-read git request"
            )

        github_app = None
        with get_session_with_tenant(tenant_id=ctx.sandbox.tenant_id) as db:
            github_app = get_built_in_external_app(db, ExternalAppType.GITHUB)

        if github_app is not None:
            # Refresh an expiring OAuth token before injecting (no-op for
            # non-expiring tokens; single-flighted via Redis internally).
            ensure_fresh_credentials(
                ctx.sandbox.tenant_id, github_app.id, ctx.sandbox.user_id
            )

        with get_session_with_tenant(tenant_id=ctx.sandbox.tenant_id) as db:
            token = get_user_github_access_token(db, ctx.sandbox.user_id)

        if token is None:
            # No connected GitHub app: forward unauthenticated. Public clones
            # work; private repos surface GitHub's own auth error.
            logger.debug(
                "git_remote_resolver.pass_through sandbox=%s repo=%s/%s",
                short_log_id(ctx.sandbox.sandbox_id),
                info.owner,
                info.name,
            )
            return {}

        logger.info(
            "git_remote_resolver.injected sandbox=%s repo=%s/%s",
            short_log_id(ctx.sandbox.sandbox_id),
            info.owner,
            info.name,
        )
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        return {"Authorization": f"Basic {basic}"}
