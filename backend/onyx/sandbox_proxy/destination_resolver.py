"""Resolve egress destinations under sandbox access and tenant security policy."""

from collections.abc import Callable

from onyx.sandbox_proxy.destination_policy import resolve_destination
from onyx.sandbox_proxy.models import DestinationPolicyConfig
from onyx.sandbox_proxy.resolvers.mcp_server import MCPServerResolver
from onyx.sandbox_proxy.sandbox_identity.models import ResolvedSandbox
from onyx.sandbox_proxy.sandbox_identity.resolution import PeerAddress, source_ip
from onyx.server.security.models import OutboundSSRFParams, outbound_ssrf_params
from onyx.server.security.store import get_security_settings
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

logger = setup_logger()


class DestinationResolver:
    """Apply the same destination rules at every proxy lifecycle hook."""

    def __init__(
        self,
        config: DestinationPolicyConfig,
        resolve_sandbox: Callable[[str], ResolvedSandbox | None],
        mcp_resolver: MCPServerResolver | None = None,
    ) -> None:
        self._config = config
        self._resolve_sandbox = resolve_sandbox
        self._mcp_resolver = mcp_resolver

    def resolve(
        self, peer: PeerAddress | None, scheme: str, host: str, port: int
    ) -> tuple[str, ...] | None:
        """Resolve once; authorize internal answers before returning addresses to pin."""
        return resolve_destination(
            self._config,
            host,
            port,
            authorize_internal=lambda: self._authorize_mcp(peer, scheme, host, port),
        )

    def _authorize_mcp(
        self, peer: PeerAddress | None, scheme: str, host: str, port: int
    ) -> OutboundSSRFParams | None:
        if self._mcp_resolver is None:
            return None
        try:
            src_ip = source_ip(peer)
            if src_ip is None:
                return None
            sandbox = self._resolve_sandbox(src_ip)
            if sandbox is None or not self._mcp_resolver.allows_destination(
                sandbox, scheme, host, port
            ):
                return None
            token = CURRENT_TENANT_ID_CONTEXTVAR.set(sandbox.tenant_id)
            try:
                return outbound_ssrf_params(
                    get_security_settings(allow_fallback=False).ssrf_protection_level
                )
            finally:
                CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
        except Exception:
            logger.exception("mcp_destination_error host=%s port=%s", host, port)
            return None
