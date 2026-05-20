"""Pass-through addon: identifies every flow, logs it, forwards it."""

from mitmproxy import http

from onyx.sandbox_proxy.identity import IdentityResolver
from onyx.utils.logger import setup_logger

logger = setup_logger()


class PassthroughAddon:
    """Resolves identity per flow and attaches it to `flow.metadata`
    for downstream addons to consume."""

    METADATA_KEY = "onyx_session_context"

    def __init__(self, identity: IdentityResolver) -> None:
        self._identity = identity

    def request(self, flow: http.HTTPFlow) -> None:
        src_ip = self._extract_src_ip(flow)
        if src_ip is None:
            logger.warning(
                "egress without resolvable src_ip host=%s path=%s",
                flow.request.host,
                flow.request.path,
            )
            return

        try:
            ctx = self._identity.resolve(src_ip)
        except Exception:
            # Errors out of an addon hook abort the flow. Forward
            # unidentified so a DB blip can't take down sandbox egress.
            logger.exception(
                "identity resolution raised for src_ip=%s host=%s; "
                "forwarding without context",
                src_ip,
                flow.request.host,
            )
            return

        if ctx is None:
            logger.warning(
                "unidentified_egress src_ip=%s host=%s path=%s",
                src_ip,
                flow.request.host,
                flow.request.path,
            )
            return

        flow.metadata[self.METADATA_KEY] = ctx
        logger.info(
            "egress session_id=%s tenant_id=%s host=%s path=%s",
            ctx.session_id,
            ctx.tenant_id,
            flow.request.host,
            flow.request.path,
        )

    def _extract_src_ip(self, flow: http.HTTPFlow) -> str | None:
        peer = flow.client_conn.peername
        if peer is None or len(peer) < 1:
            return None
        addr = peer[0]
        if not isinstance(addr, str):
            return None
        return addr
