"""Onyx-API PAT credential resolver.

Claims requests bound for the Onyx API host (the host of
``SANDBOX_API_SERVER_URL``) and sets both auth headers to the sandbox's real
per-sandbox PAT, read encrypted off ``Sandbox.encrypted_pat``. The tenant is
embedded in the PAT itself, so no separate tenant header is injected.
"""

from __future__ import annotations

from urllib.parse import urlparse

from mitmproxy import http

from onyx.auth.constants import API_KEY_HEADER_ALTERNATIVE_NAME
from onyx.auth.constants import API_KEY_HEADER_NAME
from onyx.auth.constants import BEARER_PREFIX
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.sandbox_proxy.credential_injection import CredentialResolver
from onyx.sandbox_proxy.credential_injection import CredentialUnavailableError
from onyx.sandbox_proxy.credential_injection import InjectionContext
from onyx.sandbox_proxy.logging_utils import full_log_id
from onyx.sandbox_proxy.logging_utils import short_log_id
from onyx.server.features.build.configs import SANDBOX_API_SERVER_URL
from onyx.server.features.build.db.sandbox import get_sandbox_by_id
from onyx.utils.logger import setup_logger

logger = setup_logger()


class OnyxPatResolver(CredentialResolver):
    """Injects the sandbox's Onyx API PAT on requests to the configured API host."""

    def __init__(self) -> None:
        parsed = urlparse(SANDBOX_API_SERVER_URL) if SANDBOX_API_SERVER_URL else None
        host = parsed.hostname if parsed else None
        self._api_host = host.lower() if host else None
        if parsed is not None and host:
            self._api_port = parsed.port or (443 if parsed.scheme == "https" else 80)
        else:
            self._api_port = None

    def claims(
        self,
        request: http.Request,
        ctx: InjectionContext,  # noqa: ARG002
    ) -> bool:
        return (
            self._api_host is not None
            and request.host.lower() == self._api_host
            and request.port == self._api_port
        )

    def resolve(self, request: http.Request, ctx: InjectionContext) -> dict[str, str]:
        sandbox_id = ctx.sandbox.sandbox_id
        with get_session_with_tenant(tenant_id=ctx.sandbox.tenant_id) as db:
            sandbox = get_sandbox_by_id(db, sandbox_id)
            if sandbox is None:
                raise CredentialUnavailableError(
                    f"sandbox {full_log_id(sandbox_id)} not found"
                )
            if sandbox.encrypted_pat is None:
                raise CredentialUnavailableError(
                    f"sandbox {full_log_id(sandbox_id)} has no PAT"
                )
            try:
                raw_token = sandbox.encrypted_pat.get_value(apply_mask=False)
            except Exception as e:
                raise CredentialUnavailableError(
                    f"failed to decrypt PAT for sandbox {full_log_id(sandbox_id)}"
                ) from e

        logger.debug(
            "onyx_pat_resolver.resolved sandbox=%s host=%s",
            short_log_id(sandbox_id),
            request.host,
        )
        bearer = f"{BEARER_PREFIX}{raw_token}"
        return {API_KEY_HEADER_NAME: bearer, API_KEY_HEADER_ALTERNATIVE_NAME: bearer}
