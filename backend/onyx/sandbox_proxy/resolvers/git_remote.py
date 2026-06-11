"""GitHub git-over-HTTPS credential resolver (read: clone/fetch).

Claims git smart-HTTP *read* requests to github.com and injects the user's
GitHub external-app OAuth token as Basic auth (`x-access-token:<token>`, the
form GitHub requires now that account-password auth is disabled). The token is
injected by the proxy — outside the sandbox — so untrusted agent code never
sees it. Unauthenticated requests (no connected GitHub app) forward as-is, so
public clones keep working and private ones fail with GitHub's own 401/404.

This resolver is repo-agnostic: it injects the user's own credential for any
github.com repo that credential can reach, mirroring the read access the
existing api.github.com injection already grants. Pushes (`git-receive-pack`)
are additionally namespace-enforced — every ref update must target
`refs/heads/craft/*`, checked before any credential is attached — so untrusted
sandbox code can never push outside the craft/ namespace.
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
from onyx.sandbox_proxy.git_smart_http import disallowed_push_refs
from onyx.sandbox_proxy.git_smart_http import GitProtocolError
from onyx.sandbox_proxy.git_smart_http import parse_git_request
from onyx.sandbox_proxy.logging_utils import short_log_id
from onyx.utils.logger import setup_logger

logger = setup_logger()


class GitRemoteResolver(CredentialResolver):
    """`CredentialResolver` for git smart-HTTP (clone/fetch/push) to github.com."""

    def claims(
        self,
        request: http.Request,
        ctx: InjectionContext,  # noqa: ARG002
    ) -> bool:
        return parse_git_request(request) is not None

    def resolve(self, request: http.Request, ctx: InjectionContext) -> dict[str, str]:
        info = parse_git_request(request)
        if info is None:
            raise CredentialUnavailableError(
                "GitRemoteResolver invoked on a non-git request"
            )

        # Enforce the push namespace BEFORE any credential decision so a
        # malformed or out-of-namespace push is blocked unconditionally.
        if info.is_push and request.method == "POST":
            # Refuse a compressed push body: `git push` sends the packfile
            # uncompressed, so a Content-Encoding here would force a
            # decompression of attacker-controlled size when we read
            # `request.content` (a gzip-bomb DoS against the shared proxy).
            content_encoding = request.headers.get("content-encoding", "").strip()
            if content_encoding and content_encoding.lower() != "identity":
                raise CredentialUnavailableError(
                    f"compressed git push rejected (content-encoding={content_encoding})"
                )
            try:
                rejected = disallowed_push_refs(request.content or b"")
            except GitProtocolError as e:
                raise CredentialUnavailableError(
                    f"unparseable git push rejected: {e}"
                ) from e
            if rejected:
                raise CredentialUnavailableError(
                    f"push to non-craft refs rejected: {', '.join(rejected[:5])}"
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
            "git_remote_resolver.injected sandbox=%s repo=%s/%s push=%s",
            short_log_id(ctx.sandbox.sandbox_id),
            info.owner,
            info.name,
            info.is_push,
        )
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        return {"Authorization": f"Basic {basic}"}
