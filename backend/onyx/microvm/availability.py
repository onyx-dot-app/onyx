"""Whether chats get sandbox tools, and the sandbox status for admins.

Tools are offered while a harness backend can serve a new sandbox:
- The container backend (`CONTAINER_HARNESS_ENABLED`) always can.
- Firecracker with `SANDBOX_RUNTIME=firecracker` follows the configuration
  alone (`HARNESS_SANDBOX_ENABLED`); placement fails when no node serves.
  With `auto` it needs a live registered node whose last report pass found
  a compatible template for `SANDBOX_FC_TEMPLATE`. The check reads only the
  shared cache (no agent call), and each process reuses its answer for
  `SANDBOX_FC_AVAILABILITY_CACHE_SECONDS`.
The backend of each sandbox is `harness_factory.harness_backend_for`.
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
    HarnessBackend,
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
from onyx.server.features.build.configs import (
    CONTAINER_HARNESS_ENABLED,
    SANDBOX_FIRECRACKER_ENABLED,
    SANDBOX_RUNTIME,
    SandboxRuntime,
)
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


def _accepts_new(node: SandboxNodeStatus) -> bool:
    # A draining node keeps its VMs but refuses new ones.
    return _serving(node) and not node.draining


# Why Firecracker serves no sandbox from the configuration alone; None when
# nodes decide.
STATIC_OFF_REASON: SandboxToolsOffReason | None = None
if not SANDBOX_FIRECRACKER_ENABLED:
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
    if SANDBOX_FIRECRACKER_ENABLED:
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
    backend: HarnessBackend | None = None
    if reason is None and (
        not CONTAINER_HARNESS_ENABLED
        or SANDBOX_RUNTIME is not SandboxRuntime.AUTO
        or any(_accepts_new(n) for n in nodes)
    ):
        backend = HarnessBackend.FIRECRACKER
    elif CONTAINER_HARNESS_ENABLED:
        backend = HarnessBackend.CONTAINER
    return SandboxStatus(
        runtime=SANDBOX_RUNTIME,
        template=SANDBOX_FC_TEMPLATE,
        tools_offered=backend is not None,
        tools_off_reason=None if backend is not None else reason,
        container_backend=CONTAINER_HARNESS_ENABLED,
        new_sandbox_backend=backend,
        firecracker_off_reason=reason,
        nodes=nodes,
    )


def _live_node_has_template(
    shared_cache: CacheBackend, now: int, *, exclude_draining: bool
) -> bool:
    for node in list_registered_nodes(shared_cache):
        if node_reports_stopped(shared_cache, node.node_id, now):
            continue
        info = get_node_info(shared_cache, node.node_id)
        if not _has_template(info):
            continue
        if exclude_draining and (
            (info is not None and info.draining)
            or is_node_draining(shared_cache, node.node_id)
        ):
            continue
        return True
    return False


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
_new_sandbox_availability = _AvailabilityCache()


def _check_live_node(*, exclude_draining: bool) -> bool:
    try:
        return _live_node_has_template(
            get_shared_cache_backend(),
            int(time.time()),
            exclude_draining=exclude_draining,
        )
    except Exception:
        logger.exception("sandbox_fc_availability_check_failed")
        return False


def firecracker_available() -> bool:
    """Whether Firecracker can serve a new sandbox now."""
    if STATIC_OFF_REASON is not None:
        return False
    if SANDBOX_RUNTIME is not SandboxRuntime.AUTO:
        return True
    return _availability.get(lambda: _check_live_node(exclude_draining=False))


def firecracker_accepts_new_sandboxes() -> bool:
    """Whether a new sandbox can start on Firecracker now: as
    `firecracker_available`, without draining nodes. The backend choice uses
    it; the tools keep `firecracker_available`, so sandboxes on a draining
    node keep their tools."""
    if STATIC_OFF_REASON is not None:
        return False
    if SANDBOX_RUNTIME is not SandboxRuntime.AUTO:
        return True
    return _new_sandbox_availability.get(
        lambda: _check_live_node(exclude_draining=True)
    )


def sandbox_tools_configured() -> bool:
    """Whether the configuration alone offers chat sandbox tools. A resumed
    parked run uses this, so its saved sandbox calls keep their tools; with
    no serving node they fail at placement."""
    return CONTAINER_HARNESS_ENABLED or STATIC_OFF_REASON is None


def sandbox_tools_available() -> bool:
    """Whether this deployment offers chat sandbox tools now, on either
    backend."""
    return CONTAINER_HARNESS_ENABLED or firecracker_available()
