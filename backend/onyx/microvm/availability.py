"""Whether chats get sandbox tools, and the sandbox status for admins.

With `SANDBOX_RUNTIME=firecracker` the tools follow the configuration alone
(`HARNESS_SANDBOX_ENABLED`); placement fails when no node serves. With
`auto` they need a live registered node whose last report pass found a
compatible template for `SANDBOX_FC_TEMPLATE`. The check reads only the
shared cache (no agent call), and each process reuses its answer for
`SANDBOX_FC_AVAILABILITY_CACHE_SECONDS`.
"""

import threading
import time
from collections.abc import Callable

from onyx.cache.factory import get_shared_cache_backend
from onyx.cache.interface import CacheBackend
from onyx.microvm.configs import (
    HARNESS_SANDBOX_ENABLED,
    SANDBOX_FC_TEMPLATE,
)
from onyx.microvm.models import (
    NodeInfo,
    SandboxNodeStatus,
    SandboxStatus,
    SandboxToolsOffReason,
)
from onyx.microvm.registry import (
    get_node_info,
    get_node_last_report,
    is_node_draining,
    list_registered_nodes,
    node_reports_stopped,
)
from onyx.server.features.build.configs import SANDBOX_RUNTIME, SandboxRuntime
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Below one node report interval (20 s), so tools follow a node within a report.
SANDBOX_FC_AVAILABILITY_CACHE_SECONDS = 15.0


def _has_template(info: NodeInfo | None) -> bool:
    if info is None:
        return False
    template = info.template(SANDBOX_FC_TEMPLATE)
    return template is not None and template.compatible


def _node_status(
    shared_cache: CacheBackend, node_id: str, now: int
) -> SandboxNodeStatus:
    info = get_node_info(shared_cache, node_id)
    last_report = get_node_last_report(shared_cache, node_id)
    return SandboxNodeStatus(
        node_id=node_id,
        live=not node_reports_stopped(shared_cache, node_id, now),
        draining=is_node_draining(shared_cache, node_id)
        or (info is not None and info.draining),
        has_template=_has_template(info),
        last_report_age_seconds=None if last_report is None else now - last_report,
        agent_version=None if info is None else info.agent_version,
        templates=[] if info is None else [t.version for t in info.templates],
        vm_count=None if info is None else info.vm_count,
        max_vms=None if info is None else info.max_vms,
    )


def _serving(node: SandboxNodeStatus) -> bool:
    # A node that never reported has no info, so it does not serve here.
    return node.live and node.has_template


# Why tools are off from the configuration alone; None when nodes decide.
STATIC_OFF_REASON: SandboxToolsOffReason | None = None
if not SANDBOX_RUNTIME.uses_firecracker:
    STATIC_OFF_REASON = SandboxToolsOffReason.RUNTIME_WITHOUT_FIRECRACKER
elif not HARNESS_SANDBOX_ENABLED:
    STATIC_OFF_REASON = SandboxToolsOffReason.TEMPLATE_NOT_CONFIGURED


def get_sandbox_status(
    shared_cache: CacheBackend | None = None, now: int | None = None
) -> SandboxStatus:
    """The current status, read fresh (no process cache)."""
    now = int(time.time()) if now is None else now
    reason = STATIC_OFF_REASON
    nodes: list[SandboxNodeStatus] = []
    if SANDBOX_RUNTIME.uses_firecracker:
        cache = shared_cache or get_shared_cache_backend()
        try:
            nodes = [
                _node_status(cache, node.node_id, now)
                for node in list_registered_nodes(cache)
            ]
        except Exception:
            logger.exception("sandbox_fc_status_read_failed")
            if reason is None and SANDBOX_RUNTIME is SandboxRuntime.AUTO:
                reason = SandboxToolsOffReason.NODE_STATE_UNREADABLE
    if reason is None and SANDBOX_RUNTIME is SandboxRuntime.AUTO:
        if not nodes:
            reason = SandboxToolsOffReason.NO_REGISTERED_NODE
        elif not any(_serving(n) for n in nodes):
            reason = SandboxToolsOffReason.NO_LIVE_NODE_WITH_TEMPLATE
    return SandboxStatus(
        runtime=SANDBOX_RUNTIME,
        template=SANDBOX_FC_TEMPLATE,
        tools_offered=reason is None,
        tools_off_reason=reason,
        nodes=nodes,
    )


def _live_node_has_template(shared_cache: CacheBackend, now: int) -> bool:
    return any(
        not node_reports_stopped(shared_cache, node.node_id, now)
        and _has_template(get_node_info(shared_cache, node.node_id))
        for node in list_registered_nodes(shared_cache)
    )


class _AvailabilityCache:
    """One answer per process for a while. One check runs at a time; callers
    that wait for it get its answer."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._value: bool | None = None
        self._checked_at = 0.0

    def get(self, check: Callable[[], bool]) -> bool:
        with self._lock:
            now = time.monotonic()
            if (
                self._value is not None
                and now - self._checked_at < SANDBOX_FC_AVAILABILITY_CACHE_SECONDS
            ):
                return self._value
            self._value = check()
            self._checked_at = now
            return self._value

    def clear(self) -> None:
        with self._lock:
            self._value = None


_availability = _AvailabilityCache()


def _check_live_node() -> bool:
    try:
        return _live_node_has_template(get_shared_cache_backend(), int(time.time()))
    except Exception:
        logger.exception("sandbox_fc_availability_check_failed")
        return False


def sandbox_tools_configured() -> bool:
    """Whether the configuration alone offers chat sandbox tools. A resumed
    parked run uses this, so its saved sandbox calls keep their tools; with
    no serving node they fail at placement."""
    return STATIC_OFF_REASON is None


def sandbox_tools_available() -> bool:
    """Whether this deployment offers chat sandbox tools now."""
    if STATIC_OFF_REASON is not None:
        return False
    if SANDBOX_RUNTIME is not SandboxRuntime.AUTO:
        return True
    return _availability.get(_check_live_node)
